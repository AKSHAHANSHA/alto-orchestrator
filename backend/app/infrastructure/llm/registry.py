"""Model registry, cost accounting and the daily budget guard.

Prices are per million tokens, in USD. They are declared here rather than
fetched, so a trace from six months ago still costs what it cost — retroactive
repricing would make historical cost analysis meaningless.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from app.core.logging import get_logger
from app.domain.enums import ModelTier
from app.domain.value_objects import TokenUsage

logger = get_logger(__name__)


@dataclass(frozen=True)
class ModelPricing:
    input_per_million: float
    output_per_million: float

    def cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (
            prompt_tokens * self.input_per_million
            + completion_tokens * self.output_per_million
        ) / 1_000_000


# Published list prices at time of writing. Unknown models fall back to the
# most expensive entry, so an unpriced model over-reports rather than
# silently costing nothing — a budget guard that under-counts is worse than
# useless.
PRICING: dict[str, ModelPricing] = {
    # NOTE: gpt-5-mini pricing is a placeholder — verify against the
    # current OpenAI list price before trusting the cost dashboard. The
    # BudgetGuard uses these rates directly, so a wrong number here
    # under- or over-counts spend.
    "gpt-5-mini": ModelPricing(0.25, 2.00),
    "gpt-4o-mini": ModelPricing(0.15, 0.60),
    "gpt-4o": ModelPricing(2.50, 10.00),
    "claude-haiku-4-5-20251001": ModelPricing(1.00, 5.00),
    "claude-opus-5": ModelPricing(5.00, 25.00),
    # Priced at zero because clarification runs on a free Groq key. If that
    # key is ever moved to a paid tier, put the real rates here — otherwise
    # the budget guard will not see the spend.
    "llama-3.1-8b-instant": ModelPricing(0.0, 0.0),
    "llama-3.3-70b-versatile": ModelPricing(0.0, 0.0),
    "openai/gpt-oss-20b": ModelPricing(0.0, 0.0),
    "mock-fast": ModelPricing(0.0, 0.0),
    "mock-premium": ModelPricing(0.0, 0.0),
}

_FALLBACK = ModelPricing(5.00, 25.00)


def price_for(model: str) -> ModelPricing:
    pricing = PRICING.get(model)
    if pricing is None:
        logger.warning("unpriced_model", model=model, note="charging at the highest rate")
        return _FALLBACK
    return pricing


def compute_usage(model: str, prompt_tokens: int, completion_tokens: int) -> TokenUsage:
    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=price_for(model).cost(prompt_tokens, completion_tokens),
    )


class BudgetGuard:
    """Tracks daily spend and demotes the premium tier once the cap is hit.

    Demotion rather than refusal is deliberate. Refusing to answer because an
    internal budget ran out is a self-inflicted outage visible to customers;
    answering on the cheaper model is a quality reduction nobody outside the
    building notices.
    """

    def __init__(self, daily_limit_usd: float) -> None:
        self._limit = daily_limit_usd
        self._day: date = datetime.now(UTC).date()
        self._spent = 0.0

    @property
    def spent_today(self) -> float:
        self._roll_over()
        return self._spent

    @property
    def remaining(self) -> float:
        return max(0.0, self._limit - self.spent_today)

    @property
    def exhausted(self) -> bool:
        return self.spent_today >= self._limit

    def _roll_over(self) -> None:
        today = datetime.now(UTC).date()
        if today != self._day:
            self._day, self._spent = today, 0.0

    def record(self, usage: TokenUsage) -> None:
        self._roll_over()
        self._spent += usage.cost_usd

    def effective_tier(self, requested: ModelTier) -> ModelTier:
        if requested is ModelTier.PREMIUM and self.exhausted:
            logger.warning(
                "budget_exhausted_demoting_tier",
                limit_usd=self._limit,
                spent_usd=round(self._spent, 4),
            )
            return ModelTier.FAST
        return requested
