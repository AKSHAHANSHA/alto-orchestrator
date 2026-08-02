"""API integration tests.

Exercised against the real application with the deterministic mock provider,
so these assert the actual wire contract the frontend depends on.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
async def client() -> AsyncClient:
    app = create_app()
    async with (
        AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as http_client,
        app.router.lifespan_context(app),
    ):
        yield http_client


class TestOps:
    async def test_health(self, client: AsyncClient) -> None:
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    async def test_ready_reports_configuration(self, client: AsyncClient) -> None:
        body = (await client.get("/ready")).json()
        assert body["status"] == "ready"
        assert body["catalog_size"] > 11_000, "the full catalog should be loaded"


class TestInquiries:
    async def test_mixed_intent_message_returns_every_intent(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/inquiries",
            json={
                "message": (
                    "I want to trade in my old Karva SUV and also check financing "
                    "for a new Renzo S5 - and can I test drive it Saturday?"
                ),
                "channel": "whatsapp",
            },
        )
        assert response.status_code == 200
        body = response.json()

        categories = {i["category"] for i in body["intents"]}
        assert {"trade_in_valuation", "financing_emi", "test_drive_booking"} <= categories

        departments = {i["department"] for i in body["intents"]}
        assert {"trade_in", "finance", "sales"} <= departments

    async def test_the_response_explains_every_decision(self, client: AsyncClient) -> None:
        body = (
            await client.post(
                "/api/v1/inquiries", json={"message": "I need financing for a Renzo S5"}
            )
        ).json()

        confidence = body["confidence"]
        assert set(confidence) >= {
            "language", "intent", "entity", "retrieval", "risk", "policy",
            "decision_score", "weakest_signal",
        }

        routing = body["routing"]
        assert routing["rule_id"] and routing["rationale"]

        assert body["spans"], "every stage must be traceable"
        assert body["total_latency_ms"] >= 0

    async def test_a_vague_message_asks_a_targeted_question(
        self, client: AsyncClient
    ) -> None:
        body = (
            await client.post("/api/v1/inquiries", json={"message": "is this still available?"})
        ).json()

        assert body["awaiting"] == "vehicle_reference"
        assert "which vehicle" in body["reply"]["en"].lower()

    async def test_arabic_message_gets_a_bilingual_reply(self, client: AsyncClient) -> None:
        body = (
            await client.post("/api/v1/inquiries", json={"message": "هل ما زالت متوفرة؟"})
        ).json()

        assert body["language"]["primary"] == "ar"
        assert body["reply"]["is_bilingual"]
        assert body["reply"]["ar"]

    async def test_a_complaint_escalates(self, client: AsyncClient) -> None:
        body = (
            await client.post(
                "/api/v1/inquiries",
                json={"message": "This is unacceptable. I want a refund immediately."},
            )
        ).json()

        assert body["escalated"]
        assert body["routing"]["tier"] == "human"
        assert body["routing"]["overrides_applied"]

    async def test_empty_message_is_rejected(self, client: AsyncClient) -> None:
        assert (await client.post("/api/v1/inquiries", json={"message": ""})).status_code == 422


class TestTools:
    async def test_emi_endpoint_returns_a_full_quote(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/tools/emi",
            json={"vehicle_price": 150000, "tenure_months": 48, "salary_transfer": True},
        )
        assert response.status_code == 200
        quote = response.json()

        assert quote["monthly_instalment"] > 0
        assert quote["down_payment_ratio"] >= 0.20, "regulatory minimum"
        assert quote["tenure_months"] == 48
        assert "not a finance offer" in quote["disclaimer_en"]

    async def test_emi_rejects_an_impossible_request(self, client: AsyncClient) -> None:
        # Refusing beats quoting terms no bank may legally offer.
        response = await client.post(
            "/api/v1/tools/emi", json={"vehicle_price": 5_000_000}
        )
        assert response.status_code == 422

    async def test_trade_in_returns_a_range_not_a_number(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/tools/trade-in",
            json={"brand": "Karva", "model": "Sedan", "year": 2018, "mileage_km": 90000},
        )
        if response.status_code == 200:
            estimate = response.json()
            assert estimate["estimate_low"] < estimate["estimate_high"]
            assert "inspection" in estimate["disclaimer_en"].lower()
        else:
            # Declining is a valid, designed outcome when the model is out of
            # its depth — but it must say why.
            assert response.status_code == 422
            assert "appraisal" in str(response.json()).lower()


class TestCatalog:
    async def test_catalog_filters_by_brand(self, client: AsyncClient) -> None:
        rows = (await client.get("/api/v1/catalog/vehicles?brand=Renzo&limit=5")).json()
        assert rows
        assert all(r["brand"] == "Renzo" for r in rows)

    async def test_only_the_two_alto_brands_exist(self, client: AsyncClient) -> None:
        rows = (await client.get("/api/v1/catalog/vehicles?limit=200")).json()
        assert {r["brand"] for r in rows} <= {"Karva", "Renzo"}


class TestAdmin:
    async def test_human_queue_lists_escalations(self, client: AsyncClient) -> None:
        await client.post(
            "/api/v1/inquiries",
            json={"message": "Terrible service, get me a manager right now"},
        )
        items = (await client.get("/api/v1/admin/human-queue")).json()

        assert items
        assert items[0]["reason"]
        assert items[0]["routing"]["rationale"]
        assert items[0]["confidence"]["decision_score"] >= 0

    async def test_dismissing_a_review_closes_it_without_delivering(
        self, client: AsyncClient
    ) -> None:
        # Complaints escalate before the graph would draft anything, so the
        # only defensible way to close them via `approved` would be to invent
        # a reply — the API refuses. `rejected` is the right verb here.
        await client.post(
            "/api/v1/inquiries", json={"message": "This is unacceptable, refund me"}
        )
        items = (await client.get("/api/v1/admin/human-queue")).json()
        item_id = items[0]["id"]

        response = await client.post(
            f"/api/v1/admin/human-queue/{item_id}/resolve",
            json={"outcome": "rejected", "reviewer": "coordinator@alto"},
        )
        assert response.status_code == 200
        assert response.json()["outcome"] == "rejected"

        # Resolving twice is a conflict, not a silent no-op.
        again = await client.post(
            f"/api/v1/admin/human-queue/{item_id}/resolve",
            json={"outcome": "rejected", "reviewer": "coordinator@alto"},
        )
        assert again.status_code == 409

    async def test_approving_without_any_text_is_a_client_error(
        self, client: AsyncClient
    ) -> None:
        # A "reply approved for delivery" that has neither a drafted nor an
        # operator-written text is nonsensical, and used to slide through as
        # a successful no-op. It must not.
        await client.post(
            "/api/v1/inquiries", json={"message": "This is unacceptable, refund me"}
        )
        items = (await client.get("/api/v1/admin/human-queue")).json()
        item_id = items[0]["id"]
        assert items[0]["draft"] is None, "complaints have no draft to approve"

        response = await client.post(
            f"/api/v1/admin/human-queue/{item_id}/resolve",
            json={"outcome": "approved", "reviewer": "coordinator@alto"},
        )
        assert response.status_code == 422

    async def test_edited_delivery_reaches_the_customer_transcript(
        self, client: AsyncClient
    ) -> None:
        # The whole point of the review UI: what the reviewer sends must
        # land in the customer's transcript.
        submission = await client.post(
            "/api/v1/inquiries",
            json={"message": "Terrible service, get me a manager immediately"},
        )
        conversation_id = submission.json()["conversation_id"]

        items = (await client.get("/api/v1/admin/human-queue")).json()
        item_id = items[0]["id"]

        reply_text = "A senior colleague will call you within the hour to sort this."
        response = await client.post(
            f"/api/v1/admin/human-queue/{item_id}/resolve",
            json={
                "outcome": "edited",
                "reviewer": "coordinator@alto",
                "final_text": reply_text,
            },
        )
        assert response.status_code == 200

        conversation = (
            await client.get(f"/api/v1/conversations/{conversation_id}")
        ).json()
        assistant_lines = [
            t["text"] for t in conversation["transcript"] if t["role"] == "assistant"
        ]
        assert reply_text in assistant_lines
        assert conversation["human_handled"] is True

    async def test_reassign_requires_a_target_department(
        self, client: AsyncClient
    ) -> None:
        await client.post(
            "/api/v1/inquiries", json={"message": "This is unacceptable, refund me"}
        )
        items = (await client.get("/api/v1/admin/human-queue")).json()
        item_id = items[0]["id"]

        # Without reassign_to the reviewer is closing without actually
        # reassigning; the API used to accept this silently.
        missing_target = await client.post(
            f"/api/v1/admin/human-queue/{item_id}/resolve",
            json={"outcome": "reassigned", "reviewer": "coordinator@alto"},
        )
        assert missing_target.status_code == 422

        ok = await client.post(
            f"/api/v1/admin/human-queue/{item_id}/resolve",
            json={
                "outcome": "reassigned",
                "reviewer": "coordinator@alto",
                "reassign_to": "customer_relations",
            },
        )
        assert ok.status_code == 200
        assert ok.json()["department"] == "customer_relations"

    async def test_a_customer_message_after_handoff_does_not_re_engage_the_graph(
        self, client: AsyncClient
    ) -> None:
        # Once a person has taken over, the assistant stays out. Customer
        # messages get recorded in the transcript for the reviewer to see;
        # the graph does not run.
        first = await client.post(
            "/api/v1/inquiries", json={"message": "Terrible service, escalate this"}
        )
        conversation_id = first.json()["conversation_id"]

        items = (await client.get("/api/v1/admin/human-queue")).json()
        await client.post(
            f"/api/v1/admin/human-queue/{items[0]['id']}/resolve",
            json={
                "outcome": "edited",
                "reviewer": "coordinator@alto",
                "final_text": "We are on it.",
            },
        )

        follow_up = await client.post(
            "/api/v1/inquiries",
            json={
                "message": "Any update?",
                "conversation_id": conversation_id,
            },
        )
        body = follow_up.json()
        assert body["awaiting"] == "human_response"
        assert body["escalated"] is True

        conversation = (
            await client.get(f"/api/v1/conversations/{conversation_id}")
        ).json()
        customer_lines = [
            t["text"] for t in conversation["transcript"] if t["role"] == "customer"
        ]
        assert "Any update?" in customer_lines

    async def test_operator_can_reply_live_after_handoff(
        self, client: AsyncClient
    ) -> None:
        first = await client.post(
            "/api/v1/inquiries", json={"message": "This is unacceptable"}
        )
        conversation_id = first.json()["conversation_id"]
        items = (await client.get("/api/v1/admin/human-queue")).json()
        await client.post(
            f"/api/v1/admin/human-queue/{items[0]['id']}/resolve",
            json={
                "outcome": "edited",
                "reviewer": "coordinator@alto",
                "final_text": "Escalating this now.",
            },
        )

        follow_up = await client.post(
            f"/api/v1/admin/conversations/{conversation_id}/reply",
            json={"text": "The head of sales will call you in 10 minutes.",
                  "reviewer": "coordinator@alto"},
        )
        assert follow_up.status_code == 200

        conversation = (
            await client.get(f"/api/v1/conversations/{conversation_id}")
        ).json()
        assistant_lines = [
            t["text"] for t in conversation["transcript"] if t["role"] == "assistant"
        ]
        assert "The head of sales will call you in 10 minutes." in assistant_lines

    async def test_metrics_aggregate_cost_and_latency(self, client: AsyncClient) -> None:
        await client.post("/api/v1/inquiries", json={"message": "Do you have a Karva SUV?"})
        metrics = (await client.get("/api/v1/admin/metrics")).json()

        assert metrics["conversations"] >= 1
        assert metrics["by_node"]
        assert metrics["by_layer"]
        # Provider is whatever the environment configured; both real vendors
        # and the mock have the same DTO surface.
        assert metrics["provider"] in {"mock", "openai", "anthropic"}

    async def test_trace_is_retrievable_per_conversation(self, client: AsyncClient) -> None:
        # Whatever the classification, understanding and planning layers must
        # both fire — those are on the required path for every graph run.
        # Decision is contingent on the plan not stopping at clarify, and
        # real LLM extraction is enough of a coin-flip on short prompts that
        # we don't require it here.
        body = (
            await client.post(
                "/api/v1/inquiries", json={"message": "How much is the Renzo S5?"}
            )
        ).json()

        trace = (
            await client.get(f"/api/v1/conversations/{body['conversation_id']}/trace")
        ).json()

        assert trace["spans"]
        assert {s["layer"] for s in trace["spans"]} >= {"understanding", "planning"}

    async def test_a_vague_availability_question_asks_for_the_vehicle(
        self, client: AsyncClient
    ) -> None:
        # "is this still available?" references a vehicle without naming one.
        # The planner should stop and ask "which vehicle?" rather than route.
        body = (
            await client.post(
                "/api/v1/inquiries", json={"message": "is this still available?"}
            )
        ).json()

        assert body["awaiting"] == "vehicle_reference"
        assert body["routing"] is None

    async def test_unknown_trace_returns_404(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/conversations/conv_nonexistent/trace")
        assert response.status_code == 404


class TestMultiIntentDoesNotCollapse:
    """The three-intent scenario from the brief, followed through a booking.

    Both bugs pinned here shipped together and produced the same symptom from
    the customer's side: the platform answered one intent and behaved as if
    the conversation were over.
    """

    MESSAGE = (
        "I want to trade in my old Karva SUV and also check financing for a "
        "new Renzo S5 — and can I test drive it Saturday?"
    )

    async def test_the_calendar_does_not_hijack_a_different_question(
        self, client: AsyncClient
    ) -> None:
        # The graph may be asking about the trade-in while the test drive is
        # still the highest-priority intent. Showing the picker then stapled
        # "pick a slot below" onto "which Karva model is it?", and overwrote
        # `awaiting` so the next turn misread the customer's answer.
        body = (
            await client.post(
                "/api/v1/inquiries",
                json={"message": self.MESSAGE, "channel": "whatsapp"},
            )
        ).json()

        reply = body["reply"]["en"]
        awaiting = body["awaiting"]

        if awaiting != "test_drive_slot":
            assert "calendar below" not in reply, (
                "the calendar call-to-action was appended to a reply that was "
                f"asking about {awaiting!r}"
            )

        # Whatever happened, the reply must not congratulate the customer for
        # a choice they have not made.
        assert not reply.startswith("Perfect")

    async def test_booking_a_slot_asks_about_what_is_still_open(
        self, client: AsyncClient
    ) -> None:
        # The bug: the confirmation was a hardcoded string that never touched
        # the intent queue, so the trade-in and financing requests were
        # silently abandoned the moment a slot was booked.
        conversation_id = "conv_multi_intent_booking"
        await client.post(
            "/api/v1/inquiries",
            json={
                "message": self.MESSAGE,
                "channel": "whatsapp",
                "conversation_id": conversation_id,
            },
        )

        slots = (await client.get("/api/v1/appointments/slots?days=7")).json()["slots"]
        assert slots, "no bookable slots were offered"

        booked = await client.post(
            "/api/v1/appointments/book",
            json={
                "conversation_id": conversation_id,
                "slot_id": slots[0]["slot_id"],
                "vehicle": "Renzo S5",
            },
        )
        assert booked.status_code == 200
        confirmation = booked.json()["confirmation"]

        assert "Booked!" in confirmation
        assert "?" in confirmation, (
            "the booking confirmation ended the conversation with the trade-in "
            "and financing requests still unanswered:\n" + confirmation
        )

    async def test_the_test_drive_is_resolved_and_the_rest_are_not(
        self, client: AsyncClient
    ) -> None:
        conversation_id = "conv_booking_resolves_one_intent"
        await client.post(
            "/api/v1/inquiries",
            json={
                "message": self.MESSAGE,
                "channel": "whatsapp",
                "conversation_id": conversation_id,
            },
        )
        slots = (await client.get("/api/v1/appointments/slots?days=7")).json()["slots"]
        await client.post(
            "/api/v1/appointments/book",
            json={
                "conversation_id": conversation_id,
                "slot_id": slots[0]["slot_id"],
                "vehicle": "Renzo S5",
            },
        )

        conversation = (
            await client.get(f"/api/v1/conversations/{conversation_id}")
        ).json()
        # The endpoint exposes only what is still outstanding, which is
        # exactly the question here: the booked intent should have left the
        # queue and the other two should not have.
        open_categories = {i["category"] for i in conversation["open_intents"]}

        assert "test_drive_booking" not in open_categories, (
            "the slot was booked but the test-drive intent is still open"
        )
        assert open_categories, (
            "booking a slot emptied the whole queue — the trade-in and "
            "financing requests were resolved without ever being answered"
        )
