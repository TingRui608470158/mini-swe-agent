# Feature-space search after Stage 3.5 batch 1 — 2026-09-20

Harness `456042d`; data fingerprint as in `stage3.5-2026-09-20-batch1.md` (BTCUSDT.csv sha256 `b16f0d06870418cf…`,
train segment `2021-01-01 → 2023-05-27`). **Train segment only**; validation and holdout were never read. No change
to `quantharness/` or the prompt — everything here is exploratory scripts under `scripts/`.

## Question

Batch 1 was scenario C (no PASS, no validation query spent, every agent's own backtest deeply negative). Before
spending another batch: is there *any* simple edge in reach of the feature set, and if not, does changing the
sampling frequency or adding cross-asset information create one?

## Method (all three scripts)

- Brute-force threshold rules: for every feature, long/short/±1 above or below each of 5 quantiles; for every
  pair of features, long/short on the conjunction of two such conditions. ~28k rules for 17 features.
- Every rule is scored with the Stage 1 formula (`pos[t]` earns `close[t] → close[t+1]`, 15 bps per unit turnover
  charged at `t`, Sharpe annualised by `√(8760 / bar_hours)`); `freq_search.py` asserts bit-level parity with
  `backtest_positions` on one rule.
- **Null**: the same rules re-scored against closes rolled by k bars (positions no longer aligned with returns).
  The best Sharpe on shifted data is what best-of-thousands selection alone produces. A feature set has a
  detectable edge only if the real best is clearly above that, *and* the top rules keep their sign on the other
  two symbols.

## Results

| feature set | script | freq | bars | rules | B&H Sharpe | best in-sample | null best (3 shifts) | above null? |
|---|---|---|---:|---:|---:|---:|---|---|
| v1 (8) | `rule_search.py` | 1h | 21,038 | 5,840 | 0.31 | 1.15 | 0.87–0.99 | marginally (3 rules ≥ bar, ≤ 20 trades) |
| v2 (17) | `rule_search.py` | 1h | 21,038 | 27,710 | 0.31 | 1.42 | 1.51–1.61 | no |
| v2 (17), time-scaled windows | `freq_search.py` | 4h | 5,259 | 27,710 | 0.30 | 1.61 | 1.38–1.98 | no |
| v2 (17), time-scaled windows | `freq_search.py` | 1d | 876 | 27,710 | 0.29 | 1.67 | 1.57–2.08 | no (test has no power at 876 bars) |
| cross-asset relative (20) | `cross_search.py` | 1h | 21,038 | 38,600 | 0.31 | 1.37 | 1.22–1.82 | no |
| cross-asset relative (20) | `cross_search.py` | 4h | 5,259 | 38,600 | 0.30 | 1.57 | 1.52–1.94 | no |

Cross-asset consistency: at 1d the top rules flip sign on ETH/SOL. At 4h a handful hold on all three symbols —
`long if ret_24 < q0.25 & vol_168 > q0.75` (1.44 / 1.25 / 1.03, 276 trades), `long if volatility_720 > q0.5 &
volatility_ratio_24_720 > q0.9` (1.40 / 1.02 / 1.69), and six of the cross-asset top ten share
`corr_168 < q0.1` (long when the target decouples from the basket; 1.35–1.48 on the other targets). All of these
are inside the null band, and BTC/ETH/SOL are so correlated that agreement across them is weak evidence.

## Conclusion

Within **single-timestamp point-in-time OHLCV features, threshold rules, 15 bps round-trip cost**, the 2021–2023
training segment has no edge distinguishable from selection noise — at 1h, 4h or 1d, with or without cross-asset
relative features. This is the empirical output of Stage 3.5, not a harness defect: the same harness passed the
synthetic acceptance 3/3 hours before batch 1.

Decision: **stop feature iteration in this space; no new real-data batch** (Stage 3.5 R5 scenario C). Re-opening
requires a change outside the current design docs — cheaper execution assumptions, a different market/asset
class, or a non-OHLCV information source — and goes through the design doc first, then the full re-validation
chain (Stage 0–2 tests → Stage 3 synthetic acceptance on both `ar1` and `regime` sets → rule search → batch).

## Appendix — script output

## 4h bars — BTCUSDT train (5259 bars, 27710 rules)
- B&H Sharpe 0.30; gate bar 0.80; rules >= bar: 178; > 1: 67
- best in-sample 1.61 | null best (shifts [125, 250, 500]): 1.98, 1.68, 1.38

| rule | sharpe | net ret | trades | ETHUSDT | SOLUSDT |
|---|---:|---:|---:|---:|---:|
| long if volatility_ratio_24_168 < q0.75 & volatility_ratio_24_720 > q0.9 | 1.61 | 0.422 | 44.0 | 0.23 | 0.49 |
| long if vol_24 > q0.9 & hl_pos_720 > q0.5 | 1.52 | 0.781 | 74.0 | 0.07 | 1.59 |
| long if ret_24 < q0.25 & vol_168 > q0.75 | 1.44 | 1.663 | 276.0 | 1.25 | 1.03 |
| long if volatility_720 > q0.5 & volatility_ratio_24_720 > q0.9 | 1.40 | 0.979 | 96.0 | 1.02 | 1.69 |
| long if sma_50_ratio > q0.9 & hl_pos_720 < q0.9 | 1.37 | 0.773 | 138.0 | -0.54 | 0.01 |
| long if sma_20_ratio > q0.25 & volatility_720 < q0.1 | 1.36 | 0.500 | 19.0 | 0.73 | -0.66 |
| long if sma_20_ratio > q0.1 & volatility_720 < q0.1 | 1.30 | 0.477 | 13.0 | 0.92 | -0.95 |
| long if vol_168 > q0.9 & volatility_ratio_24_720 > q0.9 | 1.28 | 0.617 | 32.0 | 0.97 | 1.14 |
| short if vol_168 > q0.1 & volatility_720 < q0.5 | 1.26 | 1.720 | 66.0 | 0.68 | 0.09 |
| long if volatility_ratio_24_720 > q0.9 & volume_ratio_168 < q0.9 | 1.26 | 0.867 | 228.0 | 0.41 | 0.59 |
| short if vol_168 < q0.75 & volatility_720 < q0.5 | 1.25 | 1.570 | 43.0 | 0.53 | 0.31 |
| short if vol_168 > q0.5 & volatility_720 < q0.1 | 1.25 | 0.105 | 8.0 | -0.01 | -0.82 |

## 24h bars — BTCUSDT train (876 bars, 27710 rules)
- B&H Sharpe 0.29; gate bar 0.79; rules >= bar: 500; > 1: 199
- best in-sample 1.67 | null best (shifts [20, 41, 83]): 2.08, 2.08, 1.57

| rule | sharpe | net ret | trades | ETHUSDT | SOLUSDT |
|---|---:|---:|---:|---:|---:|
| short if volatility_ratio_24_168 < q0.25 & hl_pos_168 > q0.25 | 1.67 | 1.741 | 233.0 | -0.63 | -0.43 |
| short if ret_1 > q0.25 & volatility_ratio_24_168 < q0.25 | 1.65 | 1.738 | 267.0 | -0.43 | -0.66 |
| short if ret_1 > q0.5 & vol_168 > q0.9 | 1.61 | 0.931 | 62.0 | 0.53 | -0.68 |
| short if ret_1 > q0.25 & vol_168 > q0.9 | 1.58 | 0.949 | 62.0 | 0.27 | -0.58 |
| long if vol_168 < q0.1 & volume_ratio_168 < q0.25 | 1.57 | 0.233 | 28.0 | 0.65 | 0.51 |
| short if vol_168 > q0.9 & range_ratio_24 < q0.1 | 1.54 | 0.346 | 20.0 | 0.29 | 0.26 |
| short if sma_20_ratio > q0.25 & volatility_ratio_24_168 < q0.25 | 1.53 | 1.446 | 237.0 | -0.88 | -0.69 |
| short if volatility_ratio_24_168 < q0.25 & weekday_utc > q0.25 | 1.49 | 1.130 | 211.0 | 0.12 | -0.81 |
| long if ret_1 < q0.5 & ret_24 > q0.9 | 1.49 | 0.207 | 20.0 | 1.07 | 0.65 |
| long if ret_1 < q0.5 & volatility_720 > q0.9 | 1.49 | 1.168 | 56.0 | 0.29 | 0.34 |
| long if ret_1 < q0.25 & sma_50_ratio < q0.1 | 1.46 | 0.795 | 64.0 | 0.45 | 0.26 |
| long if sma_20_ratio > q0.9 & volatility_ratio_24_720 < q0.75 | 1.45 | 0.969 | 46.0 | 0.20 | 0.38 |

## 1h — BTCUSDT target, train (21038 bars, 38600 rules, 20 features)
- B&H Sharpe 0.31; gate bar 0.81; rules >= bar: 37; > 1: 15
- best in-sample 1.37 | null best (shifts [500, 1000, 2000]): 1.39, 1.82, 1.22

| rule | sharpe | net ret | trades | ETH target | SOL target |
|---|---:|---:|---:|---:|---:|
| long if vol_168 < q0.1 & corr_168 < q0.1 | 1.37 | 0.085 | 6.0 | 1.62 | -0.86 |
| long if vol_168 < q0.25 & corr_168 < q0.1 | 1.32 | 0.152 | 12.0 | 0.95 | -0.11 |
| long if vol_168 < q0.25 & corr_168 < q0.25 | 1.31 | 0.309 | 24.0 | 0.44 | -0.05 |
| long if rel_ret_24 > q0.9 & o2_rel_sma_50 > q0.75 | 1.18 | 0.095 | 30.0 | -1.16 | 1.67 |
| long if basket_ret_24 < q0.1 & o2_ret_24 > q0.5 | 1.15 | 0.125 | 18.0 | -0.60 | nan |
| long if rel_ret_24 > q0.1 & corr_168 < q0.1 | 1.15 | 0.541 | 150.0 | 0.93 | 1.28 |
| short if ret_24 < q0.1 & basket_ret_24 > q0.9 | 1.14 | 0.195 | 24.0 | 0.09 | -0.72 |
| long if rel_sma_50 > q0.75 & o2_rel_sma_50 > q0.75 | 1.14 | 0.094 | 14.0 | -0.31 | 0.03 |
| short if basket_ret_24 > q0.9 & o1_ret_24 < q0.25 | 1.10 | 0.210 | 30.0 | 0.14 | 0.91 |
| long if corr_168 < q0.1 & o1_rel_sma_50 > q0.1 | 1.06 | 0.520 | 124.0 | 0.50 | 1.20 |
| short if vol_168 < q0.5 & corr_168 > q0.9 | 1.05 | 0.299 | 70.0 | 0.29 | -0.27 |
| long if vol_168 > q0.5 & corr_168 > q0.75 | 1.04 | 0.823 | 144.0 | 0.96 | 0.43 |

## 4h — BTCUSDT target, train (5259 bars, 38600 rules, 20 features)
- B&H Sharpe 0.30; gate bar 0.80; rules >= bar: 241; > 1: 77
- best in-sample 1.57 | null best (shifts [125, 250, 500]): 1.94, 1.52, 1.90

| rule | sharpe | net ret | trades | ETH target | SOL target |
|---|---:|---:|---:|---:|---:|
| long if rel_hl_pos_168 > q0.1 & corr_168 < q0.1 | 1.57 | 0.955 | 96.0 | 1.35 | 1.48 |
| long if basket_ret_24 < q0.75 & corr_168 < q0.1 | 1.56 | 0.666 | 126.0 | 1.48 | 1.39 |
| long if rel_ret_24 > q0.25 & corr_168 < q0.1 | 1.47 | 0.616 | 94.0 | 1.48 | 0.79 |
| long if ret_24 < q0.25 & vol_168 > q0.75 | 1.44 | 1.663 | 276.0 | 1.25 | 1.03 |
| long if corr_168 < q0.1 & o1_rel_sma_50 < q0.75 | 1.34 | 0.694 | 52.0 | 0.40 | 1.47 |
| long if corr_168 < q0.1 & o2_ret_24 < q0.75 | 1.32 | 0.559 | 114.0 | 1.48 | 1.43 |
| short if rel_hl_pos_168 < q0.1 & corr_168 < q0.5 | 1.32 | 0.895 | 268.0 | -0.41 | -0.85 |
| short if rel_hl_pos_168 < q0.1 & corr_168 < q0.75 | 1.32 | 0.951 | 328.0 | -0.36 | -0.96 |
| long if rel_ret_24 > q0.1 & corr_168 < q0.1 | 1.30 | 0.631 | 92.0 | 1.24 | 0.98 |
| long if vol_168 > q0.75 & o1_ret_24 < q0.25 | 1.30 | 1.334 | 234.0 | 1.15 | 1.92 |
| short if rel_ret_24 < q0.1 & rel_hl_pos_168 < q0.1 | 1.28 | 0.801 | 252.0 | 0.31 | 0.16 |
| long if vol_168 < q0.1 & rel_sma_200 > q0.75 | 1.28 | 0.134 | 28.0 | 0.37 | nan |

---

# Addendum — tier 0 (order flow) and cost sensitivity — 2026-09-20

Script: `scripts/flow_search.py` (+ `evaluate(..., rate=)` in `freq_search.py`). Data: the same Binance klines
re-downloaded with all 12 fields for the train window into `build/flow/` (git-ignored); closes match the frozen
`data/raw` bit for bit on all three symbols. Still train only.

## Question

Two things the earlier searches could not answer:
1. The downloader keeps only OHLCV; the same kline carries trade count, taker-buy volume and quote volume.
   `taker_buy / volume` is non-price information on the same grid. Does it carry an edge? (11 features:
   taker-buy ratio and its 24/168 deviations, volume-weighted 24h net flow, trade-count ratios, average trade
   size ratio, plus `ret_1`/`ret_24`/`vol_168` for regime pairing.)
2. Is the OHLCV null result "no predictability" or "predictability smaller than 15 bps"? Sweep 0/2/5/15 bps.

## Results

| feature set | cost (bps) | rules ≥ bar | best in-sample | null best (3 shifts) | null, 10 shifts (max / median) | above null? |
|---|---:|---:|---:|---|---|---|
| flow (11) | 15 | 3 | 0.85 | 0.90–0.95 | — | no |
| flow (11) | 5 | 35 | 1.40 | 1.02–1.32 | 1.74 / 1.36 | no |
| flow (11) | 2 | 177 | 1.77 | 1.28–1.75 | 1.86 / 1.69 | no |
| flow (11) | 0 | 956 | 2.03 | 1.85–2.08 | — | no |
| v2 (17) | 15 | 73 | 1.42 | 1.52–1.61 | — | no |
| v2 (17) | 5 | 275 | 1.55 | 1.65–1.86 | — | no |
| v2 (17) | 2 | 646 | 2.02 | 1.69–2.04 | — | no |
| v2 (17) | 0 | 1902 | 2.34 | 1.84–2.38 | — | no |

- At 15 bps the order-flow set is the weakest set tried: no rule reaches Sharpe 1, and the top rules flip sign
  on ETH/SOL.
- At 2–5 bps the flow best briefly looked above the three-shift null (1.40 vs 1.32; 1.77 vs 1.75). With ten
  shifts it is inside the band (median 1.36 / 1.69), and the top rule at both costs
  (`short if net_flow_24 < q0.1 & trades_ratio_24 < q0.75`, ~700 trades) is negative or flat on the other two
  symbols. Nothing survives.
- Cost sweep on v2: lowering the cost lifts the best rule and the null together; at 0 bps the best (2.34) is
  still inside 1.84–2.38. The OHLCV result is "no predictability", not "eaten by costs".

Method note for future runs: the null max over only three shifts is itself noisy — a one-bar difference in the
window moved the v2 0-bps null from 2.00 to 1.84. Use ≥ 10 shifts and read the median as well as the max before
calling anything "above null".

## Verdict (pre-registered decision rule, case 3)

Nothing is above the null even at 0 bps, with or without order flow. **OHLCV + kline order flow at 1h is
closed** for BTC/ETH/SOL 2021–2023. The only remaining re-open path inside crypto is a genuinely different
information source — perpetual premium index / funding rate (tier 1) — and that is a Stage 0 schema change that
goes through the design doc and the full re-validation chain first. No new real-data batch.

## Appendix — `scripts/flow_search.py` output (run by the user; this shell has no network)

## Data (train window, re-downloaded with all kline fields)
- BTCUSDT: 21039 bars; closes match data/raw
- ETHUSDT: 21039 bars; closes match data/raw
- SOLUSDT: 21039 bars; closes match data/raw

## 1. Order-flow features — BTCUSDT train (21039 bars, 11330 rules, 15 bps)
- B&H Sharpe 0.31; gate bar 0.81; rules >= bar: 3; > 1: 0
- best in-sample 0.85 | null best (shifts [500, 1000, 2000]): 0.95, 0.90, 0.94

| rule | sharpe | net ret | trades | ETHUSDT | SOLUSDT |
|---|---:|---:|---:|---:|---:|
| long if vol_168 > q0.9 & trades_ratio_168 > q0.9 | 0.85 | 0.332 | 138.0 | 0.56 | 0.67 |
| short if vol_168 > q0.9 & net_flow_24 > q0.75 | 0.83 | 0.286 | 124.0 | -0.75 | -0.35 |
| long if vol_168 < q0.1 & tbr_mean_24 > q0.9 | 0.82 | 0.060 | 14.0 | -0.66 | -1.12 |
| short if tbr_dev_24 > q0.9 & tbr_dev_168 < q0.75 | 0.80 | 0.020 | 8.0 | -1.15 | -1.28 |
| long if ret_24 < q0.1 & vol_168 > q0.9 | 0.74 | 0.428 | 136.0 | 0.23 | 0.70 |
| short if vol_168 > q0.9 & tbr_mean_24 > q0.5 | 0.72 | 0.338 | 174.0 | 0.20 | -0.98 |
| long if ret_24 < q0.1 & vol_168 > q0.75 | 0.69 | 0.477 | 356.0 | 0.40 | 0.31 |
| long if vol_168 < q0.1 | 0.68 | 0.182 | 27.0 | 0.75 | -1.39 |
| short if vol_168 > q0.9 & tbr_mean_24 > q0.75 | 0.66 | 0.218 | 142.0 | -0.04 | -0.81 |
| long if vol_168 > q0.9 & tbr_mean_24 < q0.5 | 0.65 | 0.460 | 174.0 | 0.33 | 0.27 |
| long if tbr_mean_24 > q0.9 & net_flow_24 < q0.25 | 0.62 | 0.037 | 2.0 | nan | -0.45 |
| long if vol_168 < q0.1 & net_flow_24 > q0.9 | 0.60 | 0.040 | 16.0 | -0.31 | -0.32 |

## 2. Cost sensitivity — BTCUSDT train, best in-sample vs null

| feature set | rules | cost (bps) | B&H Sharpe | rules >= bar | best in-sample | null best |
|---|---:|---:|---:|---:|---:|---|
| v2 (17) | 27710 | 0 | 0.31 | 1902 | 2.34 | 2.38, 2.14, 1.84 |
| v2 (17) | 27710 | 2 | 0.31 | 646 | 2.02 | 2.04, 1.96, 1.69 |
| v2 (17) | 27710 | 5 | 0.31 | 275 | 1.55 | 1.86, 1.72, 1.65 |
| v2 (17) | 27710 | 15 | 0.31 | 73 | 1.42 | 1.58, 1.61, 1.52 |
| flow (11) | 11330 | 0 | 0.31 | 956 | 2.03 | 2.01, 1.85, 2.08 |
| flow (11) | 11330 | 2 | 0.31 | 177 | 1.77 | 1.38, 1.28, 1.75 |
| flow (11) | 11330 | 5 | 0.31 | 35 | 1.40 | 1.10, 1.02, 1.32 |
| flow (11) | 11330 | 15 | 0.31 | 3 | 0.85 | 0.95, 0.90, 0.94 |

### Re-check at 2 / 5 bps with ten null shifts and cross-asset columns


### flow @ 2 bps: best 1.77 | null over 10 shifts: max 1.86, median 1.69, min 1.28
| rule | sharpe | trades | ETHUSDT | SOLUSDT |
|---|---:|---:|---:|---:|
| short if net_flow_24 < q0.1 & trades_ratio_24 < q0.75 | 1.77 | 702 | 0.35 | -0.48 |
| long if ret_24 < q0.1 & trade_size_ratio_24 < q0.5 | 1.49 | 800 | 0.06 | 0.36 |
| long if ret_24 > q0.75 & trades_ratio_24 > q0.9 | 1.46 | 854 | 0.48 | 0.72 |
| short if net_flow_24 < q0.1 & trades_ratio_168 < q0.9 | 1.39 | 659 | 0.02 | -0.40 |
| long if ret_24 > q0.9 & tbr < q0.75 | 1.38 | 1138 | 1.15 | 0.82 |
| long if vol_168 > q0.75 & tbr < q0.25 | 1.38 | 1896 | 0.22 | 0.21 |

### flow @ 5 bps: best 1.40 | null over 10 shifts: max 1.74, median 1.36, min 1.02
| rule | sharpe | trades | ETHUSDT | SOLUSDT |
|---|---:|---:|---:|---:|
| short if net_flow_24 < q0.1 & trades_ratio_24 < q0.75 | 1.40 | 702 | -0.11 | -0.76 |
| long if vol_168 > q0.9 & trades_ratio_168 > q0.9 | 1.22 | 138 | 0.84 | 0.81 |
| short if vol_168 > q0.9 & net_flow_24 > q0.75 | 1.21 | 124 | -0.51 | -0.22 |
| long if ret_24 < q0.1 & vol_168 > q0.75 | 1.17 | 356 | 0.72 | 0.51 |
| short if vol_168 > q0.9 & tbr_mean_24 > q0.5 | 1.09 | 174 | 0.48 | -0.86 |
| long if ret_24 < q0.1 & net_flow_24 > q0.1 | 1.09 | 584 | 0.14 | 0.54 |

---

# Addendum — tier 1 (perpetual funding rate / premium index) — 2026-09-20

Script: `scripts/perp_search.py`. Data: Binance USDT-M `premiumIndexKlines` (1h) and `fundingRate` (8h,
forward-filled from settlement time) for the train window, cached in `build/perp/` (git-ignored); both series
cover the whole window for all three symbols. Spot returns from the frozen `data/raw`. Train only; validation and
holdout were not read, by me or by any script.

## Result: the first signal above the null

| cost | best in-sample | null, 10 shifts (max / median) | rules ≥ bar | above null? |
|---:|---:|---|---:|---|
| 15 bps | 2.16 | 1.87 / 1.62 | 139 | **yes** |
| 5 bps | 2.41 | 2.01 / 1.80 | 472 | **yes** |

All twelve top rules at both costs are one theme: **long when funding has been deeply negative for about a week**
(`fr` and/or `fr_mean_168` in the bottom decile/quartile). Economically this is "crowded shorts paying to stay
short → squeeze/recovery", i.e. a positioning signal, not a price-derived one — which is why nothing in the
OHLCV space could see it. Basis (`basis_*`) features do not appear in the top rules; the information is in the
funding rate.

## Robustness checks on train (rule A = `long if fr < q0.1 & fr_mean_168 < q0.1`)

Real gate criteria (`quantharness.gate.evaluate` logic, `docker/gate/config.json` thresholds), BTCUSDT train:

| rule | Sharpe | bench | C1 | corr B&H | C3 | net | bull/bear/sideways | C2 | ETH ret/Sharpe/bench | SOL ret/Sharpe/bench | C6 |
|---|---:|---:|:-:|---:|:-:|---:|---|:-:|---|---|:-:|
| A: `fr<q.1 & fr_mean_168<q.1` | 2.16 | 0.31 | Y | 0.22 | Y | 1.18 | 0.64 / 0.20 / 0.11 | Y | 0.33 / 0.65 / 0.87 | 0.32 / 0.48 / 1.45 | **n** |
| B: `fr_mean_168<q.1` | 1.08 | 0.31 | Y | 0.32 | Y | 0.71 | 0.43 / −0.03 / 0.23 | n | 0.28 / 0.49 / 0.87 | 1.30 / 0.88 / 1.45 | n |
| C: `fr<q.1` | 0.54 | 0.31 | n | 0.36 | Y | 0.30 | 0.70 / −0.32 / 0.13 | n | −0.54 / −0.77 / 0.87 | −0.47 / −0.11 / 1.45 | n |
| D: `fr_mean_168<q.25` | 1.44 | 0.31 | Y | 0.46 | Y | 1.73 | 0.67 / 0.09 / 0.50 | Y | 1.13 / 0.90 / 0.87 | −0.25 / 0.26 / 1.45 | n |
| E: `fr_mean_168<0` (absolute) | 0.99 | 0.31 | Y | 0.29 | Y | 0.57 | 0.55 / −0.10 / 0.12 | n | 1.33 / 1.13 / 0.87 | −0.23 / 0.27 / 1.45 | n |

- Rule A passes **C1–C4 on train** (low beta, positive in all three regimes). It fails **C6**: ETH and SOL
  returns are positive, but their Sharpe is below their own 2021-inflated B&H Sharpe (0.87 / 1.45). No variant
  passes C6.
- Per year on BTC: 2021 +50% (Sharpe 2.8), 2022 +45% (2.1), 2023-Jan–May never fires. In the market only
  4–6% of bars; 46 episodes, 57% win rate, median episode +0.3%, top three episodes = 32% of total. Episodes
  cluster in 2021-07 and 2022-11 (capitulations). Not a one-event artefact, but it is a **capitulation-buying**
  signal: it needs bear episodes to fire at all.
- Threshold surface (5 × 5 quantile grid, 15 bps): BTC 1.16–2.16, every cell above the 0.81 bar — smooth, not
  a lucky cell. ETH 0–1.0 (bench 0.87), SOL ≈ 0 (bench 1.45). The signal is strong on BTC, weak on ETH,
  absent on SOL.

## What this does and does not mean

- It is the only above-null finding in the project and it is economically motivated, threshold-robust and low-
  beta on the target symbol. It is real information the current schema cannot express.
- As the gate is written it would **not pass on train** (C6), and the validation window (2023-05 → 2024-03,
  B&H Sharpe ≈ 3.1, mostly positive funding) is structurally hostile to a signal that is in the market 5% of the
  time and fires in capitulations: the expected gate outcome on validation is FAIL on C1 and probably "never
  fires". That is a property of the frozen criteria and split, not evidence against the signal. Relaxing C6 or
  C1 because of this finding is exactly what Stage 3.5 R5 forbids ("放寬門檻不是選項"), and none of this
  addendum touched validation.

## Decision

Per the pre-registered rule: above null → re-opening is *justified*; sign-consistent on ETH/SOL only weakly →
it is not a candidate as the gate stands. Two honest paths, chosen by the project owner, not here:
1. **Re-open as v3** (Stage 0 schema: `fr`, `basis` columns; alignment rule = funding known at its settlement
   hour, basis at bar close; synthetic set with planted funding mean-reversion; full re-validation chain; batch 2).
   Expected outcome under the current criteria and validation window: FAIL. Worth it only if the point is to
   let the harness test the signal properly, accepting that answer.
2. **Wrap up** with this recorded as the one open lead, to be revisited with a validation window that contains a
   bear episode (i.e. a later re-split when more history exists — also a design change).

## Appendix — `scripts/perp_search.py` output (run by the user)

## Data (train window; perp series from fapi.binance.com, spot from data/raw)
- BTCUSDT: basis from 2021-01-01 01:00:00+00:00, fr from 2021-01-01 01:00:00+00:00
- ETHUSDT: basis from 2021-01-01 01:00:00+00:00, fr from 2021-01-01 01:00:00+00:00
- SOLUSDT: basis from 2021-01-01 01:00:00+00:00, fr from 2021-01-01 01:00:00+00:00
- common window: 2021-01-01 01:00:00+00:00 -> 2023-05-27 15:00:00+00:00 (search restricted to it)

## Perp features @ 15 bps — BTCUSDT train (21039 bars, 18620 rules)
- B&H Sharpe 0.31; gate bar 0.81; rules >= bar: 139; > 1: 85
- best in-sample 2.16 | null over 10 shifts: max 1.87, median 1.62, min 1.38

| rule | sharpe | net ret | trades | ETHUSDT | SOLUSDT |
|---|---:|---:|---:|---:|---:|
| long if fr < q0.1 & fr_mean_168 < q0.1 | 2.16 | 1.183 | 92 | 0.65 | 0.48 |
| long if fr_mean_168 < q0.1 & fr_z_168 < q0.25 | 2.03 | 0.747 | 76 | 1.25 | 0.14 |
| long if fr_mean_168 < q0.1 & fr_z_720 < q0.1 | 1.97 | 0.781 | 66 | 0.90 | 0.33 |
| long if fr_mean_168 < q0.1 & fr_z_720 < q0.25 | 1.83 | 0.825 | 82 | 0.55 | 0.21 |
| long if fr < q0.1 & fr_mean_168 < q0.25 | 1.82 | 1.287 | 180 | 0.33 | -0.20 |
| long if fr_mean_168 < q0.1 & fr_z_168 < q0.5 | 1.79 | 0.860 | 94 | 1.04 | 0.19 |
| long if fr < q0.5 & fr_mean_168 < q0.25 | 1.79 | 2.113 | 162 | 0.35 | -0.07 |
| long if fr < q0.75 & fr_mean_168 < q0.25 | 1.79 | 2.113 | 162 | 0.35 | -0.07 |
| long if fr_mean_168 < q0.1 & fr_z_168 < q0.75 | 1.75 | 1.082 | 112 | 0.37 | 0.46 |
| long if fr < q0.25 & fr_mean_168 < q0.1 | 1.74 | 1.021 | 104 | 0.33 | 0.29 |
| long if fr_mean_168 < q0.25 & fr_z_720 < q0.75 | 1.73 | 2.088 | 158 | 0.30 | -0.20 |
| long if fr_mean_168 < q0.25 & fr_z_168 < q0.75 | 1.73 | 1.816 | 212 | 0.42 | -0.44 |

## Perp features @ 5 bps — BTCUSDT train (21039 bars, 18620 rules)
- B&H Sharpe 0.31; gate bar 0.81; rules >= bar: 472; > 1: 275
- best in-sample 2.41 | null over 10 shifts: max 2.01, median 1.80, min 1.61

| rule | sharpe | net ret | trades | ETHUSDT | SOLUSDT |
|---|---:|---:|---:|---:|---:|
| long if fr < q0.1 & fr_mean_168 < q0.1 | 2.41 | 1.394 | 92 | 0.85 | 0.54 |
| long if fr_mean_168 < q0.1 & fr_z_168 < q0.25 | 2.30 | 0.885 | 76 | 1.42 | 0.20 |
| long if fr < q0.1 & fr_mean_168 < q0.25 | 2.20 | 1.739 | 180 | 0.57 | -0.10 |
| long if fr_mean_168 < q0.1 & fr_z_720 < q0.1 | 2.19 | 0.902 | 66 | 1.05 | 0.37 |
| long if fr < q0.25 & fr_mean_168 < q0.25 | 2.14 | 2.287 | 244 | 0.42 | -0.22 |
| long if fr_mean_168 < q0.25 & fr_z_168 < q0.5 | 2.13 | 1.956 | 262 | 0.73 | -0.79 |
| long if fr_mean_168 < q0.25 & fr_z_720 < q0.25 | 2.07 | 1.607 | 178 | 0.54 | -0.50 |
| long if fr_mean_168 < q0.1 & fr_z_720 < q0.25 | 2.07 | 0.981 | 82 | 0.74 | 0.26 |
| long if fr_mean_168 < q0.25 & fr_z_720 < q0.1 | 2.06 | 1.202 | 138 | 0.90 | -0.31 |
| long if fr_mean_168 < q0.1 & fr_z_168 < q0.5 | 2.06 | 1.044 | 94 | 1.26 | 0.28 |
| long if fr_mean_168 < q0.25 & fr_z_168 < q0.75 | 2.05 | 2.482 | 212 | 0.65 | -0.31 |
| long if fr_mean_168 < q0.25 & fr_z_720 < q0.5 | 2.04 | 2.166 | 234 | 0.78 | -0.70 |

### Gate criteria on train, per-year and episode breakdown (rule A)

BTC fr quantiles: q.1=-1.67e-05 q.25=3.31e-05 median=1.00e-04 | fr_mean_168 q.1=8.04e-06 q.25=3.64e-05

| rule | BTC sharpe | bench | C1 | corr | C3 | net ret | bull/bear/sideways | C2 | ETH ret/sharpe/bench | SOL ret/sharpe/bench | C6 | ALL |
|---|---:|---:|:-:|---:|:-:|---:|---|:-:|---|---|:-:|:-:|
| A: long if fr<q.1 & fr_mean_168<q.1 | 2.16 | 0.31 | Y | 0.22 | Y | 1.18 | 0.64/0.20/0.11 | Y | 0.33/0.65/0.87 | 0.32/0.48/1.45 | n | - |
| B: long if fr_mean_168<q.1 | 1.08 | 0.31 | Y | 0.32 | Y | 0.71 | 0.43/-0.03/0.23 | n | 0.28/0.49/0.87 | 1.30/0.88/1.45 | n | - |
| C: long if fr<q.1 | 0.54 | 0.31 | n | 0.36 | Y | 0.30 | 0.70/-0.32/0.13 | n | -0.54/-0.77/0.87 | -0.47/-0.11/1.45 | n | - |
| D: long if fr_mean_168<q.25 | 1.44 | 0.31 | Y | 0.46 | Y | 1.73 | 0.67/0.09/0.50 | Y | 1.13/0.90/0.87 | -0.25/0.26/1.45 | n | - |
| E: long if fr_mean_168<0 (absolute) | 0.99 | 0.31 | Y | 0.29 | Y | 0.57 | 0.55/-0.10/0.12 | n | 1.33/1.13/0.87 | -0.23/0.27/1.45 | n | - |

Rule A, BTC per year: 2021: ret 0.50 sharpe 2.77 (4% in market), 2022: ret 0.45 sharpe 2.07 (6% in market), 2023: ret 0.00 sharpe nan (0% in market)
Rule A episodes: 46; top-3 contribute 32% of total (top: 0.147, 0.143, 0.093, 0.076, 0.065); median episode 0.0032; win rate 57%
Rule A episode start months: 2021-06:3, 2021-07:11, 2022-01:2, 2022-02:4, 2022-03:1, 2022-04:6, 2022-05:2, 2022-06:2, 2022-08:7, 2022-11:8

### Threshold surface

### BTCUSDT — Sharpe (rows: fr < q, cols: fr_mean_168 < q), train, 15 bps

| fr \ week | q0.05 | q0.1 | q0.15 | q0.2 | q0.3 |
|---|---:|---:|---:|---:|---:|
| q0.05 | 1.19 | 1.63 | 1.46 | 1.40 | 1.34 |
| q0.1 | 1.69 | 2.16 | 1.81 | 1.73 | 1.45 |
| q0.15 | 1.65 | 1.96 | 1.70 | 1.71 | 1.53 |
| q0.2 | 1.69 | 1.93 | 1.75 | 1.82 | 1.59 |
| q0.3 | 1.36 | 1.55 | 1.40 | 1.51 | 1.16 |

### ETHUSDT — Sharpe (rows: fr < q, cols: fr_mean_168 < q), train, 15 bps

| fr \ week | q0.05 | q0.1 | q0.15 | q0.2 | q0.3 |
|---|---:|---:|---:|---:|---:|
| q0.05 | 0.47 | 0.94 | 1.02 | 0.68 | 0.95 |
| q0.1 | 0.04 | 0.65 | 0.49 | 0.00 | 0.16 |
| q0.15 | -0.10 | 0.62 | 0.52 | 0.01 | 0.28 |
| q0.2 | -0.16 | 0.42 | 0.62 | 0.03 | 0.33 |
| q0.3 | -0.02 | 0.41 | 0.55 | -0.10 | 0.33 |

### SOLUSDT — Sharpe (rows: fr < q, cols: fr_mean_168 < q), train, 15 bps

| fr \ week | q0.05 | q0.1 | q0.15 | q0.2 | q0.3 |
|---|---:|---:|---:|---:|---:|
| q0.05 | -0.00 | 0.21 | 0.18 | -0.16 | -0.15 |
| q0.1 | 0.37 | 0.48 | 0.39 | -0.05 | -0.04 |
| q0.15 | 0.33 | 0.26 | 0.18 | -0.10 | -0.33 |
| q0.2 | 0.34 | 0.30 | 0.32 | 0.00 | -0.32 |
| q0.3 | 0.32 | 0.48 | 0.48 | 0.23 | 0.09 |
