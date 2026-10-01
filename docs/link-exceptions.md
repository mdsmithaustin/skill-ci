# Allow links to files a template creates

`check-skill-content.py` fails on any relative Markdown link whose target does not exist. That is wrong for one case. A skill can ship a template that the agent copies into a user's project, and the template can link to a file that exists only after the copy, such as a report the agent writes. A link-exceptions file lists those links so the checker accepts them.

Use a link-exceptions file only for that case. Every other content check stays on. The file cannot exempt images, reference-style link definitions, paths in inline code, sibling skill names, fences, or retired text from a conventions file.

## Write the policy file

The file is version-1 JSON. Each key in `inline_link_exceptions` is a source file path relative to `SKILLS_DIR`. Each value is a nonempty list of unique link destinations, spelled exactly as they appear in that file's direct inline Markdown links.

```json
{
  "version": 1,
  "inline_link_exceptions": {
    "example-skill/assets/report.template.md": [
      "../REPORT-[TOPIC].md"
    ]
  }
}
```

The match is exact. The entry above does not allow `<../REPORT-[TOPIC].md>`, and it does not allow the same destination in a different source file.

## Point the checks at the file

- For the checker directly, pass `--link-exceptions-file PATH`.
- For local linting, set `CONTENT_LINK_EXCEPTIONS_FILE` to the path, then run `mise run skill-lint`.
- For the reusable workflow, set the `content-link-exceptions-file` input to the same path.

If every relative link resolves in the skills tree, leave out the option, the variable, and the input.

## Keep a local checker copy in sync

If your repository keeps its own copy of `tools/check-skill-content.py` for a pre-commit hook, copy it from the same skill-ci revision that your workflow pins. The workflow fails when the two copies differ.
