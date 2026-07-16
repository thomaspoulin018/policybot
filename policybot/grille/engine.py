# policybot/grille/engine.py
from __future__ import annotations
from policybot.models import (
    Usage, ContractFacts, IagType, GlobalResult, RiskFactor,
)
from policybot.criteria import USAGE_CRITERIA
from policybot.grille.matrix import evaluate_matrix
from policybot.grille.rules import Rule, load_rules, evaluate_rules, highest_risk

_REC_ORDER = {"Autoriser": 0, "Autoriser_avec_conditions": 1, "Escalader": 2, "Refuser": 3}
_LETTER_FROM_LEVEL = {"Faible": "F", "Modéré": "M", "Élevé": "E", "Critique": "C"}
_LETTER_ORDER = {"F": 0, "M": 1, "E": 2, "C": 3}
_BASE_RISK_BY_CLASSIFICATION = {
    "Non classifié": "F",
    "Protégé A": "F",
    "Protégé B": "M",
    "Protégé C": "E",
}


def _build_partie_b(usage: Usage, triggered: list[Rule]) -> list[RiskFactor]:
    by_criterion: dict[str, list[str]] = {}
    for rule in triggered:
        criterion = rule.then.get("criterion")
        if criterion is None:
            continue
        level = rule.then.get("risk_level")
        letter = _LETTER_FROM_LEVEL[level] if level else "M"
        by_criterion.setdefault(criterion, []).append(letter)

    rows: list[RiskFactor] = []
    for category, criterion, _description in USAGE_CRITERIA:
        if criterion == "Fuite de données confidentielles":
            letter = _BASE_RISK_BY_CLASSIFICATION[usage.data_classification]
        else:
            letters = by_criterion.get(criterion, [])
            letter = max(letters, key=lambda value: _LETTER_ORDER[value]) if letters else "F"
        rows.append(RiskFactor(
            category=category,
            criterion=criterion,
            inherent=letter,
            residual=letter,
            origin="rule",
        ))
    return rows


def evaluate_usage(
    usage: Usage,
    contract_facts: ContractFacts,
    iag_type: IagType,
    rules: list[Rule] | None = None,
) -> Usage:
    out = usage.model_copy(deep=True)
    out.efvpr_required = out.rens_personnels
    result = evaluate_matrix(out.data_classification, iag_type)
    out.matrix_result = result

    if result == "INTERDIT":
        out.verdict = "Refuser"
        out.risk_level = "Critique"
        out.conditions = ["Combinaison interdite par la matrice MCN "
                          f"({out.data_classification} × IAG {iag_type})."]
        return out

    facts = {
        "data_classification": out.data_classification,
        "automated_decisions": out.automated_decisions,
        "training_default": contract_facts.training_default,
        "opt_out_available": contract_facts.opt_out_available,
        "opt_out_confirmed_enabled": contract_facts.opt_out_confirmed_enabled,
        "data_residency": contract_facts.data_residency,
        "sub_processors": contract_facts.sub_processors,
        "data_retention": contract_facts.data_retention,
        "encryption_standard": contract_facts.encryption_standard,
        "ip_ownership": contract_facts.ip_ownership,
        "rens_personnels": out.rens_personnels,
        "needs_officer_confirmation": out.needs_officer_confirmation,
    }
    triggered = evaluate_rules(facts, rules if rules is not None else load_rules())

    levels = [r.then["risk_level"] for r in triggered if "risk_level" in r.then]
    recs = [r.then["recommendation"] for r in triggered if "recommendation" in r.then]
    conditions: list[str] = []
    for r in triggered:
        conditions.extend(r.then.get("conditions", []))

    out.risk_level = highest_risk(levels)  # "Faible" if none triggered
    out.conditions = conditions
    out.verdict = (
        max(recs, key=lambda rec: _REC_ORDER.get(rec, 0)) if recs else "Autoriser"
    )
    out.partie_b = _build_partie_b(out, triggered)
    return out


def synthesize(usages: list[Usage]) -> GlobalResult:
    levels = [u.risk_level for u in usages if u.risk_level]
    recs = [u.verdict for u in usages if u.verdict]
    conditions: list[str] = []
    for u in usages:
        conditions.extend(u.conditions)
    return GlobalResult(
        risk_level=highest_risk(levels) if levels else "Faible",
        efvpr_required=any(u.efvpr_required for u in usages),
        recommendation=(max(recs, key=lambda r: _REC_ORDER.get(r, 0)) if recs else "Autoriser"),
        conditions=list(dict.fromkeys(conditions)),
    )
