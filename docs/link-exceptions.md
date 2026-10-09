# Allow links to files a template creates

The content check fails on any relative Markdown link whose target does not exist. That is wrong for one case. A skill can ship a template that the agent copies into a user's project, and the template can link to a file that exists only after the copy, such as a report the agent writes. A link-exceptions file lists those links so the content check accepts them.

Use a link-exceptions file only for that case. The file exempts only exact missing direct inline Markdown links. Every other content check stays on.

## Write the policy file

The file is version-1 JSON. Each key in `inline_link_exceptions` is a source file path relative to the skills directory. Each value is a nonempty list of unique link destinations, spelled exactly as they appear in that file's direct inline Markdown links.

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

Set `content_link_exceptions_file` in `.skill-ci.toml` to the path. A path in the file is relative to the file. `skill-ci lint`, `skill-ci check`, and the hook entries that run `skill-ci check --fast` all read that key. For one run, pass `--content-link-exceptions-file PATH`.

If every relative link resolves in the skills tree, leave out the key.
