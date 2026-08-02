"""Model-capability detection.

Both vendors have shipped models that reject `temperature` outright with a
400, and both times the failure showed up only against a live key — the mock
provider cannot catch it, and there was no unit coverage. These tests pin the
detection so the next model in either family is a one-line change with a
failing test to prove it, rather than a production 400.
"""

from __future__ import annotations

import pytest

from app.infrastructure.llm.providers import (
    _accepts_custom_temperature,
    _anthropic_accepts_temperature,
)


class TestOpenAiTemperature:
    @pytest.mark.parametrize(
        "model",
        ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
    )
    def test_earlier_models_still_get_deterministic_extraction(self, model) -> None:
        assert _accepts_custom_temperature(model)

    @pytest.mark.parametrize("model", ["gpt-5-mini", "gpt-5", "gpt-5-turbo-2026"])
    def test_the_gpt5_family_is_left_on_its_default(self, model) -> None:
        assert not _accepts_custom_temperature(model)


class TestAnthropicTemperature:
    @pytest.mark.parametrize(
        "model",
        [
            "claude-opus-5",
            "claude-sonnet-5",
            "claude-fable-5",
            # A dated Claude 5 id must be caught too — the family is what
            # matters, not whether a release date is appended.
            "claude-sonnet-5-20260101",
        ],
    )
    def test_the_claude5_family_rejects_temperature(self, model) -> None:
        assert not _anthropic_accepts_temperature(model)

    @pytest.mark.parametrize(
        "model",
        [
            # Haiku 4.5. The "-4-5-" is the version, not a generation-5 marker,
            # and a naive substring match on "-5" would wrongly strip the
            # parameter from the entire fast tier.
            "claude-haiku-4-5-20251001",
            "claude-opus-4-20250514",
            "claude-3-5-sonnet-20241022",
        ],
    )
    def test_earlier_models_keep_it(self, model) -> None:
        assert _anthropic_accepts_temperature(model)

    def test_the_configured_defaults_are_classified(self) -> None:
        # Guards the pairing that actually ships: the fast tier wants
        # temperature=0 for stable extraction, the premium tier must not send
        # the parameter at all.
        from app.core.settings import Settings

        settings = Settings(llm_provider="mock")
        assert _anthropic_accepts_temperature(settings.anthropic_fast_model)
        assert not _anthropic_accepts_temperature(settings.anthropic_premium_model)
