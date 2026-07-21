# policybot/grille/engine.py
from __future__ import annotations
from policybot.models import (
    Usage, ContractFacts, IagType, GlobalResult, RiskFactor,
    QualificationProfile,
)
from policybot.criteria import USAGE_CRITERIA
from policybot.grille.matrix import evaluate_matrix
from policybot.grille.rules import Rule, load_rules, evaluate_rules, highest_risk

_REC_ORDER = {"Autoriser": 0, "Autoriser_avec_conditions": 1, "Escalader": 2, "Refuser": 3}
_LETTER_FROM_LEVEL = {"Faible": "F", "Modéré": "M", "Élevé": "E", "Critique": "C"}
_LETTER_ORDER = {"F": 0, "M": 1, "E": 2, "C": 3}
_LEVEL_FROM_LETTER = {"F": "Faible", "M": "Modéré", "E": "Élevé", "C": "Critique"}
_BASE_RISK_BY_CLASSIFICATION = {
    "Non classifié": "F",
    "Protégé A": "F",
    "Protégé B": "M",
    "Protégé C": "E",
}


def _build_partie_b(usage: Usage, triggered: list[Rule]) -> list[RiskFactor]:
    by_criterion: dict[str, list[Rule]] = {}
    for rule in triggered:
        criterion = rule.then.get("criterion")
        if criterion is None:
            continue
        by_criterion.setdefault(criterion, []).append(rule)

    rows: list[RiskFactor] = []
    for category, criterion, _description in USAGE_CRITERIA:
        if criterion == "Fuite de données confidentielles":
            letter = _BASE_RISK_BY_CLASSIFICATION[usage.data_classification]
            observations = (
                f"Coté {_LEVEL_FROM_LETTER[letter]} car les données sont classées "
                f"{usage.data_classification}."
            )
        else:
            criterion_rules = by_criterion.get(criterion, [])
            letters = [
                _LETTER_FROM_LEVEL[rule.then["risk_level"]]
                if rule.then.get("risk_level") else "M"
                for rule in criterion_rules
            ]
            letter = max(letters, key=lambda value: _LETTER_ORDER[value]) if letters else "F"
            if criterion_rules:
                conditions = [
                    condition
                    for rule in criterion_rules
                    for condition in rule.then.get("conditions", [])
                ]
                rule_ids = ", ".join(rule.id for rule in criterion_rules)
                reason = " | ".join(conditions) or "Règle de la grille déclenchée."
                observations = (
                    f"Coté {_LEVEL_FROM_LETTER[letter]} car {reason} ({rule_ids})"
                )
            else:
                observations = (
                    "Aucune règle de la grille déclenchée — risque inhérent de base "
                    "(Faible)."
                )
        rows.append(RiskFactor(
            category=category,
            criterion=criterion,
            inherent=letter,
            residual=None,
            origin="rule",
            observations=observations,
        ))
    return rows


def evaluate_usage(
    usage: Usage,
    contract_facts: ContractFacts,
    iag_type: IagType,
    rules: list[Rule] | None = None,
    qualification: QualificationProfile | None = None,
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
        "result_used_for_decision": "Prise de décision" in out.result_use,
        "result_published": "Publication" in out.result_use,
        "api_integration": "api" in out.mode,
        "formation_iag_recue": (
            qualification.formation_iag_recue
            if qualification is not None and qualification.formation_iag_recue is not None
            else "unknown"
        ),
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
