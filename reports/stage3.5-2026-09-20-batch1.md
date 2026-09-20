# Stage 3.5 batch report — 2026-09-20-batch1

## 1. Fingerprint

- `BTCUSDT.csv`: 35064 rows, sha256 `b16f0d06870418cf…`
- `ETHUSDT.csv`: 35064 rows, sha256 `af4914f2bb4777d7…`
- `SOLUSDT.csv`: 35064 rows, sha256 `f5484d4409865bd4…`
- split: `{"train_end": "2023-05-27T15:00:00+00:00", "validation_end": "2024-03-14T20:00:00+00:00"}`
- harness: git `53752685c56c`, quant_research.yaml sha256 `58eae098f19c84be…`
- model: `ollama_chat/qwen3.6:latest`

## 2. Runs (N = 5, interrupted = 0)

| run | verdict | steps | val queries | final ctx | best: C1 gap | C3 slack | C4 return | criteria (best) | strategy family |
|---|---|---:|---:|---:|---:|---:|---:|---|---|
| 20260920-012058-quantharness-gate-real | FAIL_LIMITS | 21 | 0 | 22642 | n/a | n/a | n/a | - | sma_20 momentum × vol_24/vol_168 scaling + ret_1 mean reversion, long-only |
| 20260920-101208-quantharness-gate-real | FAIL_LIMITS | 26 | 0 | 21978 | n/a | n/a | n/a | - | sma_20 & sma_50 mean reversion (long below both, short above both) |
| 20260920-102033-quantharness-gate-real | FAIL_LIMITS | 22 | 0 | 22691 | n/a | n/a | n/a | - | sma_20/sma_50 + ret_1/ret_24 blend with vol scaling, long-only |
| 20260920-103126-quantharness-gate-real | FAIL_LIMITS | 31 | 0 | 22624 | n/a | n/a | n/a | - | all 8 features, vol-regime gated sma mean reversion, long/short |
| 20260920-104317-quantharness-gate-real | FAIL_LIMITS | 24 | 0 | 22837 | n/a | n/a | n/a | - | sma_20 > 2% & sma_50 > 3% & ret_24 > 1% trend-following, long/short, high threshold |

criteria column order: purity, relative_sharpe, regimes, beta, net_return, cross_asset

## 3. Criterion failures across all 0 validation queries

- purity: 0
- relative_sharpe: 0
- regimes: 0
- beta: 0
- net_return: 0
- cross_asset: 0

## 4. Distance to threshold

See columns `C1 gap` (strategy − benchmark − margin, pass at ≥ 0), `C3 slack` (0.7 − |corr|, pass at ≥ 0) and `C4 return` (pass at > 0) above; each is the run's best validation score.

## 5. Strategy families

Filled in above. Five runs, five variants of the same two ideas — SMA-ratio mean reversion and SMA/ret_24 trend following — with volatility scaling as the only sizing idea. No run used `range_1` or `vol_ratio_24` as a primary signal.

## 6. Train-segment evidence (manual; from trajectories, since no validation query was spent)

No run ever scored on validation: every agent stopped at the free train-segment score because its own backtests were already deeply negative, then kept analysing until the context window filled (`ContextExhausted` in all five, budget 20/20 untouched). The best free train-segment score per run (BTCUSDT, 21,038 bars, benchmark Sharpe 0.31):

| run | gate train scores (Sharpe / net return / corr) | regimes (bull / bear / sideways) |
|---|---|---|
| 012058 | none via gate; own backtest −99.9% on all three symbols, ~9,900 trades | — |
| 101208 | −3.58 / −0.99 / 0.17 | −0.89 / −0.52 / −0.82 |
| 102033 | −2.6 / −0.61 / −0.05 | all negative |
| 103126 | −2.8 / −0.08 / −0.14 (best of two) | all negative |
| 104317 | −2.85 / −0.79 / 0.17 | −0.49 / −0.29 / −0.42 |

Nearest to the C1 threshold on train was still ≈ 3.7 Sharpe short of `benchmark + 0.5`; C4 (net return > 0) failed in every case. Costs are the dominant drag: turnover 0.06–0.24 per bar × 15 bps.

Run 012058 measured the return autocorrelation of the training data itself (lag-1: BTC 0.0006, ETH 0.014, SOL −0.021; lags 2–24 all within ±0.04). The mean-reverting structure that every run tried to trade — and that the synthetic acceptance set contains by construction (φ = 0.6) — is absent at 1h in this period.

## 7. Harness observations (not acted on in this batch, per R2)

- Agents rarely use the free `--segment train` score more than twice; they iterate with their own `run_backtest` instead. Fine in principle, but the analysis scripts are what fill the context.
- Two runs computed contemporaneous correlations between features and `ret_1` and read them as predictive; the prompt could state that features are known at bar close and must predict the *next* bar.
- All five runs hit `ContextExhausted` at ~22–23k tokens with `num_ctx = 24576`. On synthetic data the same setting passed 3/3; real data simply needs more exploration per unit of insight.

Any of these is a data-agnostic change; per R2 they go through the synthetic acceptance (≥ 2/3) before a new real-data batch.

## Verdict

**Scenario: C** — no edge found in this feature set / frequency / model -> no new batch until one of those changes

This is not a harness failure: the identical harness passed the synthetic acceptance 9/12 (3/3 at the final settings) hours earlier, and the agents here behaved rationally — they measured the data, found no mean reversion, and refused to spend validation budget on losing strategies. The negative answer is the deliverable. Next: revisit the Stage 0 feature set (Stage 4 remains unimplemented until a candidate exists).
