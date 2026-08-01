# Architecture

## The organising idea: four cognitive layers

| Layer | Question | Owner |
|---|---|---|
| **1 — Understanding** | What did the customer say? | LLM (fast tier) |
| **2 — Planning** | What should happen? | Deterministic rule engine |
| **3 — Decision** | Answer, clarify, route, or escalate? | Deterministic business rules |
| **4 — Execution** | Do it. | Deterministic; LLM writes prose only |

Every routing decision is code. The model reports what it heard; the
business decides what happens. This split is what makes decisions
reproducible, diffable and explainable.

## Folder structure

```
alto-orchestrator/
├─ backend/
│  ├─ app/
│  │  ├─ domain/               pure business core, zero framework imports
│  │  │  ├─ entities.py        Inquiry, Intent, IntentQueue, ConversationState, HumanReviewItem, ExecutionAction, Span
│  │  │  ├─ value_objects.py   LanguageProfile, Sentiment, ConfidenceVector, RetrievedChunk, DraftReply, ...
│  │  │  ├─ enums.py           closed vocabularies (IntentCategory, Department, RoutingTier, ...)
│  │  │  ├─ ports.py           Protocol interfaces (LLMProvider, Retriever, Cache, VehicleCatalog, ...)
│  │  │  └─ policies/          YAML business rules + typed loaders
│  │  │     ├─ intents.yaml    intent → department, priority, required slots, dependencies
│  │  │     ├─ confidence.yaml six signal weights, thresholds, hard overrides
│  │  │     ├─ finance.yaml    regulatory limits, rate bands, disclaimers
│  │  │     └─ valuation.yaml  synthetic trade-in model
│  │  ├─ services/             pure services, depend on domain ports
│  │  │  ├─ understanding/     normalizer, language detection, LLM engine, schemas
│  │  │  ├─ planning/          rule-engine planner
│  │  │  ├─ decision/          confidence engine, department router
│  │  │  └─ execution/         finance/valuation tools, grounding, runtime (tools/actuator/generator/queue/memory)
│  │  ├─ infrastructure/       framework adapters
│  │  │  ├─ llm/               OpenAI, Anthropic, Mock providers + ModelRouter, cost registry
│  │  │  ├─ vectorstore/       Qdrant HybridRetriever + NullRetriever
│  │  │  ├─ embeddings/        FastEmbed dense + sparse + cross-encoder rerank
│  │  │  └─ persistence/       SQLAlchemy engine, VehicleRow, CatalogLookupService
│  │  ├─ graph/                LangGraph wiring
│  │  │  ├─ state.py           GraphState TypedDict + reducers (merge_intents, concat_sequence, take_last)
│  │  │  ├─ nodes.py           17 nodes across the four layers
│  │  │  └─ builder.py         graph assembly, conditional edges, retry loop
│  │  ├─ api/v1/               FastAPI routes + DTOs
│  │  ├─ composition/          container.py — the DI root (the only place allowed to touch all layers)
│  │  ├─ core/                 settings, logging, errors
│  │  ├─ workers/ingestion/    one-shot batch: PDFs + policies + catalog → Qdrant + Postgres
│  │  └─ main.py               FastAPI app factory + lifespan
│  └─ tests/                   unit + integration + e2e
├─ frontend/
│  └─ src/
│     ├─ app/
│     │  ├─ page.tsx           short public landing (non-technical)
│     │  ├─ workflow/          deep technical page (architecture, layers, signals)
│     │  ├─ chat/              customer chat with provenance
│     │  └─ admin/             operations view with human queue
│     ├─ components/           Reveal (scroll-in animator)
│     ├─ lib/api.ts            typed API client, DTOs mirror backend
│     └─ styles/globals.css    Swiss design tokens
├─ data/
│  ├─ catalog/vehicles.csv     11,914 rows
│  └─ knowledge/
│     ├─ finance/              6 real UAE bank PDFs (ADIB, DIB, ENBD, CBD, Ajman, CBUAE)
│     └─ policies/             10 authored Alto Motors policies (synthetic Velmora content)
├─ docs/
│  ├─ spec/                    canonical specification, numbered 00–16
│  ├─ reference/               LangGraph agentic-RAG documentation
│  └─ REFERENCE_PATTERNS.md    engineering distilled from four now-deleted reference repos
├─ docker-compose.yml
├─ tasks.py                    cross-platform runner (works on Windows)
├─ Makefile                    delegates to tasks.py on Linux/CI
├─ .env / .env.example
├─ CLAUDE.md                   session entry point
└─ memory/                     persistent memory files
```

## Dependency rule (enforced by fitness test)

```
api  ──►  application  ──►  domain  ◄──  infrastructure
                              ▲
                            graph, services
```

- `domain/` imports **no framework** — no FastAPI, SQLAlchemy, Qdrant,
  LangGraph or vendor SDKs. Pure Python.
- `services/` may import `domain` and other `services`. Not `infrastructure`.
- `graph/` may import `services`, `domain`, `core`.
- `infrastructure/` may import `domain` and `core`.
- `api/` and `composition/` are the only layers allowed to touch all of them.
- `composition/container.py` is the composition root — the single place
  where concrete adapters are wired to ports.

The architecture fitness test in `tests/unit/test_architecture.py`
enforces this at build time.

## The graph

Nodes are grouped by cognitive layer. Reducers own how state merges across
turns.

**Layer 1 (LLM, fast tier)**
- `normalize` — deterministic Arabic/Arabizi/PII normaliser (no model call)
- `detect_language` — script-ratio detector (no model call)
- `discover_intents` — structured output → `IntentQueue`
- `extract_entities` — structured output → `ExtractedEntity[]`
- `score_sentiment` — structured output → `Sentiment`

Understanding runs the last three in parallel — three fan-out edges from
`detect_language`, all converging on `build_plan`.

**Layer 2 (deterministic)**
- `build_plan` — enriches intents with policy (department, required slots,
  dependencies), recomputes missing slots, chooses a `next_action`. Renamed
  from `plan` because LangGraph reserves node names against state keys.

**Layer 3 (deterministic)**
- `score_confidence` — evaluates all six signals, weighted per policy
- `decide` — routes to auto (≥90), premium (75–89), or human (<75). Hard
  overrides fire first.

**Layer 4 (deterministic + LLM for prose)**
- `retrieve` — Qdrant hybrid RRF + rerank
- `call_tools` — catalog lookup (Postgres), EMI, trade-in valuation
- `actuate` — CRM/booking/notification adapters with idempotency
- `generate` — LLM writes the reply prose, injected with tool results
- `validate_grounding` — deterministic claim-vs-evidence check, one retry on soft fail
- `clarify` — targeted single-slot question (no LLM)
- `escalate_human` — enqueues review with full transcript
- `persist_memory` — writes wide-event spans, updates transcript

## Reducers

- `merge_intents` — folds new intents into the queue by category, never
  drops unresolved intents, preserves rule-engine fields (department,
  priority, depends_on) on merge.
- `concat_sequence` — appends entities and actions across turns, tolerating
  the tuple↔list round-trip through LangGraph's checkpointer.
- `take_last` — default for single-valued fields.

## Storage layout

Three stores, three failure modes, one truthful catalog:

| Store | Role | What lives here |
|---|---|---|
| **PostgreSQL** | Structured facts | Vehicles table (11,914 rows), used for exact catalog lookups. Wide-event spans, conversation state, human queue — currently in-memory, will move here for Module 14. |
| **Qdrant** | Vector search | Three collections: `alto_finance_kb` (bank PDFs), `alto_policy_kb` (10 authored policies), `alto_vehicle_catalog` (embedded natural-language cards). Each with dense multilingual + BM25 sparse (IDF modifier). |
| **Redis** | Short-term | Session buffers, transient state. Not currently exercised heavily. |

## Retrieval funnel

Per query, per intent-relevant collection:

1. **Prefetch × 2** — dense (multilingual MiniLM 384d) and sparse (BM25 with
   IDF modifier), 100 candidates each, in parallel.
2. **Server-side RRF** — Qdrant's `FusionQuery(fusion=Fusion.RRF)`. No
   score-scale blending; rank-based fusion.
3. **Rerank** — cross-encoder scores top 20 fused. **Skipped for Arabic
   queries** — the ms-marco reranker is English-only and returns uniformly
   negative scores on non-Latin input, so we preserve the RRF ranking rather
   than scramble it.
4. **Top-K** — 5 chunks to the generator, every stage's score persisted.

## API surface

`POST /api/v1/inquiries` — submit a message, run the graph.
`GET /api/v1/conversations/{id}` — full state + transcript (customer restore
and reviewer viewing).
`GET /api/v1/conversations/{id}/trace` — every span.
`GET /api/v1/conversations/{id}/stream` — SSE, node events + final result.
`GET /api/v1/admin/human-queue` — open review items with transcripts attached.
`POST /api/v1/admin/human-queue/{id}/resolve` — approve/edit/reassign/reject.
  For approved and edited, the text is appended to the customer transcript.
`POST /api/v1/admin/conversations/{id}/reply` — live operator message,
  used after handoff to continue the thread without going through the queue.
`GET /api/v1/admin/metrics` — layer/node latency, cost, tokens, escalation
  rate.
`POST /api/v1/tools/emi` and `/tools/trade-in` — deterministic tools
  exposed directly for the operations UI.
`GET /health` and `/ready`.

## Ports and adapters

The domain declares these Protocol interfaces in `domain/ports.py`:

- `LLMProvider` — implemented by OpenAI, Anthropic, Mock.
- `Retriever` — implemented by `HybridRetriever` and `NullRetriever`.
- `Embedder` and `Reranker` — implemented by FastEmbed adapters.
- `Cache` — Redis adapter (thin; not heavily exercised).
- `VehicleCatalog` — implemented by `VehicleCatalogService` (in-memory CSV).
- `CrmPort`, `AppointmentPort`, `NotificationPort` — implemented by in-process
  adapters in `services/execution/runtime.py::Actuator`.

The concrete `CatalogLookupService` (structured Postgres lookup) lives in
`infrastructure/persistence/catalog_repository.py` and is exposed to the
tool runner through a local `_CatalogLookupPort` Protocol declared in
`runtime.py` — that Protocol lets the service module depend on shape
without importing infrastructure directly.
