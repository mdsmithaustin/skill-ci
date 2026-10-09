# Five additions to the free skill lints

Research checked on 2026-10-09. This brief chooses five additions from 15 candidates for authors whose repositories consume skill-ci. The ranking is engineering judgment, not a measured defect rate. The decision stops at five contracts that fit the existing checks without a model, a network request at lint time, or another runtime dependency.

Keep the proposed five. They catch missing bundled resources, ignored reference definitions, absent instructions, literal controls, and decoding failures. The top five use the existing Markdown parser or Python's standard library. They do not certify the skill's usefulness, safe execution, or resistance to prompt injection.

## Existing checks determine the useful additions

The inventory below describes the research baseline at commit `e9e274a6ea8d3a569f4ca4874a6b0cf5f7641bbf`, before these five additions.

The inspected [content checker](../../src/skill_ci/checks/content.py) checked relative Markdown destinations, entire inline-code paths starting with `./` or `../`, sibling skill names, unclosed fences, and configured retired text. It retained duplicate reference definitions but did not report conflicts between their meanings.

The inspected [frontmatter checker](../../src/skill_ci/checks/frontmatter.py) validated metadata, rejected duplicate YAML keys, checked Codex invocation policy, and optionally checked trigger declarations. Both Markdown readers explicitly selected UTF-8 and caught `OSError`, which left decoding failures outside their diagnostic paths. The [package checker](../../src/skill_ci/checks/package.py) rejected symlinks and special files. Its inventory included executable permission bits. The [harvest record](../harvest-skill-optimizer.md) identified bare resource paths as follow-up work and kept the donor's semantic audit with its existing owner.

## Primary evidence and its limits

The [Agent Skills specification](https://agentskills.io/specification) requires frontmatter followed by Markdown instructions. It permits additional directories and recommends `scripts`, `references`, and `assets`. It recommends paths relative to the skill root and a main file under 500 lines. It does not require particular body sections. Its frontmatter-only minimal example makes a strict nonempty-body rule an authoring policy, rather than a claim that every specification example passes that rule.

[CommonMark 0.31.2](https://spec.commonmark.org/0.31.2/#link-reference-definitions) gives the first matching reference definition precedence. Matching folds case and normalizes whitespace. CommonMark defines characters rather than a required byte encoding. The [CommonMark character section](https://spec.commonmark.org/0.31.2/#characters-and-lines) defines ASCII controls, while the specification permits arbitrary character sequences as documents. These proposed findings therefore report authoring defects, rather than CommonMark syntax errors.

The [Unicode Bidirectional Algorithm](https://www.unicode.org/reports/tr9/#Explicit_Directional_Overrides) identifies U+202D and U+202E as directional overrides and advises avoiding overrides where possible because of security concerns. [Unicode Source Code Handling](https://www.unicode.org/reports/tr55/#Blank_And_Invisible_Characters) explains that some invisible characters serve normal orthography and shaping. That evidence supports a narrow list, not a ban on non-ASCII or invisible text. The source-code guidance does not itself define a Markdown lint policy.

[Python's exception documentation](https://docs.python.org/3/library/exceptions.html#UnicodeDecodeError) places `UnicodeDecodeError` under `UnicodeError` and `ValueError`, separately from `OSError`. [Path.read_text](https://docs.python.org/3/library/pathlib.html#pathlib.Path.read_text) decodes file contents using the selected encoding. Catching a decode failure at the reader boundary follows skill-ci's existing UTF-8 choice.

## Decision matrix

All 15 candidates are free of model calls. The dependency column names additions beyond skill-ci's current Python, PyYAML, and markdown-it-py dependencies. The attacks and dispositions are judgments about a shared default lint, unless a row states an existing behavior.

| Rank | Candidate and author value | Added dependency | Attack on noise, overlap, or portability | Decision |
| --- | --- | --- | --- | --- |
| 1 | Missing bare bundled-resource paths in complete inline-code spans. Agents can find the named file. Supported by the resource conventions in the [Agent Skills specification](https://agentskills.io/specification). | None. | Commands, placeholders, globs, directory mentions, and generated outputs can look like paths. Nested Markdown also raises an ambiguity between the skill root and the current file. | Select a narrow grammar. Preserve the current file-relative resolution rule. |
| 2 | Conflicting reference definitions. Authors discover that a later definition is ignored. The precedence rule is explicit in [CommonMark](https://spec.commonmark.org/0.31.2/#link-reference-definitions). | None. | Identical repeated definitions are harmless for this purpose. Raw source comparison would flag alternate escaping or spelling that has the same parsed meaning. Existing target checks already cover missing files. | Select conflicts in parsed destination or title only. |
| 3 | Empty `SKILL.md` body. Authors discover a marker with metadata but no instructions. The [specification](https://agentskills.io/specification) describes the body as instructions. | None. | Frontmatter-only scaffolds can be deliberate. A prescribed section list or minimum word count would reject valid short skills. Comments can conceal apparent content. | Select emptiness as an authoring policy. Count headings and code instructions as content. |
| 4 | Literal C0 controls, DEL, and two bidi overrides. Authors can review the file without those literal characters. See [Unicode overrides](https://www.unicode.org/reports/tr9/#Explicit_Directional_Overrides). | None. | A blanket invisible-character ban damages valid multilingual text. Literal demonstrations are intentional in some security documentation. This list cannot detect every deceptive Unicode construction. | Select the explicit list. Allow escaped demonstrations. Avoid a broad security claim. |
| 5 | Invalid UTF-8 becomes a diagnostic. One malformed Markdown file no longer aborts checking through a decoding exception. See [Python decoding exceptions](https://docs.python.org/3/library/exceptions.html#UnicodeDecodeError). | None. | This is reader robustness rather than a new semantic lint. Replacing invalid bytes would hide damage. An unsupported encoding may be deliberate. | Select diagnostics for the two Markdown entry readers. Keep strict decoding. |
| 6 | Undefined full or collapsed reference labels. Authors find links that appear as bracketed text. [markdownlint MD052](https://github.com/DavidAnson/markdownlint/blob/main/doc/Rules.md#md052---reference-links-and-images-should-use-a-label-that-is-defined) documents the distinction from ambiguous shortcut labels. | None if implemented locally. | Templates and literal bracket examples resemble intended links. The current parser yields text after failed recognition, so detection needs a separate source grammar. | Defer. Require examples from consumers before adding another grammar. |
| 7 | Missing local heading anchors. Authors discover section links broken by heading edits. [markdownlint MD051](https://github.com/DavidAnson/markdownlint/blob/main/doc/Rules.md#md051---link-fragments-should-be-valid) describes this check. | None with a local renderer-specific algorithm. | Heading IDs depend on the renderer. Explicit HTML IDs, extensions, and duplicate heading suffixes make a universal default unreliable. Existing checks deliberately strip fragments when resolving files. | Defer until a consumer declares its renderer. |
| 8 | ShellCheck on bundled shell scripts. Authors find shell bugs before agents execute scripts. [ShellCheck](https://github.com/koalaman/shellcheck) is a static shell analyzer. | A pinned ShellCheck executable. | Embedded examples can be incomplete. Dialect and sourced-file discovery depend on the project. A generic skill package need not contain shell. | Recommend consumer-owned CI for actual script files. Do not add it to shared defaults. |
| 9 | Ruff on bundled Python scripts. Authors find Python lint defects. [Ruff](https://docs.astral.sh/ruff/) supports project configuration. | Ruff plus a selected rule policy. | Language-specific lint policy is separate from skill structure. Templates and examples can intentionally contain unresolved names. Consumers may already run Ruff over their scripts. | Recommend consumer-owned CI using the consumer's configuration. |
| 10 | Secret-pattern detection. Authors reduce accidental credential publication. [Gitleaks](https://github.com/gitleaks/gitleaks#configuration) supplies rules and allowlists. | A pinned Gitleaks executable and rule configuration. | Skills teach authentication and ship sample credentials. The existing personal-data scan addresses a related but different concern. Pattern matches neither prove a credential is live nor establish secret absence. | Defer shared integration. Consumers can run Gitleaks separately with their example allowlists. |
| 11 | Main-file length budget. Authors receive feedback on context cost. The [specification](https://agentskills.io/specification) recommends fewer than 500 lines. | None for line counts. A tokenizer for exact token budgets. | Lines are a weak proxy for context cost. Templates and generated reference tables inflate counts. A recommendation is not a universal validity requirement. | Keep as an optional authoring convention. |
| 12 | Deep reference chains. Authors find resources that require repeated navigation. The [specification](https://agentskills.io/specification) recommends one level of references. | None if the current link graph is reused. | Intentional shared reference libraries and cycles need ownership rules. Traversing every link can include navigation that an agent never follows. | Defer a default depth gate. Document the recommendation. |
| 13 | Blanket Markdown formatting, including heading structure and fence language tags. Authors get consistent formatting through [markdownlint](https://github.com/DavidAnson/markdownlint). | Node and markdownlint for the maintained tool. | Skills can validly use unusual headings and language-free fences. Style settings differ by repository. The existing unclosed-fence rule already targets the consequential defect. | Leave style to consumer configuration. |
| 14 | Absolute local paths in instructions. Authors discover machine-specific resource references before sharing a skill. The [specification](https://agentskills.io/specification) recommends relative resource paths. | None for known path forms. | `/usr/bin`, `/tmp`, Windows drive paths, and paths a skill creates can be intentional. Slash commands and URL paths resemble local paths. Supporting every host's path grammar requires explicit scope. | Defer a default failure. Consider an opt-in portability report with consumer examples. |
| 15 | Stale link-exception entries. Authors find exceptions whose source or exact destination no longer appears. The [exception policy](../link-exceptions.md) defines exact source and destination pairs. | None if the existing parsed links are reused. | A template can retain an exception for a future branch or generated form. Reporting source absence is stronger evidence than assuming a present destination no longer needs an exception. Exception use must respect raw spelling and placeholders. | Defer until the consumer chooses whether unused exceptions are errors. |

Duplicate YAML keys and unsafe package entries are excluded from the 15 additions. At baseline `e9e274a6ea8d3a569f4ca4874a6b0cf5f7641bbf`, the frontmatter loader already rejected duplicate keys and the package checker already rejected symlinks and special files. [YAML 1.2.2](https://yaml.org/spec/1.2.2/#3211-nodes) supports unique mapping keys. The [harvest record](../harvest-skill-optimizer.md) records the package check's ownership. Repeating those checks would add no new coverage.

## Contracts for the five selected checks

These are implementation decisions for skill-ci. The citations above supply context rather than a claim that an external standard mandates each decision.

### 1. Bare resource paths extend the existing path check

Inspect parser-recognized inline-code spans. Add paths starting with `scripts/`, `references/`, or `assets/` only when the complete span is one concrete path. Preserve the existing code-span treatment inside image text. Skip fenced and indented code blocks.

Do not interpret a command such as `python scripts/check.py` as a path. Skip placeholders, glob syntax, shell expansion, and paths ending in `/`. Skip a resolved directory as a directory mention. Do not percent-decode code spans or strip query and fragment text as if code were a Markdown URL. Existing quoted path support can accept a quoted concrete resource path with spaces.

Resolve against the current Markdown file's parent, exactly as the existing relative-link check does. For `SKILL.md`, this is also the skill root. In nested references, authors must use a path relative to that nested file. Switching the base to the enclosing skill root would be a separate compatibility change. The current link-exceptions file does not exempt code spans.

A bare path naming a generated output remains ambiguous. A separate file-existence check cannot infer the author's intent. Restricting the prefixes reduces that ambiguity, but does not remove it. An author can put a generated-output example in a fenced block or write it as part of the complete command.

### 2. Reference conflicts compare meanings after parsing

Use the parser's normalized reference identity and its parsed `href` and `title`. Compare each later definition with the first definition. Report the later line when either field differs. Different labels remain independent. Different source spelling with the same parsed values is accepted. Identical repeated definitions are accepted.

The first definition still governs rendered links. The existing relative-target check still checks each definition's target. Conflict checking does not replace that check. Do not resolve two different destinations to the same filesystem target and call them identical, since the parser retains different link destinations.

### 3. Empty body checks presence, not instructional quality

Apply this rule only to `SKILL.md` after a recognized frontmatter block. Ignore whitespace and HTML comments. Reject a body with nothing else. A heading, a nonempty code block, or a nonempty code span counts as content. Do not strip comment-looking text inside code instructions.

Reference definitions are body text for this minimal presence rule. This rule does not judge whether a heading-only or definition-only body gives useful instructions. Rejecting such bodies would require a stronger content policy than the selected emptiness contract. Leave a missing or malformed frontmatter block to the existing metadata diagnostics.

### 4. Literal controls use a fixed list

Scan raw decoded Markdown, including comments and code blocks. Report U+0000 through U+001F except TAB, LF, and CR. Also report U+007F, U+202D, and U+202E. Print the code point in an ASCII diagnostic rather than emit the literal character again. Escape every listed character at the content diagnostic output boundary, including source paths and other finding details.

Accept literal RTL letters, combining marks, joiners, variation selectors, bidi isolates, and other unlisted characters. Accept visible escape notation such as `\u202e` or `U+202E`. Do not decode those examples or HTML character references to expand the rejected list.

An intentional literal demonstration fails and must use escaped notation. Form feed and vertical tab fail even though some text formats use them. The check does not detect homoglyphs, validate balanced directional formatting, sanitize rendered HTML, or establish resistance to Trojan Source or prompt injection.

### 5. Invalid UTF-8 stays at the Markdown read boundary

Retain strict UTF-8 decoding. Catch `UnicodeDecodeError` for every Markdown file read by content lint and for `SKILL.md` read by frontmatter lint. Emit a file-specific diagnostic, skip parsing that file, continue checking other files, and return the ordinary failing lint result. A stable file-level line number is sufficient. Do not claim a precise decoded line after the first invalid byte.

Do not use replacement decoding or a fallback encoding. Keep ordinary read errors distinct. This bounded contract does not add encoding checks to JSON conventions, trigger corpora, YAML sidecars, opaque package files, or every reader in the application.

## Acceptance and unresolved evidence

Implementation acceptance needs positive and negative fixtures for each contract. The positive controls need complete paths with commands, placeholders, globs, directories, identical definitions, comment-looking code, escaped controls, RTL text, joiners, and isolates. The negative controls need each selected defect and a healthy second file after a decoding failure. Nested Markdown must exercise the current file-relative base. A title-only reference conflict must fail.

A direct CLI probe found that a literal ESC in a missing resource path could appear again in the existing relative-link diagnostic. The selected control rule therefore also shares its rejected character set with the content diagnostic formatter. The regression test checks both the code-point finding and the absence of literal ESC in output. This is a bounded content-output rule, not a claim that every application diagnostic is sanitized.

No consumer-corpus defect rate was measured. That gap could change the ordering, especially for the generated-output ambiguity in resource paths. It does not require replacing the five before implementation. The first adoption run should inspect findings before widening any grammar or adding exemptions.

The maintainer inherits five bounded checks with no new executable installation or online lint-time dependency. Authors inherit earlier feedback about concrete files and bytes. A passing run remains structural evidence and does not replace a behavioral evaluation.
