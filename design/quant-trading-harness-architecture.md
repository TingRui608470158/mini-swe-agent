# 量化交易 Harness Agent — 開發架構與分階段 MVP

## Context

規劃一個量化交易 harness agent：離線側用 LLM agent 研發策略，線上側完全不含 LLM、確定性運行。目標是讓「這個 harness 好不好」有客觀、可自動驗證的答案，類比 SWE-bench 的 FAIL_TO_PASS。

範圍：標的為加密貨幣（Binance/OKX 類交易所），開發頻率 1h bar、單一 BTC/USDT 起步；終點是 paper trading 即時運行，不含真實資金自動下單（下一份文件的範圍）。

選 1h 而非更高或更低頻率：15 分鐘以下雜訊佔比高、手續費吃掉大部分 alpha，且回測迭代變慢；日線四年僅約 1400 根，樣本不足以支撐統計結論；1h 四年約 35000 根，是三者的甜蜜點。

## 核心設計原則

```
                              LLM 邊界線
離線側（LLM 在這邊）                    │      線上側（LLM 絕不進入）
─────────────────────────────────────┼──────────────────────────
ResearchAgent / DevAgent / AnalystAgent │  策略程式碼（純函數）
                                        │  風控引擎（硬編碼、agent 不可寫）
                                        │  執行引擎（確定性、agent 不可寫）
        產出策略檔 ──── 人工審核關卡 ────┘
```

三個硬性約束，後面所有設計都由此推導：

1. **策略必須是純函數**：`generate_signal(features: dict) -> float`，無 IO、無隨機、無網路、同輸入同輸出。晉升關卡以靜態分析（禁止匯入 `requests/socket/os/random` 無固定 seed、`datetime.now` 等）與 determinism test（同輸入跑兩次逐位元比對）強制檢查，不依賴約定。
2. **風控在策略之外，且不可被繞過**：`final = risk_engine.clamp(strategy.generate_signal(features), state)`。風控與執行引擎所在的路徑對 agent 的 environment 不掛載、無寫入權限，靠檔案系統權限落實，不靠約定。
3. **晉升關卡明確、agent 不可修改**：見「資料與評估設計」，是這個 harness 的 FAIL_TO_PASS。

## 資料與評估設計

**切分方式**：按時間切，`train` 60% / `validation-OOS` 20% / `final-holdout` 20%。三段在檔案系統權限層面隔離：`train` 唯讀開放，`validation-OOS` 無讀取權限、只能透過 CLI 工具取分數，`final-holdout` 容器內完全不掛載，只在人工審核（Stage 4）評估一次。

**查詢額度**：對 `validation-OOS` 的查詢額度是整個 run 的總預算（20 次），與 `cost_limit`、`step_limit` 放在同一層 agent config，用完即結束——額度算在 run 上而不是策略血統上，避免每次迭代自然產生新血統就重置額度的漏洞。

**跨標的驗證**：策略只在 BTC/USDT 上開發，晉升前額外拿 ETH/USDT、SOL/USDT 當跨標的 holdout，套用相同程式碼、不重新調參。加密市場只有一個主導共同因子（BTC beta），跨標的泛化比跨時間泛化更難造假。

**晉升關卡（Promotion Gate）標準**，全部為相對基準，不用絕對門檻——BTC buy-and-hold 在部分年份 Sharpe 就超過 2，絕對門檻會被「永遠滿倉多」直接通過：

- `Sharpe > buy_and_hold_Sharpe（同期）+ margin`
- 多頭 / 空頭 / 盤整三段分開評估，任一段不能是負的
- 與 buy-and-hold 報酬的相關性 < 閾值（排除策略只是加槓桿的 beta）
- 扣除手續費滑價後仍為正
- 純函數檢查（靜態分析 + determinism test + 斷網沙盒）全部通過
- 跨標的 holdout（ETH/USDT、SOL/USDT）表現不能顯著劣化
- `final-holdout` 分數達標 + 人工簽核

## 整體架構

### Offline 側（沿用 mini-swe-agent 的 agent / environment / model 三層）

| mini-swe-agent 既有抽象 | 對應到本專案的角色 |
|---|---|
| `minisweagent/models` | 不變，直接沿用既有 LLM model 介面（litellm/anthropic 等） |
| `minisweagent/agents` | 策略研發控制迴圈，單一 agent（見「分階段 MVP」Stage 3 的理由） |
| `minisweagent/environments` | 直接沿用原版 `DockerEnvironment`，只給 bash，不做自訂工具白名單。隔離全部靠掛載權限，environment 本身幾乎不用改：`/workspace` 可讀寫（策略程式碼）、`/data/train` 唯讀、`/data/validation` 不掛載（只能透過 CLI 拿分數）、`/data/holdout` 不掛載、`/gate` 唯讀（晉升關卡程式碼） |
| `minisweagent/run/*.py` | 新增進入點腳本，組裝上述三層 + 掛載規則，跑一個「研發一個能通過晉升關卡的策略」任務 |

Offline 側新增、與 mini-swe-agent 抽象平行但不屬於三層本身的元件（掛載在 `/gate` 或容器外，agent 不可寫的確定性工具）：

- **Data/Feature Library**：point-in-time 正確的歷史資料 + 特徵計算，離線線上共用同一份程式碼，避免時區對齊、K 棒收線時間點、resample 邊界等細節不一致導致「回測賺錢、實盤不像」。
- **Backtest Engine**：純函數策略 + 特徵 + 手續費滑價模型 → 績效指標，確定性、可重現，同時算出同期 buy-and-hold 基準。
- **Promotion Gate**：見「資料與評估設計」，獨立、agent 不可修改。

### 銜接層：人工審核 + 策略登記表

人工看程式碼 + 晉升關卡報告（含 final-holdout 分數、跨標的驗證結果）核准或拒絕。核准後策略以 hash 標識、內容不可變，寫入登記表；只有登記表允許被線上側讀取。拒絕的策略連同原因封存，可追溯。

### Online 側（完全不含 LLM，獨立、輕量、常駐服務）

```
行情 feed（自建模擬器 → 交易所 testnet/paper）
        ↓
Feature Library（與離線同一份程式碼）
        ↓
Strategy Runner（載入登記表核准的純函數）── target position
        ↓
Risk Engine（硬編碼、agent 無寫入權限、容器不掛載）── clamp → final position
        ↓
Execution Engine（確定性下單、對帳、重試）
        ↓
自建模擬撮合 / 交易所 testnet / paper trading 帳戶
        ↓
Monitoring / PnL / Drift Detection（比對線上決策與離線 replay）→ 告警
```

自建模擬器與交易所 testnet 分別驗證不同的東西，順序不能顛倒：自建模擬器完全確定性，用來驗證邏輯正確性與 offline/online parity；testnet 的撮合和流動性是假的且不可控，但只有真的接上去才會遇到斷線重連、rate limit、API 怪癖、時間戳對齊這些工程問題。因此 Stage 5 拆成 5a（自建模擬器）、5b（testnet）。

## 分階段 MVP

每個階段都是前一階段的必要基礎，且都有客觀、可自動驗證的可驗收標準。

### Stage 0 — 共用 Feature Library（無 agent）
**目標**：建立離線線上都會用到的同一份特徵計算程式碼與資料流水線。
**可驗收**：
- 固定一段歷史 OHLCV 資料（BTC/USDT 1h，固定時間範圍）與一組固定特徵（報酬率、均線、波動度等）。
- 同一輸入跑兩次，輸出逐位元相同。
- 同一份程式碼餵「歷史資料」與「模擬的即時資料快照」，輸出 schema 與數值在重疊時間點上一致。
- look-ahead 檢查：把特徵整體往前平移一根 K 棒，確認任何依賴未來資訊的 bug 會被抓到。

### Stage 1 — 確定性回測引擎（無 agent）
**目標**：純函數策略 + 特徵 + 手續費滑價模型 → 績效報告，含同期 buy-and-hold 基準。
**可驗收**：
- 手寫 trivial 策略（均線交叉）在固定歷史資料上跑出報告（Sharpe、最大回撤、換手率、交易次數、同期 buy-and-hold Sharpe）。
- 同一策略同一資料跑兩次，結果逐位元相同。
- 人工算好答案的極小合成資料集，驗證引擎算出的 Sharpe/報酬與手算結果一致。

### Stage 2 — 晉升關卡 / Evaluator（無 agent）
**目標**：實作 agent 不可修改的固定檢查套件，作為獨立 CLI 工具，對應「資料與評估設計」列出的全部標準。
**可驗收**：
- 三段式切分與檔案系統權限隔離落地（`/data/holdout` 不掛載，`/data/validation` 只能透過 CLI 拿分數）。
- 「永遠滿倉多」策略被相對基準攔下（不能因絕對 Sharpe 夠高就通過）；一個明顯有效的手造策略能通過。
- 查詢額度為整個 run 的總預算，用盡後拒絕後續查詢。
- 純函數檢查能正確攔截一個刻意呼叫網路的假策略。

### Stage 2.5 — 合成資料沙盒（無 agent）
**目標**：造一組植入已知 alpha 的假行情，建立有標準答案的驗收集，讓 Stage 3 的「agent 失敗」可以被歸因為 harness 問題或市場問題。
**可驗收**：
- 合成行情植入已知訊號（例如「波動度高於某閾值後的 3 根 K 棒有正漂移」）。
- 人工寫出對應的「正確答案」策略，確認能通過 Stage 2 晉升關卡。
- 純噪音策略確認被關卡擋下。
- 此合成資料集與兩個對照策略成為 Stage 3 的驗收資料。

### Stage 3 — Offline 研發 Harness MVP（單一 agent，驗收用合成資料）
**目標**：串接 `DockerEnvironment`、model 層與 `DefaultAgent` 風格控制迴圈，agent 在 `/workspace` 用 bash 自主：寫策略檔 → 跑 train 段回測 → 讀結果 → 修正 → 呼叫晉升關卡 → 直到 PASS 或用完 step/query/cost 預算。先做單一 agent：目前沒有「拆成 Research/Dev/Analyst 是否有增益」的量測基準，先跑通單 agent、拿到 trajectory，才看得出瓶頸在哪，屆時再拆才知道怎麼拆。
**可驗收**：
- 在 Stage 2.5 的合成資料上，agent 全自動找到植入的 alpha 並通過晉升關卡，過程無需人工介入——二元判定，失敗時可明確歸因為 harness 問題（標準答案已知存在）。
- 完整 trajectory 被保存，可回放檢視 agent 每一步做了什麼、為何。
- 執行沙盒驗證：`/data/holdout` 不可見、無網路、有資源/時間上限。

### Stage 3.5 — 真實市場資料實戰（非驗收門檻）
**目標**：把 Stage 3 跑通的 harness 原封不動套用到真實 BTC/USDT 歷史資料，觀察 agent 能否找到真的 alpha。
**可驗收**：不設通過/失敗的二元標準。產出一份紀錄：agent 嘗試了什麼、是否通過晉升關卡；通過則進入 Stage 4，未通過視為「本階段暫無可上線策略」，不視為 harness 失敗——harness 有效性已在 Stage 3 用合成資料證明過。

### Stage 4 — 人工審核關卡 + 策略登記表
**目標**：在 offline 產出與 online 消費之間，加入人工簽核與不可變的策略登記表。
**可驗收**：
- CLI 列出待審核候選策略，檢視程式碼與晉升關卡報告（含 final-holdout 與跨標的驗證結果，皆為 agent 沒看過/沒調過參的資料，只評估一次）。
- 核准策略以 hash 標識、內容不可變，線上側可依 hash 讀取；拒絕策略連同原因封存，可追溯。

### Stage 5a — 自建模擬撮合（驗證邏輯正確性與 parity）
**目標**：用完全確定性的自建模擬器驗證線上骨架的邏輯正確性。
**可驗收**：
- 常駐服務骨架：自建模擬行情 + Stage 0 的共用 feature library（原封不動重用）+ strategy runner（載入 Stage 4 核准的純函數）+ 硬編碼風控引擎（容器不掛載）+ 確定性執行引擎。
- 固定測試視窗（連續 24 小時）連續運行，離線用同一段時間重放一次，特徵與策略訊號差異在容許誤差內。
- 主動注入超出正常範圍的訊號（例如策略回傳 target=100），驗證風控引擎確實 clamp 到安全範圍，且此測試可自動化重跑。

### Stage 5b — 交易所 Testnet（驗證工程健壯性）
**目標**：接上 Binance/OKX testnet，磨真實 API 才會遇到的問題。
**可驗收**：
- 主動製造斷線後能正確重連、狀態一致、不重複下單、不遺漏對帳。
- Rate limit 觸發時有正確退避/排隊行為，不導致訂單遺失或風控狀態不同步。
- 下單、對帳、時間戳與交易所回報一致。

### Stage 6a — Harness 完工驗收（3 天，阻擋後續開發的關卡）
**目標**：證明 harness 本身（風控、執行、監控、告警）可靠，此關卡不與策略績效綁定。
**可驗收**：
- 連續 72 小時無故障運行（接 Stage 5b 的 testnet）。
- Feature/decision parity 全程維持在容許誤差內。
- 風控注入測試在 testnet 環境下重跑一次，結果與 Stage 5a 一致。
- 主動製造一次風控觸發、一次連線異常、一次對帳失敗，確認皆有告警。

### Stage 6b — 策略畢業標準（30 天，背景跑，不阻擋 harness 後續開發）
**目標**：核准策略在 paper trading 帳戶長期無人值守運行，作為策略本身（非 harness）的最終晉升標準。
**可驗收**：
- Stage 6a 完工後，策略在 paper trading 持續運行 30 天，期間可平行開發下一個策略或優化 harness，不互相阻擋。
- 每日自動產出 PnL / 績效報告；期間發現問題可重來，不影響 harness 已完工的事實。
- 觀察期結束後產出客觀報告，判定策略是否達到最終標準——這是「策略好不好」的答案，Stage 6a 是「harness 好不好」的答案，兩者分開判定。

**明確排除（Out of scope）**：真實資金自動下單、多資產類別擴充（除跨標的驗證外）、高頻/低延遲優化、Research/Dev/Analyst 三 agent 拆分的細節設計（留待 Stage 3 有結果後評估）。
