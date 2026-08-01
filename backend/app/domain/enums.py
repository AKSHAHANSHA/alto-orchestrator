"""Closed vocabularies for the domain.

Every enum here is a business fact, not an implementation detail. They are
strings rather than integers so that persisted rows, JSON payloads and log
lines stay readable without a lookup table.
"""

from __future__ import annotations

from enum import StrEnum


class Channel(StrEnum):
    """Where an inquiry arrived from.

    Carried through the whole pipeline because it constrains the response:
    WhatsApp has length and formatting limits that a web form does not.
    """

    WHATSAPP = "whatsapp"
    WEB_FORM = "web_form"
    WALK_IN = "walk_in"


class Language(StrEnum):
    ARABIC = "ar"
    ENGLISH = "en"


class CognitiveLayer(StrEnum):
    """The four layers of the coordinator's thinking.

    Every span is tagged with the layer that produced it, which is what lets
    the admin UI show where time and money actually go.
    """

    UNDERSTANDING = "understanding"
    PLANNING = "planning"
    DECISION = "decision"
    EXECUTION = "execution"


class IntentCategory(StrEnum):
    """What the customer wants.

    ``UNCLEAR_NEEDS_CLARIFICATION`` is a first-class outcome, not a failure
    mode: it is how "is this still available?" is handled honestly instead of
    being forced into a category the message does not support.
    """

    TEST_DRIVE_BOOKING = "test_drive_booking"
    FINANCING_EMI = "financing_emi"
    TRADE_IN_VALUATION = "trade_in_valuation"
    VEHICLE_AVAILABILITY_INFO = "vehicle_availability_info"
    PRICING_OFFERS = "pricing_offers"
    SERVICE_AFTERSALES = "service_aftersales"
    COMPLAINT_ESCALATION = "complaint_escalation"
    # Hours, location, general enquiries about the dealership itself.
    # No vehicle required — asking "when are you open?" doesn't need a
    # brand+model to answer.
    GENERAL_INFO = "general_info"
    # Greetings, thanks, goodbyes. Acknowledged warmly, never escalated,
    # never asked for a vehicle.
    SMALL_TALK = "small_talk"
    UNCLEAR_NEEDS_CLARIFICATION = "unclear_needs_clarification"


class IntentStatus(StrEnum):
    """Lifecycle of a single intent.

    ``RESOLVED`` and ``ESCALATED`` are the only terminal states. Anything else
    keeps the intent in the queue, which is what makes "never lose an
    unresolved intent" checkable rather than aspirational.
    """

    PENDING = "pending"
    WAITING_INFORMATION = "waiting_information"
    ROUTED = "routed"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    RESOLVED = "resolved"
    ESCALATED = "escalated"

    @property
    def is_terminal(self) -> bool:
        return self in {IntentStatus.RESOLVED, IntentStatus.ESCALATED}


class Department(StrEnum):
    """Who owns the work. Assigned by business rules, never by the model."""

    SALES = "sales"
    FINANCE = "finance"
    TRADE_IN = "trade_in"
    SERVICE = "service"
    CUSTOMER_RELATIONS = "customer_relations"


class RoutingTier(StrEnum):
    """Outcome of the decision layer."""

    AUTO = "auto"
    PREMIUM = "premium"
    HUMAN = "human"


class ModelTier(StrEnum):
    """Which class of model to call. Maps to a concrete model per provider."""

    FAST = "fast"
    PREMIUM = "premium"


class Polarity(StrEnum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class Urgency(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ConfidenceSignal(StrEnum):
    """The six independent signals behind a routing decision.

    Kept separate on purpose: a system that collapses these into one number
    cannot explain which one dragged a decision down.
    """

    LANGUAGE = "language"
    INTENT = "intent"
    ENTITY = "entity"
    RETRIEVAL = "retrieval"
    RISK = "risk"
    POLICY = "policy"


class EntityType(StrEnum):
    """Slots the pipeline extracts and fills.

    Prefixed by subject (``new_``/``old_``) because a single message routinely
    references two vehicles — the one being traded in and the one being
    bought — and conflating them produces a wrong quote.
    """

    NEW_VEHICLE_BRAND = "new_vehicle_brand"
    NEW_VEHICLE_MODEL = "new_vehicle_model"
    NEW_VEHICLE_YEAR = "new_vehicle_year"
    NEW_VEHICLE_BODY = "new_vehicle_body"

    OLD_VEHICLE_BRAND = "old_vehicle_brand"
    OLD_VEHICLE_MODEL = "old_vehicle_model"
    OLD_VEHICLE_YEAR = "old_vehicle_year"
    OLD_VEHICLE_BODY = "old_vehicle_body"
    OLD_VEHICLE_MILEAGE = "old_vehicle_mileage"
    OLD_VEHICLE_CONDITION = "old_vehicle_condition"

    BUDGET = "budget"
    DOWN_PAYMENT = "down_payment"
    TENURE_MONTHS = "tenure_months"
    MONTHLY_INCOME = "monthly_income"
    SALARY_TRANSFER = "salary_transfer"

    PREFERRED_DATE = "preferred_date"
    PREFERRED_TIME = "preferred_time"
    VEHICLE_REFERENCE = "vehicle_reference"

    CUSTOMER_NAME = "customer_name"
    CONTACT_PHONE = "contact_phone"
    CONTACT_EMAIL = "contact_email"


class ActionType(StrEnum):
    """Side effects the execution layer performs.

    Read-only actions are safe to run automatically; the rest mutate state a
    customer can see and are gated behind confidence or human approval.
    """

    CRM_UPSERT = "crm_upsert"
    CREATE_LEAD = "create_lead"
    BOOK_TEST_DRIVE = "book_test_drive"
    NOTIFY_DEPARTMENT = "notify_department"
    SEND_EMAIL = "send_email"

    @property
    def is_sensitive(self) -> bool:
        """Sensitive actions are externally visible and hard to walk back."""
        return self in {
            ActionType.BOOK_TEST_DRIVE,
            ActionType.SEND_EMAIL,
            ActionType.NOTIFY_DEPARTMENT,
        }


class ActionStatus(StrEnum):
    PENDING = "pending"
    EXECUTED = "executed"
    FAILED = "failed"
    SKIPPED = "skipped"
    AWAITING_APPROVAL = "awaiting_approval"


class GroundingVerdict(StrEnum):
    """Whether a drafted answer is supported by retrieved evidence."""

    GROUNDED = "grounded"
    PARTIALLY_GROUNDED = "partially_grounded"
    UNGROUNDED = "ungrounded"


class SpanStatus(StrEnum):
    OK = "ok"
    ERROR = "error"


class HumanReviewReason(StrEnum):
    """Why a conversation reached a person.

    Recorded verbatim so the escalation rate can be decomposed: a spike in
    ``LOW_CONFIDENCE`` is a model problem, a spike in ``GROUNDING_FAILED`` is
    a retrieval problem, and they need different fixes.
    """

    LOW_CONFIDENCE = "low_confidence"
    GROUNDING_FAILED = "grounding_failed"
    COMPLAINT = "complaint"
    NEGATIVE_SENTIMENT = "negative_sentiment"
    UNSUPPORTED_FINANCIAL_CLAIM = "unsupported_financial_claim"
    POLICY_REQUIRES_APPROVAL = "policy_requires_approval"
    PREVIOUSLY_HUMAN_HANDLED = "previously_human_handled"
    # The customer sent a new message on a conversation that was already
    # handed off. The operator needs to see it and reply — one queue item
    # per conversation, not per message.
    AWAITING_OPERATOR_REPLY = "awaiting_operator_reply"


class ReviewOutcome(StrEnum):
    APPROVED = "approved"
    EDITED = "edited"
    REASSIGNED = "reassigned"
    REJECTED = "rejected"


class UserRole(StrEnum):
    CUSTOMER = "customer"
    COORDINATOR = "coordinator"
    FINANCE = "finance"
    TRADE_IN = "trade_in"
    MANAGEMENT = "management"
