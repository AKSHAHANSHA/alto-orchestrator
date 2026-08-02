"""HTTP surface.

Routers translate between the wire format and the application layer, and do
nothing else. No business logic, no direct infrastructure access — a route
handler that started making decisions would put those decisions outside the
places designed to make them explainable.
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.api.v1.schemas import (
    ChunkDTO,
    ConfidenceDTO,
    ConversationSummary,
    EmiRequestDTO,
    GroundingDTO,
    InquiryRequest,
    InquiryResponse,
    IntentDTO,
    MetricsResponse,
    ReplyDTO,
    ResolveReviewRequest,
    ReviewItemDTO,
    RoutingDTO,
    SpanDTO,
    ValuationRequestDTO,
)
from app.core.errors import AltoError, ToolError
from app.core.logging import get_logger
from app.domain.enums import Department, EntityType, IntentCategory, ReviewOutcome
from app.graph.state import initial_state
from app.services.execution.appointments import SlotUnavailableError
from app.services.execution.finance_tools import EmiRequest, calculate_emi
from app.services.execution.valuation_tools import ValuationRequest, estimate_trade_in

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1")


def _container(request: Request) -> Any:
    return request.app.state.container


def _graph(request: Request) -> Any:
    return request.app.state.graph


# ══════════════════════════════════════════════════════════════════════
# Inquiries
# ══════════════════════════════════════════════════════════════════════
@router.post("/inquiries", response_model=InquiryResponse, tags=["customer"])
async def submit_inquiry(payload: InquiryRequest, request: Request) -> InquiryResponse:
    """Run a customer message through the orchestrator."""
    container = _container(request)
    graph = _graph(request)

    conversation_id = payload.conversation_id or f"conv_{uuid.uuid4().hex[:12]}"
    trace_id = f"trc_{uuid.uuid4().hex[:12]}"

    # If a human has taken over, do not run the graph — the assistant's job
    # is done and the customer is talking to a person now. Record the
    # customer's message and, if there isn't already a card in the queue
    # for this conversation, put one there. Without this the customer sees
    # "handled by our team" while the operator's queue stays empty.
    existing = await container.memory.get(conversation_id)
    if existing and existing.human_handled:
        await container.memory.append_turn(conversation_id, "customer", payload.message)
        refreshed = await container.memory.get(conversation_id)
        if refreshed is not None:
            await container.human_queue.enqueue_customer_followup(refreshed)
        return _to_response(
            {"conversation": refreshed or existing, "spans": []},
            conversation_id,
            trace_id,
            awaiting_human=True,
        )

    # Record the customer's message before the graph runs, so the reviewer
    # can always see what was actually asked — even on a run that crashed.
    await container.memory.append_turn(conversation_id, "customer", payload.message)

    # Carry the slot the previous turn asked about into the next turn's
    # understanding prompts. A two-word answer to "which model?" needs to
    # be interpreted as an answer to that question, not as a fresh message.
    previous_awaiting = _resolve_previous_awaiting(existing)

    # Full transcript (now including the message we just appended) so the
    # generator sees the customer's actual words plus the assistant's own
    # previous replies. Without this, the generator has intent categories
    # and retrieved docs but no idea what the customer said, and writes
    # stock corporate filler.
    refreshed = await container.memory.get(conversation_id)
    transcript = refreshed.transcript if refreshed else ()

    try:
        result = await graph.ainvoke(
            initial_state(
                conversation_id=conversation_id,
                inquiry_id=f"inq_{uuid.uuid4().hex[:12]}",
                trace_id=trace_id,
                raw_text=payload.message,
                channel=payload.channel,
                customer_id=payload.customer_id,
                previous_awaiting=previous_awaiting,
                transcript=transcript,
            ),
            config={"configurable": {"thread_id": conversation_id}},
        )
    except AltoError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_dict()) from exc

    # Record the assistant's reply too, so a customer refreshing the page or
    # a reviewer opening the queue item sees the same thing.
    draft = result.get("draft")
    if draft is not None and not result.get("escalated"):
        await container.memory.append_turn(conversation_id, "assistant", draft.en)

    response = _to_response(result, conversation_id, trace_id)

    # Detect a booking-ready state and replace the reply with a call to
    # show the calendar. The customer picks a slot inline instead of the
    # assistant asking for a date and time in words.
    if _should_show_calendar(result):
        # Carry the graph's own reply through instead of discarding it. It
        # holds the vehicle's availability and specs and whatever other open
        # requests are still outstanding; replacing it outright meant a
        # booking-ready message showed the customer nothing but the picker.
        prologue = (
            draft.en.strip()
            if draft is not None and not result.get("escalated")
            else ""
        )
        call_to_action = (
            "Perfect — pick a 2-hour slot for your test drive "
            "using the calendar below."
        )
        response = response.model_copy(
            update={
                "awaiting": "test_drive_slot",
                "reply": ReplyDTO(
                    en=(
                        f"{prologue}\n\n{call_to_action}"
                        if prologue
                        else call_to_action
                    ),
                    ar=None,
                    is_bilingual=False,
                    requires_human_approval=False,
                ),
            }
        )
        # Only the call to action goes to the transcript — the prologue was
        # already appended above, and appending it again would repeat it.
        await container.memory.append_turn(
            conversation_id, "assistant", call_to_action
        )

    return response


def _should_show_calendar(result: dict[str, Any]) -> bool:
    """Whether the customer is ready to pick a slot.

    True when the primary intent is a test-drive booking and we have a
    vehicle to book it for — the only remaining information is the slot,
    which the calendar handles better than a text question.
    """
    intents = result.get("intents")
    if intents is None:
        return False
    primary = intents.primary
    if primary is None or primary.category is not IntentCategory.TEST_DRIVE_BOOKING:
        return False

    entity_types = {e.type for e in result.get("entities", ())}
    has_vehicle = (
        EntityType.NEW_VEHICLE_BRAND in entity_types
        and EntityType.NEW_VEHICLE_MODEL in entity_types
    )
    if not has_vehicle:
        return False

    # Only trigger the calendar when the missing information is a date or
    # time. If the customer has already stated a date, the graph is
    # progressing toward actuation and we do not interrupt it.
    missing = set(primary.missing_slots)
    needs_date_or_time = bool(
        missing & {EntityType.PREFERRED_DATE, EntityType.PREFERRED_TIME}
    )
    return needs_date_or_time or (not missing and not primary.depends_on)


@router.get("/conversations/{conversation_id}", tags=["customer"])
async def get_conversation(
    conversation_id: str, request: Request
) -> dict[str, Any]:
    """Full conversation state, including transcript.

    Serves two views: the customer restoring a session on page reload, and
    the operations view showing a reviewer what actually happened.
    """
    state = await _container(request).memory.get(conversation_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    return {
        "conversation_id": state.conversation_id,
        "customer_id": state.customer_id,
        "channel": state.channel.value,
        "human_handled": state.human_handled,
        "transcript": [
            {"role": turn.role, "text": turn.text, "at": turn.at.isoformat()}
            for turn in state.transcript
        ],
        "open_intents": [
            {
                "id": i.id,
                "category": i.category.value,
                "status": i.status.value,
                "department": i.department.value if i.department else None,
                "missing_slots": [s.value for s in i.missing_slots],
            }
            for i in state.intents.unresolved
        ],
    }


@router.get("/conversations/{conversation_id}/stream", tags=["customer"])
async def stream_inquiry(
    conversation_id: str, message: str, request: Request
) -> StreamingResponse:
    """Server-sent events: node transitions as they happen, then the answer.

    Streaming node events rather than only tokens is deliberate. The customer
    sees progress from the first stage, and the admin workflow graph animates
    from the same feed — one mechanism serving both.
    """
    graph = _graph(request)
    trace_id = f"trc_{uuid.uuid4().hex[:12]}"

    async def events() -> Any:
        try:
            async for chunk in graph.astream(
                initial_state(
                    conversation_id=conversation_id,
                    inquiry_id=f"inq_{uuid.uuid4().hex[:12]}",
                    trace_id=trace_id,
                    raw_text=message,
                    channel="web_form",
                ),
                config={"configurable": {"thread_id": conversation_id}},
            ):
                for node, delta in chunk.items():
                    spans = delta.get("spans") or []
                    yield _sse(
                        "node",
                        {
                            "node": node,
                            "layer": spans[0].layer.value if spans else None,
                            "latency_ms": spans[0].latency_ms if spans else 0,
                            "attributes": spans[0].attributes if spans else {},
                        },
                    )

            state = await graph.aget_state(
                {"configurable": {"thread_id": conversation_id}}
            )
            payload = _to_response(state.values, conversation_id, trace_id)
            yield _sse("result", json.loads(payload.model_dump_json()))
        except Exception as exc:
            logger.exception("stream_failed")
            yield _sse("error", {"message": str(exc)})
        finally:
            yield _sse("done", {})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _resolve_previous_awaiting(state: Any) -> str | None:
    """Read the slot the last completed turn was asking about.

    Cheap enough to inline: reading the intents' missing slots off the most
    recent conversation state. Not persisted separately — there is no need
    to add a column when the data is already there.
    """
    if state is None:
        return None
    for intent in state.intents.unresolved:
        if intent.missing_slots:
            return str(intent.missing_slots[0].value)
    return None


@router.get("/conversations", response_model=list[ConversationSummary], tags=["admin"])
async def list_conversations(request: Request, limit: int = 50) -> list[ConversationSummary]:
    states = await _container(request).memory.list_active(limit)
    return [ConversationSummary.of(s) for s in states]


@router.get("/conversations/{conversation_id}/trace", tags=["admin"])
async def get_trace(conversation_id: str, request: Request) -> dict[str, Any]:
    """Every span for a conversation, in execution order."""
    spans = await _container(request).memory.spans_for(conversation_id)
    if not spans:
        raise HTTPException(status_code=404, detail="No trace for that conversation.")

    return {
        "conversation_id": conversation_id,
        "spans": [SpanDTO.of(s).model_dump() for s in spans],
        "total_latency_ms": round(sum(s.latency_ms for s in spans), 2),
        "total_cost_usd": round(sum(s.usage.cost_usd for s in spans), 6),
        "total_tokens": sum(s.usage.total_tokens for s in spans),
    }


# ══════════════════════════════════════════════════════════════════════
# Human review
# ══════════════════════════════════════════════════════════════════════
@router.get("/admin/human-queue", response_model=list[ReviewItemDTO], tags=["admin"])
async def human_queue(
    request: Request, department: str | None = Query(default=None)
) -> list[ReviewItemDTO]:
    """Open review items with their full conversation transcripts attached."""
    container = _container(request)
    items = await container.human_queue.list_open()
    if department:
        wanted = Department(department)
        items = [i for i in items if i.department is wanted]

    result: list[ReviewItemDTO] = []
    for item in items:
        dto = ReviewItemDTO.of(item)
        # Attach the transcript so the reviewer can see the whole exchange,
        # not just the drafted reply — this is the difference between review
        # as a decision and review as an investigation.
        state = await container.memory.get(item.conversation_id)
        if state:
            dto = dto.model_copy(
                update={
                    "transcript": [
                        {"role": t.role, "text": t.text, "at": t.at.isoformat()}
                        for t in state.transcript
                    ],
                }
            )
        result.append(dto)
    return result


@router.post("/admin/human-queue/{item_id}/resolve", tags=["admin"])
async def resolve_review(
    item_id: str, payload: ResolveReviewRequest, request: Request
) -> dict[str, Any]:
    """Close a review item, and — for approved and edited outcomes — deliver
    the reply back to the customer's transcript.

    Marks the conversation as human-handled either way, which is a hard
    routing override: automation does not quietly resume after a person has
    taken over.
    """
    container = _container(request)
    queue = container.human_queue
    item = await queue.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="No such review item.")
    if not item.is_open:
        raise HTTPException(status_code=409, detail="That item is already resolved.")

    try:
        outcome = ReviewOutcome(payload.outcome)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown outcome '{payload.outcome}'.",
        ) from exc

    # For outcomes that produce a customer-visible reply, work out which text
    # actually gets delivered — the operator's edited copy if supplied, else
    # the drafted one.
    delivered_text: str | None = None
    if outcome in {ReviewOutcome.APPROVED, ReviewOutcome.EDITED}:
        delivered_text = payload.final_text or (item.draft.en if item.draft else None)
        if not delivered_text:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Cannot approve or edit a review with no text — the draft is "
                    "empty and no final_text was supplied."
                ),
            )
        await container.memory.append_turn(
            item.conversation_id, "assistant", delivered_text
        )

    # Reassignment must name a target department. Without one the reviewer is
    # closing the item without actually reassigning anything.
    if outcome is ReviewOutcome.REASSIGNED:
        if not payload.reassign_to:
            raise HTTPException(
                status_code=422,
                detail="Reassign requires reassign_to (target department).",
            )
        try:
            new_dept = Department(payload.reassign_to)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown department '{payload.reassign_to}'.",
            ) from exc

        note = (
            f"Reassigned to {new_dept.value.replace('_', ' ')} by {payload.reviewer}."
        )
        await container.memory.append_turn(item.conversation_id, "system", note)
        item = item.model_copy(update={"department": new_dept})

    # Every terminal outcome marks the conversation human-handled, which stops
    # the graph from taking it back over on the next customer message.
    await container.memory.mark_human_handled(item.conversation_id)

    resolved = item.resolve(outcome, payload.reviewer, delivered_text)
    await queue.save(resolved)

    logger.info(
        "review_resolved", item_id=item_id, outcome=outcome.value, reviewer=payload.reviewer
    )
    return {
        "id": resolved.id,
        "outcome": outcome.value,
        "resolved_at": resolved.resolved_at,
        "delivered_text": delivered_text,
        "department": resolved.department.value if resolved.department else None,
    }


@router.post("/admin/conversations/{conversation_id}/reply", tags=["admin"])
async def human_reply(
    conversation_id: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    """Send a live message from a human operator into an ongoing conversation.

    Used for the follow-up messages after a conversation has been handed to
    a person: they can keep replying without going through the review queue
    for each turn. The message lands in the transcript so the customer sees
    it on their next fetch.
    """
    container = _container(request)
    text = str(payload.get("text", "")).strip()
    reviewer = str(payload.get("reviewer", "operator"))

    if not text:
        raise HTTPException(status_code=422, detail="Reply text is required.")

    state = await container.memory.get(conversation_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    await container.memory.append_turn(conversation_id, "assistant", text)
    await container.memory.mark_human_handled(conversation_id)

    logger.info("human_reply_sent", conversation_id=conversation_id, reviewer=reviewer)
    return {
        "conversation_id": conversation_id,
        "delivered_text": text,
        "reviewer": reviewer,
    }


# ══════════════════════════════════════════════════════════════════════
# Deterministic tools, exposed directly
# ══════════════════════════════════════════════════════════════════════
@router.post("/tools/emi", tags=["tools"])
async def emi(payload: EmiRequestDTO) -> dict[str, Any]:
    """Instalment calculation. Never performed by a model."""
    try:
        quote = calculate_emi(
            EmiRequest(
                vehicle_price=payload.vehicle_price,
                down_payment=payload.down_payment,
                tenure_months=payload.tenure_months,
                salary_transfer=payload.salary_transfer,
                monthly_income=payload.monthly_income,
            )
        )
    except ToolError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_dict()) from exc
    return quote.model_dump()


@router.post("/tools/trade-in", tags=["tools"])
async def trade_in(payload: ValuationRequestDTO, request: Request) -> dict[str, Any]:
    """Trade-in range. Declines rather than guessing when out of range."""
    from datetime import UTC, datetime

    catalog = _container(request).catalog
    record = await catalog.best_match(payload.brand, payload.model, payload.year)

    try:
        estimate = estimate_trade_in(
            ValuationRequest(
                brand=payload.brand,
                model=payload.model,
                year=payload.year,
                mileage_km=payload.mileage_km,
                condition=payload.condition,
                base_msrp=record.msrp if record else None,
                current_year=datetime.now(UTC).year,
            )
        )
    except ToolError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_dict()) from exc
    return estimate.model_dump()


# ══════════════════════════════════════════════════════════════════════
# Test-drive appointments
# ══════════════════════════════════════════════════════════════════════
@router.get("/appointments/slots", tags=["customer"])
async def list_slots(
    request: Request, days: int = Query(default=14, ge=1, le=30)
) -> dict[str, Any]:
    """Available 2-hour slots for the next `days` days.

    Consumed by the calendar widget inside the customer chat once the
    assistant has confirmed the vehicle to book. Past and taken slots are
    filtered here so the client cannot pick something invalid.
    """
    appointments = _container(request).appointments
    slots = appointments.available_slots(horizon_days=days)
    return {
        "slots": [s.to_dict() for s in slots if s.is_available],
        "horizon_days": days,
        "slot_hours": 2,
    }


@router.post("/appointments/book", tags=["customer"])
async def book_slot(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    """Book a slot for a conversation.

    Called by the calendar picker when the customer taps a slot.
    Appends a confirmation turn to the transcript so the assistant's
    message shows the booking details, and returns the booking record.
    """
    container = _container(request)
    conversation_id = str(payload.get("conversation_id") or "").strip()
    slot_id = str(payload.get("slot_id") or "").strip()
    vehicle = str(payload.get("vehicle") or "").strip() or "test drive"
    customer_name = payload.get("customer_name")
    contact_phone = payload.get("contact_phone")

    if not conversation_id or not slot_id:
        raise HTTPException(
            status_code=422,
            detail="conversation_id and slot_id are required.",
        )

    try:
        booking = container.appointments.book_slot(
            conversation_id=conversation_id,
            slot_id=slot_id,
            vehicle=vehicle,
            customer_name=customer_name,
            contact_phone=contact_phone,
        )
    except SlotUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    confirmation = (
        f"Booked! Your test drive of the {vehicle} is confirmed for "
        f"{booking.slot_start.strftime('%A %d %B')}, {booking.time_label}. "
        f"Please bring your Emirates ID and driving licence on the day. "
        f"See you at Legend Motors, Showroom #46, Ras Al Khor."
    )
    await container.memory.append_turn(conversation_id, "assistant", confirmation)

    return {
        "booking": booking.to_dict(),
        "confirmation": confirmation,
    }


@router.get("/admin/appointments", tags=["admin"])
async def list_admin_appointments(request: Request) -> dict[str, Any]:
    """Bookings the operator dashboard shows.

    Marks each item as notified when read — the operator saw it, that's
    the notification. Simple and honest; a real integration would push to
    a CRM or messaging channel.
    """
    container = _container(request)
    bookings = container.appointments.list_recent()
    for booking in bookings:
        container.appointments.mark_notified(booking.id)
    return {"appointments": [b.to_dict() for b in bookings]}


@router.get("/catalog/vehicles", tags=["customer"])
async def vehicles(
    request: Request,
    brand: str | None = None,
    model: str | None = None,
    year: int | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    records = await _container(request).catalog.find(brand, model, year, limit)
    return [r.model_dump() for r in records]


# ══════════════════════════════════════════════════════════════════════
# Metrics
# ══════════════════════════════════════════════════════════════════════
@router.get("/admin/metrics", response_model=MetricsResponse, tags=["admin"])
async def metrics(request: Request) -> MetricsResponse:
    container = _container(request)
    spans = await container.memory.all_spans()
    conversations = await container.memory.list_active(1000)
    reviews = await container.human_queue.list_open()

    by_node: dict[str, list[float]] = defaultdict(list)
    by_layer: dict[str, dict[str, float]] = defaultdict(
        lambda: {"latency_ms": 0.0, "cost_usd": 0.0, "calls": 0.0}
    )

    for span in spans:
        by_node[span.node].append(span.latency_ms)
        layer = by_layer[span.layer.value]
        layer["latency_ms"] += span.latency_ms
        layer["cost_usd"] += span.usage.cost_usd
        layer["calls"] += 1

    escalated = sum(
        1 for c in conversations if c.routing and c.routing.requires_human
    )

    return MetricsResponse(
        conversations=len(conversations),
        open_reviews=len(reviews),
        escalation_rate=round(escalated / len(conversations), 4) if conversations else 0.0,
        total_cost_usd=round(sum(s.usage.cost_usd for s in spans), 6),
        total_tokens=sum(s.usage.total_tokens for s in spans),
        avg_latency_ms=round(sum(s.latency_ms for s in spans) / len(spans), 2) if spans else 0.0,
        provider=container.router.provider_name,
        budget_remaining_usd=round(container.router.budget.remaining, 4),
        retrieval_enabled=container.retrieval_enabled,
        by_node=[
            {
                "node": node,
                "calls": len(times),
                "avg_latency_ms": round(sum(times) / len(times), 2),
                "max_latency_ms": round(max(times), 2),
            }
            for node, times in sorted(by_node.items(), key=lambda kv: -sum(kv[1]))
        ],
        by_layer=[
            {
                "layer": layer,
                "calls": int(values["calls"]),
                "latency_ms": round(values["latency_ms"], 2),
                "cost_usd": round(values["cost_usd"], 6),
            }
            for layer, values in by_layer.items()
        ],
    )


# ══════════════════════════════════════════════════════════════════════
# Projection
# ══════════════════════════════════════════════════════════════════════
def _to_response(
    result: dict[str, Any],
    conversation_id: str,
    trace_id: str,
    *,
    awaiting_human: bool = False,
) -> InquiryResponse:
    """Project graph state onto the wire format.

    ``awaiting_human=True`` skips the graph output entirely and produces a
    response signalling that the conversation is now in human hands. Used
    when a customer message arrives on a conversation that has already been
    handed off — the assistant does not re-engage.
    """
    if awaiting_human:
        return InquiryResponse(
            conversation_id=conversation_id,
            trace_id=trace_id,
            reply=ReplyDTO(
                en=(
                    "A member of our team is handling this conversation and "
                    "will reply to you here shortly."
                ),
                ar=None,
                is_bilingual=False,
                requires_human_approval=False,
            ),
            awaiting="human_response",
            escalated=True,
            total_latency_ms=0.0,
        )

    spans = result.get("spans", [])
    confidence = result.get("confidence")
    routing = result.get("routing")
    draft = result.get("draft")
    grounding = result.get("grounding")
    plan = result.get("plan")
    language = result.get("language")
    sentiment = result.get("sentiment")

    # The queue is absent only when understanding failed outright — in which
    # case there is nothing to project, and the conversation has already been
    # routed to a person.
    queue = result.get("intents")
    ordered_intents = queue.ordered() if queue is not None else ()

    return InquiryResponse(
        conversation_id=conversation_id,
        trace_id=trace_id,
        language=language.model_dump() if language else None,
        sentiment=sentiment.model_dump() if sentiment else None,
        intents=[
            IntentDTO(
                id=i.id,
                category=i.category.value,
                status=i.status.value,
                confidence=i.confidence,
                priority=i.priority,
                is_primary=i.is_primary,
                department=i.department.value if i.department else None,
                missing_slots=[s.value for s in i.missing_slots],
                depends_on=list(i.depends_on),
                evidence=i.evidence,
            )
            for i in ordered_intents
        ],
        entities=[e.model_dump() for e in result.get("entities", ())],
        next_action=plan.next_action if plan else None,
        plan_steps=[s.model_dump() for s in plan.steps] if plan else [],
        confidence=(
            ConfidenceDTO(
                **confidence.as_dict(),
                decision_score=confidence.decision_score,
                weakest_signal=confidence.weakest_signal.value,
            )
            if confidence
            else None
        ),
        routing=(
            RoutingDTO(
                tier=routing.tier.value,
                department=routing.department.value if routing.department else None,
                model_tier=routing.model_tier.value if routing.model_tier else None,
                rule_id=routing.rule_id,
                rationale=routing.rationale,
                overrides_applied=list(routing.overrides_applied),
            )
            if routing
            else None
        ),
        reply=(
            ReplyDTO(
                en=draft.en,
                ar=draft.ar,
                is_bilingual=draft.is_bilingual,
                requires_human_approval=draft.requires_human_approval,
            )
            if draft
            else None
        ),
        grounding=(
            GroundingDTO(
                verdict=grounding.verdict.value,
                faithfulness_score=grounding.faithfulness_score,
                total_claims=len(grounding.claims),
                unsupported_claims=len(grounding.unsupported_claims),
                has_unsupported_numeric_claim=grounding.has_unsupported_numeric_claim,
            )
            if grounding
            else None
        ),
        chunks=[ChunkDTO.of(c) for c in result.get("chunks", ())],
        actions=[a.model_dump() for a in result.get("actions", ())],
        escalated=result.get("escalated", False),
        awaiting=result.get("awaiting"),
        total_latency_ms=round(sum(s.latency_ms for s in spans), 2),
        total_cost_usd=round(sum(s.usage.cost_usd for s in spans), 6),
        total_tokens=sum(s.usage.total_tokens for s in spans),
        spans=[SpanDTO.of(s) for s in spans],
    )
