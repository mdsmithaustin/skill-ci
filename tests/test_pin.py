from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from support import ENVIRONMENT, REPOSITORY, skill_ci, write, write_skill

ISOLATED_GIT = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "skill-ci tests",
    "GIT_AUTHOR_EMAIL": "tests@example.com",
    "GIT_COMMITTER_NAME": "skill-ci tests",
    "GIT_COMMITTER_EMAIL": "tests@example.com",
}
FAKE_UV = """\
import json, os, sys
with open(os.environ["FAKE_UV_LOG"], "w", encoding="utf-8") as log:
    json.dump({"arguments": sys.argv[1:], "pinned": os.environ.get("SKILL_CI_PINNED"), "pythonpath": os.environ.get("PYTHONPATH")}, log)
raise SystemExit(3)
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

    def handed_off(self, result: subprocess.CompletedProcess[str], commit: str, *arguments: str) -> None:
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertEqual(
            json.loads(self.uv_log.read_text()),
            {
                "arguments": ["tool", "run", "--isolated", "--from", f"git+{self.source.as_uri()}@{commit}", "skill-ci", *arguments],
                "pinned": commit,
                "pythonpath": None,
            },
        )
        self.uv_log.unlink()

    def unreachable(self) -> None:
        self.source.rename(self.root / "moved.git")


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
        shimmed = {"PATH": f"{self.root / 'git shim'}{os.pathsep}{self.environment['PATH']}"}
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
        [cached] = (self.cache / "skill-ci" / "refs").glob("*.json")
        record = json.loads(cached.read_text())
        cached.write_text(json.dumps({**record, "fetched_at": (datetime.now(UTC) - timedelta(days=2)).isoformat()}))
        stale = self.skill_ci("lint")
        self.handed_off(stale, self.commits["v0.9.0"], "lint")
        self.assertIn("v0.11.0 is newer than the pinned v0.9.0", stale.stderr)

    def test_a_corrupt_cache_counts_as_no_cache(self) -> None:
        self.pin("latest")
        self.handed_off(self.skill_ci("lint"), self.commits["v0.10.0"], "lint")
        [cached] = (self.cache / "skill-ci" / "refs").glob("*.json")
        self.unreachable()
        well_formed = {"fetched_at": "2026-10-06T00:00:00+00:00", "main": None, "tags": {}}
        for text in ('{"source": 1}', json.dumps(well_formed), "[]", "not json", json.dumps({**well_formed, "fetched_at": "2026-10-06"})):
            with self.subTest(text=text):
                cached.write_text(text)
                result = self.skill_ci("lint")
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("no version was ever resolved from it", result.stderr)


class RerunGuardTests(PinTestCase):
    def test_the_pinned_child_runs_in_place_and_reports_only_its_installed_commit(self) -> None:
        self.pin("v0.9.1")
        child = {"SKILL_CI_PINNED": self.commits["v0.9.0"]}
        result = self.skill_ci("check", "--fast", **child)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], "checks run: 3; failed: 0")
        self.assertNotIn("skill-ci v0.9", result.stderr)
        self.assertFalse(self.uv_log.exists())
        version = self.skill_ci("--version", **child)
        self.assertRegex(version.stdout, r"^skill-ci \S+ \(commit unknown\)\n$")

    def test_a_run_pinned_to_its_own_commit_stays_one_process(self) -> None:
        installed = self.root / "installed"
        dist_info = installed / "skill_ci-1.0.0.dist-info"
        write(dist_info / "METADATA", "Metadata-Version: 2.1\nName: skill-ci\nVersion: 1.0.0\n")
        direct_url = {"url": self.source.as_uri(), "vcs_info": {"vcs": "git", "commit_id": self.commits["v0.9.0"]}}
        write(dist_info / "direct_url.json", json.dumps(direct_url))
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

    def test_an_empty_guard_still_resolves(self) -> None:
        self.pin("v0.9.0")
        self.handed_off(self.skill_ci("lint", SKILL_CI_PINNED=""), self.commits["v0.9.0"], "lint")

    def test_a_key_this_version_does_not_know_still_hands_off_to_the_pin(self) -> None:
        self.pin("v0.9.0", "key_from_a_later_version = true")
        self.handed_off(self.skill_ci("check", "--fast"), self.commits["v0.9.0"], "check", "--fast")
        in_place = self.skill_ci("check", "--fast", SKILL_CI_PINNED=self.commits["v0.9.0"])
        self.assertEqual(in_place.returncode, 2, in_place.stderr)
        self.assertEqual(in_place.stderr, "skill-ci: .skill-ci.toml: unknown key 'key_from_a_later_version'\n")

    def test_without_a_file_the_run_names_its_own_version(self) -> None:
        result = self.skill_ci("check", "--fast")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(result.stderr.splitlines()[0], r"^skill-ci \S+ \(commit unknown\)$")
        self.assertFalse(self.uv_log.exists())
        version = self.skill_ci("--version")
        self.assertRegex(version.stdout, r"^skill-ci \S+ \(commit unknown\)\n$")
        self.assertEqual(version.stderr, "")


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

    def test_update_ignores_keys_it_does_not_read_and_keeps_line_endings(self) -> None:
        path = self.consumer / ".skill-ci.toml"
        path.write_bytes(f'version = "v0.9.0"\r\nsource = "{self.source}"\r\nkey_from_a_later_version = 1\r\n'.encode())
        result = self.skill_ci("update")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(path.read_bytes(), f'version = "v0.10.0"\r\nsource = "{self.source}"\r\nkey_from_a_later_version = 1\r\n'.encode())

    def test_update_never_moves_a_pin_backwards(self) -> None:
        path = self.pin("v2.0.0")
        result = self.skill_ci("update")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(
            result.stderr.splitlines()[1:],
            [f"skill-ci: .skill-ci.toml pins v2.0.0, but the newest tag on {self.source.as_uri()} is v0.10.0; left unchanged"],
        )
        self.assertEqual(path.read_text(), f'version = "v2.0.0"\nsource = "{self.source}"\n')

    def test_update_moves_a_moving_pin_to_the_newest_tag(self) -> None:
        self.pin("main")
        result = self.skill_ci("update")
        self.assertEqual(result.stdout, ".skill-ci.toml: version main -> v0.10.0\n")

    def test_update_needs_the_source(self) -> None:
        self.pin("v0.9.0")
        self.unreachable()
        result = self.skill_ci("update")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertRegex(result.stderr, rf"^skill-ci \S+ \(commit unknown\)\nskill-ci: cannot reach {self.source.as_uri()} \(.*\)\n$")
        self.assertEqual((self.consumer / ".skill-ci.toml").read_text(), f'version = "v0.9.0"\nsource = "{self.source}"\n')


if __name__ == "__main__":
    unittest.main()
