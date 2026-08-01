# Project overview

## Vision

Automate the coordinator's thinking at Alto Motors — the human who currently
reads every incoming inquiry, classifies it, and routes it — while making
every AI decision auditable and every low-confidence case land in the hands
of a person.

The platform is not a chatbot and not an LLM wrapper. The intelligence lives
in orchestration, hybrid retrieval, structured memory, six-signal confidence
scoring, and honest handoff to humans. The LLM participates in two places
only: **understanding** (what did the customer say?) and **response
generation** (write the reply prose). Every other decision — which
department, whether to escalate, what tool to run, whether the answer is
supported by evidence — is deterministic application code.

## Business context (fictional)

Alto Motors is a single-showroom dealership in **Velmora** (fictional
market patterned on the UAE). It sells two brands:

- **Karva** — mass-market sedans and SUVs, AED 45k–180k, volume of the
  showroom, first-time buyers and families. 9,015 vehicles in the catalog.
- **Renzo** — premium and performance vehicles, AED 195k–750k+, returning
  buyers and business owners. 2,899 vehicles in the catalog.

The showroom receives 80–100 inquiries a day across web forms and walk-in
follow-ups. A human coordinator currently spends ~5 hours a day reading,
classifying and routing them. Real messages mix intents in one sentence,
arrive as fragments ("is this still available?"), and switch between
Arabic and English mid-thought.

## Users

The AI serves four internal personas plus the customer:

- **Customer** — via the chat surface at `/chat`.
- **Sales consultant** — receives test-drive and pricing routings.
- **Finance consultant** — receives financing routings.
- **Trade-in appraiser** — receives valuation routings.
- **Customer relations** — receives complaints and low-confidence escalations.

## Goals

1. **Multi-intent handling as the default path**, not a special case. A
   message with three requests becomes an intent queue of three.
2. **Six-signal confidence, not one number.** Language, intent, entity,
   retrieval, risk, policy — measured and displayed separately.
3. **Bilingual (Arabic/English) throughout**, including messages that
   switch mid-sentence. When any Arabic appears, the reply carries both
   languages.
4. **Structured retrieval where the question is structured** (Postgres
   catalog for exact vehicle lookups), vector retrieval where the question
   is fuzzy (policy and finance documents).
5. **Interactive human handoff** — when a conversation escalates, the
   reviewer sees the full transcript, sends the drafted reply as-is or
   edits it, and can continue the thread live from the operations view.
6. **Explainability at every stage** — every retrieval score, every
   routing rule, every confidence signal is visible in the UI.

## Success criteria (nominal)

Documented in the specification files under `docs/spec/`:

- **Intent accuracy ≥ 0.85** on the golden set (not yet built; Module 14).
- **Retrieval recall@100 ≥ 0.90** on the golden set.
- **Hallucination rate ≤ 0.02** as measured by the grounding validator.
- **p95 latency ≤ 6 seconds** on the premium path.

Actual measurement is blocked pending Module 14 (evaluation service and
golden set).

## Constraints

- **Runs entirely locally in Docker Compose** — Postgres, Qdrant, Redis,
  plus the backend and frontend. No cloud dependency required to demo.
- **Mock provider allows keyless operation.** `LLM_PROVIDER=mock` is
  deterministic and the default. Real providers (OpenAI, Anthropic) sit
  behind the same port and slot in with one line of `.env`.
- **No autonomous customer-facing sending in v1.** `ALLOW_AUTO_SEND=false`
  is the default; every reply is drafted for approval until an operator
  turns it on explicitly.
- **Regulatory-grounded financing.** Every financing answer is grounded in
  either the ingested CBUAE regulation or one of the six bank Key Facts
  Statements. Numbers never come from the model.

## Fictional-but-real distinction

- **Karva, Renzo, Velmora, Alto Motors** — fictional. Explicitly labelled
  as such in every authored document.
- **The six bank PDFs** (ADIB, DIB, Emirates NBD, CBD, Ajman Bank, CBUAE) —
  **real UAE documents**, indexed verbatim. Financing answers must cite
  them, never rebrand them.
- **The 11,914-row vehicle catalog** — real Kaggle vehicle-features data
  with the `Make` column rebranded to Karva/Renzo. Data underneath is
  authentic (MSRP, horsepower, fuel economy).
- **The ten authored policy documents** (`data/knowledge/policies/`) —
  synthetic Velmora content, UAE-shaped, clearly disclaimed at the top of
  each file.
