"""Brute-force search over simple threshold rules on the 8 Stage 0 features, train segment only.

Answers "is there any simple edge in these features, or did the agents just fail to find it?"
Uses the Stage 1 engine so costs and accounting match the gate. Never reads validation/holdout.
A shifted-alignment null (same rules, returns shifted by k bars) shows what the best in-sample
Sharpe looks like when there is no predictability at all.
"""

import itertools
from pathlib import Path

import numpy as np
import pandas as pd
import typer

from quantharness.backtest import CostModel, backtest_positions
from quantharness.data import load_ohlcv
from quantharness.features import FEATURE_NAMES, compute_features

QUANTILES = (0.1, 0.25, 0.5, 0.75, 0.9)
NULL_SHIFTS = (500, 1000, 2000)


def rules(features: pd.DataFrame) -> list[tuple[str, np.ndarray]]:
    x = {f: features[f].to_numpy() for f in FEATURE_NAMES}
    q = {f: np.nanquantile(x[f], QUANTILES) for f in FEATURE_NAMES}
    out = []
    for f in FEATURE_NAMES:
        for qi, thr in zip(QUANTILES, q[f]):
            above = x[f] > thr
            for direction, name in ((1.0, "long"), (-1.0, "short")):
                out.append((f"{name} if {f} > q{qi}", direction * above))
                out.append((f"{name} if {f} < q{qi}", direction * (x[f] < thr)))
            out.append((f"+1 above / -1 below {f} q{qi}", np.where(above, 1.0, -1.0)))
            out.append((f"-1 above / +1 below {f} q{qi}", np.where(above, -1.0, 1.0)))
    for f1, f2 in itertools.combinations(FEATURE_NAMES, 2):
        for (q1, t1), (q2, t2) in itertools.product(zip(QUANTILES, q[f1]), zip(QUANTILES, q[f2])):
            for c1, c2 in itertools.product(("<", ">"), repeat=2):
                cond = ((x[f1] > t1) if c1 == ">" else (x[f1] < t1)) & ((x[f2] > t2) if c2 == ">" else (x[f2] < t2))
                for direction, name in ((1.0, "long"), (-1.0, "short")):
                    out.append((f"{name} if {f1} {c1} q{q1} & {f2} {c2} q{q2}", direction * cond))
    return [(name, np.nan_to_num(pos, nan=0.0)) for name, pos in out]


def evaluate(bars: pd.DataFrame, candidates: list[tuple[str, np.ndarray]]) -> pd.DataFrame:
    rows = []
    for name, pos in candidates:
        r = backtest_positions(bars, pos, CostModel()).report()
        rows.append({"rule": name, **r["strategy"], "bh_sharpe": r["benchmark"]["sharpe"], "corr": r["corr_with_benchmark"]})
    return pd.DataFrame(rows).sort_values("sharpe", ascending=False).reset_index(drop=True)


def shifted(bars: pd.DataFrame, k: int) -> pd.DataFrame:
    """Closes rolled by k bars; positions computed from the unrolled features are then unaligned with returns."""
    out = bars.copy()
    out["close"] = np.roll(bars["close"].to_numpy(), k)
    return out


app = typer.Typer(add_completion=False)


@app.command()
def main(
    segments_dir: Path = Path("build/segments"),
    symbol: str = "BTCUSDT",
    cross: list[str] = typer.Option(["ETHUSDT", "SOLUSDT"], "--cross"),
    top: int = 15,
    out: Path = Path("reports/rule-search.md"),
) -> None:
    bars = load_ohlcv(segments_dir / "train" / f"{symbol}.csv")
    features = compute_features(bars)
    candidates = rules(features)
    typer.echo(f"{len(candidates)} rules on {symbol} train ({len(bars)} bars)", err=True)
    real = evaluate(bars, candidates)
    bh = real["bh_sharpe"].iloc[0]

    # Same positions (from the real features), returns rolled by k bars: destroys any real alignment.
    null_best = [evaluate(shifted(bars, k), candidates)["sharpe"].max() for k in NULL_SHIFTS]

    lines = [f"# Rule search — {symbol} train segment ({len(bars)} bars, {len(candidates)} rules)", ""]
    lines += [
        f"- benchmark (buy & hold) Sharpe: {bh:.2f}; gate needs strategy Sharpe ≥ {bh + 0.5:.2f}",
        f"- rules with Sharpe > 0: {(real['sharpe'] > 0).sum()}  |  > 0.5: {(real['sharpe'] > 0.5).sum()}  |  > 1: {(real['sharpe'] > 1).sum()}  |  ≥ gate bar: {(real['sharpe'] >= bh + 0.5).sum()}",
        f"- rules with positive net return: {(real['total_return'] > 0).sum()}",
        f"- best in-sample Sharpe: {real['sharpe'].iloc[0]:.2f}  |  best on shifted (no-predictability) data, shifts {NULL_SHIFTS}: {', '.join(f'{s:.2f}' for s in null_best)}",
        "",
        f"## Top {top} rules (in-sample, {symbol})",
        "",
        "| rule | sharpe | net return | trades | corr B&H |",
        "|---|---:|---:|---:|---:|",
    ]
    for _, r in real.head(top).iterrows():
        lines.append(f"| {r['rule']} | {r['sharpe']:.2f} | {r['total_return']:.3f} | {r['n_trades']} | {r['corr']:.2f} |")

    lines += ["", f"## Same top {top} rules on cross assets (train segment, no re-tuning)", "", "| rule | " + " | ".join(f"{c} sharpe" for c in cross) + " |", "|---|" + "---:|" * len(cross)]
    top_rules = dict(candidates)
    cross_results = {}
    for c in cross:
        cb = load_ohlcv(segments_dir / "train" / f"{c}.csv")
        cf = compute_features(cb)
        by_name = dict(rules(cf))
        cross_results[c] = {name: backtest_positions(cb, by_name[name], CostModel()).report()["strategy"]["sharpe"] for name in real["rule"].head(top)}
    for name in real["rule"].head(top):
        lines.append(f"| {name} | " + " | ".join(f"{cross_results[c][name]:.2f}" for c in cross) + " |")
    _ = top_rules

    lines += ["", "## Reading this", "", "In-sample best-of-thousands is inflated by selection: compare the best real Sharpe with the best Sharpe on shifted data. If they are similar, the features carry no usable signal at this frequency and cost level; if the real best is far above the null and holds on cross assets, the agents' search — not the features — is the bottleneck."]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    typer.echo("\n".join(lines[:6]), err=True)
    typer.echo(f"-> {out}", err=True)


if __name__ == "__main__":
    app()
