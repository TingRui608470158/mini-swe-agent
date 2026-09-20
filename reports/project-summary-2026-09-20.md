# Quant trading harness — project summary at pause (2026-09-20)

Branch `quanta_trade`. Design: `design/quant-trading-harness-architecture.md` and the per-stage rulebooks in
`design/`. This document is the closing record: what was built, what was proven, what was found, and why the
project stops here rather than at Stage 4.

## What exists and is verified

| stage | deliverable | acceptance |
|---|---|---|
| 0 | `quantharness/features.py`, `data.py`, `binance.py` — 17 point-in-time features (v2), bit-exact offline/online parity, fixed gap policy | `tests/quantharness/test_features.py`, `test_data.py` |
| 1 | `quantharness/backtest.py`, `metrics.py` — deterministic engine, B&H through the same path, 15 bps cost | `test_backtest.py` |
| 2 | `quantharness/gate.py`, `purity.py`, `split.py`, `regimes.py`, `docker/gate/` — sandboxed purity check, relative-only criteria C1–C6, validation budget, mount-level isolation | `test_gate.py`, `test_purity.py`, `test_split.py`, `test_regimes.py`, `test_gate_container.py` (Docker) |
| 2.5 | `quantharness/synthetic.py` — `ar1` and `regime` sets with planted, known answers | `test_gate.py` proves the planted answer passes and noise fails |
| 3 | `minisweagent/run/extra/quant_research.py`, `agents/extra/quant_research.py`, `config/extra/quant_research.yaml` — unmodified `DefaultAgent` + `DockerEnvironment`, five sandbox probes, verdict from the root-only score log only | `tests/run/test_quant_research.py`, `test_quant_research_container.py`; **synthetic acceptance: 9 PASS of 12 valid runs, 3/3 at the final settings** (`runs/*synthetic*`) |
| 3.5 | `minisweagent/run/extra/quant_research_report.py`, rulebook `design/stage3.5-real-data.md` | `tests/run/test_quant_research_report.py`; batch 1 report below |

103 non-Docker tests pass (`pytest tests/quantharness tests/run/test_quant_research*.py -m "not slow"`).

## What was found on real data

Data: Binance BTC/ETH/SOL spot 1h, 2021-01-01 → 2025-01-01, frozen (fingerprint in the batch-1 report).
Split: train → 2023-05-27, validation → 2024-03-14, holdout → 2025-01-01. Only train was ever read by a human.

1. **Batch 1** (`reports/stage3.5-2026-09-20-batch1.md`): 5 runs, qwen3.6 local, identical harness to the
   synthetic acceptance. 5 × `FAIL_LIMITS`; no run spent a validation query because every own backtest was
   deeply negative. Scenario C. Agents measured lag-1 autocorrelation ≈ 0 and behaved rationally.
2. **Feature-space search** (`reports/feature-search-2026-09-20.md`, `scripts/*_search.py`): brute-force
   threshold rules on train against a shifted-returns null.
   - OHLCV v1/v2 at 1h, 4h, 1d; cross-asset relative features; kline order flow: **all inside the null**, and
     still inside it at **0 bps**. Not "eaten by costs" — no predictability in that space.
   - **Perp funding rate** (tier 1): *above* the null (2.16 vs 1.87 at 15 bps, 10 shifts). One theme — long
     after a week of deeply negative funding. Passes C1–C4 on BTC train with a smooth threshold surface; fails
     C6 (weak on ETH, absent on SOL); in the market ~5% of bars; fires only in capitulations.

## Why it stops here (decision: wrap up, not re-open)

- Stage 4+ requires a candidate that passed the gate. None exists.
- The one real lead cannot get a fair test under the frozen split: the validation window is a bull market
  with B&H Sharpe ≈ 3.1 and mostly positive funding, so a capitulation-buying signal is expected to never
  fire there. Running the full v3 re-validation chain now would produce a FAIL that carries no information.
- Relaxing C1/C6 or moving the split because of the finding is forbidden by the rulebook (Stage 3.5 R2/R5),
  and rightly so — that is the human doing validation-set search by proxy.

## How to re-open (when more history exists)

1. Re-split so validation contains at least one bear episode; this is a design change to Stage 2 R1, made
   before looking at any result.
2. Stage 0 v3 schema: add `fr` (funding, known at its settlement hour, ffilled) and `basis` (premium-index
   close) columns; append features, never reorder; synthetic set with a planted funding mean-reversion answer.
3. Full chain: Stage 0–2 tests → Stage 3 synthetic acceptance on every set (≥ 2/3 each) → `scripts/perp_search.py`
   style null check on the new train → batch 2 (N = 5, untouched prompt).
4. Data-agnostic prompt fixes from batch 1 §7 (features predict the *next* bar; use the free train score) go in
   at the same time, through the synthetic acceptance.

## Method lessons

- A shifted-returns null on the *same* rule set is the cheapest honest test of "is there anything here";
  use ≥ 10 shifts and read the median as well as the max — three shifts moved by 0.2 Sharpe from a one-bar
  window change.
- Best-of-thousands in-sample Sharpe around 1.5–2.4 on ~20k hourly bars is what pure noise produces; it is
  not evidence.
- Cross-asset agreement among BTC/ETH/SOL is weak evidence (they co-move); the C6 criterion is demanding on
  purpose, and alt B&H Sharpe in 2021 makes it harder still.
- The harness's value showed in the negative result: five independent agents found nothing, refused to spend
  budget on losers, and brute force confirmed there was nothing to find — the verdict is attributable.
