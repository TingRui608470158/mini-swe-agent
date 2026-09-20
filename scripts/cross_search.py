"""Cross-asset relative features: does information from the *other* symbols predict the target?
Train segment only. Same rule search / shifted null as freq_search.py.
Usage (from the repo root): python scripts/cross_search.py 1 4

Features on target T with others o1, o2 (fixed order after removing T) and basket = mean(o1, o2):
  own: ret_1, ret_24, vol_168 (for regime pairing)
  basket: basket_ret_1/24, rel_ret_1/24 (T - basket), rel_sma_50/200 (T/basket log ratio vs its SMA),
          rel_hl_pos_168, corr_168 (T vs basket), dispersion_24 (std of ret_24 across the 3)
  per other: o{k}_ret_1, o{k}_ret_24, o{k}_rel_sma_50, o{k}_lead (o ret_1 - T ret_1)
"""

import sys

import numpy as np
import pandas as pd
from freq_search import ROOT, TRAIN_END, evaluate, resample, rules

from quantharness.data import load_ohlcv

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def feats(closes: pd.DataFrame, target: str, f: int) -> pd.DataFrame:
    w = lambda hours: max(2, hours // f)  # noqa: E731
    others = [s for s in SYMBOLS if s != target]
    lc = np.log(closes)
    r1, r24 = lc.diff(), lc.diff(w(24))
    basket = lc[others].mean(axis=1)
    b1, b24 = basket.diff(), basket.diff(w(24))
    ratio = lc[target] - basket
    lo, hi = ratio.rolling(w(168)).min(), ratio.rolling(w(168)).max()
    out = {
        "ret_1": r1[target],
        "ret_24": r24[target],
        "vol_168": r1[target].rolling(w(168)).std(ddof=1),
        "basket_ret_1": b1,
        "basket_ret_24": b24,
        "rel_ret_1": r1[target] - b1,
        "rel_ret_24": r24[target] - b24,
        "rel_sma_50": ratio - ratio.rolling(50).mean(),
        "rel_sma_200": ratio - ratio.rolling(200).mean(),
        "rel_hl_pos_168": (ratio - lo) / (hi - lo),
        "corr_168": r1[target].rolling(w(168)).corr(b1),
        "dispersion_24": r24.std(axis=1, ddof=1),
    }
    for k, o in enumerate(others, 1):
        ro = lc[o] - lc[target]
        out[f"o{k}_ret_1"], out[f"o{k}_ret_24"] = r1[o], r24[o]
        out[f"o{k}_rel_sma_50"] = ro - ro.rolling(50).mean()
        out[f"o{k}_lead"] = r1[o] - r1[target]
    return pd.DataFrame(out).replace([np.inf, -np.inf], np.nan)


def main(freqs=(1, 4), top=12):
    raw = {s: load_ohlcv(ROOT / "data/raw" / f"{s}.csv") for s in SYMBOLS}
    raw = {s: b[b.index < TRAIN_END] for s, b in raw.items()}
    for f in freqs:
        bars = {s: (resample(b, f) if f > 1 else b) for s, b in raw.items()}
        closes = pd.DataFrame({s: b["close"] for s, b in bars.items()}).dropna()
        res = {}
        for t in SYMBOLS:
            labels, pos = rules(feats(closes, t, f))
            res[t] = (labels, evaluate(closes[t].to_numpy(), pos, f), pos)
        labels, real, pos = res["BTCUSDT"]
        close = closes["BTCUSDT"].to_numpy()
        bh = float(evaluate(close, np.ones((1, len(close))), f)["sharpe"].iloc[0])
        shifts = [max(5, s // f) for s in (500, 1000, 2000)]
        null = [evaluate(np.roll(close, k), pos, f)["sharpe"].max() for k in shifts]
        order = real["sharpe"].sort_values(ascending=False).index[:top]
        n_feat = len(feats(closes, "BTCUSDT", f).columns)
        print(f"\n## {f}h — BTCUSDT target, train ({len(close)} bars, {len(labels)} rules, {n_feat} features)")
        print(
            f"- B&H Sharpe {bh:.2f}; gate bar {bh + 0.5:.2f}; "
            f"rules >= bar: {(real['sharpe'] >= bh + 0.5).sum()}; > 1: {(real['sharpe'] > 1).sum()}"
        )
        print(
            f"- best in-sample {real['sharpe'].max():.2f} | "
            f"null best (shifts {shifts}): {', '.join(f'{s:.2f}' for s in null)}"
        )
        print("\n| rule | sharpe | net ret | trades | ETH target | SOL target |")
        print("|---|---:|---:|---:|---:|---:|")
        idx = {t: {lab: i for i, lab in enumerate(res[t][0])} for t in SYMBOLS}
        for i in order:
            cs = " | ".join(f"{res[t][1]['sharpe'].iloc[idx[t][labels[i]]]:.2f}" for t in ("ETHUSDT", "SOLUSDT"))
            r = real.loc[i]
            print(f"| {labels[i]} | {r['sharpe']:.2f} | {r['total_return']:.3f} | {r['n_trades']} | {cs} |")


if __name__ == "__main__":
    main(freqs=tuple(int(a) for a in sys.argv[1:]) or (1, 4))
