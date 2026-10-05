# Decisions

Why this repository is shaped the way it is. `README.md` covers how to use it. The evidence behind each decision is in `docs/AGENT-SKILL-TEST-FRAMEWORKS-RESEARCH.md` in the agent-loop-runner repository, which records the sources, the measured runs, and the checkpoint verdicts.

## Why this repository exists

Two skill repositories were testing skills separately and duplicating the work. One had a frontmatter checker, a reference checker, and a trigger file that only asserted a description contained a phrase. The other had a stricter frontmatter validator, no reference checker, ninety-two behavioral trigger rows in an incompatible schema, and a bespoke runner that could not move. The duplication was two validators and two trigger formats.

One shared home fixes that. A skill repository gets its lints, its runner pin, and its task definitions from here, and owns only its cases.

## Why an external runner instead of our own

A capability census across `claude plugin eval`, skillroll, NVIDIA SkillEvaluator, skillgrade, and skill-eval-harness found that skill-eval-harness already held every behavioral capability the others held, plus four none of them held. The two capabilities no tool had, proof that a referenced file was read and a measure of instruction clarity, turned out to be a per-case assertion and a variance readout rather than harness features.

Building our own would have reproduced about twenty thousand lines to add two things. agent-loop-runner had already built one, and that runner is precisely what could not be shared.

## Why a fork, and when to leave it

`runner.lock` pins a fork rather than the upstream release. At the `80e49af` pin, the fork carried the twenty patches listed below. Patches 1 to 8 were classified on 2026-09-27. Patches 9 to 20 arrived with that pin and name the fork pull request each came from. Fork #11 and #13 changed only tests and docs, so they are not patches. The `6634de1` pin also includes fork #20, classified below on 2026-10-04.

1. The judge prompt no longer reveals which arm it is grading.
2. Codex skill loads are read from the session rollout, because an explicit mention injects the skill with no tool event.
3. A skill mounts under its own directory name, which the Agent Skills format requires.
4. An agent CLI's own event stream parses leniently, because Codex repeats a key and the strict reader was discarding whole rows.
5. A manifest under `evals/<skill>/` resolves to the repository above it, so a manifest can sit outside the tree a skill installer copies.
6. A Codex `file_change` event counts as a file write, because Codex reports edits under a type name the generic reader did not recognize.
7. An answer run saves the agent's file edits before the runner deletes its temporary workspace. Scoring does not read them.
8. The answer prompt and arm instructions no longer tell the answering agent it is being graded or call its skill "the skill under test".
9. A trace event's provider type name is matched by whole word, so Codex's `thread.started` no longer reads as a file read (fork #6).
10. A Jetty task file carries only the instruction, prompt, and file lists, and every arm uploads under an opaque name (fork #7).
11. `run-subagent`'s default backend runs in the prepared workspace and reports only numeric usage (fork #8).
12. Answer runs hide the operator's host skills, agents, instructions, and MCP servers, and the `without_skill` instruction no longer mentions a skill (fork #9).
13. An instruction-simulated ablation arm is told what to ignore, but not which regression to expect, and its directive drops the word "ablation" (fork #10).
14. `run-subagent` saves the agent's file edits before deleting its workspace, as `run-agent` already did (fork #12).
15. Trigger runs hide the operator's host skills, agents, instructions, and MCP servers (fork #14).
16. A trigger run detects a Claude skill by its mount folder name, which is the name Claude Code lists and invokes (fork #15).
17. `judge_task_id` accepts the runner's own `RunNumber`, so `token-overhead` no longer crashes on a judge assertion (fork #16).
18. A `tool_sequence` assertion scores a run's whole tool trajectory against a reference list (fork #18).
19. `judge-alignment` reports judge score calibration (fork #17).
20. Answer and subagent runs use the trigger runs' isolation flags plus `"autoMemoryEnabled":false`, so skills and agents mounted in the workspace stay visible while host context stays hidden. Judges keep patch 12's sealed flags. Codex answer runs redact host skill paths in the saved command and stderr (fork #19).

The original exit test counted patches. That measured the wrong thing, because driving two command line tools that ship weekly produces a steady trickle of adapter fixes. The test is now where a patch lands, and a patch lands in one of four places.

- A fix at the adapter edge is the ordinary cost of the dependency.
- A fix that applies one of the tool's own evaluation rules to a path that missed it is a bug fix in the tool. The rule must exist in the tool's code or docs before the patch, and the classification must cite it by symbol.
- Any other fix that changes grading, aggregation, the case model, or prompt design means the tool disagrees with us about evaluation. That is when to leave.
- An opt-in addition, such as a new assertion type or report, is not the third kind when it changes no existing grading, aggregation, or case meaning. A manifest that does not use it grades exactly as before. The operator added this kind on 2026-10-01.

Patches 2 to 7 are adapter edge. Patch 1 is a bug fix. Before it, the runner already hid the arm from the model in blind A/B comparison (`compare-tasks`, keyed by `blind_nonce`). Patch 1 applies that rule to the judge that grades a single run, and adds `blind_judge_payload_text` to do it.

Patch 8 has two parts.

- **Arm instructions.** `old_skill` said it was the "old/baseline version". The runner already gives a blind ablation arm the `with_skill` instruction (`Arm(..., blind=True)`) so that it cannot tell which arm it is in. Giving `old_skill` the same instruction applies that rule, so this part is a bug fix.
- **Grading words.** The answer prompt dropped "hidden answer keys" and Eval vocabulary, `with_skill` stopped calling its skill "the skill under test", and a new test bans those words. The runner had no rule against telling the answering agent it is graded. This part is the third kind, and it is the first patch of that kind.

It moves `instruction_sha256` for the `with_skill`, `old_skill`, and blind ablation arms.

The test fired on 2026-09-27. The decision was to stay on the fork and keep the grading-words rule as a permanent fork difference. It changes only the wording of text the answering agent sees, not case text, grading, or aggregation. It moves the runner toward a subject that does not know it is tested. The other seven patches show no wider disagreement. Offering it upstream was set aside. Leaving the fork would cost more than keeping one known difference.

The fork now carries one accepted difference in evaluation. It does not count toward the test again.

Patches 9 to 20 were classified on 2026-10-01.

- **Adapter edge.** Patches 9, 11, 14, 15, and 16, and the isolation flags in patches 12 and 20. Patch 20 replaced patch 12's answer-run flags.
- **Bug fix.** Three parts apply a rule the runner already had. Patch 17 lets `judge_task_id` accept `RunNumber` (`manifest_contracts.py`), the runner's run-identity type, which already rejects booleans and non-positive values. The `old_skill` part of patch 10 gives that arm the opaque upload name that `Arm.upload_token()` (`ablation_model.py`) already gave a blind ablation arm. The word part of patch 13 applies `SubjectVisiblePromptTests._BANNED_RE`, which already banned `ablat\w*` from text the answering agent sees. That rule came from patch 8, so this part extends the fork's own accepted difference.
- **Opt-in addition.** Patches 18 and 19. Patch 18 adds the `tool_sequence` assertion and patch 19 adds judge calibration to `judge-alignment`. Neither changes how an existing assertion grades, so both fall under the opt-in kind and do not count toward the test.
- **Third kind.** The model-visible blinding in patches 10, 12, and 13. That is the arm and case names hidden from the Jetty task file, the `without_skill` instruction that no longer mentions a skill, and the expected regression hidden from an ablation arm.

On 2026-10-01 the operator decided that the blinding in patches 10, 12, and 13 is part of the accepted difference, widened from patch 8's grading words to one principle. The answering agent should not know it is being tested or which arm it is in. Those patches do not count toward the test. The next patch of the third kind that falls outside that principle reopens this decision.

Fork [#20](https://github.com/mdsmithaustin/skill-eval-harness/pull/20) was classified on 2026-10-04 under the same exit test.

- **Opt-in additions.** `benchmark_gate` adds an explicit saved-report exit gate. Rendering remains the default, and the gate changes no grading or aggregation. `SkillTriggerConstraints` adds expected and forbidden catalog identities only when a case declares them. Cases that omit both lists retain the any-mounted-skill rule. The captured-edit example supplies its own manifest, script oracle, and fixtures. Its separate permission smoke requires `--live --permission-edit`. Neither changes existing cases or default permissions.
- **Adapter edge.** Provider load-name attribution, selected-root path matching, and rejection of incomplete or failed native operations correct how adapter evidence identifies a loaded skill. `detect_trigger_records` already required completed operations through `trace_contracts.event_is_completed`; the new checks also reject error and unsuccessful exit evidence. These corrections can change activation observations, so both trigger comparison arms must be regenerated with the new pin.

These changes fit the existing opt-in and adapter categories. They do not add another accepted difference in evaluation or reopen the exit decision.

Leaving stays cheap to assess. The upstream `adewale/skill-eval-harness` revision assessed on 2026-10-01, `2297000`, remains an ancestor of the `6634de1` pin. Verified on 2026-10-04 with `git merge-base --is-ancestor`. The fork remains a superset of that assessed revision.

## Why execution derives from the lock

`runner.lock` records the runner commit once. `tools/run_runner.py` validates that one specification each time a local task or reusable workflow runs. It starts Python in uv's isolated tool environment and executes the runner from that environment's scripts directory. uv can otherwise fall back to a same-named command on `PATH` when a source does not provide an entrypoint.

The reusable workflow checks out the revision that GitHub selected for that workflow through `job.workflow_repository` and `job.workflow_sha`. A caller therefore records one full SHA in its `uses` line. The deprecated `skill-ci-ref` input remains accepted for callers that have not removed it, but it cannot change the checkout. Dependabot can update the remote reusable-workflow reference through its `github-actions` ecosystem without a cross-repository credential.

GitHub documents the [called workflow identity](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#job-context) and [automatic reusable-workflow updates](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/auto-update-actions).

## Where manifests live

A manifest belongs outside the skills tree, at `evals/<skill>/shared-benchmark.json`, with `skill_paths` relative to the repository root. The reason is what a skill installer does. `npx skills` copies a skill directory verbatim to every consumer, in both copy and symlink mode, and it has no ignore or exclude mechanism. A manifest at `<skills-dir>/<skill>/evals/shared-benchmark.json` therefore hands every consumer of that skill its trigger queries, its expected answers, and its oracle scripts. Measured on 2026-09-13 by installing a fixture skill with an `evals/` tree and reading a planted transcript back from the installed path.

The old layout still resolves, because the runner's rule for the repository root runs the existing case first. The reusable workflow's `evals-dir` input and the `EVALS_DIR` variable the mise tasks read select the tree to search, and both default to the skills tree. The choice is one or the other for a whole repository, because each search reads a single tree. A repository that starts moving manifests moves all of them in the same change; the ones left behind stop being checked. The runner also resolves `evals/shared-benchmark.json` with no skill segment, which suits a repository holding one skill, but the scaffold does not write that shape.

The cost is that a manifest and its skill no longer share a directory, so nothing keeps them in step automatically. Case files, `prompt_ref`, and script-oracle paths resolve against the manifest's own directory in both layouts, which is the trap worth knowing when a manifest moves.

## Where runs happen

Everything model-free runs in continuous integration on every pull request. That is the lints, manifest validation, the leakage check, and the readiness audit including judge independence.

Behavioral runs are operator-local and never a pull request gate. They drive the installed `claude` and `codex` binaries on the operator's own logins. Since the runner pin to `80e49af`, the runner keeps the operator's own setup out of answer and trigger runs itself. For Claude that is host skills, agents, `CLAUDE.md`, MCP servers, and auto memory. For Codex it is every skill under `~/.agents/skills`, Codex's bundled skills, and apps. The launchers in `tools/` predate that. `tools/claude-project-only` is still needed, because the runner grants a print-mode run no tool permissions and the launcher grants `acceptEdits`. In answer and trigger runs its `--setting-sources project` repeats the runner's flag and is harmless. Judge runs are sealed instead: the runner passes `--safe-mode --disable-slash-commands`, which hides workspace skills too. Whether the launcher's flag adds anything on a judge run has not been tested. `tools/codex-project-only` only moves HOME, which the runner has made redundant.

Cost is the reason this is not a gate. Fifty-two skills at twenty queries, three runs, and two harnesses is over six thousand command line invocations.

## What gets tested

Every skill gets outcome cases. Skills that a model may not invoke on its own are exercised by explicit invocation.

Only description-triggerable skills get the trigger matrix. For skills gated from model invocation, a description-driven trigger measurement would be meaningless.

Mode-to-skill routing is the primary trigger measurement, not bare description matching. A harvest of six thousand three hundred real prompts across both harnesses found that skills reach context through modes and plays, not through their descriptions. Harness-native description-driven loads were in single digits across the entire history. Measuring only bare descriptions would measure a path that is nearly unused. Bare description matching is kept as a secondary signal, because it is what a standalone install of a skill depends on.

## Where cases come from

Trigger rows are harvested from local session history with ground truth taken from whether the skill actually loaded, then reviewed by a person before use. Near-miss negatives are written by hand only where history has none. Harvested prompts are the least artificial corpus available and their labels are observed rather than asserted.

Outcome cases are the skill author's. The readiness audit refuses a paid run on a manifest without adversarial cases, which is the anti-theatre gate.

## Judges

A judge assertion carries gate severity, anchored dimensions, and repeats. The reasons are in `docs/authoring-cases.md`, rule 7, and they were paid for by a measured run where the judge was the only assertion that discriminated while every deterministic gate sat at ceiling.

An external scoring framework, LLM-as-a-Verifier, was evaluated and declined. Its method needs token log probabilities, which the Claude Messages API does not expose at all. It improves score resolution, which the measured evidence says is not the limit. The limit is case discrimination and sample size. The harness already ships the calibration machinery that framework does not claim, including alignment against human labels, robustness probes with negative controls, panels with quorum, and repeated judging.

## Honest limits

Two things no tool measures directly, and we do not claim otherwise. Whether a harness understood a skill is inferred from paired lift. Whether a skill's instructions are clear is inferred from variance across repeated runs of one case. Both are proxies and should be described as proxies in any result.

## Run artifacts and populated coverage

Paid task outputs default to a unique directory beside the consuming checkout. A working-tree installer copies ignored files too, so gitignore cannot keep raw transcripts out of a skill package. Canonical containment checks reject a default destination inside the selected skill before any model call. An explicit nonempty `OUT` keeps its existing meaning.

The reusable workflow offers `require-populated-manifests` as an opt-in policy. It requires each discovered skill directory to have a manifest with cases and a binding to that skill. Empty scaffolds remain valid by default so activation can stop before case authoring. The pinned runner continues to own schema validation, leakage checks, and readiness audit.
