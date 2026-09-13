# TODO

Deliberate gaps, each with the reason it is open.

- `runner.lock` says `PIN_ME`. The real commit SHA lands after the fork's two patches (blind judge payload, Codex rollout-file skill-load detection) merge at github.com/mdsmithaustin/skill-eval-harness. Until then the `manifests` job's install step fails on purpose.

- `strict-frontmatter` is accepted by the reusable workflow and fails the job when set. agent-loop-runner's stricter allowed-keys policy (only `name` and `description` permitted) is not expressible without adding logic to `tools/check-skill-frontmatter.py`, and that file is kept verbatim from mds-pstack. Expressing it means either a flag added in mds-pstack first and re-copied here, or a separate small checker.

- `tools/test_check_skill_frontmatter.py` is the mds-pstack file minus one test, `test_shipped_inventory_and_corpus_pass`, which runs the checker over that repository's own `skills/` tree and trigger corpus. This repository has neither. Every other test is unchanged.

- The caller passes `skill-ci-ref` (default `main`) so the workflow can fetch its own tools and `runner.lock`. A reusable workflow cannot read the ref it was called at, so the caller states it twice. A tag replaces `main` in both places once this repository has one.

- Trigger-row harvesting from local Claude and Codex session history is not in this repository. The decision record says the user reviews the harvest before use; the tool that produces it has not been written.

- The mds-pstack checkers are copied, not shared. When mds-pstack moves to consuming this repository's workflow, its own copies and its `lint.yml` steps for them are deleted in the same change.
