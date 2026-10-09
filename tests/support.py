from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import time
import unittest
import venv
from pathlib import Path
from typing import Any

REPOSITORY = Path(__file__).resolve().parents[1]
INSTALLED_COMMAND = Path(sysconfig.get_path("scripts")) / "skill-ci"
# A git hook exports GIT_DIR and GIT_INDEX_FILE, which would point every fixture repository at the real one.
# A shell that exports SKILL_CI_DEBUG=1 would turn the one-line errors the tests check into tracebacks.
ENVIRONMENT = {key: value for key, value in os.environ.items() if not key.startswith(("GIT_", "SKILL_CI_"))}
PLANTED_EMAIL = "@".join(("jane.doe", "corp-mail.net"))
ISOLATED_GIT = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "skill-ci tests",
    "GIT_AUTHOR_EMAIL": "tests@example.com",
    "GIT_COMMITTER_NAME": "skill-ci tests",
    "GIT_COMMITTER_EMAIL": "tests@example.com",
}
FAKE_HARNESS = """\
import json, os, signal, subprocess, sys, time
arguments = sys.argv[1:]
record = {
    "command": os.path.basename(sys.argv[0]),
    "arguments": arguments,
    "cwd": os.getcwd(),
    "inherited": os.environ.get("FAKE_HARNESS_INHERITED"),
    "skill_ci_variables": sorted(key for key in os.environ if key.startswith("SKILL_CI_")),
}
with open(os.environ["FAKE_HARNESS_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(record) + "\\n")
failing = os.environ.get("FAKE_HARNESS_FAIL_STAGE")
stage = arguments[0] if arguments else ""
if (killed := os.environ.get("FAKE_HARNESS_SIGNAL")) and (not failing or failing == stage):
    os.kill(os.getpid(), int(killed))
if waiting := os.environ.get("FAKE_HARNESS_WAIT"):
    with open(os.path.join(waiting, "ignored"), "w") as log:
        log.write(" ".join(str(int(number)) for number in signal.valid_signals() if signal.getsignal(number) == signal.SIG_IGN))
    def record(number, frame):
        with open(os.path.join(waiting, "received"), "a") as log:
            log.write(f"{number}\\n")
        raise SystemExit(100 + number)
    for number in signal.valid_signals() - {signal.SIGKILL, signal.SIGSTOP, signal.SIGCHLD}:
        signal.signal(number, record)
    if os.environ.get("FAKE_HARNESS_DEAF"):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    grandchild = subprocess.Popen(["sleep", "60"])
    with open(os.path.join(waiting, "pids.partial"), "w") as log:
        log.write(f"{os.getpid()} {grandchild.pid}")
    os.rename(os.path.join(waiting, "pids.partial"), os.path.join(waiting, "pids"))
    deadline = time.monotonic() + 60
    while not os.path.exists(os.path.join(waiting, "release")) and time.monotonic() < deadline:
        time.sleep(0.02)
    grandchild.kill()
    grandchild.wait()
raise SystemExit(int(os.environ.get("FAKE_HARNESS_EXIT", "0")) if not failing or failing == stage else 0)
"""
FAKE_UV = """\
import json, os, signal, subprocess, sys, time
with open(os.environ["FAKE_UV_LOG"], "a", encoding="utf-8") as log:
    record = {"arguments": sys.argv[1:], "pinned": os.environ.get("SKILL_CI_PINNED"), "pythonpath": os.environ.get("PYTHONPATH")}
    log.write(json.dumps(record) + "\\n")
arguments = sys.argv[sys.argv.index("skill-ci") + 1:]
offline = "--offline" in sys.argv or os.environ.get("UV_OFFLINE") == "1"
if os.environ.get("FAKE_UV_DIES"):
    os.kill(os.getpid(), signal.SIGTERM)
if os.environ.get("FAKE_UV_FAILS") in ("always", "offline" if offline else "online"):
    sys.exit("error: Remote Git fetches are not allowed because network connectivity is disabled" if offline else "error: Failed to fetch: https://pypi.org/simple/mdurl/")
if waiting := os.environ.get("FAKE_UV_WAITS"):
    signal.signal(signal.SIGINT, lambda number, frame: sys.exit(2))
    with open(waiting, "w") as log:
        log.write(str(os.getpid()))
    time.sleep(30)
if installed := os.environ.get("FAKE_UV_CHILD"):
    command = os.environ["FAKE_UV_COMMAND"]
    environment = {**os.environ, "PYTHONPATH": installed}
    if pids := os.environ.get("FAKE_UV_SPAWNS"):
        # Like uv 0.12.7, run the pinned skill-ci as a child in uv's group and pass on a signal sent to uv's pid.
        child = subprocess.Popen([command, *arguments], env=environment)
        for name in ("SIGINT", "SIGTERM", "SIGHUP", "SIGQUIT", "SIGUSR1", "SIGUSR2", "SIGALRM", "SIGWINCH", "SIGPIPE", "SIGINFO"):
            if hasattr(signal, name):
                signal.signal(getattr(signal, name), lambda number, frame: child.send_signal(number))
        with open(pids, "w") as log:
            log.write(f"{os.getpid()} {child.pid}")
        status = child.wait()
        raise SystemExit(128 - status if status < 0 else status)
    os.execve(command, [command, *arguments], environment)
open(os.environ["SKILL_CI_STARTED"], "x").close()
if received := os.environ.get("FAKE_UV_SIGNALS"):
    def record(number, frame):
        with open(received, "a") as log:
            log.write(f"{number}\\n")
        raise SystemExit(100 + number)
    for number in signal.valid_signals() - {signal.SIGKILL, signal.SIGSTOP}:
        signal.signal(number, record)
    with open(received + ".pid", "w") as log:
        log.write(str(os.getpid()))
    open(received, "w").close()
    time.sleep(30)
raise SystemExit(int(os.environ.get("FAKE_UV_EXIT", "3")))
"""


def skill_ci(*arguments: str, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(INSTALLED_COMMAND), *arguments],
        cwd=cwd,
        env=ENVIRONMENT if env is None else env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def run_in_a_broken_cwd(directory: Path, breaking_command: str, *command: str) -> subprocess.CompletedProcess[str]:
    directory.mkdir()
    return subprocess.run(
        ["/bin/sh", "-c", f'cd "$1" && {breaking_command} "$1" && shift && exec "$@"', "sh", str(directory), *command],
        env=ENVIRONMENT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def git(*arguments: str, cwd: Path, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(["git", *arguments], cwd=cwd, env=ENVIRONMENT if env is None else env, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def write_skill(directory: Path) -> Path:
    name = directory.name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Use when asked for {name}.\n---\n# {name}\n")
    return directory


def manifest(name: str, skill_paths: list[str], cases: list[dict[str, Any]] | None = None) -> str:
    return json.dumps(
        {
            "version": 2,
            "skill_name": name,
            "skill_description": f"Use when asked for {name}.",
            "skill_paths": skill_paths,
            "variants": ["with_skill", "without_skill"],
            "cases": [] if cases is None else cases,
        }
    )


def case(**changes: Any) -> dict[str, Any]:
    populated = {
        "id": "repair",
        "kind": "adversarial",
        "split": "tune",
        "prompt": "Repair the thing.",
        "assertions": [{"type": "contains", "name": "names-fix", "severity": "gate", "value": "repaired"}],
    }
    return {key: value for key, value in {**populated, **changes}.items() if value is not None}


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def fake_git_install(directory: Path, commit: str) -> Path:
    dist_info = directory / "skill_ci-1.0.0.dist-info"
    write(dist_info / "METADATA", "Metadata-Version: 2.1\nName: skill-ci\nVersion: 1.0.0\n")
    write(dist_info / "direct_url.json", json.dumps({"url": "https://git.example.com/skill-ci.git", "vcs_info": {"vcs": "git", "commit_id": commit}}))
    return directory


class FakeHarness:
    def __init__(self, root: Path, source: Path = REPOSITORY / "src") -> None:
        environment = root / "fake environment"
        venv.create(environment, with_pip=False)
        paths = sysconfig.get_paths(scheme="venv", vars={"base": str(environment), "platbase": str(environment)})
        self.scripts = Path(paths["scripts"])
        self.purelib = Path(paths["purelib"])
        self.python = self.scripts / "python"
        self.log = root / "harness.jsonl"
        (self.purelib / "skill_ci_source.pth").write_text(f"{source}\n{sysconfig.get_path('purelib')}\n")
        for command in ("skill-benchmark", "skill-trigger-matrix"):
            (self.scripts / command).write_text(FAKE_HARNESS)
            (self.scripts / command).chmod(0o755)

    def run(self, *arguments: str, cwd: Path, path: str | None = None, **variables: str) -> subprocess.CompletedProcess[str]:
        environment = {
            **ENVIRONMENT,
            "PATH": path or f"{self.scripts}{os.pathsep}{os.environ['PATH']}",
            "FAKE_HARNESS_LOG": str(self.log),
            **variables,
        }
        return subprocess.run(
            [str(self.python), "-I", "-m", "skill_ci", *arguments],
            cwd=cwd,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def calls(self) -> list[dict[str, Any]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def arguments(self) -> list[list[str]]:
        return [call["arguments"] for call in self.calls()]



def still_running(pid: int) -> bool:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if exited(pid):
            return False
        time.sleep(0.05)
    return True


def exited(pid: int) -> bool:
    # A zombie has exited, but it stays listed until its parent reaps it, and nothing reaps it when the tests run as
    # PID 1 in a container without an init process. A slim Linux image may have no ps, so read /proc there.
    if Path("/proc/self/stat").exists():
        try:
            return Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()[0] == "Z"
        except FileNotFoundError:
            return True
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, check=False).stdout.strip()
    return state[:1] in ("", "Z")


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
        self.scratch = self.root / "tmp"
        self.scratch.mkdir()
        self.environment = {
            **{key: value for key, value in ENVIRONMENT.items() if key != "UV_OFFLINE"},
            **ISOLATED_GIT,
            "GIT_CEILING_DIRECTORIES": str(self.root),
            "HOME": str(self.root / "home"),
            "XDG_CACHE_HOME": str(self.cache),
            "TMPDIR": str(self.scratch),
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
        return git(*arguments, cwd=cwd or self.work, env=self.environment)

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
                    "arguments": ["tool", "run", "--offline", "--isolated", "--from", f"git+{self.source.as_uri()}@{commit}", "skill-ci", *arguments],
                    "pinned": commit,
                    "pythonpath": None,
                }
            ],
        )
        self.uv_log.unlink()

    def refused(self, result: subprocess.CompletedProcess[str], stderr_lines: list[str]) -> None:
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(result.stderr.splitlines(), stderr_lines)
        self.assertFalse(self.uv_log.exists())

    def running(self, commit: str) -> dict[str, str]:
        return {"PYTHONPATH": str(fake_git_install(self.root / "installed", commit))}

    def unreachable(self) -> None:
        self.source.rename(self.root / "moved.git")

    def shimmed(self) -> dict[str, str]:
        return {"PATH": f"{self.root / 'git shim'}{os.pathsep}{self.environment['PATH']}"}

    def cache_record(self) -> tuple[Path, dict[str, object]]:
        [cached] = (self.cache / "skill-ci" / "refs").glob("*.json")
        return cached, json.loads(cached.read_text())

    def rewrite_cache(self, **changes: object) -> None:
        cached, record = self.cache_record()
        cached.write_text(json.dumps({**record, **changes}))

    def tag(self, name: str) -> str:
        commit = self.push_commit(name)
        self.git("tag", name, commit)
        self.git("push", "-q", "origin", name)
        return commit
