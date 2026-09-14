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
        (real / "refs" / "my").write_text("x", encoding="utf-8")
        (real / "refs" / "diagram(1).svg").write_text("x", encoding="utf-8")
        (real / "refs" / "my#notes.md").write_text("x", encoding="utf-8")
        (real / "refs" / "my?notes.md").write_text("x", encoding="utf-8")
        (real / "refs" / "literal%20name.md").write_text("x", encoding="utf-8")
        (real / "refs" / r"foo\q.md").write_text("x", encoding="utf-8")
        (real / "run.sh").write_text("x", encoding="utf-8")
        (real / "LICENSE").write_text("x", encoding="utf-8")

    def body(self, body: str) -> tuple[int, str]:
        self.skill("a", 'name: a\ndescription: "d"', body)
        return run(CONTENT, self.root)

    def test_clean_tree_passes(self) -> None:
        self.assertEqual(run(CONTENT, self.root), (0, ""))

    def test_whitespace_only_line_does_not_hide_a_broken_link(self) -> None:
        code, out = self.body("Intro.\n   \nSee [bad](MISSING).")
        self.assertEqual(code, 1)
        self.assertIn("MISSING", out)

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

    def test_broken_markdown_image_fires(self) -> None:
        code, out = self.body("See ![diagram](references/gone.svg).")
        self.assertEqual(code, 1)
        self.assertIn("references/gone.svg", out)

    def test_explicit_placeholder_does_not_hide_a_broken_extensionless_link(self) -> None:
        code, out = self.body("See [PR]({url}) and [license](MISSING).")
        self.assertEqual(code, 1)
        self.assertIn("MISSING", out)
        self.assertNotIn("{url}", out)

    def test_multiline_explicit_placeholders_are_ignored(self) -> None:
        body = (
            "See [PR](\n  {url}\n) and [issue][issue].\n\n"
            "[issue]:\n  {issue_url}"
        )
        self.assertEqual(self.body(body)[0], 0)

    def test_raw_placeholder_variants_are_ignored(self) -> None:
        body = (
            "See [angle](<{url}>), [fragment]({url}#section), and "
            "[query]({url}?q=1).\n\n"
            "[reference]: <{issue_url}>\n"
            "See [reference]."
        )
        self.assertEqual(self.body(body)[0], 0)

    def test_raw_placeholders_with_escaped_uri_delimiters_are_ignored(self) -> None:
        body = (
            r"See [fragment]({url}\#section), "
            r"![query]({url}\?q=1), and [angle](<{url}\#section>)."
            "\n\n"
            r"[reference]: <{issue_url}\?q=1>"
            "\nSee [reference]."
        )
        self.assertEqual(self.body(body)[0], 0)

    def test_placeholder_prefix_with_balanced_suffix_is_a_filename(self) -> None:
        code, out = self.body("See [missing]({url}(tail)).")
        self.assertEqual(code, 1)
        self.assertIn("{url}(tail)", out)

    def test_percent_encoded_placeholder_is_a_filename(self) -> None:
        code, out = self.body("See [missing](%7Burl%7D).")
        self.assertEqual(code, 1)
        self.assertIn("target does not exist: {url}", out)

    def test_escaped_placeholder_is_a_filename(self) -> None:
        code, out = self.body(r"See [missing](\{url\}).")
        self.assertEqual(code, 1)
        self.assertIn("target does not exist: {url}", out)

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

    def test_quoted_inline_code_paths_may_contain_spaces(self) -> None:
        code, out = self.body(
            "Use `\"../real-skill/refs/my notes.md\"` and "
            "`\"../real-skill/refs/MISSING FILE.md\"`."
        )
        self.assertEqual(code, 1)
        self.assertIn("MISSING FILE.md", out)
        self.assertNotIn("my notes.md", out)

    def test_inline_code_percent_escapes_are_literal(self) -> None:
        code, out = self.body(
            "Use `../real-skill/refs/literal%20name.md` and "
            "`../real-skill/refs/MISSING%20LITERAL.md`."
        )
        self.assertEqual(code, 1)
        self.assertIn("MISSING%20LITERAL.md", out)
        self.assertNotIn("literal%20name.md", out)

    def test_inline_command_with_options_is_not_a_path(self) -> None:
        self.assertEqual(
            self.body("Run `../real-skill/run.sh --check`.")[0],
            0,
        )

    def test_unquoted_spaced_inline_content_is_not_a_path(self) -> None:
        self.assertEqual(
            self.body("Use `../real-skill/refs/MISSING FILE.md`.")[0],
            0,
        )

    def test_multiple_quoted_tokens_are_not_one_path(self) -> None:
        cases = (
            '`"../real-skill/LICENSE" "../MISSING.md"`',
            "`'../real-skill/LICENSE' '../MISSING.md'`",
        )
        for body in cases:
            with self.subTest(body=body):
                self.assertEqual(self.body(body)[0], 0)

    def test_inline_code_delimiters_remain_part_of_the_filename(self) -> None:
        code, out = self.body(
            "Use `../real-skill/refs/my?notes.md`, "
            "`../real-skill/refs/my#notes.md`, "
            "`../real-skill/refs/gone?notes.md`, and "
            "`../real-skill/refs/gone#notes.md`."
        )
        self.assertEqual(code, 1)
        self.assertIn("gone?notes.md", out)
        self.assertIn("gone#notes.md", out)
        self.assertNotIn("my?notes.md", out)
        self.assertNotIn("my#notes.md", out)

    def test_markdown_examples_inside_inline_code_are_ignored(self) -> None:
        body = (
            "Use `[inline](MISSING-INLINE-EXAMPLE.svg)` and "
            "`[reference]: MISSING-REFERENCE-EXAMPLE.svg`; "
            "see [real](MISSING-REAL.svg)."
        )
        code, out = self.body(body)
        self.assertEqual(code, 1)
        self.assertIn("MISSING-REAL.svg", out)
        self.assertNotIn("MISSING-INLINE-EXAMPLE.svg", out)
        self.assertNotIn("MISSING-REFERENCE-EXAMPLE.svg", out)

    def test_even_length_code_span_hides_markdown_examples(self) -> None:
        body = (
            "Use ``[example](MISSING-DOUBLE-SPAN.svg)`` and "
            "see [real](MISSING-REAL.svg)."
        )
        code, out = self.body(body)
        self.assertEqual(code, 1)
        self.assertIn("MISSING-REAL.svg", out)
        self.assertNotIn("MISSING-DOUBLE-SPAN.svg", out)

    def test_even_length_code_span_still_checks_a_filesystem_path(self) -> None:
        code, out = self.body("Use ``../real-skill/refs/gone.svg``.")
        self.assertEqual(code, 1)
        self.assertIn("../real-skill/refs/gone.svg", out)

    def test_escaped_backticks_do_not_hide_a_real_link(self) -> None:
        code, out = self.body(r"Use \`[real](MISSING-ESCAPED-TICKS.svg)\`.")
        self.assertEqual(code, 1)
        self.assertIn("MISSING-ESCAPED-TICKS.svg", out)

    def test_multiline_code_span_hides_markdown_examples(self) -> None:
        body = (
            "Use ``code\n"
            "[example](MISSING-MULTILINE-SPAN.svg)\n"
            "code`` and see [real](MISSING-REAL.svg)."
        )
        code, out = self.body(body)
        self.assertEqual(code, 1)
        self.assertIn("MISSING-REAL.svg", out)
        self.assertNotIn("MISSING-MULTILINE-SPAN.svg", out)

    def test_link_after_multiline_code_span_reports_its_own_line(self) -> None:
        code, out = self.body(
            "Prefix ``code\ncontinued`` then [bad](MISSING-AFTER-CODE.svg)"
        )
        self.assertEqual(code, 1)
        self.assertIn("SKILL.md:7: relative-link", out)

    def test_links_after_multiline_link_syntax_report_their_lines(self) -> None:
        code, out = self.body(
            "[first](\nMISSING-FIRST.svg\n)\n"
            "[second](MISSING-SECOND.svg)"
        )
        self.assertEqual(code, 1)
        self.assertIn("SKILL.md:6: relative-link", out)
        self.assertIn("SKILL.md:9: relative-link", out)

    def test_code_path_inside_multiline_link_label_reports_its_line(self) -> None:
        code, out = self.body(
            "[label\n`../MISSING-NESTED-LABEL.md`](https://example.com)"
        )
        self.assertEqual(code, 1)
        self.assertIn("SKILL.md:7: relative-link", out)

    def test_skill_after_multiline_code_span_reports_its_own_line(self) -> None:
        code, out = self.body(
            "Prefix ``code\ncontinued`` then **fake-skill** skill."
        )
        self.assertEqual(code, 1)
        self.assertIn("SKILL.md:7: sibling-skill", out)

    def test_nested_multiline_tokens_advance_the_line_once(self) -> None:
        cases = (
            "[``code\ncontinued``](https://example.com) then "
            "**fake-skill** skill.",
            "[![alt\ncontinued](../real-skill/LICENSE)](https://example.com) "
            "then **fake-skill** skill.",
        )
        for body in cases:
            with self.subTest(body=body):
                code, out = self.body(body)
                self.assertEqual(code, 1)
                self.assertIn("SKILL.md:7: sibling-skill", out)

    def test_inline_code_path_inside_image_alt_is_checked(self) -> None:
        code, out = self.body(
            "![`../MISSING-IN-ALT.md`](../real-skill/LICENSE)"
        )
        self.assertEqual(code, 1)
        self.assertIn("../MISSING-IN-ALT.md", out)

    def test_spaced_inline_code_path_inside_image_alt_is_checked(self) -> None:
        code, out = self.body(
            "![`\"../MISSING IMAGE ALT.md\"`](../real-skill/LICENSE)"
        )
        self.assertEqual(code, 1)
        self.assertIn("../MISSING IMAGE ALT.md", out)

    def test_skill_reference_inside_image_alt_is_checked(self) -> None:
        code, out = self.body(
            "![Use the **fake-skill** skill.](../real-skill/LICENSE)"
        )
        self.assertEqual(code, 1)
        self.assertIn("sibling-skill", out)

    def test_multiline_image_alt_skill_reports_its_own_line(self) -> None:
        code, out = self.body(
            "![alt\nUse the **fake-skill** skill.](../real-skill/LICENSE)"
        )
        self.assertEqual(code, 1)
        self.assertIn("SKILL.md:7: sibling-skill", out)

    def test_code_spans_stop_at_markdown_block_boundaries(self) -> None:
        cases = {
            "blank": "Use `open\n\n[real](MISSING-BLANK.svg)`",
            "list": "- Start `open\n- [real](MISSING-LIST.svg)`",
            "heading": "# Start `open\n[real](MISSING-HEADING.svg)`",
        }
        for name, body in cases.items():
            with self.subTest(name=name):
                code, out = self.body(body)
                self.assertEqual(code, 1)
                self.assertIn(f"MISSING-{name.upper()}.svg", out)

    def test_lazy_blockquote_continuation_stays_in_its_inline_block(self) -> None:
        code, out = self.body(
            "> Start `open\n[example](MISSING-LAZY-QUOTE.svg)`"
        )
        self.assertEqual(code, 0, out)

    def test_commonmark_block_boundaries_end_unmatched_code_spans(self) -> None:
        cases = {
            "setext": (
                "Use `open\nHeading\n=======\n\n"
                "[bad](MISSING-SETEXT.svg)"
            ),
            "thematic": (
                "Use `open\n\n***\n\n"
                "[bad](MISSING-THEMATIC.svg)"
            ),
            "indented": (
                "Use `open\n\n    [hidden](MISSING-HIDDEN.svg)\n\n"
                "[bad](MISSING-INDENTED.svg)"
            ),
            "html": (
                "<div>\n[hidden](MISSING-HIDDEN.svg)\n</div>\n\n"
                "[bad](MISSING-HTML.svg)"
            ),
        }
        for name, body in cases.items():
            with self.subTest(name=name):
                code, out = self.body(body)
                self.assertEqual(code, 1)
                self.assertIn(f"MISSING-{name.upper()}.svg", out)
                self.assertNotIn("MISSING-HIDDEN.svg", out)

    def test_noninterrupting_ordered_marker_stays_in_its_inline_block(self) -> None:
        code, out = self.body(
            "Use `open\n2. [example](MISSING-ORDERED.svg)`"
        )
        self.assertEqual(code, 0, out)

    def test_line_leading_triple_code_span_is_not_a_fence(self) -> None:
        body = (
            "```[example](MISSING-TRIPLE-SPAN.svg)```\n"
            "See [real](MISSING-REAL.svg)."
        )
        code, out = self.body(body)
        self.assertEqual(code, 1)
        self.assertIn("MISSING-REAL.svg", out)
        self.assertNotIn("MISSING-TRIPLE-SPAN.svg", out)

    def test_unequal_code_span_delimiters_do_not_create_a_path(self) -> None:
        body = (
            "Use `../real-skill/refs/gone.md`` as literal prose; "
            "see [real](MISSING-REAL.svg)."
        )
        code, out = self.body(body)
        self.assertEqual(code, 1)
        self.assertIn("MISSING-REAL.svg", out)
        self.assertNotIn("gone.md", out)

    def test_code_span_mask_does_not_join_a_link_destination(self) -> None:
        body = (
            "Use [label]`code`(MISSING-JOINED.svg) and "
            "see [real](MISSING-REAL.svg)."
        )
        code, out = self.body(body)
        self.assertEqual(code, 1)
        self.assertIn("MISSING-REAL.svg", out)
        self.assertNotIn("MISSING-JOINED.svg", out)

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

    def test_encoded_null_reports_a_finding_instead_of_crashing(self) -> None:
        code, out = self.body("See [bad](references/gone%00.svg).")
        self.assertEqual(code, 1)
        self.assertIn("relative-link", out)

    def test_escaped_delimiters_still_have_uri_semantics(self) -> None:
        code, out = self.body(
            r"See [hash](../real-skill/refs/my\#notes.md), "
            r"[query](../real-skill/refs/my\?notes.md), "
            r"[bad-hash](../real-skill/refs/gone\#notes.md), and "
            r"[bad-query](../real-skill/refs/gone\?notes.md)."
        )
        self.assertEqual(code, 1)
        self.assertIn("target does not exist: ../real-skill/refs/gone", out)
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

    def test_duplicate_reference_definition_targets_are_checked(self) -> None:
        code, out = self.body(
            "[x]: ../real-skill/LICENSE\n"
            "[x]: references/MISSING-DUPLICATE.svg\n\n"
            "See [x]."
        )
        self.assertEqual(code, 1)
        self.assertIn("references/MISSING-DUPLICATE.svg", out)

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

    def test_defined_reference_link_precedes_a_literal_parenthesis(self) -> None:
        body = (
            "[bar]: ../real-skill/LICENSE\n\n"
            "Use [foo][bar](MISSING-LITERAL.svg) and "
            "see [real](MISSING-REAL.svg)."
        )
        code, out = self.body(body)
        self.assertEqual(code, 1)
        self.assertIn("MISSING-REAL.svg", out)
        self.assertNotIn("MISSING-LITERAL.svg", out)

    def test_collapsed_and_nested_reference_links_precede_parentheses(self) -> None:
        body = (
            "[bar]: ../real-skill/LICENSE\n\n"
            "Use [bar][](MISSING-COLLAPSED.svg), "
            "[foo [nested]][bar](MISSING-NESTED-REFERENCE.svg), and "
            "[real](MISSING-REAL.svg)."
        )
        code, out = self.body(body)
        self.assertEqual(code, 1)
        self.assertIn("MISSING-REAL.svg", out)
        self.assertNotIn("MISSING-COLLAPSED.svg", out)
        self.assertNotIn("MISSING-NESTED-REFERENCE.svg", out)

    def test_empty_text_reference_links_precede_parentheses(self) -> None:
        body = (
            "[bar]: ../real-skill/LICENSE\n\n"
            "Use [][bar](MISSING-EMPTY.svg), "
            "![][bar](MISSING-EMPTY-IMAGE.svg), and "
            "[real](MISSING-REAL.svg)."
        )
        code, out = self.body(body)
        self.assertEqual(code, 1)
        self.assertIn("MISSING-REAL.svg", out)
        self.assertNotIn("MISSING-EMPTY.svg", out)
        self.assertNotIn("MISSING-EMPTY-IMAGE.svg", out)

    def test_reference_chain_leaves_the_final_inline_link_active(self) -> None:
        body = (
            "[baz]: ../real-skill/LICENSE\n"
            "[bar]: ../real-skill/LICENSE\n\n"
            "Use [foo][baz][bar](MISSING-FINAL-INLINE.svg)."
        )
        code, out = self.body(body)
        self.assertEqual(code, 1)
        self.assertIn("MISSING-FINAL-INLINE.svg", out)

    def test_longer_reference_chains_follow_renderer_precedence(self) -> None:
        definition = "[a]: ../real-skill/LICENSE\n\n"
        code, out = self.body(
            definition + "Use [x][a][a][a](MISSING-LITERAL.svg)."
        )
        self.assertEqual(code, 0, out)

        code, out = self.body(
            definition + "Use [x][a][a][a][a](MISSING-ACTIVE.svg)."
        )
        self.assertEqual(code, 1)
        self.assertIn("MISSING-ACTIVE.svg", out)

    def test_ordered_list_continuation_reference_definition_is_checked(self) -> None:
        code, out = self.body(
            "10. item\n\n"
            "    [existing]: ../real-skill/LICENSE\n"
            "    [missing]: MISSING-ORDERED-CONT.svg"
        )
        self.assertEqual(code, 1)
        self.assertIn("MISSING-ORDERED-CONT.svg", out)
        self.assertNotIn("../real-skill/LICENSE", out)

    def test_bullet_list_continuation_reference_definition_is_checked(self) -> None:
        code, out = self.body(
            "-    item\n\n"
            "     [existing]: ../real-skill/LICENSE\n"
            "     [missing]: MISSING-BULLET-CONT.svg"
        )
        self.assertEqual(code, 1)
        self.assertIn("MISSING-BULLET-CONT.svg", out)
        self.assertNotIn("../real-skill/LICENSE", out)

    def test_reference_label_rejects_unescaped_open_bracket(self) -> None:
        self.assertEqual(self.body("[draft[note]: MISSING-INVALID-LABEL.svg")[0], 0)
        code, out = self.body(r"[draft\[note]: MISSING-ESCAPED-LABEL.svg")
        self.assertEqual(code, 1)
        self.assertIn("MISSING-ESCAPED-LABEL.svg", out)

    def test_reference_label_requires_non_whitespace_text(self) -> None:
        self.assertEqual(self.body("[   ]: MISSING-WHITESPACE-LABEL.svg")[0], 0)
        code, out = self.body("[x]: MISSING-SINGLE-LABEL.svg")
        self.assertEqual(code, 1)
        self.assertIn("MISSING-SINGLE-LABEL.svg", out)

    def test_long_reference_labels_do_not_hide_destinations(self) -> None:
        valid = "v" * 999
        invalid = "i" * 1000
        code, out = self.body(
            f"[{valid}]: MISSING-999-LABEL.svg\n"
            f"[{invalid}]: MISSING-1000-LABEL.svg"
        )
        self.assertEqual(code, 1)
        self.assertIn("MISSING-999-LABEL.svg", out)
        self.assertIn("MISSING-1000-LABEL.svg", out)

    def test_reference_definition_inside_blockquote_fence_is_ignored(self) -> None:
        body = "> ```markdown\n> [example]: MISSING\n> ```"
        self.assertEqual(self.body(body)[0], 0)

    def test_reference_definition_inside_list_fence_is_ignored(self) -> None:
        body = "- ```markdown\n  [example]: MISSING\n  ```"
        self.assertEqual(self.body(body)[0], 0)

    def test_blockquote_fence_does_not_hide_following_prose(self) -> None:
        body = "> ```markdown\n> example\n\n[bad]: MISSING.svg\n```"
        code, out = self.body(body)
        self.assertEqual(code, 1)
        self.assertIn("MISSING.svg", out)

    def test_list_fence_does_not_hide_following_prose(self) -> None:
        body = "- ```markdown\n  example\n\n[bad]: MISSING.svg\n```"
        code, out = self.body(body)
        self.assertEqual(code, 1)
        self.assertIn("MISSING.svg", out)

    def test_container_boundary_implicitly_closes_a_fence(self) -> None:
        cases = (
            "> ```markdown\n> example\n\nOutside.",
            "- ```markdown\n  example\n\nOutside.",
        )
        for body in cases:
            with self.subTest(body=body):
                code, out = self.body(body)
                self.assertEqual(code, 0, out)

    def test_unclosed_container_fence_at_eof_is_reported(self) -> None:
        cases = (
            "> ```markdown\n> hidden\n> Use **fake-skill** skill.",
            "- ```markdown\n  hidden\n  Use **fake-skill** skill.",
        )
        for body in cases:
            with self.subTest(body=body):
                code, out = self.body(body)
                self.assertEqual(code, 1)
                self.assertIn("unclosed-fence", out)

    def test_bullet_list_continuation_fence_is_ignored(self) -> None:
        body = "- item\n\n  ```markdown\n  [example]: MISSING\n  ```"
        self.assertEqual(self.body(body)[0], 0)

    def test_bullet_list_continuation_fence_ends_on_deindent(self) -> None:
        body = "- item\n\n  ```markdown\n  example\n\n[bad]: MISSING-BULLET.svg"
        code, out = self.body(body)
        self.assertEqual(code, 1)
        self.assertIn("MISSING-BULLET.svg", out)
        self.assertNotIn("unclosed-fence", out)

    def test_ordered_list_continuation_fence_is_ignored(self) -> None:
        body = "1. item\n\n   ```markdown\n   [example]: MISSING\n   ```"
        self.assertEqual(self.body(body)[0], 0)

    def test_ordered_list_continuation_fence_ends_on_deindent(self) -> None:
        body = "1. item\n\n   ```markdown\n   example\n\n[bad]: MISSING-ORDERED.svg"
        code, out = self.body(body)
        self.assertEqual(code, 1)
        self.assertIn("MISSING-ORDERED.svg", out)
        self.assertNotIn("unclosed-fence", out)

    def test_list_blockquote_fence_keeps_reference_examples_hidden(self) -> None:
        body = "- > ```markdown\n  > [example]: MISSING\n  > ```"
        self.assertEqual(self.body(body)[0], 0)

    def test_blockquote_list_fence_keeps_reference_examples_hidden(self) -> None:
        body = "> - ```markdown\n>   [example]: MISSING\n>   ```"
        self.assertEqual(self.body(body)[0], 0)

    def test_bullet_fence_uses_its_full_padding_width(self) -> None:
        hidden = "-  ```markdown\n   [example]: MISSING\n   ```"
        self.assertEqual(self.body(hidden)[0], 0)

        exposed = "-  ```markdown\n   example\n  [bad]: MISSING.svg\n  ```"
        code, out = self.body(exposed)
        self.assertEqual(code, 1)
        self.assertIn("MISSING.svg", out)

    def test_ordered_fence_uses_its_full_padding_width(self) -> None:
        hidden = "1.  ```markdown\n    [example]: MISSING\n    ```"
        self.assertEqual(self.body(hidden)[0], 0)

        exposed = "1.  ```markdown\n    example\n   [bad]: MISSING.svg\n   ```"
        code, out = self.body(exposed)
        self.assertEqual(code, 1)
        self.assertIn("MISSING.svg", out)

    def test_tabbed_bullet_fence_uses_the_expanded_content_column(self) -> None:
        hidden = "-\t```markdown\n    [example]: MISSING\n    ```"
        self.assertEqual(self.body(hidden)[0], 0)

        exposed = "-\t```markdown\n    example\n   [bad]: MISSING-TAB.svg\n   ```"
        code, out = self.body(exposed)
        self.assertEqual(code, 1)
        self.assertIn("MISSING-TAB.svg", out)

    def test_tabbed_ordered_fence_uses_the_expanded_content_column(self) -> None:
        hidden = "1.\t```markdown\n    [example]: MISSING\n    ```"
        self.assertEqual(self.body(hidden)[0], 0)

        exposed = "1.\t```markdown\n    example\n   [bad]: MISSING-TAB.svg\n   ```"
        code, out = self.body(exposed)
        self.assertEqual(code, 1)
        self.assertIn("MISSING-TAB.svg", out)

    def test_five_space_bullet_padding_does_not_create_a_fence(self) -> None:
        body = "-     ```markdown\n  [bad]: MISSING-SHORT.svg\n  ```"
        code, out = self.body(body)
        self.assertEqual(code, 1)
        self.assertIn("MISSING-SHORT.svg", out)

    def test_five_space_ordered_padding_does_not_create_a_fence(self) -> None:
        body = "1.     ```markdown\n   [bad]: MISSING-SHORT.svg\n   ```"
        code, out = self.body(body)
        self.assertEqual(code, 1)
        self.assertIn("MISSING-SHORT.svg", out)

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

    def test_inline_angle_destination_requires_space_before_title(self) -> None:
        for title in ('"Title"', "'Title'", "(Title)"):
            with self.subTest(title=title):
                adjacent = f"See [invalid](<MISSING-ADJACENT.svg>{title})."
                self.assertEqual(self.body(adjacent)[0], 0)

                spaced = f"See [valid](<MISSING-SPACED.svg> {title})."
                code, out = self.body(spaced)
                self.assertEqual(code, 1)
                self.assertIn("MISSING-SPACED.svg", out)

    def test_inline_destination_allows_leading_and_trailing_whitespace(self) -> None:
        body = (
            "See [existing]( <../real-skill/LICENSE> ) and "
            "[missing]( <MISSING-PADDED.svg> )."
        )
        code, out = self.body(body)
        self.assertEqual(code, 1)
        self.assertIn("MISSING-PADDED.svg", out)
        self.assertNotIn("../real-skill/LICENSE", out)

    def test_inline_angle_destination_rejects_unescaped_open_angle(self) -> None:
        body = (
            "See [invalid](<MISSING<INVALID.svg>) and "
            r"[escaped](<MISSING\<ESCAPED.svg>)."
        )
        code, out = self.body(body)
        self.assertEqual(code, 1)
        self.assertIn("MISSING<ESCAPED.svg", out)
        self.assertNotIn("MISSING<INVALID.svg", out)

    def test_reference_angle_destination_requires_space_before_title(self) -> None:
        for title in ('"Title"', "'Title'", "(Title)"):
            with self.subTest(title=title):
                adjacent = f"[invalid]: <MISSING-ADJACENT.svg>{title}"
                self.assertEqual(self.body(adjacent)[0], 0)

                spaced = f"[valid]: <MISSING-SPACED.svg> {title}"
                code, out = self.body(spaced)
                self.assertEqual(code, 1)
                self.assertIn("MISSING-SPACED.svg", out)

    def test_reference_angle_destination_rejects_unescaped_open_angle(self) -> None:
        self.assertEqual(self.body("[invalid]: <MISSING<INVALID.svg>")[0], 0)
        code, out = self.body(r"[escaped]: <MISSING\<ESCAPED.svg>")
        self.assertEqual(code, 1)
        self.assertIn("MISSING<ESCAPED.svg", out)

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
