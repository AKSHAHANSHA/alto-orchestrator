"""When the structured catalog lookup runs.

The lookup is what lets the platform say honestly "we don't stock that" —
and, just as importantly, stops it saying so about a car we *do* stock.
Which turns trigger it is therefore a correctness question, not a
performance one.
"""

from __future__ import annotations

from app.domain.entities import ConversationState, Intent, IntentQueue
from app.domain.enums import EntityType, IntentCategory
from app.domain.value_objects import ExtractedEntity
from app.infrastructure.persistence.catalog_repository import CatalogLookupResult
from app.services.execution.runtime import ToolRunner


class StubLookup:
    """Records what it was asked, so a test can assert it was asked at all."""

    def __init__(self) -> None:
        self.calls: list[tuple[str | None, str | None, int | None]] = []

    async def lookup(
        self, brand: str | None, model: str | None, year: int | None = None
    ) -> CatalogLookupResult:
        self.calls.append((brand, model, year))
        return CatalogLookupResult(verdict="not_stocked")


class StubCatalog:
    """The legacy vector-matching catalog. Not under test here."""

    async def search(self, *args: object, **kwargs: object) -> tuple[()]:
        return ()

    def match(self, *args: object, **kwargs: object) -> tuple[()]:
        return ()


def entity(kind: EntityType, value: str) -> ExtractedEntity:
    return ExtractedEntity(type=kind, value=value, raw_value=value, confidence=0.95)


def conversation_with(
    category: IntentCategory, *entities: ExtractedEntity
) -> ConversationState:
    return ConversationState(
        conversation_id="conv_gating",
        intents=IntentQueue(intents=(Intent(category=category, confidence=0.9),)),
        entities=entities,
    )


class TestCatalogLookupGating:
    async def test_an_unclear_intent_still_looks_a_named_vehicle_up(self) -> None:
        # The bug: `unclear_needs_clarification` was missing from the intent
        # list that triggered the lookup — and a one-word reply like "Renzo"
        # is exactly what classifies as unclear. With brand and model sitting
        # filled in the conversation, the lookup was skipped, and the
        # generator told customers "I do not see a Renzo S5 in our vehicle
        # records". We stock several.
        stub = StubLookup()
        runner = ToolRunner(StubCatalog(), stub)

        await runner.run_for(
            conversation_with(
                IntentCategory.UNCLEAR_NEEDS_CLARIFICATION,
                entity(EntityType.NEW_VEHICLE_BRAND, "Renzo"),
                entity(EntityType.NEW_VEHICLE_MODEL, "S5"),
            )
        )

        assert stub.calls == [("Renzo", "S5", None)]

    async def test_small_talk_naming_a_vehicle_is_still_looked_up(self) -> None:
        # Gating on the vehicle rather than the category means this follows
        # for free, and it is the behaviour we want: the customer named a car.
        stub = StubLookup()
        runner = ToolRunner(StubCatalog(), stub)

        await runner.run_for(
            conversation_with(
                IntentCategory.SMALL_TALK,
                entity(EntityType.NEW_VEHICLE_BRAND, "Karva"),
                entity(EntityType.NEW_VEHICLE_MODEL, "Samurai"),
            )
        )

        assert stub.calls == [("Karva", "Samurai", None)]

    async def test_no_vehicle_named_means_no_query(self) -> None:
        # Dropping the category gate must not turn this into a database
        # round-trip on every greeting.
        stub = StubLookup()
        runner = ToolRunner(StubCatalog(), stub)

        await runner.run_for(conversation_with(IntentCategory.SMALL_TALK))

        assert stub.calls == []

    async def test_a_brand_without_a_model_is_not_enough(self) -> None:
        stub = StubLookup()
        runner = ToolRunner(StubCatalog(), stub)

        await runner.run_for(
            conversation_with(
                IntentCategory.UNCLEAR_NEEDS_CLARIFICATION,
                entity(EntityType.NEW_VEHICLE_BRAND, "Renzo"),
            )
        )

        assert stub.calls == []

    async def test_the_trade_in_vehicle_alone_triggers_a_lookup(self) -> None:
        stub = StubLookup()
        runner = ToolRunner(StubCatalog(), stub)

        await runner.run_for(
            conversation_with(
                IntentCategory.UNCLEAR_NEEDS_CLARIFICATION,
                entity(EntityType.OLD_VEHICLE_BRAND, "Karva"),
                entity(EntityType.OLD_VEHICLE_MODEL, "4Runner"),
            )
        )

        assert stub.calls == [("Karva", "4Runner", None)]
