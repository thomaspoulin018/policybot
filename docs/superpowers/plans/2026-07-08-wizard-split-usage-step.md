# Wizard: Split "Ton usage" Step in Two — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the wizard's step 3 ("Ton usage", `wizard_usage.html.j2`) into two separate screens: "Ton usage" (tool mode + free-text description) and a new "Usage des résultats" screen (result-use checkboxes + automated-decisions checkbox), matching the design in [`docs/superpowers/specs/2026-07-08-wizard-split-usage-step-design.md`](../specs/2026-07-08-wizard-split-usage-step-design.md).

**Architecture:** `POST /wizard/usage` stops being the final "run the assessment" route — it now only reads `mode` + `usage_description` and renders a new template, `wizard_resultats.html.j2`, on a new `active_step="resultats"`. A new route, `POST /wizard/resultats`, takes over the assessment logic that used to live in `wizard_usage_submit` (compose `usage_input`, call `Interview.assess`, render `resultat.html.j2` or `error.html.j2`). The `_steps.html.j2` progress rail gains a `"resultats"` entry between `"usage"` and `"resultat"`. No changes to `WizardState`, `wizard_state.py`, `ai_assist.py`, or `questions.py` — every field already flows through hidden fields.

**Tech Stack:** FastAPI + Jinja2Templates (`policybot/web/`), pytest + `TestClient` (`tests/web/`), no new dependencies.

## Global Constraints

- Do not change `WizardState`, `usage_details_question()`, `compose_description()`, or `Interview.assess` — this is a UI-only split (spec §1).
- `POST /wizard/mode-guess` and `POST /wizard/suggest/usage` keep their exact current behavior and URLs — they only read the posted form, not which screen it came from (spec §4).
- The final report step keeps `active_step="resultat"` (singular) — the new intermediate step must use the distinct key `"resultats"` (plural) so the two are never confused in `_steps.html.j2` (spec §3).

---

### Task 1: Split the route logic — `/wizard/usage` hands off to new `/wizard/resultats`

**Files:**
- Modify: `policybot/web/routes.py:144-176` (`wizard_usage_submit`)
- Test: `tests/web/test_routes_resultat.py`

**Interfaces:**
- Consumes: `WizardState.from_form(form)`, `WizardState.to_hidden_fields()`, `usage_details_question()` (all existing, unchanged signatures).
- Produces: new route `POST /wizard/resultats` → `wizard_resultats_submit(request: Request)`, which renders `resultat.html.j2` (success) or `error.html.j2` (502, on `Interview.assess` failure) — same contract the old `POST /wizard/usage` had. `POST /wizard/usage` now renders `"wizard_resultats.html.j2"` (a template Task 2 creates) with context `{"active_step": "resultats", "hidden_fields": ..., "question": usage_details_question()}`.

- [ ] **Step 1: Update `test_routes_resultat.py` to post to the new final route**

Replace every `client.post("/wizard/usage", data={...})` in this file with `client.post("/wizard/resultats", data={...})`. The four tests (`test_final_submit_renders_report_on_success`, `test_golden_scenario_chatgpt_protege_b_is_refused`, `test_final_submit_renders_error_screen_when_assess_fails`, `test_final_submit_logs_exception_when_assess_fails`) keep their existing `data=` payloads and assertions unchanged — only the URL changes.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/web/test_routes_resultat.py -v`
Expected: all 4 tests FAIL with `404 Not Found` (no route registered for `POST /wizard/resultats` yet).

- [ ] **Step 3: Split `wizard_usage_submit` into two route handlers**

In `policybot/web/routes.py`, replace the current `wizard_usage_submit` function (lines 144-176) with:

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
        logger.exception("wizard/resultats assess failed for tool_name=%r numero=%s", state.tool_name, numero)
        return templates.TemplateResponse(request, "error.html.j2", {
            "active_step": "resultats",
        }, status_code=502)
    report_html = render_html(result_state)
    return templates.TemplateResponse(request, "resultat.html.j2", {
        "active_step": "resultat", "report_html": report_html,
    })
```

Leave `wizard_donnees` (lines 85-93) untouched for now — it still passes `question=usage_details_question()` into `wizard_usage.html.j2`, and that template still reads `{{ question.question }}` until Task 2 trims it. Removing the kwarg here first would break `test_routes_donnees.py` with a Jinja2 `UndefinedError`. Task 2 removes this kwarg in the same step that trims the template.

- [ ] **Step 4: Run the resultat tests again to verify they pass**

Run: `pytest tests/web/test_routes_resultat.py -v`
Expected: all 4 tests PASS. (`test_routes_donnees.py` and `test_routes_usage.py` are expected to still pass too — `wizard_usage_submit` now renders a template that doesn't exist yet, but no test calls `POST /wizard/usage` until Task 2, so this is safe.)

- [ ] **Step 5: Commit**

```bash
git add policybot/web/routes.py tests/web/test_routes_resultat.py
git commit -m "refactor(web): split wizard_usage_submit into usage handoff + resultats assess route"
```

---

### Task 2: Split the templates and add the new stepper entry

**Files:**
- Modify: `policybot/web/templates/wizard_usage.html.j2` (trim to mode + description only)
- Create: `policybot/web/templates/wizard_resultats.html.j2`
- Modify: `policybot/web/templates/_steps.html.j2`
- Modify: `policybot/web/routes.py:85-93` (`wizard_donnees` — drop the now-unused `question` kwarg)
- Test: `tests/web/test_routes_usage.py`

**Interfaces:**
- Consumes: `hidden_fields` (list of `(name, value)` tuples from `WizardState.to_hidden_fields()`), `question` (a `QuestionSpec` with `.question` and `.options[].label`, from `usage_details_question()`) — both already produced by Task 1's routes.
- Produces: the rendered "Usage des résultats" screen at `POST /wizard/usage`'s response body, and the `_steps.html.j2` `"resultats"` step key other templates can rely on via `active_step="resultats"`.

- [ ] **Step 1: Add a failing test for the new page-A → page-B handoff**

Append to `tests/web/test_routes_usage.py`:

```python
def test_usage_submit_renders_resultats_step_with_hidden_fields(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/usage", data={
        "tool_name": "ChatGPT",
        "usage_description": "Chercher des informations publiques",
        "mode": "prompt",
    })
    assert resp.status_code == 200
    assert "Usage des résultats" in resp.text
    assert "Comment comptez-vous utiliser les résultats" in resp.text
    assert 'name="tool_name" value="ChatGPT"' in resp.text
    assert 'name="usage_description" value="Chercher des informations publiques"' in resp.text
    assert 'name="mode" value="prompt"' in resp.text
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/web/test_routes_usage.py::test_usage_submit_renders_resultats_step_with_hidden_fields -v`
Expected: FAIL — the `client.post(...)` call itself raises `jinja2.exceptions.TemplateNotFound: wizard_resultats.html.j2` (TestClient propagates unhandled server exceptions by default), since Task 1 already points `wizard_usage_submit` at this template but it doesn't exist yet.

- [ ] **Step 3: Trim `wizard_usage.html.j2` down to mode + description**

Replace the full contents of `policybot/web/templates/wizard_usage.html.j2` with:

```jinja
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
  <div class="foot">
    <button class="back" type="button" onclick="history.back()">← Retour</button>
    <button class="next" type="submit">Continuer →</button>
  </div>
</form>
{% endblock %}
```

- [ ] **Step 4: Create `wizard_resultats.html.j2`**

Create `policybot/web/templates/wizard_resultats.html.j2`:

```jinja
{# policybot/web/templates/wizard_resultats.html.j2 #}
{% extends "_layout.html.j2" %}
{% block content %}
<div class="kicker">Étape 4 · Usage des résultats</div>
<h1>{{ question.question }}</h1>
<div class="assist"><img src="/static/friendly.png" alt=""> Coche tout ce qui s'applique, ou décris en tes mots.</div>
<form method="post" action="/wizard/resultats">
  {% for name, value in hidden_fields %}
  <input type="hidden" name="{{ name }}" value="{{ value }}">
  {% endfor %}
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

- [ ] **Step 5: Drop the now-unused `question` kwarg from `wizard_donnees`**

The trimmed `wizard_usage.html.j2` (Step 3) no longer reads `question` anywhere, so in `policybot/web/routes.py`, change `wizard_donnees` (lines 85-93) from:

```python
@router.post("/wizard/donnees", response_class=HTMLResponse)
async def wizard_donnees(request: Request):
    form = _group_form(await request.form())
    state = WizardState.from_form(form)
    return templates.TemplateResponse(request, "wizard_usage.html.j2", {
        "active_step": "usage",
        "hidden_fields": state.to_hidden_fields(),
        "question": usage_details_question(),
    })
```

to:

```python
@router.post("/wizard/donnees", response_class=HTMLResponse)
async def wizard_donnees(request: Request):
    form = _group_form(await request.form())
    state = WizardState.from_form(form)
    return templates.TemplateResponse(request, "wizard_usage.html.j2", {
        "active_step": "usage",
        "hidden_fields": state.to_hidden_fields(),
    })
```

- [ ] **Step 6: Add the new step to `_steps.html.j2`**

In `policybot/web/templates/_steps.html.j2`, change:

```jinja
{% set order = ["outil", "donnees", "usage", "resultat"] %}
{% set labels = {"outil": "Ton outil", "donnees": "Tes données", "usage": "Ton usage", "resultat": "Résultat"} %}
```

to:

```jinja
{% set order = ["outil", "donnees", "usage", "resultats", "resultat"] %}
{% set labels = {"outil": "Ton outil", "donnees": "Tes données", "usage": "Ton usage", "resultats": "Usage des résultats", "resultat": "Résultat"} %}
```

- [ ] **Step 7: Run the new test to verify it passes**

Run: `pytest tests/web/test_routes_usage.py::test_usage_submit_renders_resultats_step_with_hidden_fields -v`
Expected: PASS.

- [ ] **Step 8: Run the full web test suite**

Run: `pytest tests/web/ -v`
Expected: all tests PASS, including `test_routes_donnees.py`, `test_routes_outil.py`, `test_routes_resultat.py` (Task 1), `test_routes_usage.py` (mode-guess, suggest-usage fragments, and the new handoff test), `test_wizard_state.py`, `test_ai_assist.py`.

- [ ] **Step 9: Commit**

```bash
git add policybot/web/templates/wizard_usage.html.j2 policybot/web/templates/wizard_resultats.html.j2 policybot/web/templates/_steps.html.j2 policybot/web/routes.py tests/web/test_routes_usage.py
git commit -m "feat(web): split wizard usage step into 'Ton usage' and 'Usage des résultats' screens"
```

---

### Task 3: Full regression pass

**Files:** none (verification only)

**Interfaces:** none — this task only runs the existing suite end-to-end.

- [ ] **Step 1: Run the entire test suite**

Run: `pytest -v`
Expected: all tests PASS (web wizard tests from Tasks 1-2, plus the untouched backend/classify/interview/report suites).

- [ ] **Step 2: Manually smoke-test the two-screen flow**

Start the app (`uvicorn policybot.api.app:create_app --factory --reload` or the project's existing run command) and walk through: pick a known tool → fill data description → fill "Ton usage" (mode + description) → confirm it lands on the new "Usage des résultats" screen with the stepper showing 5 steps and the right one highlighted → check result-use boxes + "Décision automatisée" → submit → confirm the final report renders. Confirm the back button on the new screen returns to "Ton usage" with the previously entered mode/description still filled in (via hidden fields → browser history, same behavior as every other step today).

- [ ] **Step 3: Commit (only if the smoke test surfaced fixes)**

If Step 2 required any code changes, stage and commit them with a message describing what the smoke test caught. If no changes were needed, skip this step — nothing to commit.
