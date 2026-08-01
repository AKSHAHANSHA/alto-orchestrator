"""Tests for the deterministic tools.

These produce the numbers customers act on, so they are tested against the
regulation they encode rather than against themselves.
"""

from __future__ import annotations

import pytest

from app.core.errors import ToolError
from app.domain.policies import finance_policy, valuation_policy
from app.services.execution.finance_tools import EmiRequest, calculate_emi
from app.services.execution.valuation_tools import ValuationRequest, estimate_trade_in


class TestEmiArithmetic:
    def test_matches_the_standard_reducing_balance_formula(self) -> None:
        # 100,000 financed at 12% nominal over 12 months. The closed-form
        # answer is 8,884.88; the tool rounds to whole currency units.
        quote = calculate_emi(
            EmiRequest(
                vehicle_price=125_000,
                down_payment=25_000,
                tenure_months=12,
                annual_rate=0.12,
            )
        )
        assert quote.finance_amount == pytest.approx(100_000)
        assert quote.monthly_instalment == pytest.approx(8885, abs=1)

    def test_zero_rate_divides_the_principal_evenly(self) -> None:
        # The general formula divides by zero here, so this path is separate.
        quote = calculate_emi(
            EmiRequest(vehicle_price=120_000, down_payment=24_000, tenure_months=48,
                       annual_rate=0.0)
        )
        assert quote.monthly_instalment == pytest.approx(2000, abs=1)
        assert quote.total_profit == pytest.approx(0, abs=1)

    def test_total_payable_reconciles_with_the_instalment(self) -> None:
        quote = calculate_emi(EmiRequest(vehicle_price=200_000, tenure_months=60))
        assert quote.total_payable == pytest.approx(
            quote.monthly_instalment * quote.tenure_months, abs=1
        )
        assert quote.total_profit == pytest.approx(
            quote.total_payable - quote.finance_amount, abs=1
        )

    def test_longer_tenure_lowers_the_instalment_but_costs_more_overall(self) -> None:
        short = calculate_emi(EmiRequest(vehicle_price=200_000, tenure_months=24))
        long = calculate_emi(EmiRequest(vehicle_price=200_000, tenure_months=60))
        assert long.monthly_instalment < short.monthly_instalment
        assert long.total_profit > short.total_profit


class TestRegulatoryCompliance:
    """The CBUAE limits are not advisory. The tool cannot be argued past them."""

    def test_down_payment_below_the_minimum_is_raised_not_accepted(self) -> None:
        quote = calculate_emi(EmiRequest(vehicle_price=100_000, down_payment=5_000))
        policy = finance_policy()
        assert quote.down_payment_ratio >= policy.regulatory.min_down_payment_ratio
        assert any("minimum down payment" in w.lower() for w in quote.warnings)

    def test_tenure_beyond_the_maximum_is_capped(self) -> None:
        quote = calculate_emi(EmiRequest(vehicle_price=150_000, tenure_months=84))
        assert quote.tenure_months == finance_policy().regulatory.max_tenure_months
        assert any("maximum repayment period" in w.lower() for w in quote.warnings)

    def test_loan_to_value_never_exceeds_eighty_percent(self) -> None:
        quote = calculate_emi(EmiRequest(vehicle_price=100_000, down_payment=0))
        ltv = quote.finance_amount / quote.vehicle_price
        assert ltv <= finance_policy().regulatory.max_loan_to_value + 1e-9

    def test_defaults_are_the_conservative_floor(self) -> None:
        # Quoting the cheapest possible instalment and revising upward later
        # is how trust is lost.
        quote = calculate_emi(EmiRequest(vehicle_price=100_000))
        assert quote.down_payment_ratio == pytest.approx(0.20)
        assert any("assumed" in a.lower() for a in quote.assumptions)


class TestEmiRefusals:
    def test_refuses_when_the_amount_exceeds_the_market_maximum(self) -> None:
        with pytest.raises(ToolError, match="exceeds the maximum"):
            calculate_emi(EmiRequest(vehicle_price=2_000_000, down_payment=400_000))

    def test_refuses_when_no_financing_is_needed(self) -> None:
        with pytest.raises(ToolError, match="no financing is needed"):
            calculate_emi(EmiRequest(vehicle_price=100_000, down_payment=100_000))


class TestSalaryTransferAndAffordability:
    def test_salary_transfer_improves_the_rate(self) -> None:
        with_transfer = calculate_emi(
            EmiRequest(vehicle_price=150_000, salary_transfer=True)
        )
        without = calculate_emi(EmiRequest(vehicle_price=150_000, salary_transfer=False))
        assert with_transfer.annual_rate < without.annual_rate
        assert with_transfer.monthly_instalment < without.monthly_instalment

    def test_unaffordable_instalments_are_flagged_not_hidden(self) -> None:
        quote = calculate_emi(
            EmiRequest(vehicle_price=400_000, tenure_months=24, monthly_income=8_000)
        )
        assert quote.affordability_ok is False
        assert any("monthly income" in w.lower() for w in quote.warnings)

    def test_every_quote_carries_its_disclaimer(self) -> None:
        quote = calculate_emi(EmiRequest(vehicle_price=150_000))
        assert "not a finance offer" in quote.disclaimer_en
        assert quote.disclaimer_ar.strip()


class TestValuation:
    def base(self, **kwargs: object) -> ValuationRequest:
        defaults: dict[str, object] = {
            "brand": "Karva",
            "model": "Sedan",
            "year": 2020,
            "base_msrp": 100_000,
            "current_year": 2026,
        }
        return ValuationRequest(**{**defaults, **kwargs})  # type: ignore[arg-type]

    def test_returns_a_range_never_a_single_number(self) -> None:
        # A precise figure implies a binding offer nobody has made.
        result = estimate_trade_in(self.base())
        assert result.estimate_low < result.point_estimate < result.estimate_high

    def test_value_falls_monotonically_with_age(self) -> None:
        values = [
            estimate_trade_in(self.base(year=year)).point_estimate
            for year in (2024, 2022, 2020, 2018)
        ]
        assert values == sorted(values, reverse=True)

    def test_high_mileage_reduces_the_estimate(self) -> None:
        low = estimate_trade_in(self.base(mileage_km=40_000)).point_estimate
        high = estimate_trade_in(self.base(mileage_km=200_000)).point_estimate
        assert high < low

    def test_condition_moves_the_estimate_in_the_expected_direction(self) -> None:
        poor = estimate_trade_in(self.base(condition="poor")).point_estimate
        good = estimate_trade_in(self.base(condition="good")).point_estimate
        excellent = estimate_trade_in(self.base(condition="excellent")).point_estimate
        assert poor < good < excellent

    def test_renzo_holds_value_better_than_karva(self) -> None:
        karva = estimate_trade_in(self.base(brand="Karva")).point_estimate
        renzo = estimate_trade_in(self.base(brand="Renzo")).point_estimate
        assert renzo > karva

    def test_an_estimate_never_exceeds_the_original_price(self) -> None:
        result = estimate_trade_in(
            self.base(year=2026, condition="excellent", mileage_km=0)
        )
        assert result.point_estimate <= result.base_msrp

    def test_unknown_condition_falls_back_to_the_default(self) -> None:
        result = estimate_trade_in(self.base(condition="pristine-ish"))
        assert result.condition_used == valuation_policy().default_condition

    def test_every_estimate_explains_itself(self) -> None:
        result = estimate_trade_in(self.base(mileage_km=180_000, condition="fair"))
        assert len(result.factors) >= 3
        assert "inspection" in result.disclaimer_en.lower()
        assert result.is_synthetic_model


class TestValuationRefusals:
    """Out of its depth, the model hands off rather than guessing."""

    def test_refuses_a_vehicle_older_than_the_model_range(self) -> None:
        with pytest.raises(ToolError, match="manual appraisal"):
            estimate_trade_in(
                ValuationRequest(brand="Karva", model="Sedan", year=1995,
                                 base_msrp=50_000, current_year=2026)
            )

    def test_refuses_absurd_mileage(self) -> None:
        with pytest.raises(ToolError, match="manual appraisal"):
            estimate_trade_in(
                ValuationRequest(brand="Karva", model="Sedan", year=2020, mileage_km=900_000,
                                 base_msrp=100_000, current_year=2026)
            )

    def test_refuses_when_the_vehicle_is_not_in_the_catalog(self) -> None:
        # No catalog price means no defensible basis for a number.
        with pytest.raises(ToolError, match="No catalog price"):
            estimate_trade_in(
                ValuationRequest(brand="Karva", model="Ghost", year=2020, current_year=2026)
            )
