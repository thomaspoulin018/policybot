from policybot.llm.provider import LLMProvider


class FakeLLMProvider(LLMProvider):
    def __init__(self, json_responses=None, text_responses=None):
        self._json = list(json_responses or [])
        self._text = list(text_responses or [])
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str, *,
                      run_name: str | None = None,
                      tags: list[str] | None = None) -> dict:
        self.calls.append((system, user))
        return self._json.pop(0)

    def draft_text(self, system: str, user: str, *,
                   run_name: str | None = None,
                   tags: list[str] | None = None) -> str:
        self.calls.append((system, user))
        return self._text.pop(0)
