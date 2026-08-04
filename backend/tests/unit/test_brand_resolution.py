"""A model name answered into the brand slot.

Asked "Karva or Renzo?", a customer who knows the car but not the badge says
"S5". The extractor obeys the pending question and files it as the brand, at
0.95 confidence. Observed live: four cooperative turns — "S5", "S5",
"2016 Coupe" — ending in "which vehicle are you asking about?", never reaching
a calendar. The same customer typing "Renzo S5" got one in two turns.

Rejecting the answer would be worse than accepting it, because it returns the
customer to the question they could not answer. These tests pin the third
option: resolve it against the catalog, which knows whose model it is.
"""

from __future__ import annotations

from typing import ClassVar

from app.domain.enums import EntityType
from app.domain.value_objects import ExtractedEntity
from app.graph.nodes import _resolve_model_named_as_brand


class FakeCatalog:
    """The real catalog's shape, with a handful of rows.

    Mirrors the live data: two brands, models that name their brand uniquely,
    and one ("Coupe") that both brands sell — four of the catalog's 914 models
    are genuinely ambiguous.
    """

    BRANDS = frozenset({"Karva", "Renzo"})
    MODELS: ClassVar[dict[str, set[str]]] = {
        "s5": {"Renzo"},
        "4runner": {"Karva"},
        "coupe": {"Karva", "Renzo"},
    }

    @property
    def brands(self) -> frozenset[str]:
        return self.BRANDS

    def is_known_model(self, model: str) -> bool:
        return model.strip().lower() in self.MODELS

    def brand_for_model(self, model: str) -> str | None:
        brands = self.MODELS.get(model.strip().lower())
        if brands is None or len(brands) != 1:
            return None
        return next(iter(brands))


def entity(kind: EntityType, value: str) -> ExtractedEntity:
    return ExtractedEntity(type=kind, value=value, raw_value=value, confidence=0.95)


def slots(entities: tuple[ExtractedEntity, ...]) -> dict[str, str]:
    return {e.type.value: e.value for e in entities}


class TestTheReportedCase:
    def test_a_lone_model_fills_both_slots(self) -> None:
        # The live failure, verbatim: new_vehicle_brand = 'S5' at 0.95.
        result, note = _resolve_model_named_as_brand(
            (entity(EntityType.NEW_VEHICLE_BRAND, "S5"),), FakeCatalog()
        )
        assert slots(result) == {
            "new_vehicle_brand": "Renzo",
            "new_vehicle_model": "S5",
        }
        assert note == "S5 -> Renzo"

    def test_the_customer_who_knew_the_brand_is_untouched(self) -> None:
        # "Renzo S5" was already correct and must stay byte-for-byte the same.
        original = (
            entity(EntityType.NEW_VEHICLE_BRAND, "Renzo"),
            entity(EntityType.NEW_VEHICLE_MODEL, "S5"),
        )
        result, note = _resolve_model_named_as_brand(original, FakeCatalog())
        assert result == original
        assert note is None

    def test_it_works_for_the_trade_in_slots_too(self) -> None:
        result, _ = _resolve_model_named_as_brand(
            (entity(EntityType.OLD_VEHICLE_BRAND, "4Runner"),), FakeCatalog()
        )
        assert slots(result) == {
            "old_vehicle_brand": "Karva",
            "old_vehicle_model": "4Runner",
        }


class TestItDoesNotGuess:
    def test_an_ambiguous_model_keeps_the_brand_unanswered(self) -> None:
        # Both brands sell a Coupe. Filing one would be a guess; the value is
        # still recorded as the model, so the follow-up question gets asked
        # for a real reason rather than from scratch.
        result, note = _resolve_model_named_as_brand(
            (entity(EntityType.NEW_VEHICLE_BRAND, "Coupe"),), FakeCatalog()
        )
        assert slots(result) == {"new_vehicle_model": "Coupe"}
        assert "ambiguous" in (note or "")

    def test_an_unrecognised_value_is_left_alone(self) -> None:
        # Could be a typo, or a marque this dealership does not stock. Either
        # way it is not this function's business to invent a correction.
        original = (entity(EntityType.NEW_VEHICLE_BRAND, "Lamborghini"),)
        result, note = _resolve_model_named_as_brand(original, FakeCatalog())
        assert result == original
        assert note is None

    def test_a_stated_model_is_never_overwritten(self) -> None:
        # Brand misfiled *and* a model already present: repair the brand, but
        # the customer's own model wins.
        result, _ = _resolve_model_named_as_brand(
            (
                entity(EntityType.NEW_VEHICLE_BRAND, "S5"),
                entity(EntityType.NEW_VEHICLE_MODEL, "IS 350"),
            ),
            FakeCatalog(),
        )
        assert slots(result) == {
            "new_vehicle_brand": "Renzo",
            "new_vehicle_model": "IS 350",
        }

    def test_unrelated_slots_pass_through(self) -> None:
        original = (
            entity(EntityType.NEW_VEHICLE_YEAR, "2016"),
            entity(EntityType.NEW_VEHICLE_BODY, "Coupe"),
        )
        result, note = _resolve_model_named_as_brand(original, FakeCatalog())
        assert result == original
        assert note is None

    def test_no_entities_is_not_an_error(self) -> None:
        result, note = _resolve_model_named_as_brand((), FakeCatalog())
        assert result == ()
        assert note is None


class TestAgainstTheRealCatalog:
    """The fake above is only trustworthy if it matches the shipped data."""

    def test_the_shipped_catalog_resolves_the_reported_values(self) -> None:
        from pathlib import Path

        from app.services.execution.catalog import VehicleCatalogService

        catalog = VehicleCatalogService(
            Path(__file__).resolve().parents[3] / "data" / "catalog" / "vehicles.csv"
        )
        assert catalog.size > 0, "catalog did not load; the rest proves nothing"
        assert catalog.brands == frozenset({"Karva", "Renzo"})
        assert catalog.brand_for_model("S5") == "Renzo"
        assert catalog.brand_for_model("4Runner") == "Karva"
        # Ambiguous in the real data, which is why the fake models it.
        assert catalog.brand_for_model("Coupe") is None
        assert catalog.is_known_model("Coupe")


class TestTheNodeActuallyCallsIt:
    """The repair is worthless if `extract_entities` never invokes it.

    Learned the hard way on the calendar bug: `_should_show_calendar` was
    perfectly correct while its caller returned before ever asking. Testing
    the function alone would have passed throughout. This drives the real
    node so removing the call fails here.
    """

    async def test_extract_entities_repairs_a_misfiled_brand(self) -> None:
        from types import SimpleNamespace

        from app.domain.value_objects import TokenUsage
        from app.graph.nodes import build_nodes

        async def extract(text: str, previous_awaiting: str | None = None):
            # What the live service returned for the message "S5" when the
            # assistant had just asked "Karva or Renzo?".
            return (entity(EntityType.NEW_VEHICLE_BRAND, "S5"),), TokenUsage()

        deps = SimpleNamespace(
            understanding=SimpleNamespace(extract_entities=extract),
            catalog=FakeCatalog(),
            router=SimpleNamespace(
                model_for_fast=lambda: "fake-fast", provider_name="fake"
            ),
        )

        node = build_nodes(deps)["extract_entities"]
        result = await node(
            {
                "raw_text": "S5",
                "normalized_text": "S5",
                "trace_id": "trc_test",
                "conversation_id": "conv_test",
                "previous_awaiting": "new_vehicle_brand",
            }
        )

        assert slots(result["entities"]) == {
            "new_vehicle_brand": "Renzo",
            "new_vehicle_model": "S5",
        }
        # The repair is recorded on the span, so a reviewer can see that the
        # brand was inferred rather than stated.
        assert result["spans"][0].attributes["brand_resolved_from_model"] == "S5 -> Renzo"
