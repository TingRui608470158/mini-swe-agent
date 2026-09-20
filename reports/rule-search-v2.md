# Rule search — BTCUSDT train segment (21038 bars, 27710 rules)

- benchmark (buy & hold) Sharpe: 0.31; gate needs strategy Sharpe ≥ 0.81
- rules with Sharpe > 0: 1161  |  > 0.5: 267  |  > 1: 22  |  ≥ gate bar: 73
- rules with positive net return: 834
- best in-sample Sharpe: 1.42  |  best on shifted (no-predictability) data, shifts (500, 1000, 2000): 1.58, 1.61, 1.51

## Top 20 rules (in-sample, BTCUSDT)

| rule | sharpe | net return | trades | corr B&H |
|---|---:|---:|---:|---:|
| short if vol_168 > q0.75 & volatility_720 < q0.25 | 1.42 | 0.144 | 2 | -0.06 |
| long if vol_24 < q0.75 & volatility_720 < q0.1 | 1.30 | 0.476 | 31 | 0.18 |
| long if volatility_720 < q0.1 & hl_pos_168 > q0.5 | 1.28 | 0.405 | 48 | 0.16 |
| long if range_1 < q0.9 & volatility_720 < q0.1 | 1.24 | 0.462 | 89 | 0.19 |
| short if vol_168 > q0.1 & volatility_720 < q0.5 | 1.18 | 1.503 | 54 | -0.54 |
| long if hl_pos_168 > q0.75 & weekday_utc < q0.25 | 1.16 | 0.470 | 136 | 0.20 |
| short if ret_24 < q0.9 & volatility_720 < q0.5 | 1.15 | 1.445 | 191 | -0.53 |
| long if volatility_720 > q0.9 & weekday_utc < q0.5 | 1.15 | 0.793 | 34 | 0.33 |
| short if vol_24 < q0.25 & vol_168 > q0.9 | 1.15 | 0.042 | 2 | -0.02 |
| long if vol_24 < q0.9 & volatility_720 < q0.1 | 1.12 | 0.428 | 25 | 0.20 |
| long if volatility_720 < q0.1 & weekday_utc > q0.1 | 1.12 | 0.416 | 47 | 0.19 |
| +1 above / -1 below volatility_720 q0.5 | 1.12 | 2.702 | 31 | 0.13 |
| short if sma_50_ratio < q0.9 & volatility_720 < q0.5 | 1.09 | 1.299 | 151 | -0.53 |
| short if vol_24 < q0.9 & volatility_720 < q0.5 | 1.09 | 1.221 | 73 | -0.51 |
| long if volatility_720 > q0.9 & hl_pos_720 < q0.25 | 1.09 | 0.458 | 66 | 0.22 |
| long if volatility_720 < q0.1 & weekday_utc > q0.25 | 1.08 | 0.344 | 45 | 0.17 |
| long if volatility_ratio_24_168 > q0.25 & volatility_720 < q0.1 | 1.07 | 0.360 | 83 | 0.18 |
| short if volatility_ratio_24_168 < q0.9 & volatility_720 < q0.5 | 1.06 | 1.088 | 197 | -0.48 |
| short if vol_24 < q0.25 & vol_168 > q0.75 | 1.04 | 0.072 | 20 | -0.04 |
| long if volatility_720 < q0.1 & volatility_ratio_24_720 > q0.25 | 1.01 | 0.357 | 68 | 0.19 |

## Same top 20 rules on cross assets (train segment, no re-tuning)

| rule | ETHUSDT sharpe | SOLUSDT sharpe |
|---|---:|---:|
| short if vol_168 > q0.75 & volatility_720 < q0.25 | nan | 0.28 |
| long if vol_24 < q0.75 & volatility_720 < q0.1 | 0.63 | -0.78 |
| long if volatility_720 < q0.1 & hl_pos_168 > q0.5 | 0.41 | -0.49 |
| long if range_1 < q0.9 & volatility_720 < q0.1 | 0.46 | -0.67 |
| short if vol_168 > q0.1 & volatility_720 < q0.5 | 0.56 | 0.12 |
| long if hl_pos_168 > q0.75 & weekday_utc < q0.25 | -0.13 | 0.19 |
| short if ret_24 < q0.9 & volatility_720 < q0.5 | 0.11 | 0.47 |
| long if volatility_720 > q0.9 & weekday_utc < q0.5 | 0.18 | 0.98 |
| short if vol_24 < q0.25 & vol_168 > q0.9 | 0.44 | 0.77 |
| long if vol_24 < q0.9 & volatility_720 < q0.1 | 0.66 | -0.74 |
| long if volatility_720 < q0.1 & weekday_utc > q0.1 | 0.63 | -0.44 |
| +1 above / -1 below volatility_720 q0.5 | 0.56 | 1.23 |
| short if sma_50_ratio < q0.9 & volatility_720 < q0.5 | 0.03 | 0.42 |
| short if vol_24 < q0.9 & volatility_720 < q0.5 | 0.08 | 0.25 |
| long if volatility_720 > q0.9 & hl_pos_720 < q0.25 | 0.56 | 0.06 |
| long if volatility_720 < q0.1 & weekday_utc > q0.25 | 0.46 | -0.67 |
| long if volatility_ratio_24_168 > q0.25 & volatility_720 < q0.1 | 0.66 | -0.57 |
| short if volatility_ratio_24_168 < q0.9 & volatility_720 < q0.5 | 0.00 | 0.27 |
| short if vol_24 < q0.25 & vol_168 > q0.75 | 1.03 | 0.65 |
| long if volatility_720 < q0.1 & volatility_ratio_24_720 > q0.25 | 0.79 | -0.77 |

## Reading this

In-sample best-of-thousands is inflated by selection: compare the best real Sharpe with the best Sharpe on shifted data. If they are similar, the features carry no usable signal at this frequency and cost level; if the real best is far above the null and holds on cross assets, the agents' search — not the features — is the bottleneck.
## Conclusion (2026-09-20, feature set v2, before any LLM run)

- 27,710 rules over 17 features. Best in-sample Sharpe **1.42 is below the best Sharpe the same search finds on shifted (no-predictability) returns, 1.51–1.61**. Nothing in this table is distinguishable from selection noise.
- Only 4% of rules (1,161) have a positive Sharpe; the top of the list is dominated by `volatility_720` conditions with 2–90 trades, and cross-asset results flip sign between ETH and SOL for almost every rule.
- The one economically coherent rule — `+1 above / −1 below volatility_720 median` (long in high 30-day volatility, short in low; Sharpe 1.12, 31 trades, corr 0.13, ETH 0.56 / SOL 1.23) — is exactly the shape of the planted synthetic regime edge, but it sits inside the null band and would fail C6 (ETH buy-and-hold Sharpe is 0.87). Record it as a hypothesis for a longer sample, not as evidence.
- Calendar features (`hour_utc`, `weekday_utc`) appear only as secondary conditions; no standalone seasonality rule reaches the gate bar.

**Decision: do not start real-data batch 2 with this feature set.** The v2 features add volatility structure and seasonality, and neither carries a signal at 1h that survives 15 bps costs on 2021-01 → 2023-05 BTC. Single-symbol OHLCV-derived features are now exhausted along two axes (price direction in v1, volatility/calendar in v2); the next candidates must bring *new information*, not new transforms of the same series: cross-asset relative strength, funding rates / basis, or a different frequency. The synthetic `regime` acceptance set stays useful as the harness check for whatever volatility-type feature comes next.
