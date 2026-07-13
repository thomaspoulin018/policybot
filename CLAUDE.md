# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

PolicyBot is a self-service web tool for **UQAM** that tells an employee whether a
planned use of a generative-AI tool is safe, and produces a sourced report a
security/privacy officer can review and authorize. It automates the first two
steps of the MCN mandatory guide for generative AI (IAG) under the LGGRI:
1. **Fiche de qualification** — who, what tool, what data, what usage.
2. **Grille d'évaluation des risques** — matrix gate + risk scoring per usage.
3. *(out of scope)* Authorization by the Direction SI officer.

**PolicyBot recommends; it never authorizes.** That distinction shapes every
design decision below — don't blur it.

Full background, glossary (MCN, LGGRI, IAG, ARP, ÉFVP-R, F/M/E/C), and source
docs live in `docs/superpowers/specs/2026-07-02-policybot-design.md`. The
step-by-step TDD build plan is `docs/superpowers/plans/2026-07-02-policybot.md`.
Later increments (web UI, grille rules) have their own spec/plan pairs in the
same directories, dated by feature. Treat these specs/plans as the source of
truth for *intent* — the README and this file summarize what's actually built.

## Commands

```bash
pip install -e ".[dev]"     # install (add "[pdf]" too for WeasyPrint PDF export)
pytest -v                   # run the whole suite (offline, deterministic)
pytest tests/grille -v      # run one package's tests
pytest tests/grille/test_matrix.py::test_protege_c_gouvernementale_obligatoire -v  # single test
uvicorn policybot.api.app:app --reload   # run the web app locally
```

There is no separate lint/typecheck command configured — `pytest` is the only
gate. `tests/conftest.py` force-disables LangSmith tracing env vars before any
test module imports, so `policybot.api.app` (which loads `.env`) never
accidentally traces during a test run.

## Core architectural invariant

| | Decides the verdict? | Role |
|---|---|---|
| **Deterministic Python** (matrix + `grille.yaml` rules) | Yes | The only source of a verdict. Pure functions, exhaustively unit-tested. |
| **LLM** (via swappable `LLMProvider`) | Never | Phrases questions, proposes answer options, extracts facts from tool terms, drafts narrative prose. |

Two guardrails make this concrete, and any change touching the grille/matrix
must preserve them:
- **The MCN permission matrix is an absolute hard gate.** Nothing — no LLM
  output, no rule, no score — can override an `INTERDIT`.
- **F/M/E/C risk ratings are pre-filled proposals, not computed verdicts.**
  Every `RiskFactor` carries `origin: "rule" | "llm_proposed"` and `proposed:
  bool`; the officer sets the final rating. The matrix result itself is the
  one exception (it's policy, not a proposal).

Other baked-in principles: **conservative-by-default** data classification
(when unsure between two levels, pick the more restrictive one and flag it);
**nothing derived is silently trusted** (low-confidence or "Autre" free-text
answers set `needs_officer_confirmation`); **the whole decision is auditable**
(every question, offered options, and selection is logged; the report is a
pure rendering of `InterviewState` — nothing is invented at render time).

## Pipeline (`Interview.assess`, `policybot/interview/orchestrator.py`)

```
Web UI (renders QuestionSpec)
        │
Interview Orchestrator  ── holds InterviewState, drives the pipeline below
        │
  ┌─────┼───────────┬──────────────┬───────────┬────────────┐
  LLM   Classifiers  Pre-approved   Contract     Grille        → Report (PDF/DOCX)
  layer (data, tool  DB (SQLite)    analyzer     engine
  (swap) type)       ArpRecord +    (fetch terms (matrix gate
                     PreApproved    → extract    + grille.yaml
                                    ContractFacts rules)
                                    → Partie A)
```

**Invariant: only the Grille engine decides.** Every other component gathers
or presents facts. For one tool + one or more usages:

1. **Identify the tool** via `policybot/classify/tool_registry.py` to get
   vendor + IAG type (`publique` / `circuit_ferme` / `souveraine` /
   `gouvernementale`). Unknown tools fall back to asking the user
   (`tool_type_question()`), which the API surfaces as a 422
   `UnknownToolError` and the web wizard surfaces as an extra step.
2. **Resolve the tool's contract facts (Partie A / ARP), once per tool.**
   Check the SQLite `PreApprovedStore` for a cached `ArpRecord` first. Otherwise
   fetch terms of use — via `TermsFetcher` (registry URL → HTML → text) or, if
   `POLICYBOT_CONTRACT_SEARCH=tavily` is set (or a `tavily_search` callable is
   injected), via `policybot/contract/tavily.py` (Tavily Search + Extract,
   config auto-generated per tool under `configs/tavily_contracts/`) — then
   have the LLM extract normalized `ContractFacts` (trains on input? retention?
   residency? sub-processors? human review? …), and cache the result.
3. **For each usage, classify the data.** The employee describes data in plain
   language (never the data itself); the LLM returns structured signals; a
   deterministic decision tree maps those to Non classifié / Protégé A/B/C
   (+ `rens_personnels`), conservatively, with a confidence score.
4. **Run the MCN permission matrix (hard gate).** `data_classification ×
   iag_type → PERMIS | INTERDIT | OBLIGATOIRE`, a plain 4×4 dict lookup in
   `policybot/grille/matrix.py` (all 16 cells parametrized in
   `tests/grille/test_matrix.py`). An `INTERDIT` immediately sets the usage's
   verdict to `Refuser` — nothing downstream can change it.
5. **Otherwise, evaluate `policybot/grille/grille.yaml` rules** (data, not
   code) over the ARP + usage facts via `rules.py`, take the highest-severity
   match, collect every triggered rule for transparency (Partie B), and set
   `efvpr_required` if personal information is involved.
6. **Synthesize across usages (Partie C).** Global risk = worst residual level
   across usages (no averaging); recommendation follows the same rule (any
   `Refuser` wins; else Élevé/Critique → `Escalader` or
   `Autoriser_avec_conditions`; else `Autoriser`).
7. **Render the report** — an HTML template mirroring the two official forms,
   with the "recommendation, not authorization" disclaimer on every page.
   With the `pdf` extra installed, `write_pdf`/`render_pdf` (ReportLab, lazily
   imported) writes a styled PDF to `output/pdf/`, and `write_docx`/
   `render_docx` fills the official Word qualification fiche template and
   saves it to `output/docx/`. (`renderer.py` also has a WeasyPrint-based
   `html_to_pdf`, but it's not wired into the API/web routes — those call
   `write_pdf`/`write_docx`.)

`policybot/interview/graph.py` wraps this same orchestrator in a LangGraph
state machine (`run_graph`) — that's what the FastAPI `/assess` endpoint calls,
not `Interview.assess` directly. The web wizard (`policybot/web/routes.py`)
calls `Interview.assess` directly per step instead of going through the graph.

## Package layout

```
policybot/
  models.py       Pydantic v2 domain models: QuestionSpec, ContractFacts,
                  RiskFactor, ArpRecord, PreApprovedRecord, Usage, InterviewState
  criteria.py     Fixed (category, criterion, description) tables — ARP_CRITERIA
                  and USAGE_CRITERIA — mirroring the reference Grille docx in
                  document order; the report renderer relies on this order.
  tracing.py      Internal step-by-step traceability, see below — separate
                  from LangSmith LLM tracing.
  llm/            LLMProvider ABC (complete_json / draft_text) +
                  FakeLLMProvider (tests, queued canned responses) +
                  OpenRouterProvider (langchain ChatOpenAI → OpenRouter, POC)
  classify/       data_classifier.py (LLM signals → decision tree),
                  tool_type.py + tool_registry.py (known-tool lookup)
  contract/       fetcher.py (terms URL → text via TermsFetcher), arp.py (LLM
                  extraction → ContractFacts + Partie A RiskFactors),
                  tavily.py (Tavily Search + Extract alternative source, one
                  auto-generated query config per tool under
                  `configs/tavily_contracts/`), tavily_probe.py (manual CLI:
                  `python -m policybot.contract.tavily_probe "<tool>"`)
  grille/         matrix.py (hard gate), rules.py + grille.yaml (rule engine,
                  data not code, ~15 rules), engine.py (per-usage verdict +
                  synthesis)
  preapproved/    store.py — SQLite cache of ArpRecord/PreApprovedRecord, each
                  with an expiry so stale approvals force re-review;
                  known_tools.py + known_tools.yaml — separate list of known
                  tool names (distinct from the store's cache and from
                  classify/tool_registry.py's vendor/IAG-type metadata)
  interview/      questions.py (QuestionSpec builders), orchestrator.py
                  (Interview.assess — the pipeline above), graph.py (LangGraph
                  wrapper used by the API)
  api/            app.py (FastAPI: POST /assess, POST /report, mounts the web
                  router + static files), deps.py (wires OpenRouter vs Fake
                  provider based on OPENROUTER_API_KEY)
  web/            routes.py — multi-step wizard driven by Interview.assess per
                  step: outil → outil/type (only if the tool is unrecognized)
                  → profil-utilisateurs → donnees (+ suggest/donnees) →
                  mode-guess → usage (+ suggest/usage) → contexte-affaires →
                  resultats, plus download routes output/pdf/{filename} and
                  output/docx/{filename}; wizard_state.py (WizardState —
                  carries answers across steps via hidden form fields, no
                  server session); ai_assist.py (LLM-backed suggestion
                  endpoints: guess tool type/mode, suggest checkbox options
                  from free text), templates/, static/
  report/         templates/report.html.j2 + renderer.py (render_html;
                  write_pdf/render_pdf via ReportLab for output/pdf/;
                  write_docx/render_docx fills the official Word fiche
                  template for output/docx/; uses criteria.py for row order)
tests/            mirrors the package layout 1:1; fixtures under tests/*/fixtures
docs/superpowers/ design specs + implementation plans (source of truth for intent)
```

## Testing strategy

- **Grille engine — pure unit tests, priority.** All 16 matrix cells and every
  `grille.yaml` rule are tested; deterministic, no I/O.
- **LLM-touching components** (classifiers, ARP extraction, orchestrator, web
  `ai_assist`) are tested against `FakeLLMProvider`, which returns queued
  canned JSON/text and records every call — fully offline and deterministic.
  When adding a test that hits an LLM-backed path, queue a fake response
  rather than mocking at a lower level.
- **TermsFetcher** is tested against saved HTML fixtures in
  `tests/contract/fixtures/`, never the live web.
- **`tests/test_golden_scenarios.py`** is the canonical end-to-end acceptance
  test (the real UQAM slide-5 example: ChatGPT/Perplexity + Protégé B
  strategic/financial data ⇒ `INTERDIT` / `Refuser`). Extend this file when a
  new real-world scenario needs a full-pipeline regression test.
- The web wizard tests (`tests/web/test_routes_*.py`) exercise each step of the
  form flow against a FastAPI `TestClient`, one file per wizard step.

## LLM provider and tracing

- `default_interview()` (`policybot/api/deps.py`) picks `OpenRouterProvider` if
  `OPENROUTER_API_KEY` is set, else falls back to `FakeLLMProvider` — so the
  app runs (with fake answers) even with no key configured.
- `OpenRouterProvider` (`policybot/llm/openrouter.py`) is built on
  `langchain_openai.ChatOpenAI` pointed at OpenRouter's OpenAI-compatible
  endpoint; default model is `google/gemma-4-31b-it` (confirm the exact slug
  on OpenRouter before relying on it — it's flagged as a POC choice in the
  source).
- Every LLM-assisted step (data classification, ARP extraction) is traced in
  LangSmith when tracing is enabled, tagged by call site
  (`data_classification`, `arp_extraction`) for distinguishing traces in the
  dashboard. Tracing is opt-in via `.env` (`LANGCHAIN_TRACING_V2=true` +
  `LANGCHAIN_API_KEY` + `LANGCHAIN_PROJECT`); it is force-disabled under
  pytest regardless of `.env` contents (see `tests/conftest.py`). Never commit
  `.env` — it's gitignored; use `.env.example` as the template.

## Internal traceability (`logs/policybot.jsonl`)

Separate from LangSmith (which only covers LLM calls): every step of
`Interview.assess` (classification, ARP resolution, LLM calls, grille
evaluation, synthesis) writes a JSON line via `policybot/tracing.py`. All
sub-steps of one request share an `interview_id`, so a full case can be
reconstructed by filtering on it.

**Non-negotiable constraint: never log free text in the clear.** Usage
descriptions, contract content, and LLM prompts/responses are never written
verbatim — only their length and a truncated SHA-256 hash (`mask_text()`)
appear, to avoid leaking personal information into an unprotected file. Any
change to `tracing.py` or its call sites must preserve this. The log path is
configurable via `POLICYBOT_LOG_PATH` (`tests/conftest.py` redirects it so the
test suite never writes into the repo's `logs/`); the file rotates
automatically (5 MB × 5 backups).

## Known gaps / in-flight work

- `grille.yaml` now has ~15 rules (past the original 3 starter rules from
  `docs/superpowers/plans/2026-07-07-grille-rules.md`), refined further in
  `docs/superpowers/plans/2026-07-09-grille-report-alignment.md` — check
  those specs/plans before assuming the rule set is either final or complete.
- **Packaging debt:** `grille.yaml` and report/web templates are not yet
  declared as package data in `pyproject.toml` — they work in an editable
  install (`pip install -e`) but would be missing from a built wheel.
- `README.md`'s "16 tasks / 64 tests" status table is stale (the suite has
  grown well past that — 192 tests collected as of this writing); treat the
  README's process narrative as historical, not a live dashboard.
- Deferred beyond MVP (last confirmed against the design spec): an officer
  review/back-office dashboard, scheduled re-fetching of stale ARPs, UQAM
  visual-identity PDF theming.
