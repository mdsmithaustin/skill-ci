#!/usr/bin/env python3
"""Regression tests for the repository PII gate."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


PII_CHECK = Path(__file__).with_name("check-pii.py")
SPEC = spec_from_file_location("check_pii", PII_CHECK)
assert SPEC and SPEC.loader
CHECK_PII = module_from_spec(SPEC)
sys.modules[SPEC.name] = CHECK_PII
SPEC.loader.exec_module(CHECK_PII)


class PiiCheck(unittest.TestCase):
    def check(self, content: str, *, suffix: str = ".txt") -> tuple[int, str]:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / f"fixture{suffix}"
            target.write_text(content, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(PII_CHECK), str(target)],
                capture_output=True,
                text=True,
            )
        return result.returncode, result.stdout

    def test_clean_text_passes(self) -> None:
        self.assertEqual(self.check("A safe documentation example.\n"), (0, ""))

    def test_daily_exact_local_schedule_fails_without_echoing_the_value(self) -> None:
        schedule = "".join(
            ("The sync runs daily at ", "9:", "17 PM local time.\n")
        )
        code, output = self.check(schedule)
        self.assertEqual(code, 1)
        self.assertIn("local automation schedule", output)
        self.assertNotIn(schedule.strip(), output)

    def test_launch_agent_path_fails_without_echoing_the_value(self) -> None:
        path = "~/Library/Launch" + "Agents/com.example.sync.plist"
        code, output = self.check(f"Install {path}.\n")
        self.assertEqual(code, 1)
        self.assertIn("LaunchAgent path", output)
        self.assertNotIn(path, output)

    def test_home_relative_log_path_fails_without_echoing_the_value(self) -> None:
        path = "~/" + ".local/state/example/" + "sync.log"
        code, output = self.check(f"Logs are written to {path}.\n")
        self.assertEqual(code, 1)
        self.assertIn("home-relative log path", output)
        self.assertNotIn(path, output)

    def test_generic_github_workflow_and_secret_name_pass(self) -> None:
        content = (
            "See .github/workflows/upstream-sync.yml and configure "
            "secrets.CLAUDE_CODE_OAUTH_TOKEN.\n"
        )
        self.assertEqual(self.check(content), (0, ""))

    def test_normal_schedules_pass(self) -> None:
        examples = (
            "The GitHub workflow runs daily.\n",
            "The maintenance window starts at 02:00 UTC.\n",
            "Cron example: 15 4 * * *.\n",
            "Office hours start at 9:17 PM local time.\n",
        )
        for example in examples:
            with self.subTest(example=example):
                self.assertEqual(self.check(example), (0, ""))

    def test_unrelated_filesystem_paths_pass(self) -> None:
        examples = (
            "/usr/local/bin/python3\n",
            "docs/runbook.md\n",
            "~/src/project/README.md\n",
            "/var/log/example.log\n",
        )
        for example in examples:
            with self.subTest(example=example):
                self.assertEqual(self.check(example), (0, ""))

    def test_checker_source_does_not_report_its_own_patterns(self) -> None:
        result = subprocess.run(
            [sys.executable, str(PII_CHECK), str(PII_CHECK)],
            capture_output=True,
            text=True,
        )
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_core_scans_in_memory_text_source(self) -> None:
        address = "lin" + "@" + "private.test"
        reports = CHECK_PII.findings(
            CHECK_PII.Source(name="memory", content=f"Contact {address}.\n")
        )
        self.assertEqual(reports, ["memory:1: possible email address"])

    def test_personal_email_fails_without_echoing_the_value(self) -> None:
        address = "ada" + "@" + "private.test"
        code, output = self.check(f"Contact {address}.\n")
        self.assertEqual(code, 1)
        self.assertIn("email address", output)
        self.assertNotIn(address, output)

    def test_documented_example_email_passes(self) -> None:
        address = "orch" + "@" + "example.com"
        self.assertEqual(self.check(f"git config user.email {address}\n"), (0, ""))

    def test_ssh_github_url_does_not_match_as_an_email(self) -> None:
        url = "ssh://" + "git" + "@" + "github.com/owner/repository"
        self.assertEqual(self.check(f"remote = {url}\n"), (0, ""))

    def test_dotted_personal_email_fails(self) -> None:
        address = "ada.lovelace" + "@" + "private.test"
        code, output = self.check(f"Contact {address}.\n")
        self.assertEqual(code, 1)
        self.assertIn("email address", output)
        self.assertNotIn(address, output)

    def test_us_social_security_number_fails(self) -> None:
        number = "123" + "-" + "45" + "-" + "6789"
        code, output = self.check(f"Identifier {number}.\n")
        self.assertEqual(code, 1)
        self.assertIn("US social security number", output)

    def test_luhn_valid_card_number_fails(self) -> None:
        card = "4242" + " " + "4242" + " " + "4242" + " " + "4242"
        code, output = self.check(f"Card {card}.\n")
        self.assertEqual(code, 1)
        self.assertIn("payment card number", output)

    def test_luhn_invalid_card_number_passes(self) -> None:
        card = "4242" + " " + "4242" + " " + "4242" + " " + "4241"
        self.assertEqual(self.check(f"Reference {card}.\n"), (0, ""))

    def test_north_american_phone_number_fails(self) -> None:
        phone = "415" + "-" + "555" + "-" + "2671"
        code, output = self.check(f"Call {phone}.\n")
        self.assertEqual(code, 1)
        self.assertIn("North American phone number", output)

    def test_binary_file_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "fixture.bin"
            target.write_bytes(b"\x00" + b"x" * 32)
            result = subprocess.run(
                [sys.executable, str(PII_CHECK), str(target)],
                capture_output=True,
                text=True,
            )
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_staged_mode_scans_index_contents_not_working_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repository = Path(tmp)
            subprocess.run(["git", "init", "--quiet"], cwd=repository, check=True)
            target = repository / "fixture.txt"
            address = "grace" + "@" + "private.test"
            target.write_text(f"Contact {address}.\n", encoding="utf-8")
            subprocess.run(["git", "add", target.name], cwd=repository, check=True)
            target.write_text("Clean working tree content.\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(PII_CHECK), "--staged"],
                cwd=repository,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("fixture.txt:1: possible email address", result.stdout)
        self.assertNotIn(address, result.stdout)


if __name__ == "__main__":
    unittest.main()
