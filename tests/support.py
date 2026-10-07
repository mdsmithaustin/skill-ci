from __future__ import annotations

import json
import os
import subprocess
import sysconfig
import venv
from pathlib import Path
from typing import Any

REPOSITORY = Path(__file__).resolve().parents[1]
INSTALLED_COMMAND = Path(sysconfig.get_path("scripts")) / "skill-ci"
# A git hook exports GIT_DIR and GIT_INDEX_FILE, which would point every fixture repository at the real one.
# A shell that exports SKILL_CI_DEBUG=1 would turn the one-line errors the tests check into tracebacks.
ENVIRONMENT = {key: value for key, value in os.environ.items() if not key.startswith(("GIT_", "SKILL_CI_"))}
PLANTED_EMAIL = "@".join(("jane.doe", "corp-mail.net"))
FAKE_HARNESS = """\
import json, os, sys
arguments = sys.argv[1:]
record = {
    "command": os.path.basename(sys.argv[0]),
    "arguments": arguments,
    "cwd": os.getcwd(),
    "inherited": os.environ.get("FAKE_HARNESS_INHERITED"),
    "skill_ci_variables": sorted(key for key in os.environ if key.startswith("SKILL_CI_")),
}
with open(os.environ["FAKE_HARNESS_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(record) + "\\n")
failing = os.environ.get("FAKE_HARNESS_FAIL_STAGE")
stage = arguments[0] if arguments else ""
raise SystemExit(int(os.environ.get("FAKE_HARNESS_EXIT", "0")) if not failing or failing == stage else 0)
"""


def skill_ci(*arguments: str, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(INSTALLED_COMMAND), *arguments],
        cwd=cwd,
        env=ENVIRONMENT if env is None else env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def run_in_a_broken_cwd(directory: Path, breaking_command: str, *command: str) -> subprocess.CompletedProcess[str]:
    directory.mkdir()
    return subprocess.run(
        ["/bin/sh", "-c", f'cd "$1" && {breaking_command} "$1" && shift && exec "$@"', "sh", str(directory), *command],
        env=ENVIRONMENT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def git(*arguments: str, cwd: Path) -> None:
    subprocess.run(["git", *arguments], cwd=cwd, env=ENVIRONMENT, capture_output=True, check=True)


def write_skill(directory: Path) -> Path:
    name = directory.name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Use when asked for {name}.\n---\n# {name}\n")
    return directory


def manifest(name: str, skill_paths: list[str], cases: list[dict[str, Any]] | None = None) -> str:
    return json.dumps(
        {
            "version": 2,
            "skill_name": name,
            "skill_description": f"Use when asked for {name}.",
            "skill_paths": skill_paths,
            "variants": ["with_skill", "without_skill"],
            "cases": [] if cases is None else cases,
        }
    )


def case(**changes: Any) -> dict[str, Any]:
    populated = {
        "id": "repair",
        "kind": "adversarial",
        "split": "tune",
        "prompt": "Repair the thing.",
        "assertions": [{"type": "contains", "name": "names-fix", "severity": "gate", "value": "repaired"}],
    }
    return {key: value for key, value in {**populated, **changes}.items() if value is not None}


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def install_record(directory: Path, commit: str) -> Path:
    """Write the metadata uv leaves for skill-ci installed from git at commit, so a run from directory reports it."""
    dist_info = directory / "skill_ci-1.0.0.dist-info"
    write(dist_info / "METADATA", "Metadata-Version: 2.1\nName: skill-ci\nVersion: 1.0.0\n")
    write(dist_info / "direct_url.json", json.dumps({"url": "https://git.example.com/skill-ci.git", "vcs_info": {"vcs": "git", "commit_id": commit}}))
    return directory


class FakeHarness:
    def __init__(self, root: Path, source: Path = REPOSITORY / "src") -> None:
        environment = root / "fake environment"
        venv.create(environment, with_pip=False)
        paths = sysconfig.get_paths(scheme="venv", vars={"base": str(environment), "platbase": str(environment)})
        self.scripts = Path(paths["scripts"])
        self.purelib = Path(paths["purelib"])
        self.python = self.scripts / "python"
        self.log = root / "harness.jsonl"
        (self.purelib / "skill_ci_source.pth").write_text(f"{source}\n{sysconfig.get_path('purelib')}\n")
        for command in ("skill-benchmark", "skill-trigger-matrix"):
            (self.scripts / command).write_text(FAKE_HARNESS)
            (self.scripts / command).chmod(0o755)

    def run(self, *arguments: str, cwd: Path, path: str | None = None, **variables: str) -> subprocess.CompletedProcess[str]:
        environment = {
            **ENVIRONMENT,
            "PATH": path or f"{self.scripts}{os.pathsep}{os.environ['PATH']}",
            "FAKE_HARNESS_LOG": str(self.log),
            **variables,
        }
        return subprocess.run(
            [str(self.python), "-I", "-m", "skill_ci", *arguments],
            cwd=cwd,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def calls(self) -> list[dict[str, Any]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def arguments(self) -> list[list[str]]:
        return [call["arguments"] for call in self.calls()]
