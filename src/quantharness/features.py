"""Point-in-time features of OHLCV bars.

`_core` is the only implementation. Both the batch (offline) and single-bar (online) entry
points call it on the same trailing slice, so their outputs are bit-identical by construction.
"""

import numpy as np
import pandas as pd

from quantharness.data import OHLCV_COLUMNS

LOOKBACK = 169
FEATURE_NAMES = ("ret_1", "ret_24", "sma_20_ratio", "sma_50_ratio", "vol_24", "vol_168", "range_1", "vol_ratio_24")


def _log_return(close: np.ndarray, k: int) -> float:
    return float(np.log(close[-1] / close[-1 - k])) if len(close) > k else np.nan


def _sma_ratio(close: np.ndarray, window: int) -> float:
    return float(close[-1] / close[-window:].mean() - 1) if len(close) >= window else np.nan


def _std(returns: np.ndarray, window: int) -> float:
    return float(returns[-window:].std(ddof=1)) if len(returns) >= window else np.nan


def _volume_ratio(volume: np.ndarray, window: int) -> float:
    mean = volume[-window:].mean() if len(volume) >= window else 0.0
    return float(volume[-1] / mean) if mean > 0 else np.nan


def _core(
    open_: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: np.ndarray
) -> dict[str, float]:
    """Features of the last bar, using only the trailing LOOKBACK bars."""
    high, low, close, volume = high[-LOOKBACK:], low[-LOOKBACK:], close[-LOOKBACK:], volume[-LOOKBACK:]
    returns = np.log(close[1:] / close[:-1])
    return {
        "ret_1": _log_return(close, 1),
        "ret_24": _log_return(close, 24),
        "sma_20_ratio": _sma_ratio(close, 20),
        "sma_50_ratio": _sma_ratio(close, 50),
        "vol_24": _std(returns, 24),
        "vol_168": _std(returns, 168),
        "range_1": float((high[-1] - low[-1]) / close[-1]),
        "vol_ratio_24": _volume_ratio(volume, 24),
    }


def _arrays(bars: pd.DataFrame) -> list[np.ndarray]:
    return [bars[col].to_numpy(dtype="float64") for col in OHLCV_COLUMNS]


def compute_features_at(bars: pd.DataFrame) -> dict[str, float]:
    """Online mode: features of the last bar given the history known so far."""
    return _core(*_arrays(bars))


def compute_features(bars: pd.DataFrame) -> pd.DataFrame:
    """Offline mode: features of every bar; row i only sees bars[: i + 1]."""
    arrays = _arrays(bars)
    rows = [_core(*(a[: i + 1] for a in arrays)) for i in range(len(bars))]
    return pd.DataFrame(rows, index=bars.index, columns=list(FEATURE_NAMES))
