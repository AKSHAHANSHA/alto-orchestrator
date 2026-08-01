# Reusable prompts

Prompt templates that have proven useful during this project. Each has a
one-line justification for why it exists.

## LLM system prompts in the codebase

These live in `backend/app/services/understanding/engine.py` and are the
prompts the platform sends to the LLM every conversation. Copy from there
if you need to tweak — they are the source of truth, not this file.

- `INTENT_SYSTEM` — classifies inbound messages into the intent taxonomy.
  Key rule: return every distinct request; return
  `unclear_needs_clarification` when the message is too vague. Do not
  guess.
- `ENTITY_SYSTEM` — extracts stated facts. Key rule: distinguish old_* from
  new_* vehicle slots. Never infer.
- `SENTIMENT_SYSTEM` — reads tone. Key rule: flag genuine frustration, not
  ordinary directness.

The `_wrap_with_context` helper prepends the previous turn's awaited slot
when there was one, so a short reply is understood as an answer rather than
a new intent.

## Response generation

The customer-facing reply prompt lives in
`backend/app/services/execution/runtime.py::ResponseGenerator.SYSTEM`. Key
rules:

- Use only figures given in the context. Never calculate.
- Address every open request in the message.
- Be warm, brief, specific.
- Always carry any disclaimer attached to a quote.

The Arabic translation is a separate call with
`ResponseGenerator.ARABIC_SYSTEM`. It preserves every figure verbatim.

## Working with Claude on this project

### Prompt: "Read the memory and continue development"

> Read `CLAUDE.md`, then read only the memory files relevant to the task
> at hand. Trust the memory for what has been decided; verify the code for
> current state. Do not preload every memory file — that wastes context.

Why: The whole point of the memory system is to survive a new chat. This
is the entry-point prompt.

### Prompt: "Diagnose a failing test"

> Isolate the failing test with `pytest tests/path::TestClass::test_name`.
> Read the traceback bottom-up — the real failure is at the leaf, not the
> surrounding stack. If it looks environmental (Docker down, port busy,
> network), verify the environment before touching the code. If the test
> catches a real bug, land the fix and the regression test in the same
> change.

Why: Repeated when a test failure surfaces. Environmental noise is common
on this platform because tests exercise Postgres, Qdrant, and real LLM
providers.

### Prompt: "Add a new intent category"

> 1. Add the value to `IntentCategory` in `backend/app/domain/enums.py`.
> 2. Add its rule (department, priority, required_slots, sla, dependencies)
>    to `backend/app/domain/policies/intents.yaml`.
> 3. Add its action verb to `ACTIONS` in
>    `backend/app/services/planning/planner.py`.
> 4. Add its retrieval collections to `COLLECTIONS_FOR_INTENT` in
>    `backend/app/infrastructure/vectorstore/retriever.py`.
> 5. Add mock keywords in
>    `backend/app/infrastructure/llm/mock_provider.py::INTENT_KEYWORDS` so
>    the mock provider covers it.
> 6. Add slot-question wording in
>    `backend/app/domain/policies/intents.yaml::slot_questions` if the new
>    intent needs a slot that doesn't already have one.
> 7. Update the LLM system prompt if the category's boundaries need
>    describing to the model.
> 8. Add a regression test that pins the new routing behaviour.

Why: An intent touches many files. This checklist ensures none are
missed. The policy YAML files and mock provider are the most commonly
forgotten ones.

### Prompt: "Add a new entity slot"

> 1. Add the value to `EntityType` in `backend/app/domain/enums.py`.
> 2. Add slot-question wording in `intents.yaml::slot_questions`.
> 3. Add it to `slot_question_order` in `intents.yaml` at the right
>    priority.
> 4. Add it to the required_slots of the intents that need it.
> 5. Add extraction rules in the mock provider if it needs mock coverage.
> 6. Update `CustomerProfile.vehicle_of_interest` or `.trade_in_vehicle`
>    in `entities.py` if the slot informs those.
> 7. Regression test.

### Prompt: "Update memory after a substantive change"

> Identify which memory files reflect the change. Update only those files.
> Update `current_state.md` to reflect the new working context. If a
> decision was made, append to `decisions.md` with alternatives considered.
> If a bug was discovered or fixed, update `known_issues.md`. Never
> rewrite an entire file for a small update.

Why: Keeps memory small and precise. Avoids the trap of a file becoming a
diary that nobody reads.

## Commit-message convention (not yet enforced)

Would use conventional commits (`feat:`, `fix:`, `refactor:`, `docs:`,
`test:`, `chore:`) if version control gains a hook. Currently no CI.

## Data authoring

### Prompt: "Write a policy document for the corpus"

> Author it in `data/knowledge/policies/NN-name.md`. Head with a
> `> **Synthetic content.**` disclaimer. Structure with `## H2` headings
> — the ingestion worker splits on them. Use the phrasing customers
> actually use, not marketing prose. Numbers must be either grounded in
> the ingested bank documents or explicitly labelled indicative.

Why: Chunks that read like real customer questions get retrieved for real
customer questions. Marketing prose doesn't match anything customers
actually say.
