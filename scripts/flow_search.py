"""Tier-0 information source: the kline fields quantharness/binance.py drops (trade count, taker-buy volume,
quote volume), plus a cost sweep. Train window only, no harness changes; downloads to build/flow/ (cached).
Usage (from the repo root): python scripts/flow_search.py

Section 1 — order-flow features vs the shifted null at 15 bps, BTCUSDT target, same rule on ETH/SOL.
Section 2 — best in-sample vs null at 0 / 2 / 5 / 15 bps for the v2 feature set and the flow set.
"""

import numpy as np
import pandas as pd
import requests
from freq_search import ROOT, TRAIN_END, evaluate, features, rules

from quantharness.backtest import CostModel, backtest_positions
from quantharness.data import INTERVAL, load_ohlcv

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
START = pd.Timestamp("2021-01-01", tz="UTC")
URL = "https://api.binance.com/api/v3/klines"
COLUMNS = ("open", "high", "low", "close", "volume", "quote_volume", "n_trades", "taker_buy_base", "taker_buy_quote")
FLOW_DIR = ROOT / "build/flow"
RATES_BPS = (0, 2, 5, 15)
SHIFTS = (500, 1000, 2000)


def fetch(symbol: str) -> pd.DataFrame:
    """Full 12-field klines with open_time in [START, TRAIN_END), on the 1h close-time grid; cached as CSV."""
    path = FLOW_DIR / f"{symbol}.csv"
    if path.exists():
        return pd.read_csv(path, index_col="ts", parse_dates=True, float_precision="round_trip")
    rows: list[list] = []
    cursor, end_ms = int(START.timestamp() * 1000), int(TRAIN_END.timestamp() * 1000)
    while cursor < end_ms:
        params = {"symbol": symbol, "interval": "1h", "startTime": cursor, "endTime": end_ms - 1, "limit": 1000}
        response = requests.get(URL, params=params, timeout=30)
        response.raise_for_status()
        if not (batch := response.json()):
            break
        rows.extend(batch)
        cursor = batch[-1][0] + 1
    df = pd.DataFrame([[r[0], *r[1:6], r[7], r[8], r[9], r[10]] for r in rows], columns=["open_time", *COLUMNS])
    df = df.set_index((pd.to_datetime(df.pop("open_time"), unit="ms", utc=True) + INTERVAL).rename("ts"))
    df = df.astype("float64")
    grid = pd.date_range(df.index[0], df.index[-1], freq=INTERVAL, name="ts")
    out = df[~df.index.duplicated(keep="last")].reindex(grid)
    out["close"] = out["close"].ffill()
    for col in ("open", "high", "low"):
        out[col] = out[col].fillna(out["close"])
    out = out.fillna(0.0)  # gap bars: no volume, no trades
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, date_format="%Y-%m-%dT%H:%M:%S%z")
    return out


def check_closes(symbol: str, flow: pd.DataFrame) -> None:
    frozen = load_ohlcv(ROOT / "data/raw" / f"{symbol}.csv")["close"]
    common = flow.index.intersection(frozen.index)
    dev = np.abs(flow.loc[common, "close"].to_numpy() / frozen.loc[common].to_numpy() - 1).max()
    status = "match" if dev < 1e-12 else f"DIFFER (max rel dev {dev:.2e})"
    print(f"- {symbol}: {len(flow)} bars; closes {status} data/raw")


def flow_features(b: pd.DataFrame) -> pd.DataFrame:
    c, v, tb, n, qv = b["close"], b["volume"], b["taker_buy_base"], b["n_trades"], b["quote_volume"]
    r = np.log(c / c.shift(1))
    tbr = tb / v.where(v > 0)
    size = qv / n.where(n > 0)
    return pd.DataFrame(
        {
            "ret_1": r,
            "ret_24": np.log(c / c.shift(24)),
            "vol_168": r.rolling(168).std(ddof=1),
            "tbr": tbr,
            "tbr_mean_24": tbr.rolling(24).mean(),
            "tbr_dev_24": tbr - tbr.rolling(24).mean(),
            "tbr_dev_168": tbr - tbr.rolling(168).mean(),
            "net_flow_24": (2 * tb - v).rolling(24).sum() / v.rolling(24).sum().where(lambda s: s > 0),
            "trades_ratio_24": n / n.rolling(24).mean().where(lambda s: s > 0),
            "trades_ratio_168": n / n.rolling(168).mean().where(lambda s: s > 0),
            "trade_size_ratio_24": size / size.rolling(24).mean(),
        }
    ).replace([np.inf, -np.inf], np.nan)


def summary(close: np.ndarray, pos: np.ndarray, rate: float) -> tuple[float, float, list[float], int]:
    real = evaluate(close, pos, 1, rate)
    bh = float(evaluate(close, np.ones((1, len(close))), 1, rate)["sharpe"].iloc[0])
    null = [float(evaluate(np.roll(close, k), pos, 1, rate)["sharpe"].max()) for k in SHIFTS]
    return bh, float(real["sharpe"].max()), null, int((real["sharpe"] >= bh + 0.5).sum())


def main(top: int = 12) -> None:
    print("## Data (train window, re-downloaded with all kline fields)")
    bars = {s: fetch(s) for s in SYMBOLS}
    for s in SYMBOLS:
        check_closes(s, bars[s])
    close = bars["BTCUSDT"]["close"].to_numpy()
    sets = {s: rules(flow_features(bars[s])) for s in SYMBOLS}
    labels, pos = sets["BTCUSDT"]
    eng = backtest_positions(bars["BTCUSDT"], pos[7], CostModel()).report()["strategy"]
    real = evaluate(close, pos, 1)
    assert abs(eng["total_return"] - real["total_return"].iloc[7]) < 1e-9, (eng, real.iloc[7])

    bh, best, null, n_bar = summary(close, pos, CostModel().rate)
    print(f"\n## 1. Order-flow features — BTCUSDT train ({len(close)} bars, {len(labels)} rules, 15 bps)")
    print(f"- B&H Sharpe {bh:.2f}; gate bar {bh + 0.5:.2f}; rules >= bar: {n_bar}; > 1: {(real['sharpe'] > 1).sum()}")
    print(f"- best in-sample {best:.2f} | null best (shifts {list(SHIFTS)}): {', '.join(f'{s:.2f}' for s in null)}")
    print("\n| rule | sharpe | net ret | trades | ETHUSDT | SOLUSDT |")
    print("|---|---:|---:|---:|---:|---:|")
    order = real["sharpe"].sort_values(ascending=False).index[:top]
    cross = {}
    for s in ("ETHUSDT", "SOLUSDT"):
        cl, cp = sets[s]
        ce = evaluate(bars[s]["close"].to_numpy(), cp, 1)
        idx = {lab: i for i, lab in enumerate(cl)}
        cross[s] = {labels[i]: ce["sharpe"].iloc[idx[labels[i]]] for i in order}
    for i in order:
        r, cs = real.loc[i], " | ".join(f"{cross[s][labels[i]]:.2f}" for s in ("ETHUSDT", "SOLUSDT"))
        print(f"| {labels[i]} | {r['sharpe']:.2f} | {r['total_return']:.3f} | {r['n_trades']} | {cs} |")

    print("\n## 2. Cost sensitivity — BTCUSDT train, best in-sample vs null")
    print("\n| feature set | rules | cost (bps) | B&H Sharpe | rules >= bar | best in-sample | null best |")
    print("|---|---:|---:|---:|---:|---:|---|")
    v2_labels, v2_pos = rules(features(bars["BTCUSDT"], 1))
    for name, p in (("v2 (17)", v2_pos), ("flow (11)", pos)):
        for bps in RATES_BPS:
            bh, best, null, n_bar = summary(close, p, bps / 10_000)
            nulls = ", ".join(f"{s:.2f}" for s in null)
            print(f"| {name} | {len(p)} | {bps} | {bh:.2f} | {n_bar} | {best:.2f} | {nulls} |")


if __name__ == "__main__":
    main()
