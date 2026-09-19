# Stage 2 — 晉升關卡 / Evaluator（無 agent）

> 本文件是 [quant-trading-harness-architecture.md](quant-trading-harness-architecture.md) 「分階段 MVP」中 Stage 2 的規則書，建立在 [Stage 0](stage0-feature-library.md) 的特徵與 [Stage 1](stage1-backtest-engine.md) 的回測引擎之上。晉升關卡是這個 harness 的 FAIL_TO_PASS：**agent 不可修改、標準明確、結果二元**。主文件「資料與評估設計」列出的每一條標準在這裡都對應到一個可自動判定的準則（C1–C7）與一條落實機制。

## 目標

做出一個獨立的 CLI 工具 `gate`，輸入一個策略檔，輸出「通過 / 未通過 / 拒絕評估」與每條準則的數值，並且：

1. 對 validation 資料的查詢受**整個 run 的總額度**限制；
2. agent 在容器內**讀不到** validation、**看不見** holdout，但能透過 `gate` 拿到 validation 分數；
3. 純函數性靠**靜態分析 + 執行期檢查**強制，不靠約定；
4. 以上三點全部由檔案系統權限與程序邊界落實，agent 改不掉。

## 範圍

- 輸入：策略檔（Stage 1 R1 介面）、Stage 0 格式的 K 棒資料（BTC/USDT 為主、ETH/USDT 與 SOL/USDT 為跨標的）。
- 輸出：JSON 報告 + exit code。
- **本階段不含**：合成 alpha 驗收集（Stage 2.5）、agent 與 run script（Stage 3）、人工簽核與登記表（Stage 4）、holdout 的實際評估（Stage 4 才跑，Stage 2 只讓同一個函式能接受 `segment="holdout"`）。

## 規則（實作時不可偏離）

### R1. 資料三段切分

- 以 BTC/USDT 正規化後的 K 棒為準，依**根數**切：`train = bars[: floor(0.6n)]`、`validation = bars[floor(0.6n) : floor(0.8n)]`、`holdout = bars[floor(0.8n) :]`。三段半開區間、互不重疊、聯集為全體。
- 切點轉成 `ts` 後寫入 `split.json`（`train_end`、`validation_end`），ETH/USDT、SOL/USDT **套用同一組 `ts` 切點**，不各自依根數切。
- 每個段的資料檔**自帶前置 `LOOKBACK` 根 warmup**（來自前一段的尾巴），使該段的特徵可以獨立計算且與「全序列算完再切」逐位元相同（Stage 0 parity 的直接推論）。回測只在段本身的根上跑：`pos` 從段的第一根開始、起始空手，warmup 根不產生部位、報酬或成本。
- 對 agent 可見性（見 R6）：`train` 可讀；`validation` 存在但不可讀，只能透過 `gate score` 取分數；`holdout` 完全不掛載。

### R2. 純函數檢查（三層，缺一不可）

**R2a 靜態分析**（`ast`，不執行策略碼；失敗**不消耗**額度，因為沒碰到任何資料）：

- `import` 白名單：只允許 `math`、`typing`。其他一律拒絕——`random`、`time`、`datetime`、`os`、`sys`、`socket`、`requests`、`subprocess`、`pathlib`、`io`、`numpy`、`pandas` 都不在名單上。策略的輸入是 8 個 float，不需要別的。
- 呼叫黑名單（任何位置）：`open`、`exec`、`eval`、`compile`、`__import__`、`getattr`、`setattr`、`delattr`、`globals`、`locals`、`vars`、`input`、`print`、`breakpoint`。
- 屬性黑名單：任何以雙底線開頭結尾的屬性存取（`__dict__`、`__globals__`、`__builtins__`、`__class__`…）。
- 禁止 `global`、`nonlocal` 陳述式。
- 模組層級只允許：`import`、`def`、`class`、以及右邊是字面常數（數字、字串、bool、None、由前述組成的 tuple）的 `Name = ...` 賦值。模組層級的可變容器（`list`/`dict`/`set` 字面值或呼叫）一律拒絕——那是跨呼叫狀態的藏身處。
- 必須存在模組層級的 `def generate_signal(features)`（恰好一個位置參數）。
- 拒絕時回報第一個違規的行號與原因。

**R2b 執行期 determinism**（在 `train` 段特徵上執行，失敗**不消耗**額度）：

- 順序評估一次得到 `sig_seq[t]`；用固定 seed 的排列 `π` 以**同一個已載入的模組**再評估一次得到 `sig_perm[π(t)]`；兩者必須逐根逐位元相等。這抓的是靜態分析漏掉的跨呼叫狀態（例如以 closure 或參數預設值藏狀態）。
- 重新 `import` 一次再順序評估，與 `sig_seq` 逐位元相等。這抓 import 時的隨機性。
- 非有限回傳值在此不算失敗（Stage 1 R1 已定義為空手）。

**R2c 執行沙盒**：

- 策略評估在**子程序**中執行，wall-clock 上限 `timeout_seconds`（預設 60 秒，涵蓋單一段全部根）；超時視為 R2 失敗，不消耗額度。
- 無網路是**容器層級**屬性（`--network none`，見 R6），gate 不重新實作；Stage 2 的容器煙霧測試會從 agent 使用者的視角驗證連不出去。

### R3. 晉升準則

全部在 **validation 段**上、用 Stage 1 引擎與預設 `CostModel` 計算。全部是**相對**或**符號**判定，沒有任何絕對數值門檻。

| 準則 | 定義 | 預設參數 |
|---|---|---|
| **C1 相對 Sharpe** | `strategy.sharpe >= benchmark.sharpe + sharpe_margin` | `sharpe_margin = 0.5` |
| **C2 三段分開為正** | 見下方分段規則；每個**出現過**的 regime，策略在該 regime 全部根上的 `summarize(...)["total_return"] >= 0` | `regime_window = 720`（30 天）、`regime_threshold = 0.10` |
| **C3 排除 beta** | `abs(corr_with_benchmark) <= max_abs_corr` | `max_abs_corr = 0.7` |
| **C4 扣成本後為正** | `strategy.total_return > 0`（Stage 1 的 `net` 已含成本） | — |
| **C5 純函數** | R2a、R2b、R2c 全部通過 | — |
| **C6 跨標的不劣化** | 對每個 `cross_symbols`，用**同一個策略檔、不重新調參**跑同一 validation 期間：`total_return > 0` **且** `sharpe >= benchmark.sharpe`（margin 為 0，比 C1 寬） | `cross_symbols = ("ETHUSDT", "SOLUSDT")` |
| **C7 final-holdout + 人工簽核** | 同一個 `evaluate(segment="holdout")` 在容器外由 Stage 4 執行一次，C1–C4、C6 全部通過；人工核准 | Stage 4 |

**分段規則（C2）**：在 validation 段上，從第一根起切**非重疊**的 `regime_window` 根視窗，最後不足半個視窗的尾巴丟棄。視窗 regime 由 benchmark 該視窗的複利 gross 報酬決定：`> +regime_threshold` 為多頭、`< -regime_threshold` 為空頭、其餘盤整。策略在某 regime 的 `total_return` 是把該 regime 所有視窗的根 mask 出來、對 `net`/`turnover` 呼叫 Stage 1 的 `summarize`（權益在 mask 內重新從 1 複利）。validation 段沒出現的 regime 不判定、但在報告中標示為 `absent`。

**判定**：`pass = C1 and C2 and C3 and C4 and C5 and C6`。C5 不通過時不計算 C1–C4、C6（見 R2）。

**「永遠滿倉多」必被擋下的證明**：其 `sharpe == benchmark.sharpe`（差 0 < margin，C1 fail）且 `corr == 1.0`（C3 fail），與該段 B&H 的絕對 Sharpe 是 0.5 還是 3 無關。這是為什麼所有準則都不能是絕對門檻。

### R4. 查詢額度

- `budget = 20` 次 `gate score --segment validation`，**以 run 為單位**（一個容器 = 一個 run），不以策略血統為單位。
- 額度狀態存於 gate 專屬、agent 不可寫的檔案（`/gate/state/budget.json`，見 R6），容器啟動時初始化。
- **消耗**：任何真的碰到 validation 資料的評估都消耗一次——不論結果 pass/fail、不論策略多爛。
- **不消耗**：R2 任一層失敗（靜態分析、determinism、超時）——它們在碰資料之前就結束；`gate check`；`gate score --segment train`（train 本來就對 agent 開放，無限制）。
- 額度耗盡：`gate score --segment validation` 立即以 exit code 2 結束，不載入策略、不讀資料，stdout 只有 `{"refused": "budget exhausted", "budget_remaining": 0}`。

### R5. CLI 介面與輸出

```
gate check  STRATEGY.py                          # 只跑 R2，免費
gate score  STRATEGY.py [--segment train|validation]   # 預設 validation；R2 + C1–C4、C6
gate budget                                      # 剩餘額度
```

- stdout 只輸出一個 JSON 物件；stderr 給人讀的訊息。exit code：`0` = 全部準則通過、`1` = 有準則未通過、`2` = 拒絕評估（額度耗盡 / R2 失敗 / 檔案不存在）。
- `score` 的 JSON 結構（key 順序固定）：

```
{
  "segment": "validation", "symbol": "BTCUSDT",
  "period": {"start": ..., "end": ..., "n_bars": ...},
  "budget_remaining": 17,
  "criteria": {
    "purity":          {"pass": true},
    "relative_sharpe": {"pass": ..., "value": strategy.sharpe, "benchmark": benchmark.sharpe, "margin": 0.5},
    "regimes":         {"pass": ..., "value": {"bull": x, "bear": y, "sideways": "absent"}, "n_windows": {...}},
    "beta":            {"pass": ..., "value": corr, "max_abs": 0.7},
    "net_return":      {"pass": ..., "value": strategy.total_return},
    "cross_asset":     {"pass": ..., "value": {"ETHUSDT": {"total_return": ..., "sharpe": ..., "benchmark_sharpe": ...}, "SOLUSDT": {...}}}
  },
  "pass": false
}
```

- **不輸出**逐根序列、不輸出 validation 的任何價格或時間戳細節（`period` 只給段的首尾 `ts`，那已寫在 `split.json`）。20 次查詢 × 十幾個彙總數字是刻意設計的資訊上限。
- `check` 的 JSON：`{"purity": {"pass": bool, "reason": "...", "line": n}}`。
- 參數（`sharpe_margin` 等）集中在一個 `GateConfig` dataclass，由 `/gate/config.json` 載入；agent 對該檔無寫入權限。

### R6. 容器佈局與權限（落實機制，不是約定）

```
/workspace                        agent:agent  rw     策略程式碼、agent 的暫存
/data/train/{BTCUSDT,ETHUSDT,SOLUSDT}.csv   root:root  0644   agent 可讀
/data/validation/{...}.csv        root:root  0600         agent 不可讀，只有 root（gate）可讀
/data/holdout                     不掛載，容器內不存在
/gate/                            root:root  0755  ro     quantharness 套件 + gate CLI + config.json + split.json
/gate/state/budget.json           root:root  0600         只有 gate 程序可寫
```

- agent 以非 root 使用者 `agent`（uid 1000）執行，只有 `/workspace` 可寫。
- `gate` 透過 `sudo -n /gate/bin/gate ...` 執行，sudoers 只授權這一個可執行檔、`NOPASSWD`、`env_reset`、`secure_path`。agent 拿到的是 gate 的**輸出**，不是 validation 的**資料**。
- 容器 `--network none`；`--memory`、`--cpus`、`--pids-limit` 設上限（值放在 run script，Stage 3 決定）。
- `mini-swe-agent` 的 `DockerEnvironment` 原封不動使用；上述全部是 image 與 `docker run` 參數的事，environment 類別不需要改（主文件的決定）。

## 模組配置（建議）

- `quantharness/split.py`：`split_bounds(bars) -> tuple[Timestamp, Timestamp]`、`segment(bars, name, bounds) -> DataFrame`（含 warmup）、`write_segments(...)`。
- `quantharness/purity.py`：`check_static(source: str) -> Violation | None`、`check_determinism(path, features) -> Violation | None`（R2a/R2b）。
- `quantharness/regimes.py`：`label_regimes(benchmark_gross, window, threshold) -> Series[str]`（C2 的視窗標記）。
- `quantharness/gate.py`：`GateConfig`、`evaluate(strategy_path, segment, data_dir, config) -> dict`（C1–C6 的計算與判定，純函式、不管額度）、`Budget`（R4 的檔案狀態）、typer app（R5）。
- `docker/gate/`：`Dockerfile`、`entrypoint.sh`（初始化 budget、擺放資料與權限）、`sudoers`。
- 資料段的產生是**容器外**一次性的建置步驤：`python -m quantharness.split data/ build/segments/`。

## 可驗收標準

對應主文件原文，具體化為自動化測試（`tests/quantharness/test_split.py`、`test_purity.py`、`test_gate.py`；容器測試在 `tests/quantharness/test_gate_container.py`，無 Docker 時 skip）。

1. **切分正確且與全序列一致**：三段互斥、聯集為全體、順序正確；validation 段檔的前 `LOOKBACK` 根等於 train 段的最後 `LOOKBACK` 根；`compute_features(validation_file)` 去掉 warmup 後，與 `compute_features(全序列)` 在同一 `ts` 上逐位元相同；ETH/SOL 用同一組 `ts` 切點。
2. **「永遠滿倉多」被相對基準攔下**：造一段強趨勢合成資料使 B&H 的絕對 Sharpe > 2，`lambda f: 1.0` 仍 `pass=False`，且 `relative_sharpe.pass=False`、`beta.pass=False`（兩個獨立的失敗點）。
3. **明顯有效的手造策略能通過**：用均值回歸的 AR(1) 合成報酬造三個「標的」（同一製程、不同 seed），`generate_signal = -sign(ret_1)` 型策略在 validation 段 C1–C6 全部通過、`pass=True`。同一份資料上，純噪音策略 `sign(hash-free 常數)`（例如依 `ret_24` 符號）必須 `pass=False`。（Stage 2.5 會把這組資料升級為正式的植入 alpha 沙盒；本項只證明關卡能放行真有效的策略。）
4. **額度是 run 的總預算**：連續 20 次 `score --segment validation` 後，第 21 次回 exit code 2、stdout 為 refused、且策略檔**沒有被載入**（用一個載入時會寫檔到 tmp 的策略證明）。`check`、`score --segment train`、以及靜態分析失敗的提交不改變 `budget_remaining`。
5. **純函數檢查**（每一項都是獨立測試）：
   - 靜態：`import socket` / `import requests` / `import random` / `import os` / `from time import time` 各被拒絕並回報行號；`open("x")`、`__import__("socket")`、`getattr(math, "sin")`、`x.__dict__` 被拒絕；`global counter` 被拒絕；模組層級 `cache = {}` 被拒絕；缺少 `generate_signal` 被拒絕；合法策略（只 `import math`、模組層級 `THRESHOLD = 0.01`）通過。
   - 執行期：以參數預設值藏狀態的策略（`def generate_signal(f, _state=[0])`）通過靜態分析但被排列測試抓到；無狀態策略兩種順序逐位元一致。
   - 超時：`while True: pass` 的策略在 `timeout_seconds` 內被終止、回報超時、不消耗額度。
6. **容器權限（Docker，可 skip）**：以 `agent` 使用者執行 `cat /data/validation/BTCUSDT.csv` 得 permission denied；`ls /data/holdout` 得 no such file；`touch /gate/x`、`echo 0 > /gate/state/budget.json` 失敗；`sudo -n /gate/bin/gate budget` 成功回 JSON；`python -c "import socket; socket.create_connection(('1.1.1.1', 53), 2)"` 失敗。

## Out of scope（本階段明確不做）

- 合成植入 alpha 的正式驗收集（Stage 2.5；本階段第 3 項驗收的 AR(1) 資料是它的前身）
- agent、run script、prompt（Stage 3）
- holdout 的實際評估、人工簽核流程、策略登記表（Stage 4；`evaluate(segment="holdout")` 只需能跑）
- 最小交易次數之類的「活躍度」門檻：低交易次數靠運氣通過 validation 的策略，交給 C6 跨標的與 C7 holdout 攔截，不另設絕對門檻
- 網路隔離的程式層重實作（容器層 `--network none` 已足夠）
- 額度的跨 run 持久化、多 run 排程（Stage 3 的 run script 決定一個 run 的生命週期）

## 完成後銜接

- **Stage 2.5** 只需要替換第 3 項驗收用的合成資料製程，關卡本身不動。
- **Stage 3** 的 agent 任務就是「在 `/workspace` 寫出一個 `gate score` 回 exit code 0 的策略檔」；agent 的 prompt 要把 R2a 白名單、R4 額度、Stage 1 R1 的 `nan` 處理講清楚，因為這些是 agent 最可能踩到的規則。
- **Stage 4** 呼叫同一個 `evaluate(strategy, segment="holdout")`（在容器外、有 holdout 資料的地方），結果連同 validation 報告一起進人工審核。
