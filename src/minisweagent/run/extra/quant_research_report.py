"""Stage 3.5 batch report: summarize `runs/<id>/` artifacts of real-data runs (design/stage3.5-real-data.md R4/R5).

Reads only what the research harness already wrote; touches no container, model or data segment.
"""

import hashlib
import json
import math
import subprocess
from datetime import date
from pathlib import Path

import typer

from minisweagent.config import builtin_config_dir

CRITERIA = ("purity", "relative_sharpe", "regimes", "beta", "net_return", "cross_asset")
NEAR_MISS_SHARPE_GAP = -0.5

app = typer.Typer(add_completion=False)


def load_run(run_dir: Path) -> dict | None:
    if not (run_dir / "verdict.json").exists():
        return None
    verdict = json.loads((run_dir / "verdict.json").read_text())
    trajectory = (
        json.loads((run_dir / "trajectory.traj.json").read_text(encoding="utf-8"))
        if (run_dir / "trajectory.traj.json").exists()
        else {}
    )
    assistant = [m for m in trajectory.get("messages", []) if m.get("role") == "assistant"]
    ctx = [((m.get("extra") or {}).get("response") or {}).get("usage", {}).get("prompt_tokens") for m in assistant]
    scores_path = run_dir / "scores.jsonl"
    return {
        "id": run_dir.name,
        "verdict": verdict.get("verdict", "ERROR"),
        "exit_status": verdict.get("exit_status", ""),
        "image": verdict.get("image", ""),
        "budget": verdict.get("budget"),
        "budget_remaining": verdict.get("budget_remaining"),
        "steps": len(assistant),
        "final_ctx": next((c for c in reversed(ctx) if c), 0),
        "model": trajectory.get("info", {}).get("config", {}).get("model", {}).get("model_name", "?"),
        "scores": [json.loads(l) for l in scores_path.read_text().splitlines() if l.strip()]
        if scores_path.exists()
        else [],
        "sha256": verdict.get("sha256"),
    }


def _sharpe(score: dict) -> float:
    value = score["criteria"].get("relative_sharpe", {}).get("value")
    return value if isinstance(value, (int, float)) and not math.isnan(value) else -math.inf


def best_score(scores: list[dict]) -> dict | None:
    passed = [s for s in scores if s.get("pass")]
    return passed[-1] if passed else (max(scores, key=_sharpe) if scores else None)


def criteria_failures(runs: list[dict]) -> dict[str, int]:
    counts = dict.fromkeys(CRITERIA, 0)
    for run in runs:
        for score in run["scores"]:
            for name in CRITERIA:
                counts[name] += not score["criteria"].get(name, {}).get("pass", True)
    return counts


def distances(score: dict) -> dict[str, float]:
    c = score["criteria"]
    rs, beta = c.get("relative_sharpe", {}), c.get("beta", {})
    return {
        "c1_gap": rs.get("value", math.nan) - (rs.get("benchmark", math.nan) + rs.get("margin", 0)),
        "c3_slack": beta.get("max_abs", math.nan) - abs(beta.get("value", math.nan)),
        "c4_return": c.get("net_return", {}).get("value", math.nan),
    }


def scenario(runs: list[dict]) -> str:
    if any(r["verdict"] == "PASS" for r in runs):
        return "A"
    for run in runs:
        if (best := best_score(run["scores"])) is None:
            continue
        d = distances(best)
        if d["c1_gap"] >= NEAR_MISS_SHARPE_GAP and best["criteria"].get("beta", {}).get("pass") and d["c4_return"] > 0:
            return "B"
    return "C"


def fingerprint(data_dir: Path, segments_dir: Path) -> dict:
    files = {
        csv.name: {
            "sha256": hashlib.sha256(csv.read_bytes()).hexdigest(),
            "rows": len(csv.read_bytes().splitlines()) - 1,
        }
        for csv in sorted(data_dir.glob("*.csv"))
    }
    split = json.loads((segments_dir / "split.json").read_text()) if (segments_dir / "split.json").exists() else {}
    git = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
    return {
        "data": files,
        "split": split,
        "git": git.stdout.strip() if git.returncode == 0 else "unknown",
        "config_sha256": hashlib.sha256(
            (builtin_config_dir / "extra" / "quant_research.yaml").read_bytes()
        ).hexdigest(),
    }


NEXT_STEP = {
    "A": "candidates exist -> Stage 4 (holdout evaluation + human review); holdout untouched until then",
    "B": "near miss -> no deployable strategy yet; iterate the Stage 0 feature set, do not loosen thresholds or tune the prompt",
    "C": "no edge found in this feature set / frequency / model -> no new batch until one of those changes",
}


def _fmt(x: float | None) -> str:
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.2f}"


def render(runs: list[dict], interrupted: list[str], fp: dict, batch: str) -> str:
    lines = [f"# Stage 3.5 batch report — {batch}", "", "## 1. Fingerprint", ""]
    for name, info in fp["data"].items():
        lines.append(f"- `{name}`: {info['rows']} rows, sha256 `{info['sha256'][:16]}…`")
    lines += [
        f"- split: `{json.dumps(fp['split'])}`",
        f"- harness: git `{fp['git'][:12]}`, quant_research.yaml sha256 `{fp['config_sha256'][:16]}…`",
    ]
    lines += [
        f"- model: `{runs[0]['model'] if runs else '?'}`",
        "",
        f"## 2. Runs (N = {len(runs)}, interrupted = {len(interrupted)})",
        "",
    ]
    lines.append(
        "| run | verdict | steps | val queries | final ctx | best: C1 gap | C3 slack | C4 return | criteria (best) | strategy family |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---|---|")
    for r in runs:
        best = best_score(r["scores"])
        d = distances(best) if best else {}
        flags = "".join("✓" if best["criteria"].get(n, {}).get("pass") else "✗" for n in CRITERIA) if best else "-"
        used = (r["budget"] or 0) - (r["budget_remaining"] or 0) if r["budget_remaining"] is not None else "?"
        lines.append(
            f"| {r['id']} | {r['verdict']} | {r['steps']} | {used} | {r['final_ctx']} | {_fmt(d.get('c1_gap'))} | "
            f"{_fmt(d.get('c3_slack'))} | {_fmt(d.get('c4_return'))} | {flags} | _(fill in)_ |"
        )
    for name in interrupted:
        lines.append(f"| {name} | INTERRUPTED | - | - | - | - | - | - | - | - |")
    failures = criteria_failures(runs)
    total = sum(len(r["scores"]) for r in runs)
    lines += [
        "",
        f"criteria column order: {', '.join(CRITERIA)}",
        "",
        f"## 3. Criterion failures across all {total} validation queries",
        "",
    ]
    lines += [f"- {name}: {count}" for name, count in failures.items()]
    lines += [
        "",
        "## 4. Distance to threshold",
        "",
        "See columns `C1 gap` (strategy − benchmark − margin, pass at ≥ 0), `C3 slack` (0.7 − |corr|, pass at ≥ 0) and `C4 return` (pass at > 0) above; each is the run's best validation score.",
    ]
    lines += [
        "",
        "## 5. Strategy families",
        "",
        "Fill in the `strategy family` column per run from `runs/<id>/strategy.py` (what signal, what sizing).",
    ]
    s = scenario(runs)
    lines += ["", "## Verdict", "", f"**Scenario: {s}** — {NEXT_STEP[s]}", ""]
    return "\n".join(lines)


# fmt: off
@app.command(help="Summarize a batch of research-harness runs into reports/stage3.5-<batch>.md")
def main(
    runs_dir: Path = typer.Argument(Path("runs")),
    image: str = typer.Option("real", "--image", help="Only runs whose gate image tag is this"),
    data_dir: Path = typer.Option(Path("data/raw"), "--data-dir"),
    segments_dir: Path = typer.Option(Path("build/segments"), "--segments-dir"),
    batch: str = typer.Option(date.today().isoformat(), "--batch"),
    out: Path | None = typer.Option(None, "--out"),
) -> None:
    # fmt: on
    runs, interrupted = [], []
    for run_dir in sorted(p for p in runs_dir.iterdir() if p.is_dir()):
        run = load_run(run_dir)
        if run is None:
            if run_dir.name.endswith(f"-gate-{image}"):
                interrupted.append(run_dir.name)
        elif run["image"].endswith(f":{image}"):
            runs.append(run)
    out = out or Path("reports") / f"stage3.5-{batch}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(runs, interrupted, fingerprint(data_dir, segments_dir), batch), encoding="utf-8")
    typer.echo(f"{len(runs)} runs -> {out} (scenario {scenario(runs)})", err=True)


if __name__ == "__main__":
    app()
