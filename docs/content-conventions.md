# Add your repository's naming conventions to the content check

`check-skill-content.py` applies one rule to bold names. A bold kebab name on a line that contains the word "skill" must name a directory under `SKILLS_DIR`. Some repositories need more. A family of skills can share a name prefix, so that a bold `pattern-` name is always a skill reference even when the line never says "skill". A repository can also retire a path or a command and want every remaining mention reported. A conventions file declares both for your repository.

Without the file, the checker applies only the "skill" rule and reports no retired text.

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

`retired_text` maps retired text to the message the checker prints. The checker reports a `retired-text` finding on every line that contains the text, including lines inside code blocks, because a template in a code block gets copied too. Keys and messages must be nonempty strings.

`skill_prefixes` lists name prefixes. Each prefix is lowercase kebab case and ends with a hyphen. A prefix has two effects:

- A bold name that starts with the prefix always reads as a skill reference, so `**pattern-nope**` fails when `pattern-nope/` does not exist.
- On a line that contains the prefix without its hyphen, a bare bold name also resolves against the prefixed directory. With `pattern-`, the line "Apply the **retry** pattern from the skill list." passes when `pattern-retry/` exists.

The checker rejects the file with exit code 2 if it has unknown keys, a version other than 1, a value of the wrong type, an empty string, a prefix that does not end in a hyphen, a repeated prefix, or a repeated object key.

## Point the checks at the file

- For the checker directly, pass `--conventions-file PATH`.
- For local linting, set `CONTENT_CONVENTIONS_FILE` to the path, then run `mise run skill-lint`.
- For the reusable workflow, set the `content-conventions-file` input to the same path.

If your repository has no prefixed skill family and no retired text to report, leave out the option, the variable, and the input.

## Keep a local checker copy in sync

If your repository keeps its own copy of `tools/check-skill-content.py` for a pre-commit hook, copy it from the same skill-ci revision that your workflow pins, and pass the same `--conventions-file` in the hook. The workflow fails when the two copies differ.
