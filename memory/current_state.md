# Current state

*Snapshot of exactly where development stands right now. Update whenever
work-in-progress changes.*

## As of 2026-08-01 (latest session)

### Current task

Just completed the fast-tier model swap to `gpt-5-mini` and the fixes it
required (temperature parameter incompatibility). Also landed, same
session: generator transcript-context bug, operator queue re-enqueue bug,
operator UI full-width rework, test-drive booking calendar, dealership
address correction. All verified live against real OpenAI. No task
in-flight right now — awaiting next instruction.

### Branch

Working directly on the local filesystem, no explicit branch tracking
mentioned. No CI configured yet. Git repository state has not been
verified by memory; run `git status` if needed.

### Files most recently touched (this session)

- `backend/app/infrastructure/llm/providers.py` — `_accepts_custom_temperature()`
  helper; all three `OpenAIProvider` methods now omit `temperature` for
  gpt-5-family models instead of sending a value OpenAI rejects.
- `backend/app/infrastructure/llm/registry.py` — added `gpt-5-mini` to
  `PRICING` (rate is a placeholder, flagged for verification).
- `backend/app/core/settings.py`, `.env.example`, `.env` —
  `openai_fast_model` default changed to `gpt-5-mini`.
- `backend/app/graph/state.py` — added `transcript` field to `GraphState`
  so the full conversation history flows through the graph, not just the
  current message.
- `backend/app/graph/nodes.py` — `_rebuild_conversation` now passes
  `transcript` through (previously silently dropped it).
- `backend/app/api/v1/routes.py` — `submit_inquiry` loads and passes the
  transcript into `initial_state`; `_should_show_calendar` /
  `_resolve_previous_awaiting` helpers; re-enqueue via
  `enqueue_customer_followup` when a customer messages a handed-off
  conversation.
- `backend/app/services/execution/runtime.py` — `ResponseGenerator._build_context`
  rewritten to show last 8 turns, per-intent missing slots, and known
  entities; `HumanReviewQueue.enqueue_customer_followup` +
  `open_for` (idempotent, one card per conversation).
  `SlotUnavailable` renamed to `SlotUnavailableError`.
- `backend/app/services/understanding/engine.py` — `ENTITY_SYSTEM` prompt
  has worked examples for brand/model splitting ("Renzo Discovery" →
  two slots, not one).
- `backend/app/services/execution/appointments.py` — `Asia/Dubai` timezone
  throughout; every UI-facing string pre-formatted server-side
  (`day_label`, `time_label`, `slot_label`) so chat and operator views
  never disagree on wall-clock time.
- `backend/app/domain/enums.py` — new `HumanReviewReason.AWAITING_OPERATOR_REPLY`.
- `frontend/src/components/CalendarPicker.tsx` — new: day-strip →
  time-pills booking flow, renders backend-formatted strings verbatim.
- `frontend/src/app/admin/page.tsx` — `ReviewCard` rebuilt: chat window
  full-width (440px, scrollable, pinned input), confidence/routing/actions
  stacked in a 2-column strip below. Also shows recent bookings sidebar.
- `frontend/src/app/chat/page.tsx` — renders `<CalendarPicker>` inline
  when `response.awaiting === "test_drive_slot"`.
- `data/knowledge/policies/00-about-alto-motors.md`,
  `09-frequently-asked-questions.md` — address corrected to Legend
  Motors, Showroom #46, Ras Al Khor.
- `data/knowledge/policies/02-test-drive-procedure.md` — slot length
  45min → 2 hours.

### Configuration (current values)

- `.env` — `LLM_PROVIDER=openai`, `OPENAI_FAST_MODEL=gpt-5-mini`,
  `OPENAI_PREMIUM_MODEL=gpt-4o`, `API_PORT=8080`,
  `CORS_ORIGINS=http://localhost:3000,http://localhost:3010`. API keys
  for both OpenAI and Anthropic are populated.
- `frontend/.env.local` — `NEXT_PUBLIC_API_BASE_URL=http://localhost:8080`.

### Runtime state

**Docker data plane**: confirmed reachable during this session (live
smoke test hit real Qdrant + OpenAI successfully — `retrieval_enabled`
was true). May not still be running if the user has since closed it;
`python tasks.py up` brings it back.

**Backend and frontend servers**: not running as background processes —
the user runs these themselves in their own terminals to learn the
system. Claude should not start background servers unless asked.

**Postgres catalog population**: unconfirmed whether the CSV has been
loaded into Postgres in the user's current environment (requires
`python -m app.workers.ingestion` with Docker up). Verify via
`curl http://localhost:8080/ready` → look for `structured_catalog: true`
before relying on "we don't stock that" behavior.

**Ports**:
- `8000` — occupied by an unrelated app on the developer's machine
  (`bidpilot.dev`). We do not use it.
- `8080` — backend, when running.
- `3000` — frontend, when running.
- `5432`, `6379`, `6333` — Postgres, Redis, Qdrant when data plane is up.

### Tests

**199 backend tests passing**, verified live against real OpenAI
(`gpt-5-mini` fast tier) as of this session. Ruff clean, mypy strict
clean. Frontend builds clean under strict TypeScript with all four
routes prerendered (`/`, `/workflow`, `/chat`, `/admin`).

### Known-but-not-yet-acted-on observation

`gpt-5-mini` is measurably slower (8-22s per fast-tier call vs.
gpt-4o-mini's low single digits) and burns unusually high completion-token
counts on simple structured-extraction tasks — consistent with
reasoning-model behavior where chain-of-thought tokens are billed but
never surface in the parsed output. Not treated as a bug; flagged for a
cost/latency-vs-accuracy tradeoff decision once Module 14's golden set
exists to measure whether it's worth it. See `completed_work.md`
2026-08-01 entry for the measured numbers.

### Pending work (short-list, see `future_tasks.md` for the full backlog)

- Decide whether `gpt-5-mini`'s latency/cost profile is worth it once
  Module 14 can measure accuracy against the golden set. Fallback is a
  one-line revert to `gpt-4o-mini` in `.env`.
- Verify the `gpt-5-mini` pricing entry in `registry.py` against OpenAI's
  actual current list price — it was estimated, not sourced.
- Confirm Postgres catalog population is current in the live environment.
- Re-run ingestion if the ten policy documents or the address correction
  haven't been reflected in Qdrant yet (`python -m app.workers.ingestion --recreate`).

### Blockers

None currently blocking.

### Temporary notes

- The user prefers to run backend and frontend themselves, in their own
  terminals, to learn. Claude should not start background servers unless
  explicitly asked.
- The user's OpenAI and Anthropic keys are in `.env`. `.env` is gitignored.
  Keys have been visible in shell output during past sessions — treated
  as a known situation, not a leak requiring rotation, unless the user
  says otherwise.
