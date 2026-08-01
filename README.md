# Alto AI Support Orchestrator

Multilingual AI customer-support orchestration for **Alto Motors**, a dealership in the fictional market of Velmora selling two brands — **Karva** (mass-market sedans and SUVs) and **Renzo** (premium and performance).

The showroom takes 80–100 inquiries a day across WhatsApp, web forms and walk-in follow-ups. A coordinator reads every one, classifies it and routes it by hand — roughly five hours daily, with misroutes and delays costing sales. Real messages are not clean: they mix intents in a single sentence, arrive as fragments like *"is this still available?"*, and switch between Arabic and English mid-thought.

This platform automates **the coordinator's thinking**, not "classification".

> It is not a chatbot and not an LLM wrapper. The intelligence is in the orchestration: routing, hybrid retrieval, structured memory, confidence scoring and explainability. Every AI decision is auditable, and low-confidence cases escalate to a human rather than guess.

---

## The organising idea: four cognitive layers

| Layer | Question | Owned by |
|---|---|---|
| **1 — Understanding** | What did the customer actually say? | **LLM** (fast tier) |
| **2 — Planning** | What should happen? | Deterministic rule engine |
| **3 — Decision** | Answer, clarify, route, or escalate? | Deterministic business rules |
| **4 — Execution** | Do it. | Deterministic; LLM writes prose only |

**The LLM participates in Understanding and Response Generation. Nothing else.** The model reports *"intent = TRADE_IN, confidence 96%"*; the business engine — not the model — decides that trade-ins go to the Trade-In team. Routing, escalation, memory and plan construction are application code, which makes them reproducible, diffable and testable.

Three consequences worth stating plainly:

- **Multi-intent is the default path.** Every message produces an intent queue; a simple message just yields a queue of length one. Nothing downstream branches on "how many intents". Unresolved intents are never dropped — that is enforced by a state reducer, not by hoping the prompt remembers.
- **Conversation state is an object, not a transcript.** The system remembers, so the model doesn't have to. No component re-derives intent by re-reading chat history.
- **Confidence is evidence, not a probability.** Six signals — language, intent, entity, retrieval, risk, policy — are measured and displayed separately. A system that collapses them into one number cannot explain itself.

Full design rationale: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) *(Module 2)*. Canonical specification: [`docs/spec/`](docs/spec/), read in numeric order.

---

## Quick start

**Requires** Docker, Python 3.11+, Node 20+.

```bash
cp .env.example .env
python tasks.py up
```

That starts Postgres, Redis and Qdrant, waits for every container to report healthy, then probes each published port from the host. On Linux, macOS or CI you can use `make up` instead — the Makefile just delegates here.

Then install and index:

```bash
cd backend && python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"
```

```bash
cd backend && .venv/Scripts/python -m app.workers.ingestion --recreate
```

Ingestion downloads ~250 MB of ONNX weights on first run and takes a few
minutes. Add `--catalog-limit 400` for a fast smoke run. It builds three
things in one pass:

1. **Qdrant vector collections** — the ten Alto Motors policy documents,
   six UAE bank finance PDFs, and the 11,914-vehicle catalog embedded as
   natural language.
2. **Postgres `vehicles` table** — the same catalog as a structured table,
   so *"do you have the Renzo GX 470?"* is an exact row lookup instead of a
   vector-similarity guess.
3. **Postgres schema for the app** — auto-created on the same run.

If Postgres isn't up, add `--skip-postgres` and the vector-only path still
works — you just lose honest "we don't stock that" replies.

Run the two services:

```bash
cd backend && .venv/Scripts/python -m uvicorn app.main:app --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

Then open <http://localhost:3000>. If port 3000 is taken, run the frontend on
another port and add it to `CORS_ORIGINS` in `.env` — the backend rejects
unlisted origins, which surfaces in the browser as an opaque "failed to
fetch".

```bash
python tasks.py help     # every target
python tasks.py test     # backend suite
python tasks.py down     # stop, keep data
python tasks.py reset    # stop and destroy volumes
```

**No API key is needed.** `LLM_PROVIDER=mock` is the default and runs the
whole stack deterministically at zero cost; embeddings and reranking are local
models, so retrieval never calls a paid API either. Set `LLM_PROVIDER=openai`
or `anthropic` with the matching key for real inference — nothing else
changes, because both sit behind the same port.

---

## Layout

```
alto-orchestrator/
├─ backend/               FastAPI + LangGraph, clean architecture
│  ├─ app/
│  │  ├─ domain/          pure business core — entities, policies, ports
│  │  ├─ application/     use cases
│  │  ├─ infrastructure/  adapters: Postgres, Redis, Qdrant, LLMs, embeddings
│  │  ├─ graph/           LangGraph state, nodes, edges
│  │  ├─ services/        understanding / planning / decision / execution
│  │  ├─ api/             HTTP surface
│  │  └─ workers/         ingestion
│  └─ tests/              unit · integration · e2e
├─ frontend/              Next.js 15, feature-sliced
├─ data/
│  ├─ knowledge/finance/  6 UAE bank auto-finance PDFs (real documents)
│  ├─ knowledge/policies/ Alto Motors policies (authored, synthetic)
│  ├─ catalog/            11,914 vehicles — Karva 9,015 / Renzo 2,899
│  └─ eval/               golden set
├─ docs/
│  ├─ spec/               canonical specification, 00–16
│  ├─ reference/          LangGraph RAG documentation
│  └─ REFERENCE_PATTERNS.md
├─ docker-compose.yml
└─ tasks.py               canonical command runner
```

The dependency rule points inward: `api → application → domain ← infrastructure`. `domain/` imports no framework — not FastAPI, SQLAlchemy, Qdrant or LangGraph — so the business core is testable with no I/O. An architecture fitness test enforces this.

---

## Data

**Vehicle catalog** — 11,914 rows, Karva 9,015 / Renzo 2,899, with MSRP, market category, body style, engine and efficiency data. Powers catalog retrieval and the trade-in valuation model.

**Finance knowledge base** — six auto-finance documents from ADIB, Dubai Islamic Bank, Emirates NBD, Commercial Bank of Dubai, Ajman Bank, and the CBUAE lending regulation. 39 pages covering profit rates, tenure caps, down-payment minimums, early-settlement fees and insurance obligations.

> These are **real UAE regulatory and banking documents**, retained verbatim because financing answers must be accurate. They are tagged `source_authority: real_uae_regulatory` and surfaced with a provenance disclaimer. Velmora and both car brands are fictional; the finance corpus is not, and is never rebranded.

**Authored content** — test-drive and trade-in policies, and the evaluation golden set, are written for this project and clearly marked as synthetic Velmora content. No source material for them was supplied.

---

## Build status

Delivered one module at a time; each ships tested and runnable before the next begins.

| # | Module | Status |
|---|---|---|
| 1 | Workspace scaffold & cleanup | **done** |
| 2 | Domain core | **done** |
| 3 | Infrastructure & DI | **done** |
| 4 | Language layer (Arabic / Arabizi / mixed) | **done** |
| 5 | Ingestion & hybrid retrieval | **done** |
| 6 | LLM providers & model router | **done** |
| 7a | Understanding layer | **done** |
| 7b | Planning & Decision layers | **done** |
| 7c | Execution layer | **done** |
| 8 | LangGraph orchestrator | **done** |
| 9 | FastAPI surface | **done** |
| 10 | Frontend foundation | **done** |
| 11 | Swiss landing page | **done** |
| 12 | Customer chat & provenance UI | **done** |
| 13 | Admin dashboard | partial — see below |
| 14 | Evaluation & hardening | **not built** |

**192 backend tests pass**, covering the domain, the language layer, the
deterministic tools, the decision layer, the full graph end to end, and the
API. The frontend builds clean under strict TypeScript.

### Known gaps

Stated plainly rather than left to be discovered:

- **No golden set and no evaluation service (Module 14).** Faithfulness,
  groundedness, retrieval precision/recall, hallucination rate and intent
  accuracy are all specified and none are measured. `python tasks.py eval`
  reports that the suite does not exist rather than printing a passing score
  it did not compute. This is the largest gap.
- **The admin dashboard has no animated workflow graph.** The SSE endpoint
  streams node transitions and the trace API exposes every span, so the data
  is there; the React Flow visualisation on top of it is not built. The queue,
  confidence breakdown, routing rationale and per-layer cost/latency are.
- **Persistence is in-process.** Repositories, span storage and the human
  queue are in-memory implementations behind their ports; the SQLAlchemy
  adapters and Alembic migrations are not written, so state does not survive a
  restart. Postgres runs in Compose and the DSNs are configured.
- **Provenance click-through opens no document.** Chunks carry page numbers
  and every retrieval score, and the UI shows them; the document viewer that
  opens the source PDF at the highlighted passage is not built.
- **Reranking is skipped for Arabic queries.** The `ms-marco` cross-encoder is
  English-only and returned uniformly negative scores on Arabic input, which
  scrambled a fusion order that was already correct. The reranker detects
  non-Latin queries and preserves the RRF ranking instead. Cross-lingual
  retrieval itself works — the dense model is multilingual. A multilingual
  reranker would close this properly.
- **No auth.** JWT settings exist; no middleware enforces them.

---

## Technology

**Backend** — Python 3.11, FastAPI, LangGraph, SQLAlchemy, Pydantic, PostgreSQL 16, Redis 7, Qdrant 1.17
**Frontend** — Next.js 15, TypeScript (strict), Tailwind, TanStack Query, React Flow
**Models** — OpenAI / Anthropic / deterministic Mock behind one port; local FastEmbed for dense, sparse and reranking

Qdrant is pinned to 1.17 because DBSF fusion, tunable RRF `k` and `FormulaQuery` all require it. Retrieval uses one collection with two named vectors (`dense` + `bm25`), fused server-side by Reciprocal Rank Fusion, then reranked by a local cross-encoder. Every score from every stage is persisted and shown in the UI — that is the explainability requirement, and it is not optional.

Dense embeddings are cross-lingual (`multilingual-e5-small`), so an Arabic query retrieves the English source documents directly, with no translation hop. When Arabic appears anywhere in a message, the reply is bilingual.

---

## Documentation

| Document | Contents |
|---|---|
| [`docs/spec/`](docs/spec/) | Canonical specification, 00–16. Overrides assumptions on conflict. |
| [`docs/REFERENCE_PATTERNS.md`](docs/REFERENCE_PATTERNS.md) | Engineering extracted from the four supplied reference repositories, which were analysed and then removed. |
| [`docs/reference/`](docs/reference/) | LangGraph agentic-RAG documentation. |
