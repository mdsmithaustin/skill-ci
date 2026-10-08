from __future__ import annotations

import contextlib
import io
import json
import os
import re
import signal
import subprocess
import tempfile
import tomllib
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

import yaml
from support import ENVIRONMENT, REPOSITORY, fake_git_install, skill_ci, write, write_skill

from skill_ci import children, config, init

ISOLATED_GIT = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "skill-ci tests",
    "GIT_AUTHOR_EMAIL": "tests@example.com",
    "GIT_COMMITTER_NAME": "skill-ci tests",
    "GIT_COMMITTER_EMAIL": "tests@example.com",
}
FAKE_LEFTHOOK = """\
#!/bin/sh
echo "$@" >> "$FAKE_LEFTHOOK_LOG"
if [ -n "$FAKE_LEFTHOOK_FAILS" ]; then echo "lefthook: the configuration is invalid" >&2; exit 1; fi
"""
LEFTHOOK_BEFORE = """\
# Local hooks.
pre-commit:
  parallel: true
  commands:
    lint:
      run: make lint
      glob: "*.py"

    # Keep this last.
    format:
      run: make format
post-checkout:
  commands:
    deps:
      run: make deps
"""
LEFTHOOK_AFTER = """\
# Local hooks.
pre-commit:
  parallel: true
  commands:
    lint:
      run: make lint
      glob: "*.py"

    # Keep this last.
    format:
      run: make format
    skill-ci-check-fast:
      run: skill-ci check --fast
post-checkout:
  commands:
    deps:
      run: make deps

pre-push:
  commands:
    skill-ci-check:
      run: skill-ci check
"""
SKILL_CHECK_TASKS = {f"skill-{command}": f"skill-ci {command}" for command in ("check", "lint", "package", "coverage", "validate", "audit", "trigger", "run")}


@dataclass(frozen=True)
class Result:
    status: int
    stdout: str
    stderr: str

    @property
    def lines(self) -> list[str]:
        return self.stdout.splitlines()


class InitTestCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="skill-ci-init-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / "source.git"
        self.work = self.root / "work"
        bin_directory = self.root / "bin"
        self.lefthook_log = self.root / "lefthook.log"
        write(bin_directory / "lefthook", FAKE_LEFTHOOK).chmod(0o755)
        self.environment = {
            **ENVIRONMENT,
            **ISOLATED_GIT,
            "GIT_CEILING_DIRECTORIES": str(self.root),
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": f"url.{self.source}.insteadOf",
            "GIT_CONFIG_VALUE_0": config.DEFAULT_SOURCE,
            "HOME": str(self.root / "home"),
            "XDG_CACHE_HOME": str(self.root / "cache"),
            "FAKE_LEFTHOOK_LOG": str(self.lefthook_log),
            "PATH": f"{bin_directory}{os.pathsep}{os.environ['PATH']}",
        }
        self.git("init", "-q", "--bare", "--initial-branch=main", str(self.source), cwd=self.root)
        self.git("clone", "-q", str(self.source), str(self.work), cwd=self.root)
        self.commits = {name: self.commit(name) for name in ("v0.9.0", "v1.1.0")}
        self.git("tag", "v0.9.0", self.commits["v0.9.0"], cwd=self.work)
        self.git("tag", "-a", "-m", "annotated", "v1.1.0", self.commits["v1.1.0"], cwd=self.work)
        self.git("tag", "release-candidate", self.commits["v1.1.0"], cwd=self.work)
        self.git("push", "-q", "origin", "main", "--tags", cwd=self.work)
        self.repository = self.root / "repository"
        write_skill(self.repository / "skills" / "alpha")
        write_skill(self.repository / "skills" / "beta")
        self.git("init", "-q", cwd=self.repository)

    def git(self, *arguments: str, cwd: Path | None = None) -> str:
        done = subprocess.run(["git", *arguments], cwd=cwd or self.repository, env=self.environment, capture_output=True, text=True, check=True)
        return done.stdout.strip()

    def commit(self, message: str) -> str:
        self.git("commit", "-q", "--allow-empty", "-m", message, cwd=self.work)
        return self.git("rev-parse", "HEAD", cwd=self.work)

    def init(self, *, skills_dir: str | None = None, evals_dir: str | None = None, **variables: str) -> Result:
        found = self.repository / config.FILE_NAME
        loaded = config.read(found) if found.exists() else None
        settings = tomllib.loads(found.read_text()) if found.exists() else {}
        skills_dir = skills_dir or settings.get("skills_dir")
        evals_dir = evals_dir or settings.get("evals_dir")
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            mock.patch.dict(os.environ, {**self.environment, **variables}, clear=True),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            status = init.run(
                self.repository,
                skills_dir=None if skills_dir is None else Path(skills_dir),
                evals_dir=None if evals_dir is None else Path(evals_dir),
                loaded=loaded,
            )
        return Result(status, stdout.getvalue(), stderr.getvalue())

    def cli(self, *arguments: str, **variables: str) -> subprocess.CompletedProcess[str]:
        return skill_ci(*arguments, cwd=self.repository, env={**self.environment, **variables})

    def tree(self) -> dict[str, bytes]:
        return {
            path.relative_to(self.repository).as_posix(): path.read_bytes()
            for path in sorted(self.repository.rglob("*"))
            if path.is_file() and ".git" not in path.relative_to(self.repository).parts
        }

    def written(self) -> set[str]:
        return set(self.tree()) - {"skills/alpha/SKILL.md", "skills/beta/SKILL.md"}


class BareRepositoryTests(InitTestCase):
    def test_a_bare_repository_gets_the_pin_the_workflow_the_manifests_and_the_ignores(self) -> None:
        result = self.init()
        self.assertEqual((result.status, result.stderr), (0, ""))
        self.assertEqual(
            result.lines,
            [
                "wrote .skill-ci.toml (version v1.1.0)",
                "wrote .github/workflows/skill-checks.yml",
                "wrote evals/alpha/shared-benchmark.json",
                "wrote evals/beta/shared-benchmark.json",
                "wrote .gitignore (added eval-runs/, evals/runs/)",
            ],
        )
        self.assertEqual(
            self.written(),
            {".skill-ci.toml", ".github/workflows/skill-checks.yml", "evals/alpha/shared-benchmark.json", "evals/beta/shared-benchmark.json", ".gitignore"},
        )
        self.assertEqual(
            (self.repository / ".skill-ci.toml").read_text(),
            "# The skill-ci release this repository runs, here and in CI. skill-ci update moves it to the newest tag.\n"
            'version = "v1.1.0"\nskills_dir = "skills"\nevals_dir = "evals"\n',
        )
        self.assertEqual((self.repository / ".gitignore").read_text(), "eval-runs/\nevals/runs/\n")
        manifest = json.loads((self.repository / "evals/alpha/shared-benchmark.json").read_text())
        self.assertEqual((manifest["skill_name"], manifest["skill_paths"], manifest["cases"]), ("alpha", ["skills/alpha/SKILL.md"], []))

    def test_the_pin_is_the_newest_release_tag_and_ignores_other_tags(self) -> None:
        self.commit("v1.2.0")
        self.git("tag", "-a", "-m", "annotated", "v1.2.0", cwd=self.work)
        self.git("tag", "v10.0.0-rc1", cwd=self.work)
        self.git("push", "-q", "origin", "main", "--tags", cwd=self.work)
        self.assertEqual(self.init().status, 0)
        self.assertEqual(config.read(self.repository / config.FILE_NAME).pin.version, config.Tag(1, 2, 0))

    def test_a_source_with_no_release_tag_exits_2_and_writes_nothing(self) -> None:
        for tag in ("v0.9.0", "v1.1.0"):
            self.git("push", "-q", "origin", f":refs/tags/{tag}", cwd=self.work)
        self.git("tag", "-d", "release-candidate", cwd=self.work)
        before = self.tree()
        result = self.init()
        self.assertEqual((result.status, result.stdout), (2, ""))
        self.assertEqual(
            result.stderr.splitlines(),
            [
                f"skill-ci: {config.DEFAULT_SOURCE} has no release tag yet, and init pins an exact tag, so it wrote nothing",
                'skill-ci: to follow the branch head until the first tag exists, write .skill-ci.toml with version = "main" and run skill-ci init again',
            ],
        )
        self.assertEqual(self.tree(), before)

    def test_an_unreachable_source_exits_2_and_writes_nothing(self) -> None:
        self.source.rename(self.root / "moved.git")
        before = self.tree()
        result = self.init()
        self.assertEqual((result.status, result.stdout), (2, ""))
        self.assertIn(f"skill-ci: cannot reach {config.DEFAULT_SOURCE} (", result.stderr)
        self.assertIn("init needs the network to find the newest release tag", result.stderr)
        self.assertEqual(self.tree(), before)

    def test_a_hand_written_main_pin_lets_init_finish_without_a_tag(self) -> None:
        for tag in ("v0.9.0", "v1.1.0"):
            self.git("push", "-q", "origin", f":refs/tags/{tag}", cwd=self.work)
        pinned = write(self.repository / config.FILE_NAME, 'version = "main"\nskills_dir = "skills"\nevals_dir = "evals"\n')
        text = pinned.read_text()
        result = self.init()
        self.assertEqual((result.status, result.stderr), (0, ""))
        self.assertEqual(result.lines[0], "kept .skill-ci.toml")
        self.assertEqual(pinned.read_text(), text)
        self.assertIn("evals/alpha/shared-benchmark.json", self.written())

    def test_init_refuses_a_directory_that_is_not_the_repository_root(self) -> None:
        nested = write_skill(self.repository / "packages" / "one" / "skills" / "gamma").parents[1]
        self.repository = nested
        result = self.init()
        self.assertEqual((result.status, result.stdout), (2, ""))
        self.assertEqual(result.stderr, f"skill-ci: run init at the repository root, {self.root / 'repository'}\n")

    def test_init_refuses_a_directory_in_no_repository(self) -> None:
        outside = self.root / "plain"
        write_skill(outside / "skills" / "alpha")
        self.repository = outside
        result = self.init()
        self.assertEqual((result.status, result.stderr), (2, "skill-ci: init runs inside a git repository, and this directory is in none\n"))

    def test_init_stops_when_the_skills_directory_holds_no_skill(self) -> None:
        for skill in ("alpha", "beta"):
            (self.repository / "skills" / skill / "SKILL.md").unlink()
        before = self.tree()
        result = self.init()
        self.assertEqual(result.status, 2)
        self.assertIn("skills holds no skill", result.stderr)
        self.assertIn("pass --skills-dir to name another", result.stderr)
        self.assertEqual(self.tree(), before)

    def test_a_skills_directory_outside_the_repository_is_refused(self) -> None:
        result = self.init(skills_dir="../elsewhere")
        self.assertEqual((result.status, result.stderr), (2, "skill-ci: the skills directory ../elsewhere is outside the repository\n"))

    def test_an_evals_directory_not_named_evals_is_refused_before_anything_is_written(self) -> None:
        before = self.tree()
        result = self.init(evals_dir="manifests")
        self.assertEqual((result.status, result.stdout), (2, ""))
        self.assertIn("an external evals directory must be named 'evals'", result.stderr)
        self.assertEqual(self.tree(), before)

    def test_a_path_with_a_control_character_is_refused_before_it_is_written_to_the_pin(self) -> None:
        write_skill(self.repository / "skills\u202e" / "gamma")
        result = self.init(skills_dir="skills\u202e")
        self.assertEqual(result.status, 2)
        self.assertIn("contains a control character", result.stderr)
        self.assertFalse((self.repository / config.FILE_NAME).exists())


class LayoutTests(InitTestCase):
    def test_a_skills_directory_flag_is_written_to_the_pin(self) -> None:
        for skill in ("alpha", "beta"):
            (self.repository / "skills" / skill).rename(self.repository / skill)
        (self.repository / "skills").rmdir()
        write_skill(self.repository / "agent skills" / "gamma")
        result = self.cli("init", "--skills-dir", "agent skills")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(tomllib.loads((self.repository / config.FILE_NAME).read_text())["skills_dir"], "agent skills")
        self.assertIn("evals/gamma/shared-benchmark.json", self.written())
        self.assertEqual(json.loads((self.repository / "evals/gamma/shared-benchmark.json").read_text())["skill_paths"], ["agent skills/gamma/SKILL.md"])

    def test_manifests_that_sit_beside_their_skills_stay_there(self) -> None:
        kept = write(self.repository / "skills/alpha/evals/shared-benchmark.json", '{"kept": true}\n')
        result = self.init()
        self.assertEqual(result.status, 0, result.stderr)
        self.assertEqual(tomllib.loads((self.repository / config.FILE_NAME).read_text()), {"version": "v1.1.0", "skills_dir": "skills"})
        self.assertEqual(kept.read_text(), '{"kept": true}\n')
        self.assertEqual(
            result.lines[2:4], ["wrote skills/beta/evals/shared-benchmark.json", "kept 1 existing manifest"]
        )
        self.assertFalse((self.repository / "evals").exists())

    def test_manifests_in_the_evals_directory_win_over_manifests_beside_skills(self) -> None:
        write(self.repository / "skills/alpha/evals/shared-benchmark.json", "{}\n")
        write(self.repository / "evals/beta/shared-benchmark.json", "{}\n")
        self.assertEqual(self.init().status, 0)
        self.assertEqual(tomllib.loads((self.repository / config.FILE_NAME).read_text())["evals_dir"], "evals")

    def test_an_existing_manifest_stays_byte_identical(self) -> None:
        kept = write(self.repository / "evals/alpha/shared-benchmark.json", '{"cases": [{"id": "mine"}],\n "kept": true}')
        before = kept.read_bytes()
        result = self.init()
        self.assertEqual(result.status, 0, result.stderr)
        self.assertEqual(kept.read_bytes(), before)
        self.assertIn("kept 1 existing manifest", result.lines)
        self.assertIn("wrote evals/beta/shared-benchmark.json", result.lines)

    def test_a_skill_that_cannot_be_read_does_not_stop_the_others(self) -> None:
        (self.repository / "skills/alpha/SKILL.md").write_text("no frontmatter here\n")
        result = self.init()
        self.assertEqual(result.status, 1)
        self.assertIn("wrote evals/beta/shared-benchmark.json", result.lines)
        self.assertIn("to do: write the manifest for skills/alpha", result.stdout)
        self.assertIn("skills/alpha/SKILL.md: missing frontmatter", result.stdout)
        self.assertFalse((self.repository / "evals/alpha").exists())

    def test_what_init_writes_passes_check(self) -> None:
        self.assertEqual(self.init().status, 0)
        self.git("add", "-A")
        commit = self.commits["v1.1.0"]
        running = {"PYTHONPATH": str(fake_git_install(self.root / "installed", commit))}
        result = self.cli("check", **running)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr.splitlines()[0], f"skill-ci v1.1.0 ({commit})")
        self.assertIn("manifests checked: 2", result.stdout)


class SecondRunTests(InitTestCase):
    def test_a_second_run_changes_nothing(self) -> None:
        write(self.repository / "lefthook.yml", LEFTHOOK_BEFORE)
        write(self.repository / "mise.toml", '[tools]\nuv = "0.12.7"\n')
        write(self.repository / ".no-mistakes.yaml", "commands:\n  lint: make lint\n")
        write(self.repository / ".gitignore", "node_modules/\n")
        first = self.init()
        self.assertEqual(first.status, 0, first.stdout + first.stderr)
        snapshot = self.tree()
        again = self.init()
        self.assertEqual((again.status, again.stderr), (0, ""))
        self.assertEqual(self.tree(), snapshot)
        self.assertNotRegex(again.stdout, r"(?m)^(wrote|updated)")
        self.assertEqual(again.lines[-1], "nothing to change")

    def test_a_second_run_through_the_command_keeps_the_pin_and_the_settings(self) -> None:
        self.assertEqual(self.cli("init").returncode, 0)
        snapshot = self.tree()
        commit = self.commits["v1.1.0"]
        running = {"PYTHONPATH": str(fake_git_install(self.root / "installed", commit))}
        again = self.cli("init", **running)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(again.stderr, f"skill-ci v1.1.0 ({commit})\n")
        self.assertEqual(again.stdout.splitlines()[0], "kept .skill-ci.toml")
        self.assertEqual(self.tree(), snapshot)


class WorkflowTests(InitTestCase):
    def workflow(self) -> dict[str, object]:
        return yaml.safe_load((self.repository / ".github/workflows/skill-checks.yml").read_text())

    def test_the_workflow_installs_uv_once_and_runs_check_at_the_pinned_version(self) -> None:
        self.init()
        text = (self.repository / ".github/workflows/skill-checks.yml").read_text()
        self.assertEqual(text.count("pip install uv==0.12.7"), 1)
        job = self.workflow()["jobs"]["skills"]
        self.assertEqual(job["env"], {"SKILL_CI_SOURCE": config.DEFAULT_SOURCE})
        self.assertEqual(
            [step.get("run") for step in job["steps"] if "run" in step],
            ["pip install uv==0.12.7", 'uv tool run --from "git+$SKILL_CI_SOURCE" skill-ci check'],
        )
        self.assertNotIn("v1.1.0", text)
        self.assertNotIn(self.commits["v1.1.0"], text)

    def test_the_workflow_names_the_source_the_pin_names(self) -> None:
        write(self.repository / config.FILE_NAME, f'version = "v1.1.0"\nsource = "{self.source}"\n')
        self.assertEqual(self.init().status, 0)
        self.assertEqual(self.workflow()["jobs"]["skills"]["env"], {"SKILL_CI_SOURCE": self.source.as_uri()})

    def test_a_source_with_shell_characters_stays_out_of_the_shell_text(self) -> None:
        source = 'ssh://git@example.com/a"b;c$d.git'
        write(self.repository / config.FILE_NAME, f"version = \"v1.1.0\"\nsource = '{source}'\n")
        self.assertEqual(self.init().status, 0)
        job = self.workflow()["jobs"]["skills"]
        self.assertEqual(job["env"], {"SKILL_CI_SOURCE": source})
        self.assertNotIn(source, str(job["steps"]))

    def test_an_existing_workflow_is_kept(self) -> None:
        path = write(self.repository / ".github/workflows/skill-checks.yml", "name: mine\njobs:\n  skills:\n    steps:\n      - run: skill-ci check --fast && skill-ci check\n")
        before = path.read_bytes()
        result = self.init()
        self.assertIn("kept .github/workflows/skill-checks.yml", result.lines)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse([line for line in result.lines if line.startswith("note:")])

    def test_an_existing_workflow_that_does_not_run_check_draws_a_note(self) -> None:
        write(self.repository / ".github/workflows/skill-checks.yml", "name: old\njobs:\n  skills:\n    uses: example/skill-ci/.github/workflows/skill-checks.yml@abc\n")
        result = self.init()
        self.assertEqual(result.status, 0)
        self.assertIn("note: .github/workflows/skill-checks.yml does not run `skill-ci check`; add a step that does, or replace the file with the template in the README", result.lines)


class LefthookTests(InitTestCase):
    def test_a_lefthook_file_gets_both_entries_and_is_validated(self) -> None:
        path = write(self.repository / "lefthook.yml", LEFTHOOK_BEFORE)
        result = self.init()
        self.assertEqual(result.status, 0, result.stdout + result.stderr)
        self.assertEqual(path.read_text(), LEFTHOOK_AFTER)
        self.assertIn("updated lefthook.yml (added skill-ci check --fast under pre-commit; skill-ci check under pre-push)", result.lines)
        self.assertIn("note: lefthook install activates the hooks in this clone", result.lines)
        self.assertEqual(self.lefthook_log.read_text(), "validate\n")

    def test_a_repository_without_lefthook_is_not_given_a_file(self) -> None:
        self.init()
        self.assertFalse((self.repository / "lefthook.yml").exists())
        self.assertFalse(self.lefthook_log.exists())

    def test_a_file_lefthook_rejects_is_put_back_and_reported(self) -> None:
        path = write(self.repository / "lefthook.yml", LEFTHOOK_BEFORE)
        result = self.init(FAKE_LEFTHOOK_FAILS="1")
        self.assertEqual(result.status, 1)
        self.assertEqual(path.read_text(), LEFTHOOK_BEFORE)
        self.assertIn("to do: add skill-ci to lefthook.yml", result.stdout)
        self.assertIn("lefthook validate failed after the change, so the file is as it was:", result.stdout)
        self.assertIn("lefthook: the configuration is invalid", result.stdout)

    def test_a_file_that_already_runs_check_is_kept(self) -> None:
        text = "pre-commit:\n  commands:\n    mine:\n      run: uv run skill-ci check --fast\npre-push:\n  jobs:\n    - run: skill-ci check\n"
        path = write(self.repository / "lefthook.yml", text)
        result = self.init()
        self.assertEqual(path.read_text(), text)
        self.assertIn("kept lefthook.yml pre-commit (already runs skill-ci check)", result.lines)
        self.assertIn("kept lefthook.yml pre-push (already runs skill-ci check)", result.lines)
        self.assertFalse(self.lefthook_log.exists())

    def test_a_hook_in_a_shape_init_cannot_edit_safely_becomes_a_to_do(self) -> None:
        text = "pre-commit:\n  jobs:\n    - run: make lint\n"
        path = write(self.repository / "lefthook.yml", text)
        result = self.init()
        self.assertEqual(result.status, 1)
        self.assertIn("to do: add skill-ci check --fast under pre-commit in lefthook.yml", result.stdout)
        self.assertIn("    pre-commit:\n      commands:\n        skill-ci-check-fast:\n          run: skill-ci check --fast", result.stdout)
        self.assertIn("pre-push:\n  commands:\n    skill-ci-check:\n      run: skill-ci check\n", path.read_text())

    def test_another_lefthook_file_name_is_found(self) -> None:
        path = write(self.repository / ".lefthook.yaml", "output:\n  - summary\n")
        self.init()
        self.assertEqual(
            yaml.safe_load(path.read_text()),
            {
                "output": ["summary"],
                "pre-commit": {"commands": {"skill-ci-check-fast": {"run": "skill-ci check --fast"}}},
                "pre-push": {"commands": {"skill-ci-check": {"run": "skill-ci check"}}},
            },
        )


class LefthookEditTests(unittest.TestCase):
    ADD = ("pre-commit", "skill-ci-check-fast", "skill-ci check --fast")

    def test_each_shape_gains_the_command_and_keeps_everything_else(self) -> None:
        for name, before, after in (
            ("empty file", "", "pre-commit:\n  commands:\n    skill-ci-check-fast:\n      run: skill-ci check --fast\n"),
            ("only comments", "# nothing\n", "# nothing\n\npre-commit:\n  commands:\n    skill-ci-check-fast:\n      run: skill-ci check --fast\n"),
            ("no final newline", "output:\n  - summary", "output:\n  - summary\n\npre-commit:\n  commands:\n    skill-ci-check-fast:\n      run: skill-ci check --fast\n"),
            (
                "hook without commands",
                "pre-commit:\n  parallel: true\nother:\n  x: 1\n",
                "pre-commit:\n  parallel: true\n  commands:\n    skill-ci-check-fast:\n      run: skill-ci check --fast\nother:\n  x: 1\n",
            ),
            (
                "empty hook",
                "pre-commit:\nother:\n  x: 1\n",
                "pre-commit:\n  commands:\n    skill-ci-check-fast:\n      run: skill-ci check --fast\nother:\n  x: 1\n",
            ),
            (
                "four-space indent",
                "pre-commit:\n    commands:\n        lint:\n            run: make\n",
                "pre-commit:\n    commands:\n        lint:\n            run: make\n        skill-ci-check-fast:\n            run: skill-ci check --fast\n",
            ),
            (
                "empty commands",
                "pre-commit:\n  commands:\nnext: 1\n",
                "pre-commit:\n  commands:\n    skill-ci-check-fast:\n      run: skill-ci check --fast\nnext: 1\n",
            ),
            (
                "trailing comment on the hook line",
                "pre-commit: # hooks\n  commands:\n    lint:\n      run: make\n",
                "pre-commit: # hooks\n  commands:\n    lint:\n      run: make\n    skill-ci-check-fast:\n      run: skill-ci check --fast\n",
            ),
            (
                "comment after the block",
                "pre-commit:\n  commands:\n    lint:\n      run: make\n# end\n",
                "pre-commit:\n  commands:\n    lint:\n      run: make\n    skill-ci-check-fast:\n      run: skill-ci check --fast\n# end\n",
            ),
            (
                "windows line endings",
                "pre-commit:\r\n  commands:\r\n    lint:\r\n      run: make\r\n",
                "pre-commit:\r\n  commands:\r\n    lint:\r\n      run: make\r\n    skill-ci-check-fast:\r\n      run: skill-ci check --fast\r\n",
            ),
        ):
            with self.subTest(name):
                self.assertEqual(init.with_command(before, *self.ADD), after)

    def test_a_shape_that_cannot_be_edited_safely_comes_back_none(self) -> None:
        for name, before in (
            ("jobs", "pre-commit:\n  jobs:\n    - run: make\n"),
            ("flow mapping", "pre-commit: {commands: {lint: {run: make}}}\n"),
            ("quoted key", '"pre-commit":\n  commands:\n    lint:\n      run: make\n'),
            ("list at the top", "- pre-commit\n"),
            ("commands is a list", "pre-commit:\n  commands:\n    - make\n"),
            ("not yaml", "pre-commit: [\n"),
        ):
            with self.subTest(name):
                try:
                    edited = init.with_command(before, *self.ADD)
                except yaml.YAMLError:
                    continue
                self.assertIsNone(edited)


class MiseTests(InitTestCase):
    def tasks(self) -> dict[str, object]:
        return tomllib.loads((self.repository / "mise.toml").read_text())["tasks"]

    def test_mise_gets_one_line_tasks_that_call_the_subcommands(self) -> None:
        write(self.repository / "mise.toml", '[tools]\nuv = "0.12.7"')
        result = self.init()
        self.assertEqual(result.status, 0, result.stderr)
        self.assertEqual(self.tasks(), {name: {"run": command} for name, command in SKILL_CHECK_TASKS.items()})
        self.assertIn(f"updated mise.toml (added {', '.join(SKILL_CHECK_TASKS)})", result.lines)
        self.assertTrue((self.repository / "mise.toml").read_text().startswith('[tools]\nuv = "0.12.7"\n\n[tasks.skill-check]\nrun = "skill-ci check"\n'))

    def test_a_task_the_repository_already_defines_is_kept(self) -> None:
        text = '[tasks.skill-lint]\nrun = "make lint"\n\n[tasks.test]\nrun = "make test"\n'
        write(self.repository / ".mise.toml", text)
        self.init()
        tasks = tomllib.loads((self.repository / ".mise.toml").read_text())["tasks"]
        self.assertEqual(tasks["skill-lint"], {"run": "make lint"})
        self.assertEqual(tasks["test"], {"run": "make test"})
        self.assertEqual(set(tasks), {"test", *SKILL_CHECK_TASKS})
        self.assertTrue((self.repository / ".mise.toml").read_text().startswith(text))

    def test_a_tasks_table_written_inline_becomes_a_to_do(self) -> None:
        text = 'tasks = { test = { run = "make test" } }\n'
        path = write(self.repository / "mise.toml", text)
        result = self.init()
        self.assertEqual(result.status, 1)
        self.assertEqual(path.read_text(), text)
        self.assertIn("to do: add the skill tasks to mise.toml", result.stdout)
        self.assertIn("[tasks.skill-lint]", result.stdout)

    def test_a_repository_without_mise_is_not_given_a_file(self) -> None:
        self.init()
        self.assertFalse((self.repository / "mise.toml").exists())


class NoMistakesTests(InitTestCase):
    def test_a_lint_command_gains_check_and_the_default_branch_is_named(self) -> None:
        path = write(self.repository / ".no-mistakes.yaml", "agent: claude\ncommands:\n  test: make test\n  lint: make lint\n")
        result = self.init()
        self.assertEqual(result.status, 0, result.stderr)
        self.assertEqual(path.read_text(), "agent: claude\ncommands:\n  test: make test\n  lint: make lint && skill-ci check\n")
        self.assertIn("updated .no-mistakes.yaml (commands.lint: make lint -> make lint && skill-ci check)", result.lines)
        self.assertIn("note: no-mistakes reads commands from the default branch, not from the branch you push, so this change applies after it merges there", result.lines)

    def test_each_scalar_style_gains_the_suffix_and_keeps_its_quotes_and_comment(self) -> None:
        for name, before, after in (
            ("plain", "commands:\n  lint: make lint\n", "commands:\n  lint: make lint && skill-ci check\n"),
            ("plain with comment", "commands:\n  lint: make lint  # fast\n", "commands:\n  lint: make lint && skill-ci check  # fast\n"),
            ("double quoted", 'commands:\n  lint: "make lint"\n', 'commands:\n  lint: "make lint && skill-ci check"\n'),
            ("single quoted with comment", "commands:\n  lint: 'make lint' # fast\n", "commands:\n  lint: 'make lint && skill-ci check' # fast\n"),
            ("four spaces", "commands:\n    lint: make lint\n", "commands:\n    lint: make lint && skill-ci check\n"),
            ("windows line endings", "commands:\r\n  lint: make lint\r\n", "commands:\r\n  lint: make lint && skill-ci check\r\n"),
            ("after other keys", "commands:\n  prepare: npm ci\n  lint: eslint .\n  format: prettier -w .\n", "commands:\n  prepare: npm ci\n  lint: eslint . && skill-ci check\n  format: prettier -w .\n"),
        ):
            with self.subTest(name):
                self.assertEqual(init.with_lint_suffix(before), after)

    def test_a_scalar_init_cannot_edit_safely_comes_back_none(self) -> None:
        for name, before in (
            ("block scalar", "commands:\n  lint: |\n    make lint\n"),
            ("folded scalar", "commands:\n  lint: >\n    make lint\n"),
            ("flow mapping", "commands: {lint: make lint}\n"),
            ("anchor", "commands:\n  lint: &lint make lint\n"),
            ("lint outside commands", "other:\n  lint: make lint\ncommands:\n  test: make\n"),
        ):
            with self.subTest(name):
                self.assertIsNone(init.with_lint_suffix(before))

    def test_a_lint_command_that_init_cannot_edit_becomes_a_to_do_and_the_file_is_untouched(self) -> None:
        text = "commands:\n  lint: |\n    make lint\n"
        path = write(self.repository / ".no-mistakes.yaml", text)
        result = self.init()
        self.assertEqual(result.status, 1)
        self.assertEqual(path.read_text(), text)
        self.assertIn("to do: append ` && skill-ci check` to commands.lint in .no-mistakes.yaml (it could not be edited safely)", result.lines)

    def test_an_empty_lint_command_leaves_the_file_alone_and_prints_the_override(self) -> None:
        self.git("remote", "add", "origin", "https://github.com/example/widget.git")
        for text in ("agent: claude\n", "commands:\n  test: make test\n", "commands:\n  lint: ''\n"):
            with self.subTest(text=text):
                path = write(self.repository / ".no-mistakes.yaml", text)
                result = self.init()
                self.assertEqual(result.status, 0, result.stderr)
                self.assertEqual(path.read_text(), text)
                self.assertIn("kept .no-mistakes.yaml (commands.lint is empty, and setting it would replace the agent's lint duty)", result.lines)
                [note] = [line for line in result.lines if line.startswith("note: add this to ~/.no-mistakes/config.yaml")]
                self.assertIn("no-mistakes reads commands from the default branch", note)
                self.assertIn(
                    "    repository_overrides:\n      https://github.com/example/widget.git:\n        commands:\n          lint:\n            additional:\n              - skill-ci check",
                    result.stdout,
                )

    def test_the_override_names_a_placeholder_when_the_repository_has_no_origin(self) -> None:
        write(self.repository / ".no-mistakes.yaml", "agent: claude\n")
        self.assertIn("  <remote URL>:", self.init().stdout)

    def test_a_lint_command_that_already_runs_check_is_kept(self) -> None:
        text = "commands:\n  lint: skill-ci check\n"
        path = write(self.repository / ".no-mistakes.yaml", text)
        result = self.init()
        self.assertEqual(path.read_text(), text)
        self.assertIn("kept .no-mistakes.yaml (commands.lint already runs skill-ci check)", result.lines)

    def test_a_repository_without_no_mistakes_prints_nothing_about_it(self) -> None:
        self.assertNotIn("no-mistakes", self.init().stdout)


class GitignoreTests(InitTestCase):
    def test_only_the_missing_patterns_are_added_after_a_file_with_no_final_newline(self) -> None:
        path = write(self.repository / ".gitignore", "node_modules/\n/eval-runs")
        result = self.init()
        self.assertEqual(path.read_text(), "node_modules/\n/eval-runs\nevals/runs/\n")
        self.assertIn("updated .gitignore (added evals/runs/)", result.lines)

    def test_the_file_keeps_its_line_endings_and_bytes_that_are_not_utf8(self) -> None:
        path = self.repository / ".gitignore"
        path.write_bytes(b"caf\xe9/\r\nnode_modules/")
        self.init()
        self.assertEqual(
            path.read_bytes(),
            b"caf\xe9/\r\nnode_modules/\r\neval-runs/\r\nevals/runs/\r\n",
        )

    def test_a_file_that_ignores_both_is_kept(self) -> None:
        text = "evals/runs\neval-runs/\n"
        path = write(self.repository / ".gitignore", text)
        result = self.init()
        self.assertEqual(path.read_text(), text)
        self.assertIn("kept .gitignore (already ignores the run output)", result.lines)


class TemplateTests(unittest.TestCase):
    def test_the_templates_are_package_data_that_parse(self) -> None:
        from importlib import resources

        for name in ("skill-checks.yml", "lefthook.yml"):
            with self.subTest(name):
                text = resources.files("skill_ci").joinpath("templates", name).read_text(encoding="utf-8")
                self.assertIsInstance(yaml.safe_load(text.replace("@SOURCE@", '"https://example.com/skill-ci.git"')), dict)
        self.assertEqual(
            init.lefthook_commands(),
            [("pre-commit", "skill-ci-check-fast", "skill-ci check --fast"), ("pre-push", "skill-ci-check", "skill-ci check")],
        )


class ReadmeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.readme = (REPOSITORY / "README.md").read_text(encoding="utf-8")

    def test_the_keys_table_names_every_key_the_model_accepts_and_no_other(self) -> None:
        table = self.readme.split("\n### Keys\n", 1)[1].split("\n### ", 1)[0]
        documented = set(re.findall(r"^\| `([a-z_]+)` \|", table, re.MULTILINE))
        self.assertEqual(documented, {"version", "source", *config.OPTIONS})

    def test_the_signals_section_names_every_signal_that_stops_a_run(self) -> None:
        section = self.readme.split("\n### Signals\n", 1)[1].split("\n## ", 1)[0]
        stops = section.split("Each one ends", 1)[0]
        documented = set(re.findall(r"`(SIG[A-Z0-9]+)`", stops))
        # SIGIO and SIGPOLL are one number on Linux, so compare numbers.
        numbers = {getattr(signal, name) for name in documented if hasattr(signal, name)}
        self.assertLessEqual(children.STOPPING, numbers)
        self.assertLessEqual({name for name in documented if not hasattr(signal, name)}, {"SIGPOLL", "SIGPWR"})

    def test_the_readme_documents_every_exit_code_it_can_end_with(self) -> None:
        table = self.readme.split("\n### Exit codes\n", 1)[1].split("\n### ", 1)[0]
        self.assertEqual(re.findall(r"^\| (\d+)", table, re.MULTILINE), ["0", "1", "2", "126", "127", "128"])


if __name__ == "__main__":
    unittest.main()
