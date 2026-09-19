"""Deterministic backtest. See design/stage1-backtest-engine.md for the rules (R1-R6).

Position `pos[t]` is decided at bar t's close (from bar t's features), filled at close[t], and
earns close[t] -> close[t+1]. Turnover is charged at t. The benchmark is the constant strategy
`1.0` pushed through the exact same path.
"""

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from quantharness.metrics import summarize
from quantharness.strategy import Strategy, sanitize


@dataclass
class CostModel:
    fee_bps: float = 10.0
    slippage_bps: float = 5.0

    @property
    def rate(self) -> float:
        return (self.fee_bps + self.slippage_bps) / 10_000


@dataclass
class BacktestResult:
    series: pd.DataFrame
    benchmark: pd.DataFrame
    cost_model: CostModel

    def report(self) -> dict:
        return {
            "period": {
                "start": self.series.index[0].isoformat(),
                "end": self.series.index[-1].isoformat(),
                "n_bars": len(self.series),
            },
            "cost_model": asdict(self.cost_model),
            "strategy": summarize(self.series["net"].to_numpy(), self.series["turnover"].to_numpy()),
            "benchmark": summarize(self.benchmark["net"].to_numpy(), self.benchmark["turnover"].to_numpy()),
            "corr_with_benchmark": float(np.corrcoef(self.series["net"], self.benchmark["net"])[0, 1]),
        }


def _positions(features: pd.DataFrame, strategy: Strategy) -> np.ndarray:
    return np.array([sanitize(strategy(row)) for row in features.to_dict("records")], dtype="float64")


def _simulate(close: np.ndarray, pos: np.ndarray, rate: float, index: pd.Index) -> pd.DataFrame:
    gross = np.zeros(len(close))
    gross[1:] = pos[:-1] * (close[1:] / close[:-1] - 1)
    turnover = np.abs(np.diff(pos, prepend=0.0))
    cost = turnover * rate
    net = gross - cost
    return pd.DataFrame(
        {"pos": pos, "turnover": turnover, "gross": gross, "cost": cost, "net": net, "equity": np.cumprod(1 + net)},
        index=index,
    )


def backtest_positions(bars: pd.DataFrame, pos: np.ndarray, cost: CostModel = CostModel()) -> BacktestResult:
    close = bars["close"].to_numpy(dtype="float64")
    return BacktestResult(
        series=_simulate(close, pos, cost.rate, bars.index),
        benchmark=_simulate(close, np.ones_like(close), cost.rate, bars.index),
        cost_model=cost,
    )


def run_backtest(
    bars: pd.DataFrame, features: pd.DataFrame, strategy: Strategy, cost: CostModel = CostModel()
) -> BacktestResult:
    if not features.index.equals(bars.index):
        raise ValueError("features and bars must share the same index")
    return backtest_positions(bars, _positions(features, strategy), cost)
