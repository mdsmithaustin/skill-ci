from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path

from skill_ci import harness

MANIFEST = "shared-benchmark.json"
VALIDATE = ("validate", "--strict-leakage")
AUDIT = ("audit-manifest", "--fail-on-blockers", "--strict-judge")


def validate(skills_dir: Path, evals_dir: Path | None) -> int:
    return each_manifest(skills_dir, evals_dir, lambda manifest: harness.call([*VALIDATE, str(manifest)]))


def audit(skills_dir: Path, evals_dir: Path | None) -> int:
    return each_manifest(skills_dir, evals_dir, lambda manifest: harness.call([*AUDIT, str(manifest)]))


def check(skills_dir: Path, evals_dir: Path | None, *, require_manifests: bool) -> int:
    return each_manifest(skills_dir, evals_dir, validate_then_audit, require_manifests=require_manifests)


def validate_then_audit(manifest: Path) -> int:
    validated = harness.call([*VALIDATE, str(manifest)])
    if validated != 0:
        return validated
    if not json.loads(manifest.read_text(encoding="utf-8")).get("cases"):
        print(f"{manifest}: no cases yet, readiness audit skipped")
        return 0
    return harness.call([*AUDIT, str(manifest)])


def each_manifest(
    skills_dir: Path,
    evals_dir: Path | None,
    step: Callable[[Path], int],
    *,
    require_manifests: bool = False,
) -> int:
    root, pattern = (skills_dir, f"**/evals/{MANIFEST}") if evals_dir is None else (evals_dir, f"**/{MANIFEST}")
    if not root.is_dir():
        print(f"skill-ci: {root} is not a directory; no manifest would be checked", file=sys.stderr)
        return 1
    manifests = sorted(root.glob(pattern), key=str)
    codes = [step(manifest) for manifest in manifests]
    print(f"manifests checked: {len(manifests)}")
    if require_manifests and not manifests:
        print("skill-ci: require-manifests is enabled, but no manifest files were checked", file=sys.stderr)
        return 1
    return max(codes, default=0)
