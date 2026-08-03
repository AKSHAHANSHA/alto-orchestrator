"""The intent queue is the spine of the system, so it gets the hardest tests.

The central claim of the architecture is that an unresolved intent cannot be
lost. That is a structural guarantee enforced by the merge reducer, not an
emergent property of prompting, which means it is testable — and these are
the tests that hold it to account.
"""

from __future__ import annotations

import pytest

from app.domain.entities import Intent, IntentQueue
from app.domain.enums import Department, EntityType, IntentCategory, IntentStatus


def intent(
    category: IntentCategory,
    *,
    confidence: float = 0.9,
    priority: int = 50,
    status: IntentStatus = IntentStatus.PENDING,
    primary: bool = False,
    missing: tuple[EntityType, ...] = (),
) -> Intent:
    return Intent(
        category=category,
        confidence=confidence,
        priority=priority,
        status=status,
        is_primary=primary,
        missing_slots=missing,
    )


class TestMergeNeverLosesIntents:
    """Rule 3 of the reducer, and the reason the whole class exists."""

    def test_silence_in_a_later_turn_is_not_withdrawal(self) -> None:
        # The customer asked about financing and a trade-in, then sent a
        # follow-up mentioning only the test drive. The first two are still
        # open and must survive.
        queue = IntentQueue(
            intents=(
                intent(IntentCategory.FINANCING_EMI),
                intent(IntentCategory.TRADE_IN_VALUATION),
            )
        )

        merged = queue.merge((intent(IntentCategory.TEST_DRIVE_BOOKING),))

        assert {i.category for i in merged} == {
            IntentCategory.FINANCING_EMI,
            IntentCategory.TRADE_IN_VALUATION,
            IntentCategory.TEST_DRIVE_BOOKING,
        }
        assert len(merged.unresolved) == 3

    def test_merging_an_empty_turn_changes_nothing(self) -> None:
        queue = IntentQueue(intents=(intent(IntentCategory.FINANCING_EMI),))
        assert queue.merge(()).intents == queue.intents

    @pytest.mark.parametrize("turns", [1, 5, 20])
    def test_unresolved_intents_survive_arbitrarily_many_turns(self, turns: int) -> None:
        queue = IntentQueue(intents=(intent(IntentCategory.TRADE_IN_VALUATION),))

        for _ in range(turns):
            queue = queue.merge((intent(IntentCategory.VEHICLE_AVAILABILITY_INFO),))

        assert queue.by_category(IntentCategory.TRADE_IN_VALUATION) is not None


class TestMergeIsByCategory:
    """Rule 1. The model mints fresh ids every turn, so id-matching would
    accumulate duplicates of the same request."""

    def test_repeating_an_intent_updates_rather_than_duplicates(self) -> None:
        original = intent(IntentCategory.FINANCING_EMI, confidence=0.7)
        queue = IntentQueue(intents=(original,))

        merged = queue.merge((intent(IntentCategory.FINANCING_EMI, confidence=0.95),))

        assert len(merged) == 1
        assert merged.intents[0].id == original.id, "the existing intent's identity is kept"

    def test_confidence_takes_the_stronger_evidence(self) -> None:
        queue = IntentQueue(intents=(intent(IntentCategory.FINANCING_EMI, confidence=0.62),))
        merged = queue.merge((intent(IntentCategory.FINANCING_EMI, confidence=0.94),))
        assert merged.intents[0].confidence == pytest.approx(0.94)

    def test_weaker_repetition_does_not_erode_confidence(self) -> None:
        # A vaguer restatement shouldn't make us less sure of what we already
        # established from a clear one.
        queue = IntentQueue(intents=(intent(IntentCategory.FINANCING_EMI, confidence=0.94),))
        merged = queue.merge((intent(IntentCategory.FINANCING_EMI, confidence=0.40),))
        assert merged.intents[0].confidence == pytest.approx(0.94)

    def test_rule_engine_fields_survive_a_merge(self) -> None:
        # department, priority and depends_on are assigned by business rules.
        # A later model observation must never overwrite them.
        enriched = intent(IntentCategory.FINANCING_EMI, priority=70).model_copy(
            update={"department": Department.FINANCE, "depends_on": ("int_abc",)}
        )
        queue = IntentQueue(intents=(enriched,))

        merged = queue.merge((intent(IntentCategory.FINANCING_EMI, priority=1),))

        survivor = merged.intents[0]
        assert survivor.department is Department.FINANCE
        assert survivor.depends_on == ("int_abc",)
        assert survivor.priority == 70

    def test_a_resolved_intent_does_not_absorb_a_new_request(self) -> None:
        # The customer booked a test drive, then later asks for another one.
        # That is genuinely new work, not an update to finished work.
        done = intent(IntentCategory.TEST_DRIVE_BOOKING, status=IntentStatus.RESOLVED)
        queue = IntentQueue(intents=(done,))

        merged = queue.merge((intent(IntentCategory.TEST_DRIVE_BOOKING),))

        assert len(merged) == 2
        assert len(merged.unresolved) == 1

    def test_primary_flag_is_sticky_once_set(self) -> None:
        queue = IntentQueue(intents=(intent(IntentCategory.TRADE_IN_VALUATION, primary=True),))
        merged = queue.merge((intent(IntentCategory.TRADE_IN_VALUATION, primary=False),))
        assert merged.intents[0].is_primary


class TestOrdering:
    def test_ordered_returns_unresolved_by_descending_priority(self) -> None:
        queue = IntentQueue(
            intents=(
                intent(IntentCategory.VEHICLE_AVAILABILITY_INFO, priority=40),
                intent(IntentCategory.COMPLAINT_ESCALATION, priority=100),
                intent(IntentCategory.FINANCING_EMI, priority=70),
            )
        )

        assert [i.category for i in queue.ordered()] == [
            IntentCategory.COMPLAINT_ESCALATION,
            IntentCategory.FINANCING_EMI,
            IntentCategory.VEHICLE_AVAILABILITY_INFO,
        ]

    def test_ordering_is_deterministic_for_equal_priorities(self) -> None:
        queue = IntentQueue(
            intents=(
                intent(IntentCategory.FINANCING_EMI, priority=50),
                intent(IntentCategory.TRADE_IN_VALUATION, priority=50),
                intent(IntentCategory.SERVICE_AFTERSALES, priority=50),
            )
        )
        assert [i.id for i in queue.ordered()] == [i.id for i in queue.ordered()]

    def test_resolved_intents_are_excluded_from_ordering(self) -> None:
        queue = IntentQueue(
            intents=(
                intent(IntentCategory.FINANCING_EMI, status=IntentStatus.RESOLVED),
                intent(IntentCategory.TRADE_IN_VALUATION),
            )
        )
        assert len(queue.ordered()) == 1

    def test_primary_prefers_the_flagged_intent_over_the_highest_priority(self) -> None:
        queue = IntentQueue(
            intents=(
                intent(IntentCategory.COMPLAINT_ESCALATION, priority=100),
                intent(IntentCategory.TRADE_IN_VALUATION, priority=60, primary=True),
            )
        )
        primary = queue.primary
        assert primary is not None
        assert primary.category is IntentCategory.TRADE_IN_VALUATION

    def test_primary_is_none_when_everything_is_resolved(self) -> None:
        queue = IntentQueue(
            intents=(intent(IntentCategory.FINANCING_EMI, status=IntentStatus.RESOLVED),)
        )
        assert queue.primary is None


class TestSlotFilling:
    def test_filling_a_slot_removes_it_from_missing(self) -> None:
        queue = IntentQueue(
            intents=(
                intent(
                    IntentCategory.TRADE_IN_VALUATION,
                    status=IntentStatus.WAITING_INFORMATION,
                    missing=(EntityType.OLD_VEHICLE_MODEL, EntityType.OLD_VEHICLE_YEAR),
                ),
            )
        )

        updated = queue.intents[0].fill_slots({EntityType.OLD_VEHICLE_MODEL})

        assert updated.missing_slots == (EntityType.OLD_VEHICLE_YEAR,)
        assert updated.status is IntentStatus.WAITING_INFORMATION, "still incomplete"

    def test_filling_the_last_slot_releases_the_waiting_state(self) -> None:
        waiting = intent(
            IntentCategory.TRADE_IN_VALUATION,
            status=IntentStatus.WAITING_INFORMATION,
            missing=(EntityType.OLD_VEHICLE_YEAR,),
        )

        updated = waiting.fill_slots({EntityType.OLD_VEHICLE_YEAR})

        assert updated.missing_slots == ()
        assert updated.status is IntentStatus.PENDING
        assert updated.is_ready

    def test_filling_an_irrelevant_slot_is_a_no_op(self) -> None:
        original = intent(
            IntentCategory.TRADE_IN_VALUATION, missing=(EntityType.OLD_VEHICLE_YEAR,)
        )
        assert original.fill_slots({EntityType.CONTACT_EMAIL}) is original

    def test_an_intent_with_dependencies_is_not_ready_even_when_fully_slotted(self) -> None:
        blocked = intent(IntentCategory.FINANCING_EMI).model_copy(
            update={"depends_on": ("int_tradein",)}
        )
        assert not blocked.is_ready


class TestTheMixedIntentScenario:
    """The example from the brief, end to end.

    "I want to trade in my old Karva SUV and also check financing for a new
    Renzo S5 - and can I test drive it Saturday?"
    """

    def test_three_intents_are_tracked_independently(self) -> None:
        queue = IntentQueue().merge(
            (
                intent(IntentCategory.TRADE_IN_VALUATION, confidence=0.96, priority=60,
                       primary=True),
                intent(IntentCategory.FINANCING_EMI, confidence=0.91, priority=70),
                intent(IntentCategory.TEST_DRIVE_BOOKING, confidence=0.88, priority=80),
            )
        )

        assert len(queue) == 3
        assert len(queue.unresolved) == 3
        primary = queue.primary
        assert primary is not None and primary.category is IntentCategory.TRADE_IN_VALUATION

    def test_resolving_one_intent_leaves_the_others_open(self) -> None:
        queue = IntentQueue().merge(
            (
                intent(IntentCategory.TRADE_IN_VALUATION),
                intent(IntentCategory.FINANCING_EMI),
                intent(IntentCategory.TEST_DRIVE_BOOKING),
            )
        )

        booked = queue.by_category(IntentCategory.TEST_DRIVE_BOOKING)
        assert booked is not None
        queue = queue.replace(booked.transition(IntentStatus.RESOLVED))

        assert len(queue.unresolved) == 2
        assert len(queue) == 3, "resolved work stays on the record"

    def test_a_single_intent_message_is_just_a_queue_of_one(self) -> None:
        # Nothing downstream should branch on "how many intents".
        queue = IntentQueue().merge((intent(IntentCategory.TEST_DRIVE_BOOKING),))
        assert len(queue) == 1
        assert queue.primary is not None


class TestTheReducerAcrossTurns:
    """The reducer is where the guarantee lives — including on the turn seed.

    `IntentQueue.merge` was always correct. The loss happened one level up:
    `initial_state()` seeds an empty `IntentQueue`, LangGraph folds that seed
    into the checkpointed state on every turn after the first, and the
    reducer honoured it as "the new truth". Three intents became one the
    moment the customer answered a follow-up question.
    """

    def test_the_turn_seed_does_not_wipe_the_queue(self) -> None:
        from app.graph.state import initial_state, merge_intents

        accumulated = IntentQueue(
            intents=(
                intent(IntentCategory.TEST_DRIVE_BOOKING),
                intent(IntentCategory.TRADE_IN_VALUATION),
                intent(IntentCategory.FINANCING_EMI),
            )
        )
        seed = initial_state(
            conversation_id="c",
            inquiry_id="i",
            trace_id="t",
            raw_text="Renzo",
            channel="web_form",
        )

        merged = merge_intents(accumulated, seed["intents"])

        assert {i.category for i in merged.unresolved} == {
            IntentCategory.TEST_DRIVE_BOOKING,
            IntentCategory.TRADE_IN_VALUATION,
            IntentCategory.FINANCING_EMI,
        }

    def test_the_planner_can_still_replace_the_queue(self) -> None:
        # The authoritative-replace path exists so `enrich` and
        # `recompute_missing_slots` can rewrite policy-owned fields without
        # being merge-folded back into stale values. Guarding the empty case
        # must not cost that.
        from app.graph.state import merge_intents

        before = IntentQueue(intents=(intent(IntentCategory.TEST_DRIVE_BOOKING),))
        after = IntentQueue(
            intents=(
                intent(IntentCategory.TEST_DRIVE_BOOKING, priority=80).model_copy(
                    update={"department": Department.SALES}
                ),
            )
        )

        merged = merge_intents(before, after)
        assert merged.intents[0].priority == 80
        assert merged.intents[0].department is Department.SALES

    def test_an_empty_queue_is_kept_when_there_is_nothing_to_protect(self) -> None:
        from app.graph.state import merge_intents

        assert merge_intents(IntentQueue(), IntentQueue()).intents == ()

    def test_newly_discovered_intents_still_fold_in(self) -> None:
        # Guarding the empty case must not block the normal path: a tuple of
        # freshly discovered intents merges by category as before.
        from app.graph.state import merge_intents

        existing = IntentQueue(intents=(intent(IntentCategory.TEST_DRIVE_BOOKING),))
        merged = merge_intents(existing, (intent(IntentCategory.FINANCING_EMI),))

        assert {i.category for i in merged.unresolved} == {
            IntentCategory.TEST_DRIVE_BOOKING,
            IntentCategory.FINANCING_EMI,
        }
