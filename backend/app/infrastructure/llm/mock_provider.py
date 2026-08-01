"""Deterministic mock language model.

This is not a stub. It is a real implementation of the `LLMProvider` port that
returns plausible, schema-valid output derived from the input by rule — which
makes it three useful things at once:

* CI runs the full pipeline with no API key, no network and no spend.
* Tests get identical output for identical input, so a failing assertion means
  the pipeline changed rather than the weather.
* The platform demos end to end at zero cost.

Rule-based understanding is genuinely weaker than a real model on messy
Arabizi, and that is fine: it is the fallback, not the product. What matters
is that every downstream stage — planning, routing, grounding, escalation —
behaves identically regardless of which provider produced the understanding.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import AsyncIterator
from typing import Any, TypeVar

from pydantic import BaseModel

from app.core.errors import StructuredOutputError
from app.domain.enums import ModelTier
from app.domain.ports import LLMResponse, StructuredResponse
from app.domain.value_objects import TokenUsage

SchemaT = TypeVar("SchemaT", bound=BaseModel)

# Keyword evidence for rule-based intent discovery. Deliberately bilingual:
# the mock has to exercise the Arabic path, not just the English one.
INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "test_drive_booking": (
        "test drive", "testdrive", "drive it", "try the car", "book a drive",
        "تجربة قيادة", "تجربه قياده", "اجرب", "قيادة تجريبية",
    ),
    "financing_emi": (
        "financ", "emi", "instal", "instal", "monthly payment", "loan", "down payment",
        "interest", "profit rate", "tenure",
        "تمويل", "قسط", "اقساط", "أقساط", "شهري", "قرض", "دفعة",
    ),
    "trade_in_valuation": (
        "trade in", "trade-in", "tradein", "exchange my", "part exchange",
        "my old car", "sell my", "valuation",
        "استبدال", "تبديل", "سيارتي القديمة", "تقييم",
    ),
    "vehicle_availability_info": (
        "available", "in stock", "still have", "do you have",
        "متوفر", "متوفرة", "موجود", "موجودة",
    ),
    "pricing_offers": (
        "price", "cost", "how much", "offer", "discount",
        "سعر", "كم سعر", "تخفيض", "عرض",
    ),
    "service_aftersales": (
        "service", "repair", "maintenance", "warranty", "spare part",
        "صيانة", "اصلاح", "ضمان", "قطع غيار",
    ),
    "complaint_escalation": (
        "complaint", "unacceptable", "terrible", "angry", "manager", "refund",
        "disappointed", "worst",
        "شكوى", "سيء", "غاضب", "مدير", "استرجاع",
    ),
    "general_info": (
        "hours", "open", "opening", "closed", "location", "address", "where are you",
        "showroom hours", "when are you",
        "ساعات", "العنوان", "الموقع", "اين",
    ),
    "small_talk": (
        "thanks", "thank you", "thx", "cheers", "hi", "hello", "hey",
        "goodbye", "bye", "you're welcome", "your welcome",
        "شكرا", "مرحبا", "سلام", "مع السلامة", "أهلا",
    ),
}

NEGATIVE_MARKERS = (
    "unacceptable", "terrible", "angry", "disappointed", "worst", "awful",
    "ridiculous", "complaint", "refund", "waste",
    "سيء", "غاضب", "شكوى", "مرفوض",
)
URGENT_MARKERS = (
    "urgent", "asap", "immediately", "today", "right now", "still waiting",
    "عاجل", "فورا", "اليوم", "الان",
)

BRANDS = ("karva", "renzo")


class MockProvider:
    """Rule-based `LLMProvider`."""

    name = "mock"

    def __init__(
        self, *, fast_model: str = "mock-fast", premium_model: str = "mock-premium"
    ) -> None:
        self._models = {ModelTier.FAST: fast_model, ModelTier.PREMIUM: premium_model}

    def model_for(self, tier: ModelTier) -> str:
        return self._models[tier]

    # ── Token accounting ──────────────────────────────────────────────
    def _usage(self, prompt: str, completion: str) -> TokenUsage:
        """Approximate tokens at ~4 characters each.

        Reported as zero cost, which is true and keeps the mock from polluting
        the cost dashboard with fictional spend.
        """
        return TokenUsage(
            prompt_tokens=max(1, len(prompt) // 4),
            completion_tokens=max(1, len(completion) // 4),
            cost_usd=0.0,
        )

    # ── Free-text completion ──────────────────────────────────────────
    async def complete(
        self,
        *,
        system: str,
        user: str,
        tier: ModelTier,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        text = self._draft_reply(user)
        return LLMResponse(
            text=text,
            model=self.model_for(tier),
            provider=self.name,
            usage=self._usage(system + user, text),
        )

    async def stream(
        self,
        *,
        system: str,
        user: str,
        tier: ModelTier,
        temperature: float = 0.0,
    ) -> AsyncIterator[str]:
        for word in self._draft_reply(user).split(" "):
            yield word + " "

    # ── Structured output ─────────────────────────────────────────────
    async def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[SchemaT],
        tier: ModelTier,
        temperature: float = 0.0,
    ) -> StructuredResponse[SchemaT]:
        """Build a schema-valid instance by rule.

        Dispatch is on the schema's name so the mock stays decoupled from the
        services that call it — a new understanding stage needs a branch here,
        not a change to this method's contract.
        """
        payload = self._payload_for(schema.__name__, user)
        try:
            value = schema.model_validate(payload)
        except Exception as exc:
            raise StructuredOutputError(
                f"The mock provider has no rule producing valid {schema.__name__}.",
                schema=schema.__name__,
            ) from exc

        return StructuredResponse[schema](  # type: ignore[valid-type]
            value=value,
            model=self.model_for(tier),
            provider=self.name,
            usage=self._usage(system + user, str(payload)),
        )

    # ── Rules ─────────────────────────────────────────────────────────
    def _payload_for(self, schema_name: str, text: str) -> dict[str, Any]:
        match schema_name:
            case "IntentDiscoveryResult":
                return {"intents": self._discover_intents(text)}
            case "EntityExtractionResult":
                return {"entities": self._extract_entities(text)}
            case "SentimentResult":
                return self._score_sentiment(text)
            case _:
                return {}

    def _discover_intents(self, text: str) -> list[dict[str, Any]]:
        """Keyword-evidence intent discovery.

        Always returns a list, never a single label. A message matching three
        categories yields three intents, which is what exercises the queue.
        """
        lowered = text.lower()
        found: list[dict[str, Any]] = []

        for category, keywords in INTENT_KEYWORDS.items():
            hits = [k for k in keywords if k in lowered]
            if not hits:
                continue
            # More independent keyword hits means firmer evidence, capped so
            # the mock never claims certainty a rule cannot justify.
            confidence = min(0.94, 0.72 + 0.06 * len(hits))
            found.append(
                {"category": category, "confidence": round(confidence, 2),
                 "evidence": hits[0]}
            )

        if not found:
            # Nothing matched. That is a real answer — "is this still
            # available?" is genuinely unclear — and must not be forced into
            # a category the message does not support.
            return [
                {
                    "category": "unclear_needs_clarification",
                    "confidence": 0.55,
                    "evidence": "no recognisable intent keywords",
                }
            ]

        found.sort(key=lambda i: -float(i["confidence"]))
        found[0]["is_primary"] = True
        return found

    def _extract_entities(self, text: str) -> list[dict[str, Any]]:
        lowered = text.lower()
        entities: list[dict[str, Any]] = []

        def add(entity_type: str, value: str, raw: str, confidence: float) -> None:
            entities.append(
                {"type": entity_type, "value": value, "raw_value": raw,
                 "confidence": confidence}
            )

        # Brands, split by whether the sentence frames them as old or new.
        # "trade in my old Karva ... financing for a new Renzo" is the exact
        # case a naive extractor gets wrong.
        for brand in BRANDS:
            if brand not in lowered:
                continue
            position = lowered.index(brand)
            context = lowered[max(0, position - 40) : position]
            is_old = any(w in context for w in ("old", "my ", "current", "trade", "قديم", "سيارتي"))
            prefix = "old_vehicle" if is_old else "new_vehicle"
            add(f"{prefix}_brand", brand.capitalize(), brand, 0.88)

            # A model name that immediately follows the brand token — either an
            # alphanumeric designation (S5, X3, Q7), a hyphenated identifier
            # (CR-V, X-Trail), a numeric line (300, 3, 6), or a proper-noun
            # word (Discovery, Acadia). This is what the previous "letter +
            # digits" pattern missed, and why answers like "Karva CR-V" or
            # "Karva Discovery" left the entity signal at zero.
            after = text[position + len(brand):]
            model_match = re.match(
                r"\s*([A-Za-z][A-Za-z0-9\-]{1,15}|\d{1,4})",
                after,
            )
            if model_match:
                raw_model = model_match.group(1)
                # Filter out follow-on stop-words that look like model names.
                if raw_model.lower() not in {
                    "and", "or", "with", "for", "the", "a", "an", "is", "was",
                    "sedan", "suv", "coupe", "car", "vehicle",
                }:
                    add(
                        f"{prefix}_model",
                        raw_model.upper() if len(raw_model) <= 3 else raw_model.title(),
                        raw_model,
                        0.80,
                    )

        # Model designations mentioned without a brand token nearby: a letter
        # plus digits (S5, X3) still triggers the fallback, so single-word
        # follow-ups like "S5" after a brand-first turn still catch.
        for match in re.finditer(r"\b([A-Z]\d{1,2})\b", text):
            add("new_vehicle_model", match.group(1), match.group(1), 0.82)

        for body in ("sedan", "suv", "coupe", "convertible", "wagon", "hatchback"):
            if body in lowered:
                add("new_vehicle_body", body.upper() if body == "suv" else body.capitalize(),
                    body, 0.80)

        # Years, bounded to plausible vehicle years so a price is not read as
        # a model year.
        for match in re.finditer(r"\b(19[89]\d|20[0-4]\d)\b", text):
            add("new_vehicle_year", match.group(1), match.group(1), 0.85)

        # Mileage.
        mileage = re.search(r"\b(\d[\d,]{2,})\s*(km|kilomet|كم)", lowered)
        if mileage:
            add("old_vehicle_mileage", mileage.group(1).replace(",", ""), mileage.group(0), 0.86)

        # Weekday mentions for test-drive scheduling.
        for day in ("monday", "tuesday", "wednesday", "thursday", "friday",
                    "saturday", "sunday", "tomorrow", "السبت", "الاحد", "غدا"):
            if day in lowered:
                add("preferred_date", day.capitalize(), day, 0.79)
                break

        # Amounts, distinguished from years by magnitude.
        amount = re.search(r"\b(\d{5,7})\b", text.replace(",", ""))
        if amount and not 1980 <= int(amount.group(1)) <= 2049:
            add("budget", amount.group(1), amount.group(0), 0.70)

        return entities

    def _score_sentiment(self, text: str) -> dict[str, Any]:
        lowered = text.lower()
        negative = sum(1 for marker in NEGATIVE_MARKERS if marker in lowered)
        urgent = sum(1 for marker in URGENT_MARKERS if marker in lowered)

        if negative >= 1:
            polarity = "negative"
            frustration = min(1.0, 0.5 + 0.2 * negative)
        elif any(w in lowered for w in ("thank", "great", "perfect", "شكرا", "ممتاز")):
            polarity, frustration = "positive", 0.0
        else:
            polarity, frustration = "neutral", 0.1

        urgency = "high" if urgent or negative >= 2 else "medium" if negative else "low"

        return {
            "polarity": polarity,
            "urgency": urgency,
            "frustration_score": round(frustration, 2),
            "confidence": 0.75,
        }

    def _draft_reply(self, text: str) -> str:
        """A deterministic but non-degenerate reply.

        Seeded from the input hash so the same message always produces the
        same wording, which keeps snapshot tests stable.
        """
        seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
        openings = (
            "Thank you for getting in touch with Alto Motors.",
            "Thanks for reaching out to Alto Motors.",
            "Happy to help with that.",
        )
        return (
            f"{openings[seed % len(openings)]} A member of our team will follow up "
            f"shortly with the details you asked about."
        )
