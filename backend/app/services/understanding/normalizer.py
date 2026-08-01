"""Text normalisation for Gulf customer messages.

Pure functions, no LLM, no I/O — which means every rule here is unit-testable
and costs nothing to run. That matters: normalisation happens on every inbound
message, and paying a model call for work a regex does correctly would be
indefensible at 100 inquiries a day.

The problems this solves are specific to the market:

* Arabic has multiple orthographic forms of the same letter (أ إ آ ا), and
  customers use them interchangeably. Without unification, BM25 treats
  "الرنزو" and "ألرنزو" as different terms.
* Arabic-Indic digits (٢٠٢٠) must become ASCII before any year or price can
  be parsed.
* "Arabizi" — Arabic written in Latin script with digits standing in for
  letters that have no Latin equivalent (3 for ع, 7 for ح). Common in
  WhatsApp, invisible to a language detector, and it turns "3andi" into
  something no model handles well.
* Tatweel (ـــ) is decorative elongation that carries no meaning but breaks
  exact matching.

Normalisation never discards the original. `raw_text` is retained on the
inquiry so provenance survives: the UI can show that "٢٠٢٠" was read as 2020.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

# ── Character classes ─────────────────────────────────────────────────
ARABIC_BLOCK: Final = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
LATIN_LETTER: Final = re.compile(r"[A-Za-z]")

# Harakat (short vowel marks) and other combining diacritics. Optional in
# written Arabic and almost never used by customers, but they break matching
# when they do appear.
DIACRITICS: Final = re.compile(r"[ً-ْٓ-ٰٕۖ-ۭ]")
TATWEEL: Final = "ـ"

# ── Letter unification ────────────────────────────────────────────────
# Maps orthographic variants onto a single canonical form. This is standard
# Arabic IR preprocessing and materially improves BM25 recall.
LETTER_NORMALISATION: Final[dict[str, str]] = {
    # Alef with any hamza or madda -> bare alef
    "آ": "ا",  # آ
    "أ": "ا",  # أ
    "إ": "ا",  # إ
    "ٱ": "ا",  # ٱ
    # Alef maqsura -> ya
    "ى": "ي",  # ى
    # Ta marbuta -> ha
    "ة": "ه",  # ة
    # Hamza carriers -> bare hamza
    "ؤ": "ء",  # ؤ
    "ئ": "ء",  # ئ
    # Persian/Urdu characters that appear via mobile keyboards
    "ک": "ك",  # ک -> ك
    "ی": "ي",  # ی -> ي
}

# Arabic-Indic and Eastern Arabic-Indic digits -> ASCII.
DIGIT_TRANSLATION: Final = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩" "۰۱۲۳۴۵۶۷۸۹",
    "0123456789" "0123456789",
)

PUNCTUATION_TRANSLATION: Final = str.maketrans(
    {"،": ",", "؛": ";", "؟": "?", "٪": "%", "ـ": "", "”": '"', "“": '"', "’": "'", "‘": "'"}
)

_LETTER_TABLE: Final = str.maketrans(LETTER_NORMALISATION)

# ── Arabizi ───────────────────────────────────────────────────────────
# Digits standing in for Arabic letters. Detection has to be conservative,
# because this market is full of alphanumeric model names — Renzo S5, X3, Q7 —
# and misreading one as transliterated Arabic replies to an English customer
# in Arabic.
#
# Two patterns, both requiring the digit to behave like a *letter*:
#   INFIX   a digit between Latin letters      sa3r, ta2seet, mo7ammed
#   INITIAL a word opening with a digit        3andi, 7abibi
#
# A trailing digit is deliberately excluded, because that is exactly what a
# model name looks like: S5, X3, 2020, 50000.
ARABIZI_INFIX: Final = re.compile(r"[A-Za-z][2345789][A-Za-z]")
ARABIZI_INITIAL: Final = re.compile(r"\b[23579][A-Za-z]{2,}\b")

# Common Arabizi tokens seen in dealership enquiries, mapped to English so the
# rest of the pipeline can reason about them. Transliterating to Arabic script
# would be more faithful but less useful — the retrieval corpus is English.
ARABIZI_LEXICON: Final[dict[str, str]] = {
    "3andi": "i have", "3ndi": "i have", "3aiz": "i want", "3ayez": "i want",
    "3awez": "i want", "3auz": "i want", "bghit": "i want", "abgha": "i want",
    "biddi": "i want", "kam": "how much", "keem": "how much",
    "bkam": "how much", "shoo": "what", "wesh": "what",
    # "fee" and "fi" are genuine Arabizi for "is there", but they are also
    # ordinary English — and "fee" is core finance vocabulary here. The cost
    # of corrupting "processing fee" outweighs the benefit of catching them.
    "mawjood": "available", "mawjoud": "available", "mojood": "available",
    "sayara": "car", "sayarah": "car", "seyara": "car", "3arabiya": "car",
    "taqseet": "instalments", "ta2seet": "instalments", "qist": "instalment",
    "2ist": "instalment", "shahri": "monthly", "shahriya": "monthly",
    "tamweel": "financing", "tamwil": "financing",
    "mo3ayana": "inspection", "tajriba": "test drive", "tajribi": "test drive",
    "sa3r": "price", "se3r": "price", "thaman": "price",
    "jadeed": "new", "jdeed": "new", "qadeem": "old", "2adeem": "old",
    "mashi": "mileage", "kilomitr": "kilometres",
    "mumkin": "possible", "momken": "possible", "mumken": "possible",
    "shukran": "thank you", "min fadlak": "please", "law samaht": "please",
}

# Misspellings frequent enough in dealership traffic to be worth fixing before
# they reach intent classification.
SPELLING_CORRECTIONS: Final[dict[str, str]] = {
    "finence": "finance", "finanace": "finance", "finacing": "financing",
    "fainance": "finance", "instalment": "instalment", "installement": "instalment",
    "emi": "EMI", "tradein": "trade-in", "trade in": "trade-in",
    "tradin": "trade-in", "exchage": "exchange", "exchnage": "exchange",
    "testdrive": "test drive", "test-drive": "test drive", "tesdrive": "test drive",
    "availabe": "available", "avilable": "available", "availble": "available",
    "vehical": "vehicle", "vehcile": "vehicle", "vehicel": "vehicle",
    "sedaan": "sedan", "suvv": "SUV", "downpayment": "down payment",
    "montly": "monthly", "moanthly": "monthly", "pyament": "payment",
    "paymnet": "payment", "intrest": "interest", "warrenty": "warranty",
}

WHITESPACE: Final = re.compile(r"\s+")
REPEATED_PUNCT: Final = re.compile(r"([!?.,])\1{1,}")
REPEATED_CHAR: Final = re.compile(r"([A-Za-zء-ي])\1{2,}")
EMOJI: Final = re.compile(
    "[" "\U0001f300-\U0001faff" "\U00002600-\U000027bf" "\U0001f000-\U0001f2ff" "]+",
    flags=re.UNICODE,
)

# ── PII redaction ─────────────────────────────────────────────────────
# Applied before persistence. UAE mobile numbers appear in a range of formats.
PHONE_PATTERN: Final = re.compile(
    r"(?:\+?971[\s\-]?|0)?5[0-9][\s\-]?[0-9]{3}[\s\-]?[0-9]{4}\b"
)
EMAIL_PATTERN: Final = re.compile(r"\b[\w.\-+]+@[\w\-]+\.[A-Za-z]{2,}\b")
EMIRATES_ID_PATTERN: Final = re.compile(r"\b784[\s\-]?\d{4}[\s\-]?\d{7}[\s\-]?\d\b")


def strip_diacritics(text: str) -> str:
    """Remove harakat and tatweel."""
    return DIACRITICS.sub("", text).replace(TATWEEL, "")


def unify_letters(text: str) -> str:
    """Collapse orthographic variants onto canonical Arabic letters."""
    return text.translate(_LETTER_TABLE)


def normalise_digits(text: str) -> str:
    """Convert Arabic-Indic digits to ASCII so numbers can be parsed."""
    return text.translate(DIGIT_TRANSLATION)


def normalise_punctuation(text: str) -> str:
    return text.translate(PUNCTUATION_TRANSLATION)


def strip_emoji(text: str) -> str:
    return EMOJI.sub(" ", text)


def collapse_repeats(text: str) -> str:
    """Tame elongation and punctuation spam: "hellooooo!!!!" -> "helloo!".

    Two repeats are kept rather than one because English has genuine double
    letters, and collapsing to a single character would corrupt real words.
    """
    text = REPEATED_PUNCT.sub(r"\1", text)
    return REPEATED_CHAR.sub(r"\1\1", text)


def looks_like_arabizi(text: str) -> bool:
    """Whether Latin text is likely transliterated Arabic.

    Two independent signals, either of which suffices: a known Arabizi word,
    or a digit used as a letter. Both are matched on word boundaries — a
    substring scan would fire on "kamera" for "kam", and a bare digit scan
    would fire on every model name in the catalog.
    """
    if not LATIN_LETTER.search(text):
        return False

    words = set(re.findall(r"[a-z0-9]+", text.lower()))
    if words & ARABIZI_LEXICON.keys():
        return True

    return bool(ARABIZI_INFIX.search(text) or ARABIZI_INITIAL.search(text))


def expand_arabizi(text: str) -> str:
    """Replace known Arabizi tokens with their English equivalents.

    Word-boundary matched and applied longest-first, so "3andi" is not
    partially rewritten by a shorter overlapping entry.
    """
    result = text
    for token in sorted(ARABIZI_LEXICON, key=len, reverse=True):
        result = re.sub(
            rf"\b{re.escape(token)}\b",
            ARABIZI_LEXICON[token],
            result,
            flags=re.IGNORECASE,
        )
    return result


def correct_spelling(text: str) -> str:
    result = text
    for wrong, right in sorted(SPELLING_CORRECTIONS.items(), key=lambda kv: -len(kv[0])):
        result = re.sub(rf"\b{re.escape(wrong)}\b", right, result, flags=re.IGNORECASE)
    return result


def redact_pii(text: str) -> str:
    """Replace direct identifiers with typed placeholders.

    Placeholders rather than deletion so the pipeline can still tell that a
    phone number *was* provided — which is exactly what the contact-details
    slot needs to know — without the number itself reaching storage or logs.
    """
    text = EMIRATES_ID_PATTERN.sub("[emirates-id]", text)
    text = EMAIL_PATTERN.sub("[email]", text)
    return PHONE_PATTERN.sub("[phone]", text)


def arabic_char_ratio(text: str) -> float:
    """Share of letter characters that are Arabic.

    Digits, punctuation and whitespace are excluded from the denominator: a
    message that is one Arabic word and a long model number should not read
    as mostly English.
    """
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    arabic = sum(1 for c in letters if ARABIC_BLOCK.match(c))
    return arabic / len(letters)


def normalise(text: str, *, redact: bool = True, expand_transliteration: bool = True) -> str:
    """Full normalisation pipeline.

    Order matters. Unicode composition runs first so that later character
    rules see a predictable encoding; PII redaction runs before Arabizi
    expansion so a phone number cannot be mangled into something that no
    longer matches the phone pattern; whitespace collapses last, once every
    substitution has finished introducing it.
    """
    if not text or not text.strip():
        return ""

    # NFKC folds presentation forms (ﻻ) onto their canonical equivalents.
    result = unicodedata.normalize("NFKC", text)
    result = strip_emoji(result)

    if redact:
        result = redact_pii(result)

    result = strip_diacritics(result)
    result = unify_letters(result)
    result = normalise_digits(result)
    result = normalise_punctuation(result)
    result = collapse_repeats(result)

    if expand_transliteration and looks_like_arabizi(result):
        result = expand_arabizi(result)

    result = correct_spelling(result)
    return WHITESPACE.sub(" ", result).strip()
