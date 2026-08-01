# Future tasks

Prioritised backlog. Mark items completed with a `~~strikethrough~~` and a
date rather than removing them, so future sessions can see history.

## High priority

### H-6 — Decide gpt-5-mini vs gpt-4o-mini for the fast tier
Swapped 2026-08-01 (see decisions.md D-013). gpt-5-mini is 4-6x the
per-call cost and 3-8x the latency of gpt-4o-mini on the same
structured-extraction task shape, consistent with reasoning-model
chain-of-thought overhead. Cost per turn is still trivial in absolute
terms (~$0.004), but the fast tier's whole design premise was "cheap and
quick enough to run three parallel calls every turn" — worth revisiting
once Module 14 (H-1) can measure whether gpt-5-mini's presumed accuracy
edge is real and big enough to justify the tradeoff. One-line revert in
`.env` if not.

### H-7 — Verify gpt-5-mini pricing in registry.py
The `PRICING["gpt-5-mini"]` entry in `infrastructure/llm/registry.py` is
an estimate, not sourced from OpenAI's published rate card. The
BudgetGuard uses this number directly for spend tracking and tier
demotion — a wrong number silently mis-tracks the daily budget. Check
against OpenAI's current pricing page and correct if needed.

### H-1 — Module 14: evaluation service
Build the harness that measures the metrics named in the spec.

- Author a golden set (~40 cases) covering:
  - Single-intent and multi-intent messages
  - Arabic-only, English-only, mixed
  - Vague fragments requiring clarification
  - Complaints (must always escalate)
  - Cases that exercise the "we don't stock that" reply
- Implement metrics: intent accuracy, retrieval recall@100, hallucination
  rate, faithfulness score, escalation rate, latency percentiles, cost per
  conversation.
- Add `POST /api/v1/admin/eval/run` endpoint returning full metric report.
- Add CI gate: prompt or model changes must not regress the golden set.
- **Effort**: multi-day.

### H-2 — Real persistence for conversations and spans
Postgres schema for the state currently held in `MemoryService`.

- ORM models: `ConversationRow`, `SpanRow`, `HumanReviewRow`,
  `ExecutionActionRow`.
- Repositories in `infrastructure/persistence/`.
- Update `MemoryService` to use them (or replace with per-entity
  repositories injected into the container).
- Alembic migration for the schema.
- Confirm the graph checkpointer (`AsyncPostgresSaver`) also runs against
  Postgres — currently `MemorySaver`.
- **Effort**: 1–2 days.

### H-3 — Animated workflow graph in `/admin`
Consume the existing SSE endpoint (`GET /api/v1/conversations/{id}/stream`)
and render a live React Flow diagram highlighting the current node.

- Static graph shape from `graph/builder.py` (17 nodes, layered).
- Node state: idle / running / done / error / skipped.
- Emit per-node latency badges as they complete.
- Click a node to see its span attributes.
- **Effort**: 1 day.

## Medium priority

### M-1 — Populate Postgres and re-run ingestion end to end
Currently the structured catalog code is wired but the data isn't loaded
in the user's environment.

- `python tasks.py up` to start Docker.
- `python -m app.workers.ingestion --recreate` to populate both Qdrant
  (with the ten new policy documents) and Postgres.
- Verify `curl http://localhost:8080/ready` returns
  `structured_catalog: true`.
- Test the "Renzo GX 470" scenario end to end.
- **Effort**: hours, once Docker is up.

### M-2 — Auth middleware
JWT enforcement with role claims and a seed script for demo users.

- Roles: `customer`, `coordinator`, `finance`, `trade_in`, `management`.
- Guards on `/admin/*` endpoints.
- Login endpoint issuing a JWT.
- **Effort**: half a day.

### M-3 — Multilingual reranker
Replace `Xenova/ms-marco-MiniLM-L-6-v2` (English-only) with a multilingual
cross-encoder so Arabic queries no longer skip reranking.

- Candidate: `BAAI/bge-reranker-v2-m3` (supports Arabic and English).
- Verify via a small test set that Arabic reranked results are better than
  RRF-only.
- Update `_is_non_latin` bypass to be gated on the reranker's language
  coverage.
- **Effort**: half a day + test data.

### M-4 — Provenance click-through opens source PDFs
- Add a `/documents/[docId]` route that serves the PDF.
- Scroll to `?page=N` on mount.
- Highlight the passage text if the URL carries a chunk id.
- **Effort**: 1 day.

### M-5 — Live cost dashboard in `/admin`
Extend the metrics view with a per-provider, per-tier cost chart and a
budget-remaining bar.

- **Effort**: half a day.

## Low priority

### L-1 — Frontend test framework
Playwright or Vitest wired up, cover the customer chat and operations
happy paths.

### L-2 — Full localisation of the operations UI
Currently the admin is English-only; the customer chat is bilingual. If
Arabic-first operators exist, the admin also needs Arabic.

### L-3 — Voice input on the customer chat
Speech-to-text via a browser API for accessibility and mobile use.

### L-4 — WhatsApp channel adapter
`Inquiry.channel` already carries `whatsapp`. A webhook adapter would
receive WhatsApp Business messages and route them through the same graph.

### L-5 — Prompt versioning with hashes
Every span already records the prompt version hash could be added — every
historical answer would then be exactly reproducible.

## Nice to have

### N-1 — Shadow-mode replay
Re-run any historical conversation against a new config and diff the
routing decisions. De-risks threshold changes.

### N-2 — Confidence calibration curve
Log predicted confidence versus human-verified correctness after review.
Surface a reliability curve in the admin. Would catch overconfident
models before they cost a sale.

### N-3 — WhatsApp-style read receipts in the operations UI
Timestamps for "delivered" and "read" states, so operators know when a
customer has seen their reply.

## Future ideas

### F-1 — Non-Alto brands as trade-ins that go straight to auction
The trade-in policy already says we auction onward. Model this in
`ExecutionAction` with a partner-auction adapter.

### F-2 — Fleet enquiries as a distinct intent
Alto Motors doesn't currently sell fleet — but a customer asking about
fleet should be told so directly and referred to a partner. Would need a
new intent category and a new department.

### F-3 — Recall lookups
The service documentation mentions the assistant can look up open recalls
by VIN or plate. Not built. Would need a recall database (synthetic).

## Completed items (retained for history)

*(Move items here with a completion date when they land. Do not delete.)*
