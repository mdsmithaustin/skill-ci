from __future__ import annotations

import argparse
import difflib
import os
import re
import stat
import tomllib
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from skill_ci.runs import Agent
from skill_ci.suite import PiiScope

FILE_NAME = ".skill-ci.toml"
DEFAULT_SOURCE = "https://github.com/mdsmithaustin/skill-ci.git"
SOURCE_SCHEMES = ("https", "ssh", "file")
TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
VERSION_LINE = re.compile(r"""^[ \t]*version[ \t]*=[ \t]*(?P<quote>["'])(?P<value>[^"'\n]*)(?P=quote)""", re.MULTILINE)

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
        {"type": PiiScope, "choices": tuple(PiiScope), "help": "limit the PII scan to the skills directory, or cover the whole repository"},
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
            "help": "skill names that live in another repository, separated by commas or newlines, '#' comment lines allowed",
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
    "require_manifests": ("--require-manifests", {"action": argparse.BooleanOptionalAction, "help": "fail when no manifest is found"}),
    "require_populated_manifests": (
        "--require-populated-manifests",
        {"action": argparse.BooleanOptionalAction, "help": "require a manifest with cases bound to every skill"},
    ),
    "package": (
        "--package",
        {"action": argparse.BooleanOptionalAction, "help": "inspect every package entry and reject symlinks and special files"},
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


@dataclass(frozen=True, order=True)
class Tag:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, name: str) -> Tag | None:
        match = TAG.fullmatch(name)
        return None if match is None else cls(*(int(part) for part in match.groups()))

    def __str__(self) -> str:
        return f"v{self.major}.{self.minor}.{self.patch}"


class Track(StrEnum):
    LATEST = "latest"
    MAIN = "main"


Version = Tag | Track


@dataclass(frozen=True)
class Pin:
    version: Version
    source: str


@dataclass(frozen=True)
class Config:
    path: Path
    pin: Pin
    settings: Mapping[str, Any]
    unknown_keys: tuple[str, ...]


class ConfigError(Exception):
    def __init__(self, path: Path, problems: Sequence[str]) -> None:
        super().__init__("\n".join(f"{os.path.relpath(path)}: {problem}" for problem in problems))


def find(directory: Path) -> Path | None:
    searched = (directory, *directory.parents)
    # Before Python 3.14, Path.exists raises PermissionError inside a directory that cannot be searched.
    root = next((candidate for candidate in searched if os.path.exists(candidate / ".git")), directory)
    for candidate in searched[: searched.index(root) + 1]:
        if os.path.lexists(candidate / FILE_NAME):
            return candidate / FILE_NAME
    return None


def read(path: Path, *, ignore_unknown: bool = False) -> Config:
    try:
        # Reading a FIFO would wait for a writer.
        if not stat.S_ISREG(path.stat().st_mode):
            raise ConfigError(path, ["cannot read: not a regular file"])
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(path, [f"cannot read: {error}"]) from error
    problems: list[str] = []

    def attempt[T](parser: Callable[..., T], *arguments: object) -> T | None:
        try:
            return parser(*arguments)
        except ValueError as error:
            problems.append(str(error))
            return None

    version = attempt(parse_version, data.pop("version", None))
    source = attempt(parse_source, data.pop("source", DEFAULT_SOURCE), path.parent)
    base = Path(os.path.relpath(path.parent))
    settings = {key: value for key in data if key in OPTIONS and (value := attempt(parse_setting, key, data[key], base)) is not None}
    unknown = () if ignore_unknown else tuple(unknown_key_problem(key) for key in data if key not in OPTIONS)
    if problems or version is None or source is None:
        raise ConfigError(path, [*problems, *unknown])
    return Config(path, Pin(version, source), settings, unknown)


def unknown_key_problem(key: str) -> str:
    close = difflib.get_close_matches(key, [*OPTIONS, "version", "source"], n=1)
    return f"unknown key {key!r}" + (f"; did you mean {close[0]!r}?" if close else "")


def parse_version(value: object) -> Version:
    if isinstance(value, str):
        if value in Track:
            return Track(value)
        if (tag := Tag.parse(value)) is not None:
            return tag
    shown = "missing" if value is None else repr(value)
    raise ValueError(f"version is {shown}; set it to latest, main, or a tag such as v1.0.0")


def parse_source(value: object, directory: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"source {value!r} is not a git URL or a path")
    reject_control_characters("source", value)
    scheme, separator, _ = value.partition("://")
    if not separator:
        if ":" in value.partition("/")[0]:
            raise ValueError(f"source {value!r} is an scp-style address; write it as ssh://user@host/path")
        return (directory / expand_user("source", value)).resolve().as_uri()
    if scheme not in SOURCE_SCHEMES:
        raise ValueError(f"source {value!r} uses {scheme}; use one of {', '.join(SOURCE_SCHEMES)}")
    # uv drops a query or a fragment from a git URL, and with it the @<commit> the hand-off appends.
    misread = [character for character in value if character.isspace() or character in "#?"]
    if misread:
        raise ValueError(f"source {value!r} contains {misread[0]!r}; percent-encode it or remove it")
    parts = urlsplit(value)
    if scheme == "file" and (parts.netloc or not parts.path.startswith("/")):
        raise ValueError(f"source {value!r} names no absolute path; write file:///absolute/path, or a plain path")
    if scheme != "file" and not parts.hostname:
        raise ValueError(f"source {value!r} names no host")
    return value


def parse_setting(key: str, value: object, base: Path) -> Any:
    spec = OPTIONS[key][1]
    if spec.get("action") is argparse.BooleanOptionalAction:
        if not isinstance(value, bool):
            raise ValueError(f"{key} is {value!r}; set it to true or false")
        return value
    if spec.get("action") == "append":
        if not isinstance(value, list) or not value:
            raise ValueError(f"{key} is {value!r}; set it to a nonempty list")
        return [parse_value(key, spec, item, base) for item in value]
    return parse_value(key, spec, value, base)


def parse_value(key: str, spec: Mapping[str, Any], value: object, base: Path) -> Any:
    kind = spec.get("type", str)
    if kind is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{key} is {value!r}; set it to a whole number")
        return value
    if not isinstance(value, str):
        raise ValueError(f"{key} is {value!r}; set it to a string")
    if "choices" in spec and value not in spec["choices"]:
        raise ValueError(f"{key} is {value!r}; set it to one of {', '.join(spec['choices'])}")
    if kind is Path:
        reject_control_characters(key, value)
        return base / expand_user(key, value)
    return kind(value)


def expand_user(key: str, value: str) -> Path:
    try:
        return Path(value).expanduser()
    except RuntimeError as error:
        raise ValueError(f"{key} {value!r} names a home directory that cannot be found; write the full path") from error


def reject_control_characters(key: str, value: str) -> None:
    if control := next((character for character in value if unicodedata.category(character) == "Cc"), None):
        raise ValueError(f"{key} {value!r} contains the control character {control!r}; remove it")


def with_version(text: str, tag: Tag) -> str:
    matches = list(VERSION_LINE.finditer(text))
    if len(matches) != 1:
        raise ValueError("cannot find the one version line to rewrite")
    updated = text[: matches[0].start("value")] + str(tag) + text[matches[0].end("value") :]
    if tomllib.loads(updated) != {**tomllib.loads(text), "version": str(tag)}:
        raise ValueError("rewriting the version line would change other keys")
    return updated
