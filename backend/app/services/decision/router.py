"""The decision layer: answer now, clarify, route, or escalate.

Business rules own this, not the model. The model reported what it heard; this
decides who handles it and with what care. Keeping the two apart is what makes
every routing decision reproducible and explainable.

Hard overrides run *before* the score is consulted. A weighted average can
always be dragged over a threshold by strong unrelated signals, and confident
retrieval must never be able to authorise auto-sending a reply to a furious
customer.
"""

from __future__ import annotations

from app.domain.entities import ConversationState
from app.domain.enums import (
    Department,
    HumanReviewReason,
    IntentCategory,
    ModelTier,
    RoutingTier,
)
from app.domain.policies import ConfidencePolicy, IntentPolicy, confidence_policy, intent_policy
from app.domain.value_objects import ConfidenceVector, GroundingReport, RoutingDecision


def decide_department(
    state: ConversationState, policy: IntentPolicy | None = None
) -> Department | None:
    """Which team owns this conversation.

    Driven by the primary intent, which is the one the reply addresses. Other
    intents keep their own department assignment on the queue and are notified
    separately — a three-intent message legitimately involves three teams.
    """
    policy = policy or intent_policy()
    primary = state.intents.primary
    if primary is None:
        return None
    return primary.department or policy.rule(primary.category).department


def _fired_overrides(
    state: ConversationState,
    grounding: GroundingReport | None,
    policy: ConfidencePolicy,
) -> list[tuple[str, HumanReviewReason]]:
    """Conditions that force a human regardless of score."""
    fired: list[tuple[str, HumanReviewReason]] = []
    categories = {i.category for i in state.intents.unresolved}

    for override in policy.hard_overrides:
        match override.when:
            case "intent_category_is":
                if override.value and IntentCategory(override.value) in categories:
                    fired.append((override.id, override.reason))
            case "sentiment_negative_and_urgent":
                if state.sentiment and state.sentiment.demands_human:
                    fired.append((override.id, override.reason))
            case "grounding_not_passed":
                if grounding is not None and not grounding.passes:
                    fired.append((override.id, override.reason))
            case "numeric_claim_unsupported":
                if grounding is not None and grounding.has_unsupported_numeric_claim:
                    fired.append((override.id, override.reason))
            case "conversation_touched_by_human":
                if state.human_handled:
                    fired.append((override.id, override.reason))

    # A category flagged force_human in intent policy is equivalent to an
    # override, expressed where the rest of that category's rules live.
    intents = intent_policy()
    for category in categories:
        if intents.rule(category).force_human:
            entry = (f"force_human:{category.value}", HumanReviewReason.POLICY_REQUIRES_APPROVAL)
            if entry not in fired:
                fired.append(entry)

    return fired


def route(
    state: ConversationState,
    confidence: ConfidenceVector,
    *,
    grounding: GroundingReport | None = None,
    policy: ConfidencePolicy | None = None,
    allow_auto_send: bool = False,
) -> RoutingDecision:
    """Produce the routing decision, with the reasoning that justifies it."""
    policy = policy or confidence_policy()
    department = decide_department(state)
    overrides = _fired_overrides(state, grounding, policy)

    # ── Hard overrides ────────────────────────────────────────────────
    if overrides:
        reasons = ", ".join(reason.value.replace("_", " ") for _, reason in overrides)
        return RoutingDecision(
            tier=RoutingTier.HUMAN,
            department=department,
            model_tier=None,
            rule_id=overrides[0][0],
            rationale=(
                f"Escalated to a person because {reasons}. This overrides the computed "
                f"score of {confidence.decision_score:.0f}."
            ),
            confidence=confidence,
            overrides_applied=tuple(rule_id for rule_id, _ in overrides),
        )

    score = confidence.decision_score
    weakest = confidence.weakest_signal
    weakest_value = confidence.signal(weakest)

    # ── Score bands ───────────────────────────────────────────────────
    if score >= policy.thresholds.auto:
        return RoutingDecision(
            tier=RoutingTier.AUTO,
            department=department,
            model_tier=ModelTier.FAST,
            rule_id="score_auto",
            rationale=(
                f"Score {score:.0f} clears the automatic threshold of "
                f"{policy.thresholds.auto:.0f}. "
                + (
                    "Reply may be sent automatically."
                    if allow_auto_send
                    else "Auto-send is disabled, so the reply is drafted for approval."
                )
            ),
            confidence=confidence,
        )

    if score >= policy.thresholds.premium:
        return RoutingDecision(
            tier=RoutingTier.PREMIUM,
            department=department,
            model_tier=ModelTier.PREMIUM,
            rule_id="score_premium",
            rationale=(
                f"Score {score:.0f} sits between {policy.thresholds.premium:.0f} and "
                f"{policy.thresholds.auto:.0f}, so the premium model handles it. "
                f"Weakest signal: {weakest.value} at {weakest_value:.2f}."
            ),
            confidence=confidence,
        )

    return RoutingDecision(
        tier=RoutingTier.HUMAN,
        department=department,
        model_tier=None,
        rule_id="score_below_threshold",
        rationale=(
            f"Score {score:.0f} is below the {policy.thresholds.premium:.0f} threshold, so "
            f"a person reviews this. Weakest signal: {weakest.value} at "
            f"{weakest_value:.2f}."
        ),
        confidence=confidence,
    )


def escalation_reason(decision: RoutingDecision) -> HumanReviewReason:
    """Why this reached a person, recorded verbatim on the queue item.

    Decomposable on purpose: a spike in `low_confidence` is a model problem
    and a spike in `grounding_failed` is a retrieval problem, and they need
    different fixes.
    """
    mapping = {
        "complaint_always_human": HumanReviewReason.COMPLAINT,
        "negative_high_urgency": HumanReviewReason.NEGATIVE_SENTIMENT,
        "grounding_failed": HumanReviewReason.GROUNDING_FAILED,
        "unsupported_financial_claim": HumanReviewReason.UNSUPPORTED_FINANCIAL_CLAIM,
        "previously_human_handled": HumanReviewReason.PREVIOUSLY_HUMAN_HANDLED,
    }
    for applied in decision.overrides_applied:
        if applied in mapping:
            return mapping[applied]
        if applied.startswith("force_human:"):
            return HumanReviewReason.POLICY_REQUIRES_APPROVAL
    return HumanReviewReason.LOW_CONFIDENCE
