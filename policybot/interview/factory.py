from __future__ import annotations
import os
from pathlib import Path
from policybot.config import CleApiManquante, load_config
from policybot.llm import OpenRouterProvider
from policybot.interview.orchestrator import Interview


def default_interview(config_path: str | Path | None = None) -> Interview:
    """Assemble une Interview prête à évaluer une demande.

    Aucun repli hors ligne : sans `OPENROUTER_API_KEY`, `FakeLLMProvider` était
    installé silencieusement puis levait `IndexError` au premier appel, motif
    affiché « échec » sans indiquer la cause. `FakeLLMProvider` reste réservé
    aux tests, qui construisent `Interview` directement.
    """
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise CleApiManquante("OPENROUTER_API_KEY")
    task_config = load_config(config_path).llm.tasks.data_classification
    return Interview(
        llm=OpenRouterProvider(
            key,
            model=task_config.model,
            reasoning_effort=task_config.reasoning_effort,
            max_tokens=task_config.max_tokens,
            temperature=task_config.temperature,
            timeout=task_config.timeout,
        ),
    )
