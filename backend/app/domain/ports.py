"""Ports: what the domain needs from the outside world.

Structural ``Protocol`` definitions rather than ABCs, so adapters in
``infrastructure/`` satisfy them by shape and never import the domain to
inherit from it. Dependencies point inward; nothing here imports SQLAlchemy,
Qdrant, LangGraph or an LLM SDK.

This is what makes the business core testable with no I/O: every port has a
deterministic in-memory or mock implementation used by the test suite and by
the zero-cost demo mode.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from typing import Generic, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

from app.domain.entities import (
    ConversationState,
    CustomerProfile,
    ExecutionAction,
    HumanReviewItem,
    Inquiry,
    Span,
)
from app.domain.enums import Department, ModelTier
from app.domain.value_objects import RetrievedChunk, TokenUsage

SchemaT = TypeVar("SchemaT", bound=BaseModel)


# ──────────────────────────────────────────────────────────────────────
# Language models
# ──────────────────────────────────────────────────────────────────────
class LLMResponse(BaseModel):
    """One completion, with the accounting needed to bill and trace it."""

    text: str
    model: str
    provider: str
    usage: TokenUsage


class StructuredResponse(BaseModel, Generic[SchemaT]):
    """A completion parsed into a validated schema.

    Understanding-layer stages always use this rather than free text: an
    unparseable model response should fail loudly at the boundary, not leak
    a malformed string into the pipeline.
    """

    value: SchemaT
    model: str
    provider: str
    usage: TokenUsage


@runtime_checkable
class LLMProvider(Protocol):
    """A model backend. Implemented by OpenAI, Anthropic and a deterministic Mock."""

    name: str

    def model_for(self, tier: ModelTier) -> str: ...

    async def complete(
        self,
        *,
        system: str,
        user: str,
        tier: ModelTier,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse: ...

    async def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[SchemaT],
        tier: ModelTier,
        temperature: float = 0.0,
    ) -> StructuredResponse[SchemaT]: ...

    def stream(
        self,
        *,
        system: str,
        user: str,
        tier: ModelTier,
        temperature: float = 0.0,
    ) -> AsyncIterator[str]: ...


# ──────────────────────────────────────────────────────────────────────
# Retrieval
# ──────────────────────────────────────────────────────────────────────
class RetrievalQuery(BaseModel):
    """A hybrid search request."""

    text: str
    collections: tuple[str, ...]
    prefetch_limit: int = 100
    fusion_top_k: int = 20
    rerank_top_k: int = 5
    filters: dict[str, str | int | float | bool] | None = None


class RetrievalResult(BaseModel):
    """Retrieved chunks plus the timing of each stage.

    Stage timings are returned rather than logged so the customer UI can show
    where latency went, and so a slow reranker is visible instead of hiding
    inside a single retrieval number.
    """

    chunks: tuple[RetrievedChunk, ...]
    query: str
    dense_ms: float = 0.0
    sparse_ms: float = 0.0
    fusion_ms: float = 0.0
    rerank_ms: float = 0.0

    @property
    def total_ms(self) -> float:
        return self.dense_ms + self.sparse_ms + self.fusion_ms + self.rerank_ms


@runtime_checkable
class Retriever(Protocol):
    """Hybrid dense + sparse retrieval with reranking."""

    async def search(self, query: RetrievalQuery) -> RetrievalResult: ...

    async def get_document(self, doc_id: str) -> str | None: ...


@runtime_checkable
class Embedder(Protocol):
    """Text to vectors. Kept behind a port so the model can be swapped when
    cross-lingual recall is measured against the golden set."""

    dimension: int
    model_name: str

    async def embed_dense(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_sparse(self, texts: Sequence[str]) -> list[dict[int, float]]: ...


@runtime_checkable
class Reranker(Protocol):
    """Cross-encoder reranking of candidates against a query."""

    model_name: str

    async def rerank(
        self, query: str, chunks: Sequence[RetrievedChunk], top_k: int
    ) -> list[RetrievedChunk]: ...


# ──────────────────────────────────────────────────────────────────────
# Persistence
# ──────────────────────────────────────────────────────────────────────
@runtime_checkable
class ConversationRepository(Protocol):
    async def get(self, conversation_id: str) -> ConversationState | None: ...

    async def save(self, state: ConversationState) -> None: ...

    async def list_active(self, limit: int = 50) -> list[ConversationState]: ...


@runtime_checkable
class CustomerRepository(Protocol):
    async def get(self, customer_id: str) -> CustomerProfile | None: ...

    async def find_by_phone(self, phone: str) -> CustomerProfile | None: ...

    async def save(self, profile: CustomerProfile) -> None: ...


@runtime_checkable
class InquiryRepository(Protocol):
    async def save(self, inquiry: Inquiry) -> None: ...

    async def find_by_idempotency_key(self, key: str) -> Inquiry | None: ...


@runtime_checkable
class SpanRepository(Protocol):
    """Append-only wide-event storage.

    Append-only on purpose: updates would force read-time deduplication and
    make historical traces mutable, which defeats the point of an audit trail.
    """

    async def append(self, span: Span) -> None: ...

    async def for_conversation(self, conversation_id: str) -> list[Span]: ...

    async def for_trace(self, trace_id: str) -> list[Span]: ...

    async def aggregate_cost(
        self, since: datetime | None = None
    ) -> dict[str, float]: ...


@runtime_checkable
class HumanReviewRepository(Protocol):
    async def enqueue(self, item: HumanReviewItem) -> None: ...

    async def get(self, item_id: str) -> HumanReviewItem | None: ...

    async def list_open(
        self, department: Department | None = None, limit: int = 50
    ) -> list[HumanReviewItem]: ...

    async def save(self, item: HumanReviewItem) -> None: ...


@runtime_checkable
class ActionRepository(Protocol):
    async def save(self, action: ExecutionAction) -> None: ...

    async def find_by_idempotency_key(self, key: str) -> ExecutionAction | None: ...

    async def for_conversation(self, conversation_id: str) -> list[ExecutionAction]: ...


@runtime_checkable
class Cache(Protocol):
    """Short-term memory. Everything stored here must be reconstructible."""

    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None: ...

    async def delete(self, key: str) -> None: ...


# ──────────────────────────────────────────────────────────────────────
# Execution — the side effects the coordinator used to perform by hand
# ──────────────────────────────────────────────────────────────────────
class BookingRequest(BaseModel):
    conversation_id: str
    customer_name: str | None
    contact_phone: str | None
    vehicle_description: str
    preferred_date: str
    preferred_time: str | None = None
    idempotency_key: str


class BookingResult(BaseModel):
    booking_id: str
    confirmed_slot: datetime
    was_already_booked: bool = False


@runtime_checkable
class AppointmentPort(Protocol):
    """Test-drive scheduling. Idempotent by contract: a redelivered webhook
    must never produce a second booking."""

    async def book(self, request: BookingRequest) -> BookingResult: ...

    async def available_slots(self, date: str) -> list[datetime]: ...


class LeadPayload(BaseModel):
    conversation_id: str
    customer_id: str | None
    department: Department
    summary: str
    vehicle_of_interest: str | None = None
    idempotency_key: str


@runtime_checkable
class CrmPort(Protocol):
    """Customer and lead records. The seam where Salesforce/Zoho would attach."""

    async def upsert_customer(self, profile: CustomerProfile) -> str: ...

    async def create_lead(self, payload: LeadPayload) -> str: ...


class Notification(BaseModel):
    department: Department
    subject: str
    body: str
    conversation_id: str
    urgent: bool = False
    idempotency_key: str


@runtime_checkable
class NotificationPort(Protocol):
    """Reaching a department. Defaults to an in-platform queue; the seam where
    email, WhatsApp Business or Slack would attach."""

    async def notify(self, notification: Notification) -> str: ...


# ──────────────────────────────────────────────────────────────────────
# Catalog
# ──────────────────────────────────────────────────────────────────────
class VehicleRecord(BaseModel):
    """One row of the vehicle catalog."""

    id: str
    brand: str
    model: str
    year: int
    body_style: str | None = None
    market_category: str | None = None
    engine_hp: float | None = None
    transmission: str | None = None
    driven_wheels: str | None = None
    doors: int | None = None
    highway_mpg: int | None = None
    city_mpg: int | None = None
    msrp: float | None = None
    popularity: int | None = None

    def describe(self) -> str:
        return f"{self.year} {self.brand} {self.model}".strip()


@runtime_checkable
class VehicleCatalog(Protocol):
    """Structured access to the vehicle catalog.

    Separate from retrieval: a trade-in valuation needs an exact MSRP lookup,
    not the semantically nearest vehicle.
    """

    async def find(
        self,
        brand: str | None = None,
        model: str | None = None,
        year: int | None = None,
        limit: int = 20,
    ) -> list[VehicleRecord]: ...

    async def best_match(
        self, brand: str, model: str, year: int | None = None
    ) -> VehicleRecord | None: ...


# ──────────────────────────────────────────────────────────────────────
# Telemetry
# ──────────────────────────────────────────────────────────────────────
@runtime_checkable
class TraceEmitter(Protocol):
    """Publishes span events for live consumption by the admin UI."""

    async def emit(self, span: Span) -> None: ...

    def subscribe(self, conversation_id: str) -> AsyncIterator[Span]: ...


@runtime_checkable
class Clock(Protocol):
    """Injected time.

    Nothing calls ``datetime.now`` directly in a service. SLA arithmetic,
    booking conflicts and depreciation all depend on the current date, and
    tests need those to be deterministic.
    """

    def now(self) -> datetime: ...


__all__ = [
    "ActionRepository",
    "AppointmentPort",
    "BookingRequest",
    "BookingResult",
    "Cache",
    "Clock",
    "ConversationRepository",
    "CrmPort",
    "CustomerRepository",
    "Embedder",
    "HumanReviewRepository",
    "InquiryRepository",
    "LLMProvider",
    "LLMResponse",
    "LeadPayload",
    "Notification",
    "NotificationPort",
    "Reranker",
    "RetrievalQuery",
    "RetrievalResult",
    "Retriever",
    "SpanRepository",
    "StructuredResponse",
    "TraceEmitter",
    "VehicleCatalog",
    "VehicleRecord",
]
