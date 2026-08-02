"""Grounding validation.

The check exists to catch a figure nobody can source. These tests pin the
other half of that contract — what it must *not* flag — because a validator
that fails clean replies escalates them to a human, and a queue full of
false alarms is how a review queue stops being read.
"""

from __future__ import annotations

from app.domain.enums import GroundingVerdict
from app.services.execution.grounding import vacuously_grounded, validate_grounding


class TestQuestionsAreNotClaims:
    """Asking for information is the opposite of asserting it."""

    def test_a_greeting_and_a_question_assert_nothing(self) -> None:
        # This exact reply was escalated to a human: scored 0.0 against a
        # corpus of finance documents, because a question was counted as an
        # unsupported claim.
        report = validate_grounding(
            "Good morning! How can I assist you today with your vehicle needs?",
            (),
            {},
        )
        assert report.verdict is GroundingVerdict.GROUNDED
        assert report.claims == ()
        assert report.passes

    def test_a_clarifying_question_passes_with_no_evidence_at_all(self) -> None:
        report = validate_grounding(
            "Which day would suit you for the test drive?", (), {}
        )
        assert report.passes

    def test_an_arabic_question_mark_counts_too(self) -> None:
        report = validate_grounding("ما هو اليوم المناسب لك لتجربة القيادة؟", (), {})
        assert report.passes


class TestAssertionsAreStillChecked:
    """Loosening the question rule must not loosen anything else."""

    def test_an_invented_clock_is_still_unsupported(self) -> None:
        # The model has no clock. Stating one is a factual claim with no
        # source, and it must still fail — the prompt forbids it, and this is
        # the net underneath that.
        report = validate_grounding(
            "Good morning! It's currently 09:00. How can I help?", (), {}
        )
        assert not report.passes
        assert len(report.claims) == 1

    def test_an_unsourced_price_still_condemns_the_draft(self) -> None:
        report = validate_grounding(
            "The Renzo S5 is priced at 67350 AED.", (), {}
        )
        assert report.verdict is GroundingVerdict.UNGROUNDED
        assert report.has_unsupported_numeric_claim

    def test_a_price_from_a_tool_is_grounded(self) -> None:
        # The model designation matters: "S5" reads as the digit 5, so the
        # tool result has to carry the model name as well as the price or the
        # sentence cites a figure the tools never produced. Real catalog
        # lookups return the whole record, which is why this holds in practice.
        report = validate_grounding(
            "The Renzo S5 is priced at 67350 AED.",
            (),
            {"catalog": {"model": "S5", "brand": "Renzo", "msrp": 67350.0}},
        )
        assert report.passes

    def test_a_question_does_not_launder_a_figure_in_the_same_reply(self) -> None:
        # A question is skipped, but the assertion beside it is not — so a
        # draft cannot smuggle a number through by ending on a question.
        report = validate_grounding(
            "The instalment is 2450 AED per month. Shall I book you in?", (), {}
        )
        assert not report.passes


class TestVacuouslyGrounded:
    def test_it_matches_what_an_empty_draft_produces(self) -> None:
        # The helper callers use when they know up front there is nothing to
        # check must not be a different, weaker verdict than the real thing.
        assert vacuously_grounded() == validate_grounding("Hi!", (), {})
