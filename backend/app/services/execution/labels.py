"""Customer-facing names for internal categories.

Both the clarifier and the generator put the list of open requests into a
prompt, and both were rendering it as `category.value.replace("_", " ")`.
That puts internal vocabulary one echo away from a buyer — and it got there:
a drafted reply came back reading "still need: unclear needs clarification".

Shared rather than duplicated because the two prompts describe the same
queue, and a customer should not see it named two different ways depending
on which node happened to write the reply.
"""

from __future__ import annotations

from app.domain.enums import IntentCategory

INTENT_LABELS: dict[IntentCategory, str] = {
    IntentCategory.TEST_DRIVE_BOOKING: "the test drive",
    IntentCategory.FINANCING_EMI: "financing",
    IntentCategory.TRADE_IN_VALUATION: "the trade-in",
    IntentCategory.VEHICLE_AVAILABILITY_INFO: "availability",
    IntentCategory.PRICING_OFFERS: "pricing",
    IntentCategory.SERVICE_AFTERSALES: "service",
    IntentCategory.COMPLAINT_ESCALATION: "the complaint",
    IntentCategory.GENERAL_INFO: "the general enquiry",
    # Deliberately not "unclear needs clarification". The category is a note
    # to ourselves that we do not yet know which vehicle they mean; phrased
    # for a customer it is simply the vehicle.
    IntentCategory.UNCLEAR_NEEDS_CLARIFICATION: "which vehicle they mean",
    IntentCategory.SMALL_TALK: "the greeting",
}


def intent_label(category: IntentCategory) -> str:
    """A phrase a customer would recognise, never the raw enum value."""
    return INTENT_LABELS.get(category, category.value.replace("_", " "))
