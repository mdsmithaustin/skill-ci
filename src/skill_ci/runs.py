from __future__ import annotations

import os
import shlex
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from importlib import resources
from pathlib import Path

from skill_ci import harness, outputs
from skill_ci.harness import Command


class Agent(StrEnum):
    CLAUDE = "claude"
    CODEX = "codex"


@dataclass(frozen=True)
class TriggerOptions:
    skill: Path
    evals_dir: Path | None = None
    out: Path | None = None
    runs: int = 3
    matrix_model: str | None = None
    codex_cmd: str | None = None


@dataclass(frozen=True)
class RunOptions:
    skill: Path
    evals_dir: Path | None = None
    out: Path | None = None
    runs: int = 3
    agents: Sequence[Agent] = (Agent.CLAUDE, Agent.CODEX)
    model: str = "sonnet"
    codex_model: str = "gpt-5.6-sol"
    codex_cmd: str | None = None
    timeout: int = 240
    judge_model: str = "opus"
    judge_runs: int = 3


class SetupError(Exception):
    pass


def trigger(options: TriggerOptions) -> int:
    manifest = str(manifest_path(options.skill, options.evals_dir))
    try:
        claude = str(launcher("claude-project-only"))
        codex_cmd = codex_command(options.codex_cmd)
        out = create_output(output_directory(options.skill, "trigger", options.out))
    except SetupError as error:
        print(f"skill-ci: {error}", file=sys.stderr)
        return 1
    model = ["--model", options.matrix_model] if options.matrix_model is not None else []
    return harness.run(
        Command.TRIGGER_MATRIX,
        [
            manifest,
            "--agent", Agent.CLAUDE, "--agent", Agent.CODEX,
            "--claude-bin", claude,
            "--codex-cmd", codex_cmd,
            "--runs-per-query", str(options.runs), *model,
            "--trace-runs", str(out / "traces"),
            "--out", str(out / "trigger-matrix.json"),
        ],
    )


def run(options: RunOptions) -> int:
    manifest = str(manifest_path(options.skill, options.evals_dir))
    try:
        claude = str(launcher("claude-project-only"))
        flags = {agent: agent_flags(agent, options, claude) for agent in options.agents}
        out = output_directory(options.skill, "run", options.out)
        audited = harness.run(Command.BENCHMARK, ["audit-manifest", manifest, "--fail-on-blockers", "--strict-judge"])
        if audited != 0:
            return audited
        create_output(out)
    except SetupError as error:
        print(f"skill-ci: {error}", file=sys.stderr)
        return 1
    tasks = str(out / "tasks.jsonl")
    stages = [
        ["prepare", manifest, "--split", "tune", "--runs-per-variant", str(options.runs), "--out", tasks],
    ]
    for agent in options.agents:
        runs = str(out / agent)
        judged = str(out / f"{agent}-judge.jsonl")
        benchmark = str(out / f"{agent}-benchmark.json")
        stages += [
            ["run-agent", "--agent", agent, *flags[agent], "--tasks", tasks, "--runs", runs, "--timeout", str(options.timeout)],
            ["grade", manifest, "--runs", runs, "--allow-scripts"],
            [
                "judge", manifest,
                "--runs", runs,
                "--judge-backend", "claude",
                "--judge-model", options.judge_model,
                "--claude-bin", claude,
                "--judge-runs", str(options.judge_runs),
                "--out", judged,
            ],
            [
                "benchmark", manifest,
                "--runs", runs,
                "--split", "tune",
                "--allow-scripts",
                "--judge-results", judged,
                "--out", benchmark,
            ],
            ["report", "--benchmark", benchmark, "--format", "github"],
        ]
    for arguments in stages:
        code = harness.run(Command.BENCHMARK, arguments)
        if code != 0:
            return code
    return 0


def agent_flags(agent: Agent, options: RunOptions, claude: str) -> list[str]:
    if agent is Agent.CLAUDE:
        return ["--model", options.model, "--claude-bin", claude]
    return ["--model", options.codex_model, "--codex-cmd", codex_command(options.codex_cmd)]


def manifest_path(skill: Path, evals_dir: Path | None) -> Path:
    if evals_dir is not None:
        return evals_dir / skill.name / "shared-benchmark.json"
    return skill / "evals" / "shared-benchmark.json"


def launcher(name: str) -> Path:
    path = Path(str(resources.files("skill_ci") / "launchers" / name))
    if not (path.is_file() and os.access(path, os.X_OK)):
        raise SetupError(f"launcher {path} is not an executable file")
    return path


def codex_command(codex_cmd: str | None) -> str:
    if codex_cmd is not None:
        return codex_cmd
    # The harness splits --codex-cmd with shlex.split, so the launcher path is quoted.
    codex = shlex.quote(str(launcher("codex-project-only")))
    return f"{codex} exec --json --skip-git-repo-check --sandbox read-only"


def output_directory(skill: Path, kind: str, out: Path | None) -> Path:
    try:
        if out is None:
            return outputs.allocate_output(skill, kind, outputs.checkout_root(Path.cwd()))
        return outputs.claim_output(out, skill)
    # Path.resolve raises RuntimeError on a symlink loop before Python 3.13.
    except (OSError, ValueError, RuntimeError) as error:
        raise SetupError(f"output allocation failed: {error}") from error


def create_output(out: Path) -> Path:
    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise SetupError(f"output allocation failed: {error}") from error
    return out
