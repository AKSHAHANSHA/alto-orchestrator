"""Groq adapter, used for one job: phrasing clarifying questions.

Deliberately *not* a full `LLMProvider`. The understanding layer needs
schema-enforced structured output and the generator needs the budget-guarded
router; neither wants a third vendor in the path. Clarification is different
— it is a single short sentence, it runs constantly, and it has a correct
deterministic answer to fall back to. That combination is what makes a free
key on a small open-weights model the right fit here and the wrong fit
everywhere else.

Groq serves an OpenAI-compatible API, so this reuses the `openai` SDK the
project already depends on rather than adding a vendor SDK. That is most of
why it replaced the Gemini adapter: same job, one less dependency, and none
of the vendor-specific thinking-budget handling that made the previous
version fragile.

Every call is bounded by a timeout. A clarifying question is on the critical
path of a customer waiting for a reply, and a hung request is strictly worse
than the template we already have in hand.
"""

from __future__ import annotations

import asyncio

from app.core.logging import get_logger
from app.domain.ports import LLMResponse
from app.infrastructure.llm.registry import compute_usage

logger = get_logger(__name__)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class GroqClarifier:
    """Phrases one clarifying question. Returns JSON; raises on any failure.

    Raising rather than degrading is intentional — the caller owns the
    fallback, and burying it here would hide how often the model path is
    actually being used.
    """

    name = "groq"

    def __init__(
        self, *, api_key: str, model: str, timeout_seconds: float = 4.0
    ) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key, base_url=GROQ_BASE_URL)
        self._model = model
        self._timeout = timeout_seconds

    @property
    def model(self) -> str:
        return self._model

    async def phrase(self, *, system: str, user: str) -> LLMResponse:
        response = await asyncio.wait_for(
            self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                # Warm enough not to read like a form field, cold enough not
                # to wander off the question it was asked to ask.
                temperature=0.4,
                max_tokens=400,
                # Groq honours OpenAI's JSON mode across the open-weights
                # models, which is what keeps the caller's parser strict
                # rather than lenient.
                response_format={"type": "json_object"},
            ),
            timeout=self._timeout,
        )

        usage = response.usage
        return LLMResponse(
            text=response.choices[0].message.content or "",
            model=self._model,
            provider=self.name,
            usage=compute_usage(
                self._model,
                usage.prompt_tokens if usage else 0,
                usage.completion_tokens if usage else 0,
            ),
        )
