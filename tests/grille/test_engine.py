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


def test_facts_dict_includes_all_eleven_keys(monkeypatch):
    captured = {}
    from policybot.grille import engine as engine_module

    original = engine_module.evaluate_rules

    def spy(facts, rules):
        captured.update(facts)
        return original(facts, rules)

    monkeypatch.setattr(engine_module, "evaluate_rules", spy)

    usage = Usage(data_classification="Non classifié", rens_personnels=True,
                  needs_officer_confirmation=True)
    facts = ContractFacts(sub_processors="disclosed", data_retention="none",
                           human_review="yes", encryption_standard="strong",
                           ip_ownership="customer")
    evaluate_usage(usage, facts, iag_type="publique")

    assert set(captured.keys()) == {
        "data_classification", "automated_decisions", "trains_on_input",
        "data_residency", "sub_processors", "data_retention", "human_review",
        "encryption_standard", "ip_ownership", "rens_personnels",
        "needs_officer_confirmation",
    }


def test_synthesize_deduplicates_conditions_preserving_order():
    u1 = Usage(data_classification="Non classifié", verdict="Autoriser",
               risk_level="Faible", conditions=["Rappel A", "Rappel B"])
    u2 = Usage(data_classification="Non classifié", verdict="Autoriser",
               risk_level="Faible", conditions=["Rappel B", "Rappel C"])
    g = synthesize([u1, u2])
    assert g.conditions == ["Rappel A", "Rappel B", "Rappel C"]


def test_r21_undisclosed_subprocessors_with_classified_data():
    usage = Usage(data_classification="Protégé A")
    facts = ContractFacts(sub_processors="undisclosed", trains_on_input="no")
    out = evaluate_usage(usage, facts, iag_type="circuit_ferme")
    assert out.risk_level == "Modéré"
    assert any("sous-traitants" in c for c in out.conditions)


def test_r21_does_not_trigger_when_subprocessors_disclosed():
    usage = Usage(data_classification="Protégé A")
    facts = ContractFacts(sub_processors="disclosed")
    out = evaluate_usage(usage, facts, iag_type="circuit_ferme")
    assert not any("sous-traitants" in c for c in out.conditions)


def test_r22_indefinite_retention_with_protege_b():
    usage = Usage(data_classification="Protégé B")
    facts = ContractFacts(data_retention="indefinite")
    out = evaluate_usage(usage, facts, iag_type="circuit_ferme")
    assert out.risk_level == "Élevé"
    assert any("conservation" in c.lower() for c in out.conditions)


def test_r22_does_not_trigger_when_retention_is_limited():
    usage = Usage(data_classification="Protégé B")
    facts = ContractFacts(data_retention="limited")
    out = evaluate_usage(usage, facts, iag_type="circuit_ferme")
    assert not any("conservation" in c.lower() for c in out.conditions)


def test_r23_no_human_review_with_personal_info():
    usage = Usage(data_classification="Protégé A", rens_personnels=True)
    facts = ContractFacts(human_review="no")
    out = evaluate_usage(usage, facts, iag_type="circuit_ferme")
    assert out.risk_level == "Élevé"
    assert any("révision humaine" in c.lower() for c in out.conditions)


def test_r23_does_not_trigger_without_personal_info():
    usage = Usage(data_classification="Protégé A", rens_personnels=False)
    facts = ContractFacts(human_review="no")
    out = evaluate_usage(usage, facts, iag_type="circuit_ferme")
    assert not any("révision humaine" in c.lower() for c in out.conditions)


def test_r24_personal_info_hosted_outside_quebec_escalates():
    usage = Usage(data_classification="Protégé A", rens_personnels=True)
    facts = ContractFacts(data_residency="us")
    out = evaluate_usage(usage, facts, iag_type="circuit_ferme")
    assert out.verdict == "Escalader"
    assert any("lai/prp" in c.lower() for c in out.conditions)


def test_r24_does_not_trigger_when_residency_is_canada():
    usage = Usage(data_classification="Protégé A", rens_personnels=True)
    facts = ContractFacts(data_residency="canada")
    out = evaluate_usage(usage, facts, iag_type="circuit_ferme")
    assert not any("lai/prp" in c.lower() for c in out.conditions)


def test_r25_needs_officer_confirmation_triggers():
    usage = Usage(data_classification="Non classifié", needs_officer_confirmation=True)
    out = evaluate_usage(usage, ContractFacts(), iag_type="publique")
    assert out.risk_level == "Modéré"
    assert any("agent si" in c.lower() for c in out.conditions)


def test_r25_does_not_trigger_when_confirmation_not_needed():
    usage = Usage(data_classification="Non classifié", needs_officer_confirmation=False)
    out = evaluate_usage(usage, ContractFacts(), iag_type="publique")
    assert not any("agent si" in c.lower() for c in out.conditions)


def test_r26_weak_encryption_with_classified_data():
    usage = Usage(data_classification="Protégé C")
    facts = ContractFacts(encryption_standard="none", trains_on_input="no", data_retention="limited")
    out = evaluate_usage(usage, facts, iag_type="gouvernementale")
    assert out.risk_level == "Modéré"
    assert any("chiffrement" in c.lower() for c in out.conditions)


def test_r26_does_not_trigger_with_strong_encryption():
    usage = Usage(data_classification="Protégé C")
    facts = ContractFacts(encryption_standard="strong", trains_on_input="no", data_retention="limited")
    out = evaluate_usage(usage, facts, iag_type="gouvernementale")
    assert not any("chiffrement" in c.lower() for c in out.conditions)


def test_r27_unclear_ip_ownership_triggers():
    usage = Usage(data_classification="Protégé A")
    facts = ContractFacts(ip_ownership="vendor", trains_on_input="no",
                          data_residency="canada", sub_processors="disclosed",
                          encryption_standard="strong")
    out = evaluate_usage(usage, facts, iag_type="circuit_ferme")
    assert out.risk_level == "Modéré"
    assert any("propriété intellectuelle" in c.lower() for c in out.conditions)


def test_r27_does_not_trigger_when_customer_owns_ip():
    usage = Usage(data_classification="Protégé A")
    facts = ContractFacts(ip_ownership="customer", trains_on_input="no",
                          data_residency="canada", sub_processors="disclosed",
                          encryption_standard="strong")
    out = evaluate_usage(usage, facts, iag_type="circuit_ferme")
    assert not any("propriété intellectuelle" in c.lower() for c in out.conditions)


def test_r27_does_not_trigger_for_non_classified_data():
    usage = Usage(data_classification="Non classifié")
    facts = ContractFacts(ip_ownership="unknown")
    out = evaluate_usage(usage, facts, iag_type="publique")
    assert not any("propriété intellectuelle" in c.lower() for c in out.conditions)
