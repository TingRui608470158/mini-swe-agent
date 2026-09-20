import hashlib
import json
import math
from pathlib import Path

import pytest
from typer.testing import CliRunner

from minisweagent.run.extra.quant_research_report import (
    CRITERIA,
    app,
    best_score,
    criteria_failures,
    fingerprint,
    load_run,
    render,
    scenario,
)


def score(
    passed: bool,
    sharpe: float = 1.0,
    benchmark: float = 3.0,
    corr: float = 0.1,
    ret: float = 0.2,
    beta_pass: bool = True,
) -> dict:
    return {
        "ts": "t",
        "sha256": "abc",
        "pass": passed,
        "criteria": {
            "purity": {"pass": True},
            "relative_sharpe": {
                "pass": sharpe >= benchmark + 0.5,
                "value": sharpe,
                "benchmark": benchmark,
                "margin": 0.5,
            },
            "regimes": {"pass": True, "value": {}},
            "beta": {"pass": beta_pass, "value": corr, "max_abs": 0.7},
            "net_return": {"pass": ret > 0, "value": ret},
            "cross_asset": {"pass": True, "value": {}},
        },
    }


def make_run(
    root: Path,
    name: str,
    verdict: str,
    scores: list[dict],
    image: str = "quantharness-gate:real",
    steps: int = 5,
    remaining: int = 19,
) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "verdict.json").write_text(
        json.dumps(
            {
                "verdict": verdict,
                "exit_status": "Submitted",
                "image": image,
                "budget": 20,
                "budget_remaining": remaining,
                "sha256": "abc",
            }
        )
    )
    (d / "scores.jsonl").write_text("".join(json.dumps(s) + "\n" for s in scores))
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    for i in range(steps):
        messages.append(
            {"role": "assistant", "content": "", "extra": {"response": {"usage": {"prompt_tokens": 1000 * (i + 1)}}}}
        )
        messages.append({"role": "tool", "content": "ok"})
    (d / "trajectory.traj.json").write_text(
        json.dumps({"info": {"config": {"model": {"model_name": "ollama_chat/x"}}}, "messages": messages})
    )
    (d / "strategy.py").write_text("def generate_signal(f):\n    return 0.0\n")
    return d


def test_load_run_reads_artifacts_and_skips_interrupted(tmp_path):
    make_run(tmp_path, "r1", "PASS", [score(True, sharpe=5)], steps=7, remaining=18)
    (tmp_path / "r2-quantharness-gate-real").mkdir()
    run = load_run(tmp_path / "r1")
    assert (run["verdict"], run["steps"], run["final_ctx"], run["budget_remaining"], run["model"]) == (
        "PASS",
        7,
        7000,
        18,
        "ollama_chat/x",
    )
    assert len(run["scores"]) == 1 and load_run(tmp_path / "r2-quantharness-gate-real") is None


def test_best_score_prefers_pass_then_highest_sharpe():
    assert best_score([score(False, sharpe=1), score(True, sharpe=2), score(False, sharpe=5)])["pass"] is True
    assert (
        best_score([score(False, sharpe=math.nan), score(False, sharpe=1.5), score(False, sharpe=0.5)])["criteria"][
            "relative_sharpe"
        ]["value"]
        == 1.5
    )
    assert best_score([]) is None


def test_criteria_failures_counts_every_validation_query():
    runs = [
        {"scores": [score(False, sharpe=1), score(False, sharpe=1, beta_pass=False), score(False, sharpe=1)]},
        {"scores": [score(False, sharpe=1, beta_pass=False), score(True, sharpe=5)]},
    ]
    assert criteria_failures(runs) == {
        "purity": 0,
        "relative_sharpe": 4,
        "regimes": 0,
        "beta": 2,
        "net_return": 0,
        "cross_asset": 0,
    }


@pytest.mark.parametrize(
    ("runs", "expected"),
    [
        ([{"verdict": "PASS", "scores": [score(True, sharpe=5)]}, {"verdict": "FAIL_LIMITS", "scores": []}], "A"),
        ([{"verdict": "FAIL_LIMITS", "scores": [score(False, sharpe=3.2)]}], "B"),
        ([{"verdict": "FAIL_LIMITS", "scores": [score(False, sharpe=3.2, beta_pass=False)]}], "C"),
        ([{"verdict": "FAIL_LIMITS", "scores": [score(False, sharpe=2.7)]}], "C"),
        ([{"verdict": "FAIL_LIMITS", "scores": [score(False, sharpe=3.2, ret=-0.1)]}], "C"),
        ([{"verdict": "FAIL_BUDGET", "scores": []}], "C"),
    ],
)
def test_scenario_follows_the_rulebook(runs, expected):
    assert scenario(runs) == expected


def test_fingerprint_hashes_data_and_records_split(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "BTCUSDT.csv").write_bytes(b"ts,close\n1,2\n3,4\n")
    (tmp_path / "raw" / "ETHUSDT.csv").write_bytes(b"ts,close\n1,2\n")
    (tmp_path / "seg").mkdir()
    (tmp_path / "seg" / "split.json").write_text(json.dumps({"train_end": "a", "validation_end": "b"}))
    fp = fingerprint(tmp_path / "raw", tmp_path / "seg")
    assert fp["data"]["BTCUSDT.csv"] == {"sha256": hashlib.sha256(b"ts,close\n1,2\n3,4\n").hexdigest(), "rows": 2}
    assert fp["data"]["ETHUSDT.csv"]["rows"] == 1 and fp["split"] == {"train_end": "a", "validation_end": "b"}
    assert len(fp["config_sha256"]) == 64


def test_render_and_cli_filter_by_image(tmp_path):
    make_run(tmp_path / "runs", "20260101-000000-quantharness-gate-real", "PASS", [score(True, sharpe=5)])
    make_run(
        tmp_path / "runs",
        "20260101-000001-quantharness-gate-real",
        "FAIL_LIMITS",
        [score(False, sharpe=2)],
        steps=9,
        remaining=17,
    )
    make_run(
        tmp_path / "runs",
        "20260101-000002-quantharness-gate-synthetic",
        "PASS",
        [score(True, sharpe=9)],
        image="quantharness-gate:synthetic",
    )
    (tmp_path / "runs" / "20260101-000003-quantharness-gate-real").mkdir()
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "BTCUSDT.csv").write_text("ts\n1\n")
    (tmp_path / "seg").mkdir()
    out = tmp_path / "report.md"
    result = CliRunner().invoke(
        app,
        [
            str(tmp_path / "runs"),
            "--image",
            "real",
            "--data-dir",
            str(tmp_path / "raw"),
            "--segments-dir",
            str(tmp_path / "seg"),
            "--out",
            str(out),
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    text = out.read_text(encoding="utf-8")
    assert "N = 2, interrupted = 1" in text and "**Scenario: A**" in text
    assert "20260101-000002" not in text and "| 20260101-000003-quantharness-gate-real | INTERRUPTED" in text
    assert (
        "| 20260101-000001-quantharness-gate-real | FAIL_LIMITS | 9 | 3 | 9000 | -1.50 | 0.60 | 0.20 | ✓✗✓✓✓✓ |" in text
    )
    assert "- relative_sharpe: 1" in text and f"criteria column order: {', '.join(CRITERIA)}" in text


def test_render_handles_runs_without_scores():
    runs = [
        {
            "id": "x",
            "verdict": "FAIL_BUDGET",
            "steps": 3,
            "final_ctx": 0,
            "budget": 20,
            "budget_remaining": 0,
            "model": "m",
            "scores": [],
        }
    ]
    text = render(runs, [], {"data": {}, "split": {}, "git": "unknown", "config_sha256": "0" * 64}, "b")
    assert "| x | FAIL_BUDGET | 3 | 20 | 0 | n/a | n/a | n/a | - |" in text and "**Scenario: C**" in text
