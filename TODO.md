# TODO

Deliberate gaps, each with the reason it is open.


- A stricter frontmatter policy that permits only `name` and `description` is not implemented. It needs a flag on `skill-ci lint` and `skill-ci check`, or a separate small checker.

- `tests/test_check_skill_frontmatter.py` tests the shared checker with fixtures. Consumer repositories must test their own shipped skill inventory and trigger corpus. This repository has neither.

- Trigger-row harvesting from local Claude and Codex session history is not in this repository. The decision record says the user reviews the harvest before use; the tool that produces it has not been written.

- `skill-ci run` and `skill-ci trigger` drive the CLIs through the launchers in `src/skill_ci/launchers/`. Since the runner pin to `80e49af`, the runner hides host skills and other host context itself in answer and trigger runs. `claude-project-only` is still needed, because the runner invokes `claude -p` with no tool permissions and the launcher grants `acceptEdits`. In answer and trigger runs its `--setting-sources project` repeats the runner's flag, which Claude Code 2.1.286 accepts. Judge runs get the runner's sealed `--safe-mode --disable-slash-commands` instead, and whether the launcher's flag adds anything there is untested. `codex-project-only` only moves HOME, which is now redundant. Removing it needs one Codex run through `--codex-cmd` without it, which has not been done. If either CLI changes how it scopes skills or grants tools, the launchers are the first thing to recheck.

- The edited-file proof passed capture and deterministic grading on both providers. Claude's `acceptEdits` launcher permitted edits but denied the requested Python checks. The oracle verified the reconstructed product afterward. An agent-verification gate or broader command permissions would need a separate task and proof. The fixture proves plumbing, not skill benefit. See [the proof record](docs/research/edited-file-grading.md).

- Dependabot covers the GitHub Actions used by the workflows and the pinned Python dependencies in `pyproject.toml`. It ignores `skill-eval-harness-ext`, which `pyproject.toml` pins as a git commit. Moving that pin stays a judgement call gated on the fork's tests and the exit test in `DECISIONS.md`, so a person has to classify the change. A scheduled check of the fork branch can flag new commits.

- `src/skill_ci/templates/skill-checks.yml` pins the checkout action's SHA and `uv==0.12.7` for every repository that `init` sets up. Dependabot reads this repository's own workflows and not the template, so moving those pins is manual.

- A harvest review sheet quotes real user prompts, and those quotes contain text shaped like markdown links and bold skill names. The content check reads them as real links and fails. Nothing is broken while review sheets stay untracked, which is where they belong, but committing one needs the quoted text escaped or the sheet kept out of the skills tree.

- Consumers still need committed manifests to exercise their own validate and audit paths in CI. `skill-ci check` fails when `evals_dir` names a directory that does not exist. Set `require_manifests = true` to also reject an existing but empty search tree. Set `require_populated_manifests = true` to require populated, correctly bound manifests for every skill. Both defaults remain false for activation compatibility. Empty scaffolded manifests satisfy only the file-count requirement and skip readiness audit. This repository exercises an empty scaffold and a separate populated fixture through two fixture-contract jobs that run `skill-ci check`.

## Known limits

Low-severity findings from the v1.0.0 reviews that stay open. The operator accepted on 2026-10-09 that each is recorded rather than fixed. Each line gives the reason it stays open: it is rare, it is by design, or it is upstream.

### Process, output, and signals

- With standard output closed, `sys.stdout.reconfigure` prints a traceback, and a broken pipe exits 120. Rare.
- With standard error closed, a pinned run exits 1, and a reader of standard error that exits early gives 120 rather than 141. Rare.
- SIGINT while the console script is still importing prints a `KeyboardInterrupt` traceback, because the handlers are not installed yet. Rare.
- Ctrl-Z suspends skill-ci but not its child. By design, and the README says so.
- A `uv` wrapper that defers SIGINT can leave the pinned run's harness running. Rare.
- A commit tagged by hand before v1.0.0 runs twice and then exits 126, which would repeat a paid `run`. By design, since pins start at v1.0.0 and the README says not to tag an earlier commit.
- The hand-off retry line says "with network access" even under `UV_OFFLINE=1`, and its exit-126 hint "see the uv error above" can point at nothing when the child was killed or the marker directory is unwritable. Rare.
- A stop that lands between the hand-off's check and its fork can start the online `uv` retry and stop it at once. Rare.

### The pin, the source, and the cache

- An oddly shaped `pyproject.toml` in the consuming project exits 1 with a one-line `TypeError`. Rare.
- An exact tag served from the cache offline prints no warning. By design, because an exact tag in the cache needs no lookup.
- The rejection of an scp-style `source`, and of a fullwidth `＠`, does not mention a credential helper. Rare.
- Any `@` in an https or ssh path draws the credentials message, and `%40` works in its place. By design, since `source` rejects credentials and does not parse them.
- Default-ignorable characters outside Cf, Zl, and Zp pass the control-character check and print raw. Rare.
- With the working directory deleted, skill-ci skips the config lookup and the run is unpinned. Rare.
- A cache path that is a dangling or looping symlink, or that links to `/dev/null` or a read-only directory, is never written, so the offline fallback is lost. Reading a FIFO there can raise `BrokenPipeError` in its writer. Rare.

### `update`

- `update` replaces `.skill-ci.toml` with a renamed copy. It fails in a directory you cannot write to, replaces a read-only file, breaks hard links, and drops extended attributes. By design, and the README says so.
- A stop inside the write window completes the rename but prints no `a -> b` line. SIGTRAP, SIGSYS, or SIGKILL mid-write leave a temporary file, and a stop waits for a hung `fsync`. Rare.

### `init`

- A lefthook `run` that merely mentions `skill-ci check`, such as `skill-ci check --fast` under `pre-push`, counts as wired. Rare.
- Appending to a no-mistakes `lint` value that ends in `;`, `&`, or `\` gives invalid shell, a list or number `lint` is reported as empty, and a byte-order mark or trailing spaces give a to-do line. Rare.
- A mixed-line-ending `.no-mistakes.yaml` is refused. Rare.
- mise config in `.config/mise.toml` and the other mise locations is skipped without a note, and "already has the skill tasks" prints even when a task such as `skill-lint` is the user's own. Rare.
- A FIFO at `.gitignore` or the workflow path hangs `init`, and a directory there exits 1 after partial writes. Rare.
- Dangling symlinks are followed, so targets can be created outside the repository, and auto-detected `evals` or symlinked skill directories can write manifests outside it. Rare.
- New files are written in place, so a crash or a full disk leaves a truncated file that a later run reports as kept. A truncated `.skill-ci.toml` makes every command exit 2. Rare.
- An interrupted or SIGTERMed `lefthook validate` leaves an unvalidated edit in place. Rare.
- Entries the user deliberately removed come back on each run. By design, since `init` adds what is missing.
- `--skills-dir '~'` writes a directory named `~`. Rare.
- A `source` that contains `${{ ... }}` is written into the workflow's `env:` value, where GitHub evaluates it as an expression. Rare, since `source` comes from the repository's own committed file.
- In the printed no-mistakes snippet, control characters in the `origin` URL print raw, so a newline can add YAML lines. A token in the URL's path or query, rather than its user part, prints too. Rare.
- Every scp-style `origin` prints as `<remote URL>` in that snippet. By design, since the user part of an scp-style URL cannot be told apart from a token.

### The CI workflow template

- The job uses the runner image's system Python rather than a pinned one. By design, because `uv` picks an interpreter that meets `requires-python`.
- The job installs skill-ci from the source's default branch with no ref, then hands off to the pin. By design, so the workflow names no version.
- The job's install has no `--require-hashes`, and the harness's own dependencies, such as `regex`, are not pinned. Upstream, because a git dependency installs without a hash lock.
- A cold install spends most of its time fetching the harness git dependency from github.com. Upstream, for the same reason.

### Checks and paid runs

- `SKILL_CI_DEBUG` does not change the per-check lines. By design, and the README says so.
- `run` exits 0 when every agent call fails. The harness's FAIL line omits the manifest. Rare.
- A mode-000 working directory with relative paths gives a misleading message. `package` reports `FileNotFoundError` without the path. Rare.
- `--out` is not checked for being creatable before a paid run starts. Rare.
- `runs`, `timeout`, and `judge_runs` accept negative values though the README calls them whole numbers. Rare.

### Docs

- The no-mistakes snippet that `init` prints is indented four spaces, where the README shows column 0. "version key is quoted" in the `update` section is easy to misread. Rare.
- The README does not say that uv's "Remote Git fetches are not allowed" error on a cold cache is expected before the online retry. Rare.
- The README says the harness has two commands, but the package also ships `skill-pi-trigger-eval`. By design, since `skill-ci harness` runs only the two.
- The README's `--evals-dir` wording is loose, as `skills/evals` is accepted. Rare.
- The README's hand-written workflow omits the two-line header comment that `init` writes. By design, since a hand-written file was not written by `init`.
- The exit-code table's 128+N row says a harness command died of that signal, but with the `c23ed79` pin the harness exits 130 or 143 itself. The code a user sees is the same. Rare.
- `DECISIONS.md` does not say that `runner.lock` was retired or why, and the other-CI example has no decision of its own. Rare.

### Tests

- Four older tests fail when `TMPDIR` is inside a git repository: `test_a_pii_scan_git_cannot_run_names_the_reason` and three in `test_written_product_oracle.py`. Rare.
- No test sees `atomic_write`'s `fsync`, a failed cache write's temporary-file cleanup, a socket at `.skill-ci.toml`, a U+2029 row in the source or path tables, or `init.rewrite` dropping its stop window. Rare.
- A mutant that starts `uv` after a stop survives, because no test counts `Popen` calls or uses a child that ignores SIGINT. Rare.
- The longest comment in `src/skill_ci/children.py` is 128 characters, and no lint sets a limit. Rare.

### The harness

- The harness fork, `skill-eval-harness-ext` at `c23ed79`, keeps these upstream. Stopping a run prints a `KeyboardInterrupt` traceback. SIGHUP, as when a terminal closes, still leaves agents running. macOS has no `os.waitid`, so a stopped session's leader can stay unreaped there, and `stop_session` does not catch the `OSError` that `killpg` raises on a zombie-only group. The `Popen` in `run-agent` sits outside the guarded `try`, a signal before the handlers install gives exit 1 or a traceback, `main()` off the main thread raises `ValueError`, and other exceptions in the wait loop are uncovered. The newer pin adds a recommended `case-source-unrecorded` finding to each manifest audit. `skill-ci trigger` on a manifest with no trigger cases prints the harness's "pass --eval-set" hint, though `skill-ci trigger` has no such option. skill-ci cannot catch that case first without copying the harness's case expansion, so the message stays until the harness changes it.
