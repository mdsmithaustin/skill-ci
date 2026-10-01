#!/usr/bin/env python3
"""Regression tests for the repository PII gate."""
from __future__ import annotations

import os
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

    def test_enterprise_github_host_fails_without_echoing_it(self) -> None:
        host = "github." + "acme-corp.com"
        examples = {
            "url": f"remote https://{host}",
            "quoted": f'"{host}";',
            "backticked": f"Point it at `{host}`.",
            "prose": f"Our host is {host} for work.",
            "table cell": f"| host | {host} |",
            "parenthesized": f"({host})",
            "comma list": f"hosts={host},other",
            "statement end": f"url=https://{host};",
            "pipe list": f"hosts={host}|other",
            "query": f"https://{host}?tab=1",
            "fragment": f"https://{host}#readme",
            "sentence end": f"See https://{host}.",
            "escaped slash": f'"https:\\/\\/{host}\\/o"',
            "uppercase": f"https://{host.upper()}/x",
            "label before github": f"https://raw.{host}/x",
            "country code domain": '"github.' + 'acme.jp"',
            "lookalike of an example domain": "https://github." + "notexample.com/x",
        }
        for name, line in examples.items():
            with self.subTest(name):
                code, output = self.check(line + "\n")
                self.assertEqual(code, 1)
                self.assertIn(":1: possible GitHub Enterprise host", output)
                self.assertNotIn(host, output.casefold())

    def test_host_context_flags_a_host_on_any_top_level_domain(self) -> None:
        host = "github." + "corp.internal"
        examples = {
            "url": f"https://{host}/x",
            "scp remote": f"git@{host}:team/project.git",
            "hostname flag": f"gh api --hostname {host} user",
            "hostname flag with equals": f"gh api --hostname={host} user",
            "short host flag": f"gh auth login -h {host}",
            "GH_HOST": f"GH_HOST={host} gh pr view",
            "escaped newline": f'command.includes("--hostname\\n{host}\\n")',
            "escaped tab": f'"x\\t{host}"',
            "host key": f"host: {host}",
            "hostname key": f"hostname: {host}",
        }
        for name, line in examples.items():
            with self.subTest(name):
                code, output = self.check(line + "\n")
                self.assertEqual(code, 1)
                self.assertIn(":1: possible GitHub Enterprise host", output)
                self.assertNotIn(host, output)

    def test_public_reserved_and_github_owned_hosts_pass(self) -> None:
        examples = {
            "github.com": "https://github.com/owner/repository",
            "api.github.com": "https://api.github.com/repos",
            "pages": "https://owner.github.io/site",
            "example.com": "https://github.example.com/team/project",
            "example.net": "https://github.example.net/team/project",
            "example.org": "https://github.example.org/team/project",
            ".example": "https://github.corp.example/x",
            ".test": "host: github.corp.test",
            ".invalid": "https://github.corp.invalid/x",
            ".localhost": "https://github.corp.localhost/x",
            "githubassets.com": "https://github.githubassets.com/assets/app.js",
            "githubusercontent.com": "https://github.githubusercontent.com/x",
        }
        for name, line in examples.items():
            with self.subTest(name):
                self.assertEqual(self.check(line + "\n"), (0, ""))

    def test_dotted_names_outside_a_host_context_pass(self) -> None:
        examples = {
            "actions expression": "if: ${{ github.event.number }}",
            "quoted actions expression": 'run: echo "github.event.number is set"',
            "backticked expression": "Read `github.event.inputs.name` in the step.",
            "expression ending in a domain-like label": "run: echo ${{ github.event.co_author }}",
            "editor setting": '"github.copilot.enable": {',
            "module string": "require('github.something.js')",
            "class path": "'github.MainClass.Github'",
            "internal domain outside a host context": '"github.corp.internal"',
        }
        for name, line in examples.items():
            with self.subTest(name):
                self.assertEqual(self.check(line + "\n"), (0, ""))

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

    def email_report(self, content: str, suffix: str) -> tuple[int, str]:
        code, output = self.check(content, suffix=suffix)
        return code, output.rpartition("/")[2]

    def test_address_opening_a_diff_line_fails_and_a_decorator_passes(self) -> None:
        address = "alice" + "@" + "corp.io"
        finding = (1, "fixture.patch:1: possible email address\n")
        self.assertEqual(self.email_report(f"+{address}\n", ".patch"), finding)
        self.assertEqual(self.email_report(f"-{address}\n", ".patch"), finding)
        self.assertEqual(self.check("+@pytest.mark.parametrize(\n", suffix=".patch"), (0, ""))

    def test_address_after_a_sign_in_markdown_fails_and_a_hex_hash_passes(self) -> None:
        address = "alice" + "@" + "corp.io"
        finding = (1, "fixture.md:1: possible email address\n")
        self.assertEqual(self.email_report(f"+{address}\n", ".md"), finding)
        self.assertEqual(self.email_report(f"-{address}\n", ".md"), finding)
        digest = "sha256:513a" + "37841" + "04839770" + "d690e0"
        self.assertEqual(self.check(f"hash = {digest}\n", suffix=".md"), (0, ""))

    def test_address_whose_local_part_opens_with_a_symbol_fails(self) -> None:
        address = "alice" + "@" + "corp.io"
        finding = (1, "fixture.py:1: possible email address\n")
        self.assertEqual(self.email_report(f"email = '{address}'\n", ".py"), finding)
        self.assertEqual(self.email_report(f"owner = `{address}`\n", ".py"), finding)
        self.assertEqual(self.email_report(f"_{address}\n", ".py"), finding)
        self.assertEqual(self.email_report("+tag" + "@" + "corp.io\n", ".py"), finding)
        self.assertEqual(self.check("-@decorator.name\n", suffix=".py"), (0, ""))

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
        environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        with tempfile.TemporaryDirectory() as tmp:
            repository = Path(tmp)
            subprocess.run(["git", "init", "--quiet"], cwd=repository, env=environment, check=True)
            target = repository / "fixture.txt"
            address = "grace" + "@" + "private.test"
            target.write_text(f"Contact {address}.\n", encoding="utf-8")
            subprocess.run(["git", "add", target.name], cwd=repository, env=environment, check=True)
            target.write_text("Clean working tree content.\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(PII_CHECK), "--staged"],
                cwd=repository,
                env=environment,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("fixture.txt:1: possible email address", result.stdout)
        self.assertNotIn(address, result.stdout)

    def test_staged_fixture_preserves_the_calling_hooks_repository(self) -> None:
        environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        with tempfile.TemporaryDirectory() as tmp:
            caller = Path(tmp)
            subprocess.run(["git", "init", "--quiet"], cwd=caller, env=environment, check=True)
            (caller / "sentinel.txt").write_text("Keep this staged content.\n", encoding="utf-8")
            subprocess.run(["git", "add", "sentinel.txt"], cwd=caller, env=environment, check=True)
            git_dir = caller / ".git"
            config_before = (git_dir / "config").read_bytes()
            index_before = (git_dir / "index").read_bytes()
            hook_environment = environment | {
                "GIT_DIR": str(git_dir),
                "GIT_WORK_TREE": ".",
                "GIT_INDEX_FILE": str(git_dir / "index"),
            }
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "PiiCheck.test_staged_mode_scans_index_contents_not_working_tree"],
                cwd=caller,
                env=hook_environment,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((git_dir / "config").read_bytes(), config_before)
            self.assertEqual((git_dir / "index").read_bytes(), index_before)


if __name__ == "__main__":
    unittest.main()
