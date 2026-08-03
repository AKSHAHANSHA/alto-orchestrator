"""Graph state and its reducers.

The state is *structured*, not a transcript. Nodes read typed fields and write
typed deltas; nothing re-derives intent by re-reading chat history. That rule
is enforced by an architecture test, and it is what lets a conversation pause
for three days and resume knowing exactly what it was waiting for.

Reducers own how a delta merges. The intent-queue reducer is the important
one — it is where "never lose an unresolved intent" stops being a hope about
prompting and becomes a property of the data structure.
"""

from __future__ import annotations

import operator
from collections.abc import Sequence
from typing import Annotated, Any, TypedDict

from app.domain.entities import (
    ConversationState,
    ExecutionAction,
    Intent,
    IntentQueue,
    Span,
)
from app.domain.value_objects import (
    ConfidenceVector,
    ConversationTurn,
    DraftReply,
    ExtractedEntity,
    GroundingReport,
    Plan,
    RetrievedChunk,
    RoutingDecision,
)


def merge_intents(
    current: IntentQueue | None, incoming: tuple[Intent, ...] | IntentQueue | None
) -> IntentQueue:
    """Fold newly observed intents into the queue.

    Delegates to `IntentQueue.merge`, which merges by category, preserves the
    fields the rule engine owns, and never drops an unresolved intent. Nodes
    that need to *replace* the queue wholesale — enrichment and slot
    recomputation, which rewrite policy-owned fields — pass an `IntentQueue`
    and it is taken as authoritative.
    """
    if incoming is None:
        return current or IntentQueue()
    if current is None:
        return incoming if isinstance(incoming, IntentQueue) else IntentQueue(intents=incoming)

    # A whole queue means "this is the new truth" — the planner recomputing
    # departments and slots must not be merge-folded back into stale values.
    #
    # An *empty* queue is the exception, and getting this wrong silently
    # destroyed the guarantee in this module's docstring. `initial_state()`
    # seeds `intents=IntentQueue()`, and on every turn after the first
    # LangGraph folds that seed into the checkpointed state — so an empty
    # queue arrived claiming to be the new truth and wiped every unresolved
    # intent the conversation had accumulated. A customer asking about a
    # trade-in, financing and a test drive lost two of the three the moment
    # they answered a follow-up question.
    #
    # No node ever empties the queue deliberately: `enrich` and
    # `recompute_missing_slots` return exactly the intents they were given.
    # So an empty queue is not an assertion that nothing is open — it is the
    # absence of an opinion, and the accumulated truth survives it.
    if isinstance(incoming, IntentQueue):
        if not incoming.intents and current.intents:
            return current
        return incoming

    return current.merge(incoming)


def take_last(current: Any, incoming: Any) -> Any:
    """Last write wins. The default for single-valued fields."""
    return current if incoming is None else incoming


def concat_sequence(
    current: Sequence[Any] | None, incoming: Sequence[Any] | None
) -> tuple[Any, ...]:
    """Append incoming onto current, tolerating list/tuple round-trips.

    `operator.add` seems like the obvious reducer for accumulating entities
    and actions, and it works within a single graph invocation. It fails
    across invocations on the same conversation, because the checkpointer
    serialises state and rehydrates tuples as lists — so on the next turn
    the reducer runs `list + tuple` and Python refuses. Handling both types
    on both sides is what makes multi-turn conversations survive a resume.
    """
    left = tuple(current) if current else ()
    right = tuple(incoming) if incoming else ()
    return left + right


class GraphState(TypedDict, total=False):
    """What flows between nodes.

    Deliberately flat and typed rather than a bag of dicts: a node that
    mistypes a key should fail at the boundary, not silently write a field
    nobody reads.
    """

    # ── Identity ──────────────────────────────────────────────────────
    conversation_id: str
    inquiry_id: str
    trace_id: str
    customer_id: str | None
    channel: str

    # ── Layer 1: understanding ────────────────────────────────────────
    raw_text: str
    normalized_text: Annotated[str | None, take_last]
    language: Annotated[Any, take_last]
    sentiment: Annotated[Any, take_last]
    intents: Annotated[IntentQueue, merge_intents]
    entities: Annotated[tuple[ExtractedEntity, ...], concat_sequence]
    # Full conversation history, authoritative from the API — the graph
    # doesn't accumulate it turn by turn (that would race with the API's
    # own transcript writes). Passed in verbatim each turn so the
    # generator has the customer's actual words, not just intent labels.
    transcript: Annotated[tuple[ConversationTurn, ...], take_last]

    # ── Layer 2: planning ─────────────────────────────────────────────
    plan: Annotated[Plan | None, take_last]

    # ── Layer 3: decision ─────────────────────────────────────────────
    confidence: Annotated[ConfidenceVector | None, take_last]
    routing: Annotated[RoutingDecision | None, take_last]

    # ── Layer 4: execution ────────────────────────────────────────────
    chunks: Annotated[tuple[RetrievedChunk, ...], take_last]
    tool_results: Annotated[dict[str, Any], operator.or_]
    actions: Annotated[tuple[ExecutionAction, ...], concat_sequence]
    draft: Annotated[DraftReply | None, take_last]
    grounding: Annotated[GroundingReport | None, take_last]

    # ── Control flow ──────────────────────────────────────────────────
    # Set when the graph pauses. The conversation is durable and resumable at
    # exactly the step it stopped on.
    awaiting: Annotated[str | None, take_last]
    # The slot the previous turn asked about, carried into this turn as
    # context for entity extraction. A two-word answer to "which model?" is
    # extractable only when the extractor knows the question — otherwise a
    # fragment reads as low-confidence and the conversation loops.
    previous_awaiting: Annotated[str | None, take_last]
    escalated: Annotated[bool, take_last]
    human_handled: Annotated[bool, take_last]
    retry_count: Annotated[int, take_last]

    # ── Telemetry ─────────────────────────────────────────────────────
    spans: Annotated[list[Span], operator.add]

    # ── Memory ────────────────────────────────────────────────────────
    conversation: Annotated[ConversationState | None, take_last]


def initial_state(
    *,
    conversation_id: str,
    inquiry_id: str,
    trace_id: str,
    raw_text: str,
    channel: str,
    customer_id: str | None = None,
    previous_awaiting: str | None = None,
    transcript: tuple[ConversationTurn, ...] = (),
) -> GraphState:
    return GraphState(
        conversation_id=conversation_id,
        inquiry_id=inquiry_id,
        trace_id=trace_id,
        customer_id=customer_id,
        channel=channel,
        raw_text=raw_text,
        intents=IntentQueue(),
        entities=(),
        chunks=(),
        tool_results={},
        actions=(),
        spans=[],
        escalated=False,
        human_handled=False,
        retry_count=0,
        awaiting=None,
        previous_awaiting=previous_awaiting,
        transcript=transcript,
    )
