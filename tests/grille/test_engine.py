# tests/grille/test_engine.py
from policybot.models import Usage, ContractFacts, QualificationProfile
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
    facts = ContractFacts(
        training_default="yes",
        opt_out_available="yes",
        opt_out_confirmed_enabled="unknown",
    )
    out = evaluate_usage(usage, facts, iag_type="circuit_ferme")
    assert out.matrix_result == "PERMIS"
    assert out.risk_level == "Élevé"
    assert out.verdict == "Autoriser_avec_conditions"
    assert any("opt-out" in c for c in out.conditions)


def test_permis_clean_case_authorises():
    usage = Usage(data_classification="Non classifié")
    out = evaluate_usage(usage, ContractFacts(training_default="no"), iag_type="publique")
    assert out.verdict == "Autoriser"
    assert out.risk_level == "Faible"


def test_partie_b_has_eleven_fixed_criteria():
    from policybot.criteria import USAGE_CRITERIA
    usage = Usage(data_classification="Non classifié")
    out = evaluate_usage(usage, ContractFacts(training_default="no"), iag_type="publique")
    assert len(out.partie_b) == 11
    assert {c.criterion for c in out.partie_b} == {name for _, name, _ in USAGE_CRITERIA}


def test_partie_b_training_criterion_reflects_r07():
    usage = Usage(data_classification="Protégé B")
    facts = ContractFacts(training_default="yes")
    out = evaluate_usage(usage, facts, iag_type="circuit_ferme")
    by_criterion = {c.criterion: c for c in out.partie_b}
    assert by_criterion["Utilisation de données pour entraînement"].inherent == "E"
    assert by_criterion["Utilisation de données pour entraînement"].residual is None
    assert "Aucune garantie active" in by_criterion["Utilisation de données pour entraînement"].observations
    assert by_criterion["Utilisation de données pour entraînement"].observations.endswith("(R-07B)")


def test_partie_b_observations_explain_classification_and_default_risk():
    out = evaluate_usage(
        Usage(data_classification="Protégé B"),
        ContractFacts(training_default="no", data_residency="quebec", sub_processors="disclosed"),
        iag_type="circuit_ferme",
    )

    by_criterion = {factor.criterion: factor for factor in out.partie_b}
    assert by_criterion["Fuite de données confidentielles"].observations == (
        "Coté Modéré car les données sont classées Protégé B."
    )
    assert by_criterion["Compatibilité avec la LAI/PRP"].observations == (
        "Aucune règle de la grille déclenchée — risque inhérent de base (Faible)."
    )


def test_partie_b_observations_combine_rules_and_list_their_ids():
    from policybot.grille.rules import Rule

    rules = [
        Rule(id="R-100", when={}, then={
            "criterion": "Mauvaise classification des données",
            "risk_level": "Modéré",
            "conditions": ["Première condition."],
        }),
        Rule(id="R-101", when={}, then={
            "criterion": "Mauvaise classification des données",
            "risk_level": "Élevé",
            "conditions": ["Deuxième condition."],
        }),
    ]

    out = evaluate_usage(
        Usage(data_classification="Non classifié"), ContractFacts(),
        iag_type="publique", rules=rules,
    )

    factor = next(
        row for row in out.partie_b if row.criterion == "Mauvaise classification des données"
    )
    assert factor.inherent == "E"
    assert factor.observations == (
        "Coté Élevé car Première condition. | Deuxième condition. (R-100, R-101)"
    )


def test_available_opt_out_is_not_treated_as_enabled():
    usage = Usage(data_classification="Protégé A")
    facts = ContractFacts(
        training_default="yes",
        opt_out_available="yes",
        opt_out_confirmed_enabled="unknown",
    )

    out = evaluate_usage(usage, facts, iag_type="circuit_ferme")

    assert out.risk_level == "Élevé"
    assert any("activation n'est pas confirmée" in condition for condition in out.conditions)


def test_confirmed_enabled_opt_out_removes_training_condition():
    usage = Usage(data_classification="Protégé A")
    facts = ContractFacts(
        training_default="yes",
        opt_out_available="yes",
        opt_out_confirmed_enabled="yes",
    )

    out = evaluate_usage(usage, facts, iag_type="circuit_ferme")

    assert not any("opt-out" in condition for condition in out.conditions)


def test_partie_b_base_risk_scales_with_data_classification():
    facts = ContractFacts()
    non_classifie = evaluate_usage(Usage(data_classification="Non classifié"), facts, iag_type="publique")
    protege_c = evaluate_usage(Usage(data_classification="Protégé C"), facts, iag_type="gouvernementale")
    by_nc = {c.criterion: c for c in non_classifie.partie_b}
    by_pc = {c.criterion: c for c in protege_c.partie_b}
    assert by_nc["Fuite de données confidentielles"].inherent == "F"
    assert by_pc["Fuite de données confidentielles"].inherent == "E"


def test_partie_b_fixed_advisories_always_present_with_moderate_risk():
    usage = Usage(data_classification="Non classifié")
    out = evaluate_usage(usage, ContractFacts(training_default="no"), iag_type="publique")
    by_criterion = {c.criterion: c for c in out.partie_b}
    for name in ("Hallucinations et erreurs factuelles", "Biais algorithmiques",
                 "Formation insuffisante du personnel", "Dépendance technologique",
                 "Image et réputation institutionnelle"):
        assert by_criterion[name].inherent == "M"


def test_partie_b_stays_empty_on_interdit():
    usage = Usage(data_classification="Protégé B")
    out = evaluate_usage(usage, ContractFacts(), iag_type="publique")
    assert out.matrix_result == "INTERDIT"
    assert out.partie_b == []


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


def test_facts_dict_contains_only_usage_and_relevant_contract_semantics(monkeypatch):
    captured = {}
    from policybot.grille import engine as engine_module

    original = engine_module.evaluate_rules

    def spy(facts, rules):
        captured.update(facts)
        return original(facts, rules)

    monkeypatch.setattr(engine_module, "evaluate_rules", spy)

    usage = Usage(
        data_classification="Non classifié",
        rens_personnels=True,
        needs_officer_confirmation=True,
        mode=["api"],
        result_use=["Prise de décision", "Publication"],
    )
    facts = ContractFacts(
        training_default="no", opt_out_available="yes",
        opt_out_confirmed_enabled="yes", sub_processors="disclosed",
        data_retention="none", provider_human_access="yes",
        encryption_standard="strong", ip_ownership="customer",
    )
    evaluate_usage(
        usage,
        facts,
        iag_type="publique",
        qualification=QualificationProfile(formation_iag_recue="partielle"),
    )

    assert set(captured.keys()) == {
        "data_classification", "automated_decisions", "training_default",
        "opt_out_available", "opt_out_confirmed_enabled",
        "data_residency", "sub_processors", "data_retention",
        "encryption_standard", "ip_ownership", "rens_personnels",
        "needs_officer_confirmation", "result_used_for_decision",
        "result_published", "api_integration", "formation_iag_recue",
    }
    assert "provider_human_access" not in captured


def test_synthesize_deduplicates_conditions_preserving_order():
    u1 = Usage(data_classification="Non classifié", verdict="Autoriser",
               risk_level="Faible", conditions=["Rappel A", "Rappel B"])
    u2 = Usage(data_classification="Non classifié", verdict="Autoriser",
               risk_level="Faible", conditions=["Rappel B", "Rappel C"])
    g = synthesize([u1, u2])
    assert g.conditions == ["Rappel A", "Rappel B", "Rappel C"]


def test_r21_undisclosed_subprocessors_with_classified_data():
    usage = Usage(data_classification="Protégé A")
    facts = ContractFacts(sub_processors="undisclosed", training_default="no")
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


def test_provider_human_access_does_not_control_internal_supervision():
    usage = Usage(
        data_classification="Protégé A", rens_personnels=True,
        automated_decisions=False,
    )
    facts = ContractFacts(provider_human_access="no")

    out = evaluate_usage(usage, facts, iag_type="circuit_ferme")

    assert not any("supervision humaine" in c.lower() for c in out.conditions)


def test_internal_supervision_is_derived_from_usage():
    usage = Usage(data_classification="Protégé A", automated_decisions=True)
    facts = ContractFacts(provider_human_access="yes")

    out = evaluate_usage(usage, facts, iag_type="circuit_ferme")

    assert out.risk_level == "Élevé"
    assert any("supervision humaine" in c.lower() for c in out.conditions)


def test_r24_personal_info_hosted_outside_quebec_escalates():
    usage = Usage(data_classification="Protégé A", rens_personnels=True)
    facts = ContractFacts(data_residency="us")
    out = evaluate_usage(usage, facts, iag_type="circuit_ferme")
    assert out.verdict == "Escalader"
    assert any("lai/prp" in c.lower() for c in out.conditions)


def test_r24_eu_is_explicitly_outside_quebec():
    usage = Usage(data_classification="Protégé A", rens_personnels=True)
    facts = ContractFacts(data_residency="eu")

    out = evaluate_usage(usage, facts, iag_type="circuit_ferme")

    assert out.verdict == "Escalader"
    assert any("lai/prp" in c.lower() for c in out.conditions)


def test_r24_does_not_trigger_when_residency_is_quebec():
    usage = Usage(data_classification="Protégé A", rens_personnels=True)
    facts = ContractFacts(data_residency="quebec")
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
    facts = ContractFacts(encryption_standard="none", training_default="no",
                          data_retention="limited", sub_processors="disclosed")
    out = evaluate_usage(usage, facts, iag_type="gouvernementale")
    assert out.risk_level == "Modéré"
    assert any("chiffrement" in c.lower() for c in out.conditions)


def test_r26_does_not_trigger_with_strong_encryption():
    usage = Usage(data_classification="Protégé C")
    facts = ContractFacts(encryption_standard="strong", training_default="no",
                          data_retention="limited", sub_processors="disclosed")
    out = evaluate_usage(usage, facts, iag_type="gouvernementale")
    assert not any("chiffrement" in c.lower() for c in out.conditions)


def test_r26_partial_encryption_triggers():
    usage = Usage(data_classification="Protégé C")
    facts = ContractFacts(encryption_standard="partial", training_default="no",
                          data_retention="limited", sub_processors="disclosed")
    out = evaluate_usage(usage, facts, iag_type="gouvernementale")
    assert out.risk_level == "Modéré"
    assert any("chiffrement" in c.lower() for c in out.conditions)


def test_r27_unclear_ip_ownership_triggers():
    usage = Usage(data_classification="Protégé A")
    facts = ContractFacts(ip_ownership="vendor", training_default="no",
                          data_residency="quebec", sub_processors="disclosed",
                          encryption_standard="strong")
    out = evaluate_usage(usage, facts, iag_type="circuit_ferme")
    assert out.risk_level == "Modéré"
    assert any("propriété intellectuelle" in c.lower() for c in out.conditions)


def test_r27_does_not_trigger_when_customer_owns_ip():
    usage = Usage(data_classification="Protégé A")
    facts = ContractFacts(ip_ownership="customer", training_default="no",
                          data_residency="quebec", sub_processors="disclosed",
                          encryption_standard="strong")
    out = evaluate_usage(usage, facts, iag_type="circuit_ferme")
    assert not any("propriété intellectuelle" in c.lower() for c in out.conditions)


def test_r27_does_not_trigger_for_non_classified_data():
    usage = Usage(data_classification="Non classifié")
    facts = ContractFacts(ip_ownership="unknown")
    out = evaluate_usage(usage, facts, iag_type="publique")
    assert not any("propriété intellectuelle" in c.lower() for c in out.conditions)


def test_fixed_advisories_always_present_and_dont_affect_verdict():
    usage = Usage(data_classification="Non classifié")
    out = evaluate_usage(usage, ContractFacts(training_default="no"), iag_type="publique")
    assert out.verdict == "Autoriser"
    assert out.risk_level == "Faible"
    joined = " ".join(out.conditions).lower()
    for keyword in ("hallucination", "biais", "formation", "dépendance", "réputation"):
        assert keyword in joined


def test_personal_information_in_quebec_requires_lai_prp_controls():
    usage = Usage(data_classification="Protégé A", rens_personnels=True)
    facts = ContractFacts(
        training_default="no",
        data_residency="quebec",
        sub_processors="disclosed",
        encryption_standard="strong",
    )

    out = evaluate_usage(usage, facts, iag_type="circuit_ferme")

    factor = next(
        row for row in out.partie_b if row.criterion == "Compatibilité avec la LAI/PRP"
    )
    assert factor.inherent == "M"
    assert out.verdict == "Autoriser_avec_conditions"
    assert any("éfvp-r" in condition.lower() for condition in out.conditions)


def test_decision_support_strengthens_ethics_rules():
    usage = Usage(
        data_classification="Non classifié",
        result_use=["Prise de décision"],
    )

    out = evaluate_usage(
        usage,
        ContractFacts(training_default="no"),
        iag_type="publique",
    )

    by_criterion = {factor.criterion: factor for factor in out.partie_b}
    assert by_criterion["Hallucinations et erreurs factuelles"].inherent == "E"
    assert by_criterion["Biais algorithmiques"].inherent == "E"
    assert by_criterion["Supervision humaine insuffisante"].inherent == "E"
    assert out.verdict == "Autoriser_avec_conditions"


def test_publication_strengthens_output_and_reputation_rules():
    usage = Usage(
        data_classification="Non classifié",
        result_use=["Publication"],
    )

    out = evaluate_usage(
        usage,
        ContractFacts(training_default="no"),
        iag_type="publique",
    )

    by_criterion = {factor.criterion: factor for factor in out.partie_b}
    assert by_criterion["Hallucinations et erreurs factuelles"].inherent == "M"
    assert by_criterion["Propriété intellectuelle du contenu généré"].inherent == "M"
    assert by_criterion["Image et réputation institutionnelle"].inherent == "M"
    assert out.verdict == "Autoriser_avec_conditions"


def test_missing_iag_training_requires_training_before_use():
    usage = Usage(data_classification="Non classifié")

    out = evaluate_usage(
        usage,
        ContractFacts(training_default="no"),
        iag_type="publique",
        qualification=QualificationProfile(formation_iag_recue="aucune"),
    )

    factor = next(
        row for row in out.partie_b if row.criterion == "Formation insuffisante du personnel"
    )
    assert factor.inherent == "E"
    assert out.verdict == "Autoriser_avec_conditions"
    assert any("formation préalable" in condition.lower() for condition in out.conditions)


def test_partial_iag_training_requires_completion_before_deployment():
    usage = Usage(data_classification="Non classifié")

    out = evaluate_usage(
        usage,
        ContractFacts(training_default="no"),
        iag_type="publique",
        qualification=QualificationProfile(formation_iag_recue="partielle"),
    )

    factor = next(
        row for row in out.partie_b if row.criterion == "Formation insuffisante du personnel"
    )
    assert factor.inherent == "M"
    assert out.verdict == "Autoriser_avec_conditions"
    assert any("compléter les modules" in condition.lower() for condition in out.conditions)


def test_api_integration_requires_dependency_controls():
    usage = Usage(data_classification="Non classifié", mode=["api"])

    out = evaluate_usage(
        usage,
        ContractFacts(training_default="no"),
        iag_type="publique",
    )

    factor = next(
        row for row in out.partie_b if row.criterion == "Dépendance technologique"
    )
    assert factor.inherent == "M"
    assert out.verdict == "Autoriser_avec_conditions"
    assert any("plan de continuité" in condition.lower() for condition in out.conditions)
