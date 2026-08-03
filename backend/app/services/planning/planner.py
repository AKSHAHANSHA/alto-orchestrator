"""The planning layer: what should happen.

A rule engine, not a prompt. Given an intent queue and the entities gathered
so far, the plan is a pure function of policy — so the same conversation
always produces the same plan, the plan can be diffed when policy changes,
and it cannot hallucinate a step.

This is the layer where a model observation ("intent = trade_in, 0.96")
becomes work ("Trade-In team, needs model/year/mileage, blocks the financing
quote"). The model never makes that leap; this does.
"""

from __future__ import annotations

from app.domain.entities import Intent, IntentQueue
from app.domain.enums import EntityType, IntentCategory, IntentStatus
from app.domain.policies import IntentPolicy, intent_policy
from app.domain.slots import is_slot_filled
from app.domain.value_objects import Plan, PlanStep

# Slot equivalences.
#
# The required slot on an intent is often a *type* of information, not a
# specific slot name. `vehicle_reference` means "the customer has identified
# which vehicle we are talking about" — and naming a brand (with or without
# a model) is a valid way to do that. Without this mapping the planner would
# keep asking "which vehicle?" of a customer who has already answered with a
# brand, because the specific slot name "vehicle_reference" was never filled.
#
# The dict is one-way: a required slot on the left is satisfied by *any* of
# the entity types on the right (in addition to itself).
# Human-readable action verbs per category, used in the plan and in the
# admin UI. Kept beside the planner rather than in policy because they
# describe what this code does, not a business rule that gets tuned.
ACTIONS: dict[IntentCategory, str] = {
    IntentCategory.TEST_DRIVE_BOOKING: "book_test_drive",
    IntentCategory.FINANCING_EMI: "prepare_financing_quote",
    IntentCategory.TRADE_IN_VALUATION: "estimate_trade_in",
    IntentCategory.VEHICLE_AVAILABILITY_INFO: "check_availability",
    IntentCategory.PRICING_OFFERS: "provide_pricing",
    IntentCategory.SERVICE_AFTERSALES: "route_to_service",
    IntentCategory.COMPLAINT_ESCALATION: "escalate_complaint",
    IntentCategory.GENERAL_INFO: "answer_general",
    IntentCategory.SMALL_TALK: "acknowledge",
    IntentCategory.UNCLEAR_NEEDS_CLARIFICATION: "request_clarification",
}


def enrich(queue: IntentQueue, policy: IntentPolicy | None = None) -> IntentQueue:
    """Apply business rules to raw model observations.

    Assigns the department, priority, required slots and cross-intent
    dependencies that the understanding layer deliberately does not produce.
    Runs before planning and before any routing decision.
    """
    policy = policy or intent_policy()
    present = {i.category for i in queue.intents if not i.is_resolved}
    enriched: list[Intent] = []

    for intent in queue.intents:
        if intent.is_resolved:
            enriched.append(intent)
            continue

        rule = policy.rule(intent.category)

        # A dependency only binds when the other intent is actually in play.
        # Financing depends on a trade-in valuation *if the customer is
        # trading something in* — a customer paying cash outright is not
        # blocked by a trade-in that was never requested.
        blocking_ids = tuple(
            other.id
            for other in queue.intents
            if other.category in rule.depends_on_categories
            and other.category in present
            and not other.is_resolved
        )

        enriched.append(
            intent.model_copy(
                update={
                    "department": rule.department,
                    "priority": rule.priority,
                    "required_slots": rule.required_slots,
                    "depends_on": blocking_ids,
                }
            )
        )

    return IntentQueue(intents=tuple(enriched))


def recompute_missing_slots(
    queue: IntentQueue, filled: set[EntityType], policy: IntentPolicy | None = None
) -> IntentQueue:
    """Recalculate what each intent is still waiting on.

    Derived from the required-slot policy and the entities gathered so far
    rather than carried forward, so a slot filled three turns ago is never
    asked for again.
    """
    policy = policy or intent_policy()
    updated: list[Intent] = []

    for intent in queue.intents:
        if intent.is_resolved:
            updated.append(intent)
            continue

        rule = policy.rule(intent.category)
        missing = tuple(
            slot for slot in rule.required_slots if not is_slot_filled(slot, filled)
        )

        status = intent.status
        if missing and status in {IntentStatus.PENDING, IntentStatus.ROUTED}:
            status = IntentStatus.WAITING_INFORMATION
        elif not missing and status is IntentStatus.WAITING_INFORMATION:
            status = IntentStatus.PENDING

        updated.append(
            intent.model_copy(update={"missing_slots": missing, "status": status})
        )

    return IntentQueue(intents=tuple(updated))


def build_plan(queue: IntentQueue, policy: IntentPolicy | None = None) -> Plan:
    """Turn an enriched intent queue into an ordered set of steps.

    Ordering comes from `IntentQueue.ordered()`, which sorts by policy
    priority with a deterministic tiebreak. `next_action` names the single
    most useful thing to do now — asking for a missing fact if one blocks the
    highest-priority step, otherwise performing that step.
    """
    policy = policy or intent_policy()
    steps: list[PlanStep] = []

    for order, intent in enumerate(queue.ordered()):
        steps.append(
            PlanStep(
                order=order,
                intent_id=intent.id,
                action=ACTIONS.get(intent.category, "route_to_department"),
                department=intent.department or policy.rule(intent.category).department,
                required_slots=intent.required_slots,
                missing_slots=intent.missing_slots,
                blocked_by=intent.depends_on,
            )
        )

    return Plan(steps=tuple(steps), next_action=_next_action(steps, policy))


def _next_action(steps: tuple[PlanStep, ...] | list[PlanStep], policy: IntentPolicy) -> str | None:
    """The one thing to do next.

    Information gathering wins over execution: an incomplete step performed
    now produces a wrong answer, whereas one question produces a right one.
    The slot chosen is the highest-priority missing slot across the whole
    plan, so a single question can unblock several steps at once.
    """
    if not steps:
        return None

    for step in steps:
        if step.missing_slots:
            slot = policy.next_question_slot(set(step.missing_slots))
            if slot is not None:
                return f"ask_{slot.value}"

    actionable = next((s for s in steps if s.is_actionable), None)
    if actionable is not None:
        return actionable.action

    # Everything is blocked by a dependency rather than by missing facts.
    return steps[0].action
