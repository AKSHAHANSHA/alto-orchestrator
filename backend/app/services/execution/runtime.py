"""Execution-layer services: tools, actuation, generation, review queue, memory.

The default adapters here are in-process and durable enough for local
operation and the demo. Each sits behind a port, so swapping the CRM for
Salesforce or the queue for a real ticketing system is an adapter change, not
a rewrite.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from app.core.errors import ToolError
from app.core.logging import get_logger
from app.domain.entities import (
    ConversationState,
    ExecutionAction,
    HumanReviewItem,
    Span,
)
from app.domain.enums import (
    ActionStatus,
    ActionType,
    EntityType,
    HumanReviewReason,
    IntentCategory,
    ModelTier,
)
from app.domain.value_objects import DraftReply, RetrievedChunk, RoutingDecision, TokenUsage
from app.services.decision.router import escalation_reason
from app.services.execution.catalog import VehicleCatalogService
from app.services.execution.finance_tools import EmiRequest, calculate_emi
from app.services.execution.valuation_tools import ValuationRequest, estimate_trade_in

logger = get_logger(__name__)


class _CatalogLookupPort(Protocol):
    """Shape of the catalog-lookup adapter this module depends on.

    The concrete implementation lives in ``infrastructure/persistence/`` —
    depending on this Protocol lets the service module stay in ``services/``
    without importing infrastructure directly, which the dependency rule
    forbids.
    """

    async def lookup(
        self, brand: str | None, model: str | None, year: int | None = None
    ) -> Any: ...


# ══════════════════════════════════════════════════════════════════════
# Tools
# ══════════════════════════════════════════════════════════════════════
class ToolRunner:
    """Runs the deterministic tools an intent requires.

    A tool only runs when its intent is present *and* fully specified. Running
    an EMI calculation against a half-known vehicle would produce a number
    that looks authoritative and is not.
    """

    def __init__(
        self,
        catalog: VehicleCatalogService,
        catalog_lookup: _CatalogLookupPort | None = None,
    ) -> None:
        self._catalog = catalog
        self._catalog_lookup_service = catalog_lookup

    async def run_for(self, conversation: ConversationState) -> dict[str, Any]:
        results: dict[str, Any] = {}
        categories = {i.category for i in conversation.intents.unresolved}

        # Structured catalog lookup runs first for any intent that names a
        # specific vehicle — its outcome informs both the trade-in tool
        # (which needs an MSRP) and the generator (which needs to be honest
        # if we don't stock the vehicle asked about).
        needs_catalog = categories & {
            IntentCategory.VEHICLE_AVAILABILITY_INFO,
            IntentCategory.PRICING_OFFERS,
            IntentCategory.TEST_DRIVE_BOOKING,
            IntentCategory.FINANCING_EMI,
            IntentCategory.TRADE_IN_VALUATION,
        }
        catalog_lookups: dict[str, Any] = {}
        if needs_catalog and self._catalog_lookup_service is not None:
            catalog_lookups = await self._run_catalog_lookups(conversation)
            if catalog_lookups:
                results["catalog"] = catalog_lookups

        if IntentCategory.TRADE_IN_VALUATION in categories:
            trade_in = await self._trade_in(conversation)
            if trade_in is not None:
                results["trade_in"] = trade_in

        if IntentCategory.FINANCING_EMI in categories:
            emi = await self._emi(conversation, results.get("trade_in"))
            if emi is not None:
                results["emi"] = emi

        # Legacy vector-based catalog match still runs for search-style
        # intents where similarity is genuinely useful ("affordable Karva
        # SUV"). It stays under a different key so the generator can tell
        # the two apart.
        if categories & {
            IntentCategory.VEHICLE_AVAILABILITY_INFO,
            IntentCategory.PRICING_OFFERS,
            IntentCategory.TEST_DRIVE_BOOKING,
        }:
            matches = await self._catalog_lookup(conversation)
            if matches:
                results["catalog_similar"] = matches

        return results

    async def _run_catalog_lookups(
        self, conversation: ConversationState
    ) -> dict[str, Any]:
        """Structured lookup for both the new and old vehicle, when named.

        Any exception is degraded to a warning — a Postgres blip must never
        take a customer conversation down. The vector retriever will still
        surface the corpus; the "we do not stock that" honesty just isn't
        available until the DB comes back.
        """
        lookup_service = self._catalog_lookup_service
        assert lookup_service is not None
        result: dict[str, Any] = {}

        async def _safe_lookup(brand: str, model: str, year: int | None) -> Any:
            try:
                return await lookup_service.lookup(brand, model, year)
            except Exception as exc:
                logger.warning("catalog_lookup_failed", error=str(exc))
                return None

        new_vehicle = conversation.vehicle_of_interest()
        if new_vehicle.brand and new_vehicle.model:
            lookup = await _safe_lookup(
                new_vehicle.brand, new_vehicle.model, new_vehicle.year
            )
            if lookup is not None:
                result["new_vehicle"] = {
                    "verdict": lookup.verdict,
                    "explanation": lookup.explain(),
                    "matches": [r.model_dump() for r in lookup.matches],
                    "suggestions": list(lookup.suggestions),
                }

        old_vehicle = conversation.trade_in_vehicle()
        if old_vehicle.brand and old_vehicle.model:
            lookup = await _safe_lookup(
                old_vehicle.brand, old_vehicle.model, old_vehicle.year
            )
            if lookup is not None:
                result["old_vehicle"] = {
                    "verdict": lookup.verdict,
                    "explanation": lookup.explain(),
                    "matches": [r.model_dump() for r in lookup.matches[:1]],
                }

        return result

    async def _trade_in(self, conversation: ConversationState) -> dict[str, Any] | None:
        vehicle = conversation.trade_in_vehicle()
        if not vehicle.is_identified or vehicle.year is None:
            return None

        # Prefer the structured lookup — it will tell us honestly that we do
        # not have the model, rather than returning a semantic neighbour and
        # producing a valuation against the wrong MSRP. Falls back to the
        # in-memory best-match if Postgres is unavailable.
        record = None
        if self._catalog_lookup_service is not None:
            try:
                lookup = await self._catalog_lookup_service.lookup(
                    vehicle.brand or "", vehicle.model or "", vehicle.year
                )
                if lookup.matches:
                    record = lookup.matches[0]
            except Exception as exc:
                logger.warning("catalog_lookup_failed", error=str(exc))
        if record is None:
            record = await self._catalog.best_match(
                vehicle.brand or "", vehicle.model or "", vehicle.year
            )

        mileage = conversation.entity(EntityType.OLD_VEHICLE_MILEAGE)
        condition = conversation.entity(EntityType.OLD_VEHICLE_CONDITION)

        try:
            estimate = estimate_trade_in(
                ValuationRequest(
                    brand=vehicle.brand or "",
                    model=vehicle.model or "",
                    year=vehicle.year,
                    mileage_km=int(mileage.value) if mileage and mileage.value.isdigit() else None,
                    condition=condition.value if condition else None,
                    base_msrp=record.msrp if record else None,
                    current_year=datetime.now(UTC).year,
                )
            )
        except ToolError as exc:
            # Refusing to quote is the designed behaviour, not an error. The
            # reason travels forward so the reply can explain the handoff.
            logger.info("valuation_declined", reason=exc.message)
            return {"declined": True, "reason": exc.message}

        return estimate.model_dump()

    async def _emi(
        self, conversation: ConversationState, trade_in: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        vehicle = conversation.vehicle_of_interest()
        if not vehicle.is_identified:
            return None

        # An honest lookup — if we don't stock the model the customer named,
        # we return nothing here and the generator explains why rather than
        # quoting an instalment against a semantically-similar car.
        record = None
        if self._catalog_lookup_service is not None:
            try:
                lookup = await self._catalog_lookup_service.lookup(
                    vehicle.brand or "", vehicle.model or "", vehicle.year
                )
                if lookup.was_missing:
                    return {
                        "declined": True,
                        "reason": lookup.explain(),
                    }
                if lookup.matches:
                    record = lookup.matches[0]
            except Exception as exc:
                logger.warning("catalog_lookup_failed", error=str(exc))
        if record is None:
            record = await self._catalog.best_match(
                vehicle.brand or "", vehicle.model or "", vehicle.year
            )
        if record is None or not record.msrp:
            return None

        # A trade-in offsets the amount to finance. This is exactly why the
        # planner makes financing depend on the valuation: quoting first
        # would give a number that has to be retracted.
        down_payment = None
        if trade_in and not trade_in.get("declined"):
            down_payment = float(trade_in["estimate_low"])

        stated_down = conversation.entity(EntityType.DOWN_PAYMENT)
        if stated_down and stated_down.value.replace(".", "").isdigit():
            down_payment = (down_payment or 0) + float(stated_down.value)

        tenure = conversation.entity(EntityType.TENURE_MONTHS)
        salary = conversation.entity(EntityType.SALARY_TRANSFER)

        try:
            quote = calculate_emi(
                EmiRequest(
                    vehicle_price=record.msrp,
                    down_payment=down_payment,
                    tenure_months=int(tenure.value) if tenure and tenure.value.isdigit() else None,
                    salary_transfer=bool(salary and salary.value.lower() in {"true", "yes"}),
                )
            )
        except ToolError as exc:
            logger.info("emi_declined", reason=exc.message)
            return {"declined": True, "reason": exc.message}

        payload = quote.model_dump()
        payload["vehicle"] = record.describe()
        payload["trade_in_applied"] = down_payment is not None and bool(trade_in)
        return payload

    async def _catalog_lookup(self, conversation: ConversationState) -> list[dict[str, Any]]:
        vehicle = conversation.vehicle_of_interest()
        if not vehicle.brand:
            return []
        matches = await self._catalog.find(
            brand=vehicle.brand, model=vehicle.model, year=vehicle.year, limit=5
        )
        return [m.model_dump() for m in matches]


# ══════════════════════════════════════════════════════════════════════
# Actuation
# ══════════════════════════════════════════════════════════════════════
class Actuator:
    """Performs the side effects the coordinator used to do by hand.

    Every action carries an idempotency key derived from
    (conversation, intent, action type). WhatsApp webhooks retry, and a
    redelivered message must never book a second Saturday slot.
    """

    def __init__(self) -> None:
        self._performed: dict[str, ExecutionAction] = {}
        self._bookings: dict[str, str] = {}

    async def execute(
        self, conversation: ConversationState, tool_results: dict[str, Any]
    ) -> list[ExecutionAction]:
        actions: list[ExecutionAction] = []

        for intent in conversation.intents.unresolved:
            if intent.missing_slots or intent.depends_on:
                continue

            if intent.category is IntentCategory.TEST_DRIVE_BOOKING:
                actions.append(await self._book(conversation, intent.id))

            if intent.department:
                actions.append(
                    await self._notify(conversation, intent.id, intent.department.value)
                )

        return actions

    async def _book(self, conversation: ConversationState, intent_id: str) -> ExecutionAction:
        key = ExecutionAction.make_key(
            conversation.conversation_id, intent_id, ActionType.BOOK_TEST_DRIVE
        )

        if key in self._performed:
            # The idempotency guarantee, made visible rather than silent.
            existing = self._performed[key]
            logger.info("booking_deduplicated", key=key, booking=existing.result)
            return existing

        preferred = conversation.entity(EntityType.PREFERRED_DATE)
        slot = datetime.now(UTC) + timedelta(days=1)

        action = ExecutionAction(
            conversation_id=conversation.conversation_id,
            intent_id=intent_id,
            type=ActionType.BOOK_TEST_DRIVE,
            payload={
                "vehicle": conversation.vehicle_of_interest().describe(),
                "requested_date": preferred.value if preferred else None,
            },
            status=ActionStatus.EXECUTED,
            idempotency_key=key,
            result={"booking_id": f"bk_{key[:10]}", "slot": slot.isoformat()},
        )
        self._performed[key] = action
        return action

    async def _notify(
        self, conversation: ConversationState, intent_id: str, department: str
    ) -> ExecutionAction:
        key = ExecutionAction.make_key(
            conversation.conversation_id, intent_id, ActionType.NOTIFY_DEPARTMENT
        )
        if key in self._performed:
            return self._performed[key]

        action = ExecutionAction(
            conversation_id=conversation.conversation_id,
            intent_id=intent_id,
            type=ActionType.NOTIFY_DEPARTMENT,
            payload={"department": department},
            status=ActionStatus.EXECUTED,
            idempotency_key=key,
            result={"notified": department},
        )
        self._performed[key] = action
        return action


# ══════════════════════════════════════════════════════════════════════
# Generation
# ══════════════════════════════════════════════════════════════════════
class ResponseGenerator:
    """Drafts the customer-facing reply.

    The model writes prose; it does not decide facts. Every figure comes from
    a deterministic tool and is injected into the prompt as authoritative
    context, which is what makes the grounding check meaningful rather than
    circular.
    """

    SYSTEM = """\
You write replies for Alto Motors, a dealership in Velmora selling Karva \
(affordable sedans and SUVs) and Renzo (premium and performance vehicles).

Rules you must not break:
- Use only the figures given to you in the context. Never calculate, estimate \
or adjust a number yourself. If a figure is not supplied, do not state one.
- Before you finish a reply, check every line under "Open requests and what is \
still missing". If the one you are acting on this turn is not the only one \
listed, say what is still needed for each of the others too, even in one short \
sentence. Confirming a booking or quote must never crowd out the rest.
- Whenever a specific vehicle is named and its catalog record is in the \
context, state its availability plus year, transmission, horsepower, drivetrain, \
highway mpg and price as one dense line the first time it comes up and again \
whenever you confirm a booking or quote for it — e.g. "2016 Renzo S5 — \
Automatic, 333hp, all wheel drive, 26 hwy mpg, 67350 AED, in stock." If the \
catalog says the vehicle is not stocked, say that plainly instead of guessing.
- If the customer just answered a question you asked, acknowledge the answer \
in one short phrase and move to the next step — either the next missing piece \
of information, or the action itself if you have everything you need.
- Be warm, brief and specific. No corporate filler. Never write \
"Thank you for reaching out" or "Best regards, Alto Motors". You are already \
in a conversation with them.
- Never write "please provide more details" as a whole reply. Always name the \
specific thing you need next — the model, the year, the down payment.
- Always carry through any disclaimer attached to a quote.

Write only the English reply."""

    ARABIC_SYSTEM = """\
Translate the reply into Modern Standard Arabic suitable for a Gulf customer.

Keep every figure, currency amount and vehicle name exactly as written. \
Preserve the disclaimer. Return only the Arabic text."""

    def __init__(self, router: Any) -> None:
        self._router = router

    async def draft(
        self,
        conversation: ConversationState,
        *,
        chunks: tuple[RetrievedChunk, ...],
        tool_results: dict[str, Any],
        tier: ModelTier | None,
        allow_auto_send: bool = False,
    ) -> tuple[DraftReply, TokenUsage, str]:
        context = self._build_context(conversation, chunks, tool_results)
        model_tier = tier or ModelTier.FAST

        response = await self._router.complete(
            system=self.SYSTEM, user=context, tier=model_tier, temperature=0.3
        )
        usage = response.usage

        arabic: str | None = None
        if conversation.language and conversation.language.requires_bilingual_reply:
            translation = await self._router.complete(
                system=self.ARABIC_SYSTEM,
                user=response.text,
                tier=model_tier,
                temperature=0.2,
            )
            arabic = translation.text
            usage = usage + translation.usage

        return (
            DraftReply(
                en=response.text.strip(),
                ar=arabic.strip() if arabic else None,
                # Reached only for AUTO/PREMIUM tiers — HUMAN tier never
                # generates a draft, it escalates straight to a person. So
                # this flag is exactly the master kill-switch: whether those
                # two tiers may reach the customer without operator sign-off.
                requires_human_approval=not allow_auto_send,
            ),
            usage,
            response.model,
        )

    def _build_context(
        self,
        conversation: ConversationState,
        chunks: tuple[RetrievedChunk, ...],
        tool_results: dict[str, Any],
    ) -> str:
        lines: list[str] = []

        # Show the last few turns so the model can pick up context — the
        # difference between a generic "please provide more details" reply
        # and a specific "Great, Renzo — which model did you have in mind?"
        # is precisely that the model has seen what the customer answered.
        transcript = conversation.transcript
        if transcript:
            lines.append("## Conversation so far")
            recent = transcript[-8:]
            for turn in recent:
                who = "Customer" if turn.role == "customer" else "You"
                lines.append(f"{who}: {turn.text}")
            lines.append("")

        # Enumerate intents with what's still missing so the model can pick
        # the next question or action rather than describe intents in the
        # abstract.
        if conversation.intents.unresolved:
            lines.append("## Open requests and what is still missing")
            for intent in conversation.intents.ordered():
                label = intent.category.value.replace("_", " ")
                if intent.missing_slots:
                    missing = ", ".join(
                        s.value.replace("_", " ") for s in intent.missing_slots
                    )
                    lines.append(f"- {label} — still need: {missing}")
                else:
                    lines.append(f"- {label} — ready to act")

        # Everything the customer has told us so far, so the reply doesn't
        # ask again for something they've already provided.
        if conversation.entities:
            lines.append("\n## What the customer has told us")
            by_type: dict[str, str] = {}
            for entity in conversation.entities:
                by_type[entity.type.value] = entity.value
            for key, value in by_type.items():
                lines.append(f"- {key.replace('_', ' ')}: {value}")

        if tool_results:
            lines.append(
                "\n## Authoritative figures (use these exactly, never recompute)"
            )
            for name, payload in tool_results.items():
                lines.append(f"\n### {name}")
                lines.append(_format_tool_result(payload))

        if chunks:
            lines.append("\n## Supporting documents")
            for chunk in chunks[:5]:
                source = chunk.metadata.get("source", chunk.doc_id)
                lines.append(f"\n[{chunk.chunk_id}] ({source})\n{chunk.text[:600]}")

        if transcript:
            last_customer = next(
                (t for t in reversed(transcript) if t.role == "customer"), None
            )
            if last_customer is not None:
                lines.append("\n## The customer's most recent message")
                lines.append(last_customer.text)

        return "\n".join(lines)


def _format_tool_result(payload: Any) -> str:
    """Flatten a tool result into prompt text.

    Recurses through nesting — catalog lookups return
    ``{"new_vehicle": {"matches": [...]}}``, and a non-recursive formatter
    silently drops everything past the first level, which is exactly how
    vehicle specs used to vanish before ever reaching the model.
    """
    if isinstance(payload, dict):
        if payload.get("declined"):
            return f"Declined: {payload.get('reason')}"
        lines: list[str] = []
        for key, value in payload.items():
            if value is None or value == () or value == []:
                continue
            if isinstance(value, dict):
                nested = _format_tool_result(value)
                if nested:
                    lines.append(f"{key}:")
                    lines.append(_indent(nested))
            elif isinstance(value, list | tuple):
                nested = _format_tool_result(list(value))
                if nested:
                    lines.append(f"{key}:")
                    lines.append(_indent(nested))
            else:
                lines.append(f"- {key}: {value}")
        return "\n".join(lines)
    if isinstance(payload, list):
        lines = []
        for item in payload[:5]:
            if isinstance(item, dict) and "brand" in item and "model" in item:
                lines.append(f"- {describe_vehicle(item)}")
            else:
                lines.append(f"- {item}")
        return "\n".join(lines)
    return str(payload)


def _indent(text: str) -> str:
    return "\n".join(f"  {line}" for line in text.splitlines())


def describe_vehicle(vehicle: dict[str, Any]) -> str:
    """One compact line with the specs a customer actually asks about.

    Not a table — the chat UI renders plain text only, so this is the
    tabular-format request expressed as a dense single line instead.
    """
    heading = " ".join(
        str(vehicle.get(key, "")) for key in ("year", "brand", "model")
    ).strip()
    specs: list[str] = []
    if vehicle.get("transmission"):
        specs.append(str(vehicle["transmission"]).replace("_", " ").title())
    if vehicle.get("engine_hp"):
        specs.append(f"{vehicle['engine_hp']:.0f}hp")
    if vehicle.get("driven_wheels"):
        specs.append(str(vehicle["driven_wheels"]))
    if vehicle.get("highway_mpg"):
        specs.append(f"{vehicle['highway_mpg']} hwy mpg")
    if vehicle.get("msrp"):
        specs.append(f"{vehicle['msrp']:.0f} AED")
    return f"{heading} — {', '.join(specs)}" if specs else heading


# ══════════════════════════════════════════════════════════════════════
# Human review queue
# ══════════════════════════════════════════════════════════════════════
class HumanReviewQueue:
    """Escalations awaiting a person.

    Each item carries the draft, the routing rationale and the reason it
    escalated, so review is a decision rather than an investigation.
    """

    def __init__(self) -> None:
        self._items: dict[str, HumanReviewItem] = {}

    async def enqueue_for(
        self,
        conversation: ConversationState,
        decision: RoutingDecision,
        draft: DraftReply | None = None,
    ) -> HumanReviewItem:
        primary = conversation.intents.primary
        item = HumanReviewItem(
            conversation_id=conversation.conversation_id,
            intent_id=primary.id if primary else None,
            reason=escalation_reason(decision),
            department=decision.department,
            draft=draft,
            routing=decision,
        )
        self._items[item.id] = item
        logger.info(
            "escalated_to_human",
            review_id=item.id,
            reason=item.reason.value,
            score=decision.confidence.decision_score,
        )
        return item

    async def get(self, item_id: str) -> HumanReviewItem | None:
        return self._items.get(item_id)

    async def list_open(self, limit: int = 50) -> list[HumanReviewItem]:
        return [i for i in self._items.values() if i.is_open][:limit]

    async def open_for(self, conversation_id: str) -> HumanReviewItem | None:
        """Return the open review item for this conversation, if any.

        Callers check this before enqueuing an
        `awaiting_operator_reply` item — one card per conversation, not one
        per customer message.
        """
        for item in self._items.values():
            if item.is_open and item.conversation_id == conversation_id:
                return item
        return None

    async def enqueue_customer_followup(
        self, conversation: ConversationState
    ) -> HumanReviewItem | None:
        """Add (or keep) a card for a customer reply on a handed-off chat.

        If there is already an open card for this conversation, do nothing —
        the operator will see the fresh customer message in the same card's
        transcript on their next poll.
        """
        existing = await self.open_for(conversation.conversation_id)
        if existing is not None:
            return existing

        primary = conversation.intents.primary
        item = HumanReviewItem(
            conversation_id=conversation.conversation_id,
            intent_id=primary.id if primary else None,
            reason=HumanReviewReason.AWAITING_OPERATOR_REPLY,
            department=(
                conversation.routing.department
                if conversation.routing and conversation.routing.department
                else None
            ),
            draft=None,
            routing=conversation.routing,
        )
        self._items[item.id] = item
        logger.info(
            "customer_replied_after_handoff",
            review_id=item.id,
            conversation_id=conversation.conversation_id,
        )
        return item

    async def save(self, item: HumanReviewItem) -> None:
        self._items[item.id] = item


# ══════════════════════════════════════════════════════════════════════
# Memory
# ══════════════════════════════════════════════════════════════════════
class MemoryService:
    """Working and long-term memory, plus the wide-event span log."""

    def __init__(self) -> None:
        self._conversations: dict[str, ConversationState] = {}
        self._spans: list[Span] = []

    async def persist(self, conversation: ConversationState, spans: list[Span]) -> None:
        # Preserve the transcript across turns. Each graph run rebuilds a
        # ConversationState from state fields, which does not know about the
        # prior transcript — so without this merge, the transcript would be
        # wiped every message and only show the current turn.
        previous = self._conversations.get(conversation.conversation_id)
        if previous and previous.transcript:
            # ``append_turn`` is the only writer of the transcript. The graph
            # receives a snapshot of it and hands the same tuple back
            # untouched, so the stored copy is never behind the one returning
            # from the graph — concatenating the two appended every turn
            # twice, which only became visible once the customer navigated
            # away and the page restored from the server.
            conversation = conversation.model_copy(
                update={
                    "transcript": previous.transcript,
                    "turn_count": previous.turn_count,
                }
            )
        self._conversations[conversation.conversation_id] = conversation
        self._spans.extend(spans)

    async def append_turn(
        self, conversation_id: str, role: str, text: str
    ) -> ConversationState | None:
        """Add one turn to the transcript, out-of-band from the graph.

        Called by the API for the incoming customer message (before the graph
        runs) and by the human-review endpoints for operator-authored replies
        (after review). The graph itself does not touch the transcript, which
        keeps its state contract narrow.
        """
        from datetime import UTC, datetime

        from app.domain.value_objects import ConversationTurn

        existing = self._conversations.get(conversation_id)
        turn = ConversationTurn(role=role, text=text, at=datetime.now(UTC))

        if existing is None:
            existing = ConversationState(
                conversation_id=conversation_id,
                transcript=(turn,),
                turn_count=1,
            )
        else:
            existing = existing.model_copy(
                update={
                    "transcript": (*existing.transcript, turn),
                    "turn_count": existing.turn_count + 1,
                }
            )

        self._conversations[conversation_id] = existing
        return existing

    async def mark_human_handled(self, conversation_id: str) -> None:
        state = self._conversations.get(conversation_id)
        if state:
            self._conversations[conversation_id] = state.model_copy(
                update={"human_handled": True}
            )

    async def get(self, conversation_id: str) -> ConversationState | None:
        return self._conversations.get(conversation_id)

    async def list_active(self, limit: int = 50) -> list[ConversationState]:
        return sorted(
            self._conversations.values(), key=lambda c: c.updated_at, reverse=True
        )[:limit]

    async def spans_for(self, conversation_id: str) -> list[Span]:
        return [s for s in self._spans if s.conversation_id == conversation_id]

    async def all_spans(self) -> list[Span]:
        return list(self._spans)
