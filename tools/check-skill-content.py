#!/usr/bin/env python3
"""Fail on broken content inside skills/**/*.md.

Relative destinations in CommonMark links and reference definitions must resolve
to something on disk. Whitespace-free paths beginning `./` or `../` and quoted
paths with spaces that occupy an entire inline-code span follow the same rule.
Explicit project placeholders such as `[PR]({url})` are skipped.

A bolded name that reads as a skill reference must name a real directory under
the skills root. A principle- prefix always reads as one. Any other kebab name
reads as one only when "skill" appears on the same rendered line. On a line that
mentions a principle, a bare name also resolves against its principle- directory.

CommonMark code blocks are skipped for link and sibling checks. Port substitution
checks scan every raw line, including templates inside code blocks. An unclosed
fence is itself a finding because it would otherwise hide the rest of the file.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator, Mapping
from urllib.parse import unquote

from markdown_it import MarkdownIt
from markdown_it.rules_inline import image, link
from markdown_it.rules_inline.backticks import backtick
from markdown_it.rules_inline.state_inline import StateInline
from markdown_it.token import Token

ROOT = Path("skills")
IGNORE: frozenset[str] = frozenset()
MARKDOWN = MarkdownIt("commonmark")


def rendered_newlines(tokens: list[Token]) -> int:
    total = 0
    for token in tokens:
        total += token.type in {"softbreak", "hardbreak"}
        total += int(token.meta.get("line_advance", 0))
        if token.type == "image" and token.children:
            total += rendered_newlines(token.children)
    return total


def source_positioned(
    rule: Callable[[StateInline, bool], bool], token_type: str
) -> Callable[[StateInline, bool], bool]:
    """Attach an inline source offset to tokens used in diagnostics."""

    def wrapped(state: StateInline, silent: bool) -> bool:
        start = state.pos
        token_count = len(state.tokens)
        matched = rule(state, silent)
        if matched and not silent:
            created = state.tokens[token_count:]
            for token in created:
                if token.type == token_type:
                    token.meta["source_offset"] = start
                    source_newlines = state.src[start : state.pos].count("\n")
                    if token_type == "link_open":
                        raw_destination = raw_inline_destination(state, start, state.pos)
                        if raw_destination is not None:
                            token.meta["raw_destination"] = raw_destination
                        represented = rendered_newlines(created)
                        for item in reversed(created):
                            if item.type == "link_close":
                                item.meta["line_advance"] = max(
                                    source_newlines - represented, 0
                                )
                                break
                    elif token_type == "image":
                        represented = rendered_newlines(token.children or [])
                        token.meta["line_advance"] = max(
                            source_newlines - represented, 0
                        )
                    else:
                        token.meta["line_advance"] = source_newlines
                    break
        return matched

    return wrapped


for _rule_name, _token_type, _rule in (
    ("backticks", "code_inline", backtick),
    ("link", "link_open", link),
    ("image", "image", image),
):
    MARKDOWN.inline.ruler.at(_rule_name, source_positioned(_rule, _token_type))


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
    tokens: list[Token]
    references: dict[str, dict[str, Any]]
    duplicate_references: list[dict[str, Any]]


@dataclass(frozen=True)
class InlineLinkExceptions:
    destinations_by_source: Mapping[PurePosixPath, frozenset[str]]

    def permits(self, path: Path, raw_destination: str) -> bool:
        try:
            source = PurePosixPath(path.relative_to(ROOT).as_posix())
        except ValueError:
            return False
        return raw_destination in self.destinations_by_source.get(source, frozenset())


INLINE_LINK_EXCEPTIONS = InlineLinkExceptions({})


CODE_PATH = re.compile(r"\.\.?/[^\s<>]+")
QUOTED_CODE_PATH = re.compile(
    r'(?:"(?P<double>\.\.?/[^"\r\n<>]+)"|'
    r"'(?P<single>\.\.?/[^'\r\n<>]+)')"
)
SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)
SKILL_NAME = re.compile(r"[a-z][a-z0-9-]*")
INLINE_PLACEHOLDER = re.compile(
    r"(?<=\]\()(?P<space>[ \t\r\n]*)(?:"
    r"<\{[a-z][a-z0-9_-]*\}(?:[\\]?[#?][^>\s]*)?>|"
    r"\{[a-z][a-z0-9_-]*\}(?:[\\]?[#?][^)\s]*)?)"
    r"(?=(?:[ \t\r\n]*\)|[ \t\r\n]+[\"'(]))",
    re.I,
)
REFERENCE_PLACEHOLDER = re.compile(
    r"(?m)(?<=\]:)(?P<space>[ \t]*(?:\r?\n[ \t]+)?)"
    r"(?:<\{[a-z][a-z0-9_-]*\}(?:[\\]?[#?][^>\s]*)?>|"
    r"\{[a-z][a-z0-9_-]*\}(?:[\\]?[#?][^\s]*)?)"
    r"(?=(?:[ \t]*$|[ \t\r\n]+[\"'(]))",
    re.I,
)


def protect_explicit_placeholders(text: str) -> str:
    def replacement(match: re.Match[str]) -> str:
        return match.group("space") + "placeholder:ignored"

    text = INLINE_PLACEHOLDER.sub(replacement, text)
    return REFERENCE_PLACEHOLDER.sub(replacement, text)


def raw_inline_destination(state: StateInline, start: int, end: int) -> str | None:
    label_end = state.md.helpers.parseLinkLabel(state, start, True)
    position = label_end + 1
    if label_end < 0 or position >= end or state.src[position] != "(":
        return None
    position += 1
    while position < end and state.src[position] in " \t\n":
        position += 1
    destination = state.md.helpers.parseLinkDestination(state.src, position, end)
    return state.src[position : destination.pos] if destination.ok else None


def parse_file(path: Path) -> ParsedFile:
    text = path.read_text(encoding="utf-8")
    env: dict[str, Any] = {}
    tokens = MARKDOWN.parse(protect_explicit_placeholders(text), env)
    references = env.get("references", {})
    return ParsedFile(
        path=path,
        raw=list(enumerate(text.splitlines(), start=1)),
        tokens=tokens,
        references=references,
        duplicate_references=env.get("duplicate_refs", []),
    )


def relative_target(href: str, *, markdown: bool) -> str | None:
    source = re.split(r"[?#]", href, maxsplit=1)[0] if markdown else href
    if not source or SCHEME.match(source) or source.startswith("/"):
        return None
    target = unquote(source) if markdown else source
    return None if target.startswith("/") else target


def load_inline_link_exceptions(path: Path | None) -> InlineLinkExceptions:
    if path is None:
        return InlineLinkExceptions({})
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"cannot read link exceptions file {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid link exceptions JSON in {path}: {error.msg}") from error
    if not isinstance(document, dict) or set(document) != {
        "version",
        "inline_link_exceptions",
    }:
        raise ValueError(
            "link exceptions must contain only version and inline_link_exceptions"
        )
    if type(document["version"]) is not int or document["version"] != 1:
        raise ValueError("link exceptions version must be 1")
    entries = document["inline_link_exceptions"]
    if not isinstance(entries, dict):
        raise ValueError("inline_link_exceptions must be an object")
    destinations_by_source: dict[PurePosixPath, frozenset[str]] = {}
    for source, destinations in entries.items():
        if not isinstance(source, str) or not source:
            raise ValueError("link exception source paths must be nonempty strings")
        source_path = PurePosixPath(source)
        if (
            source_path.as_posix() != source
            or source_path.is_absolute()
            or any(part in {".", ".."} for part in source_path.parts)
        ):
            raise ValueError(f"link exception source path is not root-relative: {source}")
        if not isinstance(destinations, list) or not destinations:
            raise ValueError(f"link exception destinations must be a nonempty list: {source}")
        if any(
            not isinstance(destination, str) or not destination
            for destination in destinations
        ):
            raise ValueError(
                f"link exception destinations must be nonempty strings: {source}"
            )
        if len(set(destinations)) != len(destinations):
            raise ValueError(f"link exception destinations must not repeat: {source}")
        destinations_by_source[source_path] = frozenset(destinations)
    return InlineLinkExceptions(destinations_by_source)


def inline_code_path(content: str) -> str | None:
    if CODE_PATH.fullmatch(content):
        return content
    quoted = QUOTED_CODE_PATH.fullmatch(content)
    return (quoted.group("double") or quoted.group("single")) if quoted else None


def finding_for_target(
    parsed: ParsedFile, line: int, href: str, *, markdown: bool = True
) -> Finding | None:
    target = relative_target(href, markdown=markdown)
    if target is None:
        return None
    resolved = parsed.path.parent / target
    try:
        ok = resolved.is_file() if target.endswith(".md") else resolved.exists()
    except (OSError, ValueError):
        ok = False
    if ok:
        return None
    return Finding(
        parsed.path,
        line,
        "relative-link",
        f"target does not exist: {target}",
    )


def inline_children(parsed: ParsedFile) -> Iterator[tuple[Token, list[Token]]]:
    for token in parsed.tokens:
        if token.type == "inline" and token.map is not None:
            yield token, token.children or []


def token_line(parent: Token, child: Token, offset: int | None = None) -> int:
    if offset is None:
        offset = int(child.meta.get("source_offset", 0))
    return parent.map[0] + parent.content.count("\n", 0, offset) + 1


def nested_image_code_spans(
    children: list[Token], base_offset: int
) -> Iterator[tuple[Token, int]]:
    for child in children:
        offset = base_offset + int(child.meta.get("source_offset", 0))
        if child.type == "code_inline":
            yield child, offset
        elif child.type == "image" and child.children:
            yield from nested_image_code_spans(child.children, offset + 2)


def check_relative_links(parsed: ParsedFile) -> Iterator[Finding]:
    reference_hrefs: set[str] = set()
    for definition in parsed.references.values():
        href = str(definition["href"])
        reference_hrefs.add(href)
        source_map = definition.get("map")
        line = int(source_map[0]) + 1 if source_map else 1
        finding = finding_for_target(parsed, line, href)
        if finding is not None:
            yield finding
    for definition in parsed.duplicate_references:
        href = str(definition["href"])
        source_map = definition.get("map")
        line = int(source_map[0]) + 1 if source_map else 1
        finding = finding_for_target(parsed, line, href)
        if finding is not None:
            yield finding

    for parent, children in inline_children(parsed):
        for child in children:
            line = token_line(parent, child)
            if child.type in {"link_open", "image"}:
                attribute = "href" if child.type == "link_open" else "src"
                href = child.attrGet(attribute) or ""
                if href not in reference_hrefs:
                    finding = finding_for_target(parsed, line, href)
                    if finding is not None and not (
                        child.type == "link_open"
                        and INLINE_LINK_EXCEPTIONS.permits(
                            parsed.path,
                            str(child.meta.get("raw_destination", "")),
                        )
                    ):
                        yield finding
                if child.type == "image" and child.children:
                    image_offset = int(child.meta.get("source_offset", 0)) + 2
                    for code, offset in nested_image_code_spans(
                        child.children, image_offset
                    ):
                        if (path := inline_code_path(code.content)) is not None:
                            finding = finding_for_target(
                                parsed,
                                token_line(parent, code, offset),
                                path,
                                markdown=False,
                            )
                            if finding is not None:
                                yield finding
            elif child.type == "code_inline" and (
                path := inline_code_path(child.content)
            ) is not None:
                finding = finding_for_target(
                    parsed, line, path, markdown=False
                )
                if finding is not None:
                    yield finding


def rendered_lines(
    children: list[Token], first_line: int
) -> dict[int, tuple[str, list[str]]]:
    text_by_line: dict[int, list[str]] = {}
    names_by_line: dict[int, list[str]] = {}
    strong: list[tuple[int, list[str]]] = []
    line = first_line

    def consume(tokens: list[Token], current_line: int) -> int:
        for child in tokens:
            if child.type == "strong_open":
                strong.append((current_line, []))
            elif child.type == "strong_close":
                if strong:
                    opened, pieces = strong.pop()
                    name = "".join(pieces)
                    if opened == current_line and SKILL_NAME.fullmatch(name):
                        names_by_line.setdefault(current_line, []).append(name)
            elif child.type == "text":
                text_by_line.setdefault(current_line, []).append(child.content)
                for _opened, pieces in strong:
                    pieces.append(child.content)
            elif child.type == "image" and child.children:
                current_line = consume(child.children, current_line)
            elif child.type in {"softbreak", "hardbreak"}:
                current_line += 1
            current_line += int(child.meta.get("line_advance", 0))
        return current_line

    consume(children, line)

    return {
        line_number: (
            "".join(text_by_line.get(line_number, [])),
            names_by_line.get(line_number, []),
        )
        for line_number in text_by_line.keys() | names_by_line.keys()
    }


def check_sibling_skill(parsed: ParsedFile) -> Iterator[Finding]:
    for parent, children in inline_children(parsed):
        lines = rendered_lines(children, parent.map[0] + 1)
        for line, (visible, names) in lines.items():
            near_skill = "skill" in visible
            principle_hint = "principle" in visible
            for name in names:
                if name in IGNORE:
                    continue
                if not name.startswith("principle-") and not near_skill:
                    continue
                if (ROOT / name).is_dir():
                    continue
                if principle_hint and (ROOT / f"principle-{name}").is_dir():
                    continue
                yield Finding(
                    parsed.path,
                    line,
                    "sibling-skill",
                    f"**{name}** has no matching directory under {ROOT}/",
                )


def check_unclosed_fence(parsed: ParsedFile) -> Iterator[Finding]:
    for token in parsed.tokens:
        if token.type != "fence" or token.map is None:
            continue
        if token.level > 0 and token.map[1] < len(parsed.raw):
            continue
        source_lines = token.map[1] - token.map[0]
        content_lines = len(token.content.splitlines())
        if source_lines != content_lines + 2:
            yield Finding(
                parsed.path,
                token.map[0] + 1,
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
    global ROOT, IGNORE, INLINE_LINK_EXCEPTIONS
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--ignore",
        default="",
        help="comma-separated bolded names to never treat as skill references",
    )
    ap.add_argument(
        "--link-exceptions-file",
        type=Path,
        help="JSON file that allows exact missing direct inline Markdown links",
    )
    ap.add_argument("root", nargs="?", default="skills")
    args = ap.parse_args()
    ROOT = Path(args.root)
    IGNORE = frozenset(n for n in args.ignore.split(",") if n)
    try:
        INLINE_LINK_EXCEPTIONS = load_inline_link_exceptions(
            args.link_exceptions_file
        )
    except ValueError as error:
        ap.error(str(error))

    findings: list[Finding] = []
    files_checked = 0
    for path in iter_markdown_files(ROOT):
        files_checked += 1
        parsed = parse_file(path)
        for _name, check in REGISTRY:
            findings.extend(check(parsed))

    findings.sort(key=lambda f: (str(f.path), f.line, f.kind))
    for finding in findings:
        print(finding)
    print(f"content: {files_checked} files, {len(findings)} findings", file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
