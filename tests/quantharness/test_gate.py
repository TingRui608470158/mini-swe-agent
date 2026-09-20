import json

import pytest
from typer.testing import CliRunner

from quantharness.gate import Budget, GateConfig, app, evaluate, purity_check
from quantharness.split import load_bounds
from tests.quantharness.conftest import ALWAYS_LONG_STRATEGY, GOOD_STRATEGY, NOISE_STRATEGY, VOL_REGIME_STRATEGY

CRITERIA = ("purity", "relative_sharpe", "regimes", "beta", "net_return", "cross_asset")


def _evaluate(segments, strategy, config, segment="validation"):
    return evaluate(strategy, segment, segments, load_bounds(segments / "split.json"), config)


def test_always_long_is_blocked_despite_high_absolute_sharpe(trend_segments, strategy_file, gate_config):
    result = _evaluate(trend_segments, strategy_file(ALWAYS_LONG_STRATEGY), gate_config)
    assert result["criteria"]["relative_sharpe"]["benchmark"] > 2
    assert result["pass"] is False
    assert result["criteria"]["relative_sharpe"]["pass"] is False
    assert result["criteria"]["beta"]["pass"] is False
    assert result["criteria"]["beta"]["value"] == pytest.approx(1.0)


def test_real_edge_passes_and_noise_fails(ar1_segments, strategy_file, gate_config):
    good = _evaluate(ar1_segments, strategy_file(GOOD_STRATEGY, "good.py"), gate_config)
    assert good["pass"] is True
    assert {name: c["pass"] for name, c in good["criteria"].items()} == dict.fromkeys(CRITERIA, True)
    assert sum(v != "absent" for v in good["criteria"]["regimes"]["value"].values()) >= 2
    assert set(good["criteria"]["cross_asset"]["value"]) == {"ETHUSDT", "SOLUSDT"}
    noise = _evaluate(ar1_segments, strategy_file(NOISE_STRATEGY, "noise.py"), gate_config)
    assert noise["pass"] is False and noise["criteria"]["net_return"]["pass"] is False


def test_volatility_regime_edge_passes_and_noise_fails(regime_segments, strategy_file, gate_config):
    """Stage 2.5 for feature set v2: the planted regime edge is findable through the new features."""
    good = _evaluate(regime_segments, strategy_file(VOL_REGIME_STRATEGY, "regime.py"), gate_config)
    assert good["pass"] is True
    assert {name: c["pass"] for name, c in good["criteria"].items()} == dict.fromkeys(CRITERIA, True)
    assert good["criteria"]["relative_sharpe"]["benchmark"] < 1  # buy-and-hold has nothing to offer here
    assert _evaluate(regime_segments, strategy_file(NOISE_STRATEGY, "noise.py"), gate_config)["pass"] is False


def test_purity_check_runs_on_train_and_reports_violations(ar1_segments, strategy_file, gate_config):
    bounds = load_bounds(ar1_segments / "split.json")
    assert purity_check(strategy_file(GOOD_STRATEGY), ar1_segments, bounds, gate_config) is None
    violation = purity_check(
        strategy_file("import os\n" + ALWAYS_LONG_STRATEGY, "bad.py"), ar1_segments, bounds, gate_config
    )
    assert violation.line == 1 and "os" in violation.reason


def test_cli_budget_is_a_per_run_total(ar1_segments, strategy_file, tmp_path):
    runner, state, config = CliRunner(), tmp_path / "budget.json", tmp_path / "config.json"
    Budget(state).init(2)
    config.write_text(json.dumps({"timeout_seconds": 30}))
    data = ["--segments-dir", str(ar1_segments), "--split", str(ar1_segments / "split.json"), "--config", str(config)]
    good = str(strategy_file(GOOD_STRATEGY, "good.py"))

    def invoke(*args):
        result = runner.invoke(app, list(args), catch_exceptions=False)
        return result.exit_code, json.loads(result.stdout)

    assert invoke("check", good, *data) == (0, {"purity": {"pass": True}})
    assert Budget(state).remaining() == 2

    code, payload = invoke("score", good, "--segment", "train", *data, "--state", str(state))
    assert code in (0, 1) and payload["budget_remaining"] == 2 and Budget(state).remaining() == 2

    bad = str(strategy_file("import socket\n" + GOOD_STRATEGY, "bad.py"))
    code, payload = invoke("score", bad, *data, "--state", str(state))
    assert code == 2 and payload["refused"].startswith("purity") and Budget(state).remaining() == 2

    code, payload = invoke("score", good, *data, "--state", str(state))
    assert code == 0 and payload["pass"] is True and payload["budget_remaining"] == 1
    assert tuple(payload) == ("segment", "symbol", "period", "budget_remaining", "criteria", "pass")
    assert tuple(payload["criteria"]) == CRITERIA and payload["segment"] == "validation"
    assert "series" not in json.dumps(payload) and "close" not in json.dumps(payload)

    code, payload = invoke("score", good, *data, "--state", str(state))
    assert code == 0 and payload["budget_remaining"] == 0

    # Exhausted budget refuses before the file is even read: a syntax error would otherwise be reported
    broken = str(strategy_file("def generate_signal(\n", "broken.py"))
    assert invoke("score", broken, *data, "--state", str(state)) == (
        2,
        {"refused": "budget exhausted", "budget_remaining": 0},
    )
    assert invoke("budget", "--state", str(state)) == (0, {"budget_remaining": 0})


def test_config_round_trips_through_json(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"sharpe_margin": 1.0, "cross_symbols": ["ETHUSDT"], "budget": 5}))
    assert GateConfig.load(path) == GateConfig(sharpe_margin=1.0, cross_symbols=("ETHUSDT",), budget=5)
