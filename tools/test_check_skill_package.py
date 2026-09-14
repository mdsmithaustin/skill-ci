#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


CHECKER = Path(__file__).with_name("check-skill-package.py")


def snapshot(root: Path) -> dict[str, tuple[int, bytes | str]]:
    contents: dict[str, tuple[int, bytes | str]] = {}
    for current, directories, files in os.walk(root, followlinks=False):
        for name in sorted([*directories, *files]):
            path = Path(current) / name
            relative = str(path.relative_to(root))
            mode = os.lstat(path).st_mode
            if stat.S_ISLNK(mode):
                contents[relative] = (mode, os.readlink(path))
            elif stat.S_ISREG(mode):
                contents[relative] = (mode, path.read_bytes())
            else:
                contents[relative] = (mode, b"")
    return contents


class PackageChecker(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.skills = self.root / "skills"
        self.skills.mkdir()
        self.installed = self.root / "installed"
        self.installed.mkdir()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def execute(self, *arguments: Path | str, cwd: Path | None = None) -> tuple[int, str]:
        result = subprocess.run(
            [sys.executable, str(CHECKER), *(str(argument) for argument in arguments)],
            capture_output=True,
            text=True,
            check=False,
            cwd=cwd,
            timeout=5,
        )
        return result.returncode, result.stdout + result.stderr

    def skill(self, name: str, root: Path | None = None) -> Path:
        package = (root or self.skills) / name
        package.mkdir(parents=True)
        (package / "SKILL.md").write_text("---\nname: fixture\n---\n", encoding="utf-8")
        return package

    def install(self, package: Path) -> Path:
        destination = self.installed / package.name
        shutil.copytree(package, destination, copy_function=shutil.copy2)
        return destination

    def digest(self, package: Path) -> str:
        code, output = self.execute("--skill", package)
        self.assertEqual(code, 0, output)
        return output.split("sha256:", 1)[1].splitlines()[0]

    def test_digest_changes_for_bytes_paths_empty_directories_and_each_executable_mask(self) -> None:
        base = self.skill("base")
        base_digest = self.digest(base)
        changed_bytes = self.skill("changed-bytes")
        (changed_bytes / "SKILL.md").write_text("changed", encoding="utf-8")
        self.assertNotEqual(self.digest(changed_bytes), base_digest)
        path_a = self.skill("path-a")
        path_b = self.skill("path-b")
        (path_a / "a").write_bytes(b"same")
        (path_b / "b").write_bytes(b"same")
        self.assertNotEqual(self.digest(path_a), self.digest(path_b))
        empty = self.skill("empty")
        (empty / "directory").mkdir()
        self.assertNotEqual(self.digest(empty), base_digest)
        mode_a = self.skill("mode-a")
        mode_b = self.skill("mode-b")
        for package, mode in ((mode_a, 0o700), (mode_b, 0o410)):
            executable = package / "run"
            executable.write_bytes(b"same")
            executable.chmod(mode)
        self.assertNotEqual(self.digest(mode_a), self.digest(mode_b))

    def test_healthy_collection_compares_hidden_binary_empty_and_executable_content_without_writes(self) -> None:
        alpha = self.skill("alpha")
        (alpha / ".hidden").write_bytes(b"\x00\xff")
        (alpha / "empty").mkdir()
        executable = alpha / "run"
        executable.write_bytes(b"#!/bin/sh\n")
        executable.chmod(0o751)
        beta = self.skill("beta")
        (beta / "agents").mkdir()
        (beta / "agents" / "openai.yaml").write_bytes(b"binary\x00metadata")
        (self.skills / "README.txt").write_text("ignored collection file", encoding="utf-8")
        self.install(alpha)
        self.install(beta)
        source_before = snapshot(self.skills)
        installed_before = snapshot(self.installed)

        code, output = self.execute("--skills-dir", self.skills, "--compare-to", self.installed)

        self.assertEqual(code, 0, output)
        self.assertEqual(output.count("sha256:"), 2)
        self.assertIn("packages checked: 2; passed: 2; failed: 0; copies compared: 2", output)
        self.assertEqual(snapshot(self.skills), source_before)
        self.assertEqual(snapshot(self.installed), installed_before)

    def test_single_skill_maps_to_installed_parent_by_basename_and_ignores_unselected_siblings(self) -> None:
        alpha = self.skill("alpha")
        self.skill("beta")
        self.install(alpha)
        installed_other = self.installed / "other"
        installed_other.mkdir()
        (installed_other / "unexpected").write_text("outside scope", encoding="utf-8")

        code, output = self.execute("--skill", alpha, "--compare-to", self.installed)

        self.assertEqual(code, 0, output)
        self.assertIn("packages checked: 1; passed: 1; failed: 0; copies compared: 1", output)

    def test_relative_single_skill_selectors_map_to_their_actual_package_basename(self) -> None:
        package = self.skill("alpha")
        nested = package / "nested"
        nested.mkdir()
        self.install(package)

        code, output = self.execute("--skill", ".", "--compare-to", self.installed, cwd=package)
        self.assertEqual(code, 0, output)
        self.assertIn("copies compared: 1", output)
        code, output = self.execute("--skill", "..", "--compare-to", self.installed, cwd=nested)
        self.assertEqual(code, 0, output)
        self.assertIn("copies compared: 1", output)

    def test_parent_selector_through_a_symlink_maps_to_the_physical_package(self) -> None:
        package = self.skill("alpha")
        nested = package / "nested"
        nested.mkdir()
        (self.root / "nested-link").symlink_to(nested, target_is_directory=True)
        self.install(package)

        code, output = self.execute(
            "--skill", "nested-link/..", "--compare-to", self.installed, cwd=self.root
        )

        self.assertEqual(code, 0, output)
        self.assertIn("alpha sha256:", output)
        self.assertIn("copies compared: 1", output)

    def test_read_failure_reports_the_path_and_summary_without_a_traceback(self) -> None:
        package = self.skill("alpha")
        driver = (
            "import errno, os, runpy, sys\n"
            "from unittest.mock import patch\n"
            "sys.argv = sys.argv[1:]\n"
            "with patch('os.read', side_effect=OSError(errno.EIO, 'Input/output error')):\n"
            "    runpy.run_path(sys.argv[0], run_name='__main__')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", driver, str(CHECKER), "--skill", str(package)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("cannot read file SKILL.md: Input/output error", result.stdout, result.stderr)
        self.assertIn("packages checked: 1; passed: 0; failed: 1; copies compared: 0", result.stdout)
        self.assertNotIn("sha256:", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_comparison_reports_missing_added_content_executable_and_empty_directory_drift(self) -> None:
        package = self.skill("alpha")
        (package / "missing.txt").write_text("source", encoding="utf-8")
        (package / "empty").mkdir()
        executable = package / "run"
        executable.write_text("source", encoding="utf-8")
        executable.chmod(0o755)
        installed = self.install(package)
        (installed / "missing.txt").unlink()
        (installed / "empty").rmdir()
        (installed / "SKILL.md").write_text("different", encoding="utf-8")
        (installed / "run").chmod(0o644)
        (installed / "added.txt").write_text("added", encoding="utf-8")

        code, output = self.execute("--skill", package, "--compare-to", self.installed)

        self.assertEqual(code, 1)
        for finding in (
            "missing installed path: missing.txt",
            "missing installed path: empty",
            "added installed path: added.txt",
            "content changed: SKILL.md",
            "executable bits changed: run",
        ):
            self.assertIn(finding, output)
        self.assertIn("packages checked: 1; passed: 0; failed: 1; copies compared: 1", output)

    def test_collection_requires_a_regular_marker_for_each_directory_and_ignores_regular_files(self) -> None:
        self.skill("valid")
        incomplete = self.skills / "incomplete"
        incomplete.mkdir()
        (self.skills / "ordinary.txt").write_text("ignored", encoding="utf-8")

        code, output = self.execute("--skills-dir", self.skills)

        self.assertEqual(code, 1)
        self.assertIn("missing or unreadable SKILL.md", output)
        self.assertIn("packages checked: 0; passed: 0; failed: 0; copies compared: 0", output)

    def test_empty_and_missing_selections_fail_visibly(self) -> None:
        code, output = self.execute("--skills-dir", self.skills)
        self.assertEqual(code, 1)
        self.assertIn("skills directory inventory is empty", output)
        code, output = self.execute("--skill", self.root / "missing")
        self.assertEqual(code, 1)
        self.assertIn("skill selection is missing or unreadable", output)

    def test_selector_misuse_exits_two(self) -> None:
        package = self.skill("alpha")
        code, output = self.execute("--skill", package, "--skills-dir", self.skills)
        self.assertEqual(code, 2)
        self.assertIn("not allowed with argument", output)
        code, output = self.execute()
        self.assertEqual(code, 2)
        self.assertIn("one of the arguments", output)

    def test_symlinks_are_rejected_at_roots_collection_entries_markers_and_nested_paths(self) -> None:
        package = self.skill("alpha")
        (package / "linked").symlink_to("SKILL.md")
        code, output = self.execute("--skill", package)
        self.assertEqual(code, 1)
        self.assertIn("package contains a symlink: linked", output)
        marker = self.skill("marker")
        (marker / "SKILL.md").unlink()
        (marker / "SKILL.md").symlink_to("../alpha/SKILL.md")
        code, output = self.execute("--skill", marker)
        self.assertEqual(code, 1)
        self.assertIn("SKILL.md must not be a symlink", output)
        linked_root = self.root / "linked-root"
        linked_root.symlink_to(package, target_is_directory=True)
        code, output = self.execute("--skill", linked_root)
        self.assertEqual(code, 1)
        self.assertIn("skill selection must not be a symlink", output)

    def test_collection_symlink_and_special_file_fail(self) -> None:
        self.skill("valid")
        (self.skills / "linked").symlink_to("valid", target_is_directory=True)
        code, output = self.execute("--skills-dir", self.skills)
        self.assertEqual(code, 1)
        self.assertIn("collection contains a symlink", output)
        (self.skills / "linked").unlink()
        fifo = self.skills / "pipe"
        os.mkfifo(fifo)
        code, output = self.execute("--skills-dir", self.skills)
        self.assertEqual(code, 1)
        self.assertIn("collection contains a special file", output)

    def test_special_files_and_unsafe_or_missing_installed_copies_fail(self) -> None:
        package = self.skill("alpha")
        fifo = package / "pipe"
        os.mkfifo(fifo)
        code, output = self.execute("--skill", package)
        self.assertEqual(code, 1)
        self.assertIn("package contains a special file: pipe", output)
        fifo.unlink()
        self.install(package)
        shutil.rmtree(self.installed / "alpha")
        (self.installed / "alpha").symlink_to("elsewhere", target_is_directory=True)
        code, output = self.execute("--skill", package, "--compare-to", self.installed)
        self.assertEqual(code, 1)
        self.assertIn("installed copy", output)
        self.assertIn("package root must not be a symlink", output)

    def test_type_drift_and_a_missing_installed_copy_fail_with_path_level_findings(self) -> None:
        package = self.skill("alpha")
        (package / "item").write_text("file", encoding="utf-8")
        installed = self.install(package)
        (installed / "item").unlink()
        (installed / "item").mkdir()
        code, output = self.execute("--skill", package, "--compare-to", self.installed)
        self.assertEqual(code, 1)
        self.assertIn("type changed: item", output)
        shutil.rmtree(installed)
        code, output = self.execute("--skill", package, "--compare-to", self.installed)
        self.assertEqual(code, 1)
        self.assertIn("installed copy", output)
        self.assertIn("package root is missing or unreadable", output)
        self.assertIn("copies compared: 0", output)

    def test_unreadable_source_file_and_installed_parent_symlink_fail(self) -> None:
        package = self.skill("alpha")
        blocked = package / "blocked"
        blocked.write_text("secret", encoding="utf-8")
        blocked.chmod(0)
        try:
            code, output = self.execute("--skill", package)
        finally:
            blocked.chmod(0o600)
        self.assertEqual(code, 1)
        self.assertIn("cannot read file blocked", output)
        installed_link = self.root / "installed-link"
        installed_link.symlink_to(self.installed, target_is_directory=True)
        code, output = self.execute("--skill", package, "--compare-to", installed_link)
        self.assertEqual(code, 1)
        self.assertIn("installed skills directory must not be a symlink", output)

    def test_failed_source_inspection_does_not_count_as_a_completed_comparison(self) -> None:
        package = self.skill("alpha")
        self.install(package)
        os.mkfifo(package / "pipe")

        code, output = self.execute("--skill", package, "--compare-to", self.installed)

        self.assertEqual(code, 1)
        self.assertIn("package contains a special file: pipe", output)
        self.assertIn("packages checked: 1; passed: 0; failed: 1; copies compared: 0", output)

    def test_nonprintable_path_diagnostics_are_escaped(self) -> None:
        package = self.skill("alpha")
        unusual = package / "bad\nname"
        unusual.symlink_to("SKILL.md")

        code, output = self.execute("--skill", package)

        self.assertEqual(code, 1)
        self.assertIn("bad\\x0aname", output)
        self.assertNotIn("bad\nname", output)


if __name__ == "__main__":
    unittest.main()
