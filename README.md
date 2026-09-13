# skill-ci

The single home for testing Agent Skills across this maintainer's skill repositories. It is itself an Agent Skill: say "activate skill-ci" in any repository that holds skills and the agent wires that repository up by following `SKILL.md`. No new harness lives here. The behavioral runner is a pinned fork of skill-eval-harness; this repository holds the case convention, the shared lints, the reusable workflow, the mise tasks, and the scaffold.

## Three layers

1. One case convention, in the skill directory. Each skill owns `evals/shared-benchmark.json`, a skill-eval-harness manifest (format version 1) with `skill_name`, a `harness` block naming the fork, `skill_paths` relative to the skill directory, the `with_skill` and `without_skill` variants, and a `cases` list. Trigger rows (`kind: trigger`, `should_trigger` true or false) are harvested from local Claude and Codex session history with observed ground truth and reviewed before use. Outcome cases are written by the skill's author. Gated skills (the ones a model may not invoke on its own) get outcome cases only, invoked by explicit `/name` or `$name`; description-triggerable skills get the trigger matrix too.

2. One lint set, owned here and consumed everywhere. `tools/check-skill-frontmatter.py` validates agentskills.io metadata and the Codex invocation policy. `tools/check-skill-content.py` fails on dangling relative links, unknown bold skill references, unclosed fences, and retired port paths. Both came from mds-pstack unchanged and are parametrized on a skills root. The reusable workflow `.github/workflows/skill-checks.yml` runs them on every push and pull request, then runs `skill-benchmark validate --strict-leakage` on every manifest and `skill-benchmark audit-manifest --fail-on-blockers` on every manifest that has at least one case. A scaffolded manifest with no cases is validated but not audited, because readiness is a question about a manifest someone has started to write. All of this is model-free.

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
| `skill-run <skill>` | Local only | Readiness audit, then paired with and without runs on Claude and Codex, host logins, paid |

`skill-run` refuses to start when the readiness audit reports a blocker. Set `RUNS` to change repetitions, `OUT` to choose the output directory, and `CODEX_CMD` to override the Codex command prefix (the configured default model on this host is rejected by the current codex-cli, so a working prefix names a model explicitly). This repository's own `mise.toml` includes the same task file and adds `test`, which runs the unit tests.

## Authoring conventions

Sixth, learned the hard way on 2026-09-13. Assert on the artifact, never on the whole reply. A skill that works often explains what it did, and an explanation quotes the very thing the skill removed. A substring gate over the reply then fails the good run and passes the silent one, and the report reads as negative lift when the skill actually performed better. Have the prompt write its product to a file and point the assertion at that file. Text assertions cannot take a file directly, so use the `script` oracle against the run directory. Two more rules from the same run: encode the skill's rule, not a crude substring of it, and check a judge assertion's threshold, because a rubric that scores 0.85 still records as a failure against a threshold of 1.0.

Five rules for anyone writing cases, harvested from the research that chose this shape.

1. Describe the world in prose instead of fixtures. A case states what the repository, the files, and the situation look like in a few sentences the agent reads as context. Build a fixture tree only when an assertion has to read a real file that the agent was expected to write or change.

2. Grade the trace, not the message. The final reply is the easiest thing to fake. Assertions look at what the agent did: which files it read, which commands it ran, whether the skill loaded, what it wrote to disk. A trace assertion on a read of a referenced file is also the only proof that the reference resolves and loads.

3. One result assertion and one path assertion per case. The result assertion says what must be true of the outcome. The path assertion says what must be true of how the agent got there. A case with five assertions is five cases with worse names. A case with only a result assertion passes when the agent guesses.

4. Near-miss negatives. Every trigger matrix needs prompts that look like they want the skill and do not, and every outcome set needs a case where the right move is to scope down, refuse, or hold a rule under pressure. The readiness audit calls these adversarial cases and will not pass a manifest without them.

5. Readiness audit before any paid run. `skill-benchmark audit-manifest --fail-on-blockers` runs before any command that spends model budget. It is wired into `skill-run` and into CI. A manifest that fails it is not ready, whatever the author believes about it.

## Layout

```text
SKILL.md                          activation contract for an agent
README.md                         this file
TODO.md                           what is deliberately not done yet
runner.lock                       the one runner pin
skill-tasks.toml                  mise tasks a target includes
mise.toml                         this repository's own tools and tasks
lefthook.yml                      pre-commit runs the unit tests
.github/workflows/skill-checks.yml  reusable workflow_call workflow
tools/check-skill-frontmatter.py  verbatim from mds-pstack
tools/check-skill-content.py      verbatim from mds-pstack
tools/scaffold_manifest.py        writes an empty manifest per skill
tools/test_*.py                   unit tests for the three scripts
tools/requirements.txt            hashed PyYAML pin for the checkers
```

## Running the tests here

`mise run test`, or without mise:

```sh
uv run --no-project --with-requirements tools/requirements.txt \
  python -m unittest discover -s tools -p 'test_*.py'
```
