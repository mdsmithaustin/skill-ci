from __future__ import annotations

import contextlib
import io
import json
import os
import pty
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from support import ENVIRONMENT, INSTALLED_COMMAND, REPOSITORY, FakeHarness, fake_git_install, skill_ci, write, write_skill

from skill_ci import pin
from skill_ci.config import Tag

ISOLATED_GIT = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "skill-ci tests",
    "GIT_AUTHOR_EMAIL": "tests@example.com",
    "GIT_COMMITTER_NAME": "skill-ci tests",
    "GIT_COMMITTER_EMAIL": "tests@example.com",
}
UNKNOWN_KEY = "skill-ci: .skill-ci.toml: unknown key 'skils_dir'; did you mean 'skills_dir'?"
FAKE_UV = """\
import json, os, signal, sys, time
with open(os.environ["FAKE_UV_LOG"], "a", encoding="utf-8") as log:
    record = {"arguments": sys.argv[1:], "pinned": os.environ.get("SKILL_CI_PINNED"), "pythonpath": os.environ.get("PYTHONPATH")}
    log.write(json.dumps(record) + "\\n")
if os.environ.get("FAKE_UV_DIES"):
    os.kill(os.getpid(), signal.SIGTERM)
if os.environ.get("FAKE_UV_FAILS"):
    sys.exit("error: Failed to fetch the pinned commit")
if installed := os.environ.get("FAKE_UV_CHILD"):
    command = os.environ["FAKE_UV_COMMAND"]
    os.execve(command, [command, *sys.argv[7:]], {**os.environ, "PYTHONPATH": installed})
open(os.environ["SKILL_CI_STARTED"], "x").close()
if received := os.environ.get("FAKE_UV_SIGNALS"):
    def record(number, frame):
        with open(received, "a") as log:
            log.write(f"{number}\\n")
        raise SystemExit(100 + number)
    signal.signal(signal.SIGINT, record)
    signal.signal(signal.SIGTERM, record)
    open(received, "w").close()
    time.sleep(30)
raise SystemExit(int(os.environ.get("FAKE_UV_EXIT", "3")))
"""


class PinTestCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="skill-ci-pin-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        bin_directory = self.root / "bin"
        self.uv_log = self.root / "uv.json"
        write(bin_directory / "uv", f"#!{sys.executable}\n{FAKE_UV}").chmod(0o755)
        self.git_log = self.root / "git.log"
        write(self.root / "git shim" / "git", f'#!/bin/sh\necho "$*" >> "{self.git_log}"\nexec "{shutil.which("git")}" "$@"\n').chmod(0o755)
        self.cache = self.root / "cache"
        self.environment = {
            **{key: value for key, value in ENVIRONMENT.items() if key != "SKILL_CI_PINNED"},
            **ISOLATED_GIT,
            "GIT_CEILING_DIRECTORIES": str(self.root),
            "HOME": str(self.root / "home"),
            "XDG_CACHE_HOME": str(self.cache),
            "FAKE_UV_LOG": str(self.uv_log),
            "PATH": f"{bin_directory}{os.pathsep}{os.environ['PATH']}",
        }
        self.source = self.root / "source.git"
        self.work = self.root / "work"
        self.git("init", "-q", "--bare", "--initial-branch=main", str(self.source), cwd=self.root)
        self.git("clone", "-q", str(self.source), str(self.work), cwd=self.root)
        self.commits = {name: self.commit(name) for name in ("v0.9.0", "v0.9.1", "v0.10.0")}
        self.git("tag", "v0.9.0", self.commits["v0.9.0"])
        self.git("tag", "-a", "-m", "annotated", "v0.9.1", self.commits["v0.9.1"])
        self.git("tag", "-a", "-m", "annotated", "v0.10.0", self.commits["v0.10.0"])
        self.git("tag", "release-candidate", self.commits["v0.10.0"])
        self.main = self.commit("after v0.10.0")
        self.git("push", "-q", "origin", "main", "--tags")
        self.consumer = self.root / "consumer"
        write_skill(self.consumer / "skills" / "example")
        self.git("init", "-q", cwd=self.consumer)
        self.git("add", "-A", cwd=self.consumer)

    def git(self, *arguments: str, cwd: Path | None = None) -> str:
        result = subprocess.run(
            ["git", *arguments], cwd=cwd or self.work, env=self.environment, capture_output=True, text=True, check=True
        )
        return result.stdout.strip()

    def commit(self, message: str) -> str:
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")

    def push_commit(self, message: str) -> str:
        commit = self.commit(message)
        self.git("push", "-q", "origin", "main")
        return commit

    def pin(self, version: str, *lines: str) -> Path:
        return write(self.consumer / ".skill-ci.toml", "\n".join((f'version = "{version}"', f'source = "{self.source}"', *lines, "")))

    def skill_ci(self, *arguments: str, **variables: str) -> subprocess.CompletedProcess[str]:
        return skill_ci(*arguments, cwd=self.consumer, env={**self.environment, **variables})

    def handed_off(self, result: subprocess.CompletedProcess[str], commit: str, *arguments: str, status: int = 3) -> None:
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        self.assertEqual(
            [json.loads(line) for line in self.uv_log.read_text().splitlines()],
            [
                {
                    "arguments": ["tool", "run", "--isolated", "--from", f"git+{self.source.as_uri()}@{commit}", "skill-ci", *arguments],
                    "pinned": commit,
                    "pythonpath": None,
                }
            ],
        )
        self.uv_log.unlink()

    def running(self, commit: str) -> dict[str, str]:
        return {"PYTHONPATH": str(fake_git_install(self.root / "installed", commit))}

    def unreachable(self) -> None:
        self.source.rename(self.root / "moved.git")

    def shimmed(self) -> dict[str, str]:
        return {"PATH": f"{self.root / 'git shim'}{os.pathsep}{self.environment['PATH']}"}

    def cache_record(self) -> tuple[Path, dict[str, object]]:
        [cached] = (self.cache / "skill-ci" / "refs").glob("*.json")
        return cached, json.loads(cached.read_text())

    def tag(self, name: str) -> str:
        commit = self.push_commit(name)
        self.git("tag", name, commit)
        self.git("push", "-q", "origin", name)
        return commit


class ResolutionTests(PinTestCase):
    def test_an_exact_tag_runs_its_commit_and_names_a_newer_tag(self) -> None:
        self.pin("v0.9.0")
        result = self.skill_ci("check", "--fast")
        self.handed_off(result, self.commits["v0.9.0"], "check", "--fast")
        self.assertEqual(
            result.stderr.splitlines(),
            [
                f"skill-ci v0.9.0 ({self.commits['v0.9.0']})",
                "skill-ci: v0.10.0 is newer than the pinned v0.9.0; run skill-ci update to move the pin",
            ],
        )

    def test_an_annotated_tag_runs_the_commit_it_names_not_the_tag_object(self) -> None:
        self.pin("v0.9.1")
        result = self.skill_ci("--version")
        self.handed_off(result, self.commits["v0.9.1"], "--version")
        self.assertEqual(result.stderr.splitlines()[0], f"skill-ci v0.9.1 ({self.commits['v0.9.1']})")

    def test_latest_is_the_highest_version_tag(self) -> None:
        self.git("tag", "-a", "-m", "release candidate", "v0.11.0-rc.1", self.main)
        self.git("push", "-q", "origin", "v0.11.0-rc.1")
        self.pin("latest")
        result = self.skill_ci("lint")
        self.handed_off(result, self.commits["v0.10.0"], "lint")
        self.assertEqual(result.stderr.splitlines(), [f"skill-ci v0.10.0 ({self.commits['v0.10.0']})"])

    def test_main_follows_the_branch_head(self) -> None:
        self.pin("main")
        self.handed_off(self.skill_ci("lint"), self.main, "lint")
        moved = self.push_commit("main moves")
        result = self.skill_ci("lint")
        self.handed_off(result, moved, "lint")
        self.assertEqual(result.stderr.splitlines(), [f"skill-ci main ({moved})"])

    def test_a_missing_tag_stops_before_any_run(self) -> None:
        self.pin("v9.9.9")
        result = self.skill_ci("lint")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stderr.splitlines(), [f"skill-ci: {self.source.as_uri()} has no tag v9.9.9"])
        self.assertFalse(self.uv_log.exists())

    def test_a_control_character_in_source_stops_before_git_runs(self) -> None:
        write(self.consumer / ".skill-ci.toml", 'version = "latest"\nsource = "https://git.example.com/skill-ci.git\\u0000x"\n')
        result = self.skill_ci("lint", **self.shimmed())
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(
            result.stderr.splitlines(),
            ["skill-ci: .skill-ci.toml: source 'https://git.example.com/skill-ci.git\\x00x' contains the control character '\\x00'; remove it"],
        )
        self.assertFalse(self.git_log.exists())

    def test_an_unknown_key_is_reported_before_a_resolution_error(self) -> None:
        self.pin("v9.9.9", 'skils_dir = "skills"')
        missing = self.skill_ci("lint")
        self.assertEqual(missing.returncode, 2, missing.stderr)
        self.assertEqual(missing.stderr.splitlines(), [UNKNOWN_KEY, f"skill-ci: {self.source.as_uri()} has no tag v9.9.9"])
        shutil.rmtree(self.cache)
        self.unreachable()
        self.pin("latest", 'skils_dir = "skills"')
        unreachable = self.skill_ci("lint")
        self.assertEqual(unreachable.returncode, 2, unreachable.stderr)
        self.assertRegex(
            unreachable.stderr,
            rf"^{re.escape(UNKNOWN_KEY)}\nskill-ci: cannot reach {re.escape(self.source.as_uri())} \(.*\), and no version was ever resolved from it\n$",
        )
        self.assertFalse(self.uv_log.exists())


class OfflineTests(PinTestCase):
    def test_a_moving_pin_falls_back_to_its_cached_commit_with_a_warning(self) -> None:
        for version, commit in (("latest", self.commits["v0.10.0"]), ("main", self.main)):
            with self.subTest(version=version):
                self.pin(version)
                self.handed_off(self.skill_ci("lint"), commit, "lint")
        self.unreachable()
        for version, commit in (("latest", self.commits["v0.10.0"]), ("main", self.main)):
            with self.subTest(version=version):
                self.pin(version)
                result = self.skill_ci("lint")
                self.handed_off(result, commit, "lint")
                first, warning = result.stderr.splitlines()
                self.assertEqual(first, f"skill-ci {'v0.10.0' if version == 'latest' else 'main'} ({commit})")
                self.assertRegex(
                    warning,
                    rf"^skill-ci: warning: cannot reach {self.source.as_uri()} \(.*does not appear to be a git repository\); "
                    rf"running {commit}, which {version} named on \d{{4}}-\d\d-\d\d \d\d:\d\d UTC$",
                )

    def test_a_moving_pin_with_nothing_cached_stops(self) -> None:
        self.unreachable()
        self.pin("latest")
        result = self.skill_ci("lint")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertRegex(
            result.stderr,
            rf"^skill-ci: cannot reach {self.source.as_uri()} \(.*\), and no version was ever resolved from it\n$",
        )
        self.assertFalse(self.uv_log.exists())

    def test_an_exact_tag_reads_a_fresh_cache_without_the_network(self) -> None:
        self.pin("v0.9.0")
        shimmed = self.shimmed()
        self.handed_off(self.skill_ci("lint", **shimmed), self.commits["v0.9.0"], "lint")
        self.assertEqual(self.git_log.read_text(), f"ls-remote {self.source.as_uri()} refs/heads/main refs/tags/v*\n")
        self.git_log.unlink()
        result = self.skill_ci("lint", **shimmed)
        self.handed_off(result, self.commits["v0.9.0"], "lint")
        self.assertFalse(self.git_log.exists(), "a fresh cache answers an exact tag without git")
        self.assertNotIn("warning", result.stderr)

    def test_an_exact_tag_refreshes_the_newer_tag_notice_after_a_day(self) -> None:
        self.pin("v0.9.0")
        self.handed_off(self.skill_ci("lint"), self.commits["v0.9.0"], "lint")
        self.git("tag", "v0.11.0", self.push_commit("v0.11.0"))
        self.git("push", "-q", "origin", "v0.11.0")
        fresh = self.skill_ci("lint")
        self.handed_off(fresh, self.commits["v0.9.0"], "lint")
        self.assertIn("v0.10.0 is newer than the pinned v0.9.0", fresh.stderr)
        cached, record = self.cache_record()
        cached.write_text(json.dumps({**record, "fetched_at": (datetime.now(UTC) - timedelta(days=2)).isoformat()}))
        stale = self.skill_ci("lint")
        self.handed_off(stale, self.commits["v0.9.0"], "lint")
        self.assertIn("v0.11.0 is newer than the pinned v0.9.0", stale.stderr)

    def test_a_cache_dated_in_the_future_is_stale(self) -> None:
        self.pin("v0.9.0")
        self.handed_off(self.skill_ci("lint"), self.commits["v0.9.0"], "lint")
        cached, record = self.cache_record()
        cached.write_text(json.dumps({**record, "fetched_at": "2099-01-01T00:00:00+00:00", "tags": {"v0.9.0": self.commits["v0.9.0"]}}))
        result = self.skill_ci("lint", **self.shimmed())
        self.handed_off(result, self.commits["v0.9.0"], "lint")
        self.assertTrue(self.git_log.exists(), "a cache dated in the future asks the source again")
        self.assertIn("v0.10.0 is newer than the pinned v0.9.0", result.stderr)

    def test_a_fresh_cache_without_the_pinned_tag_asks_the_source(self) -> None:
        self.pin("v0.9.0")
        self.handed_off(self.skill_ci("lint"), self.commits["v0.9.0"], "lint")
        newer = self.tag("v0.11.0")
        self.pin("v0.11.0")
        self.handed_off(self.skill_ci("lint"), newer, "lint")

    def test_an_exact_tag_offline_runs_its_cached_commit_or_names_what_the_cache_lacks(self) -> None:
        self.pin("v0.9.0")
        self.handed_off(self.skill_ci("lint"), self.commits["v0.9.0"], "lint")
        cached, record = self.cache_record()
        cached.write_text(json.dumps({**record, "fetched_at": (datetime.now(UTC) - timedelta(days=2)).isoformat()}))
        self.unreachable()
        result = self.skill_ci("lint")
        self.handed_off(result, self.commits["v0.9.0"], "lint")
        self.assertEqual(
            result.stderr.splitlines(),
            [
                f"skill-ci v0.9.0 ({self.commits['v0.9.0']})",
                "skill-ci: v0.10.0 is newer than the pinned v0.9.0; run skill-ci update to move the pin",
            ],
        )
        self.pin("v0.11.0")
        missing = self.skill_ci("lint")
        self.assertEqual(missing.returncode, 2, missing.stderr)
        self.assertRegex(
            missing.stderr,
            rf"^skill-ci: cannot reach {self.source.as_uri()} \(.*\), and the versions cached on \d{{4}}-\d\d-\d\d have no tag v0\.11\.0\n$",
        )
        self.assertFalse(self.uv_log.exists())

    def test_a_corrupt_cache_counts_as_no_cache(self) -> None:
        self.pin("latest")
        self.handed_off(self.skill_ci("lint"), self.commits["v0.10.0"], "lint")
        cached, record = self.cache_record()
        self.unreachable()
        for text in (
            "not json",
            "[]",
            json.dumps({key: value for key, value in record.items() if key != "source"}),
            json.dumps({**record, "source": "https://git.example.com/skill-ci.git"}),
            json.dumps({**record, "fetched_at": "2026-10-06T00:00:00"}),
            json.dumps({**record, "main": "not a commit"}),
            json.dumps({**record, "tags": {"v0.10.0": "not a commit"}}),
        ):
            with self.subTest(text=text):
                cached.write_text(text)
                result = self.skill_ci("lint")
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("no version was ever resolved from it", result.stderr)
        cached.write_text(json.dumps(record))
        self.handed_off(self.skill_ci("lint"), self.commits["v0.10.0"], "lint")

    def test_a_relative_cache_home_is_ignored(self) -> None:
        self.pin("v0.9.0")
        self.handed_off(self.skill_ci("lint", XDG_CACHE_HOME=".cache"), self.commits["v0.9.0"], "lint")
        self.assertFalse((self.consumer / ".cache").exists())
        self.assertEqual(len(list((self.root / "home" / ".cache" / "skill-ci" / "refs").glob("*.json"))), 1)


class CacheWriteTests(unittest.TestCase):
    def test_writers_in_one_process_never_collide(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="skill-ci-cache-")
        self.addCleanup(temporary.cleanup)
        cache = Path(temporary.name)
        source = "https://git.example.com/skill-ci.git"
        refs = pin.Refs(source, datetime.now(UTC).replace(microsecond=0), "a" * 40, {Tag(1, 0, 0): "b" * 40})
        warnings = io.StringIO()

        def write_often() -> None:
            for _ in range(300):
                pin.write_cache(cache, refs)

        with contextlib.redirect_stderr(warnings):
            writers = [threading.Thread(target=write_often) for _ in range(4)]
            for writer in writers:
                writer.start()
            for writer in writers:
                writer.join()
        self.assertEqual(warnings.getvalue(), "")
        self.assertEqual(pin.read_cache(cache, source), refs)
        self.assertEqual([path.name for path in (cache / "refs").iterdir()], [pin.cache_file(cache, source).name])


class RerunGuardTests(PinTestCase):
    def test_the_pinned_child_runs_in_place_and_reports_only_its_installed_commit(self) -> None:
        self.pin("v0.9.1")
        child = {"PYTHONPATH": str(fake_git_install(self.root / "installed", self.commits["v0.9.0"])), "SKILL_CI_PINNED": self.commits["v0.9.0"]}
        result = self.skill_ci("check", "--fast", **child)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], "checks run: 3; failed: 0")
        self.assertNotIn("skill-ci v0.9", result.stderr)
        self.assertFalse(self.uv_log.exists())
        version = self.skill_ci("--version", **child)
        self.assertEqual(version.stdout, f"skill-ci 1.0.0 ({self.commits['v0.9.0']})\n")

    def test_a_child_that_is_not_the_pinned_commit_refuses_to_run(self) -> None:
        self.pin("v0.9.0")
        installed = str(fake_git_install(self.root / "installed", self.commits["v0.9.0"]))
        other = self.commits["v0.9.1"]
        for variables, problem in (
            ({"SKILL_CI_PINNED": "1"}, "SKILL_CI_PINNED is '1', not a full commit"),
            ({"SKILL_CI_PINNED": other}, f"SKILL_CI_PINNED names {other}, but this skill-ci was not installed from a git commit"),
            ({"SKILL_CI_PINNED": other, "PYTHONPATH": installed}, f"SKILL_CI_PINNED names {other}, but this skill-ci was installed from {self.commits['v0.9.0']}"),
        ):
            with self.subTest(problem=problem):
                result = self.skill_ci("check", "--fast", **variables)
                self.assertEqual(result.returncode, 126, result.stdout + result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertEqual(result.stderr, f"skill-ci: {problem}\n")
        self.assertFalse(self.uv_log.exists())

    def test_the_pinned_child_marks_its_start_and_hides_the_hand_off_from_what_it_runs(self) -> None:
        fake = FakeHarness(self.root)
        fake_git_install(fake.purelib, self.commits["v0.9.0"])
        started = self.root / "started"
        result = fake.run(
            "harness", "skill-benchmark", "--help", cwd=self.consumer, SKILL_CI_PINNED=self.commits["v0.9.0"], SKILL_CI_STARTED=str(started)
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(started.is_file())
        self.assertEqual([call["skill_ci_variables"] for call in fake.calls()], [[]])

    def test_a_run_pinned_to_its_own_commit_stays_one_process(self) -> None:
        installed = fake_git_install(self.root / "installed", self.commits["v0.9.0"])
        self.pin("v0.9.0")

        def module(*arguments: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, "-m", "skill_ci", *arguments],
                cwd=self.consumer,
                env={**self.environment, "PYTHONPATH": os.pathsep.join((str(installed), str(REPOSITORY / "src")))},
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )

        result = module("check", "--fast")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr.splitlines()[:2], [f"skill-ci v0.9.0 ({self.commits['v0.9.0']})", "skill-ci: v0.10.0 is newer than the pinned v0.9.0; run skill-ci update to move the pin"])
        self.assertEqual(result.stdout.splitlines()[-1], "checks run: 3; failed: 0")
        self.assertFalse(self.uv_log.exists())
        self.assertEqual(module("--version").stdout, f"skill-ci 1.0.0 ({self.commits['v0.9.0']})\n")

    def test_the_hand_off_drops_python_path_overrides(self) -> None:
        self.pin("v0.9.0")
        result = self.skill_ci("lint", PYTHONPATH=str(self.root / "impostor"))
        self.handed_off(result, self.commits["v0.9.0"], "lint")

    def test_a_hand_off_without_a_runnable_uv_stops_with_the_reason(self) -> None:
        self.pin("v0.9.0")
        git_only = self.root / "git only"
        write(git_only / "git", f'#!/bin/sh\nexec "{shutil.which("git")}" "$@"\n').chmod(0o755)
        missing = self.skill_ci("lint", PATH=str(git_only))
        self.assertEqual(missing.returncode, 127, missing.stderr)
        self.assertIn(f"skill-ci: running the pinned commit {self.commits['v0.9.0']} needs uv on PATH\n", missing.stderr)
        write(git_only / "uv", "#!/nonexistent/interpreter\n").chmod(0o755)
        broken = self.skill_ci("lint", PATH=str(git_only))
        self.assertEqual(broken.returncode, 126, broken.stderr)
        self.assertIn(f"skill-ci: cannot run {git_only / 'uv'} for the pinned commit {self.commits['v0.9.0']}: ", broken.stderr)

    def test_an_empty_guard_still_resolves(self) -> None:
        self.pin("v0.9.0")
        self.handed_off(self.skill_ci("lint", SKILL_CI_PINNED=""), self.commits["v0.9.0"], "lint")

    def test_a_bad_key_stops_the_run_before_any_resolution_or_hand_off(self) -> None:
        problems = ["skill-ci: .skill-ci.toml: runs is 'five'; set it to a whole number", UNKNOWN_KEY]
        running = self.running(self.commits["v0.10.0"])
        for version, variables in (
            ("v0.10.0", running),
            ("v0.9.0", running),
            ("v0.9.0", {}),
            ("latest", {}),
            ("unreachable latest", {}),
        ):
            with self.subTest(version=version, running=bool(variables)):
                if version == "unreachable latest":
                    self.unreachable()
                self.pin(version.split()[-1], 'skils_dir = "skills"', 'runs = "five"')
                result = self.skill_ci("check", "--fast", **self.shimmed(), **variables)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(result.stderr.splitlines(), problems)
        self.assertFalse(self.git_log.exists())
        self.assertFalse(self.uv_log.exists())

    def test_a_pin_on_the_running_commit_reports_an_unknown_key_without_a_hand_off(self) -> None:
        self.pin("v0.10.0", 'skils_dir = "skills"')
        result = self.skill_ci("check", "--fast", **self.running(self.commits["v0.10.0"]))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr.splitlines(), [f"skill-ci v0.10.0 ({self.commits['v0.10.0']})", UNKNOWN_KEY])
        self.assertFalse(self.uv_log.exists())

    def test_a_direct_child_run_reports_an_unknown_key_and_nothing_else(self) -> None:
        self.pin("v0.9.1", 'skils_dir = "skills"')
        child = {**self.running(self.commits["v0.9.0"]), "SKILL_CI_PINNED": self.commits["v0.9.0"]}
        result = self.skill_ci("check", "--fast", **child)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr.splitlines(), [UNKNOWN_KEY])
        self.assertFalse(self.uv_log.exists())

    def test_a_deleted_working_directory_counts_as_no_file(self) -> None:
        gone = self.consumer / "gone"

        def from_gone(*arguments: str) -> subprocess.CompletedProcess[str]:
            gone.mkdir()
            return subprocess.run(
                ["sh", "-c", 'cd "$0" && rmdir "$0" && exec "$@"', str(gone), str(INSTALLED_COMMAND), *arguments],
                cwd=self.consumer,
                env=self.environment,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )

        version = from_gone("--version")
        self.assertEqual(version.returncode, 0, version.stderr)
        self.assertRegex(version.stdout, r"^skill-ci \S+ \(commit unknown\)\n$")
        lint = from_gone("lint", "--skills-dir", str(self.consumer / "skills"))
        self.assertEqual(lint.returncode, 0, lint.stderr)
        self.assertEqual(lint.stdout, "checks run: 2; failed: 0\n")
        update = from_gone("update")
        self.assertEqual(update.returncode, 2, update.stderr)
        self.assertEqual(update.stderr.splitlines()[1:], ["skill-ci: no .skill-ci.toml in the working directory, or in a parent directory inside the same git repository"])

    def test_without_a_file_the_run_names_its_own_version(self) -> None:
        result = self.skill_ci("check", "--fast")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(result.stderr.splitlines()[0], r"^skill-ci \S+ \(commit unknown\)$")
        self.assertFalse(self.uv_log.exists())
        version = self.skill_ci("--version")
        self.assertRegex(version.stdout, r"^skill-ci \S+ \(commit unknown\)\n$")
        self.assertEqual(version.stderr, "")


class HandOffTests(PinTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.pin("v0.10.0")
        self.banner = f"skill-ci v0.10.0 ({self.commits['v0.10.0']})"

    def test_a_uv_failure_before_the_pinned_commit_starts_names_the_commit(self) -> None:
        failed = self.skill_ci("lint", FAKE_UV_FAILS="1")
        self.assertEqual(failed.returncode, 126, failed.stderr)
        self.assertEqual(
            failed.stderr.splitlines(),
            [
                self.banner,
                "error: Failed to fetch the pinned commit",
                f"skill-ci: uv could not start the pinned commit {self.commits['v0.10.0']} (exit 1); fix the uv error above, "
                f"such as no network access to {self.source.as_uri()} or a UV_PYTHON that this commit does not support",
            ],
        )
        killed = self.skill_ci("lint", FAKE_UV_DIES="1")
        self.assertEqual(killed.returncode, 128 + signal.SIGTERM, killed.stderr)
        self.assertEqual(killed.stderr.splitlines(), [self.banner])

    def test_a_pin_on_another_commit_hands_off_once_and_the_child_reports_an_unknown_key(self) -> None:
        self.pin("v0.10.0", 'skils_dir = "skills"')
        installed = fake_git_install(self.root / "installed by uv", self.commits["v0.10.0"])
        result = self.skill_ci("check", "--fast", FAKE_UV_CHILD=str(installed), FAKE_UV_COMMAND=str(INSTALLED_COMMAND))
        self.handed_off(result, self.commits["v0.10.0"], "check", "--fast", status=2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr.splitlines(), [self.banner, UNKNOWN_KEY])

    def test_the_pinned_commit_keeps_its_own_exit_code(self) -> None:
        for code in (0, 1, 2):
            with self.subTest(code=code):
                result = self.skill_ci("lint", FAKE_UV_EXIT=str(code))
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertEqual(result.stderr.splitlines(), [self.banner])

    def signalled(self, *numbers: signal.Signals, terminal: bool = False) -> tuple[int, str]:
        received = self.root / "received"
        primary, replica = pty.openpty() if terminal else (None, None)
        process = subprocess.Popen(
            [str(INSTALLED_COMMAND), "lint"],
            cwd=self.consumer,
            env={**self.environment, "FAKE_UV_SIGNALS": str(received)},
            stdin=subprocess.DEVNULL if replica is None else replica,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 30
            while not received.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            for number in numbers:
                os.kill(process.pid, number)
                time.sleep(0.5)
            return process.wait(timeout=30), received.read_text()
        finally:
            if process.poll() is None:
                process.kill()
            for descriptor in (primary, replica):
                if descriptor is not None:
                    os.close(descriptor)

    def test_a_signal_to_skill_ci_reaches_the_pinned_commit(self) -> None:
        for number in (signal.SIGTERM, signal.SIGINT):
            with self.subTest(signal=number.name):
                self.assertEqual(self.signalled(number), (100 + number, f"{int(number)}\n"))
                (self.root / "received").unlink()

    def test_an_interrupt_at_a_terminal_is_left_to_the_terminal(self) -> None:
        self.assertEqual(self.signalled(signal.SIGINT, signal.SIGTERM, terminal=True), (100 + signal.SIGTERM, f"{int(signal.SIGTERM)}\n"))


class UpdateTests(PinTestCase):
    def test_update_rewrites_only_the_version_value(self) -> None:
        path = write(
            self.consumer / ".skill-ci.toml",
            f'# Pinned by hand.\nversion = "v0.9.0"  # move with skill-ci update\nsource = "{self.source}"\n\n# Layout\nskills_dir = "skills"\n',
        )
        result = self.skill_ci("update")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, ".skill-ci.toml: version v0.9.0 -> v0.10.0\n")
        self.assertEqual(
            path.read_text(),
            f'# Pinned by hand.\nversion = "v0.10.0"  # move with skill-ci update\nsource = "{self.source}"\n\n# Layout\nskills_dir = "skills"\n',
        )
        again = self.skill_ci("update")
        self.assertEqual(again.stdout, ".skill-ci.toml: version is already v0.10.0, the newest tag\n")
        self.assertFalse(self.uv_log.exists())

    def test_update_keeps_line_endings(self) -> None:
        path = self.consumer / ".skill-ci.toml"
        path.write_bytes(f'version = "v0.9.0"\r\nsource = "{self.source}"\r\nskills_dir = "skills"\r\n'.encode())
        result = self.skill_ci("update")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(path.read_bytes(), f'version = "v0.10.0"\r\nsource = "{self.source}"\r\nskills_dir = "skills"\r\n'.encode())

    def test_update_moves_the_pin_in_a_file_with_a_key_this_version_does_not_know(self) -> None:
        text = f'# Pinned by hand.\nversion = "v0.9.0"  # move with skill-ci update\nsource = "{self.source}"\n\nskils_dir = "skills"  # typo kept\n'
        path = write(self.consumer / ".skill-ci.toml", text)
        result = self.skill_ci("update")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, ".skill-ci.toml: version v0.9.0 -> v0.10.0\n")
        self.assertNotIn("skils_dir", result.stderr)
        self.assertEqual(path.read_text(), text.replace('"v0.9.0"', '"v0.10.0"'))

    def test_update_checks_every_known_key_before_it_asks_the_source(self) -> None:
        path = self.pin("v0.9.0", 'skils_dir = "skills"', 'runs = "five"')
        text = path.read_text()
        result = self.skill_ci("update", **self.shimmed())
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stderr.splitlines(), ["skill-ci: .skill-ci.toml: runs is 'five'; set it to a whole number"])
        self.assertEqual(path.read_text(), text)
        self.assertFalse(self.git_log.exists())

    def test_update_refuses_a_rewrite_that_would_change_another_key(self) -> None:
        text = f'"version" = "v0.9.0"\nsource = "{self.source}"\ncodex_cmd = """\nversion = "v0.9.0"\n"""\n'
        path = write(self.consumer / ".skill-ci.toml", text)
        result = self.skill_ci("update")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stderr.splitlines()[1:], ["skill-ci: cannot update .skill-ci.toml: rewriting the version line would change other keys"])
        self.assertEqual(path.read_text(), text)

    def test_update_never_moves_a_pin_backwards(self) -> None:
        path = self.pin("v2.0.0")
        result = self.skill_ci("update")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(
            result.stderr.splitlines()[1:],
            [f"skill-ci: .skill-ci.toml pins v2.0.0, but the newest tag on {self.source.as_uri()} is v0.10.0; left unchanged"],
        )
        self.assertEqual(path.read_text(), f'version = "v2.0.0"\nsource = "{self.source}"\n')

    def test_update_leaves_a_floating_pin_alone(self) -> None:
        for version in ("latest", "main"):
            with self.subTest(version=version):
                text = f'# Float on purpose.\nversion = "{version}"  # keep\nsource = "{self.source}"\n'
                path = write(self.consumer / ".skill-ci.toml", text)
                result = self.skill_ci("update", **self.shimmed())
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, f".skill-ci.toml: version is {version}, which floats; update moves only an exact tag, so the file is unchanged\n")
                self.assertEqual(path.read_text(), text)
        self.assertFalse(self.git_log.exists())

    def test_update_needs_the_source(self) -> None:
        self.pin("v0.9.0")
        self.unreachable()
        result = self.skill_ci("update")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertRegex(result.stderr, rf"^skill-ci \S+ \(commit unknown\)\nskill-ci: cannot reach {self.source.as_uri()} \(.*\)\n$")
        self.assertEqual((self.consumer / ".skill-ci.toml").read_text(), f'version = "v0.9.0"\nsource = "{self.source}"\n')


if __name__ == "__main__":
    unittest.main()
