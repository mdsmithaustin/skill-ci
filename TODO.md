# TODO

Deliberate gaps, each with the reason it is open.


- `strict-frontmatter` is accepted by the reusable workflow and fails the job when set. agent-loop-runner's stricter allowed-keys policy (only `name` and `description` permitted) is not expressible without adding logic to `tools/check-skill-frontmatter.py`, and that file is kept verbatim from mds-pstack. Expressing it means either a flag added in mds-pstack first and re-copied here, or a separate small checker.

- `tools/test_check_skill_frontmatter.py` is the mds-pstack file minus one test, `test_shipped_inventory_and_corpus_pass`, which runs the checker over that repository's own `skills/` tree and trigger corpus. This repository has neither. Every other test is unchanged.

- The caller passes `skill-ci-ref` (default `main`) so the workflow can fetch its own tools and `runner.lock`. A reusable workflow cannot read the ref it was called at, so the caller states it twice. A tag replaces `main` in both places once this repository has one.

- Trigger-row harvesting from local Claude and Codex session history is not in this repository. The decision record says the user reviews the harvest before use; the tool that produces it has not been written.

- The mds-pstack checkers are copied, not shared. When mds-pstack moves to consuming this repository's workflow, its own copies and its `lint.yml` steps for them are deleted in the same change.

- `skill-run` and `skill-trigger` drive the CLIs through `tools/claude-project-only` and `tools/codex-project-only`. Those launchers exist because the runner invokes `claude -p` with no tool permissions and because both harnesses discover user-level skills from the operator's home directory, which would otherwise put all of them inside an isolated run. If either CLI changes how it scopes skills or grants tools, the launchers are the first thing to recheck.

- Outcome cases cannot grade a file the agent writes. On the `run-agent` path the agent's working directory is temporary and is discarded, and only `run-subagent` copies sidecar files into the run directory. Cases work around this by asking for the product inside tags and extracting it from `output.md`. Moving outcome runs to `run-subagent` would remove the workaround and is worth evaluating.
