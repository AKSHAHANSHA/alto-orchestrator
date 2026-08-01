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

### Calendar UX rebuilt as day-first, then time-first
- Reference model was the classic date-picker → time-slot-pills pattern. Adopted the pattern; kept our Swiss discipline.
- **Day strip** at the top: horizontal-scroll pills, each showing weekday initials over the day-of-month over month-abbr. Selected day fills with ink; unselected has a hairline border and lifts on hover (`-translate-y-0.5`). Each pill also shows the slot count for that day.
- **Time pills** below for the selected day only: mono time labels, wrap-flow. Selected pill uses Karva amber (`bg-karva text-paper`) with a small checkmark badge in ink. Unavailable pills are muted with `line-through decoration-1`. Hover lift matches the day strip.
- **Confirm bar** at the bottom: fills with `karva-soft` when a slot is selected — subtle "you're one click away" affordance.
- No modals. The selection is inline and reversible; a single Confirm button completes the booking.
