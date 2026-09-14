# Harvest from skill-optimizer

The source review covered [skill-optimizer at `914629f`](https://github.com/mdsmithaustin/skill-optimizer/tree/914629f842655865d712641448f1849fe9359527). Skill-ci keeps its shared lints, activation contract, manifest convention, and pinned external runner.

## Adopted capabilities

| Source | Adaptation in skill-ci | Why |
| --- | --- | --- |
| [`inspect_regular_tree`, `tree_digest`, and `compare_installed`](https://github.com/mdsmithaustin/skill-optimizer/blob/914629f842655865d712641448f1849fe9359527/tools/check_repo.py) | A separate [package checker](../tools/check-skill-package.py), local task, and opt-in CI check. | Detect unsafe package entries and differences between reviewed source and installed copies. |
| [Package regression tests](https://github.com/mdsmithaustin/skill-optimizer/blob/914629f842655865d712641448f1849fe9359527/tests/test_repo.py) | [Temporary package fixtures and CLI tests](../tools/test_check_skill_package.py). | Exercise healthy copies and defects through the command users run. |
| [Nonempty evaluation-definition checks](https://github.com/mdsmithaustin/skill-optimizer/blob/914629f842655865d712641448f1849fe9359527/evals/validate_evals.py) | The reusable workflow's `require-manifests` input, covered by [workflow integration tests](../tools/test_workflow_integration.py). | Let a consumer reject CI runs that examine zero manifests while preserving empty scaffolds. |
| [Repository test workflow](https://github.com/mdsmithaustin/skill-optimizer/blob/914629f842655865d712641448f1849fe9359527/.github/workflows/test.yml) | [A pinned workflow](../.github/workflows/test.yml) that runs `mise run test` on Linux and macOS. | Enforce the existing unit-test task in CI as well as local hooks. |
| [Six evidence layers](https://github.com/mdsmithaustin/skill-optimizer/blob/914629f842655865d712641448f1849fe9359527/docs/adr/0002-six-evidence-layers.md) and [evaluation guidance](https://github.com/mdsmithaustin/skill-optimizer/blob/914629f842655865d712641448f1849fe9359527/evals/README.md) | [Evidence guidance](evidence.md), including healthy controls for review and repair skills. | Keep validation, installation, activation, observed utility, and copy identity as separate claims. |

## Changes to the donor's package design

The new checker is read-only and accepts explicit single-package or collection selection. Copy comparison always takes the installed skills parent directory. Each selected source maps to its own basename below that parent.

The inventory includes empty directories and exact executable permission bits as well as file paths and bytes. The donor's digest omitted directories and permissions. Symlink roots are checked before path resolution. All file content is opaque, so native metadata extensions do not acquire a new validation policy.

The command owns one in-memory inventory and derives both its digest and path-level differences from it. A separate serialized-inventory format would add storage, freshness, and schema coordination without a current consumer. Automatic selection based on whether `SKILL.md` exists was rejected because a missing marker would change which directories the command inspected.

Both new reusable workflow inputs default to false. Consumers can adopt package inspection or require manifests independently. The existing copied checker files and their drift checks retain their current contracts.

## Left with their existing owners

| Candidate | Reason |
| --- | --- |
| The donor's full frontmatter, reference, and OpenAI-sidecar validator. | The recipient already validates metadata and invocation policy. The donor requires UI fields and portable-only keys that conflict with valid recipient packages. |
| Bare resource paths in code spans. | This is useful follow-up work for the shared parser-based content checker. The donor's regex uses different path rules and would misread examples if copied directly. The shared checker must be updated and synchronized with its consumers. |
| The donor's eval JSON schema, audit-focus taxonomy, and optimizer-specific fixtures. | The external runner already owns manifest validation and readiness. The donor cases judge the optimizer's semantic audits, not general skill infrastructure. |
| The live `npx skills` installer probe. | It hard-codes the donor name, installer identity, target, and listing expectations. Generalizing it adds Node and registry dependencies. The package check makes no installer claim. |
| The `install_to` helper. | It removes an existing destination before copying. Offline comparison needs no installation or replacement operation. |
| The semantic optimizer skill, full rubric, runtime matrix, research, and historical audit logs. | These remain in the repository that maintains semantic review and runtime research. The evidence guide links the source rather than duplicating that material. |

The [package guide](packages.md) documents commands and limits. No import here replaces a behavioral run or establishes skill quality from file structure alone.
