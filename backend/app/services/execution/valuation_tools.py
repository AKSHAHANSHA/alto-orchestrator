"""Deterministic trade-in valuation.

Base MSRP from the catalog, then depreciation, mileage and condition
adjustments in that order. The model is authored for Velmora and explicitly
synthetic — no trade-in pricing data was supplied — which is precisely why it
is transparent: a customer quoted a number is owed the reasoning behind it.

Output is always a *range*, never a point estimate, and always "subject to
inspection". A precise figure implies a binding offer the dealership has not
made and cannot honour before seeing the car.

When the vehicle falls outside the model's competence — too old, absurd
mileage, or absent from the catalog — this refuses to quote and hands off to
the Trade-In team. An honest handoff costs a phone call; a wrong number costs
the sale and the relationship.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, Field

from app.core.errors import ToolError
from app.domain.policies import ValuationPolicy, valuation_policy


class ValuationRequest(BaseModel):
    brand: str
    model: str
    year: int = Field(gt=1900, lt=2100)
    mileage_km: int | None = Field(default=None, ge=0)
    condition: str | None = None
    base_msrp: float | None = Field(default=None, gt=0)
    current_year: int = Field(gt=1900, lt=2100)


class ValuationEstimate(BaseModel):
    vehicle: str
    age_years: int
    base_msrp: float
    estimate_low: float
    estimate_high: float
    point_estimate: float
    currency: str

    retained_ratio: float
    brand_multiplier: float
    mileage_adjustment: float
    condition_multiplier: float
    condition_used: str

    factors: list[str]
    disclaimer_en: str
    disclaimer_ar: str
    is_synthetic_model: bool = True


def _round_to(value: float, step: int) -> float:
    return float(
        (Decimal(str(value)) / Decimal(step)).quantize(Decimal(1), ROUND_HALF_UP) * Decimal(step)
    )


def estimate_trade_in(
    request: ValuationRequest, policy: ValuationPolicy | None = None
) -> ValuationEstimate:
    """Estimate a trade-in range.

    Raises `ToolError` whenever the model is out of its depth, so the caller
    routes to a human appraiser instead of publishing a guess.
    """
    policy = policy or valuation_policy()

    age = max(0, request.current_year - request.year)
    if age > policy.limits.max_age_years:
        raise ToolError(
            f"At {age} years old this vehicle is beyond the valuation model's range and "
            f"needs a manual appraisal.",
            age_years=age,
        )

    if request.mileage_km is not None and request.mileage_km > policy.limits.max_mileage_km:
        raise ToolError(
            f"A reading of {request.mileage_km:,} km is beyond the valuation model's range "
            f"and needs a manual appraisal.",
            mileage_km=request.mileage_km,
        )

    if request.base_msrp is None:
        raise ToolError(
            f"No catalog price is available for a {request.year} {request.brand} "
            f"{request.model}, so it needs a manual appraisal.",
            brand=request.brand,
            model=request.model,
            year=request.year,
        )

    factors: list[str] = []

    # ── Depreciation ──────────────────────────────────────────────────
    retained = policy.retained_ratio(age)
    factors.append(
        f"{age} year{'s' if age != 1 else ''} old: retains about {retained:.0%} of the "
        f"original price."
    )

    # ── Brand ─────────────────────────────────────────────────────────
    brand_multiplier = policy.brand_multipliers.get(request.brand, 1.0)
    if brand_multiplier != 1.0:
        direction = (
            "holds its value better than"
            if brand_multiplier > 1
            else "depreciates faster than"
        )
        factors.append(f"{request.brand} {direction} the market average.")

    # ── Mileage ───────────────────────────────────────────────────────
    mileage_adjustment = 0.0
    if request.mileage_km is not None:
        expected = policy.mileage.expected_km_per_year * max(age, 1)
        deviation = request.mileage_km - expected
        raw = -(deviation / 1000) * policy.mileage.adjustment_per_1000km
        mileage_adjustment = max(
            -policy.mileage.max_penalty_ratio, min(policy.mileage.max_bonus_ratio, raw)
        )
        if deviation > 0:
            factors.append(
                f"{request.mileage_km:,} km is above the ~{expected:,.0f} km expected at "
                f"this age, reducing the estimate."
            )
        elif deviation < 0:
            factors.append(
                f"{request.mileage_km:,} km is below the ~{expected:,.0f} km expected at "
                f"this age, improving the estimate."
            )
    else:
        factors.append(
            "No mileage was provided; the estimate assumes average usage for the age."
        )

    # ── Condition ─────────────────────────────────────────────────────
    condition = (request.condition or policy.default_condition).lower()
    condition_multiplier = policy.condition_multipliers.get(condition)
    if condition_multiplier is None:
        condition = policy.default_condition
        condition_multiplier = policy.condition_multipliers[condition]
    if request.condition:
        factors.append(f"Condition reported as {condition}.")

    # ── Combine ───────────────────────────────────────────────────────
    # Mileage is applied as an additive adjustment to the retained ratio
    # rather than a multiplier, so that a heavy-mileage penalty on an old car
    # cannot compound into a near-zero valuation.
    ratio = (retained * brand_multiplier + mileage_adjustment) * condition_multiplier
    ratio = max(policy.floor_retained_ratio * 0.5, min(1.0, ratio))

    point = request.base_msrp * ratio
    if point < policy.limits.min_estimate_aed:
        raise ToolError(
            "The estimated value falls below the minimum this model will quote; the "
            "vehicle needs a manual appraisal.",
            point_estimate=point,
        )

    spread = policy.output.range_spread
    step = policy.output.round_to

    return ValuationEstimate(
        vehicle=f"{request.year} {request.brand} {request.model}",
        age_years=age,
        base_msrp=request.base_msrp,
        estimate_low=_round_to(point * (1 - spread), step),
        estimate_high=_round_to(point * (1 + spread), step),
        point_estimate=_round_to(point, step),
        currency=policy.currency,
        retained_ratio=round(retained, 4),
        brand_multiplier=brand_multiplier,
        mileage_adjustment=round(mileage_adjustment, 4),
        condition_multiplier=condition_multiplier,
        condition_used=condition,
        factors=factors,
        disclaimer_en=policy.output.disclaimer_en.strip(),
        disclaimer_ar=policy.output.disclaimer_ar.strip(),
        is_synthetic_model=policy.synthetic,
    )
