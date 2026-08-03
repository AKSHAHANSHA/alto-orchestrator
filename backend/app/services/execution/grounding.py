"""Grounding validation.

Checks that a drafted reply is supported by evidence that was actually
retrieved, and treats numeric claims far more seriously than qualitative ones.
A vague adjective nobody can source is a style problem; a profit rate nobody
can source is a regulatory one.

Deliberately deterministic. Asking a model whether its own answer was
faithful is circular, and the failure mode — a confident model confidently
validating its own hallucination — is exactly the one this exists to catch.
"""

from __future__ import annotations

import re
from typing import Any

from app.domain.enums import GroundingVerdict
from app.domain.value_objects import Claim, GroundingReport, RetrievedChunk

# Sentences carrying figures customers act on: money, percentages, tenures.
NUMERIC_PATTERN = re.compile(
    r"\b\d[\d,]*(?:\.\d+)?\s*(?:%|percent|aed|dirham|month|months|year|years|km)?\b",
    re.IGNORECASE,
)
MONEY_PATTERN = re.compile(r"\b\d[\d,]{2,}(?:\.\d+)?\b|\bAED\s*\d|\b\d+\s*%")

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")

# Language that makes no factual assertion and therefore cannot be unsupported.
BOILERPLATE = (
    "thank you", "thanks", "happy to help", "get in touch", "reach out",
    "our team", "let me know", "best regards", "kind regards", "hello", "hi ",
    "subject to", "please note", "indicative", "not a finance offer",
)


def _is_boilerplate(sentence: str) -> bool:
    lowered = sentence.lower().strip()
    return len(lowered) < 15 or any(marker in lowered for marker in BOILERPLATE)


def _is_question(sentence: str) -> bool:
    """Questions assert nothing, so there is nothing in them to support.

    Counting them as claims is how "How can I assist you today with your
    vehicle needs?" became an unsupported claim against a corpus of finance
    documents, dragging a greeting to zero faithfulness and escalating it to
    a human. Asking for information is the opposite of asserting it.
    """
    return sentence.rstrip().endswith(("?", "؟"))


def _canonical(raw: str) -> str:
    """One spelling per value, so equal numbers compare equal.

    The comparison is textual, which meant `10620.0` in a draft did not match
    `10620` from a tool and a correct, tool-sourced instalment was condemned
    as invented. Seen in production: five figures from the EMI and trade-in
    tools all flagged unsupported in one reply, escalating a conversation
    scoring 92 for quoting exactly what it was given.
    """
    value = raw.replace(",", "")
    if "." in value:
        value = value.rstrip("0").rstrip(".")
    return value or "0"


def _numbers_in(text: str) -> set[str]:
    """Bare digit sequences, normalised so 150,000, 150000 and 150000.0 agree."""
    return {
        _canonical(match.group(0))
        for match in re.finditer(r"\d[\d,]*(?:\.\d+)?", text)
    }


def _tool_numbers(tool_results: dict[str, Any]) -> set[str]:
    """Every figure a deterministic tool produced.

    These are authoritative: they came from arithmetic, not from a model, so
    a draft quoting them is grounded by construction.
    """
    numbers: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list | tuple):
            for item in value:
                walk(item)
        elif isinstance(value, int | float) and not isinstance(value, bool):
            numbers.add(_canonical(str(value)))
            numbers.add(_canonical(f"{value:.2f}"))
        elif isinstance(value, str):
            numbers.update(_numbers_in(value))

    walk(tool_results)
    return numbers


def vacuously_grounded() -> GroundingReport:
    """A pass for a reply that asserts nothing.

    Not a bypass: the same verdict `validate_grounding` already returns when a
    draft decomposes to zero claims. Callers use it when they know up front
    that a turn carries no factual content, rather than paying for a check
    whose only possible finding would be wrong.
    """
    return GroundingReport(
        verdict=GroundingVerdict.GROUNDED, claims=(), faithfulness_score=1.0
    )


def validate_grounding(
    draft: str,
    chunks: tuple[RetrievedChunk, ...],
    tool_results: dict[str, Any] | None = None,
) -> GroundingReport:
    """Decompose a draft into claims and check each against the evidence.

    A claim is supported when its content overlaps a retrieved chunk, or when
    every figure it cites came from a deterministic tool.
    """
    tool_results = tool_results or {}
    evidence = " ".join(chunk.text.lower() for chunk in chunks)
    evidence_numbers = _numbers_in(evidence)
    tool_numbers = _tool_numbers(tool_results)
    authoritative = evidence_numbers | tool_numbers

    sentences = [s.strip() for s in SENTENCE_SPLIT.split(draft) if s.strip()]
    claims: list[Claim] = []

    for sentence in sentences:
        if _is_boilerplate(sentence) or _is_question(sentence):
            continue

        is_numeric = bool(MONEY_PATTERN.search(sentence))
        cited = _numbers_in(sentence)

        supporting: list[str] = []

        if is_numeric and cited:
            # Every figure must trace to a tool result or a retrieved chunk.
            # Partial support is not support: one invented number in an
            # otherwise correct sentence is still a wrong quote.
            if cited <= authoritative:
                supporting = [
                    chunk.chunk_id
                    for chunk in chunks
                    if cited & _numbers_in(chunk.text)
                ] or ["tool:deterministic"]
        else:
            # Qualitative claims are supported by lexical overlap with the
            # retrieved text. Crude, but it reliably catches a draft that
            # wandered off the corpus entirely.
            for chunk in chunks:
                if _overlaps(sentence, chunk.text):
                    supporting.append(chunk.chunk_id)

        claims.append(
            Claim(
                text=sentence,
                supporting_chunk_ids=tuple(supporting),
                is_numeric=is_numeric,
            )
        )

    return _report(claims)


def _overlaps(sentence: str, chunk_text: str, threshold: float = 0.25) -> bool:
    """Content-word overlap between a claim and a chunk."""
    stop = {
        "the", "a", "an", "is", "are", "was", "were", "to", "of", "for", "and",
        "or", "in", "on", "at", "with", "you", "your", "we", "our", "can", "will",
        "be", "this", "that", "it", "as", "by", "from", "if", "not",
    }
    words = {w for w in re.findall(r"[a-z]{3,}", sentence.lower()) if w not in stop}
    if not words:
        return False
    chunk_words = set(re.findall(r"[a-z]{3,}", chunk_text.lower()))
    return len(words & chunk_words) / len(words) >= threshold


def _report(claims: list[Claim]) -> GroundingReport:
    if not claims:
        # Nothing factual was asserted — a pure acknowledgement. Grounded by
        # vacuity, and correctly so: there is nothing to be wrong about.
        return GroundingReport(
            verdict=GroundingVerdict.GROUNDED, claims=(), faithfulness_score=1.0
        )

    supported = [c for c in claims if c.is_supported]
    faithfulness = len(supported) / len(claims)
    has_bad_number = any(c.is_numeric and not c.is_supported for c in claims)

    if has_bad_number:
        # One unsupported figure condemns the whole draft. This is the single
        # most important rule in the module: an invented profit rate reaching
        # a customer is a commercial and regulatory problem.
        verdict = GroundingVerdict.UNGROUNDED
    elif faithfulness >= 0.8:
        verdict = GroundingVerdict.GROUNDED
    elif faithfulness >= 0.5:
        verdict = GroundingVerdict.PARTIALLY_GROUNDED
    else:
        verdict = GroundingVerdict.UNGROUNDED

    return GroundingReport(
        verdict=verdict,
        claims=tuple(claims),
        faithfulness_score=round(faithfulness, 4),
    )
