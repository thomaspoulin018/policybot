# Alignement du rapport sur la Grille d'évaluation des risques — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PolicyBot's generated report reproduce the exact sections, categories, and named criteria of `documents_reference/SI_-_Grille_valuation_des_risques.docx` (Identification, Partie A — ARP, Partie B — par usage, Partie C — Synthèse), instead of today's aggregated summary.

**Architecture:** A new shared constants module (`policybot/criteria.py`) becomes the single source of truth for the 13 Partie A criteria and 11 Partie B criteria (category, criterion name, description — verbatim from the reference document). `build_arp()` and `evaluate_usage()` populate `RiskFactor` rows keyed by those exact criterion names; `report/renderer.py` merges the fixed criteria order with whatever data is available (leaving blanks where PolicyBot has no signal) before handing rows to the Jinja template, grouped by category using `itertools.groupby` (not Jinja's `groupby`, which re-sorts and would break document order).

**Tech Stack:** Python 3.11, Pydantic v2, Jinja2, pytest, PyYAML (`grille.yaml`).

## Global Constraints

- The MCN permission matrix (`policybot/grille/matrix.py`) is an absolute hard gate — nothing in this plan touches it or overrides an `INTERDIT`.
- F/M/E/C ratings remain proposals (`origin="rule"`, never officer-authoritative) — this plan only changes *which* criteria get a proposal and how they reach the report.
- Conservative-by-default: any new field defaulting to `"unknown"` must resolve to the higher-risk letter (`E`), never `F`.
- Per `docs/superpowers/specs/2026-07-07-grille-rules-design.md`, do NOT add LLM extraction for: authentification SSO/MFA, journalisation/traçabilité, gestion des incidents, compatibilité licence gouvernementale, conditions d'utilisation acceptables. These 5 Partie A criteria stay blank in the report.
- `pytest -v` is the only gate (no separate lint/typecheck). Every task must leave the full suite green.
- `tests/conftest.py` already disables LangSmith tracing under pytest — no changes needed there.

---

### Task 1: Fixed criteria tables (`policybot/criteria.py`)

**Files:**
- Create: `policybot/criteria.py`
- Test: `tests/test_criteria.py`

**Interfaces:**
- Produces: `ARP_CRITERIA: list[tuple[str, str, str]]` (13 entries, `(category, criterion, description)`), `USAGE_CRITERIA: list[tuple[str, str, str]]` (11 entries, same shape). Consumed by Tasks 4, 7, 8, 9.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_criteria.py
from policybot.criteria import ARP_CRITERIA, USAGE_CRITERIA


def test_arp_criteria_has_thirteen_unique_entries():
    assert len(ARP_CRITERIA) == 13
    names = [criterion for _, criterion, _ in ARP_CRITERIA]
    assert len(names) == len(set(names))


def test_arp_criteria_categories_match_document():
    categories = {category for category, _, _ in ARP_CRITERIA}
    assert categories == {
        "Souveraineté et hébergement des données",
        "Sécurité de l'information",
        "Conformité légale et contractuelle",
    }


def test_usage_criteria_has_eleven_unique_entries():
    assert len(USAGE_CRITERIA) == 11
    names = [criterion for _, criterion, _ in USAGE_CRITERIA]
    assert len(names) == len(set(names))


def test_usage_criteria_categories_match_document():
    categories = {category for category, _, _ in USAGE_CRITERIA}
    assert categories == {
        "Gestion des données",
        "Éthique et fiabilité des résultats",
        "Risques organisationnels",
    }


def test_every_entry_has_a_non_empty_description():
    for _, _, description in ARP_CRITERIA + USAGE_CRITERIA:
        assert description.strip()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_criteria.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'policybot.criteria'`

- [ ] **Step 3: Write the implementation**

```python
# policybot/criteria.py
"""Fixed criteria tables mirroring the two risk tables of
documents_reference/SI_-_Grille_valuation_des_risques.docx (Parties A & B).

Each tuple is (category, criterion, description), in document order and
grouped by category (report rendering relies on this grouping — see
policybot/report/renderer.py). This is the single source of truth for the
exact criterion names used by policybot/contract/arp.py (Partie A) and
policybot/grille/engine.py (Partie B): both look up computed risk data by
matching these names verbatim.
"""

ARP_CRITERIA: list[tuple[str, str, str]] = [
    ("Souveraineté et hébergement des données", "Localisation des serveurs",
     "Les données sont-elles hébergées au Québec ou dans une juridiction "
     "équivalente ?"),
    ("Souveraineté et hébergement des données", "Juridiction applicable",
     "Quelle loi s'applique en cas de litige ? Risque d'accès par des "
     "autorités étrangères (ex. : Cloud Act US) ?"),
    ("Souveraineté et hébergement des données", "Dépendance technologique",
     "Le produit augmente-t-il la dépendance envers des fournisseurs "
     "étrangers?"),
    ("Souveraineté et hébergement des données",
     "Données soumises utilisées pour entraînement du modèle",
     "Les requêtes soumises sont-elles utilisées pour améliorer ou "
     "entraîner le modèle ? Opt-out disponible ?"),
    ("Souveraineté et hébergement des données",
     "Garanties contractuelles de non-divulgation",
     "Le contrat interdit-il explicitement la réutilisation des données "
     "soumises ?"),
    ("Sécurité de l'information", "Mécanismes d'authentification",
     "L'outil supporte-t-il l'authentification forte (SSO, MFA) ? "
     "Intégrable avec l'infrastructure UQAM ?"),
    ("Sécurité de l'information", "Chiffrement des données",
     "Les données sont-elles chiffrées de bout en bout en transit et au "
     "repos ? Quel standard (AES-256, TLS 1.3) ?"),
    ("Sécurité de l'information", "Journalisation et traçabilité",
     "L'outil génère-t-il des journaux d'accès et des journaux permettant "
     "d'auditer les entrées (prompts) et les sorties? Accessibles par "
     "l'organisation ?"),
    ("Sécurité de l'information", "Utilisation des entrées et des sorties",
     "Existe-t-il une façon d'interdire le réentraînement du modèle à "
     "partir des données soumises par l'utilisateur et de celles qui sont "
     "produites?"),
    ("Sécurité de l'information", "Gestion des incidents",
     "Le fournisseur dispose-t-il d'un plan de réponse aux incidents ? "
     "Délais de notification en cas de brèche ?"),
    ("Conformité légale et contractuelle", "Propriété intellectuelle",
     "Qui détient les droits sur les contenus générés ? Le contrat "
     "préserve-t-il la PI de l'UQAM ?"),
    ("Conformité légale et contractuelle",
     "Conditions d'utilisation acceptables",
     "Les conditions d'utilisation sont-elles acceptables pour un usage "
     "institutionnel ? Clauses problématiques ?"),
    ("Conformité légale et contractuelle",
     "Compatibilité licence usage gouvernemental",
     "La licence permet-elle un usage par une institution d'enseignement "
     "supérieur québécoise ?"),
]

USAGE_CRITERIA: list[tuple[str, str, str]] = [
    ("Gestion des données", "Fuite de données confidentielles",
     "Risque de soumettre des données institutionnelles sensibles ou "
     "stratégiques à un outil public non sécurisé."),
    ("Gestion des données", "Mauvaise classification des données",
     "Le personnel soumet des données d'une classification supérieure à ce "
     "que l'outil permet."),
    ("Gestion des données", "Utilisation de données pour entraînement",
     "Les données soumises pourraient être réutilisées par le fournisseur "
     "pour entraîner son modèle."),
    ("Gestion des données", "Compatibilité avec la LAI/PRP",
     "Les conditions du fournisseur sont-elles compatibles avec la Loi sur "
     "l'accès et la protection des renseignements personnels du Québec ?"),
    ("Éthique et fiabilité des résultats",
     "Hallucinations et erreurs factuelles",
     "L'outil génère des informations inexactes présentées comme vraies. "
     "Risque de décisions basées sur des données erronées."),
    ("Éthique et fiabilité des résultats", "Biais algorithmiques",
     "Les résultats reflètent des biais présents dans les données "
     "d'entraînement, pouvant mener à des conclusions discriminatoires."),
    ("Éthique et fiabilité des résultats", "Supervision humaine insuffisante",
     "Les décisions ou contenus générés sont utilisés sans validation "
     "humaine adéquate avant diffusion ou action."),
    ("Éthique et fiabilité des résultats",
     "Propriété intellectuelle du contenu généré",
     "Les contenus générés pourraient reproduire du matériel protégé ou "
     "créer des ambiguïtés sur la propriété des livrables."),
    ("Risques organisationnels", "Formation insuffisante du personnel",
     "Le personnel utilise l'outil sans formation adéquate, augmentant le "
     "risque d'erreurs et de non-conformité."),
    ("Risques organisationnels", "Dépendance technologique",
     "Risque de surconfiance ou de dépendance à l'outil au détriment du "
     "jugement professionnel."),
    ("Risques organisationnels", "Image et réputation institutionnelle",
     "Publication de contenus générés incorrects ou inappropriés associés "
     "à l'UQAM."),
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_criteria.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add policybot/criteria.py tests/test_criteria.py
git commit -m "feat: add fixed ARP/usage criteria tables mirroring reference docx"
```

---

### Task 2: Extend `ContractFacts` with 4 new fields

**Files:**
- Modify: `policybot/models.py:30-41` (the `ContractFacts` class)
- Test: `tests/contract/test_arp.py` (extraction tests, extended)

**Interfaces:**
- Consumes: nothing new.
- Produces: `ContractFacts.applicable_law`, `.foreign_vendor_dependency`, `.contract_prohibits_reuse`, `.reentraining_opt_out` — all `Literal[..., "unknown"]`, default `"unknown"`. Consumed by Task 3 (extraction) and Task 4 (`build_arp`).

- [ ] **Step 1: Write the failing test**

```python
# add to tests/contract/test_arp.py
def test_extract_maps_new_sovereignty_and_security_fields():
    llm = FakeLLMProvider(json_responses=[{
        "applicable_law": "foreign", "foreign_vendor_dependency": "yes",
        "contract_prohibits_reuse": "no", "reentraining_opt_out": "no",
        "extraction_confidence": 0.7,
    }])
    facts = extract_contract_facts(_terms(), llm)
    assert facts.applicable_law == "foreign"
    assert facts.foreign_vendor_dependency == "yes"
    assert facts.contract_prohibits_reuse == "no"
    assert facts.reentraining_opt_out == "no"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/contract/test_arp.py::test_extract_maps_new_sovereignty_and_security_fields -v`
Expected: FAIL — `ContractFacts` has no field `applicable_law` (pydantic ignores unknown extraction keys silently today because `extract_contract_facts` only reads keys it explicitly maps; the test fails because `facts.applicable_law` raises `AttributeError`)

- [ ] **Step 3: Write the minimal implementation**

In `policybot/models.py`, extend `ContractFacts` (insert after `ip_ownership`, before `source_url`):

```python
class ContractFacts(BaseModel):
    trains_on_input: Literal["yes", "no", "opt_out_available", "unknown"] = "unknown"
    data_retention: Literal["none", "limited", "indefinite", "unknown"] = "unknown"
    data_residency: Literal["canada", "us", "eu", "other", "unknown"] = "unknown"
    sub_processors: Literal["disclosed", "undisclosed", "unknown"] = "unknown"
    human_review: Literal["yes", "no", "unknown"] = "unknown"
    encryption_standard: Literal["strong", "partial", "none", "unknown"] = "unknown"
    ip_ownership: Literal["customer", "vendor", "unclear", "unknown"] = "unknown"
    applicable_law: Literal["quebec_canada", "foreign", "unknown"] = "unknown"
    foreign_vendor_dependency: Literal["yes", "no", "unknown"] = "unknown"
    contract_prohibits_reuse: Literal["yes", "no", "unknown"] = "unknown"
    reentraining_opt_out: Literal["yes", "no", "unknown"] = "unknown"
    source_url: Optional[str] = None
    fetched_at: Optional[date] = None
    snapshot_ref: Optional[str] = None
    extraction_confidence: float = 0.0
```

This test still fails at this point (the fields exist now, but `extract_contract_facts` doesn't map them yet) — that's expected, Task 3 finishes it.

- [ ] **Step 4: Run test to verify it still fails for the right reason**

Run: `pytest tests/contract/test_arp.py::test_extract_maps_new_sovereignty_and_security_fields -v`
Expected: FAIL — now `facts.applicable_law == "unknown"` (the field exists with its default) instead of `"foreign"`, because `extract_contract_facts` doesn't read `raw["applicable_law"]` yet.

- [ ] **Step 5: Commit the model change alone**

```bash
git add policybot/models.py tests/contract/test_arp.py
git commit -m "feat: add 4 new ContractFacts fields for Partie A sovereignty/security criteria"
```

(Test stays red until Task 3 — this is intentional: the field and its test are committed together so the next task's diff is pure wiring.)

---

### Task 3: Extend extraction prompt and `extract_contract_facts` mapping

**Files:**
- Modify: `policybot/contract/arp.py:6-35` (`_SYSTEM` and `extract_contract_facts`)

**Interfaces:**
- Consumes: `ContractFacts` fields from Task 2.
- Produces: `extract_contract_facts()` now populates all 4 new fields from the LLM's JSON response.

- [ ] **Step 1: Run the Task 2 test to confirm it's still failing**

Run: `pytest tests/contract/test_arp.py::test_extract_maps_new_sovereignty_and_security_fields -v`
Expected: FAIL (as left off in Task 2)

- [ ] **Step 2: Write the implementation**

Replace `_SYSTEM` and `extract_contract_facts` in `policybot/contract/arp.py`:

```python
_SYSTEM = (
    "Tu extrais des faits normalisés des conditions d'utilisation d'un outil d'IA. "
    "Réponds uniquement en JSON avec: trains_on_input (yes|no|opt_out_available|"
    "unknown), data_retention (none|limited|indefinite|unknown), data_residency "
    "(canada|us|eu|other|unknown), sub_processors (disclosed|undisclosed|unknown), "
    "human_review (yes|no|unknown), encryption_standard (strong|partial|none|"
    "unknown) [strong = chiffrement en transit ET au repos explicitement mentionné, "
    "partial = un seul des deux ou non précisé, none = absence explicite de "
    "chiffrement], ip_ownership (customer|vendor|unclear|unknown) [qui détient les "
    "droits sur le contenu généré], applicable_law (quebec_canada|foreign|unknown) "
    "[le droit applicable au contrat est-il celui du Québec/Canada ou un droit "
    "étranger ?], foreign_vendor_dependency (yes|no|unknown) [l'usage de l'outil "
    "crée-t-il une dépendance envers un fournisseur étranger ?], "
    "contract_prohibits_reuse (yes|no|unknown) [le contrat interdit-il "
    "explicitement au fournisseur de réutiliser les données soumises ?], "
    "reentraining_opt_out (yes|no|unknown) [existe-t-il un mécanisme permettant "
    "d'interdire le réentraînement du modèle à partir des données soumises et de "
    "celles qui sont produites ?], extraction_confidence (0-1)."
)


def extract_contract_facts(terms: FetchedTerms, llm: LLMProvider) -> ContractFacts:
    raw = llm.complete_json(
        _SYSTEM, terms.text[:12000],
        run_name="extract_contract_facts", tags=["arp_extraction"],
    )
    return ContractFacts(
        trains_on_input=raw.get("trains_on_input", "unknown"),
        data_retention=raw.get("data_retention", "unknown"),
        data_residency=raw.get("data_residency", "unknown"),
        sub_processors=raw.get("sub_processors", "unknown"),
        human_review=raw.get("human_review", "unknown"),
        encryption_standard=raw.get("encryption_standard", "unknown"),
        ip_ownership=raw.get("ip_ownership", "unknown"),
        applicable_law=raw.get("applicable_law", "unknown"),
        foreign_vendor_dependency=raw.get("foreign_vendor_dependency", "unknown"),
        contract_prohibits_reuse=raw.get("contract_prohibits_reuse", "unknown"),
        reentraining_opt_out=raw.get("reentraining_opt_out", "unknown"),
        source_url=terms.source_url,
        fetched_at=terms.fetched_at,
        extraction_confidence=float(raw.get("extraction_confidence", 0.0)),
    )
```

- [ ] **Step 3: Run test to verify it passes**

Run: `pytest tests/contract/test_arp.py -v`
Expected: PASS (all tests in the file, including the new one)

- [ ] **Step 4: Commit**

```bash
git add policybot/contract/arp.py
git commit -m "feat: extract 4 new sovereignty/security fields in ARP contract facts"
```

---

### Task 4: Rewrite `build_arp()` — 8 derived Partie A criteria

**Files:**
- Modify: `policybot/contract/arp.py:38-94` (`build_arp`)
- Modify: `tests/contract/test_arp.py` (replace criteria-count and risky/safe-facts tests)

**Interfaces:**
- Consumes: `ARP_CRITERIA` from Task 1, `ContractFacts` from Tasks 2-3.
- Produces: `build_arp(tool_name, iag_type, facts) -> ArpRecord` whose `.criteria` contains exactly 8 `RiskFactor` rows, criterion names taken verbatim from `ARP_CRITERIA`. Consumed by Task 5 (orchestrator) and Task 8 (renderer, via `ArpRecord.criteria`).

- [ ] **Step 1: Replace the obsolete tests**

In `tests/contract/test_arp.py`, replace `test_build_arp_generates_seven_criteria_rows`, `test_build_arp_flags_risky_facts_as_high_or_critical`, and `test_build_arp_flags_safe_facts_as_low_risk` with:

```python
def test_build_arp_generates_eight_criteria_rows():
    from policybot.models import ContractFacts
    arp = build_arp("ChatGPT", "publique", ContractFacts(
        trains_on_input="yes", data_residency="us",
        applicable_law="foreign", foreign_vendor_dependency="yes",
        contract_prohibits_reuse="no", encryption_standard="none",
        reentraining_opt_out="no", ip_ownership="vendor",
    ))
    assert len(arp.criteria) == 8
    assert all(c.origin == "rule" for c in arp.criteria)
    criteria_names = {c.criterion for c in arp.criteria}
    assert criteria_names == {
        "Localisation des serveurs", "Juridiction applicable",
        "Dépendance technologique",
        "Données soumises utilisées pour entraînement du modèle",
        "Garanties contractuelles de non-divulgation",
        "Chiffrement des données", "Utilisation des entrées et des sorties",
        "Propriété intellectuelle",
    }


def test_build_arp_flags_risky_facts_as_high_risk():
    from policybot.models import ContractFacts
    facts = ContractFacts(
        applicable_law="foreign", foreign_vendor_dependency="yes",
        contract_prohibits_reuse="no", encryption_standard="none",
        reentraining_opt_out="no", ip_ownership="vendor",
    )
    arp = build_arp("ToolX", "publique", facts)
    by_criterion = {c.criterion: c for c in arp.criteria}
    assert by_criterion["Juridiction applicable"].inherent == "E"
    assert by_criterion["Dépendance technologique"].inherent == "E"
    assert by_criterion["Garanties contractuelles de non-divulgation"].inherent == "E"
    assert by_criterion["Chiffrement des données"].inherent == "E"
    assert by_criterion["Utilisation des entrées et des sorties"].inherent == "E"
    assert by_criterion["Propriété intellectuelle"].inherent == "E"


def test_build_arp_flags_safe_facts_as_low_risk():
    from policybot.models import ContractFacts
    facts = ContractFacts(
        applicable_law="quebec_canada", foreign_vendor_dependency="no",
        contract_prohibits_reuse="yes", encryption_standard="strong",
        reentraining_opt_out="yes", ip_ownership="customer",
    )
    arp = build_arp("ToolX", "publique", facts)
    by_criterion = {c.criterion: c for c in arp.criteria}
    assert by_criterion["Juridiction applicable"].inherent == "F"
    assert by_criterion["Dépendance technologique"].inherent == "F"
    assert by_criterion["Garanties contractuelles de non-divulgation"].inherent == "F"
    assert by_criterion["Chiffrement des données"].inherent == "F"
    assert by_criterion["Utilisation des entrées et des sorties"].inherent == "F"
    assert by_criterion["Propriété intellectuelle"].inherent == "F"


def test_build_arp_defaults_to_conservative_risk_on_unknown():
    from policybot.models import ContractFacts
    arp = build_arp("ToolX", "publique", ContractFacts())
    by_criterion = {c.criterion: c for c in arp.criteria}
    assert by_criterion["Juridiction applicable"].inherent == "E"
    assert by_criterion["Dépendance technologique"].inherent == "E"
    assert by_criterion["Garanties contractuelles de non-divulgation"].inherent == "E"
    assert by_criterion["Utilisation des entrées et des sorties"].inherent == "E"
```

Leave `test_build_arp_flags_training_as_high_risk` and `test_build_arp_flags_partial_encryption_as_risky` as-is (unaffected).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/contract/test_arp.py -v`
Expected: FAIL on the 4 new/replaced tests — `build_arp` still returns 7 rows including "Conservation des données" / "Révision humaine par le fournisseur", and has no rows for the new criteria.

- [ ] **Step 3: Write the implementation**

Replace `build_arp` in `policybot/contract/arp.py` (add the import at the top of the file too):

```python
from policybot.criteria import ARP_CRITERIA  # add to the existing import block


def build_arp(tool_name: str, iag_type: IagType, facts: ContractFacts) -> ArpRecord:
    """Produce the 8 of 13 Partie A criteria PolicyBot can derive from
    ContractFacts. The other 5 (authentification, journalisation, gestion
    des incidents, conditions d'utilisation acceptables, compatibilité
    licence gouvernementale) require a real security review or signed
    contract, not a public terms-of-use page — see
    docs/superpowers/specs/2026-07-07-grille-rules-design.md. The report
    renders those as blank rows for the SI officer to fill in (see
    policybot/report/renderer.py)."""
    criteria: list[RiskFactor] = []

    residency_risk = "F" if facts.data_residency == "canada" else "M"
    criteria.append(RiskFactor(
        category="Souveraineté et hébergement des données",
        criterion="Localisation des serveurs",
        inherent=residency_risk, residual=residency_risk, origin="rule",
        observations=f"data_residency={facts.data_residency}",
    ))

    law_risk = "F" if facts.applicable_law == "quebec_canada" else "E"
    criteria.append(RiskFactor(
        category="Souveraineté et hébergement des données",
        criterion="Juridiction applicable",
        inherent=law_risk, residual=law_risk, origin="rule",
        observations=f"applicable_law={facts.applicable_law}",
    ))

    dependency_risk = "F" if facts.foreign_vendor_dependency == "no" else "E"
    criteria.append(RiskFactor(
        category="Souveraineté et hébergement des données",
        criterion="Dépendance technologique",
        inherent=dependency_risk, residual=dependency_risk, origin="rule",
        observations=f"foreign_vendor_dependency={facts.foreign_vendor_dependency}",
    ))

    training_risk = "E" if facts.trains_on_input in ("yes", "unknown") else "F"
    criteria.append(RiskFactor(
        category="Souveraineté et hébergement des données",
        criterion="Données soumises utilisées pour entraînement du modèle",
        inherent=training_risk, residual=training_risk, origin="rule",
        observations=f"trains_on_input={facts.trains_on_input}",
    ))

    reuse_risk = "F" if facts.contract_prohibits_reuse == "yes" else "E"
    criteria.append(RiskFactor(
        category="Souveraineté et hébergement des données",
        criterion="Garanties contractuelles de non-divulgation",
        inherent=reuse_risk, residual=reuse_risk, origin="rule",
        observations=f"contract_prohibits_reuse={facts.contract_prohibits_reuse}",
    ))

    encryption_risk = "E" if facts.encryption_standard in ("none", "partial", "unknown") else "F"
    criteria.append(RiskFactor(
        category="Sécurité de l'information",
        criterion="Chiffrement des données",
        inherent=encryption_risk, residual=encryption_risk, origin="rule",
        observations=f"encryption_standard={facts.encryption_standard}",
    ))

    opt_out_risk = "F" if facts.reentraining_opt_out == "yes" else "E"
    criteria.append(RiskFactor(
        category="Sécurité de l'information",
        criterion="Utilisation des entrées et des sorties",
        inherent=opt_out_risk, residual=opt_out_risk, origin="rule",
        observations=f"reentraining_opt_out={facts.reentraining_opt_out}",
    ))

    ip_risk = "E" if facts.ip_ownership in ("vendor", "unclear", "unknown") else "F"
    criteria.append(RiskFactor(
        category="Conformité légale et contractuelle",
        criterion="Propriété intellectuelle",
        inherent=ip_risk, residual=ip_risk, origin="rule",
        observations=f"ip_ownership={facts.ip_ownership}",
    ))

    assert {c.criterion for c in criteria} <= {name for _, name, _ in ARP_CRITERIA}, (
        "build_arp criterion names must match policybot.criteria.ARP_CRITERIA"
    )

    return ArpRecord(
        tool_name=tool_name, iag_type=iag_type, contract_facts=facts,
        criteria=criteria, terms_snapshot=facts.source_url,
        fetched_at=facts.fetched_at,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/contract/test_arp.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Run the full suite to check for fallout**

Run: `pytest -v`
Expected: Only `tests/report/test_renderer.py` and `tests/test_golden_scenarios.py` might still be green at this point since nothing consumes the removed criteria names yet outside `test_arp.py` — confirm no other failures. If something else fails referencing "Conservation des données" or "Révision humaine par le fournisseur", note it and fix in this task (search first: `grep -rn "Conservation des données\|Révision humaine par le fournisseur" --include=*.py .`).

- [ ] **Step 6: Commit**

```bash
git add policybot/contract/arp.py policybot/models.py tests/contract/test_arp.py
git commit -m "feat: rebuild ARP to produce the 8 derivable Partie A criteria"
```

---

### Task 5: Wire `ArpRecord` into `InterviewState.tools[].arp`

**Files:**
- Modify: `policybot/interview/orchestrator.py:12,45-59,95-96`
- Test: `tests/interview/test_orchestrator.py` (new test)

**Interfaces:**
- Consumes: `build_arp` (Task 4), `PreApprovedStore.get_arp`/`save_arp` (unchanged).
- Produces: `Interview.assess(...)` now sets `state.tools[0].arp` to the resolved `ArpRecord` (previously this field was always `None` — nothing populated it, so Partie A had no data to render regardless of what `build_arp` produced). Consumed by Task 8 (renderer reads `tool.arp.criteria`).

- [ ] **Step 1: Write the failing test**

Add to `tests/interview/test_orchestrator.py`:

```python
def test_assess_attaches_arp_record_to_tool_ref(tmp_path):
    llm = FakeLLMProvider(json_responses=[
        {"already_public": True, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.9},
        {"trains_on_input": "no", "data_retention": "none", "data_residency": "canada",
         "sub_processors": "disclosed", "human_review": "yes", "extraction_confidence": 0.9},
    ])
    store = PreApprovedStore(str(tmp_path / "pb.db"))
    itv = Interview(llm=llm, store=store, http_get=_terms_get)
    state = itv.assess(
        request=RequestInfo(numero="IAG-2026-010"),
        tool_name="ChatGPT",
        usage_inputs=[{"description": "Chercher de l'info publique",
                       "data_description": "information publique sur le web",
                       "automated_decisions": False, "mode": ["prompt"], "result_use": []}],
    )
    assert state.tools[0].arp is not None
    assert len(state.tools[0].arp.criteria) == 8


def test_assess_reuses_cached_arp_record_on_second_call(tmp_path):
    llm = FakeLLMProvider(json_responses=[
        {"already_public": True, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.9},
        {"trains_on_input": "no", "data_retention": "none", "data_residency": "canada",
         "sub_processors": "disclosed", "human_review": "yes", "extraction_confidence": 0.9},
        {"already_public": True, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.9},
    ])
    store = PreApprovedStore(str(tmp_path / "pb.db"))
    itv = Interview(llm=llm, store=store, http_get=_terms_get)
    usage_inputs = [{"description": "Chercher de l'info publique",
                     "data_description": "information publique sur le web",
                     "automated_decisions": False, "mode": ["prompt"], "result_use": []}]
    itv.assess(request=RequestInfo(numero="IAG-2026-011"), tool_name="ChatGPT",
               usage_inputs=usage_inputs)
    state2 = itv.assess(request=RequestInfo(numero="IAG-2026-012"), tool_name="ChatGPT",
                        usage_inputs=usage_inputs)
    # Second call only queues 1 more LLM response (data classifier) — if the
    # ARP were re-fetched/re-extracted, FakeLLMProvider would raise
    # (no more queued responses for a second extraction call).
    assert state2.tools[0].arp is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/interview/test_orchestrator.py -v`
Expected: FAIL on both new tests with `AssertionError: assert None is not None` (`state.tools[0].arp` is never set today)

- [ ] **Step 3: Write the implementation**

In `policybot/interview/orchestrator.py`, update the import line and `_resolve_arp`/`assess`:

```python
from policybot.models import (
    InterviewState, RequestInfo, ToolRef, Usage, ContractFacts, ArpRecord, IagType,
)
```

```python
def _resolve_arp(self, tool_name: str, iag_type) -> ArpRecord:
    with trace_step(None, "resolve_arp", tool_name=tool_name) as extra:
        cached = self._store.get_arp(tool_name)
        if cached:
            extra["cache"] = "hit"
            return cached
        extra["cache"] = "miss"
        with trace_step(None, "resolve_arp_fetch", tool_name=tool_name) as fetch_extra:
            terms = fetch_terms(tool_name, http_get=self._http_get)
            fetch_extra["found"] = terms is not None
            if terms is None:
                facts = ContractFacts()  # manual-paste fallback handled by the UI layer
            else:
                facts = extract_contract_facts(terms, self._llm)
        arp = build_arp(tool_name, iag_type, facts)
        self._store.save_arp(arp)
        return arp
```

In `assess()`, replace:

```python
            facts = self._resolve_arp(tool_name, iag_type)
```

with:

```python
            arp = self._resolve_arp(tool_name, iag_type)
            state.tools[0].arp = arp
            facts = arp.contract_facts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/interview/test_orchestrator.py -v`
Expected: PASS (all tests, including the 2 new ones)

- [ ] **Step 5: Run the full suite to check for fallout**

Run: `pytest -v`
Expected: PASS — `tests/test_golden_scenarios.py` and `tests/interview/test_graph.py` don't inspect `.arp` today, so this should be a clean addition.

- [ ] **Step 6: Commit**

```bash
git add policybot/interview/orchestrator.py tests/interview/test_orchestrator.py
git commit -m "fix: attach the resolved ArpRecord to InterviewState.tools[].arp"
```

---

### Task 6: Tag `grille.yaml` rules with `category`/`criterion`

**Files:**
- Modify: `policybot/grille/grille.yaml`

**Interfaces:**
- Consumes: nothing new (schema is additive — `Rule.then` is already `dict = Field(default_factory=dict)` in `policybot/grille/rules.py:13`, so new keys need no model change).
- Produces: `rule.then.get("category")` / `rule.then.get("criterion")` on R-07, R-20, R-23, R-24, R-25, R-27 through R-32. Consumed by Task 7 (`evaluate_usage`).

- [ ] **Step 1: Write the failing test**

```python
# add to tests/grille/test_rules.py — it already imports load_rules at the
# top of the file (used by test_load_rules_returns_nonempty), so only the
# new import below is needed.
from policybot.criteria import USAGE_CRITERIA


def test_rules_tagged_with_usage_criteria_use_exact_names():
    valid_criteria = {name for _, name, _ in USAGE_CRITERIA}
    rules = load_rules()
    tagged = [r for r in rules if "criterion" in r.then]
    assert tagged, "expected at least one rule tagged with a criterion"
    for rule in tagged:
        assert rule.then["criterion"] in valid_criteria, (
            f"{rule.id} criterion {rule.then['criterion']!r} not in USAGE_CRITERIA"
        )
        assert "category" in rule.then, f"{rule.id} has criterion but no category"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/grille/test_rules.py::test_rules_tagged_with_usage_criteria_use_exact_names -v`
Expected: FAIL — `assert tagged` fails, no rule has a `"criterion"` key yet

- [ ] **Step 3: Write the implementation**

Replace `policybot/grille/grille.yaml` in full:

```yaml
# Starter rules of thumb. Officers extend this file; it is data, not code.
# Each rule runs only for usages the matrix marks PERMIS / OBLIGATOIRE.
# `category`/`criterion` (when present) rattach a rule to one of the 11 fixed
# Partie B criteria in policybot.criteria.USAGE_CRITERIA — engine.py uses
# them to build Usage.partie_b. Rules without these keys still affect the
# aggregate risk_level/verdict/conditions but have no dedicated Partie B row.
- id: R-07
  when:
    trains_on_input: ["yes", "unknown"]
    data_classification: ["Protégé A", "Protégé B", "Protégé C"]
  then:
    category: "Gestion des données"
    criterion: "Utilisation de données pour entraînement"
    risk_level: "Élevé"
    recommendation: "Autoriser_avec_conditions"
    conditions: ["Confirmer l'opt-out d'entraînement auprès du fournisseur."]
- id: R-12
  when:
    data_residency: ["us", "other", "unknown"]
    data_classification: ["Protégé A", "Protégé B"]
  then:
    risk_level: "Modéré"
    recommendation: "Autoriser_avec_conditions"
    conditions: ["Vérifier l'hébergement des données au Québec."]
- id: R-20
  when:
    automated_decisions: ["True"]
  then:
    category: "Éthique et fiabilité des résultats"
    criterion: "Supervision humaine insuffisante"
    risk_level: "Élevé"
    recommendation: "Escalader"
    conditions: ["Décision automatisée affectant des individus — supervision humaine requise."]
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
- id: R-23
  when:
    human_review: ["no", "unknown"]
    rens_personnels: ["True"]
  then:
    category: "Éthique et fiabilité des résultats"
    criterion: "Supervision humaine insuffisante"
    risk_level: "Élevé"
    recommendation: "Autoriser_avec_conditions"
    conditions: ["Aucune révision humaine confirmée chez le fournisseur pour des renseignements personnels — prévoir une validation manuelle interne."]
- id: R-24
  when:
    rens_personnels: ["True"]
    data_residency: ["us", "other", "unknown"]
  then:
    category: "Gestion des données"
    criterion: "Compatibilité avec la LAI/PRP"
    risk_level: "Élevé"
    recommendation: "Escalader"
    conditions: ["Renseignements personnels traités hors Québec — valider la conformité LAI/PRP avant autorisation."]
- id: R-25
  when:
    needs_officer_confirmation: ["True"]
  then:
    category: "Gestion des données"
    criterion: "Mauvaise classification des données"
    risk_level: "Modéré"
    recommendation: "Autoriser_avec_conditions"
    conditions: ["Classification à faible confiance ou réponse libre « Autre » — confirmation de l'agent SI requise avant de considérer ce résultat final."]
- id: R-26
  when:
    encryption_standard: ["none", "partial", "unknown"]
    data_classification: ["Protégé A", "Protégé B", "Protégé C"]
  then:
    risk_level: "Modéré"
    recommendation: "Autoriser_avec_conditions"
    conditions: ["Confirmer le niveau de chiffrement des données en transit et au repos auprès du fournisseur."]
- id: R-27
  when:
    ip_ownership: ["vendor", "unclear", "unknown"]
    data_classification: ["Protégé A", "Protégé B", "Protégé C"]
  then:
    category: "Éthique et fiabilité des résultats"
    criterion: "Propriété intellectuelle du contenu généré"
    risk_level: "Modéré"
    recommendation: "Autoriser_avec_conditions"
    conditions: ["Le fournisseur pourrait revendiquer des droits sur le contenu généré — vérifier les clauses de propriété intellectuelle avant publication ou usage externe."]
- id: R-28
  when: {}
  then:
    category: "Éthique et fiabilité des résultats"
    criterion: "Hallucinations et erreurs factuelles"
    conditions: ["Rappel : les contenus générés peuvent contenir des erreurs factuelles (hallucinations) — valider l'exactitude avant toute utilisation externe ou décisionnelle."]
- id: R-29
  when: {}
  then:
    category: "Éthique et fiabilité des résultats"
    criterion: "Biais algorithmiques"
    conditions: ["Rappel : les résultats peuvent refléter des biais présents dans les données d'entraînement du modèle — rester vigilant pour les usages à portée décisionnelle."]
- id: R-30
  when: {}
  then:
    category: "Risques organisationnels"
    criterion: "Formation insuffisante du personnel"
    conditions: ["Rappel : s'assurer que la personne utilisatrice a reçu une formation adéquate sur l'usage responsable de cet outil."]
- id: R-31
  when: {}
  then:
    category: "Risques organisationnels"
    criterion: "Dépendance technologique"
    conditions: ["Rappel : éviter la surconfiance envers l'outil — le jugement professionnel demeure requis (dépendance technologique)."]
- id: R-32
  when: {}
  then:
    category: "Risques organisationnels"
    criterion: "Image et réputation institutionnelle"
    conditions: ["Rappel : valider que tout contenu généré associé à l'UQAM respecte les standards d'image et de qualité institutionnels, essentiels pour la réputation de l'organisation, avant diffusion publique."]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/grille/test_rules.py::test_rules_tagged_with_usage_criteria_use_exact_names -v`
Expected: PASS

- [ ] **Step 5: Run the full suite to check for fallout**

Run: `pytest -v`
Expected: PASS — adding dict keys that nothing reads yet (Task 7 wires the read side) must not change any existing behavior; `evaluate_rules`/`highest_risk` only ever read `risk_level`/`recommendation`/`conditions`.

- [ ] **Step 6: Commit**

```bash
git add policybot/grille/grille.yaml tests/grille/test_rules.py
git commit -m "feat: tag grille.yaml rules with their Partie B category/criterion"
```

---

### Task 7: Populate `Usage.partie_b` in `evaluate_usage()`

**Files:**
- Modify: `policybot/grille/engine.py`
- Test: `tests/grille/test_engine.py` (extended)

**Interfaces:**
- Consumes: `USAGE_CRITERIA` (Task 1), tagged rules (Task 6).
- Produces: `evaluate_usage(...)` now returns a `Usage` whose `.partie_b` holds exactly 11 `RiskFactor` rows (one per `USAGE_CRITERIA` entry, in order) whenever the matrix result isn't `INTERDIT`. On `INTERDIT`, `.partie_b` stays `[]` (unchanged, existing test locks this in). Consumed by Task 8 (renderer).

- [ ] **Step 1: Write the failing tests**

Add to `tests/grille/test_engine.py`:

```python
def test_partie_b_has_eleven_fixed_criteria():
    from policybot.criteria import USAGE_CRITERIA
    usage = Usage(data_classification="Non classifié")
    out = evaluate_usage(usage, ContractFacts(trains_on_input="no"), iag_type="publique")
    assert len(out.partie_b) == 11
    assert {c.criterion for c in out.partie_b} == {name for _, name, _ in USAGE_CRITERIA}


def test_partie_b_training_criterion_reflects_r07():
    usage = Usage(data_classification="Protégé B")
    facts = ContractFacts(trains_on_input="yes")
    out = evaluate_usage(usage, facts, iag_type="circuit_ferme")
    by_criterion = {c.criterion: c for c in out.partie_b}
    assert by_criterion["Utilisation de données pour entraînement"].inherent == "E"


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
    out = evaluate_usage(usage, ContractFacts(trains_on_input="no"), iag_type="publique")
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/grille/test_engine.py -v`
Expected: FAIL on the 4 new tests — `out.partie_b` is always `[]` today regardless of matrix result.

- [ ] **Step 3: Write the implementation**

Replace `policybot/grille/engine.py` in full:

```python
# policybot/grille/engine.py
from __future__ import annotations
from policybot.models import (
    Usage, ContractFacts, IagType, GlobalResult, RiskLevel, Recommendation, RiskFactor,
)
from policybot.criteria import USAGE_CRITERIA
from policybot.grille.matrix import evaluate_matrix
from policybot.grille.rules import Rule, load_rules, evaluate_rules, highest_risk, RISK_ORDER

_REC_ORDER = {"Autoriser": 0, "Autoriser_avec_conditions": 1, "Escalader": 2, "Refuser": 3}
_LETTER_FROM_LEVEL = {"Faible": "F", "Modéré": "M", "Élevé": "E", "Critique": "C"}
_LETTER_ORDER = {"F": 0, "M": 1, "E": 2, "C": 3}
_BASE_RISK_BY_CLASSIFICATION = {
    "Non classifié": "F", "Protégé A": "F", "Protégé B": "M", "Protégé C": "E",
}


def _build_partie_b(usage: Usage, triggered: list[Rule]) -> list[RiskFactor]:
    """Fold the triggered rules into the 11 fixed Partie B rows. A criterion
    with no tagged rule (or no matching rule) defaults to 'F' — no risk
    signal found; the always-on advisories (R-28..R-32) have no risk_level
    of their own and default to 'M', a neutral flag that PolicyBot always
    surfaces this generic risk without claiming a specific severity."""
    by_criterion: dict[str, list[str]] = {}
    for rule in triggered:
        criterion = rule.then.get("criterion")
        if criterion is None:
            continue
        level = rule.then.get("risk_level")
        letter = _LETTER_FROM_LEVEL[level] if level else "M"
        by_criterion.setdefault(criterion, []).append(letter)

    rows = []
    for category, criterion, _description in USAGE_CRITERIA:
        if criterion == "Fuite de données confidentielles":
            letter = _BASE_RISK_BY_CLASSIFICATION[usage.data_classification]
        else:
            letters = by_criterion.get(criterion, [])
            letter = max(letters, key=lambda l: _LETTER_ORDER[l]) if letters else "F"
        rows.append(RiskFactor(
            category=category, criterion=criterion,
            inherent=letter, residual=letter, origin="rule",
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/grille/test_engine.py -v`
Expected: PASS (all tests, including the 5 new/existing ones — note `test_interdit_short_circuits_to_refuser`'s pre-existing `assert out.partie_b == []` still holds)

- [ ] **Step 5: Run the full suite to check for fallout**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add policybot/grille/engine.py tests/grille/test_engine.py
git commit -m "feat: populate Usage.partie_b with the 11 fixed Partie B criteria"
```

---

### Task 8: Rewrite `report/renderer.py` — row merging and category grouping

**Files:**
- Modify: `policybot/report/renderer.py`
- Test: `tests/report/test_renderer.py` (extended)

**Interfaces:**
- Consumes: `ARP_CRITERIA`, `USAGE_CRITERIA` (Task 1), `ToolRef.arp` (Task 5), `Usage.partie_b` (Task 7).
- Produces: `render_html(state)` unchanged signature; the Jinja context gains `arp_tables` (`list[{"tool_name": str, "groups": list[tuple[str, list[dict]]]}]`) and `usage_tables` (`list[{"usage": Usage, "index": int, "groups": list[tuple[str, list[dict]]]}]`). Each row dict has keys `criterion`, `description`, `inherent`, `mitigation`, `residual`, `responsable`, `observations` (the last 5 are `None`/`""` when no computed `RiskFactor` exists for that criterion). Consumed by Task 9 (template).

- [ ] **Step 1: Write the failing tests**

Add to `tests/report/test_renderer.py`:

```python
def test_render_contains_identification_section():
    html = render_html(_state())
    assert "Identification" in html
    assert "Numéro demande" in html


def test_render_contains_all_thirteen_arp_criteria():
    from policybot.criteria import ARP_CRITERIA
    html = render_html(_state())
    for _, criterion, _ in ARP_CRITERIA:
        assert criterion in html, f"missing ARP criterion: {criterion}"


def test_render_contains_all_eleven_usage_criteria():
    from policybot.criteria import USAGE_CRITERIA
    html = render_html(_state())
    for _, criterion, _ in USAGE_CRITERIA:
        assert criterion in html, f"missing usage criterion: {criterion}"


def test_render_contains_partie_c_conditions():
    state = _state()
    state.result_global.conditions = ["Vérifier l'hébergement des données au Québec."]
    html = render_html(state)
    assert "Vérifier l'hébergement des données au Québec." in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/report/test_renderer.py -v`
Expected: FAIL on all 4 new tests — the current template has no Identification section, no Partie A table, no per-criterion Partie B rows, and drops `result_global.conditions` entirely.

- [ ] **Step 3: Write the implementation**

Replace `policybot/report/renderer.py` in full:

```python
from __future__ import annotations
import os
from itertools import groupby
from jinja2 import Environment, FileSystemLoader, select_autoescape
from policybot.models import InterviewState, RiskFactor
from policybot.criteria import ARP_CRITERIA, USAGE_CRITERIA

_TEMPLATES = os.path.join(os.path.dirname(__file__), "templates")
_env = Environment(
    loader=FileSystemLoader(_TEMPLATES, encoding="utf-8"),
    autoescape=select_autoescape(["html", "j2"]),
)


def _merge_rows(criteria_table: list[tuple[str, str, str]],
                 factors: list[RiskFactor]) -> list[dict]:
    """Overlay computed RiskFactor data onto the fixed, document-ordered
    criteria table. Criteria with no matching RiskFactor (no automated
    signal available) render with blank risk/mitigation/observations."""
    by_criterion = {f.criterion: f for f in factors}
    rows = []
    for category, criterion, description in criteria_table:
        factor = by_criterion.get(criterion)
        rows.append({
            "category": category,
            "criterion": criterion,
            "description": description,
            "inherent": factor.inherent if factor else None,
            "mitigation": factor.mitigation if factor else "",
            "residual": factor.residual if factor else None,
            "responsable": factor.responsable if factor else "",
            "observations": factor.observations if factor else "",
        })
    return rows


def _group_by_category(rows: list[dict]) -> list[tuple[str, list[dict]]]:
    # itertools.groupby (not Jinja's `groupby` filter, which re-sorts by key
    # and would break the document's category order) — safe here because
    # criteria_table is already grouped by category, in document order.
    return [(category, list(group)) for category, group in groupby(rows, key=lambda r: r["category"])]


def render_html(state: InterviewState) -> str:
    arp_tables = [
        {
            "tool_name": tool.name,
            "groups": _group_by_category(
                _merge_rows(ARP_CRITERIA, tool.arp.criteria if tool.arp else [])
            ),
        }
        for tool in state.tools
    ]
    usage_tables = [
        {
            "usage": usage,
            "index": i + 1,
            "groups": _group_by_category(_merge_rows(USAGE_CRITERIA, usage.partie_b)),
        }
        for i, usage in enumerate(state.usages)
    ]
    return _env.get_template("report.html.j2").render(
        state=state, arp_tables=arp_tables, usage_tables=usage_tables,
    )


def html_to_pdf(html: str) -> bytes:
    try:
        from weasyprint import HTML  # optional dependency
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "WeasyPrint non installé. `pip install policybot[pdf]` "
            "(nécessite les bibliothèques GTK sur Windows)."
        ) from exc
    return HTML(string=html).write_pdf()  # pragma: no cover
```

Note: Step 3 alone will not turn the tests green — the template (Task 9) still needs to actually render `arp_tables`/`usage_tables`/`state.result_global.conditions`. That's expected; both tasks land together in the TDD cycle below.

- [ ] **Step 4: Run tests to verify they still fail (template not updated yet)**

Run: `pytest tests/report/test_renderer.py -v`
Expected: Still FAIL on the same 4 tests — `render_html` now computes the right data, but `report.html.j2` doesn't use `arp_tables`/`usage_tables`/`state.result_global.conditions` yet. Continue to Task 9 before committing.

---

### Task 9: Rewrite `report.html.j2` template

**Files:**
- Modify: `policybot/report/templates/report.html.j2`

**Interfaces:**
- Consumes: `state`, `arp_tables`, `usage_tables` from Task 8's `render_html`.
- Produces: final HTML string with Identification, Partie A, Partie B, Partie C sections.

- [ ] **Step 1: Write the implementation**

Replace `policybot/report/templates/report.html.j2` in full:

```html
<article>
  <h1>Rapport de recommandation — PolicyBot</h1>
  <p class="disclaimer"><strong>PolicyBot recommande ; il n'autorise pas.</strong>
     Ce rapport requiert la validation et l'autorisation de l'autorité désignée.</p>

  <section>
    <h2>Identification</h2>
    <table>
      <tr><th>Numéro demande</th><td>{{ state.request.numero }}</td></tr>
      <tr><th>Numéro grille d'évaluation</th><td></td></tr>
      <tr><th>Outil évalué</th><td>
        {% for t in state.tools %}{{ t.name }}{% if not loop.last %}, {% endif %}{% endfor %}
      </td></tr>
      <tr><th>Analyste SI</th><td></td></tr>
      <tr><th>Date</th><td>{{ state.request.date or "" }}</td></tr>
    </table>
  </section>

  <section>
    <h2>Partie A — Analyse des risques du produit (ARP)</h2>
    <p>L'ARP évalue l'outil en tant que produit, indépendamment des usages
       spécifiques. Elle porte sur la sécurité, la souveraineté et les
       conditions contractuelles du fournisseur.</p>
    {% for table in arp_tables %}
    <h3>Outil : {{ table.tool_name }}</h3>
    <table class="risk-table">
      <tr>
        <th>Critère</th><th>Description / Question d'évaluation</th>
        <th>Risque inhérent</th><th>Mesures de mitigation</th>
        <th>Risque résiduel</th><th>Responsable</th><th>Observations / Constats</th>
      </tr>
      {% for category, rows in table.groups %}
      <tr class="category-row"><td colspan="7"><strong>{{ category }}</strong></td></tr>
      {% for row in rows %}
      <tr>
        <td>{{ row.criterion }}</td>
        <td>{{ row.description }}</td>
        <td>{{ row.inherent or "—" }}</td>
        <td>{{ row.mitigation }}</td>
        <td>{{ row.residual or "—" }}</td>
        <td>{{ row.responsable }}</td>
        <td>{{ row.observations }}</td>
      </tr>
      {% endfor %}
      {% endfor %}
    </table>
    {% endfor %}
  </section>

  <section>
    <h2>Partie B — Évaluation des risques par usage</h2>
    <p>Une section par usage documenté dans la fiche de qualification. Si des
       renseignements personnels sont impliqués dans un usage, une ÉFVP-R
       distincte est requise.</p>
    {% for table in usage_tables %}
    <h3>Usage {{ table.index }} : {{ table.usage.description }}</h3>
    <p>
      <strong>Classification des données :</strong> {{ table.usage.data_classification }}
      {% if table.usage.needs_officer_confirmation %}⚠ à valider{% endif %}
      — <strong>Rens. personnels impliqués :</strong>
      {{ "Oui → ÉFVP-R requise" if table.usage.rens_personnels else "Non" }}
    </p>
    <p><strong>Matrice MCN :</strong> {{ table.usage.matrix_result }}</p>
    <table class="risk-table">
      <tr>
        <th>Critère</th><th>Risque évalué</th>
        <th>Risque inhérent</th><th>Mesures de mitigation</th>
        <th>Risque résiduel</th><th>Responsable</th><th>Observations</th>
      </tr>
      {% for category, rows in table.groups %}
      <tr class="category-row"><td colspan="7"><strong>{{ category }}</strong></td></tr>
      {% for row in rows %}
      <tr>
        <td>{{ row.criterion }}</td>
        <td>{{ row.description }}</td>
        <td>{{ row.inherent or "—" }}</td>
        <td>{{ row.mitigation }}</td>
        <td>{{ row.residual or "—" }}</td>
        <td>{{ row.responsable }}</td>
        <td>{{ row.observations }}</td>
      </tr>
      {% endfor %}
      {% endfor %}
    </table>
    {% endfor %}
  </section>

  <section>
    <h2>Partie C — Synthèse et décision</h2>
    <table>
      <tr><th>Niveau de risque global</th><td>{{ state.result_global.risk_level }}</td></tr>
      <tr><th>ÉFVP-R requise</th><td>{{ "Oui" if state.result_global.efvpr_required else "Non" }}</td></tr>
      <tr><th>Recommandation préliminaire</th><td>{{ state.result_global.recommendation }}</td></tr>
      <tr>
        <th>Conditions / Restrictions proposées</th>
        <td>
          {% if state.result_global.conditions %}
          <ul>{% for c in state.result_global.conditions %}<li>{{ c }}</li>{% endfor %}</ul>
          {% endif %}
        </td>
      </tr>
    </table>
  </section>

  <footer>Recommandation générée par PolicyBot — requiert validation et autorisation par l'autorité désignée.</footer>
</article>
```

- [ ] **Step 2: Run the Task 8 tests to verify they now pass**

Run: `pytest tests/report/test_renderer.py -v`
Expected: PASS (all tests, including the 4 added in Task 8)

- [ ] **Step 3: Run the full suite to check for fallout**

Run: `pytest -v`
Expected: PASS. In particular check `tests/test_golden_scenarios.py` — it asserts `"Refuser" in html`, `"ÉFVP-R requise" in html`, and the disclaimer footer text, all of which remain present verbatim in the new template.

- [ ] **Step 4: Commit**

```bash
git add policybot/report/renderer.py policybot/report/templates/report.html.j2 tests/report/test_renderer.py
git commit -m "feat: render report as Identification/Partie A/Partie B/Partie C mirroring the reference docx"
```

---

### Task 10: Full-suite regression check + golden scenario review

**Files:**
- Read-only check: `tests/test_golden_scenarios.py`, `tests/interview/test_graph.py`, `tests/web/test_routes_*.py`

**Interfaces:**
- Consumes: everything from Tasks 1-9.
- Produces: confidence that the UQAM slide-5 acceptance scenario and the web wizard still work end-to-end with the new report structure.

- [ ] **Step 1: Run the full suite**

Run: `pytest -v`
Expected: PASS, 0 failures. If `tests/web/test_routes_*.py` fails because it asserts on old report substrings (unlikely — those tests exercise wizard steps, not the final report render — verify with `grep -rln "render_html\|report.html" tests/web/`), fix inline before proceeding.

- [ ] **Step 2: Manually eyeball one rendered report**

Run:
```bash
python -c "
from datetime import date
from policybot.models import InterviewState, RequestInfo, ToolRef, Usage, ArpRecord, ContractFacts, GlobalResult
from policybot.contract.arp import build_arp
from policybot.report.renderer import render_html

arp = build_arp('ChatGPT', 'publique', ContractFacts(trains_on_input='yes', data_residency='us'))
state = InterviewState(
    interview_id='demo',
    request=RequestInfo(numero='IAG-2026-999', demandeur='Demo', unite='TI', date=date.today()),
    tools=[ToolRef(name='ChatGPT', iag_type='publique', arp=arp)],
    usages=[Usage(description='Résumer des rapports', data_classification='Protégé B',
                  matrix_result='PERMIS', verdict='Autoriser_avec_conditions',
                  risk_level='Élevé', conditions=['Confirmer opt-out.'])],
    result_global=GlobalResult(risk_level='Élevé', recommendation='Autoriser_avec_conditions',
                               efvpr_required=False, conditions=['Confirmer opt-out.']),
)
html = render_html(state)
open('$CLAUDE_JOB_DIR/tmp/report_preview.html', 'w', encoding='utf-8').write(html)
print('wrote report_preview.html, length', len(html))
"
```
Expected: prints a length, no traceback. Open `report_preview.html` and confirm visually: Identification block, 13-row Partie A table (grouped under 3 category headers), 11-row Partie B table under "Usage 1", Partie C row with "Confirmer opt-out." listed.

- [ ] **Step 3: Commit only if Step 1/2 required fixes**

If no fixes were needed, there is nothing to commit for this task — it's a verification checkpoint, not a code change.

---

## Summary of files touched

- `policybot/criteria.py` (new)
- `policybot/models.py` (4 new `ContractFacts` fields)
- `policybot/contract/arp.py` (prompt + `build_arp` rewrite)
- `policybot/interview/orchestrator.py` (`ArpRecord` wiring)
- `policybot/grille/grille.yaml` (category/criterion tags)
- `policybot/grille/engine.py` (`partie_b` population)
- `policybot/report/renderer.py` (row merge/group helpers)
- `policybot/report/templates/report.html.j2` (full rewrite)
- `tests/test_criteria.py` (new)
- `tests/contract/test_arp.py`, `tests/interview/test_orchestrator.py`, `tests/grille/test_rules.py`, `tests/grille/test_engine.py`, `tests/report/test_renderer.py` (extended)
