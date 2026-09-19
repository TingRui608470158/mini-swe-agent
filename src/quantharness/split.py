"""Time-ordered train / validation / holdout split (Stage 2 R1).

Bounds are taken from BTCUSDT by bar count and applied to every symbol by timestamp. Each
segment file carries the preceding LOOKBACK bars as warmup so its features equal the
full-series features bit for bit; the warmup is not part of the segment body.
"""

import json
from pathlib import Path

import pandas as pd
import typer

from quantharness.data import load_ohlcv, save_ohlcv
from quantharness.features import LOOKBACK

SEGMENTS = ("train", "validation", "holdout")
REFERENCE_SYMBOL = "BTCUSDT"
Bounds = tuple[pd.Timestamp, pd.Timestamp]


def split_bounds(bars: pd.DataFrame) -> Bounds:
    return bars.index[int(len(bars) * 0.6)], bars.index[int(len(bars) * 0.8)]


def body_start(name: str, bounds: Bounds) -> pd.Timestamp | None:
    return {"train": None, "validation": bounds[0], "holdout": bounds[1]}[name]


def segment(bars: pd.DataFrame, name: str, bounds: Bounds) -> pd.DataFrame:
    """Segment body plus LOOKBACK warmup bars (train has none)."""
    start, end = body_start(name, bounds), {"train": bounds[0], "validation": bounds[1], "holdout": None}[name]
    i0 = 0 if start is None else bars.index.searchsorted(start)
    i1 = len(bars) if end is None else bars.index.searchsorted(end)
    return bars.iloc[max(0, i0 - LOOKBACK) : i1]


def load_bounds(path: Path) -> Bounds:
    raw = json.loads(path.read_text())
    return pd.Timestamp(raw["train_end"]), pd.Timestamp(raw["validation_end"])


def write_segments(data_dir: Path, out_dir: Path) -> Bounds:
    bounds = split_bounds(load_ohlcv(data_dir / f"{REFERENCE_SYMBOL}.csv"))
    for csv in data_dir.glob("*.csv"):
        bars = load_ohlcv(csv)
        for name in SEGMENTS:
            save_ohlcv(segment(bars, name, bounds), out_dir / name / csv.name)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "split.json").write_text(
        json.dumps({"train_end": bounds[0].isoformat(), "validation_end": bounds[1].isoformat()}, indent=2)
    )
    return bounds


app = typer.Typer()


@app.command()
def main(data_dir: Path, out_dir: Path) -> None:
    """Example: python -m quantharness.split data/ build/segments/"""
    train_end, validation_end = write_segments(data_dir, out_dir)
    typer.echo(f"train < {train_end} <= validation < {validation_end} <= holdout", err=True)


if __name__ == "__main__":
    app()
