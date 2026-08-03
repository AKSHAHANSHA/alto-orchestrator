"""Tests for the deterministic planning and decision layers.

The claim under test is that these layers make no model calls and are pure
functions of state plus policy — so identical input yields byte-identical
plans and routing, every time.
"""

from __future__ import annotations

import pytest

from app.domain.entities import ConversationState, Intent, IntentQueue
from app.domain.enums import (
    Department,
    EntityType,
    GroundingVerdict,
    HumanReviewReason,
    IntentCategory,
    IntentStatus,
    Language,
    ModelTier,
    Polarity,
    RoutingTier,
    Urgency,
)
from app.domain.value_objects import (
    Claim,
    ConfidenceVector,
    ExtractedEntity,
    GroundingReport,
    LanguageProfile,
    RoutingDecision,
    Sentiment,
)
from app.services.decision import confidence as conf
from app.services.decision.router import decide_department, escalation_reason, route
from app.services.planning.planner import build_plan, enrich, recompute_missing_slots


def intent(category: IntentCategory, confidence: float = 0.9, primary: bool = False) -> Intent:
    return Intent(category=category, confidence=confidence, is_primary=primary)


def entity(entity_type: EntityType, value: str, confidence: float = 0.9) -> ExtractedEntity:
    return ExtractedEntity(
        type=entity_type, value=value, raw_value=value, confidence=confidence
    )


def state(
    *intents: Intent,
    entities: tuple[ExtractedEntity, ...] = (),
    sentiment: Sentiment | None = None,
    human_handled: bool = False,
) -> ConversationState:
    return ConversationState(
        conversation_id="conv_test",
        language=LanguageProfile(
            primary=Language.ENGLISH,
            has_arabic=False,
            is_mixed=False,
            arabic_char_ratio=0.0,
            confidence=0.95,
        ),
        sentiment=sentiment,
        intents=IntentQueue(intents=intents),
        entities=entities,
        human_handled=human_handled,
    )


class TestEnrichment:
    def test_business_rules_assign_department_and_priority(self) -> None:
        # The model reported a category; the rule engine decides everything else.
        queue = enrich(IntentQueue(intents=(intent(IntentCategory.TRADE_IN_VALUATION),)))
        assigned = queue.intents[0]
        assert assigned.department is Department.TRADE_IN
        assert assigned.priority == 60
        assert EntityType.OLD_VEHICLE_MODEL in assigned.required_slots

    def test_financing_depends_on_a_trade_in_when_both_are_present(self) -> None:
        # The part-exchange changes the financeable amount, so quoting first
        # would give a number that has to be retracted.
        queue = enrich(
            IntentQueue(
                intents=(
                    intent(IntentCategory.TRADE_IN_VALUATION),
                    intent(IntentCategory.FINANCING_EMI),
                )
            )
        )
        financing = queue.by_category(IntentCategory.FINANCING_EMI)
        trade_in = queue.by_category(IntentCategory.TRADE_IN_VALUATION)
        assert financing is not None and trade_in is not None
        assert financing.depends_on == (trade_in.id,)

    def test_financing_alone_has_no_dependency(self) -> None:
        # A cash-free customer with no trade-in must not be blocked by one.
        queue = enrich(IntentQueue(intents=(intent(IntentCategory.FINANCING_EMI),)))
        assert queue.intents[0].depends_on == ()

    def test_a_resolved_trade_in_no_longer_blocks_financing(self) -> None:
        done = intent(IntentCategory.TRADE_IN_VALUATION).transition(IntentStatus.RESOLVED)
        queue = enrich(IntentQueue(intents=(done, intent(IntentCategory.FINANCING_EMI))))
        financing = queue.by_category(IntentCategory.FINANCING_EMI)
        assert financing is not None and financing.depends_on == ()


class TestPlanning:
    def test_a_plan_is_a_pure_function_of_its_input(self) -> None:
        queue = enrich(
            IntentQueue(
                intents=(
                    intent(IntentCategory.TRADE_IN_VALUATION),
                    intent(IntentCategory.FINANCING_EMI),
                )
            )
        )
        queue = recompute_missing_slots(queue, set())

        first, second = build_plan(queue), build_plan(queue)
        assert first == second, "the same queue must always produce the same plan"

    def test_steps_are_ordered_by_policy_priority(self) -> None:
        queue = enrich(
            IntentQueue(
                intents=(
                    intent(IntentCategory.VEHICLE_AVAILABILITY_INFO),
                    intent(IntentCategory.COMPLAINT_ESCALATION),
                    intent(IntentCategory.TEST_DRIVE_BOOKING),
                )
            )
        )
        plan = build_plan(queue)
        assert plan.steps[0].department is Department.CUSTOMER_RELATIONS

    def test_next_action_asks_for_information_before_acting(self) -> None:
        # An incomplete step performed now gives a wrong answer; one question
        # gives a right one.
        queue = recompute_missing_slots(
            enrich(IntentQueue(intents=(intent(IntentCategory.TRADE_IN_VALUATION),))), set()
        )
        plan = build_plan(queue)
        assert plan.next_action is not None
        assert plan.next_action.startswith("ask_")

    def test_next_action_becomes_the_step_once_slots_are_filled(self) -> None:
        filled = {
            EntityType.OLD_VEHICLE_BRAND,
            EntityType.OLD_VEHICLE_MODEL,
            EntityType.OLD_VEHICLE_YEAR,
        }
        queue = recompute_missing_slots(
            enrich(IntentQueue(intents=(intent(IntentCategory.TRADE_IN_VALUATION),))), filled
        )
        assert build_plan(queue).next_action == "estimate_trade_in"

    def test_filling_slots_releases_the_waiting_state(self) -> None:
        queue = enrich(IntentQueue(intents=(intent(IntentCategory.TRADE_IN_VALUATION),)))
        waiting = recompute_missing_slots(queue, set())
        assert waiting.intents[0].status is IntentStatus.WAITING_INFORMATION

        complete = recompute_missing_slots(
            queue,
            {
                EntityType.OLD_VEHICLE_BRAND,
                EntityType.OLD_VEHICLE_MODEL,
                EntityType.OLD_VEHICLE_YEAR,
            },
        )
        assert complete.intents[0].status is IntentStatus.PENDING


class TestConfidenceSignals:
    def test_intent_confidence_averages_the_whole_queue(self) -> None:
        # One confident intent plus one guess is not a confident message.
        mixed = state(
            intent(IntentCategory.FINANCING_EMI, 0.95),
            intent(IntentCategory.TEST_DRIVE_BOOKING, 0.55),
        )
        assert conf.score_intent(mixed) == pytest.approx(0.75)

    def test_an_unclear_intent_drags_confidence_to_its_floor(self) -> None:
        unclear = state(
            intent(IntentCategory.UNCLEAR_NEEDS_CLARIFICATION, 0.4),
            intent(IntentCategory.VEHICLE_AVAILABILITY_INFO, 0.9),
        )
        assert conf.score_intent(unclear) == pytest.approx(0.4)

    def test_entity_confidence_is_zero_when_nothing_is_filled(self) -> None:
        queue = recompute_missing_slots(
            enrich(IntentQueue(intents=(intent(IntentCategory.TRADE_IN_VALUATION),))), set()
        )
        assert conf.score_entity(state(*queue.intents)) == 0.0

    def test_empty_retrieval_scores_zero(self) -> None:
        assert conf.score_retrieval(()) == 0.0

    def test_negative_sentiment_reduces_the_risk_signal(self) -> None:
        from app.domain.policies import confidence_policy

        calm = state(intent(IntentCategory.FINANCING_EMI))
        angry = state(
            intent(IntentCategory.FINANCING_EMI),
            sentiment=Sentiment(
                polarity=Polarity.NEGATIVE,
                urgency=Urgency.HIGH,
                frustration_score=0.9,
                confidence=0.8,
            ),
        )
        policy = confidence_policy()
        assert conf.score_risk(angry, 0.9, policy) < conf.score_risk(calm, 0.9, policy)

    def test_the_weakest_signal_is_identifiable(self) -> None:
        vector = conf.evaluate(state(intent(IntentCategory.FINANCING_EMI, 0.95)))
        assert vector.signal(vector.weakest_signal) == min(vector.as_dict().values())


class TestRouting:
    def test_high_confidence_answers_automatically_on_the_writing_model(self) -> None:
        # `model_tier` selects the model that *writes the reply*, and the
        # fast tier is not fast at writing: gpt-5-mini measured 34-36s and
        # 4,200 completion tokens on a three-intent reply where gpt-4o took
        # under 3s and 252. Answering automatically is about the routing
        # tier; which model writes it is a separate question, and the
        # premium model wins it on latency, length and cost.
        from app.domain.value_objects import ConfidenceVector

        vector = ConfidenceVector(
            language=1.0, intent=1.0, entity=1.0, retrieval=1.0, risk=1.0, policy=1.0,
            decision_score=95.0,
        )
        decision = route(state(intent(IntentCategory.VEHICLE_AVAILABILITY_INFO)), vector)
        assert decision.tier is RoutingTier.AUTO
        assert decision.model_tier is ModelTier.PREMIUM

    def test_mid_confidence_routes_to_the_premium_model(self) -> None:
        from app.domain.value_objects import ConfidenceVector

        vector = ConfidenceVector(
            language=0.9, intent=0.8, entity=0.7, retrieval=0.8, risk=0.8, policy=0.8,
            decision_score=82.0,
        )
        decision = route(state(intent(IntentCategory.FINANCING_EMI)), vector)
        assert decision.tier is RoutingTier.PREMIUM
        assert decision.model_tier is ModelTier.PREMIUM

    def test_low_confidence_escalates_to_a_person(self) -> None:
        from app.domain.value_objects import ConfidenceVector

        vector = ConfidenceVector(
            language=0.5, intent=0.4, entity=0.2, retrieval=0.3, risk=0.5, policy=0.6,
            decision_score=44.0,
        )
        decision = route(state(intent(IntentCategory.UNCLEAR_NEEDS_CLARIFICATION, 0.4)), vector)
        assert decision.tier is RoutingTier.HUMAN
        assert decision.model_tier is None
        assert "below" in decision.rationale.lower()

    def test_the_rationale_names_the_weakest_signal(self) -> None:
        from app.domain.value_objects import ConfidenceVector

        vector = ConfidenceVector(
            language=0.95, intent=0.85, entity=0.15, retrieval=0.8, risk=0.8, policy=0.9,
            decision_score=80.0,
        )
        decision = route(state(intent(IntentCategory.FINANCING_EMI)), vector)
        assert "entity" in decision.rationale or "risk" in decision.rationale


class TestHardOverrides:
    """A weighted average must never be able to authorise these."""

    def test_a_complaint_always_reaches_a_person(self) -> None:
        from app.domain.value_objects import ConfidenceVector

        perfect = ConfidenceVector(
            language=1.0, intent=1.0, entity=1.0, retrieval=1.0, risk=1.0, policy=1.0,
            decision_score=100.0,
        )
        decision = route(state(intent(IntentCategory.COMPLAINT_ESCALATION)), perfect)
        assert decision.tier is RoutingTier.HUMAN
        assert decision.overrides_applied

    def test_an_unsupported_financial_claim_blocks_automation(self) -> None:
        from app.domain.value_objects import ConfidenceVector

        perfect = ConfidenceVector(
            language=1.0, intent=1.0, entity=1.0, retrieval=1.0, risk=1.0, policy=1.0,
            decision_score=98.0,
        )
        grounding = GroundingReport(
            verdict=GroundingVerdict.UNGROUNDED,
            claims=(Claim(text="The rate is 2.5%", is_numeric=True),),
            faithfulness_score=0.2,
        )
        decision = route(
            state(intent(IntentCategory.FINANCING_EMI)), perfect, grounding=grounding
        )
        assert decision.tier is RoutingTier.HUMAN
        # Recorded precisely: a grounding spike is a retrieval problem, not a
        # model-confidence one, and the two need different fixes.
        assert escalation_reason(decision) in {
            HumanReviewReason.GROUNDING_FAILED,
            HumanReviewReason.UNSUPPORTED_FINANCIAL_CLAIM,
        }

    def test_automation_does_not_resume_after_a_human_took_over(self) -> None:
        from app.domain.value_objects import ConfidenceVector

        perfect = ConfidenceVector(
            language=1.0, intent=1.0, entity=1.0, retrieval=1.0, risk=1.0, policy=1.0,
            decision_score=97.0,
        )
        decision = route(
            state(intent(IntentCategory.FINANCING_EMI), human_handled=True), perfect
        )
        assert decision.tier is RoutingTier.HUMAN

    def test_an_override_says_it_overrode_the_score(self) -> None:
        from app.domain.value_objects import ConfidenceVector

        perfect = ConfidenceVector(
            language=1.0, intent=1.0, entity=1.0, retrieval=1.0, risk=1.0, policy=1.0,
            decision_score=99.0,
        )
        decision = route(state(intent(IntentCategory.COMPLAINT_ESCALATION)), perfect)
        assert "overrides" in decision.rationale.lower()


class TestDepartmentRouting:
    @pytest.mark.parametrize(
        ("category", "expected"),
        [
            (IntentCategory.FINANCING_EMI, Department.FINANCE),
            (IntentCategory.TRADE_IN_VALUATION, Department.TRADE_IN),
            (IntentCategory.TEST_DRIVE_BOOKING, Department.SALES),
            (IntentCategory.SERVICE_AFTERSALES, Department.SERVICE),
            (IntentCategory.COMPLAINT_ESCALATION, Department.CUSTOMER_RELATIONS),
        ],
    )
    def test_each_category_reaches_its_owning_team(
        self, category: IntentCategory, expected: Department
    ) -> None:
        # The model never makes this call; policy does.
        queue = enrich(IntentQueue(intents=(intent(category, primary=True),)))
        assert decide_department(state(*queue.intents)) is expected


class TestEscalationReasonReflectsWhatActuallyStopped:
    """The queue reason has to be actionable, not merely present.

    Seen in production: score 91.99, every signal healthy, tier `auto`, and
    the draft rejected for quoting a figure no tool produced — filed as
    `low_confidence`. That reading came from the routing decision alone,
    which is computed *before* grounding runs and therefore cannot know.
    A spike in `low_confidence` sends someone to look at the model; a spike
    in `unsupported_financial_claim` sends them to look at the tools.
    """

    def _decision(self, score: float) -> RoutingDecision:
        return RoutingDecision(
            tier=RoutingTier.AUTO,
            department=Department.SALES,
            model_tier=ModelTier.FAST,
            rule_id="score_auto",
            rationale="clears the automatic threshold",
            confidence=ConfidenceVector(
                language=0.95, intent=0.92, entity=0.98,
                retrieval=0.94, risk=0.8, policy=1.0,
                decision_score=score,
            ),
        )

    def test_an_unsourced_figure_is_named_as_such(self) -> None:
        grounding = GroundingReport(
            verdict=GroundingVerdict.UNGROUNDED,
            claims=(
                Claim(text="The instalment is 801 AED.", is_numeric=True),
            ),
            faithfulness_score=0.85,
        )
        assert (
            escalation_reason(self._decision(91.99), grounding)
            is HumanReviewReason.UNSUPPORTED_FINANCIAL_CLAIM
        )

    def test_a_qualitative_grounding_failure_is_distinguished(self) -> None:
        grounding = GroundingReport(
            verdict=GroundingVerdict.UNGROUNDED,
            claims=(Claim(text="We are the best dealer around.", is_numeric=False),),
            faithfulness_score=0.0,
        )
        assert (
            escalation_reason(self._decision(91.99), grounding)
            is HumanReviewReason.GROUNDING_FAILED
        )

    def test_a_passing_report_does_not_mask_the_real_reason(self) -> None:
        grounding = GroundingReport(
            verdict=GroundingVerdict.GROUNDED, claims=(), faithfulness_score=1.0
        )
        assert (
            escalation_reason(self._decision(40.0), grounding)
            is HumanReviewReason.LOW_CONFIDENCE
        )

    def test_no_grounding_report_keeps_the_previous_behaviour(self) -> None:
        assert (
            escalation_reason(self._decision(40.0))
            is HumanReviewReason.LOW_CONFIDENCE
        )
