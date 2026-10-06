from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import fields
from importlib import metadata
from pathlib import Path
from typing import Any

from skill_ci import harness, runs, suite
from skill_ci.checks import coverage, manifests, package
from skill_ci.harness import Command
from skill_ci.runs import Agent, RunOptions, TriggerOptions
from skill_ci.suite import CheckOptions, PiiScope

OPTIONS: dict[str, tuple[str, dict[str, Any]]] = {
    "skills_dir": ("--skills-dir", {"type": Path, "metavar": "DIR", "help": "directory holding one subdirectory per skill"}),
    "evals_dir": (
        "--evals-dir",
        {
            "type": Path,
            "metavar": "DIR",
            "help": "directory holding <skill>/shared-benchmark.json; unset, manifests sit at <skill>/evals/",
        },
    ),
    "pii_scope": (
        "--pii-scope",
        {"type": PiiScope, "choices": tuple(PiiScope), "help": "scan the skills tree, or every tracked file"},
    ),
    "trigger_cases": (
        "--trigger-cases",
        {"type": Path, "metavar": "FILE", "help": "version-1 trigger declaration corpus that must declare every skill"},
    ),
    "content_ignore_file": (
        "--content-ignore-file",
        {
            "type": Path,
            "metavar": "FILE",
            "help": "skill names that live in another repository, one per line, '#' comments allowed",
        },
    ),
    "content_link_exceptions_file": (
        "--content-link-exceptions-file",
        {"type": Path, "metavar": "FILE", "help": "version-1 JSON file of missing inline links created at output time"},
    ),
    "content_conventions_file": (
        "--content-conventions-file",
        {"type": Path, "metavar": "FILE", "help": "version-1 JSON file of skill-name prefixes and retired text"},
    ),
    "require_manifests": ("--require-manifests", {"action": "store_true", "help": "fail when no manifest is found"}),
    "require_populated_manifests": (
        "--require-populated-manifests",
        {"action": "store_true", "help": "require a manifest with cases bound to every skill"},
    ),
    "package": (
        "--package",
        {"action": "store_true", "help": "inspect every package entry and reject symlinks and special files"},
    ),
    "out": (
        "--out",
        {
            "type": Path,
            "metavar": "DIR",
            "help": "output directory outside the skill package; unset, a new directory under <checkout>.eval-runs/<skill>/",
        },
    ),
    "runs": ("--runs", {"type": int, "metavar": "N", "help": "runs per query or variant"}),
    "agents": ("--agent", {"action": "append", "type": Agent, "choices": tuple(Agent), "help": "agent to run; repeatable"}),
    "model": ("--model", {"help": "Claude model"}),
    "matrix_model": ("--model", {"metavar": "MODEL", "help": "model for every agent; unset, each agent's own model list"}),
    "codex_model": ("--codex-model", {"help": "Codex model"}),
    "codex_cmd": (
        "--codex-cmd",
        {"metavar": "COMMAND", "help": "Codex command line (default: the bundled codex launcher, read-only sandbox)"},
    ),
    "timeout": ("--timeout", {"type": int, "metavar": "SECONDS", "help": "per-run timeout"}),
    "judge_model": ("--judge-model", {"help": "Claude judge model"}),
    "judge_runs": ("--judge-runs", {"type": int, "metavar": "N", "help": "judge repeats per run"}),
}
LINT = ("skills_dir", "trigger_cases", "content_ignore_file", "content_link_exceptions_file", "content_conventions_file")
MANIFESTS = ("skills_dir", "evals_dir")


def main(argv: Sequence[str] | None = None) -> int:
    # Piped stdout is block-buffered and stderr is not, so findings would print after later summaries.
    sys.stdout.reconfigure(line_buffering=True)
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        namespace = build_parser().parse_args(arguments)
        return namespace.handler(namespace)
    except KeyboardInterrupt:
        return 130


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skill-ci",
        description="Model-free checks and operator-local eval runs for repositories of Agent Skills.",
    )
    parser.add_argument("--version", action="version", version=f"skill-ci {metadata.version('skill-ci')}")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    def subcommand(name: str, handler: Callable[[argparse.Namespace], int], help_text: str) -> argparse.ArgumentParser:
        subparser = commands.add_parser(name, help=help_text, description=help_text, argument_default=argparse.SUPPRESS)
        subparser.set_defaults(handler=handler)
        return subparser

    add_options(subcommand("lint", lint, "check frontmatter, links, sibling references, and retired text"), CheckOptions, LINT)
    package_parser = subcommand("package", check_package, "inspect package trees and optionally compare installed copies")
    add_options(package_parser, CheckOptions, ("skills_dir",))
    package_parser.add_argument("--compare-to", type=Path, default=None, metavar="DIR", help="installed skills directory")
    add_options(subcommand("coverage", check_coverage, "require a populated manifest bound to every skill"), CheckOptions, MANIFESTS)
    add_options(subcommand("validate", validate, "validate every manifest with the pinned harness"), CheckOptions, MANIFESTS)
    add_options(subcommand("audit", audit, "run the readiness audit on every manifest"), CheckOptions, MANIFESTS)
    check_parser = subcommand("check", check, "run the model-free checks that CI runs")
    add_options(check_parser, CheckOptions, tuple(field.name for field in fields(CheckOptions)))
    check_parser.add_argument("--fast", action="store_true", default=False, help="run only the PII scan of staged files and the lint checks; other check flags are ignored")
    trigger_parser = subcommand("trigger", trigger, "run the trigger matrix for one skill on the host's logins (paid)")
    trigger_parser.add_argument("skill", type=Path, help="skill directory, such as skills/my-skill")
    add_options(trigger_parser, TriggerOptions, ("evals_dir", "out", "runs", "matrix_model", "codex_cmd"))
    run_parser = subcommand("run", run, "run the paired benchmark for one skill on the host's logins (paid)")
    run_parser.add_argument("skill", type=Path, help="skill directory, such as skills/my-skill")
    add_options(run_parser, RunOptions, tuple(field.name for field in fields(RunOptions) if field.name != "skill"))
    harness_parser = subcommand(
        "harness", lambda namespace: run_harness(namespace.arguments), "run skill-benchmark or skill-trigger-matrix"
    )
    harness_parser.add_argument("arguments", nargs=argparse.REMAINDER, metavar="COMMAND [ARGS...]")
    return parser


def add_options(parser: argparse.ArgumentParser, options_type: type, names: Sequence[str]) -> None:
    defaults = {field.name: field.default for field in fields(options_type)}
    for name in names:
        flag, spec = OPTIONS[name]
        default = defaults[name]
        if default is not None and default is not False:
            shown = " ".join(default) if isinstance(default, tuple) else default
            spec = {**spec, "help": f"{spec['help']} (default: {shown})"}
        parser.add_argument(flag, dest=name, **spec)


def options[T](options_type: type[T], namespace: argparse.Namespace) -> T:
    return options_type(**{field.name: getattr(namespace, field.name) for field in fields(options_type) if hasattr(namespace, field.name)})


def warn_about_shadowing() -> None:
    for warning in harness.shadowing_warnings(Path.cwd()):
        print(f"skill-ci: warning: {warning}", file=sys.stderr)


def lint(namespace: argparse.Namespace) -> int:
    return suite.lint(options(CheckOptions, namespace))


def check_package(namespace: argparse.Namespace) -> int:
    return package.check_packages(skills_dir=options(CheckOptions, namespace).skills_dir, compare_to=namespace.compare_to)


def check_coverage(namespace: argparse.Namespace) -> int:
    selected = options(CheckOptions, namespace)
    return coverage.check_coverage(selected.skills_dir, selected.evals_dir)


def validate(namespace: argparse.Namespace) -> int:
    warn_about_shadowing()
    selected = options(CheckOptions, namespace)
    return manifests.validate(selected.skills_dir, selected.evals_dir)


def audit(namespace: argparse.Namespace) -> int:
    warn_about_shadowing()
    selected = options(CheckOptions, namespace)
    return manifests.audit(selected.skills_dir, selected.evals_dir)


def check(namespace: argparse.Namespace) -> int:
    if not namespace.fast:
        warn_about_shadowing()
    return suite.check(options(CheckOptions, namespace), fast=namespace.fast)


def trigger(namespace: argparse.Namespace) -> int:
    warn_about_shadowing()
    return runs.trigger(options(TriggerOptions, namespace))


def run(namespace: argparse.Namespace) -> int:
    warn_about_shadowing()
    return runs.run(options(RunOptions, namespace))


def run_harness(arguments: Sequence[str]) -> int:
    if not arguments or arguments[0] not in Command:
        print(f"skill-ci: harness runs {Command.BENCHMARK} or {Command.TRIGGER_MATRIX}, then its arguments", file=sys.stderr)
        return 2
    warn_about_shadowing()
    return harness.execute(Command(arguments[0]), arguments[1:])
