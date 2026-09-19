# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

## Commands

Dev install (editable, with dev extras) and pre-commit:

```bash
pip install -e '.[dev]'
pip install pre-commit && pre-commit install
```

Run the full test suite (parallelized across cores, ~3 min):

```bash
pytest -n auto
```

Run a single test file / test:

```bash
pytest tests/agents/test_default.py
pytest tests/agents/test_default.py::test_name -v
```

Lint/format (also runs automatically via pre-commit on commit):

```bash
ruff check --fix .
ruff format .
```

Run the CLI directly from source (no install needed for quick iteration):

```bash
python src/minisweagent/run/hello_world.py   # minimal example run script
mini                                          # main CLI (after `pip install -e .`)
mini-extra config setup                       # first-time model setup wizard
```

Tests requiring Docker/Singularity/network are in `tests/environments/test_docker.py`,
`test_singularity.py`, and `tests/models/test_anthropic_model_integration.py` — expect these to
be skipped unless the relevant runtime/credentials are available.

## Architecture

Every use case is a **run script** (`minisweagent/run/*.py`) that wires together exactly one
`Model`, one `Environment`, and one `Agent`, per the `Protocol` classes defined in
`minisweagent/__init__.py`. This is the only place where the three concerns are combined — models,
environments, and agents never import each other.

- **`agents/`** — control flow. `DefaultAgent` (`agents/default.py`) is the ~100-line core loop:
  `run()` seeds system/instance messages then repeats `step()` (query model → execute actions →
  append observation messages) until a message with `role: "exit"` appears. History is fully
  linear — every message the LM sees is just `self.messages`, nothing is hidden or replayed.
  Control-flow signals (task submitted, limits exceeded, format error, user interrupt) are all
  subclasses of `InterruptAgentFlow` in `exceptions.py`, raised by the model/environment and caught
  in the agent's `run()` loop rather than checked with conditionals.
- **`environments/`** — turns an `action` dict (`{"command": ...}`) into an `output` dict via
  `execute()`. `LocalEnvironment` shells out with `subprocess.run`-style calls — **not** a
  persistent shell session; every action is independent, which is what makes it trivial to swap in
  `docker.py`, `singularity.py`, or the `extra/` variants (swerex, bubblewrap, contree) for
  sandboxed execution.
  The special string `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` as the first output line (with
  returncode 0) is how the agent recognizes task completion; it's environment-checked and raises
  `Submitted`.
- **`models/`** — one class per provider/protocol (`litellm_model.py`, `openrouter_model.py`,
  `portkey_model.py`, plus `*_textbased_model.py` / `*_response_model.py` variants for different
  action-parsing/response-API strategies). Shared parsing/formatting logic lives in `models/utils/`
  (e.g. `actions_text.py` vs `actions_toolcall.py` for the two ways an LM output gets turned into
  `extra.actions`). `models/__init__.py` is the factory: `get_model()` resolves a model name/config
  to a class via `_MODEL_CLASS_MAPPING`.
- **`agents/__init__.py`** and **`environments/__init__.py`** follow the same factory pattern
  (`get_agent`/`get_environment` + a `_*_MAPPING` dict of short names to dotted class paths). Adding
  a new implementation means adding a class plus one mapping entry — prefer this over branching
  inside an existing class.
- **Config** (`minisweagent/config/*.yaml`) supplies Jinja2 templates (`system_template`,
  `instance_template`) and default kwargs for the three components; `run/mini.py` shows the
  pattern of merging CLI args over YAML config over defaults via `recursive_merge` /
  `UNSET` sentinel (`utils/serialize.py`). Config file resolution order (first match wins) is in
  `config/get_config_path`: literal path → `$MSWEA_CONFIG_DIR` → built-in `config/` →
  `config/extra/` → `config/benchmarks/`.
- **`run/extra/`** holds more specific/less-core run scripts (mirrors the `environments/extra/` and
  the `_*` "extra" convention used elsewhere); **`run/benchmarks/`** holds batch-inference harnesses
  (SWE-bench, ProgramBench) built on top of the same three-component wiring, run in parallel across
  many task instances.
- **`run/utilities/inspector.py`** is the Textual-based trajectory browser for saved `.traj.json`
  files (format versioned via `"trajectory_format"` in `DefaultAgent.serialize()`).

When adding a feature, prefer creating a new variant of one of the four components (agent, env,
model, run script) over adding configuration branches/complexity to an existing one — this mirrors
how the existing `extra/` subpackages and `_textbased`/`_response` model suffixes are organized.

## Quant Trading Harness (planned project, design-only)

`design/quant-trading-harness-architecture.md` is the design doc for a **separate project being
built on top of this codebase** (branch `quanta_trade`): an offline/online quant trading harness
for crypto (BTC/USDT, 1h bars). Implementation lives in the separate top-level package
`src/quantharness/` (tests in `tests/quantharness/`, run with `pytest tests/quantharness`); it
depends on the `quant` extra (`pip install -e '.[quant]'`, pandas + numpy). Stage 0 (shared
feature library, spec in `design/stage0-feature-library.md`) is implemented; Stage 1+ is not.
Read the full design doc before doing any work related to it; do not re-derive its plan from
memory since it may be updated. What follows is only a pointer/summary, not a substitute for
reading it.

Stage 0 invariants baked into `quantharness` (don't break them):
- Bars are keyed by **close time** (`ts` = `open_time + 1h`, UTC); a feature dated `ts` only sees
  bars with index <= `ts`.
- `features._core` is the single implementation for both `compute_features` (batch/offline) and
  `compute_features_at` (single-bar/online); it truncates to the trailing `LOOKBACK` bars itself.
  Never add a vectorized (`rolling()`) fast path — it breaks bit-exact offline/online parity.
- `data.load_ohlcv` uses `float_precision="round_trip"`; the default CSV parser is not bit-exact.
- Gap policy is fixed in `data.normalize_ohlcv`: missing hourly bars are filled at the previous
  close with zero volume and `is_gap=True`; off-grid timestamps raise.

**Non-negotiable constraints from the doc** (any implementation work must preserve these, not just
follow them by convention):

- Strategies are pure functions: `generate_signal(features: dict) -> float`, no IO/network/randomness/
  wall-clock reads. Enforced by static analysis + a determinism test (same input run twice, bit-identical),
  not by convention.
- The risk engine and execution engine sit **outside** anything the agent can write to or the
  agent's container mounts — this is filesystem-permission-enforced, not a coding-style rule.
- Promotion gate criteria are all **relative to buy-and-hold**, never absolute thresholds (an
  absolute Sharpe bar would let "always long" trivially pass).
- Data is split by time (train/validation-OOS/final-holdout) with the split enforced via filesystem
  mount permissions per stage, not just directory convention; validation queries are capped by a
  fixed total budget per run.
- The staged MVP (Stage 0 → Stage 6b) is sequential and each stage's acceptance criteria gate the
  next — don't skip ahead to later-stage work (e.g. online/execution engine, testnet integration)
  before the offline research harness and promotion gate (Stages 0–3) exist and pass their
  synthetic-data acceptance tests.
- Offline reuses the existing `minisweagent/models`, `minisweagent/agents`, and `minisweagent/environments`
  abstractions as-is (single agent for now, plain `DockerEnvironment` with bash only — isolation is
  done via mount permissions, not custom tool allowlisting); only `minisweagent/run/*.py` entry
  points, the feature/backtest/promotion-gate libraries, and the online-side services are new.
