"""When a required slot counts as satisfied.

Some requirements are satisfiable by more specific facts. `vehicle_reference`
means "we know which car they mean" — a brand and model say that more
precisely than the generic slot ever could, so extracting them satisfies it.

This lives in the domain rather than in either service because both the
planner and the confidence engine have to agree on it. They did not: the
planner applied the rule and stopped asking for the slot, while the
confidence engine did a plain set intersection, scored the entity signal
0.00, and escalated a conversation whose extraction had in fact worked
perfectly. Two halves of the system disagreeing about the same fact is the
kind of bug that reads as model flakiness for weeks.
"""

from __future__ import annotations

from app.domain.enums import EntityType

SLOT_ALIASES: dict[EntityType, tuple[EntityType, ...]] = {
    EntityType.VEHICLE_REFERENCE: (
        EntityType.NEW_VEHICLE_BRAND,
        EntityType.NEW_VEHICLE_MODEL,
        EntityType.OLD_VEHICLE_BRAND,
        EntityType.OLD_VEHICLE_MODEL,
    ),
}


def is_slot_filled(slot: EntityType, filled: set[EntityType]) -> bool:
    """Whether a required slot has been satisfied, directly or by an alias."""
    if slot in filled:
        return True
    return any(alias in filled for alias in SLOT_ALIASES.get(slot, ()))


def satisfying_types(slot: EntityType, filled: set[EntityType]) -> set[EntityType]:
    """The extracted entity types that actually satisfy `slot`.

    Needed because a confidence score is only as good as the entities it
    averages: crediting `vehicle_reference` while averaging the confidence of
    entities that had nothing to do with it would be a different kind of wrong
    answer.
    """
    if slot in filled:
        return {slot}
    return set(SLOT_ALIASES.get(slot, ())) & filled
