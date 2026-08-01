"""Ingestion worker.

Builds the three Qdrant collections: the bank finance PDFs, the authored Alto
Motors policies, and the vehicle catalog. Runs as its own process rather than
inside the API, because indexing is a batch job with completely different
resource and failure characteristics from serving.

Collection layout follows the pattern the Qdrant fusion reference establishes:
one collection per corpus, each carrying two named vectors — `dense` and a
`bm25` sparse vector with the IDF modifier — so fusion happens server-side
rather than being stitched together in Python.

    python -m app.workers.ingestion [--recreate]
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from app.core.logging import configure_logging, get_logger
from app.core.settings import get_settings
from app.infrastructure.embeddings.fastembed_adapter import FastEmbedEmbedder
from app.infrastructure.vectorstore.retriever import (
    CATALOG_COLLECTION,
    FINANCE_COLLECTION,
    POLICY_COLLECTION,
)

logger = get_logger(__name__)

CHUNK_SIZE = 700
CHUNK_OVERLAP = 120
BATCH_SIZE = 64

# Below this length a chunk is layout debris rather than a passage. PDF
# extraction leaves plenty of it, and short fragments score deceptively well
# on keyword overlap while carrying no usable information.
MIN_CHUNK_CHARS = 120


@dataclass
class Chunk:
    """A passage plus the metadata the UI needs to show provenance."""

    doc_id: str
    text: str
    source: str
    page: int | None = None
    title: str | None = None
    authority: str | None = None

    @property
    def point_id(self) -> str:
        digest = hashlib.sha256(
            f"{self.doc_id}|{self.page}|{self.text[:120]}".encode()
        ).hexdigest()
        # Qdrant point ids must be UUIDs or unsigned integers.
        return f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"


def split_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Recursive character splitting on progressively weaker boundaries.

    Prefers paragraph breaks, then sentences, then words — so a chunk rarely
    severs a sentence, which matters because chunks are shown verbatim to the
    customer as evidence.

    Fragments below `MIN_CHUNK_CHARS` are dropped. PDF text extraction produces
    a lot of layout debris — stray headers, orphaned label text — and a chunk
    reading "loan.\\nFollowing\\nDown Payment" is worse than useless: it ranks
    well on keyword overlap and tells the customer nothing.
    """
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    if len(text) <= size:
        return [text] if len(text) >= MIN_CHUNK_CHARS else []

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            for separator in ("\n\n", ". ", "\n", " "):
                cut = text.rfind(separator, start + size // 2, end)
                if cut != -1:
                    end = cut + len(separator)
                    break
        piece = text[start:end].strip()
        if len(piece) >= MIN_CHUNK_CHARS:
            chunks.append(piece)
        start = max(start + 1, end - overlap)

    return chunks


def _fingerprint(text: str) -> str:
    """Normalised signature for near-duplicate detection.

    Whitespace and punctuation are stripped and the text is lowercased, so two
    chunks differing only by where the overlap window happened to cut are
    recognised as the same passage.
    """
    return hashlib.sha1(re.sub(r"[^a-z0-9؀-ۿ]+", "", text.lower()).encode()).hexdigest()


def deduplicate(chunks: list[Chunk]) -> list[Chunk]:
    """Drop chunks whose content already appears in the index.

    Sliding-window overlap means adjacent chunks legitimately share text, but
    when a short passage is fully contained in its neighbour the result is
    several near-identical entries competing for the same top-k slots. Left
    unchecked, a customer sees three copies of one sentence presented as three
    independent sources — which is actively misleading about how much evidence
    supports the answer.
    """
    seen: set[str] = set()
    kept: list[Chunk] = []
    dropped = 0

    for chunk in chunks:
        fingerprint = _fingerprint(chunk.text)
        if fingerprint in seen:
            dropped += 1
            continue
        seen.add(fingerprint)
        kept.append(chunk)

    if dropped:
        logger.info("duplicates_dropped", count=dropped, kept=len(kept))
    return kept


def load_pdfs(directory: Path) -> list[Chunk]:
    """Page-aware PDF chunking.

    Page numbers are retained on every chunk so the customer UI can open the
    source document at the exact page and highlight the passage. Losing the
    page here would make the provenance click-through impossible later.
    """
    import fitz

    chunks: list[Chunk] = []
    for path in sorted(directory.glob("*.pdf")):
        document = fitz.open(path)
        title = path.stem.replace("-", " ").title()

        for page_number, page in enumerate(document, start=1):
            for piece in split_text(page.get_text()):
                chunks.append(
                    Chunk(
                        doc_id=path.name,
                        text=piece,
                        source=path.name,
                        page=page_number,
                        title=title,
                        # These are real UAE regulatory and banking documents,
                        # flagged so the UI can show the correct provenance
                        # disclaimer alongside a financing answer.
                        authority="real_uae_regulatory",
                    )
                )

        logger.info("pdf_ingested", file=path.name, pages=len(document))

    return chunks


def load_policies(directory: Path) -> list[Chunk]:
    """Heading-aware Markdown chunking for the authored policies."""
    chunks: list[Chunk] = []
    if not directory.exists():
        logger.warning("no_policy_directory", path=str(directory))
        return chunks

    for path in sorted(directory.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        # Split on H2 boundaries so a chunk is a complete policy clause.
        sections = re.split(r"\n(?=## )", content)

        for section in sections:
            heading = section.splitlines()[0].lstrip("# ").strip() if section.strip() else ""
            for piece in split_text(section):
                chunks.append(
                    Chunk(
                        doc_id=path.name,
                        text=piece,
                        source=path.name,
                        title=heading or path.stem,
                        authority="alto_motors_policy",
                    )
                )

        logger.info("policy_ingested", file=path.name)

    return chunks


def load_catalog(csv_path: Path, limit: int | None = None) -> list[Chunk]:
    """Turn catalog rows into natural-language vehicle cards.

    A row of columns embeds poorly; a sentence embeds well. Writing each
    vehicle as prose means a query like "affordable Karva SUV with good
    mileage" can actually match it.
    """
    chunks: list[Chunk] = []
    if not csv_path.exists():
        logger.error("catalog_missing", path=str(csv_path))
        return chunks

    seen: set[str] = set()
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            brand, model, year = row.get("Make"), row.get("Model"), row.get("Year")
            if not brand or not model or not year:
                continue

            # The catalog has many near-duplicate trims of the same model
            # year. Collapsing them keeps the index useful instead of
            # returning eight variants of one car.
            key = f"{brand}|{model}|{year}|{row.get('Vehicle Style')}"
            if key in seen:
                continue
            seen.add(key)

            parts = [f"{year} {brand} {model}"]
            if row.get("Vehicle Style"):
                parts.append(f"body style: {row['Vehicle Style']}")
            if row.get("Market Category"):
                parts.append(f"category: {row['Market Category']}")
            if row.get("Engine HP"):
                parts.append(f"{row['Engine HP']} horsepower")
            if row.get("Transmission Type"):
                parts.append(f"{row['Transmission Type'].lower()} transmission")
            if row.get("Driven_Wheels"):
                parts.append(row["Driven_Wheels"])
            if row.get("highway MPG"):
                parts.append(f"{row['highway MPG']} highway MPG")
            if row.get("MSRP"):
                parts.append(f"list price {row['MSRP']} AED")

            chunks.append(
                Chunk(
                    doc_id=f"vehicle:{brand}:{model}:{year}",
                    text=". ".join(parts) + ".",
                    source="vehicles.csv",
                    title=f"{year} {brand} {model}",
                    authority="alto_motors_catalog",
                )
            )

            if limit and len(chunks) >= limit:
                break

    logger.info("catalog_ingested", vehicles=len(chunks))
    return chunks


async def index(collection: str, chunks: list[Chunk], *, recreate: bool) -> None:
    """Create the collection and upsert every chunk."""
    from qdrant_client import QdrantClient, models

    settings = get_settings()
    client = QdrantClient(
        url=settings.qdrant_url, api_key=settings.qdrant_api_key or None, timeout=120
    )
    embedder = FastEmbedEmbedder(
        dense_model=settings.dense_embedding_model,
        sparse_model=settings.sparse_embedding_model,
        dimension=settings.dense_embedding_dim,
    )

    if recreate and client.collection_exists(collection):
        client.delete_collection(collection)

    if not client.collection_exists(collection):
        client.create_collection(
            collection_name=collection,
            vectors_config={
                "dense": models.VectorParams(
                    size=settings.dense_embedding_dim,
                    distance=models.Distance.COSINE,
                )
            },
            sparse_vectors_config={
                # The IDF modifier is required. Without it Qdrant stores raw
                # term frequencies and BM25 scoring is silently wrong — one of
                # the easiest mistakes to make here and the hardest to notice.
                "bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)
            },
        )
        logger.info("collection_created", collection=collection)

    for start in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[start : start + BATCH_SIZE]
        texts = [c.text for c in batch]

        # Passages use the `passage:` prefix; queries use `query:`. The e5
        # family is trained asymmetrically and loses accuracy without it.
        dense = await embedder.embed_dense(texts, is_query=False)
        sparse = await embedder.embed_sparse(texts)

        client.upsert(
            collection_name=collection,
            points=[
                models.PointStruct(
                    id=chunk.point_id,
                    vector={
                        "dense": dense_vector,
                        "bm25": models.SparseVector(
                            indices=list(sparse_vector.keys()),
                            values=list(sparse_vector.values()),
                        ),
                    },
                    payload={
                        "text": chunk.text,
                        "doc_id": chunk.doc_id,
                        "source": chunk.source,
                        "page": chunk.page,
                        "title": chunk.title,
                        "authority": chunk.authority,
                    },
                )
                for chunk, dense_vector, sparse_vector in zip(
                    batch, dense, sparse, strict=True
                )
            ],
        )
        logger.info(
            "batch_indexed",
            collection=collection,
            progress=f"{min(start + BATCH_SIZE, len(chunks))}/{len(chunks)}",
        )


async def populate_postgres_catalog(csv_path: Path, limit: int | None = None) -> int:
    """Load the vehicle catalog into Postgres for exact-match lookups.

    Complements the Qdrant vector index rather than replacing it: the SQL
    table answers questions like *"do you stock the Renzo GX 470?"* (an exact
    row lookup), and the vector index answers *"affordable Karva SUV under
    150k"* (a semantic filter). Two stores, two failure modes, one truthful
    catalog.
    """
    from sqlalchemy import delete

    from app.infrastructure.persistence.engine import (
        build_engine,
        build_session_factory,
        ensure_schema,
    )
    from app.infrastructure.persistence.models import VehicleRow

    if not csv_path.exists():
        logger.error("catalog_missing", path=str(csv_path))
        return 0

    settings = get_settings()
    engine = build_engine(settings)
    await ensure_schema(engine)
    factory = build_session_factory(engine)

    rows: list[VehicleRow] = []
    seen: set[str] = set()

    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        for index_no, raw in enumerate(csv.DictReader(handle)):
            brand = (raw.get("Make") or "").strip()
            model = (raw.get("Model") or "").strip()
            year_raw = (raw.get("Year") or "").strip()
            if not brand or not model or not year_raw:
                continue
            try:
                year = int(float(year_raw))
            except ValueError:
                continue

            key = f"{brand}|{model}|{year}|{raw.get('Vehicle Style') or ''}"
            if key in seen:
                continue
            seen.add(key)

            rows.append(
                VehicleRow(
                    id=f"veh_{index_no}",
                    brand=brand,
                    model=model,
                    model_normalized=_normalise_model_key(model),
                    year=year,
                    body_style=(raw.get("Vehicle Style") or "").strip() or None,
                    market_category=(raw.get("Market Category") or "").strip() or None,
                    engine_hp=_as_float(raw.get("Engine HP", "")),
                    engine_cylinders=_as_float(raw.get("Engine Cylinders", "")),
                    engine_fuel_type=(raw.get("Engine Fuel Type") or "").strip() or None,
                    transmission=(raw.get("Transmission Type") or "").strip() or None,
                    driven_wheels=(raw.get("Driven_Wheels") or "").strip() or None,
                    doors=_as_int(raw.get("Number of Doors", "")),
                    highway_mpg=_as_int(raw.get("highway MPG", "")),
                    city_mpg=_as_int(raw.get("city mpg", "")),
                    msrp=_as_float(raw.get("MSRP", "")),
                    popularity=_as_int(raw.get("Popularity", "")),
                )
            )
            if limit and len(rows) >= limit:
                break

    async with factory() as session:
        # Wipe and reload — the source CSV is the whole truth, incremental
        # merging would just add a bug for no ergonomic gain.
        await session.execute(delete(VehicleRow))
        session.add_all(rows)
        await session.commit()

    await engine.dispose()
    logger.info("postgres_catalog_populated", vehicles=len(rows))
    return len(rows)


def _as_int(value: str) -> int | None:
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def _as_float(value: str) -> float | None:
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _normalise_model_key(raw: str) -> str:
    """Same normalisation the catalog-lookup service applies at query time."""
    cleaned = raw.strip().upper().replace("_", " ")
    return " ".join(cleaned.split())


async def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest the Alto Motors corpora.")
    parser.add_argument("--recreate", action="store_true", help="drop collections first")
    parser.add_argument("--catalog-limit", type=int, default=None,
                        help="cap catalog rows (useful for a quick smoke run)")
    parser.add_argument(
        "--skip-postgres",
        action="store_true",
        help="skip the Postgres catalog populate (useful when Postgres isn't up)",
    )
    args = parser.parse_args()

    configure_logging()
    settings = get_settings()

    corpora = [
        (FINANCE_COLLECTION, load_pdfs(settings.finance_docs_dir)),
        (POLICY_COLLECTION, load_policies(settings.policy_docs_dir)),
        (CATALOG_COLLECTION, load_catalog(settings.catalog_path, args.catalog_limit)),
    ]

    corpora = [(name, deduplicate(chunks)) for name, chunks in corpora]

    for collection, chunks in corpora:
        if not chunks:
            logger.warning("nothing_to_index", collection=collection)
            continue
        await index(collection, chunks, recreate=args.recreate)

    if not args.skip_postgres:
        # Same source data, second store — structured lookup for exact
        # brand+model+year questions, complementing the vector index.
        await populate_postgres_catalog(settings.catalog_path, args.catalog_limit)

    total = sum(len(c) for _, c in corpora)
    logger.info("ingestion_complete", total_chunks=total)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
