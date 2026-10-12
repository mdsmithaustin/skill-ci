from __future__ import annotations

import os
import re
import shutil
import sys
import sysconfig
import tomllib
from collections.abc import Callable, Sequence
from enum import StrEnum
from pathlib import Path

from skill_ci import children

HARNESS_DISTRIBUTIONS = frozenset({"skill-eval-harness", "skill-eval-harness-ext"})
REQUIREMENT_NAME = re.compile(r"\s*([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)")


class Command(StrEnum):
    BENCHMARK = "skill-benchmark"
    TRIGGER_MATRIX = "skill-trigger-matrix"


def script(command: Command) -> Path:
    return Path(sysconfig.get_path("scripts")) / command


def isolated_argv(command: Command, arguments: Sequence[str]) -> list[str] | None:
    path = script(command)
    if not path.is_file():
        print(f"skill-ci: {path} does not exist; skill-ci's environment lacks the harness", file=sys.stderr)
        return None
    return [sys.executable, "-I", str(path), *arguments]


def run(command: Command, arguments: Sequence[str]) -> int:
    argv = isolated_argv(command, arguments)
    if argv is None:
        return 127
    return shell_status(children.run(argv).returncode)


def shell_status(returncode: int) -> int:
    # subprocess reports a child that signal N ended as -N, which sys.exit would turn into 256 - N.
    return 128 - returncode if returncode < 0 else returncode


def execute(command: Command, arguments: Sequence[str]) -> int:
    argv = isolated_argv(command, arguments)
    if argv is None:
        return 127
    sys.stdout.flush()
    sys.stderr.flush()
    os.execv(sys.executable, argv)


def operand(path: Path) -> str:
    text = str(path)
    return os.path.join(os.curdir, text) if text.startswith("-") else text


def call(command: Sequence[str], manifest: Path) -> int:
    try:
        import skill_benchmark

        handlers = {"validate": skill_benchmark.validate_cli_command, "audit-manifest": skill_benchmark.audit_manifest}
        namespace = skill_benchmark.build_arg_parser().parse_args([*command, operand(manifest)])
        return handlers[command[0]](skill_benchmark.CLIInvocation.from_namespace(namespace).to_legacy_namespace())
    except SystemExit as error:
        return exit_status(error)


def exit_code(unit: str, run: Callable[[], int]) -> int:
    try:
        return run()
    except SystemExit as error:
        return exit_status(error)
    except Exception as error:
        print(f"skill-ci: {unit}: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


def exit_status(error: SystemExit) -> int:
    if error.code is None or isinstance(error.code, int):
        return error.code or 0
    print(error.code, file=sys.stderr)
    return 1


def shadowing_warnings(project: Path) -> list[str]:
    warnings = []
    found = shutil.which(Command.BENCHMARK)
    if found is not None and Path(found).resolve() != script(Command.BENCHMARK).resolve():
        warnings.append(f"{found} on PATH is not skill-ci's harness; skill-ci runs its own pinned copy")
    declared = declared_harness(project / "pyproject.toml")
    if declared is not None:
        warnings.append(f"{project / 'pyproject.toml'} requires {declared!r}; skill-ci runs its own pinned copy")
    return warnings


def declared_harness(pyproject: Path) -> str | None:
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    project = data.get("project", {})
    if normalized_name(project.get("name", "")) == "skill-ci":
        return None
    groups = [
        project.get("dependencies", []),
        *project.get("optional-dependencies", {}).values(),
        *data.get("dependency-groups", {}).values(),
    ]
    return next(
        (
            requirement
            for group in groups
            for requirement in group
            if isinstance(requirement, str) and normalized_name(requirement) in HARNESS_DISTRIBUTIONS
        ),
        None,
    )


def normalized_name(requirement: str) -> str | None:
    match = REQUIREMENT_NAME.match(requirement)
    return re.sub(r"[-_.]+", "-", match.group(1)).lower() if match else None
