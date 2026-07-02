# tests/classify/test_data_classifier.py
from policybot.llm.fake import FakeLLMProvider
from policybot.classify.data_classifier import classify_data


def _llm(signals):
    return FakeLLMProvider(json_responses=[signals])


def test_public_data_is_non_classifie():
    llm = _llm({"already_public": True, "contains_personal_info": False,
                "strategic_sensitive": False, "internal_nonpublic": False,
                "highly_sensitive_secret": False, "confidence": 0.9})
    out = classify_data("statistiques publiées", llm)
    assert out.data_classification == "Non classifié"
    assert out.rens_personnels is False
    assert out.needs_officer_confirmation is False


def test_personal_info_is_protege_b():
    llm = _llm({"already_public": False, "contains_personal_info": True,
                "strategic_sensitive": False, "internal_nonpublic": True,
                "highly_sensitive_secret": False, "confidence": 0.9})
    out = classify_data("liste de noms et numéros de dossier de citoyens", llm)
    assert out.data_classification == "Protégé B"
    assert out.rens_personnels is True


def test_internal_nonpublic_is_protege_a():
    llm = _llm({"already_public": False, "contains_personal_info": False,
                "strategic_sensitive": False, "internal_nonpublic": True,
                "highly_sensitive_secret": False, "confidence": 0.9})
    out = classify_data("notes internes de travail", llm)
    assert out.data_classification == "Protégé A"


def test_low_confidence_flags_officer_confirmation():
    llm = _llm({"already_public": True, "contains_personal_info": False,
                "strategic_sensitive": False, "internal_nonpublic": False,
                "highly_sensitive_secret": False, "confidence": 0.4})
    out = classify_data("quelque chose", llm)
    assert out.needs_officer_confirmation is True


def test_unknown_defaults_conservatively_to_protege_a():
    llm = _llm({"already_public": False, "contains_personal_info": False,
                "strategic_sensitive": False, "internal_nonpublic": False,
                "highly_sensitive_secret": False, "confidence": 0.8})
    out = classify_data("ambigu", llm)
    assert out.data_classification == "Protégé A"
    assert out.needs_officer_confirmation is True
