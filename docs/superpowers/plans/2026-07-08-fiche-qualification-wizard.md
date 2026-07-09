# Fiche de qualification — Wizard Data Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend PolicyBot's data model and wizard flow so it captures every field of the UQAM "Fiche de qualification des usages" (sections 1-7) that the requesting employee can answer themselves, without touching the risk decision engine.

**Architecture:** Add a new `QualificationProfile` model (sections 4/6/7, one per `InterviewState`, never read by `grille/matrix.py` or `grille/rules.py`) plus small descriptive extensions to the existing `ToolRef` (section 2) and `Usage` (section 3) models. Insert two new wizard screens — `profil_utilisateurs` (after `outil`) and `contexte_affaires` (after `resultats`, now the screen that triggers `Interview.assess`) — into the existing five-step wizard, following the established `WizardState` hidden-field-carry pattern (no server session).

**Tech Stack:** FastAPI, Jinja2 (`.html.j2` templates), Pydantic v2, pytest + `FastAPI TestClient`, `FakeLLMProvider` for offline tests.

## Global Constraints

- New fields are purely descriptive: never read by `policybot/grille/matrix.py` or `policybot/grille/rules.py`, and never passed into `classify_data`, `evaluate_usage`, or `synthesize`.
- No LLM assistance on any new field — no `suggest_options`/`guess_*` wiring, plain HTML inputs only.
- Section 1 admin fields (Responsable SI assigné, date/participants de rencontre) and section 8 (observations Direction SI) are out of scope for this plan — do not add them.
- Every new parameter on `Interview.assess` must default such that all existing calls (in `tests/interview/test_orchestrator.py`, `tests/test_golden_scenarios.py`, `tests/web/test_routes_*.py`) keep passing unmodified in their assertions about verdicts/risk — only URL/field additions described below change.
- Follow existing code style exactly: French field/label text with correct accents, same template structure (`kicker` / `h1` / `assist` / `form` / `foot`), same `_group_form` + `WizardState.from_form` pattern in every route.

---

### Task 1: Extend data models (`policybot/models.py`)

**Files:**
- Modify: `policybot/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `QualificationProfile` (new Pydantic model, all fields optional/empty-default), `ToolRef.version_plan_tarifaire: str`, `Usage.frequence_utilisation: str`, `Usage.nb_utilisateurs: Optional[int]`, `Usage.systemes_api_cibles: str`, `InterviewState.qualification: QualificationProfile`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_models.py` (append at end of file; extend the existing import line too):

```python
from policybot.models import (
    QuestionSpec, QuestionOption, RiskFactor, Usage, InterviewState, RequestInfo,
    ContractFacts, ToolRef, QualificationProfile,
)
```

```python
def test_qualificationprofile_defaults_to_empty_values():
    profile = QualificationProfile()
    assert profile.nb_utilisateurs_vises is None
    assert profile.fonctions_roles == ""
    assert profile.niveau_maitrise_ti is None
    assert profile.formation_iag_recue is None
    assert profile.acces_protege_a_ou_plus is None
    assert profile.besoin_affaires == ""
    assert profile.urgence_percue is None
    assert profile.cout_annuel_par_utilisateur == ""
    assert profile.mode_acquisition is None
    assert profile.responsable_budgetaire == ""


def test_interviewstate_defaults_to_empty_qualification_profile():
    st = InterviewState(interview_id="abc", request=RequestInfo(numero="IAG-2026-001"))
    assert st.qualification == QualificationProfile()


def test_toolref_defaults_version_plan_tarifaire_to_empty_string():
    ref = ToolRef(name="ChatGPT")
    assert ref.version_plan_tarifaire == ""


def test_usage_defaults_new_section3_fields_to_empty():
    usage = Usage()
    assert usage.frequence_utilisation == ""
    assert usage.nb_utilisateurs is None
    assert usage.systemes_api_cibles == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'QualificationProfile'` (or `ToolRef` missing depending on import order).

- [ ] **Step 3: Implement the model changes**

In `policybot/models.py`, add the new model after `RequestInfo` (which sits at line 81-85) and before `ToolRef`:

```python
class QualificationProfile(BaseModel):
    # Section 4 — Profil des utilisateurs
    nb_utilisateurs_vises: Optional[int] = None
    fonctions_roles: str = ""
    niveau_maitrise_ti: Optional[Literal["débutant", "intermédiaire", "avancé"]] = None
    formation_iag_recue: Optional[Literal["aucune", "partielle", "complète"]] = None
    acces_protege_a_ou_plus: Optional[Literal["oui", "non", "à vérifier"]] = None

    # Section 6 — Valeur attendue et bénéfices
    besoin_affaires: str = ""
    gains_qualitatifs: str = ""
    gains_quantitatifs: str = ""
    alternatives_considerees: str = ""
    urgence_percue: Optional[Literal["faible", "modérée", "élevée"]] = None

    # Section 7 — Informations contractuelles et financières
    cout_annuel_par_utilisateur: str = ""
    cout_total_annuel: str = ""
    mode_acquisition: Optional[Literal[
        "achat_direct", "seao", "appel_offres", "contrat_existant"
    ]] = None
    duree_contrat: str = ""
    responsable_budgetaire: str = ""
```

Modify `ToolRef` (currently lines 88-92) to add one field:

```python
class ToolRef(BaseModel):
    name: str
    vendor: Optional[str] = None
    iag_type: Optional[IagType] = None
    arp: Optional[ArpRecord] = None
    version_plan_tarifaire: str = ""
```

Modify `Usage` (currently lines 95-111) to add three fields — insert them right after `mode`:

```python
class Usage(BaseModel):
    description: str = ""
    tool_ref: str = ""
    raw_answers: dict = Field(default_factory=dict)
    data_classification: Optional[DataClass] = None
    rens_personnels: bool = False
    efvpr_required: bool = False
    mode: list[Literal["prompt", "api"]] = Field(default_factory=list)
    frequence_utilisation: str = ""
    nb_utilisateurs: Optional[int] = None
    systemes_api_cibles: str = ""
    result_use: list[str] = Field(default_factory=list)
    automated_decisions: bool = False
    classifier_confidence: float = 0.0
    needs_officer_confirmation: bool = False
    matrix_result: Optional[MatrixResult] = None
    partie_b: list[RiskFactor] = Field(default_factory=list)
    verdict: Optional[Recommendation] = None
    risk_level: Optional[RiskLevel] = None
    conditions: list[str] = Field(default_factory=list)
```

Modify `InterviewState` (currently lines 122-129) to add the profile field:

```python
class InterviewState(BaseModel):
    interview_id: str
    status: Literal["in_progress", "awaiting_terms", "complete"] = "in_progress"
    request: RequestInfo
    tools: list[ToolRef] = Field(default_factory=list)
    usages: list[Usage] = Field(default_factory=list)
    qualification: QualificationProfile = Field(default_factory=QualificationProfile)
    result_global: GlobalResult = Field(default_factory=GlobalResult)
    audit: dict = Field(default_factory=lambda: {"question_log": [], "timestamps": {}})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_models.py -v`
Expected: PASS (all tests, including the 4 new ones).

- [ ] **Step 5: Run the full suite to check for regressions, then commit**

Run: `pytest -v`
Expected: PASS (no test reads the new fields yet, so nothing else should break).

```bash
git add policybot/models.py tests/test_models.py
git commit -m "feat(models): add QualificationProfile and Fiche de qualification descriptive fields"
```

---

### Task 2: Extend `WizardState` (`policybot/web/wizard_state.py`)

**Files:**
- Modify: `policybot/web/wizard_state.py`
- Test: `tests/web/test_wizard_state.py`

**Interfaces:**
- Consumes: nothing new from Task 1 (WizardState stays a flat string-only carrier; parsing to `int`/`Literal` happens later in routes.py, Task 6).
- Produces: 19 new `WizardState` string fields (all default `""`), extended `to_hidden_fields()` and `from_form()` covering them.

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_wizard_state.py`:

```python
def test_to_hidden_fields_emits_new_qualification_and_context_fields_when_set():
    state = WizardState(
        version_plan_tarifaire="Plan Plus",
        nb_utilisateurs_vises="25",
        fonctions_roles="conseillers",
        niveau_maitrise_ti="intermédiaire",
        formation_iag_recue="partielle",
        acces_protege_a_ou_plus="non",
        frequence_utilisation="quotidienne",
        nb_utilisateurs="5",
        systemes_api_cibles="CRM",
        besoin_affaires="gagner du temps",
        gains_qualitatifs="clarté",
        gains_quantitatifs="2h/semaine",
        alternatives_considerees="Outil X",
        urgence_percue="modérée",
        cout_annuel_par_utilisateur="200$",
        cout_total_annuel="5000$",
        mode_acquisition="seao",
        duree_contrat="1 an",
        responsable_budgetaire="Direction SI",
    )
    fields = state.to_hidden_fields()
    for name, value in [
        ("version_plan_tarifaire", "Plan Plus"),
        ("nb_utilisateurs_vises", "25"),
        ("fonctions_roles", "conseillers"),
        ("niveau_maitrise_ti", "intermédiaire"),
        ("formation_iag_recue", "partielle"),
        ("acces_protege_a_ou_plus", "non"),
        ("frequence_utilisation", "quotidienne"),
        ("nb_utilisateurs", "5"),
        ("systemes_api_cibles", "CRM"),
        ("besoin_affaires", "gagner du temps"),
        ("gains_qualitatifs", "clarté"),
        ("gains_quantitatifs", "2h/semaine"),
        ("alternatives_considerees", "Outil X"),
        ("urgence_percue", "modérée"),
        ("cout_annuel_par_utilisateur", "200$"),
        ("cout_total_annuel", "5000$"),
        ("mode_acquisition", "seao"),
        ("duree_contrat", "1 an"),
        ("responsable_budgetaire", "Direction SI"),
    ]:
        assert (name, value) in fields


def test_from_form_roundtrips_new_qualification_and_context_fields():
    form = {
        "version_plan_tarifaire": "Plan Plus",
        "nb_utilisateurs_vises": "25",
        "fonctions_roles": "conseillers",
        "niveau_maitrise_ti": "intermédiaire",
        "formation_iag_recue": "partielle",
        "acces_protege_a_ou_plus": "non",
        "frequence_utilisation": "quotidienne",
        "nb_utilisateurs": "5",
        "systemes_api_cibles": "CRM",
        "besoin_affaires": "gagner du temps",
        "gains_qualitatifs": "clarté",
        "gains_quantitatifs": "2h/semaine",
        "alternatives_considerees": "Outil X",
        "urgence_percue": "modérée",
        "cout_annuel_par_utilisateur": "200$",
        "cout_total_annuel": "5000$",
        "mode_acquisition": "seao",
        "duree_contrat": "1 an",
        "responsable_budgetaire": "Direction SI",
    }
    state = WizardState.from_form(form)
    assert state.version_plan_tarifaire == "Plan Plus"
    assert state.nb_utilisateurs_vises == "25"
    assert state.fonctions_roles == "conseillers"
    assert state.niveau_maitrise_ti == "intermédiaire"
    assert state.formation_iag_recue == "partielle"
    assert state.acces_protege_a_ou_plus == "non"
    assert state.frequence_utilisation == "quotidienne"
    assert state.nb_utilisateurs == "5"
    assert state.systemes_api_cibles == "CRM"
    assert state.besoin_affaires == "gagner du temps"
    assert state.gains_qualitatifs == "clarté"
    assert state.gains_quantitatifs == "2h/semaine"
    assert state.alternatives_considerees == "Outil X"
    assert state.urgence_percue == "modérée"
    assert state.cout_annuel_par_utilisateur == "200$"
    assert state.cout_total_annuel == "5000$"
    assert state.mode_acquisition == "seao"
    assert state.duree_contrat == "1 an"
    assert state.responsable_budgetaire == "Direction SI"


def test_from_form_defaults_new_fields_to_empty_string_on_missing_keys():
    state = WizardState.from_form({})
    assert state.version_plan_tarifaire == ""
    assert state.nb_utilisateurs_vises == ""
    assert state.mode_acquisition == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_wizard_state.py -v`
Expected: FAIL — `pydantic.ValidationError` / `AttributeError` (unknown fields like `version_plan_tarifaire` don't exist on `WizardState` yet).

- [ ] **Step 3: Implement the `WizardState` extension**

Replace the full contents of `policybot/web/wizard_state.py` with:

```python
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field
from policybot.models import IagType


class WizardState(BaseModel):
    tool_name: str = ""
    tool_type_override: IagType | None = None
    version_plan_tarifaire: str = ""
    nb_utilisateurs_vises: str = ""
    fonctions_roles: str = ""
    niveau_maitrise_ti: str = ""
    formation_iag_recue: str = ""
    acces_protege_a_ou_plus: str = ""
    data_checked: list[str] = Field(default_factory=list)
    data_free_text: str = ""
    usage_description: str = ""
    mode: Literal["prompt", "api"] | None = None
    frequence_utilisation: str = ""
    nb_utilisateurs: str = ""
    systemes_api_cibles: str = ""
    result_use_checked: list[str] = Field(default_factory=list)
    result_use_free_text: str = ""
    automated_decisions: bool = False
    besoin_affaires: str = ""
    gains_qualitatifs: str = ""
    gains_quantitatifs: str = ""
    alternatives_considerees: str = ""
    urgence_percue: str = ""
    cout_annuel_par_utilisateur: str = ""
    cout_total_annuel: str = ""
    mode_acquisition: str = ""
    duree_contrat: str = ""
    responsable_budgetaire: str = ""

    def to_hidden_fields(self) -> list[tuple[str, str]]:
        fields: list[tuple[str, str]] = []
        if self.tool_name:
            fields.append(("tool_name", self.tool_name))
        if self.tool_type_override:
            fields.append(("tool_type_override", self.tool_type_override))
        if self.version_plan_tarifaire:
            fields.append(("version_plan_tarifaire", self.version_plan_tarifaire))
        if self.nb_utilisateurs_vises:
            fields.append(("nb_utilisateurs_vises", self.nb_utilisateurs_vises))
        if self.fonctions_roles:
            fields.append(("fonctions_roles", self.fonctions_roles))
        if self.niveau_maitrise_ti:
            fields.append(("niveau_maitrise_ti", self.niveau_maitrise_ti))
        if self.formation_iag_recue:
            fields.append(("formation_iag_recue", self.formation_iag_recue))
        if self.acces_protege_a_ou_plus:
            fields.append(("acces_protege_a_ou_plus", self.acces_protege_a_ou_plus))
        for label in self.data_checked:
            fields.append(("data_checked", label))
        if self.data_free_text:
            fields.append(("data_free_text", self.data_free_text))
        if self.usage_description:
            fields.append(("usage_description", self.usage_description))
        if self.mode:
            fields.append(("mode", self.mode))
        if self.frequence_utilisation:
            fields.append(("frequence_utilisation", self.frequence_utilisation))
        if self.nb_utilisateurs:
            fields.append(("nb_utilisateurs", self.nb_utilisateurs))
        if self.systemes_api_cibles:
            fields.append(("systemes_api_cibles", self.systemes_api_cibles))
        for label in self.result_use_checked:
            fields.append(("result_use_checked", label))
        if self.result_use_free_text:
            fields.append(("result_use_free_text", self.result_use_free_text))
        if self.automated_decisions:
            fields.append(("automated_decisions", "true"))
        if self.besoin_affaires:
            fields.append(("besoin_affaires", self.besoin_affaires))
        if self.gains_qualitatifs:
            fields.append(("gains_qualitatifs", self.gains_qualitatifs))
        if self.gains_quantitatifs:
            fields.append(("gains_quantitatifs", self.gains_quantitatifs))
        if self.alternatives_considerees:
            fields.append(("alternatives_considerees", self.alternatives_considerees))
        if self.urgence_percue:
            fields.append(("urgence_percue", self.urgence_percue))
        if self.cout_annuel_par_utilisateur:
            fields.append(("cout_annuel_par_utilisateur", self.cout_annuel_par_utilisateur))
        if self.cout_total_annuel:
            fields.append(("cout_total_annuel", self.cout_total_annuel))
        if self.mode_acquisition:
            fields.append(("mode_acquisition", self.mode_acquisition))
        if self.duree_contrat:
            fields.append(("duree_contrat", self.duree_contrat))
        if self.responsable_budgetaire:
            fields.append(("responsable_budgetaire", self.responsable_budgetaire))
        return fields

    @classmethod
    def from_form(cls, form: dict) -> "WizardState":
        def as_list(key: str) -> list[str]:
            value = form.get(key, [])
            if isinstance(value, list):
                return value
            return [value] if value else []

        return cls(
            tool_name=form.get("tool_name", "") or "",
            tool_type_override=form.get("tool_type_override") or None,
            version_plan_tarifaire=form.get("version_plan_tarifaire", "") or "",
            nb_utilisateurs_vises=form.get("nb_utilisateurs_vises", "") or "",
            fonctions_roles=form.get("fonctions_roles", "") or "",
            niveau_maitrise_ti=form.get("niveau_maitrise_ti", "") or "",
            formation_iag_recue=form.get("formation_iag_recue", "") or "",
            acces_protege_a_ou_plus=form.get("acces_protege_a_ou_plus", "") or "",
            data_checked=as_list("data_checked"),
            data_free_text=form.get("data_free_text", "") or "",
            usage_description=form.get("usage_description", "") or "",
            mode=form.get("mode") or None,
            frequence_utilisation=form.get("frequence_utilisation", "") or "",
            nb_utilisateurs=form.get("nb_utilisateurs", "") or "",
            systemes_api_cibles=form.get("systemes_api_cibles", "") or "",
            result_use_checked=as_list("result_use_checked"),
            result_use_free_text=form.get("result_use_free_text", "") or "",
            automated_decisions=str(form.get("automated_decisions", "")).lower() == "true",
            besoin_affaires=form.get("besoin_affaires", "") or "",
            gains_qualitatifs=form.get("gains_qualitatifs", "") or "",
            gains_quantitatifs=form.get("gains_quantitatifs", "") or "",
            alternatives_considerees=form.get("alternatives_considerees", "") or "",
            urgence_percue=form.get("urgence_percue", "") or "",
            cout_annuel_par_utilisateur=form.get("cout_annuel_par_utilisateur", "") or "",
            cout_total_annuel=form.get("cout_total_annuel", "") or "",
            mode_acquisition=form.get("mode_acquisition", "") or "",
            duree_contrat=form.get("duree_contrat", "") or "",
            responsable_budgetaire=form.get("responsable_budgetaire", "") or "",
        )


def compose_description(checked_labels: list[str], free_text: str) -> str:
    parts = list(checked_labels) + ([free_text] if free_text else [])
    return "; ".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/web/test_wizard_state.py -v`
Expected: PASS (all tests, including the 3 new ones).

- [ ] **Step 5: Run the full suite, then commit**

Run: `pytest -v`
Expected: PASS.

```bash
git add policybot/web/wizard_state.py tests/web/test_wizard_state.py
git commit -m "feat(wizard): carry Fiche de qualification fields through WizardState hidden fields"
```

---

### Task 3: Extend `Interview.assess` (`policybot/interview/orchestrator.py`)

**Files:**
- Modify: `policybot/interview/orchestrator.py`
- Test: `tests/interview/test_orchestrator.py`

**Interfaces:**
- Consumes: `QualificationProfile` (Task 1), `ToolRef.version_plan_tarifaire` (Task 1), `Usage.frequence_utilisation`/`nb_utilisateurs`/`systemes_api_cibles` (Task 1).
- Produces: `Interview.assess(..., qualification: QualificationProfile | None = None, tool_version_plan_tarifaire: str | None = None)`, and `usage_inputs` dict items may now carry optional keys `frequence_utilisation: str`, `nb_utilisateurs: int | None`, `systemes_api_cibles: str`.

- [ ] **Step 1: Write the failing test**

Add to `tests/interview/test_orchestrator.py` (extend the import line and append at the end):

```python
from policybot.models import RequestInfo, QualificationProfile
```

```python
def test_assess_stores_qualification_profile_and_tool_version(tmp_path):
    llm = FakeLLMProvider(json_responses=[
        {"already_public": True, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.9},
        {"trains_on_input": "no", "data_retention": "none", "data_residency": "canada",
         "sub_processors": "disclosed", "human_review": "yes", "extraction_confidence": 0.9},
    ])
    store = PreApprovedStore(str(tmp_path / "pb.db"))
    itv = Interview(llm=llm, store=store, http_get=_terms_get)
    qualification = QualificationProfile(nb_utilisateurs_vises=12, fonctions_roles="conseillers")
    state = itv.assess(
        request=RequestInfo(numero="IAG-2026-010"),
        tool_name="ChatGPT",
        usage_inputs=[{
            "description": "Chercher de l'info publique",
            "data_description": "information publique sur le web",
            "automated_decisions": False, "mode": ["prompt"], "result_use": [],
            "frequence_utilisation": "quotidienne", "nb_utilisateurs": 5,
            "systemes_api_cibles": "",
        }],
        qualification=qualification,
        tool_version_plan_tarifaire="Plan Plus",
    )
    assert state.qualification.nb_utilisateurs_vises == 12
    assert state.qualification.fonctions_roles == "conseillers"
    assert state.tools[0].version_plan_tarifaire == "Plan Plus"
    assert state.usages[0].frequence_utilisation == "quotidienne"
    assert state.usages[0].nb_utilisateurs == 5


def test_assess_defaults_qualification_and_new_usage_fields_when_omitted(tmp_path):
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
        request=RequestInfo(numero="IAG-2026-011"),
        tool_name="ChatGPT",
        usage_inputs=[{"description": "Chercher de l'info publique",
                       "data_description": "information publique sur le web",
                       "automated_decisions": False, "mode": ["prompt"], "result_use": []}],
    )
    assert state.qualification == QualificationProfile()
    assert state.tools[0].version_plan_tarifaire == ""
    assert state.usages[0].frequence_utilisation == ""
    assert state.usages[0].nb_utilisateurs is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/interview/test_orchestrator.py -v`
Expected: FAIL — `TypeError: assess() got an unexpected keyword argument 'qualification'`.

- [ ] **Step 3: Implement the `assess` changes**

In `policybot/interview/orchestrator.py`, update the import line (line 3-5) to include `QualificationProfile`:

```python
from policybot.models import (
    InterviewState, RequestInfo, ToolRef, Usage, ContractFacts, IagType,
    QualificationProfile,
)
```

Replace the `assess` method signature and body (currently lines 61-126) with:

```python
    def assess(self, request: RequestInfo, tool_name: str,
               usage_inputs: list[dict],
               iag_type_override: IagType | None = None,
               qualification: QualificationProfile | None = None,
               tool_version_plan_tarifaire: str | None = None) -> InterviewState:
        state = InterviewState(interview_id=str(uuid.uuid4()), request=request)
        if qualification is not None:
            state.qualification = qualification
        with trace_step(state.interview_id, "assess", tool_name=tool_name):
            entry = lookup_tool(tool_name)
            iag_type = classify_tool_type(tool_name)
            if iag_type is None:
                if iag_type_override is None:
                    raise UnknownToolError(tool_name)
                iag_type = iag_type_override
            state.tools.append(ToolRef(
                name=tool_name,
                vendor=entry["vendor"] if entry else None,
                iag_type=iag_type,
                version_plan_tarifaire=tool_version_plan_tarifaire or "",
            ))

            # Classify each usage's data description first, then resolve (and cache)
            # the tool's contract facts once — this fixes the LLM call order to
            # (1) data classifier signals per usage, (2) ARP contract facts.
            classifications = []
            for i, item in enumerate(usage_inputs):
                description = item["data_description"]
                with trace_step(None, "classify_data", usage_index=i,
                                 **mask_text(description)) as extra:
                    classification = classify_data(description, self._llm)
                    extra.update(
                        data_classification=classification.data_classification,
                        rens_personnels=classification.rens_personnels,
                        confidence=classification.confidence,
                        needs_officer_confirmation=classification.needs_officer_confirmation,
                    )
                classifications.append((item, classification))

            facts = self._resolve_arp(tool_name, iag_type)

            for i, (item, classification) in enumerate(classifications):
                usage = Usage(
                    description=item.get("description", ""),
                    tool_ref=tool_name,
                    data_classification=classification.data_classification,
                    rens_personnels=classification.rens_personnels,
                    classifier_confidence=classification.confidence,
                    needs_officer_confirmation=classification.needs_officer_confirmation,
                    mode=item.get("mode", []),
                    frequence_utilisation=item.get("frequence_utilisation", ""),
                    nb_utilisateurs=item.get("nb_utilisateurs"),
                    systemes_api_cibles=item.get("systemes_api_cibles", ""),
                    result_use=item.get("result_use", []),
                    automated_decisions=item.get("automated_decisions", False),
                )
                with trace_step(None, "evaluate_usage", usage_index=i) as extra:
                    evaluated = evaluate_usage(usage, facts, iag_type)
                    extra.update(
                        matrix_result=evaluated.matrix_result,
                        risk_level=evaluated.risk_level,
                        verdict=evaluated.verdict,
                    )
                state.usages.append(evaluated)

            with trace_step(None, "synthesize") as extra:
                state.result_global = synthesize(state.usages)
                extra.update(
                    risk_level=state.result_global.risk_level,
                    recommendation=state.result_global.recommendation,
                    efvpr_required=state.result_global.efvpr_required,
                )
            state.status = "complete"
        return state
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/interview/test_orchestrator.py -v`
Expected: PASS (all tests, including the 2 new ones).

- [ ] **Step 5: Run the full suite, then commit**

Run: `pytest -v`
Expected: PASS.

```bash
git add policybot/interview/orchestrator.py tests/interview/test_orchestrator.py
git commit -m "feat(interview): thread QualificationProfile and section-3 usage fields through assess()"
```

---

### Task 4: Insert the "profil_utilisateurs" wizard screen

**Files:**
- Create: `policybot/web/templates/wizard_profil_utilisateurs.html.j2`
- Modify: `policybot/web/templates/wizard_outil.html.j2`
- Modify: `policybot/web/templates/wizard_tool_type.html.j2`
- Modify: `policybot/web/templates/_steps.html.j2`
- Modify: `policybot/web/routes.py`
- Modify: `tests/web/test_routes_outil.py`
- Create: `tests/web/test_routes_profil_utilisateurs.py`

**Interfaces:**
- Consumes: `WizardState` fields from Task 2 (`version_plan_tarifaire`, `nb_utilisateurs_vises`, `fonctions_roles`, `niveau_maitrise_ti`, `formation_iag_recue`, `acces_protege_a_ou_plus`).
- Produces: new route `POST /wizard/profil-utilisateurs` rendering `wizard_donnees.html.j2` (unchanged target); `wizard_outil` and `wizard_outil/type` now render `wizard_profil_utilisateurs.html.j2` instead of `wizard_donnees.html.j2`.

- [ ] **Step 1: Write the failing tests**

Replace the two tests in `tests/web/test_routes_outil.py` that currently assert a jump straight to the "données" step:

```python
def test_known_tool_skips_straight_to_profil_utilisateurs_step(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/outil", data={
        "tool_name": "ChatGPT", "tool_name_other": "", "version_plan_tarifaire": "Plan Plus",
    })
    assert resp.status_code == 200
    assert "profil" in resp.text.lower()
    assert 'value="ChatGPT"' in resp.text
    assert 'name="version_plan_tarifaire" value="Plan Plus"' in resp.text
```

```python
def test_confirming_tool_type_carries_override_to_profil_utilisateurs_step(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/outil/type", data={
        "tool_name": "Notion AI", "tool_type": "IAG circuit fermé",
    })
    assert resp.status_code == 200
    assert 'value="circuit_ferme"' in resp.text
    assert "profil" in resp.text.lower()
```

Also update `test_unknown_tool_renders_guided_fallback_with_llm_guess_precheck` to check `version_plan_tarifaire` is carried onto the tool-type screen:

```python
def test_unknown_tool_renders_guided_fallback_with_llm_guess_precheck(tmp_path):
    client = _client(tmp_path, json_responses=[{"iag_type_guess": "publique", "confidence": 0.7}])
    resp = client.post("/wizard/outil", data={
        "tool_name": "", "tool_name_other": "Notion AI", "version_plan_tarifaire": "Free",
    })
    assert resp.status_code == 200
    assert "type d" in resp.text.lower()
    checked_marker = 'value="IAG publique" checked'
    assert checked_marker in resp.text
    assert 'name="version_plan_tarifaire" value="Free"' in resp.text
```

Create `tests/web/test_routes_profil_utilisateurs.py`:

```python
from fastapi.testclient import TestClient
from policybot.llm.fake import FakeLLMProvider
from policybot.preapproved.store import PreApprovedStore
from policybot.interview.orchestrator import Interview
from policybot.api.app import create_app


def _client(tmp_path, json_responses=None):
    llm = FakeLLMProvider(json_responses=json_responses or [])
    itv = Interview(llm=llm, store=PreApprovedStore(str(tmp_path / "pb.db")),
                    http_get=lambda url: "<html><body>ok</body></html>")
    return TestClient(create_app(itv))


def test_profil_utilisateurs_submit_renders_donnees_step_with_hidden_fields(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/profil-utilisateurs", data={
        "tool_name": "ChatGPT",
        "version_plan_tarifaire": "Plan Plus",
        "nb_utilisateurs_vises": "25",
        "fonctions_roles": "conseillers pédagogiques",
        "niveau_maitrise_ti": "intermédiaire",
        "formation_iag_recue": "partielle",
        "acces_protege_a_ou_plus": "non",
    })
    assert resp.status_code == 200
    assert "données" in resp.text.lower()
    assert 'name="tool_name" value="ChatGPT"' in resp.text
    assert 'name="version_plan_tarifaire" value="Plan Plus"' in resp.text
    assert 'name="nb_utilisateurs_vises" value="25"' in resp.text
    assert 'name="fonctions_roles" value="conseillers pédagogiques"' in resp.text
    assert 'name="niveau_maitrise_ti" value="intermédiaire"' in resp.text
    assert 'name="formation_iag_recue" value="partielle"' in resp.text
    assert 'name="acces_protege_a_ou_plus" value="non"' in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_routes_outil.py tests/web/test_routes_profil_utilisateurs.py -v`
Expected: FAIL — old assertions ("données" text) don't match, and `/wizard/profil-utilisateurs` returns 404.

- [ ] **Step 3: Implement the screen, routes, and stepper**

Create `policybot/web/templates/wizard_profil_utilisateurs.html.j2`:

```html
{# policybot/web/templates/wizard_profil_utilisateurs.html.j2 #}
{% extends "_layout.html.j2" %}
{% block content %}
<div class="kicker">Étape 2 · Profil utilisateurs</div>
<h1>Qui va utiliser cet outil&nbsp;?</h1>
<div class="assist"><img src="/static/friendly.png" alt=""> Ces informations aident à évaluer les risques liés aux personnes qui utiliseront l'outil.</div>
<form method="post" action="/wizard/profil-utilisateurs">
  {% for name, value in hidden_fields %}
  <input type="hidden" name="{{ name }}" value="{{ value }}">
  {% endfor %}
  <label class="freefield">
    Nombre d'utilisateurs visés :
    <input type="number" name="nb_utilisateurs_vises" min="0">
  </label>
  <label class="freefield">
    Fonctions / rôles concernés :
    <input type="text" name="fonctions_roles" placeholder="ex. agents de bureau, conseillers pédagogiques">
  </label>
  <div class="grid">
    <label class="opt"><div class="top"><input type="radio" name="niveau_maitrise_ti" value="débutant"></div><b>Débutant</b></label>
    <label class="opt"><div class="top"><input type="radio" name="niveau_maitrise_ti" value="intermédiaire"></div><b>Intermédiaire</b></label>
    <label class="opt"><div class="top"><input type="radio" name="niveau_maitrise_ti" value="avancé"></div><b>Avancé</b></label>
  </div>
  <div class="grid">
    <label class="opt"><div class="top"><input type="radio" name="formation_iag_recue" value="aucune"></div><b>Aucune formation IAG reçue</b></label>
    <label class="opt"><div class="top"><input type="radio" name="formation_iag_recue" value="partielle"></div><b>Formation partielle</b></label>
    <label class="opt"><div class="top"><input type="radio" name="formation_iag_recue" value="complète"></div><b>Formation complète (MCN)</b></label>
  </div>
  <div class="grid">
    <label class="opt"><div class="top"><input type="radio" name="acces_protege_a_ou_plus" value="oui"></div><b>Accès à Protégé A+ : Oui</b></label>
    <label class="opt"><div class="top"><input type="radio" name="acces_protege_a_ou_plus" value="non"></div><b>Accès à Protégé A+ : Non</b></label>
    <label class="opt"><div class="top"><input type="radio" name="acces_protege_a_ou_plus" value="à vérifier"></div><b>À vérifier</b></label>
  </div>
  <div class="foot">
    <button class="back" type="button" onclick="history.back()">← Retour</button>
    <button class="next" type="submit">Continuer →</button>
  </div>
</form>
{% endblock %}
```

In `policybot/web/templates/wizard_outil.html.j2`, add the version field before the `foot` div (currently line 17):

```html
  <label class="freefield">
    Version / plan tarifaire (optionnel) :
    <input type="text" name="version_plan_tarifaire" placeholder="ex. Plan Plus, Entreprise">
  </label>
  <div class="foot">
```

In `policybot/web/templates/wizard_tool_type.html.j2`, add a hidden field right after the existing `tool_name` hidden input (currently line 8):

```html
  <input type="hidden" name="tool_name" value="{{ tool_name }}">
  <input type="hidden" name="version_plan_tarifaire" value="{{ version_plan_tarifaire }}">
```

In `policybot/web/templates/_steps.html.j2`, replace line 2-3:

```jinja
{% set order = ["outil", "profil_utilisateurs", "donnees", "usage", "resultats", "resultat"] %}
{% set labels = {"outil": "Ton outil", "profil_utilisateurs": "Profil utilisateurs", "donnees": "Tes données", "usage": "Ton usage", "resultats": "Usage des résultats", "resultat": "Résultat"} %}
```

In `policybot/web/routes.py`, replace the `wizard_outil`, `wizard_outil_type` functions (currently lines 44-81) and insert a new route right after `wizard_outil_type`:

```python
@router.post("/wizard/outil", response_class=HTMLResponse)
async def wizard_outil(request: Request):
    form = _group_form(await request.form())
    tool_name = (form.get("tool_name") or form.get("tool_name_other") or "").strip()
    version_plan_tarifaire = form.get("version_plan_tarifaire", "") or ""

    if classify_tool_type(tool_name) is not None or lookup_tool(tool_name) is not None:
        state = WizardState(tool_name=tool_name, version_plan_tarifaire=version_plan_tarifaire)
        return templates.TemplateResponse(request, "wizard_profil_utilisateurs.html.j2", {
            "active_step": "profil_utilisateurs",
            "hidden_fields": state.to_hidden_fields(),
        })

    llm = request.app.state.interview.llm
    try:
        guessed_type = guess_tool_type(tool_name, llm)
    except Exception:
        guessed_type = None
    guessed_label = IAG_TYPE_LABELS.get(guessed_type) if guessed_type else None
    return templates.TemplateResponse(request, "wizard_tool_type.html.j2", {
        "active_step": "outil",
        "question": tool_type_question(), "tool_name": tool_name,
        "guessed_label": guessed_label,
        "version_plan_tarifaire": version_plan_tarifaire,
    })


@router.post("/wizard/outil/type", response_class=HTMLResponse)
async def wizard_outil_type(request: Request):
    form = _group_form(await request.form())
    tool_name = form.get("tool_name", "") or ""
    tool_type_label = form.get("tool_type", "") or ""
    tool_type_override = LABEL_TO_IAG_TYPE.get(tool_type_label)
    version_plan_tarifaire = form.get("version_plan_tarifaire", "") or ""
    state = WizardState(tool_name=tool_name, tool_type_override=tool_type_override,
                         version_plan_tarifaire=version_plan_tarifaire)
    return templates.TemplateResponse(request, "wizard_profil_utilisateurs.html.j2", {
        "active_step": "profil_utilisateurs",
        "hidden_fields": state.to_hidden_fields(),
    })


@router.post("/wizard/profil-utilisateurs", response_class=HTMLResponse)
async def wizard_profil_utilisateurs_submit(request: Request):
    form = _group_form(await request.form())
    state = WizardState.from_form(form)
    return templates.TemplateResponse(request, "wizard_donnees.html.j2", {
        "active_step": "donnees",
        "hidden_fields": state.to_hidden_fields(),
        "question": data_description_question(),
    })
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/web/test_routes_outil.py tests/web/test_routes_profil_utilisateurs.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite, then commit**

Run: `pytest -v`
Expected: PASS (routes.py's `wizard_donnees` function is untouched, so `tests/web/test_routes_donnees.py` still passes unmodified).

```bash
git add policybot/web/templates/wizard_profil_utilisateurs.html.j2 \
        policybot/web/templates/wizard_outil.html.j2 \
        policybot/web/templates/wizard_tool_type.html.j2 \
        policybot/web/templates/_steps.html.j2 \
        policybot/web/routes.py \
        tests/web/test_routes_outil.py \
        tests/web/test_routes_profil_utilisateurs.py
git commit -m "feat(web): insert profil_utilisateurs wizard screen after outil step"
```

---

### Task 5: Add section-3 fields to the "usage" screen

**Files:**
- Modify: `policybot/web/templates/wizard_usage.html.j2`
- Modify: `tests/web/test_routes_usage.py`

**Interfaces:**
- Consumes: `WizardState.frequence_utilisation`/`nb_utilisateurs`/`systemes_api_cibles` (Task 2). No route or model changes needed — `wizard_donnees`/`wizard_usage_submit` already round-trip every `WizardState` field generically.

- [ ] **Step 1: Write the failing test**

Replace `test_usage_submit_renders_resultats_step_with_hidden_fields` in `tests/web/test_routes_usage.py`:

```python
def test_usage_submit_renders_resultats_step_with_hidden_fields(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/usage", data={
        "tool_name": "ChatGPT",
        "usage_description": "Chercher des informations publiques",
        "mode": "prompt",
        "frequence_utilisation": "quelques fois par semaine",
        "nb_utilisateurs": "10",
        "systemes_api_cibles": "",
    })
    assert resp.status_code == 200
    assert "Usage des résultats" in resp.text
    assert "Comment comptez-vous utiliser les résultats" in resp.text
    assert 'name="tool_name" value="ChatGPT"' in resp.text
    assert 'name="usage_description" value="Chercher des informations publiques"' in resp.text
    assert 'name="mode" value="prompt"' in resp.text
    assert 'name="frequence_utilisation" value="quelques fois par semaine"' in resp.text
    assert 'name="nb_utilisateurs" value="10"' in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/web/test_routes_usage.py -v`
Expected: FAIL — the new fields aren't in the posted form's echo because `wizard_usage.html.j2` doesn't render them as hidden fields on this screen yet (the assertion for `frequence_utilisation`/`nb_utilisateurs` in the *next* screen's hidden fields fails since nothing was captured to carry forward — the test posts them directly to `/wizard/usage`, so this actually already passes at the `WizardState` layer from Task 2. This step's real purpose is to prove the *screen itself* exposes the inputs to a real user).

Since `WizardState.from_form` (Task 2) already parses these fields regardless of which screen posted them, this specific test will already pass before the template edit. Add a second, template-focused assertion instead — append to the same test file:

```python
def test_usage_screen_renders_section3_input_fields(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/donnees", data={"tool_name": "ChatGPT"})
    assert resp.status_code == 200
    assert 'name="frequence_utilisation"' in resp.text
    assert 'name="nb_utilisateurs"' in resp.text
    assert 'name="systemes_api_cibles"' in resp.text
```

Run: `pytest tests/web/test_routes_usage.py -v`
Expected: FAIL on `test_usage_screen_renders_section3_input_fields` — the three input names aren't present in `wizard_usage.html.j2` yet.

- [ ] **Step 3: Implement the template change**

In `policybot/web/templates/wizard_usage.html.j2`, insert before the `<div class="foot">` (currently line 21):

```html
  <label class="freefield">
    Fréquence d'utilisation prévue :
    <input type="text" name="frequence_utilisation" placeholder="ex. quelques fois par semaine">
  </label>
  <label class="freefield">
    Nombre d'utilisateurs pour cet usage :
    <input type="number" name="nb_utilisateurs" min="0">
  </label>
  <label class="freefield">
    Systèmes cibles si intégré par API :
    <input type="text" name="systemes_api_cibles" placeholder="ex. CRM interne, portail étudiant">
  </label>
  <div class="foot">
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/web/test_routes_usage.py -v`
Expected: PASS (all tests in the file, including both new/changed ones).

- [ ] **Step 5: Run the full suite, then commit**

Run: `pytest -v`
Expected: PASS.

```bash
git add policybot/web/templates/wizard_usage.html.j2 tests/web/test_routes_usage.py
git commit -m "feat(web): capture usage frequency, user count, and API targets on the usage screen"
```

---

### Task 6: Insert the "contexte_affaires" wizard screen and move the `assess()` call

**Files:**
- Create: `policybot/web/templates/wizard_contexte_affaires.html.j2`
- Modify: `policybot/web/templates/_steps.html.j2`
- Modify: `policybot/web/routes.py`
- Modify: `tests/web/test_routes_resultat.py`
- Create: `tests/web/test_routes_resultats_step.py`

**Interfaces:**
- Consumes: `WizardState` context fields (Task 2), `Interview.assess(qualification=..., tool_version_plan_tarifaire=...)` (Task 3).
- Produces: `POST /wizard/resultats` now renders `wizard_contexte_affaires.html.j2` (intermediate screen) instead of calling `assess()`; new `POST /wizard/contexte-affaires` is the terminal route that calls `assess()` and renders `resultat.html.j2` or `error.html.j2`.

- [ ] **Step 1: Write the failing tests**

Create `tests/web/test_routes_resultats_step.py`:

```python
from fastapi.testclient import TestClient
from policybot.llm.fake import FakeLLMProvider
from policybot.preapproved.store import PreApprovedStore
from policybot.interview.orchestrator import Interview
from policybot.api.app import create_app


def _client(tmp_path, json_responses=None):
    llm = FakeLLMProvider(json_responses=json_responses or [])
    itv = Interview(llm=llm, store=PreApprovedStore(str(tmp_path / "pb.db")),
                    http_get=lambda url: "<html><body>ok</body></html>")
    return TestClient(create_app(itv))


def test_resultats_submit_renders_contexte_affaires_step_with_hidden_fields(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/resultats", data={
        "tool_name": "ChatGPT",
        "usage_description": "Chercher des informations publiques",
        "mode": "prompt",
        "result_use_checked": "Publication",
    })
    assert resp.status_code == 200
    assert "contexte d'affaires" in resp.text.lower()
    assert 'name="tool_name" value="ChatGPT"' in resp.text
    assert 'name="result_use_checked" value="Publication"' in resp.text
```

Replace the full contents of `tests/web/test_routes_resultat.py` — same four tests, only the posted URL changes from `/wizard/resultats` to `/wizard/contexte-affaires`:

```python
# tests/web/test_routes_resultat.py
from fastapi.testclient import TestClient
from policybot.llm.fake import FakeLLMProvider
from policybot.preapproved.store import PreApprovedStore
from policybot.interview.orchestrator import Interview
from policybot.api.app import create_app


def _client(tmp_path, json_responses=None):
    llm = FakeLLMProvider(json_responses=json_responses or [])
    itv = Interview(llm=llm, store=PreApprovedStore(str(tmp_path / "pb.db")),
                    http_get=lambda url: "<html><body>ok</body></html>")
    return TestClient(create_app(itv))


def test_final_submit_renders_report_on_success(tmp_path):
    client = _client(tmp_path, json_responses=[
        {"already_public": True, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.9},
        {"trains_on_input": "no", "data_residency": "canada", "extraction_confidence": 0.9},
    ])
    resp = client.post("/wizard/contexte-affaires", data={
        "tool_name": "ChatGPT",
        "data_checked": "Info déjà publique",
        "usage_description": "Chercher de l'info publique",
        "mode": "prompt",
    })
    assert resp.status_code == 200
    assert "Rapport de recommandation" in resp.text
    assert "Autoriser" in resp.text


def test_golden_scenario_chatgpt_protege_b_is_refused(tmp_path):
    client = _client(tmp_path, json_responses=[
        {"already_public": False, "contains_personal_info": False,
         "strategic_sensitive": True, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.9},
        {"trains_on_input": "yes", "data_residency": "us", "extraction_confidence": 0.9},
    ])
    resp = client.post("/wizard/contexte-affaires", data={
        "tool_name": "ChatGPT",
        "data_checked": "Données stratégiques / confidentielles",
        "usage_description": "Analyser des chiffres financiers internes",
        "mode": "prompt",
    })
    assert resp.status_code == 200
    assert "Refuser" in resp.text


def test_final_submit_renders_error_screen_when_assess_fails(tmp_path):
    client = _client(tmp_path, json_responses=[])  # empty queue -> classify_data raises IndexError
    resp = client.post("/wizard/contexte-affaires", data={
        "tool_name": "ChatGPT",
        "data_checked": "Info déjà publique",
        "usage_description": "Chercher de l'info publique",
        "mode": "prompt",
    })
    assert resp.status_code == 502
    assert "bloqué" in resp.text.lower()


def test_final_submit_logs_exception_when_assess_fails(tmp_path, caplog):
    client = _client(tmp_path, json_responses=[])  # empty queue -> classify_data raises IndexError
    with caplog.at_level("ERROR", logger="policybot.web.routes"):
        resp = client.post("/wizard/contexte-affaires", data={
            "tool_name": "ChatGPT",
            "data_checked": "Info déjà publique",
            "usage_description": "Chercher de l'info publique",
            "mode": "prompt",
        })
    assert resp.status_code == 502
    assert any("assess failed" in record.message for record in caplog.records)
    assert any(record.exc_info for record in caplog.records)
```

Also add one assertion of the qualification/version wiring reaching `assess()` through the real route — append to `tests/web/test_routes_resultat.py`:

```python
def test_final_submit_passes_qualification_fields_into_assess(tmp_path):
    client = _client(tmp_path, json_responses=[
        {"already_public": True, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.9},
        {"trains_on_input": "no", "data_residency": "canada", "extraction_confidence": 0.9},
    ])
    resp = client.post("/wizard/contexte-affaires", data={
        "tool_name": "ChatGPT",
        "version_plan_tarifaire": "Plan Plus",
        "data_checked": "Info déjà publique",
        "usage_description": "Chercher de l'info publique",
        "mode": "prompt",
        "frequence_utilisation": "quotidienne",
        "nb_utilisateurs_vises": "25",
        "fonctions_roles": "conseillers",
        "besoin_affaires": "gagner du temps",
        "mode_acquisition": "seao",
    })
    assert resp.status_code == 200
    assert "Rapport de recommandation" in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_routes_resultat.py tests/web/test_routes_resultats_step.py -v`
Expected: FAIL — `/wizard/contexte-affaires` returns 404, and `/wizard/resultats` still calls `assess()` directly instead of rendering the new intermediate screen.

- [ ] **Step 3: Implement the screen and route rewiring**

Create `policybot/web/templates/wizard_contexte_affaires.html.j2`:

```html
{# policybot/web/templates/wizard_contexte_affaires.html.j2 #}
{% extends "_layout.html.j2" %}
{% block content %}
<div class="kicker">Étape 6 · Contexte d'affaires</div>
<h1>Quelques dernières questions sur ce projet</h1>
<div class="assist"><img src="/static/friendly.png" alt=""> Ça nous aide à documenter la valeur attendue et le cadre contractuel.</div>
<form method="post" action="/wizard/contexte-affaires">
  {% for name, value in hidden_fields %}
  <input type="hidden" name="{{ name }}" value="{{ value }}">
  {% endfor %}
  <label class="freefield">
    Besoin ou problème d'affaires adressé :
    <input type="text" name="besoin_affaires">
  </label>
  <label class="freefield">
    Gains anticipés (qualitatifs) :
    <input type="text" name="gains_qualitatifs">
  </label>
  <label class="freefield">
    Gains anticipés (quantitatifs) :
    <input type="text" name="gains_quantitatifs" placeholder="ex. heures économisées, coût évité">
  </label>
  <label class="freefield">
    Alternatives considérées (outils déjà disponibles à l'UQAM) :
    <input type="text" name="alternatives_considerees">
  </label>
  <div class="grid">
    <label class="opt"><div class="top"><input type="radio" name="urgence_percue" value="faible"></div><b>Urgence faible</b></label>
    <label class="opt"><div class="top"><input type="radio" name="urgence_percue" value="modérée"></div><b>Urgence modérée</b></label>
    <label class="opt"><div class="top"><input type="radio" name="urgence_percue" value="élevée"></div><b>Urgence élevée</b></label>
  </div>
  <label class="freefield">
    Coût estimé (annuel par utilisateur) :
    <input type="text" name="cout_annuel_par_utilisateur">
  </label>
  <label class="freefield">
    Coût total estimé (annuel) :
    <input type="text" name="cout_total_annuel">
  </label>
  <div class="grid">
    <label class="opt"><div class="top"><input type="radio" name="mode_acquisition" value="achat_direct"></div><b>Achat direct</b></label>
    <label class="opt"><div class="top"><input type="radio" name="mode_acquisition" value="seao"></div><b>Via SEAO</b></label>
    <label class="opt"><div class="top"><input type="radio" name="mode_acquisition" value="appel_offres"></div><b>Via appel d'offres</b></label>
    <label class="opt"><div class="top"><input type="radio" name="mode_acquisition" value="contrat_existant"></div><b>Contrat existant</b></label>
  </div>
  <label class="freefield">
    Durée du contrat envisagée :
    <input type="text" name="duree_contrat">
  </label>
  <label class="freefield">
    Responsable budgétaire :
    <input type="text" name="responsable_budgetaire">
  </label>
  <div class="foot">
    <button class="back" type="button" onclick="history.back()">← Retour</button>
    <button class="next" type="submit">Voir le résultat →</button>
  </div>
</form>
{% endblock %}
```

In `policybot/web/templates/_steps.html.j2`, replace line 2-3 (set in Task 4) with the final list:

```jinja
{% set order = ["outil", "profil_utilisateurs", "donnees", "usage", "resultats", "contexte_affaires", "resultat"] %}
{% set labels = {"outil": "Ton outil", "profil_utilisateurs": "Profil utilisateurs", "donnees": "Tes données", "usage": "Ton usage", "resultats": "Usage des résultats", "contexte_affaires": "Contexte d'affaires", "resultat": "Résultat"} %}
```

In `policybot/web/routes.py`:

1. Add `QualificationProfile` to the models import (currently line 13):

```python
from policybot.models import RequestInfo, QualificationProfile
```

2. Replace the `wizard_usage_submit` and `wizard_resultats_submit` functions (their
   line numbers have shifted since Task 4 inserted `wizard_profil_utilisateurs_submit`
   earlier in the file — locate them by name, not by line number) with:

```python
@router.post("/wizard/usage", response_class=HTMLResponse)
async def wizard_usage_submit(request: Request):
    form = _group_form(await request.form())
    state = WizardState.from_form(form)
    return templates.TemplateResponse(request, "wizard_resultats.html.j2", {
        "active_step": "resultats",
        "hidden_fields": state.to_hidden_fields(),
        "question": usage_details_question(),
    })


@router.post("/wizard/resultats", response_class=HTMLResponse)
async def wizard_resultats_submit(request: Request):
    form = _group_form(await request.form())
    state = WizardState.from_form(form)
    return templates.TemplateResponse(request, "wizard_contexte_affaires.html.j2", {
        "active_step": "contexte_affaires",
        "hidden_fields": state.to_hidden_fields(),
    })


def _as_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@router.post("/wizard/contexte-affaires", response_class=HTMLResponse)
async def wizard_contexte_affaires_submit(request: Request):
    form = _group_form(await request.form())
    state = WizardState.from_form(form)
    description = compose_description(state.data_checked, state.data_free_text)
    result_use = list(state.result_use_checked)
    if state.result_use_free_text:
        result_use.append(state.result_use_free_text)
    usage_input = {
        "description": state.usage_description,
        "data_description": description,
        "automated_decisions": state.automated_decisions,
        "mode": [state.mode] if state.mode else ["prompt"],
        "result_use": result_use,
        "frequence_utilisation": state.frequence_utilisation,
        "nb_utilisateurs": _as_int(state.nb_utilisateurs),
        "systemes_api_cibles": state.systemes_api_cibles,
    }
    qualification = QualificationProfile(
        nb_utilisateurs_vises=_as_int(state.nb_utilisateurs_vises),
        fonctions_roles=state.fonctions_roles,
        niveau_maitrise_ti=state.niveau_maitrise_ti or None,
        formation_iag_recue=state.formation_iag_recue or None,
        acces_protege_a_ou_plus=state.acces_protege_a_ou_plus or None,
        besoin_affaires=state.besoin_affaires,
        gains_qualitatifs=state.gains_qualitatifs,
        gains_quantitatifs=state.gains_quantitatifs,
        alternatives_considerees=state.alternatives_considerees,
        urgence_percue=state.urgence_percue or None,
        cout_annuel_par_utilisateur=state.cout_annuel_par_utilisateur,
        cout_total_annuel=state.cout_total_annuel,
        mode_acquisition=state.mode_acquisition or None,
        duree_contrat=state.duree_contrat,
        responsable_budgetaire=state.responsable_budgetaire,
    )
    itv: Interview = request.app.state.interview
    numero = f"IAG-{date.today():%Y}-{uuid.uuid4().hex[:6]}"
    try:
        result_state = itv.assess(
            request=RequestInfo(numero=numero),
            tool_name=state.tool_name,
            usage_inputs=[usage_input],
            iag_type_override=state.tool_type_override,
            qualification=qualification,
            tool_version_plan_tarifaire=state.version_plan_tarifaire,
        )
    except Exception:
        logger.exception("wizard/contexte-affaires assess failed for tool_name=%r numero=%s", state.tool_name, numero)
        return templates.TemplateResponse(request, "error.html.j2", {
            "active_step": "contexte_affaires",
        }, status_code=502)
    report_html = render_html(result_state)
    return templates.TemplateResponse(request, "resultat.html.j2", {
        "active_step": "resultat", "report_html": report_html,
    })
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/web/test_routes_resultat.py tests/web/test_routes_resultats_step.py -v`
Expected: PASS (all tests, including the new qualification-wiring test).

- [ ] **Step 5: Run the full suite, then commit**

Run: `pytest -v`
Expected: PASS.

```bash
git add policybot/web/templates/wizard_contexte_affaires.html.j2 \
        policybot/web/templates/_steps.html.j2 \
        policybot/web/routes.py \
        tests/web/test_routes_resultat.py \
        tests/web/test_routes_resultats_step.py
git commit -m "feat(web): insert contexte_affaires screen and move the assess() call to it"
```

---

### Task 7: Full regression pass

**Files:** none (verification only).

- [ ] **Step 1: Run the entire test suite**

Run: `pytest -v`
Expected: PASS — every test file in `tests/` (including `tests/test_golden_scenarios.py`, which calls `Interview.assess` directly and is unaffected by the wizard/route changes) passes.

- [ ] **Step 2: Manually smoke-test the new flow**

Run: `uvicorn policybot.api.app:app --reload` and walk through the wizard in a browser: `outil` (fill version/plan tarifaire) → `profil_utilisateurs` (fill all 5 fields) → `donnees` → `usage` (fill fréquence/nb utilisateurs/API) → `resultats` → `contexte_affaires` (fill all 9 fields) → confirm the final report renders as before (this plan intentionally does not render the new fields into the report — that's the next sub-project).

- [ ] **Step 3: Commit is already done per-task — no further action**

No additional commit needed; Task 7 is verification-only. If Step 1 or Step 2 surfaces a regression, fix it within the task whose file caused it, re-run `pytest -v`, and commit the fix with a message referencing which task's code it corrects.
