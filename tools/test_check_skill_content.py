#!/usr/bin/env python3
"""Both lints must fire on planted defects and stay quiet on valid input."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
CONTENT = TOOLS / "check-skill-content.py"
FRONTMATTER = TOOLS / "check-skill-frontmatter.py"


def run(script: Path, root: Path) -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(script), str(root)], capture_output=True, text=True)
    return p.returncode, p.stdout


class Tree(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "skills"
        self.root.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def skill(self, name: str, frontmatter: str, body: str = "Body.") -> Path:
        d = self.root / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n\n{body}\n", encoding="utf-8")
        return d


class ContentLint(Tree):
    def setUp(self) -> None:
        super().setUp()
        real = self.skill("real-skill", 'name: real-skill\ndescription: "d"')
        (real / "refs").mkdir()
        (real / "refs" / "my notes.md").write_text("x", encoding="utf-8")
        (real / "refs" / "diagram(1).svg").write_text("x", encoding="utf-8")
        (real / "refs" / "my#notes.md").write_text("x", encoding="utf-8")
        (real / "refs" / "my?notes.md").write_text("x", encoding="utf-8")
        (real / "refs" / r"foo\q.md").write_text("x", encoding="utf-8")
        (real / "LICENSE").write_text("x", encoding="utf-8")

    def body(self, body: str) -> tuple[int, str]:
        self.skill("a", 'name: a\ndescription: "d"', body)
        return run(CONTENT, self.root)

    def test_clean_tree_passes(self) -> None:
        self.assertEqual(run(CONTENT, self.root), (0, ""))

    def test_dotdot_link_broken_fires(self) -> None:
        code, out = self.body("See [x](../gone/n.md).")
        self.assertEqual(code, 1)
        self.assertIn("relative-link", out)

    def test_bare_relative_link_broken_fires(self) -> None:
        code, out = self.body("See [x](references/gone.md).")
        self.assertEqual(code, 1, "a link with no ./ prefix is still a relative link")
        self.assertIn("references/gone.md", out)

    def test_broken_non_md_markdown_link_fires(self) -> None:
        code, out = self.body("See [diagram](references/gone.svg).")
        self.assertEqual(code, 1, "markdown links are checked whatever the extension")
        self.assertIn("references/gone.svg", out)

    def test_explicit_placeholder_does_not_hide_a_broken_extensionless_link(self) -> None:
        code, out = self.body("See [PR]({url}) and [license](MISSING).")
        self.assertEqual(code, 1)
        self.assertIn("MISSING", out)
        self.assertNotIn("{url}", out)

    def test_existing_extensionless_link_does_not_hide_a_broken_peer(self) -> None:
        code, out = self.body("See [license](../real-skill/LICENSE) and [bad](MISSING).")
        self.assertEqual(code, 1)
        self.assertIn("MISSING", out)
        self.assertNotIn("../real-skill/LICENSE", out)

    def test_inline_code_path_broken_fires(self) -> None:
        code, out = self.body("Read `../gone/setup.md` first.")
        self.assertEqual(code, 1)

    def test_broken_non_md_inline_path_fires(self) -> None:
        code, out = self.body("Run `../real-skill/gone.sh` first.")
        self.assertEqual(code, 1, "inline code paths are checked whatever the extension")
        self.assertIn("relative-link", out)

    def test_resolving_link_passes(self) -> None:
        self.assertEqual(self.body("See `../real-skill/SKILL.md`.")[0], 0)

    def test_url_encoded_target_that_exists_passes(self) -> None:
        self.assertEqual(self.body("See [x](../real-skill/refs/my%20notes.md).")[0], 0)

    def test_angle_bracket_target_with_spaces_does_not_hide_a_broken_peer(self) -> None:
        code, out = self.body(
            "See [x](<../real-skill/refs/my notes.md>) and [bad](<../real-skill/refs/gone notes.md>)."
        )
        self.assertEqual(code, 1)
        self.assertIn("gone notes.md", out)
        self.assertNotIn("my notes.md", out)

    def test_balanced_parentheses_resolve_before_the_link_closes(self) -> None:
        code, out = self.body(
            "See [x](../real-skill/refs/diagram(1).svg) and [bad](../real-skill/refs/diagram(2).svg)."
        )
        self.assertEqual(code, 1)
        self.assertIn("diagram(2).svg", out)
        self.assertNotIn("diagram(1).svg", out)

    def test_literal_delimiters_are_removed_before_percent_decoding(self) -> None:
        code, out = self.body(
            "See [hash](../real-skill/refs/my%23notes.md) and "
            "[query](../real-skill/refs/my%3Fnotes.md) and "
            "[bad](../missing?version=1)."
        )
        self.assertEqual(code, 1)
        self.assertIn("../missing", out)
        self.assertNotIn("my#notes.md", out)
        self.assertNotIn("my?notes.md", out)

    def test_literal_fragment_is_removed_from_existing_and_missing_targets(self) -> None:
        code, out = self.body(
            "See [license](../real-skill/LICENSE#terms) and [bad](MISSING#section)."
        )
        self.assertEqual(code, 1)
        self.assertIn("MISSING", out)
        self.assertNotIn("#section", out)
        self.assertNotIn("../real-skill/LICENSE", out)

    def test_missing_percent_encoded_delimiter_targets_fire(self) -> None:
        code, out = self.body(
            "See [hash](../real-skill/refs/gone%23notes.md) and "
            "[query](../real-skill/refs/gone%3Fnotes.md)."
        )
        self.assertEqual(code, 1)
        self.assertIn("gone#notes.md", out)
        self.assertIn("gone?notes.md", out)

    def test_percent_encoded_colon_remains_a_relative_filename(self) -> None:
        skill = self.skill(
            "a",
            'name: a\ndescription: "d"',
            "See [existing](foo%3Abar.md) and [missing](gone%3Abar.md).",
        )
        (skill / "foo:bar.md").write_text("x", encoding="utf-8")
        code, out = run(CONTENT, self.root)
        self.assertEqual(code, 1)
        self.assertIn("gone:bar.md", out)
        self.assertNotIn("foo:bar.md", out)

    def test_escaped_delimiters_remain_part_of_the_filename(self) -> None:
        code, out = self.body(
            r"See [hash](../real-skill/refs/my\#notes.md), "
            r"[query](../real-skill/refs/my\?notes.md), "
            r"[bad-hash](../real-skill/refs/gone\#notes.md), and "
            r"[bad-query](../real-skill/refs/gone\?notes.md)."
        )
        self.assertEqual(code, 1)
        self.assertIn("gone#notes.md", out)
        self.assertIn("gone?notes.md", out)
        self.assertNotIn("my#notes.md", out)
        self.assertNotIn("my?notes.md", out)

    def test_backslash_before_non_punctuation_is_preserved(self) -> None:
        code, out = self.body(
            r"See [existing](<../real-skill/refs/foo\q.md>) and "
            r"[missing](<../real-skill/refs/gone\q.md>)."
        )
        self.assertEqual(code, 1)
        self.assertIn(r"gone\q.md", out)
        self.assertNotIn(r"foo\q.md", out)

    def test_reference_definition_targets_are_checked(self) -> None:
        code, out = self.body(
            '[license]: ../real-skill/LICENSE "Terms"\n'
            "[missing]: references/MISSING.svg 'Diagram'\n\n"
            "See [license] and [missing]."
        )
        self.assertEqual(code, 1)
        self.assertIn("references/MISSING.svg", out)
        self.assertNotIn("../real-skill/LICENSE", out)

    def test_angle_reference_targets_with_spaces_are_checked(self) -> None:
        code, out = self.body(
            "   [existing]: <../real-skill/refs/my notes.md>\n"
            "[missing]: <../real-skill/refs/gone notes.md>\n\n"
            "See [existing] and [missing]."
        )
        self.assertEqual(code, 1)
        self.assertIn("gone notes.md", out)
        self.assertNotIn("my notes.md", out)

    def test_indented_code_is_not_a_reference_definition(self) -> None:
        self.assertEqual(self.body("    [example]: MISSING")[0], 0)

    def test_reference_definitions_inside_block_containers_are_checked(self) -> None:
        code, out = self.body(
            "> [existing]: ../real-skill/LICENSE\n"
            "- [missing]: references/MISSING.svg\n\n"
            "> See [existing].\n"
            "- See [missing]."
        )
        self.assertEqual(code, 1)
        self.assertIn("references/MISSING.svg", out)
        self.assertNotIn("../real-skill/LICENSE", out)

    def test_reference_definition_inside_blockquote_fence_is_ignored(self) -> None:
        body = "> ```markdown\n> [example]: MISSING\n> ```"
        self.assertEqual(self.body(body)[0], 0)

    def test_reference_definition_inside_list_fence_is_ignored(self) -> None:
        body = "- ```markdown\n  [example]: MISSING\n  ```"
        self.assertEqual(self.body(body)[0], 0)

    def test_trailing_prose_does_not_form_a_reference_definition(self) -> None:
        body = (
            "[plain]: MISSING.svg trailing prose\n"
            '[titled]: MISSING.svg "Title" garbage'
        )
        self.assertEqual(self.body(body)[0], 0)

    def test_markdown_title_forms_share_one_destination(self) -> None:
        body = (
            'See [double](../real-skill/LICENSE "Double"), '
            "[single](../real-skill/LICENSE 'Single'), "
            "[paren](../real-skill/LICENSE (Paren)), and [bad](MISSING \"Bad\")."
        )
        code, out = self.body(body)
        self.assertEqual(code, 1)
        self.assertEqual(out.count("MISSING"), 1)

    def test_each_markdown_title_form_reports_a_missing_destination(self) -> None:
        body = (
            'See [double](MISSING-DOUBLE "Double"), '
            "[single](MISSING-SINGLE 'Single'), and "
            "[paren](MISSING-PAREN (Paren))."
        )
        code, out = self.body(body)
        self.assertEqual(code, 1)
        self.assertIn("MISSING-DOUBLE", out)
        self.assertIn("MISSING-SINGLE", out)
        self.assertIn("MISSING-PAREN", out)

    def test_escaped_closing_marker_is_ignored_but_a_real_peer_fires(self) -> None:
        code, out = self.body(r"See [example\](ESCAPED-CLOSE) and [bad](MISSING).")
        self.assertEqual(code, 1)
        self.assertIn("MISSING", out)
        self.assertNotIn("ESCAPED-CLOSE", out)

    def test_even_backslashes_leave_the_closing_marker_active(self) -> None:
        code, out = self.body(r"See [example\\](MISSING-EVEN).")
        self.assertEqual(code, 1)
        self.assertIn("MISSING-EVEN", out)

    def test_link_requires_an_unescaped_opening_bracket(self) -> None:
        code, out = self.body(r"See \[example](ESCAPED-OPEN) and [bad](MISSING).")
        self.assertEqual(code, 1)
        self.assertIn("MISSING", out)
        self.assertNotIn("ESCAPED-OPEN", out)

    def test_bare_closing_marker_is_ignored(self) -> None:
        code, out = self.body("See prose ](BARE-TOKEN) and [bad](MISSING).")
        self.assertEqual(code, 1)
        self.assertIn("MISSING", out)
        self.assertNotIn("BARE-TOKEN", out)

    def test_nested_label_reports_a_missing_destination(self) -> None:
        code, out = self.body("See [outer [inner]](MISSING-NESTED).")
        self.assertEqual(code, 1)
        self.assertIn("MISSING-NESTED", out)

    def test_link_inside_a_fence_is_ignored(self) -> None:
        self.assertEqual(self.body("```markdown\n[x](../nope/gone.md)\n```")[0], 0)

    def test_placeholder_path_is_ignored(self) -> None:
        self.assertEqual(self.body("Use `../<suite>/notes.md` here.")[0], 0)

    def test_absolute_url_is_ignored(self) -> None:
        self.assertEqual(self.body("See [x](https://example.com/a.md).")[0], 0)

    def test_unknown_skill_reference_fires(self) -> None:
        code, out = self.body("Use the **fake-skill** skill.")
        self.assertEqual(code, 1)
        self.assertIn("sibling-skill", out)

    def test_principle_name_fires_without_the_word_skill(self) -> None:
        code, out = self.body("- **L** (**principle-nope**). Bias to deletion.")
        self.assertEqual(code, 1, "a principle- name is checked even with no 'skill' on the line")
        self.assertIn("principle-nope", out)

    def test_known_skill_reference_passes(self) -> None:
        self.assertEqual(self.body("Use the **real-skill** skill.")[0], 0)

    def test_bold_prose_is_not_a_skill_reference(self) -> None:
        self.assertEqual(self.body("- **promoted**: it cleared every gate.")[0], 0)

    def test_bold_inside_a_fence_is_ignored(self) -> None:
        self.assertEqual(self.body("```\nuse the **fake-skill** skill\n```")[0], 0)

    def test_bold_inside_inline_code_is_ignored(self) -> None:
        self.assertEqual(self.body("Write `**fake-skill** skill` here.")[0], 0)

    def test_old_monorepo_path_fires_in_prose_and_fenced_templates(self) -> None:
        code, out = self.body(
            "Read pstack/skills/example/SKILL.md.\n\n"
            "````markdown\n"
            "```sh\n"
            "node pstack/skills/example/check.mjs\n"
            "```\n"
            "````"
        )
        self.assertEqual(code, 1)
        self.assertIn("SKILL.md:6: port-substitution", out)
        self.assertIn("SKILL.md:10: port-substitution", out)

    def test_retired_deslop_command_fires_in_prose_and_fenced_templates(self) -> None:
        code, out = self.body(
            "Run /deslop before the commit.\n\n"
            "````markdown\n"
            "```text\n"
            "/deslop\n"
            "```\n"
            "````"
        )
        self.assertEqual(code, 1)
        self.assertIn("SKILL.md:6: port-substitution", out)
        self.assertIn("SKILL.md:10: port-substitution", out)


class FenceHandling(Tree):
    def setUp(self) -> None:
        super().setUp()
        self.skill("real-skill", 'name: real-skill\ndescription: "d"')

    def body(self, body: str) -> tuple[int, str]:
        self.skill("a", 'name: a\ndescription: "d"', body)
        return run(CONTENT, self.root)

    def test_scripts_parse(self) -> None:
        for script in (CONTENT, FRONTMATTER):
            compile(script.read_text(encoding="utf-8"), str(script), "exec")

    def test_only_one_function_reads_the_fence_rule(self) -> None:
        import ast

        tree = ast.parse(CONTENT.read_text(encoding="utf-8"))
        readers = [
            fn.name
            for fn in ast.walk(tree)
            if isinstance(fn, ast.FunctionDef)
            and any(isinstance(n, ast.Name) and n.id == "FENCE" for n in ast.walk(fn))
        ]
        self.assertEqual(readers, ["scan_blocks"], "a second fence walker will drift from the first")

    def test_four_backtick_fence_survives_an_inner_fence(self) -> None:
        code, out = self.body("````\n```\nSee [x](../gone/n.md).\n```\n````")
        self.assertEqual(code, 0, out)

    def test_tilde_fence_is_skipped(self) -> None:
        self.assertEqual(self.body("~~~\n[x](../gone/n.md)\n~~~")[0], 0)

    def test_fence_with_info_string_is_skipped(self) -> None:
        self.assertEqual(self.body("```markdown\n[x](../gone/n.md)\n```")[0], 0)

    def test_a_line_with_an_info_string_does_not_close_a_fence(self) -> None:
        code, out = self.body("```markdown\n```json\nSee [x](../gone/n.md).\n```")
        self.assertEqual(code, 0, "only a bare fence closes one, so the link stays inside the block")

    def test_content_after_a_closed_fence_is_checked(self) -> None:
        self.assertEqual(self.body("```\nx\n```\n\nSee [x](../gone/n.md).")[0], 1)

    def test_unclosed_fence_is_reported(self) -> None:
        code, out = self.body("```\nx\n\nSee [x](../gone/n.md).\nRun /deslop.")
        self.assertEqual(code, 1, "an unclosed fence hides the rest of the file")
        self.assertIn("unclosed-fence", out)
        self.assertIn("link and sibling checks skip the rest of the file", out)
        self.assertIn("port-substitution", out, "raw port checks still inspect text after an unclosed fence")

    def test_fence_indented_inside_a_nested_list_is_still_a_fence(self) -> None:
        code, out = self.body("- a\n  - b\n\n    ```\n    See [x](../gone/n.md).\n    ```")
        self.assertEqual(code, 0, out)

    def test_list_continuation_at_four_spaces_is_checked(self) -> None:
        code, _ = self.body("1. First\n\n    Continued, see [x](../gone/n.md).")
        self.assertEqual(code, 1, "four-space list continuation is prose, not a code block")

    def test_link_with_a_title_attribute_is_checked(self) -> None:
        code, out = self.body('See [x](../gone/n.md "Title").')
        self.assertEqual(code, 1, "a title attribute does not make the target unreachable")
        self.assertIn("../gone/n.md", out)


if __name__ == "__main__":
    unittest.main()
