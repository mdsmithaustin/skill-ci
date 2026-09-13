#!/usr/bin/env python3
"""Fail on broken content inside skills/**/*.md.

A relative Markdown destination in an inline link or reference definition must
resolve to something on disk. A relative path written in inline code follows
the same rule. Explicit placeholders such as `[PR]({url})` are not filesystem
paths.

A bolded name that reads as a skill reference must name a real directory under
the skills root. A principle- prefix always reads as one. Any other kebab name
reads as one only when "skill" appears on the same line. On a line mentioning a
principle, a bare name also resolves against its principle- directory, which is
how the suite writes "the **model-the-domain** principle skill". Here inline
code IS skipped, so a bolded word quoted inside backticks is not a reference.

Fenced blocks are skipped for link and sibling checks. Port substitution checks
scan every raw line, including templates inside fences. Blockquote and list
prefixes are removed before fence detection. A fence at any remaining
indentation counts, since telling it from an indented code block needs container
tracking this does not do. A fence that is never closed is itself a finding,
because it would otherwise silently hide the rest of the file.
"""
from __future__ import annotations

import argparse
import re
import string
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import unquote

ROOT = Path("skills")
IGNORE: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    kind: str
    detail: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.kind}: {self.detail}"


@dataclass(frozen=True)
class ParsedFile:
    path: Path
    raw: list[tuple[int, str]]
    prose: list[tuple[int, str]]
    unclosed_fence: int | None


CODE_TARGET = re.compile(r"`(\.\.?/[^`\s<>]+)`")
INLINE_CODE = re.compile(r"`[^`]*`")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})\s*(.*)$")
SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)
PLACEHOLDER_TARGET = re.compile(r"^\{[a-z][a-z0-9_-]*\}$", re.I)
LIST_MARKER = re.compile(r"(?:[*+-]|\d{1,9}[.)])(?=[ \t])")


def scan_blocks(lines: list[str]) -> tuple[list[tuple[int, str]], int | None]:
    """One fence walk for every caller, so no two checks can disagree about what is code."""
    prose: list[tuple[int, str]] = []
    fence: str | None = None
    opened = 0
    for lineno, line in enumerate(lines, start=1):
        m = FENCE.match(reference_content(line))
        if m:
            run, info = m.group(1), m.group(2).strip()
            if fence is None:
                fence, opened = run, lineno
            elif run[0] == fence[0] and len(run) >= len(fence) and not info:
                fence = None
            continue
        if fence is None:
            prose.append((lineno, line))
    return prose, (opened if fence else None)


def parse_markdown_destination(line: str, start: int) -> tuple[str, int] | None:
    pos = start
    target: list[str] = []

    if pos < len(line) and line[pos] == "<":
        pos += 1
        while pos < len(line) and line[pos] != ">":
            if line[pos] == "\\" and pos + 1 < len(line):
                target.extend((line[pos], line[pos + 1]))
                pos += 2
                continue
            target.append(line[pos])
            pos += 1
        if pos >= len(line):
            return None
        return "".join(target), pos + 1

    depth = 0
    while pos < len(line):
        char = line[pos]
        if char == "\\" and pos + 1 < len(line):
            target.extend((char, line[pos + 1]))
            pos += 2
            continue
        if char == "(":
            depth += 1
            target.append(char)
        elif char == ")":
            if depth == 0:
                break
            depth -= 1
            target.append(char)
        elif char.isspace() and depth == 0:
            break
        else:
            target.append(char)
        pos += 1
    if depth:
        return None
    return "".join(target), pos


def iter_markdown_targets(line: str) -> Iterator[str]:
    cursor = 0
    while (marker := line.find("](", cursor)) >= 0:
        start = marker + 2
        backslashes = 0
        before = marker - 1
        while before >= 0 and line[before] == "\\":
            backslashes += 1
            before -= 1
        if backslashes % 2:
            cursor = start
            continue

        label_depth = 0
        label_pos = marker - 1
        label_open = False
        while label_pos >= 0:
            label_backslashes = 0
            before_label = label_pos - 1
            while before_label >= 0 and line[before_label] == "\\":
                label_backslashes += 1
                before_label -= 1
            if label_backslashes % 2:
                label_pos = before_label
                continue
            if line[label_pos] == "]":
                label_depth += 1
            elif line[label_pos] == "[":
                if label_depth == 0:
                    label_open = True
                    break
                label_depth -= 1
            label_pos -= 1
        if not label_open:
            cursor = start
            continue

        parsed = parse_markdown_destination(line, start)
        if parsed is None:
            cursor = start
            continue
        target, pos = parsed

        pos = skip_markdown_title(line, pos)
        if pos is None:
            cursor = start
            continue

        if target and pos < len(line) and line[pos] == ")":
            yield target
            cursor = pos + 1
        else:
            cursor = start


def reference_content(line: str) -> str:
    pos = 0
    while pos < len(line):
        level = pos
        while pos < len(line) and line[pos] == " " and pos - level < 4:
            pos += 1
        if pos - level == 4:
            return line[level:]
        if pos < len(line) and line[pos] == ">":
            pos += 1
        else:
            marker = LIST_MARKER.match(line, pos)
            if marker is None:
                return line[pos:]
            pos = marker.end()
        if pos < len(line) and line[pos] in " \t":
            pos += 1
    return ""


def skip_markdown_title(line: str, pos: int) -> int | None:
    while pos < len(line) and line[pos].isspace():
        pos += 1
    if pos == len(line):
        return pos
    if line[pos] not in {'"', "'", "("}:
        return pos

    closing = ")" if line[pos] == "(" else line[pos]
    pos += 1
    while pos < len(line) and line[pos] != closing:
        if line[pos] == "\\" and pos + 1 < len(line):
            pos += 2
            continue
        pos += 1
    if pos == len(line):
        return None
    pos += 1
    while pos < len(line) and line[pos].isspace():
        pos += 1
    return pos


def iter_reference_targets(line: str) -> Iterator[str]:
    line = reference_content(line)
    if not line or line[0] != "[":
        return

    pos = 1
    while pos < len(line):
        if line[pos] == "\\" and pos + 1 < len(line):
            pos += 2
            continue
        if line[pos] == "]":
            break
        pos += 1
    if pos == 1 or pos + 1 >= len(line) or line[pos + 1] != ":":
        return

    pos += 2
    while pos < len(line) and line[pos].isspace():
        pos += 1
    parsed = parse_markdown_destination(line, pos)
    if parsed is None or not parsed[0]:
        return
    title_end = skip_markdown_title(line, parsed[1])
    if title_end == len(line):
        yield parsed[0]


def strip_unescaped_suffix(raw_target: str, markdown: bool) -> str:
    target: list[str] = []
    pos = 0
    while pos < len(raw_target):
        char = raw_target[pos]
        if markdown and char == "\\" and pos + 1 < len(raw_target):
            target.extend((char, raw_target[pos + 1]))
            pos += 2
            continue
        if char in "#?":
            break
        target.append(char)
        pos += 1
    return "".join(target)


def unescape_markdown_target(raw_target: str) -> str:
    target: list[str] = []
    pos = 0
    while pos < len(raw_target):
        char = raw_target[pos]
        if (
            char == "\\"
            and pos + 1 < len(raw_target)
            and raw_target[pos + 1] in string.punctuation
        ):
            target.append(raw_target[pos + 1])
            pos += 2
            continue
        target.append(char)
        pos += 1
    return "".join(target)


def relative_target(raw_target: str, *, markdown: bool) -> str | None:
    source = strip_unescaped_suffix(raw_target, markdown)
    scheme_target = unescape_markdown_target(source) if markdown else source
    if not scheme_target or SCHEME.match(scheme_target):
        return None
    target = unquote(scheme_target)
    if (
        target.startswith("/")
        or PLACEHOLDER_TARGET.match(target)
    ):
        return None
    return target


def check_relative_links(parsed: ParsedFile) -> Iterator[Finding]:
    for lineno, line in parsed.prose:
        targets = [
            *((target, True) for target in iter_markdown_targets(line)),
            *((target, True) for target in iter_reference_targets(line)),
            *((match.group(1), False) for match in CODE_TARGET.finditer(line)),
        ]
        for raw_target, markdown in targets:
            target = relative_target(raw_target, markdown=markdown)
            if target is not None:
                resolved = parsed.path.parent / target
                ok = resolved.is_file() if target.endswith(".md") else resolved.exists()
                if not ok:
                    yield Finding(
                        parsed.path,
                        lineno,
                        "relative-link",
                        f"target does not exist: {target}",
                    )


BOLD_NAME = re.compile(r"\*\*([a-z][a-z0-9-]*)\*\*")


def check_sibling_skill(parsed: ParsedFile) -> Iterator[Finding]:
    for lineno, raw in parsed.prose:
        line = INLINE_CODE.sub("``", raw)
        near_skill = "skill" in line
        principle_hint = "principle" in line
        for m in BOLD_NAME.finditer(line):
            name = m.group(1)
            if name in IGNORE:
                continue
            # A principle- prefix names a skill unambiguously. Any other bolded
            # kebab word needs "skill" nearby, or ordinary emphasis in prose
            # (glossary terms, enum bullets) would flood the findings.
            if not name.startswith("principle-") and not near_skill:
                continue
            if (ROOT / name).is_dir():
                continue
            if principle_hint and (ROOT / f"principle-{name}").is_dir():
                continue
            yield Finding(
                parsed.path,
                lineno,
                "sibling-skill",
                f"**{name}** has no matching directory under {ROOT}/",
            )


def check_unclosed_fence(parsed: ParsedFile) -> Iterator[Finding]:
    opened = parsed.unclosed_fence
    if opened is not None:
        yield Finding(
            parsed.path,
            opened,
            "unclosed-fence",
            "fence opened here is never closed, so link and sibling checks skip the rest of the file",
        )


PORT_SUBSTITUTIONS = {
    "pstack/skills/": "use the installed or verified-source root instead of the upstream monorepo path",
    "/deslop": "use the bundled unslop skill instead of the retired command",
}


def check_port_substitutions(parsed: ParsedFile) -> Iterator[Finding]:
    for lineno, line in parsed.raw:
        for old, replacement in PORT_SUBSTITUTIONS.items():
            if old in line:
                yield Finding(parsed.path, lineno, "port-substitution", replacement)


REGISTRY: list[tuple[str, Callable[[ParsedFile], Iterator[Finding]]]] = [
    ("relative-link", check_relative_links),
    ("sibling-skill", check_sibling_skill),
    ("unclosed-fence", check_unclosed_fence),
    ("port-substitution", check_port_substitutions),
]


def iter_markdown_files(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*.md")):
        if "node_modules" in path.parts:
            continue
        yield path


def main() -> int:
    global ROOT, IGNORE
    ap = argparse.ArgumentParser()
    ap.add_argument("--ignore", default="", help="comma-separated bolded names to never treat as skill references")
    ap.add_argument("root", nargs="?", default="skills")
    args = ap.parse_args()
    ROOT = Path(args.root)
    IGNORE = frozenset(n for n in args.ignore.split(",") if n)

    findings: list[Finding] = []
    files_checked = 0
    for path in iter_markdown_files(ROOT):
        files_checked += 1
        raw = list(enumerate(path.read_text(encoding="utf-8").splitlines(), start=1))
        prose, unclosed = scan_blocks([line for _lineno, line in raw])
        parsed = ParsedFile(path, raw, prose, unclosed)
        for _name, check in REGISTRY:
            findings.extend(check(parsed))

    findings.sort(key=lambda f: (str(f.path), f.line, f.kind))
    for f in findings:
        print(f)
    print(f"content: {files_checked} files, {len(findings)} findings", file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
