"""Tier-1 information source: perpetual-futures positioning (premium index basis, funding rate) from Binance
USDT-M futures. Train window only, no harness changes; downloads to build/perp/ (cached).
Usage (from the repo root): python scripts/perp_search.py

Series (per symbol, 1h close-time grid like data.py):
  basis  = premium index kline close (perp mark vs spot index), known at bar close
  fr     = last settled funding rate (settles 00/08/16 UTC), forward-filled from its settlement time
Spot returns come from the frozen data/raw. Rules are searched at 15 and 5 bps against a 10-shift null,
with the same rule scored on the other two symbols.
"""

import numpy as np
import pandas as pd
import requests
from freq_search import ROOT, TRAIN_END, evaluate, rules

from quantharness.backtest import CostModel, backtest_positions
from quantharness.data import INTERVAL, load_ohlcv

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
START = pd.Timestamp("2021-01-01", tz="UTC")
PREMIUM_URL = "https://fapi.binance.com/fapi/v1/premiumIndexKlines"
FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
PERP_DIR = ROOT / "build/perp"
SHIFTS = (300, 500, 700, 1000, 1300, 1600, 2000, 2500, 3000, 4000)
RATES_BPS = (15, 5)


def _page(url: str, symbol: str, key: str, **extra) -> list:
    rows: list = []
    cursor, end_ms = int(START.timestamp() * 1000), int(TRAIN_END.timestamp() * 1000)
    while cursor < end_ms:
        params = {"symbol": symbol, "startTime": cursor, "endTime": end_ms - 1, "limit": 1000, **extra}
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        if not (batch := response.json()):
            break
        rows.extend(batch)
        last = batch[-1][0] if key == "0" else batch[-1][key]
        cursor = int(last) + 1
    return rows


def fetch(symbol: str) -> pd.DataFrame:
    """Columns basis, fr on the 1h grid [START, TRAIN_END]; nan before each series starts. Cached as CSV."""
    path = PERP_DIR / f"{symbol}.csv"
    if path.exists():
        return pd.read_csv(path, index_col="ts", parse_dates=True, float_precision="round_trip")
    grid = pd.date_range(START + INTERVAL, TRAIN_END, freq=INTERVAL, name="ts")
    prem = pd.DataFrame(_page(PREMIUM_URL, symbol, "0", interval="1h"))
    prem_ts = pd.to_datetime(prem[0], unit="ms", utc=True) + INTERVAL
    basis = pd.Series(prem[4].astype("float64").to_numpy(), index=prem_ts).reindex(grid)
    fund = pd.DataFrame(_page(FUNDING_URL, symbol, "fundingTime"))
    fund_ts = pd.to_datetime(fund["fundingTime"], unit="ms", utc=True).dt.ceil("1h")
    fr = pd.Series(fund["fundingRate"].astype("float64").to_numpy(), index=fund_ts)
    fr = fr[~fr.index.duplicated(keep="last")].sort_index().reindex(grid, method="ffill")
    out = pd.DataFrame({"basis": basis, "fr": fr})
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, date_format="%Y-%m-%dT%H:%M:%S%z")
    return out


def perp_features(spot: pd.DataFrame, perp: pd.DataFrame) -> pd.DataFrame:
    c = spot["close"]
    r = np.log(c / c.shift(1))
    basis, fr = perp["basis"], perp["fr"]
    z = lambda s, n: (s - s.rolling(n).mean()) / s.rolling(n).std(ddof=1)  # noqa: E731
    return pd.DataFrame(
        {
            "ret_1": r,
            "ret_24": np.log(c / c.shift(24)),
            "vol_168": r.rolling(168).std(ddof=1),
            "basis": basis,
            "basis_dev_24": basis - basis.rolling(24).mean(),
            "basis_dev_168": basis - basis.rolling(168).mean(),
            "basis_chg_24": basis - basis.shift(24),
            "basis_z_168": z(basis, 168),
            "fr": fr,
            "fr_mean_24": fr.rolling(24).mean(),
            "fr_mean_168": fr.rolling(168).mean(),
            "fr_z_168": z(fr, 168),
            "fr_chg_8": fr - fr.shift(8),
            "fr_z_720": z(fr, 720),
        }
    ).replace([np.inf, -np.inf], np.nan)


def main(top: int = 12) -> None:
    print("## Data (train window; perp series from fapi.binance.com, spot from data/raw)")
    perp = {s: fetch(s) for s in SYMBOLS}
    spot = {s: load_ohlcv(ROOT / "data/raw" / f"{s}.csv") for s in SYMBOLS}
    start = max(perp[s][col].first_valid_index() for s in SYMBOLS for col in ("basis", "fr"))
    for s in SYMBOLS:
        p = perp[s]
        print(f"- {s}: basis from {p['basis'].first_valid_index()}, fr from {p['fr'].first_valid_index()}")
    print(f"- common window: {start} -> {TRAIN_END} (search restricted to it)")
    frames = {s: spot[s].loc[start:TRAIN_END].join(perp[s]) for s in SYMBOLS}
    sets = {s: rules(perp_features(frames[s], frames[s])) for s in SYMBOLS}
    labels, pos = sets["BTCUSDT"]
    close = frames["BTCUSDT"]["close"].to_numpy()
    eng = backtest_positions(frames["BTCUSDT"], pos[7], CostModel()).report()["strategy"]
    assert abs(eng["total_return"] - evaluate(close, pos, 1)["total_return"].iloc[7]) < 1e-9

    for bps in RATES_BPS:
        rate = bps / 10_000
        real = evaluate(close, pos, 1, rate)
        bh = float(evaluate(close, np.ones((1, len(close))), 1, rate)["sharpe"].iloc[0])
        null = [float(evaluate(np.roll(close, k), pos, 1, rate)["sharpe"].max()) for k in SHIFTS]
        n_bar = int((real["sharpe"] >= bh + 0.5).sum())
        print(f"\n## Perp features @ {bps} bps — BTCUSDT train ({len(close)} bars, {len(labels)} rules)")
        n_one = int((real["sharpe"] > 1).sum())
        print(f"- B&H Sharpe {bh:.2f}; gate bar {bh + 0.5:.2f}; rules >= bar: {n_bar}; > 1: {n_one}")
        print(
            f"- best in-sample {real['sharpe'].max():.2f} | null over {len(SHIFTS)} shifts: "
            f"max {max(null):.2f}, median {np.median(null):.2f}, min {min(null):.2f}"
        )
        order = real["sharpe"].sort_values(ascending=False).index[:top]
        cross = {}
        for s in ("ETHUSDT", "SOLUSDT"):
            cl, cp = sets[s]
            ce = evaluate(frames[s]["close"].to_numpy(), cp, 1, rate)
            idx = {lab: i for i, lab in enumerate(cl)}
            cross[s] = {labels[i]: ce["sharpe"].iloc[idx[labels[i]]] for i in order}
        print("\n| rule | sharpe | net ret | trades | ETHUSDT | SOLUSDT |")
        print("|---|---:|---:|---:|---:|---:|")
        for i in order:
            r, cs = real.loc[i], " | ".join(f"{cross[s][labels[i]]:.2f}" for s in ("ETHUSDT", "SOLUSDT"))
            print(f"| {labels[i]} | {r['sharpe']:.2f} | {r['total_return']:.3f} | {int(r['n_trades'])} | {cs} |")


if __name__ == "__main__":
    main()
