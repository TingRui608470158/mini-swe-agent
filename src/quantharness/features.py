"""Point-in-time features of OHLCV bars.

`_core` is the only implementation. Both the batch (offline) and single-bar (online) entry
points call it on the same trailing slice, so their outputs are bit-identical by construction.
Feature set v2 (design/stage0-feature-library.md): the original 8 plus 9 volatility-structure
and calendar features. Names and order are the schema; never reorder or rename.
"""

import numpy as np
import pandas as pd

from quantharness.data import OHLCV_COLUMNS

LOOKBACK = 721
FEATURE_NAMES = (
    "ret_1",
    "ret_24",
    "sma_20_ratio",
    "sma_50_ratio",
    "vol_24",
    "vol_168",
    "range_1",
    "vol_ratio_24",
    "volatility_ratio_24_168",
    "volatility_720",
    "volatility_ratio_24_720",
    "hl_pos_168",
    "hl_pos_720",
    "volume_ratio_168",
    "range_ratio_24",
    "hour_utc",
    "weekday_utc",
)


def _log_return(close: np.ndarray, k: int) -> float:
    return float(np.log(close[-1] / close[-1 - k])) if len(close) > k else np.nan


def _sma_ratio(close: np.ndarray, window: int) -> float:
    return float(close[-1] / close[-window:].mean() - 1) if len(close) >= window else np.nan


def _std(returns: np.ndarray, window: int) -> float:
    return float(returns[-window:].std(ddof=1)) if len(returns) >= window else np.nan


def _ratio(numerator: float, denominator: float) -> float:
    return float(numerator / denominator) if denominator > 0 else np.nan


def _mean_ratio(values: np.ndarray, window: int) -> float:
    """values[-1] relative to the mean of the trailing `window` values (nan when short or zero)."""
    return _ratio(values[-1], values[-window:].mean()) if len(values) >= window else np.nan


def _hl_pos(high: np.ndarray, low: np.ndarray, close: np.ndarray, window: int) -> float:
    if len(close) < window:
        return np.nan
    lo, hi = low[-window:].min(), high[-window:].max()
    return _ratio(close[-1] - lo, hi - lo)


def _core(
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    hour: np.ndarray,
    weekday: np.ndarray,
) -> dict[str, float]:
    """Features of the last bar, using only the trailing LOOKBACK bars."""
    high, low, close, volume = high[-LOOKBACK:], low[-LOOKBACK:], close[-LOOKBACK:], volume[-LOOKBACK:]
    returns = np.log(close[1:] / close[:-1])
    ranges = (high - low) / close
    vol_24, vol_168, volatility_720 = _std(returns, 24), _std(returns, 168), _std(returns, 720)
    return {
        "ret_1": _log_return(close, 1),
        "ret_24": _log_return(close, 24),
        "sma_20_ratio": _sma_ratio(close, 20),
        "sma_50_ratio": _sma_ratio(close, 50),
        "vol_24": vol_24,
        "vol_168": vol_168,
        "range_1": float(ranges[-1]),
        "vol_ratio_24": _mean_ratio(volume, 24),
        "volatility_ratio_24_168": _ratio(vol_24, vol_168),
        "volatility_720": volatility_720,
        "volatility_ratio_24_720": _ratio(vol_24, volatility_720),
        "hl_pos_168": _hl_pos(high, low, close, 168),
        "hl_pos_720": _hl_pos(high, low, close, 720),
        "volume_ratio_168": _mean_ratio(volume, 168),
        "range_ratio_24": _mean_ratio(ranges, 24),
        "hour_utc": float(hour[-1]),
        "weekday_utc": float(weekday[-1]),
    }


def _arrays(bars: pd.DataFrame) -> list[np.ndarray]:
    ohlcv = [bars[col].to_numpy(dtype="float64") for col in OHLCV_COLUMNS]
    return [*ohlcv, bars.index.hour.to_numpy(dtype="float64"), bars.index.weekday.to_numpy(dtype="float64")]


def compute_features_at(bars: pd.DataFrame) -> dict[str, float]:
    """Online mode: features of the last bar given the history known so far."""
    return _core(*_arrays(bars))


def compute_features(bars: pd.DataFrame) -> pd.DataFrame:
    """Offline mode: features of every bar; row i only sees bars[: i + 1]."""
    arrays = _arrays(bars)
    rows = [_core(*(a[: i + 1] for a in arrays)) for i in range(len(bars))]
    return pd.DataFrame(rows, index=bars.index, columns=list(FEATURE_NAMES))
