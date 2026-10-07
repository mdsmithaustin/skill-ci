from __future__ import annotations

import ast
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from support import INSTALLED_COMMAND, REPOSITORY, FakeHarness, fake_git_install, write
from test_pin import PinTestCase, still_running

STOPS = tuple(
    getattr(signal, name)
    for name in (
        "SIGINT", "SIGTERM", "SIGHUP", "SIGQUIT", "SIGUSR1", "SIGUSR2", "SIGALRM", "SIGPIPE",
        "SIGABRT", "SIGVTALRM", "SIGPROF", "SIGXCPU", "SIGPOLL", "SIGPWR",
    )
    if hasattr(signal, name)
)
SENT_BY_A_TERMINAL = tuple(getattr(signal, name) for name in ("SIGWINCH", "SIGINFO") if hasattr(signal, name))
GRACE = 3.0
SIGNALLED_FIRST = """\
import os, subprocess, sys
number, name, pids = int(os.environ.pop("DRIVER_SIGNAL")), os.environ.pop("DRIVER_BEFORE"), os.environ.pop("DRIVER_PIDS")
spawn = subprocess.Popen


class SignalledFirst(spawn):
    def __init__(self, args, *rest, **options):
        if name in (os.path.basename(str(argument)) for argument in args):
            os.kill(os.getpid(), number)
        super().__init__(args, *rest, **options)
        with open(pids, "a") as log:
            log.write(f"{self.pid}\\n")


subprocess.Popen = SignalledFirst
from skill_ci import cli
raise SystemExit(cli.main(sys.argv[1:]))
"""

FAKE_PINNED = """\
import os, signal, time
log = os.environ["FAKE_PINNED_SIGNALS"]
first = []
def record(number, frame):
    with open(log, "a") as received:
        received.write(f"{number}\\n")
    first.append(time.monotonic())
for number in signal.valid_signals() - {signal.SIGKILL, signal.SIGSTOP, signal.SIGCHLD}:
    signal.signal(number, record)
open(log + ".ready", "w").close()
while not first or time.monotonic() - first[0] < 0.5:
    time.sleep(0.01)
raise SystemExit(3)
"""


class ChildStopTests(PinTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.fake = FakeHarness(self.root)
        self.inner = write(self.root / "inner skill-ci", f'#!/bin/sh\nexec "{self.fake.python}" -m skill_ci "$@"\n')
        self.inner.chmod(0o755)
        self.driver = write(self.root / "driver.py", SIGNALLED_FIRST)
        self.pinned = write(self.root / "pinned skill-ci", f"#!{sys.executable}\n{FAKE_PINNED}")
        self.pinned.chmod(0o755)
        self.installed = fake_git_install(self.root / "installed", self.commits["v0.10.0"])

    def start(self, *command: str, output: Path | None = None, **variables: str) -> subprocess.Popen[bytes]:
        with open(output or os.devnull, "wb") as stdout:
            process = subprocess.Popen(
                command,
                cwd=self.consumer,
                env={**self.environment, "FAKE_HARNESS_LOG": str(self.fake.log), **variables},
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=subprocess.DEVNULL,
            )
        self.addCleanup(process.wait)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        return process

    def waiting(self) -> Path:
        return Path(tempfile.mkdtemp(dir=self.root))

    def harness_stage(self, waiting: Path, *command: str, **variables: str) -> subprocess.Popen[bytes]:
        return self.start(*command, "trigger", "skills/example", "--out", str(waiting / "out"), FAKE_HARNESS_WAIT=str(waiting), **variables)

    def direct(self, waiting: Path, **variables: str) -> subprocess.Popen[bytes]:
        (self.consumer / ".skill-ci.toml").unlink(missing_ok=True)
        return self.harness_stage(waiting, str(self.fake.python), "-I", "-m", "skill_ci", **variables)

    def handed_off(self, waiting: Path, **variables: str) -> subprocess.Popen[bytes]:
        self.pin("v0.10.0")
        handing = {"FAKE_UV_CHILD": str(self.installed), "FAKE_UV_COMMAND": str(self.inner), "FAKE_UV_SPAWNS": str(waiting / "uv")}
        return self.harness_stage(waiting, str(INSTALLED_COMMAND), **handing, **variables)

    def ready(self, path: Path, process: subprocess.Popen[bytes]) -> list[int]:
        deadline = time.monotonic() + 30
        while not path.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(path.exists(), f"{path.name} never appeared; skill-ci exited {process.returncode}")
        return [int(pid) for pid in path.read_text().split()]

    def survivors(self, *pids: int) -> list[int]:
        return [pid for pid in pids if still_running(pid)]

    def received(self, waiting: Path) -> list[int]:
        log = waiting / "received"
        return [int(line) for line in log.read_text().split()] if log.exists() else []

    def test_every_stopping_signal_during_a_harness_stage_stops_it_and_its_group(self) -> None:
        for number in STOPS:
            with self.subTest(signal=number.name):
                waiting = self.waiting()
                process = self.direct(waiting)
                pids = self.ready(waiting / "pids", process)
                os.kill(process.pid, number)
                self.assertEqual(process.wait(timeout=30), 128 + number)
                self.assertEqual(self.received(waiting), [signal.SIGINT])
                self.assertEqual(self.survivors(*pids), [])

    def test_every_stopping_signal_during_a_hand_off_stops_the_pinned_commit_and_its_harness(self) -> None:
        for number in STOPS:
            with self.subTest(signal=number.name):
                waiting = self.waiting()
                process = self.handed_off(waiting)
                pids = self.ready(waiting / "pids", process)
                uv, pinned = self.ready(waiting / "uv", process)
                os.kill(process.pid, number)
                self.assertEqual(process.wait(timeout=30), 128 + number)
                self.assertEqual(self.received(waiting), [signal.SIGINT])
                self.assertEqual(self.survivors(uv, pinned, *pids), [])

    def test_a_stop_during_the_hand_off_reaches_the_pinned_commit_as_one_sigint(self) -> None:
        self.pin("v0.10.0")
        for number in (signal.SIGPIPE, signal.SIGTERM):
            with self.subTest(signal=number.name):
                waiting = self.waiting()
                handing = {"FAKE_UV_CHILD": str(self.installed), "FAKE_UV_COMMAND": str(self.pinned), "FAKE_UV_SPAWNS": str(waiting / "uv")}
                process = self.start(str(INSTALLED_COMMAND), "lint", **handing, FAKE_PINNED_SIGNALS=str(waiting / "received"))
                self.ready(waiting / "received.ready", process)
                uv, pinned = self.ready(waiting / "uv", process)
                os.kill(process.pid, number)
                self.assertEqual(process.wait(timeout=10), 128 + number)
                self.assertEqual(self.received(waiting), [signal.SIGINT])
                self.assertEqual(self.survivors(uv, pinned), [])
                self.assertEqual(list(self.scratch.iterdir()), [])

    def test_a_signal_before_the_child_exists_stops_it_as_it_starts(self) -> None:
        transport = self.root / "transport"
        slow = write(self.root / "slow-ssh", f'#!/bin/sh\necho $$ >> "{transport}"\nexec sleep 30\n')
        slow.chmod(0o755)
        for child, version, source, command in (
            ("skill-trigger-matrix", None, None, (str(self.fake.python), "-I", str(self.driver), "trigger", "skills/example", "--out", "out")),
            ("uv", "v0.10.0", str(self.source), (sys.executable, str(self.driver), "lint")),
            ("git", "latest", "ssh://git@example.com/skill-ci.git", (sys.executable, str(self.driver), "lint")),
        ):
            with self.subTest(child=child):
                if version is not None:
                    write(self.consumer / ".skill-ci.toml", f'version = "{version}"\nsource = "{source}"\n')
                waiting = self.waiting()
                variables = {"DRIVER_SIGNAL": str(int(signal.SIGTERM)), "DRIVER_BEFORE": child, "DRIVER_PIDS": str(waiting / "spawned")}
                process = self.start(*command, **variables, FAKE_HARNESS_WAIT=str(waiting), FAKE_UV_SIGNALS=str(waiting / "uv"), GIT_SSH_COMMAND=str(slow))
                self.assertEqual(process.wait(timeout=30), 128 + signal.SIGTERM)
                spawned = [int(pid) for pid in (waiting / "spawned").read_text().split()]
                self.assertEqual(self.survivors(*spawned), [])
                transports = [int(pid) for pid in transport.read_text().split()] if transport.exists() else []
                self.assertEqual(self.survivors(*transports), [])
                self.assertEqual(list(self.scratch.iterdir()), [])

    def test_a_burst_of_signals_stops_once_with_the_first(self) -> None:
        transport = self.root / "transport"
        slow = write(self.root / "slow-ssh", f'#!/bin/sh\necho $$ > "{transport}.partial"\nmv "{transport}.partial" "{transport}"\nexec sleep 30\n')
        slow.chmod(0o755)
        for name in ("harness stage", "hand-off", "ls-remote"):
            with self.subTest(child=name):
                waiting = self.waiting()
                if name == "harness stage":
                    process = self.direct(waiting)
                    pids = self.ready(waiting / "pids", process)
                elif name == "hand-off":
                    process = self.handed_off(waiting)
                    pids = [*self.ready(waiting / "pids", process), *self.ready(waiting / "uv", process)]
                else:
                    write(self.consumer / ".skill-ci.toml", 'version = "latest"\nsource = "ssh://git@example.com/skill-ci.git"\n')
                    process = self.start(str(INSTALLED_COMMAND), "lint", GIT_SSH_COMMAND=str(slow))
                    pids = self.ready(transport, process)
                started = time.monotonic()
                os.kill(process.pid, signal.SIGTERM)
                # Pending signals are handled lowest number first, and SIGPROF is above SIGTERM on Linux and macOS.
                while process.poll() is None and time.monotonic() - started < 15:
                    os.kill(process.pid, signal.SIGPROF)
                    time.sleep(0.001)
                self.assertEqual(process.wait(timeout=1), 128 + signal.SIGTERM)
                self.assertLess(time.monotonic() - started, GRACE)
                self.assertEqual(self.survivors(*pids), [])

    def test_a_resize_or_a_status_request_reaches_no_child(self) -> None:
        for number in SENT_BY_A_TERMINAL:
            for name, start in (("harness stage", self.direct), ("hand-off", self.handed_off)):
                with self.subTest(signal=number.name, child=name):
                    waiting = self.waiting()
                    process = start(waiting)
                    pids = self.ready(waiting / "pids", process)
                    os.kill(process.pid, number)
                    time.sleep(0.5)
                    self.assertIsNone(process.poll())
                    self.assertEqual(self.received(waiting), [])
                    os.kill(process.pid, signal.SIGTERM)
                    self.assertEqual(process.wait(timeout=30), 128 + signal.SIGTERM)
                    self.assertEqual(self.survivors(*pids), [])

    def test_a_child_that_ignores_the_interrupt_is_killed_after_the_grace(self) -> None:
        for name, start in (("harness stage", self.direct), ("hand-off", self.handed_off)):
            with self.subTest(child=name):
                waiting = self.waiting()
                process = start(waiting, FAKE_HARNESS_DEAF="1")
                pids = self.ready(waiting / "pids", process)
                started = time.monotonic()
                os.kill(process.pid, signal.SIGTERM)
                self.assertEqual(process.wait(timeout=30), 128 + signal.SIGTERM)
                self.assertGreaterEqual(time.monotonic() - started, GRACE)
                self.assertEqual(self.received(waiting), [])
                self.assertEqual(self.survivors(*pids), [])

    def test_a_stop_during_a_git_call_ends_the_command(self) -> None:
        real = subprocess.run(["sh", "-c", "command -v git"], capture_output=True, text=True, check=True).stdout.strip()
        for command, blocked, number in ((("check", "--fast"), "diff", signal.SIGTERM), (("run", "skills/example"), "rev-parse", signal.SIGHUP)):
            with self.subTest(command=command[0]):
                waiting = self.waiting()
                shim = write(
                    waiting / "bin" / "git",
                    f'#!/bin/sh\nif [ "$1" = "{blocked}" ]; then echo $$ > "{waiting}/git.partial"; mv "{waiting}/git.partial" "{waiting}/git"; exec sleep 30; fi\nexec "{real}" "$@"\n',
                )
                shim.chmod(0o755)
                process = self.start(
                    str(self.fake.python), "-I", "-m", "skill_ci", *command,
                    output=waiting / "stdout", PATH=f"{shim.parent}{os.pathsep}{self.environment['PATH']}",
                )
                [git] = self.ready(waiting / "git", process)
                os.kill(process.pid, number)
                self.assertEqual(process.wait(timeout=30), 128 + number)
                self.assertNotIn("checks run:", (waiting / "stdout").read_text())
                self.assertEqual(self.survivors(git), [])
                self.assertEqual(self.fake.calls(), [])


class RunnerTests(unittest.TestCase):
    def test_only_the_runner_starts_a_child_process(self) -> None:
        spawning = {
            "subprocess": {"run", "Popen", "call", "check_call", "check_output", "getoutput", "getstatusoutput"},
            "os": {"system", "popen", "fork", "forkpty", "posix_spawn", "posix_spawnp", "spawnv", "spawnve", "spawnl", "spawnle", "spawnvp", "spawnvpe", "spawnlp", "spawnlpe"},
        }
        found = []
        for path in sorted((REPOSITORY / "src" / "skill_ci").rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(), str(path))):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.attr in spawning.get(node.value.id, ()):
                    found.append(f"{path.relative_to(REPOSITORY)}:{node.lineno} {node.value.id}.{node.attr}")
        self.assertEqual([line for line in found if not line.startswith("src/skill_ci/children.py:")], [])


if __name__ == "__main__":
    unittest.main()
