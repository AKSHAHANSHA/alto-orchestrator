"""OpenAI and Anthropic adapters, plus the tier-aware router.

Both providers implement the same `LLMProvider` port, so nothing upstream
knows or cares which one is configured. Structured output uses each vendor's
native schema enforcement rather than parsing JSON out of prose — a stage that
cannot parse its own input should fail at the boundary, not leak a malformed
string into the pipeline.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, TypeVar

from pydantic import BaseModel

from app.core.errors import LLMError, StructuredOutputError
from app.core.logging import get_logger
from app.domain.enums import ModelTier
from app.domain.ports import LLMProvider, LLMResponse, StructuredResponse
from app.infrastructure.llm.registry import BudgetGuard, compute_usage

if TYPE_CHECKING:
    from app.core.settings import Settings

logger = get_logger(__name__)
SchemaT = TypeVar("SchemaT", bound=BaseModel)

# Appended to the system prompt for providers without native schema support.
JSON_INSTRUCTION = (
    "\n\nRespond with a single JSON object matching this schema exactly. "
    "Emit no prose, no markdown fences, and no commentary.\n{schema}"
)


class OpenAIProvider:
    """OpenAI adapter using native structured outputs."""

    name = "openai"

    def __init__(self, *, api_key: str, fast_model: str, premium_model: str) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key)
        self._models = {ModelTier.FAST: fast_model, ModelTier.PREMIUM: premium_model}

    def model_for(self, tier: ModelTier) -> str:
        return self._models[tier]

    async def complete(
        self,
        *,
        system: str,
        user: str,
        tier: ModelTier,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        model = self.model_for(tier)
        try:
            response = await self._client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            raise LLMError(f"OpenAI completion failed: {exc}", model=model) from exc

        usage = response.usage
        return LLMResponse(
            text=response.choices[0].message.content or "",
            model=model,
            provider=self.name,
            usage=compute_usage(
                model,
                usage.prompt_tokens if usage else 0,
                usage.completion_tokens if usage else 0,
            ),
        )

    async def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[SchemaT],
        tier: ModelTier,
        temperature: float = 0.0,
    ) -> StructuredResponse[SchemaT]:
        model = self.model_for(tier)
        try:
            response = await self._client.beta.chat.completions.parse(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format=schema,
                temperature=temperature,
            )
            parsed = response.choices[0].message.parsed
        except Exception as exc:
            raise StructuredOutputError(
                f"OpenAI structured output failed: {exc}",
                model=model,
                schema=schema.__name__,
            ) from exc

        if parsed is None:
            raise StructuredOutputError(
                "OpenAI returned no parsed value.", model=model, schema=schema.__name__
            )

        usage = response.usage
        return StructuredResponse[schema](  # type: ignore[valid-type]
            value=parsed,
            model=model,
            provider=self.name,
            usage=compute_usage(
                model,
                usage.prompt_tokens if usage else 0,
                usage.completion_tokens if usage else 0,
            ),
        )

    async def stream(
        self, *, system: str, user: str, tier: ModelTier, temperature: float = 0.0
    ) -> AsyncIterator[str]:
        stream = await self._client.chat.completions.create(
            model=self.model_for(tier),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta


class AnthropicProvider:
    """Anthropic adapter.

    Structured output is enforced by requiring a tool call whose input schema
    is the target model — the most reliable way to get schema-valid JSON out
    of the Messages API.
    """

    name = "anthropic"

    def __init__(self, *, api_key: str, fast_model: str, premium_model: str) -> None:
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=api_key)
        self._models = {ModelTier.FAST: fast_model, ModelTier.PREMIUM: premium_model}

    def model_for(self, tier: ModelTier) -> str:
        return self._models[tier]

    async def complete(
        self,
        *,
        system: str,
        user: str,
        tier: ModelTier,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        model = self.model_for(tier)
        try:
            message = await self._client.messages.create(
                model=model,
                system=system,
                messages=[{"role": "user", "content": user}],
                temperature=temperature,
                max_tokens=max_tokens or 2048,
            )
        except Exception as exc:
            raise LLMError(f"Anthropic completion failed: {exc}", model=model) from exc

        text = "".join(block.text for block in message.content if block.type == "text")
        return LLMResponse(
            text=text,
            model=model,
            provider=self.name,
            usage=compute_usage(model, message.usage.input_tokens, message.usage.output_tokens),
        )

    async def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[SchemaT],
        tier: ModelTier,
        temperature: float = 0.0,
    ) -> StructuredResponse[SchemaT]:
        model = self.model_for(tier)
        tool_name = "emit_" + schema.__name__.lower()

        try:
            message = await self._client.messages.create(
                model=model,
                system=system,
                messages=[{"role": "user", "content": user}],
                temperature=temperature,
                max_tokens=4096,
                tools=[
                    {
                        "name": tool_name,
                        "description": f"Emit a well-formed {schema.__name__}.",
                        "input_schema": schema.model_json_schema(),
                    }
                ],
                # Forcing the tool removes the possibility of a prose reply.
                tool_choice={"type": "tool", "name": tool_name},
            )
        except Exception as exc:
            raise StructuredOutputError(
                f"Anthropic structured output failed: {exc}",
                model=model,
                schema=schema.__name__,
            ) from exc

        payload = next((b.input for b in message.content if b.type == "tool_use"), None)
        if payload is None:
            raise StructuredOutputError(
                "Anthropic returned no tool call.", model=model, schema=schema.__name__
            )

        try:
            value = schema.model_validate(payload)
        except Exception as exc:
            raise StructuredOutputError(
                f"Anthropic tool input did not satisfy {schema.__name__}: {exc}",
                model=model,
                payload=json.dumps(payload)[:500],
            ) from exc

        return StructuredResponse[schema](  # type: ignore[valid-type]
            value=value,
            model=model,
            provider=self.name,
            usage=compute_usage(model, message.usage.input_tokens, message.usage.output_tokens),
        )

    async def stream(
        self, *, system: str, user: str, tier: ModelTier, temperature: float = 0.0
    ) -> AsyncIterator[str]:
        async with self._client.messages.stream(
            model=self.model_for(tier),
            system=system,
            messages=[{"role": "user", "content": user}],
            temperature=temperature,
            max_tokens=2048,
        ) as stream:
            async for text in stream.text_stream:
                yield text


class ModelRouter:
    """Wraps a provider with budget enforcement and usage accounting.

    Every call goes through here so that cost is measured once, in one place,
    rather than approximated from logs afterwards.
    """

    def __init__(self, provider: LLMProvider, budget: BudgetGuard) -> None:
        self._provider = provider
        self._budget = budget

    @property
    def provider_name(self) -> str:
        return self._provider.name

    @property
    def budget(self) -> BudgetGuard:
        return self._budget

    def model_for(self, tier: ModelTier) -> str:
        return self._provider.model_for(self._budget.effective_tier(tier))

    async def complete(
        self,
        *,
        system: str,
        user: str,
        tier: ModelTier,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        response = await self._provider.complete(
            system=system,
            user=user,
            tier=self._budget.effective_tier(tier),
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self._budget.record(response.usage)
        return response

    async def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[SchemaT],
        tier: ModelTier,
        temperature: float = 0.0,
    ) -> StructuredResponse[SchemaT]:
        response = await self._provider.complete_structured(
            system=system,
            user=user,
            schema=schema,
            tier=self._budget.effective_tier(tier),
            temperature=temperature,
        )
        self._budget.record(response.usage)
        return response

    def stream(
        self, *, system: str, user: str, tier: ModelTier, temperature: float = 0.0
    ) -> AsyncIterator[str]:
        return self._provider.stream(
            system=system,
            user=user,
            tier=self._budget.effective_tier(tier),
            temperature=temperature,
        )


def build_provider(settings: Settings) -> LLMProvider:
    """Construct the configured provider.

    Vendor SDKs are imported inside their adapters, so a deployment running
    the mock never needs the OpenAI or Anthropic packages installed.
    """
    from app.core.settings import ProviderName
    from app.infrastructure.llm.mock_provider import MockProvider

    match settings.llm_provider:
        case ProviderName.OPENAI:
            return OpenAIProvider(
                api_key=settings.openai_api_key,
                fast_model=settings.openai_fast_model,
                premium_model=settings.openai_premium_model,
            )
        case ProviderName.ANTHROPIC:
            return AnthropicProvider(
                api_key=settings.anthropic_api_key,
                fast_model=settings.anthropic_fast_model,
                premium_model=settings.anthropic_premium_model,
            )
        case _:
            return MockProvider()
