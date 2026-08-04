"""Grounding validation.

The check exists to catch a figure nobody can source. These tests pin the
other half of that contract — what it must *not* flag — because a validator
that fails clean replies escalates them to a human, and a queue full of
false alarms is how a review queue stops being read.
"""

from __future__ import annotations

from typing import ClassVar

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


class TestFigureNormalisation:
    """A tool-sourced figure must not be condemned by how it was spelled.

    Production: an EMI quote echoing exactly what the finance tool returned —
    10620.0, 42480.0, 801.0, 48060.0 — had every one of those flagged
    unsupported, because the tool numbers were canonicalised to "10620" while
    the draft said "10620.0". The reply was correct and the check was wrong.
    """

    def test_a_trailing_point_zero_still_matches_the_tool(self) -> None:
        report = validate_grounding(
            "Your monthly instalment is 801.0 AED over 60 months.",
            (),
            {"emi": {"monthly_instalment": 801.0, "tenure_months": 60}},
        )
        assert report.passes, [c.text for c in report.unsupported_claims]

    def test_the_reverse_spelling_also_matches(self) -> None:
        # Tool returns a whole number, draft writes a decimal.
        report = validate_grounding(
            "The down payment is 10620 AED.", (), {"emi": {"down_payment": 10620.0}}
        )
        assert report.passes

    def test_thousands_separators_still_match(self) -> None:
        report = validate_grounding(
            "The total payable is 48,060 AED.", (), {"emi": {"total_payable": 48060.0}}
        )
        assert report.passes

    def test_a_genuinely_different_number_still_fails(self) -> None:
        # Normalising spellings must not start accepting wrong values.
        report = validate_grounding(
            "Your monthly instalment is 810 AED.",
            (),
            {"emi": {"monthly_instalment": 801.0}},
        )
        assert not report.passes
        assert report.has_unsupported_numeric_claim

    def test_a_genuine_decimal_is_not_flattened(self) -> None:
        report = validate_grounding(
            "The annual rate is 4.99%.", (), {"emi": {"annual_rate": 4.99}}
        )
        assert report.passes


class TestSelfReferentialHedges:
    """A sentence about the assistant's own reasoning is not a claim.

    Measured against the live service. "What is my 2015 Karva 4Runner worth
    as a trade-in?" asked three times returned faithfulness 0.50, 1.00 and
    1.00 — same tool, same figures, same correctness. The only difference was
    whether the model appended its hedge. An escalation that depends on the
    model's phrasing rather than on anything being wrong is noise, and noise
    is what stops a review queue being read.
    """

    TRADE_IN_DRAFT = (
        "Your 2015 Karva 4Runner is estimated to be worth between 8,000 AED "
        "and 9,500 AED as a trade-in, with a point estimate of 8,500 AED. "
        "This is based on the vehicle details you provided, assuming average "
        "usage for its age. Please note that the final offer is subject to a "
        "physical inspection at our showroom."
    )

    # The model designation carries a digit — "4Runner" cites the figure 4 —
    # so the valuation record has to travel with the vehicle it valued, the
    # same way the catalog test above does. Real tool results return the whole
    # record, which is why the live turn reported no unsupported figure.
    TOOL_RESULTS: ClassVar[dict[str, dict[str, object]]] = {
        "valuation": {
            "brand": "Karva",
            "model": "4Runner",
            "year": 2015,
            "low": 8000.0,
            "high": 9500.0,
            "point": 8500.0,
        }
    }

    def test_the_real_escalated_draft_now_passes(self) -> None:
        # Verbatim from the operator queue, reason `grounding_failed`.
        report = validate_grounding(self.TRADE_IN_DRAFT, (), self.TOOL_RESULTS)
        assert report.passes
        # One scored claim survives: the numeric one, sourced from the tool.
        assert len(report.claims) == 1
        assert report.claims[0].is_numeric

    def test_a_hedge_carrying_a_figure_is_still_checked(self) -> None:
        # The exemption must not become an escape hatch. `_is_boilerplate` is
        # consulted before the numeric branch, so a sentence skipped here
        # skips figure-checking too.
        report = validate_grounding(
            "This is based on the vehicle details you provided and comes to "
            "12,750 AED.",
            (),
            {},
        )
        assert not report.passes
        assert report.has_unsupported_numeric_claim

    def test_an_unsourced_service_price_still_escalates(self) -> None:
        # Also verbatim from the queue, reason `unsupported_financial_claim`.
        # No tool produced this and no document contains it.
        report = validate_grounding(
            "A major service for a Karva costs 2,200 AED. If you have any "
            "other questions or need to schedule a service, feel free to let "
            "me know!",
            (),
            {},
        )
        assert not report.passes
        assert report.has_unsupported_numeric_claim

    def test_a_wrong_fact_beside_a_hedge_is_still_caught(self) -> None:
        # The three-intent chat escalated on two unsupported sentences: the
        # hedge, and Saturday hours the model read off the weekday row. The
        # hedge should stop counting; the wrong hours must not.
        report = validate_grounding(
            "This is based on the details you've provided and assumes average "
            "usage. Our showroom is open on Saturdays from 09:00 to 21:00, so "
            "you can visit us then for the test drive.",
            (),
            {},
        )
        assert not report.passes


class TestPolitenessCannotLaunderAFigure:
    """A number does not stop being a claim because the sentence is polite.

    `_is_boilerplate` runs before the numeric branch, so a sentence it skips
    is never figure-checked. Every marker in the tuple is one a model reaches
    for when it is being careful about a number, which is exactly when the
    number matters most.
    """

    def test_the_same_figure_is_judged_the_same_either_way(self) -> None:
        hedged = validate_grounding("Please note the down payment is 10,620 AED.", (), {})
        plain = validate_grounding("The down payment is 10,620 AED.", (), {})
        assert hedged.verdict is plain.verdict is GroundingVerdict.UNGROUNDED
        assert hedged.has_unsupported_numeric_claim
        assert len(hedged.claims) == len(plain.claims) == 1

    def test_every_courtesy_marker_is_covered(self) -> None:
        # One per phrasing family, so a future edit to BOILERPLATE that drops
        # the guard fails here rather than in production.
        for sentence in (
            "Please note the down payment is 10,620 AED.",
            "Our team can arrange this for 3,500 AED.",
            "Let me know if 2,400 AED per month works for you.",
            "This is indicative: the instalment is 1,850 AED.",
            "Thanks! The total comes to 7,900 AED.",
        ):
            report = validate_grounding(sentence, (), {})
            assert report.has_unsupported_numeric_claim, sentence

    def test_a_tool_sourced_figure_survives_the_guard(self) -> None:
        # The guard must not punish correct replies. A real figure inside a
        # hedge becomes a *supported* claim — it raises faithfulness, it does
        # not lower it.
        report = validate_grounding(
            "Please note the down payment is 10,620 AED.",
            (),
            {"emi": {"down_payment": 10620.0}},
        )
        assert report.passes
        assert len(report.claims) == 1
        assert report.claims[0].is_supported

    def test_courtesy_without_a_figure_is_still_skipped(self) -> None:
        # The original behaviour has to survive: politeness that asserts no
        # number stays exempt, or every sign-off becomes an escalation.
        report = validate_grounding(
            "Please note that the final offer is subject to a physical "
            "inspection at our showroom. Thanks for your patience!",
            (),
            {},
        )
        assert report.claims == ()
        assert report.passes
