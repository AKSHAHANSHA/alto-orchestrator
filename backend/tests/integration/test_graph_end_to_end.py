"""End-to-end orchestration tests.

These run the whole graph against the deterministic mock provider — no API
key, no network, no Qdrant — and assert the behaviours the brief calls out by
name. They are the tests that prove the four layers actually compose.
"""

from __future__ import annotations

import uuid

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.composition.container import Container, RouterFacade
from app.core.settings import Settings
from app.domain.enums import Department, IntentCategory, RoutingTier
from app.graph.builder import compile_graph
from app.graph.state import initial_state
from app.infrastructure.llm.mock_provider import MockProvider
from app.infrastructure.llm.providers import ModelRouter
from app.infrastructure.llm.registry import BudgetGuard
from app.infrastructure.vectorstore.retriever import NullRetriever
from app.services.execution.catalog import VehicleCatalogService
from app.services.execution.runtime import (
    Actuator,
    HumanReviewQueue,
    MemoryService,
    ResponseGenerator,
    ToolRunner,
)
from app.services.understanding.engine import UnderstandingEngine


@pytest.fixture(scope="module")
def settings() -> Settings:
    return Settings(llm_provider="mock", allow_auto_send=False)


@pytest.fixture(scope="module")
def catalog(settings: Settings) -> VehicleCatalogService:
    return VehicleCatalogService(settings.catalog_path)


@pytest.fixture
def container(settings: Settings, catalog: VehicleCatalogService) -> Container:
    router = ModelRouter(MockProvider(), BudgetGuard(settings.llm_daily_budget_usd))
    facade = RouterFacade(router)
    return Container(
        settings=settings,
        router=facade,
        understanding=UnderstandingEngine(router),
        catalog=catalog,
        tools=ToolRunner(catalog),
        retriever=NullRetriever(),
        generator=ResponseGenerator(router),
        actuator=Actuator(),
        human_queue=HumanReviewQueue(),
        memory=MemoryService(),
    )


async def run(container: Container, text: str, conversation_id: str | None = None) -> dict:
    graph = compile_graph(container, checkpointer=MemorySaver())
    conversation_id = conversation_id or f"conv_{uuid.uuid4().hex[:8]}"
    return await graph.ainvoke(
        initial_state(
            conversation_id=conversation_id,
            inquiry_id=f"inq_{uuid.uuid4().hex[:8]}",
            trace_id=f"trc_{uuid.uuid4().hex[:8]}",
            raw_text=text,
            channel="whatsapp",
        ),
        config={"configurable": {"thread_id": conversation_id}},
    )


class TestTheMixedIntentScenario:
    """The headline case from the brief."""

    MESSAGE = (
        "I want to trade in my old Karva SUV and also check financing for a new "
        "Renzo S5 - and can I test drive it Saturday?"
    )

    async def test_all_three_intents_are_discovered(self, container: Container) -> None:
        result = await run(container, self.MESSAGE)
        categories = {i.category for i in result["intents"]}

        assert IntentCategory.TRADE_IN_VALUATION in categories
        assert IntentCategory.FINANCING_EMI in categories
        assert IntentCategory.TEST_DRIVE_BOOKING in categories

    async def test_each_intent_reaches_its_owning_department(
        self, container: Container
    ) -> None:
        result = await run(container, self.MESSAGE)
        by_category = {i.category: i.department for i in result["intents"]}

        assert by_category[IntentCategory.TRADE_IN_VALUATION] is Department.TRADE_IN
        assert by_category[IntentCategory.FINANCING_EMI] is Department.FINANCE
        assert by_category[IntentCategory.TEST_DRIVE_BOOKING] is Department.SALES

    async def test_financing_records_its_dependency_on_the_trade_in(
        self, container: Container
    ) -> None:
        # The part-exchange changes the financeable amount, so quoting the
        # instalment first would produce a number that has to be retracted.
        result = await run(container, self.MESSAGE)
        queue = result["intents"]
        financing = queue.by_category(IntentCategory.FINANCING_EMI)
        trade_in = queue.by_category(IntentCategory.TRADE_IN_VALUATION)

        assert financing is not None and trade_in is not None
        assert trade_in.id in financing.depends_on

    async def test_no_intent_is_lost(self, container: Container) -> None:
        result = await run(container, self.MESSAGE)
        assert len(result["intents"].unresolved) >= 3

    async def test_the_plan_names_a_single_next_action(self, container: Container) -> None:
        result = await run(container, self.MESSAGE)
        plan = result["plan"]
        assert plan is not None
        assert plan.next_action
        assert len(plan.steps) >= 3


class TestVagueMessages:
    """"is this still available?" — the system is not confused, just missing
    one fact, and it asks for exactly that."""

    async def test_a_vague_fragment_produces_a_targeted_question(
        self, container: Container
    ) -> None:
        result = await run(container, "is this still available?")

        draft = result.get("draft")
        assert draft is not None
        assert result.get("awaiting") is not None
        # Not a generic "could you rephrase?" — a specific request.
        assert "which vehicle" in draft.en.lower()

    async def test_the_conversation_pauses_rather_than_guessing(
        self, container: Container
    ) -> None:
        result = await run(container, "is this still available?")
        assert result["awaiting"] == "vehicle_reference"


class TestArabicAndBilingual:
    async def test_arabic_message_is_understood_and_answered_bilingually(
        self, container: Container
    ) -> None:
        result = await run(container, "هل ما زالت متوفرة؟")

        profile = result["language"]
        assert profile.primary.value == "ar"
        assert profile.requires_bilingual_reply

        draft = result.get("draft")
        assert draft is not None and draft.is_bilingual

    async def test_a_single_arabic_word_triggers_a_bilingual_reply(
        self, container: Container
    ) -> None:
        result = await run(container, "Is the Renzo S5 متوفرة?")
        assert result["language"].requires_bilingual_reply

    async def test_arabic_digits_are_normalised(self, container: Container) -> None:
        result = await run(container, "كم القسط الشهري لسيارة رينزو ٢٠٢٠؟")
        assert "2020" in result["normalized_text"]


class TestRoutingAndEscalation:
    async def test_a_complaint_always_reaches_a_person(self, container: Container) -> None:
        result = await run(
            container, "This is unacceptable, I have been waiting for weeks. Refund me."
        )
        routing = result["routing"]
        assert routing.tier is RoutingTier.HUMAN
        assert routing.overrides_applied
        assert result["escalated"]

    async def test_escalation_carries_a_reason(self, container: Container) -> None:
        await run(container, "Terrible service, get me a manager immediately")
        open_items = await container.human_queue.list_open()
        assert open_items
        assert open_items[0].reason is not None
        assert open_items[0].routing is not None

    async def test_nothing_is_actuated_while_awaiting_review(
        self, container: Container
    ) -> None:
        # The reviewer decides what the customer sees.
        result = await run(container, "This is terrible, I want a refund")
        assert result.get("actions", ()) == ()


class TestExplainability:
    async def test_every_stage_emits_a_span(self, container: Container) -> None:
        result = await run(container, "I want financing for a Renzo S5")
        nodes = {s.node for s in result["spans"]}

        for expected in ("normalize", "detect_language", "discover_intents", "plan",
                         "score_confidence", "decide", "persist_memory"):
            assert expected in nodes, f"no span for {expected}"

    async def test_spans_are_tagged_with_their_cognitive_layer(
        self, container: Container
    ) -> None:
        result = await run(container, "I want financing for a Renzo S5")
        layers = {s.layer.value for s in result["spans"]}
        assert {"understanding", "planning", "decision"} <= layers

    async def test_the_confidence_breakdown_is_complete(self, container: Container) -> None:
        result = await run(container, "I want financing for a Renzo S5")
        vector = result["confidence"]

        assert set(vector.as_dict()) == {
            "language", "intent", "entity", "retrieval", "risk", "policy"
        }
        assert 0 <= vector.decision_score <= 100

    async def test_the_routing_decision_explains_itself(self, container: Container) -> None:
        result = await run(container, "I want financing for a Renzo S5")
        routing = result["routing"]
        assert routing.rule_id
        assert len(routing.rationale) > 20

    async def test_latency_is_recorded_per_node(self, container: Container) -> None:
        result = await run(container, "Do you have a Karva SUV?")
        assert all(s.latency_ms >= 0 for s in result["spans"])


class TestDeterminism:
    async def test_the_same_message_produces_the_same_routing(
        self, container: Container
    ) -> None:
        # With a deterministic provider, the whole pipeline is reproducible.
        first = await run(container, "I want to check financing for a Renzo S5")
        second = await run(container, "I want to check financing for a Renzo S5")

        assert first["routing"].tier is second["routing"].tier
        assert first["routing"].rule_id == second["routing"].rule_id
        assert first["confidence"].decision_score == second["confidence"].decision_score

    async def test_a_single_intent_message_is_just_a_queue_of_one(
        self, container: Container
    ) -> None:
        result = await run(container, "Can I book a test drive on Saturday?")
        assert len(result["intents"].unresolved) == 1


class TestMultiTurnResume:
    """A second message on the same conversation must not crash.

    The bug this pins: LangGraph's checkpointer round-trips state through a
    serializer that turns tuples into lists. The reducer that then merges the
    next turn's writes had used `operator.add`, so it tried `list + tuple` on
    turn two and Python refused. The fix — a reducer that accepts both — is
    the sort of thing a well-meaning refactor could quietly undo, which is
    why the guarantee needs a test.
    """

    async def test_two_turns_on_the_same_conversation_do_not_crash(
        self, container: Container
    ) -> None:
        conversation_id = "conv_multi_turn"
        first = await run(container, "I want a Renzo S5", conversation_id)
        assert first.get("intents") is not None

        # Turn two on the same conversation: the reducer must merge the new
        # deltas onto whatever shape the checkpointer stored, not just the
        # shape it received a moment ago.
        second = await run(container, "What is the monthly instalment?", conversation_id)
        assert second.get("intents") is not None
        assert not any(
            s.error for s in second.get("spans", [])
        ), "no node should have errored on the second turn"

    async def test_answering_a_clarification_advances_the_conversation(
        self, container: Container
    ) -> None:
        # The bug this pins: the customer answers "which vehicle?" with a
        # brand, but the intent's required slot is literally
        # `vehicle_reference`, so the planner keeps asking the same question
        # forever. Naming a vehicle should count as identifying it.
        conversation_id = "conv_clarify_answer"

        first = await run(container, "is this still available?", conversation_id)
        assert first["awaiting"] == "vehicle_reference"

        second = await run(container, "Renzo S5", conversation_id)
        assert second["awaiting"] != "vehicle_reference", (
            "answering a clarification with a vehicle brand should satisfy the slot; "
            "the planner treated it as an unfilled reference and asked again"
        )

    async def test_a_clarifying_turn_has_already_looked_the_vehicle_up(
        self, container: Container
    ) -> None:
        # The graph used to branch to `clarify` straight off the plan, before
        # retrieval or tools had run — so the node asking "which day?" had an
        # empty `tool_results` and could not have mentioned the car even if it
        # wanted to. Tools now run first, on every path.
        result = await run(
            container, "Can I test drive the Renzo S5?", "conv_clarify_has_specs"
        )

        assert result["awaiting"] == "preferred_date"
        assert result["tool_results"], (
            "clarify ran before the tools; a clarifying question can never "
            "carry vehicle specifics while that is true"
        )
        assert "catalog_similar" in result["tool_results"]
