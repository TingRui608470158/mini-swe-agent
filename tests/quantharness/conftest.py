import numpy as np
import pandas as pd
import pytest

from quantharness.data import normalize_ohlcv

N_BARS = 400
GAP = slice(100, 103)
DUPLICATED_VOLUME = 12345.0


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
