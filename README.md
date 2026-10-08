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

You need `uv` and `git`. `mise` and `lefthook` are optional, and `init` wires them when the repository already uses them.

1. Put the `skill-ci` command on your `PATH`:

   ```sh
   uv tool install git+https://github.com/mdsmithaustin/skill-ci.git
   ```

   This installs the default branch. You install it once per machine. It only has to read the repository's `.skill-ci.toml`, because it then runs the version that file pins.

2. Go to the root of the git repository. Its `skills/` directory holds your skills, one subdirectory each with a `SKILL.md`. Run:

   ```sh
   skill-ci init
   ```

   You can instead tell your agent to "activate skill-ci". The agent follows `SKILL.md`, which runs `skill-ci init` and `skill-ci check` and reports their output.

3. Write cases in each manifest. See [Write test cases for a skill](docs/authoring-cases.md).

4. Run the paid checks when you choose:

   ```sh
   skill-ci trigger skills/my-skill
   skill-ci run skills/my-skill
   ```

### What `init` does

`init` lists what it wrote, updated, and kept, then notes and to-do items. Run it again at any time. It keeps what exists and changes nothing a second time. Commit the files it wrote.

| Step | What it does | It skips the step when |
| --- | --- | --- |
| Pin | Writes `.skill-ci.toml` with `version` set to the newest release tag as an exact tag, plus `skills_dir` and, for external manifests, `evals_dir`. | The file exists. |
| Workflow | Writes `.github/workflows/skill-checks.yml`. | The file exists. `init` adds a note when it does not run `skill-ci check`. |
| lefthook | Adds `skill-ci check --fast` under `pre-commit` and `skill-ci check` under `pre-push`, then runs `lefthook validate`. If lefthook rejects the file, `init` puts the file back and prints a to-do line. Without `lefthook` on `PATH`, it skips the validation. | No `lefthook.yml`, `lefthook.yaml`, `.lefthook.yml` or `.lefthook.yaml` exists. A hook that already runs `skill-ci check` is left alone. |
| no-mistakes | Appends ` && skill-ci check` to `commands.lint` and shows the change. | No `.no-mistakes.yaml` exists, or `commands.lint` already runs `skill-ci check`. |
| mise | Adds the one-line tasks `skill-check`, `skill-lint`, `skill-package`, `skill-coverage`, `skill-validate`, `skill-audit`, `skill-trigger` and `skill-run`. | No `mise.toml` or `.mise.toml` exists. A task you already define is kept. |
| Manifests | Writes one empty `shared-benchmark.json` per skill. | A manifest exists. It stays byte for byte as it was. |
| `.gitignore` | Adds `eval-runs/` and `evals/runs/`, which cover run output kept in those two directories, such as an `out` path under either one. Run output holds raw agent transcripts and must never be committed. | The file already ignores them. |

- **Where it runs.** `init` must run at the repository root. It stops with exit code 2 anywhere else, in a directory outside a git repository, and when the skills directory holds no skill. Pass `--skills-dir DIR` for another skills directory. Pass `--evals-dir DIR` for another evals directory, whose name must be `evals`. Without `--evals-dir` and without a `.skill-ci.toml`, `init` writes manifests to `evals/<skill>/`, or beside their skills when the repository already keeps them there. With a `.skill-ci.toml`, `init` follows its `skills_dir` and `evals_dir`.
- **The network.** `init` asks the source for its newest release tag, so it needs the network. If the source cannot be reached, `init` writes nothing and exits with code 2.
- **No release tag yet.** `init` pins an exact tag. If the source has none, `init` writes nothing and exits with code 2. To follow the branch head until the first tag exists, write `.skill-ci.toml` as below and run `init` again. `init` prints this file, with your skills and evals directories. `skill-ci update` does not move a `main` pin, so change it to a tag by hand when one exists.

  ```toml
  version = "main"
  skills_dir = "skills"
  evals_dir = "evals"
  ```

  A `.skill-ci.toml` without `evals_dir` tells `init` to keep manifests beside their skills.
- **The workflow names no version.** The job installs whatever `source` serves, and that `skill-ci` reads `.skill-ci.toml` and runs the pinned version. The version lives in one file. The workflow installs uv with one line, `pip install uv==0.12.7`, so a different install method changes that line only.
- **no-mistakes.** no-mistakes reads `commands` from the default branch, not from the branch you push. A change to `commands.lint` applies after it merges there. When `.no-mistakes.yaml` exists and `commands.lint` is empty, `init` leaves the file alone, because setting `commands.lint` would replace the agent's lint duty. It prints a `repository_overrides` entry with `commands.lint.additional` instead. Add that entry to `~/.no-mistakes/config.yaml` on each machine that gates the repository. It applies on that machine at once and is not committed.
- **Exit codes.** `init` exits 0 when it finished, 1 when it printed a `to do:` line, and 2 when it refused to start. A `to do:` line names a change that `init` could not make, such as a lefthook hook written as `jobs`. It prints the entry to add by hand when there is one.

If you set the repository up by hand, write `.skill-ci.toml` as described in [The `.skill-ci.toml` file](#the-skill-citoml-file), and this workflow. `init` writes it with the `source` from your `.skill-ci.toml`.

```yaml
name: skill-checks
on: [push, pull_request]
permissions:
  contents: read
jobs:
  skills:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    env:
      SKILL_CI_SOURCE: "https://github.com/mdsmithaustin/skill-ci.git"
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - run: pip install uv==0.12.7
      - run: uv tool run --from "git+$SKILL_CI_SOURCE" skill-ci check
```

## The `.skill-ci.toml` file

A repository names its skill-ci version once, in `.skill-ci.toml` at its root. Every place that runs skill-ci runs that version, whether it starts in your terminal, lefthook, mise, no-mistakes, or CI. An example:

```toml
version = "v1.0.0"
skills_dir = "skills"
evals_dir = "evals"
```

### Keys

`version` is required. It is `latest`, `main`, or an exact tag. A tag is `v` and three whole numbers, such as `v1.0.0`, and `latest` ignores tags of any other shape. Any other value is an error, and so is a missing `version`. The other keys are optional. A key applies to every command that takes the matching flag, and a flag on the command line overrides the file. A repeated `--agent` replaces the whole `agents` list. A switch such as `--require-manifests` has a `--no-require-manifests` form that overrides a `true` in the file.

| Key | Type | Default | Used by | Effect |
| --- | --- | --- | --- | --- |
| `version` | string | none, required | all | `latest` runs the newest `v*` tag. `main` runs the head of the source's `main` branch. A tag runs that tag's commit. |
| `source` | string | `https://github.com/mdsmithaustin/skill-ci.git` | all | Where skill-ci fetches itself from. See [`source`](#source). |
| `skills_dir` | path | `skills` | `init`, `lint`, `package`, `coverage`, `validate`, `audit`, `check` | The directory whose children each hold a `SKILL.md`. |
| `evals_dir` | path | unset | `init`, `coverage`, `validate`, `audit`, `check`, `trigger`, `run` | Where manifests live. Unset means each manifest sits at `<skill>/evals/`. The directory must be named `evals`. |
| `pii_scope` | `skills` or `repository` | `skills` | `check` | `skills` scans tracked files in the skills directory for personal data. `repository` scans every tracked file. |
| `trigger_cases` | path | unset | `lint`, `check` | A version-1 trigger declaration file. See [Trigger declaration file](#trigger-declaration-file). |
| `content_ignore_file` | path | unset | `lint`, `check` | Skill names that live in another repository, separated by commas or newlines, with `#` comment lines allowed. |
| `content_link_exceptions_file` | path | unset | `lint`, `check` | A link-exceptions policy. See [Allow links to files a template creates](docs/link-exceptions.md). |
| `content_conventions_file` | path | unset | `lint`, `check` | A content conventions file. See [Add your repository's naming conventions to the content check](docs/content-conventions.md). |
| `require_manifests` | boolean | `false` | `check` | Fail when no manifest is found. |
| `require_populated_manifests` | boolean | `false` | `check` | Require a manifest with cases bound to every skill. |
| `package` | boolean | `false` | `check` | Inspect every package entry and reject symlinks and special files. |
| `out` | path | a new directory under `<checkout>.eval-runs/<skill>/` | `trigger`, `run` | The output directory, which must sit outside the skill package. |
| `runs` | whole number | `3` | `trigger`, `run` | Runs per query or variant. |
| `agents` | list of `claude` and `codex` | both | `run` | The agents the paired benchmark runs. `trigger` always runs both. |
| `model` | string | `sonnet` | `run` | The Claude model that answers the prompts. |
| `matrix_model` | string | unset | `trigger` | One model for every agent. Unset, each agent uses its own model list. |
| `codex_model` | string | `gpt-5.6-sol` | `run` | The Codex model that answers the prompts. |
| `codex_cmd` | string | the bundled Codex launcher with a read-only sandbox | `trigger`, `run` | The command line that starts Codex. It does not name a model. |
| `timeout` | whole number | `240` | `run` | Seconds allowed per run. |
| `judge_model` | string | `opus` | `run` | The Claude model that judges the runs. |
| `judge_runs` | whole number | `3` | `run` | How many times each judge task repeats before the verdicts are merged. |

An unknown key is an error that names the key and, when one is close, suggests the right spelling. The version that runs decides what is unknown, so a key from a newer release is not an error to an older command that only hands the run on. The key is an error when the pin is the commit already running, when the version cannot be resolved, and in every command under the pinned run itself. Otherwise the pinned run judges it. Skill-ci checks every known key for the right type before it resolves a version or hands off. `update` ignores unknown keys.

An invalid `.skill-ci.toml` makes every command exit with code 2, `--help` and `--version` included, because the file decides which version runs.

### Where the file is found, and what its paths mean

- **Search.** skill-ci looks for `.skill-ci.toml` in the working directory, then in each parent directory up to the repository root. The search stops at the repository root, the first directory that holds a `.git` entry. Outside a repository it looks in the working directory only. If the working directory has been deleted, the lookup is skipped and the run is unpinned.
- **Paths in the file** are relative to the directory that holds the file. `~` expands to your home directory, and an absolute path stays as written. In a symlinked `.skill-ci.toml`, relative paths resolve from the directory of the link. Path flags on the command line resolve from the working directory.
- **Control characters.** A path setting is rejected when it contains a control character, a format character, or a line or paragraph separator, such as U+202E. Other invisible characters, such as variation selectors, Hangul fillers, U+034F, unassigned code points and private-use code points, are accepted and print as written.

### `source`

`source` names where skill-ci installs itself from, and `latest` and `main` read their tags and branch from it. It runs on your machine and in CI with your permissions, so name a repository you trust. It may be:

- an `https://`, `ssh://` or `file:///absolute/path` URL. skill-ci lowercases the scheme, and it rejects `http://`, `git://` and every other scheme.
- a plain path, which is relative to the file, may start with `~`, and becomes a `file://` URL.

skill-ci rejects a `source` that:

- holds a control character, a format character, or a line or paragraph separator.
- is an scp-style address such as `git@host:path`. Write `ssh://git@host/path`.
- carries credentials. Only an ssh user name is allowed, as in `ssh://git@host/path`. Any other `@` in an `https://` URL, or a second `@` in an `ssh://` URL, draws the credentials message. In an `https://` URL, write `%40` for a literal `@`. Keep a token for a private mirror in a git credential helper.
- has a query, a fragment, white space, a port that is not a number, no host, or a character outside ASCII in its scheme or host. Write an international host as punycode.

A `source` that needs a passphrase or a host-key answer does not wait for you. The version lookup runs git without a terminal and gives up after 5 seconds. Load your key into `ssh-agent` and accept the host key first.

### Prerequisites

skill-ci needs `git` to read the source's tags, and `uv` to run a pinned version. Without `uv` on `PATH`, a run that has to hand off exits with code 127.

## Run the pinned version

When `.skill-ci.toml` names a version, skill-ci resolves it to a commit and runs that commit.

1. **Resolve.** An exact tag resolves to the commit that tag names. `latest` resolves to the newest `v*` tag. `main` resolves to the head of the `main` branch. skill-ci asks the source with `git ls-remote`, which gives up after 5 seconds.
2. **Hand off.** If the commit differs from the running one, skill-ci runs `uv tool run --isolated --from git+<source>@<commit> skill-ci <arguments>`. It always passes the commit, never the tag. It first tries with uv offline, and tries once more with network access when uv could not start. It removes `PYTHONPATH` and `PYTHONHOME` from the pinned run's environment.
3. **Run.** The pinned command runs your arguments, and its exit status becomes skill-ci's.

Every command that runs prints one line to standard error first, so a local log and a CI log show the commit they used. `--help`, `--version` and a usage error are the exceptions, and `--version` prints the same text on standard output. A pinned run prints `skill-ci v1.0.0 (<commit>)`, where the name is the tag, `main`, or the tag that `latest` chose. An unpinned run prints `skill-ci <package version> (<commit>)`, and `commit unknown` when skill-ci was not installed from a git commit. The line goes to standard error so that standard output stays clean for piping.

**`SKILL_CI_PINNED`.** skill-ci sets `SKILL_CI_PINNED=<commit>` for the pinned run, so that run never hands off again. The pinned run removes it, and `SKILL_CI_STARTED`, from the environment before any check runs. Do not set either yourself. A `SKILL_CI_PINNED` that is not a full commit, or that names a commit other than the one installed, fails with exit code 126.

**`SKILL_CI_DEBUG=1`** prints a full traceback for an unexpected error in place of its one-line message. It does not change the per-check lines that `check` prints.

### The cache and offline runs

skill-ci keeps the answers it gets from each source in `$XDG_CACHE_HOME/skill-ci/refs/`, or in `~/.cache/skill-ci/refs/` when `XDG_CACHE_HOME` is unset or relative. There is one file per source.

- **An exact tag** is served from the cache for a day without asking the source. After that, or when the cache lacks the tag, skill-ci asks the source again. A tag that you move on the source keeps its old commit until the cache expires. A tag that you publish is found at once by a pin that names it, but the newer-tag notice sees it only after the cache expires.
- **`latest` and `main`** ask the source on every run.
- **Offline**, skill-ci uses the cached answer. For `latest` and `main` it prints `skill-ci: warning: cannot reach <source> (<reason>); running <commit>, which <version> named on <date> UTC`. An exact tag that is in the cache runs from it with no warning.
- **No cache**, or an exact tag that the cache lacks, exits with code 2. The message says no version was ever resolved from the source, or that the cached versions have no such tag.
- **`update` needs the network.** It never reads the cache.

### Update the pin

`skill-ci update` rewrites `version` in `.skill-ci.toml` to the newest release tag and leaves every other key and comment alone. It keeps the line endings and the file mode, and it follows a symlink to the file it names.

- It moves only an exact tag. On a `latest` or `main` pin it prints that the version floats and leaves the file unchanged, with exit code 0.
- It never moves a pin backwards. If the pin is newer than the newest tag, it exits with code 2 and leaves the file unchanged.
- It refuses a file whose `version` key is quoted, or that holds a second line shaped like a version line, such as one inside a multi-line string. It exits with code 2 and leaves the file unchanged.
- It replaces the file with a renamed copy. It fails in a directory you cannot write to. It breaks hard links and drops extended attributes.

On an exact-tag pin, every run prints a notice on standard error when a newer tag exists: `skill-ci: v1.2.0 is newer than the pinned v1.0.0; run skill-ci update to move the pin`. The notice comes from the cached tag list, so it can lag by a day.

Pins start at v1.0.0, the first release that understands the pin. Do not tag an earlier commit yourself and pin it. That revision cannot tell skill-ci that the pinned run started, so a run can happen twice and then exit with code 126, which would repeat a paid `run`.

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | The command finished and every check passed. |
| 1 | A check failed, a command could not finish its work, or an unexpected error stopped it. `init` also exits 1 when it printed a `to do:` line. |
| 2 | A usage error, an invalid `.skill-ci.toml`, a version that cannot be resolved, a failed `update`, or a command that refused to start, such as `init` outside the repository root. |
| 126 | skill-ci could not hand the run to the pinned commit. The causes are listed below. |
| 127 | `uv` is not on `PATH` when a hand-off is needed, or the harness is missing from skill-ci's environment. |
| 128 plus a signal number | A signal stopped skill-ci, or the pinned command or a harness command died of that signal. Ctrl-C gives 130. |

Exit code 126 has these causes, and each prints its reason:

- uv could not start the pinned commit, offline or with network access, and so no pinned run began. The message says to see the uv error above it.
- skill-ci could not run `uv` at all.
- skill-ci could not record that the pinned run started.
- `SKILL_CI_PINNED` is not a full commit.
- `SKILL_CI_PINNED` is set, but this skill-ci was not installed from a git commit.
- `SKILL_CI_PINNED` names a commit other than the one installed.

### Signals

- **These signals stop a run:** `SIGINT`, `SIGTERM`, `SIGHUP`, `SIGQUIT`, `SIGUSR1`, `SIGUSR2`, `SIGALRM`, `SIGPIPE`, `SIGABRT`, `SIGVTALRM`, `SIGPROF` and `SIGXCPU`, plus `SIGPOLL` and `SIGPWR` where the system has them. Each one ends the child and its whole process group. skill-ci sends `SIGINT` to the child first. When the grace period passes, or once the child has exited, it sends `SIGKILL` to the child's whole process group. The grace period is 3 seconds, or 5 seconds for the pinned run. skill-ci exits with 128 plus the number of the first signal it got.
- **Other signals** are not forwarded, such as `SIGWINCH` from a terminal resize or `SIGINFO`.
- **Ctrl-Z** suspends skill-ci but not its child. The child keeps running until it finishes. Resume skill-ci with `fg`.
- **Fault signals** keep their default action and are not forwarded: `SIGSEGV`, `SIGBUS`, `SIGFPE`, `SIGILL`, `SIGTRAP`, `SIGEMT` and `SIGSYS`.
- **A signal ignored at startup**, as under `nohup` or in a background job, stays ignored for skill-ci and for its child. `SIGINT` is the exception. Every child starts with `SIGINT` at its default action, because skill-ci stops its children with it.

## Keep manifests outside the skills directory

Put each manifest at `evals/<skill>/shared-benchmark.json` at the repository root. Skill installers copy a skill's whole directory to every user. A manifest inside the skill directory would ship your test prompts, expected answers, and oracle scripts to everyone who installs the skill.

The older layout, `<skills-dir>/<skill>/evals/shared-benchmark.json`, still works. In that layout, leave `EVALS_DIR` and `evals-dir` unset, and `skill_paths` are relative to the skill directory instead of the repository root.

In both layouts, case files, `prompt_ref`, and oracle script paths are relative to the manifest's own directory. Keep them next to the manifest.

Use relative `skill_paths` for portable manifests. The coverage check also accepts absolute entries that resolve to the inventoried skill marker, matching the runner. Coverage verifies the binding and case presence; it does not certify portability.

## Tasks

`skill-ci init` adds these as mise tasks when the repository has a `mise.toml`. Each task is one line that calls the `skill-ci` subcommand of the same name, so `mise run skill-lint` and `skill-ci lint` do the same thing.

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

Run `skill-ci update` to move an exact-tag pin to the newest release. See [Update the pin](#update-the-pin). Your terminal, hooks, mise tasks, no-mistakes, and CI all run the version in `.skill-ci.toml`, so one commit moves them together.

- **Earlier run directories.** A runner pin can change recorded identities, so re-run `prepare` and every arm before comparing with older runs. The earlier pin to `6634de1` changed trigger protocol hashes and added optional `expected_skills` and `forbidden_skills` lists for catalog routing. Regenerate both trigger comparison arms with this runner. Unscoped queries retain their existing activation rule.

The pinned runner supports `report --fail-on-failures` for offline saved-result gates. It checks `with_skill` by default and permits expected baseline assertion failures while requiring complete evidence across all arms. Rendering remains the default. The runner also ships an [offline captured-edit example](https://github.com/mdsmithaustin/skill-eval-harness/tree/70e83674f787327e3d271310fc64106dc89a2708/examples/edited-file-demo). Its native permission smoke is separate and opt-in.

The current pin, `15cc6126bb01673884dee14d1a87a46f618d63ea`, includes harness PR #22's [fixed recovery cases](https://github.com/mdsmithaustin/skill-eval-harness/blob/70e83674f787327e3d271310fc64106dc89a2708/docs/recovery.md). On supported POSIX hosts, a prepared `run-agent` row with a `recovery` object retains one fixture across a verified checkpoint stop, fresh recovery, and fresh refusal. Successful runs save `recovery.json`, raw process evidence, and file snapshots for a consumer grader. Setup, spawn, or capture failures can leave partial or absent artifacts. Exit code 0 confirms completed runner phases and snapshots. It does not certify a model, provider, or enforced write denial. Rows without `recovery` keep their ordinary one-shot contract.

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
uv run --extra test python -m unittest discover -s tests -p 'test_*.py'
```

The tests do not call a model.
