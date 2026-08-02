"""Graph nodes.

Every node is a thin adapter: read typed state, call an injected service,
write a typed delta, emit one wide span. No business logic lives here — it
lives in `services/`, which is testable without a graph, and in
`domain/policies/`, which is editable without a deployment.

Nodes are grouped by cognitive layer, and each one is tagged with its layer so
the admin UI can show where latency and cost actually go.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.logging import get_logger
from app.domain.entities import ConversationState, Span
from app.domain.enums import (
    Channel,
    CognitiveLayer,
    IntentCategory,
    RoutingTier,
    SpanStatus,
)
from app.domain.value_objects import TokenUsage
from app.graph.state import GraphState
from app.services.decision import confidence as confidence_engine
from app.services.decision.router import route
from app.services.execution.grounding import vacuously_grounded, validate_grounding
from app.services.planning.planner import build_plan, enrich, recompute_missing_slots

logger = get_logger(__name__)

NodeFn = Callable[[GraphState], Awaitable[dict[str, Any]]]


def _span(
    state: GraphState,
    node: str,
    layer: CognitiveLayer,
    started: float,
    *,
    usage: TokenUsage | None = None,
    model: str | None = None,
    provider: str | None = None,
    error: str | None = None,
    **attributes: Any,
) -> Span:
    """One wide event per node execution.

    Wide and richly attributed rather than split across metrics, logs and
    traces — the trace view, the cost dashboard and the confidence breakdown
    all read from this one shape.
    """
    return Span(
        trace_id=state["trace_id"],
        conversation_id=state["conversation_id"],
        node=node,
        layer=layer,
        status=SpanStatus.ERROR if error else SpanStatus.OK,
        latency_ms=round((time.perf_counter() - started) * 1000, 2),
        model=model,
        provider=provider,
        usage=usage or TokenUsage(),
        attributes=attributes,
        error=error,
    )


def build_nodes(deps: Any) -> dict[str, NodeFn]:
    """Construct every node bound to the injected dependency container."""

    # ══════════════════════════════════════════════════════════════════
    # Layer 1 — Understanding (the only layer that calls a model)
    # ══════════════════════════════════════════════════════════════════
    async def normalize(state: GraphState) -> dict[str, Any]:
        started = time.perf_counter()
        text = deps.understanding.normalize(state["raw_text"])
        return {
            "normalized_text": text,
            "spans": [
                _span(state, "normalize", CognitiveLayer.UNDERSTANDING, started,
                      original_length=len(state["raw_text"]), normalized_length=len(text))
            ],
        }

    async def detect_language(state: GraphState) -> dict[str, Any]:
        started = time.perf_counter()
        profile = deps.understanding.detect_language(state.get("normalized_text") or "")
        return {
            "language": profile,
            "spans": [
                _span(state, "detect_language", CognitiveLayer.UNDERSTANDING, started,
                      primary=profile.primary.value, is_mixed=profile.is_mixed,
                      is_arabizi=profile.is_arabizi,
                      arabic_ratio=round(profile.arabic_char_ratio, 3))
            ],
        }

    async def discover_intents(state: GraphState) -> dict[str, Any]:
        started = time.perf_counter()
        text = state.get("normalized_text") or state["raw_text"]
        previous_awaiting = state.get("previous_awaiting")
        try:
            intents, usage = await deps.understanding.discover_intents(
                text, previous_awaiting=previous_awaiting
            )
        except Exception as exc:
            # A failure to understand is not a failure to respond: fall
            # through with nothing discovered and let confidence route it to
            # a person.
            logger.exception("intent_discovery_failed")
            return {
                "spans": [
                    _span(state, "discover_intents", CognitiveLayer.UNDERSTANDING,
                          started, error=str(exc))
                ]
            }

        return {
            "intents": intents,
            "spans": [
                _span(state, "discover_intents", CognitiveLayer.UNDERSTANDING, started,
                      usage=usage, model=deps.router.model_for_fast(),
                      provider=deps.router.provider_name,
                      intent_count=len(intents),
                      categories=[i.category.value for i in intents])
            ],
        }

    async def extract_entities(state: GraphState) -> dict[str, Any]:
        started = time.perf_counter()
        text = state.get("normalized_text") or state["raw_text"]
        previous_awaiting = state.get("previous_awaiting")
        try:
            entities, usage = await deps.understanding.extract_entities(
                text, previous_awaiting=previous_awaiting
            )
        except Exception as exc:
            logger.exception("entity_extraction_failed")
            return {
                "spans": [
                    _span(state, "extract_entities", CognitiveLayer.UNDERSTANDING,
                          started, error=str(exc))
                ]
            }

        return {
            "entities": entities,
            "spans": [
                _span(state, "extract_entities", CognitiveLayer.UNDERSTANDING, started,
                      usage=usage, model=deps.router.model_for_fast(),
                      provider=deps.router.provider_name,
                      slots=[e.type.value for e in entities])
            ],
        }

    async def score_sentiment(state: GraphState) -> dict[str, Any]:
        started = time.perf_counter()
        text = state.get("normalized_text") or state["raw_text"]
        sentiment, usage = await deps.understanding.score_sentiment(text)
        return {
            "sentiment": sentiment,
            "spans": [
                _span(state, "score_sentiment", CognitiveLayer.UNDERSTANDING, started,
                      usage=usage, polarity=sentiment.polarity.value,
                      urgency=sentiment.urgency.value)
            ],
        }

    # ══════════════════════════════════════════════════════════════════
    # Layer 2 — Planning (deterministic; no model calls)
    # ══════════════════════════════════════════════════════════════════
    async def plan(state: GraphState) -> dict[str, Any]:
        started = time.perf_counter()

        conversation = _rebuild_conversation(state)
        queue = enrich(state["intents"])
        queue = recompute_missing_slots(queue, conversation.filled_slots)
        built = build_plan(queue)

        return {
            "intents": queue,
            "plan": built,
            "spans": [
                _span(state, "plan", CognitiveLayer.PLANNING, started,
                      step_count=len(built.steps), next_action=built.next_action,
                      missing_slots=[s.value for s in built.all_missing_slots],
                      departments=[s.department.value for s in built.steps])
            ],
        }

    # ══════════════════════════════════════════════════════════════════
    # Layer 4 — Execution: retrieval and tools run before the decision so
    # that retrieval quality can inform it.
    # ══════════════════════════════════════════════════════════════════
    async def retrieve(state: GraphState) -> dict[str, Any]:
        started = time.perf_counter()
        query = state.get("normalized_text") or state["raw_text"]

        try:
            result = await deps.retriever.search_for(query, state["intents"])
        except Exception as exc:
            logger.warning("retrieval_failed", error=str(exc))
            return {
                "spans": [
                    _span(state, "retrieve", CognitiveLayer.EXECUTION, started,
                          error=str(exc))
                ]
            }

        return {
            "chunks": result.chunks,
            "spans": [
                _span(state, "retrieve", CognitiveLayer.EXECUTION, started,
                      chunk_count=len(result.chunks),
                      dense_ms=result.dense_ms, sparse_ms=result.sparse_ms,
                      fusion_ms=result.fusion_ms, rerank_ms=result.rerank_ms,
                      top_score=result.chunks[0].effective_score if result.chunks else None)
            ],
        }

    async def call_tools(state: GraphState) -> dict[str, Any]:
        started = time.perf_counter()
        conversation = _rebuild_conversation(state)
        results = await deps.tools.run_for(conversation)
        return {
            "tool_results": results,
            "spans": [
                _span(state, "call_tools", CognitiveLayer.EXECUTION, started,
                      tools_run=sorted(results))
            ],
        }

    # ══════════════════════════════════════════════════════════════════
    # Layer 3 — Decision (deterministic; no model calls)
    # ══════════════════════════════════════════════════════════════════
    async def score_confidence(state: GraphState) -> dict[str, Any]:
        started = time.perf_counter()
        conversation = _rebuild_conversation(state)

        # Any quoted money amount raises commercial exposure and is fed into
        # the risk signal.
        has_money = any(
            key in state.get("tool_results", {}) for key in ("emi", "trade_in")
        )

        vector = confidence_engine.evaluate(
            conversation,
            chunks=state.get("chunks", ()),
            grounding=state.get("grounding"),
            has_financial_figure=has_money,
        )

        return {
            "confidence": vector,
            "spans": [
                _span(state, "score_confidence", CognitiveLayer.DECISION, started,
                      decision_score=vector.decision_score,
                      weakest_signal=vector.weakest_signal.value,
                      # All six signals on the span, so the admin breakdown
                      # reads from the trace rather than recomputing.
                      signals=vector.as_dict())
            ],
        }

    async def decide(state: GraphState) -> dict[str, Any]:
        started = time.perf_counter()
        conversation = _rebuild_conversation(state)
        vector = state.get("confidence")

        if vector is None:
            # Scoring failed upstream. A conversation with no measured
            # confidence must not be automated — fall through to a person
            # rather than assuming the best.
            vector = confidence_engine.zero_confidence()

        decision = route(
            conversation,
            vector,
            grounding=state.get("grounding"),
            allow_auto_send=deps.settings.allow_auto_send,
        )

        return {
            "routing": decision,
            "spans": [
                _span(state, "decide", CognitiveLayer.DECISION, started,
                      tier=decision.tier.value,
                      department=decision.department.value if decision.department else None,
                      model_tier=decision.model_tier.value if decision.model_tier else None,
                      rule_id=decision.rule_id,
                      overrides=list(decision.overrides_applied),
                      rationale=decision.rationale)
            ],
        }

    # ══════════════════════════════════════════════════════════════════
    # Layer 4 — Execution: actuation and generation
    # ══════════════════════════════════════════════════════════════════
    async def actuate(state: GraphState) -> dict[str, Any]:
        """Perform the side effects the coordinator used to do by hand.

        Every action carries an idempotency key, so a redelivered webhook can
        never double-book a Saturday slot.
        """
        started = time.perf_counter()
        conversation = _rebuild_conversation(state)
        decision = state.get("routing")

        # Nothing externally visible happens while a conversation is bound
        # for human review. The reviewer decides what the customer sees.
        if decision is None or decision.tier is RoutingTier.HUMAN:
            return {
                "spans": [
                    _span(state, "actuate", CognitiveLayer.EXECUTION, started,
                          skipped="pending human review")
                ]
            }

        actions = await deps.actuator.execute(conversation, state.get("tool_results", {}))
        return {
            "actions": tuple(actions),
            "spans": [
                _span(state, "actuate", CognitiveLayer.EXECUTION, started,
                      performed=[a.type.value for a in actions],
                      statuses=[a.status.value for a in actions])
            ],
        }

    async def clarify(state: GraphState) -> dict[str, Any]:
        """Ask for exactly the one fact that unblocks the most work.

        The system is not confused here — it knows precisely which slot is
        empty. So it asks that question, not "could you rephrase?".

        Which slot gets asked about is decided by policy, never by a model.
        The model, when one is configured, only chooses the words — and the
        writer falls back to the template whenever it cannot vouch for them.
        """
        started = time.perf_counter()
        result = await deps.clarifier.write(
            plan=state.get("plan"),
            language=state.get("language"),
            conversation=_rebuild_conversation(state),
            tool_results=state.get("tool_results", {}),
        )

        return {
            "draft": result.draft,
            "awaiting": result.awaiting,
            "spans": [
                _span(state, "clarify", CognitiveLayer.EXECUTION, started,
                      usage=result.usage, model=result.model,
                      provider=result.provider,
                      asked_for=result.awaiting, source=result.source,
                      bilingual=result.draft.is_bilingual,
                      fallback_reason=result.fallback_reason)
            ],
        }

    async def generate(state: GraphState) -> dict[str, Any]:
        started = time.perf_counter()
        conversation = _rebuild_conversation(state)
        decision = state.get("routing")

        draft, usage, model = await deps.generator.draft(
            conversation,
            chunks=state.get("chunks", ()),
            tool_results=state.get("tool_results", {}),
            tier=decision.model_tier if decision else None,
            allow_auto_send=deps.settings.allow_auto_send,
        )

        return {
            "draft": draft,
            "spans": [
                _span(state, "generate", CognitiveLayer.EXECUTION, started,
                      usage=usage, model=model, provider=deps.router.provider_name,
                      bilingual=draft.is_bilingual, length=len(draft.en))
            ],
        }

    async def validate(state: GraphState) -> dict[str, Any]:
        """Check the draft against the evidence that was actually retrieved."""
        started = time.perf_counter()
        draft = state.get("draft")

        if draft is None:
            return {
                "spans": [
                    _span(state, "validate_grounding", CognitiveLayer.EXECUTION, started,
                          skipped="no draft")
                ]
            }

        # A turn that is purely social has no factual content to check. Running
        # the corpus-overlap test on "Good morning! How can I help?" scored it
        # zero against a corpus of finance documents and escalated a greeting
        # to a human — the check reporting a problem it had invented.
        if _is_only_small_talk(state):
            return {
                "grounding": vacuously_grounded(),
                "spans": [
                    _span(state, "validate_grounding", CognitiveLayer.EXECUTION, started,
                          skipped="nothing asserted", verdict="grounded")
                ],
            }

        report = validate_grounding(
            draft.en, state.get("chunks", ()), state.get("tool_results", {})
        )

        updates: dict[str, Any] = {
            "grounding": report,
            "spans": [
                _span(state, "validate_grounding", CognitiveLayer.EXECUTION, started,
                      verdict=report.verdict.value,
                      faithfulness=report.faithfulness_score,
                      unsupported=len(report.unsupported_claims),
                      unsupported_numeric=report.has_unsupported_numeric_claim)
            ],
        }

        # Increment on any failure — the previous code checked retry_count
        # but never bumped it, so soft grounding failures looped until
        # LangGraph's recursion limit killed the whole run.
        if not report.passes:
            updates["retry_count"] = state.get("retry_count", 0) + 1

        return updates

    async def escalate_human(state: GraphState) -> dict[str, Any]:
        """Hand to a person, with everything they need to decide quickly."""
        started = time.perf_counter()
        conversation = _rebuild_conversation(state)
        decision = state["routing"]

        item = await deps.human_queue.enqueue_for(
            conversation, decision, draft=state.get("draft")
        )

        return {
            "escalated": True,
            "awaiting": "human_review",
            "spans": [
                _span(state, "escalate_human", CognitiveLayer.DECISION, started,
                      review_id=item.id, reason=item.reason.value,
                      department=item.department.value if item.department else None)
            ],
        }

    async def persist_memory(state: GraphState) -> dict[str, Any]:
        started = time.perf_counter()
        conversation = _rebuild_conversation(state)
        await deps.memory.persist(conversation, state.get("spans", []))
        return {
            "conversation": conversation,
            "spans": [
                _span(state, "persist_memory", CognitiveLayer.EXECUTION, started,
                      intents_open=len(conversation.intents.unresolved),
                      intents_total=len(conversation.intents))
            ],
        }

    return {
        "normalize": normalize,
        "detect_language": detect_language,
        "discover_intents": discover_intents,
        "extract_entities": extract_entities,
        "score_sentiment": score_sentiment,
        # Named `build_plan` rather than `plan`: LangGraph reserves node names
        # against state keys, and `plan` is the state field this writes.
        "build_plan": plan,
        "retrieve": retrieve,
        "call_tools": call_tools,
        "score_confidence": score_confidence,
        "decide": decide,
        "actuate": actuate,
        "clarify": clarify,
        "generate": generate,
        "validate_grounding": validate,
        "escalate_human": escalate_human,
        "persist_memory": persist_memory,
    }


def _is_only_small_talk(state: GraphState) -> bool:
    """Whether this turn is social and nothing else.

    Deliberately strict: one real request alongside the greeting and the whole
    reply is validated as normal. Hours and location are *not* small talk —
    they are factual answers that must stay grounded in the corpus.
    """
    unresolved = state["intents"].unresolved
    return bool(unresolved) and all(
        intent.category is IntentCategory.SMALL_TALK for intent in unresolved
    )


def _rebuild_conversation(state: GraphState) -> ConversationState:
    """Project graph state onto the domain conversation entity.

    Services take domain objects, not graph dicts, so they stay testable
    without importing LangGraph. The transcript comes through so the
    generator knows what the customer literally said — without it the LLM
    sees intent categories but no words, and writes stock filler.
    """
    conversation = ConversationState(
        conversation_id=state["conversation_id"],
        customer_id=state.get("customer_id"),
        channel=Channel(state.get("channel", Channel.WEB_FORM.value)),
        language=state.get("language"),
        sentiment=state.get("sentiment"),
        intents=state.get("intents") or ConversationState.model_fields["intents"].default,
        entities=state.get("entities", ()),
        plan=state.get("plan"),
        routing=state.get("routing"),
        draft=state.get("draft"),
        human_handled=state.get("human_handled", False),
        transcript=state.get("transcript", ()),
    )
    return conversation


__all__ = ["IntentCategory", "build_nodes"]
