# Edited-file grading proof

On 2026-10-04, the standard `skill-run` task completed one with-skill and one without-skill run on each provider. All four products passed the script oracle. This proves file-edit capture, patch reconstruction, and deterministic grading through the existing runner. It does not prove skill benefit. Both provider reports flagged the case as saturated and reported zero objective lift.

The runner pin was `80e49afd5ac6502d3bb2a877846a6f49003e588d`. The host was macOS with Claude Code 2.1.289 and Codex CLI 0.160.0. Claude used the `sonnet` alias, whose native trace identified `claude-sonnet-5-5`. Codex used `gpt-6.1-sol`. Each subject call had a 240-second timeout. No tuning or retry occurred. The manifest contains no judge assertions, both judge result files were empty, and no paid judge call occurred.

## What passed

Each run changed only `inputs/product.py`, replacing `sum(prices[:-1])` with `sum(prices)`. The oracle checked successful capture, matching baseline and patch hashes, the permitted path, reconstructed bytes, and unchanged unrelated function bytes. It executed empty, single-item, multi-item, negative-price, and fractional-price checks on the reconstructed file.

Both with-skill traces read the skill file. Both Codex traces executed the requested cart checks successfully. Claude's launcher permitted the edit but denied Python execution in both variants. Claude accurately reported that limitation. The oracle's later checks establish product correctness, not that Claude verified its own work.

Output went to the newly allocated default directory beside the checkout. Raw traces and run artifacts remain local outside the repository and skill packages. They are not part of the published skill.

## Reproduce the paid path

Run from this repository with authenticated Claude and Codex CLIs. This spends four subject calls. The writable Codex override applies only to this invocation.

```sh
EVALS_DIR=.github/fixtures/populated/evals \
AGENTS='claude codex' RUNS=1 TIMEOUT=240 CODEX_MODEL=gpt-6.1-sol \
CODEX_CMD="$SKILL_CI/tools/codex-project-only exec --json --skip-git-repo-check --sandbox workspace-write" \
  mise run skill-run .github/fixtures/populated/skills/project-editing
```

A zero task exit alone does not prove passing grades. Inspect both benchmark reports for objective scores, missing runs, and execution errors. The retained run had objective score 1.00 for each variant, no missing runs, and no execution errors on either provider.

The model-free oracle tests exercise known-good evidence and rejection of missing capture, forged hashes, unrelated writes, and a behaviorally incorrect patch. CI never executes the paid path.

## Fixture identity

- `.github/fixtures/populated/evals/project-editing/shared-benchmark.json` has SHA-256 `3e5427581089354b0a5ca878d62d06c3b29b070603b69f2811bd4bb91b8602ce`.
- `.github/fixtures/populated/evals/project-editing/inputs/product.py` has SHA-256 `d9e49bb99cfb54d23bea5d74772d9eb8b691719b725063d707c6fa9bffb6dca1`.
- `.github/fixtures/populated/evals/project-editing/oracles/check_written_product.py` has SHA-256 `6c227eecb8a00424b7374e666d8190781b4bbb06a48f56e222ba17685d918662`.
- `.github/fixtures/populated/skills/project-editing/SKILL.md` has SHA-256 `8753cc046fa6b3c1bde0249c0e0766531e8b1d039e291dc883c5c6517f6cc3e3`.
