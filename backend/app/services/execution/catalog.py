"""Vehicle catalog.

Structured lookup over the 11,914-row CSV, deliberately separate from
retrieval: a trade-in valuation needs the exact MSRP for a specific
year/model, not the semantically nearest vehicle. Asking a vector store for
"the price of a 2020 Renzo S5" and getting a 2019 S4 would quietly corrupt
every quote built on top of it.

Loaded once into memory. At 11,914 rows and ~1.5 MB this is faster than any
database round trip and removes a failure mode from the hot path.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from app.core.logging import get_logger
from app.domain.ports import VehicleRecord

logger = get_logger(__name__)


def _to_int(value: str) -> int | None:
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def _to_float(value: str) -> float | None:
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


class VehicleCatalogService:
    """In-memory catalog with brand/model indexing."""

    def __init__(self, csv_path: Path) -> None:
        self._path = csv_path
        self._records: list[VehicleRecord] = []
        self._by_brand_model: dict[tuple[str, str], list[VehicleRecord]] = defaultdict(list)
        # Which brands sell a given model. Built for the reverse question —
        # "the customer said S5, whose is that?" — which the brand/model index
        # above cannot answer without a brand to key on.
        self._brands_by_model: dict[str, set[str]] = defaultdict(set)
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            logger.error("catalog_missing", path=str(self._path))
            return

        with self._path.open(encoding="utf-8-sig", newline="") as handle:
            for index, row in enumerate(csv.DictReader(handle)):
                brand = (row.get("Make") or "").strip()
                model = (row.get("Model") or "").strip()
                year = _to_int(row.get("Year", ""))
                if not brand or not model or year is None:
                    continue

                record = VehicleRecord(
                    id=f"veh_{index}",
                    brand=brand,
                    model=model,
                    year=year,
                    body_style=(row.get("Vehicle Style") or "").strip() or None,
                    market_category=(row.get("Market Category") or "").strip() or None,
                    engine_hp=_to_float(row.get("Engine HP", "")),
                    transmission=(row.get("Transmission Type") or "").strip() or None,
                    driven_wheels=(row.get("Driven_Wheels") or "").strip() or None,
                    doors=_to_int(row.get("Number of Doors", "")),
                    highway_mpg=_to_int(row.get("highway MPG", "")),
                    city_mpg=_to_int(row.get("city mpg", "")),
                    msrp=_to_float(row.get("MSRP", "")),
                    popularity=_to_int(row.get("Popularity", "")),
                )
                self._records.append(record)
                self._by_brand_model[(brand.lower(), model.lower())].append(record)
                self._brands_by_model[model.lower()].add(brand)

        logger.info(
            "catalog_loaded",
            records=len(self._records),
            brands=sorted({r.brand for r in self._records}),
        )

    @property
    def size(self) -> int:
        return len(self._records)

    @property
    def brands(self) -> frozenset[str]:
        """Every brand actually stocked. Read from the data, never hardcoded."""
        return frozenset(self._brands_by_model_brands())

    def _brands_by_model_brands(self) -> set[str]:
        return {brand for brands in self._brands_by_model.values() for brand in brands}

    def is_known_model(self, model: str) -> bool:
        return model.strip().lower() in self._brands_by_model

    def brand_for_model(self, model: str) -> str | None:
        """The one brand that sells this model, or None if that is not unique.

        Exists for the customer who knows the car but not the badge. Asked
        "Karva or Renzo?", plenty of people answer "S5" — it is the name on
        the boot lid, and the brand may be something they have never had a
        reason to notice. Refusing that answer sends them back to the one
        question they cannot answer.

        `None` covers two different situations and the caller must not
        conflate them: a model this catalog has never heard of, and a model
        both brands sell. Only four of 914 models are ambiguous — 200,
        Cabriolet, Continental and Coupe — so this resolves the overwhelming
        majority outright, and `is_known_model` separates the two cases.
        """
        brands = self._brands_by_model.get(model.strip().lower())
        if brands is None or len(brands) != 1:
            return None
        return next(iter(brands))

    async def find(
        self,
        brand: str | None = None,
        model: str | None = None,
        year: int | None = None,
        limit: int = 20,
    ) -> list[VehicleRecord]:
        results = self._records
        if brand:
            results = [r for r in results if r.brand.lower() == brand.lower()]
        if model:
            needle = model.lower()
            results = [r for r in results if needle in r.model.lower()]
        if year:
            results = [r for r in results if r.year == year]
        # Most popular first: when a customer names a model loosely, the
        # mainstream variant is far more likely to be the one they mean.
        return sorted(results, key=lambda r: -(r.popularity or 0))[:limit]

    async def best_match(
        self, brand: str, model: str, year: int | None = None
    ) -> VehicleRecord | None:
        """Closest catalog entry, tolerating an imprecise model name.

        Falls back to the nearest model year rather than returning nothing —
        a 2019 MSRP is a defensible basis for a 2020 valuation, whereas no
        answer forces an unnecessary handoff.
        """
        candidates = self._by_brand_model.get((brand.lower(), model.lower()))

        if not candidates:
            needle = model.lower()
            candidates = [
                r
                for r in self._records
                if r.brand.lower() == brand.lower()
                and (needle in r.model.lower() or r.model.lower() in needle)
            ]

        if not candidates:
            return None

        priced = [r for r in candidates if r.msrp]
        if not priced:
            return candidates[0]

        if year is None:
            return max(priced, key=lambda r: (r.year, r.popularity or 0))

        return min(priced, key=lambda r: (abs(r.year - year), -(r.popularity or 0)))


@lru_cache(maxsize=1)
def get_catalog(path: Path) -> VehicleCatalogService:
    return VehicleCatalogService(path)
