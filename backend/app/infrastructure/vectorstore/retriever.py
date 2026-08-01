"""Hybrid retrieval over Qdrant.

One collection per corpus, each holding two named vectors — `dense` and a
`bm25` sparse vector with the IDF modifier — fused server-side by Reciprocal
Rank Fusion, then reranked by a local cross-encoder.

Two details are load-bearing and easy to get wrong:

* `modifier=Modifier.IDF` on the sparse config is **required**. Without it
  Qdrant stores raw term frequencies and BM25 scoring is silently wrong.
* Naive linear blending of dense and sparse scores does not work. Dense cosine
  is bounded around 0.3-0.7 while BM25 is unbounded and shifts scale per
  query, so a fixed alpha lets BM25 dominate by an order of magnitude. RRF
  exists precisely because it fuses ranks rather than magnitudes.

Every score from every stage is retained on the chunk. That is not
diagnostics — it is the explainability requirement, and it is also how a
retrieval regression gets diagnosed later.
"""

from __future__ import annotations

import time
from typing import Any

from app.core.logging import get_logger
from app.domain.entities import IntentQueue
from app.domain.enums import IntentCategory
from app.domain.ports import RetrievalResult
from app.domain.value_objects import RetrievedChunk

logger = get_logger(__name__)

FINANCE_COLLECTION = "alto_finance_kb"
POLICY_COLLECTION = "alto_policy_kb"
CATALOG_COLLECTION = "alto_vehicle_catalog"

# Which corpus answers which question. Searching all three for every message
# wastes latency and dilutes ranking with irrelevant candidates.
COLLECTIONS_FOR_INTENT: dict[IntentCategory, tuple[str, ...]] = {
    IntentCategory.FINANCING_EMI: (FINANCE_COLLECTION, POLICY_COLLECTION),
    IntentCategory.TRADE_IN_VALUATION: (POLICY_COLLECTION, CATALOG_COLLECTION),
    IntentCategory.TEST_DRIVE_BOOKING: (POLICY_COLLECTION,),
    IntentCategory.VEHICLE_AVAILABILITY_INFO: (CATALOG_COLLECTION, POLICY_COLLECTION),
    IntentCategory.PRICING_OFFERS: (CATALOG_COLLECTION, FINANCE_COLLECTION),
    IntentCategory.SERVICE_AFTERSALES: (POLICY_COLLECTION,),
    IntentCategory.COMPLAINT_ESCALATION: (POLICY_COLLECTION,),
    IntentCategory.GENERAL_INFO: (POLICY_COLLECTION,),
    # Small talk needs no evidence — a warm reply is written by the model
    # without any retrieval.
    IntentCategory.SMALL_TALK: (),
    IntentCategory.UNCLEAR_NEEDS_CLARIFICATION: (POLICY_COLLECTION, CATALOG_COLLECTION),
}


class HybridRetriever:
    """Dense + BM25 retrieval with server-side RRF and local reranking."""

    def __init__(
        self,
        client: Any,
        embedder: Any,
        reranker: Any = None,
        *,
        prefetch_limit: int = 100,
        fusion_top_k: int = 20,
        rerank_top_k: int = 5,
        rrf_k: int = 2,
    ) -> None:
        self._client = client
        self._embedder = embedder
        self._reranker = reranker
        self._prefetch_limit = prefetch_limit
        self._fusion_top_k = fusion_top_k
        self._rerank_top_k = rerank_top_k
        self._rrf_k = rrf_k

    async def search_for(self, query: str, intents: IntentQueue) -> RetrievalResult:
        """Search the corpora relevant to the open intents."""
        collections: set[str] = set()
        for intent in intents.unresolved:
            collections.update(COLLECTIONS_FOR_INTENT.get(intent.category, ()))

        if not collections:
            collections = {POLICY_COLLECTION}

        return await self.search(query, tuple(sorted(collections)))

    async def search(self, query: str, collections: tuple[str, ...]) -> RetrievalResult:
        from qdrant_client import models

        started = time.perf_counter()
        dense_vector = (await self._embedder.embed_dense([query]))[0]
        sparse_vector = (await self._embedder.embed_sparse([query]))[0]
        embed_ms = (time.perf_counter() - started) * 1000

        all_chunks: list[RetrievedChunk] = []
        fusion_started = time.perf_counter()

        for collection in collections:
            try:
                response = self._client.query_points(
                    collection_name=collection,
                    prefetch=[
                        models.Prefetch(
                            query=dense_vector,
                            using="dense",
                            limit=self._prefetch_limit,
                        ),
                        models.Prefetch(
                            query=models.SparseVector(
                                indices=list(sparse_vector.keys()),
                                values=list(sparse_vector.values()),
                            ),
                            using="bm25",
                            limit=self._prefetch_limit,
                        ),
                    ],
                    query=models.FusionQuery(fusion=models.Fusion.RRF),
                    limit=self._fusion_top_k,
                    with_payload=True,
                )
            except Exception as exc:
                logger.warning("collection_query_failed", collection=collection, error=str(exc))
                continue

            for rank, point in enumerate(response.points):
                payload = point.payload or {}
                all_chunks.append(
                    RetrievedChunk(
                        doc_id=str(payload.get("doc_id", collection)),
                        chunk_id=str(point.id),
                        text=str(payload.get("text", "")),
                        collection=collection,
                        page=payload.get("page"),
                        rrf_score=point.score,
                        fused_rank=rank,
                        metadata={
                            k: v
                            for k, v in payload.items()
                            if k not in {"text"} and isinstance(v, str | int | float | bool)
                        },
                    )
                )

        fusion_ms = (time.perf_counter() - fusion_started) * 1000

        # Score the isolated retrievers too, so the UI can show the full
        # funnel rather than only the fused number.
        dense_ms, sparse_ms = await self._annotate_stage_scores(
            query, dense_vector, sparse_vector, collections, all_chunks
        )

        all_chunks.sort(key=lambda c: -(c.rrf_score or 0))

        rerank_started = time.perf_counter()
        if self._reranker and all_chunks:
            final = await self._reranker.rerank(
                query, all_chunks[: self._fusion_top_k], self._rerank_top_k
            )
        else:
            final = all_chunks[: self._rerank_top_k]
        rerank_ms = (time.perf_counter() - rerank_started) * 1000

        return RetrievalResult(
            chunks=tuple(final),
            query=query,
            dense_ms=round(dense_ms + embed_ms, 2),
            sparse_ms=round(sparse_ms, 2),
            fusion_ms=round(fusion_ms, 2),
            rerank_ms=round(rerank_ms, 2),
        )

    async def _annotate_stage_scores(
        self,
        query: str,
        dense_vector: list[float],
        sparse_vector: dict[int, float],
        collections: tuple[str, ...],
        chunks: list[RetrievedChunk],
    ) -> tuple[float, float]:
        """Attach isolated dense and BM25 scores to the fused candidates.

        Costs two extra queries per collection. Worth it: without them the UI
        can only show that a chunk ranked highly, not *why* — and "BM25 found
        it, dense did not" is exactly the insight that explains a surprising
        result.
        """
        from qdrant_client import models

        by_id = {c.chunk_id: c for c in chunks}
        dense_ms = sparse_ms = 0.0

        for collection in collections:
            started = time.perf_counter()
            try:
                dense_hits = self._client.query_points(
                    collection_name=collection,
                    query=dense_vector,
                    using="dense",
                    limit=self._prefetch_limit,
                    with_payload=False,
                ).points
            except Exception:
                dense_hits = []
            dense_ms += (time.perf_counter() - started) * 1000

            started = time.perf_counter()
            try:
                sparse_hits = self._client.query_points(
                    collection_name=collection,
                    query=models.SparseVector(
                        indices=list(sparse_vector.keys()),
                        values=list(sparse_vector.values()),
                    ),
                    using="bm25",
                    limit=self._prefetch_limit,
                    with_payload=False,
                ).points
            except Exception:
                sparse_hits = []
            sparse_ms += (time.perf_counter() - started) * 1000

            for rank, hit in enumerate(dense_hits):
                chunk = by_id.get(str(hit.id))
                if chunk is not None:
                    by_id[str(hit.id)] = chunk.model_copy(
                        update={"dense_score": hit.score, "dense_rank": rank}
                    )

            for rank, hit in enumerate(sparse_hits):
                chunk = by_id.get(str(hit.id))
                if chunk is not None:
                    by_id[str(hit.id)] = chunk.model_copy(
                        update={"bm25_score": hit.score, "bm25_rank": rank}
                    )

        chunks[:] = list(by_id.values())
        return dense_ms, sparse_ms


class NullRetriever:
    """Stands in when Qdrant is unavailable or the corpus is not yet ingested.

    Returns nothing rather than raising. Empty retrieval drives the retrieval
    confidence signal to zero, which routes the conversation to a human — the
    correct behaviour when the platform has no evidence to answer from.
    """

    async def search_for(self, query: str, intents: IntentQueue) -> RetrievalResult:
        return RetrievalResult(chunks=(), query=query)

    async def search(self, query: str, collections: tuple[str, ...]) -> RetrievalResult:
        return RetrievalResult(chunks=(), query=query)
