# Stage 3.5 — 真實市場資料實戰（非驗收門檻）

> 本文件是 [quant-trading-harness-architecture.md](quant-trading-harness-architecture.md) 「分階段 MVP」中 Stage 3.5 的規則書。前提：[Stage 3](stage3-research-harness.md) 已在合成資料上完成驗收（qwen3.6 修正後 12 次 9 次 PASS、最終設定 3/3）。本階段**不設通過/失敗**；它回答的是一個實證問題——「在這組特徵、這個頻率、這個模型下，真實市場有沒有能通過關卡的策略」——而 harness 的有效性已經在 Stage 3 證明過，所以無論答案是什麼，都不是 harness 的成敗。

## 目標

把 Stage 3 的 harness **原封不動**套用到真實 BTC/USDT（含 ETH/SOL 跨標的）歷史資料，跑固定次數，產出一份可追溯的紀錄，並據此決定下一步是 Stage 4 還是回頭迭代特徵。

## 範圍

- 資料：Binance BTCUSDT / ETHUSDT / SOLUSDT，1h，2021-01-01 → 2025-01-01（Stage 0 下載器）。
- 執行：Stage 3 的 run script、prompt、config、模型，唯一差異是 `--image quantharness-gate:real`。
- 產出：`runs/<id>/` × N + 一份彙整報告。
- **本階段不含**：holdout 評估、人工簽核、登記表（Stage 4）；特徵集或成本模型的任何修改；針對真實資料結果調整 prompt（見 R2）。

## 規則

### R1. 資料集凍結並留下指紋

- 三個 symbol 的原始 CSV 由 `python -m quantharness.binance` 下載到 `data/raw/`，之後**不再重新下載**（Binance 歷史 K 棒理論上不變，但凍結是為了讓所有 run 可比較）。
- `python -m quantharness.split data/raw build/segments` 產生段檔與 `split.json`；建映像 `quantharness-gate:real`。
- 報告開頭記錄資料指紋：三個原始 CSV 的 sha256、根數、`split.json` 的兩個切點、映像 ID（`docker images --digests`）。任何後續 run 若指紋不同，視為不同批次，不可與本批次的結果合併統計。

目前這份資料的切點：train `2021-01-01 → 2023-05-27`（21,038 根）、validation `2023-05-27 → 2024-03-14`（7,013 根）、holdout `2024-03-14 → 2025-01-01`（7,013 根）。已知事實：validation 期 BTC buy-and-hold 年化 Sharpe ≈ 3.1，因此 C1 要求策略 Sharpe ≥ 3.6 且 C3 要求與 B&H 相關 ≤ 0.7——門檻很高是刻意的。

### R2. 不改 harness；改了就回合成資料重驗

- 本批次所有 run 使用同一份 `quant_research.yaml`、同一個模型、同一個 `num_ctx`、同一個額度（20）。
- **禁止**依真實資料的結果修改 prompt、特徵、成本、門檻後繼續跑本批次——那等於人類在替 agent 做 validation 上的參數搜尋，繞過額度。
- 若真實資料的 trajectory 暴露出 harness 問題（例如 prompt 講不清某條規則、工具行為異常），修法必須是**資料無關**的（`tests/run/test_quant_research.py` 的資料無關檢查仍要過），且修完先回合成映像跑 3 次、至少 2 次 PASS，才能開**新批次**的真實資料 run。舊批次結果保留、標示批次號。

### R3. 執行協定

- 每批次 **N = 5** 次 run（少於 5 次無法區分「模型運氣」與「資料沒有 alpha」；qwen3.6 每次 3–30 分鐘）。
- 每次 run 是獨立容器、獨立額度 20，彼此不共享任何狀態；agent 看不到前一次 run 的 trajectory。
- 使用者不介入、不提示、不中途停止（中斷的 run 記為 `INTERRUPTED`，不計入 N）。
- 指令固定：`python -m minisweagent.run.extra.quant_research -m ollama_chat/qwen3.6:latest --image quantharness-gate:real`

### R4. 紀錄格式

彙整由 `python -m minisweagent.run.extra.quant_research_report runs/ --image real` 產生（Stage 3.5 唯一新增的程式碼：只讀 `runs/<id>/` 的產物，不碰容器、不碰資料），寫到 `reports/stage3.5-<batch>.md`，內容：

1. **資料指紋**（R1）與 harness 版本（git commit、`quant_research.yaml` 的 sha256、模型名稱）。
2. **逐 run 表**：run id、verdict、步數、validation 額度使用數、最終 context tokens、`scores.jsonl` 中**最佳一次** validation 分數的六條準則數值與各自的通過與否。
3. **準則失敗頻率**：在所有 validation 查詢（不只最佳）中，C1–C6 各失敗幾次。這一欄告訴你 alpha 卡在哪：C1/C4 失敗為主 = 訊號太弱；C3 失敗為主 = agent 只找到 beta；C6 失敗為主 = BTC 有、跨標的沒有；C2 失敗為主 = 只在某種行情有效。
4. **距離門檻**：C1 的 `strategy.sharpe − (benchmark.sharpe + margin)`、C3 的 `0.7 − |corr|`、C4 的 `total_return`，取每 run 最佳值。這是「差一點」與「完全沒有」的分水嶺。
5. **策略族群**（人工填寫，一行一個 run）：agent 最後提交或最佳分數的策略在做什麼（例如「sma_20 均值回歸 + 波動度縮放」）。這欄是給 Stage 0 特徵迭代用的：agent 反覆嘗試同一種訊號而失敗，代表該方向在這 8 個特徵裡已被挖盡。

### R5. 結果的三種解讀（報告最後一段必須明寫是哪一種）

| 情境 | 判定條件 | 下一步 |
|---|---|---|
| **A. 有候選** | ≥ 1 次 `PASS` | 進 Stage 4：所有 PASS 的策略都是候選，各自的 `runs/<id>/` 是審核輸入。**holdout 在本階段仍不碰。** |
| **B. 差一點** | 無 PASS，但至少 1 run 的最佳分數同時滿足：C1 差距 ≤ 0.5 Sharpe、C3 通過、C4 為正 | 記錄為「暫無可上線策略」；優先考慮 Stage 0 特徵集迭代（新特徵須回頭跑 Stage 0–2 全部測試與 Stage 3 合成驗收），而不是改 prompt 或放寬門檻 |
| **C. 沒有** | 其餘 | 記錄為「暫無可上線策略」；在改變特徵/頻率/模型之前不再開新批次——重跑同一設定只是在花額度買運氣 |

**放寬門檻不是選項。** 門檻是 Stage 2 規則書凍結的；真實資料過不了門檻是資訊，不是 bug。

### R6. 資訊衛生

- 人讀 validation 分數是允許的（額度限制的是 agent，不是人），但人**不寫策略、不給 agent 提示**。
- holdout 段在本階段對人也是不看的——它只在 Stage 4 對候選策略評估一次。`build/segments/holdout/` 存在於主機上，不要打開。
- 報告可以公開分享；`runs/<id>/strategy.py` 若之後進 Stage 4 核准，其內容成為登記表的一部分。

## 可驗收標準

本階段沒有通過/失敗，「完成」的定義是：

1. `reports/stage3.5-<batch>.md` 存在，R4 的五個區塊齊全，R5 的情境判定明寫。
2. N = 5 次未中斷的 run 全部保留在 `runs/`，report 的逐 run 表與 `verdict.json` 一致（report 產生器有測試：餵 `tests/` 的假 `runs/` 目錄，輸出表格正確、情境判定正確）。
3. 資料指紋已記錄，且與 `data/raw/` 的實際檔案相符。
4. 本批次期間 `quant_research.yaml`、`quantharness/` 無任何 commit（`git log` 可查）。

## Out of scope

- holdout 評估、人工簽核、登記表（Stage 4）
- 特徵集迭代（回 Stage 0，是獨立的工作項）
- 換模型或換頻率的比較實驗（每個都是新批次，要先寫進報告的「批次定義」）
- 多 run 平行執行（一台 GPU 一次只跑得動一個模型）

## 完成後銜接

- 情境 A → Stage 4 規則書 + 實作，候選策略進 holdout 與人工審核。
- 情境 B/C → Stage 4 規則書可先寫但不急著實作；工作重心回到 Stage 0 特徵集，帶著 R4 第 5 區塊「策略族群」的觀察去設計新特徵。
