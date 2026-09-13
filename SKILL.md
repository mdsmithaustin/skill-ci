---
name: skill-ci
description: Set up Agent Skill testing in the current repository. Use when the user says "activate skill-ci", "set up skill testing", "add skill evals to this repo", "add skill lints", or asks how the skills in this repo get tested. Wires the reusable lint workflow, the mise tasks, the pinned skill-eval-harness runner, and one empty manifest per skill, then stops.
---

# skill-ci

Activation wires one target repository into the shared skill testing home. It writes configuration and empty manifests and then stops. Activation never runs a paid model step. It never writes a test case, never commits, and never pushes. The person runs `skill-trigger` and `skill-run` by hand, on their own logins, when they choose.

## Before you start

- `SKILL_CI` is the absolute path of the directory holding this file. Every command below uses it.
- `SKILLS_DIR` is the target's skills directory: the one whose children each hold a `SKILL.md`. Default `skills`. If the target has no such directory, stop and say so.
- Read `$SKILL_CI/runner.lock`. Its last line is the runner spec. If the spec ends in `PIN_ME`, the fork has no pin yet. Step 3 reports that instead of installing.

## Steps

1. Workflow. Write `.github/workflows/skill-checks.yml` in the target, or add the `skills` job to an existing lint workflow. Reference the reusable workflow; do not copy its body.

   ```yaml
   name: skill-checks
   on:
     push:
       branches: [main]
     pull_request:
   permissions:
     contents: read
   jobs:
     skills:
       uses: mdsmithaustin/skill-ci/.github/workflows/skill-checks.yml@main
       with:
         skills-dir: skills
         skill-ci-ref: main
   ```

   Set `skills-dir` to `SKILLS_DIR`. Replace `main` in both places with the same tag or SHA once one exists.

2. mise tasks. In the target's `mise.toml` (create it if absent) add the env and the include. If `task_config.includes` already exists, append to it.

   ```toml
   [env]
   SKILL_CI = "{{ config_root }}/../skill-ci"

   [task_config]
   includes = ["../skill-ci/skill-tasks.toml"]
   ```

   Use the real relative path from the target to this checkout. Confirm with `mise tasks ls` that `skill-lint`, `skill-validate`, `skill-audit`, `skill-trigger`, and `skill-run` are listed.

3. Runner. Install the pinned runner:

   ```sh
   uv tool install "$(grep -v '^#' "$SKILL_CI/runner.lock" | grep -v '^[[:space:]]*$')"
   ```

   When the spec ends in `PIN_ME`, skip this and say so in the report. Never install from an unpinned ref or from upstream.

4. Manifests. Scaffold one empty manifest beside each skill:

   ```sh
   uv run --no-project --with-requirements "$SKILL_CI/tools/requirements.txt" \
     python "$SKILL_CI/tools/scaffold_manifest.py" "$SKILLS_DIR"/*/
   ```

   This writes `evals/shared-benchmark.json` with an empty `cases` list and refuses to touch a manifest that already exists. Leave `cases` empty. Trigger rows come from the reviewed session harvest. Outcome cases are the skill author's.

5. Check. Run `mise run skill-lint`, and `mise run skill-validate` when the runner is installed. Fix only what activation introduced. A lint finding inside an existing skill belongs to its author: list it in the report and leave it.

6. Stop. Report the files written, the tasks listed, the runner state (installed at which spec, or unpinned), the manifest count, and any findings.

## Rules

- Never edit `tools/check-skill-frontmatter.py` or `tools/check-skill-content.py` during activation. A checker defect gets its own change in this repository.
- Re-activation is safe. Every step converges: existing workflow jobs, includes, and manifests are kept, not rewritten.
- The pin lives in `runner.lock` only. Do not write the runner version anywhere else.
- `README.md` in this checkout owns the three-layer shape and the authoring conventions. Point authors there instead of restating them.
- `DECISIONS.md` owns the rationale, including why the runner is a pinned fork and the test for when to stop using it. Point a reader there rather than explaining it in a run report.
