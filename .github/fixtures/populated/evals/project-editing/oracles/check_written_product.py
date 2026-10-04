from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


PRODUCT_PATH = "inputs/product.py"
BASELINE = Path(__file__).resolve().parents[1] / PRODUCT_PATH


def file_state(data: bytes) -> dict[str, object]:
    return {
        "kind": "file", "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data), "text": True, "executable": False,
    }


@dataclass(frozen=True)
class TextEditReceipt:
    after: dict[str, object]
    patch: bytes


def read_receipt(output_dir: Path, baseline: bytes) -> TextEditReceipt:
    manifest = json.loads((output_dir / "workspace-changes.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("unsupported workspace capture")
    if manifest.get("captured") is not True or manifest.get("capture_error") is not None:
        raise ValueError("workspace changes were not fully captured")
    changes = manifest.get("changes")
    if not isinstance(changes, list) or len(changes) != 1:
        raise ValueError("exactly one product modification is required")
    change = changes[0]
    if not isinstance(change, dict) or change.get("path") != PRODUCT_PATH or change.get("change") != "modified":
        raise ValueError("only the product may be modified")
    if change.get("evidence") != {"kind": "patch"} or change.get("before") != file_state(baseline):
        raise ValueError("product baseline or patch evidence disagrees")
    after = change.get("after")
    if not isinstance(after, dict) or after == change["before"]:
        raise ValueError("product has no recorded text edit")
    patch = (output_dir / "candidate.patch").read_bytes()
    if manifest.get("patch") != {"path": "candidate.patch", "sha256": hashlib.sha256(patch).hexdigest()}:
        raise ValueError("candidate patch digest disagrees")
    return TextEditReceipt(after, patch)


def check_product(output_dir: Path) -> None:
    baseline = BASELINE.read_bytes()
    receipt = read_receipt(output_dir, baseline)
    with tempfile.TemporaryDirectory(prefix="written-product-") as temporary:
        root = Path(temporary)
        product = root / PRODUCT_PATH
        product.parent.mkdir()
        product.write_bytes(baseline)
        patch = root / "candidate.patch"
        patch.write_bytes(receipt.patch)
        inventory = subprocess.run(
            ["git", "apply", "--numstat", "-z", str(patch)], cwd=root,
            capture_output=True, check=True, timeout=5,
        ).stdout.split(b"\0")
        if len(inventory) != 2 or inventory[-1] != b"" or inventory[0].split(b"\t")[2:] != [PRODUCT_PATH.encode()]:
            raise ValueError("patch must modify only the product")
        subprocess.run(["git", "apply", str(patch)], cwd=root, capture_output=True, check=True, timeout=5)
        repaired = product.read_bytes()
        if product.is_symlink() or product.stat().st_mode & 0o111 or receipt.after != file_state(repaired):
            raise ValueError("reconstructed product disagrees with captured state")
        preserved = b"\n\ndef format_reference(reference):\n"
        if preserved not in repaired or repaired.split(preserved, 1)[1] != baseline.split(preserved, 1)[1]:
            raise ValueError("unrelated function bytes changed")
        subprocess.run(
            [sys.executable, "-B", "-I", "-c",
             "import runpy, sys\n"
             "product = runpy.run_path(sys.argv[1])\n"
             "total = product['total_price']\n"
             "assert total([]) == 0\n"
             "assert total([7]) == 7\n"
             "assert total([2, 3, 4]) == 9\n"
             "assert total([-3, 1, 6]) == 4\n"
             "assert total([1.25, 2.5]) == 3.75\n"
             "assert product['format_reference'](' ab-7 ') == 'order:AB-7'\n",
             str(product)], cwd=root, capture_output=True, check=True, timeout=5,
        )


def main() -> int:
    try:
        check_product(Path(sys.argv[1]).resolve())
    except (IndexError, KeyError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"written product check failed: {error}", file=sys.stderr)
        return 1
    print("written product verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
