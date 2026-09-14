#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
SCAFFOLD = TOOLS / "scaffold_manifest.py"

EXPECTED = {
    "version": 1,
    "_note": (
        "Scaffolded by skill-ci with no cases. Trigger rows (kind: trigger) come from "
        "the reviewed session harvest. Outcome cases are written by the skill's author. "
        "skill_paths are relative to the skill directory, the parent of evals/."
    ),
    "skill_name": "demo",
    "skill_description": "Use when asked to demo something.",
    "harness": {
        "name": "skill-eval-harness",
        "url": "https://github.com/mdsmithaustin/skill-eval-harness",
        "version": ">=0.6.0",
    },
    "skill_paths": ["SKILL.md"],
    "variants": ["with_skill", "without_skill"],
    "cases": [],
}

EXPECTED_EXTERNAL = {
    "version": 1,
    "_note": (
        "Scaffolded by skill-ci with no cases. Trigger rows (kind: trigger) come from "
        "the reviewed session harvest. Outcome cases are written by the skill's author. "
        "skill_paths are relative to the repository root, the parent of evals/."
    ),
    "skill_name": "demo",
    "skill_description": "Use when asked to demo something.",
    "harness": {
        "name": "skill-eval-harness",
        "url": "https://github.com/mdsmithaustin/skill-eval-harness",
        "version": ">=0.6.0",
    },
    "skill_paths": ["skills/demo/SKILL.md"],
    "variants": ["with_skill", "without_skill"],
    "cases": [],
}


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCAFFOLD), *args], capture_output=True, text=True, check=False)


class ScaffoldManifest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.skills = self.root / "skills"
        self.skills.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def skill(self, name: str, frontmatter: str) -> Path:
        directory = self.skills / name
        directory.mkdir()
        (directory / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n\nBody.\n", encoding="utf-8")
        return directory

    def test_writes_empty_version_1_manifest_from_frontmatter(self) -> None:
        skill = self.skill("demo", 'name: demo\ndescription: "Use when asked to demo something."')
        result = run(str(skill))
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = skill / "evals" / "shared-benchmark.json"
        self.assertEqual(json.loads(manifest.read_text(encoding="utf-8")), EXPECTED)
        self.assertEqual(result.stdout, f"{manifest}: wrote empty manifest for 'demo'\n")

    def test_block_scalar_description_is_flattened(self) -> None:
        skill = self.skill("demo", "name: demo\ndescription: >-\n  Use when asked\n  to demo something.")
        self.assertEqual(run(str(skill)).returncode, 0)
        manifest = json.loads((skill / "evals" / "shared-benchmark.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["skill_description"], "Use when asked to demo something.")

    def test_existing_manifest_is_refused_and_left_byte_identical(self) -> None:
        skill = self.skill("demo", "name: demo\ndescription: d")
        manifest = skill / "evals" / "shared-benchmark.json"
        manifest.parent.mkdir()
        manifest.write_text('{"cases": [{"id": "hand-written"}]}\n', encoding="utf-8")
        result = run(str(skill))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, f"{manifest}: refused to overwrite existing manifest\n")
        self.assertEqual(manifest.read_text(encoding="utf-8"), '{"cases": [{"id": "hand-written"}]}\n')

    def test_second_run_over_many_skills_keeps_the_first_and_writes_the_new(self) -> None:
        first = self.skill("a", "name: a\ndescription: d")
        self.assertEqual(run(str(first)).returncode, 0)
        before = (first / "evals" / "shared-benchmark.json").read_bytes()
        second = self.skill("b", "name: b\ndescription: d")
        result = run(str(first), str(second))
        self.assertEqual(result.returncode, 0)
        self.assertEqual((first / "evals" / "shared-benchmark.json").read_bytes(), before)
        self.assertEqual(json.loads((second / "evals" / "shared-benchmark.json").read_text(encoding="utf-8"))["skill_name"], "b")

    def test_missing_skill_or_bad_frontmatter_fails_without_writing(self) -> None:
        empty = self.skills / "empty"
        empty.mkdir()
        blank = self.skill("blank", "name: blank\ndescription: ''")
        for skill, message in ((empty, "missing SKILL.md"), (blank, "description must be a nonblank string")):
            with self.subTest(skill=skill.name):
                result = run(str(skill))
                self.assertEqual(result.returncode, 1)
                self.assertIn(message, result.stderr)
                self.assertFalse((skill / "evals").exists())

    def test_evals_dir_writes_beside_the_skills_tree_with_repo_root_skill_paths(self) -> None:
        skill = self.skill("demo", 'name: demo\ndescription: "Use when asked to demo something."')
        evals = self.root / "evals"
        result = run(str(skill), "--evals-dir", str(evals))
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = evals / "demo" / "shared-benchmark.json"
        self.assertEqual(json.loads(manifest.read_text(encoding="utf-8")), EXPECTED_EXTERNAL)
        self.assertEqual(result.stdout, f"{manifest}: wrote empty manifest for 'demo'\n")
        self.assertFalse((skill / "evals").exists())

    def test_evals_dir_refuses_an_existing_manifest_and_leaves_it_byte_identical(self) -> None:
        skill = self.skill("demo", "name: demo\ndescription: d")
        manifest = self.root / "evals" / "demo" / "shared-benchmark.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text('{"cases": [{"id": "hand-written"}]}\n', encoding="utf-8")
        result = run(str(skill), "--evals-dir", str(self.root / "evals"))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, f"{manifest}: refused to overwrite existing manifest\n")
        self.assertEqual(manifest.read_text(encoding="utf-8"), '{"cases": [{"id": "hand-written"}]}\n')

    def test_an_evals_dir_the_runner_cannot_resolve_is_refused_without_writing(self) -> None:
        skill = self.skill("demo", "name: demo\ndescription: d")
        misnamed = self.root / "benchmarks"
        elsewhere = self.root / "other" / "evals"
        cases = (
            (misnamed, "must be named 'evals'"),
            (elsewhere, f"not inside {elsewhere.parent}"),
        )
        for evals, message in cases:
            with self.subTest(evals_dir=evals.name):
                result = run(str(skill), "--evals-dir", str(evals))
                self.assertEqual(result.returncode, 1)
                self.assertIn(message, result.stderr)
                self.assertFalse(evals.exists())

    def test_no_arguments_is_a_usage_error(self) -> None:
        self.assertEqual(run().returncode, 2)

    @unittest.skipUnless(shutil.which("skill-benchmark"), "skill-benchmark not installed on this host")
    def test_scaffold_passes_the_installed_runner_validate(self) -> None:
        skill = self.skill("demo", "name: demo\ndescription: d")
        self.assertEqual(run(str(skill)).returncode, 0)
        result = subprocess.run(
            ["skill-benchmark", "validate", "--strict-leakage", str(skill / "evals" / "shared-benchmark.json")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OK: demo", result.stdout)

    @unittest.skipUnless(shutil.which("skill-benchmark"), "skill-benchmark not installed on this host")
    def test_the_installed_runner_reads_the_skill_file_in_either_layout(self) -> None:
        skill = self.skill("demo", "name: demo\ndescription: d")
        evals = self.root / "evals"
        self.assertEqual(run(str(skill)).returncode, 0)
        self.assertEqual(run(str(skill), "--evals-dir", str(evals)).returncode, 0)
        manifests = {
            "beside the skill": skill / "evals" / "shared-benchmark.json",
            "under evals/<skill>": evals / "demo" / "shared-benchmark.json",
        }
        for layout, manifest in manifests.items():
            with self.subTest(layout=layout):
                result = subprocess.run(
                    ["skill-benchmark", "profile-skill", str(manifest)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                profile = json.loads(result.stdout)
                self.assertEqual(profile["summary"]["skill_files"], 1)
                self.assertEqual(profile["files"][0]["path"], str((skill / "SKILL.md").resolve()))


if __name__ == "__main__":
    unittest.main()
