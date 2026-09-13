#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TOOLS = Path(__file__).resolve().parent
CHECKER = TOOLS / "check-skill-frontmatter.py"
REPOSITORY = TOOLS.parent


class FrontmatterChecker(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name) / "skills"
        self.root.mkdir()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def skill(self, name: str = "a", frontmatter: str = 'name: a\ndescription: "valid description"') -> Path:
        directory = self.root / name
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "SKILL.md"
        path.write_text(f"---\n{frontmatter}\n---\n\nBody.\n", encoding="utf-8")
        return path

    def corpus(self, entries: list[dict[str, object]] | None = None, **payload: object) -> Path:
        path = self.root.parent / "triggers.json"
        data: dict[str, object] = {"version": 1, "triggers": entries if entries is not None else []}
        data.update(payload)
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def check(self, triggers: Path | None = None) -> tuple[int, str]:
        command = [sys.executable, str(CHECKER), str(self.root)]
        if triggers is not None:
            command.extend(["--triggers", str(triggers)])
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        return result.returncode, result.stdout

    def test_isolated_fixture_keeps_one_argument_interface(self) -> None:
        self.skill()
        self.assertEqual(self.check()[0], 0)

    def test_valid_block_scalar_and_omitted_openai_policy_pass(self) -> None:
        self.skill(frontmatter="name: a\ndescription: >-\n  Valid block scalar description\nmetadata:\n  owner: tools")
        policy = self.root / "a" / "agents"
        policy.mkdir()
        policy_path = policy / "openai.yaml"
        policy_path.write_text("interface: chat\n", encoding="utf-8")
        self.assertEqual(self.check()[0], 0)
        policy_path.write_text("interface: chat\npolicy: {}\n", encoding="utf-8")
        self.assertEqual(self.check()[0], 0)

    def test_empty_inventory_fails(self) -> None:
        code, output = self.check()
        self.assertEqual(code, 1)
        self.assertIn("inventory is empty", output)

    def test_yaml_syntax_unsafe_tag_and_non_mapping_fail(self) -> None:
        for source in ("name: [\ndescription: d", "name: a\ndescription: !!python/object/apply:os.system [echo]", "- name: a"):
            with self.subTest(source=source):
                self.skill(frontmatter=source)
                self.assertEqual(self.check()[0], 1)
                (self.root / "a" / "SKILL.md").unlink()

    def test_markdown_rule_after_frontmatter_passes(self) -> None:
        path = self.skill()
        path.write_text("---\nname: a\ndescription: d\n---\n---\n\nBody after a Markdown rule.\n", encoding="utf-8")
        self.assertEqual(self.check()[0], 0)

    def test_top_level_and_nested_duplicate_keys_fail(self) -> None:
        for source, line in (
            ('name: a\ndescription: "d"\n"name": a', 4),
            ('name: a\ndescription: "d"\nmetadata:\n  owner: tools\n  owner: docs', 6),
        ):
            with self.subTest(source=source):
                self.skill(frontmatter=source)
                code, output = self.check()
                self.assertEqual(code, 1)
                self.assertIn("duplicate key", output)
                self.assertIn(f"SKILL.md:{line}", output)
                (self.root / "a" / "SKILL.md").unlink()

    def test_tabs_types_names_and_length_boundaries(self) -> None:
        failures = (
            "name: a\ndescription:\tbad",
            "name: a\ndescription: 3",
            "name: A\ndescription: d",
            "name: a\ndescription: d\nallowed-tools: [Read]",
            "name: a\ndescription: d\nmetadata:\n  owner: 3",
            f"name: a\ndescription: {'d' * 1025}",
        )
        for source in failures:
            with self.subTest(source=source[:30]):
                self.skill(frontmatter=source)
                self.assertEqual(self.check()[0], 1)
                (self.root / "a" / "SKILL.md").unlink()
        self.skill(frontmatter=f"name: a\ndescription: {'d' * 1024}\ncompatibility: {'c' * 500}")
        self.assertEqual(self.check()[0], 0)

    def test_policy_truth_table_and_malformed_policy(self) -> None:
        self.skill(frontmatter='name: a\ndescription: "d"\ndisable-model-invocation: true')
        policy = self.root / "a" / "agents"
        policy.mkdir()
        policy_path = policy / "openai.yaml"
        for source, expected in (
            ("policy:\n  allow_implicit_invocation: false\n", 0),
            ("policy:\n  allow_implicit_invocation: true\n", 1),
            ("policy:\n  allow_implicit_invocation: value\n", 1),
            ("policy: false\n", 1),
            ("policy:\n  allow_implicit_invocation: false\n---\ninterface: chat\n", 1),
        ):
            with self.subTest(source=source):
                policy_path.write_text(source, encoding="utf-8")
                self.assertEqual(self.check()[0], expected)
        policy_path.write_text("policy:\n  allow_implicit_invocation: false\n", encoding="utf-8")
        self.skill("b", 'name: b\ndescription: "d"')
        (self.root / "b" / "agents").mkdir()
        b_policy_path = self.root / "b" / "agents" / "openai.yaml"
        b_policy_path.write_text("policy:\n  allow_implicit_invocation: false\n", encoding="utf-8")
        code, output = self.check()
        self.assertEqual(code, 1)
        self.assertEqual(output, f"{b_policy_path}: policy.allow_implicit_invocation must match disable-model-invocation\n")

    def test_missing_disabled_policy_and_orphan_file_fail(self) -> None:
        self.skill(frontmatter='name: a\ndescription: "d"\ndisable-model-invocation: true')
        policy_path = self.root / "a" / "agents" / "openai.yaml"
        code, output = self.check()
        self.assertEqual(code, 1)
        self.assertEqual(output, f"{policy_path}: missing policy.allow_implicit_invocation: false\n")
        policy = policy_path.parent
        policy.mkdir()
        policy_path.write_text("interface: chat\npolicy: {}\n", encoding="utf-8")
        code, output = self.check()
        self.assertEqual(code, 1)
        self.assertEqual(output, f"{policy_path}: missing policy.allow_implicit_invocation: false\n")
        (self.root / "orphan" / "agents").mkdir(parents=True)
        (self.root / "orphan" / "agents" / "openai.yaml").write_text("policy: {}\n", encoding="utf-8")
        code, output = self.check()
        self.assertEqual(code, 1)
        self.assertIn("orphan", output)

    def test_corpus_coverage_literal_drift_and_mode_fail(self) -> None:
        self.skill()
        valid = [{"skill": "a", "example_request": "Help with a valid task", "description_contains": ["VALID   description"], "implicit_allowed": True}]
        self.assertEqual(self.check(self.corpus(valid))[0], 0)
        for entries in (
            [],
            [{"skill": "a", "example_request": "x", "description_contains": ["missing"], "implicit_allowed": True}],
            [{"skill": "a", "example_request": "x", "description_contains": ["valid"], "implicit_allowed": False}],
            valid + valid,
            valid + [{"skill": "gone", "example_request": "x", "description_contains": ["x"], "implicit_allowed": True}],
        ):
            with self.subTest(entries=entries):
                self.assertEqual(self.check(self.corpus(entries))[0], 1)

    def test_independent_trigger_diagnostics_survive_missing_description_anchors(self) -> None:
        self.skill()
        corpus = self.corpus(
            [
                {"skill": "a", "example_request": "x", "description_contains": ["valid"], "implicit_allowed": True},
                {"skill": "gone", "example_request": "x", "implicit_allowed": True},
            ]
        )
        code, output = self.check(corpus)
        self.assertEqual(code, 1)
        self.assertEqual(
            output,
            f"{corpus}: stale trigger declaration for 'gone'\n"
            f"{corpus}: trigger declaration 2.description_contains must be a nonempty list\n",
        )
        corpus = self.corpus([{"skill": "a", "example_request": "x", "implicit_allowed": False}])
        code, output = self.check(corpus)
        self.assertEqual(code, 1)
        self.assertEqual(
            output,
            f"{corpus}: trigger declaration 1.implicit_allowed does not match 'a'\n"
            f"{corpus}: trigger declaration 1.description_contains must be a nonempty list\n",
        )

    def test_malformed_json_duplicate_keys_and_unsupported_version_fail(self) -> None:
        self.skill()
        corpus = self.corpus()
        for payload in (
            '{"version": 1, "version": 1, "triggers": []}',
            '{"version": 1, "triggers": [{"skill": "a", "skill": "a"}]}',
            "{",
            '{"version": 2, "triggers": []}',
        ):
            with self.subTest(payload=payload):
                corpus.write_text(payload, encoding="utf-8")
                self.assertEqual(self.check(corpus)[0], 1)


if __name__ == "__main__":
    unittest.main()
