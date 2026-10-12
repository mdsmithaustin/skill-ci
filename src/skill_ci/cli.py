from __future__ import annotations

import argparse
import os
import sys
import traceback
from collections.abc import Callable, Sequence
from dataclasses import fields
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

from skill_ci import children, config, files, harness, init, pin, runs, suite
from skill_ci.checks import coverage, manifests, package
from skill_ci.config import OPTIONS, Track
from skill_ci.harness import Command
from skill_ci.runs import RunOptions, TriggerOptions
from skill_ci.suite import CheckOptions

LINT = ("skills_dir", "trigger_cases", "invocation_policy", "content_ignore_file", "content_link_exceptions_file", "content_conventions_file")
MANIFESTS = ("skills_dir", "evals_dir")


def main(argv: Sequence[str] | None = None) -> int:
    # Piped stdout is block-buffered and stderr is not, so findings would print after later summaries.
    sys.stdout.reconfigure(line_buffering=True)
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        distribution = metadata.distribution("skill-ci")
        running = pin.running_commit(distribution)
        child = pin.claim(os.environ, running)
        directory = working_directory()
        found = None if directory is None else config.find(directory)
        updating = arguments[:1] == ["update"]
        loaded = None if found is None else config.read(found, ignore_unknown=updating)
        announced = loaded is not None and not child and not updating
        if announced:
            try:
                resolved = pin.resolve(loaded.pin, pin.cache_directory(), datetime.now(UTC))
            except pin.PinError:
                if loaded.unknown_keys:
                    report(config.ConfigError(loaded.path, loaded.unknown_keys))
                raise
            announce(loaded.pin, resolved)
            if resolved.commit != running:
                pin.rerun(loaded.pin, resolved.commit, arguments)
        if loaded is not None and loaded.unknown_keys:
            raise config.ConfigError(loaded.path, loaded.unknown_keys)
        identity = f"skill-ci {distribution.version} ({running or 'commit unknown'})"
        namespace = build_parser(identity).parse_args(arguments)
        if not child and not announced:
            print(identity, file=sys.stderr)
        settings = {} if loaded is None else loaded.settings
        return namespace.handler(argparse.Namespace(**settings | vars(namespace), loaded=loaded))
    except (config.ConfigError, pin.PinError) as error:
        report(error)
        return 2
    except pin.HandoffError as error:
        print(f"skill-ci: {error}", file=sys.stderr)
        return error.status
    except children.Stopped as stopped:
        return stopped.status
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        if os.environ.get("SKILL_CI_DEBUG") == "1":
            traceback.print_exc()
        else:
            print(f"skill-ci: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


def report(error: Exception) -> None:
    for line in str(error).splitlines():
        print(f"skill-ci: {line}", file=sys.stderr)


def working_directory() -> Path | None:
    try:
        return Path.cwd()
    except OSError:
        return None


def announce(selected: config.Pin, resolved: pin.Resolved) -> None:
    print(f"skill-ci {resolved.name} ({resolved.commit})", file=sys.stderr)
    if resolved.unreachable is not None:
        print(
            f"skill-ci: warning: cannot reach {selected.source} ({resolved.unreachable}); "
            f"running {resolved.commit}, which {selected.version} named on {resolved.fetched_at:%Y-%m-%d %H:%M} UTC",
            file=sys.stderr,
        )
    if resolved.newer is not None:
        print(f"skill-ci: {resolved.newer} is newer than the pinned {selected.version}; run skill-ci update to move the pin", file=sys.stderr)


def build_parser(identity: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skill-ci",
        description="Model-free checks and operator-local eval runs for repositories of Agent Skills.",
    )
    parser.add_argument("--version", action="version", version=identity)
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
    check_parser = subcommand("check", check, "run the model-free checks that CI runs, inside a git repository")
    add_options(check_parser, CheckOptions, tuple(field.name for field in fields(CheckOptions)))
    check_parser.add_argument("--fast", action="store_true", default=False, help="run only the PII scan of staged files and the lint checks; --evals-dir, --require-*, and --package are ignored")
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
    init_parser = subcommand("init", initialize, f"set up this repository: write {config.FILE_NAME}, a CI workflow, hook entries, and one empty manifest per skill")
    add_options(init_parser, CheckOptions, ("skills_dir", "evals_dir"))
    subcommand("update", update, f"move an exact-tag version in {config.FILE_NAME} to the newest release tag, keeping comments and other keys; on latest or main, refresh the cached commit")
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
    project = working_directory()
    if project is None:
        return
    for warning in harness.shadowing_warnings(project):
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


def initialize(namespace: argparse.Namespace) -> int:
    return init.run(Path.cwd(), skills_dir=getattr(namespace, "skills_dir", None), evals_dir=getattr(namespace, "evals_dir", None), loaded=namespace.loaded)


def update(namespace: argparse.Namespace) -> int:
    loaded: config.Config | None = namespace.loaded
    if loaded is None:
        print(f"skill-ci: no {config.FILE_NAME} in the working directory, or in a parent directory inside the same git repository", file=sys.stderr)
        return 2
    path, selected = loaded.path, loaded.pin
    shown = os.path.relpath(path)
    refs = pin.refresh(selected, pin.cache_directory(), datetime.now(UTC))
    if isinstance(selected.version, Track):
        resolved = pin.answer(selected.version, refs)
        print(f"{shown}: version is {selected.version}, which floats, so the file is unchanged; it now runs {resolved.name} ({resolved.commit})")
        return 0
    newest = pin.newest(refs)
    if selected.version == newest:
        print(f"{shown}: version is already {newest}, the newest tag")
        return 0
    if selected.version > newest:
        print(f"skill-ci: {shown} pins {selected.version}, but the newest tag on {selected.source} is {newest}; left unchanged", file=sys.stderr)
        return 2
    try:
        updated = config.with_version(path.read_bytes().decode("utf-8"), newest).encode("utf-8")
        with children.stopping_signals():
            files.atomic_write(path, updated)
    except (OSError, ValueError) as error:
        print(f"skill-ci: cannot update {shown}: {error}", file=sys.stderr)
        return 2
    print(f"{shown}: version {selected.version} -> {newest}")
    return 0
