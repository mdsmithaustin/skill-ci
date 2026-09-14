# Check package files and installed copies

The package checker is an offline, read-only command for Linux and macOS. It requires Python 3.12 or later. Choose a skill directory that you intend to distribute, or the directory whose immediate children are skills.

## Inspect a package

From a consumer repository, set `SKILL_CI` to this checkout and run one of these commands. Replace `example` with a skill directory in that repository.

```sh
python3 "$SKILL_CI/tools/check-skill-package.py" --skill skills/example
python3 "$SKILL_CI/tools/check-skill-package.py" --skills-dir skills
```

Exactly one selector is required. `--skill` inspects one package. `--skills-dir` inspects every immediate directory as a package, including hidden directories. Each package must contain a regular `SKILL.md` file. Ordinary files beside those directories are ignored. Symlinks and special files at the collection level fail the check. A missing or empty collection also fails.

The checker includes every entry inside each package, including hidden, ignored, nested, and binary files. It rejects symlink roots, symlink entries, and special files. It reports read errors instead of producing a digest for an incomplete inventory. It checks that `SKILL.md` is a regular file, but leaves its metadata and instructions to the existing lints and reviews.

A passing package prints its SHA-256 digest. The final summary reports how many packages were checked, passed, failed, and compared. Exit 0 means every selected package passed. Exit 1 means an inspection or comparison finding. Invalid command arguments exit 2.

## Compare an installed copy

`--compare-to` always names the installed skills parent directory. Each selected source maps to a directory with the same basename below it.

```sh
python3 "$SKILL_CI/tools/check-skill-package.py" \
  --skill skills/example --compare-to .agents/skills
```

This compares `skills/example` with `.agents/skills/example`. It reports added, missing, content-changed, type-changed, and executable-bit-changed entries. Other installed skills are outside the comparison.

The digest includes relative path bytes, file contents, directory presence, and the file's three executable permission bits. Empty directories therefore count. Ownership, timestamps, other permission bits, and the package root's permissions do not count. The digest format is specific to this checker and is not interchangeable with the donor's byte-only digest.

The command never installs or repairs a package. A symlink-based installation fails this regular-directory policy. Use a physical copy when checking copied-package parity. Keep source and destination quiescent during inspection. The command does not take an atomic filesystem snapshot.

## Run through mise

Consumers that include `skill-tasks.toml` get `skill-package` alongside the existing tasks.

```sh
mise run skill-package
INSTALLED_SKILLS_DIR=.agents/skills mise run skill-package
```

The task reads `SKILL_CI` and `SKILLS_DIR`, which defaults to `skills`. Set `INSTALLED_SKILLS_DIR` only when comparing copies. The task selects Bash explicitly and uses collection selection. Use the Python command for a standalone package.

## Enable CI inspection

Add `package-check: true` to the reusable workflow caller's `with` block. It defaults to false because existing consumers may intentionally use symlinks or broader directory layouts.

```yaml
with:
  package-check: true
```

Set `jobs.skills.uses` to `mdsmithaustin/skill-ci/.github/workflows/skill-checks.yml` at the published skill-ci revision's full SHA. CI inspects source packages only. Installed-copy comparison is a local operation because the reusable workflow has no deployed package tree.

Package inspection supports the file-integrity and deployment-parity claims described in [the evidence guide](evidence.md). A pass does not prove metadata conformance, installer compatibility, native activation, or behavioral utility.
