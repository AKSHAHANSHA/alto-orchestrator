"""Writing the one question that unblocks the most work.

Clarification used to be a pure template lookup: correct, instant, free, and
tone-deaf. It knew the customer's vehicle was in stock at a known price and
still replied "Which date works for you?", because the template had nowhere to
put that. This module keeps the template as the floor and lets a small model
phrase it when there is something worth saying alongside the question.

Two properties are load-bearing:

* **The deterministic answer is computed first, every time.** The slot being
  asked about comes from policy, never from the model. If the model path fails,
  times out, or returns something we will not vouch for, the reply is exactly
  what it would have been before this module existed.
* **The model phrases; it does not source facts.** Every figure it may use is
  handed to it pre-rendered from a tool result, and any number in its output
  that we did not supply rejects the whole attempt. That is what keeps a free
  small open-weights model off the critical path of a quoted price.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.logging import get_logger
from app.domain.entities import ConversationState
from app.domain.enums import EntityType, IntentCategory
from app.domain.policies import intent_policy
from app.domain.ports import LLMResponse
from app.domain.value_objects import DraftReply, LanguageProfile, Plan, TokenUsage
from app.services.execution.runtime import describe_vehicle

logger = get_logger(__name__)

FALLBACK_EN = "Could you tell me a little more about what you are looking for?"
FALLBACK_AR = "هل يمكنك إخباري بالمزيد عما تبحث عنه؟"

# Any digit run, normalised so 67,350 and 67350 compare equal.
_DIGITS = re.compile(r"\d[\d,]*(?:\.\d+)?")

# Two sentences of phrasing. Anything longer means the model started answering
# the question instead of asking it.
MAX_REPLY_CHARS = 500

SYSTEM = """\
You write one short clarifying question for Alto Motors, a dealership in \
Velmora selling Karva (affordable sedans and SUVs) and Renzo (premium and \
performance vehicles).

You are given the exact thing that must be asked, and sometimes a verified \
line of vehicle specifications. Your only job is to phrase them together as \
one natural reply.

Rules you must not break:
- Ask for exactly the one thing named under "What you must ask for". Never ask \
for anything else, and never ask two questions.
- Use only the figures written in the context you were given. Never write a \
price, year, horsepower, mileage or date that does not already appear there. \
If no vehicle line is supplied, mention no vehicle and no specification at all.
- If other open requests are listed, you may note in one short clause that you \
will come back to them. Do not attempt to answer them.
- Warm, brief and specific. Two sentences at most. Never write "Thank you for \
reaching out" and never sign off — you are already in a conversation.

Return a single JSON object and nothing else:
{"en": "<the English reply>", "ar": "<Modern Standard Arabic translation, or \
an empty string if Arabic was not requested>"}

Keep every figure and vehicle name identical between the two languages."""


class PhrasingPort(Protocol):
    """A small model that rewrites a templated question as natural prose."""

    name: str

    @property
    def model(self) -> str: ...

    async def phrase(self, *, system: str, user: str) -> LLMResponse: ...


@dataclass(frozen=True)
class Clarification:
    """The question to ask, plus what the span needs to attribute it."""

    draft: DraftReply
    awaiting: str
    source: str
    model: str | None = None
    provider: str | None = None
    usage: TokenUsage = field(default_factory=TokenUsage)
    fallback_reason: str | None = None


class ClarificationWriter:
    """Builds the clarifying reply. Template-only unless a phraser is injected."""

    def __init__(self, phraser: PhrasingPort | None = None) -> None:
        self._phraser = phraser

    @property
    def uses_model(self) -> bool:
        return self._phraser is not None

    async def write(
        self,
        *,
        plan: Plan | None,
        language: LanguageProfile | None,
        conversation: ConversationState,
        tool_results: dict[str, Any],
    ) -> Clarification:
        policy = intent_policy()
        missing = set(plan.all_missing_slots) if plan else set()
        slot = policy.next_question_slot(missing)
        question = policy.question_for(slot) if slot else None

        template_en = question.en if question else FALLBACK_EN
        template_ar = question.ar if question else FALLBACK_AR
        bilingual = bool(language and language.requires_bilingual_reply)
        awaiting = slot.value if slot else "clarification"

        def templated(reason: str | None) -> Clarification:
            return Clarification(
                draft=DraftReply(
                    en=template_en,
                    ar=template_ar if bilingual else None,
                    requires_human_approval=False,
                ),
                awaiting=awaiting,
                source="template",
                fallback_reason=reason,
            )

        if self._phraser is None:
            return templated(None)

        spec_line, availability = _vehicle_context(tool_results)

        try:
            response = await self._phraser.phrase(
                system=SYSTEM,
                user=_build_context(
                    template_en=template_en,
                    spec_line=spec_line,
                    availability=availability,
                    conversation=conversation,
                    asked_slot=slot,
                    bilingual=bilingual,
                ),
            )
        except TimeoutError:
            # Called out separately because `str(TimeoutError())` is empty, so
            # folding it into the branch below produced a span attribute
            # reading "phrasing_failed: " with nothing after the colon — the
            # single most common failure, and the least legible.
            logger.warning("clarification_phrasing_timed_out")
            return templated("timed_out")
        except Exception as exc:
            # The customer is waiting; the template is already correct, so
            # this degrades rather than fails.
            logger.warning("clarification_phrasing_failed", error=str(exc))
            return templated(f"phrasing_failed: {type(exc).__name__}: {exc}")

        permitted = _numbers(
            " ".join(filter(None, (spec_line, availability, template_en)))
        )
        verdict = _verify(response.text, permitted=permitted, bilingual=bilingual)

        if verdict.rejection is not None:
            logger.info(
                "clarification_phrasing_rejected",
                reason=verdict.rejection,
                model=self._phraser.model,
            )
            return Clarification(
                draft=DraftReply(
                    en=template_en,
                    ar=template_ar if bilingual else None,
                    requires_human_approval=False,
                ),
                awaiting=awaiting,
                source="template",
                model=self._phraser.model,
                provider=self._phraser.name,
                usage=response.usage,
                fallback_reason=verdict.rejection,
            )

        return Clarification(
            draft=DraftReply(
                en=verdict.en,
                # A model that skipped the translation still gets the
                # template's Arabic — the customer asked in Arabic and must be
                # answered in it, even if the English half got nicer.
                ar=(verdict.ar or template_ar) if bilingual else None,
                requires_human_approval=False,
            ),
            awaiting=awaiting,
            source="model",
            model=self._phraser.model,
            provider=self._phraser.name,
            usage=response.usage,
        )


# ──────────────────────────────────────────────────────────────────────
# Verification
# ──────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class _Verdict:
    en: str = ""
    ar: str | None = None
    rejection: str | None = None


def _verify(raw: str, *, permitted: set[str], bilingual: bool) -> _Verdict:
    """Accept the model's phrasing only if we can vouch for all of it.

    The checks are cheap and the fallback is free, so this is deliberately
    unforgiving — a rejected rewrite costs nothing but the template we already
    had, while an accepted bad one is a wrong price in front of a customer.
    """
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return _Verdict(rejection="unparseable_json")

    if not isinstance(payload, dict):
        return _Verdict(rejection="not_an_object")

    en = str(payload.get("en") or "").strip()
    ar = str(payload.get("ar") or "").strip() or None

    if not en:
        return _Verdict(rejection="empty_reply")
    if len(en) > MAX_REPLY_CHARS:
        return _Verdict(rejection="too_long")
    if "?" not in en and "؟" not in en:
        # It was asked to ask a question. Anything else means it answered.
        return _Verdict(rejection="not_a_question")

    invented = _numbers(en) - permitted
    if bilingual and ar:
        invented |= _numbers(ar) - permitted
    if invented:
        return _Verdict(rejection=f"unsourced_figures: {sorted(invented)}")

    return _Verdict(en=en, ar=ar)


def _numbers(text: str) -> set[str]:
    return {
        match.group(0).replace(",", "").rstrip(".")
        for match in _DIGITS.finditer(text)
    }


# ──────────────────────────────────────────────────────────────────────
# Context
# ──────────────────────────────────────────────────────────────────────
def _vehicle_context(tool_results: dict[str, Any]) -> tuple[str | None, str | None]:
    """The one verified vehicle line the question may mention, if there is one.

    Prefers the structured Postgres lookup, which can say honestly that we do
    not stock something. Falls back to the in-memory catalog filter, which is
    an exact brand/model match rather than a semantic neighbour and so is still
    safe to quote.
    """
    catalog = tool_results.get("catalog")
    if isinstance(catalog, dict):
        new_vehicle = catalog.get("new_vehicle")
        if isinstance(new_vehicle, dict):
            matches = new_vehicle.get("matches") or []
            explanation = new_vehicle.get("explanation") or new_vehicle.get("verdict")
            if matches and isinstance(matches[0], dict):
                return describe_vehicle(matches[0]), _text_or_none(explanation)
            return None, _text_or_none(explanation)

    similar = tool_results.get("catalog_similar")
    if isinstance(similar, list) and similar and isinstance(similar[0], dict):
        return describe_vehicle(similar[0]), None

    return None, None


def _text_or_none(value: Any) -> str | None:
    return str(value) if value else None


_INTENT_LABELS: dict[IntentCategory, str] = {
    IntentCategory.TEST_DRIVE_BOOKING: "the test drive",
    IntentCategory.FINANCING_EMI: "financing",
    IntentCategory.TRADE_IN_VALUATION: "the trade-in",
    IntentCategory.VEHICLE_AVAILABILITY_INFO: "availability",
    IntentCategory.PRICING_OFFERS: "pricing",
    IntentCategory.SERVICE_AFTERSALES: "service",
    IntentCategory.COMPLAINT_ESCALATION: "the complaint",
    IntentCategory.GENERAL_INFO: "the general enquiry",
}


def _label(category: IntentCategory) -> str:
    """A phrase a customer would recognise.

    The raw enum value leaks otherwise. A smaller model handed
    "financing_emi" writes "financing EMI" straight into the reply, which is
    internal vocabulary appearing in front of a customer.
    """
    return _INTENT_LABELS.get(category, category.value.replace("_", " "))


def _build_context(
    *,
    template_en: str,
    spec_line: str | None,
    availability: str | None,
    conversation: ConversationState,
    asked_slot: EntityType | None,
    bilingual: bool,
) -> str:
    lines = ["## What you must ask for", template_en]

    if spec_line:
        lines += [
            "\n## Verified vehicle — the only specifications you may state",
            spec_line,
        ]
    else:
        lines.append(
            "\n## Verified vehicle\nNone. Mention no vehicle, price or specification."
        )

    if availability:
        lines += ["\n## Availability", availability]

    # Everything still outstanding *other than* the thing being asked for
    # right now. Leaving the asked slot in this list made the model describe
    # the test drive as one of the customer's "other requests" in the very
    # sentence asking them to pick a test-drive date.
    others: list[str] = []
    for intent in conversation.intents.ordered():
        remaining = [s for s in intent.missing_slots if s != asked_slot]
        if not remaining:
            continue
        needs = ", ".join(s.value.replace("_", " ") for s in remaining)
        others.append(f"- {_label(intent.category)} — still need: {needs}")

    if others:
        lines += ["\n## Other open requests you may acknowledge briefly", *others]

    if conversation.transcript:
        lines.append("\n## Conversation so far")
        for turn in conversation.transcript[-6:]:
            who = "Customer" if turn.role == "customer" else "You"
            lines.append(f"{who}: {turn.text}")

    lines.append(
        "\n## Arabic translation requested\n" + ("yes" if bilingual else "no")
    )
    return "\n".join(lines)
