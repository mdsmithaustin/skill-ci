---
name: skill-ci
description: Set up Agent Skill testing in the current repository. Use when the user says "activate skill-ci", "set up skill testing", "add skill evals to this repo", "add skill lints", or asks how the skills in this repo get tested. Runs `skill-ci init`, which writes the version pin, the CI workflow, hook entries, and one empty manifest per skill, then reports what it wrote and stops.
---

# skill-ci

Activation is `skill-ci init`, then `skill-ci check`, and a report of what they printed. `init` writes configuration and empty manifests. Activation never runs a paid model step, never writes a test case, never commits, and never pushes. The person runs `skill-ci trigger` and `skill-ci run` by hand, on their own logins, when they choose.

## Before you start

- Work at the repository root. `init` refuses to run anywhere else, and it refuses a directory that is in no git repository.
- The skills directory is the one whose children each hold a `SKILL.md`. It defaults to `skills`. If the repository keeps its skills elsewhere, pass `--skills-dir`. If there is no such directory, `init` stops and says so.
- `uv` and `git` must be on `PATH`, and the machine needs network access to the skill-ci source, because `init` pins the newest release tag.
- If `skill-ci` is not on `PATH`, run it through uv. Replace `skill-ci` with the command below in every step:

  ```sh
  uv tool run --from git+https://github.com/mdsmithaustin/skill-ci.git skill-ci
  ```

## Steps

1. Run `skill-ci init`. It lists the files it wrote, updated, and kept, plus notes and to-do items. Run it again at any point. It keeps what exists.
2. Run `skill-ci check`. Fix only what `init` introduced. A finding inside an existing skill belongs to its author. List it in the report and leave it.
3. Stop. Report the lines `init` printed, the `check` result, and the manifest count. Quote every `to do:` item and every `note:` line, such as the no-mistakes setting.

## Rules

- If `init` says the source has no release tag, report that and stop. Do not write a `main` pin for the person. That pin follows the branch head instead of a release, so it is theirs to choose.
- A `to do:` line means `init` could not finish that step. When there is an entry to add by hand, the line prints it. Report the line, and do not guess at an edit.
- Never edit the checks during activation. A checker defect gets its own change in the skill-ci repository.
- The version lives in `.skill-ci.toml` only. `skill-ci update` moves it to the newest tag. Do not write a version anywhere else.
- `README.md` in the skill-ci repository owns the overview and the `.skill-ci.toml` reference. `docs/authoring-cases.md` owns the authoring conventions. Point authors there instead of restating them.
- `DECISIONS.md` owns the rationale, including why the runner is a pinned fork and the test for when to stop using it. Point a reader there rather than explaining it in a run report.
