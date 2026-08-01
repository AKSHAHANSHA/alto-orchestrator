"""API data-transfer objects.

Deliberately separate from domain entities. The wire format is a contract with
the frontend and changes for presentational reasons; the domain model changes
for business reasons. Coupling them would make every UI tweak a domain edit.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domain.entities import ConversationState, HumanReviewItem, Span
from app.domain.value_objects import RetrievedChunk


class InquiryRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None
    customer_id: str | None = None
    channel: str = "web_form"
    idempotency_key: str | None = Field(
        default=None,
        description=(
            "Supply on retryable transports. WhatsApp webhooks redeliver, and "
            "without this a redelivery starts a second run that can double-book."
        ),
    )


class ChunkDTO(BaseModel):
    """A retrieved passage with every score that ranked it.

    All four stages are exposed because the customer UI shows the whole
    funnel — that is the explainability requirement, not a debugging aid.
    """

    chunk_id: str
    doc_id: str
    text: str
    collection: str
    source: str | None = None
    title: str | None = None
    page: int | None = None
    authority: str | None = None

    dense_score: float | None = None
    bm25_score: float | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None
    dense_rank: int | None = None
    bm25_rank: int | None = None
    fused_rank: int | None = None
    final_rank: int | None = None
    rank_delta: int | None = None

    @classmethod
    def of(cls, chunk: RetrievedChunk) -> ChunkDTO:
        return cls(
            chunk_id=chunk.chunk_id,
            doc_id=chunk.doc_id,
            text=chunk.text,
            collection=chunk.collection,
            source=str(chunk.metadata.get("source") or chunk.doc_id),
            title=str(chunk.metadata.get("title") or ""),
            page=chunk.page,
            authority=str(chunk.metadata.get("authority") or ""),
            dense_score=chunk.dense_score,
            bm25_score=chunk.bm25_score,
            rrf_score=chunk.rrf_score,
            rerank_score=chunk.rerank_score,
            dense_rank=chunk.dense_rank,
            bm25_rank=chunk.bm25_rank,
            fused_rank=chunk.fused_rank,
            final_rank=chunk.final_rank,
            rank_delta=chunk.rank_delta,
        )


class IntentDTO(BaseModel):
    id: str
    category: str
    status: str
    confidence: float
    priority: int
    is_primary: bool
    department: str | None
    missing_slots: list[str]
    depends_on: list[str]
    evidence: str | None


class ConfidenceDTO(BaseModel):
    language: float
    intent: float
    entity: float
    retrieval: float
    risk: float
    policy: float
    decision_score: float
    weakest_signal: str


class RoutingDTO(BaseModel):
    tier: str
    department: str | None
    model_tier: str | None
    rule_id: str
    rationale: str
    overrides_applied: list[str]


class ReplyDTO(BaseModel):
    en: str
    ar: str | None = None
    is_bilingual: bool
    requires_human_approval: bool


class GroundingDTO(BaseModel):
    verdict: str
    faithfulness_score: float
    total_claims: int
    unsupported_claims: int
    has_unsupported_numeric_claim: bool


class SpanDTO(BaseModel):
    node: str
    layer: str
    status: str
    latency_ms: float
    model: str | None
    provider: str | None
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    attributes: dict[str, Any]
    error: str | None

    @classmethod
    def of(cls, span: Span) -> SpanDTO:
        return cls(
            node=span.node,
            layer=span.layer.value,
            status=span.status.value,
            latency_ms=span.latency_ms,
            model=span.model,
            provider=span.provider,
            prompt_tokens=span.usage.prompt_tokens,
            completion_tokens=span.usage.completion_tokens,
            cost_usd=span.usage.cost_usd,
            attributes=span.attributes,
            error=span.error,
        )


class InquiryResponse(BaseModel):
    """Everything the UI needs to render an answer and explain it."""

    conversation_id: str
    trace_id: str

    language: dict[str, Any] | None = None
    sentiment: dict[str, Any] | None = None
    intents: list[IntentDTO] = []
    entities: list[dict[str, Any]] = []
    next_action: str | None = None
    plan_steps: list[dict[str, Any]] = []

    confidence: ConfidenceDTO | None = None
    routing: RoutingDTO | None = None
    reply: ReplyDTO | None = None
    grounding: GroundingDTO | None = None
    chunks: list[ChunkDTO] = []
    actions: list[dict[str, Any]] = []

    escalated: bool = False
    awaiting: str | None = None

    total_latency_ms: float = 0.0
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    spans: list[SpanDTO] = []


class ConversationSummary(BaseModel):
    conversation_id: str
    customer_id: str | None
    channel: str
    open_intents: int
    total_intents: int
    primary_intent: str | None
    department: str | None
    escalated: bool
    updated_at: datetime

    @classmethod
    def of(cls, state: ConversationState) -> ConversationSummary:
        primary = state.intents.primary
        return cls(
            conversation_id=state.conversation_id,
            customer_id=state.customer_id,
            channel=state.channel.value,
            open_intents=len(state.intents.unresolved),
            total_intents=len(state.intents),
            primary_intent=primary.category.value if primary else None,
            department=(
                state.routing.department.value
                if state.routing and state.routing.department
                else None
            ),
            escalated=bool(state.routing and state.routing.requires_human),
            updated_at=state.updated_at,
        )


class TranscriptTurnDTO(BaseModel):
    role: str
    text: str
    at: str


class ReviewItemDTO(BaseModel):
    id: str
    conversation_id: str
    reason: str
    department: str | None
    created_at: datetime
    is_open: bool
    draft: ReplyDTO | None
    routing: RoutingDTO | None
    confidence: ConfidenceDTO | None
    # Populated by the API layer from memory; carried on the review item so
    # the reviewer sees the whole conversation, not just the drafted reply.
    transcript: list[TranscriptTurnDTO] = []

    @classmethod
    def of(cls, item: HumanReviewItem) -> ReviewItemDTO:
        routing = item.routing
        return cls(
            id=item.id,
            conversation_id=item.conversation_id,
            reason=item.reason.value,
            department=item.department.value if item.department else None,
            created_at=item.created_at,
            is_open=item.is_open,
            draft=(
                ReplyDTO(
                    en=item.draft.en,
                    ar=item.draft.ar,
                    is_bilingual=item.draft.is_bilingual,
                    requires_human_approval=item.draft.requires_human_approval,
                )
                if item.draft
                else None
            ),
            routing=(
                RoutingDTO(
                    tier=routing.tier.value,
                    department=routing.department.value if routing.department else None,
                    model_tier=routing.model_tier.value if routing.model_tier else None,
                    rule_id=routing.rule_id,
                    rationale=routing.rationale,
                    overrides_applied=list(routing.overrides_applied),
                )
                if routing
                else None
            ),
            confidence=(
                ConfidenceDTO(
                    **routing.confidence.as_dict(),
                    decision_score=routing.confidence.decision_score,
                    weakest_signal=routing.confidence.weakest_signal.value,
                )
                if routing
                else None
            ),
        )


class ResolveReviewRequest(BaseModel):
    outcome: str = Field(description="approved | edited | reassigned | rejected")
    reviewer: str
    final_text: str | None = None
    reassign_to: str | None = Field(
        default=None,
        description=(
            "For outcome='reassigned', the department to hand off to. "
            "Ignored otherwise."
        ),
    )


class EmiRequestDTO(BaseModel):
    vehicle_price: float = Field(gt=0)
    down_payment: float | None = None
    tenure_months: int | None = None
    salary_transfer: bool = False
    monthly_income: float | None = None


class ValuationRequestDTO(BaseModel):
    brand: str
    model: str
    year: int
    mileage_km: int | None = None
    condition: str | None = None


class MetricsResponse(BaseModel):
    conversations: int
    open_reviews: int
    escalation_rate: float
    total_cost_usd: float
    total_tokens: int
    avg_latency_ms: float
    provider: str
    budget_remaining_usd: float
    retrieval_enabled: bool
    by_node: list[dict[str, Any]]
    by_layer: list[dict[str, Any]]
