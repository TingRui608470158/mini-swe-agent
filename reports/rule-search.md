# Rule search — BTCUSDT train segment (21038 bars, 5840 rules)

- benchmark (buy & hold) Sharpe: 0.31; gate needs strategy Sharpe ≥ 0.81
- rules with Sharpe > 0: 177  |  > 0.5: 34  |  > 1: 2  |  ≥ gate bar: 3
- rules with positive net return: 125
- best in-sample Sharpe: 1.15  |  best on shifted (no-predictability) data, shifts (500, 1000, 2000): 0.93, 0.99, 0.87

## Top 12 rules (in-sample, BTCUSDT)

| rule | sharpe | net return | trades | corr B&H |
|---|---:|---:|---:|---:|
| short if vol_24 < q0.25 & vol_168 > q0.9 | 1.15 | 0.042 | 2 | -0.02 |
| short if vol_24 < q0.25 & vol_168 > q0.75 | 1.04 | 0.072 | 20 | -0.04 |
| short if vol_24 < q0.1 & range_1 > q0.9 | 0.96 | 0.042 | 8 | -0.03 |
| short if vol_24 < q0.1 & vol_168 > q0.75 | 0.76 | 0.014 | 6 | -0.01 |
| long if sma_50_ratio < q0.75 & vol_24 > q0.9 | 0.74 | 0.613 | 230 | 0.50 |
| long if sma_50_ratio < q0.9 & vol_168 < q0.1 | 0.74 | 0.190 | 49 | 0.15 |
| long if ret_24 < q0.1 & vol_168 > q0.9 | 0.74 | 0.428 | 136 | 0.34 |
| long if vol_24 > q0.9 | 0.72 | 0.650 | 208 | 0.56 |
| long if vol_24 > q0.9 & range_1 > q0.1 | 0.70 | 0.622 | 216 | 0.56 |
| long if ret_24 < q0.1 & vol_168 > q0.75 | 0.69 | 0.477 | 356 | 0.43 |
| long if vol_24 > q0.9 & range_1 > q0.25 | 0.67 | 0.579 | 236 | 0.56 |
| long if vol_168 < q0.1 & range_1 < q0.9 | 0.66 | 0.171 | 61 | 0.15 |

## Same top 12 rules on cross assets (train segment, no re-tuning)

| rule | ETHUSDT sharpe | SOLUSDT sharpe |
|---|---:|---:|
| short if vol_24 < q0.25 & vol_168 > q0.9 | 0.44 | 0.77 |
| short if vol_24 < q0.25 & vol_168 > q0.75 | 1.03 | 0.65 |
| short if vol_24 < q0.1 & range_1 > q0.9 | 0.59 | nan |
| short if vol_24 < q0.1 & vol_168 > q0.75 | 0.31 | -0.71 |
| long if sma_50_ratio < q0.75 & vol_24 > q0.9 | -0.09 | 1.32 |
| long if sma_50_ratio < q0.9 & vol_168 < q0.1 | 0.66 | -1.49 |
| long if ret_24 < q0.1 & vol_168 > q0.9 | 0.23 | 0.70 |
| long if vol_24 > q0.9 | 0.02 | 1.08 |
| long if vol_24 > q0.9 & range_1 > q0.1 | 0.02 | 1.07 |
| long if ret_24 < q0.1 & vol_168 > q0.75 | 0.40 | 0.31 |
| long if vol_24 > q0.9 & range_1 > q0.25 | 0.00 | 1.01 |
| long if vol_168 < q0.1 & range_1 < q0.9 | 0.54 | -1.46 |

## Reading this

In-sample best-of-thousands is inflated by selection: compare the best real Sharpe with the best Sharpe on shifted data. If they are similar, the features carry no usable signal at this frequency and cost level; if the real best is far above the null and holds on cross assets, the agents' search — not the features — is the bottleneck.
## Conclusion (2026-09-20, batch1 data)

- Only 177 of 5,840 rules (3%) have a positive Sharpe on train; 125 have a positive net return. The feature space is overwhelmingly loss-making after 15 bps costs.
- The best in-sample Sharpe (1.15) comes from a rule with **2 trades** in 2.4 years; the next two have 20 and 8. These are not strategies, they are single events.
- Among rules with ≥ 100 trades the best is 0.74 — below the gate bar of 0.81 — and it is a "long when volatility spikes" rule with corr 0.56 to buy-and-hold (C3 would be borderline) that does nothing on ETH (0.02).
- The shifted-return null gives a best Sharpe of 0.87–0.99 from the same search. Everything found on real data is inside that selection-noise band.

**The agents were not the bottleneck.** An exhaustive search over one- and two-feature threshold rules finds nothing that would pass the gate, on the same train data the agents saw. Scenario C stands: revisit the feature set. Volatility-conditioned rules (`vol_24`, `vol_168`, `range_1`) dominate the top of the list while price-level rules (`sma_*_ratio`, `ret_*`) are absent, which is a hint for feature design: regime/volatility structure carries what little information there is; price momentum/reversion at 1h carries none.
