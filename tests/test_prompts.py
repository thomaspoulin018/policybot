from pathlib import Path

import pytest
from pydantic import ValidationError

from policybot.config import LLM_TASKS
from policybot.prompts import load_prompts


PROMPTS_PATH = Path(__file__).resolve().parents[1] / "configs" / "prompts.yaml"


def test_repository_catalog_declares_every_llm_task():
    catalog = load_prompts(PROMPTS_PATH, env={})

    assert set(type(catalog.prompts).model_fields) == set(LLM_TASKS)
    for task in LLM_TASKS:
        prompt = getattr(catalog.prompts, task)
        assert prompt.system.strip()
        assert prompt.user_template.strip()


def test_prompt_variables_are_rendered_from_the_catalog():
    catalog = load_prompts(PROMPTS_PATH, env={})
    prompt = catalog.prompts.form_suggestions

    system = prompt.render_system(
        question="Quelles données?",
        existing="Données publiques",
        free_text="Dossiers étudiants",
    )
    user = prompt.render_user(free_text="Dossiers étudiants")

    assert "Quelles données?" in system
    assert "Données publiques" in system
    assert "Dossiers étudiants" in system
    assert user == "Dossiers étudiants"


def test_missing_prompt_variable_is_rejected():
    catalog = load_prompts(PROMPTS_PATH, env={})

    with pytest.raises(KeyError):
        catalog.prompts.data_classification.render_user()


def test_unknown_prompt_section_is_rejected(tmp_path):
    invalid = tmp_path / "prompts.yaml"
    source = PROMPTS_PATH.read_text(encoding="utf-8")
    invalid.write_text(source + "\n  unknown_task:\n    system: x\n    user_template: y\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        load_prompts(invalid, env={})
