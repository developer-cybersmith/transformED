"""
GPT Image 1 Mini image generation provider implementation.

Responsibilities
----------------
- Implements ImageProvider using OpenAI's GPT Image 1 Mini endpoint.
- GPT Image models return base64-encoded image data (b64_json), not a CDN
  URL like DALL-E did — encoded here as a data:image/png;base64,... URI so
  the return value still satisfies ImageProvider.generate()'s -> str
  contract (Story 2-9 AC-4).
- Applies circuit breaker ("gpt_image" provider key) and retry decorator.
- Deliberately does NOT accumulate cost itself (2026-07-15 review finding —
  Blind Hunter + Edge Case Hunter + Acceptance Auditor, independently): the
  old dalle.py template accumulated cost internally and raised on a ceiling
  breach mid-call, which discarded an already-successful, already-paid-for
  image and misclassified it as a provider failure. image_generator_node
  now accumulates cost itself, only after a successful Storage upload —
  matching tts_node's established pattern (its TTS providers don't
  self-accumulate cost either). COST_PER_IMAGE below is exposed for the
  node to use in that calculation.
"""

from __future__ import annotations

import logging
from typing import Literal

import httpx
from langfuse import Langfuse
from openai import AsyncOpenAI

from app.core.circuit_breaker import CircuitOpenError, guard_breaker, is_circuit_open
from app.core.langfuse import deterministic_trace_context, get_langfuse, safe_trace
from app.core.retry import with_retry
from app.providers.base import ImageProvider

logger = logging.getLogger(__name__)

_PROVIDER_KEY = "gpt_image"

ImageSize = Literal["1024x1024", "1792x1024", "1024x1792"]

# GPT Image 1 Mini pricing (USD per image) — documented placeholder, not a
# verified invoiced rate (same caveat as Story 2-8's TTS cost estimates: this
# environment cannot reach the real billing API to confirm exact numbers).
COST_PER_IMAGE: dict[str, float] = {
    "1024x1024": 0.02,
    "1792x1024": 0.03,
    "1024x1792": 0.03,
}


class OpenAIImageProvider(ImageProvider):
    """Primary image provider — OpenAI GPT Image 1 Mini."""

    def __init__(self, lesson_id: str | None = None) -> None:
        from app.config import get_settings

        settings = get_settings()
        # Story 2-32: max_retries=0 — the SDK defaults to 2, so layering
        # with_retry(max_attempts=N) on top of it means N x 3 HTTP requests per
        # logical call with two independent backoff schedules. `core/retry.py` is
        # the only layer that knows the PRD §14 rules and the circuit-breaker
        # state, so it owns retry entirely.
        #
        # Timeout is an explicit httpx.Timeout, NEVER a bare float: a bare float
        # sets connect= to the same value, replacing the SDK's 5s connect guard
        # with (here) 120s and making a connect hang strictly worse.
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            max_retries=0,
            timeout=httpx.Timeout(settings.openai_image_request_timeout_s, connect=5.0),
        )
        self._lesson_id = lesson_id
        self._langfuse: Langfuse | None
        try:
            self._langfuse = get_langfuse()
        except Exception:
            logger.warning(
                "Langfuse init failed — tracing disabled for OpenAIImageProvider",
                exc_info=True,
            )
            self._langfuse = None

    async def generate(
        self,
        prompt: str,
        size: str = "1024x1024",
    ) -> str:
        """Generate an image, recording exactly one breaker outcome (Story 2-32
        AC-3). See `_generate_inner` for the full contract."""
        return await guard_breaker(_PROVIDER_KEY, lambda: self._generate_inner(prompt, size))

    @with_retry(max_attempts=2)
    async def _generate_inner(
        self,
        prompt: str,
        size: str = "1024x1024",
    ) -> str:
        """Generate an image with GPT Image 1 Mini and return a data: URI.

        Args:
            prompt: Natural-language description.
            size:   One of "1024x1024", "1792x1024", "1024x1792".

        Returns:
            ``data:image/png;base64,<...>`` — see module docstring.

        Raises:
            ValueError: if the response has no usable image data. 2026-07-15
                review finding (Blind Hunter + Edge Case Hunter): a prior
                version fell back to a speculative, untested `url` field
                ("in case a future API revision returns one") — that field
                is not decodable by the node's data-URI-only decoder and
                would have silently "succeeded" with a 0-byte image. GPT
                Image 1 Mini's actual documented behavior is `b64_json`
                only; removed the untested alternate path rather than leave
                a latent bug for a hypothetical case.
        """
        # Checked on EVERY attempt (AC-4).
        if await is_circuit_open(_PROVIDER_KEY):
            raise CircuitOpenError(
                f"Circuit breaker OPEN for provider '{_PROVIDER_KEY}' — call rejected"
            )

        generation = None
        langfuse = self._langfuse
        if langfuse is not None:
            generation = safe_trace(
                lambda: langfuse.start_observation(
                    # Verb-first, model-agnostic name (Langfuse naming
                    # guidance, best-practices.md).
                    name="generate-image",
                    as_type="generation",
                    model="gpt-image-1-mini",
                    input=prompt,
                    metadata={"size": size, "lesson_id": self._lesson_id},
                    trace_context=deterministic_trace_context(langfuse, self._lesson_id),
                )
            )

        try:
            response = await self._client.images.generate(
                model="gpt-image-1-mini",
                prompt=prompt,
                size=size,
                n=1,
            )

            # response.data is typed Optional by the OpenAI SDK; None/empty means
            # no usable image data — same ValueError the b64 check raises below.
            data = response.data
            if data is None:
                raise ValueError("GPT Image 1 Mini returned an empty response (no b64_json)")

            b64_json = getattr(data[0], "b64_json", None)
            if not b64_json:
                raise ValueError("GPT Image 1 Mini returned an empty response (no b64_json)")

            if generation is not None:
                # Trace-only annotation, NOT the real cost accumulation (that
                # deliberately stays in image_generator_node, only after a
                # successful Storage upload -- see module docstring). Same
                # COST_PER_IMAGE the node itself uses, so the two never disagree.
                image_cost = COST_PER_IMAGE.get(size, COST_PER_IMAGE["1024x1024"])
                safe_trace(
                    lambda: generation.update(
                        output="1 image generated",
                        usage_details={"images": 1},
                        cost_details={"input": image_cost},
                    )
                )

            return f"data:image/png;base64,{b64_json}"

        except Exception as exc:
            if generation is not None:
                error_message = str(exc)
                safe_trace(lambda: generation.update(level="ERROR", status_message=error_message))
            raise

        finally:
            if generation is not None:
                safe_trace(generation.end)
