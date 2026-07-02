# PolicyBot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-service web tool where a UQAM employee describes an intended generative-AI use, and PolicyBot produces a sourced PDF recommendation (Fiche + Grille) for a security officer to authorize.

**Architecture:** Hybrid — a deterministic Python core (MCN permission matrix + YAML rules) makes every decision; a swappable LLM layer only phrases questions, extracts facts from tool terms, and drafts narrative. A LangGraph state machine drives a multi-usage interview through structured `QuestionSpec` steps, then renders an HTML report (PDF via a thin, integration-flagged wrapper).

**Tech Stack:** Python 3.11+, Pydantic v2, LangGraph, FastAPI + Jinja2, httpx, BeautifulSoup4, PyYAML, SQLite (stdlib `sqlite3`), pytest. LLM via OpenRouter (Gemma) behind an interface; WeasyPrint for optional PDF.

## Global Constraints

- **Python 3.11+**, Pydantic **v2** for all models.
- **Only descriptions/metadata** are ever entered or sent to the LLM — never the sensitive data itself. Do not add fields or prompts that would carry payload data.
- **The MCN permission matrix is an absolute hard gate.** No LLM output or rule may override an `INTERDIT` → `Refuser`.
- **F/M/E/C ratings are proposals, not computed verdicts.** Every `RiskFactor` carries `origin ∈ {rule, llm_proposed}` and `proposed: bool`; officers set finals.
- **All user-facing copy is in French** (labels, questions, report). Code identifiers stay English.
- **LLM access only through the `LLMProvider` interface.** Tests use `FakeLLMProvider`; never call the network in unit tests.
- **Conservative-by-default classification:** when between two data levels, choose the higher (more restrictive) and set `needs_officer_confirmation = True`.
- **Package name:** `policybot`. **Tests:** under `tests/`. Commit after every task.
- Data classification literals are exactly: `"Non classifié"`, `"Protégé A"`, `"Protégé B"`, `"Protégé C"` (with accents).

---

### Task 1: Project scaffolding & dependencies

**Files:**
- Create: `pyproject.toml`
- Create: `policybot/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/test_smoke.py`

**Interfaces:**
- Consumes: nothing.
- Produces: an installable `policybot` package and a working `pytest` command.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_smoke.py
import policybot


def test_package_version():
    assert policybot.__version__ == "0.1.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'policybot'` (or missing `__version__`).

- [ ] **Step 3: Create the package and config**

```toml
# pyproject.toml
[project]
name = "policybot"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.6",
    "langgraph>=0.2",
    "fastapi>=0.110",
    "uvicorn>=0.29",
    "jinja2>=3.1",
    "httpx>=0.27",
    "beautifulsoup4>=4.12",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
pdf = ["weasyprint>=60"]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["policybot*"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

```python
# policybot/__init__.py
__version__ = "0.1.0"
```

```python
# tests/__init__.py
```

- [ ] **Step 4: Install and run the test**

Run: `pip install -e ".[dev]" && pytest tests/test_smoke.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml policybot/__init__.py tests/__init__.py tests/test_smoke.py
git commit -m "chore: scaffold policybot package"
```

---

### Task 2: Domain models

**Files:**
- Create: `policybot/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces (imported by nearly every later task):
  - Type aliases: `IagType`, `DataClass`, `MatrixResult`, `RiskLetter`, `RiskLevel`, `Recommendation`.
  - Models: `QuestionOption`, `QuestionSpec`, `ContractFacts`, `RiskFactor`, `ArpRecord`, `PreApprovedRecord`, `RequestInfo`, `ToolRef`, `Usage`, `InterviewState`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
from datetime import date
from policybot.models import (
    QuestionSpec, QuestionOption, RiskFactor, Usage, InterviewState, RequestInfo,
)


def test_questionspec_defaults():
    q = QuestionSpec(
        id="data_description",
        header="Type de données",
        question="Quel type de données?",
        options=[QuestionOption(label="Info publique", description="Web, docs publics")],
    )
    assert q.multi_select is False
    assert q.allow_other is True
    assert q.options[0].label == "Info publique"


def test_riskfactor_requires_origin_and_proposed():
    rf = RiskFactor(
        category="Gestion des données", criterion="Fuite de données",
        inherent="E", residual="M", origin="rule", proposed=True,
    )
    assert rf.origin == "rule"
    assert rf.proposed is True


def test_interviewstate_starts_empty():
    st = InterviewState(interview_id="abc", request=RequestInfo(numero="IAG-2026-001"))
    assert st.status == "in_progress"
    assert st.usages == []
    assert st.tools == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'policybot.models'`.

- [ ] **Step 3: Write the models**

```python
# policybot/models.py
from __future__ import annotations
from datetime import date
from typing import Literal, Optional
from pydantic import BaseModel, Field

IagType = Literal["publique", "circuit_ferme", "souveraine", "gouvernementale"]
DataClass = Literal["Non classifié", "Protégé A", "Protégé B", "Protégé C"]
MatrixResult = Literal["PERMIS", "INTERDIT", "OBLIGATOIRE"]
RiskLetter = Literal["F", "M", "E", "C"]
RiskLevel = Literal["Faible", "Modéré", "Élevé", "Critique"]
Recommendation = Literal[
    "Autoriser", "Autoriser_avec_conditions", "Refuser", "Escalader"
]


class QuestionOption(BaseModel):
    label: str
    description: str = ""


class QuestionSpec(BaseModel):
    id: str
    header: str
    question: str
    options: list[QuestionOption] = Field(default_factory=list)
    multi_select: bool = False
    allow_other: bool = True


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


class RiskFactor(BaseModel):
    category: str
    criterion: str
    inherent: RiskLetter
    mitigation: str = ""
    residual: RiskLetter
    responsable: str = ""
    observations: str = ""
    origin: Literal["rule", "llm_proposed"]
    proposed: bool = True


class ArpRecord(BaseModel):
    tool_name: str
    iag_type: IagType
    contract_facts: ContractFacts
    criteria: list[RiskFactor] = Field(default_factory=list)
    terms_snapshot: Optional[str] = None
    fetched_at: Optional[date] = None
    expires_at: Optional[date] = None
    approved_by: Optional[str] = None


class PreApprovedRecord(BaseModel):
    id: str
    tool_name: str
    data_classification: DataClass
    iag_type: IagType
    verdict: Recommendation
    risk_level: RiskLevel
    conditions: list[str] = Field(default_factory=list)
    arp_ref: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[date] = None
    expires_at: Optional[date] = None


class RequestInfo(BaseModel):
    numero: str
    demandeur: str = ""
    unite: str = ""
    date: Optional[date] = None


class ToolRef(BaseModel):
    name: str
    vendor: Optional[str] = None
    iag_type: Optional[IagType] = None
    arp: Optional[ArpRecord] = None


class Usage(BaseModel):
    description: str = ""
    tool_ref: str = ""
    raw_answers: dict = Field(default_factory=dict)
    data_classification: Optional[DataClass] = None
    rens_personnels: bool = False
    efvpr_required: bool = False
    mode: list[Literal["prompt", "api"]] = Field(default_factory=list)
    result_use: list[str] = Field(default_factory=list)
    automated_decisions: bool = False
    classifier_confidence: float = 0.0
    needs_officer_confirmation: bool = False
    matrix_result: Optional[MatrixResult] = None
    partie_b: list[RiskFactor] = Field(default_factory=list)
    verdict: Optional[Recommendation] = None
    risk_level: Optional[RiskLevel] = None
    conditions: list[str] = Field(default_factory=list)


class GlobalResult(BaseModel):
    risk_level: Optional[RiskLevel] = None
    efvpr_required: bool = False
    recommendation: Optional[Recommendation] = None
    conditions: list[str] = Field(default_factory=list)
    rationale_narrative: str = ""


class InterviewState(BaseModel):
    interview_id: str
    status: Literal["in_progress", "awaiting_terms", "complete"] = "in_progress"
    request: RequestInfo
    tools: list[ToolRef] = Field(default_factory=list)
    usages: list[Usage] = Field(default_factory=list)
    result_global: GlobalResult = Field(default_factory=GlobalResult)
    audit: dict = Field(default_factory=lambda: {"question_log": [], "timestamps": {}})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add policybot/models.py tests/test_models.py
git commit -m "feat: add domain models"
```

---

### Task 3: MCN permission matrix (hard gate)

**Files:**
- Create: `policybot/grille/__init__.py`
- Create: `policybot/grille/matrix.py`
- Test: `tests/grille/__init__.py`, `tests/grille/test_matrix.py`

**Interfaces:**
- Consumes: `DataClass`, `IagType`, `MatrixResult` from `policybot.models`.
- Produces: `evaluate_matrix(data_classification: DataClass, iag_type: IagType) -> MatrixResult`.

- [ ] **Step 1: Write the failing test (exhaustive — all 16 cells)**

```python
# tests/grille/test_matrix.py
import pytest
from policybot.grille.matrix import evaluate_matrix

EXPECTED = {
    ("Non classifié", "publique"): "PERMIS",
    ("Non classifié", "circuit_ferme"): "PERMIS",
    ("Non classifié", "souveraine"): "PERMIS",
    ("Non classifié", "gouvernementale"): "PERMIS",
    ("Protégé A", "publique"): "INTERDIT",
    ("Protégé A", "circuit_ferme"): "PERMIS",
    ("Protégé A", "souveraine"): "PERMIS",
    ("Protégé A", "gouvernementale"): "PERMIS",
    ("Protégé B", "publique"): "INTERDIT",
    ("Protégé B", "circuit_ferme"): "PERMIS",
    ("Protégé B", "souveraine"): "PERMIS",
    ("Protégé B", "gouvernementale"): "PERMIS",
    ("Protégé C", "publique"): "INTERDIT",
    ("Protégé C", "circuit_ferme"): "INTERDIT",
    ("Protégé C", "souveraine"): "INTERDIT",
    ("Protégé C", "gouvernementale"): "OBLIGATOIRE",
}


@pytest.mark.parametrize("key,expected", EXPECTED.items())
def test_matrix_all_cells(key, expected):
    data_class, iag_type = key
    assert evaluate_matrix(data_class, iag_type) == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/grille/test_matrix.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the matrix**

```python
# policybot/grille/__init__.py
```

```python
# policybot/grille/matrix.py
from policybot.models import DataClass, IagType, MatrixResult

# MCN guide — Cadre d'utilisation de l'IA générative (slide 4).
_MATRIX: dict[DataClass, dict[IagType, MatrixResult]] = {
    "Non classifié": {
        "publique": "PERMIS", "circuit_ferme": "PERMIS",
        "souveraine": "PERMIS", "gouvernementale": "PERMIS",
    },
    "Protégé A": {
        "publique": "INTERDIT", "circuit_ferme": "PERMIS",
        "souveraine": "PERMIS", "gouvernementale": "PERMIS",
    },
    "Protégé B": {
        "publique": "INTERDIT", "circuit_ferme": "PERMIS",
        "souveraine": "PERMIS", "gouvernementale": "PERMIS",
    },
    "Protégé C": {
        "publique": "INTERDIT", "circuit_ferme": "INTERDIT",
        "souveraine": "INTERDIT", "gouvernementale": "OBLIGATOIRE",
    },
}


def evaluate_matrix(data_classification: DataClass, iag_type: IagType) -> MatrixResult:
    """Hard gate: (data class × tool type) → PERMIS / INTERDIT / OBLIGATOIRE.

    Sanctioned MCN policy. No caller may override an INTERDIT result.
    """
    return _MATRIX[data_classification][iag_type]
```

```python
# tests/grille/__init__.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/grille/test_matrix.py -v`
Expected: PASS (16 parametrized cases).

- [ ] **Step 5: Commit**

```bash
git add policybot/grille/__init__.py policybot/grille/matrix.py tests/grille/
git commit -m "feat: add MCN permission matrix hard gate"
```

---

### Task 4: Grille rule engine (YAML rules of thumb)

**Files:**
- Create: `policybot/grille/rules.py`
- Create: `policybot/grille/grille.yaml`
- Test: `tests/grille/test_rules.py`

**Interfaces:**
- Consumes: nothing from other tasks (operates on plain dicts).
- Produces:
  - `Rule` (pydantic model: `id: str`, `when: dict[str, list[str]]`, `then: dict`).
  - `load_rules(path: str | None = None) -> list[Rule]`.
  - `evaluate_rules(facts: dict, rules: list[Rule]) -> list[Rule]` (returns triggered rules, priority order = file order).
  - `RISK_ORDER: dict[str, int]` mapping `RiskLevel` → severity int.
  - `highest_risk(levels: list[str]) -> str` returning the most severe `RiskLevel` (default `"Faible"`).

- [ ] **Step 1: Write the failing test**

```python
# tests/grille/test_rules.py
from policybot.grille.rules import (
    load_rules, evaluate_rules, highest_risk, Rule,
)


def test_load_rules_returns_nonempty():
    rules = load_rules()
    assert len(rules) >= 1
    assert all(isinstance(r, Rule) for r in rules)


def test_training_rule_triggers():
    rules = [Rule(
        id="R-07",
        when={"trains_on_input": ["yes", "unknown"],
              "data_classification": ["Protégé A", "Protégé B", "Protégé C"]},
        then={"risk_level": "Élevé",
              "recommendation": "Autoriser_avec_conditions",
              "conditions": ["Confirmer l'opt-out d'entraînement."]},
    )]
    facts = {"trains_on_input": "yes", "data_classification": "Protégé B"}
    triggered = evaluate_rules(facts, rules)
    assert [r.id for r in triggered] == ["R-07"]


def test_rule_does_not_trigger_when_value_absent():
    rules = [Rule(id="R-07", when={"trains_on_input": ["yes"]}, then={})]
    triggered = evaluate_rules({"trains_on_input": "no"}, rules)
    assert triggered == []


def test_highest_risk_picks_worst():
    assert highest_risk(["Faible", "Élevé", "Modéré"]) == "Élevé"
    assert highest_risk([]) == "Faible"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/grille/test_rules.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the engine and starter rules**

```python
# policybot/grille/rules.py
from __future__ import annotations
import os
import yaml
from pydantic import BaseModel, Field

RISK_ORDER = {"Faible": 0, "Modéré": 1, "Élevé": 2, "Critique": 3}
_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "grille.yaml")


class Rule(BaseModel):
    id: str
    when: dict[str, list[str]] = Field(default_factory=dict)
    then: dict = Field(default_factory=dict)


def load_rules(path: str | None = None) -> list[Rule]:
    with open(path or _DEFAULT_PATH, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or []
    return [Rule(**item) for item in raw]


def evaluate_rules(facts: dict, rules: list[Rule]) -> list[Rule]:
    """Return rules whose every `when` clause matches `facts` (file order)."""
    triggered = []
    for rule in rules:
        if all(str(facts.get(key)) in allowed for key, allowed in rule.when.items()):
            triggered.append(rule)
    return triggered


def highest_risk(levels: list[str]) -> str:
    if not levels:
        return "Faible"
    return max(levels, key=lambda lv: RISK_ORDER.get(lv, 0))
```

```yaml
# policybot/grille/grille.yaml
# Starter rules of thumb. Officers extend this file; it is data, not code.
# Each rule runs only for usages the matrix marks PERMIS / OBLIGATOIRE.
- id: R-07
  when:
    trains_on_input: ["yes", "unknown"]
    data_classification: ["Protégé A", "Protégé B", "Protégé C"]
  then:
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
    risk_level: "Élevé"
    recommendation: "Escalader"
    conditions: ["Décision automatisée affectant des individus — supervision humaine requise."]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/grille/test_rules.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add policybot/grille/rules.py policybot/grille/grille.yaml tests/grille/test_rules.py
git commit -m "feat: add grille rule engine and starter rules"
```

---

### Task 5: Grille engine — per-usage verdict

**Files:**
- Create: `policybot/grille/engine.py`
- Test: `tests/grille/test_engine.py`

**Interfaces:**
- Consumes: `evaluate_matrix` (Task 3); `load_rules`, `evaluate_rules`, `highest_risk` (Task 4); `Usage`, `ContractFacts` (Task 2).
- Produces:
  - `evaluate_usage(usage: Usage, contract_facts: ContractFacts, iag_type: IagType, rules: list[Rule] | None = None) -> Usage` — returns a **copy** of `usage` with `matrix_result`, `verdict`, `risk_level`, `conditions`, `efvpr_required` filled.
  - `synthesize(usages: list[Usage]) -> GlobalResult`.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/grille/test_engine.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the engine**

```python
# policybot/grille/engine.py
from __future__ import annotations
from policybot.models import (
    Usage, ContractFacts, IagType, GlobalResult, RiskLevel, Recommendation,
)
from policybot.grille.matrix import evaluate_matrix
from policybot.grille.rules import Rule, load_rules, evaluate_rules, highest_risk, RISK_ORDER

_REC_ORDER = {"Autoriser": 0, "Autoriser_avec_conditions": 1, "Escalader": 2, "Refuser": 3}


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
        conditions=conditions,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/grille/test_engine.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add policybot/grille/engine.py tests/grille/test_engine.py
git commit -m "feat: add per-usage grille engine and synthesis"
```

---

### Task 6: LLM provider interface + fake + OpenRouter

**Files:**
- Create: `policybot/llm/__init__.py`
- Create: `policybot/llm/provider.py`
- Create: `policybot/llm/fake.py`
- Create: `policybot/llm/openrouter.py`
- Test: `tests/llm/__init__.py`, `tests/llm/test_fake.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces:
  - `LLMProvider` (ABC) with:
    - `complete_json(self, system: str, user: str) -> dict`
    - `draft_text(self, system: str, user: str) -> str`
  - `FakeLLMProvider(json_responses: list[dict] | None = None, text_responses: list[str] | None = None)` — pops responses in FIFO order; records `.calls: list[tuple[str, str]]`.
  - `OpenRouterProvider(api_key: str, model: str = "google/gemma-2-27b-it")` implementing the same interface via httpx.

- [ ] **Step 1: Write the failing test**

```python
# tests/llm/test_fake.py
import pytest
from policybot.llm.fake import FakeLLMProvider
from policybot.llm.provider import LLMProvider


def test_fake_is_a_provider():
    assert isinstance(FakeLLMProvider(), LLMProvider)


def test_fake_returns_queued_json_and_records_calls():
    fake = FakeLLMProvider(json_responses=[{"a": 1}, {"b": 2}])
    assert fake.complete_json("sys", "u1") == {"a": 1}
    assert fake.complete_json("sys", "u2") == {"b": 2}
    assert fake.calls == [("sys", "u1"), ("sys", "u2")]


def test_fake_json_exhausted_raises():
    fake = FakeLLMProvider(json_responses=[{"a": 1}])
    fake.complete_json("s", "u")
    with pytest.raises(IndexError):
        fake.complete_json("s", "u")


def test_fake_draft_text():
    fake = FakeLLMProvider(text_responses=["bonjour"])
    assert fake.draft_text("s", "u") == "bonjour"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/llm/test_fake.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the interface, fake, and OpenRouter impl**

```python
# policybot/llm/__init__.py
```

```python
# policybot/llm/provider.py
from abc import ABC, abstractmethod


class LLMProvider(ABC):
    @abstractmethod
    def complete_json(self, system: str, user: str) -> dict:
        """Return a JSON object the model produced for the prompt."""

    @abstractmethod
    def draft_text(self, system: str, user: str) -> str:
        """Return free-form narrative text."""
```

```python
# policybot/llm/fake.py
from policybot.llm.provider import LLMProvider


class FakeLLMProvider(LLMProvider):
    def __init__(self, json_responses=None, text_responses=None):
        self._json = list(json_responses or [])
        self._text = list(text_responses or [])
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str) -> dict:
        self.calls.append((system, user))
        return self._json.pop(0)

    def draft_text(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self._text.pop(0)
```

```python
# policybot/llm/openrouter.py
import json
import httpx
from policybot.llm.provider import LLMProvider

_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterProvider(LLMProvider):
    """POC provider. Confirm the exact Gemma model slug on OpenRouter."""

    def __init__(self, api_key: str, model: str = "google/gemma-2-27b-it",
                 timeout: float = 60.0):
        self._key = api_key
        self._model = model
        self._client = httpx.Client(timeout=timeout)

    def _chat(self, system: str, user: str, json_mode: bool) -> str:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        resp = self._client.post(
            _URL, headers={"Authorization": f"Bearer {self._key}"}, json=payload
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def complete_json(self, system: str, user: str) -> dict:
        return json.loads(self._chat(system, user, json_mode=True))

    def draft_text(self, system: str, user: str) -> str:
        return self._chat(system, user, json_mode=False)
```

```python
# tests/llm/__init__.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/llm/test_fake.py -v`
Expected: PASS (4 tests). (OpenRouter is not unit-tested — network behind an integration flag.)

- [ ] **Step 5: Commit**

```bash
git add policybot/llm/ tests/llm/
git commit -m "feat: add LLM provider interface, fake, and OpenRouter impl"
```

---

### Task 7: Data classifier

**Files:**
- Create: `policybot/classify/__init__.py`
- Create: `policybot/classify/data_classifier.py`
- Test: `tests/classify/__init__.py`, `tests/classify/test_data_classifier.py`

**Interfaces:**
- Consumes: `LLMProvider` (Task 6); `DataClass` (Task 2).
- Produces:
  - `classify_data(description: str, llm: LLMProvider) -> DataClassification` where `DataClassification` is a pydantic model: `data_classification: DataClass`, `rens_personnels: bool`, `signals: list[str]`, `confidence: float`, `needs_officer_confirmation: bool`.
  - The LLM is asked (via `complete_json`) for signals only:
    `{"already_public": bool, "contains_personal_info": bool, "strategic_sensitive": bool, "internal_nonpublic": bool, "highly_sensitive_secret": bool, "confidence": float}`.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/classify/test_data_classifier.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the classifier**

```python
# policybot/classify/__init__.py
```

```python
# policybot/classify/data_classifier.py
from __future__ import annotations
from pydantic import BaseModel
from policybot.models import DataClass
from policybot.llm.provider import LLMProvider

_SYSTEM = (
    "Tu analyses la DESCRIPTION de données (jamais les données elles-mêmes) qu'un "
    "employé veut soumettre à un outil d'IA. Réponds uniquement en JSON avec les "
    "clés booléennes: already_public, contains_personal_info, strategic_sensitive, "
    "internal_nonpublic, highly_sensitive_secret, et un flottant confidence (0-1)."
)
_CONFIDENCE_FLOOR = 0.6


class DataClassification(BaseModel):
    data_classification: DataClass
    rens_personnels: bool
    signals: list[str]
    confidence: float
    needs_officer_confirmation: bool


def _decide(sig: dict) -> tuple[DataClass, bool]:
    """Deterministic, conservative decision tree over LLM signals.

    Returns (level, defaulted) where `defaulted` marks an ambiguous fallback.
    """
    if sig.get("highly_sensitive_secret"):
        return "Protégé C", False
    if sig.get("contains_personal_info") or sig.get("strategic_sensitive"):
        return "Protégé B", False
    if sig.get("already_public") and not sig.get("internal_nonpublic"):
        return "Non classifié", False
    if sig.get("internal_nonpublic"):
        return "Protégé A", False
    return "Protégé A", True  # conservative default when signals are inconclusive


def classify_data(description: str, llm: LLMProvider) -> DataClassification:
    sig = llm.complete_json(_SYSTEM, description)
    level, defaulted = _decide(sig)
    confidence = float(sig.get("confidence", 0.0))
    signals = [k for k, v in sig.items() if v is True]
    needs_confirm = defaulted or confidence < _CONFIDENCE_FLOOR
    return DataClassification(
        data_classification=level,
        rens_personnels=bool(sig.get("contains_personal_info")),
        signals=signals,
        confidence=confidence,
        needs_officer_confirmation=needs_confirm,
    )
```

```python
# tests/classify/__init__.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/classify/test_data_classifier.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add policybot/classify/__init__.py policybot/classify/data_classifier.py tests/classify/
git commit -m "feat: add data classifier (LLM signals + deterministic tree)"
```

---

### Task 8: Tool-type classifier + tool registry

**Files:**
- Create: `policybot/classify/tool_registry.py`
- Create: `policybot/classify/tool_type.py`
- Test: `tests/classify/test_tool_type.py`

**Interfaces:**
- Consumes: `IagType`, `QuestionSpec`, `QuestionOption` (Task 2).
- Produces:
  - `REGISTRY: dict[str, dict]` — lowercased tool name → `{"iag_type": IagType, "vendor": str, "terms_url": str | None}`.
  - `lookup_tool(name: str) -> dict | None`.
  - `classify_tool_type(name: str) -> IagType | None` — registry-only; `None` means "ask the user".
  - `tool_type_question() -> QuestionSpec` — the disambiguation question for unknown tools.

- [ ] **Step 1: Write the failing test**

```python
# tests/classify/test_tool_type.py
from policybot.classify.tool_type import classify_tool_type, tool_type_question
from policybot.classify.tool_registry import lookup_tool


def test_known_public_tool():
    assert classify_tool_type("ChatGPT") == "publique"
    assert classify_tool_type("claude.ai") == "publique"


def test_known_closed_circuit_tool():
    assert classify_tool_type("Microsoft Copilot Entreprise") == "circuit_ferme"


def test_unknown_tool_returns_none():
    assert classify_tool_type("OutilInconnu 9000") is None


def test_lookup_returns_terms_url():
    entry = lookup_tool("ChatGPT")
    assert entry["terms_url"].startswith("http")


def test_question_has_four_iag_options():
    q = tool_type_question()
    assert len(q.options) == 4
    assert q.multi_select is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/classify/test_tool_type.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the registry and classifier**

```python
# policybot/classify/tool_registry.py
from policybot.models import IagType

REGISTRY: dict[str, dict] = {
    "chatgpt": {"iag_type": "publique", "vendor": "OpenAI",
                "terms_url": "https://openai.com/policies/terms-of-use"},
    "chatgpt pro": {"iag_type": "publique", "vendor": "OpenAI",
                    "terms_url": "https://openai.com/policies/terms-of-use"},
    "claude.ai": {"iag_type": "publique", "vendor": "Anthropic",
                  "terms_url": "https://www.anthropic.com/legal/consumer-terms"},
    "perplexity": {"iag_type": "publique", "vendor": "Perplexity",
                   "terms_url": "https://www.perplexity.ai/hub/legal/terms-of-service"},
    "microsoft copilot entreprise": {"iag_type": "circuit_ferme", "vendor": "Microsoft",
                                     "terms_url": "https://www.microsoft.com/licensing"},
}


def lookup_tool(name: str) -> dict | None:
    return REGISTRY.get(name.strip().lower())
```

```python
# policybot/classify/tool_type.py
from policybot.models import IagType, QuestionSpec, QuestionOption
from policybot.classify.tool_registry import lookup_tool


def classify_tool_type(name: str) -> IagType | None:
    entry = lookup_tool(name)
    return entry["iag_type"] if entry else None


def tool_type_question() -> QuestionSpec:
    return QuestionSpec(
        id="tool_type",
        header="Type d'outil",
        question="Quel type d'outil d'IA générative est-ce ?",
        multi_select=False,
        allow_other=False,
        options=[
            QuestionOption(label="IAG publique",
                           description="Ex. ChatGPT, Claude.ai, Perplexity"),
            QuestionOption(label="IAG circuit fermé",
                           description="Ex. Microsoft Copilot Entreprise"),
            QuestionOption(label="IAG souveraine",
                           description="Hébergée au Québec"),
            QuestionOption(label="IAG gouvernementale",
                           description="Hébergée par l'UQAM / le gouvernement"),
        ],
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/classify/test_tool_type.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add policybot/classify/tool_registry.py policybot/classify/tool_type.py tests/classify/test_tool_type.py
git commit -m "feat: add tool-type classifier and registry"
```

---

### Task 9: Terms fetcher

**Files:**
- Create: `policybot/contract/__init__.py`
- Create: `policybot/contract/fetcher.py`
- Test: `tests/contract/__init__.py`, `tests/contract/test_fetcher.py`, `tests/contract/fixtures/openai_terms.html`

**Interfaces:**
- Consumes: `lookup_tool` (Task 8).
- Produces:
  - `FetchedTerms` (pydantic: `text: str`, `source_url: str`, `fetched_at: date`).
  - `fetch_terms(tool_name: str, http_get: Callable[[str], str] | None = None) -> FetchedTerms | None` — resolves the URL from the registry, fetches HTML via `http_get` (defaults to an httpx-backed getter), strips to text. Returns `None` when no URL is known (caller falls back to manual paste).
  - `html_to_text(html: str) -> str`.

- [ ] **Step 1: Write the fixture and failing test**

```html
<!-- tests/contract/fixtures/openai_terms.html -->
<html><head><title>Terms</title><style>.x{color:red}</style></head>
<body><h1>Terms of Use</h1><p>We may use your content to train our models.</p>
<script>console.log('ignore me')</script></body></html>
```

```python
# tests/contract/test_fetcher.py
import os
from policybot.contract.fetcher import fetch_terms, html_to_text

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "openai_terms.html")


def _fake_get(url):
    with open(FIX, encoding="utf-8") as fh:
        return fh.read()


def test_html_to_text_strips_scripts_and_styles():
    text = html_to_text(open(FIX, encoding="utf-8").read())
    assert "train our models" in text
    assert "ignore me" not in text
    assert "color:red" not in text


def test_fetch_known_tool_returns_terms():
    res = fetch_terms("ChatGPT", http_get=_fake_get)
    assert res is not None
    assert "train our models" in res.text
    assert res.source_url.startswith("http")


def test_fetch_unknown_tool_returns_none():
    assert fetch_terms("OutilInconnu 9000", http_get=_fake_get) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/contract/test_fetcher.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the fetcher**

```python
# policybot/contract/__init__.py
```

```python
# policybot/contract/fetcher.py
from __future__ import annotations
from datetime import date
from typing import Callable, Optional
import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel
from policybot.classify.tool_registry import lookup_tool


class FetchedTerms(BaseModel):
    text: str
    source_url: str
    fetched_at: date


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


def _default_get(url: str) -> str:
    resp = httpx.get(url, timeout=30.0, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


def fetch_terms(
    tool_name: str,
    http_get: Optional[Callable[[str], str]] = None,
) -> Optional[FetchedTerms]:
    entry = lookup_tool(tool_name)
    if not entry or not entry.get("terms_url"):
        return None  # caller falls back to manual paste
    getter = http_get or _default_get
    html = getter(entry["terms_url"])
    return FetchedTerms(
        text=html_to_text(html),
        source_url=entry["terms_url"],
        fetched_at=date.today(),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/contract/test_fetcher.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add policybot/contract/__init__.py policybot/contract/fetcher.py tests/contract/
git commit -m "feat: add terms fetcher with registry URL resolution"
```

---

### Task 10: ARP extractor (contract facts + Partie A)

**Files:**
- Create: `policybot/contract/arp.py`
- Test: `tests/contract/test_arp.py`

**Interfaces:**
- Consumes: `LLMProvider` (Task 6); `ContractFacts`, `ArpRecord`, `RiskFactor`, `IagType` (Task 2); `FetchedTerms` (Task 9).
- Produces:
  - `extract_contract_facts(terms: FetchedTerms, llm: LLMProvider) -> ContractFacts`.
  - `build_arp(tool_name: str, iag_type: IagType, facts: ContractFacts) -> ArpRecord` — derives Partie A `RiskFactor`s (`origin="rule"`) from the normalized facts.

- [ ] **Step 1: Write the failing test**

```python
# tests/contract/test_arp.py
from datetime import date
from policybot.llm.fake import FakeLLMProvider
from policybot.contract.fetcher import FetchedTerms
from policybot.contract.arp import extract_contract_facts, build_arp


def _terms():
    return FetchedTerms(text="...", source_url="http://x", fetched_at=date.today())


def test_extract_maps_llm_output_to_contractfacts():
    llm = FakeLLMProvider(json_responses=[{
        "trains_on_input": "yes", "data_retention": "indefinite",
        "data_residency": "us", "sub_processors": "undisclosed",
        "human_review": "no", "extraction_confidence": 0.8,
    }])
    facts = extract_contract_facts(_terms(), llm)
    assert facts.trains_on_input == "yes"
    assert facts.data_residency == "us"
    assert facts.source_url == "http://x"
    assert facts.extraction_confidence == 0.8


def test_build_arp_flags_training_as_high_risk():
    facts = extract_contract_facts.__wrapped__ if False else None  # noqa
    from policybot.models import ContractFacts
    arp = build_arp("ChatGPT", "publique", ContractFacts(trains_on_input="yes"))
    training = [c for c in arp.criteria if "entraîn" in c.criterion.lower()]
    assert training and training[0].inherent == "E"
    assert all(c.origin == "rule" for c in arp.criteria)
    assert arp.iag_type == "publique"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/contract/test_arp.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the extractor**

```python
# policybot/contract/arp.py
from __future__ import annotations
from policybot.models import ContractFacts, ArpRecord, RiskFactor, IagType
from policybot.contract.fetcher import FetchedTerms
from policybot.llm.provider import LLMProvider

_SYSTEM = (
    "Tu extrais des faits normalisés des conditions d'utilisation d'un outil d'IA. "
    "Réponds uniquement en JSON avec: trains_on_input (yes|no|opt_out_available|"
    "unknown), data_retention (none|limited|indefinite|unknown), data_residency "
    "(canada|us|eu|other|unknown), sub_processors (disclosed|undisclosed|unknown), "
    "human_review (yes|no|unknown), extraction_confidence (0-1)."
)


def extract_contract_facts(terms: FetchedTerms, llm: LLMProvider) -> ContractFacts:
    raw = llm.complete_json(_SYSTEM, terms.text[:12000])
    return ContractFacts(
        trains_on_input=raw.get("trains_on_input", "unknown"),
        data_retention=raw.get("data_retention", "unknown"),
        data_residency=raw.get("data_residency", "unknown"),
        sub_processors=raw.get("sub_processors", "unknown"),
        human_review=raw.get("human_review", "unknown"),
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

    return ArpRecord(
        tool_name=tool_name, iag_type=iag_type, contract_facts=facts,
        criteria=criteria, terms_snapshot=facts.source_url,
        fetched_at=facts.fetched_at,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/contract/test_arp.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add policybot/contract/arp.py tests/contract/test_arp.py
git commit -m "feat: add ARP contract-fact extractor and Partie A builder"
```

---

### Task 11: Pre-approved store (SQLite)

**Files:**
- Create: `policybot/preapproved/__init__.py`
- Create: `policybot/preapproved/store.py`
- Test: `tests/preapproved/__init__.py`, `tests/preapproved/test_store.py`

**Interfaces:**
- Consumes: `ArpRecord`, `PreApprovedRecord`, `DataClass`, `IagType` (Task 2).
- Produces:
  - `PreApprovedStore(db_path: str)` with:
    - `save_arp(arp: ArpRecord) -> None`
    - `get_arp(tool_name: str) -> ArpRecord | None`
    - `save_decision(rec: PreApprovedRecord) -> None`
    - `find_decision(tool_name: str, data_classification: DataClass, iag_type: IagType, today: date | None = None) -> PreApprovedRecord | None` (ignores rows with `expires_at` in the past).

- [ ] **Step 1: Write the failing test**

```python
# tests/preapproved/test_store.py
from datetime import date, timedelta
from policybot.models import ArpRecord, ContractFacts, PreApprovedRecord
from policybot.preapproved.store import PreApprovedStore


def _store(tmp_path):
    return PreApprovedStore(str(tmp_path / "pb.db"))


def test_save_and_get_arp(tmp_path):
    store = _store(tmp_path)
    arp = ArpRecord(tool_name="ChatGPT", iag_type="publique", contract_facts=ContractFacts())
    store.save_arp(arp)
    got = store.get_arp("ChatGPT")
    assert got is not None and got.tool_name == "ChatGPT"


def test_find_decision_matches_current(tmp_path):
    store = _store(tmp_path)
    rec = PreApprovedRecord(
        id="d1", tool_name="Copilot", data_classification="Protégé A",
        iag_type="circuit_ferme", verdict="Autoriser", risk_level="Faible",
        expires_at=date.today() + timedelta(days=30),
    )
    store.save_decision(rec)
    found = store.find_decision("Copilot", "Protégé A", "circuit_ferme")
    assert found is not None and found.id == "d1"


def test_find_decision_ignores_expired(tmp_path):
    store = _store(tmp_path)
    rec = PreApprovedRecord(
        id="d2", tool_name="Copilot", data_classification="Protégé A",
        iag_type="circuit_ferme", verdict="Autoriser", risk_level="Faible",
        expires_at=date.today() - timedelta(days=1),
    )
    store.save_decision(rec)
    assert store.find_decision("Copilot", "Protégé A", "circuit_ferme") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/preapproved/test_store.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the store**

```python
# policybot/preapproved/__init__.py
```

```python
# policybot/preapproved/store.py
from __future__ import annotations
import sqlite3
from datetime import date
from policybot.models import ArpRecord, PreApprovedRecord, DataClass, IagType


class PreApprovedStore:
    def __init__(self, db_path: str):
        self._db = sqlite3.connect(db_path)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS arp (tool_name TEXT PRIMARY KEY, json TEXT)"
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS decision ("
            "id TEXT PRIMARY KEY, tool_name TEXT, data_classification TEXT, "
            "iag_type TEXT, expires_at TEXT, json TEXT)"
        )
        self._db.commit()

    def save_arp(self, arp: ArpRecord) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO arp VALUES (?, ?)",
            (arp.tool_name.lower(), arp.model_dump_json()),
        )
        self._db.commit()

    def get_arp(self, tool_name: str) -> ArpRecord | None:
        row = self._db.execute(
            "SELECT json FROM arp WHERE tool_name = ?", (tool_name.lower(),)
        ).fetchone()
        return ArpRecord.model_validate_json(row[0]) if row else None

    def save_decision(self, rec: PreApprovedRecord) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO decision VALUES (?, ?, ?, ?, ?, ?)",
            (rec.id, rec.tool_name.lower(), rec.data_classification, rec.iag_type,
             rec.expires_at.isoformat() if rec.expires_at else "",
             rec.model_dump_json()),
        )
        self._db.commit()

    def find_decision(
        self, tool_name: str, data_classification: DataClass, iag_type: IagType,
        today: date | None = None,
    ) -> PreApprovedRecord | None:
        today = today or date.today()
        row = self._db.execute(
            "SELECT json, expires_at FROM decision WHERE tool_name = ? "
            "AND data_classification = ? AND iag_type = ?",
            (tool_name.lower(), data_classification, iag_type),
        ).fetchone()
        if not row:
            return None
        _, expires = row
        if expires and date.fromisoformat(expires) < today:
            return None
        return PreApprovedRecord.model_validate_json(row[0])
```

```python
# tests/preapproved/__init__.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/preapproved/test_store.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add policybot/preapproved/ tests/preapproved/
git commit -m "feat: add SQLite pre-approved store with expiry"
```

---

### Task 12: Report — HTML rendering (+ optional PDF)

**Files:**
- Create: `policybot/report/__init__.py`
- Create: `policybot/report/templates/report.html.j2`
- Create: `policybot/report/renderer.py`
- Test: `tests/report/__init__.py`, `tests/report/test_renderer.py`

**Interfaces:**
- Consumes: `InterviewState` (Task 2).
- Produces:
  - `render_html(state: InterviewState) -> str` — Jinja2, mirrors Fiche + Grille A/B/C, footer on the body.
  - `html_to_pdf(html: str) -> bytes` — WeasyPrint wrapper; raises `RuntimeError` with an install hint if WeasyPrint is missing. **Not unit-tested** (integration-flagged).

- [ ] **Step 1: Write the failing test**

```python
# tests/report/test_renderer.py
from policybot.models import InterviewState, RequestInfo, Usage, ToolRef, GlobalResult
from policybot.report.renderer import render_html


def _state():
    return InterviewState(
        interview_id="i1",
        request=RequestInfo(numero="IAG-2026-001", demandeur="Jean Test", unite="VRAF"),
        tools=[ToolRef(name="ChatGPT", iag_type="publique")],
        usages=[Usage(description="Résumer des rapports", data_classification="Protégé B",
                      matrix_result="INTERDIT", verdict="Refuser", risk_level="Critique",
                      conditions=["Combinaison interdite."])],
        result_global=GlobalResult(risk_level="Critique", recommendation="Refuser",
                                   efvpr_required=False),
    )


def test_render_contains_request_and_verdict():
    html = render_html(_state())
    assert "IAG-2026-001" in html
    assert "Jean Test" in html
    assert "Refuser" in html
    assert "Protégé B" in html


def test_render_contains_disclaimer_footer():
    html = render_html(_state())
    assert "requiert validation et autorisation par l'autorité désignée" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/report/test_renderer.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the template and renderer**

```python
# policybot/report/__init__.py
```

```jinja
{# policybot/report/templates/report.html.j2 #}
<article>
  <h1>Rapport de recommandation — PolicyBot</h1>
  <section>
    <h2>1. Fiche de qualification</h2>
    <p><strong>Numéro :</strong> {{ state.request.numero }}</p>
    <p><strong>Demandeur :</strong> {{ state.request.demandeur }}</p>
    <p><strong>Unité :</strong> {{ state.request.unite }}</p>
    <h3>Outils visés</h3>
    <ul>
      {% for t in state.tools %}
      <li>{{ t.name }} — IAG {{ t.iag_type }}</li>
      {% endfor %}
    </ul>
  </section>
  <section>
    <h2>2. Grille — Évaluation par usage (Partie B)</h2>
    {% for u in state.usages %}
    <div class="usage">
      <h3>Usage {{ loop.index }} : {{ u.description }}</h3>
      <p><strong>Classification :</strong> {{ u.data_classification }}
         {% if u.needs_officer_confirmation %}⚠ à valider{% endif %}</p>
      <p><strong>Matrice MCN :</strong> {{ u.matrix_result }}</p>
      <p><strong>Niveau de risque (proposé) :</strong> {{ u.risk_level }}</p>
      <p><strong>Recommandation :</strong> {{ u.verdict }}</p>
      {% if u.efvpr_required %}<p><strong>ÉFVP-R requise.</strong></p>{% endif %}
      {% if u.conditions %}
      <p><strong>Conditions :</strong></p>
      <ul>{% for c in u.conditions %}<li>{{ c }}</li>{% endfor %}</ul>
      {% endif %}
    </div>
    {% endfor %}
  </section>
  <section>
    <h2>3. Synthèse et décision (Partie C)</h2>
    <p><strong>Niveau de risque global (proposé) :</strong> {{ state.result_global.risk_level }}</p>
    <p><strong>Recommandation :</strong> {{ state.result_global.recommendation }}</p>
    <p><strong>ÉFVP-R requise :</strong> {{ "Oui" if state.result_global.efvpr_required else "Non" }}</p>
  </section>
  <footer>
    Recommandation générée par PolicyBot — requiert validation et autorisation
    par l'autorité désignée.
  </footer>
</article>
```

```python
# policybot/report/renderer.py
from __future__ import annotations
import os
from jinja2 import Environment, FileSystemLoader, select_autoescape
from policybot.models import InterviewState

_TEMPLATES = os.path.join(os.path.dirname(__file__), "templates")
_env = Environment(
    loader=FileSystemLoader(_TEMPLATES),
    autoescape=select_autoescape(["html", "j2"]),
)


def render_html(state: InterviewState) -> str:
    return _env.get_template("report.html.j2").render(state=state)


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

```python
# tests/report/__init__.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/report/test_renderer.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add policybot/report/ tests/report/
git commit -m "feat: add HTML report renderer and optional PDF wrapper"
```

---

### Task 13: Interview orchestrator (LangGraph)

**Files:**
- Create: `policybot/interview/__init__.py`
- Create: `policybot/interview/questions.py`
- Create: `policybot/interview/orchestrator.py`
- Test: `tests/interview/__init__.py`, `tests/interview/test_orchestrator.py`

**Interfaces:**
- Consumes: everything above — `classify_data` (7), `classify_tool_type`/`lookup_tool` (8), `fetch_terms` (9), `extract_contract_facts`/`build_arp` (10), `evaluate_usage`/`synthesize` (5), `PreApprovedStore` (11), `LLMProvider` (6).
- Produces:
  - `data_description_question() -> QuestionSpec` and `usage_details_question() -> QuestionSpec` in `questions.py`.
  - `Interview(llm: LLMProvider, store: PreApprovedStore, http_get=None)` in `orchestrator.py` with:
    - `assess(request: RequestInfo, tool_name: str, usage_inputs: list[dict]) -> InterviewState` — runs the full deterministic pipeline for a known tool type. Each `usage_input` = `{"description": str, "data_description": str, "automated_decisions": bool, "mode": list, "result_use": list}`.
  - This task implements the pipeline as a linear function first; the LangGraph wrapper is added in Task 14. (Keeps this task independently testable without graph plumbing.)

- [ ] **Step 1: Write the failing test**

```python
# tests/interview/test_orchestrator.py
from policybot.models import RequestInfo
from policybot.llm.fake import FakeLLMProvider
from policybot.preapproved.store import PreApprovedStore
from policybot.interview.orchestrator import Interview


def _terms_get(url):
    return "<html><body>We may use your content to train our models.</body></html>"


def test_protege_b_into_public_tool_is_refused(tmp_path):
    # LLM calls in order: (1) data classifier signals, (2) ARP contract facts.
    llm = FakeLLMProvider(json_responses=[
        {"already_public": False, "contains_personal_info": True,
         "strategic_sensitive": True, "internal_nonpublic": True,
         "highly_sensitive_secret": False, "confidence": 0.9},
        {"trains_on_input": "yes", "data_retention": "indefinite",
         "data_residency": "us", "sub_processors": "undisclosed",
         "human_review": "no", "extraction_confidence": 0.8},
    ])
    store = PreApprovedStore(str(tmp_path / "pb.db"))
    itv = Interview(llm=llm, store=store, http_get=_terms_get)
    state = itv.assess(
        request=RequestInfo(numero="IAG-2026-001"),
        tool_name="ChatGPT",
        usage_inputs=[{"description": "Résumer des rapports financiers",
                       "data_description": "données stratégiques et renseignements personnels",
                       "automated_decisions": False, "mode": ["prompt"], "result_use": []}],
    )
    assert state.tools[0].iag_type == "publique"
    assert state.usages[0].data_classification == "Protégé B"
    assert state.usages[0].matrix_result == "INTERDIT"
    assert state.usages[0].verdict == "Refuser"
    assert state.result_global.recommendation == "Refuser"


def test_public_data_public_tool_authorised(tmp_path):
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
        request=RequestInfo(numero="IAG-2026-002"),
        tool_name="ChatGPT",
        usage_inputs=[{"description": "Chercher de l'info publique",
                       "data_description": "information publique sur le web",
                       "automated_decisions": False, "mode": ["prompt"], "result_use": []}],
    )
    assert state.usages[0].verdict == "Autoriser"
    assert state.result_global.recommendation == "Autoriser"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/interview/test_orchestrator.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the questions and orchestrator**

```python
# policybot/interview/__init__.py
```

```python
# policybot/interview/questions.py
from policybot.models import QuestionSpec, QuestionOption


def data_description_question() -> QuestionSpec:
    return QuestionSpec(
        id="data_description",
        header="Type de données",
        question="Quel type de données comptez-vous soumettre à l'outil ?",
        multi_select=False,
        allow_other=True,
        options=[
            QuestionOption(label="Information déjà publique",
                           description="Statistiques publiées, communiqués, code public"),
            QuestionOption(label="Documents internes de travail",
                           description="Notes, brouillons, code applicatif privé"),
            QuestionOption(label="Renseignements personnels",
                           description="Noms, dossiers, coordonnées de personnes"),
            QuestionOption(label="Données stratégiques / confidentielles",
                           description="Informations sensibles pour l'institution"),
        ],
    )


def usage_details_question() -> QuestionSpec:
    return QuestionSpec(
        id="usage_details",
        header="Utilisation",
        question="Comment comptez-vous utiliser les résultats ?",
        multi_select=True,
        allow_other=True,
        options=[
            QuestionOption(label="Prise de décision"),
            QuestionOption(label="Publication"),
            QuestionOption(label="Intrant dans un autre processus"),
            QuestionOption(label="Aide à la rédaction / diffusion interne"),
        ],
    )
```

```python
# policybot/interview/orchestrator.py
from __future__ import annotations
from typing import Callable, Optional
from policybot.models import (
    InterviewState, RequestInfo, ToolRef, Usage, ContractFacts,
)
from policybot.llm.provider import LLMProvider
from policybot.preapproved.store import PreApprovedStore
from policybot.classify.data_classifier import classify_data
from policybot.classify.tool_type import classify_tool_type
from policybot.classify.tool_registry import lookup_tool
from policybot.contract.fetcher import fetch_terms
from policybot.contract.arp import extract_contract_facts, build_arp
from policybot.grille.engine import evaluate_usage, synthesize
import uuid


class Interview:
    def __init__(self, llm: LLMProvider, store: PreApprovedStore,
                 http_get: Optional[Callable[[str], str]] = None):
        self._llm = llm
        self._store = store
        self._http_get = http_get

    def _resolve_arp(self, tool_name: str, iag_type) -> ContractFacts:
        cached = self._store.get_arp(tool_name)
        if cached:
            return cached.contract_facts
        terms = fetch_terms(tool_name, http_get=self._http_get)
        if terms is None:
            return ContractFacts()  # manual-paste fallback handled by the UI layer
        facts = extract_contract_facts(terms, self._llm)
        self._store.save_arp(build_arp(tool_name, iag_type, facts))
        return facts

    def assess(self, request: RequestInfo, tool_name: str,
               usage_inputs: list[dict]) -> InterviewState:
        state = InterviewState(interview_id=str(uuid.uuid4()), request=request)
        entry = lookup_tool(tool_name)
        iag_type = classify_tool_type(tool_name)
        state.tools.append(ToolRef(
            name=tool_name,
            vendor=entry["vendor"] if entry else None,
            iag_type=iag_type,
        ))
        facts = self._resolve_arp(tool_name, iag_type)

        for item in usage_inputs:
            classification = classify_data(item["data_description"], self._llm)
            usage = Usage(
                description=item.get("description", ""),
                tool_ref=tool_name,
                data_classification=classification.data_classification,
                rens_personnels=classification.rens_personnels,
                classifier_confidence=classification.confidence,
                needs_officer_confirmation=classification.needs_officer_confirmation,
                mode=item.get("mode", []),
                result_use=item.get("result_use", []),
                automated_decisions=item.get("automated_decisions", False),
            )
            state.usages.append(evaluate_usage(usage, facts, iag_type))

        state.result_global = synthesize(state.usages)
        state.status = "complete"
        return state
```

```python
# tests/interview/__init__.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/interview/test_orchestrator.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add policybot/interview/ tests/interview/
git commit -m "feat: add interview orchestrator pipeline"
```

---

### Task 14: LangGraph state machine wrapper

**Files:**
- Create: `policybot/interview/graph.py`
- Test: `tests/interview/test_graph.py`

**Interfaces:**
- Consumes: `Interview` (Task 13); `InterviewState`, `RequestInfo` (Task 2).
- Produces:
  - `build_interview_graph(itv: Interview)` returning a compiled LangGraph app whose single node runs `itv.assess`. The graph state is a `TypedDict` with keys `request`, `tool_name`, `usage_inputs`, `state`.
  - `run_graph(itv: Interview, request, tool_name, usage_inputs) -> InterviewState` convenience wrapper.

This task exists to satisfy the spec's LangGraph/checkpointer requirement while keeping the deterministic pipeline (Task 13) the tested core. The graph adds resumability and a place to later split nodes for step-by-step UI.

- [ ] **Step 1: Write the failing test**

```python
# tests/interview/test_graph.py
from policybot.models import RequestInfo
from policybot.llm.fake import FakeLLMProvider
from policybot.preapproved.store import PreApprovedStore
from policybot.interview.orchestrator import Interview
from policybot.interview.graph import run_graph


def _terms_get(url):
    return "<html><body>train our models</body></html>"


def test_graph_runs_full_pipeline(tmp_path):
    llm = FakeLLMProvider(json_responses=[
        {"already_public": True, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.9},
        {"trains_on_input": "no", "data_residency": "canada",
         "extraction_confidence": 0.9},
    ])
    itv = Interview(llm=llm, store=PreApprovedStore(str(tmp_path / "pb.db")),
                    http_get=_terms_get)
    state = run_graph(itv, RequestInfo(numero="IAG-2026-003"), "ChatGPT",
                      [{"description": "info publique", "data_description": "info publique",
                        "automated_decisions": False, "mode": ["prompt"], "result_use": []}])
    assert state.status == "complete"
    assert state.result_global.recommendation == "Autoriser"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/interview/test_graph.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the graph wrapper**

```python
# policybot/interview/graph.py
from __future__ import annotations
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from policybot.models import InterviewState, RequestInfo
from policybot.interview.orchestrator import Interview


class _GraphState(TypedDict, total=False):
    request: RequestInfo
    tool_name: str
    usage_inputs: list
    state: InterviewState


def build_interview_graph(itv: Interview):
    def assess_node(gs: _GraphState) -> _GraphState:
        result = itv.assess(gs["request"], gs["tool_name"], gs["usage_inputs"])
        return {"state": result}

    graph = StateGraph(_GraphState)
    graph.add_node("assess", assess_node)
    graph.add_edge(START, "assess")
    graph.add_edge("assess", END)
    return graph.compile()


def run_graph(itv: Interview, request: RequestInfo, tool_name: str,
              usage_inputs: list) -> InterviewState:
    app = build_interview_graph(itv)
    out = app.invoke(
        {"request": request, "tool_name": tool_name, "usage_inputs": usage_inputs}
    )
    return out["state"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/interview/test_graph.py -v`
Expected: PASS (1 test).

- [ ] **Step 5: Commit**

```bash
git add policybot/interview/graph.py tests/interview/test_graph.py
git commit -m "feat: wrap interview pipeline in a LangGraph state machine"
```

---

### Task 15: FastAPI app + minimal frontend

**Files:**
- Create: `policybot/api/__init__.py`
- Create: `policybot/api/app.py`
- Create: `policybot/api/deps.py`
- Test: `tests/api/__init__.py`, `tests/api/test_app.py`

**Interfaces:**
- Consumes: `Interview` (13), `run_graph` (14), `render_html`/`html_to_pdf` (12), `PreApprovedStore` (11), `FakeLLMProvider` (6).
- Produces:
  - `create_app(itv: Interview) -> FastAPI` with:
    - `POST /assess` — body `{request: {...}, tool_name: str, usage_inputs: [...]}` → returns the `InterviewState` as JSON.
    - `GET /report?...` is replaced by `POST /report` — body = an `InterviewState` JSON → returns `text/html` report.
  - `deps.py` builds a default `Interview` from env (`OPENROUTER_API_KEY`), used by `app.py`'s module-level `app` for real runs; tests inject a fake via `create_app`.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_app.py
from fastapi.testclient import TestClient
from policybot.llm.fake import FakeLLMProvider
from policybot.preapproved.store import PreApprovedStore
from policybot.interview.orchestrator import Interview
from policybot.api.app import create_app


def _client(tmp_path):
    llm = FakeLLMProvider(json_responses=[
        {"already_public": True, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.9},
        {"trains_on_input": "no", "data_residency": "canada", "extraction_confidence": 0.9},
    ])
    itv = Interview(llm=llm, store=PreApprovedStore(str(tmp_path / "pb.db")),
                    http_get=lambda url: "<html><body>ok</body></html>")
    return TestClient(create_app(itv))


def test_assess_endpoint_returns_state(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/assess", json={
        "request": {"numero": "IAG-2026-004"},
        "tool_name": "ChatGPT",
        "usage_inputs": [{"description": "info publique", "data_description": "info publique",
                          "automated_decisions": False, "mode": ["prompt"], "result_use": []}],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["result_global"]["recommendation"] == "Autoriser"


def test_report_endpoint_returns_html(tmp_path):
    client = _client(tmp_path)
    state = client.post("/assess", json={
        "request": {"numero": "IAG-2026-005"},
        "tool_name": "ChatGPT",
        "usage_inputs": [{"description": "info publique", "data_description": "info publique",
                          "automated_decisions": False, "mode": ["prompt"], "result_use": []}],
    }).json()
    resp = client.post("/report", json=state)
    assert resp.status_code == 200
    assert "PolicyBot" in resp.text
    assert "IAG-2026-005" in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/api/test_app.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the app**

```python
# policybot/api/__init__.py
```

```python
# policybot/api/app.py
from __future__ import annotations
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from policybot.models import InterviewState, RequestInfo
from policybot.interview.orchestrator import Interview
from policybot.interview.graph import run_graph
from policybot.report.renderer import render_html


def create_app(itv: Interview) -> FastAPI:
    app = FastAPI(title="PolicyBot")

    @app.post("/assess")
    def assess(payload: dict) -> InterviewState:
        return run_graph(
            itv,
            RequestInfo(**payload["request"]),
            payload["tool_name"],
            payload["usage_inputs"],
        )

    @app.post("/report", response_class=HTMLResponse)
    def report(state: InterviewState) -> str:
        return render_html(state)

    return app
```

```python
# policybot/api/deps.py
from __future__ import annotations
import os
from policybot.llm.openrouter import OpenRouterProvider
from policybot.llm.fake import FakeLLMProvider
from policybot.preapproved.store import PreApprovedStore
from policybot.interview.orchestrator import Interview


def default_interview(db_path: str = "policybot.db") -> Interview:
    key = os.environ.get("OPENROUTER_API_KEY")
    llm = OpenRouterProvider(key) if key else FakeLLMProvider()
    return Interview(llm=llm, store=PreApprovedStore(db_path))
```

```python
# tests/api/__init__.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/api/test_app.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add policybot/api/ tests/api/
git commit -m "feat: add FastAPI assess/report endpoints"
```

---

### Task 16: Golden end-to-end acceptance test (UQAM slide-5 scenario)

**Files:**
- Create: `tests/test_golden_scenarios.py`

**Interfaces:**
- Consumes: `Interview.assess` (13), `render_html` (12).
- Produces: the canonical acceptance test asserting the real UQAM example resolves correctly end to end.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_golden_scenarios.py
from policybot.models import RequestInfo
from policybot.llm.fake import FakeLLMProvider
from policybot.preapproved.store import PreApprovedStore
from policybot.interview.orchestrator import Interview
from policybot.report.renderer import render_html


def _terms_get(url):
    return "<html><body>content may be used to train models</body></html>"


def test_slide5_chatgpt_protege_b_is_refused_and_report_flags_it(tmp_path):
    """Slide 5: ChatGPT/Perplexity + Protégé B strategic/financial data ⇒ INTERDIT."""
    llm = FakeLLMProvider(json_responses=[
        {"already_public": False, "contains_personal_info": True,
         "strategic_sensitive": True, "internal_nonpublic": True,
         "highly_sensitive_secret": False, "confidence": 0.95},
        {"trains_on_input": "yes", "data_retention": "indefinite", "data_residency": "us",
         "sub_processors": "undisclosed", "human_review": "no", "extraction_confidence": 0.85},
    ])
    itv = Interview(llm=llm, store=PreApprovedStore(str(tmp_path / "pb.db")),
                    http_get=_terms_get)
    state = itv.assess(
        request=RequestInfo(numero="IAG-2026-006", demandeur="VRAF", unite="Finances"),
        tool_name="ChatGPT Pro",
        usage_inputs=[{
            "description": "Résumer des rapports financiers stratégiques",
            "data_description": "rapports financiers stratégiques et renseignements personnels",
            "automated_decisions": False, "mode": ["prompt"],
            "result_use": ["Prise de décision"],
        }],
    )
    usage = state.usages[0]
    assert usage.data_classification == "Protégé B"
    assert usage.matrix_result == "INTERDIT"
    assert usage.verdict == "Refuser"
    assert usage.efvpr_required is True
    assert state.result_global.recommendation == "Refuser"

    html = render_html(state)
    assert "Refuser" in html
    assert "ÉFVP-R requise" in html
    assert "requiert validation et autorisation par l'autorité désignée" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_golden_scenarios.py -v`
Expected: FAIL — assertion or import until the pipeline is wired (should pass if Tasks 1–13 are complete; run to confirm).

- [ ] **Step 3: (No new implementation)**

If any assertion fails, fix the responsible module (matrix, classifier, engine, or renderer) — do not weaken the test. The scenario is sanctioned policy.

- [ ] **Step 4: Run the full suite**

Run: `pytest -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_golden_scenarios.py
git commit -m "test: add UQAM slide-5 golden acceptance scenario"
```

---

## Self-Review

**1. Spec coverage:**
- Hybrid engine (rules decide) → Tasks 3–5. ✅
- MCN matrix hard gate → Task 3 (exhaustive). ✅
- Grille as YAML data → Task 4. ✅
- F/M/E/C as proposals (`origin`/`proposed`) → Task 2 model + Task 10 (`origin="rule"`). ✅
- Data classifier (LLM signals + conservative tree + confirmation flag) → Task 7. ✅
- Tool-type classifier + registry → Task 8. ✅
- Terms fetcher (auto-fetch, registry URL, manual fallback via `None`) → Task 9. ✅
- ARP extractor + per-tool caching → Tasks 10, 11 (`get_arp`/`save_arp`). ✅
- Pre-approved DB with expiry → Task 11. ✅
- Multi-usage loop → Task 13 (`usage_inputs` list). ✅
- Report mirrors Fiche + Grille A/B/C + disclaimer → Task 12. ✅
- PDF as thin wrapper (Windows-safe) → Task 12 (`html_to_pdf`, integration-flagged). ✅
- Structured `QuestionSpec` layer → Task 2 model + Tasks 8/13 question builders. ✅
- LangGraph state machine → Task 14. ✅
- Swappable LLM (OpenRouter/Gemma + fake) → Task 6. ✅
- Metadata-only constraint → honored (only descriptions passed to `classify_data`/`extract_contract_facts`). ✅
- Golden slide-5 scenario → Task 16. ✅
- *Deferred per spec §14:* officer dashboard, live re-fetch scheduling, UQAM PDF theming — intentionally not in this plan.
- *Partial:* pre-approved short-circuit reuse is implemented at the ARP level (Task 13 `_resolve_arp` reuses cached ARP); full decision-level short-circuit (skip interview on a matching `PreApprovedRecord`) is a thin future addition using `find_decision` (Task 11) — noted, not blocking MVP.

**2. Placeholder scan:** No "TBD"/"handle edge cases"/"similar to Task N" — all steps carry real code. ✅

**3. Type consistency:** `DataClass`/`IagType`/`MatrixResult`/`RiskLevel`/`Recommendation` used identically across Tasks 2–16; `evaluate_matrix`, `evaluate_usage`, `synthesize`, `classify_data`, `fetch_terms`, `extract_contract_facts`, `build_arp`, `PreApprovedStore` method names match their definitions where consumed. ✅

---

## Notes for the implementer

- **Run order:** Tasks are dependency-ordered; execute 1→16.
- **`git init` first:** the repo isn't initialized yet. Run `git init` before Task 1's commit (the user plans to do this).
- **OpenRouter model slug:** confirm the exact Gemma slug on OpenRouter before any live run; the default in `OpenRouterProvider` is a placeholder (`google/gemma-2-27b-it`).
- **Seeding `grille.yaml`:** collect the officers' real rules of thumb and extend the starter file; each new rule gets a test like Task 4.
