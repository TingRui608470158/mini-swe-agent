# Stage 1 — 確定性回測引擎（無 agent）

> 本文件是 [quant-trading-harness-architecture.md](quant-trading-harness-architecture.md) 「分階段 MVP」中 Stage 1 的規則書，直接建立在 [stage0-feature-library.md](stage0-feature-library.md) 的產出之上。這裡定下的每一條規則之後都會被 Stage 2 的晉升關卡引用，並在 Stage 5 的線上 Strategy Runner 原封不動重現，因此**一旦有策略被這個引擎評估過，本文件的規則即凍結**；要改就要連帶重跑所有已評估過的策略。

## 目標

給定 Stage 0 的 K 棒與特徵、一個純函數策略、一組手續費滑價參數，產出**確定性、可重現**的績效報告，並在同一份報告裡算出同期 buy-and-hold 基準。回測引擎是 agent 不可修改的工具（掛載在 `/gate`），agent 只能餵策略進去、讀報告出來。

## 範圍

- 輸入：Stage 0 的 `normalize_ohlcv` 輸出 + `compute_features` 輸出（同一段 `ts`）、一個 `generate_signal` 純函數、成本參數。
- 輸出：逐 K 棒的部位/報酬/成本/權益序列 + 彙總報告（JSON 可序列化）。
- **本階段不含**：晉升關卡的門檻判定與多空盤整分段（Stage 2）、資料切分與權限隔離（Stage 2）、純函數靜態檢查（Stage 2）、agent（Stage 3）。本階段只負責「算得對、算得一樣」。

## 規則（實作時不可偏離）

### R1. 策略介面

```python
def generate_signal(features: dict[str, float]) -> float: ...
```

- 引擎對每一根 K 棒呼叫一次，傳入**該根 `ts` 的特徵 dict**（key 順序 = `FEATURE_NAMES`），不傳 K 棒本身、不傳歷史、不傳目前部位。策略看不到任何 DataFrame。
- warmup 期間的特徵值是 `nan`，引擎**照樣傳入**；策略自行決定怎麼處理。
- 回傳值語意：**目標部位**，以權益的倍數計，`+1` = 全倉多、`-1` = 全倉空、`0` = 空手（永續合約語意，允許做空；資金費率不在本階段模型內，見 R3）。
- 引擎對回傳值做兩件事，且只做這兩件：非有限值（`nan`/`inf`）視為 `0.0`；其餘 clip 到 `[-1, 1]`。這是線上 `risk_engine.clamp` 的最小版本，之後線上側只會更嚴、不會更鬆。
- 策略以 Python 檔案交付，模組層級必須有 `generate_signal`。Stage 1 的載入器只負責 `importlib` 載入並取出這個函式；純函數性（禁止 IO/隨機/wall-clock）的強制檢查是 Stage 2 的事。

### R2. 執行時點與報酬歸屬（本階段最重要的一條）

設 K 棒依 `ts` 排序，索引 `t = 0, 1, ..., n-1`，`c_t` 為收盤價，`pos_t` 為引擎在 `ts_t` 決定的部位（用 `ts_t` 的特徵算出來的訊號經 R1 處理）。

- `pos_t` 於 `ts_t`（即第 `t` 根收盤、收盤價已知的那一刻）成交，以 `c_t` 成交。
- `pos_t` 持有整個第 `t+1` 根，賺取 `c_t → c_{t+1}` 的報酬：
  `gross_{t+1} = pos_t × (c_{t+1} / c_t − 1)`
- 邊界：`pos_{-1} = 0`（開始時空手），`gross_0 = 0`。最後一根的 `pos_{n-1}` 不會產生報酬（沒有 `c_n`），但**會**產生換手成本。
- 這是標準的「訊號延後一根」回測：`gross_{t+1}` 只依賴 `pos_t`，而 `pos_t` 只依賴 `ts_t` 為止的資訊，look-ahead 在結構上被排除。
- 「以 `c_t` 成交」是輕微樂觀假設（實際上不可能剛好成交在收盤價）。加密市場 24/7 連續交易，`open_{t+1}` 與 `c_t` 是同一個 tick，因此與「下一根開盤成交」等價，差異全部由 R3 的滑價吸收。

### R3. 成本模型

```python
@dataclass
class CostModel:
    fee_bps: float = 10.0       # Binance 現貨 taker 0.1%
    slippage_bps: float = 5.0
```

- 換手：`turnover_t = |pos_t − pos_{t-1}|`
- 成本（以權益比例計，在 `t` 當下扣）：`cost_t = turnover_t × (fee_bps + slippage_bps) / 10_000`
- 淨報酬：`net_t = gross_t − cost_t`
- 權益：`equity_t = equity_{t-1} × (1 + net_t)`，`equity_{-1} = 1`。部位是權益倍數，所以這等於每根重新平衡到目標倍數。
- 不模型化：資金費率、借券利息、部分成交、最小下單單位、槓桿保證金。這些都是把回測**推向樂觀**的省略，Stage 2 的門檻 margin 要把這件事考慮進去；Stage 5b 接 testnet 後再決定要不要補。
- 成本參數是報告的一部分（見 R5），不可隱含。

### R4. 績效指標定義

所有指標都定義在一段 `net_t` 序列上，並可套用在任意子集（Stage 2 要拿去做多空盤整分段、跨標的評估，只需要傳 mask 進來，不需要改引擎）。

| 指標 | 定義 |
|---|---|
| `total_return` | `equity_{n-1} − 1` |
| `sharpe` | `mean(net) / std(net, ddof=1) × sqrt(8760)`；無風險利率 = 0；`std == 0` 或樣本 < 2 時為 `nan` |
| `max_drawdown` | `min_t (equity_t / max_{s≤t} equity_s − 1)`，介於 `[-1, 0]` |
| `turnover` | `mean(turnover_t)`，每根平均換手（權益倍數） |
| `n_trades` | `turnover_t > 0` 的根數 |
| `n_bars` | 序列長度 |

年化因子 `8760 = 24 × 365`。1h 資料一律用這個數，不因閏年或缺漏根調整。

### R5. Buy-and-hold 基準與報告

- 基準 = 同一段 K 棒、同一個 `CostModel`、`pos_t ≡ 1` 跑同一個引擎（所以只在 `t = 0` 付一次進場成本）。**不是**另外寫一段程式算，是把常數策略餵進同一條路徑。
- 報告額外提供 `corr_with_benchmark = corr(net_t, net^{bh}_t)`（Pearson，Stage 2 用來排除純 beta 策略）。
- 報告結構（JSON 可序列化，key 順序固定）：

```
{
  "period": {"start": ts_0, "end": ts_{n-1}, "n_bars": n},
  "cost_model": {"fee_bps": ..., "slippage_bps": ...},
  "strategy": {total_return, sharpe, max_drawdown, turnover, n_trades, n_bars},
  "benchmark": {同上},
  "corr_with_benchmark": ...
}
```

- 引擎同時回傳逐根序列（`pos`, `turnover`, `gross`, `cost`, `net`, `equity`）供 Stage 2 分段與人工檢視；序列 index = 輸入 `ts`。

### R6. Determinism

- 同一份輸入（K 棒 + 特徵 + 策略 + 成本）跑兩次，逐根序列逐位元相同，報告 JSON 序列化後**位元組**相同。
- 引擎本身無隨機、無 wall-clock、無 IO（載入策略檔除外）。
- 逐根迴圈按 `t` 順序呼叫策略，不平行、不向量化策略呼叫，確保策略被呼叫的順序與次數在離線線上一致。

## 模組配置（建議）

- `quantharness/strategy.py`：`load_strategy(path: Path) -> Callable[[dict], float]`、`sanitize(signal: float) -> float`（R1 的非有限→0 + clip）。
- `quantharness/backtest.py`：`CostModel`、`run_backtest(bars, features, generate_signal, cost) -> BacktestResult`（逐根序列 DataFrame + `report()`）。
- `quantharness/metrics.py`：`sharpe`、`max_drawdown`、`summarize(net, turnover) -> dict`（R4 的六個指標）。
- 範例策略只放在測試裡，不進套件。

## 可驗收標準

對應主文件原文，具體化為自動化測試：

1. **手寫 trivial 策略跑出完整報告**：`generate_signal = lambda f: 1.0 if f["sma_50_ratio"] > 0 else 0.0`（價格在 50h 均線上就全倉多，否則空手）在 Stage 0 的合成 K 棒上跑出 R5 結構的報告，六個指標全部有值（`sharpe` 可為 `nan` 僅限 R4 定義的退化情況）、`benchmark` 存在、`corr_with_benchmark` 在 `[-1, 1]`。
2. **Determinism**：同一輸入跑兩次，`assert_frame_equal(check_exact=True)` 逐根序列相同，`json.dumps(report, sort_keys=False)` 位元組相同。
3. **手算對照（極小合成資料）**：5–6 根人工設定的收盤價 + 一個部位路徑固定的策略（例如 `[0, 1, 1, -1, 0, ...]`），人工算出每根的 `gross`、`cost`、`net`、`equity`、`max_drawdown`、`turnover`、`n_trades`，引擎輸出必須**精確**相等（成本設成整數 bps、價格設成讓除法精確的數，例如 100 → 110 → 99）。Sharpe 用 `pytest.approx` 對 `statistics` 模組手算。
4. **R2 無 look-ahead**：把第 `t` 根之後的 K 棒與特徵全部換成隨機垃圾，`pos_{≤t}`、`gross_{≤t}`、`net_{≤t}` 必須完全不變（同 Stage 0 的做法）。另放一個作弊策略（引擎測試裡直接用 `c_{t+1}` 決定部位）證明檢查抓得到。
5. **R1 clamp**：策略回傳 `2.0`、`-5.0`、`nan`、`inf` 時，`pos` 分別為 `1.0`、`-1.0`、`0.0`、`0.0`。
6. **基準走同一條路徑**：常數策略 `lambda f: 1.0` 的 `strategy` 區塊必須與 `benchmark` 區塊逐位元相同。

## Out of scope（本階段明確不做）

- 多空盤整分段、相對門檻判定、跨標的評估（Stage 2；本階段只提供可套 mask 的 `summarize`）
- 資料三段切分與掛載隔離（Stage 2）
- 策略純函數靜態分析、斷網沙盒（Stage 2）
- 資金費率、槓桿、部分成交（見 R3）
- 多標的同時持倉、投組層級風控（單一標的到底）
- 效能最佳化：逐根呼叫策略是刻意的（R6），35k 根 × 一次 Python 函式呼叫在一秒內

## 完成後銜接

Stage 2 的晉升關卡完全建立在 R4/R5 之上：相對門檻 = `strategy.sharpe − benchmark.sharpe`、beta 排除 = `corr_with_benchmark`、分段評估 = 對逐根序列套 mask 再呼叫 `summarize`。Stage 5 的線上 Strategy Runner 會以 R1 的介面、R2 的時點語意逐根呼叫同一個 `generate_signal`，因此 Stage 5a 的 parity 測試就是「線上逐根決策序列 == 離線 `pos` 序列」。
