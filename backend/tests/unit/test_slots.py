"""Slot satisfaction, and the two consumers agreeing about it.

The planner and the confidence engine both decide whether a required slot is
filled. When they disagreed, the platform asked no question — the planner was
satisfied — and escalated anyway, because the confidence engine scored the
same conversation 0.00. These tests exist to keep them in step.
"""

from __future__ import annotations

from app.domain.entities import ConversationState, Intent, IntentQueue
from app.domain.enums import EntityType, IntentCategory
from app.domain.slots import is_slot_filled, satisfying_types
from app.domain.value_objects import ExtractedEntity
from app.services.decision.confidence import score_entity
from app.services.planning.planner import recompute_missing_slots


def entity(kind: EntityType, value: str, confidence: float = 0.95) -> ExtractedEntity:
    return ExtractedEntity(
        type=kind, value=value, raw_value=value, confidence=confidence
    )


def unclear_about_a_known_vehicle() -> ConversationState:
    """The exact shape that was scoring zero.

    A short reply gets classified `unclear_needs_clarification`, whose only
    required slot is `vehicle_reference` — but the extractor produced brand
    and model, which is strictly more information.
    """
    return ConversationState(
        conversation_id="conv_slots",
        intents=IntentQueue(
            intents=(
                Intent(
                    category=IntentCategory.UNCLEAR_NEEDS_CLARIFICATION,
                    confidence=0.85,
                    required_slots=(EntityType.VEHICLE_REFERENCE,),
                    missing_slots=(EntityType.VEHICLE_REFERENCE,),
                ),
            )
        ),
        entities=(
            entity(EntityType.NEW_VEHICLE_BRAND, "Renzo"),
            entity(EntityType.NEW_VEHICLE_MODEL, "S5"),
        ),
    )


class TestTheAliasRule:
    def test_a_brand_satisfies_a_vehicle_reference(self) -> None:
        assert is_slot_filled(
            EntityType.VEHICLE_REFERENCE, {EntityType.NEW_VEHICLE_BRAND}
        )

    def test_an_unrelated_slot_does_not(self) -> None:
        assert not is_slot_filled(
            EntityType.VEHICLE_REFERENCE, {EntityType.PREFERRED_DATE}
        )

    def test_a_slot_with_no_aliases_needs_itself(self) -> None:
        assert not is_slot_filled(
            EntityType.PREFERRED_DATE, {EntityType.NEW_VEHICLE_BRAND}
        )
        assert is_slot_filled(EntityType.PREFERRED_DATE, {EntityType.PREFERRED_DATE})

    def test_satisfying_types_names_only_the_entities_that_did_the_work(self) -> None:
        # The averaged confidence must come from the entities that actually
        # satisfied the requirement, not from every entity in the state.
        types = satisfying_types(
            EntityType.VEHICLE_REFERENCE,
            {
                EntityType.NEW_VEHICLE_BRAND,
                EntityType.NEW_VEHICLE_MODEL,
                EntityType.PREFERRED_DATE,
            },
        )
        assert types == {
            EntityType.NEW_VEHICLE_BRAND,
            EntityType.NEW_VEHICLE_MODEL,
        }

    def test_a_directly_filled_slot_credits_itself(self) -> None:
        assert satisfying_types(
            EntityType.VEHICLE_REFERENCE, {EntityType.VEHICLE_REFERENCE}
        ) == {EntityType.VEHICLE_REFERENCE}


class TestThePlannerAndTheScorerAgree:
    def test_the_planner_considers_the_slot_filled(self) -> None:
        state = unclear_about_a_known_vehicle()
        queue = recompute_missing_slots(state.intents, state.filled_slots)
        assert queue.intents[0].missing_slots == (), (
            "the planner should not ask which vehicle when brand and model "
            "are already known"
        )

    def test_the_scorer_no_longer_reports_zero(self) -> None:
        # The bug: brand and model extracted at 0.95, and this returned 0.00
        # because neither type is literally `vehicle_reference`.
        assert score_entity(unclear_about_a_known_vehicle()) > 0.9

    def test_genuinely_missing_information_still_scores_zero(self) -> None:
        # Loosening the rule must not make the signal unable to fire.
        state = ConversationState(
            conversation_id="conv_empty",
            intents=IntentQueue(
                intents=(
                    Intent(
                        category=IntentCategory.TEST_DRIVE_BOOKING,
                        confidence=0.9,
                        required_slots=(
                            EntityType.NEW_VEHICLE_BRAND,
                            EntityType.PREFERRED_DATE,
                        ),
                        missing_slots=(
                            EntityType.NEW_VEHICLE_BRAND,
                            EntityType.PREFERRED_DATE,
                        ),
                    ),
                )
            ),
            entities=(),
        )
        assert score_entity(state) == 0.0

    def test_a_partial_fill_scores_partially(self) -> None:
        state = ConversationState(
            conversation_id="conv_partial",
            intents=IntentQueue(
                intents=(
                    Intent(
                        category=IntentCategory.TEST_DRIVE_BOOKING,
                        confidence=0.9,
                        required_slots=(
                            EntityType.NEW_VEHICLE_BRAND,
                            EntityType.PREFERRED_DATE,
                        ),
                        missing_slots=(EntityType.PREFERRED_DATE,),
                    ),
                )
            ),
            entities=(entity(EntityType.NEW_VEHICLE_BRAND, "Renzo", 1.0),),
        )
        # One of two required slots, at full confidence.
        assert score_entity(state) == 0.5
