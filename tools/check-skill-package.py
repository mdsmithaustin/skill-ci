#!/usr/bin/env python3
"""Inspect skill package trees and compare selected deployed copies."""

from __future__ import annotations

import argparse
import hashlib
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path


class CheckError(RuntimeError):
    pass


@dataclass(frozen=True)
class Directory:
    pass


@dataclass(frozen=True)
class FileIdentity:
    digest: bytes
    executable_mask: int


Entry = Directory | FileIdentity
DIRECTORY = Directory()


@dataclass(frozen=True)
class PackageResult:
    name: str
    digest: str | None
    findings: tuple[str, ...]
    compared: bool


def escaped(value: bytes | str | Path) -> str:
    raw = value if isinstance(value, bytes) else os.fsencode(os.fspath(value))
    return "".join(chr(byte) if 32 <= byte < 127 and byte != 92 else f"\\x{byte:02x}" for byte in raw)


def require_directory(path: Path, label: str) -> None:
    try:
        mode = os.lstat(path).st_mode
    except OSError as exc:
        raise CheckError(f"{label} is missing or unreadable: {escaped(path)}: {exc.strerror}") from exc
    if stat.S_ISLNK(mode):
        raise CheckError(f"{label} must not be a symlink: {escaped(path)}")
    if not stat.S_ISDIR(mode):
        raise CheckError(f"{label} must be a directory: {escaped(path)}")


def require_marker(root: Path) -> None:
    marker = root / "SKILL.md"
    try:
        mode = os.lstat(marker).st_mode
    except OSError as exc:
        raise CheckError(f"missing or unreadable SKILL.md: {escaped(marker)}: {exc.strerror}") from exc
    if stat.S_ISLNK(mode):
        raise CheckError(f"SKILL.md must not be a symlink: {escaped(marker)}")
    if not stat.S_ISREG(mode):
        raise CheckError(f"SKILL.md must be a regular file: {escaped(marker)}")


def selected_packages(skill: Path | None, skills_dir: Path | None) -> tuple[Path, ...]:
    if skill is not None:
        require_directory(skill, "skill selection")
        require_marker(skill)
        return (skill,)

    assert skills_dir is not None
    require_directory(skills_dir, "skills directory")
    packages: list[Path] = []
    try:
        entries = sorted(os.scandir(skills_dir), key=lambda entry: os.fsencode(entry.name))
    except OSError as exc:
        raise CheckError(f"cannot read skills directory {escaped(skills_dir)}: {exc.strerror}") from exc
    for entry in entries:
        path = skills_dir / entry.name
        try:
            mode = os.lstat(path).st_mode
        except OSError as exc:
            raise CheckError(f"cannot inspect collection entry {escaped(path)}: {exc.strerror}") from exc
        if stat.S_ISLNK(mode):
            raise CheckError(f"collection contains a symlink: {escaped(path)}")
        if stat.S_ISDIR(mode):
            require_marker(path)
            packages.append(path)
        elif not stat.S_ISREG(mode):
            raise CheckError(f"collection contains a special file: {escaped(path)}")
    if not packages:
        raise CheckError(f"skills directory inventory is empty: {escaped(skills_dir)}")
    return tuple(packages)


def read_identity(directory: int, name: str, relative: bytes, expected: os.stat_result) -> FileIdentity:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    if not getattr(os, "O_NOFOLLOW", 0):
        raise CheckError("this platform does not provide O_NOFOLLOW")
    try:
        descriptor = os.open(name, flags, dir_fd=directory)
    except OSError as exc:
        raise CheckError(f"cannot read file {escaped(relative)}: {exc.strerror}") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise CheckError(f"file changed type while reading: {escaped(relative)}")
        if (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino):
            raise CheckError(f"file changed while reading: {escaped(relative)}")
        digest = hashlib.sha256()
        while block := os.read(descriptor, 65536):
            digest.update(block)
    finally:
        os.close(descriptor)
    return FileIdentity(digest.digest(), opened.st_mode & 0o111)


def inventory(root: Path) -> dict[bytes, Entry]:
    require_directory(root, "package root")
    entries: dict[bytes, Entry] = {}

    def open_directory(path: str | Path, relative: bytes, parent: int | None = None) -> int:
        flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
        if not getattr(os, "O_NOFOLLOW", 0):
            raise CheckError("this platform does not provide O_NOFOLLOW")
        try:
            descriptor = os.open(path, flags, dir_fd=parent)
        except OSError as exc:
            raise CheckError(f"cannot read directory {escaped(relative)}: {exc.strerror}") from exc
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise CheckError(f"directory changed type while reading: {escaped(relative)}")
        return descriptor

    def walk(directory: int, relative: bytes) -> None:
        try:
            with os.scandir(directory) as scanner:
                children = sorted(scanner, key=lambda entry: os.fsencode(entry.name))
        except OSError as exc:
            raise CheckError(f"cannot read directory {escaped(relative)}: {exc.strerror}") from exc
        for child in children:
            child_relative = os.fsencode(child.name) if not relative else relative + b"/" + os.fsencode(child.name)
            try:
                info = os.stat(child.name, dir_fd=directory, follow_symlinks=False)
            except OSError as exc:
                raise CheckError(f"cannot inspect path {escaped(child_relative)}: {exc.strerror}") from exc
            if stat.S_ISLNK(info.st_mode):
                raise CheckError(f"package contains a symlink: {escaped(child_relative)}")
            if stat.S_ISDIR(info.st_mode):
                entries[child_relative] = DIRECTORY
                child_directory = open_directory(child.name, child_relative, directory)
                try:
                    walk(child_directory, child_relative)
                finally:
                    os.close(child_directory)
            elif stat.S_ISREG(info.st_mode):
                entries[child_relative] = read_identity(directory, child.name, child_relative, info)
            else:
                raise CheckError(f"package contains a special file: {escaped(child_relative)}")

    root_directory = open_directory(root, b".")
    try:
        walk(root_directory, b"")
    finally:
        os.close(root_directory)
    if not entries:
        raise CheckError(f"package inventory is empty: {escaped(root)}")
    return entries


def inventory_digest(entries: dict[bytes, Entry]) -> str:
    digest = hashlib.sha256(b"skill-package-inventory-v1\0")
    for path in sorted(entries):
        entry = entries[path]
        digest.update(len(path).to_bytes(8, "big"))
        digest.update(path)
        if isinstance(entry, Directory):
            digest.update(b"d")
        else:
            digest.update(b"f")
            digest.update(entry.digest)
            digest.update(entry.executable_mask.to_bytes(1, "big"))
    return digest.hexdigest()


def compare(source: dict[bytes, Entry], installed: dict[bytes, Entry]) -> list[str]:
    findings: list[str] = []
    for path in sorted(source.keys() | installed.keys()):
        original = source.get(path)
        deployed = installed.get(path)
        display = escaped(path)
        if original is None:
            findings.append(f"added installed path: {display}")
        elif deployed is None:
            findings.append(f"missing installed path: {display}")
        elif type(original) is not type(deployed):
            findings.append(f"type changed: {display}")
        elif isinstance(original, FileIdentity) and isinstance(deployed, FileIdentity):
            if original.digest != deployed.digest:
                findings.append(f"content changed: {display}")
            if original.executable_mask != deployed.executable_mask:
                findings.append(f"executable bits changed: {display}")
    return findings


def check(packages: tuple[Path, ...], installed_parent: Path | None) -> tuple[PackageResult, ...]:
    if installed_parent is not None:
        require_directory(installed_parent, "installed skills directory")
    results: list[PackageResult] = []
    for root in packages:
        name = root.resolve().name
        findings: list[str] = []
        digest: str | None = None
        compared = False
        try:
            source = inventory(root)
            digest = inventory_digest(source)
        except CheckError as exc:
            source = None
            findings.append(str(exc))
        if installed_parent is not None and source is not None:
            destination = installed_parent / name
            try:
                deployed = inventory(destination)
            except CheckError as exc:
                findings.append(f"installed copy {escaped(destination)}: {exc}")
            else:
                findings.extend(compare(source, deployed))
                compared = True
        results.append(PackageResult(name, digest, tuple(findings), compared))
    return tuple(results)


def print_results(results: tuple[PackageResult, ...]) -> int:
    for result in results:
        if result.digest is not None:
            print(f"{escaped(result.name)} sha256:{result.digest}")
        for finding in result.findings:
            print(f"{escaped(result.name)}: {finding}")
    checked = len(results)
    failed = sum(bool(result.findings) for result in results)
    passed = checked - failed
    compared = sum(result.compared for result in results)
    print(f"packages checked: {checked}; passed: {passed}; failed: {failed}; copies compared: {compared}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--skill", type=Path, metavar="DIRECTORY")
    selection.add_argument("--skills-dir", type=Path, metavar="DIRECTORY")
    parser.add_argument("--compare-to", type=Path, metavar="INSTALLED_SKILLS_DIRECTORY")
    args = parser.parse_args(argv)
    try:
        packages = selected_packages(args.skill, args.skills_dir)
        return print_results(check(packages, args.compare_to))
    except CheckError as exc:
        print(f"error: {exc}")
        print("packages checked: 0; passed: 0; failed: 0; copies compared: 0")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
