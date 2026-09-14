# TODO

Deliberate gaps, each with the reason it is open.


- `strict-frontmatter` is accepted by the reusable workflow and fails the job when set. agent-loop-runner's stricter allowed-keys policy (only `name` and `description` permitted) is not expressible without adding logic to `tools/check-skill-frontmatter.py`, and that file is kept verbatim from mds-pstack. Expressing it means either a flag added in mds-pstack first and re-copied here, or a separate small checker.

- `tools/test_check_skill_frontmatter.py` is the mds-pstack file minus one test, `test_shipped_inventory_and_corpus_pass`, which runs the checker over that repository's own `skills/` tree and trigger corpus. This repository has neither. Every other test is unchanged.

- The caller passes `skill-ci-ref` (default `main`) so the workflow can fetch its own tools and `runner.lock`. A reusable workflow cannot read the ref it was called at, so the caller states it twice. A tag replaces `main` in both places once this repository has one.

- Trigger-row harvesting from local Claude and Codex session history is not in this repository. The decision record says the user reviews the harvest before use; the tool that produces it has not been written.

- The mds-pstack checkers are copied, not shared, and that is the settled shape rather than a transition. mds-pstack consumes this repository's reusable workflow at a pinned SHA and its `lint.yml` no longer runs the three checkers, but its `tools/` copies stay, because a reusable workflow cannot run a pre-commit hook. The lint job's drift check is what keeps a copy honest. Measured on 2026-09-13 against mds-pstack's `.github/workflows/skill-checks.yml` and `lint.yml`.

- `skill-run` and `skill-trigger` drive the CLIs through `tools/claude-project-only` and `tools/codex-project-only`. Those launchers exist because the runner invokes `claude -p` with no tool permissions and because both harnesses discover user-level skills from the operator's home directory, which would otherwise put all of them inside an isolated run. If either CLI changes how it scopes skills or grants tools, the launchers are the first thing to recheck.

- Outcome cases cannot grade a file the agent writes. On the `run-agent` path the agent's working directory is temporary and is discarded, and only `run-subagent` copies sidecar files into the run directory. Cases work around this by asking for the product inside tags and extracting it from `output.md`. Moving outcome runs to `run-subagent` would remove the workaround and is worth evaluating.

- Dependabot covers the GitHub Actions used by the workflow and the pinned PyYAML in `tools/requirements.txt`. It does not cover the behavioral runner, which `runner.lock` pins as a git commit that no ecosystem reads. Moving that pin stays a judgement call gated on the fork's own tests, so it needs a person or a scheduled check of the fork branch.

- `tools/check-pii.py` is a fourth verbatim copy from mds-pstack. It shares the settled shape of the other checkers, a consumer copy kept for the pre-commit hook and held to the shared version by the drift check.


- A harvest review sheet quotes real user prompts, and those quotes contain text shaped like markdown links and bold skill names. `check-skill-content.py` reads them as real links and fails. Nothing is broken while review sheets stay untracked, which is where they belong, but committing one needs the quoted text escaped or the sheet kept out of the skills tree. Measured on three sheets under mds-pstack on 2026-09-13.

- The reusable workflow ran green end to end for the first time on 2026-09-13, against mdsmithaustin/pstack pull request 40. The lint job executed the PII, frontmatter, and content checkers over 52 skills. The manifests job installed the pinned runner and then reported `manifests checked: 0`, because pstack's only manifest is still untracked. So the validate and audit half of the workflow has started successfully but has never examined a real manifest. Committing one manifest is what proves that half, and the `evals-dir` layout is what makes committing one cheap, because a manifest under `evals/<skill>/` no longer ships to everyone who installs the skill. The job now fails when `evals-dir` names a directory that does not exist, which closes one route to a vacuous zero. An existing but empty directory still reports `manifests checked: 0` and passes, and so does a caller that leaves `evals-dir` unset.

- `skill-trigger` and `skill-run` still write run output under the skill directory, at `<skill>/eval-runs/`, in both manifest layouts. It is gitignored, so it never reaches a consumer through the repository, but a skill installer copying a working tree would pick it up. Moving the default output beside the manifest is the obvious fix and has not been done.
