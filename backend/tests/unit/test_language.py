"""Table-driven tests for normalisation and language detection.

These cover the message shapes that actually arrive from Gulf customers:
clean English, Arabic script, code-switching mid-sentence, Arabizi, and
misspelled text. The brief calls this out explicitly, so it is tested
explicitly rather than assumed.
"""

from __future__ import annotations

import pytest

from app.domain.enums import Language
from app.services.understanding.language import detect
from app.services.understanding.normalizer import (
    arabic_char_ratio,
    collapse_repeats,
    correct_spelling,
    expand_arabizi,
    looks_like_arabizi,
    normalise,
    normalise_digits,
    redact_pii,
    strip_diacritics,
    unify_letters,
)


class TestArabicOrthography:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("أحمد", "احمد"),        # alef with hamza above
            ("إبراهيم", "ابراهيم"),   # alef with hamza below
            ("آسيا", "اسيا"),         # alef with madda
            ("سيارة", "سياره"),       # ta marbuta -> ha
            ("على", "علي"),           # alef maqsura -> ya
            ("مسؤول", "مسءول"),       # hamza on waw
        ],
    )
    def test_letter_variants_unify(self, raw: str, expected: str) -> None:
        # Without this, BM25 treats each spelling as a distinct term and
        # recall collapses on Arabic queries.
        assert unify_letters(raw) == expected

    def test_diacritics_are_stripped(self) -> None:
        assert strip_diacritics("مَرْحَبًا") == "مرحبا"

    def test_tatweel_is_removed(self) -> None:
        assert strip_diacritics("سيــــارة") == "سيارة"

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("٢٠٢٠", "2020"), ("١٥٠٠٠٠", "150000"), ("۱۹۹۹", "1999")],
    )
    def test_arabic_indic_digits_become_ascii(self, raw: str, expected: str) -> None:
        # Years and prices are unparseable until this runs.
        assert normalise_digits(raw) == expected


class TestArabizi:
    @pytest.mark.parametrize(
        "text",
        ["3andi Karva 2015", "kam el qist?", "3ayez sayara jadeed", "mumkin tajriba?"],
    )
    def test_transliteration_is_recognised(self, text: str) -> None:
        assert looks_like_arabizi(text)

    @pytest.mark.parametrize(
        "text",
        [
            "I want a Renzo 2020",
            "My budget is 150000 AED",
            "Karva SUV with 50000 km",
            "Call me on 4 pm",
            # Alphanumeric model names are everywhere in this catalog and were
            # the original false positive: a trailing digit is a model number,
            # not a transliterated letter.
            "Is the Renzo S5 available?",
            "Looking at the Karva X3 and the Q7",
            "processing fee and early settlement fee",
        ],
    )
    def test_plain_english_with_numbers_is_not_arabizi(self, text: str) -> None:
        # The failure mode this guards: reading "Renzo S5" as transliterated
        # Arabic and replying to an English customer in Arabic.
        assert not looks_like_arabizi(text)

    def test_finance_vocabulary_is_never_rewritten(self) -> None:
        # "fee" is Arabizi for "is there", and also the single most important
        # noun in the financing corpus. English wins.
        assert "fee" in normalise("what is the early settlement fee?")

    def test_known_tokens_expand_to_english(self) -> None:
        assert "i have" in expand_arabizi("3andi sayara").lower()
        assert "how much" in expand_arabizi("kam el qist").lower()

    def test_expansion_respects_word_boundaries(self) -> None:
        # "kam" must not rewrite the "kam" inside another word.
        assert "how much" not in expand_arabizi("kamera").lower()


class TestPiiRedaction:
    @pytest.mark.parametrize(
        "text",
        ["Call me on +971 50 123 4567", "my number is 0501234567", "reach me: 971521234567"],
    )
    def test_uae_mobile_numbers_are_redacted(self, text: str) -> None:
        assert "[phone]" in redact_pii(text)
        assert "1234567" not in redact_pii(text)

    def test_email_is_redacted(self) -> None:
        assert redact_pii("write to ahmed.k@example.com") == "write to [email]"

    def test_emirates_id_is_redacted(self) -> None:
        assert "[emirates-id]" in redact_pii("ID 784-1990-1234567-1")

    def test_placeholder_preserves_the_fact_a_number_was_given(self) -> None:
        # The contact-details slot needs to know a phone was supplied, without
        # the digits reaching storage or logs.
        assert "[phone]" in normalise("my number is 0501234567")


class TestCleanup:
    def test_repeated_punctuation_collapses(self) -> None:
        assert collapse_repeats("really???!!!") == "really?!"

    def test_elongation_collapses_to_two_characters(self) -> None:
        # Two, not one: English has genuine double letters.
        assert collapse_repeats("helloooooo") == "helloo"

    def test_genuine_double_letters_survive(self) -> None:
        assert collapse_repeats("balloon") == "balloon"

    @pytest.mark.parametrize(
        ("wrong", "right"),
        [
            ("I need finence", "finance"),
            ("tradein my car", "trade-in"),
            ("testdrive please", "test drive"),
            ("is it availabe", "available"),
            ("what vehical", "vehicle"),
        ],
    )
    def test_common_misspellings_are_corrected(self, wrong: str, right: str) -> None:
        assert right in correct_spelling(wrong)

    def test_emoji_are_stripped(self) -> None:
        assert "🚗" not in normalise("I want a Renzo 🚗🔥")


class TestNormalisePipeline:
    def test_empty_input_is_handled(self) -> None:
        assert normalise("") == ""
        assert normalise("   ") == ""

    def test_whitespace_is_collapsed_last(self) -> None:
        assert normalise("I   want\n\na  Renzo") == "I want a Renzo"

    def test_the_mixed_intent_example_survives_normalisation(self) -> None:
        text = normalise(
            "I want to trade in my old Karva SUV and also check financing "
            "for a new Renzo S5 — and can I test drive it Saturday?"
        )
        for token in ("trade-in", "Karva", "Renzo", "S5", "test drive"):
            assert token.lower() in text.lower()

    def test_arabic_message_normalises_without_loss(self) -> None:
        result = normalise("كم القسط الشهري لسيارة رينزو ٢٠٢٠؟")
        assert "2020" in result, "digits must become ASCII"
        assert "رينزو" in result
        assert "?" in result, "Arabic question mark is normalised"

    def test_redaction_can_be_disabled_for_display(self) -> None:
        assert "[phone]" not in normalise("call 0501234567", redact=False)


class TestLanguageDetection:
    def test_plain_english(self) -> None:
        profile = detect("I want to book a test drive for a Renzo S5")
        assert profile.primary is Language.ENGLISH
        assert not profile.has_arabic
        assert not profile.requires_bilingual_reply

    def test_pure_arabic(self) -> None:
        profile = detect("اريد حجز تجربة قيادة لسيارة رينزو")
        assert profile.primary is Language.ARABIC
        assert profile.has_arabic
        assert profile.requires_bilingual_reply
        assert profile.confidence >= 0.75

    def test_code_switching_is_flagged_as_mixed(self) -> None:
        profile = detect("اريد test drive لسيارة Renzo S5 يوم السبت")
        assert profile.is_mixed
        assert profile.has_arabic
        assert profile.requires_bilingual_reply

    def test_a_single_arabic_word_still_triggers_a_bilingual_reply(self) -> None:
        # Replying in English to a customer who wrote Arabic is a worse
        # failure than an unnecessary translation.
        assert detect("Is the Renzo S5 متوفرة?").requires_bilingual_reply

    def test_arabizi_is_treated_as_arabic(self) -> None:
        profile = detect("3andi Karva 2015, kam el qist?")
        assert profile.primary is Language.ARABIC
        assert profile.is_arabizi
        assert profile.requires_bilingual_reply

    def test_arabizi_never_claims_certainty(self) -> None:
        # Heuristic detection must surface its own ambiguity to the router.
        assert detect("3ayez sayara").confidence < 0.8

    def test_empty_input_yields_zero_confidence(self) -> None:
        profile = detect("")
        assert profile.confidence == 0.0
        assert not profile.has_arabic

    def test_numbers_alone_do_not_imply_arabic(self) -> None:
        assert not detect("2020 150000 50000").has_arabic

    @pytest.mark.parametrize(
        ("text", "lower", "upper"),
        [
            ("Renzo S5", 0.0, 0.01),
            ("رينزو", 0.99, 1.0),
            ("Renzo رينزو", 0.4, 0.6),
        ],
    )
    def test_arabic_ratio_ignores_digits_and_punctuation(
        self, text: str, lower: float, upper: float
    ) -> None:
        assert lower <= arabic_char_ratio(text) <= upper


class TestBriefScenarios:
    """The exact messages named in the brief."""

    def test_vague_english_fragment(self) -> None:
        profile = detect(normalise("is this still available?"))
        assert profile.primary is Language.ENGLISH
        assert not profile.requires_bilingual_reply

    def test_vague_arabic_fragment(self) -> None:
        profile = detect(normalise("هل ما زالت متوفرة؟"))
        assert profile.primary is Language.ARABIC
        assert profile.requires_bilingual_reply

    def test_arabic_financing_question(self) -> None:
        text = normalise("كم القسط الشهري لسيارة رينزو 2020?")
        profile = detect(text)
        assert profile.primary is Language.ARABIC
        assert profile.requires_bilingual_reply
        assert "2020" in text
