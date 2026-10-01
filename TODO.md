# TODO

Deliberate gaps, each with the reason it is open.


- `strict-frontmatter` is accepted by the reusable workflow and fails the job when set. agent-loop-runner's stricter allowed-keys policy (only `name` and `description` permitted) is not expressible without adding logic to `tools/check-skill-frontmatter.py`, and that file is kept verbatim from mds-pstack. Expressing it means either a flag added in mds-pstack first and re-copied here, or a separate small checker.

- `tools/test_check_skill_frontmatter.py` is the mds-pstack file minus one test, `test_shipped_inventory_and_corpus_pass`, which runs the checker over that repository's own `skills/` tree and trigger corpus. This repository has neither. Every other test is unchanged.

- Existing callers may still pass `skill-ci-ref`. The reusable workflow accepts and ignores it while callers move to one full SHA on the reusable workflow line. Remove the legacy input after the adopted callers migrate.

- Trigger-row harvesting from local Claude and Codex session history is not in this repository. The decision record says the user reviews the harvest before use; the tool that produces it has not been written.

- The mds-pstack checkers are copied, not shared, and that is the settled shape rather than a transition. mds-pstack consumes this repository's reusable workflow at a pinned SHA and its `lint.yml` no longer runs the three checkers, but its `tools/` copies stay, because a reusable workflow cannot run a pre-commit hook. The lint job's drift check is what keeps a copy honest. Measured on 2026-09-13 against mds-pstack's `.github/workflows/skill-checks.yml` and `lint.yml`.

- `skill-run` and `skill-trigger` drive the CLIs through `tools/claude-project-only` and `tools/codex-project-only`. Since the runner pin to `80e49af`, the runner hides host skills and other host context itself in answer and trigger runs. `claude-project-only` is still needed, because the runner invokes `claude -p` with no tool permissions and the launcher grants `acceptEdits`. In answer and trigger runs its `--setting-sources project` repeats the runner's flag, which Claude Code 2.1.286 accepts. Judge runs get the runner's sealed `--safe-mode --disable-slash-commands` instead, and whether the launcher's flag adds anything there is untested. `codex-project-only` only moves HOME, which is now redundant. Removing it needs one Codex run through `CODEX_CMD` without it, which has not been done. If either CLI changes how it scopes skills or grants tools, the launchers are the first thing to recheck.

- No outcome case grades a file the agent writes yet. Since the runner pin of 2026-09-27, `run-agent` saves the agent's edits in the run directory as `workspace-changes.json`, `candidate.patch`, and `candidate-files/`, and a script oracle can read them through `{output_dir}`. Cases still ask for the product inside tags and extract it from `output.md`. Grading from `candidate.patch` would remove that workaround and needs one paid run to prove. Codex runs would also need a writable sandbox in `CODEX_CMD`, because the default is read-only.

- Dependabot covers the GitHub Actions used by the workflow and the pinned PyYAML in `tools/requirements.txt`. It does not cover the behavioral runner, which `runner.lock` pins as a git commit that no ecosystem reads. Moving that pin stays a judgement call gated on the fork's own tests, so it needs a person or a scheduled check of the fork branch.

- `tools/check-pii.py` is a fourth verbatim copy from mds-pstack. It shares the settled shape of the other checkers, a consumer copy kept for the pre-commit hook and held to the shared version by the drift check.


- A harvest review sheet quotes real user prompts, and those quotes contain text shaped like markdown links and bold skill names. `check-skill-content.py` reads them as real links and fails. Nothing is broken while review sheets stay untracked, which is where they belong, but committing one needs the quoted text escaped or the sheet kept out of the skills tree. Measured on three sheets under mds-pstack on 2026-09-13.

- Consumers still need committed manifests to exercise their own validate and audit paths in CI. The job fails when `evals-dir` names a directory that does not exist. Set `require-manifests: true` to also reject an existing but empty search tree. Its default remains false for activation compatibility. Empty scaffolded manifests satisfy the inventory requirement and skip readiness audit. This repository's reusable-workflow contract job exercises one fixture skill and one empty manifest with a stale legacy input.

- `skill-trigger` and `skill-run` still write run output under the skill directory, at `<skill>/eval-runs/`, in both manifest layouts. It is gitignored, so it never reaches a consumer through the repository, but a skill installer copying a working tree would pick it up. Moving the default output beside the manifest is the obvious fix and has not been done.
