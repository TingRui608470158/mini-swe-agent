#!/usr/bin/env python3
"""Stage 3 research harness: one agent, one gate container, one independently verified verdict.

See design/stage3-research-harness.md. The verdict never trusts the agent: it is derived from the
gate's root-only score log and the hash of /workspace/strategy.py after the run.
"""

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

import typer

from minisweagent.agents import get_agent
from minisweagent.config import builtin_config_dir, get_config_from_spec
from minisweagent.environments import get_environment
from minisweagent.environments.docker import DockerEnvironment
from minisweagent.models import get_model
from minisweagent.utils.serialize import UNSET, recursive_merge

DEFAULT_CONFIGS = [str(builtin_config_dir / "mini.yaml"), str(builtin_config_dir / "extra" / "quant_research.yaml")]
DEFAULT_TASK = "Develop a trading strategy that passes the promotion gate."
STRATEGY_PATH = "/workspace/strategy.py"
STATE_DIR = "/gate/state"
LIMIT_STATUSES = ("LimitsExceeded", "TimeExceeded", "RepeatedFormatError", "ContextExhausted")

app = typer.Typer(rich_markup_mode="rich", add_completion=False)


def docker_root(env: DockerEnvironment, *args: str) -> subprocess.CompletedProcess:
    """Run a command in the container as root: the harness's privilege, never the agent's."""
    return subprocess.run([env.config.executable, "exec", "-u", "root", env.container_id, *args], capture_output=True)


def init_gate_state(env: DockerEnvironment, budget: int) -> None:
    script = (
        f"printf '%s' '{json.dumps({'remaining': budget})}' > {STATE_DIR}/budget.json && : > {STATE_DIR}/scores.jsonl"
    )
    docker_root(env, "sh", "-c", script).check_returncode()


def read_root_file(env: DockerEnvironment, path: str) -> bytes | None:
    result = docker_root(env, "cat", path)
    return result.stdout if result.returncode == 0 else None


PROBES = {
    "agent_user": "id -un",
    "validation_unreadable": "cat /data/validation/BTCUSDT.csv",
    "holdout_absent": "ls /data/holdout",
    "no_network": "python -c \"import socket; socket.create_connection(('1.1.1.1', 53), 2)\"",
    "gate_budget": "sudo -n /gate/bin/gate budget",
}


def run_probes(env: DockerEnvironment, budget: int) -> dict[str, bool]:
    """Stage 2's isolation checks, executed as the agent before every run (R5)."""
    return judge_probes({name: env.execute({"command": cmd}) for name, cmd in PROBES.items()}, budget)


def judge_probes(out: dict[str, dict], budget: int) -> dict[str, bool]:
    return {
        "agent_user": out["agent_user"]["output"].strip() == "agent",
        "validation_unreadable": out["validation_unreadable"]["returncode"] != 0,
        "holdout_absent": out["holdout_absent"]["returncode"] != 0,
        "no_network": out["no_network"]["returncode"] != 0,
        "gate_budget": out["gate_budget"]["returncode"] == 0
        and f'"budget_remaining": {budget}' in out["gate_budget"]["output"],
    }


def decide(exit_status: str, strategy: bytes | None, scores: list[dict], budget_remaining: int | None) -> str:
    """R3 verdict table, in priority order."""
    if exit_status == "Submitted":
        if strategy is None:
            return "FAIL_UNVERIFIED"
        digest = hashlib.sha256(strategy).hexdigest()
        matching = [s for s in scores if s["sha256"] == digest]
        return "PASS" if matching and matching[-1]["pass"] else "FAIL_UNVERIFIED"
    if budget_remaining == 0 and not any(s["pass"] for s in scores):
        return "FAIL_BUDGET"
    if exit_status in LIMIT_STATUSES:
        return "FAIL_LIMITS"
    return "ERROR"


def _parse_scores(raw: bytes | None) -> list[dict]:
    return [json.loads(line) for line in (raw or b"").decode().splitlines() if line.strip()]


# fmt: off
@app.command(help="Run the Stage 3 research harness against a gate image.")
def main(
    config_spec: list[str] = typer.Option(DEFAULT_CONFIGS, "-c", "--config", help="Config files / key=value specs, merged in order"),
    model_name: str | None = typer.Option(None, "-m", "--model", help="e.g. ollama_chat/qwen3:32b"),
    model_class: str | None = typer.Option(None, "--model-class", help="e.g. litellm_textbased for models without tool calling"),
    image: str | None = typer.Option(None, "--image", help="Gate image, e.g. quantharness-gate:synthetic"),
    budget: int | None = typer.Option(None, "--budget", help="Validation query budget for this run"),
    output_dir: Path = typer.Option(Path("runs"), "-o", "--output-dir"),
    task: str = typer.Option(DEFAULT_TASK, "-t", "--task"),
) -> None:
    # fmt: on
    config = recursive_merge(
        *[get_config_from_spec(spec) for spec in config_spec],
        {
            "model": {"model_name": model_name or UNSET, "model_class": model_class or UNSET},
            "environment": {"image": image or UNSET},
            "gate": {"budget": budget if budget is not None else UNSET},
        },
    )
    image, gate_budget = config["environment"]["image"], int(config["gate"]["budget"])
    run_dir = output_dir / f"{datetime.now():%Y%m%d-%H%M%S}-{image.replace('/', '_').replace(':', '-')}"
    run_dir.mkdir(parents=True)
    config["agent"]["output_path"] = run_dir / "trajectory.traj.json"
    config["agent"]["num_ctx"] = config["model"].get("model_kwargs", {}).get("num_ctx", 0)
    verdict: dict = {"verdict": "ERROR", "image": image, "budget": gate_budget, "config": config_spec}

    env = get_environment(config["environment"], default_type="docker")
    try:
        init_gate_state(env, gate_budget)
        verdict["probes"] = run_probes(env, gate_budget)
        if not all(verdict["probes"].values()):
            verdict["exit_status"] = "ProbeFailed"
            (run_dir / "verdict.json").write_text(json.dumps(verdict, indent=2, default=str))
            typer.echo(f"ERROR: sandbox probes failed: {verdict['probes']}", err=True)
            raise typer.Exit(1)

        agent = get_agent(get_model(config=config["model"]), env, config["agent"])
        action_format = "textbased" if "textbased" in str(config["model"].get("model_class", "")) else "toolcall"
        try:
            result = agent.run(task, action_format=action_format, gate_budget=gate_budget)
        except Exception:
            (run_dir / "verdict.json").write_text(json.dumps(verdict | {"exit_status": "Exception"}, indent=2, default=str))
            raise

        strategy = read_root_file(env, STRATEGY_PATH)
        scores_raw, budget_raw = read_root_file(env, f"{STATE_DIR}/scores.jsonl"), read_root_file(env, f"{STATE_DIR}/budget.json")
        scores = _parse_scores(scores_raw)
        remaining = json.loads(budget_raw)["remaining"] if budget_raw else None
        verdict |= {
            "verdict": decide(result.get("exit_status", ""), strategy, scores, remaining),
            "exit_status": result.get("exit_status", ""),
            "submission": result.get("submission", ""),
            "sha256": hashlib.sha256(strategy).hexdigest() if strategy is not None else None,
            "budget_remaining": remaining,
            "model_stats": {"cost": agent.cost, "n_calls": agent.n_calls},
        }
        if strategy is not None:
            (run_dir / "strategy.py").write_bytes(strategy)
        (run_dir / "scores.jsonl").write_bytes(scores_raw or b"")
        (run_dir / "budget.json").write_bytes(budget_raw or b"")
        (run_dir / "verdict.json").write_text(json.dumps(verdict, indent=2, default=str))
        typer.echo(f"{verdict['verdict']} ({verdict['exit_status']}) -> {run_dir}", err=True)
    finally:
        env.cleanup()
        # DockerEnvironment.cleanup() uses a POSIX shell one-liner that fails on Windows; be sure.
        subprocess.run([env.config.executable, "rm", "-f", env.container_id], capture_output=True)


if __name__ == "__main__":
    app()
