"""Entities: things with identity and a lifecycle.

Unlike the frozen values in ``value_objects.py``, these have an ``id`` and
change over time. They still avoid in-place mutation — every transition
returns a new instance — so a state snapshot can be persisted as an audit
record without worrying about what mutated it afterwards.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import (
    ActionStatus,
    ActionType,
    Channel,
    CognitiveLayer,
    Department,
    EntityType,
    HumanReviewReason,
    IntentCategory,
    IntentStatus,
    Language,
    ReviewOutcome,
    SpanStatus,
)
from app.domain.value_objects import (
    ConversationTurn,
    DraftReply,
    ExtractedEntity,
    LanguageProfile,
    Plan,
    RoutingDecision,
    Sentiment,
    TokenUsage,
    VehicleRef,
)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _now() -> datetime:
    return datetime.now(UTC)


class Entity(BaseModel):
    """Base for identified, evolving domain objects."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# ──────────────────────────────────────────────────────────────────────
# Inbound
# ──────────────────────────────────────────────────────────────────────
class Inquiry(Entity):
    """A single inbound customer message."""

    id: str = Field(default_factory=lambda: _new_id("inq"))
    conversation_id: str
    customer_id: str | None = None
    channel: Channel
    raw_text: str
    normalized_text: str | None = None
    received_at: datetime = Field(default_factory=_now)
    idempotency_key: str | None = None

    def with_idempotency_key(self) -> Self:
        """Derive a stable key from the message content when none was supplied.

        WhatsApp webhooks retry. Without this, a redelivered message starts a
        second graph run and can double-book a test-drive slot.
        """
        if self.idempotency_key:
            return self
        digest = hashlib.sha256(
            f"{self.conversation_id}|{self.raw_text}".encode()
        ).hexdigest()[:32]
        return self.model_copy(update={"idempotency_key": digest})


# ──────────────────────────────────────────────────────────────────────
# Intents
# ──────────────────────────────────────────────────────────────────────
class Intent(Entity):
    """One thing the customer wants, tracked to resolution.

    ``category`` and ``confidence`` come from the model. Everything else —
    ``department``, ``priority``, ``required_slots``, ``depends_on`` — is
    assigned by the rule engine. That split is the whole architecture in one
    class: the model reports what it heard, the business decides what happens.
    """

    id: str = Field(default_factory=lambda: _new_id("int"))
    category: IntentCategory
    confidence: float = Field(ge=0.0, le=1.0)

    is_primary: bool = False
    priority: int = Field(default=50, ge=0, le=100)
    status: IntentStatus = IntentStatus.PENDING
    department: Department | None = None

    required_slots: tuple[EntityType, ...] = ()
    missing_slots: tuple[EntityType, ...] = ()
    depends_on: tuple[str, ...] = ()

    evidence: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    @property
    def is_resolved(self) -> bool:
        return self.status.is_terminal

    @property
    def is_ready(self) -> bool:
        """Every required slot is filled and nothing blocks it."""
        return not self.missing_slots and not self.depends_on

    def transition(self, status: IntentStatus) -> Intent:
        return self.model_copy(update={"status": status, "updated_at": _now()})

    def fill_slots(self, filled: set[EntityType]) -> Intent:
        """Remove now-satisfied slots and advance status if fully specified."""
        remaining = tuple(s for s in self.missing_slots if s not in filled)
        if remaining == self.missing_slots:
            return self

        status = self.status
        if not remaining and status is IntentStatus.WAITING_INFORMATION:
            status = IntentStatus.PENDING

        return self.model_copy(
            update={"missing_slots": remaining, "status": status, "updated_at": _now()}
        )


class IntentQueue(Entity):
    """The ordered set of everything the customer is waiting on.

    This is the spine of the system. A single-intent message simply produces
    a queue of length one, so nothing downstream ever branches on "how many
    intents" — it processes a queue.

    ``merge`` is the reducer that makes the central guarantee structural
    rather than aspirational: an unresolved intent cannot be dropped by a
    later turn, only updated or resolved.
    """

    intents: tuple[Intent, ...] = ()

    def __len__(self) -> int:
        return len(self.intents)

    def __iter__(self) -> Iterator[Intent]:  # type: ignore[override]
        return iter(self.intents)

    @property
    def unresolved(self) -> tuple[Intent, ...]:
        return tuple(i for i in self.intents if not i.is_resolved)

    @property
    def primary(self) -> Intent | None:
        """The intent driving the reply: explicit flag, else highest priority."""
        flagged = [i for i in self.intents if i.is_primary and not i.is_resolved]
        if flagged:
            return flagged[0]
        return max(self.unresolved, key=lambda i: i.priority, default=None)

    def by_category(self, category: IntentCategory) -> Intent | None:
        return next((i for i in self.intents if i.category is category), None)

    def get(self, intent_id: str) -> Intent | None:
        return next((i for i in self.intents if i.id == intent_id), None)

    def merge(self, incoming: tuple[Intent, ...]) -> IntentQueue:
        """Fold a new turn's intents into the queue.

        Merge is by category, not by id, because the model mints fresh ids
        every turn: a customer repeating "and what about financing?" must
        update the existing financing intent rather than accumulate
        duplicates.

        Three rules, in order:

        1. An incoming intent matching an *unresolved* existing category
           updates that intent in place, keeping its id, department and
           dependencies — the fields the rule engine owns.
        2. An incoming intent with no unresolved match is appended.
        3. Existing intents absent from the incoming set are left untouched.
           This is the important one: silence in a later turn is not
           withdrawal, so nothing is ever dropped here.
        """
        merged = list(self.intents)
        index = {i.category: pos for pos, i in enumerate(merged) if not i.is_resolved}

        for candidate in incoming:
            pos = index.get(candidate.category)
            if pos is None:
                merged.append(candidate)
                index[candidate.category] = len(merged) - 1
                continue

            existing = merged[pos]
            merged[pos] = existing.model_copy(
                update={
                    # Confidence reflects the latest evidence.
                    "confidence": max(existing.confidence, candidate.confidence),
                    "evidence": candidate.evidence or existing.evidence,
                    "is_primary": candidate.is_primary or existing.is_primary,
                    "updated_at": _now(),
                }
            )

        return IntentQueue(intents=tuple(merged))

    def apply_entities(self, entities: tuple[ExtractedEntity, ...]) -> IntentQueue:
        """Propagate newly filled slots to every intent waiting on them."""
        filled = {e.type for e in entities}
        return IntentQueue(intents=tuple(i.fill_slots(filled) for i in self.intents))

    def replace(self, intent: Intent) -> IntentQueue:
        return IntentQueue(
            intents=tuple(intent if i.id == intent.id else i for i in self.intents)
        )

    def ordered(self) -> tuple[Intent, ...]:
        """Unresolved intents by descending priority, then creation order.

        Ties break on creation time so ordering is deterministic — required
        for reproducible plans.
        """
        return tuple(
            sorted(self.unresolved, key=lambda i: (-i.priority, i.created_at, i.id))
        )


# ──────────────────────────────────────────────────────────────────────
# Conversation & memory
# ──────────────────────────────────────────────────────────────────────
class ConversationState(Entity):
    """Working memory: the structured truth about a live conversation.

    The system remembers so the model does not have to. Nothing here is
    reconstructed by re-reading ``transcript`` — that field exists for audit
    and for the generation prompt window, and is explicitly not a source of
    intent or entity data.
    """

    conversation_id: str
    customer_id: str | None = None
    channel: Channel = Channel.WEB_FORM

    language: LanguageProfile | None = None
    sentiment: Sentiment | None = None
    intents: IntentQueue = Field(default_factory=IntentQueue)
    entities: tuple[ExtractedEntity, ...] = ()
    plan: Plan | None = None
    routing: RoutingDecision | None = None
    draft: DraftReply | None = None

    transcript: tuple[ConversationTurn, ...] = ()
    turn_count: int = 0
    human_handled: bool = False
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    def entity(self, entity_type: EntityType) -> ExtractedEntity | None:
        """Most confident value for a slot.

        Later turns supersede earlier ones at equal confidence, since the
        customer is usually correcting themselves.
        """
        matches = [e for e in self.entities if e.type is entity_type]
        return max(matches, key=lambda e: e.confidence, default=None)

    @property
    def filled_slots(self) -> set[EntityType]:
        return {e.type for e in self.entities}

    def vehicle_of_interest(self) -> VehicleRef:
        def value(t: EntityType) -> str | None:
            found = self.entity(t)
            return found.value if found else None

        year = value(EntityType.NEW_VEHICLE_YEAR)
        return VehicleRef(
            brand=value(EntityType.NEW_VEHICLE_BRAND),
            model=value(EntityType.NEW_VEHICLE_MODEL),
            year=int(year) if year and year.isdigit() else None,
            body_style=value(EntityType.NEW_VEHICLE_BODY),
        )

    def trade_in_vehicle(self) -> VehicleRef:
        def value(t: EntityType) -> str | None:
            found = self.entity(t)
            return found.value if found else None

        year = value(EntityType.OLD_VEHICLE_YEAR)
        return VehicleRef(
            brand=value(EntityType.OLD_VEHICLE_BRAND),
            model=value(EntityType.OLD_VEHICLE_MODEL),
            year=int(year) if year and year.isdigit() else None,
            body_style=value(EntityType.OLD_VEHICLE_BODY),
        )

    def absorb_entities(self, incoming: tuple[ExtractedEntity, ...]) -> ConversationState:
        """Add new entity observations and propagate them to the intent queue.

        Observations accumulate rather than overwrite: ``entity()`` resolves
        conflicts by confidence, which preserves the evidence trail for the
        admin UI instead of silently discarding it.
        """
        combined = self.entities + incoming
        return self.model_copy(
            update={
                "entities": combined,
                "intents": self.intents.apply_entities(combined),
                "updated_at": _now(),
            }
        )


class CustomerProfile(Entity):
    """Long memory: what matters if the customer comes back tomorrow.

    Deliberately not a transcript archive. A coordinator returning to a
    customer needs their name, what they were looking at and what is still
    open — not every sentence they have ever written.
    """

    id: str = Field(default_factory=lambda: _new_id("cus"))
    name: str | None = None
    preferred_language: Language = Language.ENGLISH
    phone: str | None = None
    email: str | None = None

    vehicles_owned: tuple[VehicleRef, ...] = ()
    vehicle_of_interest: VehicleRef | None = None
    open_intent_ids: tuple[str, ...] = ()
    previous_conversation_ids: tuple[str, ...] = ()
    visit_count: int = 0
    preferences: dict[str, str] = Field(default_factory=dict)

    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    @property
    def is_returning(self) -> bool:
        return self.visit_count > 1


# ──────────────────────────────────────────────────────────────────────
# Execution & audit
# ──────────────────────────────────────────────────────────────────────
class ExecutionAction(Entity):
    """A side effect the platform performed on the customer's behalf.

    Recorded so the admin can see what the system *did*, not only what it
    *said*. The idempotency key is what stops a redelivered webhook from
    booking two slots.
    """

    id: str = Field(default_factory=lambda: _new_id("act"))
    conversation_id: str
    intent_id: str | None = None
    type: ActionType
    payload: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    status: ActionStatus = ActionStatus.PENDING
    idempotency_key: str
    result: dict[str, str | int | float | bool | None] | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=_now)

    @staticmethod
    def make_key(conversation_id: str, intent_id: str | None, action: ActionType) -> str:
        raw = f"{conversation_id}|{intent_id or '-'}|{action.value}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]


class Span(Entity):
    """One wide event per pipeline stage.

    Wide and richly attributed rather than split across metrics, logs and
    traces: the admin trace view, the cost dashboard and the confidence
    breakdown all read from this one table instead of three subsystems.
    """

    id: str = Field(default_factory=lambda: _new_id("spn"))
    trace_id: str
    conversation_id: str
    node: str
    layer: CognitiveLayer
    status: SpanStatus = SpanStatus.OK

    started_at: datetime = Field(default_factory=_now)
    latency_ms: float = 0.0

    model: str | None = None
    provider: str | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)

    attributes: dict[str, object] = Field(default_factory=dict)
    error: str | None = None


class HumanReviewItem(Entity):
    """A conversation waiting for a person.

    Holds the full context a reviewer needs — the draft, the routing
    rationale and why it escalated — so review is a decision, not an
    investigation.
    """

    id: str = Field(default_factory=lambda: _new_id("hrq"))
    conversation_id: str
    intent_id: str | None = None
    reason: HumanReviewReason
    department: Department | None = None
    draft: DraftReply | None = None
    routing: RoutingDecision | None = None

    created_at: datetime = Field(default_factory=_now)
    resolved_at: datetime | None = None
    outcome: ReviewOutcome | None = None
    reviewer: str | None = None
    final_text: str | None = None

    @property
    def is_open(self) -> bool:
        return self.outcome is None

    def resolve(
        self,
        outcome: ReviewOutcome,
        reviewer: str,
        final_text: str | None = None,
    ) -> HumanReviewItem:
        return self.model_copy(
            update={
                "outcome": outcome,
                "reviewer": reviewer,
                "final_text": final_text,
                "resolved_at": _now(),
            }
        )
