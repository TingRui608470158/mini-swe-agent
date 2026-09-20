"""Does a coarser bar frequency expose an edge that 1h does not? Train segment only, no harness changes.

Resamples raw 1h bars to F hours, computes the v2 feature set with time-scaled windows (same
information at coarser sampling), brute-forces the same threshold rules as rule_search.py and
compares the best in-sample Sharpe to a shifted-returns null. Costs/accounting replicate the
Stage 1 engine formula exactly (asserted against backtest_positions on one rule).
Prints markdown. Usage (from the repo root): python scripts/freq_search.py 4 24
"""

import itertools
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from quantharness.backtest import CostModel, backtest_positions
from quantharness.data import load_ohlcv

ROOT = Path(".")
QUANTILES = (0.1, 0.25, 0.5, 0.75, 0.9)
RATE = CostModel().rate
TRAIN_END = pd.Timestamp(json.loads((ROOT / "build/segments/split.json").read_text())["train_end"])


def resample(bars: pd.DataFrame, f: int) -> pd.DataFrame:
    """Bars keyed by close time; group by open_time floored to f hours, close time = group open + f h."""
    g = bars.groupby((bars.index - pd.Timedelta(hours=1)).floor(f"{f}h"))
    out = pd.DataFrame(
        {
            "open": g["open"].first(),
            "high": g["high"].max(),
            "low": g["low"].min(),
            "close": g["close"].last(),
            "volume": g["volume"].sum(),
        }
    )
    out.index = out.index + pd.Timedelta(hours=f)
    return out[(g.size() == f).to_numpy()]  # drop partial bars at the edges


def features(b: pd.DataFrame, f: int) -> pd.DataFrame:
    w = lambda hours: max(2, hours // f)  # time-scaled window in bars  # noqa: E731
    c, h, l, v = b["close"], b["high"], b["low"], b["volume"]
    r = np.log(c / c.shift(1))
    rng = (h - l) / c
    vol_24, vol_168, vol_720 = (r.rolling(w(n)).std(ddof=1) for n in (24, 168, 720))
    hl = lambda n: (c - l.rolling(n).min()) / (h.rolling(n).max() - l.rolling(n).min())  # noqa: E731
    return pd.DataFrame(
        {
            "ret_1": r,
            "ret_24": np.log(c / c.shift(w(24))),
            "sma_20_ratio": c / c.rolling(20).mean() - 1,
            "sma_50_ratio": c / c.rolling(50).mean() - 1,
            "vol_24": vol_24,
            "vol_168": vol_168,
            "range_1": rng,
            "vol_ratio_24": v / v.rolling(w(24)).mean(),
            "volatility_ratio_24_168": vol_24 / vol_168,
            "volatility_720": vol_720,
            "volatility_ratio_24_720": vol_24 / vol_720,
            "hl_pos_168": hl(w(168)),
            "hl_pos_720": hl(w(720)),
            "volume_ratio_168": v / v.rolling(w(168)).mean(),
            "range_ratio_24": rng / rng.rolling(w(24)).mean(),
            "hour_utc": b.index.hour.astype(float),
            "weekday_utc": b.index.weekday.astype(float),
        }
    ).replace([np.inf, -np.inf], np.nan)


def rules(feat: pd.DataFrame) -> tuple[list[str], np.ndarray]:
    names = list(feat.columns)
    x = {f: feat[f].to_numpy() for f in names}
    q = {f: np.nanquantile(x[f], QUANTILES) for f in names}
    labels, pos = [], []
    for f in names:
        for qi, thr in zip(QUANTILES, q[f]):
            above, below = x[f] > thr, x[f] < thr
            for d, nm in ((1.0, "long"), (-1.0, "short")):
                labels += [f"{nm} if {f} > q{qi}", f"{nm} if {f} < q{qi}"]
                pos += [d * above, d * below]
            labels += [f"+1 above / -1 below {f} q{qi}", f"-1 above / +1 below {f} q{qi}"]
            pos += [np.where(above, 1.0, -1.0), np.where(above, -1.0, 1.0)]
    for f1, f2 in itertools.combinations(names, 2):
        for (q1, t1), (q2, t2) in itertools.product(zip(QUANTILES, q[f1]), zip(QUANTILES, q[f2])):
            for c1, c2 in itertools.product(("<", ">"), repeat=2):
                cond = ((x[f1] > t1) if c1 == ">" else (x[f1] < t1)) & ((x[f2] > t2) if c2 == ">" else (x[f2] < t2))
                for d, nm in ((1.0, "long"), (-1.0, "short")):
                    labels.append(f"{nm} if {f1} {c1} q{q1} & {f2} {c2} q{q2}")
                    pos.append(d * cond)
    return labels, np.nan_to_num(np.array(pos, dtype="float64"), nan=0.0)


def evaluate(close: np.ndarray, pos: np.ndarray, f: int, rate: float = RATE) -> pd.DataFrame:
    """Vectorised Stage 1 formula: pos[t] earns close[t]->close[t+1], turnover charged at t."""
    simple = close[1:] / close[:-1] - 1
    gross = np.zeros_like(pos)
    gross[:, 1:] = pos[:, :-1] * simple
    turnover = np.abs(np.diff(pos, prepend=0.0, axis=1))
    net = gross - turnover * rate
    std = net.std(ddof=1, axis=1)
    sharpe = np.where(std > 0, net.mean(axis=1) / np.where(std > 0, std, 1) * math.sqrt(8760 / f), np.nan)
    return pd.DataFrame(
        {
            "sharpe": sharpe,
            "total_return": np.cumprod(1 + net, axis=1)[:, -1] - 1,
            "n_trades": (turnover > 0).sum(axis=1),
        }
    )


def bh_sharpe(close: np.ndarray, f: int) -> float:
    return float(evaluate(close, np.ones((1, len(close))), f)["sharpe"].iloc[0])


def main(freqs=(4, 24), symbol="BTCUSDT", cross=("ETHUSDT", "SOLUSDT"), top=12):
    raw = {s: load_ohlcv(ROOT / "data/raw" / f"{s}.csv") for s in (symbol, *cross)}
    raw = {s: b[b.index < TRAIN_END] for s, b in raw.items()}
    for f in freqs:
        b = resample(raw[symbol], f)
        close = b["close"].to_numpy()
        labels, pos = rules(features(b, f))
        real = evaluate(close, pos, f)
        # parity check of the vectorised formula against the engine on one rule
        eng = backtest_positions(b, pos[7], CostModel()).report()["strategy"]
        assert abs(eng["total_return"] - real["total_return"].iloc[7]) < 1e-9, (eng, real.iloc[7])
        bh = bh_sharpe(close, f)
        shifts = [max(5, s // f) for s in (500, 1000, 2000)]
        null = [evaluate(np.roll(close, k), pos, f)["sharpe"].max() for k in shifts]
        order = real["sharpe"].sort_values(ascending=False).index[:top]
        cross_sh = {}
        for c in cross:
            cb = resample(raw[c], f)
            cl, cp = rules(features(cb, f))
            ce = evaluate(cb["close"].to_numpy(), cp, f)
            idx = {lab: i for i, lab in enumerate(cl)}
            cross_sh[c] = {labels[i]: ce["sharpe"].iloc[idx[labels[i]]] for i in order}
        print(f"\n## {f}h bars — {symbol} train ({len(close)} bars, {len(labels)} rules)")
        print(
            f"- B&H Sharpe {bh:.2f}; gate bar {bh + 0.5:.2f}; "
            f"rules >= bar: {(real['sharpe'] >= bh + 0.5).sum()}; > 1: {(real['sharpe'] > 1).sum()}"
        )
        print(
            f"- best in-sample {real['sharpe'].max():.2f} | "
            f"null best (shifts {shifts}): {', '.join(f'{s:.2f}' for s in null)}"
        )
        print("\n| rule | sharpe | net ret | trades | " + " | ".join(cross) + " |")
        print("|---|---:|---:|---:|" + "---:|" * len(cross))
        for i in order:
            cs, r = " | ".join(f"{cross_sh[c][labels[i]]:.2f}" for c in cross), real.loc[i]
            print(f"| {labels[i]} | {r['sharpe']:.2f} | {r['total_return']:.3f} | {r['n_trades']} | {cs} |")


if __name__ == "__main__":
    main(freqs=tuple(int(a) for a in sys.argv[1:]) or (4, 24))
