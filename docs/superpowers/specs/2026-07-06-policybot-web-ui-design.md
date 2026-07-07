# PolicyBot — Web UI Design Spec (Interview Wizard, MVP)

**Date:** 2026-07-06
**Status:** Approved (design), pending implementation plan
**Context:** First real web UI for PolicyBot. Builds on
[`2026-07-02-policybot-design.md`](2026-07-02-policybot-design.md), which specifies
the full backend pipeline (already implemented, 64 passing tests). This spec covers
only the interview UI — a self-service wizard an employee fills in directly in the
browser, for **one tool + one usage** end to end.

---

## 1. Purpose

The backend pipeline (`Interview.assess`, `policybot/api/app.py`) is complete but
has no web interface — an employee cannot yet use PolicyBot without writing Python.
This spec designs the missing piece: a browser-based wizard that collects the same
inputs `Interview.assess` already accepts (tool name, data description, usage
details) and renders the existing report at the end.

**Explicitly out of scope for this pass:** multiple usages per tool in one session,
an accueil/landing screen, a back-office/officer view, session persistence across
browser restarts. These are natural follow-ups once this first slice works
end-to-end.

## 2. Users & tone

Same primary user as the main design spec — a non-expert UQAM employee, easily
intimidated by security/privacy topics. The UI should feel closer to a friendly
product wizard than a government form: the mascotte (`friendly.png` / `Thinking.png`)
appears throughout as a guide that talks, sentences are short and reassuring, and
every screen restates "PolicyBot recommande, il n'autorise jamais."

Visual direction: the **"Moderne/SaaS"** mockup validated in
`ui-mockups-entrevue.html` (step rail on the left, card-grid checkboxes, mascotte as
a speaking accent) — chosen over the "amicale" and "institutionnelle" alternatives
also explored.

## 3. Relationship to the original QuestionSpec vision

§5 of the main design spec describes the LLM *always* composing tailored option
menus for every question. The two `QuestionSpec` builders that exist today
(`data_description_question`, `usage_details_question` in
`policybot/interview/questions.py`) are static stand-ins for that vision, and are
not yet wired into the orchestrator — `classify_data()` takes free text directly
(`policybot/classify/data_classifier.py`).

This spec keeps that free-text backend contract **unchanged** and reconciles it
with the original vision through a hybrid, pragmatic middle ground: start from a
small set of static, pre-written options (fast, testable, no LLM latency on the
common path), and call the LLM only to *augment* that list when the user's own
words don't fit — rather than generating the full menu from scratch every time.
This is cheaper, faster on the happy path, and easier to test than full dynamic
generation, while still delivering on "the AI helps when the user hesitates."

## 4. The generic "aide-moi" mechanism

Applies to every `QuestionSpec`-driven step (Données, Usage's `result_use`):

1. Render the spec's fixed `options` as checkboxes (respecting `multi_select`).
2. Always render a free-text "Autre" field (`allow_other` is already `True` on both
   existing specs).
3. When the user types in "Autre", an HTMX request (`POST /wizard/suggest`) sends
   the question's `id`, the labels already shown, and the free text to a new,
   generic helper:

   ```python
   def suggest_options(question: QuestionSpec, free_text: str, llm: LLMProvider) -> list[QuestionOption]:
       """LLM proposes 2-4 additional options tailored to free_text,
       avoiding duplicates with question.options. Domain-agnostic —
       only sees the QuestionSpec + the user's words."""
   ```

4. The response HTML-swaps in the new checkboxes (unchecked by default) below the
   existing ones. The user can check any mix of fixed + suggested options and/or
   leave text in "Autre".
5. On step submit, everything checked + any remaining free text is collected
   together (see §6.2 for how Données turns this into the single string
   `classify_data()` expects).

Because `suggest_options()` only knows about `QuestionSpec`, one implementation
serves every step — no per-domain duplication.

## 5. Step 1 — Outil

- **Quick-pick chips** for the 5 tools already in `policybot/classify/tool_registry.py`
  (ChatGPT, ChatGPT Pro, Claude.ai, Perplexity, Microsoft Copilot Entreprise) —
  single choice, since one tool is being assessed at a time.
- **Free-text field** for anything not listed.
- **Unknown tool → guided fallback, now with an AI-generated first guess:**
  1. New helper `guess_tool_type(name: str, llm: LLMProvider) -> IagType | None`
     (mirrors the shape of `classify_data`: LLM proposes, nothing decides) infers a
     likely IAG type from the tool name alone (e.g. "Notion AI" → `publique`).
  2. The existing `tool_type_question()` (`policybot/classify/tool_type.py`) renders
     as usual, but with the guessed option **pre-checked**. The user confirms or
     picks a different one.
  3. The guess is marked `needs_officer_confirmation`-style (proposal, not fact) —
     consistent with how `RiskFactor.origin: "llm_proposed"` is already handled
     elsewhere in the system.
- This reuses the existing 422 (`UnknownToolError`) response from `POST /assess`
  unchanged; the wizard just renders it as a wizard step instead of a raw JSON
  error, with the extra LLM-guess pre-fill layered on top.

## 6. Step 2 — Données

- **Checkboxes**: the four options already written in `data_description_question()`
  (Info déjà publique, Documents internes de travail, Renseignements personnels,
  Données stratégiques/confidentielles) — reused as-is, this is the first time
  they're actually rendered anywhere.
- **Free-text "Autre"** field, always visible.
- **`suggest_options()`** (§4) proposes 2-4 more precise checkboxes from whatever the
  user types (e.g. "des courriels d'étudiants" → "Renseignements personnels
  d'étudiants", "Correspondance nominative").

### 6.2 Composing the description sent to `classify_data()`

`classify_data(description: str, llm)` (`policybot/classify/data_classifier.py:33`)
is unchanged and still takes one string. The wizard route composes it:

```python
def compose_description(checked_labels: list[str], free_text: str) -> str:
    parts = list(checked_labels) + ([free_text] if free_text else [])
    return "; ".join(parts)
```

Checked labels + free text, joined into one sentence, sent as-is to the existing
classifier. No change to `classify_data`, `_decide`, or the decision tree.

## 7. Step 3 — Usage

The `Usage` model (`policybot/models.py:93`) needs four fields from this step:

| Field | UI treatment |
|---|---|
| `description` | Free text: what will you do with the tool. |
| `mode` (`"prompt"` \| `"api"`) | Not shown as a raw technical choice. New helper `guess_mode(description: str, llm: LLMProvider) -> Literal["prompt","api"]` infers it from the free-text description (e.g. mentions of "intégré à notre CRM" → `api`); pre-checked, user confirms/corrects — same proposal pattern as tool-type guessing. |
| `result_use` | Checkboxes from the existing `usage_details_question()` options (Prise de décision, Publication, Intrant dans un autre processus, Aide à la rédaction/diffusion interne) + "Autre" + `suggest_options()`, same mechanism as Données. |
| `automated_decisions` | A single plain checkbox: "Le résultat va-t-il déclencher une décision automatique sans révision humaine ?" No AI involved — it's a direct yes/no fact, not something to classify. |

## 8. Step 4 — Résultat

Unchanged rendering path. Once step 3 submits, the wizard route calls
`Interview.assess(...)` directly (in-process, no internal HTTP round-trip) and
renders `resultat.html.j2`, which wraps the existing `render_html(state)`
(`policybot/report/renderer.py`) verbatim — verdict, matrix result, disclaimer.
**No AI mechanism here.** This is the deterministic, already-tested part of the
system; the design deliberately does not touch it.

## 9. Wizard state across steps

Per the "no server-side session" decision: each step's HTML form carries the
accumulated answers forward as `<input type="hidden">` fields. A single module
owns the encode/decode logic so no template duplicates it:

```python
# policybot/web/wizard_state.py
class WizardState(BaseModel):
    tool_name: str = ""
    tool_type_override: IagType | None = None      # set only via the fallback step
    data_checked: list[str] = []
    data_free_text: str = ""
    usage_description: str = ""
    mode_override: Literal["prompt", "api"] | None = None
    result_use_checked: list[str] = []
    result_use_free_text: str = ""
    automated_decisions: bool = False

    def to_hidden_fields(self) -> dict[str, str]: ...
    @classmethod
    def from_form(cls, form: dict) -> "WizardState": ...
```

Stateless by construction: the server can restart between two requests without
losing anything, since the browser is holding the state.

## 10. Architecture / project layout

```
policybot/web/
  routes.py           # GET /  , POST /wizard/outil, /wizard/donnees,
                       # /wizard/usage, /wizard/suggest
  wizard_state.py      # WizardState (§9)
  ai_assist.py         # suggest_options(), guess_tool_type(), guess_mode()
  templates/
    _layout.html.j2    # shared shell: mascotte, CSS, step rail
    wizard_outil.html.j2
    wizard_donnees.html.j2
    wizard_usage.html.j2
    resultat.html.j2   # wraps report/templates/report.html.j2
  static/
    htmx.min.js        # vendored, no CDN
    style.css          # adapted from the .moderne block in ui-mockups-entrevue.html
    friendly.png
    thinking.png
```

`create_app()` in `policybot/api/app.py` mounts this router alongside the existing
`/assess` and `/report` JSON routes — one FastAPI process serves both.

## 11. Error handling

- **Unknown tool** → existing 422 flow, now rendered as the guided fallback step
  (§5), not a raw JSON error.
- **LLM/network failure** during `assess()` or any `ai_assist.py` call → an error
  screen with the "Thinking" mascotte and a back button. `ai_assist.py` failures are
  non-fatal: if `suggest_options`/`guess_tool_type`/`guess_mode` fail or time out,
  the step degrades to just the static options / no pre-fill — the wizard never
  blocks on the AI-assist calls.
- **Missing required fields** → Pydantic validation on the composed payload before
  calling `Interview.assess`; re-render the current step with an inline message,
  no data loss (hidden fields already preserve prior steps).

## 12. Testing

New tests under `tests/web/`, using `TestClient` (already used for the JSON API):

- One test per step transition (submit valid answers → correct next step rendered).
- `ai_assist.py` functions tested against `FakeLLMProvider`, same pattern as
  `classify_data`/`classify_tool_type` today — deterministic, offline.
- Unknown-tool fallback test: confirms the guessed IAG type is pre-checked and the
  user's override is what actually gets sent to `assess()`.
- One end-to-end test replaying the README's golden scenario (ChatGPT + Protégé B
  strategic data ⇒ INTERDIT/Refuser) through the real HTML routes rather than
  calling `Interview.assess` directly — proves the wizard wiring, not just the
  pipeline.

## 13. Deferred (explicitly out of scope here)

- Multiple usages per tool in a single session (`usage_inputs` already accepts a
  list; the wizard only builds a one-item list for now).
- Landing/accueil screen and any screen beyond the 3 wizard steps + résultat.
- Session persistence across browser restarts / server-side session store.
- Officer back-office view (already deferred in the main design spec).
- UQAM visual-identity theming (already deferred in the main design spec).
