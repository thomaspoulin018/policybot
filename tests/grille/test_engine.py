# tests/grille/test_engine.py
from policybot.models import Usage, ContractFacts
from policybot.grille.engine import evaluate_usage, synthesize


def test_interdit_short_circuits_to_refuser():
    usage = Usage(data_classification="Protégé B")
    out = evaluate_usage(usage, ContractFacts(), iag_type="publique")
    assert out.matrix_result == "INTERDIT"
    assert out.verdict == "Refuser"
    # No scoring performed on a hard-refused usage.
    assert out.partie_b == []


def test_permis_with_training_rule_adds_conditions():
    usage = Usage(data_classification="Protégé B")
    facts = ContractFacts(trains_on_input="yes")
    out = evaluate_usage(usage, facts, iag_type="circuit_ferme")
    assert out.matrix_result == "PERMIS"
    assert out.risk_level == "Élevé"
    assert out.verdict == "Autoriser_avec_conditions"
    assert any("opt-out" in c for c in out.conditions)


def test_permis_clean_case_authorises():
    usage = Usage(data_classification="Non classifié")
    out = evaluate_usage(usage, ContractFacts(trains_on_input="no"), iag_type="publique")
    assert out.verdict == "Autoriser"
    assert out.risk_level == "Faible"


def test_efvpr_flag_set_when_personal_info():
    usage = Usage(data_classification="Protégé B", rens_personnels=True)
    out = evaluate_usage(usage, ContractFacts(), iag_type="circuit_ferme")
    assert out.efvpr_required is True


def test_synthesize_takes_worst_and_flags_efvpr():
    u1 = Usage(data_classification="Non classifié", verdict="Autoriser", risk_level="Faible")
    u2 = Usage(data_classification="Protégé B", verdict="Refuser",
               risk_level="Critique", efvpr_required=True)
    g = synthesize([u1, u2])
    assert g.risk_level == "Critique"
    assert g.recommendation == "Refuser"
    assert g.efvpr_required is True
