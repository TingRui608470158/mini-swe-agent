"""Stage 2 acceptance 6: filesystem/network isolation as seen by the agent user inside the container."""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
IMAGE = "quantharness-gate-test"

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def image(ar1_segments):
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        pytest.skip("docker daemon not available")
    build = REPO / "build" / "segments"
    shutil.rmtree(build, ignore_errors=True)
    shutil.copytree(ar1_segments, build)
    subprocess.run(["docker", "build", "-q", "-f", "docker/gate/Dockerfile", "-t", IMAGE, "."], cwd=REPO, check=True)
    return IMAGE


def _run(image: str, command: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "run", "--rm", "--network", "none", image, "bash", "-lc", command], capture_output=True, text=True
    )


def test_agent_cannot_read_validation_or_see_holdout(image):
    assert _run(image, "id -un").stdout.strip() == "agent"
    features = "from pathlib import Path; from quantharness.data import load_ohlcv; from quantharness.features import compute_features; print(compute_features(load_ohlcv(Path('/data/train/BTCUSDT.csv'))).shape[1])"
    assert _run(image, f'python -c "{features}"').stdout.strip() == "8"
    assert "Permission denied" in _run(image, "cat /data/validation/BTCUSDT.csv").stderr
    assert "No such file" in _run(image, "ls /data/holdout").stderr


def test_agent_cannot_tamper_with_gate_or_budget(image):
    assert _run(image, "touch /gate/x").returncode != 0
    assert _run(image, "echo '{\"remaining\": 99}' > /gate/state/budget.json").returncode != 0
    assert _run(image, "cat /gate/state/budget.json").returncode != 0


def test_agent_can_only_reach_gate_through_sudo(image):
    gate = _run(image, "sudo -n /gate/bin/gate budget")
    assert '"budget_remaining": 20' in gate.stdout and gate.stderr == ""
    assert _run(image, "sudo -n cat /data/validation/BTCUSDT.csv").returncode != 0
    assert _run(image, "sudo -n python -c 'print(1)'").returncode != 0


def test_container_has_no_network(image):
    probe = "import socket; socket.create_connection(('1.1.1.1', 53), 2)"
    assert _run(image, f'python -c "{probe}"').returncode != 0
