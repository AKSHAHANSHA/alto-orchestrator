"""SQLAlchemy ORM models.

Currently only the vehicle catalog lives here. Other domain entities are held
in-memory in the current build; when they move to Postgres they will join this
module. The important discipline: `domain/` never imports from here — these
are infrastructure adapters, not the domain model itself.
"""

from __future__ import annotations

from sqlalchemy import Column, Float, Index, Integer, String
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base for every ORM class in the platform."""


class VehicleRow(Base):
    """One row from the vehicle catalog.

    Loaded from `data/catalog/vehicles.csv` by the ingestion worker. Powers
    exact and near-match lookups from the ``CatalogLookupService``, which is
    the right tool for questions like "do you have a Renzo GX 470?" — those
    are structured queries, not semantic ones, and vector similarity would
    give a confidently wrong answer.
    """

    __tablename__ = "vehicles"

    # Composite natural key expressed as an internal id.
    id = Column(String(64), primary_key=True)

    brand = Column(String(32), nullable=False, index=True)
    model = Column(String(64), nullable=False)
    # Lowercase model for case-insensitive comparisons without a functional
    # index on every backend. Populated at load time.
    model_normalized = Column(String(64), nullable=False, index=True)
    year = Column(Integer, nullable=False, index=True)

    body_style = Column(String(48), nullable=True)
    market_category = Column(String(128), nullable=True)
    engine_hp = Column(Float, nullable=True)
    engine_cylinders = Column(Float, nullable=True)
    engine_fuel_type = Column(String(64), nullable=True)
    transmission = Column(String(32), nullable=True)
    driven_wheels = Column(String(32), nullable=True)
    doors = Column(Integer, nullable=True)
    highway_mpg = Column(Integer, nullable=True)
    city_mpg = Column(Integer, nullable=True)
    msrp = Column(Float, nullable=True)
    popularity = Column(Integer, nullable=True)

    __table_args__ = (
        # The most common lookup is by (brand, model, year), so a compound
        # index keeps it cheap. `model_normalized` is what the tool actually
        # queries by, so it's the one that goes into the index.
        Index("ix_vehicles_brand_model_year", "brand", "model_normalized", "year"),
    )
