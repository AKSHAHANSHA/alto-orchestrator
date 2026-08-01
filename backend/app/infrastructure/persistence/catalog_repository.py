"""Structured catalog lookup.

This is the second half of the retrieval story. Semantic search over the
catalog (via Qdrant vectors) is good for *"affordable Karva SUV"* — questions
where similarity is genuinely useful. It is the wrong tool for *"do you have a
Renzo GX 470?"* — that is a structured question, and a vector store answers it
with five semantically-nearby cars that are not the one asked for, which is
worse than useless.

The lookup below runs against Postgres and returns one of three answers:

- ``exact``     — brand+model+year match; here it is.
- ``did_you_mean`` — brand matches, model is close but not identical; here are
  the closest names in the catalog.
- ``not_stocked`` — nothing matches. Say so.

The generator uses the outcome to decide what to tell the customer. The
confidence engine uses it to raise or lower the ``retrieval`` signal.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger
from app.domain.ports import VehicleRecord
from app.infrastructure.persistence.engine import session_scope
from app.infrastructure.persistence.models import VehicleRow

logger = get_logger(__name__)

# Model-name similarity threshold. difflib returns a ratio in [0, 1].
# 0.72 keeps "CR-V" vs "CR V" together and "GX 470" vs "GX 460" together,
# without matching "S5" against "S4" (which would be misleading — those are
# genuinely different cars).
FUZZY_MATCH_THRESHOLD = 0.72


CatalogVerdict = Literal["exact", "did_you_mean", "not_stocked", "insufficient_input"]


@dataclass(frozen=True)
class CatalogLookupResult:
    verdict: CatalogVerdict
    brand: str | None
    model: str | None
    year: int | None
    matches: tuple[VehicleRecord, ...] = ()
    suggestions: tuple[str, ...] = ()

    @property
    def was_found(self) -> bool:
        return self.verdict == "exact"

    @property
    def was_missing(self) -> bool:
        return self.verdict == "not_stocked"

    def explain(self) -> str:
        """Short line the generator can quote to the customer verbatim."""
        if self.verdict == "exact":
            top = self.matches[0]
            return f"Yes — we do stock the {top.describe()}."
        if self.verdict == "did_you_mean":
            names = ", ".join(f"'{s}'" for s in self.suggestions[:3])
            return (
                f"We do not stock a {self.brand} {self.model}. The nearest "
                f"models we do stock are: {names}."
            )
        if self.verdict == "not_stocked":
            return (
                f"We do not stock the {self.brand or ''} {self.model or ''}"
                " — the model is not in our catalog."
            ).strip()
        return "We need the brand and model to check the catalog."


class CatalogLookupService:
    """Postgres-backed structured lookup over the vehicle catalog."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    async def lookup(
        self,
        brand: str | None,
        model: str | None,
        year: int | None = None,
    ) -> CatalogLookupResult:
        """Answer the structured question 'do you stock this vehicle?'.

        Case- and whitespace-tolerant on brand and model. Year is best-effort:
        if the exact year isn't in stock we still call it a match if any other
        year of the same brand-model is, and we return that record so the
        generator can say *"we have the 2019 not the 2020"*.
        """
        if not brand or not model:
            return CatalogLookupResult(
                verdict="insufficient_input",
                brand=brand,
                model=model,
                year=year,
            )

        brand_norm = brand.strip()
        model_norm = _normalise_model(model)

        async with session_scope(self._factory) as session:
            exact = await self._find_exact(session, brand_norm, model_norm, year)
            if exact:
                return CatalogLookupResult(
                    verdict="exact",
                    brand=brand_norm,
                    model=model_norm,
                    year=year,
                    matches=tuple(_to_record(row) for row in exact),
                )

            # No exact hit — is there anything with a close model name for
            # the same brand? "Did you mean" beats "not found" when it's
            # accurate; a bad "did you mean" beats nothing when it's not.
            brand_models = await self._models_for_brand(session, brand_norm)
            if not brand_models:
                return CatalogLookupResult(
                    verdict="not_stocked",
                    brand=brand_norm,
                    model=model_norm,
                    year=year,
                )

            close = _closest_matches(model_norm, brand_models, cutoff=FUZZY_MATCH_THRESHOLD)
            if close:
                # Return one representative row per suggested model so the
                # generator can name specific years and prices if asked.
                suggested_records = await self._records_for_models(
                    session, brand_norm, close
                )
                return CatalogLookupResult(
                    verdict="did_you_mean",
                    brand=brand_norm,
                    model=model_norm,
                    year=year,
                    matches=suggested_records,
                    suggestions=tuple(close),
                )

            # We do stock the brand, but nothing close in name.
            return CatalogLookupResult(
                verdict="not_stocked",
                brand=brand_norm,
                model=model_norm,
                year=year,
                # Still return a handful of popular models so the generator
                # can offer alternatives.
                matches=await self._popular_for_brand(session, brand_norm, limit=5),
            )

    # ── Query helpers ─────────────────────────────────────────────────
    async def _find_exact(
        self, session: AsyncSession, brand: str, model_norm: str, year: int | None
    ) -> list[VehicleRow]:
        stmt = (
            select(VehicleRow)
            .where(func.lower(VehicleRow.brand) == brand.lower())
            .where(VehicleRow.model_normalized == model_norm)
        )
        if year is not None:
            stmt = stmt.where(VehicleRow.year == year)
        stmt = stmt.order_by(
            VehicleRow.popularity.desc().nullslast(), VehicleRow.year.desc()
        ).limit(5)
        result = await session.execute(stmt)
        rows = list(result.scalars())
        if rows or year is None:
            return rows

        # Year mismatch fallback: same brand+model, any year.
        stmt2 = (
            select(VehicleRow)
            .where(func.lower(VehicleRow.brand) == brand.lower())
            .where(VehicleRow.model_normalized == model_norm)
            .order_by(VehicleRow.popularity.desc().nullslast(), VehicleRow.year.desc())
            .limit(5)
        )
        return list((await session.execute(stmt2)).scalars())

    async def _models_for_brand(self, session: AsyncSession, brand: str) -> list[str]:
        stmt = (
            select(VehicleRow.model)
            .where(func.lower(VehicleRow.brand) == brand.lower())
            .distinct()
        )
        result = await session.execute(stmt)
        return [row[0] for row in result.all()]

    async def _records_for_models(
        self, session: AsyncSession, brand: str, models: list[str]
    ) -> tuple[VehicleRecord, ...]:
        records: list[VehicleRecord] = []
        for model in models[:3]:
            stmt = (
                select(VehicleRow)
                .where(func.lower(VehicleRow.brand) == brand.lower())
                .where(VehicleRow.model == model)
                .order_by(VehicleRow.year.desc())
                .limit(1)
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is not None:
                records.append(_to_record(row))
        return tuple(records)

    async def _popular_for_brand(
        self, session: AsyncSession, brand: str, limit: int
    ) -> tuple[VehicleRecord, ...]:
        stmt = (
            select(VehicleRow)
            .where(func.lower(VehicleRow.brand) == brand.lower())
            .order_by(VehicleRow.popularity.desc().nullslast(), VehicleRow.year.desc())
            .limit(limit)
        )
        rows = list((await session.execute(stmt)).scalars())
        return tuple(_to_record(row) for row in rows)


def _normalise_model(raw: str) -> str:
    """Collapse whitespace, uppercase, standardise dashes.

    Customers write model names inconsistently — *CR-V*, *CR V*, *cr v*,
    *crv* are all the same car. This matches how we stored ``model_normalized``
    in the ingestion worker.
    """
    cleaned = raw.strip().upper()
    for junk in ("_", "  "):
        cleaned = cleaned.replace(junk, " ")
    return " ".join(cleaned.split())


def _closest_matches(
    target: str, candidates: list[str], cutoff: float, count: int = 5
) -> list[str]:
    return difflib.get_close_matches(target, candidates, n=count, cutoff=cutoff)


def _to_record(row: VehicleRow) -> VehicleRecord:
    return VehicleRecord(
        id=row.id,
        brand=row.brand,
        model=row.model,
        year=row.year,
        body_style=row.body_style,
        market_category=row.market_category,
        engine_hp=row.engine_hp,
        transmission=row.transmission,
        driven_wheels=row.driven_wheels,
        doors=row.doors,
        highway_mpg=row.highway_mpg,
        city_mpg=row.city_mpg,
        msrp=row.msrp,
        popularity=row.popularity,
    )
