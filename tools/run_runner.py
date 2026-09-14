#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn, Sequence


RUNNER_PREFIX = "git+https://github.com/mdsmithaustin/skill-eval-harness.git@"
LOCK_PATTERN = re.compile(re.escape(RUNNER_PREFIX) + r"([0-9a-fA-F]{40})\Z")
COMMANDS = frozenset(("skill-benchmark", "skill-trigger-matrix"))
LOCK_PATH = Path(__file__).resolve().parents[1] / "runner.lock"
BOOTSTRAP = (
    "import os, sys, sysconfig\n"
    "script = os.path.join(sysconfig.get_path('scripts'), sys.argv[1])\n"
    "os.execv(script, [script, *sys.argv[2:]])\n"
)


class LockError(ValueError):
    pass


@dataclass(frozen=True)
class RunnerPin:
    commit: str

    @property
    def spec(self) -> str:
        return f"{RUNNER_PREFIX}{self.commit}"


def parse_lock(text: str) -> RunnerPin:
    entries = [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if len(entries) != 1:
        raise LockError("runner.lock must contain exactly one approved runner specification")
    match = LOCK_PATTERN.fullmatch(entries[0])
    if match is None:
        raise LockError("runner.lock must pin mdsmithaustin/skill-eval-harness to a full commit")
    return RunnerPin(match.group(1).lower())


def execution_argv(pin: RunnerPin, command: str, arguments: Sequence[str]) -> list[str]:
    return [
        "uv",
        "tool",
        "run",
        "--isolated",
        "--from",
        pin.spec,
        "python",
        "-I",
        "-c",
        BOOTSTRAP,
        command,
        *arguments,
    ]


def fail(message: str, code: int) -> NoReturn:
    print(f"run_runner: {message}", file=sys.stderr)
    raise SystemExit(code)


def main(argv: Sequence[str] | None = None) -> NoReturn:
    values = list(sys.argv[1:] if argv is None else argv)
    if not values or values[0] not in COMMANDS:
        fail("expected skill-benchmark or skill-trigger-matrix followed by runner arguments", 2)
    try:
        pin = parse_lock(LOCK_PATH.read_text(encoding="utf-8"))
    except OSError as error:
        fail(f"could not read {LOCK_PATH}: {error}", 2)
    except LockError as error:
        fail(str(error), 2)
    try:
        os.execvp("uv", execution_argv(pin, values[0], values[1:]))
    except FileNotFoundError:
        fail("uv is required to run the pinned runner", 127)


if __name__ == "__main__":
    main()
