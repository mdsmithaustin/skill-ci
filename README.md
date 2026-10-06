# skill-ci

skill-ci tests Agent Skills. A skill is a directory with a `SKILL.md` file that tells an AI coding agent, such as Claude Code or Codex, how to do a task. If a repository holds skills, skill-ci gives it two kinds of checks:

- **Free checks in CI.** A GitHub Actions workflow runs on every push and pull request. It lints each `SKILL.md`, finds broken links, rejects personal data, and validates the test-case files. No model is called.
- **Paid checks on your machine.** Two mise tasks run Claude and Codex on test prompts. One checks whether the skill loads when it should. The other runs each prompt with and without the skill and grades whether the skill helped. They use your own logins and spend model budget. They never run in CI.

skill-ci does not have its own test runner. It pins a fork of [skill-eval-harness](https://github.com/mdsmithaustin/skill-eval-harness) in `runner.lock` and runs that. `DECISIONS.md` explains why, and when to stop using the fork.

skill-ci is also a skill itself. In a repository that holds skills, tell your agent "activate skill-ci" and it sets the repository up by following `SKILL.md`.

## Terms

| Term | Meaning |
| --- | --- |
| Skills directory | The directory whose children each hold a `SKILL.md`. Set by `SKILLS_DIR` locally and `skills-dir` in CI. Default `skills`. |
| Manifest | The test file for one skill, `shared-benchmark.json`, in skill-eval-harness format version 1 or 2. It names the skill, its files (`skill_paths`), the two variants, and a list of cases. |
| Case | One test prompt in a manifest, with the assertions that grade it. |
| Trigger case | A case that checks whether the agent loads the skill for a prompt. `should_trigger` says whether it should. |
| Outcome case | A case that checks whether the skill made the agent's result better. |
| Variant | One side of a paired run. `with_skill` has the skill installed. `without_skill` does not. |
| Oracle | A script that grades a run's output. |
| Judge | A model that grades a run against a rubric. |
| Readiness audit | `skill-benchmark audit-manifest`. It fails a manifest that is not ready for a paid run, for example one with no near-miss negative cases. |

## Add skill-ci to a repository

You need `mise` and `uv` on your machine. The CI workflow needs GitHub.com. GitHub Enterprise Server does not provide the job fields the workflow uses to find its own revision.

1. Clone skill-ci next to the repository that holds your skills.

2. In that repository, ask your agent to "activate skill-ci". The agent follows `SKILL.md`, which is the full procedure. It does the following:

   - Writes `.github/workflows/skill-checks.yml`, which calls this repository's reusable workflow at one full commit SHA.
   - Adds a Dependabot `github-actions` entry if none covers the workflow, so the SHA gets update pull requests.
   - Adds `SKILL_CI`, `EVALS_DIR`, and the `skill-tasks.toml` include to your `mise.toml`.
   - Downloads the pinned runner.
   - Writes one empty manifest per skill at `evals/<skill>/shared-benchmark.json`.
   - Adds run-output directories to `.gitignore`, because runs save raw agent transcripts.
   - Runs `mise run skill-lint` and `mise run skill-validate`, and reports the results.

   Activation never runs a paid task, never writes a case, and never commits or pushes. You can run it again safely. It keeps existing manifests, workflow inputs, includes, and Dependabot entries.

3. Write cases in each manifest. See [Write test cases for a skill](docs/authoring-cases.md).

4. Run the paid checks when you choose:

   ```sh
   mise run skill-trigger skills/my-skill
   mise run skill-run skills/my-skill
   ```

If you set the repository up by hand, the caller workflow looks like this. Replace the SHA with the full commit SHA of the skill-ci revision you want.

```yaml
name: skill-checks
on: [push, pull_request]
jobs:
  skills:
    uses: mdsmithaustin/skill-ci/.github/workflows/skill-checks.yml@<full-commit-sha>
    with:
      skills-dir: skills
      evals-dir: evals
```

## Keep manifests outside the skills directory

Put each manifest at `evals/<skill>/shared-benchmark.json` at the repository root. Skill installers copy a skill's whole directory to every user. A manifest inside the skill directory would ship your test prompts, expected answers, and oracle scripts to everyone who installs the skill.

The older layout, `<skills-dir>/<skill>/evals/shared-benchmark.json`, still works. In that layout, leave `EVALS_DIR` and `evals-dir` unset, and `skill_paths` are relative to the skill directory instead of the repository root.

In both layouts, case files, `prompt_ref`, and oracle script paths are relative to the manifest's own directory. Keep them next to the manifest.

Use relative `skill_paths` for portable manifests. The coverage check also accepts absolute entries that resolve to the inventoried skill marker, matching the runner. Coverage verifies the binding and case presence; it does not certify portability.

## Tasks

`skill-tasks.toml` defines these mise tasks. Your repository includes that file from its `mise.toml`.

| Task | Where it runs | Cost | What it does |
| --- | --- | --- | --- |
| `skill-lint` | CI and local | Free | Runs the frontmatter checker and the content checker over the skills directory. |
| `skill-package` | Local, and CI when `package-check` is on | Free | Lists every file in each skill package. If `INSTALLED_SKILLS_DIR` is set, also compares each package with its installed copy. See [Check package files and installed copies](docs/packages.md). |
| `skill-coverage` | Local, and CI when `require-populated-manifests` is on | Free | Requires a populated, correctly bound manifest for every skill directory. |
| `skill-validate` | CI and local | Free | Runs `skill-benchmark validate --strict-leakage` on every manifest. |
| `skill-audit` | CI and local | Free | Runs the readiness audit on every manifest. |
| `skill-trigger <skill>` | Local only | Paid | Runs every trigger case on Claude and Codex and records whether the skill loaded. |
| `skill-run <skill>` | Local only | Paid | Runs the readiness audit, then runs the cases in the manifest's `tune` split with and without the skill on Claude and Codex. It grades the runs, judges them, and writes a report. It stops if the audit finds a blocker. |

In CI, the audit skips a manifest that has no cases yet. A scaffolded empty manifest is validated but not audited. Set `require-populated-manifests: true` after authoring cases to require coverage for every skill. This checks inventory and bindings without calling a model.

This repository's own `mise.toml` adds a `test` task that runs the unit tests.

### What the lints check

- `check-skill-frontmatter.py` validates each `SKILL.md` against the agentskills.io metadata rules and the Codex invocation policy. With `trigger-cases` set, it also fails for any skill missing from the trigger declaration file.
- `check-skill-content.py` fails on relative links whose target does not exist, bold skill names that match no known skill, and unclosed code fences. A bold name counts as a skill name when its line contains the word "skill". A conventions file can add name prefixes and retired text for your repository. See [Add your repository's naming conventions to the content check](docs/content-conventions.md).
- `check-pii.py` fails on likely personal data and on GitHub Enterprise hosts named `github.<domain>`, which name an employer. A host after `://`, `@`, `--hostname`, `-h`, `GH_HOST=`, an escaped `\n` or `\t`, or a `host:` or `hostname:` key, quoted or not, fails on any top-level domain. Anywhere else it fails only when the last label is a common top-level domain such as `com`, `net`, `org`, or `io`, so Actions expressions such as `github.event.comment.id` and settings such as `github.copilot.enable` pass. Hosts under `example.com`, `example.net`, `example.org`, `.example`, `.test`, `.invalid`, `.localhost`, `githubassets.com`, and `githubusercontent.com` pass. A made-up company host fails too, so write `github.example.com` for a placeholder. This matters because trigger cases are cut from real session transcripts.

## Configuration

### Workflow inputs

Set these under `with:` in your caller workflow.

| Input | Default | Effect |
| --- | --- | --- |
| `skills-dir` | `skills` | The skills directory. |
| `evals-dir` | empty | Where manifests live. Empty means search inside the skills directory. The job fails if this names a directory that does not exist. |
| `require-manifests` | `false` | Fail when no manifest files are found. An empty scaffolded manifest counts as a file. |
| `require-populated-manifests` | `false` | Require a populated manifest for every skill directory and a `skill_paths` binding to that skill. Validation and readiness audit still apply. |
| `package-check` | `false` | Run the package check. Rejects symlinks and special files in skill packages. |
| `pii-scope` | `skills` | `skills` scans tracked files in the skills directory for personal data. `repository` scans every tracked file. |
| `trigger-cases` | empty | Path to a version-1 trigger declaration file. Leave it empty to skip the coverage check. When set, the frontmatter check also fails for any skill that the file does not declare. See [Trigger declaration file](#trigger-declaration-file). |
| `content-ignore-file` | empty | Path to a list of skill names that live in another repository, one per line, with `#` comments allowed. The content checker does not report mentions of them as broken. |
| `content-link-exceptions-file` | empty | Path to a link-exceptions policy. See [Allow links to files a template creates](docs/link-exceptions.md). |
| `content-conventions-file` | empty | Path to a content conventions file. See [Add your repository's naming conventions to the content check](docs/content-conventions.md). |
| `strict-frontmatter` | `false` | Not implemented. Setting it fails the job. See `TODO.md`. |
| `skill-ci-ref` | empty | Deprecated and ignored. Remove it from your caller. |

### Trigger declaration file

`trigger-cases` is optional. When you set it, the file must use this version-1 format. It has one declaration per skill, and every skill under `skills-dir` needs one.

```json
{
  "version": 1,
  "triggers": [
    {
      "skill": "example",
      "example_request": "set up skill testing in this repo",
      "description_contains": ["set up skill testing"],
      "implicit_allowed": true
    }
  ]
}
```

Each `description_contains` entry must appear in that skill's `description`, compared case-insensitively with whitespace collapsed. `implicit_allowed` must match the skill's Codex invocation policy. The check fails for a missing, duplicate, or stale declaration. It does not run a model. `skill-trigger` measures real triggering from the eval manifest instead.

If your repository keeps its own copy of `check-skill-frontmatter.py`, `check-skill-content.py`, `check-pii.py`, or `requirements.txt` under `tools/`, for example for a pre-commit hook, the workflow fails when that copy differs from the skill-ci copy.

### Environment variables for local tasks

| Variable | Default | Used by | Effect |
| --- | --- | --- | --- |
| `SKILL_CI` | required | all | Path to your skill-ci checkout. |
| `SKILLS_DIR` | `skills` | `skill-lint`, `skill-package`, `skill-coverage`, `skill-validate`, `skill-audit` | The skills directory. `skill-trigger` and `skill-run` take the skill directory as an argument instead. |
| `EVALS_DIR` | unset | tasks that read manifests | Where manifests live. Unset means search inside the skills directory. The directory must be named `evals`, because the runner finds the repository root from that name. A task fails if this names a directory that does not exist. |
| `CONTENT_LINK_EXCEPTIONS_FILE` | unset | `skill-lint` | Path to a link-exceptions policy. |
| `CONTENT_CONVENTIONS_FILE` | unset | `skill-lint` | Path to a content conventions file. |
| `INSTALLED_SKILLS_DIR` | unset | `skill-package` | Installed skills to compare against. |
| `AGENTS` | `claude codex` | `skill-run` | Which agents to run. |
| `RUNS` | `3` | `skill-trigger`, `skill-run` | Repetitions per case. |
| `MODEL` | `sonnet` for `skill-run`, the runner's default for `skill-trigger` | `skill-trigger`, `skill-run` | Model that answers the prompts. In `skill-run` it applies to Claude only. |
| `CODEX_MODEL` | `gpt-5.6-sol` | `skill-run` | Codex model that answers the prompts. `skill-run` sets it explicitly because the current codex-cli rejects the default model configured on the maintainer's machine. |
| `JUDGE_MODEL` | `opus` | `skill-run` | Model that judges the runs. |
| `JUDGE_RUNS` | `3` | `skill-run` | How many times each judge task repeats before the verdicts are merged. |
| `TIMEOUT` | `240` | `skill-run` | Seconds allowed per run. |
| `OUT` | `<checkout>.eval-runs/<skill>/trigger-<timestamp>-<unique>` or `run-<timestamp>-<unique>` | `skill-trigger`, `skill-run` | Output directory beside the consuming checkout. A nonempty value uses your explicit path unchanged. |
| `CODEX_CMD` | `tools/codex-project-only exec ...` | `skill-trigger`, `skill-run` | Command prefix that starts Codex. It does not name a model. `CODEX_MODEL` does. |

The default run directory sits beside the consuming checkout, outside installed skill packages. Each invocation allocates a unique directory. If a skill path contains that default destination, the task stops before calling a model and asks you to set `OUT` outside the skill package. An explicit `OUT` remains your responsibility.

The runner keeps the skills in your home directory out of every answer and trigger run, so a run sees only the skills it mounts. For Claude it also hides your agents, `CLAUDE.md`, MCP servers, and auto memory. Judge runs are sealed further and see no skills at all. The paid tasks still start Claude through `tools/claude-project-only`, which lets a case write files inside the run's temporary workspace. They start Codex through `tools/codex-project-only`, which moves HOME to an empty directory. That move is now redundant.

An answer run refuses to start when a folder above its workspace holds `.claude`, `.agents`, `CLAUDE.md`, or `AGENTS.md`, because Claude and Codex would read them. The default macOS `TMPDIR` passes. If yours sits inside a repository or under a home directory with `~/.claude`, point `TMPDIR` somewhere else.

## Update skill-ci

- **CI.** Each repository's workflow uses the skill-ci SHA it pins. Dependabot opens a pull request when skill-ci changes, and the new SHA takes effect when you merge it.
- **Local tasks.** They use whatever your `SKILL_CI` checkout contains. Pull that checkout to get the latest runner pin.
- **Earlier run directories.** A runner pin can change recorded identities, so re-run `prepare` and every arm before comparing with older runs. The earlier pin to `6634de1` changed trigger protocol hashes and added optional `expected_skills` and `forbidden_skills` lists for catalog routing. Regenerate both trigger comparison arms with this runner. Unscoped queries retain their existing activation rule.

The pinned runner supports `report --fail-on-failures` for offline saved-result gates. It checks `with_skill` by default and permits expected baseline assertion failures while requiring complete evidence across all arms. Rendering remains the default. The runner also ships an [offline captured-edit example](https://github.com/mdsmithaustin/skill-eval-harness/tree/70e83674f787327e3d271310fc64106dc89a2708/examples/edited-file-demo). Its native permission smoke is separate and opt-in.

The current pin, `70e83674f787327e3d271310fc64106dc89a2708`, includes harness PR #22's [fixed recovery cases](https://github.com/mdsmithaustin/skill-eval-harness/blob/70e83674f787327e3d271310fc64106dc89a2708/docs/recovery.md). On supported POSIX hosts, a prepared `run-agent` row with a `recovery` object retains one fixture across a verified checkpoint stop, fresh recovery, and fresh refusal. Successful runs save `recovery.json`, raw process evidence, and file snapshots for a consumer grader. Setup, spawn, or capture failures can leave partial or absent artifacts. Exit code 0 confirms completed runner phases and snapshots. It does not certify a model, provider, or enforced write denial. Rows without `recovery` keep their ordinary one-shot contract.

## What a passing check proves

A green CI run means the lints passed and the manifests are well formed. It does not mean any paid run happened, or that the skill helps. [What a passing check proves](docs/evidence.md) lists what each kind of check can and cannot show.

## Repository layout

```text
SKILL.md                            instructions an agent follows to activate skill-ci
DECISIONS.md                        why the repository is shaped this way
TODO.md                             known gaps, each with its reason
runner.lock                         the one runner pin
skill-tasks.toml                    mise tasks that a repository includes
mise.toml                           this repository's own tools and tasks
lefthook.yml                        pre-commit hook: rejects personal data, runs the unit tests
.github/workflows/skill-checks.yml  the reusable workflow that callers pin
.github/workflows/test.yml          unit tests on Linux and macOS, plus a run of the reusable workflow
.github/fixtures/                   empty scaffold and populated edited-file contracts
.github/dependabot.yml              weekly updates for actions and pip
docs/authoring-cases.md             how to write test cases
docs/link-exceptions.md             the link-exceptions policy
docs/content-conventions.md         the content conventions file
docs/packages.md                    package inspection and copy comparison
docs/evidence.md                    what each kind of check can prove
docs/harvest-skill-optimizer.md     what was imported from skill-optimizer, and why
tools/check-skill-frontmatter.py    frontmatter checker
tools/check-skill-content.py        link, reference, and fence checker
tools/check-pii.py                  personal-data checker
tools/check-skill-package.py        package inventory and copy comparison
tools/check-skill-coverage.py       populated manifest inventory and skill binding check
tools/allocate-eval-output.py       allocates unique run directories outside packages
tools/run_runner.py                 runs the runner pinned in runner.lock
tools/scaffold_manifest.py          writes one empty manifest per skill
tools/claude-project-only           starts Claude with file edits allowed in the run's workspace
tools/codex-project-only            starts Codex with HOME moved to an empty directory
tools/requirements.txt              hashed PyYAML pin for the checkers
tools/test_*.py                     unit tests
```

## Run this repository's tests

```sh
mise run test
```

Without mise:

```sh
uv run --no-project --with-requirements tools/requirements.txt \
	python -m unittest discover -s tools -p 'test_*.py'
```

The tests do not call a model.
