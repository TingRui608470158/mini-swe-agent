"""Download 1h klines from Binance's public REST API into the OHLCV CSV format."""

from pathlib import Path

import pandas as pd
import requests
import typer

from quantharness.data import INTERVAL, OHLCV_COLUMNS, normalize_ohlcv, save_ohlcv

URL = "https://api.binance.com/api/v3/klines"


def fetch_klines(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Bars with open_time in [start, end). Pages through the 1000-bar limit; no retries."""
    rows: list[list] = []
    cursor, end_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    while cursor < end_ms:
        params = {"symbol": symbol, "interval": "1h", "startTime": cursor, "endTime": end_ms - 1, "limit": 1000}
        response = requests.get(URL, params=params, timeout=30)
        response.raise_for_status()
        if not (batch := response.json()):
            break
        rows.extend(batch)
        cursor = batch[-1][0] + 1
    df = pd.DataFrame([row[:6] for row in rows], columns=["open_time", *OHLCV_COLUMNS])
    return normalize_ohlcv(df.set_index((pd.to_datetime(df["open_time"], unit="ms", utc=True) + INTERVAL).rename("ts")))


app = typer.Typer()


@app.command()
def main(symbol: str, start: str, end: str, out: Path) -> None:
    """Example: python -m quantharness.binance BTCUSDT 2021-01-01 2025-01-01 data/btcusdt_1h.csv"""
    save_ohlcv(fetch_klines(symbol, pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")), out)
    typer.echo(f"Saved {out}")


if __name__ == "__main__":
    app()
