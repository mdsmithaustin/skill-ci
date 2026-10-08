from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from importlib import metadata
from pathlib import Path
from typing import NewType, NoReturn

from skill_ci import children, files
from skill_ci.config import Pin, Source, Tag, Track, Version
from skill_ci.harness import shell_status

PINNED = "SKILL_CI_PINNED"
STARTED = "SKILL_CI_STARTED"
HANDOFF_FAILED = 126
# uv's console script starts Python without -I, so these would load other code under the pinned commit's name.
SHADOWING = frozenset({"PYTHONPATH", "PYTHONHOME"})
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
    source: Source
    fetched_at: datetime
    main: Commit | None
    tags: Mapping[Tag, Commit]


@dataclass(frozen=True)
class Resolved:
    name: str
    commit: Commit
    fetched_at: datetime
    unreachable: str | None = None
    newer: Tag | None = None


def resolve(pin: Pin, cache: Path, now: datetime) -> Resolved:
    cached = read_cache(cache, pin.source)
    if (
        isinstance(pin.version, Tag)
        and cached is not None
        and pin.version in cached.tags
        and timedelta(0) <= now - cached.fetched_at < NEWER_TAG_CHECK_INTERVAL
    ):
        return answer(pin.version, cached)
    try:
        return answer(pin.version, fetch(pin, cache, now))
    except Unreachable as error:
        if cached is None:
            raise PinError(f"cannot reach {pin.source} ({error}), and no version was ever resolved from it") from error
        return answer(pin.version, cached, str(error))


def answer(version: Version, refs: Refs, unreachable: str | None = None) -> Resolved:
    match version:
        case Tag():
            if version not in refs.tags:
                if unreachable is None:
                    raise PinError(f"{refs.source} has no tag {version}")
                raise PinError(f"cannot reach {refs.source} ({unreachable}), and the versions cached on {refs.fetched_at:%Y-%m-%d} have no tag {version}")
            latest = newest(refs)
            return Resolved(str(version), refs.tags[version], refs.fetched_at, newer=latest if latest > version else None)
        case Track.LATEST:
            latest = newest(refs)
            return Resolved(str(latest), refs.tags[latest], refs.fetched_at, unreachable)
        case Track.MAIN:
            if refs.main is None:
                raise PinError(f"{refs.source} has no main branch")
            return Resolved(str(Track.MAIN), refs.main, refs.fetched_at, unreachable)


def newest(refs: Refs) -> Tag:
    if not refs.tags:
        raise PinError(f"{refs.source} has no tag such as v1.0.0")
    return max(refs.tags)


def newest_tag(pin: Pin, cache: Path, now: datetime) -> Tag:
    try:
        return newest(fetch(pin, cache, now))
    except Unreachable as error:
        raise PinError(f"cannot reach {pin.source} ({error})") from error


def fetch(pin: Pin, cache: Path, now: datetime) -> Refs:
    try:
        listed = children.run(
            ["git", "ls-remote", pin.source, "refs/heads/main", "refs/tags/v*"],
            capture=True,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            timeout=LS_REMOTE_TIMEOUT,
        )
    except OSError as error:
        raise Unreachable(f"cannot run git: {error}") from error
    except subprocess.TimeoutExpired as error:
        raise Unreachable(f"git ls-remote gave no answer in {LS_REMOTE_TIMEOUT} s") from error
    if listed.returncode != 0:
        errors = listed.stderr.decode(errors="replace")
        reason = next((line for line in errors.splitlines() if line.strip()), f"git ls-remote exited {listed.returncode}")
        raise Unreachable(reason.removeprefix("fatal: "))
    refs = parse_listing(pin.source, now, listed.stdout.decode(errors="replace"))
    # A stop between creating the temporary file and renaming it would leave the temporary file behind.
    with children.stopping_signals():
        write_cache(cache, refs)
    return refs


def parse_listing(source: Source, fetched_at: datetime, listing: str) -> Refs:
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


def cache_file(cache: Path, source: Source) -> Path:
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
        files.atomic_write(path, (json.dumps(record, indent=2) + "\n").encode())
    except OSError as error:
        print(f"skill-ci: warning: cannot cache the versions of {refs.source} in {path}: {error}", file=sys.stderr)


def read_cache(cache: Path, source: Source) -> Refs | None:
    try:
        refs = as_refs(json.loads(files.read_regular_text(cache_file(cache, source))))
    except (OSError, ValueError, RecursionError):
        return None
    return refs if refs.source == source else None


def as_refs(value: object) -> Refs:
    match value:
        case {"source": str(source), "fetched_at": str(fetched_at), "main": main, "tags": dict(tags)}:
            fetched = datetime.fromisoformat(fetched_at)
            if fetched.tzinfo is None:
                raise ValueError("fetched_at names no time zone")
            commits = {tag: as_commit(commit) for name, commit in tags.items() if (tag := Tag.parse(name)) is not None}
            return Refs(Source(source), fetched, None if main is None else as_commit(main), commits)
    raise ValueError("not a cache record")


def as_commit(value: object) -> Commit:
    if not isinstance(value, str) or COMMIT.fullmatch(value) is None:
        raise ValueError(f"{value!r} is not a commit")
    return Commit(value)


def running_commit(distribution: metadata.Distribution) -> Commit | None:
    try:
        record = json.loads(distribution.read_text("direct_url.json") or "{}")
        return as_commit(record["vcs_info"]["commit_id"])
    except (ValueError, KeyError, TypeError):
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


def rerun(pin: Pin, commit: Commit, arguments: Sequence[str]) -> NoReturn:
    uv = shutil.which("uv")
    if uv is None:
        raise HandoffError(f"running the pinned commit {commit} needs uv on PATH", status=127)
    try:
        # The pinned run's own window would open after the scratch directory exists and close before it is removed.
        with children.stopping_signals(), tempfile.TemporaryDirectory(prefix="skill-ci-") as scratch:
            started = Path(scratch) / "started"
            # Online, uv revalidates package index pages cached more than 10 minutes ago even when the pinned commit is
            # built, which is slower and fails without a network. Offline fails only when uv lacks something it needs.
            for network in (("--offline",), ()):
                if not network:
                    print(f"skill-ci: uv could not start the pinned commit {commit} offline; trying again with network access", file=sys.stderr)
                status = children.run(
                    [uv, "tool", "run", *network, "--isolated", "--from", f"git+{pin.source}@{commit}", "skill-ci", *arguments],
                    env={**{key: value for key, value in os.environ.items() if key not in SHADOWING}, PINNED: commit, STARTED: str(started)},
                    grace=children.HAND_OFF_GRACE,
                ).returncode
                if status <= 0 or started.exists():
                    break
            else:
                raise HandoffError(f"uv could not start the pinned commit {commit}; see the uv error above")
    except OSError as error:
        raise HandoffError(f"cannot run {uv} for the pinned commit {commit}: {error}") from error
    raise SystemExit(shell_status(status))
