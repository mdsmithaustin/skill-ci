#!/usr/bin/env python3
"""Reject likely PII in tracked files or the staged Git index."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path


EXAMPLE_EMAIL_DOMAINS = {"example.com", "example.net", "example.org"}
ALLOWED_EMAILS = {"git@github.com"}
EMAIL = re.compile(
    r"(?<![A-Za-z0-9.!#$%&'*+=?^_`{|}~/-])"
    r"[A-Za-z0-9!#$%&'*+=?^_`{|}~-]+"
    r"(?:\.[A-Za-z0-9!#$%&'*+=?^_`{|}~-]+)*"
    r"@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,63}"
    r"(?![A-Za-z0-9-])"
)
US_SOCIAL_SECURITY_NUMBER = re.compile(
    r"(?<!\d)(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}(?!\d)"
)
NORTH_AMERICAN_PHONE_NUMBER = re.compile(
    r"(?<!\w)(?:\+?1[-.\s]?)?(?:\([2-9]\d{2}\)|[2-9]\d{2})[-.\s]?[2-9]\d{2}[-.\s]\d{4}(?!\w)"
)
PAYMENT_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
DAILY_EXACT_LOCAL_TIME = re.compile(
    r"^(?=.*\b(?:daily|every\s+day)\b)"
    r"(?=.*(?<!\d)(?:[01]?\d|2[0-3]):[0-5]\d"
    r"(?:\s*(?:a\.?m\.?|p\.?m\.?))?(?!\w))"
    r"(?=.*\blocal\s+time\b)",
    re.IGNORECASE,
)
LAUNCH_AGENT_PATH = re.compile(
    r"(?<![\w.-])"
    r"(?:~|\$HOME|\$\{HOME\}|/Users/[^/\s\"'`<>]+)?"
    r"/Library/Launch"
    r"Agents(?:/[^\s\"'`<>]+)?"
)
HOME_RELATIVE_LOG_PATH = re.compile(
    r"(?<![\w.-])(?:~|\$HOME|\$\{HOME\})/[^\s\"'`<>]*\.log\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Source:
    name: str
    content: bytes | str


def git_output(*args: str) -> bytes:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True
    ).stdout


def source_name(raw_name: bytes) -> str:
    return raw_name.decode("utf-8", errors="surrogateescape")


def repository_sources() -> list[Source]:
    names = git_output("ls-files", "-z").split(b"\0")
    return [
        Source(name, Path(name).read_bytes())
        for raw_name in names
        if (name := source_name(raw_name))
    ]


def staged_sources() -> list[Source]:
    names = git_output("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").split(b"\0")
    return [
        Source(name, git_output("show", f":{name}"))
        for raw_name in names
        if (name := source_name(raw_name))
    ]


def explicit_path_sources(paths: Iterable[str]) -> list[Source]:
    return [Source(path, Path(path).read_bytes()) for path in paths]


def is_example_email(value: str) -> bool:
    local, domain = value.casefold().rsplit("@", 1)
    return bool(local) and domain in EXAMPLE_EMAIL_DOMAINS


def luhn_valid(value: str) -> bool:
    digits = [int(char) for char in value if char.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for index, digit in enumerate(reversed(digits)):
        if index % 2:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def line_findings(line: str) -> list[str]:
    findings: list[str] = []
    for match in EMAIL.finditer(line):
        value = match.group()
        if value.casefold() not in ALLOWED_EMAILS and not is_example_email(value):
            findings.append("email address")
    if US_SOCIAL_SECURITY_NUMBER.search(line):
        findings.append("US social security number")
    if NORTH_AMERICAN_PHONE_NUMBER.search(line):
        findings.append("North American phone number")
    if any(luhn_valid(match.group()) for match in PAYMENT_CARD.finditer(line)):
        findings.append("payment card number")
    if DAILY_EXACT_LOCAL_TIME.search(line):
        findings.append("local automation schedule")
    if LAUNCH_AGENT_PATH.search(line):
        findings.append("LaunchAgent path")
    if HOME_RELATIVE_LOG_PATH.search(line):
        findings.append("home-relative log path")
    return findings


def findings(source: Source) -> list[str]:
    """Return PII reports for one source without reading from the environment."""
    if isinstance(source.content, bytes):
        if b"\0" in source.content:
            return []
        text = source.content.decode("utf-8", errors="replace")
    else:
        text = source.content
    if "\0" in text:
        return []
    return [
        f"{source.name}:{number}: possible {kind}"
        for number, line in enumerate(text.splitlines(), start=1)
        for kind in line_findings(line)
    ]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--staged", action="store_true", help="scan staged additions and modifications"
    )
    parser.add_argument("paths", nargs="*", help="files to scan instead of the repository")
    args = parser.parse_args(argv)
    if args.staged and args.paths:
        parser.error("--staged cannot be combined with explicit paths")
    return args


def main() -> int:
    args = parse_args()
    try:
        sources = (
            explicit_path_sources(args.paths)
            if args.paths
            else staged_sources()
            if args.staged
            else repository_sources()
        )
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"check-pii: unable to read input: {error}", file=sys.stderr)
        return 2

    errors = [finding for source in sources for finding in findings(source)]
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
