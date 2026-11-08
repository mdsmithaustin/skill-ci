from __future__ import annotations

import json
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
    runs: int = 1
    agents: Sequence[Agent] = (Agent.CLAUDE, Agent.CODEX)
    model: str = "sonnet"
    codex_model: str = "gpt-5.6-sol"
    codex_cmd: str | None = None
    timeout: int = 240
    judge_backend: Agent = Agent.CLAUDE
    judge_model: str | None = None
    judge_runs: int = 1
    dry_run: bool = False


class SetupError(Exception):
    pass


def trigger(options: TriggerOptions) -> int:
    manifest = harness.operand(manifest_path(options.skill, options.evals_dir))
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
            "--trace-runs", harness.operand(out / "traces"),
            "--out", harness.operand(out / "trigger-matrix.json"),
        ],
    )


def run(options: RunOptions) -> int:
    manifest = harness.operand(manifest_path(options.skill, options.evals_dir))
    try:
        if options.runs < 1 or options.judge_runs < 1 or options.timeout < 1:
            raise SetupError("runs, judge-runs, and timeout must be positive")
        if options.dry_run and options.out is None:
            raise SetupError("--dry-run requires --out so previewing allocates no run directory")
        claude = str(launcher("claude-project-only"))
        flags = {agent: agent_flags(agent, options, claude) for agent in options.agents}
        out = output_directory(options.skill, "run", options.out)
    except SetupError as error:
        print(f"skill-ci: {error}", file=sys.stderr)
        return 1
    tasks = harness.operand(out / "tasks.jsonl")
    stages = [
        ["audit-manifest", manifest, "--fail-on-blockers", "--strict-judge"],
        ["prepare", manifest, "--split", "tune", "--runs-per-variant", str(options.runs), "--out", tasks],
    ]
    for agent in options.agents:
        runs = harness.operand(out / agent)
        judged = harness.operand(out / f"{agent}-judge.jsonl")
        benchmark = harness.operand(out / f"{agent}-benchmark.json")
        stages += [
            ["run-agent", "--agent", agent, *flags[agent], "--tasks", tasks, "--runs", runs, "--timeout", str(options.timeout)],
            ["grade", manifest, "--runs", runs, "--allow-scripts"],
            [
                "judge", manifest,
                "--runs", runs,
                "--judge-backend", options.judge_backend,
                *judge_flags(options, claude),
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
    if options.dry_run:
        print(json.dumps({"validated": False, "stages": stages}, indent=2))
        return 0
    for index, arguments in enumerate(stages):
        code = harness.run(Command.BENCHMARK, arguments)
        if code != 0:
            return code
        if index == 0:
            try:
                create_output(out)
            except SetupError as error:
                print(f"skill-ci: {error}", file=sys.stderr)
                return 1
            print(
                f"skill-ci: answer agents: {', '.join(options.agents)}; paired repetitions: {options.runs}; "
                f"judge: {options.judge_backend}; judge repetitions: {options.judge_runs}",
                file=sys.stderr,
            )
    return 0


def judge_flags(options: RunOptions, claude: str) -> list[str]:
    if options.judge_backend is Agent.CLAUDE:
        return ["--judge-model", options.judge_model or "opus", "--claude-bin", claude]
    return ["--judge-model", options.judge_model or options.codex_model,
            "--codex-cmd", codex_command(options.codex_cmd)]


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
