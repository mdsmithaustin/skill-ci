from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import venv
from pathlib import Path
import run_runner


REPOSITORY = Path(__file__).resolve().parents[1]
VALID_SPEC = "git+https://github.com/mdsmithaustin/skill-eval-harness.git@0123456789abcdef0123456789abcdef01234567"


class RunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="skill-ci-runner-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.checkout = self.root / "checkout"
        self.tools = self.checkout / "tools"
        self.tools.mkdir(parents=True)
        self.dispatcher = self.tools / "run_runner.py"
        shutil.copy2(REPOSITORY / "tools" / "run_runner.py", self.dispatcher)
        self.lock = self.checkout / "runner.lock"
        self.lock.write_text(f"{VALID_SPEC}\n", encoding="utf-8")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "uv.jsonl"
        self.write_executable(
            self.bin / "uv",
            "import json, os, sys\n"
            "args = sys.argv[1:]\n"
            "if args[:3] == ['run', '--no-project', 'python']:\n"
            "    os.execv(sys.executable, [sys.executable, *args[3:]])\n"
            "if args[:2] != ['tool', 'run']:\n"
            "    raise SystemExit(9)\n"
            "command = next(arg for arg in args if arg in {'skill-benchmark', 'skill-trigger-matrix'})\n"
            "index = args.index(command)\n"
            "record = {'argv': args, 'command': command, 'arguments': args[index + 1:], 'cwd': os.getcwd(), 'claude_config_dir': os.environ.get('CLAUDE_CONFIG_DIR')}\n"
            "with open(os.environ['RUNNER_LOG'], 'a', encoding='utf-8') as output:\n"
            "    output.write(json.dumps(record) + '\\n')\n"
            "raise SystemExit(int(os.environ.get('RUNNER_EXIT', '0')))\n",
        )

    def write_executable(self, path: Path, body: str) -> None:
        path.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
        path.chmod(0o755)

    def environment(self, **changes: str) -> dict[str, str]:
        return {
            **os.environ,
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "RUNNER_LOG": str(self.log),
            "CLAUDE_CONFIG_DIR": "host-login",
            **changes,
        }

    def execute(self, *arguments: str, **changes: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.dispatcher), *arguments],
            cwd=self.root,
            env=self.environment(**changes),
            capture_output=True,
            text=True,
            check=False,
        )

    def recorded(self) -> list[dict[str, object]]:
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def test_parser_accepts_comments_and_whitespace(self) -> None:
        pin = run_runner.parse_lock(f"\n # a note\n {VALID_SPEC} \n\n")
        self.assertEqual(pin.spec, VALID_SPEC)

    def test_parser_rejects_unapproved_or_ambiguous_specs(self) -> None:
        invalid = (
            "",
            "# only a comment\n",
            f"{VALID_SPEC}\n{VALID_SPEC}\n",
            "PIN_ME\n",
            "git+https://github.com/mdsmithaustin/skill-eval-harness.git@main\n",
            "git+https://github.com/mdsmithaustin/skill-eval-harness.git@0123456\n",
            "git+https://github.com/other/skill-eval-harness.git@0123456789abcdef0123456789abcdef01234567\n",
            "git+https://gitlab.com/mdsmithaustin/skill-eval-harness.git@0123456789abcdef0123456789abcdef01234567\n",
            f"{VALID_SPEC}#extra\n",
        )
        for text in invalid:
            with self.subTest(text=text):
                with self.assertRaises(run_runner.LockError):
                    run_runner.parse_lock(text)

    def test_invalid_lock_exits_before_uv(self) -> None:
        self.lock.write_text("PIN_ME\n", encoding="utf-8")
        result = self.execute("skill-benchmark", "--help")
        self.assertEqual(result.returncode, 2)
        self.assertIn("must pin", result.stderr)
        self.assertFalse(self.log.exists())

    def test_missing_lock_exits_before_uv(self) -> None:
        self.lock.unlink()
        result = self.execute("skill-benchmark", "--help")
        self.assertEqual(result.returncode, 2)
        self.assertIn("could not read", result.stderr)
        self.assertFalse(self.log.exists())

    def test_invalid_command_exits_before_uv(self) -> None:
        result = self.execute("other-runner", "--help")
        self.assertEqual(result.returncode, 2)
        self.assertIn("expected skill-benchmark", result.stderr)
        self.assertFalse(self.log.exists())

    def test_missing_uv_has_a_focused_exit_code(self) -> None:
        empty_path = self.root / "empty-path"
        empty_path.mkdir()
        result = subprocess.run(
            [sys.executable, str(self.dispatcher), "skill-benchmark", "--help"],
            cwd=self.root,
            env=self.environment(PATH=str(empty_path)),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 127)
        self.assertEqual(result.stderr, "run_runner: uv is required to run the pinned runner\n")

    def test_dispatcher_preserves_arguments_cwd_environment_and_exit_code(self) -> None:
        result = self.execute("skill-benchmark", "validate", "a path/with spaces", RUNNER_EXIT="7")
        self.assertEqual(result.returncode, 7, result.stderr)
        [record] = self.recorded()
        self.assertEqual(record["arguments"], ["validate", "a path/with spaces"])
        self.assertEqual(record["cwd"], str(self.root.resolve()))
        self.assertEqual(record["claude_config_dir"], "host-login")
        self.assertEqual(
            record["argv"][:7],
            ["tool", "run", "--isolated", "--from", VALID_SPEC, "python", "-I"],
        )

    def test_lock_change_controls_the_next_invocation(self) -> None:
        self.assertEqual(self.execute("skill-benchmark", "--help").returncode, 0)
        next_spec = "git+https://github.com/mdsmithaustin/skill-eval-harness.git@fedcba9876543210fedcba9876543210fedcba98"
        self.lock.write_text(f"{next_spec}\n", encoding="utf-8")
        self.assertEqual(self.execute("skill-benchmark", "--version").returncode, 0)
        records = self.recorded()
        self.assertEqual(records[0]["argv"][4], VALID_SPEC)
        self.assertEqual(records[1]["argv"][4], next_spec)

    def test_absolute_dispatcher_never_falls_back_to_path(self) -> None:
        environment = self.root / "environment"
        venv.create(environment, with_pip=False)
        scripts = environment / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        safe = scripts / "skill-benchmark"
        hostile = self.bin / "skill-benchmark"
        marker = self.root / "marker"
        safe.write_text("#!/bin/sh\nprintf safe > \"$RUNNER_MARKER\"\n", encoding="utf-8")
        hostile.write_text("#!/bin/sh\nprintf hostile > \"$RUNNER_MARKER\"\n", encoding="utf-8")
        safe.chmod(0o755)
        hostile.chmod(0o755)
        result = subprocess.run(
            [str(python), "-I", "-c", run_runner.BOOTSTRAP, "skill-benchmark", "argument"],
            env=self.environment(RUNNER_MARKER=str(marker)),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(marker.read_text(encoding="utf-8"), "safe")
        safe.unlink()
        marker.unlink()
        missing = subprocess.run(
            [str(python), "-I", "-c", run_runner.BOOTSTRAP, "skill-benchmark"],
            env=self.environment(RUNNER_MARKER=str(marker)),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(missing.returncode, 0)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
