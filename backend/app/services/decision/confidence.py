"""The confidence engine.

Confidence is treated as *evidence*, not as a probability. Six signals are
measured independently and reported separately, because a single blended
number cannot answer the only question a reviewer actually asks: what went
wrong here?

The weighted aggregation follows `domain/policies/confidence.yaml`, which
encodes the canonical formula from the specification. `entity` confidence is
displayed as first-class evidence but enters the score through `risk` — low
slot confidence *is* commercial risk, because it is what sends a lead to the
wrong department.
"""

from __future__ import annotations

from app.domain.entities import ConversationState
from app.domain.enums import ConfidenceSignal, EntityType, IntentCategory
from app.domain.policies import ConfidencePolicy, confidence_policy
from app.domain.value_objects import (
    ConfidenceVector,
    GroundingReport,
    LanguageProfile,
    RetrievedChunk,
    Sentiment,
)


def score_language(profile: LanguageProfile | None) -> float:
    """How sure we are which language to answer in."""
    return profile.confidence if profile else 0.0


def score_intent(state: ConversationState) -> float:
    """Confidence across the whole intent queue, not just the primary one.

    Averaging matters: a message with one confident intent and one guessed
    intent is not a confident message, and routing the guess automatically is
    exactly how a lead reaches the wrong department.
    """
    unresolved = state.intents.unresolved
    if not unresolved:
        return 0.0

    # An unclear intent is an honest outcome, but it is not a confident one.
    if any(
        i.category is IntentCategory.UNCLEAR_NEEDS_CLARIFICATION for i in unresolved
    ):
        return min(i.confidence for i in unresolved)

    return sum(i.confidence for i in unresolved) / len(unresolved)


def score_entity(state: ConversationState) -> float:
    """Slot fill rate weighted by per-entity confidence.

    Two failure modes are folded together deliberately: extracting nothing,
    and extracting something we do not believe. Both leave the pipeline
    acting on facts it does not have.
    """
    required: set[EntityType] = set()
    for intent in state.intents.unresolved:
        required |= set(intent.required_slots)

    if not required:
        return 1.0 if not state.entities else _mean_entity_confidence(state)

    filled = state.filled_slots & required
    fill_rate = len(filled) / len(required)

    if not filled:
        return 0.0

    return fill_rate * _mean_entity_confidence(state, restrict_to=filled)


def _mean_entity_confidence(
    state: ConversationState, restrict_to: set[EntityType] | None = None
) -> float:
    relevant = [
        e for e in state.entities if restrict_to is None or e.type in restrict_to
    ]
    if not relevant:
        return 0.0
    return sum(e.confidence for e in relevant) / len(relevant)


# Intents that legitimately need no supporting evidence — scoring their
# empty retrieval as zero would incorrectly drag the whole conversation
# below the auto threshold.
_INTENTS_WITHOUT_RETRIEVAL: set[IntentCategory] = {
    IntentCategory.SMALL_TALK,
    IntentCategory.COMPLAINT_ESCALATION,
}


def score_retrieval(
    chunks: tuple[RetrievedChunk, ...],
    state: ConversationState | None = None,
) -> float:
    """Retrieval quality, from the top chunk's score and its margin.

    Margin matters as much as absolute score. A top result that barely beats
    the runner-up means the retriever could not discriminate, which is a
    weaker signal than the raw number suggests.

    When the only open intents legitimately need no retrieval (small talk,
    complaint escalation), the absence of chunks is not a signal of poor
    retrieval — it is the correct state. Score it neutrally.
    """
    if not chunks:
        if state is not None and state.intents.unresolved:
            all_no_retrieval = all(
                i.category in _INTENTS_WITHOUT_RETRIEVAL
                for i in state.intents.unresolved
            )
            if all_no_retrieval:
                return 1.0
        return 0.0

    top = chunks[0].effective_score
    # Rerank scores are logits and can be negative; squash to [0, 1] without
    # assuming a particular scale.
    normalised = max(0.0, min(1.0, (top + 10) / 20)) if top < 0 or top > 1 else top

    if len(chunks) == 1:
        return normalised

    margin = max(0.0, chunks[0].effective_score - chunks[1].effective_score)
    confidence_from_margin = min(1.0, margin * 2)
    return round(0.75 * normalised + 0.25 * confidence_from_margin, 4)


def score_risk(
    state: ConversationState,
    entity_confidence: float,
    policy: ConfidencePolicy,
    *,
    has_financial_figure: bool = False,
) -> float:
    """Commercial exposure, expressed as a confidence.

    Starts at full confidence and subtracts for each condition that makes an
    automated reply more likely to cause damage. Inverted so that it composes
    with the other signals — higher is always safer everywhere in this module.
    """
    penalties = policy.risk_penalties
    risk = 1.0

    if entity_confidence < policy.entity_floor:
        risk -= penalties.low_entity_confidence

    if any(i.missing_slots for i in state.intents.unresolved):
        risk -= penalties.missing_required_slot

    sentiment: Sentiment | None = state.sentiment
    if sentiment:
        if sentiment.polarity.value == "negative":
            risk -= penalties.negative_sentiment
        if sentiment.urgency.value == "high":
            risk -= penalties.high_urgency

    if has_financial_figure:
        risk -= penalties.financial_figure_present

    if len(state.intents.unresolved) > 1:
        risk -= penalties.multi_intent

    return max(0.0, min(1.0, risk))


def score_policy(
    state: ConversationState, grounding: GroundingReport | None, policy: ConfidencePolicy
) -> float:
    """Whether the rules that govern this reply are satisfied."""
    score = 1.0

    if grounding is not None:
        # Faithfulness is the dominant term: an answer the evidence does not
        # support is a policy failure regardless of how confident everything
        # else is.
        score = min(score, grounding.faithfulness_score)
        if grounding.has_unsupported_numeric_claim:
            score = 0.0

    if state.human_handled:
        # Once a person has taken over, automation should not quietly resume.
        score = min(score, 0.4)

    for intent in state.intents.unresolved:
        if intent.category is IntentCategory.COMPLAINT_ESCALATION:
            score = 0.0

    return max(0.0, score)


def zero_confidence() -> ConfidenceVector:
    """An all-zero vector, used when scoring itself failed.

    A conversation whose confidence could not be measured must never be
    automated. Returning zero routes it to a person, which is the only safe
    reading of "we do not know".
    """
    return ConfidenceVector(
        language=0.0,
        intent=0.0,
        entity=0.0,
        retrieval=0.0,
        risk=0.0,
        policy=0.0,
        decision_score=0.0,
    )


def evaluate(
    state: ConversationState,
    *,
    chunks: tuple[RetrievedChunk, ...] = (),
    grounding: GroundingReport | None = None,
    has_financial_figure: bool = False,
    policy: ConfidencePolicy | None = None,
) -> ConfidenceVector:
    """Measure all six signals and aggregate them into a decision score."""
    policy = policy or confidence_policy()

    language = score_language(state.language)
    intent = score_intent(state)
    entity = score_entity(state)
    retrieval = score_retrieval(chunks, state)
    risk = score_risk(state, entity, policy, has_financial_figure=has_financial_figure)
    policy_score = score_policy(state, grounding, policy)

    weighted = (
        policy.weight(ConfidenceSignal.INTENT) * intent
        + policy.weight(ConfidenceSignal.RETRIEVAL) * retrieval
        + policy.weight(ConfidenceSignal.LANGUAGE) * language
        + policy.weight(ConfidenceSignal.RISK) * risk
        + policy.weight(ConfidenceSignal.POLICY) * policy_score
    )

    return ConfidenceVector(
        language=round(language, 4),
        intent=round(intent, 4),
        entity=round(entity, 4),
        retrieval=round(retrieval, 4),
        risk=round(risk, 4),
        policy=round(policy_score, 4),
        decision_score=round(min(100.0, max(0.0, weighted * 100)), 2),
    )
