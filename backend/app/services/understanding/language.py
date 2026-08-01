"""Language detection for mixed Arabic-English traffic.

A single language label is the wrong output for this market. A message can be
Arabic script, English, both in one sentence, or Arabic written in Latin
characters — and the response policy needs to distinguish all four.

Detection is a script-ratio measurement first and a statistical detector
second. Script ratio is exact and free; the statistical detector only breaks
ties on pure-Latin text, where it cannot tell English from transliteration
anyway. Running the cheap deterministic check first is both faster and more
reliable than deferring to a library that was never trained on Arabizi.
"""

from __future__ import annotations

from app.domain.enums import Language
from app.domain.value_objects import LanguageProfile
from app.services.understanding.normalizer import (
    LATIN_LETTER,
    arabic_char_ratio,
    looks_like_arabizi,
)

# Above this share of Arabic letters the message is Arabic; below the lower
# bound it is English. Between them it is genuinely mixed.
ARABIC_DOMINANT = 0.60
ENGLISH_DOMINANT = 0.15

# A single Arabic word in an otherwise English message still triggers a
# bilingual reply. The threshold is a floor against stray characters, not a
# judgement about which language "wins".
MIXED_FLOOR = 0.05


def detect(text: str) -> LanguageProfile:
    """Classify a message's language composition.

    Confidence reflects how unambiguous the classification is: a message that
    is 95% Arabic script is a clear call, one sitting at the mixed boundary is
    not. That uncertainty propagates into the `language` confidence signal and
    can push a borderline conversation to a human, which is the correct
    outcome — a reply in the wrong language reads as carelessness.
    """
    if not text or not text.strip():
        return LanguageProfile(
            primary=Language.ENGLISH,
            has_arabic=False,
            is_mixed=False,
            is_arabizi=False,
            arabic_char_ratio=0.0,
            confidence=0.0,
        )

    ratio = arabic_char_ratio(text)
    has_latin = bool(LATIN_LETTER.search(text))
    has_arabic_script = ratio > 0.0
    arabizi = not has_arabic_script and has_latin and looks_like_arabizi(text)

    # Arabizi is Arabic that happens to use Latin characters. Treating it as
    # English would reply in the wrong language to a customer writing Arabic.
    if arabizi:
        return LanguageProfile(
            primary=Language.ARABIC,
            has_arabic=True,
            is_mixed=has_latin,
            is_arabizi=True,
            arabic_char_ratio=ratio,
            # Transliteration detection is heuristic, so it never claims
            # certainty — this is exactly the ambiguity the routing layer
            # should see.
            confidence=0.72,
        )

    if ratio >= ARABIC_DOMINANT:
        primary, is_mixed = Language.ARABIC, has_latin
        # Confidence scales with how far past the threshold the ratio sits.
        confidence = _scale(ratio, ARABIC_DOMINANT, 1.0)
    elif ratio <= ENGLISH_DOMINANT and not has_arabic_script:
        primary, is_mixed = Language.ENGLISH, False
        confidence = 0.95
    else:
        # Genuine code-switching. Whichever script carries more letters is
        # primary, but both are present and the reply must be bilingual.
        primary = Language.ARABIC if ratio >= 0.5 else Language.ENGLISH
        is_mixed = True
        # Deliberately capped: mid-range ratios are the hardest cases, and
        # overstating certainty here is what produces confidently wrong
        # single-language replies.
        confidence = 0.70

    return LanguageProfile(
        primary=primary,
        has_arabic=ratio > MIXED_FLOOR,
        is_mixed=is_mixed,
        is_arabizi=False,
        arabic_char_ratio=ratio,
        confidence=round(confidence, 4),
    )


def _scale(value: float, floor: float, ceiling: float) -> float:
    """Map a value within [floor, ceiling] onto a 0.75-1.0 confidence band.

    The floor is 0.75 rather than 0 because clearing the dominance threshold
    at all is already strong evidence; the remaining range expresses how
    emphatic that evidence is.
    """
    if ceiling <= floor:
        return 1.0
    span = (min(value, ceiling) - floor) / (ceiling - floor)
    return 0.75 + 0.25 * span
