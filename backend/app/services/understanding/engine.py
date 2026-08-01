"""The understanding layer: what did the customer actually say?

This layer makes no decisions. It normalises, detects language, discovers
intents, extracts facts and reads sentiment — then stops. Which department
handles the request, whether it can be answered automatically, and what
happens next are all somebody else's job.

Keeping that boundary sharp is what makes the system auditable: the model's
contribution is visible and bounded, and every consequential choice
downstream is a rule someone can read.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.domain.entities import Intent
from app.domain.enums import ModelTier, Polarity, Urgency
from app.domain.value_objects import ExtractedEntity, LanguageProfile, Sentiment
from app.services.understanding import language as language_detector
from app.services.understanding.normalizer import normalise
from app.services.understanding.schemas import (
    EntityExtractionResult,
    IntentDiscoveryResult,
    SentimentResult,
)

logger = get_logger(__name__)

INTENT_SYSTEM = """\
You classify inbound messages to Alto Motors, a car dealership in Velmora \
selling two brands: Karva (affordable sedans and SUVs) and Renzo (premium and \
performance vehicles).

Categories, and when to use each:
- test_drive_booking: the customer wants to try a specific vehicle.
- financing_emi: monthly payment, instalment, loan, EMI, tenure.
- trade_in_valuation: value or exchange their existing car.
- vehicle_availability_info: "do you have X in stock?"
- pricing_offers: what does X cost? discount? offer?
- service_aftersales: booking a service, warranty claim, spare parts.
- complaint_escalation: dissatisfaction, refund, "get me a manager", angry.
- general_info: showroom hours, location, days open, walk-in rules, \
warranty details in general (not for a specific vehicle). Anything about \
the dealership itself rather than a car.
- small_talk: greetings ("hi", "hello", "salaam"), thanks, goodbyes, \
"you're welcome", trivial acknowledgements. Even one word alone.
- unclear_needs_clarification: the customer clearly wants something about \
a vehicle but has not said which vehicle. e.g. "is this still available?"

Real messages are messy. They mix several requests in one sentence, arrive as \
fragments, and switch between Arabic and English mid-thought. Reason in the \
language the customer wrote in; do not translate first.

Rules:
- Return every distinct request, not just the clearest one. A message asking \
about a trade-in, financing and a test drive contains three intents.
- A single-request message returns exactly one intent.
- "thanks", "hi", "cheers", "goodbye" alone is small_talk. Not unclear.
- "what are your hours" or "where are you located" is general_info. Not unclear.
- Reserve unclear_needs_clarification for messages that reference an \
unnamed vehicle. Guessing a category the message does not support sends \
the customer to the wrong department.
- Set confidence honestly. Low confidence routes to a human, which is what \
should happen when you are unsure."""

ENTITY_SYSTEM = """\
You extract stated facts from inbound messages to Alto Motors.

The critical distinction: a customer trading in one car and buying another \
mentions two vehicles in one sentence. Facts about the car they already own \
use the old_* slots; facts about the car they want use the new_* slots. \
Conflating them produces a wrong valuation and a wrong finance quote.

Brand-and-model splitting is essential — the two are separate slots:
- "Karva SUV" -> new_vehicle_brand=Karva, new_vehicle_body=SUV
- "Renzo S5" -> new_vehicle_brand=Renzo, new_vehicle_model=S5
- "Renzo Discovery" -> new_vehicle_brand=Renzo, new_vehicle_model=Discovery
- "2020 Karva Acadia" -> new_vehicle_year=2020, new_vehicle_brand=Karva, \
new_vehicle_model=Acadia
- "Karva CR-V" -> new_vehicle_brand=Karva, new_vehicle_model=CR-V
Never emit "Renzo Discovery" as a single model. The brand is always its own \
slot.

Extraction rules:
- preferred_date accepts every date form: day names ("Saturday", \
"tomorrow", "next Friday"), formatted dates ("08-08-2026", "8/8/2026", \
"2026-08-08", "Aug 8", "8th August"), and relative phrases ("next week", \
"this weekend"). Extract them all as preferred_date.
- preferred_time accepts "2 pm", "14:00", "14.00", "afternoon", "morning", \
"evening", "afternoon at 4".
- Model names are literal — "S5", "GX 470", "CR-V", "Discovery", "Acadia". \
Do not interpret them.

Extract only what the customer actually stated. Never infer a budget from a \
model, or a year from a description. If it is not in the message, leave it out."""

SENTIMENT_SYSTEM = """\
You assess the tone of inbound messages to Alto Motors.

Flag genuine frustration, not ordinary directness — a customer who writes \
tersely is not angry. High urgency combined with negative polarity routes the \
conversation straight to a person, so reserve that combination for messages \
where automation would clearly make things worse."""


def _wrap_with_context(text: str, previous_awaiting: str | None) -> str:
    """Prepend the previous turn's question, when there was one.

    Otherwise a two-word reply — 'Renzo S5', 'Saturday', 'about 90,000 km' —
    lands with no context and the model has to guess whether that fragment is
    a new intent, an answer to a previous question, or noise. Giving it the
    slot the last turn asked about is a small structural change that fixes a
    disproportionate number of clarification loops.
    """
    if not previous_awaiting:
        return text
    label = previous_awaiting.replace("_", " ")
    return (
        f"[The assistant just asked the customer for their {label}. "
        f"Interpret the message as an answer to that question if it fits.]\n\n"
        f"Customer message: {text}"
    )


class UnderstandingEngine:
    """Runs the understanding stages against an injected model provider."""

    def __init__(self, router: object) -> None:
        # Typed as the ModelRouter protocol shape; kept loose here so the
        # domain-facing service does not import an infrastructure class.
        self._router = router

    # ── Stage 1: normalise ────────────────────────────────────────────
    def normalize(self, raw_text: str) -> str:
        """Deterministic cleanup. No model call, no cost, fully testable."""
        return normalise(raw_text)

    # ── Stage 2: detect language ──────────────────────────────────────
    def detect_language(self, text: str) -> LanguageProfile:
        """Script-ratio detection. Also deterministic and free."""
        return language_detector.detect(text)

    # ── Stage 3: discover intents ─────────────────────────────────────
    async def discover_intents(
        self, text: str, previous_awaiting: str | None = None
    ) -> tuple[tuple[Intent, ...], object]:
        """Find every request in the message.

        Returns raw `Intent` objects carrying only what the model reported —
        category and confidence. Department, priority, required slots and
        dependencies are left unset for the planning layer to assign.

        When ``previous_awaiting`` is set, the message is understood as an
        answer to that clarification — a two-word fragment like "Renzo S5"
        continues the previous intent rather than being classified as unclear.
        """
        user = _wrap_with_context(text, previous_awaiting)
        response = await self._router.complete_structured(  # type: ignore[attr-defined]
            system=INTENT_SYSTEM,
            user=user,
            schema=IntentDiscoveryResult,
            tier=ModelTier.FAST,
        )

        discovered = response.value.intents
        if not discovered:
            logger.warning("no_intents_returned", note="falling back to clarification")

        intents = tuple(
            Intent(
                category=found.category,
                confidence=found.confidence,
                is_primary=found.is_primary,
                evidence=found.evidence,
            )
            for found in discovered
        )

        # Exactly one primary, always. Ambiguity here would make the reply
        # address a request the customer did not lead with.
        if intents and not any(i.is_primary for i in intents):
            strongest = max(intents, key=lambda i: i.confidence)
            intents = tuple(
                i.model_copy(update={"is_primary": i.id == strongest.id}) for i in intents
            )

        return intents, response.usage

    # ── Stage 4: extract entities ─────────────────────────────────────
    async def extract_entities(
        self, text: str, previous_awaiting: str | None = None
    ) -> tuple[tuple[ExtractedEntity, ...], object]:
        user = _wrap_with_context(text, previous_awaiting)
        response = await self._router.complete_structured(  # type: ignore[attr-defined]
            system=ENTITY_SYSTEM,
            user=user,
            schema=EntityExtractionResult,
            tier=ModelTier.FAST,
        )

        entities = tuple(
            ExtractedEntity(
                type=slot.type,
                value=slot.value,
                raw_value=slot.raw_value,
                confidence=slot.confidence,
            )
            for slot in response.value.entities
        )
        return entities, response.usage

    # ── Stage 5: score sentiment ──────────────────────────────────────
    async def score_sentiment(self, text: str) -> tuple[Sentiment, object]:
        try:
            response = await self._router.complete_structured(  # type: ignore[attr-defined]
                system=SENTIMENT_SYSTEM,
                user=text,
                schema=SentimentResult,
                tier=ModelTier.FAST,
            )
        except Exception as exc:
            # Sentiment is an input to risk, not a hard requirement. A failure
            # here should degrade the score, never abort the conversation.
            logger.warning("sentiment_failed", error=str(exc))
            return (
                Sentiment(
                    polarity=Polarity.NEUTRAL,
                    urgency=Urgency.LOW,
                    frustration_score=0.0,
                    confidence=0.0,
                ),
                None,
            )

        result = response.value
        return (
            Sentiment(
                polarity=result.polarity,
                urgency=result.urgency,
                frustration_score=result.frustration_score,
                confidence=result.confidence,
            ),
            response.usage,
        )
