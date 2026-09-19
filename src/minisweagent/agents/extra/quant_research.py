"""DefaultAgent plus one hook: stop once the promotion gate's validation budget is gone.

See design/stage3-research-harness.md (R6). The hook only reads the gate's own stdout as it
appears in the observation; the run-level verdict never trusts anything the agent saw.
"""

import json

from minisweagent import Environment, Model
from minisweagent.agents.default import AgentConfig, DefaultAgent
from minisweagent.exceptions import ContextExhausted, QueryBudgetExhausted


class QuantResearchAgentConfig(AgentConfig):
    gate_score_marker: str = "gate score"
    """Actions containing this substring are treated as validation queries."""
    num_ctx: int = 0
    """Model context window in tokens (0 = unknown). Ollama truncates the oldest tokens silently once
    it is full, i.e. the task prompt, so the agent stops instead of running blind."""
    context_reserve_tokens: int = 3000
    """Stop when fewer than this many tokens remain: a reply needs room, otherwise the model gets cut
    off and the run ends as RepeatedFormatError instead of the more informative ContextExhausted."""


def _last_json(text: str) -> dict | None:
    for line in reversed(text.strip().splitlines()):
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                return None
    return None


class QuantResearchAgent(DefaultAgent):
    def __init__(self, model: Model, env: Environment, *, config_class: type = QuantResearchAgentConfig, **kwargs):
        super().__init__(model, env, config_class=config_class, **kwargs)
        self.gate_passed = False

    def query(self) -> dict:
        message = super().query()
        prompt_tokens = ((message.get("extra", {}).get("response") or {}).get("usage") or {}).get("prompt_tokens", 0)
        if self.config.num_ctx and prompt_tokens + self.config.context_reserve_tokens >= self.config.num_ctx:
            raise ContextExhausted(
                {
                    "role": "exit",
                    "content": f"ContextExhausted: prompt_tokens={prompt_tokens} num_ctx={self.config.num_ctx}",
                    "extra": {"exit_status": "ContextExhausted", "submission": ""},
                }
            )
        return message

    def execute_actions(self, message: dict) -> list[dict]:
        actions = message.get("extra", {}).get("actions", [])
        outputs = [self.env.execute(action) for action in actions]
        for action, output in zip(actions, outputs):
            if self.config.gate_score_marker not in action.get("command", ""):
                continue
            if (payload := _last_json(output.get("output", ""))) is None:
                continue
            self.gate_passed |= payload.get("pass") is True
            if payload.get("budget_remaining") == 0 and not self.gate_passed:
                self.add_messages(*self.model.format_observation_messages(message, outputs, self.get_template_vars()))
                raise QueryBudgetExhausted(
                    {
                        "role": "exit",
                        "content": "QueryBudgetExhausted",
                        "extra": {"exit_status": "QueryBudgetExhausted", "submission": ""},
                    }
                )
        return self.add_messages(*self.model.format_observation_messages(message, outputs, self.get_template_vars()))
