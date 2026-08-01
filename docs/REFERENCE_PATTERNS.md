# Reference Patterns

**Purpose.** Four GitHub repositories (~250 MB) were supplied as implementation references. They were analysed, the reusable engineering was extracted here, and the repositories were then deleted to keep the workspace clean.

**This document is the permanent record of that analysis.** Nothing below requires the original repositories to be present. Design is reused; code is not copied.

| Repository | Size | Role | Status |
|---|---|---|---|
| `examples-master` (Qdrant official examples) | 92 MB | Hybrid retrieval core | Analysed → deleted |
| `open-webui-main` | 110 MB | Streaming chat UX | Analysed → deleted |
| `langfuse-main` | 45 MB | Observability model + frontend structure | Analysed → deleted |
| `multi-agent-rag-customer-support-main` | 5.5 MB | LangGraph orchestration shape | Analysed → deleted |

A fifth reference, the LangChain "Build a custom RAG agent with LangGraph" documentation export, was **kept** at [`docs/reference/langgraph-agentic-rag.md`](reference/langgraph-agentic-rag.md) — it is 25 KB of directly-applicable API documentation, not a repository.

---

## 1. Qdrant `examples-master` → the retrieval core

**Source:** `fusion-methods/Choosing_a_Fusion_Method.ipynb`
The single most directly applicable artifact supplied. It defines our entire retrieval strategy.

### 1.1 One collection, two named vectors

The naive design — one collection for dense, another for sparse, merged in Python — is wrong. Qdrant holds both vector types on the same point and fuses server-side:

```python
client.create_collection(
    collection_name=COLLECTION,
    vectors_config={
        "dense": models.VectorParams(size=DENSE_DIM, distance=models.Distance.COSINE),
    },
    sparse_vectors_config={
        "bm25": models.SparseVectorParams(modifier=models.Modifier.IDF),
    },
)
```

> **Critical detail:** `modifier=models.Modifier.IDF` is **required**. Without it Qdrant stores raw term frequencies and BM25 scoring is wrong. This single flag is easy to miss and hard to debug.

### 1.2 Server-side fusion

```python
client.query_points(
    collection_name=COLLECTION,
    prefetch=[
        models.Prefetch(query=models.Document(text=q, model=DENSE_MODEL),
                        using="dense", limit=PREFETCH_LIMIT),
        models.Prefetch(query=models.Document(text=q, model=BM25_MODEL,
                                              options={"avg_len": BM25_AVG_LEN}),
                        using="bm25", limit=PREFETCH_LIMIT),
    ],
    query=models.RrfQuery(rrf=models.Rrf()),
    limit=TOP_K,
    with_payload=[...],
)
```

`PREFETCH_LIMIT=100 → TOP_K=10` is the funnel shape. **Recall@100 is the ceiling metric**: a downstream reranker can fix top-10 ordering, but it cannot recover a document the prefetch never returned. Guard recall first, ranking second.

### 1.3 Why not linear score blending

Dense cosine scores are bounded (~0.3–0.7); BM25 scores are unbounded positives (2–20+, and the scale shifts per query). `0.5·dense + 0.5·sparse` lets BM25 dominate by an order of magnitude; pushing `alpha` to either extreme is selection, not fusion. **This is why RRF exists** — it discards magnitudes and fuses ranks:

```
rrf(d) = Σᵢ 1 / (k + rᵢ(d))
```

`k` defaults to **2** in Qdrant (classic literature uses 60). Smaller `k` sharpens the rank-1 advantage; larger `k` smooths it. Tunable since v1.16 via `models.RrfQuery(rrf=models.Rrf(k=...))`.

### 1.4 Benchmarked alternatives (BEIR/SciFact, 5,183 docs, 300 queries)

| Method | nDCG@10 | Recall@100 | MRR@10 |
|---|---|---|---|
| dense only | 0.654 | 0.932 | 0.607 |
| bm25 only | 0.683 | 0.925 | 0.648 |
| **RRF** | **0.723** | **0.958** | **0.681** |
| DBSF | **0.736** | 0.958 | — |
| weighted RRF (1.0, 2.0) | 0.721 | 0.950 | — |

**Adopted:** RRF as the default — strongest no-eval-set option, and it beat both single-retriever baselines on every metric.

**Recorded tuning levers for Module 14**, once our golden set exists:
- **DBSF** led on SciFact (+0.013 nDCG). Worth a run on our corpus — the ordering can flip on different data, so re-benchmark rather than assume.
- **Weighted RRF** via `models.Rrf(weights=[dense_w, bm25_w])`, grid-searched over `(1,3) … (5,1)`. Underperformed plain RRF on SciFact; only adopt if our eval set says otherwise.
- **`FormulaQuery`** layers business ranking on top of a fused result — recency decay, popularity boosts, category multipliers using `$score` and payload fields. Relevant to us for boosting in-stock vehicles and recent price lists. Note the notebook's warning: writing `0.7*$score[0] + 0.3*$score[1]` over *raw* retriever scores reintroduces the exact scale problem RRF solves. Only apply formulas over already-fused scores.

### 1.5 Diagnostics worth keeping

If hybrid lands materially below either single-retriever baseline, the usual causes are: `PREFETCH_LIMIT` too small, `avg_len` mismatch on BM25, or low diversity between retrievers (both surfacing the same documents).

**Applied in:** Module 5 (`infrastructure/vectorstore/`), Module 14 (evaluation).

---

## 2. `multi-agent-rag-customer-support-main` → orchestration shape

The closest architectural sibling: LangGraph + Qdrant + customer support, structured as `core/` + `services/` + a separate `vectorizer/` ingestion service.

### 2.1 The reducer-based stack — our most important borrowing

```python
def update_dialog_stack(left: list[str], right: Optional[str]) -> list[str]:
    """Push or pop the dialog state stack."""
    if right is None:      return left
    if right == "pop":     return left[:-1]
    return left + [right]

class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    dialog_state: Annotated[list[Literal[...]], update_dialog_stack]
```

State evolution is expressed as a **reducer**, not as mutation scattered across nodes. A node returns a small delta; the reducer owns how it merges.

**We generalise this into the intent-queue reducer** — merge-by-category, where a new turn updates an existing intent in place and appends genuinely new ones, but *cannot* drop an unresolved intent. This is the mechanism that makes "never lose an intent" a structural guarantee rather than a hope about prompt behaviour. (Module 8.)

### 2.2 Safe vs sensitive tool split

Each assistant exposes two tool lists. Safe tools execute freely; sensitive tools pause for confirmation before execution:

```python
safe_toolnames = [t.name for t in update_flight_safe_tools]
if all(tc["name"] in safe_toolnames for tc in tool_calls):
    return "update_flight_safe_tools"
return "update_flight_sensitive_tools"
```

**Adopted directly** as our human-in-the-loop boundary. Reads (EMI calculation, catalog lookup, valuation estimate) are safe; writes (book a test-drive slot, create a CRM lead, notify a department, send a customer message) are sensitive and pass through `escalate_human` / approval when confidence is below threshold. (Module 7c, Module 8.)

### 2.3 Escalation as structured output

```python
class CompleteOrEscalate(BaseModel):
    """Mark the task complete or hand control back to the main assistant."""
    cancel: bool = True
    reason: str
```

Handing control back is a **typed tool call**, not free-text the router has to parse. Adopted for our escalation signal.

### 2.4 Structural patterns adopted

- `create_tool_node_with_fallback(...)` — every tool node wraps a fallback path so a tool exception becomes a handled `ToolMessage` instead of a crashed graph run.
- Separate **`vectorizer/` ingestion service** with its own `core/`, `embeddings/`, `vectordb/` — ingestion is a distinct deployable, not a script inside the API. Adopted as `workers/ingestion/` with its own Compose profile.
- `RecursiveCharacterTextSplitter(separators=["\n\n", "\n", " ", ""])` as the chunking base — we extend it with page-awareness so PDF chunks retain `page` for UI highlighting.

### 2.5 Anti-patterns explicitly rejected

| Found | Problem | Our approach |
|---|---|---|
| `llm = ChatOpenAI(...)` at module import | Untestable, unswappable, requires a key just to import | LLM behind a port, injected via DI container (Module 3, 6) |
| `class Config` of bare `environ.get` strings — `LIMIT_ROWS: int = environ.get("LIMIT_ROWS", "100")` | Annotated `int`, actually a `str`. Silent type lie | `pydantic-settings` with real validation |
| Retry by appending `("user", "Respond with a real output.")` to state | Mutates conversation history to coerce the model | Structured output with schema validation + bounded retry, history untouched |
| `if not self.client.get_collection(...)` | Raises on missing collection rather than returning falsy — the guard never works as written | `client.collection_exists(name)` |
| `openai.Embedding.create` per chunk in a loop | No batching; slow and expensive at corpus scale | Batched embedding calls |

**Applied in:** Modules 3, 5, 6, 7c, 8.

---

## 3. `langfuse-main` → observability model & frontend structure

### 3.1 Wide events over fragmented telemetry

From `.agents/ARCHITECTURE_PRINCIPLES.md` — a genuinely valuable design input:

- Model **observations** as the primary analytical unit; a trace is a correlation handle, not the only entry point.
- Prefer **wide, richly attributed events** over fragmented metrics/logs/traces that must be reconstructed later.
- **Preserve high-cardinality context** so you can slice and debug unknown unknowns without predefining every future question.
- Favour **immutable, append-oriented** records for high-volume telemetry; update-heavy designs force read-time deduplication.
- Keep list/dashboard views on **compact representations**; fetch large payloads only for focused detail views.
- Treat **cost and operational simplicity as architectural constraints** — extra databases, queues and materialized views must earn their long-term burden.

**Adopted:** one wide `Span` row per graph node execution, carrying `trace_id, node, layer, status, latency_ms, tokens_in/out, cost_usd, model, attributes(jsonb)`. This single decision is what makes the admin trace view, the cost dashboard and the confidence breakdown all fall out of one table instead of three subsystems.

### 3.2 Feature-sliced frontend

`web/src/features/<feature>/` with co-located components, server logic, hooks and types — `annotation-queues`, `evals`, `dashboard`, `filters`, `models`, `comments`. Mirrored as `frontend/src/features/{chat,provenance,workflow-graph,human-queue,traces,metrics}`.

Two features map almost one-to-one onto ours: `annotation-queues` ≈ our human review queue, `evals` ≈ our evaluation service.

### 3.3 Deliberately not adopted

- **ClickHouse for telemetry.** Correct at Langfuse's scale, wrong at ours (~100 inquiries/day). Adopting it would violate their own principle that extra databases must earn their operational burden. Postgres, with a documented ceiling around 10⁶ spans.
- **tRPC** — we need a language-agnostic OpenAPI contract between a Python backend and a TypeScript frontend.
- **EE / entitlements split** — no commercial tiering here.

**Applied in:** Modules 3 (span table), 10 (frontend structure), 13 (admin dashboard).

---

## 4. `open-webui-main` → UX reference only

**Svelte, not Next.js — zero code reuse.** Retained as interaction patterns:

- Token-by-token streaming with a visible in-flight indicator, so perceived latency tracks first-token rather than completion.
- Collapsible citation blocks beneath an answer — the default view stays clean, provenance is one click away. Directly informs our expandable Sources panel.
- Model-selector affordance showing which model answered. We extend this: model, tier, confidence, cost and latency badges per message.

**Applied in:** Module 12.

---

## 5. LangChain LangGraph RAG documentation

Kept in full at [`docs/reference/langgraph-agentic-rag.md`](reference/langgraph-agentic-rag.md).

- `StateGraph` + `add_conditional_edges` for retrieve-or-answer branching.
- Retriever exposed as a `@tool` so the model decides when to search.
- **Grade-documents → rewrite-question** self-correction loop.

**Adaptation:** we use document grading as a *retrieval confidence signal* feeding the confidence engine — not as an unbounded rewrite loop. Rewrites are bounded to one retry to protect the latency budget; a second failure escalates rather than spinning.

**Applied in:** Modules 5, 7b, 8.

---

## Traceability

| Pattern | Source | Module |
|---|---|---|
| Named vectors `dense` + `bm25`, IDF modifier | Qdrant fusion notebook | 5 |
| Server-side RRF, prefetch 100 → top 10 | Qdrant fusion notebook | 5 |
| DBSF / weighted-RRF / FormulaQuery as tuning levers | Qdrant fusion notebook | 14 |
| Recall@100 as the prefetch ceiling metric | Qdrant fusion notebook | 14 |
| Reducer-based state → **intent-queue reducer** | multi-agent-rag `core/state.py` | 8 |
| Safe vs sensitive tools → HITL boundary | multi-agent-rag routing | 7c, 8 |
| Escalation as typed structured output | multi-agent-rag `CompleteOrEscalate` | 7b, 8 |
| Tool-node fallback wrapper | multi-agent-rag `utils.py` | 8 |
| Ingestion as a separate deployable | multi-agent-rag `vectorizer/` | 5 |
| Wide-event spans | Langfuse architecture principles | 3, 13 |
| Feature-sliced frontend | Langfuse `web/src/features/` | 10–13 |
| Streaming + collapsible citations | Open-WebUI | 12 |
| Conditional edges, document grading | LangGraph docs | 5, 7b, 8 |
