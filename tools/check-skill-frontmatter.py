#!/usr/bin/env python3
"""Validate skill metadata, Codex invocation policy, and trigger declarations."""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from yaml.constructor import ConstructorError
from yaml.resolver import BaseResolver


FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", re.DOTALL)
SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


@dataclass(frozen=True)
class SkillMetadata:
    path: Path
    name: str
    description: str
    implicit_allowed: bool


@dataclass(frozen=True)
class Diagnostic:
    path: Path
    message: str
    line: int | None = None

    def __str__(self) -> str:
        position = f":{self.line}" if self.line is not None else ""
        return f"{self.path}{position}: {self.message}"


class UniqueKeySafeLoader(yaml.SafeLoader):
    pass


def construct_unique_mapping(loader: UniqueKeySafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise ConstructorError("while constructing a mapping", node.start_mark, "mapping keys must be strings", key_node.start_mark)
        if key in mapping:
            raise ConstructorError("while constructing a mapping", node.start_mark, f"duplicate key {key!r}", key_node.start_mark)
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeySafeLoader.add_constructor(BaseResolver.DEFAULT_MAPPING_TAG, construct_unique_mapping)


def yaml_error(path: Path, error: yaml.YAMLError, line_offset: int) -> Diagnostic:
    mark = getattr(error, "problem_mark", None) or getattr(error, "context_mark", None)
    line = mark.line + 1 + line_offset if mark is not None else None
    return Diagnostic(path, f"invalid YAML: {getattr(error, 'problem', str(error))}", line)


def load_yaml_mapping(text: str, path: Path, line_offset: int = 0) -> tuple[dict[str, Any] | None, list[Diagnostic]]:
    try:
        documents = list(yaml.load_all(text, Loader=UniqueKeySafeLoader))
    except yaml.YAMLError as error:
        return None, [yaml_error(path, error, line_offset)]
    if len(documents) != 1:
        return None, [Diagnostic(path, "YAML must contain exactly one document")]
    if not isinstance(documents[0], dict):
        return None, [Diagnostic(path, "YAML document must be a mapping")]
    return documents[0], []


def nonblank_string(value: Any, label: str, path: Path, errors: list[Diagnostic], limit: int | None = None) -> str | None:
    if not isinstance(value, str):
        errors.append(Diagnostic(path, f"{label} must be a string"))
        return None
    if not value.strip():
        errors.append(Diagnostic(path, f"{label} must not be blank"))
        return None
    if limit is not None and len(value) > limit:
        errors.append(Diagnostic(path, f"{label} must be at most {limit} characters"))
        return None
    return value


def read_skill(path: Path) -> tuple[SkillMetadata | None, list[Diagnostic]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        return None, [Diagnostic(path, f"cannot read file: {error}")]
    match = FRONTMATTER.match(text)
    if match is None:
        return None, [Diagnostic(path, "missing frontmatter")]
    block = match.group(1)
    if "\t" in block:
        return None, [Diagnostic(path, "tab character in frontmatter")]
    fields, errors = load_yaml_mapping(block, path, line_offset=1)
    if fields is None:
        return None, errors
    name = nonblank_string(fields.get("name"), "name", path, errors, 64)
    description = nonblank_string(fields.get("description"), "description", path, errors, 1024)
    if name is not None:
        if SKILL_NAME.fullmatch(name) is None:
            errors.append(Diagnostic(path, "name must use lowercase ASCII letters, digits, and single hyphens"))
        if name != path.parent.name:
            errors.append(Diagnostic(path, f"name {name!r} != directory {path.parent.name!r}"))
    for field, limit in (("compatibility", 500), ("license", None), ("allowed-tools", None)):
        if field in fields:
            nonblank_string(fields[field], field, path, errors, limit)
    if "metadata" in fields:
        metadata = fields["metadata"]
        if not isinstance(metadata, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in metadata.items()):
            errors.append(Diagnostic(path, "metadata must be a mapping of strings to strings"))
    disabled = fields.get("disable-model-invocation", False)
    if type(disabled) is not bool:
        errors.append(Diagnostic(path, "disable-model-invocation must be a boolean"))
    if errors or name is None or description is None or type(disabled) is not bool:
        return None, errors
    return SkillMetadata(path, name, description, not disabled), []


def check_invocation_policy(skill: SkillMetadata) -> list[Diagnostic]:
    path = skill.path.parent / "agents" / "openai.yaml"
    if not path.exists():
        return [] if skill.implicit_allowed else [Diagnostic(path, "missing policy.allow_implicit_invocation: false")]
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        return [Diagnostic(path, f"cannot read file: {error}")]
    fields, errors = load_yaml_mapping(text, path)
    if fields is None:
        return errors
    if "policy" not in fields:
        return [] if skill.implicit_allowed else [Diagnostic(path, "missing policy.allow_implicit_invocation: false")]
    policy = fields["policy"]
    if not isinstance(policy, dict):
        return [Diagnostic(path, "policy must be a mapping")]
    if "allow_implicit_invocation" not in policy:
        return [] if skill.implicit_allowed else [Diagnostic(path, "missing policy.allow_implicit_invocation: false")]
    allowed = policy["allow_implicit_invocation"]
    if type(allowed) is not bool:
        return [Diagnostic(path, "policy.allow_implicit_invocation must be a boolean")]
    if allowed != skill.implicit_allowed:
        return [Diagnostic(path, "policy.allow_implicit_invocation must match disable-model-invocation")]
    return []


class DuplicateJsonKey(ValueError):
    pass


def unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKey(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def check_trigger_declarations(skills: dict[str, SkillMetadata], corpus_path: Path) -> list[Diagnostic]:
    try:
        payload = json.loads(corpus_path.read_text(encoding="utf-8"), object_pairs_hook=unique_json_object)
    except OSError as error:
        return [Diagnostic(corpus_path, f"cannot read trigger corpus: {error}")]
    except (json.JSONDecodeError, DuplicateJsonKey) as error:
        return [Diagnostic(corpus_path, f"invalid trigger corpus JSON: {error}")]
    errors: list[Diagnostic] = []
    if not isinstance(payload, dict):
        return [Diagnostic(corpus_path, "trigger corpus must be a JSON object")]
    if type(payload.get("version")) is not int or payload.get("version") != 1:
        errors.append(Diagnostic(corpus_path, "trigger corpus version must be integer 1"))
    declarations = payload.get("triggers")
    if not isinstance(declarations, list) or not declarations:
        return errors + [Diagnostic(corpus_path, "trigger corpus must contain a nonempty triggers list")]
    seen: set[str] = set()
    for index, raw in enumerate(declarations, start=1):
        label = f"trigger declaration {index}"
        if not isinstance(raw, dict):
            errors.append(Diagnostic(corpus_path, f"{label} must be an object"))
            continue
        skill = raw.get("skill")
        request = raw.get("example_request")
        anchors = raw.get("description_contains")
        allowed = raw.get("implicit_allowed")
        if not isinstance(skill, str) or not skill.strip():
            errors.append(Diagnostic(corpus_path, f"{label}.skill must be a nonblank string"))
            continue
        if skill in seen:
            errors.append(Diagnostic(corpus_path, f"duplicate trigger declaration for {skill!r}"))
            continue
        seen.add(skill)
        metadata = skills.get(skill)
        if metadata is None:
            errors.append(Diagnostic(corpus_path, f"stale trigger declaration for {skill!r}"))
        if not isinstance(request, str) or not request.strip():
            errors.append(Diagnostic(corpus_path, f"{label}.example_request must be a nonblank string"))
        if type(allowed) is not bool:
            errors.append(Diagnostic(corpus_path, f"{label}.implicit_allowed must be a boolean"))
        if metadata is not None and type(allowed) is bool and allowed != metadata.implicit_allowed:
            errors.append(Diagnostic(corpus_path, f"{label}.implicit_allowed does not match {skill!r}"))
        if not isinstance(anchors, list) or not anchors:
            errors.append(Diagnostic(corpus_path, f"{label}.description_contains must be a nonempty list"))
            continue
        if any(not isinstance(anchor, str) or not normalize(anchor) for anchor in anchors):
            errors.append(Diagnostic(corpus_path, f"{label}.description_contains entries must be nonblank strings"))
            continue
        if metadata is None:
            continue
        description = normalize(metadata.description)
        for anchor in anchors:
            if normalize(anchor) not in description:
                errors.append(Diagnostic(corpus_path, f"{label} anchor {anchor!r} is absent from {skill!r} description"))
    for skill in sorted(set(skills) - seen):
        errors.append(Diagnostic(corpus_path, f"missing trigger declaration for {skill!r}"))
    return errors


def main(root: Path, triggers: Path | None = None) -> int:
    errors: list[Diagnostic] = []
    if not root.is_dir():
        errors.append(Diagnostic(root, "skills root is not a directory"))
        skill_files: list[Path] = []
    else:
        skill_files = sorted(root.glob("*/SKILL.md"))
        if not skill_files:
            errors.append(Diagnostic(root, "skills inventory is empty"))
    skills: dict[str, SkillMetadata] = {}
    for path in skill_files:
        skill, skill_errors = read_skill(path)
        errors.extend(skill_errors)
        if skill is not None:
            if skill.name in skills:
                errors.append(Diagnostic(path, f"duplicate skill name {skill.name!r}"))
            else:
                skills[skill.name] = skill
    if root.is_dir():
        for openai_path in sorted(root.glob("*/agents/openai.yaml")):
            if not (openai_path.parent.parent / "SKILL.md").is_file():
                errors.append(Diagnostic(openai_path, "orphan OpenAI policy file"))
    for skill in skills.values():
        errors.extend(check_invocation_policy(skill))
    if triggers is not None:
        errors.extend(check_trigger_declarations(skills, triggers))
    for error in errors:
        print(error)
    detail = f", trigger declaration coverage: {triggers}" if triggers is not None else ""
    print(f"frontmatter: {len(skill_files)} skills, {len(errors)} errors{detail}", file=sys.stderr)
    return 1 if errors else 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skills_root", nargs="?", default="skills", type=Path)
    parser.add_argument("--triggers", type=Path, help="version-1 trigger declaration corpus")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args(sys.argv[1:])
    raise SystemExit(main(args.skills_root, args.triggers))
