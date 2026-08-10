from pathlib import Path

import pytest
import yaml

from policybot.intake.formulaire import DEFAULT_FORMULAIRE_PATH


@pytest.fixture
def catalogue_brut() -> dict:
    """Le YAML du catalogue livré, en données modifiables par les tests."""
    return yaml.safe_load(DEFAULT_FORMULAIRE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def ecrire_catalogue(tmp_path: Path):
    def _ecrire(data: dict) -> Path:
        chemin = tmp_path / "formulaire.yaml"
        chemin.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return chemin

    return _ecrire


def question_par_champ(data: dict, champ: str) -> dict:
    for section in data["sections"]:
        for question in section["questions"]:
            if question["champ"] == champ:
                return question
    raise KeyError(champ)


DEMANDE_MINIMALE = {
    "demandeur": "Marie Tremblay",
    "unite": "Direction des services administratifs",
    "tool_name": "ChatGPT",
    "data_free_text": "articles et communiqués déjà publiés sur le Web",
    "usage_description": "Préparer une veille et résumer des sources publiques.",
    "besoin_affaires": "réduire le temps de préparation des réponses récurrentes",
}
