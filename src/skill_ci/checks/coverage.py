from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SkillBinding:
    marker: Path
    manifest: Path
    resolution_root: Path


def resolution_root(manifest: Path) -> Path:
    directory = manifest.parent
    if directory.name != "evals":
        directory = directory.parent
    return (directory.parent if directory.name == "evals" else manifest.parent).resolve()


def skill_bindings(skills: Path, evals: Path | None) -> tuple[SkillBinding, ...]:
    if not skills.is_dir():
        raise ValueError(f"skills root is not a directory: {skills}")
    if evals is not None and not evals.is_dir():
        raise ValueError(f"evals root is not a directory: {evals}")
    markers = sorted(path for path in skills.glob("*/SKILL.md") if path.is_file())
    if not markers:
        raise ValueError(f"skills inventory is empty: {skills}")
    bindings = []
    for marker in markers:
        manifest = (evals / marker.parent.name if evals is not None else marker.parent / "evals") / "shared-benchmark.json"
        bindings.append(SkillBinding(marker.resolve(), manifest, resolution_root(manifest)))
    return tuple(bindings)


def check_binding(binding: SkillBinding) -> None:
    with binding.manifest.open(encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be an object")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("manifest must contain nonempty cases")
    paths = manifest.get("skill_paths")
    if not isinstance(paths, list) or not paths or not all(isinstance(path, str) and path for path in paths):
        raise ValueError("skill_paths must be a nonempty list of paths")
    for entry in paths:
        candidate = (binding.resolution_root / entry).resolve()
        if candidate.is_dir():
            candidate = (candidate / "SKILL.md").resolve()
        if candidate == binding.marker:
            return
    raise ValueError(f"skill_paths does not bind to {binding.marker}")


def check_coverage(skills_dir: Path, evals_dir: Path | None = None) -> int:
    try:
        bindings = skill_bindings(skills_dir, evals_dir)
    except (OSError, ValueError) as error:
        print(f"skill coverage failed: {error}", file=sys.stderr)
        return 1
    failures = 0
    for binding in bindings:
        try:
            check_binding(binding)
        except (OSError, ValueError) as error:
            print(f"{binding.manifest}: {error}", file=sys.stderr)
            failures += 1
    print(f"skill manifests checked: {len(bindings)}; failed: {failures}")
    return int(failures != 0)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Require a populated manifest bound to every direct child skill package.")
    parser.add_argument("--skills-dir", type=Path, default=Path("skills"))
    parser.add_argument("--evals-dir", type=Path)
    arguments = parser.parse_args(argv)
    return check_coverage(arguments.skills_dir, arguments.evals_dir)


if __name__ == "__main__":
    raise SystemExit(main())
