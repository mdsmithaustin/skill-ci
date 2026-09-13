#!/usr/bin/env python3
"""Write an empty skill-eval-harness manifest beside a skill.

Given one or more skill directories, read `name` and `description` from each
SKILL.md and write `evals/shared-benchmark.json` in manifest format version 1
with no cases. An existing manifest is never overwritten. Nothing here calls a
model.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", re.DOTALL)
HARNESS = {
    "name": "skill-eval-harness",
    "url": "https://github.com/mdsmithaustin/skill-eval-harness",
    "version": ">=0.6.0",
}
NOTE = (
    "Scaffolded by skill-ci with no cases. Trigger rows (kind: trigger) come from "
    "the reviewed session harvest. Outcome cases are written by the skill's author. "
    "skill_paths are relative to the skill directory, the parent of evals/."
)


class ScaffoldError(Exception):
    pass


def read_frontmatter(skill_dir: Path) -> tuple[str, str]:
    path = skill_dir / "SKILL.md"
    if not path.is_file():
        raise ScaffoldError(f"{path}: missing SKILL.md")
    match = FRONTMATTER.match(path.read_text(encoding="utf-8"))
    if match is None:
        raise ScaffoldError(f"{path}: missing frontmatter")
    try:
        fields = yaml.safe_load(match.group(1))
    except yaml.YAMLError as error:
        raise ScaffoldError(f"{path}: invalid YAML: {error}") from error
    if not isinstance(fields, dict):
        raise ScaffoldError(f"{path}: frontmatter must be a mapping")
    values = []
    for key in ("name", "description"):
        value = fields.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ScaffoldError(f"{path}: {key} must be a nonblank string")
        values.append(value.strip())
    return values[0], values[1]


def manifest_for(name: str, description: str) -> dict[str, object]:
    return {
        "version": 1,
        "_note": NOTE,
        "skill_name": name,
        "skill_description": description,
        "harness": dict(HARNESS),
        "skill_paths": ["SKILL.md"],
        "variants": ["with_skill", "without_skill"],
        "cases": [],
    }


def scaffold(skill_dir: Path) -> str:
    """Return one status line. Raises ScaffoldError when the skill cannot be read."""
    target = skill_dir / "evals" / "shared-benchmark.json"
    if target.exists():
        return f"{target}: refused to overwrite existing manifest"
    name, description = read_frontmatter(skill_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest_for(name, description), indent=2) + "\n", encoding="utf-8")
    return f"{target}: wrote empty manifest for {name!r}"


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: scaffold_manifest.py SKILL_DIR [SKILL_DIR ...]", file=sys.stderr)
        return 2
    failures = 0
    for raw in argv:
        try:
            print(scaffold(Path(raw)))
        except ScaffoldError as error:
            failures += 1
            print(error, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
