"""The calendar gate, and what an escalation is allowed to take away from it.

Pinned here because the failure was invisible from the outside: the booking
flow did not error, it simply stopped offering a calendar. A customer asked to
test-drive a Renzo S5, answered "which model?" and "which day?", and was told a
colleague would come back to them — with no picker, on that turn or any turn
after it.

The cause was ordering. `submit_inquiry` returned inside its escalation branch
before the calendar block below it ever ran, so *any* escalation reason removed
the picker as collateral damage. The reported case escalated on
`unsupported_financial_claim`, which grounding was very likely right about — a
drafted vehicle price with no catalog chunk behind it. Being right about the
prose is not a reason to cancel the booking: slots come from the appointments
service, not from the model.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.api.v1.routes import (
    CALENDAR_CALL_TO_ACTION,
    HOLDING_MESSAGE_EN,
    _should_show_calendar,
    submit_inquiry,
)
from app.api.v1.schemas import InquiryRequest
from app.domain.entities import Intent, IntentQueue
from app.domain.enums import EntityType, IntentCategory
from app.domain.value_objects import ExtractedEntity


def _vehicle_entities() -> tuple[ExtractedEntity, ...]:
    """Brand and model, both filled — the gate demands both."""
    return (
        ExtractedEntity(
            type=EntityType.NEW_VEHICLE_BRAND,
            value="Renzo",
            raw_value="renzo",
            confidence=0.9,
        ),
        ExtractedEntity(
            type=EntityType.NEW_VEHICLE_MODEL,
            value="S5",
            raw_value="s5",
            confidence=0.9,
        ),
    )


def _booking_result(**overrides: object) -> dict[str, object]:
    """A turn that is ready for the picker: test drive, vehicle known, no date."""
    intent = Intent(
        category=IntentCategory.TEST_DRIVE_BOOKING,
        confidence=0.9,
        is_primary=True,
        missing_slots=(EntityType.PREFERRED_DATE,),
    )
    result: dict[str, object] = {
        "awaiting": EntityType.PREFERRED_DATE.value,
        "intents": IntentQueue(intents=(intent,)),
        "entities": _vehicle_entities(),
        "escalated": False,
    }
    result.update(overrides)
    return result


class TestCalendarSurvivesEscalation:
    def test_shows_on_an_ordinary_booking_turn(self) -> None:
        assert _should_show_calendar(_booking_result()) is True

    def test_shows_even_when_the_turn_escalated(self) -> None:
        # `escalate_human` stamps "human_review" over the slot the turn was
        # really waiting on. Read literally that is "not a calendar slot", and
        # the gate refused every escalated turn — which is the reported bug.
        escalated = _booking_result(awaiting="human_review", escalated=True)
        assert _should_show_calendar(escalated) is True

    def test_human_review_without_escalation_is_still_refused(self) -> None:
        # The override is scoped to a turn that actually escalated. A stray
        # "human_review" with no escalation is not something to reinterpret.
        stray = _booking_result(awaiting="human_review", escalated=False)
        assert _should_show_calendar(stray) is False


class TestCalendarStillMindsItsOwnBusiness:
    """The escalation carve-out must not widen the gate in any other way."""

    def test_refuses_when_the_turn_is_asking_about_something_else(self) -> None:
        asking_trade_in = _booking_result(awaiting=EntityType.OLD_VEHICLE_MODEL.value)
        assert _should_show_calendar(asking_trade_in) is False

    def test_refuses_when_escalated_but_asking_about_something_else(self) -> None:
        # An escalated trade-in question must not inherit the carve-out just
        # because a test drive is also open somewhere in the queue.
        intent = Intent(
            category=IntentCategory.TRADE_IN_VALUATION,
            confidence=0.9,
            is_primary=True,
            missing_slots=(EntityType.OLD_VEHICLE_MODEL,),
        )
        result = _booking_result(
            awaiting="human_review",
            escalated=True,
            intents=IntentQueue(intents=(intent,)),
        )
        assert _should_show_calendar(result) is False

    def test_refuses_without_a_vehicle_to_book(self) -> None:
        brand_only = _booking_result(entities=(_vehicle_entities()[0],))
        assert _should_show_calendar(brand_only) is False


class _FakeMemory:
    """Records turns instead of persisting them."""

    def __init__(self) -> None:
        self.turns: list[tuple[str, str]] = []

    async def get(self, conversation_id: str) -> None:
        return None

    async def append_turn(self, conversation_id: str, role: str, text: str) -> None:
        self.turns.append((role, text))


class _FakeGraph:
    def __init__(self, result: dict[str, object]) -> None:
        self._result = result

    async def ainvoke(self, state: object, config: object = None) -> dict[str, object]:
        return self._result


def _request_for(result: dict[str, object]) -> tuple[SimpleNamespace, _FakeMemory]:
    memory = _FakeMemory()
    container = SimpleNamespace(memory=memory, human_queue=None)
    state = SimpleNamespace(container=container, graph=_FakeGraph(result))
    return SimpleNamespace(app=SimpleNamespace(state=state)), memory


class TestSubmitInquiryKeepsTheBookingAlive:
    """The regression itself: the escalation branch used to `return` early.

    `_should_show_calendar` can be perfectly correct and the customer still
    sees no picker, because the caller never asks it. This drives the real
    handler so a future reordering of those two blocks fails here.
    """

    async def test_escalated_booking_turn_still_offers_the_calendar(self) -> None:
        result = _booking_result(awaiting="human_review", escalated=True)
        request, memory = _request_for(result)

        response = await submit_inquiry(InquiryRequest(message="friday"), request)

        assert response.awaiting == "test_drive_slot"
        assert "calendar below" in response.reply.en
        # The unreviewed draft must still not reach the customer.
        assert HOLDING_MESSAGE_EN in response.reply.en
        assert ("assistant", CALENDAR_CALL_TO_ACTION) in memory.turns

    async def test_escalated_non_booking_turn_is_unchanged(self) -> None:
        # A complaint gets the holding message and nothing else — no calendar
        # smuggled in behind the carve-out.
        intent = Intent(
            category=IntentCategory.COMPLAINT_ESCALATION,
            confidence=0.9,
            is_primary=True,
        )
        result = _booking_result(
            awaiting="human_review",
            escalated=True,
            intents=IntentQueue(intents=(intent,)),
        )
        request, _ = _request_for(result)

        response = await submit_inquiry(InquiryRequest(message="this is unacceptable"), request)

        assert response.reply.en == HOLDING_MESSAGE_EN
        assert response.awaiting != "test_drive_slot"
