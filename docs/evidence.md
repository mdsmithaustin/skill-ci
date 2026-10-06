# What a passing check proves

Skill-ci has three implementation layers. A result can support one or more of the six evidence layers below. Report each claim separately, including `NOT RUN` or `UNKNOWN` when evidence is missing.

| Claim | Evidence | Limit |
| --- | --- | --- |
| Portable conformance | Named format rules and validator results at a recorded revision. | A parser accepting metadata does not prove that an installer or harness uses it. |
| Installer compatibility | A named installer version discovers, installs, and lists a package in an isolated target scope. | A file copy or package digest does not exercise an installer. |
| Static semantic quality | A review cites the instructions and explains how they affect an agent's decisions. | Keywords, headings, and length limits cannot establish useful instructions. |
| Native discovery and activation | A named harness lists the skill and records its load in a native trace. | Record catalog presence and activation separately. Neither establishes task success. |
| Behavioral utility | Matched with-skill and baseline runs use the same tasks, settings, tools, and environment, with outcome evidence and repeated grading. | A valid manifest, successful load, or plausible review does not establish improvement. |
| Deployment parity | The reviewed source and installed or evaluated copy have matching package inventories. | Matching copies can reproduce the same defects. |

The existing frontmatter and content lints cover their documented structural rules. Manifest validation checks case definitions, leakage, and readiness. The opt-in populated coverage check proves that every discovered skill has cases bound to its actual marker. It does not prove that those cases distinguish useful behavior. The external runner collects trigger and paired outcome evidence. A green model-free CI run does not mean those paid runs happened.

Prepared [fixed recovery cases](https://github.com/mdsmithaustin/skill-eval-harness/blob/70e83674f787327e3d271310fc64106dc89a2708/docs/recovery.md) collect raw process evidence and file snapshots in `recovery.json` and `recovery/`, instead of ordinary answer grades. A model-free run with fake processes can verify checkpoint-stop plumbing, fixture retention, and fresh process phases. It cannot establish live provider eligibility or model behavior. A missing forbidden file alone does not prove an enforcing denial. The consumer must establish the attempted write, enforcing denial, and absent forbidden file from the evidence.

The optional package check inventories files and compares copies. Its digest includes relative paths, file bytes, empty directories, and executable bits. It does not validate metadata, run an installer, load a skill, or grade an outcome. Compare quiescent trees. A read-only inventory is not an atomic filesystem snapshot.

## Author cases that can distinguish behavior

Keep evaluation definitions separate from executed results. A scaffold with cases and assertions is a test plan until a run and its evidence-backed grade exist.

For skills that audit, review, or repair, include a healthy control where the correct result is to keep the input unchanged or report no findings. Pair it with a concrete defect. An audit that criticizes every input must fail the healthy control.

Test positive, near-miss negative, and ambiguous trigger requests separately from outcome quality. Keep a held-out set when tuning a description. Preserve failures and repeat runs to expose variance. The [authoring conventions](authoring-cases.md) describe how to write cases in the existing manifest format.

Do not turn the optimizer's audit-focus categories into required coverage for every skill. Choose the cases that distinguish the particular skill's promised behavior, and use the pinned runner's readiness audit for its existing checks.

## Retain enough evidence to check a claim

Record the source revision or digest, compared package paths, model and harness versions, case set and split, relevant settings, run artifacts, grading evidence, and failures. Record duration and token cost when the claim concerns efficiency.

Scope an improvement claim to the tested skill, tasks, model, harness, and environment. Stronger causal claims may need an irrelevant-instruction control or component ablation. These controls must answer a concrete question about the claimed effect.

This guidance adapts [skill-optimizer ADR 0002](https://github.com/mdsmithaustin/skill-optimizer/blob/914629f842655865d712641448f1849fe9359527/docs/adr/0002-six-evidence-layers.md) and its [evaluation guide](https://github.com/mdsmithaustin/skill-optimizer/blob/914629f842655865d712641448f1849fe9359527/evals/README.md). The [harvest record](harvest-skill-optimizer.md) explains the selected imports.
