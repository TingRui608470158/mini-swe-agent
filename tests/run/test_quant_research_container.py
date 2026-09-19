"""Stage 3 acceptance (scripted agent, real gate container): the verdict is derived from root-only evidence."""

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from minisweagent.models.test_models import make_output
from minisweagent.run.extra.quant_research import app
from tests.quantharness.conftest import GOOD_STRATEGY

REPO = Path(__file__).resolve().parents[2]
IMAGE = "quantharness-gate:synthetic-test"
WRITE_GOOD = f"cat <<'EOF' > /workspace/strategy.py\n{GOOD_STRATEGY}EOF"
CHECK = "sudo -n /gate/bin/gate check /workspace/strategy.py"
SCORE = "sudo -n /gate/bin/gate score /workspace/strategy.py"
SUBMIT = "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def image(tmp_path_factory):
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        pytest.skip("docker daemon not available")
    raw = tmp_path_factory.mktemp("raw")
    subprocess.run([sys.executable, "-m", "quantharness.synthetic", str(raw), "--n", "6000"], check=True)
    build = REPO / "build" / "segments"
    shutil.rmtree(build, ignore_errors=True)
    subprocess.run([sys.executable, "-m", "quantharness.split", str(raw), str(build)], check=True)
    subprocess.run(["docker", "build", "-q", "-f", "docker/gate/Dockerfile", "-t", IMAGE, "."], cwd=REPO, check=True)
    return IMAGE


def run_harness(tmp_path: Path, image: str, commands: list[str], budget: int = 20, **agent_config) -> dict:
    scripted = tmp_path / "scripted.yaml"
    scripted.write_text(
        yaml.safe_dump(
            {
                "model": {
                    "model_class": "minisweagent.models.test_models.DeterministicModel",
                    "model_name": "deterministic",
                    "outputs": [make_output(f"step {i}", [{"command": c}]) for i, c in enumerate(commands)],
                },
                "agent": {"step_limit": len(commands), **agent_config},
            }
        )
    )
    args = [
        "-c",
        "mini.yaml",
        "-c",
        "quant_research.yaml",
        "-c",
        str(scripted),
        "--image",
        image,
        "--budget",
        str(budget),
        "-o",
        str(tmp_path / "runs"),
    ]
    result = CliRunner().invoke(app, args, catch_exceptions=False)
    run_dir = next((tmp_path / "runs").iterdir())
    return {"exit_code": result.exit_code, "dir": run_dir, **json.loads((run_dir / "verdict.json").read_text())}


def test_scripted_happy_path_is_verified_pass(tmp_path, image):
    run = run_harness(tmp_path, image, [WRITE_GOOD, CHECK, SCORE, SUBMIT], budget=7)
    assert run["verdict"] == "PASS" and run["exit_status"] == "Submitted" and run["exit_code"] == 0
    assert all(run["probes"].values()) and run["budget"] == 7 and run["budget_remaining"] == 6
    assert {p.name for p in run["dir"].iterdir()} == {
        "trajectory.traj.json",
        "strategy.py",
        "scores.jsonl",
        "budget.json",
        "verdict.json",
    }
    assert run["sha256"] == hashlib.sha256((run["dir"] / "strategy.py").read_bytes()).hexdigest()
    scores = [json.loads(l) for l in (run["dir"] / "scores.jsonl").read_text().splitlines()]
    assert len(scores) == 1 and scores[0]["pass"] is True and scores[0]["sha256"] == run["sha256"]
    trajectory = json.loads((run["dir"] / "trajectory.traj.json").read_text())
    assert trajectory["trajectory_format"] == "mini-swe-agent-1.1" and trajectory["messages"][-1]["role"] == "exit"
    assert run["model_stats"]["n_calls"] == 4


def test_submitting_without_a_gate_pass_is_unverified(tmp_path, image):
    run = run_harness(tmp_path, image, [WRITE_GOOD, CHECK, SUBMIT])
    assert run["verdict"] == "FAIL_UNVERIFIED" and run["exit_status"] == "Submitted"
    assert (run["dir"] / "scores.jsonl").read_text() == ""


def test_editing_the_file_after_it_passed_is_unverified(tmp_path, image):
    tamper = "sed -i 's/return 0.0/return 0.00/' /workspace/strategy.py"
    run = run_harness(tmp_path, image, [WRITE_GOOD, SCORE, tamper, SUBMIT])
    assert run["verdict"] == "FAIL_UNVERIFIED"
    scores = [json.loads(l) for l in (run["dir"] / "scores.jsonl").read_text().splitlines()]
    assert scores[0]["pass"] is True and scores[0]["sha256"] != run["sha256"]


def test_step_limit_ends_the_run_as_fail_limits(tmp_path, image):
    run = run_harness(tmp_path, image, ["ls /workspace", "ls /data/train"])
    assert run["verdict"] == "FAIL_LIMITS" and run["exit_status"] == "LimitsExceeded"
    assert "strategy.py" not in {p.name for p in run["dir"].iterdir()}
