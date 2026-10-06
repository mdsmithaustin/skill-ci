from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from skill_ci.checks import content, coverage, frontmatter, manifests, package, pii


class PiiScope(StrEnum):
    SKILLS = "skills"
    REPOSITORY = "repository"


@dataclass(frozen=True)
class CheckOptions:
    skills_dir: Path = Path("skills")
    evals_dir: Path | None = None
    pii_scope: PiiScope = PiiScope.SKILLS
    trigger_cases: Path | None = None
    content_ignore_file: Path | None = None
    content_link_exceptions_file: Path | None = None
    content_conventions_file: Path | None = None
    require_manifests: bool = False
    require_populated_manifests: bool = False
    package: bool = False


@dataclass(frozen=True)
class CheckResult:
    name: str
    exit_code: int


Check = tuple[str, Callable[[], int]]


def lint(options: CheckOptions) -> int:
    return run_checks(lint_checks(options))


def check(options: CheckOptions, *, fast: bool) -> int:
    return run_checks(fast_checks(options) if fast else free_checks(options))


def free_checks(options: CheckOptions) -> list[Check]:
    checks: list[Check] = []
    if options.package:
        checks.append(("package", lambda: package.check_packages(skills_dir=options.skills_dir)))
    checks.append(("pii", lambda: pii.check_pii(pathspec=pii_pathspec(options))))
    checks += lint_checks(options)
    if options.require_populated_manifests:
        checks.append(("coverage", lambda: coverage.check_coverage(options.skills_dir, options.evals_dir)))
    checks.append(
        (
            "manifests",
            lambda: manifests.check(options.skills_dir, options.evals_dir, require_manifests=options.require_manifests),
        )
    )
    return checks


def fast_checks(options: CheckOptions) -> list[Check]:
    return [("pii", lambda: pii.check_pii(staged=True, pathspec=pii_pathspec(options))), *lint_checks(options)]


def lint_checks(options: CheckOptions) -> list[Check]:
    return [
        ("frontmatter", lambda: frontmatter.check_skills(options.skills_dir, options.trigger_cases)),
        ("content", lambda: lint_content(options)),
    ]


def pii_pathspec(options: CheckOptions) -> tuple[str, ...]:
    return () if options.pii_scope is PiiScope.REPOSITORY else (str(options.skills_dir),)


def lint_content(options: CheckOptions) -> int:
    ignore: frozenset[str] = frozenset()
    if options.content_ignore_file is not None:
        try:
            lines = options.content_ignore_file.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as error:
            print(f"skill-ci: cannot read content ignore file {options.content_ignore_file}: {error}", file=sys.stderr)
            return 2
        ignore = frozenset(name for line in lines if (name := line.strip()) and not name.startswith("#"))
    return content.check_content(
        options.skills_dir,
        ignore=ignore,
        link_exceptions_file=options.content_link_exceptions_file,
        conventions_file=options.content_conventions_file,
    )


def run_checks(checks: Sequence[Check]) -> int:
    results = [CheckResult(name, exit_code(run)) for name, run in checks]
    failed = [result.name for result in results if result.exit_code != 0]
    names = f" ({', '.join(failed)})" if failed else ""
    print(f"checks run: {len(results)}; failed: {len(failed)}{names}")
    return max((result.exit_code for result in results), default=0)


def exit_code(run: Callable[[], int]) -> int:
    try:
        return run()
    except SystemExit as error:
        return error.code if isinstance(error.code, int) else int(error.code is not None)
