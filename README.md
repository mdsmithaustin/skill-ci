# skill-ci

The single home for testing Agent Skills across this maintainer's skill repositories. It is itself an Agent Skill: say "activate skill-ci" in any repository that holds skills and the agent wires that repository up by following `SKILL.md`. No new harness lives here. The behavioral runner is a pinned fork of skill-eval-harness; this repository holds the case convention, the shared lints, the reusable workflow, the mise tasks, and the scaffold.

Why this repository is shaped this way, and when to abandon the dependency it pins, is in `DECISIONS.md`.

## Three layers

1. One case convention, one manifest per skill. Each skill owns a `shared-benchmark.json`, a skill-eval-harness manifest (format version 1) with `skill_name`, a `harness` block naming the fork, `skill_paths`, the `with_skill` and `without_skill` variants, and a `cases` list. Prefer `evals/<skill>/shared-benchmark.json` at the repository root, outside the skills tree, with `skill_paths` relative to the repository root. A skill installer copies a skill directory verbatim, so a manifest at `<skills-dir>/<skill>/evals/shared-benchmark.json` ships that skill's trigger queries and oracle scripts to everyone who installs it. That older layout still resolves, with `skill_paths` relative to the skill directory, and the reusable workflow's `evals-dir` input selects which tree it searches. Case files, `prompt_ref`, and script-oracle paths resolve against the manifest's own directory in both layouts, so they move with the manifest rather than staying beside the skill. Trigger rows (`kind: trigger`, `should_trigger` true or false) are harvested from local Claude and Codex session history with observed ground truth and reviewed before use. Outcome cases are written by the skill's author. Gated skills (the ones a model may not invoke on its own) get outcome cases only, invoked by explicit `/name` or `$name`; description-triggerable skills get the trigger matrix too.

2. One lint set, owned here and consumed everywhere. `tools/check-skill-frontmatter.py` validates agentskills.io metadata and the Codex invocation policy, and with the `trigger-cases` input also verifies every skill is declared in a trigger corpus. `tools/check-skill-content.py` fails on dangling relative links, unknown bold skill references, unclosed fences, and retired port paths. A repository whose skills reference skills living elsewhere declares them through the `content-ignore-file` input, so a real cross-repository mention is not read as a broken one. A reviewed `content-link-exceptions-file` policy can permit exact direct inline links in a copied template when its target exists only in the future output. `tools/check-pii.py` rejects likely personal data, which matters because harvested cases are cut from real session transcripts. It scans tracked files in the skills tree by default, because a shared skills workflow owns skill hygiene and not a consumer's application code. Tracked, not every file, because a behavioral run writes raw agent transcripts under the skill it exercised and those must never be committed. Set the `pii-scope` input to `repository` where a whole-repo scan is wanted, as mds-pstack does today. A consumer may keep its own copy of any of the three for a pre-commit hook, which a shared workflow cannot run, and the workflow fails if such a copy has drifted from the shared one. The checkers began as mds-pstack copies and are parametrized on a skills root. The content checker now also owns the output-time link policy described below. The reusable workflow `.github/workflows/skill-checks.yml` runs them on every push and pull request, then runs `skill-benchmark validate --strict-leakage` on every manifest and `skill-benchmark audit-manifest --fail-on-blockers` on every manifest that has at least one case. A scaffolded manifest with no cases is validated but not audited, because readiness is a question about a manifest someone has started to write. All of this is model-free.

3. One pinned external runner. `runner.lock` holds a single `git+https` spec pointing at github.com/mdsmithaustin/skill-eval-harness at one commit. `tools/run_runner.py` validates that pin and runs the named runner entrypoint from uv's isolated environment, so a command on `PATH` cannot replace it. The workflow checks out its own immutable revision through `job.workflow_repository` and `job.workflow_sha`; callers pin only the reusable workflow and Dependabot updates that dependency. Behavioral runs (`skill-trigger`, `skill-run`) are operator-local: they drive the installed `claude` and `codex` binaries on the host's own logins, spend model budget, and never run in CI or as a pull request gate.

An optional [package check](docs/packages.md) inventories every file in a skill and can compare it with an installed copy. It leaves the existing lint policies unchanged. The [evidence guide](docs/evidence.md) explains what format checks, package identity, installer probes, native activation, and paired runs can each establish.

Set `package-check: true` in the reusable workflow caller to inspect package trees in CI. Set `require-manifests: true` to fail when the manifest job checks zero files. Both inputs default to false. An empty scaffolded manifest counts as a file and still skips the readiness audit.

CI uses the workflow SHA pinned by each adopter. A Dependabot update takes effect after its PR merges. Local tasks use the `SKILL_CI` checkout, so update that checkout to receive its latest runner pin. Workflow self-identification requires GitHub.com; GitHub Enterprise Server does not provide these job fields.

## Activation flow

`SKILL.md` is the contract; this is the shape. The agent locates this checkout and the target's skills directory, writes a caller workflow with one full SHA pin, preserves existing workflow inputs, adds the `[env]` and `task_config.includes` lines to the target's `mise.toml`, warms the runner through `tools/run_runner.py`, scaffolds one empty manifest per skill with `tools/scaffold_manifest.py`, runs the model-free tasks, and stops with a report. It keeps an existing Dependabot configuration and adds a root `github-actions` entry only when needed. It never runs a paid step, never writes a case, and never commits or pushes. Running it twice keeps existing manifests, jobs, inputs, includes, and Dependabot entries.

## Local tasks

`skill-tasks.toml` is a mise task file. A target includes it or copies its tables. Every task reads `SKILL_CI` (this checkout) and `SKILLS_DIR` (default `skills`). A target whose manifests live outside the skills tree sets `EVALS_DIR`, and every task that reads a manifest honors it. Unset, each one searches the skills tree as before. A task fails rather than checking nothing when `EVALS_DIR` names a directory that does not exist.

| Task | Runs where | What it does |
| --- | --- | --- |
| `skill-lint` | CI and local | Both checkers over `SKILLS_DIR` |
| `skill-package` | CI when enabled, and local | Read-only package inventory, plus copy comparison when `INSTALLED_SKILLS_DIR` is set locally |
| `skill-validate` | CI and local | Runs `skill-benchmark validate --strict-leakage` on every manifest through the locked dispatcher |
| `skill-audit` | CI and local | Runs `skill-benchmark audit-manifest --fail-on-blockers` on every manifest through the locked dispatcher |
| `skill-trigger <skill>` | Local only | Trigger matrix on Claude and Codex, host logins, paid |
| `skill-run <skill>` | Local only | Readiness audit, then paired with and without runs on Claude and Codex, graded, judged and reported, host logins, paid |

`skill-run` refuses to start when the readiness audit reports a blocker. Set `AGENTS` to limit which harnesses run, `RUNS` for repetitions, `MODEL` and `CODEX_MODEL` for the answering models and `JUDGE_MODEL` for the judge, `JUDGE_RUNS` for how many times each judge task repeats before the verdicts are merged, `TIMEOUT` for the per-run ceiling, `OUT` for the output directory, and `CODEX_CMD` to override the Codex command prefix (the prefix names no model; `CODEX_MODEL` sets it, because the configured default on this host is rejected by the current codex-cli). This repository's own `mise.toml` includes the same task file and adds `test`, which runs the unit tests.

## Output-time links

Use a link-exceptions file only when a copied template names an output file that does not exist in the installed skill. The checker keeps all other content checks active. It does not exempt images, reference definitions, inline-code paths, sibling skill names, fences, or port substitutions.

The file is version-1 JSON. Each key in `inline_link_exceptions` is a path relative to `SKILLS_DIR`. Each value is a nonempty list of unique exact destination spellings from direct inline Markdown links. A policy entry for `../REPORT-[TOPIC].md` does not permit `<../REPORT-[TOPIC].md>` or a similar destination in another source file.

```json
{
  "version": 1,
  "inline_link_exceptions": {
    "example-skill/assets/report.template.md": [
      "../REPORT-[TOPIC].md"
    ]
  }
}
```

The checker reads the policy through `--link-exceptions-file PATH`. For local linting, set `CONTENT_LINK_EXCEPTIONS_FILE` to the policy path before you run `mise run skill-lint`. For the reusable workflow, set `content-link-exceptions-file` to the same path. Omit the option, the variable, and the workflow input when every relative link resolves in the checked skill tree.

If your repository keeps a local copy of `tools/check-skill-content.py`, copy the checker from the same skill-ci revision you select for the workflow. The workflow rejects drift between the local and shared checkers.

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

For review and repair skills, also include a healthy control that should remain unchanged. The [evidence guide](docs/evidence.md#author-cases-that-can-distinguish-behavior) explains how that control catches an audit that criticizes every input, and how to separate case definitions from executed results.

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
.github/workflows/test.yml         Linux and macOS unit tests on pull requests and main
.github/dependabot.yml            weekly actions and pip updates
docs/packages.md                 package inspection and copy comparison
docs/evidence.md                 evidence limits and healthy controls
docs/harvest-skill-optimizer.md   source and disposition of the peer-repo imports
tools/check-skill-frontmatter.py  verbatim from mds-pstack
tools/check-skill-content.py      content checks and exact output-time link exceptions
tools/check-pii.py                verbatim from mds-pstack
tools/check-skill-package.py      read-only package inventory and copy comparison
tools/scaffold_manifest.py        writes an empty manifest per skill, either layout
tools/test_*.py                   checker, scaffold, and workflow regression tests
tools/requirements.txt            hashed PyYAML pin for the checkers
tools/claude-project-only         Claude with user skills hidden, writes allowed
tools/codex-project-only          Codex with user skills hidden, login kept
```

## Running the tests here

The repository test workflow runs the same `mise run test` command on Linux and macOS. It is separate from the reusable consumer workflow and does not call a model.

`mise run test`, or without mise:

```sh
uv run --no-project --with-requirements tools/requirements.txt \
  python -m unittest discover -s tools -p 'test_*.py'
```
