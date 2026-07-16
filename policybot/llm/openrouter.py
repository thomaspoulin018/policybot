import json
import os
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from policybot.config import LLMTask
from policybot.llm.provider import LLMProvider, StructuredModel
from policybot.tracing import (
    extract_llm_usage,
    mask_text,
    record_llm_call_failed,
    record_llm_call_started,
    record_llm_call_succeeded,
    trace_step,
)

_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openai/gpt-5.6-luna"
DEFAULT_REASONING_EFFORT = "low"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 0.0
DEFAULT_TIMEOUT = 60.0


class OpenRouterProvider(LLMProvider):
    """LLM provider backed by OpenRouter's OpenAI-compatible API.

    Uses langchain's ChatOpenAI so every call is traced by LangSmith when the
    LANGCHAIN_TRACING_V2 / LANGCHAIN_API_KEY environment variables are set. When
    tracing is disabled the client behaves like a plain OpenRouter call.

    Configuration normally comes from ``configs/policybot.yaml`` through the
    task router. The OPENROUTER_* environment variables remain supported for
    direct construction and backward compatibility.
    """

    def __init__(self, api_key: str, model: str | None = None,
                 reasoning_effort: str | None = None, timeout: float | None = None,
                 max_tokens: int | None = None,
                 temperature: float | None = None):
        self._model = model or os.getenv("OPENROUTER_MODEL") or DEFAULT_MODEL
        self._reasoning_effort = (
            reasoning_effort
            or os.getenv("OPENROUTER_REASONING_EFFORT")
            or DEFAULT_REASONING_EFFORT
        )
        configured_max_tokens = (max_tokens if max_tokens is not None else int(
            os.getenv("OPENROUTER_MAX_TOKENS", str(DEFAULT_MAX_TOKENS))
        ))
        if configured_max_tokens <= 0:
            raise ValueError("OPENROUTER_MAX_TOKENS must be a positive integer")
        self._max_tokens = configured_max_tokens
        self._temperature = temperature if temperature is not None else float(
            os.getenv("OPENROUTER_TEMPERATURE", str(DEFAULT_TEMPERATURE))
        )
        if not 0.0 <= self._temperature <= 2.0:
            raise ValueError("OPENROUTER_TEMPERATURE must be between 0 and 2")
        self._timeout = timeout if timeout is not None else float(
            os.getenv("OPENROUTER_TIMEOUT", str(DEFAULT_TIMEOUT))
        )
        if self._timeout <= 0:
            raise ValueError("OPENROUTER_TIMEOUT must be positive")
        self._llm = ChatOpenAI(
            model=self._model,
            api_key=api_key,
            base_url=_BASE_URL,
            timeout=self._timeout,
            reasoning_effort=self._reasoning_effort,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
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

    def _record_response_usage(self, response, extra: dict) -> None:
        usage = extract_llm_usage(response)
        extra.update(usage)
        record_llm_call_succeeded(usage)

    def _chat(self, system: str, user: str, json_mode: bool,
              run_name: str | None, tags: list[str] | None,
              task: LLMTask | None) -> str:
        with trace_step(None, "llm_call", model=self._model, json_mode=json_mode,
                         task=task, system=mask_text(system), user=mask_text(user)) as extra:
            llm = self._llm
            if json_mode:
                llm = llm.bind(response_format={"type": "json_object"})
            record_llm_call_started()
            try:
                resp = llm.invoke(
                    self._messages(system, user),
                    config=self._config(run_name, tags),
                )
            except Exception:
                record_llm_call_failed()
                raise
            extra["response"] = mask_text(resp.content)
            self._record_response_usage(resp, extra)
            return resp.content

    def complete_json(self, system: str, user: str, *,
                      run_name: str | None = None,
                      tags: list[str] | None = None,
                      task: LLMTask | None = None) -> dict:
        return json.loads(self._chat(system, user, True, run_name, tags, task))

    def complete_structured(self, system: str, user: str,
                            schema: type[StructuredModel], *,
                            run_name: str | None = None,
                            tags: list[str] | None = None,
                            task: LLMTask | None = None) -> StructuredModel:
        with trace_step(None, "llm_call", model=self._model, json_mode=True,
                         structured_schema=schema.__name__,
                         task=task, system=mask_text(system), user=mask_text(user)) as extra:
            # ``include_raw`` preserves the provider response metadata, which is
            # where OpenRouter returns its billed cost and token usage.
            llm = self._llm.with_structured_output(
                schema, method="json_mode", include_raw=True,
            )
            record_llm_call_started()
            try:
                result = llm.invoke(
                    self._messages(system, user),
                    config=self._config(run_name, tags),
                )
            except Exception:
                record_llm_call_failed()
                raise
            if isinstance(result, dict) and "raw" in result:
                resp = result["raw"]
                parsed = result.get("parsed")
            else:
                # Compatibility with older LangChain integrations that do not
                # return the raw response even when requested.
                resp = result
                parsed = result
            model = parsed if isinstance(parsed, schema) else schema.model_validate(parsed)
            extra["response"] = mask_text(model.model_dump_json())
            self._record_response_usage(resp, extra)
            return model

    def draft_text(self, system: str, user: str, *,
                   run_name: str | None = None,
                   tags: list[str] | None = None,
                   task: LLMTask | None = None) -> str:
        return self._chat(system, user, False, run_name, tags, task)
