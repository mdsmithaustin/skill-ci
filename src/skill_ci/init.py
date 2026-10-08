from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from skill_ci import children, config, files, pin, scaffold_manifest

WORKFLOW = Path(".github/workflows/skill-checks.yml")
LEFTHOOK_FILES = ("lefthook.yml", "lefthook.yaml", ".lefthook.yml", ".lefthook.yaml")
MISE_FILES = ("mise.toml", ".mise.toml")
NO_MISTAKES_FILE = ".no-mistakes.yaml"
GITIGNORE = ".gitignore"
IGNORED_RUN_OUTPUT = ("eval-runs/", "evals/runs/")
MISE_TASKS = {f"skill-{command}": f"skill-ci {command}" for command in ("check", "lint", "package", "coverage", "validate", "audit", "trigger", "run")}
LINT_SUFFIX = " && skill-ci check"
COMMAND = "skill-ci check"
BLANK = re.compile(r"[ \t]*(?:#.*)?")
DEFAULT_BRANCH_NOTE = "no-mistakes reads commands from the default branch, not from the branch you push"


class Verb(StrEnum):
    WROTE = "wrote"
    UPDATED = "updated"
    KEPT = "kept"
    NOTE = "note:"
    TODO = "to do:"


@dataclass(frozen=True)
class Outcome:
    verb: Verb
    subject: str
    detail: str = ""

    def __str__(self) -> str:
        if "\n" in self.detail:
            body = "\n".join(f"    {line}" for line in self.detail.splitlines())
            return f"{self.verb} {self.subject}\n{body}"
        return f"{self.verb} {self.subject}" + (f" ({self.detail})" if self.detail else "")


@dataclass(frozen=True)
class Layout:
    root: Path
    pin: config.Pin
    skills_dir: Path
    evals_dir: Path | None
    skills: tuple[Path, ...]


class Refusal(Exception):
    pass


def run(root: Path, *, skills_dir: Path | None, evals_dir: Path | None, loaded: config.Config | None) -> int:
    try:
        layout = settle(root, skills_dir, evals_dir, loaded)
    except Refusal as refusal:
        for line in str(refusal).splitlines():
            print(f"skill-ci: {line}", file=sys.stderr)
        return 2
    steps: tuple[Callable[[Layout], list[Outcome]], ...] = (
        write_config,
        write_workflow,
        add_lefthook_commands,
        wire_no_mistakes,
        add_mise_tasks,
        scaffold_manifests,
        ignore_run_output,
    )
    changed = incomplete = False
    for step in steps:
        for outcome in step(layout):
            print(outcome)
            changed |= outcome.verb in (Verb.WROTE, Verb.UPDATED)
            incomplete |= outcome.verb is Verb.TODO
    if not changed:
        print("nothing to change")
    return int(incomplete)


def settle(root: Path, skills_dir: Path | None, evals_dir: Path | None, loaded: config.Config | None) -> Layout:
    require_repository_root(root)
    skills = inside(root, Path("skills") if skills_dir is None else skills_dir, "skills directory")
    markers = sorted(path for path in (root / skills).glob("*/SKILL.md") if path.is_file())
    if not markers:
        raise Refusal(f"{skills} holds no skill: init needs a directory whose children each hold a SKILL.md; pass --skills-dir to name another")
    if evals_dir is not None:
        evals = inside(root, evals_dir, "evals directory")
    elif loaded is not None:
        evals = None
    else:
        evals = detect_evals_dir(root, skills)
    for key, path in (("skills_dir", skills), ("evals_dir", evals)):
        if path is not None:
            toml_path(key, path)
    for marker in markers:
        try:
            scaffold_manifest.layout_for(marker.parent, None if evals is None else root / evals)
        except scaffold_manifest.ScaffoldError as error:
            raise Refusal(str(error)) from error
    source = config.Source(config.DEFAULT_SOURCE) if loaded is None else loaded.pin.source
    selected = config.Pin(newest_release(source, skills, evals), source) if loaded is None else loaded.pin
    return Layout(root, selected, skills, evals, tuple(marker.parent for marker in markers))


def require_repository_root(root: Path) -> None:
    try:
        top = children.run(["git", "rev-parse", "--show-toplevel"], capture=True, cwd=root)
    except OSError as error:
        raise Refusal(f"init needs git: {error}") from error
    if top.returncode != 0:
        raise Refusal("init runs inside a git repository, and this directory is in none")
    toplevel = Path(top.stdout.decode(errors="replace").strip())
    if toplevel.resolve() != root.resolve():
        raise Refusal(f"run init at the repository root, {toplevel}")


def inside(root: Path, path: Path, named: str) -> Path:
    relative = Path(os.path.relpath((root / path).resolve(), root.resolve()))
    if relative.parts[:1] == ("..",):
        raise Refusal(f"the {named} {path} is outside the repository")
    return relative


def detect_evals_dir(root: Path, skills: Path) -> Path | None:
    if any(root.glob("evals/*/shared-benchmark.json")):
        return Path("evals")
    return None if any((root / skills).glob("*/evals/shared-benchmark.json")) else Path("evals")


def newest_release(source: config.Source, skills: Path, evals: Path | None) -> config.Tag:
    try:
        refs = pin.fetch(config.Pin(config.Track.LATEST, source), pin.cache_directory(), datetime.now(UTC))
    except pin.Unreachable as error:
        raise Refusal(f"cannot reach {source} ({error})\ninit needs the network to find the newest release tag") from error
    if not refs.tags:
        floating = "\n".join(config_lines('"main"', skills, evals)[1:])
        raise Refusal(
            f"{source} has no release tag yet, and init pins an exact tag, so it wrote nothing\n"
            f"to follow the branch head until the first tag exists, write {config.FILE_NAME} as below and run skill-ci init again\n{floating}"
        )
    return max(refs.tags)


def write_config(layout: Layout) -> list[Outcome]:
    if os.path.lexists(layout.root / config.FILE_NAME):
        return [Outcome(Verb.KEPT, config.FILE_NAME)]
    lines = config_lines(json.dumps(str(layout.pin.version)), layout.skills_dir, layout.evals_dir)
    save(layout.root / config.FILE_NAME, ("\n".join(lines) + "\n").encode("utf-8"))
    return [Outcome(Verb.WROTE, config.FILE_NAME, f"version {layout.pin.version}")]


def config_lines(version: str, skills: Path, evals: Path | None) -> list[str]:
    lines = [
        "# The skill-ci release this repository runs, here and in CI. skill-ci update moves it to the newest tag.",
        f"version = {version}",
        f"skills_dir = {toml_path('skills_dir', skills)}",
    ]
    return lines if evals is None else [*lines, f"evals_dir = {toml_path('evals_dir', evals)}"]


def toml_path(key: str, path: Path) -> str:
    try:
        config.parse_setting(key, path.as_posix(), Path())
    except ValueError as error:
        raise Refusal(str(error)) from error
    return json.dumps(path.as_posix(), ensure_ascii=False)


def write_workflow(layout: Layout) -> list[Outcome]:
    path = layout.root / WORKFLOW
    if path.exists():
        kept = Outcome(Verb.KEPT, str(WORKFLOW))
        if COMMAND in path.read_text(encoding="utf-8", errors="replace"):
            return [kept]
        return [kept, Outcome(Verb.NOTE, f"{WORKFLOW} does not run `{COMMAND}`; add a step that does, or replace the file with the template in the README")]
    template = resources.files("skill_ci").joinpath("templates/skill-checks.yml").read_text(encoding="utf-8")
    save(path, template.replace("@SOURCE@", json.dumps(layout.pin.source, ensure_ascii=False)).encode("utf-8"))
    return [Outcome(Verb.WROTE, str(WORKFLOW))]


def save(path: Path, data: bytes) -> None:
    if path.exists():
        rewrite(path, data)
        return
    with children.stopping_signals():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def rewrite(path: Path, data: bytes) -> None:
    with children.stopping_signals():
        files.atomic_write(path, data)


def first_existing(root: Path, names: tuple[str, ...]) -> Path | None:
    return next((root / name for name in names if (root / name).is_file()), None)


def add_lefthook_commands(layout: Layout) -> list[Outcome]:
    path = first_existing(layout.root, LEFTHOOK_FILES)
    if path is None:
        return []
    shown = path.name
    original = path.read_bytes()
    try:
        text = original.decode("utf-8")
        configured = yaml_mapping(text) or {}
    except (UnicodeDecodeError, yaml.YAMLError) as error:
        return [Outcome(Verb.TODO, f"add skill-ci to {shown}", f"cannot read it: {error}")]
    outcomes: list[Outcome] = []
    added: list[str] = []
    for hook, name, run_line in lefthook_commands():
        if runs_check(configured.get(hook)):
            outcomes.append(Outcome(Verb.KEPT, f"{shown} {hook}", f"already runs {COMMAND}"))
        elif (edited := with_command(text, hook, name, run_line)) is None:
            snippet = f"{hook}:\n  commands:\n    {name}:\n      run: {run_line}"
            outcomes.append(Outcome(Verb.TODO, f"add {run_line} under {hook} in {shown}", f"it could not be edited safely; add:\n{snippet}"))
        else:
            text, configured = edited, yaml_mapping(edited) or {}
            added.append(f"{run_line} under {hook}")
    if added:
        rewrite(path, text.encode("utf-8"))
        invalid = lefthook_rejects(layout.root)
        if invalid is not None:
            rewrite(path, original)
            return [Outcome(Verb.TODO, f"add skill-ci to {shown}", f"lefthook validate failed after the change, so the file is as it was:\n{invalid}")]
        outcomes.insert(0, Outcome(Verb.UPDATED, shown, "added " + "; ".join(added)))
        outcomes.append(Outcome(Verb.NOTE, "lefthook install activates the hooks in this clone"))
    return outcomes


def lefthook_commands() -> list[tuple[str, str, str]]:
    template = yaml.safe_load(resources.files("skill_ci").joinpath("templates/lefthook.yml").read_text(encoding="utf-8"))
    return [(hook, name, entry["run"]) for hook, body in template.items() for name, entry in body["commands"].items()]


def runs_check(node: Any) -> bool:
    if isinstance(node, dict):
        return any(isinstance(value, str) and key == "run" and COMMAND in value or runs_check(value) for key, value in node.items())
    return isinstance(node, list) and any(runs_check(item) for item in node)


def lefthook_rejects(root: Path) -> str | None:
    if shutil.which("lefthook") is None:
        return None
    checked = children.run(["lefthook", "validate"], capture=True, cwd=root)
    if checked.returncode == 0:
        return None
    return (checked.stdout + checked.stderr).decode(errors="replace").strip() or f"lefthook validate exited {checked.returncode}"


def yaml_mapping(text: str) -> dict[str, Any] | None:
    loaded = yaml.safe_load(text)
    if loaded is not None and not isinstance(loaded, dict):
        raise yaml.YAMLError("the top level is not a mapping")
    return loaded


def indentation(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def block_end(lines: list[str], start: int, indent: int) -> int:
    end = start + 1
    for index in range(start + 1, len(lines)):
        if BLANK.fullmatch(lines[index]):
            continue
        if indentation(lines[index]) <= indent:
            break
        end = index + 1
    return end


def with_command(text: str, hook: str, name: str, run_line: str) -> str | None:
    before = yaml_mapping(text) or {}
    section = before.get(hook)
    if section is not None and (not isinstance(section, dict) or "jobs" in section or not isinstance(section.get("commands", {}), dict | None)):
        return None
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(newline)
    if lines[-1] == "":
        lines.pop()
    head = next((index for index, line in enumerate(lines) if re.fullmatch(rf"{re.escape(hook)}:[ \t]*(?:#.*)?", line)), None)
    if head is None:
        lines += ([""] if lines and lines[-1].strip() else []) + [f"{hook}:", "  commands:", f"    {name}:", f"      run: {run_line}"]
    else:
        stop = block_end(lines, head, 0)
        content = [index for index in range(head + 1, stop) if not BLANK.fullmatch(lines[index])]
        child = indentation(lines[content[0]]) if content else 2
        commands = next((index for index in content if indentation(lines[index]) == child and re.fullmatch(r" *commands:[ \t]*(?:#.*)?", lines[index])), None)
        if commands is None:
            lines[stop:stop] = [f"{' ' * child}commands:", f"{' ' * 2 * child}{name}:", f"{' ' * 3 * child}run: {run_line}"]
        else:
            end = block_end(lines, commands, child)
            entries = [index for index in range(commands + 1, end) if not BLANK.fullmatch(lines[index])]
            inner = indentation(lines[entries[0]]) if entries else 2 * child
            lines[end:end] = [f"{' ' * inner}{name}:", f"{' ' * (inner + inner - child)}run: {run_line}"]
    edited = newline.join(lines) + newline
    expected = {**before, hook: {**(section or {}), "commands": {**((section or {}).get("commands") or {}), name: {"run": run_line}}}}
    try:
        return edited if yaml_mapping(edited) == expected else None
    except yaml.YAMLError:
        return None


def wire_no_mistakes(layout: Layout) -> list[Outcome]:
    path = layout.root / NO_MISTAKES_FILE
    if not path.is_file():
        return []
    try:
        text = path.read_bytes().decode("utf-8")
        configured = yaml_mapping(text) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        return [Outcome(Verb.TODO, f"add skill-ci to {NO_MISTAKES_FILE}", f"cannot read it: {error}")]
    commands = configured.get("commands")
    lint = commands.get("lint") if isinstance(commands, dict) else None
    if not (isinstance(lint, str) and lint.strip()):
        return [
            Outcome(Verb.KEPT, NO_MISTAKES_FILE, "commands.lint is empty, and setting it would replace the agent's lint duty"),
            Outcome(Verb.NOTE, f"add this to ~/.no-mistakes/config.yaml to run skill-ci check beside the agent's lint, on this machine only. {DEFAULT_BRANCH_NOTE}, so a change to {NO_MISTAKES_FILE} would apply only after it merges", override_snippet(layout.root)),
        ]
    if COMMAND in lint:
        return [Outcome(Verb.KEPT, NO_MISTAKES_FILE, "commands.lint already runs skill-ci check")]
    edited = with_lint_suffix(text)
    if edited is None:
        return [Outcome(Verb.TODO, f"append `{LINT_SUFFIX}` to commands.lint in {NO_MISTAKES_FILE}", "it could not be edited safely")]
    rewrite(path, edited.encode("utf-8"))
    return [
        Outcome(Verb.UPDATED, NO_MISTAKES_FILE, f"commands.lint: {lint.strip()} -> {lint.strip()}{LINT_SUFFIX}"),
        Outcome(Verb.NOTE, f"{DEFAULT_BRANCH_NOTE}, so this change applies after it merges there"),
    ]


def override_snippet(root: Path) -> str:
    try:
        remote = children.run(["git", "remote", "get-url", "origin"], capture=True, cwd=root)
        origin = remote.stdout.decode(errors="replace").strip() if remote.returncode == 0 else ""
    except OSError:
        origin = ""
    lines = ["repository_overrides:", f"  {origin or '<remote URL>'}:", "    commands:", "      lint:", "        additional:", f"          - {COMMAND}"]
    return "\n".join(lines)


QUOTED_LINT = re.compile(r"""(?P<lead> +lint:[ \t]+)(?P<quote>["'])(?P<body>.*)(?P=quote)(?P<tail>[ \t]*(?:#.*)?)""")
PLAIN_LINT = re.compile(r"""(?P<lead> +lint:[ \t]+)(?P<body>[^\s"'#|>&*!%@`{\[](?:.*?\S)?)(?P<tail>[ \t]+#.*)?""")


def with_lint_suffix(text: str) -> str | None:
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(newline)
    head = next((index for index, line in enumerate(lines) if re.fullmatch(r"commands:[ \t]*(?:#.*)?", line)), None)
    if head is None:
        return None
    for index in range(head + 1, block_end(lines, head, 0)):
        if (matched := QUOTED_LINT.fullmatch(lines[index]) or PLAIN_LINT.fullmatch(lines[index])) is None:
            continue
        quote = matched.groupdict().get("quote") or ""
        lines[index] = f"{matched['lead']}{quote}{matched['body']}{LINT_SUFFIX}{quote}{matched['tail'] or ''}"
        edited = newline.join(lines)
        configured = yaml_mapping(text) or {}
        expected = {**configured, "commands": {**configured["commands"], "lint": configured["commands"]["lint"] + LINT_SUFFIX}}
        try:
            return edited if yaml_mapping(edited) == expected else None
        except yaml.YAMLError:
            return None
    return None


def add_mise_tasks(layout: Layout) -> list[Outcome]:
    path = first_existing(layout.root, MISE_FILES)
    if path is None:
        return []
    original = path.read_bytes()
    try:
        text = original.decode("utf-8")
        configured = tomllib.loads(text)
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        return [Outcome(Verb.TODO, f"add the skill tasks to {path.name}", f"cannot read it: {error}")]
    tasks = configured.get("tasks", {})
    missing = {name: command for name, command in MISE_TASKS.items() if not isinstance(tasks, dict) or name not in tasks}
    if not missing:
        return [Outcome(Verb.KEPT, path.name, "already has the skill tasks")]
    newline = "\r\n" if "\r\n" in text else "\n"
    tables = "".join(f"{newline}[tasks.{name}]{newline}run = {json.dumps(command)}{newline}" for name, command in missing.items())
    edited = text + ("" if not text or text.endswith("\n") else newline) + tables
    expected = {**configured, "tasks": {**(tasks if isinstance(tasks, dict) else {}), **{name: {"run": command} for name, command in missing.items()}}}
    try:
        safe = tomllib.loads(edited) == expected
    except tomllib.TOMLDecodeError:
        safe = False
    if not safe:
        return [Outcome(Verb.TODO, f"add the skill tasks to {path.name}", "it could not be edited safely; add:\n" + tables.strip())]
    rewrite(path, edited.encode("utf-8"))
    return [Outcome(Verb.UPDATED, path.name, f"added {', '.join(missing)}")]


def scaffold_manifests(layout: Layout) -> list[Outcome]:
    evals = None if layout.evals_dir is None else layout.root / layout.evals_dir
    outcomes: list[Outcome] = []
    kept = 0
    for skill in layout.skills:
        target, _, _ = scaffold_manifest.layout_for(skill, evals)
        if target.exists():
            kept += 1
            continue
        try:
            with children.stopping_signals():
                scaffold_manifest.scaffold(skill, evals)
        except scaffold_manifest.ScaffoldError as error:
            outcomes.append(Outcome(Verb.TODO, f"write the manifest for {skill.relative_to(layout.root)}", str(error)))
            continue
        outcomes.append(Outcome(Verb.WROTE, target.relative_to(layout.root).as_posix()))
    if kept:
        outcomes.append(Outcome(Verb.KEPT, f"{kept} existing manifest{'s' if kept != 1 else ''}"))
    return outcomes


def ignore_run_output(layout: Layout) -> list[Outcome]:
    path = layout.root / GITIGNORE
    data = path.read_bytes() if path.exists() else b""
    present = {line.strip().strip("/") for line in data.decode("utf-8", errors="replace").splitlines()}
    missing = [pattern for pattern in IGNORED_RUN_OUTPUT if pattern.strip("/") not in present]
    if not missing:
        return [Outcome(Verb.KEPT, GITIGNORE, "already ignores the run output")]
    newline = b"\r\n" if b"\r\n" in data else b"\n"
    separator = b"" if not data or data.endswith(b"\n") else newline
    added = newline.join(line.encode("utf-8") for line in missing) + newline
    save(path, data + separator + added)
    return [Outcome(Verb.UPDATED if data else Verb.WROTE, GITIGNORE, f"added {', '.join(missing)}")]
