# skill-ci

The single home for testing Agent Skills across this maintainer's skill repositories. It is itself an Agent Skill: say "activate skill-ci" in any repository that holds skills and the agent wires that repository up by following `SKILL.md`. No new harness lives here. The behavioral runner is a pinned fork of skill-eval-harness; this repository holds the case convention, the shared lints, the reusable workflow, the mise tasks, and the scaffold.

Why this repository is shaped this way, and when to abandon the dependency it pins, is in `DECISIONS.md`.

## Three layers

1. One case convention, one manifest per skill. Each skill owns a `shared-benchmark.json`, a skill-eval-harness manifest (format version 1) with `skill_name`, a `harness` block naming the fork, `skill_paths`, the `with_skill` and `without_skill` variants, and a `cases` list. Prefer `evals/<skill>/shared-benchmark.json` at the repository root, outside the skills tree, with `skill_paths` relative to the repository root. A skill installer copies a skill directory verbatim, so a manifest at `<skills-dir>/<skill>/evals/shared-benchmark.json` ships that skill's trigger queries and oracle scripts to everyone who installs it. That older layout still resolves, with `skill_paths` relative to the skill directory, and the reusable workflow's `evals-dir` input selects which tree it searches. Case files, `prompt_ref`, and script-oracle paths resolve against the manifest's own directory in both layouts, so they move with the manifest rather than staying beside the skill. Trigger rows (`kind: trigger`, `should_trigger` true or false) are harvested from local Claude and Codex session history with observed ground truth and reviewed before use. Outcome cases are written by the skill's author. Gated skills (the ones a model may not invoke on its own) get outcome cases only, invoked by explicit `/name` or `$name`; description-triggerable skills get the trigger matrix too.

2. One lint set, owned here and consumed everywhere. `tools/check-skill-frontmatter.py` validates agentskills.io metadata and the Codex invocation policy, and with the `trigger-cases` input also verifies every skill is declared in a trigger corpus. `tools/check-skill-content.py` fails on dangling relative links, unknown bold skill references, unclosed fences, and retired port paths. A repository whose skills reference skills living elsewhere declares them through the `content-ignore-file` input, so a real cross-repository mention is not read as a broken one. `tools/check-pii.py` rejects likely personal data, which matters because harvested cases are cut from real session transcripts. It scans tracked files in the skills tree by default, because a shared skills workflow owns skill hygiene and not a consumer's application code. Tracked, not every file, because a behavioral run writes raw agent transcripts under the skill it exercised and those must never be committed. Set the `pii-scope` input to `repository` where a whole-repo scan is wanted, as mds-pstack does today. A consumer may keep its own copy of any of the three for a pre-commit hook, which a shared workflow cannot run, and the workflow fails if such a copy has drifted from the shared one. All three came from mds-pstack unchanged and are parametrized on a skills root. The reusable workflow `.github/workflows/skill-checks.yml` runs them on every push and pull request, then runs `skill-benchmark validate --strict-leakage` on every manifest and `skill-benchmark audit-manifest --fail-on-blockers` on every manifest that has at least one case. A scaffolded manifest with no cases is validated but not audited, because readiness is a question about a manifest someone has started to write. All of this is model-free.

3. One pinned external runner. `runner.lock` holds a single `git+https` spec pointing at github.com/mdsmithaustin/skill-eval-harness at one commit. The workflow, the mise tasks, and activation all read it. Behavioral runs (`skill-trigger`, `skill-run`) are operator-local: they drive the installed `claude` and `codex` binaries on the host's own logins, spend model budget, and never run in CI or as a pull request gate.

## Activation flow

`SKILL.md` is the contract; this is the shape. The agent locates this checkout and the target's skills directory, writes a caller workflow that references the reusable one, adds the `[env]` and `task_config.includes` lines to the target's `mise.toml`, installs the runner from `runner.lock` (or reports that the lock still says `PIN_ME`), scaffolds one empty manifest per skill with `tools/scaffold_manifest.py`, runs the model-free tasks, and stops with a report. It never runs a paid step, never writes a case, and never commits or pushes. Running it twice converges to the same state: existing manifests, jobs, and includes are kept.

## Local tasks

`skill-tasks.toml` is a mise task file. A target includes it or copies its tables. Every task reads `SKILL_CI` (this checkout) and `SKILLS_DIR` (default `skills`).

| Task | Runs where | What it does |
| --- | --- | --- |
| `skill-lint` | CI and local | Both checkers over `SKILLS_DIR` |
| `skill-validate` | CI and local | `skill-benchmark validate --strict-leakage` on every manifest |
| `skill-audit` | CI and local | `skill-benchmark audit-manifest --fail-on-blockers` on every manifest |
| `skill-trigger <skill>` | Local only | Trigger matrix on Claude and Codex, host logins, paid |
| `skill-run <skill>` | Local only | Readiness audit, then paired with and without runs on Claude and Codex, graded, judged and reported, host logins, paid |

`skill-run` refuses to start when the readiness audit reports a blocker. Set `AGENTS` to limit which harnesses run, `RUNS` for repetitions, `MODEL` and `CODEX_MODEL` for the answering models and `JUDGE_MODEL` for the judge, `JUDGE_RUNS` for how many times each judge task repeats before the verdicts are merged, `TIMEOUT` for the per-run ceiling, `OUT` for the output directory, and `CODEX_CMD` to override the Codex command prefix (the prefix names no model; `CODEX_MODEL` sets it, because the configured default on this host is rejected by the current codex-cli). This repository's own `mise.toml` includes the same task file and adds `test`, which runs the unit tests.

## Authoring conventions

Eight rules for anyone writing cases. The first five come from the research that chose this shape. The last three were paid for by the runs that followed.

1. Describe the world in prose instead of fixtures. A case states what the repository, the files, and the situation look like in a few sentences the agent reads as context. Build a fixture tree only when an assertion has to read a real file that was placed there before the run. A file the agent itself writes is not readable by an assertion on the `run-agent` path, per convention six.

2. Grade the trace, not the message. The final reply is the easiest thing to fake. Assertions look at what the agent did, which files it read, which commands it ran, and whether the skill loaded. Trace evidence is the durable kind. A file the agent wrote is not, on the `run-agent` path, for the reason convention six gives. A trace assertion on a read of a referenced file is also the only proof that the reference resolves and loads.

3. One result assertion and one path assertion per case. The result assertion says what must be true of the outcome. The path assertion says what must be true of how the agent got there. A case with five assertions is five cases with worse names. A case with only a result assertion passes when the agent guesses.

4. Near-miss negatives. Every trigger matrix needs prompts that look like they want the skill and do not, and every outcome set needs a case where the right move is to scope down, refuse, or hold a rule under pressure. The readiness audit calls these adversarial cases and will not pass a manifest without them.

5. Readiness audit before any paid run. `skill-benchmark audit-manifest --fail-on-blockers --strict-judge` runs before any command that spends model budget, so a manifest whose judge is also a model under test stops the run. It is wired into `skill-run` and into CI. A manifest that fails it is not ready, whatever the author believes about it.

Sixth, learned the hard way on 2026-09-13. Assert on the skill's product, never on the whole reply. A skill that works often explains what it did, and the explanation quotes the very thing the skill removed. A substring gate over the reply then fails the good run and passes the silent one, and the report reads as negative lift when the skill actually performed better. Do not solve this by asking for a file. On the `run-agent` path the agent's working directory is temporary and is discarded, and nothing copies its files into the run directory, so a written artifact never reaches an assertion. Have the case ask for the product inside a delimiter and have a `script` oracle extract it from `output.md`. Use tags rather than code fences, because content containing a fenced code block closes an outer fence early. A script oracle must be a real file in its own subdirectory and must take `{output_dir}` as an argument, because it runs with the manifest directory as its working directory. One more rule from the same run. Encode the skill's rule, not a crude substring of it.

Seventh. Make the judge count, and make it say why. On a prose or judgement skill the judge is usually the only assertion that discriminates, because deterministic gates sit at ceiling once a case is easy enough for the base model. Three settings decide whether that signal reaches the report. Give the assertion gate severity when the judge is the instrument you trust, since a soft judge contributes nothing to the headline score and a run can separate the arms cleanly while still reporting no lift. Score anchored dimensions rather than one flat rubric, so a failure names the property that fell instead of returning a number nobody can act on. Repeat the judge and let the harness merge the verdicts, because a single sampled verdict hides its own variance.

Eighth. Prefer the calibration you already have to a new dependency. The harness ships judge alignment against human labels, judge robustness probes with negative controls, multi-judge panels with quorum, and repeated judging. Before adopting an external scoring framework, check whether the thing it improves is actually your bottleneck. Resolution and variance in the score are rarely the limit. Case discrimination and sample size usually are.

## Layout

```text
SKILL.md                          activation contract for an agent
README.md                         this file
DECISIONS.md                      why the repository is shaped this way
TODO.md                           what is deliberately not done yet
runner.lock                       the one runner pin
skill-tasks.toml                  mise tasks a target includes
mise.toml                         this repository's own tools and tasks
lefthook.yml                      pre-commit rejects PII and runs the unit tests
.github/workflows/skill-checks.yml  reusable workflow_call workflow
.github/dependabot.yml            weekly actions and pip updates
tools/check-skill-frontmatter.py  verbatim from mds-pstack
tools/check-skill-content.py      verbatim from mds-pstack
tools/check-pii.py                verbatim from mds-pstack
tools/scaffold_manifest.py        writes an empty manifest per skill, either layout
tools/test_*.py                   unit tests for the three scripts
tools/requirements.txt            hashed PyYAML pin for the checkers
tools/claude-project-only         Claude with user skills hidden, writes allowed
tools/codex-project-only          Codex with user skills hidden, login kept
```

## Running the tests here

`mise run test`, or without mise:

```sh
uv run --no-project --with-requirements tools/requirements.txt \
  python -m unittest discover -s tools -p 'test_*.py'
```
