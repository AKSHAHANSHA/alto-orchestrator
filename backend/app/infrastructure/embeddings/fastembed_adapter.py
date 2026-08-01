"""Local embedding and reranking via FastEmbed.

All three models run on CPU inside the container: no API key, no per-query
cost, no network dependency in the retrieval hot path.

The dense model is deliberately multilingual: it places Arabic and English in
the same vector space, so a customer asking "كم القسط الشهري؟" retrieves the
English Emirates NBD financing terms directly, with no translation hop. That
satisfies the requirement to reason in the original language rather than
translating first — and it is why an entirely English corpus is not a blocker
for Arabic customers.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from functools import lru_cache
from typing import Any

from app.core.logging import get_logger
from app.domain.value_objects import RetrievedChunk

logger = get_logger(__name__)

# The e5 family is trained with asymmetric prefixes and loses noticeable
# accuracy without them. Every other family is trained symmetrically, and
# prepending these would just add meaningless tokens — so the prefix is
# applied on a per-model basis rather than unconditionally.
QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "


def _uses_e5_prefixes(model_name: str) -> bool:
    return "e5" in model_name.lower()


def _is_non_latin(text: str, threshold: float = 0.2) -> bool:
    """Whether enough of the query is non-Latin to defeat an English reranker."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    non_latin = sum(1 for c in letters if not ("a" <= c.lower() <= "z"))
    return non_latin / len(letters) >= threshold


@lru_cache(maxsize=4)
def _dense_model(name: str) -> Any:
    from fastembed import TextEmbedding

    logger.info("loading_dense_model", model=name)
    return TextEmbedding(model_name=name)


@lru_cache(maxsize=4)
def _sparse_model(name: str) -> Any:
    from fastembed import SparseTextEmbedding

    logger.info("loading_sparse_model", model=name)
    return SparseTextEmbedding(model_name=name)


@lru_cache(maxsize=2)
def _cross_encoder(name: str) -> Any:
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    logger.info("loading_reranker", model=name)
    return TextCrossEncoder(model_name=name)


class FastEmbedEmbedder:
    """Dense and sparse embeddings from local ONNX models."""

    def __init__(self, *, dense_model: str, sparse_model: str, dimension: int) -> None:
        self.model_name = dense_model
        self.dimension = dimension
        self._dense_name = dense_model
        self._sparse_name = sparse_model

    async def embed_dense(
        self, texts: Sequence[str], *, is_query: bool = True
    ) -> list[list[float]]:
        if _uses_e5_prefixes(self._dense_name):
            prefix = QUERY_PREFIX if is_query else PASSAGE_PREFIX
            prepared = [prefix + t for t in texts]
        else:
            prepared = list(texts)

        def run() -> list[list[float]]:
            model = _dense_model(self._dense_name)
            return [vector.tolist() for vector in model.embed(prepared)]

        # FastEmbed is synchronous and CPU-bound; off-loading keeps the event
        # loop responsive while a batch encodes.
        return await asyncio.to_thread(run)

    async def embed_sparse(self, texts: Sequence[str]) -> list[dict[int, float]]:
        def run() -> list[dict[int, float]]:
            model = _sparse_model(self._sparse_name)
            return [
                dict(zip(emb.indices.tolist(), emb.values.tolist(), strict=True))
                for emb in model.embed(list(texts))
            ]

        return await asyncio.to_thread(run)


class FastEmbedReranker:
    """Cross-encoder reranking of fused candidates.

    Runs after fusion on a bounded candidate set. Reranking cannot recover a
    document the prefetch never returned, which is why recall@100 is the
    metric that gates the stage before it.
    """

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    async def rerank(
        self, query: str, chunks: Sequence[RetrievedChunk], top_k: int
    ) -> list[RetrievedChunk]:
        if not chunks:
            return []

        # The ms-marco cross-encoders are trained on English only. Given an
        # Arabic query they return uniformly negative scores that carry no
        # ranking signal, so applying them would scramble a fusion order that
        # was actually correct — measured directly against this corpus.
        #
        # Cross-lingual *retrieval* still works, because the dense model is
        # multilingual; it is only this reranking stage that cannot cross the
        # language boundary. So for Arabic queries we keep the RRF order and
        # say so, rather than silently degrading the result.
        if _is_non_latin(query):
            logger.info(
                "rerank_skipped_non_latin_query",
                reason="cross-encoder is English-only; preserving RRF fusion order",
            )
            return [
                chunk.model_copy(update={"final_rank": rank})
                for rank, chunk in enumerate(chunks[:top_k])
            ]

        def run() -> list[float]:
            encoder = _cross_encoder(self.model_name)
            return list(encoder.rerank(query, [c.text for c in chunks]))

        try:
            scores = await asyncio.to_thread(run)
        except Exception as exc:
            # Degrade to fusion order rather than failing the conversation.
            logger.warning("rerank_failed", error=str(exc))
            return list(chunks)[:top_k]

        scored = [
            chunk.model_copy(update={"rerank_score": score})
            for chunk, score in zip(chunks, scores, strict=True)
        ]
        scored.sort(key=lambda c: -(c.rerank_score or 0))

        # Record the final rank so the UI can show how far reranking moved
        # each chunk — a large promotion is the most interesting thing the
        # retrieval trace has to say.
        return [
            chunk.model_copy(update={"final_rank": rank})
            for rank, chunk in enumerate(scored[:top_k])
        ]
