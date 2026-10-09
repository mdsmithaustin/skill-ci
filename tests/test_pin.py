from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from support import INSTALLED_COMMAND, REPOSITORY, FakeHarness, PinTestCase, fake_git_install, run_in_a_broken_cwd, still_running, write

from skill_ci import pin
from skill_ci.config import Tag

UNKNOWN_KEY = "skill-ci: .skill-ci.toml: unknown key 'skils_dir'; did you mean 'skills_dir'?"
OFFLINE_UV_ERROR = "error: Remote Git fetches are not allowed because network connectivity is disabled"
ONLINE_UV_ERROR = "error: Failed to fetch: https://pypi.org/simple/mdurl/"


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
        self.handed_off(self.skill_ci("lint"), self.main, "lint")
        self.expire_cache()
        result = self.skill_ci("lint")
        self.handed_off(result, moved, "lint")
        self.assertEqual(result.stderr.splitlines(), [f"skill-ci main ({moved})"])

    def test_a_missing_tag_stops_before_any_run(self) -> None:
        self.pin("v9.9.9")
        self.refused(self.skill_ci("lint"), [f"skill-ci: {self.source.as_uri()} has no tag v9.9.9"])

    def test_a_control_character_in_source_stops_before_git_runs(self) -> None:
        write(self.consumer / ".skill-ci.toml", 'version = "latest"\nsource = "https://git.example.com/skill-ci.git\\u0000x"\n')
        result = self.skill_ci("lint", **self.shimmed())
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(
            result.stderr.splitlines(),
            ["skill-ci: .skill-ci.toml: source contains a control character; remove it"],
        )
        self.assertFalse(self.git_log.exists())

    def test_an_unknown_key_is_reported_before_a_resolution_error(self) -> None:
        self.pin("v9.9.9", 'skils_dir = "skills"')
        self.refused(self.skill_ci("lint"), [UNKNOWN_KEY, f"skill-ci: {self.source.as_uri()} has no tag v9.9.9"])
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
        self.expire_cache()
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

    def test_a_source_that_never_answers_leaves_no_transport_running(self) -> None:
        transport = self.root / "transport"
        slow = write(self.root / "slow-ssh", f'#!/bin/sh\necho $$ > "{transport}"\nexec sleep 30\n')
        slow.chmod(0o755)
        write(self.consumer / ".skill-ci.toml", 'version = "latest"\nsource = "ssh://git@example.com/skill-ci.git"\n')
        result = self.skill_ci("lint", GIT_SSH_COMMAND=str(slow))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(
            result.stderr.splitlines(),
            ["skill-ci: cannot reach ssh://git@example.com/skill-ci.git (git ls-remote gave no answer in 5 s), and no version was ever resolved from it"],
        )
        self.assertFalse(still_running(int(transport.read_text())), "the ssh transport outlived skill-ci")

    def test_a_credential_in_source_stops_before_git_or_uv_and_is_never_shown(self) -> None:
        credentials = (
            "skill-ci: .skill-ci.toml: source may hold a user name, password or token; keep credentials in a git credential helper, "
            "and name at most an ssh user, as in ssh://git@host/path"
        )
        for source, line in (
            ("https://alice:s3cr3t@127.0.0.1:9/x.git", credentials),
            ("https://ghp_s3cr3t@127.0.0.1:9/x.git", credentials),
            ("https://al@ice:s3cr3t@127.0.0.1:1/x.git", credentials),
            ("https://alice:p#s3cr3t@127.0.0.1:9/x.git", credentials),
            ("https://alice:p?s3cr3t@127.0.0.1:9/x.git", credentials),
            ("https://alice:p/s3cr3t@127.0.0.1:9/x.git", credentials),
            ("https://127.0.0.1:9/x.git?private_token=s3cr3t", "skill-ci: .skill-ci.toml: source has a query or a fragment, which is not allowed; keep a token in a git credential helper"),
            ("https://alice:s3cr3t%40x@127.0.0.1:9/x.git", credentials),
            ("https://alice%3As3cr3t@127.0.0.1:9/x.git", credentials),
            ("https://127.0.0.1:9/org/s3cr3t@x.git", credentials),
            ("ssh://alice:s3cr3t@localhost/x.git", credentials),
            ("ssh://alice%3As3cr3t@localhost/x.git", credentials),
            ("ssh://git%40s3cr3t@localhost/x.git", credentials),
        ):
            with self.subTest(source=source):
                write(self.consumer / ".skill-ci.toml", f'version = "latest"\nsource = "{source}"\n')
                for command in ("lint", "update"):
                    result = self.skill_ci(command, **self.shimmed())
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertEqual(result.stdout, "")
                    self.assertEqual(result.stderr.splitlines()[-1:], [line])
                    self.assertNotIn("s3cr3t", result.stderr)
                self.assertFalse(self.cache.exists(), "nothing was cached")
                self.assertFalse(self.git_log.exists(), "git never ran")
                self.assertFalse(self.uv_log.exists(), "uv never ran")

    def test_no_rejected_source_reaches_the_output_or_the_cache(self) -> None:
        for line in (
            'source = ["s3cr3t"]',
            'source = "https://example.com/x.git\\u001bs3cr3t"',
            'source = "https://127.0.0.1:9/x\\u202es3cr3t\\u200b"',
            'source = "s3cr3t@example.com:org/x.git"',
            'source = "~s3cr3t-no-such-user/x.git"',
            'source = "https://alice:s3cr3t@example.com/x.git"',
            'source = "https://ghp_s3cr3t\uff20example.com/x.git"',
            'source = "ssh://git\uff1as3cr3t@example.com/x.git"',
            'source = "s3cr3t://example.com/x.git"',
            'source = "https://example.com/s3cr3t x.git"',
            'source = "https://example.com/x.git?private_token=s3cr3t"',
            'source = "https://example.com/x.git#s3cr3t"',
            'source = "https://[alice:s3cr3t]/x.git"',
            'source = "ssh://git@[s3cr3t:tok]/x.git"',
            'source = "file://s3cr3t/x.git"',
            'source = "https:///s3cr3t"',
            'source = "https://example.com:s3cr3t/x.git"',
            'source = "ssh://git@example.com:s3cr3t/x.git"',
        ):
            with self.subTest(line=line):
                write(self.consumer / ".skill-ci.toml", f'version = "latest"\n{line}\n')
                result = self.skill_ci("lint", **self.shimmed())
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertRegex(result.stderr, r"^skill-ci: \.skill-ci\.toml: source [^\n]+\n$")
                self.assertNotIn("s3cr3t", result.stderr)
                self.assertFalse(self.cache.exists(), "nothing was cached")
                self.assertFalse(self.git_log.exists(), "git never ran")

    def test_an_ssh_source_reaches_git_and_uv_with_its_user_and_a_lowercase_scheme(self) -> None:
        serving = write(self.root / "serving-ssh", '#!/bin/sh\nshift\neval "exec $1"\n')
        serving.chmod(0o755)
        source = f"ssh://git@localhost{self.source}"
        for scheme in ("ssh", "SSH"):
            with self.subTest(scheme=scheme):
                self.uv_log.unlink(missing_ok=True)
                shutil.rmtree(self.cache, ignore_errors=True)
                write(self.consumer / ".skill-ci.toml", f'version = "latest"\nsource = "{scheme}{source.removeprefix("ssh")}"\n')
                result = self.skill_ci("lint", GIT_SSH_VARIANT="simple", GIT_SSH_COMMAND=str(serving))
                self.assertEqual(result.returncode, 3, result.stderr)
                [handed] = [json.loads(line) for line in self.uv_log.read_text().splitlines()]
                self.assertEqual(handed["arguments"][5], f"git+{source}@{self.commits['v0.10.0']}")
                cached, record = self.cache_record()
                self.assertEqual((cached, record["source"]), (pin.cache_file(self.cache / "skill-ci", source), source))

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

    def test_a_floating_pin_reads_a_fresh_cache_without_the_network(self) -> None:
        for version, commit in (("main", self.main), ("latest", self.commits["v0.10.0"])):
            with self.subTest(version=version):
                shutil.rmtree(self.cache, ignore_errors=True)
                self.git_log.unlink(missing_ok=True)
                self.pin(version)
                shimmed = self.shimmed()
                self.handed_off(self.skill_ci("lint", **shimmed), commit, "lint")
                self.assertEqual(self.git_log.read_text(), f"ls-remote {self.source.as_uri()} refs/heads/main refs/tags/v*\n")
                self.git_log.unlink()
                result = self.skill_ci("lint", **shimmed)
                self.handed_off(result, commit, "lint")
                self.assertFalse(self.git_log.exists(), "a fresh cache answers a floating pin without git")
                self.assertEqual(result.stderr.splitlines(), [f"skill-ci {version if version == 'main' else 'v0.10.0'} ({commit})"])

    def test_a_floating_pin_asks_the_source_when_the_cache_is_old_future_dated_foreign_or_missing(self) -> None:
        old = {"fetched_at": (datetime.now(UTC) - timedelta(days=2)).isoformat()}
        future = {"fetched_at": "2099-01-01T00:00:00+00:00"}
        foreign = {"source": "https://git.example.com/skill-ci.git"}
        for version in ("main", "latest"):
            for state, changes in (("old", old), ("future-dated", future), ("from another source", foreign), ("missing", None)):
                with self.subTest(version=version, cache=state):
                    shutil.rmtree(self.cache, ignore_errors=True)
                    self.git_log.unlink(missing_ok=True)
                    self.pin(version)
                    shimmed = self.shimmed()
                    self.skill_ci("lint", **shimmed)
                    self.uv_log.unlink()
                    self.git_log.unlink()
                    if changes is None:
                        shutil.rmtree(self.cache)
                    else:
                        self.rewrite_cache(**changes)
                    result = self.skill_ci("lint", **shimmed)
                    self.assertEqual(result.returncode, 3, result.stderr)
                    self.assertEqual(self.git_log.read_text(), f"ls-remote {self.source.as_uri()} refs/heads/main refs/tags/v*\n")
                    self.assertNotIn("warning", result.stderr)
                    self.uv_log.unlink()

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
            "[" * 200_000 + "]" * 200_000,
        ):
            with self.subTest(text=text[:80]):
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


class StillRunningTests(unittest.TestCase):
    def test_a_zombie_counts_as_gone_and_a_live_process_as_running(self) -> None:
        zombie = subprocess.Popen(["true"])
        self.addCleanup(zombie.wait)
        self.assertFalse(still_running(zombie.pid))
        live = subprocess.Popen(["sleep", "30"])
        self.addCleanup(live.wait)
        self.addCleanup(live.kill)
        self.assertTrue(still_running(live.pid))


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


class CacheReadTests(unittest.TestCase):
    def test_a_cache_path_that_is_not_a_regular_file_counts_as_no_cache(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="skill-ci-cache-")
        self.addCleanup(temporary.cleanup)
        cache = Path(temporary.name)
        source = "https://git.example.com/skill-ci.git"
        fifo = pin.cache_file(cache, source)
        fifo.parent.mkdir(parents=True)
        os.mkfifo(fifo)
        found: list[pin.Refs | None] = []
        reader = threading.Thread(target=lambda: found.append(pin.read_cache(cache, source)), daemon=True)
        reader.start()
        reader.join(timeout=1)

        def release() -> None:
            # A writer that opens and closes the FIFO ends a read that is waiting on it.
            with contextlib.suppress(OSError):
                os.close(os.open(fifo, os.O_WRONLY | os.O_NONBLOCK))
            reader.join()

        self.addCleanup(release)
        self.assertFalse(reader.is_alive(), "read_cache still waits on the FIFO after 1 s")
        self.assertEqual(found, [None])


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
            ({"SKILL_CI_PINNED": self.commits["v0.9.0"][:12], "PYTHONPATH": installed}, f"SKILL_CI_PINNED is '{self.commits['v0.9.0'][:12]}', not a full commit"),
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

    def test_a_child_that_cannot_mark_its_start_stops_before_the_command(self) -> None:
        self.pin("v0.9.0")
        marker = self.root / "removed" / "started"
        child = {**self.running(self.commits["v0.9.0"]), "SKILL_CI_PINNED": self.commits["v0.9.0"], "SKILL_CI_STARTED": str(marker)}
        result = self.skill_ci("check", "--fast", **child)
        self.assertEqual(result.returncode, 126, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, f"skill-ci: cannot record that the pinned commit started: [Errno 2] No such file or directory: '{marker}'\n")

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
        self.assertEqual(list(self.scratch.iterdir()), [])

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
                self.refused(self.skill_ci("check", "--fast", **self.shimmed(), **variables), problems)
        self.assertFalse(self.git_log.exists())

    def test_a_pin_on_the_running_commit_reports_an_unknown_key_without_a_hand_off(self) -> None:
        self.pin("v0.10.0", 'skils_dir = "skills"')
        result = self.skill_ci("check", "--fast", **self.running(self.commits["v0.10.0"]))
        self.refused(result, [f"skill-ci v0.10.0 ({self.commits['v0.10.0']})", UNKNOWN_KEY])
        self.assertEqual(result.stdout, "")

    def test_a_direct_child_run_reports_an_unknown_key_and_nothing_else(self) -> None:
        self.pin("v0.9.1", 'skils_dir = "skills"')
        child = {**self.running(self.commits["v0.9.0"]), "SKILL_CI_PINNED": self.commits["v0.9.0"]}
        result = self.skill_ci("check", "--fast", **child)
        self.refused(result, [UNKNOWN_KEY])
        self.assertEqual(result.stdout, "")

    def test_a_deleted_or_unreadable_working_directory_still_runs(self) -> None:
        for breaking_command in ("rmdir", "chmod 000"):
            with self.subTest(cwd=breaking_command):
                version, lint, update = (
                    run_in_a_broken_cwd(self.consumer / f"{breaking_command} {arguments[0]}", breaking_command, str(INSTALLED_COMMAND), *arguments)
                    for arguments in (("--version",), ("lint", "--skills-dir", str(self.consumer / "skills")), ("update",))
                )
                self.assertEqual(version.returncode, 0, version.stderr)
                self.assertRegex(version.stdout, r"^skill-ci \S+ \(commit unknown\)\n$")
                self.assertEqual(lint.returncode, 0, lint.stderr)
                self.assertEqual(lint.stdout, "checks run: 2; failed: 0\n")
                self.assertEqual(update.returncode, 2, update.stderr)
                # With a venv path over 127 characters, uv writes an sh trampoline, and sh adds its own getcwd error.
                self.assertEqual(
                    [line for line in update.stderr.splitlines() if line.startswith("skill-ci")][1:],
                    ["skill-ci: no .skill-ci.toml in the working directory, or in a parent directory inside the same git repository"],
                )

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
        self.retrying = f"skill-ci: uv could not start the pinned commit {self.commits['v0.10.0']} offline; trying again with network access"

    def attempts(self, *modes: str) -> list[list[str]]:
        calls = [json.loads(line)["arguments"] for line in self.uv_log.read_text().splitlines()]
        self.uv_log.unlink()
        self.assertEqual(
            calls, [["tool", "run", *mode.split(), "--isolated", "--from", f"git+{self.source.as_uri()}@{self.commits['v0.10.0']}", "skill-ci", "lint"] for mode in modes]
        )

    def test_a_built_pinned_commit_runs_offline_when_the_package_index_is_unreachable(self) -> None:
        result = self.skill_ci("lint", FAKE_UV_FAILS="online")
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(result.stderr.splitlines(), [self.banner])
        self.attempts("--offline")

    def test_a_first_build_tries_offline_and_then_once_with_network_access(self) -> None:
        result = self.skill_ci("lint", FAKE_UV_FAILS="offline")
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(result.stderr.splitlines(), [self.banner, OFFLINE_UV_ERROR, self.retrying])
        self.attempts("--offline", "")

    def test_a_uv_failure_before_the_pinned_commit_starts_names_the_commit(self) -> None:
        for variables, last_error in (({}, ONLINE_UV_ERROR), ({"UV_OFFLINE": "1"}, OFFLINE_UV_ERROR)):
            with self.subTest(**variables):
                failed = self.skill_ci("lint", FAKE_UV_FAILS="always", **variables)
                self.assertEqual(failed.returncode, 126, failed.stderr)
                self.assertEqual(
                    failed.stderr.splitlines(),
                    [
                        self.banner,
                        OFFLINE_UV_ERROR,
                        self.retrying,
                        last_error,
                        f"skill-ci: uv could not start the pinned commit {self.commits['v0.10.0']}; see the uv error above",
                    ],
                )
                self.attempts("--offline", "")
        killed = self.skill_ci("lint", FAKE_UV_DIES="1")
        self.assertEqual(killed.returncode, 128 + signal.SIGTERM, killed.stderr)
        self.assertEqual(killed.stderr.splitlines(), [self.banner])
        self.attempts("--offline")
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_a_pin_on_another_commit_hands_off_once_and_the_child_reports_an_unknown_key(self) -> None:
        self.pin("v0.10.0", 'skils_dir = "skills"')
        installed = fake_git_install(self.root / "installed by uv", self.commits["v0.10.0"])
        result = self.skill_ci("check", "--fast", FAKE_UV_CHILD=str(installed), FAKE_UV_COMMAND=str(INSTALLED_COMMAND))
        self.handed_off(result, self.commits["v0.10.0"], "check", "--fast", status=2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr.splitlines(), [self.banner, UNKNOWN_KEY])

    def test_the_pinned_commit_keeps_its_own_exit_code_and_runs_once(self) -> None:
        for code in (0, 1, 2):
            with self.subTest(code=code):
                result = self.skill_ci("lint", FAKE_UV_EXIT=str(code))
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertEqual(result.stderr.splitlines(), [self.banner])
                self.attempts("--offline")

    def test_a_hand_off_under_faulthandler_keeps_the_pinned_commits_exit_code(self) -> None:
        result = self.skill_ci("lint", FAKE_UV_EXIT="4", PYTHONFAULTHANDLER="1")
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertEqual(result.stderr.splitlines(), [self.banner])


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

    def test_update_on_a_floating_pin_fetches_refreshes_the_cache_and_leaves_the_file(self) -> None:
        for version in ("main", "latest"):
            with self.subTest(version=version):
                shutil.rmtree(self.cache, ignore_errors=True)
                text = f'# Float on purpose.\nversion = "{version}"  # keep\nsource = "{self.source}"\n'
                path = write(self.consumer / ".skill-ci.toml", text)
                self.skill_ci("lint")
                self.uv_log.unlink()
                hour_ago = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
                self.rewrite_cache(fetched_at=hour_ago)
                name, commit = (version, self.push_commit("main moves")) if version == "main" else ("v0.10.0", self.commits["v0.10.0"])
                self.git_log.unlink(missing_ok=True)
                result = self.skill_ci("update", **self.shimmed())
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    result.stdout,
                    f".skill-ci.toml: version is {version}, which floats, so the file is unchanged; it now runs {name} ({commit})\n",
                )
                self.assertEqual(self.git_log.read_text(), f"ls-remote {self.source.as_uri()} refs/heads/main refs/tags/v*\n")
                self.assertEqual(path.read_text(), text)
                self.assertGreater(datetime.fromisoformat(self.cache_record()[1]["fetched_at"]), datetime.fromisoformat(hour_ago))
                self.assertFalse(self.uv_log.exists())

    def test_update_on_a_floating_pin_needs_the_source_even_with_a_fresh_cache(self) -> None:
        for version in ("main", "latest"):
            for cached in (True, False):
                with self.subTest(version=version, cached=cached):
                    shutil.rmtree(self.cache, ignore_errors=True)
                    self.pin(version)
                    if cached:
                        self.skill_ci("lint")
                        self.uv_log.unlink()
                    self.unreachable()
                    result = self.skill_ci("update")
                    (self.root / "moved.git").rename(self.source)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertEqual(result.stdout, "")
                    self.assertRegex(result.stderr, rf"^skill-ci \S+ \(commit unknown\)\nskill-ci: cannot reach {re.escape(self.source.as_uri())} \(.*\)\n$")
                    self.assertEqual((self.consumer / ".skill-ci.toml").read_text(), f'version = "{version}"\nsource = "{self.source}"\n')

    def test_a_write_that_fails_leaves_the_file_whole(self) -> None:
        path = self.pin("v0.9.0", "# " + "padding " * 1000)
        before = path.read_bytes()
        listing = sorted(os.listdir(self.consumer))
        limited = (
            "import os, resource, sys\n"
            "resource.setrlimit(resource.RLIMIT_FSIZE, (4096, resource.getrlimit(resource.RLIMIT_FSIZE)[1]))\n"
            "os.execv(sys.argv[1], sys.argv[1:])\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", limited, str(INSTALLED_COMMAND), "update"],
            cwd=self.consumer,
            env=self.environment,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertRegex(result.stderr.splitlines()[-1], r"^skill-ci: cannot update \.skill-ci\.toml: \[Errno \d+\] File too large$")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(sorted(os.listdir(self.consumer)), listing)

    def test_update_replaces_the_file_a_link_names_and_keeps_its_mode(self) -> None:
        target = write(self.root / "shared" / "pin.toml", f'version = "v0.9.0"\nsource = "{self.source}"\n')
        target.chmod(0o640)
        link = self.consumer / ".skill-ci.toml"
        link.symlink_to(target)
        result = self.skill_ci("update")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(link.is_symlink())
        self.assertEqual(target.read_text(), f'version = "v0.10.0"\nsource = "{self.source}"\n')
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o640)
        self.assertEqual(os.listdir(target.parent), ["pin.toml"])

    def test_update_needs_the_source(self) -> None:
        self.pin("v0.9.0")
        self.unreachable()
        result = self.skill_ci("update")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertRegex(result.stderr, rf"^skill-ci \S+ \(commit unknown\)\nskill-ci: cannot reach {self.source.as_uri()} \(.*\)\n$")
        self.assertEqual((self.consumer / ".skill-ci.toml").read_text(), f'version = "v0.9.0"\nsource = "{self.source}"\n')


if __name__ == "__main__":
    unittest.main()
