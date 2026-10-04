# Skill CI lessons from Agent Skills evaluation

The useful changes for skill-ci are safer run-output placement, opt-in populated coverage, and a real edited-file grading proof. Keep the pinned behavioral runner. Consumer workflow conventions and other skill suites' effectiveness studies are outside this brief.

This comparison was recorded on 2026-10-04 against [Agent Skills at 1401c8b](https://github.com/addyosmani/agent-skills/tree/1401c8b8030e023baeebb31781a6653fe8e93026) and skill-ci at `d1c00eb4e4aae73bd73c6bc2bed23f00c4a8e1cf`. The behavioral runner pin was `80e49afd5ac6502d3bb2a877846a6f49003e588d`. Findings below describe that starting state.

## Findings that skill-ci owns

The external [case checker](https://github.com/addyosmani/agent-skills/blob/1401c8b8030e023baeebb31781a6653fe8e93026/scripts/run-evals.js) requires a populated case file for every skill. In skill-ci, `require-manifests` counts the global inventory and accepts empty scaffolds. A green manifest job can therefore leave some skills without behavioral cases. Add a separate opt-in per-skill coverage check. Keep empty scaffolds valid during activation and leave case schema, leakage, and readiness to the pinned runner.

The external custom behavioral path runs real fixture edits and grades the execution trace. In skill-ci, the runner already saves patches and capture receipts, but the standard Codex task defaults to read-only and no outcome case here yet proves grading from those saved edits. Add one deterministic fixture and run it through the standard task with the existing writable override. A passing proof establishes capture and grading. It does not establish skill benefit.

Both skill-ci paid tasks currently put default results under the selected skill directory. Installers that copy a working tree can pick up those transcripts. Move default results outside skill packages. An external manifest's neighboring directory is safe, but a legacy manifest lives inside the package. The output policy must cover both layouts and a root skill. Preserve explicit `OUT` overrides.

## Checks to defer

The external lexical routing check ranks descriptions using stemmed TF-IDF. It does not call an agent. Treat it as a possible advisory check until its failures predict actual routing failures. Its 95 percent floor is specific to its catalog and prompts.

The external workflow also installs its Claude plugin. skill-ci's package checker compares files and does not execute an installer. Installation adapters need a concrete supported-installer contract before they become a shared check. Keep consumer-specific command parity and workflow artifact conventions in consumer repositories.

## Verification and limits

The [replay script](recheck-addy-agent-skills.sh) accepts a clean checkout at the inspected external revision and runs only its free checks. Run `bash docs/research/recheck-addy-agent-skills.sh <source-checkout>`. Failure is a nonzero exit.

The macOS replay with Node 24.20.0 passed 141 lexical checks, with 89 of 89 positive prompts ranked first, and 33 runner tests. Command parity, artifact-path checks, and version consistency also passed. These results verify the inspected tools. They do not measure agent routing or behavioral lift. Linux and Windows jobs were not reproduced. No external paid eval or plugin installation ran.

Explain the Number kept lexical rank separate from agent behavior. Encode Lessons in Structure shaped the coverage recommendation. Build the Lever produced the replay script.
