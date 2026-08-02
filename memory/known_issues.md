# Known issues

Update whenever a bug is discovered, a workaround established, or a
resolved issue removed.

## Missing capabilities (not bugs — planned gaps)

### Module 14 not built — no evaluation service, no golden set
- **Impact**: Every quality metric named in the spec (intent accuracy,
  retrieval recall@100, hallucination rate, faithfulness) is unmeasured.
  There is no way to know whether prompt or model changes regress quality.
- **Effort**: Substantial (author ~40 golden test cases, build the
  evaluator, add CI gates). See `future_tasks.md`.
- **Workaround**: None. Manual testing only.

### Admin workflow graph not animated
- **Impact**: The operations view shows metrics and the queue but doesn't
  visualise the live graph as it runs.
- **What's there**: SSE endpoint (`GET /api/v1/conversations/{id}/stream`)
  emits node events. Span data is already exposed in the trace endpoint.
- **What's missing**: React Flow diagram on the frontend to consume it.
- **Effort**: Small (a day or two).

### Conversation state persistence is in-memory
- **Impact**: All conversations, spans and human-queue items are lost on
  backend restart.
- **What's there**: SQLAlchemy async engine, `VehicleRow` table, migration
  hook via `ensure_schema`. The plumbing exists.
- **What's missing**: ORM models and repositories for
  `ConversationState`, `Span`, `HumanReviewItem`, `ExecutionAction`.
  Wiring in the `MemoryService`.
- **Effort**: Medium (a day or so).

### No auth enforcement
- **Impact**: Every endpoint is publicly reachable during local dev. Fine
  for demo, not for anything real.
- **What's there**: `JWT_SECRET`, `JWT_ALGORITHM`, `JWT_EXPIRY_MINUTES` in
  settings. `pyjwt` in dependencies.
- **What's missing**: Middleware, role-claim decoding, per-route guards,
  a seed script for demo users.
- **Effort**: Medium (half a day).

### Provenance UI doesn't open source PDFs
- **Impact**: A user clicking a chunk in the customer chat sees the text
  but cannot open the original document at the highlighted page.
- **What's there**: Every chunk carries `page` and `source` metadata.
- **What's missing**: A document viewer route serving the PDFs plus a
  scroll-to-page mechanism.
- **Effort**: Small.

## Real limitations (in effect)

### Reranker is English-only
- **Symptom**: Arabic queries would get scrambled by the `ms-marco`
  cross-encoder.
- **Workaround (active)**: `_is_non_latin(query)` bypasses the reranker;
  RRF fusion order is preserved.
- **Proper fix**: Swap for a multilingual cross-encoder. Deferred as a
  future task; the workaround is not degrading quality on English and
  the RRF-only order on Arabic is measurably usable.

### Mock provider is keyword-based
- **Symptom**: Multi-token model names and colloquial phrasing fall
  through gaps in the keyword regex.
- **Workaround (active)**: Documented as a mock limitation. The user is
  encouraged to switch to `LLM_PROVIDER=openai` for real quality.
- **Proper fix**: None planned. The mock is a test/demo aid, not a
  product.

### Grounding validator is lexical
- **Symptom**: A drafted answer that paraphrases the evidence heavily
  might trip "unsupported" even when the number is right.
- **Workaround (active)**: Numeric claims are the hard check (any figure
  must appear verbatim in tool results or retrieved text). Qualitative
  claims tolerate a 25% content-word overlap threshold.
- **Proper fix**: Better claim decomposition, cross-encoder-based support
  scoring. Deferred to `future_tasks.md`.

## Recently resolved (kept for reference)

### FIXED 2026-07-31 — Multi-turn reducer crash
- **Symptom**: Second inquiry on the same conversation raised
  `TypeError: can only concatenate list (not "tuple") to list` in
  LangGraph's binop channel.
- **Root cause**: LangGraph's checkpointer serialised tuples as lists;
  the next turn's `operator.add` reducer tried `list + tuple`.
- **Fix**: `concat_sequence` reducer normalises both sides to tuple
  before appending. Regression test in `test_graph_end_to_end.py`.

### FIXED 2026-07-31 — Clarification loop
- **Symptom**: User answered "which vehicle?" with a brand+model but the
  system asked the same question again.
- **Root cause**: `vehicle_reference` slot was checked literally, not
  aliased to brand/model.
- **Fix**: `_SLOT_ALIASES` in `planning/planner.py`. `_is_slot_filled`
  helper honours the aliases.

### FIXED 2026-07-31 — Angry customer interrogated
- **Symptom**: A message like "Terrible service, get me a manager" hit
  clarification (asking which vehicle) before reaching escalation.
- **Root cause**: The clarify gate ran before the decision layer's hard
  overrides.
- **Fix**: `_needs_a_person_now(state)` in `graph/builder.py` — if the
  intent's `force_human` flag is set or sentiment demands a human,
  bypass clarify entirely.

### FIXED 2026-07-31 — Frontend CORS mismatch
- **Symptom**: "Failed to fetch http://localhost:8080" in the browser
  when the frontend was reached via the Network URL.
- **Root cause**: Only `localhost:3000` and `localhost:3010` were in the
  allow-list. Network URL uses the LAN IP, which the browser sends as the
  Origin.
- **Fix**: `CORS_ORIGINS` is configurable in `.env`. `Settings.allowed_origins`
  auto-adds the `127.0.0.1` variants of any `localhost` origin. LAN IPs
  must be added manually — a deliberate choice not to open the API to the
  Wi-Fi network by default.

### FIXED 2026-08-01 — "We don't stock that" replies
- **Symptom**: Customer asks about "Renzo GX 470" (not in catalog);
  system returned five semantically-similar Renzos as if they were the
  answer.
- **Root cause**: Vector similarity is the wrong tool for exact model
  lookup.
- **Fix**: `CatalogLookupService` (Postgres) runs before generation, with
  three verdicts. EMI tool returns `declined` when the customer's model
  isn't stocked, so the generator writes an honest reply.

### FIXED 2026-08-01 — Clarification-answer extraction on short fragments
- **Symptom**: Two-word replies like "GX 470" to "which model?" scored
  entity=0.00 and looped.
- **Root cause**: The LLM extractor had no context for what the fragment
  was answering.
- **Fix**: `previous_awaiting` field on graph state. Understanding prompts
  wrap the message with an instruction telling the LLM what slot was
  asked about.

## Environment notes (not code issues)

### Port 8000 held by unrelated app
- **Situation**: On the developer's machine, port 8000 is bound by
  `bidpilot.dev` (an unrelated project).
- **Consequence**: We use `API_PORT=8080` throughout. `.env` reflects this.

### Docker Desktop occasionally goes down
- **Situation**: The user's Docker Desktop was closed at end of the
  last session.
- **Consequence**: Data plane needs `python tasks.py up` before backend
  startup — Postgres and Qdrant are unreachable otherwise.
- **Effect on tests**: 199 backend tests still pass because both
  retrieval and catalog-lookup degrade gracefully when their backends are
  down.

## 2026-08-02 — Provider and quota gotchas

### No automatic failover between LLM providers
`LLM_PROVIDER` selects one provider at startup. An OpenAI outage does not
fall through to Anthropic — it escalates conversations to humans. Treat
Anthropic as a manual switch, not redundancy. Switching requires both
`LLM_PROVIDER=anthropic` *and* `ANTHROPIC_API_KEY`; setting only the first
makes the container **refuse to boot** (`Settings._validate` raises), which
is deliberate fail-fast but means a half-done failover is a full outage.

### New Gemini API keys get zero free-tier quota on gemini-2.0-flash
`limit: 0` for `generate_content_free_tier_requests` — every call 429s
immediately. Not transient. Use `gemini-2.5-flash`, which is verified
working; this is now the default in `settings.py`. `gemini-2.5-flash-lite`
returns 404 on this key. If clarifications suddenly go back to sounding
templated, check the logs for `clarification_phrasing_failed` before
suspecting the code — quota exhaustion looks identical to a bug from the
outside, except the reply is still correct.

### Vendor 400s cannot be caught by the mock or by any offline test
Two models have now shipped that reject `temperature`: `gpt-5-mini` and
the `claude-*-5` family. Both were found only by calling a live key. When
changing a configured model ID, run a live smoke call before deploying —
`tests/unit/test_providers.py` pins the *detection*, but only a real call
proves the model ID itself resolves.

### Reasoning models break constrained JSON on a latency budget
Two models have now failed the clarification call the same way: Gemini 2.5
Flash (thinking on by default, charged against the reply's output budget)
and `openai/gpt-oss-20b` on Groq (`json_validate_failed` — "max completion
tokens reached before generating a valid document", 3/6 runs). Before using
any reasoning-capable model for short constrained JSON, disable thinking or
raise `max_tokens` well past what the reply itself needs.

### Cloud Run image must pre-cache FastEmbed weights
If `retrieve` starts failing with "Could not load model ... from any
source" and ~39s latency, the Dockerfile's model pre-cache layer has been
dropped or `FASTEMBED_CACHE_PATH` no longer matches between build and
runtime. Retrieval degrading to nothing is silent — the node catches the
exception and the conversation continues without evidence.

### `update-traffic --to-revisions` silently pins the service off "latest"
Cloud Run services default to routing traffic to `LATEST`, so a plain
`gcloud run deploy` goes live immediately. But running
`gcloud run services update-traffic --to-revisions=<name>=100` — as the
cleanup step after a `--no-traffic --tag` test does — switches the service
into *manual pinning*. From then on every deploy builds and creates a
revision successfully while serving **0% of traffic**, and the only hint is
one easily-missed line: "is serving 0 percent of traffic."

This happened on 2026-08-02: a full day of work deployed cleanly and none
of it was live.

**Check** after any deploy:
```
gcloud run services describe alto-orchestrator-backend --region=us-central1 --format="value(status.traffic)"
```
If it names a specific revision rather than `LATEST`, traffic is pinned.

**Fix / restore auto-routing**:
```
gcloud run services update-traffic alto-orchestrator-backend --region=us-central1 --to-latest
```

Prefer `--to-latest` over `--to-revisions` whenever cleaning up a tagged
test revision, so the service returns to its default behaviour.
