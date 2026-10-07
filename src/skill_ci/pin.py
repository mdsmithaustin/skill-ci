from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from importlib import metadata
from pathlib import Path
from typing import NewType

from skill_ci.config import Pin, Tag, Track, Version

PINNED = "SKILL_CI_PINNED"
STARTED = "SKILL_CI_STARTED"
HANDOFF_FAILED = 126
# uv's console script starts Python without -I, so these would load other code under the pinned commit's name.
SHADOWING = frozenset({"PYTHONPATH", "PYTHONHOME"})
# uv forwards these to the tool it runs, and SIGINT only when stdin is not a terminal, because at a terminal
# Ctrl-C already reaches every process in the foreground group.
FORWARDED = (signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT, signal.SIGUSR1, signal.SIGUSR2)
NEWER_TAG_CHECK_INTERVAL = timedelta(days=1)
LS_REMOTE_TIMEOUT = 5
COMMIT = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")

Commit = NewType("Commit", str)


class PinError(Exception):
    pass


class Unreachable(Exception):
    pass


class HandoffError(Exception):
    def __init__(self, message: str, status: int = HANDOFF_FAILED) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Refs:
    source: str
    fetched_at: datetime
    main: Commit | None
    tags: Mapping[Tag, Commit]


@dataclass(frozen=True)
class Offline:
    reason: str
    fetched_at: datetime


@dataclass(frozen=True)
class Resolved:
    name: str
    commit: Commit
    offline: Offline | None = None
    newer: Tag | None = None


def resolve(pin: Pin, cache: Path, now: datetime) -> Resolved:
    cached = read_cache(cache, pin.source)
    if (
        isinstance(pin.version, Tag)
        and cached is not None
        and pin.version in cached.tags
        and timedelta(0) <= now - cached.fetched_at < NEWER_TAG_CHECK_INTERVAL
    ):
        return answer(pin.version, cached, None)
    try:
        return answer(pin.version, fetch(pin.source, cache, now), None)
    except Unreachable as error:
        if cached is None:
            raise PinError(f"cannot reach {pin.source} ({error}), and no version was ever resolved from it") from error
        return answer(pin.version, cached, Offline(str(error), cached.fetched_at))


def answer(version: Version, refs: Refs, offline: Offline | None) -> Resolved:
    match version:
        case Tag():
            if version not in refs.tags and offline is not None:
                raise PinError(f"cannot reach {refs.source} ({offline.reason}), and the versions cached on {offline.fetched_at:%Y-%m-%d} have no tag {version}")
            if version not in refs.tags:
                raise PinError(f"{refs.source} has no tag {version}")
            newest = max(refs.tags)
            return Resolved(str(version), refs.tags[version], newer=newest if newest > version else None)
        case Track.LATEST:
            if not refs.tags:
                raise PinError(f"{refs.source} has no tag such as v1.0.0")
            newest = max(refs.tags)
            return Resolved(str(newest), refs.tags[newest], offline)
        case Track.MAIN:
            if refs.main is None:
                raise PinError(f"{refs.source} has no main branch")
            return Resolved(str(Track.MAIN), refs.main, offline)


def newest_tag(source: str, cache: Path, now: datetime) -> Tag:
    try:
        refs = fetch(source, cache, now)
    except Unreachable as error:
        raise PinError(f"cannot reach {source} ({error})") from error
    if not refs.tags:
        raise PinError(f"{source} has no tag such as v1.0.0")
    return max(refs.tags)


def fetch(source: str, cache: Path, now: datetime) -> Refs:
    try:
        listing = subprocess.run(
            ["git", "ls-remote", source, "refs/heads/main", "refs/tags/v*"],
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=LS_REMOTE_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise Unreachable(f"git ls-remote gave no answer in {LS_REMOTE_TIMEOUT} s") from error
    except OSError as error:
        raise Unreachable(f"cannot run git: {error}") from error
    if listing.returncode != 0:
        reason = next((line for line in listing.stderr.splitlines() if line.strip()), f"git ls-remote exited {listing.returncode}")
        raise Unreachable(reason.removeprefix("fatal: "))
    refs = parse_listing(source, now, listing.stdout)
    write_cache(cache, refs)
    return refs


def parse_listing(source: str, fetched_at: datetime, listing: str) -> Refs:
    main: Commit | None = None
    tags: dict[Tag, Commit] = {}
    peeled: dict[Tag, Commit] = {}
    for line in listing.splitlines():
        object_id, _, ref = line.partition("\t")
        if not COMMIT.fullmatch(object_id):
            continue
        if ref == "refs/heads/main":
            main = Commit(object_id)
        elif (name := ref.removeprefix("refs/tags/")) != ref and (tag := Tag.parse(name.removesuffix("^{}"))) is not None:
            # An annotated tag lists its tag object first and the commit it names on a ^{} line.
            (peeled if name.endswith("^{}") else tags)[tag] = Commit(object_id)
    return Refs(source, fetched_at, main, {**tags, **peeled})


def cache_directory() -> Path:
    configured = Path(os.environ.get("XDG_CACHE_HOME", ""))
    return (configured if configured.is_absolute() else Path.home() / ".cache") / "skill-ci"


def cache_file(cache: Path, source: str) -> Path:
    return cache / "refs" / f"{hashlib.sha256(source.encode()).hexdigest()}.json"


def write_cache(cache: Path, refs: Refs) -> None:
    path = cache_file(cache, refs.source)
    record = {
        "source": refs.source,
        "fetched_at": refs.fetched_at.isoformat(),
        "main": refs.main,
        "tags": {str(tag): commit for tag, commit in sorted(refs.tags.items())},
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f"{path.name}.", delete_on_close=False) as partial:
            partial.write(json.dumps(record, indent=2) + "\n")
            partial.close()
            os.replace(partial.name, path)
    except OSError as error:
        print(f"skill-ci: warning: cannot cache the versions of {refs.source} in {path}: {error}", file=sys.stderr)


def read_cache(cache: Path, source: str) -> Refs | None:
    try:
        record = json.loads(cache_file(cache, source).read_text(encoding="utf-8"))
        if record["source"] != source:
            return None
        tags = {tag: as_commit(commit) for name, commit in record["tags"].items() if (tag := Tag.parse(name)) is not None}
        main = None if record["main"] is None else as_commit(record["main"])
        fetched_at = datetime.fromisoformat(record["fetched_at"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    return Refs(source, fetched_at, main, tags) if fetched_at.tzinfo is not None else None


def as_commit(value: object) -> Commit:
    if not isinstance(value, str) or COMMIT.fullmatch(value) is None:
        raise ValueError(f"{value!r} is not a commit")
    return Commit(value)


def running_commit() -> Commit | None:
    try:
        record = json.loads(metadata.distribution("skill-ci").read_text("direct_url.json") or "{}")
        return as_commit(record["vcs_info"]["commit_id"])
    except (metadata.PackageNotFoundError, ValueError, KeyError, TypeError):
        return None


def claim(environment: MutableMapping[str, str], running: Commit | None) -> bool:
    started = environment.pop(STARTED, "")
    pinned = environment.pop(PINNED, "")
    if started:
        try:
            Path(started).touch()
        except OSError as error:
            raise HandoffError(f"cannot record that the pinned commit started: {error}") from error
    if not pinned:
        return False
    if COMMIT.fullmatch(pinned) is None:
        raise HandoffError(f"{PINNED} is {pinned!r}, not a full commit")
    if running is None:
        raise HandoffError(f"{PINNED} names {pinned}, but this skill-ci was not installed from a git commit")
    if running != pinned:
        raise HandoffError(f"{PINNED} names {pinned}, but this skill-ci was installed from {running}")
    return True


def rerun(source: str, commit: Commit, arguments: Sequence[str]) -> int:
    uv = shutil.which("uv")
    if uv is None:
        raise HandoffError(f"running the pinned commit {commit} needs uv on PATH", status=127)
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        scratch = tempfile.TemporaryDirectory(prefix="skill-ci-")
        started = Path(scratch.name) / "started"
        child = subprocess.Popen(
            [uv, "tool", "run", "--isolated", "--from", f"git+{source}@{commit}", "skill-ci", *arguments],
            env={**{key: value for key, value in os.environ.items() if key not in SHADOWING}, PINNED: commit, STARTED: str(started)},
        )
    except OSError as error:
        raise HandoffError(f"cannot run {uv} for the pinned commit {commit}: {error}") from error
    with scratch:
        status = supervise(child)
        if status > 0 and not started.exists():
            raise HandoffError(
                f"uv could not start the pinned commit {commit} (exit {status}); fix the uv error above, "
                f"such as no network access to {source} or a UV_PYTHON that this commit does not support"
            )
    return status if status >= 0 else 128 - status


def supervise(child: subprocess.Popen[bytes]) -> int:
    at_terminal = os.isatty(0)

    def forward(number: int, _frame: object) -> None:
        if number != signal.SIGINT or not at_terminal:
            child.send_signal(number)

    previous = {number: signal.signal(number, forward) for number in (signal.SIGINT, *FORWARDED)}
    try:
        return child.wait()
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
