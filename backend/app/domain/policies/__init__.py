"""Business rules as validated, versioned configuration.

Thresholds, weights, slot requirements and department mappings live in YAML
beside this module rather than in code or prompts. Two consequences:

* Changing routing is a config edit plus a test, never a prompt change.
* The rules are reviewable by the business, because they read as rules.

Everything is loaded once and cached. Policies are immutable at runtime — a
policy that could drift mid-conversation would make traces unreproducible.
"""

from __future__ import annotations

from functools import lru_cache
from itertools import pairwise
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import (
    ConfidenceSignal,
    Department,
    EntityType,
    HumanReviewReason,
    IntentCategory,
    ModelTier,
)

POLICY_DIR = Path(__file__).parent


class PolicyError(RuntimeError):
    """Raised when a policy file is missing, malformed or self-inconsistent."""


class _Policy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# ──────────────────────────────────────────────────────────────────────
# Intent policy
# ──────────────────────────────────────────────────────────────────────
class IntentRule(_Policy):
    """How one intent category is handled."""

    department: Department
    priority: int = Field(ge=0, le=100)
    required_slots: tuple[EntityType, ...] = ()
    optional_slots: tuple[EntityType, ...] = ()
    depends_on_categories: tuple[IntentCategory, ...] = ()
    force_human: bool = False
    sla_minutes: int = Field(gt=0)


class SlotQuestion(_Policy):
    en: str
    ar: str


class IntentPolicy(_Policy):
    version: int
    categories: dict[IntentCategory, IntentRule]
    slot_question_order: tuple[EntityType, ...]
    slot_questions: dict[EntityType, SlotQuestion]

    def rule(self, category: IntentCategory) -> IntentRule:
        try:
            return self.categories[category]
        except KeyError as exc:  # pragma: no cover - guarded by validation
            raise PolicyError(f"No intent rule configured for {category}") from exc

    def next_question_slot(self, missing: set[EntityType]) -> EntityType | None:
        """First missing slot in configured priority order.

        Clarification asks one question per turn; an interrogation loses the
        customer faster than a slower reply does.
        """
        return next((slot for slot in self.slot_question_order if slot in missing), None)

    def question_for(self, slot: EntityType) -> SlotQuestion | None:
        return self.slot_questions.get(slot)


# ──────────────────────────────────────────────────────────────────────
# Confidence policy
# ──────────────────────────────────────────────────────────────────────
class RiskPenalties(_Policy):
    low_entity_confidence: float = Field(ge=0.0, le=1.0)
    missing_required_slot: float = Field(ge=0.0, le=1.0)
    negative_sentiment: float = Field(ge=0.0, le=1.0)
    high_urgency: float = Field(ge=0.0, le=1.0)
    financial_figure_present: float = Field(ge=0.0, le=1.0)
    multi_intent: float = Field(ge=0.0, le=1.0)


class HardOverride(_Policy):
    """A condition that forces a human regardless of the computed score.

    Necessary because a weighted average can be dragged over the threshold by
    strong unrelated signals — confident retrieval must never be able to
    authorise auto-sending a reply to a furious customer.
    """

    id: str
    reason: HumanReviewReason
    when: str
    value: str | None = None


class Thresholds(_Policy):
    auto: float = Field(ge=0.0, le=100.0)
    premium: float = Field(ge=0.0, le=100.0)


class ConfidencePolicy(_Policy):
    version: int
    weights: dict[str, float]
    thresholds: Thresholds
    risk_penalties: RiskPenalties
    entity_floor: float = Field(ge=0.0, le=1.0)
    hard_overrides: tuple[HardOverride, ...]
    model_tiers: dict[str, ModelTier]

    def weight(self, signal: ConfidenceSignal) -> float:
        """Weight for a signal. Unweighted signals contribute 0 by design.

        ``entity`` is measured and displayed but carries no direct weight — it
        enters the score through ``risk``. Returning 0 here rather than
        raising keeps that fact explicit instead of accidental.
        """
        return self.weights.get(signal.value, 0.0)

    def tier_for(self, stage: str) -> ModelTier:
        return self.model_tiers.get(stage, ModelTier.FAST)


# ──────────────────────────────────────────────────────────────────────
# Finance policy
# ──────────────────────────────────────────────────────────────────────
class RegulatoryLimits(_Policy):
    max_loan_to_value: float = Field(gt=0.0, le=1.0)
    min_down_payment_ratio: float = Field(ge=0.0, lt=1.0)
    max_tenure_months: int = Field(gt=0)
    interest_method: str
    max_security_cheque_ratio: float
    source: str


class FinanceDefaults(_Policy):
    down_payment_ratio: float = Field(ge=0.0, lt=1.0)
    tenure_months: int = Field(gt=0)
    annual_profit_rate: float = Field(ge=0.0, lt=1.0)
    currency: str


class RateBand(_Policy):
    id: str
    label: str
    annual_rate: float = Field(ge=0.0, lt=1.0)
    requires_salary_transfer: bool


class Eligibility(_Policy):
    max_finance_amount_aed: float = Field(gt=0)
    min_finance_amount_aed: float = Field(ge=0)
    max_age_at_maturity_national: int
    max_age_at_maturity_expat: int
    max_instalment_to_income_ratio: float = Field(gt=0.0, le=1.0)


class FinanceFees(_Policy):
    early_settlement_ratio: float = Field(ge=0.0)
    early_settlement_note: str
    processing_fee_ratio: float = Field(ge=0.0)


class QuotingRules(_Policy):
    computation: str
    disclaimer_en: str
    disclaimer_ar: str
    round_to: int = Field(gt=0)


class FinancePolicy(_Policy):
    version: int
    regulatory: RegulatoryLimits
    defaults: FinanceDefaults
    rate_bands: tuple[RateBand, ...]
    eligibility: Eligibility
    fees: FinanceFees
    quoting: QuotingRules

    def rate_for(self, salary_transfer: bool) -> RateBand:
        """Applicable rate band. Falls back to the stricter (higher) rate.

        Defaulting upward matters: quoting the cheaper instalment and revising
        it after the customer has anchored on it is how trust is lost.
        """
        match = next(
            (b for b in self.rate_bands if b.requires_salary_transfer == salary_transfer),
            None,
        )
        return match or max(self.rate_bands, key=lambda b: b.annual_rate)


# ──────────────────────────────────────────────────────────────────────
# Valuation policy
# ──────────────────────────────────────────────────────────────────────
class MileageAdjustment(_Policy):
    expected_km_per_year: int = Field(gt=0)
    adjustment_per_1000km: float = Field(ge=0.0)
    max_penalty_ratio: float = Field(ge=0.0, le=1.0)
    max_bonus_ratio: float = Field(ge=0.0, le=1.0)


class ValuationOutput(_Policy):
    range_spread: float = Field(ge=0.0, le=1.0)
    round_to: int = Field(gt=0)
    disclaimer_en: str
    disclaimer_ar: str


class ValuationLimits(_Policy):
    max_age_years: int = Field(gt=0)
    max_mileage_km: int = Field(gt=0)
    min_estimate_aed: float = Field(ge=0)


class ValuationPolicy(_Policy):
    version: int
    synthetic: bool
    currency: str
    depreciation_curve: dict[int, float]
    floor_retained_ratio: float = Field(ge=0.0, le=1.0)
    brand_multipliers: dict[str, float]
    mileage: MileageAdjustment
    condition_multipliers: dict[str, float]
    default_condition: str
    output: ValuationOutput
    limits: ValuationLimits

    def retained_ratio(self, age_years: int) -> float:
        """Retained value fraction at a given age, linearly interpolated.

        The curve is sparse (a handful of anchor years), so interpolation
        keeps valuations continuous — otherwise a car crossing a birthday
        would jump in value by thousands.
        """
        if age_years <= 0:
            return self.depreciation_curve[min(self.depreciation_curve)]

        anchors = sorted(self.depreciation_curve)
        if age_years >= anchors[-1]:
            return self.floor_retained_ratio

        lower = max(a for a in anchors if a <= age_years)
        if lower == age_years:
            return self.depreciation_curve[lower]

        upper = min(a for a in anchors if a > age_years)
        span = upper - lower
        weight = (age_years - lower) / span
        low_v, high_v = self.depreciation_curve[lower], self.depreciation_curve[upper]
        return low_v + (high_v - low_v) * weight


# ──────────────────────────────────────────────────────────────────────
# Loading
# ──────────────────────────────────────────────────────────────────────
def _read(name: str) -> dict[str, Any]:
    path = POLICY_DIR / f"{name}.yaml"
    if not path.exists():
        raise PolicyError(f"Missing policy file: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PolicyError(f"Malformed policy file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PolicyError(f"Policy file {path} must contain a mapping at the top level.")
    return data


@lru_cache(maxsize=1)
def intent_policy() -> IntentPolicy:
    policy = IntentPolicy.model_validate(_read("intents"))

    # Every category must be configured. A category with no rule would fall
    # through routing silently and strand the customer's request.
    missing = set(IntentCategory) - set(policy.categories)
    if missing:
        raise PolicyError(
            "intents.yaml is missing rules for: "
            + ", ".join(sorted(c.value for c in missing))
        )

    # Every required slot must have a question, or clarification would know
    # something is missing but have no way to ask for it.
    needed = {s for rule in policy.categories.values() for s in rule.required_slots}
    unanswerable = needed - set(policy.slot_questions)
    if unanswerable:
        raise PolicyError(
            "intents.yaml declares required slots with no clarification question: "
            + ", ".join(sorted(s.value for s in unanswerable))
        )

    return policy


@lru_cache(maxsize=1)
def confidence_policy() -> ConfidencePolicy:
    policy = ConfidencePolicy.model_validate(_read("confidence"))

    total = sum(policy.weights.values())
    if abs(total - 1.0) > 1e-6:
        raise PolicyError(f"confidence.yaml weights must sum to 1.0, got {total:.6f}")

    if policy.thresholds.premium >= policy.thresholds.auto:
        raise PolicyError(
            "confidence.yaml: the premium threshold must sit below the auto threshold."
        )

    return policy


@lru_cache(maxsize=1)
def finance_policy() -> FinancePolicy:
    policy = FinancePolicy.model_validate(_read("finance"))

    # Defaults must respect the regulator, or the platform would quote terms
    # no bank in the market is permitted to offer.
    reg, dflt = policy.regulatory, policy.defaults
    if dflt.down_payment_ratio < reg.min_down_payment_ratio:
        raise PolicyError(
            f"finance.yaml default down payment {dflt.down_payment_ratio} is below the "
            f"regulatory minimum {reg.min_down_payment_ratio} ({reg.source})."
        )
    if dflt.tenure_months > reg.max_tenure_months:
        raise PolicyError(
            f"finance.yaml default tenure {dflt.tenure_months}m exceeds the regulatory "
            f"maximum {reg.max_tenure_months}m ({reg.source})."
        )
    if not policy.rate_bands:
        raise PolicyError("finance.yaml must define at least one rate band.")

    return policy


@lru_cache(maxsize=1)
def valuation_policy() -> ValuationPolicy:
    policy = ValuationPolicy.model_validate(_read("valuation"))

    if not policy.depreciation_curve:
        raise PolicyError("valuation.yaml requires a depreciation curve.")
    if policy.default_condition not in policy.condition_multipliers:
        raise PolicyError(
            f"valuation.yaml default condition '{policy.default_condition}' has no "
            "multiplier defined."
        )

    # A curve that rises with age would produce absurd valuations.
    ratios = [policy.depreciation_curve[age] for age in sorted(policy.depreciation_curve)]
    if any(later > earlier for earlier, later in pairwise(ratios)):
        raise PolicyError("valuation.yaml depreciation curve must be non-increasing.")

    return policy


def load_all() -> None:
    """Validate every policy file. Called at startup so misconfiguration fails
    immediately rather than mid-conversation."""
    intent_policy()
    confidence_policy()
    finance_policy()
    valuation_policy()


__all__ = [
    "ConfidencePolicy",
    "FinancePolicy",
    "HardOverride",
    "IntentPolicy",
    "IntentRule",
    "PolicyError",
    "ValuationPolicy",
    "confidence_policy",
    "finance_policy",
    "intent_policy",
    "load_all",
    "valuation_policy",
]
