# Write test cases for a skill

These rules are for the person who writes the cases in a skill's manifest. Rules 1 to 5 come from the research that chose this repository's shape. Rules 6 to 8 come from paid runs that failed without them.

A case is one test prompt in `shared-benchmark.json`. A trigger case asks whether the agent loads the skill for a prompt. An outcome case asks whether the skill made the agent's work better. The [README](../README.md#terms) defines the other terms used here.

## Where cases come from

- Trigger cases (`kind: trigger`, with `should_trigger` set to true or false) are cut from real Claude and Codex session history, where you can see whether the skill loaded. A person reviews each one before it is used. The harvest tool is not in this repository yet. See `TODO.md`.
- Outcome cases are written by the skill's author.
- A gated skill is one a model may not load on its own. It runs only when the user types `/name` or `$name`. Gated skills get outcome cases only. Skills that load from their description get trigger cases too.

## Rules

1. **Describe the world in prose, not fixtures.** A case says in a few sentences what the repository, the files, and the situation look like. The agent reads that as context. Build a fixture tree only when an assertion has to read a real file that exists before the run starts. Rule 6 covers files the agent writes during the run.

2. **Grade what the agent did, not what it said.** The final reply is the easiest thing to fake. Assert on the trace: which files the agent read, which commands it ran, and whether the skill loaded. A trace assertion that a referenced file was read is also the only proof that the reference resolves and loads.

3. **Give each case one result assertion and one path assertion.** The result assertion says what must be true of the outcome. The path assertion says what must be true of how the agent got there. A case with only a result assertion passes when the agent guesses. A case with five assertions is five cases with worse names.

4. **Include near-miss negatives.** Every trigger set needs prompts that look like they want the skill and do not. Every outcome set needs a case where the right move is to do less, refuse, or keep a rule under pressure. The readiness audit calls these adversarial cases and fails a manifest that has none.

5. **Run the readiness audit before any paid run.** `skill-ci run` runs `skill-benchmark audit-manifest --fail-on-blockers --strict-judge` before it spends model budget. CI runs the audit too. A manifest that fails the audit is not ready. `--strict-judge` also stops the run when the judge model is one of the models under test.

6. **Assert on the skill's product, not on the whole reply.** A skill that works often explains what it did, and the explanation quotes the text the skill removed. A substring check over the whole reply then fails the good run and passes the silent one. The report shows negative lift when the skill did better.

   The tested fix is to ask for the product inside tags, and use a `script` oracle to extract it from `output.md`. Use tags, not code fences, because a fenced code block inside the product closes the outer fence early. Put the oracle script in its own subdirectory next to the manifest, and have it take `{output_dir}` as an argument. The script runs with the manifest directory as its working directory. Encode the skill's actual rule in the oracle, not a rough substring of it.

   For a file-editing task, grade the saved edits instead. `run-agent` records `workspace-changes.json`, `candidate.patch`, and `candidate-files/` in `{output_dir}`. Verify the capture receipt and hashes, reject unrelated writes, reconstruct the product from the patch, and execute its behavior checks. The [edited-file grading proof](research/edited-file-grading.md) exercised this path on Claude and Codex through the `skill-run` task that `skill-ci run` replaced. The fixture oracle grades the delivered file, not whether the agent ran its own checks.

   Codex needs a writable sandbox for a file-editing case. The proof gave it one through the bundled `codex-project-only` launcher, with `--sandbox workspace-write` in place of the default `--sandbox read-only`. Running Codex without that launcher has not been tested. The launcher ships inside the skill-ci package, so print its path with Python from the same environment, then pass it to `--codex-cmd`. Set `skill_ci` to the package you install skill-ci from. In a repository whose `.skill-ci.toml` pins a version, `skill-ci run` runs the pinned commit instead. There, set `skill_ci` to `git+<URL>@<commit>`, and take the commit from the `skill-ci <version> (<commit>)` line that skill-ci prints first. The URL is the file's `source`, or `https://github.com/mdsmithaustin/skill-ci.git` when the file has no `source`. If `source` is a path, write it as a `file://` URL with an absolute path, such as `file:///srv/skill-ci.git`, because uv does not accept a path after `git+`.

   ```sh
   skill_ci="git+https://github.com/mdsmithaustin/skill-ci.git@<commit>"
   launcher=$(uv tool run --from "$skill_ci" python -c 'from importlib.resources import files; print(files("skill_ci") / "launchers" / "codex-project-only")')
   uv tool run --from "$skill_ci" skill-ci run skills/my-skill \
   	--codex-cmd "\"$launcher\" exec --json --skip-git-repo-check --sandbox workspace-write"
   ```

   Learned on 2026-09-13.

7. **Make the judge count, and make it say why.** On a prose or judgment skill, the judge is often the only assertion that tells the two variants apart. The deterministic checks all pass once a case is easy enough for the base model. Three settings decide whether the judge's signal reaches the report:

   - Give the judge assertion gate severity when it is the check you trust. A soft judge adds nothing to the headline score, so a run can separate the variants cleanly and still report no lift.
   - Score anchored dimensions, not one overall rubric. A failure then names the property that fell.
   - Repeat the judge and let the runner merge the verdicts. `skill-ci run` repeats each judge task `--judge-runs` times, default 3. One verdict hides its own variance.

8. **Use the calibration the runner already has before adding a dependency.** skill-eval-harness already supports judge alignment against human labels, judge robustness probes with negative controls, multi-judge panels with a quorum, and repeated judging. Before you adopt an external scoring framework, check that score resolution is your real limit. Usually the limits are cases that do not tell the variants apart, and too few runs.

## Add a healthy control for review and repair skills

A review or repair skill also needs a case whose input is already correct and should stay unchanged. That case catches a skill that criticizes every input. The [evidence guide](evidence.md#author-cases-that-can-distinguish-behavior) explains the control and how to keep case definitions apart from run results.
