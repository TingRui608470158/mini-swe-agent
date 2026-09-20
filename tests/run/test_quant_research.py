import hashlib
import json
import re
import subprocess
import sys

import pytest
import yaml

from minisweagent.agents.extra.quant_research import QuantResearchAgent
from minisweagent.config import builtin_config_dir
from minisweagent.environments.local import LocalEnvironment
from minisweagent.models.test_models import DeterministicModel, make_output
from minisweagent.run.extra.quant_research import PROBES, decide, judge_probes
from quantharness.data import load_ohlcv
from quantharness.features import FEATURE_NAMES
from quantharness.synthetic import SYMBOLS

GOOD = b"def generate_signal(f):\n    return 0.0\n"
GOOD_SHA = hashlib.sha256(GOOD).hexdigest()
CONFIG = yaml.safe_load((builtin_config_dir / "extra" / "quant_research.yaml").read_text(encoding="utf-8"))


def _score(sha: str, passed: bool) -> dict:
    return {"ts": "2026-01-01T00:00:00+00:00", "sha256": sha, "pass": passed, "criteria": {}}


@pytest.mark.parametrize(
    ("exit_status", "strategy", "scores", "remaining", "verdict"),
    [
        ("Submitted", GOOD, [_score(GOOD_SHA, True)], 19, "PASS"),
        ("Submitted", GOOD, [_score(GOOD_SHA, False), _score(GOOD_SHA, True)], 18, "PASS"),
        ("Submitted", None, [_score(GOOD_SHA, True)], 19, "FAIL_UNVERIFIED"),
        ("Submitted", GOOD, [], 20, "FAIL_UNVERIFIED"),
        ("Submitted", b"def generate_signal(f):\n    return 0.5\n", [_score(GOOD_SHA, True)], 19, "FAIL_UNVERIFIED"),
        ("Submitted", GOOD, [_score(GOOD_SHA, True), _score(GOOD_SHA, False)], 18, "FAIL_UNVERIFIED"),
        ("Submitted", GOOD, [_score("other", False)], 0, "FAIL_UNVERIFIED"),
        ("QueryBudgetExhausted", GOOD, [_score(GOOD_SHA, False)], 0, "FAIL_BUDGET"),
        ("LimitsExceeded", GOOD, [_score(GOOD_SHA, False)], 0, "FAIL_BUDGET"),
        ("LimitsExceeded", GOOD, [_score(GOOD_SHA, True)], 0, "FAIL_LIMITS"),
        ("LimitsExceeded", None, [], 20, "FAIL_LIMITS"),
        ("TimeExceeded", None, [], 20, "FAIL_LIMITS"),
        ("RepeatedFormatError", None, [], 20, "FAIL_LIMITS"),
        ("ValueError", None, [], 20, "ERROR"),
        ("", GOOD, [], None, "ERROR"),
    ],
)
def test_verdict_table(exit_status, strategy, scores, remaining, verdict):
    assert decide(exit_status, strategy, scores, remaining) == verdict


def _fake_probe_outputs(**overrides) -> dict[str, dict]:
    good = {
        "agent_user": {"output": "agent\n", "returncode": 0},
        "validation_unreadable": {"output": "Permission denied", "returncode": 1},
        "holdout_absent": {"output": "No such file", "returncode": 2},
        "no_network": {"output": "OSError", "returncode": 1},
        "gate_budget": {"output": '{"budget_remaining": 7}\n', "returncode": 0},
    }
    return good | overrides


def test_probes_fail_closed_on_any_single_breach():
    assert all(judge_probes(_fake_probe_outputs(), 7).values())
    assert set(PROBES) == set(judge_probes(_fake_probe_outputs(), 7))
    breaches = {
        "agent_user": {"output": "root\n", "returncode": 0},
        "validation_unreadable": {"output": "ts,open,...", "returncode": 0},
        "holdout_absent": {"output": "BTCUSDT.csv", "returncode": 0},
        "no_network": {"output": "", "returncode": 0},
        "gate_budget": {"output": '{"budget_remaining": 20}\n', "returncode": 0},
    }
    for name, breach in breaches.items():
        result = judge_probes(_fake_probe_outputs(**{name: breach}), 7)
        assert result[name] is False and sum(result.values()) == len(PROBES) - 1


def _gate_output(remaining: int, passed: bool) -> str:
    return json.dumps({"segment": "validation", "budget_remaining": remaining, "pass": passed})


def _agent(tmp_path, *steps: tuple[str, bool], **config) -> QuantResearchAgent:
    """Each step prints the given text; `marked` steps carry the `gate score` marker in the command."""
    commands = []
    for i, (text, marked) in enumerate(steps):
        (tmp_path / f"{i}.txt").write_text(text)
        commands.append(
            f'"{sys.executable}" -c "import sys; print(open(sys.argv[1]).read())" "{tmp_path / f"{i}.txt"}"'
            + (" gate score" if marked else "")
        )
    return QuantResearchAgent(
        DeterministicModel(outputs=[make_output(f"step {i}", [{"command": c}]) for i, c in enumerate(commands)]),
        LocalEnvironment(),
        system_template="sys",
        instance_template="{{task}}",
        step_limit=len(commands),
        **config,
    )


def test_agent_stops_when_budget_is_gone_without_a_pass(tmp_path):
    agent = _agent(tmp_path, (_gate_output(1, False), True), (_gate_output(0, False), True), ("unreachable", False))
    assert agent.run("t")["exit_status"] == "QueryBudgetExhausted"
    assert agent.messages[-1]["role"] == "exit" and agent.n_calls == 2
    assert "unreachable" not in json.dumps(agent.messages)


def test_agent_keeps_going_after_a_pass_and_ignores_non_gate_output(tmp_path):
    agent = _agent(
        tmp_path, (_gate_output(1, True), True), (_gate_output(0, False), True), (_gate_output(0, False), False)
    )
    assert agent.run("t")["exit_status"] == "LimitsExceeded" and agent.gate_passed is True


def test_agent_ignores_unparseable_gate_output(tmp_path):
    agent = _agent(tmp_path, ("Usage: gate score ...", True))
    assert agent.run("t")["exit_status"] == "LimitsExceeded"


FORBIDDEN = re.compile(
    r"mean.?revers|revert|trend|momentum|reversal|contrarian|autocorrel|AR\(1\)|\bphi\b|copysign|ollama", re.I
)


@pytest.mark.parametrize("action_format", ["toolcall", "textbased"])
def test_prompt_is_data_agnostic_and_complete(action_format):
    agent_config = {k: v for k, v in CONFIG["agent"].items() if k != "agent_class"}
    agent = QuantResearchAgent(
        DeterministicModel(outputs=[]), LocalEnvironment(), system_template="sys", **agent_config
    )
    agent.extra_template_vars |= {"task": "T", "action_format": action_format, "gate_budget": 7}
    text = agent._render_template(agent.config.instance_template)
    assert not FORBIDDEN.search(text), FORBIDDEN.search(text)
    for required in (
        "sudo -n /gate/bin/gate check",
        "sudo -n /gate/bin/gate score",
        "/workspace/strategy.py",
        "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT",
        "7 validation queries",
        "only `math` and `typing`",
        "exactly these three subcommands",
        "Never print raw rows",
    ):
        assert required in text
    assert ("mswea_bash_command" in text) == (action_format == "textbased")
    assert all(f"| {name} " in text for name in FEATURE_NAMES), "feature table drifted from FEATURE_NAMES"


@pytest.mark.parametrize("kind", ["ar1", "regime"])
def test_synthetic_cli_writes_three_distinct_loadable_symbols(tmp_path, kind):
    subprocess.run(
        [sys.executable, "-m", "quantharness.synthetic", str(tmp_path), "--n", "500", "--kind", kind], check=True
    )
    frames = [load_ohlcv(tmp_path / f"{s}.csv") for s in SYMBOLS]
    assert [len(f) for f in frames] == [500, 500, 500]
    assert len({f["close"].iloc[-1] for f in frames}) == 3


def _output_with_usage(prompt_tokens: int) -> dict:
    output = make_output("thinking", [{"command": "echo ok"}])
    output["extra"]["response"] = {"usage": {"prompt_tokens": prompt_tokens}}
    return output


@pytest.mark.parametrize(
    ("num_ctx", "prompt_tokens", "exit_status"),
    [(1000, 950, "ContextExhausted"), (1000, 900, "LimitsExceeded"), (0, 99_999, "LimitsExceeded")],
)
def test_agent_stops_before_the_context_window_silently_truncates(num_ctx, prompt_tokens, exit_status):
    agent = QuantResearchAgent(
        DeterministicModel(outputs=[_output_with_usage(prompt_tokens)]),
        LocalEnvironment(),
        system_template="sys",
        instance_template="{{task}}",
        step_limit=1,
        num_ctx=num_ctx,
        context_reserve_tokens=60,
    )
    assert agent.run("t")["exit_status"] == exit_status
    assert agent.messages[-1]["role"] == "exit"
