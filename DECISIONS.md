# Decisions

Why this repository is shaped the way it is. `README.md` covers how to use it. The evidence behind each decision is in `docs/AGENT-SKILL-TEST-FRAMEWORKS-RESEARCH.md` in the agent-loop-runner repository, which records the sources, the measured runs, and the checkpoint verdicts.

## Why this repository exists

Two skill repositories were testing skills separately and duplicating the work. One had a frontmatter checker, a reference checker, and a trigger file that only asserted a description contained a phrase. The other had a stricter frontmatter validator, no reference checker, ninety-two behavioral trigger rows in an incompatible schema, and a bespoke runner that could not move. The duplication was two validators and two trigger formats.

One shared home fixes that. A skill repository gets its lints, its runner version, and its commands from here, and owns only its cases.

## Why an external runner instead of our own

A capability census across `claude plugin eval`, skillroll, NVIDIA SkillEvaluator, skillgrade, and skill-eval-harness found that skill-eval-harness already held every behavioral capability the others held, plus four none of them held. The two capabilities no tool had, proof that a referenced file was read and a measure of instruction clarity, turned out to be a per-case assertion and a variance readout rather than harness features.

Building our own would have reproduced about twenty thousand lines to add two things. agent-loop-runner had already built one, and that runner is precisely what could not be shared.

## Why a fork, and when to leave it

`pyproject.toml` pins a fork, as the distribution `skill-eval-harness-ext`, rather than the upstream release `skill-eval-harness`. The pin is one git commit, because the fork has no release tags of its own. `git ls-remote --tags` on the fork lists only `sync-upstream-2026-10-05`, and its local `v0.x` tags are upstream's. The pin is now `c23ed79`, fork #25. The commit before it, `15cc612`, renamed the distribution. At the `80e49af` pin, the fork carried the twenty patches listed below. Patches 1 to 8 were classified on 2026-09-27. Patches 9 to 20 arrived with that pin and name the fork pull request each came from. Fork #11 and #13 changed only tests and docs, so they are not patches. The `6634de1` pin also includes fork #20, classified below on 2026-10-04.

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

The `15cc612` pin is later than the last classification above. It adds the upstream merge `40f2927`, fork #21, #22, and #23, and the upstream commits that merge brought in. The `c23ed79` pin adds fork #25 on top of `15cc612`. The operator accepted this classification on 2026-10-09.

- **Not patches.** Fork #21 changes docs and CI. Fork #23 renames the distribution.
- **Adapter edge.** Fork #25 stops agent sessions on SIGINT and SIGTERM.
- **Opt-in addition.** Fork #22 makes a recovery case optional. `answer_case_input_fingerprint` and `answer_task_fingerprint` add a `recovery` key only when a case declares one, so existing fingerprints are unchanged.
- **Upstream's own rules.** The upstream merge `40f2927` is not a fork patch. Its upstream commits change upstream's own grading rules, which the fork follows. Its conflict resolutions were not audited for grading changes.

None of these reopens the exit decision.

Leaving stays cheap to assess. The upstream `adewale/skill-eval-harness` revision assessed on 2026-10-01, `2297000`, remains an ancestor of the `c23ed79` pin. Verified on 2026-10-08 with `git merge-base --is-ancestor`. The fork remains a superset of that assessed revision.

## How skill-ci is distributed

A repository names its skill-ci version once, in `.skill-ci.toml`. Every place that runs skill-ci runs that version, whether it starts in a terminal, lefthook, no-mistakes, or a CI service. skill-ci is a `skill-ci` command that uv installs from git, and skill-ci is not published to a package registry. The operator settled the design on 2026-10-06 in a design review. Two later review rounds changed the credentials rule and the hand-off, and their sections give those dates. Each decision below gives its reason.

The earlier setup had a consumer include `skill-tasks.toml` from a sibling checkout of skill-ci and call a reusable workflow pinned by SHA. It had three faults. Local runs and CI could run different code, and nothing showed it. The `SKILL_CI` variable moved the tools, but not the hardcoded include of the task definitions. An `sbx --clone` sandbox or a Dev Container has no sibling checkout at all.

### Why no-mistakes was compared

no-mistakes is a pipeline that validates a change before it is pushed, and it reaches a repository with nothing but a settings file. The operator asked whether that was a better pattern than a sibling checkout. Its [README](https://github.com/kunchenguid/no-mistakes) and [installer](https://raw.githubusercontent.com/kunchenguid/no-mistakes/main/docs/install.sh) show how it ships. It builds a Go binary for each platform. `install.sh` installs the latest release into `~/.no-mistakes/bin`, and `no-mistakes update` replaces it in place. A repository holds only `.no-mistakes.yaml`, which does not say where the tool lives, and `init` installs a skill whose text is built into the binary.

One version per machine suits no-mistakes because its CI checks a record that a local run happened and never repeats the checks. skill-ci's CI does repeat lint, validate, and audit, so local runs and CI have to run the same code. A latest-only install would bring back the drift that started this work. A release binary also needs a release pipeline, which skill-ci does not have.

Three ideas carried over. A settings file in the repository says which version the repository uses and how it is configured, and never where the tool sits on disk. The version is pinned in that one place, and every tool calls `skill-ci`, which reads it. And `init` does the setup, with `SKILL.md` calling it, so an adopter without an agent gets the same result.

### Why one file and one command

`.skill-ci.toml` holds the version, the `source`, and the options. `skill-ci check` runs the checks. Lefthook, no-mistakes, GitHub Actions, and any other CI call that one command, and none of them records a version of its own. Two CI paths would mean two pins to keep equal and two things to keep working, so the reusable workflow is retired. `skill-ci init` writes a short workflow that installs skill-ci and runs `skill-ci check`, the same on github.com and GitHub Enterprise Server.

The bash tasks in `skill-tasks.toml` became subcommands, because an outside adopter may have neither mise nor bash. The mise tasks that `init` adds are one-line calls to those subcommands. Hooks run in addition to CI and never instead of it. Anyone can skip a hook with `--no-verify`, so CI stays the gate. The split follows measured cost on a repository of 56 skills. Lint took 0.2 to 0.4 seconds and the personal-data scan of staged files 0.07 seconds, so `skill-ci check --fast` runs before each commit. Validate took 1.1 to 1.4 seconds and audit 1.1 seconds, so the full `skill-ci check` runs before each push.

no-mistakes runs skill-ci second. When `commands.lint` is set, `init` appends ` && skill-ci check`, so the repository's own lint still runs first. When it is empty, no-mistakes has an agent do the linting, and setting the field would switch that off without notice. `init` therefore leaves the file alone and prints a `commands.lint.additional` entry for the user's own no-mistakes settings. no-mistakes reads commands from the default branch, so the `.no-mistakes.yaml` change applies after it merges. The `repository_overrides` entry lives in the user's own settings and applies at once.

The cost is losing Dependabot's automatic bump pull requests. Dependabot bumped the `uses:` line by itself and cannot read `.skill-ci.toml`. `skill-ci update` moves an exact-tag pin, and every run of an exact-tag pin prints a notice when a newer tag exists. Both work on GHES with no extra service. An adopter who already runs Renovate can add a custom rule later.

`version` is an exact tag, `latest`, or `main`. no-mistakes tells adopters never to pin its [CI action](https://github.com/kunchenguid/no-mistakes/tree/main/.github/actions/require-no-mistakes) to `@main`. The risk that rule covers is a pull request editing the `main` that checks it. A consumer's pull request cannot edit skill-ci's `main`, so that risk does not apply here. The cost of `latest` and `main` is narrower. A CI run and a local run look the version up separately, so a release between them can make them differ. A local run can also reuse a lookup up to a day old, as [Why a tag resolves to a commit](#why-a-tag-resolves-to-a-commit) explains. Every run prints its exact commit on its first line to make that visible. `init` writes the newest tag as an exact tag, so a new adopter gets results they can reproduce.

Five alternatives lost to this design.

- **A sibling checkout with a commit check.** It fixes drift but keeps the fixed path, which fails in `sbx` and Dev Containers.
- **A mise git include at a commit.** It worked on mise 2026.9.15 with the experimental setting off. Outside adopters may not use mise, so it stays only as a fallback for mise-only consumers.
- **The reusable workflow for github.com and a settings file for GHES.** That is two CI paths and two pins.
- **A `pre-commit` framework hook.** Its `rev:` would be a second pin.
- **Copying the harness into skill-ci.** It would bury the patch list and the exit test above inside a second repository.

### Why GHES rules out a pin in a `uses:` line

The GHES 3.12 documentation says "You cannot directly use reusable workflows defined on GitHub.com." The old workflow also found its own revision through job fields that GHES does not provide. A GHES repository therefore has no `uses:` line for the local command to read, and a pin kept on that line could not serve both hosts. The pin moved to `.skill-ci.toml`, which every host can read.

Some enterprise networks block github.com, so `.skill-ci.toml` has a `source` key that points at an internal mirror and defaults to github.com. A mirrored skill-ci installs `skill-eval-harness-ext` from github.com unless the mirror's `pyproject.toml` says otherwise. The mirror therefore has to carry the harness too, and the dependency line has to change. That stays a documented step and not tooling, until an adopter needs it. The workflow that `init` writes installs uv with `pip install uv==0.12.7`, because a runner on a restricted network is more likely to reach a package mirror than github.com. `astral-sh/setup-uv` works on GHES only when an administrator lets the instance use actions from github.com. The operator deferred the choice of install method, so that command is one template line that can change on its own.

### Why skill-ci is not on PyPI

PyPI rejects an upload whose own metadata declares a dependency as a direct URL (`warehouse/forklift/legacy.py`, line 464, read on 2026-10-06). skill-ci depends on the harness fork through a git URL, so publishing it would mean publishing the fork under its own name first. Publishing is not planned. A git tag already lets anyone run `uv tool install git+https://github.com/mdsmithaustin/skill-ci.git@<tag>`.

Checking PyPI for the fork's name exposed a worse problem. PyPI already holds `skill-eval-harness` 0.6.0, published by the upstream author. The fork's `pyproject.toml` used the same name and the same version with different code. An adopter who ran `pip install skill-eval-harness` got upstream, without the blinding patches that the exit test above counts as an accepted difference. Their results would not be comparable with skill-ci's, and the version numbers would not show it. The fork's distribution is now `skill-eval-harness-ext`. Its modules and console scripts keep their names.

skill-ci owns the harness version in any repository that uses it. `pyproject.toml` pins one commit, and `skill-ci harness` is the way into that copy. skill-ci warns when it finds a different `skill-benchmark` on `PATH` or a harness named in the project's own dependencies. A harness bump stays manual. A person classifies each one against the exit test above, and an automatic bump pull request would skip that step.

### Why a tag resolves to a commit

The prototype on 2026-10-06, with uv 0.12.7, compared the two ways to run a pinned version. `uv tool run --from git+<source>@<commit>` took 0.23 to 0.34 seconds warm and worked with `--offline`. The same command with a tag took 1.31 to 1.81 seconds warm, and `--offline` failed with exit code 1. skill-ci therefore resolves a tag to its commit with `git ls-remote` and always passes the commit to uv.

Resolution has its own cost. skill-ci caches each source's answer for a day (`REFS_FRESH_FOR` in `src/skill_ci/pin.py`), and every pin reuses it while it is fresh. A tag moved on the source can keep its old commit for up to a day. An exact tag that the cache lacks is looked up at once.

`latest` and `main` asked the source on every run until v1.1.0, because following the head is their purpose. On 2026-10-09 the operator judged a network check on every run too costly. They now reuse a cached answer for up to a day, as an exact tag does. The cost is that a local run can run a commit up to a day older than CI, which starts with no cache. `skill-ci update` asks the source at once and refreshes the cache.

Offline, once the cached answer is a day old, `latest` and `main` run the last answer skill-ci looked up and print a warning that names its commit. A lookup needs the network. The warning lets a local run keep working offline without hiding that its commit may be stale. When nothing was ever looked up, skill-ci exits with a message that says so. An exact tag in the cache needs no lookup.

The package version reads `1.0.0` in the commit that gets tagged `v1.0.0`. A pin to `v1.0.0` fails until that tag exists. Pins start there because earlier revisions cannot report that the pinned run started, and a run that cannot report it can happen twice and repeat a paid `run`.

### Why the hand-off runs offline first

A pinned run starts `uv tool run --isolated` at the pinned commit. uv revalidates its cached package index over the network once those responses are 10 minutes old. With the network down, that hand-off exited with code 126 after about 6 seconds, even though the commit's environment was already built. The message also blamed the source, which was never the failing part.

The hand-off now tries `--offline` first and retries online once only when uv exits before the pinned child starts, which skill-ci knows from a start marker. A child that started and failed is never retried, because a retry could repeat a paid call. A review chose this on 2026-10-08, after a performance run measured the fault. After a stale index, a first run with the network down used to exit with code 126 after 4.2 to 7.4 seconds. It now exits with code 0 after 0.8 seconds. A first run online went from 1.0 to 0.8 seconds. A first build of a commit runs uv twice, once offline and once online.

### Why `source` rejects credentials

A review set the credentials rule on 2026-10-07. The operator can still decide to allow tokens in `source`, and that would bring redaction back. `source` is a URL that skill-ci prints, caches, and hands to git. Redacting a token from it failed three times, because each fix missed a new shape of URL. The deeper fault is that a token in a committed `.skill-ci.toml` has already reached everyone who can read the repository. Redaction protected a log line while the file itself leaked.

skill-ci now rejects a `source` that carries credentials. Only an ssh user name is allowed. The error names the key, points at a git credential helper, and never echoes the value. A private mirror authenticates through that helper. The redaction code is deleted, and the cache key is the source as written.

## Where manifests live

A manifest belongs outside the skills tree, at `evals/<skill>/shared-benchmark.json`, with `skill_paths` relative to the repository root. The reason is what a skill installer does. `npx skills` copies a skill directory verbatim to every consumer, in both copy and symlink mode, and it has no ignore or exclude mechanism. A manifest at `<skills-dir>/<skill>/evals/shared-benchmark.json` therefore hands every consumer of that skill its trigger queries, its expected answers, and its oracle scripts. Measured on 2026-09-13 by installing a fixture skill with an `evals/` tree and reading a planted transcript back from the installed path.

The old layout still resolves, because the runner's rule for the repository root runs the existing case first. The `evals_dir` key in `.skill-ci.toml`, or the `--evals-dir` flag, selects the tree to search, and it defaults to the skills tree. The choice is one or the other for a whole repository, because each search reads a single tree. A repository that starts moving manifests moves all of them in the same change; the ones left behind stop being checked. The runner also resolves `evals/shared-benchmark.json` with no skill segment, which suits a repository holding one skill, but the scaffold does not write that shape.

The cost is that a manifest and its skill no longer share a directory, so nothing keeps them in step automatically. Case files, `prompt_ref`, and script-oracle paths resolve against the manifest's own directory in both layouts, which is the trap worth knowing when a manifest moves.

## Where runs happen

Everything model-free runs in continuous integration on every pull request. That is the lints, manifest validation, the leakage check, and the readiness audit including judge independence.

Behavioral runs are operator-local and never a pull request gate. They drive the installed `claude` and `codex` binaries on the operator's own logins. Since the runner pin to `80e49af`, the runner keeps the operator's own setup out of answer and trigger runs itself. For Claude that is host skills, agents, `CLAUDE.md`, MCP servers, and auto memory. For Codex it is every skill under `~/.agents/skills`, Codex's bundled skills, and apps. The launchers in `src/skill_ci/launchers/` predate that. `claude-project-only` is still needed, because the runner grants a print-mode run no tool permissions and the launcher grants `acceptEdits`. In answer and trigger runs its `--setting-sources project` repeats the runner's flag and is harmless. Judge runs are sealed instead: the runner passes `--safe-mode --disable-slash-commands`, which hides workspace skills too. Whether the launcher's flag adds anything on a judge run has not been tested. `codex-project-only` only moves HOME, which the runner has made redundant.

Cost is the reason this is not a gate. Fifty-two skills at twenty queries, three runs, and two harnesses is over six thousand command line invocations.

## What gets tested

Every skill gets outcome cases. Skills that a model may not invoke on its own are exercised by explicit invocation.

Only description-triggerable skills get the trigger matrix. For skills gated from model invocation, a description-driven trigger measurement would be meaningless.

Mode-to-skill routing is the primary trigger measurement, not bare description matching. A harvest of six thousand three hundred real prompts across both harnesses found that skills reach context through modes and plays, not through their descriptions. Harness-native description-driven loads were in single digits across the entire history. Measuring only bare descriptions would measure a path that is nearly unused. Bare description matching is kept as a secondary signal, because it is what a standalone install of a skill depends on.

## Where a skill's invocation gate lives

The frontmatter check began by requiring `agents/openai.yaml` `policy.allow_implicit_invocation` to equal `not disable-model-invocation`, so the two gates never disagreed. A consuming repository then removed `disable-model-invocation` from 47 skills. It reported that on Claude Code the field makes the Skill tool refuse a skill even when another skill names it, and that its own notes were therefore unreachable. It hides those skills' descriptions with Claude's user-scope `skillOverrides: name-only` setting and gates them for Codex in `agents/openai.yaml` alone. The paired rule reported 94 errors on that tree under v1.1.0.

The `invocation_policy` key (`--invocation-policy`) keeps the paired rule as the default and adds `openai-yaml`. Under it, `agents/openai.yaml` is the only gate, and a `SKILL.md` that sets `disable-model-invocation: true` is an error whose message names the Skill tool refusal and the fix. The default stays `paired` so a repository that relies on the field keeps its check. `disable-model-invocation: false` passes under `openai-yaml`, since it does not stop the Skill tool and the message would otherwise be false. The trigger declaration check compares `implicit_allowed` with the gate the policy reads, so a repository on `openai-yaml` declares what Codex sees. Whether the Skill tool refuses a flagged skill comes from the consuming repository's report and was not re-measured here.

## Where cases come from

Trigger rows are harvested from local session history with ground truth taken from whether the skill actually loaded, then reviewed by a person before use. Near-miss negatives are written by hand only where history has none. Harvested prompts are the least artificial corpus available and their labels are observed rather than asserted.

Outcome cases are the skill author's. The readiness audit refuses a paid run on a manifest without adversarial cases, which is the anti-theatre gate.

## Judges

A judge assertion carries gate severity, anchored dimensions, and repeats. The reasons are in `docs/authoring-cases.md`, rule 7, and they were paid for by a measured run where the judge was the only assertion that discriminated while every deterministic gate sat at ceiling.

An external scoring framework, LLM-as-a-Verifier, was evaluated and declined. Its method needs token log probabilities, which the Claude Messages API does not expose at all. It improves score resolution, which the measured evidence says is not the limit. The limit is case discrimination and sample size. The harness already ships the calibration machinery that framework does not claim, including alignment against human labels, robustness probes with negative controls, panels with quorum, and repeated judging.

## Honest limits

Two things no tool measures directly, and we do not claim otherwise. Whether a harness understood a skill is inferred from paired lift. Whether a skill's instructions are clear is inferred from variance across repeated runs of one case. Both are proxies and should be described as proxies in any result.

## Run artifacts and populated coverage

Paid task outputs default to a unique directory beside the consuming checkout. A working-tree installer copies ignored files too, so gitignore cannot keep raw transcripts out of a skill package. Canonical containment checks reject a default destination inside the selected skill before any model call. An explicit `out` setting, or `--out`, is checked the same way and must sit outside the skill package.

`skill-ci check` offers `--require-populated-manifests`, or the `require_populated_manifests` key, as an opt-in policy. It requires each discovered skill directory to have a manifest with cases and a binding to that skill. Empty scaffolds remain valid by default so activation can stop before case authoring. The pinned runner continues to own schema validation, leakage checks, and readiness audit.
