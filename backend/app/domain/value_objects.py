"""Immutable values with no identity.

Two ``LanguageProfile`` instances holding the same data are the same profile;
that is what distinguishes these from entities in ``entities.py``, which have
an ``id`` and a lifecycle.

Everything here is frozen. Pipeline stages produce new values rather than
mutating shared ones, which keeps a graph node's effect on state legible and
makes any state snapshot safe to persist as an audit record.
"""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import (
    ConfidenceSignal,
    Department,
    EntityType,
    GroundingVerdict,
    IntentCategory,
    Language,
    ModelTier,
    Polarity,
    RoutingTier,
    Urgency,
)


class Frozen(BaseModel):
    """Base for every value object: immutable and strict about unknown keys."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# ──────────────────────────────────────────────────────────────────────
# Understanding layer
# ──────────────────────────────────────────────────────────────────────
class LanguageProfile(Frozen):
    """What language a message is in, and how sure we are.

    Gulf customers routinely code-switch mid-sentence and write Arabic in
    Latin characters ("Arabizi"), so a single language label loses
    information the response policy needs.
    """

    primary: Language
    has_arabic: bool
    is_mixed: bool
    is_arabizi: bool = False
    arabic_char_ratio: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)

    @property
    def requires_bilingual_reply(self) -> bool:
        """Any Arabic anywhere means the reply carries both languages.

        Deliberately generous: replying in English to a customer who wrote
        one Arabic word is a worse failure than sending an unnecessary
        Arabic translation.
        """
        return self.has_arabic


class Sentiment(Frozen):
    """Emotional read on the message.

    Feeds the ``risk`` confidence signal, and an angry customer with an
    urgent problem is escalated regardless of how confident everything else
    is — that combination is exactly where automation destroys goodwill.
    """

    polarity: Polarity
    urgency: Urgency
    frustration_score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)

    @property
    def demands_human(self) -> bool:
        return self.polarity is Polarity.NEGATIVE and self.urgency is Urgency.HIGH


class ExtractedEntity(Frozen):
    """One filled slot.

    ``raw_value`` keeps what the customer actually wrote and ``value`` holds
    the canonical form. Both are retained so the UI can show provenance:
    "we read '٢٠٢٠' as 2020".
    """

    type: EntityType
    value: str
    raw_value: str
    confidence: float = Field(ge=0.0, le=1.0)
    source_span: tuple[int, int] | None = None


# ──────────────────────────────────────────────────────────────────────
# Decision layer
# ──────────────────────────────────────────────────────────────────────
class ConfidenceVector(Frozen):
    """Six independent signals plus the weighted score derived from them.

    The weights live in ``domain/policies/confidence.yaml``, not here — they
    are a business rule that gets tuned, and burying them in code would make
    every adjustment a deployment.
    """

    language: float = Field(ge=0.0, le=1.0)
    intent: float = Field(ge=0.0, le=1.0)
    entity: float = Field(ge=0.0, le=1.0)
    retrieval: float = Field(ge=0.0, le=1.0)
    risk: float = Field(ge=0.0, le=1.0)
    policy: float = Field(ge=0.0, le=1.0)

    decision_score: float = Field(ge=0.0, le=100.0)

    def signal(self, which: ConfidenceSignal) -> float:
        return float(getattr(self, which.value))

    @property
    def weakest_signal(self) -> ConfidenceSignal:
        """The signal that dragged the score down.

        Surfaced verbatim in the routing rationale so a reviewer sees *why*
        something escalated without reading the arithmetic.
        """
        return min(ConfidenceSignal, key=self.signal)

    def as_dict(self) -> dict[str, float]:
        return {s.value: self.signal(s) for s in ConfidenceSignal}


class RoutingDecision(Frozen):
    """The decision layer's output: who handles this, and with what model."""

    tier: RoutingTier
    department: Department | None
    model_tier: ModelTier | None
    rule_id: str
    rationale: str
    confidence: ConfidenceVector
    overrides_applied: tuple[str, ...] = ()

    @property
    def requires_human(self) -> bool:
        return self.tier is RoutingTier.HUMAN


# ──────────────────────────────────────────────────────────────────────
# Planning layer
# ──────────────────────────────────────────────────────────────────────
class PlanStep(Frozen):
    """One unit of work, derived from one intent.

    Produced by a rule engine rather than a prompt, so the same queue always
    yields the same steps.
    """

    order: int = Field(ge=0)
    intent_id: str
    action: str
    department: Department
    required_slots: tuple[EntityType, ...] = ()
    missing_slots: tuple[EntityType, ...] = ()
    blocked_by: tuple[str, ...] = ()

    @property
    def is_actionable(self) -> bool:
        return not self.missing_slots and not self.blocked_by


class Plan(Frozen):
    """An ordered set of steps plus the single next thing to do."""

    steps: tuple[PlanStep, ...]
    next_action: str | None = None

    @property
    def actionable_steps(self) -> tuple[PlanStep, ...]:
        return tuple(s for s in self.steps if s.is_actionable)

    @property
    def all_missing_slots(self) -> tuple[EntityType, ...]:
        """Every unfilled slot across the plan, de-duplicated, order preserved.

        Order matters: clarification asks for the highest-priority missing
        slot first, one question per turn.
        """
        seen: dict[EntityType, None] = {}
        for step in self.steps:
            for slot in step.missing_slots:
                seen.setdefault(slot, None)
        return tuple(seen)


# ──────────────────────────────────────────────────────────────────────
# Execution layer
# ──────────────────────────────────────────────────────────────────────
class RetrievedChunk(Frozen):
    """A retrieved passage carrying every score that ranked it.

    All four scores are retained rather than just the final one because the
    UI exposes the whole funnel — that is the explainability requirement, and
    it is also how a retrieval regression gets diagnosed.
    """

    doc_id: str
    chunk_id: str
    text: str
    collection: str
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    page: int | None = None
    dense_score: float | None = None
    bm25_score: float | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None

    dense_rank: int | None = None
    bm25_rank: int | None = None
    fused_rank: int | None = None
    final_rank: int | None = None

    @property
    def effective_score(self) -> float:
        """Best available score, preferring the latest ranking stage."""
        for score in (self.rerank_score, self.rrf_score, self.dense_score, self.bm25_score):
            if score is not None:
                return score
        return 0.0

    @property
    def rank_delta(self) -> int | None:
        """How far reranking moved this chunk. Negative means promoted."""
        if self.fused_rank is None or self.final_rank is None:
            return None
        return self.final_rank - self.fused_rank


class Claim(Frozen):
    """One factual assertion in a drafted reply, with its supporting evidence."""

    text: str
    supporting_chunk_ids: tuple[str, ...] = ()
    is_numeric: bool = False

    @property
    def is_supported(self) -> bool:
        return bool(self.supporting_chunk_ids)


class GroundingReport(Frozen):
    """Whether a draft is backed by the evidence that was retrieved.

    An unsupported numeric claim is treated far more seriously than an
    unsupported qualitative one: a wrong profit rate quoted to a customer is
    a commercial and regulatory problem, a vague adjective is not.
    """

    verdict: GroundingVerdict
    claims: tuple[Claim, ...]
    faithfulness_score: float = Field(ge=0.0, le=1.0)

    @property
    def unsupported_claims(self) -> tuple[Claim, ...]:
        return tuple(c for c in self.claims if not c.is_supported)

    @property
    def has_unsupported_numeric_claim(self) -> bool:
        return any(c.is_numeric and not c.is_supported for c in self.claims)

    @property
    def passes(self) -> bool:
        return self.verdict is GroundingVerdict.GROUNDED


class DraftReply(Frozen):
    """A reply prepared for the customer.

    ``ar`` is populated whenever the inbound message contained any Arabic.
    """

    en: str
    ar: str | None = None
    requires_human_approval: bool = True
    cta: str | None = None

    @model_validator(mode="after")
    def _reject_blank_english(self) -> Self:
        if not self.en.strip():
            raise ValueError("A draft reply must always carry English text.")
        return self

    @property
    def is_bilingual(self) -> bool:
        return bool(self.ar and self.ar.strip())


# ──────────────────────────────────────────────────────────────────────
# Telemetry
# ──────────────────────────────────────────────────────────────────────
class TokenUsage(Frozen):
    """Token counts and cost for a single model call."""

    prompt_tokens: int = Field(ge=0, default=0)
    completion_tokens: int = Field(ge=0, default=0)
    cost_usd: float = Field(ge=0.0, default=0.0)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            cost_usd=self.cost_usd + other.cost_usd,
        )


class VehicleRef(Frozen):
    """A vehicle the conversation is about, as far as it is known.

    Every field is optional because customers reveal specifications
    gradually — "a Renzo" on Monday becomes "the 2020 Renzo S5" on Tuesday.
    """

    brand: str | None = None
    model: str | None = None
    year: int | None = None
    body_style: str | None = None

    @property
    def is_identified(self) -> bool:
        """Enough detail to look the vehicle up in the catalog."""
        return bool(self.brand and self.model)

    def describe(self) -> str:
        parts = [str(p) for p in (self.year, self.brand, self.model, self.body_style) if p]
        return " ".join(parts) if parts else "unspecified vehicle"


class IntentSignal(Frozen):
    """A raw intent observation from the understanding layer.

    Deliberately not an ``Intent``: this is what the model reported, before
    business rules assign a department, priority or dependencies. Keeping the
    two types distinct is what stops model output from silently becoming a
    routing decision.
    """

    category: IntentCategory
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str | None = None


class ConversationTurn(Frozen):
    """One inbound or outbound message.

    Retained for audit and for the generation prompt window only. No stage
    may re-derive intent, entities or status by re-reading these — structured
    state is the source of truth.
    """

    role: str
    text: str
    at: datetime
