# Stage 3 — Offline 研發 Harness MVP（單一 agent，驗收用合成資料）

> 本文件是 [quant-trading-harness-architecture.md](quant-trading-harness-architecture.md) 「分階段 MVP」中 Stage 3 的規則書，建立在 [Stage 0](stage0-feature-library.md)、[Stage 1](stage1-backtest-engine.md)、[Stage 2](stage2-promotion-gate.md) 之上，並把 Stage 2.5（合成驗收集）的**最小版**一併定義為前置條件。這是第一個有 LLM 參與的階段；所有規則的核心只有一件事——**harness 的判定不能依賴 agent 的任何說法**。

## 目標

用 mini-swe-agent 既有的三層（`DefaultAgent` 控制迴圈、`DockerEnvironment`、任一 `Model`）加一個 run script，讓單一 agent 在 Stage 2 的容器裡用 bash 自主：寫策略檔 → 用 train 段自己回測 → 讀結果 → 修正 → 呼叫 `gate score` → 直到 PASS 或用完預算。run script 在容器外**獨立驗證**結果並保存全部產物。

## 範圍

- 單一 agent（主文件的決定：先跑通、拿到 trajectory，才看得出要不要拆 Research/Dev/Analyst）。
- 輸入：Stage 2 的 gate 映像（真實或合成資料版）、一份 run config yaml、一個 model。
- 輸出：`runs/<run_id>/` 目錄：trajectory、提交的策略檔、gate 全部輸出、run 級判定。
- **本階段不含**：holdout 評估、人工簽核、登記表（Stage 4）；真實市場資料的成敗判定（Stage 3.5 明定不設二元標準）；多 agent 拆分。

## 前置：Stage 2.5 最小版（合成驗收集）

Stage 3 的驗收是二元的，只有在「標準答案已知存在」的資料上才成立。Stage 2 測試用的 AR(1) 合成資料就是這個東西，本階段把它從測試 fixture 升格為正式模組：

- `quantharness/synthetic.py`：`ar1_bars(seed, n, phi, sigma)`（均值回歸 log 報酬 `r_t = -phi·r_{t-1} + eps`）、`trend_bars(seed, n)`；CLI `python -m quantharness.synthetic OUT_DIR --seed 1` 寫出 `BTCUSDT/ETHUSDT/SOLUSDT.csv`（三個 symbol 同製程、不同 seed）。Stage 2 的測試 conftest 改為 import 這個模組。
- **已知答案**：`-sign(ret_1)`（`math.copysign(-1.0, ret_1)`，`nan` 回 0）在預設參數（`phi=0.6, sigma=0.01, n=10_000`）下通過 Stage 2 全部準則；**噪音對照**：依 `vol_ratio_24` 決定部位的策略被擋下。這兩件事已由 `tests/quantharness/test_gate.py` 自動驗證，Stage 2.5 不再另設驗收。
- 合成映像：`python -m quantharness.synthetic build/synthetic_raw && python -m quantharness.split build/synthetic_raw build/segments && docker build ... -t quantharness-gate:synthetic .`。映像 tag 是 Stage 3 唯一需要換的東西；harness 其餘部分對「資料是真是假」一無所知。
- 正式版 Stage 2.5（更貼近市場結構的植入 alpha，例如「波動度突破後 3 根正漂移」）留待 Stage 3 用最小版跑通後再決定是否需要。

## 規則（實作時不可偏離）

### R1. 元件組裝：只加 run script，不改三層

| 元件 | 用什麼 | 不做什麼 |
|---|---|---|
| Model | `get_model(config["model"])`，任何 litellm 支援的模型。本機 Ollama 要用 `ollama_chat/<model>`（走 `/api/chat`，才支援 tool calling）而不是 `ollama/<model>`（走 `/api/generate`，無 tools）；tool calling 不穩的本機模型可改 `model_class: litellm_textbased` 從文字解析 bash 區塊，完全不依賴 tool calling | 不寫新 model 類別 |
| Environment | 原版 `DockerEnvironment`，`image=quantharness-gate[:tag]`、`cwd=/workspace`、`run_args` 見 R5、`timeout` 見 R4 | **不改 `DockerEnvironment`**；隔離全靠映像與 `run_args` |
| Agent | `QuantResearchAgent(DefaultAgent)`，只多一個 hook（R6 的額度檢查與 R7 的判定資料），其餘沿用 | 不改 `DefaultAgent` |
| Run script | `minisweagent/run/extra/quant_research.py`（typer；依 `run/benchmarks/swebench_single.py` 的 config 合併模式） | — |
| Config | `minisweagent/config/extra/quant_research.yaml`：`agent`/`environment`/`model`/`gate` 四段 | — |

`DockerEnvironment` 以 `docker exec -w /workspace <id> bash -lc <cmd>` 執行每個動作，身分是映像的 `USER agent`；這正是 Stage 2 R6 假設的執行模型，不需要任何額外接線。

### R2. Prompt 規則：資料無關、規則完整、不給答案

`system_template` 與 `instance_template` 必須：

1. **對資料內容一無所知**——同一份 prompt 用於合成與真實資料的 run。prompt 裡不可出現任何暗示 alpha 型態的字眼（「均值回歸」、「趨勢」、「反轉」都不行），只能描述任務、介面與規則。這是 Stage 3 驗收有意義的前提：如果 prompt 說了答案，agent 找到它證明不了 harness 有效。
2. 完整轉述 agent 會踩到的每一條規則，因為 agent 看不到規則書：
   - 策略介面（Stage 1 R1）：`generate_signal(features: dict) -> float`、目標部位 `[-1, 1]`、`nan` 會被傳入、非有限值視為 0。
   - 特徵名稱與定義（Stage 0 的 8 個特徵，含 warmup 長度）。
   - 純函數限制（Stage 2 R2a）：import 只能 `math`、`typing`；列出呼叫黑名單與「模組層級只能放字面常數」；說明會被排列順序測試抓到的藏狀態。
   - 成本模型與時點語意（Stage 1 R2/R3）的一句話版本：訊號在收盤成交、下一根結算、每單位換手 15 bps。
   - 額度（Stage 2 R4）：`gate score` 對 validation 共 20 次、耗盡即拒絕、`check` 與 `--segment train` 免費、純函數失敗不計。
   - 檔案系統：`/workspace` 可寫、`/data/train/*.csv` 可讀、validation 只能透過 gate、holdout 不存在、無網路。
   - 工具：`sudo -n /gate/bin/gate check|score|budget`；`python` 內可 `from quantharness.data import load_ohlcv` 等自己跑 train 回測（`PYTHONPATH` 已設）。附一段最短可用的回測程式碼範例。
3. 明確的**成功與提交條件**：只有在 `gate score`（validation）回 `"pass": true` 且 exit code 0 之後，才可執行 `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`。策略檔路徑**固定**為 `/workspace/strategy.py`；提交當下該檔的內容就是提交物，必須與通過 gate 的版本位元組相同。在此之前提交視為失敗。
4. 動作格式（tool call 或 ```mswea_bash_command 區塊）由 run script 依 `model.model_class` 以 Jinja 變數 `action_format` 切換措辭；`quant_research.yaml` 只覆寫 `agent.instance_template`，`system_template` 與 `model.*` 模板沿用底層的 `mini.yaml` / `mini_textbased.yaml`（config 疊層：`-c mini.yaml -c quant_research.yaml`）。

### R3. 判定不信任 agent：以 gate 的 root-only 紀錄為準

Stage 2 的 gate 新增一項紀錄（Stage 2 小幅修訂）：每次 **validation** `score` 在 `/gate/state/scores.jsonl`（root-only，與 `budget.json` 同目錄）追加一行 `{"ts", "sha256", "pass", "criteria"}`，`sha256` 為被評估策略檔內容的雜湊。agent 讀不到也改不了這個檔。

run 結束後，run script 以 `docker exec -u root` 讀出 `scores.jsonl` 與 `/workspace/strategy.py`，判定如下（順序即優先序；`Submitted` 先於額度判定）：

| 判定 | 條件 |
|---|---|
| `PASS` | agent 以 `Submitted` 結束，`/workspace/strategy.py` 存在，其 `sha256` 在 `scores.jsonl` 中**最後一次**出現的紀錄 `pass == true` |
| `FAIL_UNVERIFIED` | agent 以 `Submitted` 結束，但檔案不存在 / 雜湊不在紀錄中 / 最後一次紀錄 `pass == false`（包含「通過後又改了檔案」） |
| `FAIL_BUDGET` | 非 `Submitted` 結束、額度歸零且無任何 `pass == true` 紀錄 |
| `FAIL_LIMITS` | agent 以 `LimitsExceeded` / `TimeExceeded` / `RepeatedFormatError` 結束 |
| `ERROR` | 其他 exit status（例外、容器啟動失敗、沙盒探針失敗等） |

`PASS` 是唯一的成功。agent 說了什麼、trajectory 裡 gate 輸出寫了什麼，一律不作為判定依據——只有 root-only 紀錄算。

### R4. 預算：三種上限、三個地方、一份 config

| 上限 | 位置 | 預設 | 用盡時 |
|---|---|---|---|
| `agent.step_limit` | agent config（既有） | 80 | `LimitsExceeded` |
| `agent.cost_limit` | agent config（既有） | 5.0 USD | `LimitsExceeded` |
| `agent.wall_time_limit_seconds` | agent config（既有） | 3600 | `TimeExceeded` |
| `gate.budget`（validation 查詢） | run config `gate` 段 → 容器啟動時由 run script 以 `docker exec -u root` 寫入 `/gate/state/budget.json` | 20 | R6 |
| `environment.timeout`（單一動作） | environment config（既有） | 300 秒 | 該動作 returncode −1，agent 繼續 |

四種上限都在同一份 yaml，符合主文件「額度與 `cost_limit`、`step_limit` 放在同一層」的要求。映像內建的 `budget.json` 只是預設值；run script **一律**在容器啟動後覆寫它，使「一個容器 = 一個 run = 一份額度」成為 run script 保證的事，而不是映像的巧合。

### R5. 沙盒：`run_args` 明列，啟動時探針驗證，fail-closed

`environment.run_args` 預設：`["--rm", "--network", "none", "--memory", "2g", "--cpus", "2", "--pids-limit", "256"]`。

容器啟動後、agent 第一步之前，run script 以 **agent 身分**執行五個探針，任何一個結果不符即中止 run（`ERROR`），不讓 agent 開始：

1. `id -un` → `agent`
2. `cat /data/validation/BTCUSDT.csv` → 非 0
3. `ls /data/holdout` → 非 0
4. `python -c "import socket; socket.create_connection(('1.1.1.1', 53), 2)"` → 非 0
5. `sudo -n /gate/bin/gate budget` → 0 且 JSON 的 `budget_remaining == gate.budget`

探針結果寫進 `verdict.json`（R7）。這是把 Stage 2 的容器測試搬進每一次 run：隔離不是「測過一次」，是「每次開跑前確認」。

### R6. 額度耗盡即結束

`QuantResearchAgent.execute_actions()` 在每個動作執行後，若動作字串含 `gate score`，解析該動作輸出的最後一行 JSON（gate 的 stdout）：記住是否曾出現 `"pass": true`；當 `budget_remaining == 0` 且從未 pass 時，raise `InterruptAgentFlow` 子類別 `QueryBudgetExhausted`，exit status `QueryBudgetExhausted`（→ R3 的 `FAIL_BUDGET`）。理由：額度歸零後 agent 已無法再讓任何策略通過，繼續燒 LLM 成本沒有意義。只解析觀察輸出而不以 root 讀檔，讓 agent 類別不耦合 Docker、可用 `LocalEnvironment` 單元測試；agent 若偽造這段輸出只會提早結束自己的 run，R3 的判定仍只看 root 紀錄。

### R7. 產物：一個目錄、可回放、可審核

`runs/<run_id>/`（`run_id` = 啟動時間 + 映像 tag）：

```
trajectory.traj.json   mini-swe-agent 標準格式，inspector 可直接開
strategy.py            agent 提交的檔案（docker cp 出來；未提交則無）
scores.jsonl           gate 的 root-only 紀錄（原樣複製）
budget.json            結束時的額度狀態
verdict.json           {"verdict", "exit_status", "submission", "sha256", "probes", "config", "model_stats", "image"}
```

`verdict.json` 與 `trajectory.traj.json` 加起來就是 Stage 4 人工審核的輸入；Stage 4 不需要再跑任何東西才能理解這個 run 發生了什麼。

## 模組配置（建議）

- `quantharness/synthetic.py`（Stage 2.5 最小版，見前置）。
- `quantharness/gate.py`：`score` 於 validation 追加 `scores.jsonl`（R3）。
- `minisweagent/agents/extra/quant_research.py`：`QuantResearchAgent(DefaultAgent)`（R6）；`exceptions.py` 加 `QueryBudgetExhausted(InterruptAgentFlow)`。
- `minisweagent/run/extra/quant_research.py`：組裝、探針、額度初始化、判定、產物（R1/R3/R4/R5/R7）。
- `minisweagent/config/extra/quant_research.yaml`：R2 的 prompt + R4 的四種上限 + R5 的 `run_args`。
- `docker/gate/README.md` 補「合成映像」建置指令。

## 可驗收標準

對應主文件三項，拆為可自動化的部分（`tests/run/test_quant_research.py`，用 `DeterministicModel` 腳本化 agent 行為，需 Docker、`slow`）與需要真 LLM 的部分（手動、有成本）。

**自動化（腳本化 agent，不需 LLM）** — 這些測試驗證的是 harness 的接線與判定，不是模型：

1. **快樂路徑 → `PASS`**：腳本 = 寫入已知答案策略 → `gate check` → `gate score` → 提交路徑。判定 `PASS`，`runs/<id>/` 五個檔案齊全，`verdict.json.sha256` 等於 `strategy.py` 的雜湊，trajectory 可被 `DefaultAgent` 的 `trajectory_format` 讀回。
2. **謊報 → `FAIL_UNVERIFIED`**：腳本寫入好策略但**不呼叫 gate** 就提交 → `FAIL_UNVERIFIED`。腳本通過 gate 後**改一個字元**再提交 → `FAIL_UNVERIFIED`（雜湊不符）。
3. **額度耗盡 → `FAIL_BUDGET`**：`gate.budget: 2`，腳本用噪音策略 score 兩次，第三步任意動作 → agent 以 `QueryBudgetExhausted` 結束、判定 `FAIL_BUDGET`、trajectory 最後一則 `role == "exit"`。
4. **上限 → `FAIL_LIMITS`**：`step_limit: 3`，腳本永遠 `ls` → `FAIL_LIMITS`。
5. **探針 fail-closed → `ERROR`**：用一個故意把 `/data/validation` 設成 0644 的測試映像啟動 → 探針 2 失敗 → 判定 `ERROR`、agent 零步、trajectory 只有 system/instance 兩則訊息。
6. **額度由 run config 決定**：`gate.budget: 7` → 探針 5 讀到 7，與映像內建的 20 無關。
7. **Prompt 資料無關**：靜態測試——渲染後的 system/instance template 不含 `mean.?revers|trend|momentum|reversal|AR\(1\)|phi` 等字樣（regex 清單放在測試裡，之後只增不減）。

**手動（真 LLM，Stage 3 的正式驗收）** — 主文件的二元判定：

8. `python -m minisweagent.run.extra.quant_research -c quant_research.yaml -m <model> --image quantharness-gate:synthetic` 在合成資料上以預設預算跑到 `PASS`，全程無人介入。**通過**：至少 3 次獨立 run 中 2 次 `PASS`（LLM 非確定性，容許一次失敗但不容許系統性失敗）。**失敗**時可歸因：`FAIL_UNVERIFIED` 多為 prompt 對提交條件講不清；`FAIL_BUDGET` 多為 prompt 對額度或純函數規則講不清；`FAIL_LIMITS` 看 trajectory 卡在哪一步。三種失敗都是 harness（prompt/工具）問題，因為答案已知存在。
9. 用 inspector 開 trajectory，能逐步看到 agent 寫了什麼、gate 回了什麼——這是 Stage 3.5 與日後多 agent 拆分決策的唯一依據。

## Out of scope（本階段明確不做）

- Research/Dev/Analyst 多 agent（主文件：等 Stage 3 trajectory 出來再決定）
- holdout 評估、人工簽核、登記表（Stage 4）
- 真實資料 run 的成敗標準（Stage 3.5：只產出紀錄）
- 正式版植入 alpha 沙盒（先用 AR(1) 最小版跑通）
- 批次多 run / 多 seed 平行執行（`run/benchmarks/` 風格的 batch runner 留待需要統計時再加）
- prompt 迭代最佳化：本階段只要求 prompt 完整且資料無關；提高通過率是拿到第一批 trajectory 之後的事

## 完成後銜接

- **Stage 3.5**：同一個 run script、同一份 prompt，只換 `--image quantharness-gate:real`（真實 BTC/ETH/SOL 段檔建的映像）。產出即為紀錄，`PASS` 進 Stage 4，否則記錄為「暫無可上線策略」。
- **Stage 4**：輸入是 `runs/<id>/`；人工審核只需 `verdict.json`、`strategy.py`、`scores.jsonl`、trajectory；holdout 評估呼叫 Stage 2 的 `evaluate(strategy, "holdout", ...)`（容器外）。
- **多 agent 決策**：看第 9 項的 trajectory——agent 在哪類步驟浪費最多 step/cost，才是拆分的依據。
