# Vraies règles `grille.yaml` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 3 starter `grille.yaml` rules with a realistic set of 12 rules (7 conditional + 5 fixed advisories), wiring up dormant `ContractFacts`/`Usage` fields and two new contract-extraction fields into the rule engine.

**Architecture:** Pure additive changes inside the existing rule-engine pattern (`grille.yaml` as data, `evaluate_usage`/`synthesize` in `policybot/grille/engine.py`). No new modules, no new architecture — this is TDD content work on models, extraction, and rules.

**Tech Stack:** Pydantic v2 (`policybot/models.py`), PyYAML (`policybot/grille/grille.yaml`), `FakeLLMProvider` for extraction tests (already in `policybot/llm/fake.py`).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-07-grille-rules-design.md` — every task in this plan implements a section of it.
- `grille.yaml` remains data, not code — no new Python branching logic in `rules.py`/`engine.py` beyond the `facts` dict expansion and the conditions dedupe.
- Out of scope (do not add): `sso_mfa_support`, `audit_logging`, `incident_response_plan`, `government_license_compatible` — these stay manual, unmodeled.
- Rule IDs continue sequentially from the existing R-07/R-12/R-20: new rules are R-21 through R-32.
- The golden scenario test (`tests/test_golden_scenarios.py`) must still pass unmodified after every task — it hits `INTERDIT`, which short-circuits before any rule evaluation, so it should never need changes.
- Run `pytest -v` (full suite) at the end of every task, not just the task's own test file — regressions in unrelated tests are exactly what a facts-dict/model change can cause silently.

---

## File Structure

```
policybot/
  models.py            Modify: ContractFacts gets 2 new fields (Task 1)
  contract/arp.py       Modify: _SYSTEM prompt + extract_contract_facts (Task 2)
                         + build_arp gets 5 new RiskFactor rows (Task 2)
  grille/
    engine.py            Modify: facts dict (Task 3), synthesize dedupe (Task 3)
    grille.yaml           Modify: +12 rules across Tasks 4-7
tests/
  test_models.py                 Modify: Task 1
  contract/test_arp.py           Modify: Task 2
  grille/test_engine.py          Modify: Tasks 3-7
```

---

## Task 1: `ContractFacts` — add `encryption_standard` and `ip_ownership`

**Files:**
- Modify: `policybot/models.py:30-39` (the `ContractFacts` class)
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `ContractFacts.encryption_standard: Literal["strong", "partial", "none", "unknown"]` (default `"unknown"`); `ContractFacts.ip_ownership: Literal["customer", "vendor", "unclear", "unknown"]` (default `"unknown"`).

- [ ] **Step 1: Write the failing tests**

Modify the import line at the top of `tests/test_models.py`:

```python
# tests/test_models.py
from datetime import date
from policybot.models import (
    QuestionSpec, QuestionOption, RiskFactor, Usage, InterviewState, RequestInfo,
    ContractFacts,
)
```

Append at the end of `tests/test_models.py`:

```python
def test_contractfacts_new_fields_default_to_unknown():
    facts = ContractFacts()
    assert facts.encryption_standard == "unknown"
    assert facts.ip_ownership == "unknown"


def test_contractfacts_accepts_explicit_encryption_and_ip_values():
    facts = ContractFacts(encryption_standard="strong", ip_ownership="customer")
    assert facts.encryption_standard == "strong"
    assert facts.ip_ownership == "customer"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_models.py -v`
Expected: FAIL with `TypeError` or `AttributeError` — `ContractFacts` has no field `encryption_standard`.

- [ ] **Step 3: Write minimal implementation**

In `policybot/models.py`, the `ContractFacts` class currently reads:

```python
class ContractFacts(BaseModel):
    trains_on_input: Literal["yes", "no", "opt_out_available", "unknown"] = "unknown"
    data_retention: Literal["none", "limited", "indefinite", "unknown"] = "unknown"
    data_residency: Literal["canada", "us", "eu", "other", "unknown"] = "unknown"
    sub_processors: Literal["disclosed", "undisclosed", "unknown"] = "unknown"
    human_review: Literal["yes", "no", "unknown"] = "unknown"
    source_url: Optional[str] = None
    fetched_at: Optional[date] = None
    snapshot_ref: Optional[str] = None
    extraction_confidence: float = 0.0
```

Change it to:

```python
class ContractFacts(BaseModel):
    trains_on_input: Literal["yes", "no", "opt_out_available", "unknown"] = "unknown"
    data_retention: Literal["none", "limited", "indefinite", "unknown"] = "unknown"
    data_residency: Literal["canada", "us", "eu", "other", "unknown"] = "unknown"
    sub_processors: Literal["disclosed", "undisclosed", "unknown"] = "unknown"
    human_review: Literal["yes", "no", "unknown"] = "unknown"
    encryption_standard: Literal["strong", "partial", "none", "unknown"] = "unknown"
    ip_ownership: Literal["customer", "vendor", "unclear", "unknown"] = "unknown"
    source_url: Optional[str] = None
    fetched_at: Optional[date] = None
    snapshot_ref: Optional[str] = None
    extraction_confidence: float = 0.0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_models.py -v`
Expected: PASS (all tests in the file, including the 2 new ones)

Then run the full suite to confirm nothing else broke: `pytest -v`
Expected: all pre-existing tests still pass (adding fields with defaults cannot break existing `ContractFacts(...)` calls).

- [ ] **Step 5: Commit**

```bash
git add policybot/models.py tests/test_models.py
git commit -m "feat: add encryption_standard and ip_ownership to ContractFacts"
```

---

## Task 2: Extend ARP extraction and `build_arp` for 5 new Partie A criteria

**Files:**
- Modify: `policybot/contract/arp.py` (whole file — `_SYSTEM`, `extract_contract_facts`, `build_arp`)
- Test: `tests/contract/test_arp.py`

**Interfaces:**
- Consumes: `ContractFacts` (Task 1, now with `encryption_standard`/`ip_ownership`).
- Produces: `extract_contract_facts` now also reads `encryption_standard`/`ip_ownership` from the LLM JSON response; `build_arp` now returns 7 `RiskFactor` rows instead of 2 (adds: sub-traitants, conservation des données, révision humaine, chiffrement, propriété intellectuelle).

- [ ] **Step 1: Write the failing tests**

Append to `tests/contract/test_arp.py`:

```python
def test_extract_maps_encryption_and_ip_fields():
    llm = FakeLLMProvider(json_responses=[{
        "trains_on_input": "no", "data_retention": "none",
        "data_residency": "canada", "sub_processors": "disclosed",
        "human_review": "yes", "encryption_standard": "strong",
        "ip_ownership": "customer", "extraction_confidence": 0.9,
    }])
    facts = extract_contract_facts(_terms(), llm)
    assert facts.encryption_standard == "strong"
    assert facts.ip_ownership == "customer"


def test_build_arp_generates_seven_criteria_rows():
    from policybot.models import ContractFacts
    arp = build_arp("ChatGPT", "publique", ContractFacts(
        trains_on_input="yes", data_retention="indefinite", data_residency="us",
        sub_processors="undisclosed", human_review="no",
        encryption_standard="none", ip_ownership="vendor",
    ))
    assert len(arp.criteria) == 7
    assert all(c.origin == "rule" for c in arp.criteria)
    criteria_names = {c.criterion for c in arp.criteria}
    assert "Garanties contractuelles de non-divulgation" in criteria_names


def test_build_arp_flags_risky_facts_as_high_or_critical():
    from policybot.models import ContractFacts
    facts = ContractFacts(
        data_retention="indefinite", sub_processors="undisclosed",
        human_review="no", encryption_standard="none", ip_ownership="vendor",
    )
    arp = build_arp("ToolX", "publique", facts)
    by_criterion = {c.criterion: c for c in arp.criteria}
    assert by_criterion["Garanties contractuelles de non-divulgation"].inherent in ("E", "C")
    assert by_criterion["Conservation des données"].inherent in ("E", "C")
    assert by_criterion["Révision humaine par le fournisseur"].inherent in ("E", "C")
    assert by_criterion["Chiffrement des données"].inherent in ("E", "C")
    assert by_criterion["Propriété intellectuelle du contenu généré"].inherent in ("E", "C")


def test_build_arp_flags_safe_facts_as_low_risk():
    from policybot.models import ContractFacts
    facts = ContractFacts(
        data_retention="none", sub_processors="disclosed",
        human_review="yes", encryption_standard="strong", ip_ownership="customer",
    )
    arp = build_arp("ToolX", "publique", facts)
    by_criterion = {c.criterion: c for c in arp.criteria}
    assert by_criterion["Garanties contractuelles de non-divulgation"].inherent == "F"
    assert by_criterion["Conservation des données"].inherent == "F"
    assert by_criterion["Révision humaine par le fournisseur"].inherent == "F"
    assert by_criterion["Chiffrement des données"].inherent == "F"
    assert by_criterion["Propriété intellectuelle du contenu généré"].inherent == "F"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/contract/test_arp.py -v`
Expected: FAIL — `test_extract_maps_encryption_and_ip_fields` fails on missing attributes (unless Task 1 already landed, in which case it fails because `extract_contract_facts` doesn't read those keys yet); the three `build_arp` tests fail on `len(arp.criteria) == 7` (currently 2) and on missing dict keys.

- [ ] **Step 3: Write minimal implementation**

Replace the full contents of `policybot/contract/arp.py`:

```python
from __future__ import annotations
from policybot.models import ContractFacts, ArpRecord, RiskFactor, IagType
from policybot.contract.fetcher import FetchedTerms
from policybot.llm.provider import LLMProvider

_SYSTEM = (
    "Tu extrais des faits normalisés des conditions d'utilisation d'un outil d'IA. "
    "Réponds uniquement en JSON avec: trains_on_input (yes|no|opt_out_available|"
    "unknown), data_retention (none|limited|indefinite|unknown), data_residency "
    "(canada|us|eu|other|unknown), sub_processors (disclosed|undisclosed|unknown), "
    "human_review (yes|no|unknown), encryption_standard (strong|partial|none|"
    "unknown) [strong = chiffrement en transit ET au repos explicitement mentionné, "
    "partial = un seul des deux ou non précisé, none = absence explicite de "
    "chiffrement], ip_ownership (customer|vendor|unclear|unknown) [qui détient les "
    "droits sur le contenu généré], extraction_confidence (0-1)."
)


def extract_contract_facts(terms: FetchedTerms, llm: LLMProvider) -> ContractFacts:
    raw = llm.complete_json(_SYSTEM, terms.text[:12000])
    return ContractFacts(
        trains_on_input=raw.get("trains_on_input", "unknown"),
        data_retention=raw.get("data_retention", "unknown"),
        data_residency=raw.get("data_residency", "unknown"),
        sub_processors=raw.get("sub_processors", "unknown"),
        human_review=raw.get("human_review", "unknown"),
        encryption_standard=raw.get("encryption_standard", "unknown"),
        ip_ownership=raw.get("ip_ownership", "unknown"),
        source_url=terms.source_url,
        fetched_at=terms.fetched_at,
        extraction_confidence=float(raw.get("extraction_confidence", 0.0)),
    )


def build_arp(tool_name: str, iag_type: IagType, facts: ContractFacts) -> ArpRecord:
    criteria: list[RiskFactor] = []

    training_risk = "E" if facts.trains_on_input in ("yes", "unknown") else "F"
    criteria.append(RiskFactor(
        category="Souveraineté", criterion="Données soumises utilisées pour entraînement",
        inherent=training_risk, residual=training_risk, origin="rule",
        observations=f"trains_on_input={facts.trains_on_input}",
    ))

    residency_risk = "F" if facts.data_residency == "canada" else "M"
    criteria.append(RiskFactor(
        category="Souveraineté", criterion="Localisation des serveurs",
        inherent=residency_risk, residual=residency_risk, origin="rule",
        observations=f"data_residency={facts.data_residency}",
    ))

    sub_processors_risk = "E" if facts.sub_processors in ("undisclosed", "unknown") else "F"
    criteria.append(RiskFactor(
        category="Souveraineté", criterion="Garanties contractuelles de non-divulgation",
        inherent=sub_processors_risk, residual=sub_processors_risk, origin="rule",
        observations=f"sub_processors={facts.sub_processors}",
    ))

    retention_risk = "E" if facts.data_retention in ("indefinite", "unknown") else "F"
    criteria.append(RiskFactor(
        category="Souveraineté", criterion="Conservation des données",
        inherent=retention_risk, residual=retention_risk, origin="rule",
        observations=f"data_retention={facts.data_retention}",
    ))

    human_review_risk = "E" if facts.human_review in ("no", "unknown") else "F"
    criteria.append(RiskFactor(
        category="Sécurité de l'information", criterion="Révision humaine par le fournisseur",
        inherent=human_review_risk, residual=human_review_risk, origin="rule",
        observations=f"human_review={facts.human_review}",
    ))

    encryption_risk = "E" if facts.encryption_standard in ("none", "unknown") else "F"
    criteria.append(RiskFactor(
        category="Sécurité de l'information", criterion="Chiffrement des données",
        inherent=encryption_risk, residual=encryption_risk, origin="rule",
        observations=f"encryption_standard={facts.encryption_standard}",
    ))

    ip_risk = "E" if facts.ip_ownership in ("vendor", "unclear", "unknown") else "F"
    criteria.append(RiskFactor(
        category="Conformité légale et contractuelle", criterion="Propriété intellectuelle du contenu généré",
        inherent=ip_risk, residual=ip_risk, origin="rule",
        observations=f"ip_ownership={facts.ip_ownership}",
    ))

    return ArpRecord(
        tool_name=tool_name, iag_type=iag_type, contract_facts=facts,
        criteria=criteria, terms_snapshot=facts.source_url,
        fetched_at=facts.fetched_at,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/contract/test_arp.py -v`
Expected: PASS (all tests, including the 4 new ones)

Then: `pytest -v` — expected: full suite passes, no regressions.

- [ ] **Step 5: Commit**

```bash
git add policybot/contract/arp.py tests/contract/test_arp.py
git commit -m "feat: extract encryption/IP facts and surface 5 more Partie A criteria in build_arp"
```

---

## Task 3: Wire 9 facts into `engine.py` and dedupe `synthesize()`

**Files:**
- Modify: `policybot/grille/engine.py`
- Test: `tests/grille/test_engine.py`

**Interfaces:**
- Consumes: `ContractFacts` (Task 1), `Usage.rens_personnels`, `Usage.needs_officer_confirmation` (already existing fields).
- Produces: `evaluate_usage`'s internal `facts` dict now has 11 keys (was 4); `synthesize()`'s `GlobalResult.conditions` is deduplicated, order-preserved.

- [ ] **Step 1: Write the failing tests**

Append to `tests/grille/test_engine.py`:

```python
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
```

The dict has 11 keys total: `data_classification`, `automated_decisions`, `trains_on_input`, `data_residency` (all 4 pre-existing) plus `sub_processors`, `data_retention`, `human_review`, `encryption_standard`, `ip_ownership`, `rens_personnels`, `needs_officer_confirmation` (7 new/reactivated).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/grille/test_engine.py -v`
Expected: FAIL — `test_facts_dict_includes_all_eleven_keys` fails because `captured.keys()` only has 4 entries; `test_synthesize_deduplicates_conditions_preserving_order` fails because `g.conditions == ["Rappel A", "Rappel B", "Rappel B", "Rappel C"]` (duplicate not removed).

- [ ] **Step 3: Write minimal implementation**

In `policybot/grille/engine.py`, replace the `facts = {...}` block inside `evaluate_usage`:

```python
    facts = {
        "data_classification": out.data_classification,
        "automated_decisions": out.automated_decisions,
        "trains_on_input": contract_facts.trains_on_input,
        "data_residency": contract_facts.data_residency,
        "sub_processors": contract_facts.sub_processors,
        "data_retention": contract_facts.data_retention,
        "human_review": contract_facts.human_review,
        "encryption_standard": contract_facts.encryption_standard,
        "ip_ownership": contract_facts.ip_ownership,
        "rens_personnels": out.rens_personnels,
        "needs_officer_confirmation": out.needs_officer_confirmation,
    }
```

And replace `synthesize()`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/grille/test_engine.py -v`
Expected: PASS (all tests)

Then: `pytest -v` — expected: full suite passes. In particular, re-check
`test_permis_with_training_rule_adds_conditions` and
`test_synthesize_takes_worst_and_flags_efvpr` (existing tests) still pass —
adding dict keys and deduping an already-unique list are both non-breaking.

- [ ] **Step 5: Commit**

```bash
git add policybot/grille/engine.py tests/grille/test_engine.py
git commit -m "feat: expose 9 dormant facts to the rule engine, dedupe synthesized conditions"
```

---

## Task 4: Rules R-21, R-22 — sub-processors and data retention

**Files:**
- Modify: `policybot/grille/grille.yaml`
- Test: `tests/grille/test_engine.py`

**Interfaces:**
- Consumes: `sub_processors`, `data_retention` keys now in the `facts` dict (Task 3).
- Produces: rules `R-21`, `R-22` in `grille.yaml`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/grille/test_engine.py`:

```python
def test_r21_undisclosed_subprocessors_with_classified_data():
    usage = Usage(data_classification="Protégé A")
    facts = ContractFacts(sub_processors="undisclosed")
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/grille/test_engine.py -k "r21 or r22" -v`
Expected: FAIL — no rule in `grille.yaml` yet produces these conditions strings, so `risk_level` stays `"Faible"` and the `any(...)` assertions on triggered-rule tests are `False`.

- [ ] **Step 3: Write minimal implementation**

Append to `policybot/grille/grille.yaml`:

```yaml
- id: R-21
  when:
    sub_processors: ["undisclosed", "unknown"]
    data_classification: ["Protégé A", "Protégé B", "Protégé C"]
  then:
    risk_level: "Modéré"
    recommendation: "Autoriser_avec_conditions"
    conditions: ["Demander la liste des sous-traitants au fournisseur avant de soumettre des données classifiées."]
- id: R-22
  when:
    data_retention: ["indefinite", "unknown"]
    data_classification: ["Protégé B", "Protégé C"]
  then:
    risk_level: "Élevé"
    recommendation: "Autoriser_avec_conditions"
    conditions: ["Confirmer la politique de conservation et de suppression des données auprès du fournisseur."]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/grille/test_engine.py -k "r21 or r22" -v`
Expected: PASS (4 tests)

Then: `pytest -v` — expected: full suite passes.

- [ ] **Step 5: Commit**

```bash
git add policybot/grille/grille.yaml tests/grille/test_engine.py
git commit -m "feat(grille): add R-21 (sub-processors) and R-22 (data retention) rules"
```

---

## Task 5: Rules R-23, R-24 — human review and LAI/PRP residency, both gated on personal information

**Files:**
- Modify: `policybot/grille/grille.yaml`
- Test: `tests/grille/test_engine.py`

**Interfaces:**
- Consumes: `human_review`, `rens_personnels`, `data_residency` keys (Task 3).
- Produces: rules `R-23`, `R-24` in `grille.yaml`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/grille/test_engine.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/grille/test_engine.py -k "r23 or r24" -v`
Expected: FAIL — rules don't exist yet, so none of the expected conditions/verdicts appear.

- [ ] **Step 3: Write minimal implementation**

Append to `policybot/grille/grille.yaml`:

```yaml
- id: R-23
  when:
    human_review: ["no", "unknown"]
    rens_personnels: ["True"]
  then:
    risk_level: "Élevé"
    recommendation: "Autoriser_avec_conditions"
    conditions: ["Aucune révision humaine confirmée chez le fournisseur pour des renseignements personnels — prévoir une validation manuelle interne."]
- id: R-24
  when:
    rens_personnels: ["True"]
    data_residency: ["us", "other", "unknown"]
  then:
    risk_level: "Élevé"
    recommendation: "Escalader"
    conditions: ["Renseignements personnels traités hors Québec — valider la conformité LAI/PRP avant autorisation."]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/grille/test_engine.py -k "r23 or r24" -v`
Expected: PASS (4 tests)

Then: `pytest -v` — expected: full suite passes.

- [ ] **Step 5: Commit**

```bash
git add policybot/grille/grille.yaml tests/grille/test_engine.py
git commit -m "feat(grille): add R-23 (human review) and R-24 (LAI/PRP residency) rules"
```

---

## Task 6: Rules R-25, R-26, R-27 — officer confirmation, encryption, IP ownership

**Files:**
- Modify: `policybot/grille/grille.yaml`
- Test: `tests/grille/test_engine.py`

**Interfaces:**
- Consumes: `needs_officer_confirmation`, `encryption_standard`, `ip_ownership` keys (Task 3).
- Produces: rules `R-25`, `R-26`, `R-27` in `grille.yaml`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/grille/test_engine.py`:

```python
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
    facts = ContractFacts(encryption_standard="none")
    out = evaluate_usage(usage, facts, iag_type="gouvernementale")
    assert out.risk_level == "Modéré"
    assert any("chiffrement" in c.lower() for c in out.conditions)


def test_r26_does_not_trigger_with_strong_encryption():
    usage = Usage(data_classification="Protégé C")
    facts = ContractFacts(encryption_standard="strong")
    out = evaluate_usage(usage, facts, iag_type="gouvernementale")
    assert not any("chiffrement" in c.lower() for c in out.conditions)


def test_r27_unclear_ip_ownership_triggers():
    usage = Usage(data_classification="Non classifié")
    facts = ContractFacts(ip_ownership="vendor")
    out = evaluate_usage(usage, facts, iag_type="publique")
    assert out.risk_level == "Modéré"
    assert any("propriété intellectuelle" in c.lower() for c in out.conditions)


def test_r27_does_not_trigger_when_customer_owns_ip():
    usage = Usage(data_classification="Non classifié")
    facts = ContractFacts(ip_ownership="customer")
    out = evaluate_usage(usage, facts, iag_type="publique")
    assert not any("propriété intellectuelle" in c.lower() for c in out.conditions)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/grille/test_engine.py -k "r25 or r26 or r27" -v`
Expected: FAIL — rules don't exist yet.

- [ ] **Step 3: Write minimal implementation**

Append to `policybot/grille/grille.yaml`:

```yaml
- id: R-25
  when:
    needs_officer_confirmation: ["True"]
  then:
    risk_level: "Modéré"
    recommendation: "Autoriser_avec_conditions"
    conditions: ["Classification à faible confiance ou réponse libre « Autre » — confirmation de l'agent SI requise avant de considérer ce résultat final."]
- id: R-26
  when:
    encryption_standard: ["none", "unknown"]
    data_classification: ["Protégé A", "Protégé B", "Protégé C"]
  then:
    risk_level: "Modéré"
    recommendation: "Autoriser_avec_conditions"
    conditions: ["Confirmer le niveau de chiffrement des données en transit et au repos auprès du fournisseur."]
- id: R-27
  when:
    ip_ownership: ["vendor", "unclear", "unknown"]
  then:
    risk_level: "Modéré"
    recommendation: "Autoriser_avec_conditions"
    conditions: ["Le fournisseur pourrait revendiquer des droits sur le contenu généré — vérifier les clauses de propriété intellectuelle avant publication ou usage externe."]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/grille/test_engine.py -k "r25 or r26 or r27" -v`
Expected: PASS (6 tests)

Then: `pytest -v` — expected: full suite passes.

- [ ] **Step 5: Commit**

```bash
git add policybot/grille/grille.yaml tests/grille/test_engine.py
git commit -m "feat(grille): add R-25 (officer confirmation), R-26 (encryption), R-27 (IP ownership) rules"
```

---

## Task 7: Rules R-28 through R-32 — fixed advisory reminders

**Files:**
- Modify: `policybot/grille/grille.yaml`
- Test: `tests/grille/test_engine.py`

**Interfaces:**
- Consumes: nothing (these rules have an empty `when: {}`, so they always match — see `evaluate_rules`'s `all(...)` over an empty dict being vacuously `True`).
- Produces: rules `R-28` (hallucinations), `R-29` (biais), `R-30` (formation), `R-31` (dépendance techno), `R-32` (réputation) in `grille.yaml`. None of them set `risk_level`/`recommendation`, so they cannot change a usage's verdict — they only append to `conditions`.

- [ ] **Step 1: Write the failing test**

Append to `tests/grille/test_engine.py`:

```python
def test_fixed_advisories_always_present_and_dont_affect_verdict():
    usage = Usage(data_classification="Non classifié")
    out = evaluate_usage(usage, ContractFacts(trains_on_input="no"), iag_type="publique")
    assert out.verdict == "Autoriser"
    assert out.risk_level == "Faible"
    joined = " ".join(out.conditions).lower()
    for keyword in ("hallucination", "biais", "formation", "dépendance", "réputation"):
        assert keyword in joined
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/grille/test_engine.py -k fixed_advisories -v`
Expected: FAIL — none of the 5 keywords are present in `out.conditions` yet.

- [ ] **Step 3: Write minimal implementation**

Append to `policybot/grille/grille.yaml`:

```yaml
- id: R-28
  when: {}
  then:
    conditions: ["Rappel : les contenus générés peuvent contenir des erreurs factuelles (hallucinations) — valider l'exactitude avant toute utilisation externe ou décisionnelle."]
- id: R-29
  when: {}
  then:
    conditions: ["Rappel : les résultats peuvent refléter des biais présents dans les données d'entraînement du modèle — rester vigilant pour les usages à portée décisionnelle."]
- id: R-30
  when: {}
  then:
    conditions: ["Rappel : s'assurer que la personne utilisatrice a reçu une formation adéquate sur l'usage responsable de cet outil."]
- id: R-31
  when: {}
  then:
    conditions: ["Rappel : éviter la surconfiance envers l'outil — le jugement professionnel demeure requis (dépendance technologique)."]
- id: R-32
  when: {}
  then:
    conditions: ["Rappel : valider que tout contenu généré associé à l'UQAM respecte les standards d'image et de qualité institutionnels avant diffusion publique."]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/grille/test_engine.py -k fixed_advisories -v`
Expected: PASS

Then run the entire suite: `pytest -v`
Expected: all pre-existing tests plus every test added in Tasks 1-7 pass — including
`tests/test_golden_scenarios.py` (still `INTERDIT` → `Refuser`, no rules evaluated,
so `R-28`-`R-32` never fire for that scenario and cannot affect its assertions).

- [ ] **Step 5: Commit**

```bash
git add policybot/grille/grille.yaml tests/grille/test_engine.py
git commit -m "feat(grille): add R-28 through R-32 fixed advisory reminders (Partie B ethics/org risks)"
```

---

## Manual verification (after Task 7)

Not automatable by pytest — confirm the rendered report reads well with the
expanded rule set:

```bash
pip install -e ".[dev]"
python -c "
from policybot.models import RequestInfo
from policybot.llm.fake import FakeLLMProvider
from policybot.preapproved.store import PreApprovedStore
from policybot.interview.orchestrator import Interview
from policybot.report.renderer import render_html

llm = FakeLLMProvider(json_responses=[
    {'already_public': False, 'contains_personal_info': True, 'strategic_sensitive': False,
     'internal_nonpublic': True, 'highly_sensitive_secret': False, 'confidence': 0.9},
    {'trains_on_input': 'yes', 'data_retention': 'indefinite', 'data_residency': 'us',
     'sub_processors': 'undisclosed', 'human_review': 'no', 'encryption_standard': 'none',
     'ip_ownership': 'vendor', 'extraction_confidence': 0.85},
])
itv = Interview(llm=llm, store=PreApprovedStore('policybot.db'),
                http_get=lambda url: '<html><body>ok</body></html>')
state = itv.assess(
    request=RequestInfo(numero='IAG-2026-999'),
    tool_name='Notion AI',
    usage_inputs=[{'description': 'Analyser des dossiers étudiants',
                   'data_description': \"renseignements personnels d'étudiants\",
                   'automated_decisions': False, 'mode': ['prompt'], 'result_use': []}],
    iag_type_override='circuit_ferme',
)
usage = state.usages[0]
print('verdict:', usage.verdict, '| risk:', usage.risk_level)
print('conditions:')
for c in usage.conditions:
    print(' -', c)
"
```

Confirm: verdict is `Escalader` (R-24 fires: personal info + `us` residency),
and the conditions list includes entries from R-21/R-22/R-23/R-24/R-25 (if
low classifier confidence)/R-26/R-27 plus all 5 fixed advisories (R-28-32),
with no duplicated lines.

---

## Self-Review Notes

- **Spec coverage:** Section A → Tasks 1-2. Section B → Task 3. Section C
  conditional rules → Tasks 4-6. Section C fixed advisories → Task 7. Section D
  testing approach → covered by every task's test file and the golden-scenario
  regression check baked into Global Constraints.
- **Placeholder scan:** none — every step has literal code/YAML.
- **Type consistency:** `ContractFacts` field names (`encryption_standard`,
  `ip_ownership`) match across Task 1 (model), Task 2 (extraction + `build_arp`),
  and Tasks 3/6 (engine facts dict + `grille.yaml` keys). `Usage.rens_personnels`
  and `Usage.needs_officer_confirmation` (both pre-existing fields, unchanged)
  match across Task 3 and Tasks 5/6.
