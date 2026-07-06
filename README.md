# PolicyBot

PolicyBot is a self-service web tool for **UQAM** that tells an employee whether a
planned use of a generative-AI tool is safe, and produces a sourced report a
security/privacy officer can review and authorize. It automates the first two
steps of the **MCN** mandatory guide for generative AI (IAG), under the **LGGRI**:

1. **Fiche de qualification** — who, what tool, what data, what usage.
2. **Grille d'évaluation des risques** — matrix gate + risk scoring per usage.
3. *(out of scope for PolicyBot)* Authorization by the **Direction SI** officer.

> **PolicyBot recommends; it never authorizes.** Every screen and every page of
> the generated report says so explicitly.

Full background, source docs (`SI_-_*.docx/pptx`), and glossary (MCN, LGGRI, IAG,
ARP, ÉFVP-R, F/M/E/C) live in the design spec —
[`docs/superpowers/specs/2026-07-02-policybot-design.md`](docs/superpowers/specs/2026-07-02-policybot-design.md).
The step-by-step TDD build order is in the implementation plan —
[`docs/superpowers/plans/2026-07-02-policybot.md`](docs/superpowers/plans/2026-07-02-policybot.md).
This README summarizes both against what's actually implemented.

## Core idea: rules decide, the LLM only assists

| | Decides the verdict? | Role |
|---|---|---|
| **Deterministic Python** (matrix + `grille.yaml` rules) | ✅ Yes | The only source of a verdict. Pure functions, exhaustively unit-tested. |
| **LLM** (via a swappable `LLMProvider`) | ❌ Never | Phrases questions, proposes answer options, extracts facts from tool terms, drafts narrative prose. |

Two guardrails make this concrete:

- **The MCN permission matrix is an absolute hard gate.** Nothing — no LLM
  output, no rule, no score — can override an `INTERDIT`.
- **F/M/E/C risk ratings are pre-filled proposals, not computed verdicts.**
  Every `RiskFactor` carries `origin: "rule" | "llm_proposed"` and
  `proposed: bool`; the officer sets the final rating. The one exception is the
  matrix result itself, which is policy, not a proposal.

Other principles baked into the design: **conservative-by-default**
classification (when unsure between two data levels, pick the more restrictive
one and flag it), **nothing derived is silently trusted** (low-confidence or
"Autre" free-text answers set `needs_officer_confirmation`), and **the whole
decision is auditable** (every question, offered options, and selection is
logged, and the report is a pure rendering of that state — nothing is invented).

## The process, end to end

```
Web UI (renders QuestionSpec)
        │
Interview Orchestrator  ── holds InterviewState, drives the pipeline below
        │
  ┌─────┼───────────┬──────────────┬───────────┬────────────┐
  LLM   Classifiers  Pre-approved   Contract     Grille        → Report (PDF)
  layer (data, tool  DB (SQLite)    analyzer     engine
  (swap) type)       ArpRecord +    (fetch terms (matrix gate
                     PreApproved    → extract    + grille.yaml
                                    ContractFacts rules)
                                    → Partie A)
```

**Invariant: only the Grille engine decides.** Every other component gathers or
presents facts.

For one tool + one or more usages, the pipeline (`Interview.assess`) runs:

1. **Identify the tool.** Look it up in the tool registry (`policybot/classify/tool_registry.py`)
   to get its vendor and **IAG type** (`publique` / `circuit_ferme` / `souveraine` /
   `gouvernementale`). Unknown tools fall back to asking the user
   (`tool_type_question()`).
2. **Resolve the tool's contract facts (Partie A / ARP), once per tool.**
   - Check the SQLite `PreApprovedStore` for a cached `ArpRecord` first (reuse).
   - Otherwise fetch the tool's terms of use (`TermsFetcher`: registry URL →
     HTML → stripped text), have the LLM extract normalized `ContractFacts`
     (training on input? retention? data residency? sub-processors? human
     review?), and cache the resulting `ArpRecord`.
3. **For each usage, classify the data.** The employee describes the data in
   plain language (never the data itself); the LLM returns structured signals
   (`already_public`, `contains_personal_info`, `strategic_sensitive`, …); a
   deterministic decision tree maps those signals to **Non classifié / Protégé
   A / Protégé B / Protégé C** (+ `rens_personnels`), conservatively, with a
   confidence score.
4. **Run the MCN permission matrix (the hard gate).** `data_classification ×
   iag_type → PERMIS | INTERDIT | OBLIGATOIRE`. An `INTERDIT` immediately sets
   the usage's verdict to `Refuser` — no scoring, no LLM opinion can change it.
5. **Otherwise, evaluate `grille.yaml` rules of thumb** over the ARP + usage
   facts, take the highest-severity match, and collect every triggered rule
   for transparency (Partie B). Set `efvpr_required` if the usage involves
   personal information.
6. **Synthesize across usages (Partie C).** Global risk = the worst residual
   level across all usages (no averaging); recommendation follows the same
   rule (any `Refuser` wins; otherwise Élevé/Critique → `Escalader` or
   `Autoriser_avec_conditions`; otherwise `Autoriser`).
7. **Render the report.** An HTML template mirrors the two official forms
   (Fiche de qualification, then Grille Partie A/B/C), with the
   "recommendation, not authorization" disclaimer on every page. An optional
   WeasyPrint wrapper turns that HTML into a PDF.

### The MCN permission matrix (hard gate)

| Data ↓ / Tool → | Publique | Circuit fermé | Souveraine | Gouv (UQAM) |
|---|---|---|---|---|
| Non classifié | PERMIS | PERMIS | PERMIS | PERMIS |
| Protégé A | INTERDIT | PERMIS | PERMIS | PERMIS |
| Protégé B | INTERDIT | PERMIS | PERMIS | PERMIS |
| Protégé C | INTERDIT | INTERDIT | INTERDIT | OBLIGATOIRE |

Implemented as a plain 4×4 dict lookup in `policybot/grille/matrix.py`; all 16
cells are exhaustively parametrized in `tests/grille/test_matrix.py`.

## Project layout

```
policybot/
  models.py       Pydantic v2 domain models: QuestionSpec, ContractFacts,
                  RiskFactor, ArpRecord, PreApprovedRecord, Usage, InterviewState
  llm/            LLMProvider interface (complete_json / draft_text) +
                  FakeLLMProvider (tests) + OpenRouterProvider (Gemma, POC)
  classify/       data_classifier.py (LLM signals → decision tree),
                  tool_type.py + tool_registry.py (known-tool lookup)
  contract/       fetcher.py (terms URL → text), arp.py (LLM extraction →
                  ContractFacts + Partie A RiskFactors)
  grille/         matrix.py (hard gate), rules.py + grille.yaml (rule engine,
                  data not code), engine.py (per-usage verdict + synthesis)
  preapproved/    store.py — SQLite cache of ArpRecord and PreApprovedRecord,
                  each with an expiry so stale approvals force re-review
  interview/      questions.py (QuestionSpec builders), orchestrator.py
                  (Interview.assess — the pipeline above)
  report/         templates/report.html.j2 + renderer.py (render_html,
                  optional html_to_pdf via WeasyPrint)
tests/            mirrors the package layout; fixtures under tests/*/fixtures
docs/superpowers/ design spec + implementation plan (source of truth for intent)
```

## Getting started

```bash
pip install -e ".[dev]"
pytest -v
```

There's no CLI or running API yet (see Status below), but the full pipeline
works end to end against a fake LLM:

```python
from policybot.models import RequestInfo
from policybot.llm.fake import FakeLLMProvider
from policybot.preapproved.store import PreApprovedStore
from policybot.interview.orchestrator import Interview

llm = FakeLLMProvider(json_responses=[
    {"already_public": True, "contains_personal_info": False,
     "strategic_sensitive": False, "internal_nonpublic": False,
     "highly_sensitive_secret": False, "confidence": 0.9},
    {"trains_on_input": "no", "data_residency": "canada", "extraction_confidence": 0.9},
])
itv = Interview(llm=llm, store=PreApprovedStore("policybot.db"),
                http_get=lambda url: "<html><body>ok</body></html>")
state = itv.assess(
    request=RequestInfo(numero="IAG-2026-001"),
    tool_name="ChatGPT",
    usage_inputs=[{"description": "Chercher de l'info publique",
                   "data_description": "information publique sur le web",
                   "automated_decisions": False, "mode": ["prompt"], "result_use": []}],
)
print(state.result_global.recommendation)  # "Autoriser"
```

A real run swaps in `OpenRouterProvider` (see `policybot/llm/openrouter.py`);
no unit test ever calls the network — the OpenRouter path is exercised only
behind an integration-test flag.

## Traceability (LangSmith)

Every LLM-assisted step (data classification, ARP fact extraction, and any
future drafting) is traced in [LangSmith](https://smith.langchain.com) for
debugging. `OpenRouterProvider` is built on `langchain_openai.ChatOpenAI`
pointed at OpenRouter's OpenAI-compatible endpoint, so tracing comes for free
and stays consistent with the LangGraph interview graph, whose nodes trace
through the same environment variables. Each call site is tagged
(`data_classification`, `arp_extraction`) so traces are distinguishable at a
glance in the UI.

Tracing is **off unless you opt in**, so tests and CI never emit traces. To
enable it, set the variables *before launching the process* (they are read once
at startup — copy `.env.example` to `.env` or export them in your shell):

```powershell
# PowerShell (Windows)
$env:LANGCHAIN_TRACING_V2 = "true"
$env:LANGCHAIN_API_KEY     = "<your LangSmith key from Settings → API Keys>"
$env:LANGCHAIN_PROJECT     = "policybot"
```

```bash
# bash
export LANGCHAIN_TRACING_V2=true
export LANGCHAIN_API_KEY=<your LangSmith key>
export LANGCHAIN_PROJECT=policybot
```

Leave `LANGCHAIN_TRACING_V2` unset (or `false`) — the default — to disable
tracing. Never set it in the environment `pytest` runs in. The modern aliases
`LANGSMITH_TRACING` / `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT` work too. Keep
both `OPENROUTER_API_KEY` and the LangSmith key in `.env` only (gitignored),
never committed. Prompts sent to the LLM are already descriptions/metadata, not
the sensitive data itself, so traces contain nothing more sensitive than what
already goes to OpenRouter.

## Testing strategy

- **Grille engine — pure unit tests, priority.** All 16 matrix cells and every
  `grille.yaml` rule are tested; deterministic, no I/O.
- **LLM-touching components** (classifiers, ARP extraction, orchestrator) are
  tested against `FakeLLMProvider`, which returns queued canned JSON/text and
  records every call — fully offline and deterministic.
- **TermsFetcher** is tested against saved HTML fixtures, never the live web.
- **Golden scenario** (planned, Task 16): the real UQAM slide-5 example —
  ChatGPT/Perplexity + Protégé B strategic/financial data ⇒ `INTERDIT` /
  `Refuser` — as the canonical end-to-end acceptance test.

Run everything with `pytest -v`.

## Status against the plan

The plan (`docs/superpowers/plans/2026-07-02-policybot.md`) defines 16
TDD tasks. As of this branch:

| Done | Task |
|---|---|
| ✅ | 1–6: scaffolding, domain models, matrix, rule engine, per-usage grille engine, LLM provider (+fake +OpenRouter) |
| ✅ | 7–9: data classifier, tool-type classifier + registry, terms fetcher |
| ✅ | 10–12: ARP extractor, SQLite pre-approved store, HTML report renderer (+ optional PDF) |
| ✅ | 13: interview orchestrator (`Interview.assess`) — full deterministic pipeline, linear (no graph yet) |
| ⬜ | 14: wrap the orchestrator in a LangGraph state machine (adds resumability) |
| ⬜ | 15: FastAPI app exposing `POST /assess` and `POST /report` |
| ⬜ | 16: golden end-to-end acceptance test (UQAM slide-5 scenario) |

**Deferred beyond MVP** (per spec §14): an officer review/back-office
dashboard, scheduled re-fetching of stale ARPs, and UQAM visual-identity PDF
theming.

**Still open before a real run:** confirm the exact OpenRouter Gemma model
slug (a placeholder is set in `OpenRouterProvider`), and seed `grille.yaml`
with the officers' actual rules of thumb beyond the three starter rules.
