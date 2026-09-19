"""Performance metrics on a per-bar net return series. All work on any subset of bars."""

import math

import numpy as np

BARS_PER_YEAR = 24 * 365


def sharpe(net: np.ndarray) -> float:
    std = net.std(ddof=1) if len(net) > 1 else 0.0
    return float(net.mean() / std * math.sqrt(BARS_PER_YEAR)) if std > 0 else math.nan


def max_drawdown(equity: np.ndarray) -> float:
    return float((equity / np.maximum.accumulate(equity) - 1).min())


def summarize(net: np.ndarray, turnover: np.ndarray) -> dict[str, float]:
    equity = np.cumprod(1 + net)
    return {
        "total_return": float(equity[-1] - 1),
        "sharpe": sharpe(net),
        "max_drawdown": max_drawdown(equity),
        "turnover": float(turnover.mean()),
        "n_trades": int((turnover > 0).sum()),
        "n_bars": int(len(net)),
    }
