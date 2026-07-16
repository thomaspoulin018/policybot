from policybot.llm.fake import FakeLLMProvider
from policybot.models import QuestionSpec, QuestionOption
from policybot.web.ai_assist import (
    guess_tool_type, guess_mode, suggest_options,
    IAG_TYPE_LABELS, LABEL_TO_IAG_TYPE,
)


def test_guess_tool_type_returns_valid_iag_type():
    llm = FakeLLMProvider(json_responses=[{"iag_type_guess": "publique", "confidence": 0.8}])
    assert guess_tool_type("Notion AI", llm) == "publique"
    assert llm.tasks == ["tool_type_detection"]


def test_guess_tool_type_returns_none_on_invalid_guess():
    llm = FakeLLMProvider(json_responses=[{"iag_type_guess": "n'importe quoi", "confidence": 0.1}])
    assert guess_tool_type("OutilBizarre", llm) is None


def test_guess_mode_returns_api_when_llm_says_so():
    llm = FakeLLMProvider(json_responses=[{"mode_guess": "api", "confidence": 0.7}])
    assert guess_mode("Intégré à notre CRM via un connecteur", llm) == "api"
    assert llm.tasks == ["mode_detection"]


def test_guess_mode_defaults_to_prompt_on_invalid_guess():
    llm = FakeLLMProvider(json_responses=[{"mode_guess": "autre chose", "confidence": 0.2}])
    assert guess_mode("Je tape mes questions", llm) == "prompt"


def test_suggest_options_returns_new_options_from_llm():
    question = QuestionSpec(
        id="data_description", header="h", question="q",
        options=[QuestionOption(label="Info déjà publique")],
    )
    llm = FakeLLMProvider(json_responses=[{"options": [
        {"label": "Renseignements personnels d'étudiants", "description": "Courriels, notes"},
        {"label": "Correspondance nominative", "description": ""},
    ]}])
    result = suggest_options(question, "des courriels d'étudiants", llm)
    assert [o.label for o in result] == [
        "Renseignements personnels d'étudiants", "Correspondance nominative",
    ]
    assert result[0].description == "Courriels, notes"
    assert llm.tasks == ["form_suggestions"]


def test_suggest_options_filters_out_duplicates_of_existing_options():
    question = QuestionSpec(
        id="data_description", header="h", question="q",
        options=[QuestionOption(label="Info déjà publique")],
    )
    llm = FakeLLMProvider(json_responses=[{"options": [
        {"label": "Info déjà publique", "description": "déjà là"},
        {"label": "Nouvelle option", "description": ""},
    ]}])
    result = suggest_options(question, "texte", llm)
    assert [o.label for o in result] == ["Nouvelle option"]


def test_iag_type_label_maps_are_consistent():
    assert LABEL_TO_IAG_TYPE[IAG_TYPE_LABELS["publique"]] == "publique"
