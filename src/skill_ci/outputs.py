from __future__ import annotations

import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def overlaps(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def checkout_root(directory: Path) -> Path:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=directory, capture_output=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return directory
    return Path(os.fsdecode(result.stdout.rstrip(b"\n")))


def allocate_output(skill: Path, kind: str, task_dir: Path) -> Path:
    package = skill.resolve(strict=True)
    if not package.is_dir() or not (package / "SKILL.md").is_file():
        raise ValueError(f"selected skill is not a package: {skill}")
    checkout = task_dir.resolve(strict=True)
    destination = (checkout.parent / f"{checkout.name}.eval-runs" / package.name).resolve()
    if overlaps(destination, package):
        raise ValueError("default output overlaps the selected skill package; pass --out with a directory outside the package")
    destination.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return Path(tempfile.mkdtemp(prefix=f"{kind}-{timestamp}-", dir=destination))


def claim_output(out: Path, skill: Path) -> Path:
    if overlaps(out.resolve(), skill.resolve()):
        raise ValueError(f"{out} overlaps the selected skill package; pass --out with a directory outside the package")
    out.mkdir(parents=True, exist_ok=True)
    return out
