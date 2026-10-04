from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

import yaml


REPOSITORY = Path(__file__).resolve().parents[1]


class WorkflowIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="skill-ci-integration-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "runner.jsonl"
        self.environment = os.environ.copy()
        self.environment.update(
            PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            SKILL_CI=str(REPOSITORY),
            SKILLS_DIR="skills",
            EVALS_DIR="",
            REQUIRE_MANIFESTS="false",
            REQUIRE_POPULATED_MANIFESTS="false",
            INSTALLED_SKILLS_DIR="",
            LINK_EXCEPTIONS_FILE="",
            CONTENT_LINK_EXCEPTIONS_FILE="",
            CONVENTIONS_FILE="",
            CONTENT_CONVENTIONS_FILE="",
            IGNORE_FILE="",
            RUNNER_LOG=str(self.log),
            RUNNER_EXIT="0",
            RUNNER_FAIL_COMMAND="",
        )
        (self.root / ".skill-ci").symlink_to(REPOSITORY, target_is_directory=True)
        self.executable("python3", "import os, sys\nos.execv(sys.executable, [sys.executable, *sys.argv[1:]])\n")
        self.executable(
            "uv",
            "import json, os, sys\n"
            "arguments = sys.argv[1:]\n"
            "if arguments[:2] == ['run', '--no-project'] and 'python' in arguments:\n"
            "    os.execv(sys.executable, [sys.executable, *arguments[arguments.index('python') + 1:]])\n"
            "if arguments[:2] != ['tool', 'run']:\n"
            "    raise SystemExit(9)\n"
            "command = next(value for value in arguments if value in {'skill-benchmark', 'skill-trigger-matrix'})\n"
            "with open(os.environ['RUNNER_LOG'], 'a') as log:\n"
            "    log.write(json.dumps(arguments[arguments.index(command) + 1:]) + '\\n')\n"
            "stage = arguments[arguments.index(command) + 1]\n"
            "raise SystemExit(int(os.environ['RUNNER_EXIT']) if not os.environ.get('RUNNER_FAIL_COMMAND') or stage == os.environ['RUNNER_FAIL_COMMAND'] else 0)\n",
        )
        self.executable(
            "jq",
            "import json, sys\n"
            "with open(sys.argv[2]) as manifest:\n"
            "    print(len(json.load(manifest)['cases']))\n",
        )
        workflow = yaml.load(
            (REPOSITORY / ".github/workflows/skill-checks.yml").read_text(),
            Loader=yaml.BaseLoader,
        )
        self.workflow = workflow
        self.steps = {
            step.get("name"): step
            for job in workflow["jobs"].values()
            for step in job["steps"]
            if "run" in step
        }

    def executable(self, name: str, body: str) -> None:
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\n{body}")
        path.chmod(0o755)

    def run_body(self, body: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", body],
            cwd=self.root,
            env=self.environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def manifests(self) -> subprocess.CompletedProcess[str]:
        return self.run_body(self.steps["Validate manifests and audit readiness"]["run"])

    def runner_calls(self) -> list[list[str]]:
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_empty_inventory_is_optional_and_can_be_required(self) -> None:
        (self.root / "skills").mkdir()
        optional = self.manifests()
        self.assertEqual(optional.returncode, 0, optional.stderr)
        self.assertIn("manifests checked: 0", optional.stdout)
        self.environment["REQUIRE_MANIFESTS"] = "true"
        required = self.manifests()
        self.assertEqual(required.returncode, 1, required.stderr)
        self.assertIn("no manifest files were checked", required.stdout)
        self.assertFalse(self.log.exists())

    def test_required_inventory_accepts_an_empty_scaffold_in_either_layout(self) -> None:
        for external in (False, True):
            with self.subTest(external=external):
                relative = "evals/a/shared-benchmark.json" if external else "skills/a/evals/shared-benchmark.json"
                manifest = self.root / relative
                manifest.parent.mkdir(parents=True, exist_ok=True)
                manifest.write_text('{"cases": []}')
                self.environment["EVALS_DIR"] = "evals" if external else ""
                self.environment["REQUIRE_MANIFESTS"] = "true"
                result = self.manifests()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("manifests checked: 1", result.stdout)
                self.assertIn("readiness audit skipped", result.stdout)
                self.assertEqual(self.runner_calls(), [["validate", "--strict-leakage", relative]])
                self.log.unlink()

    def test_populated_manifest_runs_validation_and_readiness_audit(self) -> None:
        relative = "evals/a skill/shared-benchmark.json"
        manifest = self.root / relative
        manifest.parent.mkdir(parents=True)
        manifest.write_text('{"cases": [{"id": "a"}]}')
        self.environment.update(EVALS_DIR="evals", REQUIRE_MANIFESTS="true")
        result = self.manifests()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("manifests checked: 1", result.stdout)
        self.assertEqual(
            self.runner_calls(),
            [
                ["validate", "--strict-leakage", relative],
                ["audit-manifest", "--fail-on-blockers", "--strict-judge", relative],
            ],
        )

    def test_runner_failure_stops_the_workflow(self) -> None:
        manifest = self.root / "evals/a/shared-benchmark.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text('{"cases": [{"id": "a"}]}')
        self.environment.update(EVALS_DIR="evals", RUNNER_EXIT="7")
        result = self.manifests()
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(self.runner_calls(), [["validate", "--strict-leakage", "evals/a/shared-benchmark.json"]])

    def test_audit_failure_stops_the_workflow(self) -> None:
        manifest = self.root / "evals/a/shared-benchmark.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text('{"cases": [{"id": "a"}]}')
        self.environment.update(EVALS_DIR="evals", RUNNER_EXIT="7", RUNNER_FAIL_COMMAND="audit-manifest")
        result = self.manifests()
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual([call[0] for call in self.runner_calls()], ["validate", "audit-manifest"])

    def test_populated_coverage_rejects_missing_empty_and_wrong_bindings(self) -> None:
        self.package("a")
        self.package("b")
        self.environment.update(EVALS_DIR="evals", REQUIRE_POPULATED_MANIFESTS="true")
        manifest = self.root / "evals/a/shared-benchmark.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"cases": [{"id": "a"}], "skill_paths": ["skills/a/SKILL.md"]}))
        missing = self.manifests()
        self.assertEqual(missing.returncode, 1, missing.stderr)
        self.assertIn("evals/b/shared-benchmark.json", missing.stderr)
        self.assertFalse(self.log.exists())
        other = self.root / "evals/b/shared-benchmark.json"
        other.parent.mkdir()
        for cases, paths, message in (
            ([], ["skills/b/SKILL.md"], "nonempty cases"),
            ([{"id": "b"}], ["skills/a/SKILL.md"], "does not bind"),
        ):
            with self.subTest(message=message):
                other.write_text(json.dumps({"cases": cases, "skill_paths": paths}))
                result = self.manifests()
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(message, result.stderr)
                self.assertFalse(self.log.exists())
        other.write_text(json.dumps({"cases": [{"id": "b"}], "skill_paths": ["skills/b"]}))
        complete = self.manifests()
        self.assertEqual(complete.returncode, 0, complete.stderr)
        self.assertIn("skill manifests checked: 2; failed: 0", complete.stdout)
        self.assertEqual([call[0] for call in self.runner_calls()], ["validate", "audit-manifest"] * 2)

    def test_populated_coverage_uses_directory_names_in_both_layouts(self) -> None:
        for external in (False, True):
            with self.subTest(external=external):
                self.environment["SKILLS_DIR"] = "skills with spaces"
                source = self.package("directory name")
                self.environment.update(EVALS_DIR="evals with spaces" if external else "", REQUIRE_POPULATED_MANIFESTS="true")
                manifest = (self.root / "evals with spaces" / source.name if external else source / "evals") / "shared-benchmark.json"
                manifest.parent.mkdir(parents=True)
                path = str(source.resolve()) if external else "SKILL.md"
                manifest.write_text(json.dumps({"skill_name": "example", "cases": [{"id": "a"}], "skill_paths": ["ancillary.txt", path]}))
                result = self.manifests()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("skill manifests checked: 1; failed: 0", result.stdout)
                self.assertEqual(len(self.runner_calls()), 2)
                self.log.unlink()
                shutil.rmtree(source)

    def test_missing_external_directory_fails_before_runner(self) -> None:
        self.environment["EVALS_DIR"] = "missing"
        result = self.manifests()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("not a directory", result.stdout)
        self.assertFalse(self.log.exists())

    def test_runner_tasks_use_the_dispatcher_for_each_stage(self) -> None:
        manifest = self.root / "evals/example/shared-benchmark.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text('{"cases": [{"id": "a"}]}')
        self.environment.update(EVALS_DIR="evals", OUT="run output", AGENTS="claude codex")
        for name in ("skill-validate", "skill-audit", "skill-trigger", "skill-run"):
            with self.subTest(name=name):
                tasks = tomllib.loads((REPOSITORY / "skill-tasks.toml").read_text())
                self.assertEqual(tasks[name]["shell"], "bash -c")
                self.assertIn('run_runner.py" "$@"', tasks[name]["run"])
        self.assertEqual(self.runner_task("skill-validate").returncode, 0)
        self.assertEqual(self.runner_calls(), [["validate", "--strict-leakage", "evals/example/shared-benchmark.json"]])
        self.log.unlink()
        self.assertEqual(self.runner_task("skill-audit").returncode, 0)
        self.assertEqual(self.runner_calls(), [["audit-manifest", "--fail-on-blockers", "--strict-judge", "evals/example/shared-benchmark.json"]])
        self.log.unlink()
        self.assertEqual(self.runner_task("skill-trigger").returncode, 0)
        self.assertEqual(self.runner_calls()[0][:3], ["evals/example/shared-benchmark.json", "--agent", "claude"])
        self.log.unlink()
        self.assertEqual(self.runner_task("skill-run").returncode, 0)
        calls = self.runner_calls()
        self.assertEqual(calls[0], ["audit-manifest", "evals/example/shared-benchmark.json", "--fail-on-blockers", "--strict-judge"])
        self.assertEqual(calls[1][:2], ["prepare", "evals/example/shared-benchmark.json"])
        self.assertEqual([call[0] for call in calls[2:]], ["run-agent", "grade", "judge", "benchmark", "report"] * 2)

    def test_runner_task_failure_stops_later_skill_run_stages(self) -> None:
        manifest = self.root / "evals/example/shared-benchmark.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text('{"cases": [{"id": "a"}]}')
        self.environment.update(EVALS_DIR="evals", OUT="run output", RUNNER_EXIT="7")
        result = self.runner_task("skill-run")
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(self.runner_calls(), [["audit-manifest", "evals/example/shared-benchmark.json", "--fail-on-blockers", "--strict-judge"]])

    def test_paid_task_defaults_are_outside_packages_in_both_layouts(self) -> None:
        package = self.package("a skill")
        self.addCleanup(shutil.rmtree, self.root.with_name(f"{self.root.name}.eval-runs"), True)
        for external in (False, True):
            self.environment["EVALS_DIR"] = "evals" if external else ""
            for name in ("skill-trigger", "skill-run"):
                with self.subTest(external=external, name=name):
                    result = self.runner_task(name, "skills/a skill")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    calls = self.runner_calls()
                    call = calls[0] if name == "skill-trigger" else calls[1]
                    output = Path(call[call.index("--out") + 1]).parent
                    self.assertEqual(output.parent, self.root.with_name(f"{self.root.name}.eval-runs") / "a skill")
                    self.assertTrue(output.is_dir())
                    self.assertNotIn(package, output.parents)
                    self.log.unlink()

    def test_paid_tasks_preserve_relative_and_absolute_output_overrides(self) -> None:
        for override in ("output with spaces", str(self.root / "absolute output")):
            self.environment["OUT"] = override
            for name in ("skill-trigger", "skill-run"):
                with self.subTest(override=override, name=name):
                    result = self.runner_task(name, "missing package")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    calls = self.runner_calls()
                    call = calls[0] if name == "skill-trigger" else calls[1]
                    self.assertEqual(call[call.index("--out") + 1], f"{override}/trigger-matrix.json" if name == "skill-trigger" else f"{override}/tasks.jsonl")
                    self.log.unlink()

    def test_output_overlap_fails_before_any_runner_call(self) -> None:
        source = self.package()
        output_root = self.root.with_name(f"{self.root.name}.eval-runs")
        output_root.symlink_to(source, target_is_directory=True)
        self.addCleanup(output_root.unlink)
        for name in ("skill-trigger", "skill-run"):
            result = self.runner_task(name)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("set OUT", result.stderr)
            self.assertFalse(self.log.exists())

    def test_paid_tasks_support_root_and_absolute_package_selections(self) -> None:
        package = self.package()
        (self.root / "SKILL.md").write_text("root skill")
        self.addCleanup(shutil.rmtree, self.root.with_name(f"{self.root.name}.eval-runs"), True)
        for selection, expected_name in ((".", self.root.name), (str(package), "example")):
            for name in ("skill-trigger", "skill-run"):
                with self.subTest(selection=selection, name=name):
                    result = self.runner_task(name, selection)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    calls = self.runner_calls()
                    call = calls[0] if name == "skill-trigger" else calls[1]
                    self.assertEqual(call[0] if name == "skill-trigger" else call[1], f"{selection}/evals/shared-benchmark.json")
                    output = Path(call[call.index("--out") + 1]).parent
                    self.assertEqual(output.parent, self.root.with_name(f"{self.root.name}.eval-runs") / expected_name)
                    self.assertTrue(output.is_dir())
                    self.log.unlink()

    def test_local_coverage_task_checks_complete_inventory(self) -> None:
        source = self.package()
        manifest = source / "evals/shared-benchmark.json"
        manifest.parent.mkdir()
        manifest.write_text(json.dumps({"cases": [{"id": "a"}], "skill_paths": ["SKILL.md"]}))
        result = self.runner_task("skill-coverage")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("skill manifests checked: 1; failed: 0", result.stdout)
        manifest.write_text(json.dumps({"cases": [], "skill_paths": ["SKILL.md"]}))
        empty = self.runner_task("skill-coverage")
        self.assertEqual(empty.returncode, 1, empty.stderr)
        self.assertIn("nonempty cases", empty.stderr)
        self.assertFalse(self.log.exists())

    @unittest.skipUnless(shutil.which("mise"), "requires mise")
    def test_included_paid_task_from_nested_caller_uses_config_directory(self) -> None:
        self.package()
        nested = self.root / "nested" / "caller"
        nested.mkdir(parents=True)
        self.environment["MISE_TRUSTED_CONFIG_PATHS"] = os.pathsep.join((str(self.root), str(REPOSITORY)))
        (self.root / "mise.toml").write_text(
            f"[task_config]\nincludes = [{json.dumps(str(REPOSITORY / 'skill-tasks.toml'))}]\n"
        )
        self.addCleanup(shutil.rmtree, self.root.with_name(f"{self.root.name}.eval-runs"), True)
        result = subprocess.run(
            ["mise", "run", "skill-trigger", "skills/example"], cwd=nested,
            env=self.environment, capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        call = self.runner_calls()[0]
        output = Path(call[call.index("--out") + 1]).parent
        self.assertEqual(output.parent, self.root.with_name(f"{self.root.name}.eval-runs") / "example")
        self.assertTrue(output.is_dir())

    def test_runner_tasks_require_skill_ci(self) -> None:
        self.environment.pop("SKILL_CI")
        for name in ("skill-validate", "skill-audit", "skill-trigger", "skill-run"):
            with self.subTest(name=name):
                result = self.runner_task(name)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("SKILL_CI", result.stderr)

    def test_workflow_uses_its_own_identity_and_ignores_the_legacy_input(self) -> None:
        inputs = self.workflow["on"]["workflow_call"]["inputs"]
        self.assertEqual(inputs["skill-ci-ref"]["default"], "")
        self.assertIn("Deprecated", inputs["skill-ci-ref"]["description"])
        checkouts = [
            step["with"]
            for job in self.workflow["jobs"].values()
            for step in job["steps"]
            if step.get("with", {}).get("path") == ".skill-ci"
        ]
        self.assertEqual(len(checkouts), 2)
        for checkout in checkouts:
            self.assertEqual(checkout["repository"], "${{ job.workflow_repository }}")
            self.assertEqual(checkout["ref"], "${{ job.workflow_sha }}")
            self.assertEqual(checkout["persist-credentials"], "false")
        source = (REPOSITORY / ".github/workflows/skill-checks.yml").read_text()
        self.assertNotIn("inputs.skill-ci-ref", source)
        guards = [self.steps["Check lint workflow identity"], self.steps["Check manifest workflow identity"]]
        for guard in guards:
            with self.subTest(guard=guard["name"]):
                self.environment.update(WORKFLOW_REPOSITORY="", WORKFLOW_SHA="")
                missing = self.run_body(guard["run"])
                self.assertEqual(missing.returncode, 1)
                self.environment.update(WORKFLOW_REPOSITORY="mdsmithaustin/skill-ci", WORKFLOW_SHA="main")
                malformed = self.run_body(guard["run"])
                self.assertEqual(malformed.returncode, 1)
                self.environment["WORKFLOW_SHA"] = "0123456789abcdef0123456789abcdef01234567"
                valid = self.run_body(guard["run"])
                self.assertEqual(valid.returncode, 0, valid.stderr)

    def test_repository_workflow_exercises_the_reusable_contract(self) -> None:
        workflow = yaml.load(
            (REPOSITORY / ".github/workflows/test.yml").read_text(),
            Loader=yaml.BaseLoader,
        )
        contract = workflow["jobs"]["reusable-workflow-contract"]
        self.assertEqual(contract["uses"], "./.github/workflows/skill-checks.yml")
        self.assertEqual(contract["with"]["skills-dir"], ".github/fixtures/skills")
        self.assertEqual(contract["with"]["evals-dir"], ".github/fixtures/evals")
        self.assertEqual(contract["with"]["require-manifests"], "true")
        self.assertEqual(contract["with"]["skill-ci-ref"], "ffffffffffffffffffffffffffffffffffffffff")
        self.assertTrue((REPOSITORY / ".github/fixtures/skills/example/SKILL.md").is_file())
        self.assertTrue((REPOSITORY / ".github/fixtures/evals/example/shared-benchmark.json").is_file())
        populated = workflow["jobs"]["populated-workflow-contract"]
        self.assertEqual(populated["uses"], "./.github/workflows/skill-checks.yml")
        self.assertEqual(populated["with"]["skills-dir"], ".github/fixtures/populated/skills")
        self.assertEqual(populated["with"]["evals-dir"], ".github/fixtures/populated/evals")
        self.assertEqual(populated["with"]["require-populated-manifests"], "true")
        self.assertEqual(self.workflow["on"]["workflow_call"]["inputs"]["require-populated-manifests"]["default"], "false")
        self.environment.update(SKILLS_DIR=populated["with"]["skills-dir"], EVALS_DIR=populated["with"]["evals-dir"], REQUIRE_POPULATED_MANIFESTS="true")
        shutil.copytree(REPOSITORY / ".github/fixtures/populated", self.root / ".github/fixtures/populated")
        result = self.manifests()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("skill manifests checked: 1; failed: 0", result.stdout)
        self.assertEqual([call[0] for call in self.runner_calls()], ["validate", "audit-manifest"])

    def test_link_exception_workflow_input_reaches_the_content_checker(self) -> None:
        inputs = self.workflow["on"]["workflow_call"]["inputs"]
        self.assertIn("content-link-exceptions-file", inputs)
        step = self.steps["Skill links and references, plus retired text from a conventions file"]
        self.assertEqual(
            step["env"]["LINK_EXCEPTIONS_FILE"],
            "${{ inputs.content-link-exceptions-file }}",
        )
        source = self.package()
        (source / "SKILL.md").write_text("[report](output.md)\n")
        policy = self.root / "link exceptions.json"
        policy.write_text(json.dumps({
            "version": 1,
            "inline_link_exceptions": {"example/SKILL.md": ["output.md"]},
        }))
        missing = self.run_body(step["run"])
        self.assertEqual(missing.returncode, 1, missing.stdout + missing.stderr)
        self.assertIn("target does not exist: output.md", missing.stdout)
        self.environment["LINK_EXCEPTIONS_FILE"] = str(policy)
        allowed = self.run_body(step["run"])
        self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)
        self.assertEqual(allowed.stdout, "")
        (source / "SKILL.md").write_text("[report](output.md)\n![image](output.md)\n")
        blocked = self.run_body(step["run"])
        self.assertEqual(blocked.returncode, 1, blocked.stdout + blocked.stderr)
        self.assertIn("SKILL.md:2: relative-link: target does not exist: output.md", blocked.stdout)
        policy.write_text('{"version": 2, "inline_link_exceptions": {}}')
        invalid = self.run_body(step["run"])
        self.assertEqual(invalid.returncode, 2, invalid.stdout + invalid.stderr)
        self.assertIn("version", invalid.stderr)

    def test_conventions_workflow_input_reaches_the_content_checker(self) -> None:
        inputs = self.workflow["on"]["workflow_call"]["inputs"]
        self.assertEqual(inputs["content-conventions-file"]["default"], "")
        step = self.steps["Skill links and references, plus retired text from a conventions file"]
        self.assertEqual(
            step["env"]["CONVENTIONS_FILE"],
            "${{ inputs.content-conventions-file }}",
        )
        source = self.package()
        (source / "SKILL.md").write_text("Run /retired here.\n")
        quiet = self.run_body(step["run"])
        self.assertEqual(quiet.returncode, 0, quiet.stdout + quiet.stderr)
        conventions = self.root / "content conventions.json"
        conventions.write_text(json.dumps({
            "version": 1,
            "retired_text": {"/retired": "use the new command"},
        }))
        self.environment["CONVENTIONS_FILE"] = str(conventions)
        flagged = self.run_body(step["run"])
        self.assertEqual(flagged.returncode, 1, flagged.stdout + flagged.stderr)
        self.assertIn("SKILL.md:1: retired-text: use the new command", flagged.stdout)
        conventions.write_text('{"version": 1, "skill_prefixes": ["nohyphen"]}')
        invalid = self.run_body(step["run"])
        self.assertEqual(invalid.returncode, 2, invalid.stdout + invalid.stderr)
        self.assertIn("ending in a hyphen", invalid.stderr)

    @unittest.skipUnless(shutil.which("mise") and shutil.which("dash"), "requires mise and dash")
    def test_mise_lint_task_applies_the_optional_link_policy(self) -> None:
        source = self.package()
        with (source / "SKILL.md").open("a") as skill:
            skill.write("[report](output.md)\n")
        policy = self.root / "link exceptions.json"
        policy.write_text(json.dumps({
            "version": 1,
            "inline_link_exceptions": {"example/SKILL.md": ["output.md"]},
        }))
        self.environment["MISE_TRUSTED_CONFIG_PATHS"] = os.pathsep.join((str(self.root), str(REPOSITORY)))
        self.environment["MISE_UNIX_DEFAULT_INLINE_SHELL_ARGS"] = f"{shutil.which('dash')} -c"
        tools = tomllib.loads((REPOSITORY / "mise.toml").read_text())["tools"]
        (self.root / "mise.toml").write_text(
            "[tools]\n"
            + "".join(f"{name} = {json.dumps(version)}\n" for name, version in tools.items())
            + f"[task_config]\nincludes = [{json.dumps(str(REPOSITORY / 'skill-tasks.toml'))}]\n"
        )
        for configured in (False, True):
            with self.subTest(configured=configured):
                self.environment["CONTENT_LINK_EXCEPTIONS_FILE"] = str(policy) if configured else ""
                result = subprocess.run(
                    ["mise", "run", "skill-lint"], cwd=self.root, env=self.environment,
                    capture_output=True, text=True, timeout=30, check=False,
                )
                self.assertEqual(result.returncode, 0 if configured else 1, result.stdout + result.stderr)
                if not configured:
                    self.assertIn("target does not exist: output.md", result.stdout)
        conventions = self.root / "content conventions.json"
        conventions.write_text(json.dumps({
            "version": 1,
            "retired_text": {"output.md": "name the report explicitly"},
        }))
        self.environment["CONTENT_CONVENTIONS_FILE"] = str(conventions)
        result = subprocess.run(
            ["mise", "run", "skill-lint"], cwd=self.root, env=self.environment,
            capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("retired-text: name the report explicitly", result.stdout)
        self.assertNotIn("relative-link", result.stdout)

    def package(self, name: str = "example") -> Path:
        package = self.root / self.environment["SKILLS_DIR"] / name
        package.mkdir(parents=True)
        (package / "SKILL.md").write_text("---\nname: example\ndescription: A fixture.\n---\n")
        return package

    def package_task(self) -> subprocess.CompletedProcess[str]:
        tasks = tomllib.loads((REPOSITORY / "skill-tasks.toml").read_text())
        return self.run_body(tasks["skill-package"]["run"])

    def runner_task(self, name: str, skill: str = "skills/example") -> subprocess.CompletedProcess[str]:
        tasks = tomllib.loads((REPOSITORY / "skill-tasks.toml").read_text())
        body = tasks[name]["run"].replace(
            '{{arg(name="skill", help="skill directory, e.g. skills/my-skill")}}', skill,
        )
        return self.run_body(body)

    def test_package_task_checks_the_default_collection(self) -> None:
        self.package()
        self.environment.pop("SKILLS_DIR")
        result = self.package_task()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("packages checked: 1; passed: 1; failed: 0; copies compared: 0", result.stdout)
        self.assertFalse(self.log.exists())

    def test_package_task_compares_copies_with_spaces_in_paths(self) -> None:
        self.environment["SKILLS_DIR"] = "source skills"
        source = self.package("an example")
        destination = self.root / "installed skills" / "an example"
        shutil.copytree(source, destination)
        self.environment["INSTALLED_SKILLS_DIR"] = "installed skills"
        result = self.package_task()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("copies compared: 1", result.stdout)
        (destination / "SKILL.md").write_text("changed")
        drift = self.package_task()
        self.assertEqual(drift.returncode, 1, drift.stderr)
        self.assertIn("content changed: SKILL.md", drift.stdout)
        self.assertFalse(self.log.exists())

    def test_package_task_rejects_an_empty_collection(self) -> None:
        (self.root / "skills").mkdir()
        result = self.package_task()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("inventory is empty", result.stdout)

    @unittest.skipUnless(shutil.which("mise") and shutil.which("dash"), "requires mise and dash")
    def test_mise_package_task_overrides_a_posix_default_shell(self) -> None:
        self.environment["SKILLS_DIR"] = "source skills"
        source = self.package("an example")
        destination = self.root / "installed skills" / "an example"
        shutil.copytree(source, destination)
        self.environment.update(
            INSTALLED_SKILLS_DIR="installed skills",
            MISE_UNIX_DEFAULT_INLINE_SHELL_ARGS=f"{shutil.which('dash')} -c",
            MISE_TRUSTED_CONFIG_PATHS=os.pathsep.join((str(self.root), str(REPOSITORY))),
        )
        tools = tomllib.loads((REPOSITORY / "mise.toml").read_text())["tools"]
        (self.root / "mise.toml").write_text(
            "[tools]\n"
            + "".join(f"{name} = {json.dumps(version)}\n" for name, version in tools.items())
            + f"[task_config]\nincludes = [{json.dumps(str(REPOSITORY / 'skill-tasks.toml'))}]\n"
        )

        for changed in (False, True):
            with self.subTest(changed=changed):
                if changed:
                    (destination / "SKILL.md").write_text("changed")
                result = subprocess.run(
                    ["mise", "run", "skill-package"],
                    cwd=self.root,
                    env=self.environment,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(result.returncode, int(changed), result.stdout + result.stderr)
                self.assertIn("copies compared: 1", result.stdout)
                if changed:
                    self.assertIn("content changed: SKILL.md", result.stdout)

    def test_package_workflow_step_passes_then_rejects_a_symlink(self) -> None:
        source = self.package()
        body = self.steps["Skill package integrity"]["run"]
        result = self.run_body(body)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("packages checked: 1; passed: 1", result.stdout)
        (source / "linked").symlink_to("SKILL.md")
        invalid = self.run_body(body)
        self.assertEqual(invalid.returncode, 1, invalid.stderr)
        self.assertIn("package contains a symlink", invalid.stdout)
        self.assertFalse(self.log.exists())

    def test_package_workflow_step_rejects_missing_collection(self) -> None:
        result = self.run_body(self.steps["Skill package integrity"]["run"])
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("missing or unreadable", result.stdout)


if __name__ == "__main__":
    unittest.main()
