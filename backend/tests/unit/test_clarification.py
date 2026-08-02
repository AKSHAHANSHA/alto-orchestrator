"""Clarification writing.

The question itself is a policy decision and must never move. What a model is
allowed to change is the wording — and only when we can vouch for every figure
in it. These tests pin both halves of that: the template is the floor, and the
model path is rejected the moment it states something we did not hand it.
"""

from __future__ import annotations

import json

import pytest

from app.domain.entities import ConversationState, Intent, IntentQueue
from app.domain.enums import Department, EntityType, IntentCategory, Language
from app.domain.ports import LLMResponse
from app.domain.value_objects import LanguageProfile, Plan, PlanStep, TokenUsage
from app.services.execution.clarification import ClarificationWriter

CATALOG_RESULTS = {
    "catalog": {
        "new_vehicle": {
            "verdict": "in_stock",
            "explanation": "In stock at the Ras Al Khor showroom.",
            "matches": [
                {
                    "brand": "Renzo",
                    "model": "S5",
                    "year": 2016,
                    "transmission": "AUTOMATIC",
                    "engine_hp": 333.0,
                    "driven_wheels": "all wheel drive",
                    "highway_mpg": 26,
                    "msrp": 67350.0,
                }
            ],
            "suggestions": [],
        }
    }
}


def plan_missing(slot: EntityType) -> Plan:
    return Plan(
        steps=(
            PlanStep(
                order=0,
                intent_id="int_1",
                action="ask_for_details",
                department=Department.SALES,
                required_slots=(slot,),
                missing_slots=(slot,),
            ),
        ),
        next_action="ask_for_details",
    )


def conversation() -> ConversationState:
    return ConversationState(
        conversation_id="conv_test",
        intents=IntentQueue(
            intents=(
                Intent(
                    category=IntentCategory.TEST_DRIVE_BOOKING,
                    confidence=0.9,
                    missing_slots=(EntityType.PREFERRED_DATE,),
                ),
            )
        ),
    )


class StubPhraser:
    """A phraser returning whatever the test wants, or raising."""

    name = "stub"

    def __init__(self, payload: object = None, *, raises: Exception | None = None):
        self.payload = payload
        self.raises = raises
        self.last_user_context: str | None = None

    @property
    def model(self) -> str:
        return "stub-model"

    async def phrase(self, *, system: str, user: str) -> LLMResponse:
        self.last_user_context = user
        if self.raises is not None:
            raise self.raises
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return LLMResponse(
            text=text, model=self.model, provider=self.name, usage=TokenUsage()
        )


async def write(writer: ClarificationWriter, *, tool_results=None, language=None):
    return await writer.write(
        plan=plan_missing(EntityType.PREFERRED_DATE),
        language=language,
        conversation=conversation(),
        tool_results=tool_results if tool_results is not None else {},
    )


class TestTemplateFloor:
    async def test_no_phraser_returns_the_policy_question_verbatim(self) -> None:
        result = await write(ClarificationWriter())

        assert result.source == "template"
        assert result.draft.en == "Which day would suit you for the test drive?"
        assert result.awaiting == "preferred_date"

    async def test_a_phraser_that_raises_falls_back_silently(self) -> None:
        writer = ClarificationWriter(StubPhraser(raises=RuntimeError("boom")))
        result = await write(writer, tool_results=CATALOG_RESULTS)

        assert result.source == "template"
        assert result.draft.en == "Which day would suit you for the test drive?"
        assert "RuntimeError" in result.fallback_reason
        assert "boom" in result.fallback_reason

    async def test_a_timeout_is_named_rather_than_left_blank(self) -> None:
        # `str(TimeoutError())` is empty, so the generic branch reported
        # "phrasing_failed: " with nothing after it — for the failure that
        # turns out to be by far the most common on a free-tier key.
        writer = ClarificationWriter(StubPhraser(raises=TimeoutError()))
        result = await write(writer, tool_results=CATALOG_RESULTS)

        assert result.source == "template"
        assert result.fallback_reason == "timed_out"

    @pytest.mark.parametrize(
        "payload,reason",
        [
            ("not json at all", "unparseable_json"),
            ({"en": ""}, "empty_reply"),
            ({"en": "The S5 is a lovely car."}, "not_a_question"),
            ({"en": "Which day suits you? " + "x" * 500}, "too_long"),
        ],
    )
    async def test_unusable_output_is_rejected(self, payload, reason) -> None:
        writer = ClarificationWriter(StubPhraser(payload))
        result = await write(writer)

        assert result.source == "template"
        assert result.fallback_reason.startswith(reason)


class TestFigureDiscipline:
    """The model phrases; it does not source facts."""

    async def test_specs_we_supplied_may_be_quoted(self) -> None:
        writer = ClarificationWriter(
            StubPhraser(
                {
                    "en": (
                        "The 2016 Renzo S5 is in stock — Automatic, 333hp, "
                        "26 hwy mpg, 67350 AED. Which day suits you?"
                    )
                }
            )
        )
        result = await write(writer, tool_results=CATALOG_RESULTS)

        assert result.source == "model"
        assert "67350" in result.draft.en
        assert result.awaiting == "preferred_date"
        assert result.provider == "stub"

    async def test_an_invented_figure_rejects_the_whole_reply(self) -> None:
        # 58900 was never handed to it. One unsourced number is a wrong quote,
        # so the entire rewrite is discarded rather than partially trusted.
        writer = ClarificationWriter(
            StubPhraser({"en": "The S5 is 58900 AED. Which day suits you?"})
        )
        result = await write(writer, tool_results=CATALOG_RESULTS)

        assert result.source == "template"
        assert "58900" not in result.draft.en
        assert result.fallback_reason.startswith("unsourced_figures")

    async def test_no_catalog_result_means_no_figures_at_all(self) -> None:
        # Case 1: the customer never named a vehicle, so nothing was looked
        # up. A price here would be invention regardless of how plausible.
        writer = ClarificationWriter(
            StubPhraser({"en": "The S5 starts at 67350 AED. Which day suits you?"})
        )
        result = await write(writer, tool_results={})

        assert result.source == "template"

    async def test_a_plain_question_needs_no_figures(self) -> None:
        writer = ClarificationWriter(
            StubPhraser({"en": "Happy to get that booked — which day suits you?"})
        )
        result = await write(writer, tool_results={})

        assert result.source == "model"
        assert result.draft.en.endswith("which day suits you?")


class TestBilingual:
    def profile(self) -> LanguageProfile:
        return LanguageProfile(
            primary=Language.ARABIC,
            has_arabic=True,
            is_mixed=True,
            arabic_char_ratio=0.6,
            confidence=0.9,
        )

    async def test_arabic_falls_back_to_the_template_when_omitted(self) -> None:
        language = self.profile()
        assert language.requires_bilingual_reply

        writer = ClarificationWriter(
            StubPhraser({"en": "Which day suits you?", "ar": ""})
        )
        result = await write(writer, language=language)

        assert result.source == "model"
        assert result.draft.ar == "ما هو اليوم المناسب لك لتجربة القيادة؟"

    async def test_monolingual_replies_carry_no_arabic(self) -> None:
        writer = ClarificationWriter(
            StubPhraser({"en": "Which day suits you?", "ar": "أي يوم يناسبك؟"})
        )
        result = await write(writer, language=None)

        assert result.draft.ar is None


class TestPromptContext:
    async def test_the_verified_vehicle_line_reaches_the_model(self) -> None:
        phraser = StubPhraser({"en": "Which day suits you?"})
        await write(ClarificationWriter(phraser), tool_results=CATALOG_RESULTS)

        context = phraser.last_user_context or ""
        assert "2016 Renzo S5" in context
        assert "67350 AED" in context
        assert "Which day would suit you for the test drive?" in context

    async def test_an_empty_catalog_is_stated_as_such(self) -> None:
        phraser = StubPhraser({"en": "Which day suits you?"})
        await write(ClarificationWriter(phraser), tool_results={})

        assert "Mention no vehicle" in (phraser.last_user_context or "")

    async def test_the_slot_being_asked_about_is_not_also_an_other_request(
        self,
    ) -> None:
        # The bug this pins: `preferred_date` appeared both as the thing to
        # ask for *and* in the "other open requests" list, so the model wrote
        # "which day suits you? I'll come back to your other requests,
        # including the test drive booking" — in the same breath.
        phraser = StubPhraser({"en": "Which day suits you?"})
        await write(ClarificationWriter(phraser), tool_results=CATALOG_RESULTS)

        # The only open intent needs exactly the slot being asked for, so
        # there is nothing else outstanding and the section must not appear.
        assert "## Other open requests" not in (phraser.last_user_context or "")

    async def test_intent_labels_are_customer_facing_not_enum_values(self) -> None:
        # "financing_emi" reached the customer as "financing EMI" — internal
        # vocabulary in front of a buyer.
        phraser = StubPhraser({"en": "Which day suits you?"})
        writer = ClarificationWriter(phraser)
        await writer.write(
            plan=plan_missing(EntityType.PREFERRED_DATE),
            language=None,
            conversation=ConversationState(
                conversation_id="conv_labels",
                intents=IntentQueue(
                    intents=(
                        Intent(
                            category=IntentCategory.TEST_DRIVE_BOOKING,
                            confidence=0.9,
                            missing_slots=(EntityType.PREFERRED_DATE,),
                        ),
                        Intent(
                            category=IntentCategory.FINANCING_EMI,
                            confidence=0.9,
                            missing_slots=(EntityType.DOWN_PAYMENT,),
                        ),
                    )
                ),
            ),
            tool_results=CATALOG_RESULTS,
        )

        context = phraser.last_user_context or ""
        others = context.split("## Other open requests")[1]
        assert "financing emi" not in context
        assert "- financing — still need: down payment" in others
        # The test drive is what we are asking about, not an "other" request.
        assert "the test drive" not in others
