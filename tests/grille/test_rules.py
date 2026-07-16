from policybot.grille.rules import (
    load_rules, evaluate_rules, highest_risk, Rule,
)
from policybot.criteria import USAGE_CRITERIA


def test_load_rules_returns_nonempty():
    rules = load_rules()
    assert len(rules) >= 1
    assert all(isinstance(r, Rule) for r in rules)


def test_training_rule_triggers():
    rules = [Rule(
        id="R-07",
        when={"training_default": ["yes", "unknown"],
              "data_classification": ["Protégé A", "Protégé B", "Protégé C"]},
        then={"risk_level": "Élevé",
              "recommendation": "Autoriser_avec_conditions",
              "conditions": ["Confirmer l'opt-out d'entraînement."]},
    )]
    facts = {"training_default": "yes", "data_classification": "Protégé B"}
    triggered = evaluate_rules(facts, rules)
    assert [r.id for r in triggered] == ["R-07"]


def test_rule_does_not_trigger_when_value_absent():
    rules = [Rule(id="R-07", when={"training_default": ["yes"]}, then={})]
    triggered = evaluate_rules({"training_default": "no"}, rules)
    assert triggered == []


def test_highest_risk_picks_worst():
    assert highest_risk(["Faible", "Élevé", "Modéré"]) == "Élevé"
    assert highest_risk([]) == "Faible"


def test_rules_tagged_with_usage_criteria_use_exact_names():
    valid_criteria = {name for _, name, _ in USAGE_CRITERIA}
    rules = load_rules()
    tagged = [rule for rule in rules if "criterion" in rule.then]
    assert tagged
    for rule in tagged:
        assert rule.then["criterion"] in valid_criteria
        assert "category" in rule.then
