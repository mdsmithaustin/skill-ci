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
        self.root = Path(self.temporary.name)
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
            INSTALLED_SKILLS_DIR="",
            LINK_EXCEPTIONS_FILE="",
            RUNNER_LOG=str(self.log),
            RUNNER_EXIT="0",
        )
        (self.root / ".skill-ci").symlink_to(REPOSITORY, target_is_directory=True)
        (self.bin / "python3").symlink_to(sys.executable)
        self.executable(
            "skill-benchmark",
            "import json, os, sys\n"
            "with open(os.environ['RUNNER_LOG'], 'a') as log:\n"
            "    log.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "raise SystemExit(int(os.environ['RUNNER_EXIT']))\n",
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

    def test_missing_external_directory_fails_before_runner(self) -> None:
        self.environment["EVALS_DIR"] = "missing"
        result = self.manifests()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("not a directory", result.stdout)
        self.assertFalse(self.log.exists())

    def test_link_exception_workflow_input_reaches_the_content_checker(self) -> None:
        inputs = self.workflow["on"]["workflow_call"]["inputs"]
        self.assertIn("content-link-exceptions-file", inputs)
        step = self.steps["Skill links, references, and port substitutions"]
        self.assertEqual(
            step["env"]["LINK_EXCEPTIONS_FILE"],
            "${{ inputs.content-link-exceptions-file }}",
        )
        self.assertIn(
            'command+=(--link-exceptions-file "$LINK_EXCEPTIONS_FILE")',
            step["run"],
        )

    def package(self, name: str = "example") -> Path:
        package = self.root / self.environment["SKILLS_DIR"] / name
        package.mkdir(parents=True)
        (package / "SKILL.md").write_text("---\nname: example\ndescription: A fixture.\n---\n")
        return package

    def package_task(self) -> subprocess.CompletedProcess[str]:
        tasks = tomllib.loads((REPOSITORY / "skill-tasks.toml").read_text())
        return self.run_body(tasks["skill-package"]["run"])

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
