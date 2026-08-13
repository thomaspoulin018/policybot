from pathlib import Path

import pytest
from pydantic import ValidationError

from policybot.config import load_config


CONFIG_PATH = Path(__file__).resolve().parents[1] / "configs" / "policybot.yaml"


def test_repository_config_declares_all_llm_tasks():
    config = load_config(CONFIG_PATH, env={})

    assert config.llm.provider == "openrouter"
    assert config.llm.tasks.data_classification.model


def test_environment_overrides_global_then_task_specific_values():
    config = load_config(CONFIG_PATH, env={
        "OPENROUTER_MODEL": "global/model",
        "OPENROUTER_MAX_TOKENS": "3000",
        "POLICYBOT_LLM_DATA_CLASSIFICATION_MODEL": "classification/model",
        "POLICYBOT_LLM_DATA_CLASSIFICATION_TEMPERATURE": "0.4",
    })

    # L'override specifique a la tache l'emporte sur l'override global.
    assert config.llm.tasks.data_classification.max_tokens == 3000
    assert config.llm.tasks.data_classification.model == "classification/model"
    assert config.llm.tasks.data_classification.temperature == 0.4


def test_invalid_environment_override_is_rejected():
    with pytest.raises(ValidationError):
        load_config(CONFIG_PATH, env={"OPENROUTER_TEMPERATURE": "12"})


def test_unknown_configuration_section_is_rejected(tmp_path):
    """`extra="forbid"` fait échouer un YAML qui garde une section retirée,
    par exemple l'ancien bloc `cache` du temps où PolicyBot cachait les ARP."""
    config_path = tmp_path / "policybot.yaml"
    config_path.write_text(
        CONFIG_PATH.read_text(encoding="utf-8") + "\ncache:\n  arp:\n    mode: refresh\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_config(config_path, env={})
