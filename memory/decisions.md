# Engineering decisions

Log every significant design choice. Include the alternatives that were
considered and rejected, so a future Claude session doesn't relitigate the
same discussion.

## 2026-07-30

### D-001 — LLM providers, plural

**Problem**: The initial spec named `GPT-5.5` / `GPT-5.5-mini` — not real
model IDs. Real IDs and a real strategy needed.

**Options**:
1. OpenAI only.
2. Anthropic only.
3. Provider abstraction over OpenAI + Anthropic + a deterministic Mock.

**Chosen**: Option 3. `LLMProvider` port with three adapters. Mock is
default (`LLM_PROVIDER=mock`) — deterministic, keyless, powers CI and a
zero-cost demo.

**Reasoning**: Vendor lock-in is avoidable at almost no cost. Mock is
independently useful (tests, demo without a key). Vendor SDKs imported
lazily inside adapters so a mock-only install doesn't require them.

### D-002 — Postgres for spans, not ClickHouse

**Problem**: Langfuse (a reference) uses ClickHouse for wide-event
observability. Should we?

**Options**:
1. Langfuse-style ClickHouse cluster.
2. Wide-event spans in Postgres.

**Chosen**: Option 2.

**Reasoning**: Langfuse's own architecture principles say extra databases
must earn their operational burden. At ~100 inquiries/day, ClickHouse
loses that argument. Ceiling is ~10⁶ spans in Postgres; documented.

### D-003 — Cross-lingual retrieval without translation

**Problem**: Arabic customer messages need to retrieve from an
English-only corpus. Translate the query first, or embed in a
multilingual space?

**Options**:
1. Translate Arabic → English before retrieval.
2. Use a multilingual dense model that puts Arabic and English in the
   same vector space.

**Chosen**: Option 2 (`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`).

**Reasoning**: Satisfies the "reason in the original language" rule.
Verified live — an Arabic financing question retrieves the English ENBD
document at usable dense scores (0.56–0.68). One less pipeline step, one
less failure mode.

### D-004 — Skip the reranker for Arabic queries

**Problem**: The `ms-marco` cross-encoder is English-trained and returned
uniformly negative scores on Arabic queries during initial verification —
scrambling a fusion order that was already correct.

**Options**:
1. Rerank always, tolerate the mangling.
2. Rerank only for Latin-script queries; preserve RRF order for others.
3. Find a multilingual reranker.

**Chosen**: Option 2 for now.

**Reasoning**: Silently degrading beats scrambling a good order.
`_is_non_latin` on the query bypasses reranking. Option 3 is
`future_tasks.md` medium priority.

### D-005 — Slot alias for `vehicle_reference`

**Problem**: A customer answering *"which vehicle?"* with *"Renzo S5"*
provides `new_vehicle_brand + new_vehicle_model` — but the intent's
required slot is literally `vehicle_reference`. The planner kept asking
the same question forever.

**Options**:
1. Extract a synthetic `vehicle_reference` entity whenever a brand+model
   is extracted.
2. Alias the slot: `vehicle_reference` is satisfied by any of a set of
   related entity types.

**Chosen**: Option 2, in `planning/planner.py`. Alias map is a small
module-level constant.

**Reasoning**: The extractor stays honest about what it extracted. The
alias is a policy rule and lives in the planner where it can be reviewed.

## 2026-07-31

### D-006 — Session ID in localStorage, not URL

**Problem**: Navigating between `/chat` and `/admin` lost the customer's
conversation. Where should the ID live?

**Options**:
1. URL query string (shareable but ugly).
2. Cookie (round-trips with every request).
3. `localStorage` (per-browser, no server involvement).

**Chosen**: Option 3. Restored via `GET /api/v1/conversations/{id}` on
mount; wiped on "Start over".

**Reasoning**: Simplest. Session doesn't need to be shareable, and the
server already has the full state — nothing needs to travel except the id.

### D-007 — Human handoff = graph stops

**Problem**: What does "human takes over" actually mean in code? Does the
LLM keep helping? Does automation resume after the human replies?

**Options**:
1. LLM keeps helping alongside the human.
2. LLM stops permanently once handed off. Customer messages go to the
   transcript; operator replies via a live endpoint.
3. Automation resumes if confidence looks OK on a later turn.

**Chosen**: Option 2.

**Reasoning**: Once a person takes over, quietly resuming automation is
exactly the "surprise re-engagement" that erodes trust. The policy hard
override `previously_human_handled` enforces this.

### D-008 — Approve requires text

**Problem**: The original `resolve_review` accepted `outcome=approved`
even for a review item with no drafted reply (complaints escalate before
drafting). What should approve mean without text?

**Options**:
1. Accept approve without text — closes the item silently.
2. Reject approve without text with 422; require `edited` with `final_text`
   for complaints, or use `rejected` to close without delivering.

**Chosen**: Option 2. A regression test pins the 422 response.

**Reasoning**: Approving nothing to send is nonsensical. Force the caller
to pick the honest verb: `edited` (I'm delivering this) or `rejected`
(I'm closing without delivering).

## 2026-08-01

### D-009 — Two stores for the catalog

**Problem**: A customer asks *"do you have a Renzo GX 470?"*. Semantic
search over the CSV returned five semantically-similar Renzos, none of
which was the requested model — a confidently wrong answer.

**Options**:
1. Keep vector-only, filter results by exact brand+model in Python.
2. Postgres for exact structured lookups; Qdrant for fuzzy semantic search.
3. SQLite (local file) instead of Postgres.

**Chosen**: Option 2.

**Reasoning**: A vehicle catalog is a table. Tables live in SQL. Vector
similarity is the wrong tool for an exact lookup, and post-filtering in
Python papers over that with a slower filter. Postgres is already in the
stack. SQLite would work but there's no reason to introduce a fourth
store when three are running.

Structured lookup returns three verdicts: `exact` (yes we stock it),
`did_you_mean` (nearest names in the same brand, `difflib` similarity ≥
0.72), or `not_stocked` (honest "we don't have that"). The generator uses
the verdict to write the reply.

### D-010 — Catalog lookup via a service-local Protocol

**Problem**: `runtime.py` lives in `services/` and must depend on the
Postgres-based `CatalogLookupService` in `infrastructure/persistence/`.
The dependency rule forbids `services` importing `infrastructure`
directly.

**Options**:
1. Move `CatalogLookupService` back to `services/execution/`, live with
   the violation.
2. Define a `CatalogLookup` port in `domain/ports.py`.
3. Define a local `_CatalogLookupPort` Protocol in `runtime.py` — the
   service module depends on shape, not on the concrete class.

**Chosen**: Option 3.

**Reasoning**: A port in `domain/` is the textbook answer, but the port
would be used by exactly one service and not by any other layer. Local
Protocol keeps the coupling visible and the domain uncluttered. If a
second consumer appears, we promote it to `domain/ports.py` then.

### D-011 — Landing / workflow split

**Problem**: The landing page was written for engineers evaluating the
platform, but the audience is walking-in customers and general readers.
The technical detail put them off.

**Options**:
1. Rewrite in place, remove the detail.
2. Move technical content to a separate page, write a short warm landing.

**Chosen**: Option 2. New `/` is short and non-technical. New `/workflow`
inherits the old content and expands it with a storage section, retrieval
funnel stages, and a hard-overrides list.

**Reasoning**: Two audiences with different information needs. Neither is
served well by one page. Split serves both without either sacrificing.

### D-012 — Ten policy documents authored by the assistant

**Problem**: RAG had almost nothing to answer dealer-specific questions
from — six bank PDFs (real, verbatim) and two thin policy stubs.

**Options**:
1. Wait for the business to supply the documents.
2. Author them in-session, clearly labelled as synthetic Velmora content.

**Chosen**: Option 2. Ten documents, ~15,000 words, UAE-shaped, headed
with a `> **Synthetic content.**` disclaimer.

**Reasoning**: The corpus was the primary bottleneck. Waiting produces no
value; authoring produces a working demo. Each document is versioned and
can be replaced with a real one when supplied.
