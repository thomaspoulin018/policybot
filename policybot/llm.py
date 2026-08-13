"""Le seul appel modèle de PolicyBot : la classification des données.

Un unique module remplace l'ancien paquet `policybot/llm/` (interface, routeur
par tâche, client LangChain, faux client, enregistreur de diagnostic). Le
pipeline n'appelle qu'une méthode, `complete_json`, à un seul endroit
(`classify/data_classifier.py`), et l'appel HTTP tient dans la bibliothèque
standard : PolicyBot n'a plus besoin de `langchain-openai`.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from abc import ABC, abstractmethod

from policybot.tracing import (
    extract_llm_usage,
    mask_text,
    record_llm_call_failed,
    record_llm_call_started,
    record_llm_call_succeeded,
    trace_step,
)

BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openai/gpt-5.6-luna"
DEFAULT_REASONING_EFFORT = "low"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 0.0
DEFAULT_TIMEOUT = 60.0


class LLMError(RuntimeError):
    """Un appel modèle a échoué ou a renvoyé une réponse inexploitable."""


class LLMProvider(ABC):
    @abstractmethod
    def complete_json(self, system: str, user: str) -> dict:
        """Renvoie l'objet JSON produit par le modèle pour ce prompt."""


class OpenRouterProvider(LLMProvider):
    """Client OpenRouter en JSON mode, par requête HTTP directe.

    La configuration vient normalement de `configs/policybot.yaml`. Les
    variables OPENROUTER_* restent acceptées pour une construction directe.
    """

    def __init__(self, api_key: str, model: str | None = None,
                 reasoning_effort: str | None = None, timeout: float | None = None,
                 max_tokens: int | None = None,
                 temperature: float | None = None):
        self._api_key = api_key
        self._model = model or os.getenv("OPENROUTER_MODEL") or DEFAULT_MODEL
        self._reasoning_effort = (
            reasoning_effort
            or os.getenv("OPENROUTER_REASONING_EFFORT")
            or DEFAULT_REASONING_EFFORT
        )
        self._max_tokens = (max_tokens if max_tokens is not None else int(
            os.getenv("OPENROUTER_MAX_TOKENS", str(DEFAULT_MAX_TOKENS))
        ))
        if self._max_tokens <= 0:
            raise ValueError("OPENROUTER_MAX_TOKENS must be a positive integer")
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

    def _payload(self, system: str, user: str) -> dict:
        return {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "reasoning_effort": self._reasoning_effort,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            # Sans cette demande explicite, OpenRouter ne renvoie pas le coût
            # facturé et `cost_usd` resterait vide dans le journal d'usage.
            "usage": {"include": True},
        }

    def _post(self, payload: dict) -> dict:
        request = urllib.request.Request(
            f"{BASE_URL}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:  # statut != 2xx
            raise LLMError(f"OpenRouter a répondu {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise LLMError("OpenRouter est injoignable") from exc
        return json.loads(body)

    def complete_json(self, system: str, user: str) -> dict:
        with trace_step(None, "llm_call", model=self._model, json_mode=True,
                        system=mask_text(system), user=mask_text(user)) as extra:
            record_llm_call_started()
            try:
                response = self._post(self._payload(system, user))
                content = response["choices"][0]["message"]["content"]
                parsed = json.loads(content)
            except LLMError:
                record_llm_call_failed()
                raise
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                record_llm_call_failed()
                raise LLMError("Réponse OpenRouter inexploitable") from exc
            extra["response"] = mask_text(content)
            usage = extract_llm_usage(response)
            extra.update(usage)
            record_llm_call_succeeded(usage)
            return parsed


class FakeLLMProvider(LLMProvider):
    """Repli hors ligne : sert des réponses préparées, sans réseau."""

    def __init__(self, json_responses=None):
        self._json = list(json_responses or [])
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str) -> dict:
        with trace_step(None, "llm_call", model="fake", json_mode=True,
                        system=mask_text(system), user=mask_text(user)):
            self.calls.append((system, user))
            return self._json.pop(0)
