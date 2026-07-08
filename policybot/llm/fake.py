from policybot.llm.provider import LLMProvider
from policybot.tracing import trace_step, mask_text


class FakeLLMProvider(LLMProvider):
    def __init__(self, json_responses=None, text_responses=None):
        self._json = list(json_responses or [])
        self._text = list(text_responses or [])
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str, *,
                      run_name: str | None = None,
                      tags: list[str] | None = None) -> dict:
        with trace_step(None, "llm_call", model="fake", json_mode=True,
                         system=mask_text(system), user=mask_text(user)):
            self.calls.append((system, user))
            return self._json.pop(0)

    def draft_text(self, system: str, user: str, *,
                   run_name: str | None = None,
                   tags: list[str] | None = None) -> str:
        with trace_step(None, "llm_call", model="fake", json_mode=False,
                         system=mask_text(system), user=mask_text(user)):
            self.calls.append((system, user))
            return self._text.pop(0)
