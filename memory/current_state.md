# Current state

*Snapshot of exactly where development stands right now. Update whenever
work-in-progress changes.*

## As of 2026-08-01

### Current task

**Persistent memory system setup.** No active development beyond that —
the last substantive work (corpus expansion, structured catalog wiring,
landing/workflow split) is complete and tested.

### Branch

Working directly on the local filesystem, no explicit branch tracking
mentioned. No CI configured yet. Git repository state has not been
verified by memory; run `git status` if needed.

### Files most recently touched

Backend:
- `backend/app/services/execution/runtime.py` — added `_CatalogLookupPort`
  Protocol, wired structured catalog lookup into `ToolRunner`.
- `backend/app/services/execution/catalog_lookup.py` → moved to
  `backend/app/infrastructure/persistence/catalog_repository.py`.
- `backend/app/infrastructure/persistence/models.py` — new `VehicleRow`.
- `backend/app/infrastructure/persistence/engine.py` — async engine + session
  factory + `ensure_schema` helper.
- `backend/app/composition/container.py` — added `catalog_lookup` field,
  `_build_catalog_lookup` factory (graceful fallback if Postgres down).
- `backend/app/graph/state.py` — new `previous_awaiting` field.
- `backend/app/services/understanding/engine.py` — `_wrap_with_context`
  helper, `previous_awaiting` threaded into `discover_intents` and
  `extract_entities`.
- `backend/app/api/v1/routes.py` — `_resolve_previous_awaiting` from prior
  conversation state.
- `backend/app/workers/ingestion/__main__.py` — `populate_postgres_catalog`
  step, `--skip-postgres` flag.
- `backend/app/infrastructure/llm/mock_provider.py` — model-name extraction
  extended (handles hyphenated names, multi-token models, alphanumerics).

Frontend:
- `frontend/src/app/page.tsx` — short non-technical landing (rewritten).
- `frontend/src/app/workflow/page.tsx` — new, deeper technical page.
- `frontend/src/app/chat/page.tsx` — session persistence via localStorage.
- `frontend/src/app/admin/page.tsx` — rebuilt review card with
  transcript + textarea + reassign dropdown + live follow-up.
- `frontend/src/lib/api.ts` — `TranscriptTurn`, `ConversationState`,
  `humanReply`, updated `resolveReview` signature.
- `frontend/.env.local` — `NEXT_PUBLIC_API_BASE_URL=http://localhost:8080`.

Data:
- `data/knowledge/policies/00-about-alto-motors.md`
- `data/knowledge/policies/01-showroom-hours-and-visits.md`
- `data/knowledge/policies/02-test-drive-procedure.md`
- `data/knowledge/policies/03-trade-in-inspection.md`
- `data/knowledge/policies/04-financing-partners.md`
- `data/knowledge/policies/05-vehicle-warranty-and-servicing.md`
- `data/knowledge/policies/06-delivery-and-registration.md`
- `data/knowledge/policies/07-brand-guides.md`
- `data/knowledge/policies/08-after-sales-and-complaints.md`
- `data/knowledge/policies/09-frequently-asked-questions.md`

Configuration:
- `.env` — `LLM_PROVIDER=openai`, `API_PORT=8080`,
  `CORS_ORIGINS=http://localhost:3000,http://localhost:3010`,
  `NEXT_PUBLIC_API_BASE_URL=http://localhost:8080`. API keys for both
  OpenAI and Anthropic are populated.

### Runtime state

**Docker data plane**: known to have been down at end of last session
(user closed Docker Desktop). Requires `python tasks.py up` before the
backend can populate Postgres or reach Qdrant.

**Backend and frontend servers**: not running. User controls these
manually — Claude should not start background servers unless asked.

**Ports**:
- `8000` — occupied by an unrelated app on the developer's machine
  (`bidpilot.dev`). We do not use it.
- `8080` — backend, when running.
- `3000` — frontend, when running.
- `5432`, `6379`, `6333` — Postgres, Redis, Qdrant when data plane is up.

### Tests

**199 backend tests passing** as of last full run (2026-08-01). Ruff clean,
mypy strict clean. Frontend builds clean under strict TypeScript with all
four routes prerendered.

### Pending work (short-list, see `future_tasks.md` for the full backlog)

- Populate Postgres from the CSV (requires Docker up) to activate the
  structured catalog lookup end-to-end.
- Re-run ingestion to include the ten new policy documents in Qdrant.
- Test the *"Renzo GX 470"* / *"Karva Discovery"* scenarios end-to-end
  with real OpenAI + populated Postgres and confirm the "we don't stock
  that" reply is honest.

### Blockers

None currently blocking. Docker Desktop being off is a user-driven pause,
not a code issue.

### Temporary notes

- The user prefers to run backend and frontend themselves, in their own
  terminals, to learn. Claude should not start background servers unless
  explicitly asked.
- The user's OpenAI key is in `.env`. `.env` is gitignored. It has been
  visible in shell output during past sessions — treated as a known
  situation, not a leak requiring rotation, unless the user says otherwise.
