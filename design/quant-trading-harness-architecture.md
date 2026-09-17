# 量化交易 Harness Agent — 開發架構與分階段 MVP

## Context

使用者要規劃一個「量化交易 harness agent」，目的是先釐清整體架構有沒有問題，再據此拆出可驗收的分階段 MVP。使用者提出了核心設計原則（LLM 邊界線 + pure function 策略 + 風控外掛 + 晉升關卡），並在第一版架構稿之後做了一輪嚴格的架構審查，指出晉升關卡缺基準對照、Stage 3/6 驗收標準混淆問題、environment 設計與 mini-swe-agent 哲學相衝、查詢限制有漏洞等問題。本文件是納入該輪審查意見後的版本。

範圍確認：標的為加密貨幣（Binance/OKX 類交易所），開發頻率 1h bar、單一 BTC/USDT 起步；終點是 paper trading 即時運行，**不含真實資金自動下單**（那是本文件之後、下一份文件的範圍）。

---

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

三個硬性約束（後面所有架構決策都由此推導）：

1. **策略必須是純函數**：`generate_signal(features: dict) -> float`，無 IO、無隨機、無網路、同輸入同輸出。
2. **風控在策略之外，且不可被繞過**：`final = risk_engine.clamp(strategy.generate_signal(features), state)`，風控是最後一道閘門，不是策略的一部分。
3. **晉升關卡明確、agent 不可修改**：見下方「資料與評估設計」，是這個 harness 的 FAIL_TO_PASS。

---

## 架構健檢

### 資料與評估設計

**1. 晉升關卡必須是相對基準，不能是絕對門檻（最嚴重）**
加密貨幣只有一個主導共同因子（BTC beta）。BTC buy-and-hold 在某些年份 Sharpe 就超過 2，如果關卡只寫「Sharpe > X」，agent 很快會發現「永遠滿倉多」就能過關，而且這不是 bug，是對關卡的正確解讀。
**設計**：晉升關卡必須同時滿足——
- `Sharpe > buy_and_hold_Sharpe + margin`
- 在多頭 / 空頭 / 盤整三段各自分開評估，任一段不能是負的（不分段你永遠分不清「策略有效」和「剛好賭對方向」）
- 與 buy-and-hold 報酬的相關性 < 閾值（避免策略只是加了槓桿的 beta）

**2. 三段式資料切分 + 查詢預算算在整個 run，不是策略血統**
只切 train/OOS 兩段時，agent 可以無限次查 OOS 分數並據此調參，等同隱性洩漏 OOS。但「限制查詢次數」如果算在「策略血統」上也有漏洞：agent 不需要刻意作弊，正常的迭代行為本身就會產生新血統，血統一換，額度就重置了。
**設計**：
- 按時間切分：`train`（agent 全存取）/ `validation-OOS`（只回分數、不回原始資料）/ `final-holdout`（agent 整個離線階段碰不到，只在人工審核時評估一次），比例 60/20/20。
- 查詢額度不跟著血統走，改成**整個 run 的總查詢預算**，跟 `cost_limit`、`step_limit` 放在同一層、同一個 agent config，用完即結束。這剛好對應本 repo 既有的限額機制，實作上幾乎免費。

**3. 跨標的驗證，比跨時間驗證更難造假**
策略在 BTC 上開發，時間切分再嚴謹，也只驗證了「對時間泛化」。加密市場的共同因子問題意味著一個策略可能在 BTC 的任何時間切分上都表現良好，只因為它本質是抓 BTC beta。
**設計**：策略開發只用 BTC/USDT，但晉升前額外拿 ETH/USDT、SOL/USDT 當**跨標的 holdout**（同樣的策略程式碼，不重新調參，直接套到其他標的的資料上跑），作為晉升關卡的一部分。

### 執行環境設計

**4. Environment 不做工具白名單，靠檔案系統權限隔離**
最初設計讓 `QuantResearchEnvironment` 暴露白名單化工具（寫策略檔、跑回測、查 schema），這跟 mini-swe-agent 的核心哲學相衝——本 repo 的主張是只給 bash，不做自訂工具，讓 LLM 自由發揮。用白名單工具等於重寫一個新的 environment，放棄了「沿用既有 harness」大部分的好處。
**設計**：繼續用原版 `DockerEnvironment`（或 bubblewrap），agent 照樣用 bash 為所欲為，隔離全部靠掛載權限：

```
/workspace/         agent 可讀寫，策略程式碼放這裡
/data/train/        唯讀
/data/validation/   無讀取權限，只能透過 CLI 工具拿分數（該 CLI 是容器內唯一能碰到這份資料的程式）
/data/holdout/      容器內根本不掛載
/gate/               唯讀，agent 改不了晉升關卡程式碼
```
`cat /data/holdout/*` 直接 permission denied，比維護工具白名單更簡單、更難繞過。風控引擎、執行引擎（線上側）比照辦理：整個目錄對 agent 的 environment 不可寫、甚至不掛載。

**5. 純函數強制執行**
Agent 產出的程式碼理論上不能有 IO/隨機/網路，但如果只是口頭要求，agent 遲早會不小心（或投機）寫出違反的程式碼。
**設計**：晉升關卡加自動化檢查——(a) 靜態分析禁止匯入 `requests/socket/os/random`（無固定 seed）/`datetime.now` 等；(b) 同一組輸入跑兩次，逐位元比對輸出一致（determinism test）；(c) 執行沙盒本身斷網（呼應上方的檔案系統/網路隔離）。

### 離線／線上一致性

**6. Feature 計算離線線上必須共用同一份程式碼**
回測用一套 feature 邏輯、線上重寫一套，兩者在時區對齊、K 棒收線時間點、resample 邊界上不一致，是「回測很賺、實盤完全不像」最常見的成因。
**設計**：feature library 離線線上共用同一份程式碼，並在 Stage 5 加入 replay parity test：拿線上跑過的同一段時間資料，離線重放一次，比對特徵與訊號是否一致。

---

## 整體架構

### Offline 側（沿用 mini-swe-agent 的 agent / environment / model 三層，不做自訂工具）

| mini-swe-agent 既有抽象 | 對應到本專案的角色 |
|---|---|
| `minisweagent/models` | 不變，直接沿用既有 LLM model 介面（litellm/anthropic 等） |
| `minisweagent/agents` | 策略研發控制迴圈。**MVP 先做單一 agent**——現在連「多 agent 拆分能不能帶來增益」都沒有量測基準，先跑通單 agent、拿到 trajectory，才看得出瓶頸在哪個環節，屆時再拆才知道怎麼拆 |
| `minisweagent/environments` | **直接沿用原版 `DockerEnvironment`**，只給 bash，不做自訂工具；隔離靠上方「執行環境設計 #4」的掛載權限設計，environment 本身幾乎不用改 |
| `minisweagent/run/*.py` | 新增進入點腳本，組裝上述三層 + 掛載規則，跑一個「研發一個能通過晉升關卡的策略」任務 |

Offline 側新增、與 mini-swe-agent 抽象平行、但不屬於三層本身的元件（這些是掛載在 `/gate` 或容器外、agent 不可寫的確定性工具）：
- **Data/Feature Library**：point-in-time 正確的歷史資料 + 特徵計算，離線線上共用同一份程式碼。
- **Backtest Engine**：純函數策略 + 特徵 + 手續費滑價模型 → 績效指標，確定性、可重現。
- **Promotion Gate（晉升關卡）**：相對基準 + 分段評估 + 相關性檢查 + 跨標的驗證 + 純函數檢查，是這個 harness 的 FAIL_TO_PASS。

### 銜接層：人工審核 + 策略登記表（Strategy Registry）
- 人工看程式碼 + 晉升關卡報告（含 final-holdout 分數、跨標的驗證結果），核准或拒絕。
- 核准後策略連同 hash、程式碼、報告一起寫入登記表，成為**不可變**的產出物，只有這個登記表允許被線上側讀取。

### Online 側（完全不含 LLM，獨立、輕量、常駐服務）

```
行情 feed（自建模擬器 → 交易所 testnet/paper，見 Stage 5a/5b）
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

---

## 分階段 MVP

每個階段都是前一階段的必要基礎，且都有客觀、可自動驗證的「可驗收」標準。

### Stage 0 — 共用 Feature Library（無 agent）
**目標**：建立離線線上都會用到的同一份特徵計算程式碼與資料流水線。
**可驗收**：
- 固定一段歷史 OHLCV 資料（BTC/USDT 1h，固定時間範圍）與一組固定特徵（報酬率、均線、波動度等）。
- 同一輸入跑兩次，輸出逐位元相同（determinism test）。
- 同一份程式碼餵「歷史資料」與「模擬的即時資料快照」，輸出 schema 與數值在重疊時間點上一致（為 Stage 5 的 parity test 打基礎）。
- 至少一項 look-ahead 檢查：把特徵整體往前平移一根 K 棒，確認任何依賴未來資訊的 bug 會被此測試抓到。

### Stage 1 — 確定性回測引擎（無 agent）
**目標**：純函數策略 + 特徵 + 手續費滑價模型 → 績效報告，且能對 buy-and-hold 算出同期基準。
**可驗收**：
- 用一個手寫的 trivial 策略（例如均線交叉）在固定歷史資料上跑出報告（Sharpe、最大回撤、換手率、交易次數），同時算出同期 buy-and-hold 的 Sharpe 作為基準對照。
- 同一策略同一資料跑兩次，結果逐位元相同。
- 用人工算好答案的極小合成資料集，驗證引擎算出的 Sharpe/報酬與手算結果一致（unit test）。

### Stage 2 — 晉升關卡 / Evaluator（無 agent）
**目標**：實作 agent 不可修改的固定檢查套件，作為獨立 CLI 工具，對應 SWE-bench 的 FAIL_TO_PASS runner。
**可驗收**：
- 三段式資料切分（train 60% / validation-OOS 20% / final-holdout 20%，按時間切）已落地，且三者在檔案系統權限層面確實隔離（`/data/holdout` 容器不掛載，`/data/validation` 只能透過 CLI 拿分數）。
- 關卡邏輯採相對基準：`Sharpe > buy_and_hold_Sharpe + margin`、多頭/空頭/盤整分段皆非負、與 buy-and-hold 相關性 < 閾值，三者缺一不過。
- 查詢額度是整個 run 的總預算（例如 20 次），跟 `cost_limit`/`step_limit` 同層設定，用完即結束；驗證額度用盡後確實拒絕後續查詢。
- 餵 2–3 個手造策略（一個明顯有效、一個「永遠滿倉多」）驗證：後者必須被相對基準攔下，不能因為絕對 Sharpe 夠高就通過。
- 純函數檢查（靜態分析 + determinism test + 斷網沙盒）能正確攔截一個刻意寫壞（例如呼叫網路）的假策略。

### Stage 2.5 — 合成資料沙盒（新增，無 agent）
**目標**：造一組植入已知 alpha 的假行情，建立有標準答案的驗收集，讓 Stage 3 的「agent 失敗」可以被歸因。
**可驗收**：
- 合成一段假行情，植入已知訊號（例如「波動度高於某閾值後的 3 根 K 棒有正漂移」）。
- 人工寫出對應的「正確答案」策略，確認它能通過 Stage 2 晉升關卡。
- 另寫一個純噪音策略，確認它被關卡擋下。
- 這組合成資料與兩個對照策略，直接成為 Stage 3 的驗收資料集。

### Stage 3 — Offline 研發 Harness MVP（單一 agent，沿用 mini-swe-agent 模式，驗收用合成資料）
**目標**：實作串接既有 `DockerEnvironment`、model 層與一個 `DefaultAgent` 風格控制迴圈的研發流程，讓 agent 能在 `/workspace` 自主用 bash：寫策略檔 → 跑 train 段回測 → 讀結果 → 修正 → 呼叫晉升關卡 → 直到 PASS 或用完 step/query/cost 預算。
**可驗收**：
- 在 Stage 2.5 的**合成資料**（有已知答案）上，agent 全自動找到植入的 alpha 並通過晉升關卡，過程無需人工介入。這是真正的 FAIL_TO_PASS——二元判定、失敗時能明確歸因是 harness 問題（因為標準答案已知存在）。
- **不**用真實市場資料當這一階段的驗收門檻（市場可能真的沒有可發現的 alpha，用真實資料驗收會混淆「harness 爛」和「市場沒 alpha」這兩件不能同樣方式修的問題）。
- 完整 trajectory（比照 mini-swe-agent 既有的執行紀錄）被保存，可回放檢視 agent 每一步做了什麼、為何。
- 執行沙盒驗證：`/data/holdout` 不可見、無網路、有資源/時間上限。

### Stage 3.5 — 真實市場資料實戰（非驗收門檻）
**目標**：把 Stage 3 跑通的 harness，原封不動套用到真實 BTC/USDT 歷史資料上，觀察 agent 能不能找到真的 alpha。
**可驗收**：不設通過/失敗的二元標準（這正是重點）。產出的是一份紀錄：agent 嘗試了什麼、有沒有通過晉升關卡、若通過則進入 Stage 4 人工審核，若未通過則視為「本階段暫無可上線策略」，不視為 harness 失敗——因為 harness 有效性已在 Stage 3 用合成資料證明過。

### Stage 4 — 人工審核關卡 + 策略登記表
**目標**：在 offline 產出與 online 消費之間，加入人工簽核與不可變的策略登記表。
**可驗收**：
- 人可以用簡單 CLI 列出待審核候選策略、檢視程式碼與晉升關卡報告（含 final-holdout 分數、跨標的驗證結果，這些都是 agent 全程沒看過/沒調過參的資料，只在此階段評估一次）。
- 核准後的策略以 hash 標識、內容不可再變更，可被線上側依 hash 讀取；拒絕的策略連同拒絕原因一併封存，可追溯。

### Stage 5a — 自建模擬撮合（驗證邏輯正確性與 parity）
**目標**：先用完全確定性、可控的自建模擬器驗證線上骨架的邏輯正確性——testnet 的撮合和流動性是假的且不可控，不適合拿來做 parity test。
**可驗收**：
- 常駐服務骨架：自建模擬行情 feed + Stage 0 的共用 feature library（原封不動重用）+ strategy runner（載入 Stage 4 核准的純函數）+ 硬編碼風控引擎（容器不掛載、agent 無寫入權限）+ 確定性執行引擎。
- 固定測試視窗（例如連續 24 小時）連續運行，離線用同一段時間重放一次，兩者算出的特徵與策略訊號差異在容許誤差內（feature/decision parity test）。
- 主動注入超出正常範圍的訊號（例如刻意讓策略回傳 target=100），驗證風控引擎確實 clamp 到安全範圍——證明風控無法被繞過，這是可自動化重跑的迴歸測試。

### Stage 5b — 交易所 Testnet（驗證工程健壯性）
**目標**：在 Stage 5a 確認邏輯無誤後，接上 Binance/OKX testnet，磨真實 API 才會遇到的問題：斷線重連、rate limit、API 怪癖、時間戳對齊。
**可驗收**：
- 常駐運行期間能正確處理至少一次主動製造的斷線（重連後狀態一致、不重複下單、不遺漏對帳）。
- Rate limit 觸發時有正確的退避/排隊行為，不會導致訂單遺失或風控狀態不同步。
- 下單、對帳、時間戳與交易所回報一致。

### Stage 6a — Harness 完工驗收（3 天，阻擋後續開發的關卡）
**目標**：證明 harness 本身（風控、執行、監控、告警）是可靠的，這是能繼續往下走的關卡，不該被策略績效綁住。
**可驗收**：
- 連續 72 小時無故障運行（接 Stage 5b 的 testnet）。
- Feature/decision parity 全程維持在容許誤差內。
- 風控注入測試（同 Stage 5a）在 testnet 環境下重跑一次，結果一致。
- 告警確實觸發（主動製造至少一次風控觸發、一次連線異常、一次對帳失敗，確認都有告警）。

### Stage 6b — 策略畢業標準（30 天，背景跑，不擋 harness 後續開發）
**目標**：核准策略在 paper trading 帳戶上長期無人值守運行，作為策略本身（不是 harness）能否進一步晉升的最終標準。
**可驗收**：
- Stage 6a 完工後，策略在 paper trading 上持續運行 30 天（背景進行，期間可以繼續開發下一個策略或優化 harness，不互相阻擋）。
- 每日自動產出 PnL / 績效報告；30 天內任何一天發現問題可以重來，不影響 harness 已完工的事實。
- 觀察期結束後，產出「是否達到晉升關卡最終標準」的客觀報告——這份報告是「這個策略好不好」的答案，Stage 6a 才是「這個 harness 好不好」的答案，兩者分開判定。

**明確排除（Out of scope，本文件不涉及）**：真實資金自動下單、多資產類別擴充（除跨標的驗證外）、高頻/低延遲優化、Research/Dev/Analyst 三 agent 拆分的細節設計（留待 Stage 3 跑出結果、看出瓶頸後再評估）。

---

## 已定案的設計決策

1. **資料切分**：按時間切，60/20/20（train / validation-OOS / final-holdout）；查詢額度為整個 run 的總預算（20 次），與 `cost_limit`/`step_limit` 同層設定。額外要求跨標的驗證（BTC 開發，ETH/USDT、SOL/USDT 當 holdout，不重新調參）。
2. **Agent 拆分**：Stage 3 先做單一 agent，Research/Dev/Analyst 拆分留到有 trajectory、看出瓶頸後再評估。
3. **自建模擬器 vs testnet**：兩者都要，順序不能顛倒——Stage 5a 自建模擬器先驗證邏輯正確性與 parity（需要完全確定性的環境），Stage 5b testnet 再磨工程健壯性（斷線重連、rate limit、API 怪癖）。
4. **頻率與標的**：1h bar、單一 BTC/USDT 起步開發。理由：15 分鐘以下雜訊佔比高、手續費吃掉大部分 alpha，且回測迭代變慢；日線四年僅約 1400 根，樣本不足以支撐統計結論；1h 四年約 35000 根，是三者的甜蜜點。驗證階段強制跨標的（見第 1 點）。
