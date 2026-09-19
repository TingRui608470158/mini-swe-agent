"""OHLCV bars keyed by close time.

The index `ts` (UTC) is the instant a bar's close became known, i.e. `open_time + 1h`.
Anything dated `ts` may only depend on bars with index <= `ts`.
"""

from pathlib import Path

import pandas as pd

INTERVAL = pd.Timedelta("1h")
OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")


def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Sort by `ts`, keep the last of duplicated `ts`, and fill missing bars on the 1h grid
    with a zero-volume bar at the previous close (`is_gap=True`). Raises if a `ts` is off-grid.
    """
    df = df[~df.index.duplicated(keep="last")].sort_index()
    grid = pd.date_range(df.index[0], df.index[-1], freq=INTERVAL, name="ts")
    if not df.index.isin(grid).all():
        raise ValueError(f"timestamps are not on the {INTERVAL} grid")
    out = df[list(OHLCV_COLUMNS)].astype("float64").reindex(grid)
    out.insert(0, "open_time", (grid - INTERVAL).asi8 // 1_000_000)
    out["is_gap"] = out["close"].isna()
    if "is_gap" in df:
        out["is_gap"] |= df["is_gap"].reindex(grid, fill_value=False)
    out["close"] = out["close"].ffill()
    for col in ("open", "high", "low"):
        out[col] = out[col].fillna(out["close"])
    out["volume"] = out["volume"].fillna(0.0)
    return out


def load_ohlcv(path: Path) -> pd.DataFrame:
    # The default C float parser is not bit-exact, which would break determinism across save/load
    df = pd.read_csv(path, float_precision="round_trip")
    return normalize_ohlcv(df.set_index(pd.to_datetime(df.pop("ts"), utc=True)))


def save_ohlcv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, date_format="%Y-%m-%dT%H:%M:%S%z")
