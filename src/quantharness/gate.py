"""Promotion gate (Stage 2). Rules R1-R6 in design/stage2-promotion-gate.md.

Every criterion is relative to buy-and-hold or a sign test; there are no absolute thresholds.
Validation queries consume a per-run budget; anything that fails purity does not.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import typer

from quantharness.backtest import backtest_positions
from quantharness.data import load_ohlcv
from quantharness.features import compute_features
from quantharness.metrics import summarize
from quantharness.purity import Violation, check_static, sandboxed_positions
from quantharness.regimes import REGIMES, label_regimes
from quantharness.split import SEGMENTS, Bounds, body_start, load_bounds


@dataclass
class GateConfig:
    sharpe_margin: float = 0.5
    max_abs_corr: float = 0.7
    regime_window: int = 720
    regime_threshold: float = 0.10
    budget: int = 20
    cross_symbols: tuple[str, ...] = ("ETHUSDT", "SOLUSDT")
    timeout_seconds: float = 60.0
    symbol: str = "BTCUSDT"

    @classmethod
    def load(cls, path: Path) -> "GateConfig":
        raw = json.loads(path.read_text())
        return cls(**{**raw, "cross_symbols": tuple(raw.get("cross_symbols", cls.cross_symbols))})


@dataclass
class Budget:
    """Per-run validation budget plus the root-only log of every validation score (Stage 3 R3)."""

    path: Path

    @property
    def scores_path(self) -> Path:
        return self.path.with_name("scores.jsonl")

    def init(self, remaining: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"remaining": remaining}))
        self.scores_path.write_text("")

    def remaining(self) -> int:
        return json.loads(self.path.read_text())["remaining"]

    def consume(self) -> int:
        remaining = self.remaining() - 1
        self.path.write_text(json.dumps({"remaining": remaining}))
        return remaining

    def record(self, strategy: Path, result: dict) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "sha256": hashlib.sha256(strategy.read_bytes()).hexdigest(),
            "pass": result["pass"],
            "criteria": result["criteria"],
        }
        with self.scores_path.open("a") as f:
            f.write(json.dumps(entry) + "\n")


def load_segment(segments_dir: Path, name: str, symbol: str, bounds: Bounds) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Segment body bars and features; the warmup bars in the file are used for features then dropped."""
    bars = load_ohlcv(segments_dir / name / f"{symbol}.csv")
    features = compute_features(bars)
    if (start := body_start(name, bounds)) is not None:
        body = bars.index >= start
        bars, features = bars[body], features[body]
    return bars, features


def purity_check(strategy: Path, segments_dir: Path, bounds: Bounds, config: GateConfig) -> Violation | None:
    """R2 on the train segment. Free: touches no validation data."""
    if violation := check_static(strategy.read_text()):
        return violation
    pos = sandboxed_positions(
        strategy, load_segment(segments_dir, "train", config.symbol, bounds)[1], config.timeout_seconds
    )
    return pos if isinstance(pos, Violation) else None


def _purity_failure(violation: Violation) -> dict:
    return {"criteria": {"purity": {"pass": False, "reason": violation.reason, "line": violation.line}}, "pass": False}


def _run(strategy: Path, segment: str, segments_dir: Path, symbol: str, bounds: Bounds, config: GateConfig):
    bars, features = load_segment(segments_dir, segment, symbol, bounds)
    pos = sandboxed_positions(strategy, features, config.timeout_seconds)
    return pos if isinstance(pos, Violation) else backtest_positions(bars, pos)


def evaluate(strategy: Path, segment: str, segments_dir: Path, bounds: Bounds, config: GateConfig) -> dict:
    """Criteria C1-C4 and C6 on one segment. Does not touch the budget; assumes `purity_check` passed."""
    result = _run(strategy, segment, segments_dir, config.symbol, bounds, config)
    if isinstance(result, Violation):
        return _purity_failure(result)
    report = result.report()
    strat, bench, corr = report["strategy"], report["benchmark"], report["corr_with_benchmark"]

    labels = label_regimes(result.benchmark["gross"].to_numpy(), config.regime_window, config.regime_threshold)
    net, turnover = result.series["net"].to_numpy(), result.series["turnover"].to_numpy()
    regimes = {
        name: summarize(net[labels == name], turnover[labels == name])["total_return"]
        if (labels == name).any()
        else "absent"
        for name in REGIMES
    }

    cross = {}
    for symbol in config.cross_symbols:
        cross_result = _run(strategy, segment, segments_dir, symbol, bounds, config)
        if isinstance(cross_result, Violation):
            return _purity_failure(cross_result)
        cross_report = cross_result.report()
        cross[symbol] = {
            "total_return": cross_report["strategy"]["total_return"],
            "sharpe": cross_report["strategy"]["sharpe"],
            "benchmark_sharpe": cross_report["benchmark"]["sharpe"],
        }

    criteria = {
        "purity": {"pass": True},
        "relative_sharpe": {
            "pass": bool(strat["sharpe"] >= bench["sharpe"] + config.sharpe_margin),
            "value": strat["sharpe"],
            "benchmark": bench["sharpe"],
            "margin": config.sharpe_margin,
        },
        "regimes": {
            "pass": all(v == "absent" or v >= 0 for v in regimes.values()),
            "value": regimes,
            "n_windows": {name: int((labels[:: config.regime_window] == name).sum()) for name in REGIMES},
        },
        "beta": {"pass": bool(abs(corr) <= config.max_abs_corr), "value": corr, "max_abs": config.max_abs_corr},
        "net_return": {"pass": bool(strat["total_return"] > 0), "value": strat["total_return"]},
        "cross_asset": {
            "pass": all(c["total_return"] > 0 and c["sharpe"] >= c["benchmark_sharpe"] for c in cross.values()),
            "value": cross,
        },
    }
    return {"period": report["period"], "criteria": criteria, "pass": all(c["pass"] for c in criteria.values())}


app = typer.Typer()
SEGMENTS_DIR = typer.Option(Path("/data"), "--segments-dir")
SPLIT = typer.Option(Path("/gate/split.json"), "--split")
CONFIG = typer.Option(Path("/gate/config.json"), "--config")
STATE = typer.Option(Path("/gate/state/budget.json"), "--state")


def _emit(payload: dict, code: int) -> None:
    print(json.dumps(payload))
    raise typer.Exit(code)


def _config(path: Path) -> GateConfig:
    return GateConfig.load(path) if path.exists() else GateConfig()


@app.command()
def check(strategy: Path, segments_dir: Path = SEGMENTS_DIR, split: Path = SPLIT, config: Path = CONFIG) -> None:
    """Purity only (R2). Never consumes budget."""
    if violation := purity_check(strategy, segments_dir, load_bounds(split), _config(config)):
        _emit({"purity": {"pass": False, "reason": violation.reason, "line": violation.line}}, 2)
    _emit({"purity": {"pass": True}}, 0)


@app.command()
def score(
    strategy: Path,
    segment: str = "validation",
    segments_dir: Path = SEGMENTS_DIR,
    split: Path = SPLIT,
    config: Path = CONFIG,
    state: Path = STATE,
) -> None:
    """Full evaluation. Exit 0 = promoted, 1 = failed, 2 = refused (budget / purity)."""
    if segment not in SEGMENTS:
        raise typer.BadParameter(f"segment must be one of {SEGMENTS}")
    cfg, bounds, budget = _config(config), load_bounds(split), Budget(state)
    gated = segment == "validation"
    if gated and budget.remaining() <= 0:
        _emit({"refused": "budget exhausted", "budget_remaining": 0}, 2)
    if violation := purity_check(strategy, segments_dir, bounds, cfg):
        _emit(
            {"refused": f"purity: {violation.reason} (line {violation.line})", "budget_remaining": budget.remaining()},
            2,
        )
    remaining = budget.consume() if gated else budget.remaining()
    result = evaluate(strategy, segment, segments_dir, bounds, cfg)
    if gated:
        budget.record(strategy, result)
    payload = {
        "segment": segment,
        "symbol": cfg.symbol,
        "period": result.get("period"),
        "budget_remaining": remaining,
        "criteria": result["criteria"],
        "pass": result["pass"],
    }
    _emit(payload, 0 if result["pass"] else 1)


@app.command()
def budget(state: Path = STATE) -> None:
    _emit({"budget_remaining": Budget(state).remaining()}, 0)


if __name__ == "__main__":
    app()
