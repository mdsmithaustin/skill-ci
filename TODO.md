# TODO

Deliberate gaps, each with the reason it is open.


- `strict-frontmatter` is accepted by the reusable workflow and fails the job when set. A stricter allowed-keys policy, permitting only `name` and `description`, needs a flag in `tools/check-skill-frontmatter.py` or a separate small checker.

- `tools/test_check_skill_frontmatter.py` tests the shared checker with fixtures. Consumer repositories must test their own shipped skill inventory and trigger corpus. This repository has neither.

- Existing callers may still pass `skill-ci-ref`. The reusable workflow accepts and ignores it while callers move to one full SHA on the reusable workflow line. Remove the legacy input after the adopted callers migrate.

- Trigger-row harvesting from local Claude and Codex session history is not in this repository. The decision record says the user reviews the harvest before use; the tool that produces it has not been written.

- Consumers may keep local copies of the checkers for pre-commit hooks, because a reusable workflow cannot run a local hook. The lint job's drift check requires those copies to match the shared versions. The pinned reusable workflow remains the CI enforcement boundary.

- `skill-run` and `skill-trigger` drive the CLIs through `tools/claude-project-only` and `tools/codex-project-only`. Since the runner pin to `80e49af`, the runner hides host skills and other host context itself in answer and trigger runs. `claude-project-only` is still needed, because the runner invokes `claude -p` with no tool permissions and the launcher grants `acceptEdits`. In answer and trigger runs its `--setting-sources project` repeats the runner's flag, which Claude Code 2.1.286 accepts. Judge runs get the runner's sealed `--safe-mode --disable-slash-commands` instead, and whether the launcher's flag adds anything there is untested. `codex-project-only` only moves HOME, which is now redundant. Removing it needs one Codex run through `CODEX_CMD` without it, which has not been done. If either CLI changes how it scopes skills or grants tools, the launchers are the first thing to recheck.

- The edited-file proof passed capture and deterministic grading on both providers. Claude's `acceptEdits` launcher permitted edits but denied the requested Python checks. The oracle verified the reconstructed product afterward. An agent-verification gate or broader command permissions would need a separate task and proof. The fixture proves plumbing, not skill benefit. See [the proof record](docs/research/edited-file-grading.md).

- Dependabot covers the GitHub Actions used by the workflow and the pinned PyYAML in `tools/requirements.txt`. It does not cover the behavioral runner, which `runner.lock` pins as a git commit that no ecosystem reads. Moving that pin stays a judgement call gated on the fork's own tests, so it needs a person or a scheduled check of the fork branch.

- skill-ci owns `tools/check-pii.py`. A consumer may keep a copy for its pre-commit hook. The workflow's drift check requires that copy to match the shared version, so a consumer re-copies it when it moves its pin.


- A harvest review sheet quotes real user prompts, and those quotes contain text shaped like markdown links and bold skill names. `check-skill-content.py` reads them as real links and fails. Nothing is broken while review sheets stay untracked, which is where they belong, but committing one needs the quoted text escaped or the sheet kept out of the skills tree.

- Consumers still need committed manifests to exercise their own validate and audit paths in CI. The job fails when `evals-dir` names a directory that does not exist. Set `require-manifests: true` to also reject an existing but empty search tree. Set `require-populated-manifests: true` to require populated, correctly bound manifests for every skill. Both defaults remain false for activation compatibility. Empty scaffolded manifests satisfy only the file-count requirement and skip readiness audit. This repository exercises an empty scaffold with a stale legacy input and a separate populated fixture through two reusable-workflow contract jobs.
