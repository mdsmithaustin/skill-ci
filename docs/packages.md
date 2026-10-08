# Check package files and installed copies

`skill-ci package` is an offline, read-only command for Linux and macOS. It requires Python 3.12 or later. Point it at the directory whose immediate children are the skills you intend to distribute.

## Inspect packages

From a consumer repository, run this command. `--skills-dir` defaults to `skills`, and `skills_dir` in `.skill-ci.toml` sets it for every command.

```sh
skill-ci package --skills-dir skills
```

The command inspects every immediate directory as a package, including hidden directories. Each package must contain a regular `SKILL.md` file. Ordinary files beside those directories are ignored. Symlinks and special files at the collection level fail the check. A missing or empty collection also fails.

The checker includes every entry inside each package, including hidden, ignored, nested, and binary files. It rejects symlink roots, symlink entries, and special files. It reports read errors instead of producing a digest for an incomplete inventory. It checks that `SKILL.md` is a regular file, but leaves its metadata and instructions to the existing lints and reviews.

A passing package prints its SHA-256 digest. The final summary reports how many packages were checked, passed, failed, and compared. Exit 0 means every package passed. Exit 1 means an inspection or comparison finding. Invalid command arguments exit 2.

## Compare an installed copy

`--compare-to` always names the installed skills parent directory. Each package maps to a directory with the same basename below it.

```sh
skill-ci package --skills-dir skills --compare-to .agents/skills
```

This compares each package under `skills`, such as `skills/example`, with the directory of the same name under `.agents/skills`, such as `.agents/skills/example`. It reports added, missing, content-changed, type-changed, and executable-bit-changed entries. Other installed skills are outside the comparison.

The digest includes relative path bytes, file contents, directory presence, and the file's three executable permission bits. Empty directories therefore count. Ownership, timestamps, other permission bits, and the package root's permissions do not count. The digest format is specific to this checker and is not interchangeable with the donor's byte-only digest.

The command never installs or repairs a package. A symlink-based installation fails this regular-directory policy. Use a physical copy when checking copied-package parity. Keep source and destination quiescent during inspection. The command does not take an atomic filesystem snapshot.

## Run through mise

When the repository has a `mise.toml`, `skill-ci init` adds a `skill-package` task that calls `skill-ci package`. mise appends the words after the task name, so put `--` before a flag.

```sh
mise run skill-package -- --compare-to .agents/skills
```

## Enable CI inspection

`skill-ci check` skips the package check by default, because existing consumers may intentionally use symlinks or broader directory layouts. Set `package = true` in `.skill-ci.toml` to turn it on, or pass `--package` for one run. `--no-package` turns it off for one run.

```toml
package = true
```

CI inspects source packages only. `skill-ci check` does not take `--compare-to`, so installed-copy comparison is a local operation. A CI checkout has no deployed package tree.

Package inspection supports the file-integrity and deployment-parity claims described in [the evidence guide](evidence.md). A pass does not prove metadata conformance, installer compatibility, native activation, or behavioral utility.
