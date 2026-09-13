# Decisions

Why this repository is shaped the way it is. `README.md` covers how to use it. The evidence behind each decision is in `docs/AGENT-SKILL-TEST-FRAMEWORKS-RESEARCH.md` in the agent-loop-runner repository, which records the sources, the measured runs, and the checkpoint verdicts.

## Why this repository exists

Two skill repositories were testing skills separately and duplicating the work. mds-pstack had a frontmatter checker, a reference checker, and a trigger file that only asserted a description contained a phrase. agent-loop-runner had a stricter frontmatter validator, no reference checker, ninety-two behavioral trigger rows in an incompatible schema, and a bespoke runner that could not move. The duplication was two validators and two trigger formats. The part that felt like reinvention was neither.

One shared home fixes that. A skill repository gets its lints, its runner pin, and its task definitions from here, and owns only its cases.

## Why an external runner instead of our own

A capability census across `claude plugin eval`, skillroll, NVIDIA SkillEvaluator, skillgrade, and skill-eval-harness found that skill-eval-harness already held every behavioral capability the others held, plus four none of them held. The two capabilities no tool had, proof that a referenced file was read and a measure of instruction clarity, turned out to be a per-case assertion and a variance readout rather than harness features.

Building our own would have reproduced about twenty thousand lines to add two things. agent-loop-runner had already built one, and that runner is precisely what could not be shared.

## Why a fork, and when to leave it

`runner.lock` pins a fork rather than the upstream release. The fork carries four patches, all at the boundary where the runner meets something outside itself.

1. The judge prompt no longer reveals which arm it is grading.
2. Codex skill loads are read from the session rollout, because an explicit mention injects the skill with no tool event.
3. A skill mounts under its own directory name, which the Agent Skills format requires.
4. An agent CLI's own event stream parses leniently, because Codex repeats a key and the strict reader was discarding whole rows.

The original exit test counted patches. That measured the wrong thing, because driving two command line tools that ship weekly produces a steady trickle of adapter fixes. The test is now where a patch lands. A fix in the adapter edge is the ordinary cost of the dependency. A fix that has to change grading, aggregation, or the case model means the tool disagrees with us about evaluation, and that is when to leave. Four for four have been adapter edge.

## Where runs happen

Everything model-free runs in continuous integration on every pull request. That is the lints, manifest validation, the leakage check, and the readiness audit including judge independence.

Behavioral runs are operator-local and never a pull request gate. They drive the installed `claude` and `codex` binaries on the operator's own logins through the launchers in `tools/`, which exist because the runner grants a print-mode run no tool permissions and because both harnesses discover user-level skills from the operator's home directory. Without the launchers an isolated run would silently include every skill the operator has installed.

Cost is the reason this is not a gate. Fifty-two skills at twenty queries, three runs, and two harnesses is over six thousand command line invocations.

## What gets tested

Every skill gets outcome cases. Skills that a model may not invoke on its own are exercised by explicit invocation.

Only description-triggerable skills get the trigger matrix, which is nine of mds-pstack's fifty-two. The rest are gated from model invocation, so a description-driven trigger measurement would be meaningless for them.

Mode-to-skill routing is the primary trigger measurement, not bare description matching. A harvest of six thousand three hundred real prompts across both harnesses found that skills reach context through modes and plays, not through their descriptions. Harness-native description-driven loads were in single digits across the entire history. Measuring only bare descriptions would measure a path that is nearly unused. Bare description matching is kept as a secondary signal, because it is what a standalone install of a skill depends on.

## Where cases come from

Trigger rows are harvested from local session history with ground truth taken from whether the skill actually loaded, then reviewed by a person before use. Near-miss negatives are written by hand only where history has none. Harvested prompts are the least artificial corpus available and their labels are observed rather than asserted.

Outcome cases are the skill author's. The readiness audit refuses a paid run on a manifest without adversarial cases, which is the anti-theatre gate.

## Judges

A judge assertion carries gate severity, anchored dimensions, and repeats. The reasons are in `README.md` under the authoring conventions, and they were paid for by a measured run where the judge was the only assertion that discriminated while every deterministic gate sat at ceiling.

An external scoring framework, LLM-as-a-Verifier, was evaluated and declined. Its method needs token log probabilities, which the Claude Messages API does not expose at all. It improves score resolution, which the measured evidence says is not the limit. The limit is case discrimination and sample size. The harness already ships the calibration machinery that framework does not claim, including alignment against human labels, robustness probes with negative controls, panels with quorum, and repeated judging.

## Honest limits

Two things no tool measures directly, and we do not claim otherwise. Whether a harness understood a skill is inferred from paired lift. Whether a skill's instructions are clear is inferred from variance across repeated runs of one case. Both are proxies and should be described as proxies in any result.
