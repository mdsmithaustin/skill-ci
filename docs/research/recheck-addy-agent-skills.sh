#!/usr/bin/env bash
set -euo pipefail

source_checkout=${1:?pass a clean checkout of addyosmani/agent-skills}
expected_revision=1401c8b8030e023baeebb31781a6653fe8e93026
actual_revision=$(git -C "$source_checkout" rev-parse HEAD)
test "$actual_revision" = "$expected_revision"
test -z "$(git -C "$source_checkout" status --porcelain)"
cd "$source_checkout"
node scripts/run-evals.js --min-rank1 95
node --test scripts/run-evals-test.js
node scripts/validate-commands.js
node scripts/validate-artifact-paths.js
node scripts/validate-versions.js
