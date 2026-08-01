"""Structured-output schemas for the understanding layer.

These are the contract between the model and the pipeline. Every
understanding stage demands one of these back rather than free text, so an
unparseable response fails loudly at the boundary instead of leaking a
malformed string downstream.

Field descriptions are load-bearing: both OpenAI and Anthropic surface them
to the model as part of the schema, so they carry the instruction rather than
the prompt repeating it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import EntityType, IntentCategory, Polarity, Urgency


class DiscoveredIntent(BaseModel):
    """One intent the model believes it found."""

    model_config = ConfigDict(extra="forbid")

    category: IntentCategory = Field(
        description="Which of the supported categories this request falls into."
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "How certain you are. Be honest — a low score routes the message to a "
            "human, which is the correct outcome when the request is genuinely unclear."
        ),
    )
    evidence: str | None = Field(
        default=None,
        description="The words in the message that justify this category.",
    )
    is_primary: bool = Field(
        default=False,
        description="True for the single request the customer most wants answered.",
    )


class IntentDiscoveryResult(BaseModel):
    """Every intent in a message.

    Always a list. A message containing three requests must return three
    entries — collapsing them to one loses work the customer is waiting on.
    """

    model_config = ConfigDict(extra="forbid")

    intents: list[DiscoveredIntent] = Field(
        description=(
            "All distinct requests in the message, most important first. Return "
            "unclear_needs_clarification when the message is too vague to categorise "
            "rather than guessing a category it does not support."
        )
    )


class ExtractedSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: EntityType = Field(description="Which slot this value fills.")
    value: str = Field(description="The canonical value, normalised.")
    raw_value: str = Field(description="Exactly as the customer wrote it.")
    confidence: float = Field(ge=0.0, le=1.0)


class EntityExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entities: list[ExtractedSlot] = Field(
        description=(
            "Facts stated in the message. Distinguish the vehicle being traded in "
            "(old_*) from the one being bought (new_*) — conflating them produces a "
            "wrong quote. Extract only what is stated; never infer."
        )
    )


class SentimentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    polarity: Polarity
    urgency: Urgency
    frustration_score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
