# PolicyBot Web UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the browser-based interview wizard (tool → données → usage → résultat) described in `docs/superpowers/specs/2026-07-06-policybot-web-ui-design.md`, so an employee can run PolicyBot end-to-end without writing Python.

**Architecture:** A new `policybot/web/` package holds Jinja2 templates, a stateless `WizardState` carried across steps as hidden form fields, and a small `ai_assist.py` module of LLM-assist helpers (`guess_tool_type`, `guess_mode`, `suggest_options`). Step-to-step navigation is plain HTML form POSTs (full page reload); HTMX is used only for small in-page fragments (AI suggestions, mode guess) that swap into a `<div>` without leaving the page. The wizard's final step calls the existing `Interview.assess(...)` in-process and renders the existing `render_html(state)` report unmodified.

**Tech Stack:** FastAPI (already a dependency), Jinja2 (already used by `report/renderer.py`), vendored htmx.min.js (no CDN, no build step), pytest + `fastapi.testclient.TestClient` (already used in `tests/api/test_app.py`).

## Global Constraints

- Python `>=3.11`, project already installed editable (`pip install -e ".[dev]"`).
- No new runtime dependency may be added beyond what's in `pyproject.toml` today (`fastapi`, `jinja2`, `httpx`, `pydantic`, etc.) — htmx is a vendored static file, not a pip package. **One necessary exception:** `python-multipart` is required by FastAPI/Starlette to parse `await request.form()`; it is added in Task 3 since every `/wizard/*` route from Task 4 onward depends on it.
- `classify_data()`, `Interview.assess()`, `render_html()`, and every other already-tested backend function are **not modified** — the web layer only calls them.
- Single usage per submission for this pass (per spec §1/§13) — `usage_inputs` is always built as a one-item list.
- No server-side session store — all wizard state travels in hidden form fields (spec §9).
- Every AI-assist call (`guess_tool_type`, `guess_mode`, `suggest_options`) must degrade gracefully on failure — never a 500, per spec §11.
- French UI copy throughout, tutoiement, mascotte (`friendly.png` = reassuring, `Thinking.png` = guessing/uncertain) — per spec §2.

---

## File Structure

```
policybot/web/
  __init__.py
  ai_assist.py          # guess_tool_type, guess_mode, suggest_options + label<->IagType maps
  wizard_state.py        # WizardState, compose_description
  routes.py              # APIRouter with all /  and /wizard/* endpoints
  templates/
    _layout.html.j2
    _steps.html.j2
    _suggest_fragment.html.j2
    wizard_mode_fragment.html.j2
    wizard_outil.html.j2
    wizard_tool_type.html.j2
    wizard_donnees.html.j2
    wizard_usage.html.j2
    resultat.html.j2
    error.html.j2
  static/
    htmx.min.js
    style.css
    friendly.png
    thinking.png
policybot/interview/orchestrator.py   # + Interview.llm property (modify)
policybot/api/app.py                  # + mount web router + static files (modify)
tests/web/
  __init__.py
  test_wizard_state.py
  test_ai_assist.py
  test_routes_outil.py
  test_routes_donnees.py
  test_routes_usage.py
  test_routes_resultat.py
```

---

## Task 1: `WizardState` + `compose_description`

**Files:**
- Create: `policybot/web/__init__.py` (empty)
- Create: `policybot/web/wizard_state.py`
- Test: `tests/web/__init__.py` (empty)
- Test: `tests/web/test_wizard_state.py`

**Interfaces:**
- Produces: `WizardState` (Pydantic model, fields: `tool_name: str`, `tool_type_override: IagType | None`, `data_checked: list[str]`, `data_free_text: str`, `usage_description: str`, `mode: Literal["prompt","api"] | None`, `result_use_checked: list[str]`, `result_use_free_text: str`, `automated_decisions: bool`); `WizardState.to_hidden_fields() -> list[tuple[str, str]]`; `WizardState.from_form(form: dict) -> WizardState`; `compose_description(checked_labels: list[str], free_text: str) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/web/test_wizard_state.py
from policybot.web.wizard_state import WizardState, compose_description


def test_compose_description_joins_labels_and_free_text():
    result = compose_description(
        ["Renseignements personnels", "Documents internes de travail"],
        "des courriels d'étudiants",
    )
    assert result == "Renseignements personnels; Documents internes de travail; des courriels d'étudiants"


def test_compose_description_with_only_free_text():
    assert compose_description([], "info publique") == "info publique"


def test_compose_description_with_only_labels():
    assert compose_description(["Info déjà publique"], "") == "Info déjà publique"


def test_to_hidden_fields_only_emits_nonempty_values():
    state = WizardState(tool_name="ChatGPT", data_checked=["A", "B"])
    fields = state.to_hidden_fields()
    assert ("tool_name", "ChatGPT") in fields
    assert ("data_checked", "A") in fields
    assert ("data_checked", "B") in fields
    assert not any(name == "tool_type_override" for name, _ in fields)
    assert not any(name == "automated_decisions" for name, _ in fields)


def test_to_hidden_fields_emits_automated_decisions_only_when_true():
    state = WizardState(automated_decisions=True)
    fields = state.to_hidden_fields()
    assert ("automated_decisions", "true") in fields


def test_from_form_roundtrips_single_and_repeated_fields():
    form = {
        "tool_name": "ChatGPT",
        "tool_type_override": "publique",
        "data_checked": ["Renseignements personnels", "Documents internes de travail"],
        "data_free_text": "notes de cours",
        "usage_description": "Résumer des articles",
        "mode": "api",
        "result_use_checked": "Publication",
        "result_use_free_text": "",
        "automated_decisions": "true",
    }
    state = WizardState.from_form(form)
    assert state.tool_name == "ChatGPT"
    assert state.tool_type_override == "publique"
    assert state.data_checked == ["Renseignements personnels", "Documents internes de travail"]
    assert state.data_free_text == "notes de cours"
    assert state.mode == "api"
    assert state.result_use_checked == ["Publication"]
    assert state.automated_decisions is True


def test_from_form_defaults_on_missing_keys():
    state = WizardState.from_form({})
    assert state.tool_name == ""
    assert state.tool_type_override is None
    assert state.data_checked == []
    assert state.mode is None
    assert state.automated_decisions is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_wizard_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'policybot.web'`

- [ ] **Step 3: Write minimal implementation**

```python
# policybot/web/__init__.py
```

```python
# policybot/web/wizard_state.py
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field
from policybot.models import IagType


class WizardState(BaseModel):
    tool_name: str = ""
    tool_type_override: IagType | None = None
    data_checked: list[str] = Field(default_factory=list)
    data_free_text: str = ""
    usage_description: str = ""
    mode: Literal["prompt", "api"] | None = None
    result_use_checked: list[str] = Field(default_factory=list)
    result_use_free_text: str = ""
    automated_decisions: bool = False

    def to_hidden_fields(self) -> list[tuple[str, str]]:
        fields: list[tuple[str, str]] = []
        if self.tool_name:
            fields.append(("tool_name", self.tool_name))
        if self.tool_type_override:
            fields.append(("tool_type_override", self.tool_type_override))
        for label in self.data_checked:
            fields.append(("data_checked", label))
        if self.data_free_text:
            fields.append(("data_free_text", self.data_free_text))
        if self.usage_description:
            fields.append(("usage_description", self.usage_description))
        if self.mode:
            fields.append(("mode", self.mode))
        for label in self.result_use_checked:
            fields.append(("result_use_checked", label))
        if self.result_use_free_text:
            fields.append(("result_use_free_text", self.result_use_free_text))
        if self.automated_decisions:
            fields.append(("automated_decisions", "true"))
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
            data_checked=as_list("data_checked"),
            data_free_text=form.get("data_free_text", "") or "",
            usage_description=form.get("usage_description", "") or "",
            mode=form.get("mode") or None,
            result_use_checked=as_list("result_use_checked"),
            result_use_free_text=form.get("result_use_free_text", "") or "",
            automated_decisions=str(form.get("automated_decisions", "")).lower() == "true",
        )


def compose_description(checked_labels: list[str], free_text: str) -> str:
    parts = list(checked_labels) + ([free_text] if free_text else [])
    return "; ".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/web/test_wizard_state.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add policybot/web/__init__.py policybot/web/wizard_state.py tests/web/__init__.py tests/web/test_wizard_state.py
git commit -m "feat(web): add stateless WizardState and description composition"
```

---

## Task 2: `ai_assist.py` — LLM-assist helpers

**Files:**
- Create: `policybot/web/ai_assist.py`
- Test: `tests/web/test_ai_assist.py`

**Interfaces:**
- Consumes: `LLMProvider` (`policybot/llm/provider.py`, `complete_json(system, user) -> dict`), `FakeLLMProvider` (`policybot/llm/fake.py`), `QuestionSpec`/`QuestionOption` (`policybot/models.py`), `IagType` (`policybot/models.py`).
- Produces: `guess_tool_type(name: str, llm: LLMProvider) -> IagType | None`; `guess_mode(description: str, llm: LLMProvider) -> Literal["prompt", "api"]`; `suggest_options(question: QuestionSpec, free_text: str, llm: LLMProvider) -> list[QuestionOption]`; `IAG_TYPE_LABELS: dict[str, str]` (IagType -> question label, e.g. `"publique" -> "IAG publique"`); `LABEL_TO_IAG_TYPE: dict[str, str]` (reverse of the above).

- [ ] **Step 1: Write the failing tests**

```python
# tests/web/test_ai_assist.py
from policybot.llm.fake import FakeLLMProvider
from policybot.models import QuestionSpec, QuestionOption
from policybot.web.ai_assist import (
    guess_tool_type, guess_mode, suggest_options,
    IAG_TYPE_LABELS, LABEL_TO_IAG_TYPE,
)


def test_guess_tool_type_returns_valid_iag_type():
    llm = FakeLLMProvider(json_responses=[{"iag_type_guess": "publique", "confidence": 0.8}])
    assert guess_tool_type("Notion AI", llm) == "publique"


def test_guess_tool_type_returns_none_on_invalid_guess():
    llm = FakeLLMProvider(json_responses=[{"iag_type_guess": "n'importe quoi", "confidence": 0.1}])
    assert guess_tool_type("OutilBizarre", llm) is None


def test_guess_mode_returns_api_when_llm_says_so():
    llm = FakeLLMProvider(json_responses=[{"mode_guess": "api", "confidence": 0.7}])
    assert guess_mode("Intégré à notre CRM via un connecteur", llm) == "api"


def test_guess_mode_defaults_to_prompt_on_invalid_guess():
    llm = FakeLLMProvider(json_responses=[{"mode_guess": "autre chose", "confidence": 0.2}])
    assert guess_mode("Je tape mes questions", llm) == "prompt"


def test_suggest_options_returns_new_options_from_llm():
    question = QuestionSpec(
        id="data_description", header="h", question="q",
        options=[QuestionOption(label="Info déjà publique")],
    )
    llm = FakeLLMProvider(json_responses=[{"options": [
        {"label": "Renseignements personnels d'étudiants", "description": "Courriels, notes"},
        {"label": "Correspondance nominative", "description": ""},
    ]}])
    result = suggest_options(question, "des courriels d'étudiants", llm)
    assert [o.label for o in result] == [
        "Renseignements personnels d'étudiants", "Correspondance nominative",
    ]
    assert result[0].description == "Courriels, notes"


def test_suggest_options_filters_out_duplicates_of_existing_options():
    question = QuestionSpec(
        id="data_description", header="h", question="q",
        options=[QuestionOption(label="Info déjà publique")],
    )
    llm = FakeLLMProvider(json_responses=[{"options": [
        {"label": "Info déjà publique", "description": "déjà là"},
        {"label": "Nouvelle option", "description": ""},
    ]}])
    result = suggest_options(question, "texte", llm)
    assert [o.label for o in result] == ["Nouvelle option"]


def test_iag_type_label_maps_are_consistent():
    assert LABEL_TO_IAG_TYPE[IAG_TYPE_LABELS["publique"]] == "publique"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_ai_assist.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'policybot.web.ai_assist'`

- [ ] **Step 3: Write minimal implementation**

```python
# policybot/web/ai_assist.py
from __future__ import annotations
from typing import Literal
from policybot.llm.provider import LLMProvider
from policybot.models import QuestionSpec, QuestionOption, IagType

IAG_TYPE_LABELS: dict[str, str] = {
    "publique": "IAG publique",
    "circuit_ferme": "IAG circuit fermé",
    "souveraine": "IAG souveraine",
    "gouvernementale": "IAG gouvernementale",
}
LABEL_TO_IAG_TYPE: dict[str, str] = {v: k for k, v in IAG_TYPE_LABELS.items()}

_TOOL_TYPE_SYSTEM = (
    "Tu classes un outil d'IA générative nommé par un employé, parmi 4 "
    "catégories de gouvernance : 'publique' (accessible à tous, ex. ChatGPT, "
    "Claude.ai), 'circuit_ferme' (offre entreprise avec contrat, ex. Copilot "
    "Entreprise), 'souveraine' (hébergée au Québec), 'gouvernementale' "
    "(hébergée par l'UQAM ou le gouvernement). Réponds en JSON avec les clés "
    "iag_type_guess (une des 4 valeurs exactes ci-dessus) et confidence (0-1)."
)

_MODE_SYSTEM = (
    "Tu déduis si un employé va utiliser un outil d'IA générative en tapant "
    "des messages directement ('prompt') ou via une intégration technique/API "
    "dans un autre système ('api'), à partir de sa description d'usage en "
    "langage clair. Réponds en JSON avec les clés mode_guess ('prompt' ou "
    "'api') et confidence (0-1)."
)

_SUGGEST_SYSTEM_TEMPLATE = (
    "Un employé répond à la question suivante dans un formulaire : \"{question}\". "
    "Les choix déjà proposés sont : {existing}. L'employé a écrit un texte libre "
    "qui ne correspond à aucun choix existant : \"{free_text}\". Propose entre 2 "
    "et 4 nouveaux choix courts et précis, adaptés à ce texte, qui ne répètent "
    "pas les choix déjà proposés. Réponds en JSON avec la clé options : une "
    "liste d'objets avec les clés label et description."
)


def guess_tool_type(name: str, llm: LLMProvider) -> IagType | None:
    result = llm.complete_json(_TOOL_TYPE_SYSTEM, name)
    guess = result.get("iag_type_guess")
    return guess if guess in IAG_TYPE_LABELS else None


def guess_mode(description: str, llm: LLMProvider) -> Literal["prompt", "api"]:
    result = llm.complete_json(_MODE_SYSTEM, description)
    guess = result.get("mode_guess")
    return guess if guess in ("prompt", "api") else "prompt"


def suggest_options(question: QuestionSpec, free_text: str, llm: LLMProvider) -> list[QuestionOption]:
    existing_labels = {opt.label for opt in question.options}
    system = _SUGGEST_SYSTEM_TEMPLATE.format(
        question=question.question,
        existing=", ".join(existing_labels) or "aucun",
        free_text=free_text,
    )
    result = llm.complete_json(system, free_text)
    raw_options = result.get("options", [])
    return [
        QuestionOption(label=o["label"], description=o.get("description", ""))
        for o in raw_options
        if o.get("label") and o["label"] not in existing_labels
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/web/test_ai_assist.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add policybot/web/ai_assist.py tests/web/test_ai_assist.py
git commit -m "feat(web): add LLM-assist helpers (tool-type guess, mode guess, option suggestions)"
```

---

## Task 3: App foundation — static assets, base layout, `GET /`, app wiring

**Files:**
- Modify: `policybot/interview/orchestrator.py` (add `Interview.llm` property)
- Create: `policybot/web/routes.py`
- Create: `policybot/web/templates/_layout.html.j2`
- Create: `policybot/web/templates/_steps.html.j2`
- Create: `policybot/web/templates/wizard_outil.html.j2`
- Create: `policybot/web/static/style.css`
- Create: `policybot/web/static/htmx.min.js`
- Create: `policybot/web/static/friendly.png` (copy of repo-root `friendly.png`)
- Create: `policybot/web/static/thinking.png` (copy of repo-root `Thinking.png`)
- Modify: `policybot/api/app.py` (mount web router + static files)
- Test: `tests/web/test_routes_outil.py` (only the `GET /` case in this task; `POST /wizard/outil` cases land in Task 4)

**Interfaces:**
- Consumes: `Interview` (`policybot/interview/orchestrator.py`), `create_app(itv: Interview) -> FastAPI` (`policybot/api/app.py`, existing).
- Produces: `Interview.llm` property (`-> LLMProvider`); `policybot/web/routes.py: router` (an `APIRouter`); `create_app` now also serves `GET /` and `/static/*`.

- [ ] **Step 1: Write the failing test**

```python
# tests/web/test_routes_outil.py
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


def test_home_page_renders_outil_step(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "PolicyBot" in resp.text
    assert "outil" in resp.text.lower()


def test_static_files_are_served(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/static/style.css")
    assert resp.status_code == 200
    resp = client.get("/static/htmx.min.js")
    assert resp.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/web/test_routes_outil.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'policybot.web.routes'`

- [ ] **Step 3a: Add the `Interview.llm` property**

Edit `policybot/interview/orchestrator.py`, in the `Interview` class (after `__init__`, before `_resolve_arp`):

```python
    @property
    def llm(self) -> LLMProvider:
        return self._llm
```

- [ ] **Step 3a-bis: Add `python-multipart` (required by FastAPI to parse `request.form()`)**

Edit `pyproject.toml`, in the `dependencies` list:

```toml
dependencies = [
    "pydantic>=2.6",
    "langgraph>=0.2",
    "fastapi>=0.110",
    "uvicorn>=0.29",
    "jinja2>=3.1",
    "httpx>=0.27",
    "beautifulsoup4>=4.12",
    "pyyaml>=6.0",
    "python-multipart>=0.0.9",
]
```

Then reinstall:

```bash
pip install -e ".[dev]"
```

- [ ] **Step 3b: Vendor htmx and copy mascotte assets**

```bash
mkdir -p policybot/web/static
curl -s -o policybot/web/static/htmx.min.js https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js
cp friendly.png policybot/web/static/friendly.png
cp Thinking.png policybot/web/static/thinking.png
```

If there is no network access to fetch htmx at implementation time, vendor any locally available copy of htmx.org 1.9.x `htmx.min.js` into `policybot/web/static/htmx.min.js` instead — the exact version doesn't matter, only that `hx-post`/`hx-target`/`hx-trigger`/`hx-swap` attributes are supported (stable since htmx 1.x).

- [ ] **Step 3c: Write `style.css`**

```css
/* policybot/web/static/style.css */
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --teal:#3d7d85; --teal-dark:#2b6169; --red:#d8352f; --ink:#101827;
  --muted:#5d6b7a; --line:#e5e9ef;
}
body{
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  color:var(--ink); background:#fff; line-height:1.55;
}
.app{display:grid;grid-template-columns:230px 1fr;min-height:100vh}
.rail{background:#0f1620;color:#cdd6df;padding:2rem 1.5rem;display:flex;flex-direction:column}
.rail .brand{display:flex;align-items:center;gap:.6rem;font-weight:800;font-size:1.02rem;color:#fff;margin-bottom:2.2rem}
.rail .brand img{width:34px;height:34px}
.steps .st{display:flex;align-items:center;gap:.7rem;font-size:.85rem;padding:.5rem 0;color:#5d6b7a}
.steps .st .n{width:22px;height:22px;border-radius:50%;border:1.5px solid #2c3f52;display:grid;place-items:center;font-size:.72rem;flex:none}
.steps .st.done{color:#8fb4bd}
.steps .st.done .n{background:var(--teal);border-color:var(--teal);color:#fff}
.steps .st.active{color:#fff}
.steps .st.active .n{border-color:var(--red);color:#fff;background:var(--red)}
.main{padding:2.6rem 2.6rem 2.2rem;max-width:760px}
.kicker{font-size:.72rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--teal);margin-bottom:.6rem}
h1{font-size:1.5rem;font-weight:800;letter-spacing:-.02em;line-height:1.2;margin-bottom:.5rem;max-width:22ch}
.assist{display:flex;gap:.6rem;align-items:center;color:var(--muted);font-size:.86rem;margin-bottom:1.7rem}
.assist img{width:30px;height:30px}
.chips{display:flex;flex-wrap:wrap;gap:.6rem;margin-bottom:1rem}
.chip{border:1.5px solid var(--line);border-radius:99px;padding:.5rem 1rem;font-size:.9rem;cursor:pointer}
.chip:has(input:checked){border-color:var(--teal);background:#f4fafa}
.chip input{margin-right:.4rem}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:.75rem;margin-bottom:1rem}
.opt{border:1.5px solid var(--line);border-radius:12px;padding:1rem 1.05rem;cursor:pointer;display:flex;flex-direction:column;gap:.35rem}
.opt:has(input:checked){border-color:var(--teal);background:#f4fafa}
.opt .top{display:flex;align-items:center;justify-content:space-between}
.opt b{font-size:.92rem;font-weight:600}
.opt small{font-size:.76rem;color:#8a95a3;line-height:1.35}
.freefield{display:block;font-size:.88rem;color:var(--muted);margin-bottom:1.2rem}
.freefield input[type=text]{display:block;width:100%;margin-top:.4rem;padding:.6rem .8rem;border:1.5px solid var(--line);border-radius:8px;font-size:.92rem}
.foot{display:flex;justify-content:space-between;align-items:center;border-top:1px solid #eef1f4;padding-top:1.3rem;margin-top:1rem}
.back{background:none;border:none;color:#8a95a3;font-size:.9rem;cursor:pointer}
.next{background:var(--ink);color:#fff;border:none;border-radius:10px;padding:.75rem 1.7rem;font-size:.92rem;font-weight:600;cursor:pointer}
.next:hover{background:#000}
.disclaimer{margin-top:1.5rem;text-align:center;font-size:.78rem;color:#a3adba}
.disclaimer b{color:var(--red)}
.report{border:1px solid var(--line);border-radius:10px;padding:1.5rem 1.8rem;margin-bottom:1.5rem}
@media(max-width:680px){
  .app{grid-template-columns:1fr}
  .rail{flex-direction:row;flex-wrap:wrap;gap:.5rem 1rem}
  .rail .brand{width:100%;margin-bottom:.6rem}
  .grid{grid-template-columns:1fr}
}
```

- [ ] **Step 3d: Write `_layout.html.j2` and `_steps.html.j2`**

```jinja2
{# policybot/web/templates/_layout.html.j2 #}
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PolicyBot</title>
<link rel="stylesheet" href="/static/style.css">
<script src="/static/htmx.min.js"></script>
</head>
<body>
<div class="app">
  <aside class="rail">
    <div class="brand"><img src="/static/friendly.png" alt="PolicyBot"> PolicyBot</div>
    {% include "_steps.html.j2" %}
  </aside>
  <main class="main">
    {% block content %}{% endblock %}
    <p class="disclaimer">🤖 PolicyBot <b>recommande</b>, il n'autorise jamais. La décision finale revient à l'agent SI.</p>
  </main>
</div>
</body>
</html>
```

```jinja2
{# policybot/web/templates/_steps.html.j2 #}
{% set order = ["outil", "donnees", "usage", "resultat"] %}
{% set labels = {"outil": "Ton outil", "donnees": "Tes données", "usage": "Ton usage", "resultat": "Résultat"} %}
<nav class="steps">
{% for key in order %}
  {% if order.index(active_step) > loop.index0 %}
    <div class="st done"><span class="n">✓</span> {{ labels[key] }}</div>
  {% elif key == active_step %}
    <div class="st active"><span class="n">{{ loop.index }}</span> {{ labels[key] }}</div>
  {% else %}
    <div class="st"><span class="n">{{ loop.index }}</span> {{ labels[key] }}</div>
  {% endif %}
{% endfor %}
</nav>
```

- [ ] **Step 3e: Write `wizard_outil.html.j2`**

```jinja2
{# policybot/web/templates/wizard_outil.html.j2 #}
{% extends "_layout.html.j2" %}
{% block content %}
<div class="kicker">Étape 1 · Ton outil</div>
<h1>Quel outil d'IA générative comptes-tu utiliser&nbsp;?</h1>
<div class="assist"><img src="/static/friendly.png" alt=""> Choisis un outil connu ou tape son nom.</div>
<form method="post" action="/wizard/outil">
  <div class="chips">
    {% for name in known_tools %}
    <label class="chip"><input type="radio" name="tool_name" value="{{ name }}"> {{ name }}</label>
    {% endfor %}
  </div>
  <label class="freefield">
    Autre outil :
    <input type="text" name="tool_name_other" placeholder="Nom de l'outil">
  </label>
  <div class="foot">
    <span></span>
    <button class="next" type="submit">Continuer →</button>
  </div>
</form>
{% endblock %}
```

- [ ] **Step 3f: Write `routes.py`**

```python
# policybot/web/routes.py
from __future__ import annotations
import os
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=_TEMPLATES_DIR)

KNOWN_TOOLS = ["ChatGPT", "ChatGPT Pro", "Claude.ai", "Perplexity", "Microsoft Copilot Entreprise"]

router = APIRouter()


def _group_form(form) -> dict:
    grouped: dict[str, object] = {}
    for key in dict.fromkeys(form.keys()):
        values = form.getlist(key)
        if not values:
            continue
        grouped[key] = values if len(values) > 1 else values[0]
    return grouped


@router.get("/", response_class=HTMLResponse)
def wizard_home(request: Request):
    return templates.TemplateResponse("wizard_outil.html.j2", {
        "request": request, "active_step": "outil", "known_tools": KNOWN_TOOLS,
    })
```

- [ ] **Step 3g: Mount the router and static files in `create_app`**

Edit `policybot/api/app.py`:

```python
from __future__ import annotations
import os
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from policybot.models import InterviewState, RequestInfo
from policybot.interview.orchestrator import Interview, UnknownToolError
from policybot.interview.graph import run_graph
from policybot.classify.tool_type import tool_type_question
from policybot.report.renderer import render_html
from policybot.api.deps import default_interview
from policybot.web.routes import router as web_router

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "web", "static")


def create_app(itv: Interview) -> FastAPI:
    app = FastAPI(title="PolicyBot")
    app.state.interview = itv
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
    app.include_router(web_router)

    @app.post("/assess", response_model=None)
    def assess(payload: dict) -> InterviewState | JSONResponse:
        try:
            return run_graph(
                itv,
                RequestInfo(**payload["request"]),
                payload["tool_name"],
                payload["usage_inputs"],
                payload.get("iag_type_override"),
            )
        except UnknownToolError:
            return JSONResponse(
                status_code=422,
                content={
                    "error": "unknown_tool",
                    "question": tool_type_question().model_dump(),
                },
            )

    @app.post("/report", response_class=HTMLResponse)
    def report(state: InterviewState) -> str:
        return render_html(state)

    return app


app = create_app(default_interview())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/web/test_routes_outil.py -v`
Expected: PASS (2 tests). Also re-run the full suite to confirm nothing broke: `pytest -v` — expect the pre-existing 64 tests plus the new ones, all passing.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml policybot/interview/orchestrator.py policybot/web/routes.py policybot/web/templates policybot/web/static policybot/api/app.py tests/web/test_routes_outil.py
git commit -m "feat(web): wire app foundation - static assets, base layout, home page"
```

---

## Task 4: Step 1 — Outil (known tool + unknown-tool fallback with AI guess)

**Files:**
- Modify: `policybot/web/routes.py` (add `POST /wizard/outil`, `POST /wizard/outil/type`)
- Create: `policybot/web/templates/wizard_tool_type.html.j2`
- Create: `policybot/web/templates/wizard_donnees.html.j2` (shell only — Task 5 fills in the données-specific fields; this task needs it to exist so `/wizard/outil` has somewhere to render to)
- Test: `tests/web/test_routes_outil.py` (extend)

**Interfaces:**
- Consumes: `lookup_tool` (`policybot/classify/tool_registry.py`), `classify_tool_type` (`policybot/classify/tool_type.py`), `tool_type_question` (`policybot/classify/tool_type.py`), `guess_tool_type`, `IAG_TYPE_LABELS`, `LABEL_TO_IAG_TYPE` (Task 2), `WizardState` (Task 1).
- Produces: `POST /wizard/outil`, `POST /wizard/outil/type` routes; `wizard_donnees.html.j2` (minimal shell, extended in Task 5).

- [ ] **Step 1: Write the failing tests**

```python
# tests/web/test_routes_outil.py — append to the file created in Task 3
def test_known_tool_skips_straight_to_donnees_step(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/outil", data={"tool_name": "ChatGPT", "tool_name_other": ""})
    assert resp.status_code == 200
    assert "données" in resp.text.lower()
    assert 'value="ChatGPT"' in resp.text


def test_unknown_tool_renders_guided_fallback_with_llm_guess_precheck(tmp_path):
    client = _client(tmp_path, json_responses=[{"iag_type_guess": "publique", "confidence": 0.7}])
    resp = client.post("/wizard/outil", data={"tool_name": "", "tool_name_other": "Notion AI"})
    assert resp.status_code == 200
    assert "type d" in resp.text.lower()
    checked_marker = 'value="IAG publique" checked'
    assert checked_marker in resp.text


def test_confirming_tool_type_carries_override_to_donnees_step(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/outil/type", data={
        "tool_name": "Notion AI", "tool_type": "IAG circuit fermé",
    })
    assert resp.status_code == 200
    assert 'value="circuit_ferme"' in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_routes_outil.py -v`
Expected: FAIL — `TemplateNotFound: wizard_donnees.html.j2` (or 404/405 on the new routes, since they don't exist yet).

- [ ] **Step 3a: Write `wizard_tool_type.html.j2`**

```jinja2
{# policybot/web/templates/wizard_tool_type.html.j2 #}
{% extends "_layout.html.j2" %}
{% block content %}
<div class="kicker">Étape 1 · Type d'outil</div>
<h1>{{ question.question }}</h1>
<div class="assist"><img src="/static/thinking.png" alt=""> Je ne connais pas encore « {{ tool_name }} ». Voici ma meilleure estimation — corrige-la si besoin.</div>
<form method="post" action="/wizard/outil/type">
  <input type="hidden" name="tool_name" value="{{ tool_name }}">
  <div class="grid">
    {% for opt in question.options %}
    <label class="opt">
      <div class="top">
        <input type="radio" name="tool_type" value="{{ opt.label }}" {% if opt.label == guessed_label %}checked{% endif %}>
      </div>
      <b>{{ opt.label }}</b><small>{{ opt.description }}</small>
    </label>
    {% endfor %}
  </div>
  <div class="foot">
    <button class="back" type="button" onclick="history.back()">← Retour</button>
    <button class="next" type="submit">Confirmer →</button>
  </div>
</form>
{% endblock %}
```

- [ ] **Step 3b: Write the `wizard_donnees.html.j2` shell**

```jinja2
{# policybot/web/templates/wizard_donnees.html.j2 #}
{% extends "_layout.html.j2" %}
{% block content %}
<div class="kicker">Étape 2 · Tes données</div>
<h1>Quel type de données comptes-tu soumettre à l'outil&nbsp;?</h1>
<div class="assist"><img src="/static/friendly.png" alt=""> Pas besoin de montrer tes données — décris-les avec tes mots.</div>
<form method="post" action="/wizard/donnees">
  {% for name, value in hidden_fields %}
  <input type="hidden" name="{{ name }}" value="{{ value }}">
  {% endfor %}
  <div class="foot">
    <button class="back" type="button" onclick="history.back()">← Retour</button>
    <button class="next" type="submit">Continuer →</button>
  </div>
</form>
{% endblock %}
```

- [ ] **Step 3c: Add the two routes to `routes.py`**

Add these imports at the top of `policybot/web/routes.py`:

```python
from policybot.classify.tool_registry import lookup_tool
from policybot.classify.tool_type import classify_tool_type, tool_type_question
from policybot.interview.questions import data_description_question
from policybot.web.ai_assist import guess_tool_type, IAG_TYPE_LABELS, LABEL_TO_IAG_TYPE
from policybot.web.wizard_state import WizardState
```

Append these routes at the end of `policybot/web/routes.py`:

```python
@router.post("/wizard/outil", response_class=HTMLResponse)
async def wizard_outil(request: Request):
    form = _group_form(await request.form())
    tool_name = (form.get("tool_name") or form.get("tool_name_other") or "").strip()

    if classify_tool_type(tool_name) is not None or lookup_tool(tool_name) is not None:
        state = WizardState(tool_name=tool_name)
        return templates.TemplateResponse("wizard_donnees.html.j2", {
            "request": request, "active_step": "donnees",
            "hidden_fields": state.to_hidden_fields(),
            "question": data_description_question(),
        })

    llm = request.app.state.interview.llm
    try:
        guessed_type = guess_tool_type(tool_name, llm)
    except Exception:
        guessed_type = None
    guessed_label = IAG_TYPE_LABELS.get(guessed_type) if guessed_type else None
    return templates.TemplateResponse("wizard_tool_type.html.j2", {
        "request": request, "active_step": "outil",
        "question": tool_type_question(), "tool_name": tool_name,
        "guessed_label": guessed_label,
    })


@router.post("/wizard/outil/type", response_class=HTMLResponse)
async def wizard_outil_type(request: Request):
    form = _group_form(await request.form())
    tool_name = form.get("tool_name", "") or ""
    tool_type_label = form.get("tool_type", "") or ""
    tool_type_override = LABEL_TO_IAG_TYPE.get(tool_type_label)
    state = WizardState(tool_name=tool_name, tool_type_override=tool_type_override)
    return templates.TemplateResponse("wizard_donnees.html.j2", {
        "request": request, "active_step": "donnees",
        "hidden_fields": state.to_hidden_fields(),
        "question": data_description_question(),
    })
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/web/test_routes_outil.py -v`
Expected: PASS (5 tests total in this file).

- [ ] **Step 5: Commit**

```bash
git add policybot/web/routes.py policybot/web/templates/wizard_tool_type.html.j2 policybot/web/templates/wizard_donnees.html.j2 tests/web/test_routes_outil.py
git commit -m "feat(web): step 1 (outil) with known-tool fast path and AI-guessed fallback"
```

---

## Task 5: Step 2 — Données (checkboxes + free text + AI suggestions)

**Files:**
- Modify: `policybot/web/routes.py` (add `POST /wizard/donnees`, `POST /wizard/suggest/donnees`)
- Modify: `policybot/web/templates/wizard_donnees.html.j2` (fill in real content)
- Create: `policybot/web/templates/_suggest_fragment.html.j2`
- Create: `policybot/web/templates/wizard_usage.html.j2` (shell only — Task 6 fills in usage-specific fields)
- Test: `tests/web/test_routes_donnees.py`

**Interfaces:**
- Consumes: `data_description_question` (`policybot/interview/questions.py`), `suggest_options` (Task 2), `WizardState`/`compose_description` (Task 1).
- Produces: `POST /wizard/donnees`, `POST /wizard/suggest/donnees` routes; `wizard_usage.html.j2` (minimal shell, extended in Task 6).

- [ ] **Step 1: Write the failing tests**

```python
# tests/web/test_routes_donnees.py
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


def test_donnees_submit_renders_usage_step_with_hidden_fields(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/donnees", data=[
        ("tool_name", "ChatGPT"),
        ("data_checked", "Renseignements personnels"),
        ("data_checked", "Documents internes de travail"),
        ("data_free_text", "notes de cours"),
    ])
    assert resp.status_code == 200
    assert "usage" in resp.text.lower()
    assert 'name="data_checked" value="Renseignements personnels"' in resp.text
    assert 'name="data_free_text" value="notes de cours"' in resp.text


def test_suggest_donnees_returns_fragment_with_new_checkboxes(tmp_path):
    client = _client(tmp_path, json_responses=[{"options": [
        {"label": "Renseignements personnels d'étudiants", "description": "Courriels, notes"},
    ]}])
    resp = client.post("/wizard/suggest/donnees", data={"data_free_text": "des courriels d'étudiants"})
    assert resp.status_code == 200
    assert "Renseignements personnels d'étudiants" in resp.text
    assert "<!DOCTYPE" not in resp.text


def test_suggest_donnees_with_empty_free_text_returns_no_options(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/suggest/donnees", data={"data_free_text": ""})
    assert resp.status_code == 200
    assert resp.text.strip() == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_routes_donnees.py -v`
Expected: FAIL — 404 on both new routes (they don't exist yet).

- [ ] **Step 3a: Write `_suggest_fragment.html.j2`**

```jinja2
{# policybot/web/templates/_suggest_fragment.html.j2 #}
{% for opt in options %}
<label class="opt">
  <div class="top"><input type="checkbox" name="{{ field_name }}" value="{{ opt.label }}"></div>
  <b>{{ opt.label }}</b><small>{{ opt.description }}</small>
</label>
{% endfor %}
```

- [ ] **Step 3b: Fill in `wizard_donnees.html.j2`**

```jinja2
{# policybot/web/templates/wizard_donnees.html.j2 #}
{% extends "_layout.html.j2" %}
{% block content %}
<div class="kicker">Étape 2 · Tes données</div>
<h1>{{ question.question }}</h1>
<div class="assist"><img src="/static/friendly.png" alt=""> Pas besoin de montrer tes données — décris-les avec tes mots.</div>
<form method="post" action="/wizard/donnees">
  {% for name, value in hidden_fields %}
  <input type="hidden" name="{{ name }}" value="{{ value }}">
  {% endfor %}
  <div class="grid" id="data-options">
    {% for opt in question.options %}
    <label class="opt">
      <div class="top"><input type="checkbox" name="data_checked" value="{{ opt.label }}"></div>
      <b>{{ opt.label }}</b><small>{{ opt.description }}</small>
    </label>
    {% endfor %}
  </div>
  <div id="suggested-donnees"></div>
  <label class="freefield">
    Autre (en tes mots) :
    <input type="text" name="data_free_text"
           hx-post="/wizard/suggest/donnees" hx-trigger="changed delay:500ms"
           hx-target="#suggested-donnees" hx-swap="innerHTML">
  </label>
  <div class="foot">
    <button class="back" type="button" onclick="history.back()">← Retour</button>
    <button class="next" type="submit">Continuer →</button>
  </div>
</form>
{% endblock %}
```

- [ ] **Step 3c: Write the `wizard_usage.html.j2` shell**

```jinja2
{# policybot/web/templates/wizard_usage.html.j2 #}
{% extends "_layout.html.j2" %}
{% block content %}
<div class="kicker">Étape 3 · Ton usage</div>
<h1>Comment vas-tu utiliser cet outil&nbsp;?</h1>
<div class="assist"><img src="/static/friendly.png" alt=""> Décris ce que tu comptes faire, en tes mots.</div>
<form method="post" action="/wizard/usage">
  {% for name, value in hidden_fields %}
  <input type="hidden" name="{{ name }}" value="{{ value }}">
  {% endfor %}
  <div class="foot">
    <button class="back" type="button" onclick="history.back()">← Retour</button>
    <button class="next" type="submit">Voir le résultat →</button>
  </div>
</form>
{% endblock %}
```

- [ ] **Step 3d: Add routes to `routes.py`**

Add these imports at the top of `policybot/web/routes.py` (`data_description_question` is already imported from Task 4 — only add `usage_details_question` next to it):

```python
from policybot.interview.questions import usage_details_question
from policybot.web.ai_assist import suggest_options
from policybot.web.wizard_state import compose_description
```

Append these routes at the end of `policybot/web/routes.py`:

```python
@router.post("/wizard/donnees", response_class=HTMLResponse)
async def wizard_donnees(request: Request):
    form = _group_form(await request.form())
    state = WizardState.from_form(form)
    return templates.TemplateResponse("wizard_usage.html.j2", {
        "request": request, "active_step": "usage",
        "hidden_fields": state.to_hidden_fields(),
        "question": usage_details_question(),
    })


@router.post("/wizard/suggest/donnees", response_class=HTMLResponse)
async def suggest_donnees(request: Request):
    form = _group_form(await request.form())
    free_text = form.get("data_free_text", "") or ""
    options = []
    if free_text:
        llm = request.app.state.interview.llm
        try:
            options = suggest_options(data_description_question(), free_text, llm)
        except Exception:
            options = []
    return templates.TemplateResponse("_suggest_fragment.html.j2", {
        "request": request, "options": options, "field_name": "data_checked",
    })
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/web/test_routes_donnees.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add policybot/web/routes.py policybot/web/templates/wizard_donnees.html.j2 policybot/web/templates/_suggest_fragment.html.j2 policybot/web/templates/wizard_usage.html.j2 tests/web/test_routes_donnees.py
git commit -m "feat(web): step 2 (donnees) with checkboxes, free text, and AI-suggested options"
```

---

## Task 6: Step 3 — Usage (description, AI-guessed mode, result_use, automated_decisions)

**Files:**
- Modify: `policybot/web/routes.py` (add `POST /wizard/mode-guess`, `POST /wizard/suggest/usage`)
- Modify: `policybot/web/templates/wizard_usage.html.j2` (fill in real content)
- Create: `policybot/web/templates/wizard_mode_fragment.html.j2`
- Test: `tests/web/test_routes_usage.py`

**Interfaces:**
- Consumes: `usage_details_question` (`policybot/interview/questions.py`), `guess_mode`, `suggest_options` (Task 2).
- Produces: `POST /wizard/mode-guess`, `POST /wizard/suggest/usage` routes.

- [ ] **Step 1: Write the failing tests**

```python
# tests/web/test_routes_usage.py
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


def test_mode_guess_returns_fragment_with_guessed_mode_checked(tmp_path):
    client = _client(tmp_path, json_responses=[{"mode_guess": "api", "confidence": 0.8}])
    resp = client.post("/wizard/mode-guess", data={"usage_description": "Intégré à notre CRM"})
    assert resp.status_code == 200
    assert 'value="api" checked' in resp.text
    assert "<!DOCTYPE" not in resp.text


def test_mode_guess_with_empty_description_defaults_to_prompt(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/mode-guess", data={"usage_description": ""})
    assert resp.status_code == 200
    assert 'value="prompt" checked' in resp.text


def test_suggest_usage_returns_fragment_with_new_checkboxes(tmp_path):
    client = _client(tmp_path, json_responses=[{"options": [
        {"label": "Analyse statistique interne", "description": ""},
    ]}])
    resp = client.post("/wizard/suggest/usage", data={"result_use_free_text": "pour des stats internes"})
    assert resp.status_code == 200
    assert "Analyse statistique interne" in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_routes_usage.py -v`
Expected: FAIL — 404 on both new routes.

- [ ] **Step 3a: Write `wizard_mode_fragment.html.j2`**

```jinja2
{# policybot/web/templates/wizard_mode_fragment.html.j2 #}
<label><input type="radio" name="mode" value="prompt" {% if guessed_mode == "prompt" %}checked{% endif %}> Je tape mes questions directement</label>
<label><input type="radio" name="mode" value="api" {% if guessed_mode == "api" %}checked{% endif %}> C'est intégré à un autre système (API)</label>
```

- [ ] **Step 3b: Fill in `wizard_usage.html.j2`**

```jinja2
{# policybot/web/templates/wizard_usage.html.j2 #}
{% extends "_layout.html.j2" %}
{% block content %}
<div class="kicker">Étape 3 · Ton usage</div>
<h1>Comment vas-tu utiliser cet outil&nbsp;?</h1>
<div class="assist"><img src="/static/friendly.png" alt=""> Décris ce que tu comptes faire, en tes mots.</div>
<form method="post" action="/wizard/usage">
  {% for name, value in hidden_fields %}
  <input type="hidden" name="{{ name }}" value="{{ value }}">
  {% endfor %}
  <label class="freefield">
    Description de l'usage :
    <input type="text" name="usage_description"
           hx-post="/wizard/mode-guess" hx-trigger="changed delay:500ms"
           hx-target="#mode-fragment" hx-swap="innerHTML">
  </label>
  <div id="mode-fragment">
    <label><input type="radio" name="mode" value="prompt" checked> Je tape mes questions directement</label>
    <label><input type="radio" name="mode" value="api"> C'est intégré à un autre système (API)</label>
  </div>
  <h1>{{ question.question }}</h1>
  <div class="grid" id="usage-options">
    {% for opt in question.options %}
    <label class="opt">
      <div class="top"><input type="checkbox" name="result_use_checked" value="{{ opt.label }}"></div>
      <b>{{ opt.label }}</b>
    </label>
    {% endfor %}
  </div>
  <div id="suggested-usage"></div>
  <label class="freefield">
    Autre :
    <input type="text" name="result_use_free_text"
           hx-post="/wizard/suggest/usage" hx-trigger="changed delay:500ms"
           hx-target="#suggested-usage" hx-swap="innerHTML">
  </label>
  <label class="opt">
    <div class="top"><input type="checkbox" name="automated_decisions" value="true"></div>
    <b>Décision automatisée</b>
    <small>Le résultat va-t-il déclencher une décision automatique sans révision humaine&nbsp;?</small>
  </label>
  <div class="foot">
    <button class="back" type="button" onclick="history.back()">← Retour</button>
    <button class="next" type="submit">Voir le résultat →</button>
  </div>
</form>
{% endblock %}
```

- [ ] **Step 3c: Add routes to `routes.py`**

Add this import at the top of `policybot/web/routes.py`:

```python
from policybot.web.ai_assist import guess_mode
```

Append these routes at the end of `policybot/web/routes.py`:

```python
@router.post("/wizard/mode-guess", response_class=HTMLResponse)
async def mode_guess(request: Request):
    form = _group_form(await request.form())
    description = form.get("usage_description", "") or ""
    guessed = "prompt"
    if description:
        llm = request.app.state.interview.llm
        try:
            guessed = guess_mode(description, llm)
        except Exception:
            guessed = "prompt"
    return templates.TemplateResponse("wizard_mode_fragment.html.j2", {
        "request": request, "guessed_mode": guessed,
    })


@router.post("/wizard/suggest/usage", response_class=HTMLResponse)
async def suggest_usage(request: Request):
    form = _group_form(await request.form())
    free_text = form.get("result_use_free_text", "") or ""
    options = []
    if free_text:
        llm = request.app.state.interview.llm
        try:
            options = suggest_options(usage_details_question(), free_text, llm)
        except Exception:
            options = []
    return templates.TemplateResponse("_suggest_fragment.html.j2", {
        "request": request, "options": options, "field_name": "result_use_checked",
    })
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/web/test_routes_usage.py -v`
Expected: PASS (3 tests). Then run the whole `tests/web/` directory to confirm the context fixes above didn't break Tasks 4-5's tests: `pytest tests/web/ -v`.

- [ ] **Step 5: Commit**

```bash
git add policybot/web/routes.py policybot/web/templates/wizard_usage.html.j2 policybot/web/templates/wizard_mode_fragment.html.j2 tests/web/test_routes_usage.py
git commit -m "feat(web): step 3 (usage) with AI-guessed mode and result_use suggestions"
```

---

## Task 7: Final submit — call `Interview.assess`, render result or error

**Files:**
- Modify: `policybot/web/routes.py` (add `POST /wizard/usage` final-submit handler)
- Create: `policybot/web/templates/resultat.html.j2`
- Create: `policybot/web/templates/error.html.j2`
- Test: `tests/web/test_routes_resultat.py`

**Interfaces:**
- Consumes: `Interview.assess` (`policybot/interview/orchestrator.py`), `render_html` (`policybot/report/renderer.py`), `compose_description` (Task 1), `RequestInfo` (`policybot/models.py`).
- Produces: `POST /wizard/usage` (final submit — distinct from the Task 6 `/wizard/mode-guess` and `/wizard/suggest/usage` fragment routes).

- [ ] **Step 1: Write the failing tests**

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
    resp = client.post("/wizard/usage", data=[
        ("tool_name", "ChatGPT"),
        ("data_checked", "Info déjà publique"),
        ("usage_description", "Chercher de l'info publique"),
        ("mode", "prompt"),
    ])
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
    resp = client.post("/wizard/usage", data=[
        ("tool_name", "ChatGPT"),
        ("data_checked", "Données stratégiques / confidentielles"),
        ("usage_description", "Analyser des chiffres financiers internes"),
        ("mode", "prompt"),
    ])
    assert resp.status_code == 200
    assert "Refuser" in resp.text


def test_final_submit_renders_error_screen_when_assess_fails(tmp_path):
    client = _client(tmp_path, json_responses=[])  # empty queue -> classify_data raises IndexError
    resp = client.post("/wizard/usage", data=[
        ("tool_name", "ChatGPT"),
        ("data_checked", "Info déjà publique"),
        ("usage_description", "Chercher de l'info publique"),
        ("mode", "prompt"),
    ])
    assert resp.status_code == 502
    assert "bloqué" in resp.text.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_routes_resultat.py -v`
Expected: FAIL with 404 — no `POST /wizard/usage` route exists yet (only `POST /wizard/donnees`, `POST /wizard/mode-guess`, and `POST /wizard/suggest/usage` exist so far).

- [ ] **Step 3a: Write `resultat.html.j2`**

```jinja2
{# policybot/web/templates/resultat.html.j2 #}
{% extends "_layout.html.j2" %}
{% block content %}
<div class="kicker">Résultat</div>
<div class="assist"><img src="/static/friendly.png" alt=""> Voici ce que je recommande — l'agent SI aura le dernier mot.</div>
<div class="report">
{{ report_html | safe }}
</div>
{% endblock %}
```

- [ ] **Step 3b: Write `error.html.j2`**

```jinja2
{# policybot/web/templates/error.html.j2 #}
{% extends "_layout.html.j2" %}
{% block content %}
<div class="kicker">Oups</div>
<h1>Quelque chose a bloqué pendant l'analyse</h1>
<div class="assist"><img src="/static/thinking.png" alt=""> Probablement une connexion au service d'IA. Rien n'est perdu — reviens en arrière et réessaie.</div>
<div class="foot">
  <button class="back" type="button" onclick="history.back()">← Retour</button>
  <span></span>
</div>
{% endblock %}
```

- [ ] **Step 3c: Add the final-submit handler**

`POST /wizard/usage` has no handler yet — Task 5 only added `POST /wizard/donnees` (which renders the `wizard_usage.html.j2` *shell*) and Task 6 only added the two fragment routes `POST /wizard/mode-guess` and `POST /wizard/suggest/usage`. This is a pure addition to `policybot/web/routes.py`, not a replacement of anything.

Add these imports at the top of `policybot/web/routes.py`:

```python
import uuid
from datetime import date
from policybot.models import RequestInfo
from policybot.interview.orchestrator import Interview
from policybot.report.renderer import render_html
```

Append this route at the end of `policybot/web/routes.py`:

```python
@router.post("/wizard/usage", response_class=HTMLResponse)
async def wizard_usage_submit(request: Request):
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
    }
    itv: Interview = request.app.state.interview
    numero = f"IAG-{date.today():%Y}-{uuid.uuid4().hex[:6]}"
    try:
        result_state = itv.assess(
            request=RequestInfo(numero=numero),
            tool_name=state.tool_name,
            usage_inputs=[usage_input],
            iag_type_override=state.tool_type_override,
        )
    except Exception:
        return templates.TemplateResponse("error.html.j2", {
            "request": request, "active_step": "usage",
        }, status_code=502)
    report_html = render_html(result_state)
    return templates.TemplateResponse("resultat.html.j2", {
        "request": request, "active_step": "resultat", "report_html": report_html,
    })
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/web/test_routes_resultat.py -v`
Expected: PASS (3 tests). Then run the entire suite: `pytest -v` — expect all pre-existing 64 tests plus every new test added across Tasks 1-7 to pass.

- [ ] **Step 5: Commit**

```bash
git add policybot/web/routes.py policybot/web/templates/resultat.html.j2 policybot/web/templates/error.html.j2 tests/web/test_routes_resultat.py
git commit -m "feat(web): final submit calls Interview.assess and renders result or error screen"
```

---

## Manual verification (after Task 7)

Not automatable by pytest — run once by hand to confirm the browser experience matches the design:

```bash
pip install -e ".[dev]"
uvicorn policybot.api.app:app --reload
```

Open `http://127.0.0.1:8000/`, and walk through: pick "ChatGPT" → type a data description that isn't one of the 4 checkboxes and confirm suggested checkboxes appear → type a usage description mentioning "API" or "intégration" and confirm the mode radio switches to "api" → submit and confirm the report renders with the mascotte and disclaimer visible on every screen.

(Requires `OPENROUTER_API_KEY` unset to use `FakeLLMProvider` via `default_interview()` — without a key, `guess_tool_type`/`guess_mode`/`suggest_options` will raise `IndexError` on the fake provider's empty queue and degrade to the non-fatal fallback paths, per Global Constraints. Set `OPENROUTER_API_KEY` for a real end-to-end AI-assist check.)
