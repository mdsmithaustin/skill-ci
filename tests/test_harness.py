from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from support import ENVIRONMENT, REPOSITORY, FakeHarness, git, manifest, skill_ci, write, write_skill


class HarnessCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="skill-ci-harness-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.fake = FakeHarness(self.root)
        self.marker = self.root / "hostile-ran"
        self.hostile = write(self.root / "hostile bin" / "skill-benchmark", f"#!/bin/sh\nprintf hostile > '{self.marker}'\n")
        self.hostile.chmod(0o755)
        self.hostile_path = os.pathsep.join((str(self.hostile.parent), os.environ["PATH"]))

    def test_refused_commands_exit_2_and_run_nothing(self) -> None:
        for arguments in (("harness", "other", "--help"), ("harness",)):
            with self.subTest(arguments=arguments):
                result = self.fake.run(*arguments, cwd=self.root)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("skill-benchmark or skill-trigger-matrix", result.stderr)
                self.assertEqual(self.fake.calls(), [])

    def test_lookup_uses_the_environment_scripts_never_path(self) -> None:
        result = self.fake.run(
            "harness",
            "skill-benchmark",
            "validate",
            "a path/with spaces",
            "--help",
            cwd=self.root,
            path=self.hostile_path,
            FAKE_HARNESS_EXIT="7",
            FAKE_HARNESS_INHERITED="host-login",
        )
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(
            self.fake.calls(),
            [
                {
                    "command": "skill-benchmark",
                    "arguments": ["validate", "a path/with spaces", "--help"],
                    "cwd": str(self.root),
                    "inherited": "host-login",
                }
            ],
        )
        self.assertFalse(self.marker.exists())

    def test_missing_script_exits_127_without_falling_back_to_path(self) -> None:
        missing = self.fake.scripts / "skill-trigger-matrix"
        missing.unlink()
        result = self.fake.run("harness", "skill-trigger-matrix", "--help", cwd=self.root, path=self.hostile_path)
        self.assertEqual(result.returncode, 127, result.stderr)
        self.assertIn(f"skill-ci: {missing} does not exist", result.stderr)
        self.assertEqual(self.fake.calls(), [])
        self.assertFalse(self.marker.exists())

    def test_a_different_harness_on_path_draws_one_warning(self) -> None:
        write_skill(self.root / "skills" / "example")
        warning = f"skill-ci: warning: {self.hostile} on PATH is not skill-ci's harness"
        shadowed = self.fake.run("harness", "skill-benchmark", "--help", cwd=self.root, path=self.hostile_path)
        self.assertEqual(shadowed.stderr.count("skill-ci: warning:"), 1, shadowed.stderr)
        self.assertIn(warning, shadowed.stderr)
        validate = self.fake.run("validate", cwd=self.root, path=self.hostile_path)
        self.assertIn(warning, validate.stderr)
        lint = self.fake.run("lint", cwd=self.root, path=self.hostile_path)
        self.assertEqual(lint.returncode, 0, lint.stdout + lint.stderr)
        self.assertNotIn("warning", lint.stderr)
        own = self.fake.run("harness", "skill-benchmark", "--help", cwd=self.root)
        self.assertNotIn("warning", own.stderr)

    def test_a_project_that_requires_the_harness_draws_a_warning(self) -> None:
        pyproject = self.root / "pyproject.toml"
        for text, expected in (
            ('[project]\nname = "consumer"\ndependencies = ["Skill.Eval_Harness>=1"]\n', "'Skill.Eval_Harness>=1'"),
            (
                '[project]\nname = "consumer"\n[project.optional-dependencies]\nevals = ["skill-eval-harness-ext[x] @ git+https://h/x"]\n',
                "'skill-eval-harness-ext[x] @ git+https://h/x'",
            ),
            ('[dependency-groups]\ndev = [{include-group = "lint"}, "skill_eval_harness"]\nlint = []\n', "'skill_eval_harness'"),
            ('[project]\nname = "consumer"\ndependencies = ["skill-eval-harness-extras"]\n', None),
            ('[project]\nname = "skill_ci"\ndependencies = ["skill-eval-harness-ext"]\n', None),
            ("[project\n", None),
        ):
            with self.subTest(text=text):
                pyproject.write_text(text)
                result = self.fake.run("harness", "skill-benchmark", "--help", cwd=self.root)
                self.assertEqual(result.returncode, 0, result.stderr)
                if expected is None:
                    self.assertNotIn("warning", result.stderr)
                else:
                    self.assertIn(f"skill-ci: warning: {pyproject} requires {expected}", result.stderr)


    def test_an_in_process_harness_exit_with_a_message_prints_it_and_fails(self) -> None:
        write_skill(self.root / "skills" / "a")
        write(self.root / "evals/a/shared-benchmark.json", "{}")
        write(self.fake.purelib / "skill_benchmark.py", 'raise SystemExit("the harness refused this manifest")\n')
        result = self.fake.run("validate", "--evals-dir", "evals", cwd=self.root)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "the harness refused this manifest\n")
        self.assertEqual(result.stdout, "manifests checked: 1\n")

    def test_an_interrupt_inside_the_harness_stops_the_command_with_exit_130(self) -> None:
        write_skill(self.root / "skills" / "a")
        write(self.root / "evals/a/shared-benchmark.json", "{}")
        write(self.fake.purelib / "skill_benchmark.py", "raise KeyboardInterrupt\n")
        git("init", "-q", cwd=self.root)
        git("add", "skills", "evals", cwd=self.root)
        for command, stderr in (
            ("validate", []),
            ("check", ["frontmatter: 1 skills, 0 errors", "content: 1 files, 0 findings"]),
        ):
            with self.subTest(command=command):
                result = self.fake.run(command, "--evals-dir", "evals", cwd=self.root)
                self.assertEqual(result.returncode, 130, result.stdout + result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertEqual(result.stderr.splitlines(), stderr)


class HarnessIsolationTests(unittest.TestCase):
    def test_planted_harness_module_never_loads(self) -> None:
        with tempfile.TemporaryDirectory(prefix="skill-ci-isolation-") as temporary:
            root = Path(temporary).resolve()
            marker = root / "planted-ran"
            planted = f"open({str(marker)!r}, 'w').close()\n"
            write(root / "skill_benchmark.py", planted)
            write(root / "pythonpath" / "skill_benchmark.py", planted)
            environment = {**ENVIRONMENT, "PYTHONPATH": str(root / "pythonpath")}
            control = subprocess.run([sys.executable, "-c", "import skill_benchmark"], cwd=root, env=environment, check=False)
            self.assertEqual(control.returncode, 0)
            self.assertTrue(marker.exists(), "the planted module loads without isolation")
            marker.unlink()
            result = skill_ci("harness", "skill-benchmark", "--help", cwd=root, env=environment)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(result.stdout.startswith("usage: skill-benchmark"), result.stdout[:200])
            self.assertFalse(marker.exists())

    def test_a_module_planted_in_the_working_directory_never_loads_in_process(self) -> None:
        with tempfile.TemporaryDirectory(prefix="skill-ci-isolation-") as temporary:
            root = Path(temporary).resolve()
            marker = root / "planted-ran"
            write(root / "skill_benchmark.py", f"open({str(marker)!r}, 'w').close()\n")
            write_skill(root / "skills" / "a")
            write(root / "evals/a/shared-benchmark.json", manifest("a", ["skills/a/SKILL.md"]))
            environment = {key: value for key, value in ENVIRONMENT.items() if key != "PYTHONPATH"}
            result = skill_ci("validate", "--evals-dir", "evals", cwd=root, env=environment)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.splitlines(), ["OK: a — 0 cases, 0 ablations", "manifests checked: 1"])
            self.assertFalse(marker.exists())


class HarnessPinTests(unittest.TestCase):
    def test_the_harness_is_pinned_to_a_full_commit_of_the_fork(self) -> None:
        dependencies = tomllib.loads((REPOSITORY / "pyproject.toml").read_text())["project"]["dependencies"]
        [harness] = [dependency for dependency in dependencies if dependency.startswith("skill-eval-harness")]
        self.assertRegex(
            harness, r"^skill-eval-harness-ext @ git\+https://github\.com/mdsmithaustin/skill-eval-harness\.git@[0-9a-f]{40}$"
        )


if __name__ == "__main__":
    unittest.main()
