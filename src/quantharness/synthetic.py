"""Synthetic bars with a known answer (Stage 2.5, minimal version).

`ar1_bars` has mean-reverting log returns, so `-sign(ret_1)` is a real edge that passes the
promotion gate; a strategy driven by (independent, random) volume does not. `trend_bars` has a
strong drift so that buy-and-hold alone has a large absolute Sharpe.
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


app = typer.Typer()


@app.command()
def main(out_dir: Path, seed: int = 1, n: int = 10_000) -> None:
    """Example: python -m quantharness.synthetic build/synthetic_raw --seed 1"""
    for offset, symbol in enumerate(SYMBOLS):
        save_ohlcv(ar1_bars(seed + offset, n), out_dir / f"{symbol}.csv")
    typer.echo(f"Wrote {len(SYMBOLS)} AR(1) symbols to {out_dir}", err=True)


if __name__ == "__main__":
    app()
