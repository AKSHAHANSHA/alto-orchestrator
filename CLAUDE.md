# CLAUDE.md — session entry point

Read this first. Then read only the memory files relevant to the current
task — do not preload the whole `memory/` directory.

## Project

**Alto AI Support Orchestrator** — a multilingual AI customer-support
orchestration platform for Alto Motors, a fictional dealership operating
in the fictional market of Velmora. Two brands: **Karva** (mass-market
sedans and SUVs) and **Renzo** (premium and performance). The platform
automates the coordinator's thinking — reading messages, discovering every
intent, extracting facts, deciding whether to answer, ask, route, or
escalate — while keeping every decision explainable and low-confidence
cases in the hands of a human.

Not a chatbot. Not an LLM wrapper. The intelligence lives in orchestration,
routing, hybrid retrieval, structured memory and explainability.

## Stack

- **Backend**: Python 3.11, FastAPI, LangGraph 0.2.x, SQLAlchemy 2 async,
  Pydantic v2, structlog, pytest.
- **Frontend**: Next.js 15 App Router, React 19, TypeScript strict,
  Tailwind, TanStack Query.
- **Data plane**: PostgreSQL 16, Redis 7, Qdrant v1.17.
- **Models**: OpenAI (fast: **gpt-5-mini**, premium: gpt-4o), Anthropic
  (fast: claude-haiku-4-5-20251001, premium: claude-opus-5), Mock
  (deterministic, keyless). All behind one `LLMProvider` port. Note:
  gpt-5-mini rejects any non-default `temperature` (400 error) — the
  OpenAI adapter detects `gpt-5*` models and omits the param for them.
  gpt-5-mini is slow (8–22s per fast-tier call, some of it OpenAI-side
  retry/rate-limiting) and produces high completion-token counts on simple
  extraction, consistent with reasoning-model behaviour.
- **gpt-4o-mini was trialled and reverted on 2026-08-03.** It is 3.5–6x
  faster and better at multi-intent discovery, but files a one-word slot
  answer into the wrong slot — "Renzo" answering "which brand?" became
  `old_vehicle_brand` instead of `new_vehicle_brand`, 3/3 runs, looping the
  conversation and corrupting the trade-in. This is a prompt gap in
  `ENTITY_SYSTEM`, not a settled verdict on the model: fixing it makes the
  speed available again. See `completed_work.md` 2026-08-03.
- **Retrieval**: Qdrant hybrid RRF (dense multilingual +
  BM25 sparse with IDF modifier) plus cross-encoder rerank
  (English-only — Arabic queries preserve RRF order).

## Current phase

**Post-MVP, 14 of 16 planned modules complete.** The platform is
end-to-end working with real LLM providers, structured catalog lookup and
interactive human handoff. What remains: evaluation service (Module 14)
and the animated workflow-graph in the admin dashboard.

## Current priority

Whatever the user asks. If nothing pending, likely candidates:
- Building Module 14 (evaluation harness + golden set).
- Adding real persistence for conversations (currently in-memory).
- Wiring the SSE endpoint to a React Flow workflow diagram in `/admin`.

## Important instructions

- **Do not preload every memory file.** Read `CLAUDE.md`, then only the
  ones relevant to the task.
- **Always verify facts before recommending.** Memory records the state
  at a point in time; the codebase is authoritative for current state.
- **When work meaningfully advances the project, update memory.** Update
  only the files that changed. Do not rewrite an entire file for a small
  edit.
- **Ports on the developer's machine**: 8000 is held by an unrelated
  process (`bidpilot.dev`). The project runs on **8080**. `.env`
  reflects this.
- **Auto-send is disabled by default** (`ALLOW_AUTO_SEND=false`). Every
  reply is drafted for approval unless the operator turns it on.

## Memory files

| File | When to read |
|---|---|
| [project_overview.md](memory/project_overview.md) | New session, or the project brief is in question |
| [architecture.md](memory/architecture.md) | Any structural or cross-layer work |
| [coding_standards.md](memory/coding_standards.md) | Before writing or refactoring code |
| [completed_work.md](memory/completed_work.md) | Answering "what has been built already?" |
| [current_state.md](memory/current_state.md) | Resuming work in progress |
| [decisions.md](memory/decisions.md) | Before revisiting a design choice |
| [known_issues.md](memory/known_issues.md) | Before proposing a fix or feature |
| [future_tasks.md](memory/future_tasks.md) | Picking the next task |
| [prompts.md](memory/prompts.md) | Reusable prompt templates |

## Last updated

**2026-08-01** — fast-tier model swapped to gpt-5-mini; fixed a
temperature-parameter incompatibility this surfaced in the OpenAI
adapter. Also: generator transcript-context bug fixed (LLM was writing
stock filler because `_rebuild_conversation` dropped the transcript),
operator queue re-enqueue fixed (customer replies after handoff weren't
reaching the operator), operator UI reworked to full-width chat with
metadata stacked below, test-drive booking calendar added with Dubai-
timezone-consistent formatting, dealership address corrected to Legend
Motors — Showroom #46, Ras Al Khor.
