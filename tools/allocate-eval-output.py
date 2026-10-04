from __future__ import annotations

import argparse
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def allocate_output(skill: Path, kind: str, task_dir: Path) -> Path:
    package = skill.resolve(strict=True)
    if not package.is_dir() or not (package / "SKILL.md").is_file():
        raise ValueError(f"selected skill is not a package: {skill}")
    checkout = task_dir.resolve(strict=True)
    destination = (checkout.parent / f"{checkout.name}.eval-runs" / package.name).resolve()
    if destination == package or package in destination.parents or destination in package.parents:
        raise ValueError("default output overlaps the selected skill package; set OUT to a directory outside the package")
    destination.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return Path(tempfile.mkdtemp(prefix=f"{kind}-{timestamp}-", dir=destination))


def main() -> int:
    parser = argparse.ArgumentParser(description="Allocate an exclusive run directory outside the selected skill package.")
    parser.add_argument("skill", type=Path)
    parser.add_argument("kind", choices=("run", "trigger"))
    arguments = parser.parse_args()
    try:
        print(allocate_output(arguments.skill, arguments.kind, Path.cwd()))
    except (OSError, ValueError) as error:
        print(f"output allocation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
