"""Dependency container.

Constructed once at startup and passed into the graph, so every service
receives its collaborators rather than reaching for a module-level singleton.
That is what makes each stage testable in isolation: a test builds a container
with a mock provider and a null retriever, and nothing else changes.

Optional infrastructure degrades rather than crashes. If Qdrant is down or the
corpus has not been ingested, retrieval returns nothing — which drives the
retrieval confidence signal to zero and routes conversations to a human. That
is the correct behaviour for a platform with no evidence to answer from, and
far better than refusing to accept inquiries at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger
from app.core.settings import ProviderName, Settings, get_settings
from app.domain.enums import ModelTier
from app.infrastructure.llm.providers import ModelRouter, build_provider
from app.infrastructure.llm.registry import BudgetGuard
from app.infrastructure.persistence.catalog_repository import CatalogLookupService
from app.infrastructure.vectorstore.retriever import HybridRetriever, NullRetriever
from app.services.execution.appointments import AppointmentService
from app.services.execution.catalog import VehicleCatalogService
from app.services.execution.clarification import ClarificationWriter
from app.services.execution.runtime import (
    Actuator,
    HumanReviewQueue,
    MemoryService,
    ResponseGenerator,
    ToolRunner,
)
from app.services.understanding.engine import UnderstandingEngine

logger = get_logger(__name__)


class RouterFacade:
    """Thin wrapper exposing what the nodes need for span attribution."""

    def __init__(self, router: ModelRouter) -> None:
        self._router = router

    @property
    def provider_name(self) -> str:
        return self._router.provider_name

    @property
    def budget(self) -> BudgetGuard:
        return self._router.budget

    def model_for_fast(self) -> str:
        return self._router.model_for(ModelTier.FAST)

    def model_for_premium(self) -> str:
        return self._router.model_for(ModelTier.PREMIUM)

    def __getattr__(self, item: str) -> Any:
        return getattr(self._router, item)


@dataclass
class Container:
    """Everything the graph needs, resolved once."""

    settings: Settings
    router: RouterFacade
    understanding: UnderstandingEngine
    catalog: VehicleCatalogService
    tools: ToolRunner
    retriever: Any
    generator: ResponseGenerator
    actuator: Actuator
    human_queue: HumanReviewQueue
    memory: MemoryService
    appointments: AppointmentService = field(default_factory=AppointmentService)
    # Defaults to template-only, so a container built without one — every test
    # fixture, and any deployment with no Groq key — clarifies exactly as it
    # did before, deterministically and at zero cost.
    clarifier: ClarificationWriter = field(default_factory=ClarificationWriter)
    # Optional so test fixtures constructing a Container by keyword can omit
    # it — the vector-only path still works for everything except honest
    # "we don't stock that" replies.
    catalog_lookup: CatalogLookupService | None = None

    @property
    def retrieval_enabled(self) -> bool:
        return not isinstance(self.retriever, NullRetriever)

    @property
    def structured_catalog_enabled(self) -> bool:
        return self.catalog_lookup is not None

    @property
    def clarifier_uses_model(self) -> bool:
        return self.clarifier.uses_model


def _build_retriever(settings: Settings) -> Any:
    """Attach to Qdrant, or fall back to the null retriever.

    The fallback keeps the platform usable before ingestion has run, which is
    the state a fresh clone starts in.
    """
    try:
        from qdrant_client import QdrantClient

        from app.infrastructure.embeddings.fastembed_adapter import (
            FastEmbedEmbedder,
            FastEmbedReranker,
        )

        client = QdrantClient(
            url=settings.qdrant_url, api_key=settings.qdrant_api_key or None, timeout=10
        )
        existing = {c.name for c in client.get_collections().collections}
        if not existing:
            logger.warning(
                "no_qdrant_collections",
                note="run `python tasks.py ingest`; retrieval disabled until then",
            )
            return NullRetriever()

        return HybridRetriever(
            client=client,
            embedder=FastEmbedEmbedder(
                dense_model=settings.dense_embedding_model,
                sparse_model=settings.sparse_embedding_model,
                dimension=settings.dense_embedding_dim,
            ),
            reranker=(
                FastEmbedReranker(settings.rerank_model)
                if settings.retrieval_rerank_enabled
                else None
            ),
            prefetch_limit=settings.retrieval_prefetch_limit,
            fusion_top_k=settings.retrieval_fusion_top_k,
            rerank_top_k=settings.retrieval_rerank_top_k,
            rrf_k=settings.retrieval_rrf_k,
        )
    except Exception as exc:
        logger.warning("retrieval_unavailable", error=str(exc))
        return NullRetriever()


def _build_catalog_lookup(settings: Settings) -> CatalogLookupService | None:
    """Attach to Postgres for structured catalog lookups.

    Optional: if Postgres is down, or the schema/data is not there yet, we
    fall through to the vector-only path. The generator still works; it just
    won't be able to say honestly "we don't stock that" — that's the
    capability the structured lookup adds.
    """
    try:
        from app.infrastructure.persistence.engine import (
            build_engine,
            build_session_factory,
        )

        engine = build_engine(settings)
        factory = build_session_factory(engine)
        return CatalogLookupService(factory)
    except Exception as exc:
        logger.warning("catalog_lookup_unavailable", error=str(exc))
        return None


def _build_clarifier(settings: Settings) -> ClarificationWriter:
    """Attach Groq to clarification, or stay on the templates.

    Optional in exactly the same way retrieval and the structured catalog are:
    without it the platform still asks the right question, it just asks it in
    the words `intents.yaml` supplies.
    """
    # The mock provider's contract is that identical input gives identical
    # output, so a failing assertion means the pipeline changed rather than
    # the weather. A live Groq call in the clarify path would break exactly
    # that — and it did, until this check existed: the suite was reaching the
    # network and spending quota on every clarifying turn.
    if settings.llm_provider is ProviderName.MOCK:
        return ClarificationWriter()

    if not settings.groq_api_key:
        return ClarificationWriter()

    try:
        from app.infrastructure.llm.groq_provider import GroqClarifier

        return ClarificationWriter(
            GroqClarifier(
                api_key=settings.groq_api_key,
                model=settings.groq_model,
                timeout_seconds=settings.clarifier_timeout_seconds,
            )
        )
    except Exception as exc:
        logger.warning("clarifier_model_unavailable", error=str(exc))
        return ClarificationWriter()


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or get_settings()

    provider = build_provider(settings)
    router = ModelRouter(provider, BudgetGuard(settings.llm_daily_budget_usd))
    facade = RouterFacade(router)

    catalog = VehicleCatalogService(settings.catalog_path)
    catalog_lookup = _build_catalog_lookup(settings)

    container = Container(
        settings=settings,
        router=facade,
        understanding=UnderstandingEngine(router),
        catalog=catalog,
        catalog_lookup=catalog_lookup,
        tools=ToolRunner(catalog, catalog_lookup),
        retriever=_build_retriever(settings),
        generator=ResponseGenerator(router),
        actuator=Actuator(),
        human_queue=HumanReviewQueue(),
        memory=MemoryService(),
        clarifier=_build_clarifier(settings),
    )

    logger.info(
        "container_ready",
        provider=facade.provider_name,
        catalog_size=catalog.size,
        retrieval_enabled=container.retrieval_enabled,
        structured_catalog=container.structured_catalog_enabled,
        clarifier_model=(
            settings.groq_model if container.clarifier_uses_model else "template"
        ),
        auto_send=settings.allow_auto_send,
    )
    return container
