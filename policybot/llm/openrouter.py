import json
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from policybot.llm.provider import LLMProvider, StructuredModel
from policybot.tracing import trace_step, mask_text

_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider(LLMProvider):
    """LLM provider backed by OpenRouter's OpenAI-compatible API.

    Uses langchain's ChatOpenAI so every call is traced by LangSmith when the
    LANGCHAIN_TRACING_V2 / LANGCHAIN_API_KEY environment variables are set. When
    tracing is disabled the client behaves like a plain OpenRouter call.

    POC provider. Confirm the exact Gemma model slug on OpenRouter.
    """

    def __init__(self, api_key: str, model: str = "google/gemma-4-31b-it",
                 timeout: float = 60.0):
        self._model = model
        # temperature is left unset (None -> not sent) so we defer to the model's
        # default, matching the previous raw-httpx behaviour rather than picking one.
        self._llm = ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=_BASE_URL,
            timeout=timeout,
        )

    def _config(self, run_name: str | None, tags: list[str] | None) -> dict | None:
        config: dict = {}
        if run_name:
            config["run_name"] = run_name
        if tags:
            config["tags"] = tags
        return config or None

    def _messages(self, system: str, user: str) -> list:
        return [SystemMessage(system), HumanMessage(user)]

    def _chat(self, system: str, user: str, json_mode: bool,
              run_name: str | None, tags: list[str] | None) -> str:
        with trace_step(None, "llm_call", model=self._model, json_mode=json_mode,
                         system=mask_text(system), user=mask_text(user)) as extra:
            llm = self._llm
            if json_mode:
                llm = llm.bind(response_format={"type": "json_object"})
            resp = llm.invoke(
                self._messages(system, user),
                config=self._config(run_name, tags),
            )
            extra["response"] = mask_text(resp.content)
            return resp.content

    def complete_json(self, system: str, user: str, *,
                      run_name: str | None = None,
                      tags: list[str] | None = None) -> dict:
        return json.loads(self._chat(system, user, True, run_name, tags))

    def complete_structured(self, system: str, user: str,
                            schema: type[StructuredModel], *,
                            run_name: str | None = None,
                            tags: list[str] | None = None) -> StructuredModel:
        with trace_step(None, "llm_call", model=self._model, json_mode=True,
                         structured_schema=schema.__name__,
                         system=mask_text(system), user=mask_text(user)) as extra:
            llm = self._llm.with_structured_output(schema, method="json_mode")
            resp = llm.invoke(
                self._messages(system, user),
                config=self._config(run_name, tags),
            )
            model = resp if isinstance(resp, schema) else schema.model_validate(resp)
            extra["response"] = mask_text(model.model_dump_json())
            return model

    def draft_text(self, system: str, user: str, *,
                   run_name: str | None = None,
                   tags: list[str] | None = None) -> str:
        return self._chat(system, user, False, run_name, tags)
