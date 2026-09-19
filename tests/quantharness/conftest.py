from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantharness.data import normalize_ohlcv, save_ohlcv
from quantharness.gate import GateConfig
from quantharness.split import write_segments

N_BARS = 400
GAP = slice(100, 103)
DUPLICATED_VOLUME = 12345.0
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")

GOOD_STRATEGY = """import math

def generate_signal(features):
    if math.isnan(features["ret_1"]):
        return 0.0
    return -math.copysign(1.0, features["ret_1"])
"""
# Volume is independent noise in the synthetic data, so this has no edge but trades every bar
NOISE_STRATEGY = "def generate_signal(features):\n    return 1.0 if features['vol_ratio_24'] > 1 else -1.0\n"
ALWAYS_LONG_STRATEGY = "def generate_signal(features):\n    return 1.0\n"


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
    """Mean-reverting log returns r_t = -phi * r_{t-1} + eps: `-sign(ret_1)` is a real edge."""
    eps = np.random.default_rng(seed).normal(0, sigma, n)
    returns = np.zeros(n)
    for t in range(1, n):
        returns[t] = -phi * returns[t - 1] + eps[t]
    return bars_from_log_returns(returns, seed)


def trend_bars(seed: int, n: int = 10_000) -> pd.DataFrame:
    """Strong drift: buy-and-hold has an absolute Sharpe far above any plausible threshold."""
    return bars_from_log_returns(0.001 + np.random.default_rng(seed).normal(0, 0.005, n), seed)


def build_segments(tmp_path: Path, make_bars) -> Path:
    for i, symbol in enumerate(SYMBOLS):
        save_ohlcv(make_bars(i + 1), tmp_path / "raw" / f"{symbol}.csv")
    write_segments(tmp_path / "raw", tmp_path / "segments")
    return tmp_path / "segments"


@pytest.fixture(scope="session")
def ar1_segments(tmp_path_factory) -> Path:
    return build_segments(tmp_path_factory.mktemp("ar1"), ar1_bars)


@pytest.fixture(scope="session")
def trend_segments(tmp_path_factory) -> Path:
    return build_segments(tmp_path_factory.mktemp("trend"), trend_bars)


@pytest.fixture
def gate_config() -> GateConfig:
    return GateConfig(timeout_seconds=30)


@pytest.fixture
def strategy_file(tmp_path):
    def write(source: str, name: str = "strategy.py") -> Path:
        path = tmp_path / name
        path.write_text(source)
        return path

    return write


@pytest.fixture
def raw_ohlcv() -> pd.DataFrame:
    """Synthetic 1h bars, shuffled, with 3 bars missing and 2 bars re-appended at the end with a new volume."""
    rng = np.random.default_rng(0)
    ts = pd.date_range("2024-01-01", periods=N_BARS, freq="1h", tz="UTC", name="ts")
    close = 40_000 * np.exp(np.cumsum(rng.normal(0, 0.01, N_BARS)))
    open_ = np.concatenate([close[:1], close[:-1]])
    df = pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) * (1 + rng.uniform(0, 0.005, N_BARS)),
            "low": np.minimum(open_, close) * (1 - rng.uniform(0, 0.005, N_BARS)),
            "close": close,
            "volume": rng.uniform(100, 1000, N_BARS),
        },
        index=ts,
    ).drop(ts[GAP])
    return pd.concat([df.sample(frac=1, random_state=1), df.iloc[[10, 20]].assign(volume=DUPLICATED_VOLUME)])


@pytest.fixture
def ohlcv(raw_ohlcv: pd.DataFrame) -> pd.DataFrame:
    return normalize_ohlcv(raw_ohlcv)
