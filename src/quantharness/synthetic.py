"""Synthetic bars with a known answer (Stage 2.5, minimal version).

`ar1_bars` has mean-reverting log returns, so `-sign(ret_1)` is a real edge that passes the
promotion gate; a strategy driven by (independent, random) volume does not. `regime_bars` drifts
up in its high-volatility regime and down in its low one, so a volatility-ratio switch is the edge.
`trend_bars` has a strong drift so that buy-and-hold alone has a large absolute Sharpe.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import typer

from quantharness.data import normalize_ohlcv, save_ohlcv

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def bars_from_log_returns(returns: np.ndarray, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(returns))
    open_ = np.concatenate([close[:1], close[:-1]])
    ts = pd.date_range("2021-01-01", periods=len(returns), freq="1h", tz="UTC", name="ts")
    return normalize_ohlcv(
        pd.DataFrame(
            {
                "open": open_,
                "high": np.maximum(open_, close) * 1.001,
                "low": np.minimum(open_, close) * 0.999,
                "close": close,
                "volume": rng.uniform(100, 1000, len(returns)),
            },
            index=ts,
        )
    )


def ar1_bars(seed: int, n: int = 10_000, phi: float = 0.6, sigma: float = 0.01) -> pd.DataFrame:
    """r_t = -phi * r_{t-1} + eps_t."""
    eps = np.random.default_rng(seed).normal(0, sigma, n)
    returns = np.zeros(n)
    for t in range(1, n):
        returns[t] = -phi * returns[t - 1] + eps[t]
    return bars_from_log_returns(returns, seed)


def trend_bars(seed: int, n: int = 10_000) -> pd.DataFrame:
    return bars_from_log_returns(0.001 + np.random.default_rng(seed).normal(0, 0.005, n), seed)


def regime_bars(
    seed: int,
    n: int = 10_000,
    p_stay: float = 0.99,
    sigma_low: float = 0.006,
    sigma_high: float = 0.010,
    drift: float = 0.0015,
) -> pd.DataFrame:
    """Two-state Markov volatility regime with symmetric drift: +drift in the high-volatility
    state, -drift in the low one, so buy-and-hold is flat while the regime is tradable.

    Observable proxy: `volatility_ratio_24_168`. Known answer: `+1 if ratio > 1.0 else -1`.
    Sigma levels are close enough that the strategy's correlation with buy-and-hold stays < 0.7.
    """
    rng = np.random.default_rng(seed)
    high = np.zeros(n, dtype=bool)
    for t in range(1, n):
        high[t] = high[t - 1] if rng.random() < p_stay else not high[t - 1]
    returns = np.where(high, drift, -drift) + np.where(high, sigma_high, sigma_low) * rng.normal(0, 1, n)
    return bars_from_log_returns(returns, seed)


GENERATORS = {"ar1": ar1_bars, "regime": regime_bars}

app = typer.Typer()


@app.command()
def main(out_dir: Path, seed: int = 1, n: int = 10_000, kind: str = "ar1") -> None:
    """Example: python -m quantharness.synthetic build/synthetic_raw --seed 1 --kind ar1|regime"""
    for offset, symbol in enumerate(SYMBOLS):
        save_ohlcv(GENERATORS[kind](seed + offset, n), out_dir / f"{symbol}.csv")
    typer.echo(f"Wrote {len(SYMBOLS)} {kind} symbols to {out_dir}", err=True)


if __name__ == "__main__":
    app()
