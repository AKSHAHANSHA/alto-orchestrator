"""Deterministic finance calculations.

No model ever computes an instalment. A wrong profit rate or monthly payment
quoted to a customer is a commercial and regulatory problem, and arithmetic is
the one thing a language model has no business doing when the answer is
checkable.

Every constraint applied here comes from `domain/policies/finance.yaml`, which
in turn cites the ingested CBUAE regulation and bank documents. The output
carries its own assumptions so the customer can see what the number rests on.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, Field

from app.core.errors import ToolError
from app.domain.policies import FinancePolicy, finance_policy


class EmiRequest(BaseModel):
    """Inputs for an instalment calculation.

    Only the vehicle price is required. Everything else falls back to the
    regulator's floor, so an under-specified request still produces a legal,
    conservative quote rather than an error.
    """

    vehicle_price: float = Field(gt=0)
    down_payment: float | None = Field(default=None, ge=0)
    down_payment_ratio: float | None = Field(default=None, ge=0, lt=1)
    tenure_months: int | None = Field(default=None, gt=0)
    annual_rate: float | None = Field(default=None, ge=0, lt=1)
    salary_transfer: bool = False
    monthly_income: float | None = Field(default=None, gt=0)


class EmiQuote(BaseModel):
    """A fully-explained instalment quote.

    Every intermediate figure is returned, not just the monthly payment,
    because the customer-facing answer has to be able to show its working and
    the grounding validator has to be able to check each number it cites.
    """

    vehicle_price: float
    down_payment: float
    down_payment_ratio: float
    finance_amount: float
    tenure_months: int
    annual_rate: float
    monthly_rate: float
    monthly_instalment: float
    total_payable: float
    total_profit: float
    rate_band: str
    currency: str

    assumptions: list[str]
    warnings: list[str]
    disclaimer_en: str
    disclaimer_ar: str
    affordability_ok: bool | None = None


def _round(value: float, to: int) -> float:
    quantum = Decimal(1) / Decimal(to) if to < 1 else Decimal(to)
    return float((Decimal(str(value)) / quantum).quantize(Decimal(1), ROUND_HALF_UP) * quantum)


def calculate_emi(request: EmiRequest, policy: FinancePolicy | None = None) -> EmiQuote:
    """Reducing-balance instalment, the method the CBUAE regulation mandates.

        instalment = P x r x (1+r)^n / ((1+r)^n - 1)

    where `r` is the monthly rate and `n` the tenure in months. The zero-rate
    case is handled separately because the formula divides by zero there.

    Raises `ToolError` rather than returning an approximation when the request
    cannot be satisfied — refusing to quote is always better than quoting
    terms no bank may legally offer.
    """
    policy = policy or finance_policy()
    reg, defaults, quoting = policy.regulatory, policy.defaults, policy.quoting

    assumptions: list[str] = []
    warnings: list[str] = []

    # ── Down payment ──────────────────────────────────────────────────
    if request.down_payment is not None:
        down = request.down_payment
    else:
        ratio = request.down_payment_ratio or defaults.down_payment_ratio
        down = request.vehicle_price * ratio
        if request.down_payment_ratio is None:
            assumptions.append(
                f"Down payment assumed at the regulatory minimum of "
                f"{defaults.down_payment_ratio:.0%}."
            )

    down_ratio = down / request.vehicle_price

    # The regulator caps financing at 80% of vehicle value. A request below
    # that floor is raised rather than rejected: the customer gets a valid
    # quote plus a clear explanation of why the number moved.
    if down_ratio < reg.min_down_payment_ratio:
        required = request.vehicle_price * reg.min_down_payment_ratio
        warnings.append(
            f"A minimum down payment of {reg.min_down_payment_ratio:.0%} "
            f"({required:,.0f} {defaults.currency}) is required by regulation, so the "
            f"quote uses that instead of the {down:,.0f} provided."
        )
        down = required
        down_ratio = reg.min_down_payment_ratio

    if down >= request.vehicle_price:
        raise ToolError(
            "The down payment covers the full vehicle price, so no financing is needed.",
            vehicle_price=request.vehicle_price,
            down_payment=down,
        )

    finance_amount = request.vehicle_price - down

    # ── Eligibility ───────────────────────────────────────────────────
    elig = policy.eligibility
    if finance_amount > elig.max_finance_amount_aed:
        raise ToolError(
            f"The financed amount of {finance_amount:,.0f} {defaults.currency} exceeds the "
            f"maximum of {elig.max_finance_amount_aed:,.0f}. This needs a specialist.",
            finance_amount=finance_amount,
        )
    if finance_amount < elig.min_finance_amount_aed:
        raise ToolError(
            f"The financed amount of {finance_amount:,.0f} {defaults.currency} is below the "
            f"minimum of {elig.min_finance_amount_aed:,.0f}.",
            finance_amount=finance_amount,
        )

    # ── Tenure ────────────────────────────────────────────────────────
    tenure = request.tenure_months or defaults.tenure_months
    if request.tenure_months is None:
        assumptions.append(f"Tenure assumed at {tenure} months.")
    if tenure > reg.max_tenure_months:
        warnings.append(
            f"The maximum repayment period is {reg.max_tenure_months} months by "
            f"regulation, so {tenure} months has been capped."
        )
        tenure = reg.max_tenure_months

    # ── Rate ──────────────────────────────────────────────────────────
    if request.annual_rate is not None:
        annual_rate, band_id = request.annual_rate, "custom"
    else:
        band = policy.rate_for(request.salary_transfer)
        annual_rate, band_id = band.annual_rate, band.id
        assumptions.append(f"{band.label}: {annual_rate:.2%} annual reducing-balance rate.")
        if not request.salary_transfer:
            assumptions.append(
                "Transferring your salary to the financing bank typically reduces this rate."
            )

    monthly_rate = annual_rate / 12

    # ── Instalment ────────────────────────────────────────────────────
    if monthly_rate == 0:
        instalment = finance_amount / tenure
    else:
        growth = (1 + monthly_rate) ** tenure
        instalment = finance_amount * monthly_rate * growth / (growth - 1)

    instalment = _round(instalment, quoting.round_to)
    total_payable = _round(instalment * tenure, quoting.round_to)

    # ── Affordability ─────────────────────────────────────────────────
    affordability: bool | None = None
    if request.monthly_income:
        share = instalment / request.monthly_income
        affordability = share <= elig.max_instalment_to_income_ratio
        if not affordability:
            warnings.append(
                f"This instalment is {share:.0%} of the stated monthly income, above the "
                f"{elig.max_instalment_to_income_ratio:.0%} guideline. A longer tenure or "
                f"larger down payment would bring it within range."
            )

    return EmiQuote(
        vehicle_price=request.vehicle_price,
        down_payment=_round(down, quoting.round_to),
        down_payment_ratio=round(down_ratio, 4),
        finance_amount=_round(finance_amount, quoting.round_to),
        tenure_months=tenure,
        annual_rate=annual_rate,
        monthly_rate=monthly_rate,
        monthly_instalment=instalment,
        total_payable=total_payable,
        total_profit=_round(total_payable - finance_amount, quoting.round_to),
        rate_band=band_id,
        currency=defaults.currency,
        assumptions=assumptions,
        warnings=warnings,
        disclaimer_en=quoting.disclaimer_en.strip(),
        disclaimer_ar=quoting.disclaimer_ar.strip(),
        affordability_ok=affordability,
    )
