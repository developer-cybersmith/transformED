"""
OpenAI LLM provider implementation.

Responsibilities
----------------
- Implements LLMProvider using the ``openai`` async client.
- Tracks token usage via Langfuse for cost observability.
- Applies circuit breaker (``openai`` provider key) before every call.
- Integrates with the cost tracker to accumulate per-lesson spend.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

from app.config import get_settings
from app.core.circuit_breaker import is_circuit_open, record_failure, record_success
from app.core.langfuse import get_langfuse
from app.core.retry import with_retry
from app.providers.base import LLMProvider

logger = logging.getLogger(__name__)

_PROVIDER_KEY = "openai"

# Approximate cost per 1 000 tokens (USD) — used for cost tracking estimates.
# Update these when OpenAI changes pricing.
_COST_PER_1K: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "gpt-4o-mini": {"input": 0.000150, "output": 0.000600},
}


def _safe_trace(call: Callable[[], Any]) -> Any | None:
    """Run a Langfuse tracing call; observability failures must NEVER fail the pipeline."""
    try:
        return call()
    except Exception:
        # WARNING (not DEBUG): an observability outage must be visible in prod
        # logs even though it never fails the pipeline.
        logger.warning("Langfuse tracing call failed — ignored, pipeline continues", exc_info=True)
        return None


class OpenAILLMProvider(LLMProvider):
    """Production LLM provider backed by OpenAI."""

    def __init__(self, lesson_id: str | None = None) -> None:
        settings = get_settings()
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        # AC-3 never-fail clause: a bad LANGFUSE_* env must degrade to
        # no-tracing, never crash the provider mid-job.
        try:
            self._langfuse = get_langfuse()
        except Exception:
            logger.warning(
                "Langfuse init failed — tracing disabled for OpenAILLMProvider",
                exc_info=True,
            )
            self._langfuse = None
        self._lesson_id = lesson_id

    @with_retry(max_attempts=3)
    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        **kwargs: Any,
    ) -> str:
        """Return a plain-text chat completion from OpenAI."""
        if await is_circuit_open(_PROVIDER_KEY):
            raise RuntimeError(f"Circuit breaker OPEN for provider '{_PROVIDER_KEY}' — call rejected")

        # Langfuse 4.x (OTel-based): one generation-type observation per call.
        # Tracing is best-effort — the OpenAI call must never fail because of it.
        # self._langfuse is None when init failed (AC-3) — skip tracing entirely.
        generation = None
        if self._langfuse is not None:
            generation = _safe_trace(
                lambda: self._langfuse.start_observation(
                    name="openai.chat",
                    as_type="generation",
                    model=model,
                    input=messages,
                    metadata={"model": model, "lesson_id": self._lesson_id},
                )
            )

        try:
            response: ChatCompletion = await self._client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                **kwargs,
            )
            content = response.choices[0].message.content or ""

            # Cost accumulation reads response.usage directly — never depends on tracing.
            if response.usage:
                if generation is not None:
                    _safe_trace(
                        lambda: generation.update(
                            output=content,
                            usage_details={
                                "input": response.usage.prompt_tokens,
                                "output": response.usage.completion_tokens,
                            },
                        )
                    )
                await self._maybe_accumulate_cost(model, response.usage.prompt_tokens, response.usage.completion_tokens)

            await record_success(_PROVIDER_KEY)
            return content

        except Exception as exc:
            if generation is not None:
                error_message = str(exc)
                _safe_trace(
                    lambda: generation.update(level="ERROR", status_message=error_message)
                )
            await record_failure(_PROVIDER_KEY)
            raise

        finally:
            if generation is not None:
                _safe_trace(generation.end)

    @with_retry(max_attempts=3)
    async def complete_structured(
        self,
        messages: list[dict[str, str]],
        model: str,
        response_format: type,
        **kwargs: Any,
    ) -> Any:
        """Return a structured completion parsed into *response_format* (a Pydantic model)."""
        if await is_circuit_open(_PROVIDER_KEY):
            raise RuntimeError(f"Circuit breaker OPEN for provider '{_PROVIDER_KEY}' — call rejected")

        # self._langfuse is None when init failed (AC-3) — skip tracing entirely.
        generation = None
        if self._langfuse is not None:
            generation = _safe_trace(
                lambda: self._langfuse.start_observation(
                    name="openai.chat.structured",
                    as_type="generation",
                    model=model,
                    input=messages,
                    metadata={
                        "model": model,
                        "response_format": response_format.__name__,
                        "lesson_id": self._lesson_id,
                    },
                )
            )

        try:
            # Use OpenAI's beta structured-output parse helper
            response = await self._client.beta.chat.completions.parse(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                response_format=response_format,  # type: ignore[arg-type]
                **kwargs,
            )
            parsed = response.choices[0].message.parsed

            # Cost accumulation reads response.usage directly — never depends on tracing.
            if response.usage:
                if generation is not None:
                    _safe_trace(
                        lambda: generation.update(
                            output=str(parsed),
                            usage_details={
                                "input": response.usage.prompt_tokens,
                                "output": response.usage.completion_tokens,
                            },
                        )
                    )
                await self._maybe_accumulate_cost(model, response.usage.prompt_tokens, response.usage.completion_tokens)

            await record_success(_PROVIDER_KEY)
            return parsed

        except Exception as exc:
            if generation is not None:
                error_message = str(exc)
                _safe_trace(
                    lambda: generation.update(level="ERROR", status_message=error_message)
                )
            await record_failure(_PROVIDER_KEY)
            raise

        finally:
            if generation is not None:
                _safe_trace(generation.end)

    async def _maybe_accumulate_cost(self, model: str, input_tokens: int, output_tokens: int) -> None:
        """Accumulate cost for the current lesson if a lesson_id is set."""
        if self._lesson_id is None:
            return

        pricing = _COST_PER_1K.get(model)
        if pricing is None:
            logger.warning("No pricing data for model '%s' — cost not tracked", model)
            return

        cost = (input_tokens / 1000 * pricing["input"]) + (output_tokens / 1000 * pricing["output"])

        from app.core.cost_tracker import accumulate_cost, check_ceiling  # lazy to avoid circular

        total = await accumulate_cost(self._lesson_id, cost)
        if await check_ceiling(self._lesson_id):
            raise RuntimeError(
                f"Lesson {self._lesson_id} exceeded cost ceiling at ${total:.4f} — pipeline aborted"
            )
