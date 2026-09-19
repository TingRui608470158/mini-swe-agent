import json
import math
import statistics

import numpy as np
import pandas as pd
import pytest

from quantharness.backtest import CostModel, run_backtest
from quantharness.data import OHLCV_COLUMNS
from quantharness.features import FEATURE_NAMES, compute_features
from quantharness.metrics import BARS_PER_YEAR
from quantharness.strategy import load_strategy

REPORT_KEYS = ("period", "cost_model", "strategy", "benchmark", "corr_with_benchmark")
METRIC_KEYS = ("total_return", "sharpe", "max_drawdown", "turnover", "n_trades", "n_bars")


def _frame(**columns: list[float]) -> pd.DataFrame:
    n = len(next(iter(columns.values())))
    return pd.DataFrame(columns, index=pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC", name="ts"))


def test_loaded_trivial_strategy_produces_full_report(ohlcv, tmp_path):
    (tmp_path / "sma.py").write_text(
        "def generate_signal(features):\n    return 1.0 if features['sma_50_ratio'] > 0 else 0.0\n"
    )
    report = run_backtest(ohlcv, compute_features(ohlcv), load_strategy(tmp_path / "sma.py")).report()
    assert tuple(report) == REPORT_KEYS
    assert tuple(report["strategy"]) == tuple(report["benchmark"]) == METRIC_KEYS
    assert report["period"]["n_bars"] == report["strategy"]["n_bars"] == len(ohlcv)
    assert report["cost_model"] == {"fee_bps": 10.0, "slippage_bps": 5.0}
    assert report["strategy"]["n_trades"] > 0 and -1 <= report["corr_with_benchmark"] <= 1


def test_backtest_is_deterministic(ohlcv):
    features = compute_features(ohlcv)
    first, second = (run_backtest(ohlcv, features, lambda f: f["ret_1"] * 50) for _ in range(2))
    pd.testing.assert_frame_equal(first.series, second.series, check_exact=True)
    assert json.dumps(first.report()) == json.dumps(second.report())


def test_values_against_hand_computation():
    bars = _frame(close=[100.0, 150.0, 75.0, 75.0, 112.5, 112.5])
    target = [0.0, 1.0, 1.0, -1.0, 0.0, 0.0]
    result = run_backtest(bars, _frame(target=target), lambda f: f["target"], CostModel(fee_bps=10, slippage_bps=0))
    s = result.series
    assert list(s["pos"]) == target
    assert list(s["turnover"]) == [0.0, 1.0, 0.0, 2.0, 1.0, 0.0]
    assert list(s["gross"]) == [0.0, 0.0, -0.5, 0.0, -0.5, 0.0]
    assert list(s["cost"]) == [0.0, 0.001, 0.0, 0.002, 0.001, 0.0]
    net = [0.0, 0.0 - 0.001, -0.5 - 0.0, 0.0 - 0.002, -0.5 - 0.001, 0.0]
    assert list(s["net"]) == net
    e1 = 1 + net[1]
    e2 = e1 * (1 + net[2])
    e3 = e2 * (1 + net[3])
    e4 = e3 * (1 + net[4])
    assert list(s["equity"]) == [1.0, e1, e2, e3, e4, e4]
    metrics = result.report()["strategy"]
    assert metrics["total_return"] == metrics["max_drawdown"] == e4 - 1
    assert metrics["turnover"] == 4 / 6 and metrics["n_trades"] == 3 and metrics["n_bars"] == 6
    assert metrics["sharpe"] == pytest.approx(statistics.mean(net) / statistics.stdev(net) * math.sqrt(BARS_PER_YEAR))


def test_results_do_not_depend_on_future_bars(ohlcv):
    t, rng = 250, np.random.default_rng(2)
    features = compute_features(ohlcv)

    def strategy(f: dict) -> float:
        return f["sma_20_ratio"] * 10

    clean = run_backtest(ohlcv, features, strategy).series
    corrupted_bars, corrupted_features = ohlcv.copy(), features.copy()
    corrupted_bars.iloc[t + 1 :, corrupted_bars.columns.get_indexer(list(OHLCV_COLUMNS))] = rng.uniform(
        1, 2, (len(ohlcv) - t - 1, 5)
    )
    corrupted_features.iloc[t + 1 :] = rng.uniform(-1, 1, (len(ohlcv) - t - 1, len(FEATURE_NAMES)))
    corrupted = run_backtest(corrupted_bars, corrupted_features, strategy).series
    pd.testing.assert_frame_equal(corrupted.iloc[: t + 1], clean.iloc[: t + 1], check_exact=True)

    def leaky(bars: pd.DataFrame) -> pd.DataFrame:
        """Features that leak the next close; the same check must catch a strategy using them."""
        return bars.assign(next_close=bars["close"].shift(-1))

    def peek(f: dict) -> float:
        return f["next_close"] / f["close"] - 1

    clean_pos = run_backtest(ohlcv, leaky(ohlcv), peek).series["pos"].iloc[: t + 1]
    corrupted_pos = run_backtest(corrupted_bars, leaky(corrupted_bars), peek).series["pos"].iloc[: t + 1]
    assert not clean_pos.equals(corrupted_pos)


def test_signals_are_sanitized_and_clipped():
    bars = _frame(close=[1.0] * 5)
    signals = [2.0, -5.0, math.nan, math.inf, 0.5]
    assert list(run_backtest(bars, _frame(s=signals), lambda f: f["s"]).series["pos"]) == [1.0, -1.0, 0.0, 0.0, 0.5]


def test_constant_long_strategy_equals_benchmark(ohlcv):
    result = run_backtest(ohlcv, compute_features(ohlcv), lambda f: 1.0)
    pd.testing.assert_frame_equal(result.series, result.benchmark, check_exact=True)
    assert result.report()["strategy"] == result.report()["benchmark"]
    assert result.report()["strategy"]["n_trades"] == 1


def test_misaligned_features_are_rejected(ohlcv):
    with pytest.raises(ValueError, match="index"):
        run_backtest(ohlcv, compute_features(ohlcv).iloc[1:], lambda f: 0.0)
