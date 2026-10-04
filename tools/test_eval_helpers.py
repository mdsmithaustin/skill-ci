from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


TOOLS = Path(__file__).resolve().parent


class OutputAllocationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="skill-ci-outputs-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.checkout = self.root / "checkout with spaces"
        self.checkout.mkdir()
        self.package = self.checkout / "skills" / "a skill"
        self.package.mkdir(parents=True)
        (self.package / "SKILL.md").write_text("skill")

    def allocate(self, skill: str, kind: str = "run") -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(TOOLS / "allocate-eval-output.py"), skill, kind],
            cwd=self.checkout, capture_output=True, text=True, timeout=10, check=False,
        )

    def test_relative_absolute_and_root_package_selections(self) -> None:
        (self.checkout / "SKILL.md").write_text("root skill")
        for selection, name in (("skills/a skill", "a skill"), (str(self.package), "a skill"), (".", self.checkout.name)):
            with self.subTest(selection=selection):
                result = self.allocate(selection)
                self.assertEqual(result.returncode, 0, result.stderr)
                output = Path(result.stdout.strip())
                self.assertEqual(output.parent, self.root / "checkout with spaces.eval-runs" / name)
                self.assertTrue(output.is_dir())
                self.assertRegex(output.name, r"^run-\d{8}-\d{6}-")
                self.assertNotIn(self.checkout, output.parents)

    def test_concurrent_allocations_have_exclusive_final_directories(self) -> None:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.allocate("skills/a skill", "trigger"), range(16)))
        outputs = []
        for result in results:
            self.assertEqual(result.returncode, 0, result.stderr)
            output = Path(result.stdout.strip())
            self.assertTrue(output.is_dir())
            self.assertRegex(output.name, r"^trigger-\d{8}-\d{6}-")
            outputs.append(output)
        self.assertEqual(len(set(outputs)), 16)

    def test_symlink_and_external_ancestor_overlap_fail_without_allocating(self) -> None:
        output_root = self.root / "checkout with spaces.eval-runs"
        output_root.symlink_to(self.package, target_is_directory=True)
        rejected = self.allocate("skills/a skill")
        self.assertEqual(rejected.returncode, 1, rejected.stderr)
        self.assertIn("set OUT", rejected.stderr)
        self.assertFalse((self.package / "a skill").exists())
        output_root.unlink()
        output_root.mkdir()
        external = output_root / "external" / "nested" / "external"
        external.mkdir(parents=True)
        (external / "SKILL.md").write_text("external skill")
        ancestor = self.allocate(str(external))
        self.assertEqual(ancestor.returncode, 1, ancestor.stderr)
        self.assertIn("overlaps", ancestor.stderr)
        self.assertEqual(list((output_root / "external").iterdir()), [output_root / "external" / "nested"])

    def test_missing_package_fails(self) -> None:
        rejected = self.allocate("missing")
        self.assertEqual(rejected.returncode, 1, rejected.stderr)
        self.assertIn("output allocation failed", rejected.stderr)
        self.assertFalse((self.root / "checkout with spaces.eval-runs").exists())


class SkillCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="skill-ci-coverage-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.skills = self.root / "skills"
        self.skills.mkdir()

    def coverage(self, evals: str | None = None) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(TOOLS / "check-skill-coverage.py"), "--skills-dir", "skills"]
        if evals is not None:
            command.extend(("--evals-dir", evals))
        return subprocess.run(command, cwd=self.root, capture_output=True, text=True, timeout=10, check=False)

    def test_inventory_checks_only_direct_child_markers(self) -> None:
        package = self.skills / "actual directory"
        package.mkdir()
        (package / "SKILL.md").write_text("---\nname: other-name\n---\n")
        nested = package / "nested"
        nested.mkdir()
        (nested / "SKILL.md").write_text("not in inventory")
        manifest = self.root / "evals" / package.name / "shared-benchmark.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"cases": [{"id": "a"}], "skill_paths": ["unrelated.md", "skills/actual directory"]}))
        result = self.coverage("evals")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "skill manifests checked: 1; failed: 0\n")

    def test_binding_uses_runner_roots_for_legacy_and_external_manifests(self) -> None:
        package = self.skills / "a"
        package.mkdir()
        (package / "SKILL.md").write_text("skill")
        for external, paths in ((False, ["SKILL.md"]), (True, ["skills/a/SKILL.md"])):
            with self.subTest(external=external):
                manifest = (self.root / "evals/a" if external else package / "evals") / "shared-benchmark.json"
                manifest.parent.mkdir(parents=True)
                manifest.write_text(json.dumps({"cases": [{"id": "a"}], "skill_paths": paths}))
                good = self.coverage("evals" if external else None)
                self.assertEqual(good.returncode, 0, good.stderr)
                manifest.write_text(json.dumps({"cases": [{"id": "a"}], "skill_paths": ["wrong/SKILL.md"]}))
                wrong = self.coverage("evals" if external else None)
                self.assertEqual(wrong.returncode, 1, wrong.stderr)
                self.assertIn("does not bind", wrong.stderr)

    def test_missing_inventory_and_invalid_json_fail(self) -> None:
        empty = self.coverage()
        self.assertEqual(empty.returncode, 1, empty.stderr)
        self.assertIn("inventory is empty", empty.stderr)
        package = self.skills / "a"
        package.mkdir()
        (package / "SKILL.md").write_text("skill")
        manifest = package / "evals/shared-benchmark.json"
        manifest.parent.mkdir()
        manifest.write_text("{")
        invalid = self.coverage()
        self.assertEqual(invalid.returncode, 1, invalid.stderr)
        self.assertIn("failed: 1", invalid.stdout)
        missing_evals = self.coverage("missing")
        self.assertEqual(missing_evals.returncode, 1, missing_evals.stderr)
        self.assertIn("evals root is not a directory", missing_evals.stderr)
        shutil.rmtree(self.skills)
        missing_skills = self.coverage()
        self.assertEqual(missing_skills.returncode, 1, missing_skills.stderr)
        self.assertIn("skills root is not a directory", missing_skills.stderr)


if __name__ == "__main__":
    unittest.main()
