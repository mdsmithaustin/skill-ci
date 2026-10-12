# Add your repository's naming conventions to the content check

The content check applies one rule to bold names. A bold kebab name on a line that contains the word "skill" must name a directory under the skills directory. Some repositories need more. A family of skills can share a name prefix, so that a bold `pattern-` name is always a skill reference even when the line never says "skill". A repository can also retire a path or a command and want every remaining mention reported. A conventions file declares both for your repository.

Without the file, bold-name matching uses only the "skill" hint and reports no retired text. The other content checks still run.

## Write the conventions file

The file is version-1 JSON. Both keys after `version` are optional.

```json
{
  "version": 1,
  "retired_text": {
    "/old-command": "use the new-command skill instead of the retired command"
  },
  "skill_prefixes": ["pattern-"]
}
```

`retired_text` maps retired text to the message the content check prints. The content check reports a `retired-text` finding on every line that contains the text, including lines inside code blocks, because a template in a code block gets copied too. Keys and messages must be nonempty strings.

`skill_prefixes` lists name prefixes. Each prefix is lowercase kebab case and ends with a hyphen. A prefix has two effects:

- A bold name that starts with the prefix always reads as a skill reference, so `**pattern-nope**` fails when `pattern-nope/` does not exist.
- On a line that contains the prefix without its hyphen, a bare bold name also resolves against the prefixed directory. With `pattern-`, the line "Apply the **retry** pattern from the skill list." passes when `pattern-retry/` exists.

The content check rejects the file with exit code 2 if it has unknown keys, a version other than 1, a value of the wrong type, an empty string, a prefix that does not end in a hyphen, a repeated prefix, or a repeated object key.

## Point the checks at the file

Set `content_conventions_file` in `.skill-ci.toml` to the path. A path in the file is relative to the file. `skill-ci lint`, `skill-ci check`, and the hook entries that run `skill-ci check --fast` all read that key, so CI, hooks, and your terminal apply the same conventions. For one run, pass `--content-conventions-file PATH`.

If your repository has no prefixed skill family and no retired text to report, leave out the key.
