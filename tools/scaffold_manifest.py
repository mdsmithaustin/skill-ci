#!/usr/bin/env python3
"""Write an empty skill-eval-harness manifest for a skill.

Given one or more skill directories, read `name` and `description` from each
SKILL.md and write a manifest in format version 1 with no cases. The default
layout writes `evals/shared-benchmark.json` inside the skill directory. With
`--evals-dir`, the manifest goes to `<evals-dir>/<skill>/shared-benchmark.json`
instead, which keeps it out of the directory a skill installer copies to every
consumer. An existing manifest is never overwritten. Nothing here calls a model.
"""
from __future__ import annotations

import argparse
import json
import os
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
NOTE_PREAMBLE = (
    "Scaffolded by skill-ci with no cases. Trigger rows (kind: trigger) come from "
    "the reviewed session harvest. Outcome cases are written by the skill's author. "
)
NOTE_BESIDE_SKILL = NOTE_PREAMBLE + (
    "skill_paths are relative to the skill directory, the parent of evals/."
)
NOTE_EXTERNAL_EVALS = NOTE_PREAMBLE + (
    "skill_paths are relative to the repository root, the parent of evals/."
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


def manifest_for(name: str, description: str, skill_path: str, note: str) -> dict[str, object]:
    return {
        "version": 1,
        "_note": note,
        "skill_name": name,
        "skill_description": description,
        "harness": dict(HARNESS),
        "skill_paths": [skill_path],
        "variants": ["with_skill", "without_skill"],
        "cases": [],
    }


def layout_for(skill_dir: Path, evals_dir: Path | None) -> tuple[Path, str, str]:
    """Return the manifest path, its one skill_paths entry, and its note."""
    if evals_dir is None:
        return skill_dir / "evals" / "shared-benchmark.json", "SKILL.md", NOTE_BESIDE_SKILL
    if evals_dir.name != "evals":
        raise ScaffoldError(
            f"{evals_dir}: an external evals directory must be named 'evals', "
            "because the runner resolves the repository root from that name"
        )
    relative = Path(os.path.relpath(skill_dir.resolve(), evals_dir.resolve().parent))
    if relative.parts and relative.parts[0] == "..":
        raise ScaffoldError(f"{skill_dir}: not inside {evals_dir.parent}, the repository root implied by {evals_dir}")
    target = evals_dir / skill_dir.name / "shared-benchmark.json"
    return target, (relative / "SKILL.md").as_posix(), NOTE_EXTERNAL_EVALS


def scaffold(skill_dir: Path, evals_dir: Path | None = None) -> str:
    """Return one status line. Raises ScaffoldError when the skill cannot be read."""
    target, skill_path, note = layout_for(skill_dir, evals_dir)
    if target.exists():
        return f"{target}: refused to overwrite existing manifest"
    name, description = read_frontmatter(skill_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    manifest = manifest_for(name, description, skill_path, note)
    target.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return f"{target}: wrote empty manifest for {name!r}"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="scaffold_manifest.py",
        description="Write an empty skill-eval-harness manifest for each skill directory.",
    )
    parser.add_argument("skill_dir", nargs="+", type=Path)
    parser.add_argument(
        "--evals-dir",
        type=Path,
        default=None,
        metavar="DIR",
        help=(
            "write <DIR>/<skill>/shared-benchmark.json instead of a manifest inside the "
            "skill directory, so the manifest stays out of what a skill installer copies"
        ),
    )
    args = parser.parse_args(argv)
    failures = 0
    for skill_dir in args.skill_dir:
        try:
            print(scaffold(skill_dir, args.evals_dir))
        except ScaffoldError as error:
            failures += 1
            print(error, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
