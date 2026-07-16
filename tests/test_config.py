from pathlib import Path

import pytest
from pydantic import ValidationError

from policybot.config import load_config


CONFIG_PATH = Path(__file__).resolve().parents[1] / "configs" / "policybot.yaml"


def test_repository_config_declares_all_llm_tasks_and_cache_mode():
    config = load_config(CONFIG_PATH, env={})

    assert config.llm.provider == "openrouter"
    assert config.llm.tasks.data_classification.model
    assert config.llm.tasks.tool_type_detection.model
    assert config.llm.tasks.mode_detection.model
    assert config.llm.tasks.form_suggestions.model
    assert config.llm.tasks.contract_extraction.model
    assert config.cache.arp.mode == "read_write"


def test_environment_overrides_global_then_task_specific_values():
    config = load_config(CONFIG_PATH, env={
        "OPENROUTER_MODEL": "global/model",
        "OPENROUTER_MAX_TOKENS": "3000",
        "POLICYBOT_LLM_DATA_CLASSIFICATION_MODEL": "classification/model",
        "POLICYBOT_LLM_DATA_CLASSIFICATION_TEMPERATURE": "0.4",
        "POLICYBOT_ARP_CACHE_MODE": "read_only",
    })

    assert config.llm.tasks.mode_detection.model == "global/model"
    assert config.llm.tasks.mode_detection.max_tokens == 3000
    assert config.llm.tasks.data_classification.model == "classification/model"
    assert config.llm.tasks.data_classification.temperature == 0.4
    assert config.cache.arp.mode == "read_only"


def test_invalid_environment_override_is_rejected():
    with pytest.raises(ValidationError):
        load_config(CONFIG_PATH, env={"POLICYBOT_ARP_CACHE_MODE": "sometimes"})
