# skill-ci

skill-ci tests Agent Skills. A skill is a directory with a `SKILL.md` file that tells an AI coding agent, such as Claude Code or Codex, how to do a task. If a repository holds skills, skill-ci gives it two kinds of checks:

- **Free checks.** `skill-ci check` lints each `SKILL.md`, finds broken links, rejects personal data, and validates the test-case files. No model is called. Run it from a terminal, a git hook, no-mistakes, or any CI service. `skill-ci init` writes a GitHub Actions workflow that runs it on each pull request and on each push to the default branch.
- **Paid checks on your machine.** `skill-ci trigger` and `skill-ci run` run Claude and Codex on test prompts. One checks whether the skill loads when it should. The other runs each prompt with and without the skill and grades whether the skill helped. They use your own logins and spend model budget. They never run in CI.

skill-ci is a command that uv installs from git. A repository names its skill-ci version once, in `.skill-ci.toml`, and every place that runs skill-ci runs that version. skill-ci does not have its own test runner. It installs [`skill-eval-harness-ext`](https://github.com/mdsmithaustin/skill-eval-harness), a fork of skill-eval-harness, at the commit that its own `pyproject.toml` pins, and runs that. `DECISIONS.md` explains why, and when to stop using the fork.

skill-ci is also a skill itself. In a repository that holds skills, tell your agent "activate skill-ci" and it sets the repository up by following `SKILL.md`.

## Terms

| Term | Meaning |
| --- | --- |
| Skills directory | The directory whose children each hold a `SKILL.md`. Set by `skills_dir` in `.skill-ci.toml` or `--skills-dir` on the command line. Default `skills`. |
| Manifest | The test file for one skill, `shared-benchmark.json`, in skill-eval-harness format version 1 or 2. It names the skill, its files (`skill_paths`), the two variants, and a list of cases. |
| Case | One test prompt in a manifest, with the assertions that grade it. |
| Trigger case | A case that checks whether the agent loads the skill for a prompt. `should_trigger` says whether it should. |
| Outcome case | A case that checks whether the skill made the agent's result better. |
| Variant | One side of a paired run. `with_skill` has the skill installed. `without_skill` does not. |
| Oracle | A script that grades a run's output. |
| Judge | A model that grades a run against a rubric. |
| Readiness audit | `skill-ci audit`, which runs `skill-benchmark audit-manifest`. It fails a manifest that is not ready for a paid run, for example one with no near-miss negative cases. |
| Pin | The `version` in `.skill-ci.toml`. It is an exact tag, `latest`, or `main`. |
| Source | The git URL that skill-ci installs itself from. The `source` key sets it, and it defaults to github.com. |

## Add skill-ci to a repository

You need `uv` and `git`. `mise` and `lefthook` are optional, and `init` wires them when the repository already uses them.

1. Put the `skill-ci` command on your `PATH`:

   ```sh
   uv tool install git+https://github.com/mdsmithaustin/skill-ci.git
   ```

   This installs the default branch. You install it once per machine. It only has to read the repository's `.skill-ci.toml`, because it then runs the version that file pins.

   If uv warns that `~/.local/bin` is not on your `PATH`, the command is installed but your shell cannot find it. Run `uv tool update-shell` and open a new terminal.

2. Go to the root of the git repository. Its `skills/` directory holds your skills, one subdirectory each with a `SKILL.md`. Run:

   ```sh
   skill-ci init
   ```

   You can instead tell your agent to "activate skill-ci". The agent follows `SKILL.md`, which runs `skill-ci init` and `skill-ci check` and reports their output. A headless agent such as `claude -p` cannot ask before it runs a command. Allow skill-ci first with a permission rule such as `Bash(skill-ci:*)`, or use an interactive session.

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
| Workflow | Writes `.github/workflows/skill-checks.yml` with one job, `skill-checks`. It runs on each pull request and on each push to the default branch. A newer push to a pull request cancels the older run. `init` reads the default branch from the local `origin/HEAD` ref that `git clone` sets, then from the checked-out branch, and uses `main` when git names neither. It prints the branch it chose. | The file exists. `init` adds a note when it does not run `skill-ci check`. |
| lefthook | Adds `skill-ci check --fast` under `pre-commit` and `skill-ci check` under `pre-push`, then runs `lefthook validate`. See [lefthook](#lefthook). If lefthook rejects the file, `init` puts the file back and prints a to-do line. Without `lefthook` on `PATH`, it skips the validation. | No `lefthook.yml`, `lefthook.yaml`, `.lefthook.yml` or `.lefthook.yaml` exists. A hook that already runs `skill-ci check` is left alone. |
| no-mistakes | Appends ` && skill-ci check` to `commands.lint` and shows the change. See [no-mistakes](#no-mistakes). | No `.no-mistakes.yaml` exists, or `commands.lint` already runs `skill-ci check`. |
| mise | Adds the one-line tasks `skill-check`, `skill-lint`, `skill-package`, `skill-coverage`, `skill-validate`, `skill-audit`, `skill-trigger` and `skill-run`, each with a one-line `description`. | No `mise.toml` or `.mise.toml` exists. A task you already define is kept. |
| Manifests | Writes one empty `shared-benchmark.json` per skill. | A manifest exists. It stays byte for byte as it was. |
| `.gitignore` | Adds `eval-runs/` and `evals/runs/`, which cover run output kept in those two directories, such as an `out` path under either one. Run output holds raw agent transcripts and must never be committed. | The file already ignores them. |

- **Where it runs.** `init` must run at the repository root. It stops with exit code 2 anywhere else, in a directory outside a git repository, and when the skills directory holds no skill. Pass `--skills-dir DIR` for another skills directory. Pass `--evals-dir evals` to keep manifests in `evals/<skill>/`. A directory given to `--evals-dir` must be named `evals`, and every skill must sit inside its parent, because each manifest's `skill_paths` start at that parent. Use `evals` at the repository root. Without `--evals-dir` and without a `.skill-ci.toml`, `init` writes manifests to `evals/<skill>/`, or beside their skills when the repository already keeps them there. With a `.skill-ci.toml`, `init` follows its `skills_dir` and `evals_dir`.
- **Flags and the file.** A flag overrides the file for that run of `init` only. `init` never edits an existing `.skill-ci.toml`, so a flag that the file does not repeat sends manifests to a place that `skill-ci check` does not search. After `init --evals-dir evals`, add `evals_dir = "evals"` to the file. Otherwise `check` reports `manifests checked: 0`.
- **The network.** `init` asks the source for its newest release tag, so it needs the network. If the source cannot be reached, `init` writes nothing and exits with code 2.
- **No release tag yet.** `init` pins an exact tag. If the source has none, `init` writes nothing and exits with code 2. To follow the branch head until the first tag exists, write `.skill-ci.toml` as below and run `init` again. `init` prints this file, with your skills and evals directories. `skill-ci update` does not move a `main` pin, so change it to a tag by hand when one exists.

  ```toml
  version = "main"
  skills_dir = "skills"
  evals_dir = "evals"
  ```

  A `.skill-ci.toml` without `evals_dir` tells `init` to keep manifests beside their skills.
- **The workflow names no version.** The job installs whatever `source` serves, and that `skill-ci` reads `.skill-ci.toml` and runs the pinned version. The version lives in one file. The workflow installs uv with one line, `pip install uv==0.12.7`, so a different install method changes that line only.
- **no-mistakes.** See [no-mistakes](#no-mistakes).
- **mise.** See [Commands](#commands) for the tasks. From mise 2026.8.9 on, `mise run` trusts the repository's `mise.toml` without asking. An older mise runs no task from a config file it does not trust, so run `mise trust` once in each clone. In paranoid mode, run `mise trust` again after each edit to the file, including the one `init` makes.
- **Exit codes.** `init` exits 0 when it finished, 1 when it printed a `to do:` line, and 2 when it refused to start. A `to do:` line names a change that `init` could not make, such as a lefthook hook written as `jobs`. It prints the entry to add by hand when there is one.

If you set the repository up by hand, write `.skill-ci.toml` as described in [The `.skill-ci.toml` file](#the-skill-citoml-file), and this workflow. Name your default branch under `push`. `init` writes it with the `source` from your `.skill-ci.toml`.

```yaml
name: skill-checks
on:
  push:
    branches: ["main"]
  pull_request:
permissions:
  contents: read
concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.sha }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
jobs:
  skill-checks:
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

## Use skill-ci with hooks, no-mistakes, GitHub Enterprise Server, and other CI

Every tool in this section runs the one `skill-ci` command. None of them records a version, because `skill-ci` reads the version from `.skill-ci.toml`. Hooks run in addition to CI and never instead of it, since anyone can skip a hook with `--no-verify`.

### lefthook

`init` adds two entries to your lefthook file and runs `lefthook validate`. To add them by hand:

```yaml
pre-commit:
  commands:
    skill-ci-check-fast:
      run: skill-ci check --fast
pre-push:
  commands:
    skill-ci-check:
      run: skill-ci check
```

Then run `lefthook validate`, and `lefthook install` once in each clone to activate the hooks. `skill-ci check --fast` runs the personal-data scan on staged files and the lint checks. Measured on 2026-10-06 on a repository of 56 skills, lint took 0.2 to 0.4 seconds and the staged scan 0.07 seconds, so `--fast` fits a pre-commit hook. `skill-ci check` also validates and audits every manifest, so it belongs before a push.

### no-mistakes

no-mistakes runs `commands.lint` from `.no-mistakes.yaml`. `init` handles the two cases.

- **`commands.lint` is set.** `init` appends ` && skill-ci check` to the value and shows the change. Your command still runs first.
- **`commands.lint` is empty.** `init` leaves the file alone, because setting `commands.lint` would replace the agent's lint duty. It prints a `repository_overrides` entry with `commands.lint.additional` instead:

  ```yaml
  repository_overrides:
    https://example.com/acme/repo.git:
      commands:
        lint:
          additional:
            - skill-ci check
  ```

  Add that entry to `~/.no-mistakes/config.yaml` on each machine that gates the repository. It applies on that machine at once and is not committed. `init` keys the entry by the `origin` remote URL. When that URL holds an `@`, which marks a user name or a token, `init` prints `<remote URL>` in its place and adds a note. The user name or token never reaches the output. In `config.yaml`, write the URL without them. With no `origin`, the entry names `<remote URL>` and no note follows.

no-mistakes reads `commands` from the default branch, not from the branch you push. A change to `commands.lint` applies after it merges there.

### GitHub Enterprise Server

GitHub Enterprise Server (GHES) cannot call a reusable workflow from github.com, so skill-ci no longer ships one. The version lives in `.skill-ci.toml`, a plain file in your repository. The `source` key tells skill-ci where to fetch itself. It defaults to github.com. On a network that blocks github.com, point it at a mirror on your instance.

1. Mirror skill-ci's branches into your instance, and leave its tags behind. Use a bare clone, which leaves out the `refs/pull/*` refs that GitHub refuses to receive:

   ```sh
   git clone --bare https://github.com/mdsmithaustin/skill-ci.git
   git -C skill-ci.git push --all --no-follow-tags https://ghes.example.com/acme/skill-ci.git
   ```

   The commits that upstream tags point to carry the github.com harness line. `latest`, the newer-tag notice, and `skill-ci update` pick the highest `v*` tag on the source. A copied upstream tag could therefore send a pin to a commit that cannot install on your network.

2. Mirror the harness the same way, from `https://github.com/mdsmithaustin/skill-eval-harness.git`. skill-ci installs `skill-eval-harness-ext` from the git URL on one line of its `pyproject.toml`, so a mirror of skill-ci alone still reaches github.com. Clone your mirror of skill-ci and change that line to name your mirror of the harness at the same commit. Commit the change on the default branch, because the install in step 3 and the install in the workflow both take that branch. Then tag the commit with a release tag of your own, such as `v1.0.0`, and push the branch and the tag. The tag names your commit, which can be ahead of upstream's latest release. The pinned run installs the tagged commit, so the tag carries the change too. skill-ci has no tooling for this step.

   ```sh
   git clone https://ghes.example.com/acme/skill-ci.git skill-ci-edit
   cd skill-ci-edit
   $EDITOR pyproject.toml   # replace the URL on the skill-eval-harness-ext line
   git commit -am "chore: use the internal harness mirror"
   git tag v1.0.0
   git push origin HEAD v1.0.0
   ```

3. In your repository, install skill-ci from the mirror, and write `.skill-ci.toml` with the mirror as `source` and your tag as `version`:

   ```sh
   uv tool install "git+https://ghes.example.com/acme/skill-ci.git"
   ```

   ```toml
   version = "v1.0.0"
   source = "https://ghes.example.com/acme/skill-ci.git"
   skills_dir = "skills"
   evals_dir = "evals"
   ```

4. Run `skill-ci init`, which writes the workflow with that `source`, and commit what it wrote. The workflow uses the `actions/checkout` action. If your instance does not offer it, replace that step with your own checkout step.

The workflow installs uv with `pip install uv==0.12.7`, and runners on a restricted network need three adjustments.

- Point pip and uv at your package mirror. They read different settings, so set both `PIP_INDEX_URL` and `UV_DEFAULT_INDEX`.
- Put Python 3.12 or later on the runner. Otherwise uv downloads one from `releases.astral.sh`.
- If pip stops with `externally-managed-environment` on a self-hosted runner, change the `pip install uv==0.12.7` line in the workflow to install uv in a virtual environment, or by another method.

To take a later upstream release, merge it into a clone of your mirror's default branch with `git pull --no-rebase https://github.com/mdsmithaustin/skill-ci.git v1.1.0`. That merges the release commit and does not copy its tag. If the merge conflicts on the harness line in `pyproject.toml`, keep your mirror's URL and take the release's commit hash. Tag the merge with your next release tag, such as `v1.1.0`. When the release pins a newer harness commit, push the harness to its mirror again from a fresh bare clone first. Then push the branch and the tag.

`source` may not carry credentials. A private mirror authenticates through a git credential helper on the runner.

### Any other CI

A CI service that runs shell commands can run the same check. The job needs `git`, `pip`, and network access to the `source`, to the harness's git URL, and to a Python package index. uv also downloads Python 3.12 or later when the runner has none. Three commands do it:

```sh
pip install uv==0.12.7
SKILL_CI_SOURCE="https://github.com/mdsmithaustin/skill-ci.git"
uv tool run --from "git+$SKILL_CI_SOURCE" skill-ci check
```

Use the `source` from your `.skill-ci.toml`. The first command installs uv. The second sets a shell variable that holds the source. skill-ci does not read that variable, but the workflow that `init` writes uses the same name. The third command installs skill-ci from that source. That skill-ci then reads `.skill-ci.toml` and runs the pinned version. `skill-ci check` exits 0 when every check passes and nonzero when one fails, so the service fails the job without more setup. If pip stops with `externally-managed-environment`, create a virtual environment first, or install uv another way. The job prints `skill-ci <version> (<commit>)` first, so its log shows the commit it ran.

## The `.skill-ci.toml` file

A repository names its skill-ci version once, in `.skill-ci.toml` at its root. Every place that runs skill-ci runs that version, whether it starts in your terminal, lefthook, mise, no-mistakes, or CI. [How skill-ci is distributed](DECISIONS.md#how-skill-ci-is-distributed) gives the reasons. An example:

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
| `evals_dir` | path | unset | `init`, `coverage`, `validate`, `audit`, `check`, `trigger`, `run` | Where manifests live. Unset means each manifest sits at `<skill>/evals/`. The directory must be named `evals`, and every skill must sit inside its parent. |
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
- carries credentials. Only an ssh user name is allowed, as in `ssh://git@host/path`. Any other `@` in an `https://` URL, or a second `@` in an `ssh://` URL, draws the credentials message. In an `https://` URL, write `%40` for a literal `@`. An `@` in the path of a `file://` or `ssh://` URL draws the message too, as in `file:///abs/repo@2` or `ssh://host/p@th`. Name a local repository whose path holds an `@` as a plain path, such as `/abs/repo@2`. Keep a token for a private mirror in a git credential helper.
- has a query, a fragment, white space, a port that is not a number, no host, or a character outside ASCII in its scheme or host. Write an international host as punycode.

A `source` that needs a passphrase or a host-key answer does not wait for you. The version lookup runs git without a terminal and gives up after 5 seconds. Load your key into `ssh-agent` and accept the host key first.

### Prerequisites

skill-ci needs `git` to read the source's tags, and `uv` to run a pinned version. Without `uv` on `PATH`, a run that has to hand off exits with code 127.

## Run the pinned version

When `.skill-ci.toml` names a version, skill-ci resolves it to a commit and runs that commit.

1. **Resolve.** An exact tag resolves to the commit that tag names. `latest` resolves to the newest `v*` tag. `main` resolves to the head of the `main` branch. skill-ci asks the source with `git ls-remote`, which gives up after 5 seconds, unless it asked less than a day ago. See [The cache and offline runs](#the-cache-and-offline-runs).
2. **Hand off.** If the commit differs from the running one, skill-ci runs `uv tool run --isolated --from git+<source>@<commit> skill-ci <arguments>`. It always passes the commit, never the tag. It first tries with uv offline, and tries once more with network access when uv could not start. It removes `PYTHONPATH` and `PYTHONHOME` from the pinned run's environment.
3. **Run.** The pinned command runs your arguments, and its exit status becomes skill-ci's.

Every command that runs prints one line to standard error first, so a local log and a CI log show the commit they used. With a pin, skill-ci resolves it before it reads the arguments, so `--help`, `--version` and a usage error print that line too, with any offline warning or newer-tag notice. Without a pin, and for `update`, those three print no version line on standard error. `--version` also prints `skill-ci <package version> (<commit>)` on standard output. A pinned run prints `skill-ci v1.0.0 (<commit>)`, where the name is the tag, `main`, or the tag that `latest` chose. An unpinned run prints `skill-ci <package version> (<commit>)`, and `commit unknown` when skill-ci was not installed from a git commit. The line goes to standard error so that standard output stays clean for piping.

**`SKILL_CI_PINNED`.** skill-ci sets `SKILL_CI_PINNED=<commit>` for the pinned run, so that run never hands off again. The pinned run removes it, and `SKILL_CI_STARTED`, from the environment before any check runs. Do not set either yourself. A `SKILL_CI_PINNED` that is not a full commit, or that names a commit other than the one installed, fails with exit code 126.

**`SKILL_CI_DEBUG=1`** prints a full traceback for an unexpected error in place of its one-line message. It does not change the per-check lines that `check` prints.

### The cache and offline runs

skill-ci keeps the answers it gets from each source in `$XDG_CACHE_HOME/skill-ci/refs/`, or in `~/.cache/skill-ci/refs/` when `XDG_CACHE_HOME` is unset or relative. There is one file per source.

- **Every pin** is served from the cache for a day without asking the source. After that skill-ci asks the source again. Each answer from a source replaces that source's whole cache file, so any lookup of the same source, such as `update` or an `init` with no `.skill-ci.toml`, starts the day again.
- **An exact tag** that the cache lacks is looked up at once, so a tag that you publish is found by a pin that names it. A tag that you move on the source can keep its old commit for up to a day. The newer-tag notice can take up to a day to see a new tag.
- **`latest` and `main`** can run a commit up to a day older than the source's. CI starts with no cache, so it asks the source and can run newer code than your machine. Run `skill-ci update` to look the pin up now.
- **Offline**, a cached answer less than a day old runs as usual, since skill-ci does not ask the source. Once the cache is older, skill-ci tries the source, fails, and uses the cached answer. For `latest` and `main` it then prints `skill-ci: warning: cannot reach <source> (<reason>); running <commit>, which <version> named on <date> UTC`. An exact tag that is in the cache runs from it with no warning.
- **No cache**, or an exact tag that the cache lacks, exits with code 2. The message says no version was ever resolved from the source, or that the cached versions have no such tag.
- **`update` needs the network.** It never reads the cache, and it writes the answer it gets to the cache.

### Update the pin

`skill-ci update` rewrites `version` in `.skill-ci.toml` to the newest release tag and leaves every other key and comment alone. It keeps the line endings and the file mode, and it follows a symlink to the file it names.

- It moves only an exact tag. On a `latest` or `main` pin it asks the source, refreshes the cache, and prints the commit the pin now runs, such as `.skill-ci.toml: version is main, which floats, so the file is unchanged; it now runs main (<commit>)`. It leaves the file unchanged and exits with code 0.
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

The older layout, `<skills-dir>/<skill>/evals/shared-benchmark.json`, still works. In that layout, leave `evals_dir` and `--evals-dir` unset, and `skill_paths` are relative to the skill directory instead of the repository root.

In both layouts, case files, `prompt_ref`, and oracle script paths are relative to the manifest's own directory. Keep them next to the manifest.

Use relative `skill_paths` for portable manifests. The coverage check also accepts absolute entries that resolve to the inventoried skill marker, matching the runner. Coverage verifies the binding and case presence; it does not certify portability.

## Commands

Each free check is a `skill-ci` subcommand. `skill-ci init` adds the mise tasks below when the repository has a `mise.toml`. Each task has a one-line `description` and one `run` line that calls the subcommand of the same name, so the `skill-lint` task and `skill-ci lint` do the same thing. mise appends the words after the task name to that line. Put `--` before a flag, as in `mise run skill-package -- --compare-to .agents/skills`.

| Command | mise task | Where it runs | Cost | What it does |
| --- | --- | --- | --- | --- |
| `skill-ci check` | `skill-check` | CI and local | Free | Runs the model-free checks in a git repository, in this order: the package check (with `package`), the personal-data scan, the frontmatter check, the content check, the coverage check (with `require_populated_manifests`), then validate and audit on every manifest. With `--fast`, it runs only the scan of staged files and the lint checks. |
| `skill-ci lint` | `skill-lint` | CI and local | Free | Runs the frontmatter check and the content check over the skills directory. |
| `skill-ci package` | `skill-package` | Local, and CI with `package` on | Free | Lists every file in each skill package. With `--compare-to DIR`, also compares each package with its installed copy in DIR. See [Check package files and installed copies](docs/packages.md). |
| `skill-ci coverage` | `skill-coverage` | Local, and CI with `require_populated_manifests` on | Free | Requires a populated, correctly bound manifest for every skill directory. |
| `skill-ci validate` | `skill-validate` | CI and local | Free | Runs `skill-benchmark validate --strict-leakage` on every manifest. |
| `skill-ci audit` | `skill-audit` | CI and local | Free | Runs the readiness audit on every manifest. |
| `skill-ci trigger <skill>` | `skill-trigger` | Local only | Paid | Runs every trigger case on Claude and Codex and records whether the skill loaded. |
| `skill-ci run <skill>` | `skill-run` | Local only | Paid | Runs the readiness audit, then runs the cases in the manifest's `tune` split with and without the skill on Claude and Codex. It grades the runs, judges them, and writes a report. It stops if the audit finds a blocker. |

`skill-ci init`, `skill-ci update`, and `skill-ci harness` have no mise task.

`check` skips the audit of a manifest that has no cases yet, and prints `no cases yet, readiness audit skipped`. A scaffolded empty manifest is validated but not audited. Set `require_populated_manifests = true` after authoring cases to require a populated, correctly bound manifest for every skill. That check reads the inventory and the bindings and calls no model.

This repository's own `mise.toml` adds a `test` task that runs the unit tests.

### What the lints check

- The frontmatter check validates each `SKILL.md` against the agentskills.io metadata rules and the Codex invocation policy. With `trigger_cases` set, it also fails for any skill missing from the trigger declaration file.
- The content check fails on relative links whose target does not exist, bold skill names that match no known skill, and unclosed code fences. A bold name counts as a skill name when its line contains the word "skill". A conventions file can add name prefixes and retired text for your repository. See [Add your repository's naming conventions to the content check](docs/content-conventions.md).
- Bare resource paths in whole inline-code spans, such as `scripts/extract.py`, `references/guide.md`, and `assets/template.json`, must exist relative to the Markdown file that mentions them. Quoted paths can contain spaces. Commands, directory-only mentions, globs, dynamic placeholders, and fenced examples are skipped.
- Reference definitions that reuse a normalized label with a different destination or title fail. Identical repeats pass. CommonMark uses the first definition, so a later conflicting definition can silently point an agent at the wrong resource.
- A `SKILL.md` body must contain content after its frontmatter. Whitespace and HTML comments alone do not count. This check does not grade the instructions or require named sections.
- Markdown must be valid UTF-8. The check reports invalid bytes and keeps checking other files. Literal C0 controls other than tab, newline, and carriage return, DEL, and the bidirectional override characters U+202D and U+202E fail. Content diagnostics escape these characters instead of printing them literally. Write escaped demonstrations instead. Ordinary right-to-left text, joiners, and bidi isolates pass.
- The personal-data scan fails on likely personal data and on GitHub Enterprise hosts named `github.<domain>`, which name an employer. A host after `://`, `@`, `--hostname`, `-h`, `GH_HOST=`, an escaped `\n` or `\t`, or a `host:` or `hostname:` key, quoted or not, fails on any top-level domain. Anywhere else it fails only when the last label is a common top-level domain such as `com`, `net`, `org`, or `io`, so Actions expressions such as `github.event.comment.id` and settings such as `github.copilot.enable` pass. Hosts under `example.com`, `example.net`, `example.org`, `.example`, `.test`, `.invalid`, `.localhost`, `githubassets.com`, and `githubusercontent.com` pass. A made-up company host fails too, so write `github.example.com` for a placeholder. This matters because trigger cases are cut from real session transcripts.

## Run the pinned harness directly

skill-ci installs `skill-eval-harness-ext` at the commit in its own `pyproject.toml`. `skill-ci harness` runs one of the harness's two commands from that environment:

```sh
skill-ci harness skill-benchmark --help
skill-ci harness skill-trigger-matrix --help
```

Any other first argument exits with code 2. skill-ci starts Python with `-I`, so a `skill_benchmark.py` in your working directory cannot replace the harness. The command replaces the skill-ci process, so the exit code is the harness's own.

Use `skill-ci harness` instead of installing the harness yourself. The upstream package on PyPI, `skill-eval-harness`, is a different build that lacks the fork's blinding patches, so its results do not compare with skill-ci's. Commands that run the harness print a warning when `skill-benchmark` on `PATH` is not skill-ci's copy, or when your `pyproject.toml` requires `skill-eval-harness` or `skill-eval-harness-ext`. The warning ends with `skill-ci runs its own pinned copy`, and the run goes on with that copy.

## Trigger declaration file

`trigger_cases` is optional. When you set it, the file must use this version-1 format. It has one declaration per skill, and every skill under `skills_dir` needs one.

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

Each `description_contains` entry must appear in that skill's `description`, compared case-insensitively with whitespace collapsed. `implicit_allowed` must match the skill's Codex invocation policy. The check fails for a missing, duplicate, or stale declaration. It does not run a model. `skill-ci trigger` measures real triggering from the eval manifest instead.

## Run output and host isolation

The default run directory sits beside the consuming checkout, outside installed skill packages. Each invocation allocates a unique directory. The output directory may be the default or one you name with `out`. When it overlaps the skill package, the command stops before calling a model and asks you to pass `--out` with a directory outside the package.

The runner keeps the skills in your home directory out of every answer and trigger run, so a run sees only the skills it mounts. For Claude it also hides your agents, `CLAUDE.md`, MCP servers, and auto memory. Judge runs are sealed further and see no skills at all. The paid commands still start Claude through the bundled `claude-project-only` launcher, which lets a case write files inside the run's temporary workspace. They start Codex through the bundled `codex-project-only` launcher, which moves HOME to an empty directory. That move is now redundant.

An answer run refuses to start when a folder above its workspace holds `.claude`, `.agents`, `CLAUDE.md`, or `AGENTS.md`, because Claude and Codex would read them. The default macOS `TMPDIR` passes. If yours sits inside a repository or under a home directory with `~/.claude`, point `TMPDIR` somewhere else.

## Update skill-ci

Run `skill-ci update` to move an exact-tag pin to the newest release. See [Update the pin](#update-the-pin). Your terminal, hooks, mise tasks, no-mistakes, and CI all run the version in `.skill-ci.toml`, so one commit moves them together.

- **Files that `init` wrote before v1.1.0.** `init` keeps an existing workflow and existing mise tasks, so an update does not change them. To get the v1.1.0 workflow, edit your file and keep your own `SKILL_CI_SOURCE`, checkout step, and uv step. Copy the `on` block from the [workflow above](#what-init-does) and name your default branch under `push`. That block keeps `pull_request` and runs `push` on the default branch only. Copy the workflow's `concurrency` block too. Rename the job from `skills` to `skill-checks`. Or, after `skill-ci update`, move your file out of `.github/workflows` and run `skill-ci init` again. It writes the workflow with the `source` from `.skill-ci.toml` and your default branch. Then make your changes to its steps again. The job's check is now named `skill-checks`. If your branch protection rule or ruleset requires a check named `skills`, require `skill-checks` instead. To get the mise task descriptions, add a `description` line to each `skill-*` task by hand.

- **Earlier run directories.** A runner pin can change recorded identities, so re-run `prepare` and every arm before comparing with older runs. The earlier pin to `6634de1` changed trigger protocol hashes and added optional `expected_skills` and `forbidden_skills` lists for catalog routing. Regenerate both trigger comparison arms with this runner. Unscoped queries retain their existing activation rule.

The pinned runner supports `report --fail-on-failures` for offline saved-result gates. It checks `with_skill` by default and permits expected baseline assertion failures while requiring complete evidence across all arms. Rendering remains the default. The runner also ships an [offline captured-edit example](https://github.com/mdsmithaustin/skill-eval-harness/tree/70e83674f787327e3d271310fc64106dc89a2708/examples/edited-file-demo). Its native permission smoke is separate and opt-in.

The current pin, `c23ed79554995c60cbd63cc9da9f47837cfa6f9a`, is harness PR #25. It adds `stops_on_signal`, which [stops a run on SIGINT or SIGTERM](https://github.com/mdsmithaustin/skill-eval-harness/blob/c23ed79554995c60cbd63cc9da9f47837cfa6f9a/docs/commands.md) on POSIX hosts. The native runners and trigger adapters start each agent in its own session. On SIGINT or SIGTERM, a harness command that runs agents sends that signal to each running agent's process group. It sends SIGKILL to the group as soon as the agent exits, or after 2 seconds if the agent is still running. A fixed recovery case sends SIGKILL at once. The harness command starts no queued run and exits 130 for SIGINT or 143 for SIGTERM. Before this pin, a stopped run could leave its agents running and still making paid model calls.

The pin also includes harness PR #22's [fixed recovery cases](https://github.com/mdsmithaustin/skill-eval-harness/blob/70e83674f787327e3d271310fc64106dc89a2708/docs/recovery.md). On supported POSIX hosts, a prepared `run-agent` row with a `recovery` object retains one fixture across a verified checkpoint stop, fresh recovery, and fresh refusal. Successful runs save `recovery.json`, raw process evidence, and file snapshots for a consumer grader. Setup, spawn, or capture failures can leave partial or absent artifacts. Exit code 0 confirms completed runner phases and snapshots. It does not certify a model, provider, or enforced write denial. Rows without `recovery` keep their ordinary one-shot contract.

## What a passing check proves

A green CI run means the lints passed and the manifests are well formed. It does not mean any paid run happened, or that the skill helps. [What a passing check proves](docs/evidence.md) lists what each kind of check can and cannot show.

## Repository layout

```text
SKILL.md                            instructions an agent follows to activate skill-ci
DECISIONS.md                        why the repository is shaped this way
TODO.md                             known gaps, each with its reason
pyproject.toml                      the package, its version, and the harness pin
uv.lock                             locked dependencies for developing skill-ci
mise.toml                           this repository's own tools and tasks
lefthook.yml                        pre-commit hook: runs skill-ci check --fast and the unit tests
src/skill_ci/cli.py                 the skill-ci command and its subcommands
src/skill_ci/config.py              the .skill-ci.toml model
src/skill_ci/pin.py                 version resolution, the cache, and the hand-off
src/skill_ci/children.py            the one runner for every child process, and signal handling
src/skill_ci/init.py                skill-ci init
src/skill_ci/suite.py               the free checks that check runs
src/skill_ci/runs.py                the paid trigger and run commands
src/skill_ci/harness.py             skill-ci harness and the harness calls
src/skill_ci/checks/                frontmatter, content, personal-data, package, coverage, and manifest checks
src/skill_ci/launchers/             starts Claude with file edits allowed in the run's workspace, and Codex with HOME moved
src/skill_ci/templates/             the workflow and the lefthook entries that init writes
src/skill_ci/scaffold_manifest.py   writes one empty manifest per skill
src/skill_ci/outputs.py             allocates unique run directories outside packages
src/skill_ci/files.py               atomic writes and regular-file reads
tests/                              unit tests
.github/workflows/test.yml          unit tests on Linux and macOS, plus two fixture contracts that run skill-ci check
.github/fixtures/                   empty scaffold and populated edited-file contracts
.github/dependabot.yml              weekly updates for actions and uv
docs/authoring-cases.md             how to write test cases
docs/link-exceptions.md             the link-exceptions policy
docs/content-conventions.md         the content conventions file
docs/packages.md                    package inspection and copy comparison
docs/evidence.md                    what each kind of check can prove
docs/harvest-skill-optimizer.md     what was imported from skill-optimizer, and why
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
