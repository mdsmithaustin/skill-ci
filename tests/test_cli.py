from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from skill_ci import suite
from support import ENVIRONMENT, INSTALLED_COMMAND, PLANTED_EMAIL, REPOSITORY, FakeHarness, case, git, manifest, skill_ci, write, write_skill


def lines(result: subprocess.CompletedProcess[str]) -> list[str]:
    return result.stdout.splitlines()


class FixtureContractTests(unittest.TestCase):
    def test_fixture_contract(self) -> None:
        result = skill_ci(
            "check",
            "--skills-dir",
            ".github/fixtures/skills",
            "--evals-dir",
            ".github/fixtures/evals",
            "--require-manifests",
            cwd=REPOSITORY,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(".github/fixtures/evals/example/shared-benchmark.json: no cases yet, readiness audit skipped", lines(result))
        self.assertIn("manifests checked: 1", lines(result))
        self.assertEqual(lines(result)[-1], "checks run: 4; failed: 0")

    def test_populated_contract(self) -> None:
        result = skill_ci(
            "check",
            "--skills-dir",
            ".github/fixtures/populated/skills",
            "--evals-dir",
            ".github/fixtures/populated/evals",
            "--require-populated-manifests",
            cwd=REPOSITORY,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("skill manifests checked: 1; failed: 0", lines(result))
        self.assertIn("manifests checked: 1", lines(result))
        self.assertEqual(lines(result)[-1], "checks run: 5; failed: 0")
        self.assertNotIn("warning", result.stderr)


class ConsumerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="skill-ci-cli-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / "consumer"
        self.root.mkdir()
        git("init", "-q", cwd=self.root)

    def skill_ci(self, *arguments: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        git("add", "-A", cwd=self.root)
        return skill_ci(*arguments, cwd=self.root, env=env)


class ManifestTests(ConsumerTestCase):
    def test_empty_inventory_is_optional_and_can_be_required(self) -> None:
        write_skill(self.root / "skills" / "example")
        optional = self.skill_ci("check")
        self.assertEqual(optional.returncode, 0, optional.stdout + optional.stderr)
        self.assertIn("manifests checked: 0", lines(optional))
        self.assertEqual(lines(optional)[-1], "checks run: 4; failed: 0")
        required = self.skill_ci("check", "--require-manifests")
        self.assertEqual(required.returncode, 1, required.stdout + required.stderr)
        self.assertIn("skill-ci: require-manifests is enabled, but no manifest files were checked", required.stderr)
        self.assertEqual(lines(required)[-1], "checks run: 4; failed: 1 (manifests)")

    def test_an_empty_scaffold_in_either_layout_is_validated_and_its_audit_skipped(self) -> None:
        write_skill(self.root / "skills" / "example")
        for external in (False, True):
            with self.subTest(external=external):
                relative = "evals/example/shared-benchmark.json" if external else "skills/example/evals/shared-benchmark.json"
                path = write(self.root / relative, manifest("example", ["skills/example/SKILL.md"] if external else ["SKILL.md"]))
                result = self.skill_ci("check", "--require-manifests", *(("--evals-dir", "evals") if external else ()))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("OK: example — 0 cases, 0 ablations", lines(result))
                self.assertIn(f"{relative}: no cases yet, readiness audit skipped", lines(result))
                self.assertIn("manifests checked: 1", lines(result))
                path.unlink()

    def test_audit_includes_the_empty_manifests_that_check_skips(self) -> None:
        write_skill(self.root / "skills" / "example")
        write(self.root / "evals/example/shared-benchmark.json", manifest("example", ["skills/example/SKILL.md"]))
        audited = self.skill_ci("audit", "--evals-dir", "evals")
        self.assertEqual(audited.returncode, 1, audited.stdout + audited.stderr)
        self.assertIn("readiness blocker: no adversarial cases (kind: adversarial)", audited.stderr)
        self.assertIn("manifests checked: 1", lines(audited))
        checked = self.skill_ci("check", "--evals-dir", "evals")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)

    def test_a_populated_manifest_is_validated_and_audited(self) -> None:
        write_skill(self.root / "skills" / "a")
        write(self.root / "evals with spaces/a/shared-benchmark.json", manifest("a", ["skills/a/SKILL.md"], [case()]))
        result = self.skill_ci("check", "--evals-dir", "evals with spaces", "--require-manifests")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OK: a — 1 cases, 0 ablations", lines(result))
        self.assertIn('"manifest": "evals with spaces/a/shared-benchmark.json"', result.stdout)
        self.assertEqual(lines(result)[-1], "checks run: 4; failed: 0")

    def test_a_manifest_that_fails_validation_is_not_audited_and_the_next_still_runs(self) -> None:
        write_skill(self.root / "skills" / "a")
        write_skill(self.root / "skills" / "b")
        write(self.root / "evals/b/shared-benchmark.json", manifest("b", ["skills/b/SKILL.md"], [case()]))
        for invalid, error in (
            (
                manifest("a", ["skills/a/SKILL.md"], [case(prompt="Repair the thing and say repaired.")]),
                "FAIL: prompt/assertion leakage found in 1 assertion value(s)",
            ),
            (manifest("a", ["ancillary.txt"], [case()]), "ancillary.txt is not a SKILL.md file"),
        ):
            with self.subTest(error=error):
                write(self.root / "evals/a/shared-benchmark.json", invalid)
                result = self.skill_ci("check", "--evals-dir", "evals")
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(result.stderr.count(error), 1, result.stderr)
                self.assertNotIn('"manifest": "evals/a/shared-benchmark.json"', result.stdout)
                self.assertIn("OK: b — 1 cases, 0 ablations", lines(result))
                self.assertIn('"manifest": "evals/b/shared-benchmark.json"', result.stdout)
                self.assertIn("manifests checked: 2", lines(result))
                self.assertEqual(lines(result)[-1], "checks run: 4; failed: 1 (manifests)")

    def test_a_validated_manifest_that_fails_the_audit(self) -> None:
        write_skill(self.root / "skills" / "a")
        write(self.root / "evals/a/shared-benchmark.json", manifest("a", ["skills/a/SKILL.md"], [case(kind=None)]))
        checked = self.skill_ci("check", "--evals-dir", "evals")
        self.assertEqual(checked.returncode, 1, checked.stdout + checked.stderr)
        self.assertIn("OK: a — 1 cases, 0 ablations", lines(checked))
        self.assertIn("readiness blocker: no adversarial cases (kind: adversarial)", checked.stderr)
        self.assertEqual(lines(checked)[-1], "checks run: 4; failed: 1 (manifests)")
        validated = self.skill_ci("validate", "--evals-dir", "evals")
        self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)
        self.assertEqual(lines(validated), ["OK: a — 1 cases, 0 ablations", "manifests checked: 1"])
        audited = self.skill_ci("audit", "--evals-dir", "evals")
        self.assertEqual(audited.returncode, 1, audited.stdout + audited.stderr)
        self.assertIn("audit-manifest: 1 readiness blocker(s) for 'a'", audited.stderr)

    def test_discovery_never_descends_into_a_symlinked_directory(self) -> None:
        write_skill(self.root / "skills" / "a")
        write_skill(self.root / "skills" / "b")
        elsewhere = self.root.parent / "elsewhere"
        write(elsewhere / "shared-benchmark.json", "not a manifest")
        write(self.root / "skills/b/evals/shared-benchmark.json", manifest("b", ["SKILL.md"]))
        write(self.root / "evals/b/shared-benchmark.json", manifest("b", ["skills/b/SKILL.md"]))
        (self.root / "skills/a/evals").symlink_to(elsewhere, target_is_directory=True)
        (self.root / "evals/a").symlink_to(elsewhere, target_is_directory=True)
        (self.root / "linked evals").symlink_to(self.root / "evals", target_is_directory=True)
        (self.root / "linked skills").symlink_to(self.root / "skills", target_is_directory=True)
        for layout in ((), ("--evals-dir", "evals"), ("--evals-dir", "linked evals"), ("--skills-dir", "linked skills")):
            with self.subTest(layout=layout):
                result = self.skill_ci("validate", *layout)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(lines(result), ["OK: b — 0 cases, 0 ablations", "manifests checked: 1"])

    def test_a_manifest_directly_inside_a_skills_root_named_evals_is_not_checked(self) -> None:
        write_skill(self.root / "evals" / "a")
        write(self.root / "evals/shared-benchmark.json", "not a manifest")
        write(self.root / "evals/a/evals/shared-benchmark.json", manifest("a", ["SKILL.md"]))
        result = self.skill_ci("validate", "--skills-dir", "evals")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(lines(result), ["OK: a — 0 cases, 0 ablations", "manifests checked: 1"])

    def test_an_unreadable_directory_under_the_root_fails_discovery_and_is_named(self) -> None:
        write_skill(self.root / "skills" / "a")
        write(self.root / "evals/a/shared-benchmark.json", manifest("a", ["skills/a/SKILL.md"]))
        locked = write(self.root / "evals/locked/shared-benchmark.json", "not a manifest").parent
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o755)
        if os.access(locked, os.R_OK):
            self.skipTest("this user can read a directory without read permission")
        for command, stdout in (("validate", []), ("audit", []), ("check", ["checks run: 4; failed: 1 (manifests)"])):
            with self.subTest(command=command):
                result = self.skill_ci(command, "--evals-dir", "evals")
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("skill-ci: cannot search evals/locked for manifests: Permission denied", result.stderr.splitlines())
                self.assertEqual(lines(result)[-1:], stdout)
                self.assertNotIn("manifests checked", result.stdout)

    def test_a_manifest_whose_judge_is_a_model_under_test_fails_the_audit(self) -> None:
        write_skill(self.root / "skills" / "a")
        self_judging = {**json.loads(manifest("a", ["skills/a/SKILL.md"], [case()])), "judge": {"model": "m"}, "jetty": {"model": "m"}}
        write(self.root / "evals/a/shared-benchmark.json", json.dumps(self_judging))
        for command in ("audit", "check"):
            with self.subTest(command=command):
                result = self.skill_ci(command, "--evals-dir", "evals")
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("strict-judge: judge model 'm' is also a model under test", result.stderr)

    def test_a_missing_evals_directory_fails_before_the_harness(self) -> None:
        write_skill(self.root / "skills" / "example")
        result = self.skill_ci("validate", "--evals-dir", "does-not-exist")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("does-not-exist is not a directory", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_populated_coverage_rejects_missing_empty_and_wrong_bindings(self) -> None:
        write_skill(self.root / "skills" / "a")
        write_skill(self.root / "skills" / "b")
        write(self.root / "evals/a/shared-benchmark.json", manifest("a", ["skills/a/SKILL.md"], [case()]))
        populated = ("check", "--evals-dir", "evals", "--require-populated-manifests")
        missing = self.skill_ci(*populated)
        self.assertEqual(missing.returncode, 1, missing.stdout + missing.stderr)
        self.assertIn("evals/b/shared-benchmark.json", missing.stderr)
        self.assertEqual(lines(missing)[-1], "checks run: 5; failed: 1 (coverage)")
        other = self.root / "evals/b/shared-benchmark.json"
        for cases, paths, message in (
            ([], ["skills/b/SKILL.md"], "nonempty cases"),
            ([case()], ["skills/a/SKILL.md"], "does not bind"),
        ):
            with self.subTest(message=message):
                write(other, manifest("b", paths, cases))
                result = self.skill_ci(*populated)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn(message, result.stderr)
                self.assertIn("(coverage", lines(result)[-1])
        write(other, manifest("b", ["skills/b"], [case()]))
        complete = self.skill_ci(*populated)
        self.assertEqual(complete.returncode, 0, complete.stdout + complete.stderr)
        self.assertIn("skill manifests checked: 2; failed: 0", lines(complete))
        self.assertIn("manifests checked: 2", lines(complete))

    def test_populated_coverage_uses_directory_names_in_both_layouts(self) -> None:
        for external in (False, True):
            with self.subTest(external=external):
                source = write_skill(self.root / "skills with spaces" / "directory-name")
                if external:
                    write(
                        self.root / "evals with spaces/directory-name/shared-benchmark.json",
                        manifest("example", [str(source)], [case()]),
                    )
                else:
                    write(source / "evals/shared-benchmark.json", manifest("example", ["SKILL.md"], [case()]))
                result = self.skill_ci(
                    "check",
                    "--skills-dir",
                    "skills with spaces",
                    *(("--evals-dir", "evals with spaces") if external else ()),
                    "--require-populated-manifests",
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("skill manifests checked: 1; failed: 0", lines(result))
                self.assertIn("manifests checked: 1", lines(result))
                shutil.rmtree(self.root / "skills with spaces")
                shutil.rmtree(self.root / "evals with spaces", ignore_errors=True)

    def test_coverage_requires_cases_in_every_manifest(self) -> None:
        source = write_skill(self.root / "skills" / "example")
        path = write(source / "evals/shared-benchmark.json", manifest("example", ["SKILL.md"], [case()]))
        complete = self.skill_ci("coverage")
        self.assertEqual(complete.returncode, 0, complete.stdout + complete.stderr)
        self.assertEqual(lines(complete), ["skill manifests checked: 1; failed: 0"])
        path.write_text(manifest("example", ["SKILL.md"]))
        empty = self.skill_ci("coverage")
        self.assertEqual(empty.returncode, 1, empty.stdout + empty.stderr)
        self.assertIn("nonempty cases", empty.stderr)


class PackageTests(ConsumerTestCase):
    def test_default_collection_passes(self) -> None:
        write_skill(self.root / "skills" / "example")
        result = self.skill_ci("package")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("packages checked: 1; passed: 1; failed: 0; copies compared: 0", lines(result))

    def test_compare_to_detects_a_changed_copy_with_spaces_in_paths(self) -> None:
        source = write_skill(self.root / "source skills" / "an example")
        destination = self.root / "installed skills" / "an example"
        shutil.copytree(source, destination)
        arguments = ("package", "--skills-dir", "source skills", "--compare-to", "installed skills")
        same = self.skill_ci(*arguments)
        self.assertEqual(same.returncode, 0, same.stdout + same.stderr)
        self.assertIn("packages checked: 1; passed: 1; failed: 0; copies compared: 1", lines(same))
        (destination / "SKILL.md").write_text("changed")
        drift = self.skill_ci(*arguments)
        self.assertEqual(drift.returncode, 1, drift.stdout + drift.stderr)
        self.assertIn("an example: content changed: SKILL.md", lines(drift))

    def test_missing_empty_and_symlinked_collections_fail(self) -> None:
        missing = self.skill_ci("package")
        self.assertEqual(missing.returncode, 1, missing.stdout + missing.stderr)
        self.assertIn("missing or unreadable", missing.stdout)
        (self.root / "skills").mkdir()
        empty = self.skill_ci("package")
        self.assertEqual(empty.returncode, 1, empty.stdout + empty.stderr)
        self.assertIn("inventory is empty", empty.stdout)
        source = write_skill(self.root / "skills" / "example")
        (source / "linked").symlink_to("SKILL.md")
        linked = self.skill_ci("package")
        self.assertEqual(linked.returncode, 1, linked.stdout + linked.stderr)
        self.assertIn("package contains a symlink", linked.stdout)
        checked = self.skill_ci("check", "--package")
        self.assertEqual(checked.returncode, 1, checked.stdout + checked.stderr)
        self.assertEqual(lines(checked)[-1], "checks run: 5; failed: 1 (package)")


class LintTests(ConsumerTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.skill = write_skill(self.root / "skills" / "example")

    def append(self, text: str) -> None:
        with (self.skill / "SKILL.md").open("a") as skill:
            skill.write(text)

    def test_link_exceptions_file_allows_a_named_missing_link(self) -> None:
        self.append("\n[report](output.md)\n")
        policy = write(
            self.root / "link exceptions.json",
            json.dumps({"version": 1, "inline_link_exceptions": {"example/SKILL.md": ["output.md"]}}),
        )
        missing = self.skill_ci("lint")
        self.assertEqual(missing.returncode, 1, missing.stdout + missing.stderr)
        self.assertIn("skills/example/SKILL.md:7: relative-link: target does not exist: output.md", lines(missing))
        self.assertEqual(lines(missing)[-1], "checks run: 2; failed: 1 (content)")
        allowed = self.skill_ci("lint", "--content-link-exceptions-file", str(policy))
        self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)
        self.assertEqual(lines(allowed), ["checks run: 2; failed: 0"])

    def test_conventions_file_flags_retired_text(self) -> None:
        self.append("\nRun /retired here.\n")
        quiet = self.skill_ci("lint")
        self.assertEqual(quiet.returncode, 0, quiet.stdout + quiet.stderr)
        conventions = write(
            self.root / "content conventions.json",
            json.dumps({"version": 1, "retired_text": {"/retired": "use the new command"}}),
        )
        flagged = self.skill_ci("lint", "--content-conventions-file", str(conventions))
        self.assertEqual(flagged.returncode, 1, flagged.stdout + flagged.stderr)
        self.assertIn("skills/example/SKILL.md:7: retired-text: use the new command", lines(flagged))

    def test_ignore_file_names_skills_that_live_elsewhere(self) -> None:
        self.append("\nUse the **other-tool** skill.\nThen the **x-tool** and **y-tool** skills.\n")
        flagged = self.skill_ci("lint")
        self.assertEqual(flagged.returncode, 1, flagged.stdout + flagged.stderr)
        self.assertIn("skills/example/SKILL.md:7: sibling-skill: **other-tool** has no matching directory under skills/", lines(flagged))
        self.assertIn("skills/example/SKILL.md:8: sibling-skill: **y-tool** has no matching directory under skills/", lines(flagged))
        ignore = write(self.root / "ignore list", "# skills from another repository\n\n  other-tool  \nx-tool, y-tool\n")
        ignored = self.skill_ci("lint", "--content-ignore-file", str(ignore))
        self.assertEqual(ignored.returncode, 0, ignored.stdout + ignored.stderr)
        self.assertEqual(lines(ignored), ["checks run: 2; failed: 0"])
        unreadable = self.skill_ci("lint", "--content-ignore-file", "missing list")
        self.assertEqual(unreadable.returncode, 2, unreadable.stdout + unreadable.stderr)
        self.assertIn("skill-ci: cannot read content ignore file missing list:", unreadable.stderr)
        self.assertEqual(lines(unreadable)[-1], "checks run: 2; failed: 1 (content)")

    def test_an_indented_comment_line_in_the_ignore_file_names_no_skill(self) -> None:
        self.append("\nUse the **other-tool** skill.\n")
        ignore = write(self.root / "ignore list", "  # moved out later: x-tool, other-tool\n")
        result = self.skill_ci("lint", "--content-ignore-file", str(ignore))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("skills/example/SKILL.md:7: sibling-skill: **other-tool** has no matching directory under skills/", lines(result))

    def test_trigger_cases_must_declare_every_skill(self) -> None:
        quiet = self.skill_ci("lint")
        self.assertEqual(quiet.returncode, 0, quiet.stdout + quiet.stderr)
        corpus = write(
            self.root / "trigger cases.json",
            json.dumps(
                {
                    "version": 1,
                    "triggers": [
                        {
                            "skill": "example",
                            "example_request": "Give me an example.",
                            "description_contains": ["missing anchor"],
                            "implicit_allowed": True,
                        }
                    ],
                }
            ),
        )
        flagged = self.skill_ci("lint", "--trigger-cases", str(corpus))
        self.assertEqual(flagged.returncode, 1, flagged.stdout + flagged.stderr)
        self.assertIn("anchor 'missing anchor' is absent from 'example' description", flagged.stdout)
        self.assertEqual(lines(flagged)[-1], "checks run: 2; failed: 1 (frontmatter)")


class FastCheckTests(ConsumerTestCase):
    def setUp(self) -> None:
        super().setUp()
        write_skill(self.root / "skills" / "example")

    def test_staged_pii_under_the_skills_directory_fails(self) -> None:
        write(self.root / "skills/example/notes.md", f"# Notes\n\nWrite to {PLANTED_EMAIL}.\n")
        result = self.skill_ci("check", "--fast")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("skills/example/notes.md:3: possible email address", lines(result))
        self.assertEqual(lines(result)[-1], "checks run: 3; failed: 1 (pii)")

    def test_findings_print_in_check_order_when_output_is_piped(self) -> None:
        write(self.root / "skills/example/notes.md", f"# Notes\n\nWrite to {PLANTED_EMAIL}.\n")
        git("add", "-A", cwd=self.root)
        result = subprocess.run(
            [str(INSTALLED_COMMAND), "check", "--fast"],
            cwd=self.root,
            env=ENVIRONMENT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "skills/example/notes.md:3: possible email address",
                "frontmatter: 1 skills, 0 errors",
                "content: 2 files, 0 findings",
                "checks run: 3; failed: 1 (pii)",
            ],
        )

    def test_a_pii_scan_git_cannot_run_names_the_reason(self) -> None:
        with tempfile.TemporaryDirectory(prefix="skill-ci-no-git-") as temporary:
            outside = Path(temporary).resolve()
            write_skill(outside / "skills" / "example")
            no_repository = skill_ci("check", "--fast", cwd=outside)
            skills_elsewhere = self.skill_ci("check", "--fast", "--skills-dir", str(outside / "skills"))
            untrusted = {"GIT_TEST_ASSUME_DIFFERENT_OWNER": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
            dubious_owner = self.skill_ci("check", "--fast", env={**ENVIRONMENT, **untrusted})
            no_git = self.skill_ci("check", "--fast", env={**ENVIRONMENT, "PATH": str(outside / "empty")})
        failed = "skill-ci: pii: the PII scan lists files with git, which failed: "
        self.assertEqual(no_repository.returncode, 2, no_repository.stdout + no_repository.stderr)
        self.assertIn(f"{failed}fatal: not a git repository", no_repository.stderr)
        self.assertEqual(lines(no_repository)[-1], "checks run: 3; failed: 1 (pii)")
        self.assertEqual(skills_elsewhere.returncode, 2, skills_elsewhere.stdout + skills_elsewhere.stderr)
        self.assertRegex(skills_elsewhere.stderr, rf"{failed}fatal: .*skills.* is outside repository")
        self.assertEqual(dubious_owner.returncode, 2, dubious_owner.stdout + dubious_owner.stderr)
        self.assertIn(f"{failed}fatal: detected dubious ownership in repository", dubious_owner.stderr)
        self.assertEqual(no_git.returncode, 2, no_git.stdout + no_git.stderr)
        self.assertIn("skill-ci: pii: unable to read input: [Errno 2] No such file or directory: 'git'", no_git.stderr)

    def test_the_scope_decides_whether_pii_outside_the_skills_directory_counts(self) -> None:
        write(self.root / "docs/notes.md", f"Write to {PLANTED_EMAIL}.\n")
        skills = self.skill_ci("check", "--fast")
        self.assertEqual(skills.returncode, 0, skills.stdout + skills.stderr)
        self.assertEqual(lines(skills), ["checks run: 3; failed: 0"])
        repository = self.skill_ci("check", "--fast", "--pii-scope", "repository")
        self.assertEqual(repository.returncode, 1, repository.stdout + repository.stderr)
        self.assertIn("docs/notes.md:1: possible email address", lines(repository))

    def test_fast_ignores_the_other_check_flags_and_never_loads_the_harness(self) -> None:
        marker = self.root.parent / "harness-loaded"
        plant = write(self.root.parent / "plant" / "skill_benchmark.py", f"open({str(marker)!r}, 'w').close()\n")
        result = self.skill_ci(
            "check",
            "--fast",
            "--evals-dir",
            "missing",
            "--require-manifests",
            "--require-populated-manifests",
            "--package",
            env={**ENVIRONMENT, "PYTHONPATH": str(plant.parent)},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(lines(result), ["checks run: 3; failed: 0"])
        self.assertFalse(marker.exists())


class FullCheckTests(ConsumerTestCase):
    def test_check_scans_every_tracked_file_in_the_pii_scope(self) -> None:
        write_skill(self.root / "skills" / "example")
        write(self.root / "skills/example/notes.md", f"# Notes\n\nWrite to {PLANTED_EMAIL}.\n")
        write(self.root / "docs/notes.md", f"Write to {PLANTED_EMAIL}.\n")
        git("add", "-A", cwd=self.root)
        author = ("-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false")
        git(*author, "commit", "-q", "-m", "committed findings", cwd=self.root)
        skills = skill_ci("check", cwd=self.root)
        self.assertEqual(skills.returncode, 1, skills.stdout + skills.stderr)
        self.assertIn("skills/example/notes.md:3: possible email address", lines(skills))
        self.assertNotIn("docs/notes.md:1: possible email address", lines(skills))
        self.assertEqual(lines(skills)[-1], "checks run: 4; failed: 1 (pii)")
        repository = skill_ci("check", "--pii-scope", "repository", cwd=self.root)
        self.assertEqual(repository.returncode, 1, repository.stdout + repository.stderr)
        self.assertIn("docs/notes.md:1: possible email address", lines(repository))
        self.assertIn("skills/example/notes.md:3: possible email address", lines(repository))


class CheckRunnerTests(unittest.TestCase):
    def test_a_check_that_exits_with_a_message_prints_it_and_counts_as_failed(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = suite.run_checks([("first", lambda: sys.exit("the first check gave up")), ("second", lambda: 0)])
        self.assertEqual(code, 1)
        self.assertEqual(stderr.getvalue(), "the first check gave up\n")
        self.assertEqual(stdout.getvalue(), "checks run: 2; failed: 1 (first)\n")


class PaidRunTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="skill-ci-paid-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.checkout = self.root / "checkout"
        self.package = write_skill(self.checkout / "skills" / "example")
        git("init", "-q", cwd=self.checkout)
        source = self.root / "skill ci source"
        shutil.copytree(REPOSITORY / "src", source, ignore=shutil.ignore_patterns("__pycache__"))
        self.launchers = source / "skill_ci" / "launchers"
        self.fake = FakeHarness(self.root, source)
        self.runs_root = self.root / "checkout.eval-runs"

    def paid(self, *arguments: str, cwd: Path | None = None, **variables: str) -> subprocess.CompletedProcess[str]:
        return self.fake.run(*arguments, cwd=cwd or self.checkout, **variables)

    def output(self, command: str) -> Path:
        stage = self.fake.arguments()[0 if command == "trigger" else 1]
        return Path(stage[stage.index("--out") + 1]).parent

    def test_trigger_passes_the_launchers_and_flags_to_the_matrix(self) -> None:
        result = self.paid(
            "trigger", "skills/example", "--evals-dir", "evals", "--out", "run output", "--runs", "2", "--model", "m1"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        [call] = self.fake.calls()
        self.assertEqual(call["command"], "skill-trigger-matrix")
        arguments = call["arguments"]
        codex = arguments[arguments.index("--codex-cmd") + 1]
        self.assertEqual(shlex.split(codex)[0], str(self.launchers / "codex-project-only"))
        self.assertEqual(
            arguments,
            [
                "evals/example/shared-benchmark.json",
                "--agent", "claude", "--agent", "codex",
                "--claude-bin", str(self.launchers / "claude-project-only"),
                "--codex-cmd", codex,
                "--runs-per-query", "2", "--model", "m1",
                "--trace-runs", "run output/traces",
                "--out", "run output/trigger-matrix.json",
            ],
        )
        self.assertTrue((self.checkout / "run output").is_dir())

    def test_run_stages_each_agent_through_the_harness(self) -> None:
        result = self.paid(
            "run", "skills/example",
            "--evals-dir", "evals",
            "--out", "run output",
            "--runs", "2",
            "--model", "m1",
            "--codex-model", "m2",
            "--codex-cmd", "my codex --flag",
            "--timeout", "99",
            "--judge-model", "j1",
            "--judge-runs", "4",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest_path = "evals/example/shared-benchmark.json"
        claude = str(self.launchers / "claude-project-only")

        def agent(name: str, flags: list[str]) -> list[list[str]]:
            runs = f"run output/{name}"
            return [
                ["run-agent", "--agent", name, *flags, "--tasks", "run output/tasks.jsonl", "--runs", runs, "--timeout", "99"],
                ["grade", manifest_path, "--runs", runs, "--allow-scripts"],
                [
                    "judge", manifest_path, "--runs", runs, "--judge-backend", "claude", "--judge-model", "j1",
                    "--claude-bin", claude, "--judge-runs", "4", "--out", f"{runs}-judge.jsonl",
                ],
                [
                    "benchmark", manifest_path, "--runs", runs, "--split", "tune", "--allow-scripts",
                    "--judge-results", f"{runs}-judge.jsonl", "--out", f"{runs}-benchmark.json",
                ],
                ["report", "--benchmark", f"{runs}-benchmark.json", "--format", "github"],
            ]

        self.assertEqual(
            self.fake.arguments(),
            [
                ["audit-manifest", manifest_path, "--fail-on-blockers", "--strict-judge"],
                ["prepare", manifest_path, "--split", "tune", "--runs-per-variant", "2", "--out", "run output/tasks.jsonl"],
                *agent("claude", ["--model", "m1", "--claude-bin", claude]),
                *agent("codex", ["--model", "m2", "--codex-cmd", "my codex --flag"]),
            ],
        )
        self.assertEqual({call["command"] for call in self.fake.calls()}, {"skill-benchmark"})

    def test_a_failing_stage_stops_the_pipeline_with_its_exit_code(self) -> None:
        result = self.paid("run", "skills/example", "--out", "o", FAKE_HARNESS_EXIT="7", FAKE_HARNESS_FAIL_STAGE="grade")
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual([stage[0] for stage in self.fake.arguments()], ["audit-manifest", "prepare", "run-agent", "grade"])

    def test_a_failed_readiness_audit_leaves_an_explicit_output_uncreated(self) -> None:
        result = self.paid("run", "skills/example", "--out", "o/nested", FAKE_HARNESS_EXIT="2", FAKE_HARNESS_FAIL_STAGE="audit-manifest")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual([stage[0] for stage in self.fake.arguments()], ["audit-manifest"])
        self.assertFalse((self.checkout / "o").exists())

    def test_one_agent_runs_only_its_stages(self) -> None:
        result = self.paid("run", "skills/example", "--out", "o", "--agent", "claude")
        self.assertEqual(result.returncode, 0, result.stderr)
        stages = self.fake.arguments()
        self.assertEqual([stage[0] for stage in stages], ["audit-manifest", "prepare", "run-agent", "grade", "judge", "benchmark", "report"])
        self.assertEqual(stages[2][:3], ["run-agent", "--agent", "claude"])

    def test_default_outputs_sit_beside_the_checkout_in_both_layouts(self) -> None:
        write_skill(self.checkout / "skills" / "a skill")
        for evals in ((), ("--evals-dir", "evals")):
            for command in ("trigger", "run"):
                with self.subTest(evals=evals, command=command):
                    result = self.paid(command, "skills/a skill", *evals)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    output = self.output(command)
                    self.assertEqual(output.parent, self.runs_root / "a skill")
                    self.assertRegex(output.name, rf"^{command}-\d{{8}}-\d{{6}}-")
                    self.assertTrue(output.is_dir())
                    self.fake.log.unlink()

    def test_explicit_outputs_reach_the_harness_unchanged(self) -> None:
        for out in ("output with spaces", str(self.root / "absolute output")):
            for command, product in (("trigger", "trigger-matrix.json"), ("run", "tasks.jsonl")):
                with self.subTest(out=out, command=command):
                    result = self.paid(command, "skills/example", "--out", out)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    stage = self.fake.arguments()[0 if command == "trigger" else 1]
                    self.assertEqual(stage[stage.index("--out") + 1], f"{out}/{product}")
                    self.assertTrue((self.checkout / out).is_dir())
                    self.fake.log.unlink()

    def test_an_explicit_output_still_needs_a_selected_package(self) -> None:
        missing = rf"\[Errno 2\] No such file or directory: '(?:{re.escape(str(self.checkout))}/)?example'"
        for selection, error in (("example", missing), ("skills", "selected skill is not a package: skills")):
            for out in ("skills/example/runs", "elsewhere"):
                for command in ("trigger", "run"):
                    with self.subTest(selection=selection, out=out, command=command):
                        result = self.paid(command, selection, "--evals-dir", "evals", "--out", out)
                        self.assertEqual(result.returncode, 1, result.stderr)
                        self.assertRegex(result.stderr, rf"^skill-ci: output allocation failed: {error}\n$")
        self.assertEqual(self.fake.calls(), [])
        self.assertEqual(list(self.package.iterdir()), [self.package / "SKILL.md"])
        self.assertFalse((self.checkout / "elsewhere").exists())

    def test_a_symlink_loop_in_the_output_or_the_selection_fails_without_a_traceback(self) -> None:
        loop = self.checkout / "links" / "loop"
        loop.parent.mkdir()
        loop.symlink_to("loop")
        for selection, out in (("skills/example", "links/loop/sub"), ("links/loop", "elsewhere")):
            for command in ("trigger", "run"):
                with self.subTest(selection=selection, out=out, command=command):
                    result = self.paid(command, selection, "--out", out)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertRegex(result.stderr, rf"^skill-ci: output allocation failed: .*'({re.escape(str(self.checkout))}/)?links/loop(/sub)?'\n$")
        self.assertEqual(self.fake.calls(), [])
        self.assertFalse((self.checkout / "elsewhere").exists())

    def test_a_default_output_that_resolves_into_the_package_fails_before_any_harness_call(self) -> None:
        self.runs_root.symlink_to(self.package, target_is_directory=True)
        for command in ("trigger", "run"):
            with self.subTest(command=command):
                result = self.paid(command, "skills/example")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("pass --out with a directory outside the package", result.stderr)
        self.assertEqual(self.fake.calls(), [])
        self.assertEqual(list(self.package.iterdir()), [self.package / "SKILL.md"])

    def test_an_explicit_output_that_overlaps_the_skill_fails_before_any_harness_call(self) -> None:
        for out in ("skills/example/runs", "skills/example", "skills", "."):
            for command in ("trigger", "run"):
                with self.subTest(out=out, command=command):
                    result = self.paid(command, "skills/example", "--out", out)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn("pass --out with a directory outside the package", result.stderr)
        self.assertEqual(self.fake.calls(), [])
        self.assertFalse((self.package / "runs").exists())

    def test_an_explicit_output_reached_through_a_symlink_is_judged_by_its_target(self) -> None:
        links = self.root / "links"
        links.mkdir()
        (links / "package").symlink_to(self.package, target_is_directory=True)
        (links / "skills").symlink_to(self.package.parent, target_is_directory=True)
        for out in (links / "package", links / "package" / "runs", links / "skills"):
            for command in ("trigger", "run"):
                with self.subTest(out=out, command=command):
                    result = self.paid(command, "skills/example", "--out", str(out))
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn(f"skill-ci: output allocation failed: {out} overlaps the selected skill package", result.stderr)
        self.assertEqual(self.fake.calls(), [])
        self.assertEqual(list(self.package.iterdir()), [self.package / "SKILL.md"])

    def test_an_explicit_output_that_leaves_the_package_through_dot_dot_reaches_the_harness(self) -> None:
        links = self.root / "links"
        links.mkdir()
        (links / "package").symlink_to(self.package, target_is_directory=True)
        for out, landed in (
            ("skills/example/../example-runs", self.checkout / "skills" / "example-runs"),
            (str(links / "package" / ".." / "beside"), self.checkout / "skills" / "beside"),
        ):
            with self.subTest(out=out):
                result = self.paid("trigger", "skills/example", "--out", out)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.fake.arguments()[0][-1], f"{out}/trigger-matrix.json")
                self.assertTrue(landed.is_dir())
                self.fake.log.unlink()
        self.assertEqual(list(self.package.iterdir()), [self.package / "SKILL.md"])

    def test_an_output_spelled_in_another_case_still_overlaps_on_a_case_insensitive_filesystem(self) -> None:
        if not (self.checkout / "SKILLS").exists():
            self.skipTest("the filesystem is case-sensitive")
        for out in ("SKILLS/EXAMPLE/runs", "SKILLS/EXAMPLE", "SKILLS"):
            for command in ("trigger", "run"):
                with self.subTest(out=out, command=command):
                    result = self.paid(command, "skills/example", "--out", out)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn(f"skill-ci: output allocation failed: {out} overlaps the selected skill package", result.stderr)
        installed = write_skill(self.runs_root / "example")
        for command in ("trigger", "run"):
            with self.subTest(default=True, command=command):
                result = self.paid(command, str(self.root / "CHECKOUT.EVAL-RUNS" / "example"))
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("default output overlaps the selected skill package", result.stderr)
        self.assertEqual(self.fake.calls(), [])
        self.assertEqual(list(self.package.iterdir()), [self.package / "SKILL.md"])
        self.assertEqual(list(installed.iterdir()), [installed / "SKILL.md"])

    def test_root_and_absolute_skill_selections(self) -> None:
        write_skill(self.checkout)
        for selection, manifest_path, name in (
            (".", "evals/shared-benchmark.json", "checkout"),
            (str(self.package), f"{self.package}/evals/shared-benchmark.json", "example"),
        ):
            for command in ("trigger", "run"):
                with self.subTest(selection=selection, command=command):
                    result = self.paid(command, selection)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    first = self.fake.arguments()[0]
                    self.assertEqual(first[0] if command == "trigger" else first[1], manifest_path)
                    self.assertEqual(self.output(command).parent, self.runs_root / name)
                    self.fake.log.unlink()

    def test_a_nested_caller_writes_beside_the_repository_root(self) -> None:
        nested = self.checkout / "nested" / "caller"
        nested.mkdir(parents=True)
        result = self.paid("trigger", "../../skills/example", cwd=nested)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.output("trigger").parent, self.runs_root / "example")

    def test_a_launcher_without_its_exec_bit_fails_before_any_output_or_harness_call(self) -> None:
        launcher = self.launchers / "codex-project-only"
        launcher.chmod(0o644)
        result = self.paid("trigger", "skills/example")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(f"skill-ci: launcher {launcher} is not an executable file", result.stderr)
        self.assertEqual(self.fake.calls(), [])
        self.assertFalse(self.runs_root.exists())
        claude_only = self.paid("run", "skills/example", "--agent", "claude", "--out", "o")
        self.assertEqual(claude_only.returncode, 0, claude_only.stderr)


if __name__ == "__main__":
    unittest.main()
