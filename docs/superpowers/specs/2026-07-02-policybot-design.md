# PolicyBot — Design Spec

**Date:** 2026-07-02
**Status:** Approved (design), pending implementation plan
**Context:** UQAM AI-governance tool, aligned to the MCN mandatory guide for generative AI (IAG) under the LGGRI.

---

## 1. Purpose

PolicyBot is a self-service web tool that lets a UQAM employee describe how they
want to use a generative-AI tool, then produces a **PDF report** for a
security/privacy officer (Direction SI) to review and authorize. It automates the
first two steps of the MCN-mandated process — **Fiche de qualification** and
**Grille d'évaluation des risques** — and hands a pre-filled, sourced report to the
**designated authority** for the third step (authorization).

**PolicyBot recommends; it never authorizes.** Every screen and every page of the
report states this explicitly.

## 2. Users & roles

- **Primary user — the employee (self-service).** A non-expert who wants to use an
  AI tool. PolicyBot guides them in plain language, never showing jargon
  (Protégé A/B/C, IAG types) as raw choices.
- **Consumer — the security/privacy officer.** Receives the generated PDF, reviews
  the flagged items, confirms or overrides derived values, and authorizes.
- **Out of scope for MVP:** an officer back-office dashboard (deferred). The PDF is
  the hand-off artifact for now.

## 3. Core principles

- **Hybrid decision: rules decide, LLM assists.** The verdict comes from
  deterministic Python over collected facts. The LLM only phrases questions,
  proposes answer options, extracts facts from tool terms, and drafts narrative
  prose. It never decides.
- **The MCN permission matrix is an absolute hard gate.** No LLM output or nuanced
  score can override an INTERDIT.
- **Nothing derived is silently trusted.** Classifications and extracted facts carry
  a confidence; low/borderline values are flagged `needs_officer_confirmation`.
- **Conservative by default.** When between two data classifications, pick the
  higher (more restrictive) one and flag it.
- **Everything the verdict rests on is stored.** The PDF is a pure rendering of an
  auditable `InterviewState`; the audit trail is first-class.
- **No fake formula for human judgment.** The matrix is the hard decision. F/M/E/C
  ratings are *proposals* PolicyBot pre-fills for the officer to validate — never a
  computed verdict. See §9.1.

## 4. Architecture

```
Web UI (FastAPI + minimal frontend, renders QuestionSpec)
        │  (QuestionSpec down, structured answers up)
Interview Orchestrator (LangGraph state machine, holds InterviewState)
        │
  ┌─────┼───────────┬──────────────┬───────────┬────────────┬──────────┐
  LLM   Data/Tool    Pre-approved   Contract     Grille       Report
  layer classifiers  DB (ArpRecord) analyzer      engine       (PDF)
  (swap)             + PreApproved  (TermsFetcher (matrix +    (HTML →
                                    + ARP extract) rules,       WeasyPrint)
                                                   pure Python)
```

**Invariant: only the Grille engine decides.** Every other component gathers or
presents facts.

### 4.1 Components

- **Web UI / API** — presents one interview step at a time, renders each
  `QuestionSpec` as clickable single-select cards / multi-select checkboxes with an
  optional "Other → free text" field; returns structured selections. No business
  logic.
- **Interview Orchestrator (LangGraph)** — owns the flow and a single
  `InterviewState`; drives nodes; persists via a checkpointer (resumable
  interviews). Never makes the risk decision.
- **LLM layer** — one `LLMProvider` interface (`rephrase`, `propose_options`,
  `parse_answer`, `extract_terms_facts`, `draft_rationale`). OpenRouter
  implementation for the POC (model: Gemma, "Gemma 4 31B" — confirm exact slug); a
  fake implementation for tests. Swappable.
- **Data Classifier** — LLM interprets the employee's plain-language data
  description → deterministic decision tree assigns **Non classifié / Protégé A /
  Protégé B / Protégé C** (+ `rens_personnels`), with confidence and
  `needs_officer_confirmation`.
- **Tool-type classifier** — registry-first mapping of the named tool to one of
  **IAG publique / circuit fermé / souveraine / gouvernementale**; a short
  `QuestionSpec` disambiguates unknowns.
- **Pre-approved DB (SQLite)** — stores reusable `ArpRecord` (per-tool product risk
  analysis) and `PreApprovedRecord` (per tool × classification decisions), each with
  `expires_at` so stale approvals force re-review.
- **Contract analyzer** — `TermsFetcher` (registry URL → web-search fallback →
  fetch + HTML-to-text + snapshot/date → manual paste last resort) + ARP extractor
  (LLM → fixed normalized `ContractFacts` + F/M/E/C product criteria). Cached per
  tool.
- **Grille engine** — pure Python. Per usage: matrix gate first, then encoded
  `grille.yaml` rules over ARP + Partie B residual risks → verdict, risk level,
  triggered rules, conditions. Deterministic, unit-tested.
- **Report generator** — HTML template of Fiche + Grille (A/B/C) → WeasyPrint PDF.
  Pure rendering of `InterviewState`.

## 5. The structured-question layer

The contract between graph and UI is a `QuestionSpec`, not free text:

```python
QuestionSpec = {
  "id": "data_description",
  "header": "Type de données",          # short chip label
  "question": "Quel type de données comptez-vous soumettre à l'outil ?",
  "multi_select": False,
  "options": [ { "label": str, "description": str }, ... ],
  "allow_other": True                     # renders an "Autre" free-text field
}
```

- The LLM composes the option menu (tailored to context); the **user picks**.
- Answers return as known option IDs → deterministic mapping in the classifiers and
  grille. Only "Autre" free text needs LLM interpretation, and it lowers confidence.
- The exact question, offered options, and selection are logged for the audit trail.

## 6. Interview flow (LangGraph)

```
1. Intro / consent  ("recommendation, not authorization")
2. Request info  (numéro IAG-2026-xxx, demandeur, unité)
3. Identify tool(s) + tool-type classifier
4. Per tool: ARP  (pre-approved cache? else auto-fetch terms → extract → F/M/E/C)
5. FOR EACH USAGE:
     5a. Describe data → Data classifier (level + rens. personnels?)
     5b. Usage details (mode prompt/API, result use, automated decisions)
     5c. MATRIX GATE (data × tool-type):  INTERDIT → usage Refusé, skip scoring
     5d. Partie B per-usage risk evaluation
6. Partie C synthesis  (global risk, ÉFVP-R required?, recommendation, conditions)
7. Generate PDF (Fiche + Grille A/B/C)
```

- **Pre-approved short-circuit:** a match needs tool **and** data classification, so
  the real short-circuit happens after 5a; node 4 is an early "is this tool known?"
  check that pre-loads/reuses the cached ARP.
- **Resumability:** a persisted `InterviewState` + LangGraph checkpointer lets a user
  pause (e.g., to locate a tool's terms) and resume.

## 7. The MCN permission matrix (hard gate)

The first, non-negotiable step of the Grille engine for each usage:

| Data ↓ / Tool → | Publique | Circuit fermé | Souveraine | Gouv (UQAM) |
|---|---|---|---|---|
| Non classifié | PERMIS | PERMIS | PERMIS | PERMIS |
| Protégé A | INTERDIT | PERMIS | PERMIS | PERMIS |
| Protégé B | INTERDIT | PERMIS | PERMIS | PERMIS |
| Protégé C | INTERDIT | INTERDIT | INTERDIT | OBLIGATOIRE |

- **INTERDIT ⇒ usage verdict = Refuser**, immediately, before any F/M/E/C scoring.
- **PERMIS / OBLIGATOIRE ⇒** proceed to Partie B and rule-based refinement.
- Implemented as a hard `if` over a 4×4 table in pure Python; exhaustively tested.

## 8. Data model

```python
InterviewState = {
  "interview_id": "uuid",
  "status": "in_progress | awaiting_terms | complete",
  "request": { "numero": "IAG-2026-xxx", "demandeur", "unite", "date" },
  "tools":  [ { "name", "vendor", "iag_type", "arp": ArpRecord } ],
  "usages": [ Usage, ... ],
  "result_global": {
     "risk_level": "Faible|Modéré|Élevé|Critique",
     "efvpr_required": bool,
     "recommendation": "Autoriser|Autoriser_avec_conditions|Refuser|Escalader",
     "conditions": [...], "rationale_narrative": str
  },
  "audit": { "question_log": [...], "timestamps": {...} }
}

Usage = {
  "description", "tool_ref",
  "raw_answers": {...},                    # selected option IDs
  "data_classification": "Non classifié|Protégé A|Protégé B|Protégé C",
  "rens_personnels": bool, "efvpr_required": bool,
  "mode": ["prompt"|"api"], "result_use": ["décision"|"publication"|"intrant"|"autre"],
  "automated_decisions": bool,
  "classifier_confidence": 0.0-1.0, "needs_officer_confirmation": bool,
  "matrix_result": "PERMIS|INTERDIT|OBLIGATOIRE",
  "partie_b": [ RiskFactor ],
  "verdict": "Autoriser|Autoriser_avec_conditions|Refuser|Escalader",
  "risk_level": "Faible|Modéré|Élevé|Critique", "conditions": [...]
}

ContractFacts = {                          # normalized ARP inputs
  "trains_on_input": "yes|no|opt_out_available|unknown",
  "data_retention": "none|limited|indefinite|unknown",
  "data_residency": "canada|us|eu|other|unknown",
  "sub_processors": "disclosed|undisclosed|unknown",
  "human_review": "yes|no|unknown",
  "source_url": str, "fetched_at": date, "snapshot_ref": str,
  "extraction_confidence": 0.0-1.0
}

RiskFactor = {                             # Partie A and Partie B rows
  "category", "criterion",
  "inherent": "F|M|E|C", "mitigation": str, "residual": "F|M|E|C",
  "responsable": str, "observations": str,
  "origin": "rule | llm_proposed",         # how the proposed rating was derived
  "proposed": bool                          # true until an officer validates it
}

ArpRecord = {                              # Partie A, one per tool, reusable
  "tool_name", "iag_type", "contract_facts": ContractFacts,
  "criteria": [RiskFactor], "terms_snapshot", "fetched_at",
  "expires_at", "approved_by"
}

PreApprovedRecord = {                      # per tool × classification decision
  "id", "tool_name", "data_classification", "iag_type",
  "verdict", "risk_level", "conditions": [...],
  "arp_ref", "approved_by", "approved_at", "expires_at"
}
```

Lookup match = `tool_name` + `data_classification` (+ `iag_type`) equal **and**
`expires_at` in the future.

## 9. The grille as data (grille.yaml)

The matrix is code (hard gate). The refinement rules that run *within* PERMIS are
data — a reviewable, versionable YAML the officers own. Encoding the paper grid is
data entry, not programming.

```yaml
# runs only for usages the matrix marks PERMIS / OBLIGATOIRE
- id: R-07
  when:
    contract.trains_on_input: ["yes", "unknown"]
    data.classification: ["Protégé A", "Protégé B", "Protégé C"]
  then:
    risk_level: Élevé
    recommendation: Autoriser_avec_conditions
    conditions: ["Confirmer l'opt-out d'entraînement auprès du fournisseur."]
- id: R-12
  when:
    contract.data_residency: ["us", "other", "unknown"]
    data.classification: ["Protégé A", "Protégé B"]
  then:
    risk_level: Modéré
    recommendation: Autoriser_avec_conditions
    conditions: ["Vérifier l'hébergement des données au Québec."]
```

**Engine order per usage:** ① matrix gate (INTERDIT ⇒ Refuser, stop) → ② evaluate
`grille.yaml` rules in priority order over ARP + Partie B facts → ③ take the
highest-severity match; collect all triggered rules for transparency → ④ set
`efvpr_required` if `rens_personnels`.

### 9.1 F/M/E/C ratings: pre-fill, officer decides

The F/M/E/C ratings are analyst judgment, not a computed result. PolicyBot does not
"decide" them; it pre-fills defensible proposals the officer validates or edits.
Three tiers:

1. **Deterministic proposals for clear-cut rules of thumb** — encoded in
   `grille.yaml`, only for heuristics officers already agree on. Examples:
   - `contract.trains_on_input = yes` → training-leak risk **Élevé**
   - no SSO/MFA support → auth risk **Moyen**
   - `data_residency ∈ {us, other, unknown}` + Protégé data → sovereignty risk
     **Moyen/Élevé**

   Start with the handful the officers are confident about; grow the file over time.
2. **Conservative LLM-drafted proposals for judgment criteria** (hallucination,
   reputational, org-dependency, etc.) — a suggested rating + one-line rationale
   derived from the usage answers, always flagged for officer confirmation. Lean
   higher when unsure.
3. **Global level = highest residual, labelled "proposé"** — no sum/average. The
   proposed global risk level is the worst-case residual across all criteria
   (transparent, explainable); the officer adjusts. Recommendation follows: any
   INTERDIT → Refuser; else Élevé/Critique residual → Escalader or
   Autoriser_avec_conditions; else Autoriser.

Every `RiskFactor` therefore carries an `origin ∈ {rule, llm_proposed}` and a
`proposed` flag so the report shows what was auto-suggested vs. rule-derived, and the
officer sets finals.

## 10. Report (PDF)

- **Mirrors the two official forms:** Page 1 Fiche de qualification (request, tools +
  IAG type, usages table, user profile, data management). Pages 2+ Grille — Partie A
  (ARP per tool), Partie B (per usage), Partie C (synthesis: global risk, ÉFVP-R
  flag, recommendation, conditions).
- **Every page footer:** "Recommandation générée par PolicyBot — requiert validation
  et autorisation par l'autorité désignée."
- **Sourced, not invented:** each verdict cites `triggered_rules` + the matrix
  result; classifications show derived reasoning; the ARP cites terms `source_url`
  + `fetched_at`. The LLM drafts only connective narrative.
- **Implementation:** HTML template → WeasyPrint PDF. Pure rendering of
  `InterviewState`.

## 11. Guardrails

- Every derived value carries confidence; low/borderline ⇒ `needs_officer_confirmation`
  rendered as a ⚠ flag in the report.
- Conservative-by-default classification (pick the higher level, flag it).
- The matrix gate is absolute — no override by LLM or score.
- "Autre" free-text answers always lower confidence and flag for review.
- Explicit "recommendation, not authorization" framing throughout.
- Full audit log (question, offered options, selection, timestamp).

## 12. Testing & test data

- **Grille engine — pure unit tests (priority).** All 16 matrix cells exhaustively
  tested; every `grille.yaml` rule gets a test. Deterministic, fully covered.
- **Golden scenarios** (from the real UQAM slide-5 example):
  - ChatGPT Pro / Perplexity + Protégé B strategic/financial data ⇒ INTERDIT / Refuser.
  - Public web info + ChatGPT ⇒ PERMIS.
  - Protégé A + Copilot Entreprise ⇒ PERMIS, with conditions from rules.
- **LLM-touching components** tested against a fake `LLMProvider` returning canned
  structured outputs (deterministic, offline). Real OpenRouter calls behind an
  integration-test flag.
- **TermsFetcher** tested against saved HTML fixtures, not the live web.
- **Test data:** `fixtures/` with sample tool terms HTML, sample usage descriptions
  per classification level, and expected verdicts. The slide-5 example is the
  canonical end-to-end acceptance test.

## 13. Tech & project structure (Python)

```
policybot/
  llm/            LLMProvider interface + OpenRouter impl + fake
  interview/      LangGraph graph, nodes, InterviewState, QuestionSpec
  classify/       data classifier + tool-type classifier
  contract/       TermsFetcher + ARP extractor
  grille/         matrix + rule engine + grille.yaml
  preapproved/    SQLite store, ArpRecord / PreApprovedRecord
  report/         HTML templates + WeasyPrint PDF
  api/            FastAPI + minimal frontend (renders QuestionSpec)
  fixtures/       test data
tests/
```

## 14. MVP scope

**In:** core flow (interview → grille → report), pre-approved tools lookup,
automated contract/terms analysis (auto-fetch), PDF report, multi-usage, both
classifiers, three-part grille, ÉFVP-R flag.

**Deferred:** officer review dashboard / back-office; live re-fetch scheduling of
stale ARPs; UQAM visual-identity theming of the PDF.

## 15. Open items (need input before/during implementation)

- **F/M/E/C approach — RESOLVED (see §9.1):** pre-fill proposals, officer decides.
  Still to collect: the initial set of clear-cut rules of thumb to seed
  `grille.yaml`, from the officers.
- The **tool registry** seed list (name → IAG type, terms URLs).
- **OpenRouter model — RESOLVED:** Gemma (user specified "Gemma 4 31B"); confirm the
  exact OpenRouter model slug at implementation time.
- **Data entered — RESOLVED:** interview answers contain **only descriptions and
  metadata**, never the sensitive data itself. This keeps sending prompts to a cloud
  LLM acceptable.

## 16. Glossary

- **MCN** — Ministère de la Cybersécurité et du Numérique.
- **LGGRI** — Loi sur la gouvernance et la gestion des ressources informationnelles.
- **IAG** — IA générative.
- **ARP** — Analyse des risques du produit (Partie A of the grille, per tool).
- **ÉFVP-R** — Évaluation des facteurs relatifs à la vie privée (réduite); required
  when personal information is involved.
- **LAI/PRP** — Loi sur l'accès aux documents et la protection des renseignements
  personnels.
- **F/M/E/C** — Faible / Moyen (Modéré) / Élevé / Critique risk levels.
- **SI** — Direction des systèmes d'information.
