from __future__ import annotations

import difflib
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


FIXTURE = Path(__file__).resolve().parents[1] / ".github/fixtures/populated/evals/project-editing"
ORACLE = FIXTURE / "oracles/check_written_product.py"
BASELINE = (FIXTURE / "inputs/product.py").read_bytes()


def state(data: bytes) -> dict[str, object]:
    return {"kind": "file", "sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "text": True, "executable": False}


class WrittenProductOracleTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="skill-ci-oracle-")
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name)

    def capture(self, repaired: bytes) -> dict[str, object]:
        patch = (
            "diff --git a/inputs/product.py b/inputs/product.py\n"
            + "".join(difflib.unified_diff(
                BASELINE.decode().splitlines(keepends=True), repaired.decode().splitlines(keepends=True),
                "a/inputs/product.py", "b/inputs/product.py",
            ))
        ).encode()
        (self.output / "candidate.patch").write_bytes(patch)
        receipt = {
            "schema_version": 1, "captured": True, "capture_error": None,
            "workspace_root": "/tmp/product-workspace", "workspace_root_realpath": "/tmp/product-workspace",
            "baseline_file_count": 1, "limits": {"file_bytes": 1048576, "total_bytes": 33554432},
            "patch": {"path": "candidate.patch", "sha256": hashlib.sha256(patch).hexdigest()},
            "changes": [{"path": "inputs/product.py", "change": "modified", "before": state(BASELINE), "after": state(repaired), "evidence": {"kind": "patch"}}],
        }
        self.write_receipt(receipt)
        return receipt

    def write_receipt(self, receipt: dict[str, object]) -> None:
        (self.output / "workspace-changes.json").write_text(json.dumps(receipt))

    def run_oracle(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ORACLE), str(self.output)],
            cwd=FIXTURE, capture_output=True, text=True, timeout=15, check=False,
        )

    def good_capture(self) -> dict[str, object]:
        return self.capture(BASELINE.replace(b"sum(prices[:-1])", b"sum(prices)"))

    def test_reconstructed_repair_passes_real_behavior_checks(self) -> None:
        self.good_capture()
        result = self.run_oracle()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "written product verified\n")

    def test_missing_capture_and_failed_capture_are_rejected(self) -> None:
        missing = self.run_oracle()
        self.assertEqual(missing.returncode, 1, missing.stderr)
        self.assertIn("workspace-changes.json", missing.stderr)
        receipt = self.good_capture()
        receipt["captured"] = False
        self.write_receipt(receipt)
        failed = self.run_oracle()
        self.assertEqual(failed.returncode, 1, failed.stderr)
        self.assertIn("not fully captured", failed.stderr)

    def test_forged_hashes_and_missing_patch_are_rejected(self) -> None:
        for side in ("before", "after", "patch"):
            with self.subTest(side=side):
                receipt = self.good_capture()
                target = receipt["patch"] if side == "patch" else receipt["changes"][0][side]
                target["sha256"] = "0" * 64
                self.write_receipt(receipt)
                rejected = self.run_oracle()
                self.assertEqual(rejected.returncode, 1, rejected.stderr)
        self.good_capture()
        (self.output / "candidate.patch").unlink()
        missing = self.run_oracle()
        self.assertEqual(missing.returncode, 1, missing.stderr)
        self.assertIn("candidate.patch", missing.stderr)

    def test_unrelated_receipt_and_hidden_patch_writes_are_rejected(self) -> None:
        receipt = self.good_capture()
        receipt["changes"].append({"path": "unrelated.txt", "change": "added"})
        self.write_receipt(receipt)
        unrelated = self.run_oracle()
        self.assertEqual(unrelated.returncode, 1, unrelated.stderr)
        self.assertIn("exactly one", unrelated.stderr)
        receipt = self.good_capture()
        patch = (self.output / "candidate.patch").read_bytes() + b"diff --git a/extra.txt b/extra.txt\nnew file mode 100644\n--- /dev/null\n+++ b/extra.txt\n@@ -0,0 +1 @@\n+extra\n"
        (self.output / "candidate.patch").write_bytes(patch)
        receipt["patch"]["sha256"] = hashlib.sha256(patch).hexdigest()
        self.write_receipt(receipt)
        hidden = self.run_oracle()
        self.assertEqual(hidden.returncode, 1, hidden.stderr)
        self.assertIn("only the product", hidden.stderr)

    def test_wrong_product_behavior_and_unrelated_function_edits_are_rejected(self) -> None:
        self.capture(BASELINE.replace(b"sum(prices[:-1])", b"sum(prices[1:])"))
        failing = self.run_oracle()
        self.assertEqual(failing.returncode, 1, failing.stderr)
        self.capture(BASELINE.replace(b"sum(prices[:-1])", b"sum(prices)").replace(b"order:", b"ORDER:"))
        unrelated = self.run_oracle()
        self.assertEqual(unrelated.returncode, 1, unrelated.stderr)
        self.assertIn("unrelated function bytes changed", unrelated.stderr)

    def test_executable_state_changes_are_rejected(self) -> None:
        receipt = self.good_capture()
        receipt["changes"][0]["after"]["executable"] = True
        self.write_receipt(receipt)
        result = self.run_oracle()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("disagrees", result.stderr)


if __name__ == "__main__":
    unittest.main()
