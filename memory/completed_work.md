# Completed work

Chronological log. Never truncate history — new work is appended at the
bottom.

## 2026-07-30 — Modules 1–14 initial build

Fourteen of sixteen planned modules landed in the initial build. Full
history in `docs/spec/`; brief summary of each module below.

### Module 1 — Workspace scaffold & cleanup
- Extracted engineering patterns from four supplied reference repos
  (`examples-master`, `langfuse-main`, `multi-agent-rag-customer-support-main`,
  `open-webui-main`) into `docs/REFERENCE_PATTERNS.md`.
- Deleted the four repos (~250 MB) after the extraction.
- Scaffolded the `alto-orchestrator/` directory tree.
- Relocated PDFs to `data/knowledge/finance/` with consistent naming,
  CSV to `data/catalog/vehicles.csv`, specs to `docs/spec/`.
- Wrote `docker-compose.yml` (Postgres 16, Redis 7, Qdrant v1.17),
  `tasks.py` cross-platform runner, Makefile delegator, `.env.example`,
  `.gitignore`, `README.md`.
- Verified Qdrant hybrid RRF fusion API works end-to-end against the live
  container.

### Module 2 — Domain core
- Pure-Python domain layer: `entities.py`, `value_objects.py`, `enums.py`,
  `ports.py`, `policies/` with four YAML files + typed loaders.
- Intent-queue reducer (`IntentQueue.merge`) — merges by category,
  preserves rule-engine fields, never drops unresolved intents.
- Architecture fitness test (`tests/unit/test_architecture.py`) enforces
  the dependency rule.
- All finance policy figures grounded in the ingested UAE bank documents
  (verified CBUAE limits: 80% max LTV, 60-month max tenure, reducing
  balance).

### Module 3 — Infrastructure & DI
- Typed `Settings` via `pydantic-settings`. Cross-field validation refuses
  to boot in production with a mock provider or default JWT secret.
- `structlog` logging with PII redaction and per-mode renderer.
- `AltoError` hierarchy + FastAPI exception handler.
- `Container` dataclass as the composition root (moved from `core/` to
  `composition/` after the architecture fitness test caught it violating
  the layer rule).

### Module 4 — Language layer
- Deterministic normaliser (Arabic diacritics, letter unification,
  Arabic-Indic digits, Arabizi lexicon, PII redaction).
- Script-ratio language detector + `LanguageProfile`.
- 100 table-driven test cases across EN / AR / mixed / Arabizi / misspelled.
- Fix: Arabizi detection excluded trailing-digit patterns to avoid reading
  "Renzo S5" as transliterated Arabic.

### Module 5 — Ingestion & hybrid retrieval
- One-shot ingestion worker.
- Three Qdrant collections, each with dense (multilingual MiniLM 384d) +
  BM25 sparse (IDF modifier — required for correct BM25 scoring).
- Server-side RRF fusion, then local cross-encoder rerank.
- Full per-stage score capture on `RetrievedChunk`.
- Fix: reranking skipped for Arabic queries — the English-only cross-encoder
  returned uniformly negative scores that scrambled a correct fusion order.
- Fix: chunk deduplication + minimum-length filter after PDF extraction
  produced near-duplicate fragments.

### Module 6 — LLM providers & model router
- `OpenAIProvider`, `AnthropicProvider`, `MockProvider` — all satisfy the
  same port. Vendor SDKs imported lazily inside adapters so a mock-only
  install doesn't require them.
- Per-token cost registry with fallback to the highest rate on unknown
  models.
- `BudgetGuard` demotes premium requests to fast when the daily cap is
  reached (rather than failing them).

### Module 7a — Understanding layer
- `UnderstandingEngine` calling `complete_structured` for intent, entity
  and sentiment extraction.
- Fast-tier by default.

### Module 7b — Planning & Decision layers
- `enrich`, `recompute_missing_slots`, `build_plan` — pure functions of
  policy and state.
- Slot alias: `vehicle_reference` requirement is satisfied by any of
  `{vehicle_reference, new_vehicle_brand, new_vehicle_model, old_vehicle_brand, old_vehicle_model}`.
- Six-signal confidence engine with `evaluate` and `zero_confidence`.
- `route` function with hard overrides that fire before the score.

### Module 7c — Execution layer
- Deterministic EMI (reducing balance, CBUAE-limited).
- Deterministic trade-in valuation (depreciation curve + mileage + condition,
  authored synthetic model).
- In-process `Actuator` with idempotency keys per (conversation, intent, action).
- Grounding validator that checks numeric claims against retrieved chunks
  and tool results, and blocks answers that quote unsupported figures.

### Module 8 — LangGraph orchestrator
- `GraphState` TypedDict with three reducers: `merge_intents`,
  `concat_sequence`, `take_last`.
- 17 nodes, layered fan-out from `detect_language`.
- Fix: node renamed from `plan` to `build_plan` — LangGraph forbids node
  names that collide with state keys.
- Fix: `concat_sequence` reducer tolerates tuple↔list round-trip through
  the checkpointer. Regression test pins this.
- Fix: `_needs_a_person_now` bypasses the clarify gate — an angry customer
  with a missing slot is escalated, not interrogated.

### Module 9 — FastAPI surface
- All v1 routers, DTOs mirroring domain shapes but decoupled.
- SSE streaming of node events + final result.
- CORS configurable via `CORS_ORIGINS` env var with automatic `127.0.0.1`
  aliasing.

### Module 10 — Frontend foundation
- Next.js 15 + React 19 + strict TypeScript + Tailwind.
- Swiss/International design tokens in `tailwind.config.ts`.
- Typed `api` client in `src/lib/api.ts`.

### Module 11 — Swiss landing page (superseded 2026-08-01)
- Original technical landing shipped, later moved to `/workflow`.

### Module 12 — Customer chat & provenance UI
- Streaming turn display with confidence, model, latency, tokens badges.
- Expandable Sources panel — every chunk clickable, all four scores
  (dense, BM25, RRF, rerank) visible.
- Bilingual RTL rendering via `dir` attribute + `[dir="rtl"]` selector.
- Session persistence in localStorage (later addition).

### Module 13 — Admin dashboard (partial)
- Live queue with headline metrics, layer/node latency, human queue.
- Six-signal confidence bars with weakest signal marked in red.
- Approve/reassign/dismiss actions initially, expanded 2026-07-31.
- **Not built**: animated React Flow workflow graph (SSE endpoint + span
  data exist to drive it, the visualisation itself is deferred).

### Module 14 — Evaluation & hardening
- **Not built.** No golden set, no evaluation service, no CI quality gates.
- Every quality metric named in the spec (intent accuracy, retrieval
  recall/precision, hallucination rate, faithfulness) is unmeasured.

## 2026-07-31 — Iteration on live testing

Real bugs surfaced by the user driving the browser; regression tests
landed with each fix.

- **Session persistence.** `conversationId` moved from React state to
  `localStorage`, restored via `GET /api/v1/conversations/{id}` on mount.
  Navigating between `/chat` and `/admin` no longer starts a fresh session.
- **Interactive human handoff.**
  - `MemoryService.append_turn` and `mark_human_handled`. Transcript
    persists across turns.
  - `POST /api/v1/inquiries` on a handed-off conversation now skips the
    graph and records the customer message without re-engaging automation.
  - `POST /api/v1/admin/human-queue/{id}/resolve`: `approved` and `edited`
    deliver the text to the transcript. `reassigned` requires a target
    department. `rejected` closes without delivering.
  - `POST /api/v1/admin/conversations/{id}/reply` — live operator message,
    appended to transcript, no queue round-trip.
- **Admin review UI rebuilt.** Full transcript rendering, textarea for
  custom reply, department dropdown for reassignment, live follow-up
  input. Buttons now do what they say.
- **Slot alias.** Answering "which vehicle?" with a brand+model now
  satisfies `vehicle_reference`, breaking the clarification loop.
- **Multi-turn resume fix.** Reducer for `entities` and `actions` moved
  from `operator.add` to `concat_sequence`, which tolerates
  tuple↔list checkpoint round-trips.
- **CORS auto-expansion.** `Settings.allowed_origins` computes
  `127.0.0.1` aliases automatically.
- **Provider switch.** Confirmed OpenAI provider works end-to-end;
  documented in README.

## 2026-08-01 — Corpus expansion + structured catalog + landing/workflow split

Substantial architectural work — the "everything is breaking" moment
addressed structurally.

### Ten authored policy documents (`data/knowledge/policies/`)
- `00-about-alto-motors.md` — company profile, brands, values.
- `01-showroom-hours-and-visits.md` — weekly + Ramadan hours, walk-in
  procedure, parking, accessibility.
- `02-test-drive-procedure.md` — replaces original stub. 45-min slots,
  eligibility, documents, insurance, extended and overnight rules.
- `03-trade-in-inspection.md` — replaces original stub. Inspection order,
  documents required, indicative-vs-binding language.
- `04-financing-partners.md` — Alto's view on the six banks (not the
  numbers, which live in the bank docs).
- `05-vehicle-warranty-and-servicing.md` — 3yr/100k warranty, service
  intervals, first-service voucher, courtesy vehicle policy.
- `06-delivery-and-registration.md` — RTA registration, plates, insurance,
  delivery timeframes.
- `07-brand-guides.md` — Karva/Renzo positioning, model families,
  cross-brand test drive guidance.
- `08-after-sales-and-complaints.md` — complaint routing, response
  commitments, common issues.
- `09-frequently-asked-questions.md` — top-20 questions in customer
  phrasing (high-yield for RAG).

### Postgres catalog + structured lookup
- New `VehicleRow` ORM model in `infrastructure/persistence/models.py`.
- `CatalogLookupService` in `infrastructure/persistence/catalog_repository.py`
  with three verdicts: `exact`, `did_you_mean`, `not_stocked`.
  `difflib`-based fuzzy matching with 0.72 similarity floor.
- Ingestion worker gained `populate_postgres_catalog` step (opt-out with
  `--skip-postgres`).
- `ToolRunner` uses structured lookup when available, falls back to the
  vector `best_match` if Postgres is unavailable. Wrapped in try/except so
  a Postgres blip degrades gracefully.
- EMI tool returns `declined` with a reason (from `lookup.explain()`) when
  the customer names a model not in the catalog — no more instalment
  quotes against semantically-similar cars.

### Last-asked slot context
- `GraphState.previous_awaiting` field.
- `UnderstandingEngine.discover_intents` and `.extract_entities` accept
  `previous_awaiting` and wrap the user message with an instruction:
  *"[The assistant just asked the customer for their <slot>...]"*.
- API layer computes `previous_awaiting` from the prior conversation's
  first unresolved missing slot.

### Landing / workflow split
- `frontend/src/app/page.tsx` rewritten as a **short, non-technical**
  landing: hero, two brand tiles, four typical customer questions, CTA.
- `frontend/src/app/workflow/page.tsx` created with the previous
  architecture content **expanded**: four cognitive layers, six signals,
  hard overrides list, storage layout, retrieval funnel described stage
  by stage, handoff-not-handover section.

### Tests and gates
- 199 backend tests pass (added regression tests for clarification
  advancement, multi-turn resume, complaint escalation, live operator
  reply, edited-reply delivery, reassign target requirement).
- ruff clean, mypy strict clean.
- Frontend builds clean under strict TypeScript.

## 2026-08-01 — Persistent memory system

- Created `memory/` directory and this file structure.
- `CLAUDE.md` at project root as the session entry point.

## 2026-08-01 — Four production bugs found by user testing

Live testing surfaced four real defects. All fixed.

### Intent taxonomy gap for non-vehicle questions
- **Symptom**: "What are your Saturday hours?" → "Which vehicle are you asking about?"
- **Root cause**: no `general_info` or `small_talk` intent category. Everything not matching a vehicle-adjacent intent fell through to `unclear_needs_clarification`, whose required slot is `vehicle_reference` — so the planner asked about a vehicle for questions that had no vehicle.
- **Fix**:
  - New `IntentCategory.GENERAL_INFO` (hours, location, dealership info) and `IntentCategory.SMALL_TALK` (greetings, thanks, goodbye). Neither has required slots.
  - Rules added to `intents.yaml` (`general_info` priority 45, `small_talk` priority 20).
  - `ACTIONS` in `planner.py`, `INTENT_KEYWORDS` in mock provider, `COLLECTIONS_FOR_INTENT` in retriever (small talk gets no retrieval).
  - LLM prompt rewritten to enumerate all nine categories with examples of when each fires.

### GraphRecursionError on grounding retry
- **Symptom**: `langgraph.errors.GraphRecursionError: Recursion limit of 25 reached`. Random 500s.
- **Root cause**: `route_after_grounding` checked `state.get("retry_count", 0) < MAX_GROUNDING_RETRIES` but nothing ever incremented `retry_count`. A soft grounding failure looped forever until LangGraph killed the run.
- **Fix**: `validate` node bumps `retry_count` when the report fails. First failure retries once, second failure escalates.

### Numeric-date extraction fell through
- **Symptom**: Customer said "08-08-2026, time:14:00" — extractor recorded no `preferred_date`, planner asked for the date again.
- **Root cause**: The entity prompt described day names but not formatted dates.
- **Fix**: Prompt now explicitly lists accepted date and time formats — day names, ISO dates, DD-MM-YYYY, "next week", morning/afternoon, 14:00 / 2 pm.

### Retrieval-signal zero for intents that don't need retrieval
- **Symptom**: Even after adding `small_talk`, empty chunks scored `retrieval=0.0`, dragging the decision score down.
- **Root cause**: `score_retrieval` returned 0 unconditionally on no chunks.
- **Fix**: When every open intent is in `_INTENTS_WITHOUT_RETRIEVAL` (`small_talk`, `complaint_escalation`), empty chunks score `1.0`. Otherwise 0 as before.

### Test updated
`test_an_underspecified_request_never_reaches_the_decision_layer` replaced with `test_a_vague_availability_question_asks_for_the_vehicle` — the old assertion is now provider-dependent (with the better prompt, an under-specified question can legitimately reach the decision layer if the LLM classifies it richly enough). The new test uses *"is this still available?"* which unambiguously requires a vehicle reference.

## 2026-08-01 — Test-drive calendar booking + address + operator chat UI

### Address across the corpus
- Real dealership address plugged in: **Legend Motors, Showroom #46, Ras Al Khor**.
- Files updated: `00-about-alto-motors.md`, `09-frequently-asked-questions.md`, and the booking confirmation string in `routes.py`. Requires re-ingestion for the change to appear in retrieval.

### 2-hour test-drive slots (was 45 minutes)
- `02-test-drive-procedure.md` — slots are now 2 hours, covering the drive plus the follow-up conversation with a consultant.

### Appointment service (new)
- `backend/app/services/execution/appointments.py` — deterministic slot generator plus in-memory booking store.
- `_TEST_DRIVE_WINDOWS` per weekday (Mon–Thu 09–19, Fri 14–20, Sat 10–20, Sun 10–18).
- Slots are 2 hours, start on the hour, filter past and taken slots server-side so the client cannot pick something invalid.
- Booking encodes the slot start time into the slot id (`slot_YYYYMMDDTHHMM`), so booking is stateless read-through.
- Race guarded by lookup-then-write in `book_slot`, raising `SlotUnavailable` on collision.

### API endpoints
- `GET /api/v1/appointments/slots?days=14` — available slots for the customer's calendar.
- `POST /api/v1/appointments/book` — books a slot, appends confirmation to transcript, returns booking record.
- `GET /api/v1/admin/appointments` — bookings shown in the operator dashboard. Marks each as notified when read.

### Booking-ready detection
- New helper `_should_show_calendar` in `routes.py`. When the primary intent is `test_drive_booking`, the vehicle is fully specified, and only date/time is missing, the API replaces the assistant's text-question with `awaiting=test_drive_slot` — the frontend renders the calendar instead of a wall of text.

### Frontend: `<CalendarPicker>`
- `frontend/src/components/CalendarPicker.tsx` — inline calendar rendered under the last assistant turn when `response.awaiting === "test_drive_slot"`.
- Swiss grid, grouped by day, tabular time labels. Unavailable slots are struck through.
- Confirm button posts to the booking endpoint; on success, the confirmation lands as a new assistant turn.

### Operator UI rebuilt as a real chat window
- Left column: `<div ref={transcriptRef}>` with `overflow-y-auto` and a fixed height. Auto-scrolls to bottom on new turns.
- Reply input pinned to the bottom of the same panel, Enter-to-send.
- Right column: confidence bars, rationale, close/reassign actions.
- First reply on an open review uses `edited` (delivers the operator's text). Subsequent replies use the live `humanReply` endpoint.
- Draft is now a collapsible `<details>` with a "Use this draft" button that copies it into the reply input.

### Recent bookings panel
- Right sidebar in `/admin` shows the five most recent bookings with vehicle, day, slot, and conversation id.
- "Bookings" replaces "Escalation rate" in the headline metrics tile.

## 2026-08-01 — Calendar redesign + timezone fix

### Timezone consistency (was: 10:00 in chat, 15:30 PM in operator view)
- All slot generation happens in `Asia/Dubai` timezone via `zoneinfo.ZoneInfo`.
- Backend pre-formats every string a UI would display: `day_label`, `time_label`, `slot_label`, `iso_date`, `day_short`, `day_number`, `month_short`. Frontend renders them verbatim, never reformats a timestamp.
- Booking DTO carries `slot_label` — the single string the admin dashboard, calendar footer, and confirmation message all use.
- Added `tzdata` to `pyproject.toml`. Windows ships no IANA zone database, so a fresh clone was hitting `ZoneInfoNotFoundError` on test collection.
- `formatSlot()` helper removed from `frontend/src/app/admin/page.tsx` — the whole point of the fix is that the client never formats a slot.

### Handoff re-enqueue (fixes "customer sees colleague, operator queue empty")
- **Symptom**: After a review was resolved, subsequent customer messages
  ran the "human_handled" short-circuit path in `POST /inquiries` — the
  customer saw *"a member of our team is handling this"* but the operator
  dashboard queue was empty. Nowhere for the operator to see or reply.
- **Fix**: `HumanReviewQueue.enqueue_customer_followup(conversation)` adds
  a single card per conversation (idempotent via `open_for(conversation_id)`
  check) with reason `AWAITING_OPERATOR_REPLY`. `POST /inquiries` invokes
  it whenever a customer message arrives on a handed-off conversation. One
  card per conversation, not per message — subsequent messages just land
  in the same card's transcript.
- **New enum**: `HumanReviewReason.AWAITING_OPERATOR_REPLY`.

### Generator got stock corporate filler on clarification follow-ups (fixed)
- **Symptom**: Customer said "I want to trade in my old Karva SUV and also
  check financing for a Renzo Discovery" → assistant asked "which brand?".
  Customer answered "Renzo". Assistant replied *"Hello, Thank you for
  reaching out to us. Could you please provide more details…"* — total
  loss of the three open intents and the specific answer.
- **Root cause**: `_rebuild_conversation` in `graph/nodes.py` built a
  `ConversationState` without setting `transcript`. The
  `ResponseGenerator._build_context` reads
  `conversation.transcript[-1].text` — with an empty transcript, the LLM
  received intent labels and retrieved chunks but no idea what the
  customer had actually said. That is exactly the shape of prompt that
  produces stock filler.
- **Fix (state)**: added `transcript: Annotated[tuple, take_last]` to
  `GraphState`; `initial_state` accepts it; `submit_inquiry` loads it
  from memory after appending the customer message; `_rebuild_conversation`
  passes it through.
- **Fix (context)**: `_build_context` now shows the last 8 turns as
  "Conversation so far", enumerates each open intent with *what specific
  slot is still missing*, and lists every entity the customer has already
  supplied. The generator can now say "Great, Renzo — which model?" rather
  than "please provide more details".
- **Fix (prompt)**: `ResponseGenerator.SYSTEM` explicitly forbids "please
  provide more details" as a whole reply, forbids "Thank you for reaching
  out" / "Best regards", and instructs the model to acknowledge the
  clarification answer in one short phrase before continuing.
- **Fix (extraction)**: `ENTITY_SYSTEM` prompt now has explicit worked
  examples for brand-and-model splitting — "Renzo Discovery" → brand +
  model, never one field. GPT-4o-mini was previously stuffing "Renzo
  Discovery" into `new_vehicle_model` and leaving the brand slot empty,
  which is what triggered the "which brand?" clarify loop in the first
  place.

### Operator review card layout: chat full-width, metadata stacked below
- Previous layout was 3 columns of chat + 2 columns of confidence/actions.
  Congested at typical laptop widths.
- New layout: chat window full-width (440px tall, scrollable transcript,
  pinned reply input). Below that, a 2-column strip with confidence + rationale
  on the left and close/reassign actions on the right. Everything gets
  breathing room.

## 2026-08-01 — Fast-tier model swap: gpt-4o-mini → gpt-5-mini

### What changed
- `openai_fast_model` default in `core/settings.py`, `.env.example`, and
  the user's `.env`: `gpt-4o-mini` → `gpt-5-mini`. Premium tier (`gpt-4o`)
  unchanged.
- Added a `gpt-5-mini` entry to the `PRICING` table in
  `infrastructure/llm/registry.py`, marked with a comment that the rate
  is a placeholder pending verification against OpenAI's current list
  price — the BudgetGuard uses this number directly for spend tracking.

### Bug this surfaced: gpt-5 family rejects custom temperature
- **Symptom**: every OpenAI call failed with `400 Unsupported value:
  'temperature' does not support 0.0 with this model. Only the default
  (1) value is supported.` — three of the four integration tests hitting
  live OpenAI failed immediately.
- **Root cause**: the provider adapter unconditionally passed
  `temperature=0.0` (structured extraction) or `0.3` (generation) on
  every call. gpt-5-mini only accepts the default temperature (1);
  passing anything else is a hard 400, not a warning.
- **Fix**: `_accepts_custom_temperature(model)` in
  `infrastructure/llm/providers.py` — prefix-checks for `gpt-5`, and all
  three OpenAI methods (`complete`, `complete_structured`, `stream`) omit
  the `temperature` kwarg entirely when the model doesn't accept it,
  rather than sending a value OpenAI will reject. Future gpt-5-x variants
  are covered without a further code change.
- This fix is model-detection based, not provider-wide — Anthropic and
  older OpenAI models are unaffected and still get explicit temperature
  control.

### Observed behavior difference — worth knowing before relying on this
Live smoke test (mixed-intent message, real API):

| Node | Model | Tokens in | Tokens out | Latency | Cost |
|---|---|---|---|---|---|
| discover_intents | gpt-5-mini | 943 | 350 | 9.9s | $0.00094 |
| extract_entities | gpt-5-mini | 863 | **1,145** | 22.4s | $0.00251 |
| score_sentiment | gpt-5-mini | 225 | 296 | 8.8s | $0.00065 |

Compare to typical `gpt-4o-mini` behavior on the same three calls: low
single-digit-second latency, completion tokens roughly matching the size
of the structured output (tens to low hundreds of tokens, not over a
thousand).

**Interpretation**: gpt-5-mini appears to be a reasoning-family model that
spends completion tokens on internal chain-of-thought before emitting the
final structured object — tokens that are billed but never surface in the
parsed result. This is consistent with the disproportionately high
completion-token count on `extract_entities` (a task that should produce
a handful of short fields) and the 3-8x latency increase across all three
parallel fast-tier calls.

**Not diagnosed as a bug** — the pipeline is correct, all three intents
extracted at 0.9 confidence, cost per turn is still a fraction of a cent
($0.00409 total for a 3-intent message across 3 LLM calls). But the
**fast tier is no longer fast** in wall-clock terms, and the per-request
cost is roughly 4-6x gpt-4o-mini's list price for the same task shape.
This tradeoff should be weighed once Module 14's golden set exists and
can measure whether the accuracy gain (if any) justifies the latency and
cost increase for a tier whose entire design purpose was "cheap and fast
enough to run three times in parallel every turn."

### Tests and gates
- 199 backend tests pass live against `gpt-5-mini` (was intermittently
  failing before the temperature fix — see above).
- ruff clean, mypy strict clean.
- Also fixed, unrelated pre-existing lint/type debt found while in the
  area: renamed `SlotUnavailable` → `SlotUnavailableError` (N818), three
  en-dash-in-string/comment violations in `appointments.py` (RUF001/003),
  an unnecessary list comprehension in `runtime.py` (C416), and two mypy
  narrowing issues (`_CatalogLookupPort | None` closure capture,
  `Any`-return in `_resolve_previous_awaiting`).

### Calendar UX rebuilt as day-first, then time-first
- Reference model was the classic date-picker → time-slot-pills pattern. Adopted the pattern; kept our Swiss discipline.
- **Day strip** at the top: horizontal-scroll pills, each showing weekday initials over the day-of-month over month-abbr. Selected day fills with ink; unselected has a hairline border and lifts on hover (`-translate-y-0.5`). Each pill also shows the slot count for that day.
- **Time pills** below for the selected day only: mono time labels, wrap-flow. Selected pill uses Karva amber (`bg-karva text-paper`) with a small checkmark badge in ink. Unavailable pills are muted with `line-through decoration-1`. Hover lift matches the day strip.
- **Confirm bar** at the bottom: fills with `karva-soft` when a slot is selected — subtle "you're one click away" affordance.
- No modals. The selection is inline and reversible; a single Confirm button completes the booking.

## 2026-08-02 — Clarifying questions can finally see the catalog

### The bug underneath the feature
`route_after_plan` branched to `clarify` straight off `build_plan`,
*before* `retrieve` and `call_tools`. So `tool_results` and `chunks` were
both empty in every clarify turn. The node was not choosing to omit
vehicle specs — it had never been given any. Any attempt to enrich the
clarifying question would have been specs-empty 100% of the time,
including the "narrow patch" option discussed earlier.

**Fix**: `build_plan → retrieve → call_tools → {clarify | score_confidence}`.
The branch is now `route_after_tools`. Retrieval and tools are
deterministic and cost nothing, so running them before the branch buys
context for free. Pinned by
`test_a_clarifying_turn_has_already_looked_the_vehicle_up`.

### Gemini phrases clarifications; the template is still the floor
- `infrastructure/llm/gemini_provider.py` — `GeminiClarifier`. Not a full
  `LLMProvider` on purpose: no structured output, no budget router, one
  `phrase()` method, `asyncio.wait_for` timeout. SDK imported lazily.
- `services/execution/clarification.py` — `ClarificationWriter`. Computes
  the policy template first, every time. Only then attempts a rewrite.
- **Which slot is asked about is never the model's decision** — it comes
  from `intent_policy().next_question_slot()` as before. The model only
  chooses words.
- **Figure discipline**: the permitted number set is exactly what we
  pre-rendered into the prompt (spec line + availability + template). Any
  digit in the reply outside that set rejects the whole rewrite. Also
  rejected: unparseable JSON, empty, >500 chars, no question mark.
- Rejection and failure both fall back to the template, and the reason
  lands on the `clarify` span as `fallback_reason` + `source`.
- `validate_grounding` was deliberately *not* reused here: its
  qualitative branch scores lexical overlap against retrieved chunks, and
  a question overlaps nothing, so every clarification would score
  UNGROUNDED. The numeric check is the part that transfers.

### Wiring
- `GEMINI_API_KEY` / `GEMINI_MODEL` / `CLARIFIER_TIMEOUT_SECONDS` in
  settings and `.env.example`. Empty key is a supported configuration.
- `Container.clarifier` defaults to `ClarificationWriter()` (template
  only), so every existing test fixture and any keyless deployment
  behaves exactly as before.
- `_describe_vehicle` → `describe_vehicle` in `runtime.py` so the
  clarifier can render the same one-line spec format the generator uses.

### Tests and gates
- 214 backend tests pass against the mock (199 + 15 new). ruff clean,
  mypy strict clean.
- Not verified against a live Gemini key — no key available in this
  session. The template path and every rejection branch are covered by
  `tests/unit/test_clarification.py` with a stub phraser.

## 2026-08-02 — Anthropic verified live; premium tier was broken

### There is no provider failover, and never was
Worth stating plainly because it is a natural assumption: `build_provider`
is a `match` on `LLM_PROVIDER` resolved once at startup, and `ModelRouter`
wraps exactly one provider. If OpenAI returns errors, nothing switches to
Anthropic — `discover_intents` logs and returns empty, confidence drops,
and the conversation escalates to a human. Anthropic is an *alternative*
selected by config, not a *fallback*. Switching is a deliberate two-
variable change (`LLM_PROVIDER` + the key).

### `claude-opus-5` rejected every request — now fixed
First live Anthropic call on the premium tier returned
`400 — "temperature is deprecated for this model"`. Exactly the failure
class already handled for `gpt-5-mini` via `_accepts_custom_temperature`,
but the Anthropic adapter had no equivalent guard and passed `temperature`
unconditionally in all three methods (`complete`, `complete_structured`,
`stream`).

**Fix**: `_anthropic_accepts_temperature`, regex
`^claude-[a-z]+-5(?:$|[^0-9])`. Anchored on the generation digit so
`claude-haiku-4-5-20251001` — Haiku 4.5, which *does* accept the parameter
— is not caught. A naive `"-5" in model` substring check would have
silently stripped temperature from the entire fast tier.

**Root cause of it reaching main**: no unit coverage existed for the
gpt-5 detection either, and the mock provider structurally cannot catch a
vendor 400. Added `tests/unit/test_providers.py` covering both families.

### Verified live (real keys, real spend ~$0.01 total)
- `complete` fast (`claude-haiku-4-5-20251001`) — OK
- `complete_structured` fast — OK, both intents discovered correctly
- `complete` premium (`claude-opus-5`) — was FAIL, now OK
- Full graph turn end to end on Anthropic, ten nodes, zero node errors

### GEMINI_MODEL default changed to gemini-2.5-flash
The first live clarification call 429'd with
`limit: 0, model: gemini-2.0-flash` — the newly issued key has a
free-tier allocation of literally zero requests for 2.0-flash. Probed the
alternatives: `gemini-2.5-flash` works, `gemini-2.0-flash-001` 429s,
`gemini-2.5-flash-lite` 404s. Default moved to `gemini-2.5-flash`.

That 429 was also an unplanned live test of the fallback path, and it
behaved correctly — `clarification_phrasing_failed` logged, template
returned, conversation unaffected.

With both working, the clarify node produced:
> "We have the 2017 Renzo S5, a manual, 333hp, all-wheel drive model with
> 26 hwy mpg, available for 53100 AED. Which day would suit you for the
> test drive?"

which is the behaviour this whole thread was chasing.

### Tests and gates
- 228 backend tests pass against the mock. ruff clean, mypy strict clean.

## 2026-08-02 — Verified on Cloud Run via a no-traffic tagged revision

Method: `gcloud run deploy --no-traffic --tag=anthropic-test` with
`LLM_PROVIDER=anthropic`, giving revision 00005/00006 a private URL while
production stayed pinned at 100% on 00004-mhq. Tag removed and traffic
re-pinned afterwards; production never served a test request.

### Anthropic works on Cloud Run
`discover_intents` and `extract_entities` both ran on
`claude-haiku-4-5-20251001` / provider `anthropic`, status ok, both intents
found. The SDK is already in the image via `pyproject.toml`, and Cloud Run
egress to `api.anthropic.com` is unrestricted.

### Two Cloud-Run-only failures the local run could not have caught

**1. Retrieval was dead in the deployed image.** `retrieve` failed with
"Could not load model ... from any source" after 39 seconds, every
request. The Dockerfile never actually baked the FastEmbed weights despite
CLAUDE.md claiming it did — they were being downloaded at runtime, and
that download fails on Cloud Run.

Pre-existing, but harmless until now: `clarify` used to bypass `retrieve`
entirely, so the 2026-08-02 graph reorder is what put those 39 seconds on
the most common path in the app. Fixed by pre-caching all three models in
the Dockerfile with `FASTEMBED_CACHE_PATH=/opt/fastembed` (verified
fastembed reads that variable in `common/utils.py`).

Result: `retrieve` now returns 5 reranked chunks. End-to-end latency
45.9s → 22.0s cold, 6.4s warm.

**2. `gemini-2.5-flash` returned unparseable JSON, every call.** Thinking
is on by default for the 2.5 family and is charged against the *same*
output budget as the reply, so it consumed the budget before closing the
JSON brace. Fixed with `thinking_config=ThinkingConfig(thinking_budget=0)`
and `max_output_tokens` 400 → 800. Verified 4/4 clean parses.

With both fixed, the deployed clarify node produced:
> "We can certainly arrange a test drive for the 2016 Renzo S5 with 333hp
> and all-wheel drive. Which day would suit you for the test drive? I'll
> also get back to you regarding the monthly installment."

Specs, the clarifying question, *and* an acknowledgement of the second
open intent — all three, which is what the whole thread was after.

### Timeout labelling
A later warm request showed `clarify` at exactly 6001ms falling back with
`phrasing_failed: ` — nothing after the colon, because
`str(TimeoutError())` is empty. Timeout is now caught separately and
reports `timed_out`. Free-tier Gemini latency is genuinely variable
(762ms on one call, >6s on another), so this is the failure an operator
will see most often.

### backend-env.yaml
`ANTHROPIC_API_KEY`, `ANTHROPIC_FAST_MODEL` and `ANTHROPIC_PREMIUM_MODEL`
added, with `LLM_PROVIDER` left on `openai`. Switching providers is now a
one-line edit rather than a two-variable change where getting only the
first half right refuses to boot.

## 2026-08-02 — Clarification moved from Gemini to Groq

Gemini lasted less than a day. It worked, but its free tier was erratic on
Cloud Run — 762ms on one call, a >6s timeout on the next, same prompt —
so the feature spent much of its time silently falling back to templates.

### Groq needs no SDK
Groq serves an OpenAI-compatible API, so `GroqClarifier` points the
`openai` client the project already depends on at
`https://api.groq.com/openai/v1`. Consequences:
- `google-genai` dependency **removed** and uninstalled.
- No `ThinkingConfig`, no vendor types — the fragile part of the Gemini
  adapter is simply gone.
- `response_format={"type": "json_object"}` replaces
  `response_mime_type`, so the caller's strict parser is unchanged.

`CLARIFIER_TIMEOUT_SECONDS` dropped 6.0 → 4.0. The 6s ceiling existed only
because Gemini regularly needed it.

### Model chosen from measurement, not opinion
Six runs each against the real clarification prompt:

| model | accepted | p50 | note |
|---|---|---|---|
| `llama-3.1-8b-instant` | 6/6 | 208ms | plainest wording |
| `llama-3.3-70b-versatile` | 6/6 | 286ms | also acknowledges the 2nd intent |
| `openai/gpt-oss-20b` | 3/6 | 747ms | `json_validate_failed` |

`gpt-oss-20b` failed for the *same reason Gemini did*: reasoning tokens
consumed the completion budget before the closing brace
("max completion tokens reached before generating a valid document").
Worth remembering as a pattern — any reasoning-enabled model needs its
thinking disabled or its budget raised before it can be used for
constrained JSON on a latency budget.

**Shipped `llama-3.1-8b-instant`.** 70B is a one-env-var swap
(`GROQ_MODEL`) and writes better multi-intent replies, at the cost of a
smaller free daily token budget.

### Verified on the deploy configuration
Full graph turn with `LLM_PROVIDER=openai` + Groq clarifier: ten nodes,
zero errors, `clarify` **128ms**, `source=model`, no fallback. Against
Gemini's 6001ms timeout on the same node, roughly a 47x improvement.

241 tests pass, ruff clean, mypy strict clean, and mypy still passes with
`google-genai` uninstalled — proving nothing imports it.

## 2026-08-02 — Switched clarification to llama-3.3-70b-versatile

Moved from `llama-3.1-8b-instant` after seeing 8B's wording live: it never
acknowledged the conversation's second open intent, and one production
reply read "**I'm interested in** the test drive for the 2016 Renzo S5" —
the dealership speaking as if it were the customer.

### 70B exposed a prompt bug that 8B had been hiding
Its first outputs read:
> "I will come back to your other requests, including **the test drive
> booking** and **financing EMI**"

Two faults, both in `_build_context`, neither the model's:
1. The intent owning the slot being asked about was still listed under
   "Other open requests" — so the reply asked for a test-drive date while
   describing the test drive as something to come back to later.
2. Intent categories were rendered as `category.value.replace("_"," ")`,
   putting the raw enum name "financing emi" in front of a customer.

**Fixed**: `_build_context` now takes `asked_slot` and filters it out of
every intent's remaining slots, dropping intents left with nothing; and
`_INTENT_LABELS` maps categories to customer-facing phrases ("financing",
"the trade-in") with the old behaviour as the fallback for anything
unmapped.

After: *"Which day would suit you for the test drive of the 2016 Renzo S5?
I will also come back to your financing inquiry regarding the down
payment."*

Worth noting the general lesson: the weaker model was not producing worse
output so much as **surfacing prompt defects the stronger one papered
over**. The bug was there the whole time.

`groq_model` default and `.env.example` moved to 70B so the shipped
default matches what is deployed. 8B stays documented as the
higher-quota, ~100ms-faster fallback.

231 tests pass, ruff clean, mypy strict clean.

## 2026-08-02 — Multi-intent conversations stopped collapsing after one answer

Reported symptom: a three-intent message produced two unrelated instructions
in one reply, and booking a slot ended the conversation with the trade-in
and financing requests unanswered.

**The intent queue was never at fault.** The reply
"…I'll come back to the test drive and other details afterwards" could only
be written by something that knew all three intents. Both faults were in the
API layer overriding the orchestrator.

### 1. The calendar hijacked a question about something else
`_should_show_calendar` inspected only `intents.primary` and never asked what
the graph had decided that turn. With the test drive as highest-priority
intent but the graph clarifying `old_vehicle_model`, routes.py appended its
call-to-action to that question and overwrote `awaiting` with
`test_drive_slot` — so the *next* turn's extractor was told the customer was
answering about a slot when they were answering about their Karva.

Fixed by deferring to the graph: the calendar shows only when `awaiting` is
`preferred_date`, `preferred_time`, or `None` (nothing outstanding).

### 2. "Perfect —" congratulated the customer for nothing
A hardcoded prefix on the call-to-action. Following a question it read as a
reply to an answer nobody had given. Removed.

### 3. Booking was a dead end
`book_slot` returned a hardcoded f-string, never touching the queue. Added
`_advance_after_booking`: resolves the test-drive intent, rebuilds the plan
over what remains (`ordered()` skips resolved intents, so this falls out for
free), and reuses the same `ClarificationWriter` the graph uses so the
follow-up is phrased identically to any other turn. Deliberately does *not*
re-run the graph — the customer tapped a calendar, there is no message for
the understanding layer to read, and inventing a synthetic turn would cost a
full pipeline run for nothing.

Verified live: booking now yields
> "Booked! …See you at Legend Motors, Showroom #46, Ras Al Khor.
> To assist you with the trade-in, which model is your current car?"

with `open_intents` correctly reduced to `[trade_in_valuation, financing_emi]`.

### Bonus: the suite was making live Groq calls
`_build_clarifier` only checked for a key, not the provider, so
`LLM_PROVIDER=mock` still attached the real Groq client — the test suite was
reaching the network and spending quota on every clarifying turn, and the
event loop closing mid-request produced confusing teardown errors. The mock
provider now short-circuits the clarifier too, restoring the determinism
guarantee its docstring promises.

234 tests pass, ruff clean, mypy strict clean.

## 2026-08-02 — A greeting was being escalated to a human

Reported: "Good morning" produced a drafted reply, confidence 67, escalated
with reason *grounding failed*, and the reply then vanished from the chat on
navigating away.

### The score was never the deciding factor
67 is below both thresholds (75 premium / 90 auto), but that is beside the
point — the escalation reason was a grounding failure, which is a hard
override. The reply would have escalated at 95 too.

### Why grounding failed on a greeting
`validate_grounding` treats every non-boilerplate sentence as a factual claim
to be supported by corpus overlap. Decomposing the reply gave:

| sentence | verdict |
|---|---|
| "Good morning!" | boilerplate, skipped |
| "It's currently 09:00." | unsupported |
| "How can I assist you today with your vehicle needs?" | unsupported |

Faithfulness 0.0 → UNGROUNDED → retry → fail again → human. The check was
reporting a problem it had invented: a *question* is not an assertion, and a
greeting has nothing to be wrong about.

**Three fixes, layered:**
1. `_is_question` — sentences ending in `?` or `؟` are excluded from claims.
   Asking for information is the opposite of asserting it.
2. `_is_only_small_talk` in the `validate` node — a turn whose every
   unresolved intent is `SMALL_TALK` skips validation and takes
   `vacuously_grounded()`. Deliberately strict: one real request alongside
   the greeting and the whole reply is validated as normal. `GENERAL_INFO`
   (hours, location) is *not* small talk and stays grounded.
3. The generator system prompt now forbids stating the current time or date.

### The model had invented the clock
Nothing in the codebase injects a clock — `grep` for time injection into the
generator prompt returns nothing. "It's currently 09:00" was a hallucination,
and grounding was right to flag it. It still does: the unit tests pin that an
invented clock remains ungrounded even after the question fix. The prompt
change removes it at source.

*(Correcting an earlier claim made in conversation that date/time is injected
into the system prompt — it is not.)*

### The vanishing reply
`routes.py` returned `draft.en` to the customer on every path but only wrote
it to the transcript when the run was *not* escalated. So the customer read a
full answer that existed nowhere on the server, and it disappeared on reload.

The architecture's own rule is that a reviewer decides what the customer
sees, so returning the unapproved draft was the bug — not the missing write.
Escalated turns now return a holding message ("checking this with a
colleague") which *is* persisted, so what is shown and what is stored are the
same thing. The draft still reaches the operator through the review queue.

Verified live: "Good morning" → `small_talk`, grounding `grounded` with zero
claims, `escalated: False`, reply "Good morning! How can I assist you today?"
with no invented time, and present in the stored transcript.

244 tests pass, ruff clean, mypy strict clean.
