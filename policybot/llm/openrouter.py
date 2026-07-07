import json
import httpx
from policybot.llm.provider import LLMProvider

_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "google/gemma-4-31b-it",
                 timeout: float = 60.0):
        self._key = api_key
        self._model = model
        self._client = httpx.Client(timeout=timeout)

    def _chat(self, system: str, user: str, json_mode: bool) -> str:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        resp = self._client.post(
            _URL, headers={"Authorization": f"Bearer {self._key}"}, json=payload
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def complete_json(self, system: str, user: str) -> dict:
        return json.loads(self._chat(system, user, json_mode=True))

    def draft_text(self, system: str, user: str) -> str:
        return self._chat(system, user, json_mode=False)
