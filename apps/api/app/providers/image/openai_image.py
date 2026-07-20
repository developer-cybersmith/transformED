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

from openai import AsyncOpenAI

from app.core.circuit_breaker import is_circuit_open, record_failure, record_success
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
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._lesson_id = lesson_id

    @with_retry(max_attempts=2)
    async def generate(
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
        if await is_circuit_open(_PROVIDER_KEY):
            raise RuntimeError(
                f"Circuit breaker OPEN for provider '{_PROVIDER_KEY}' — call rejected"
            )

        try:
            response = await self._client.images.generate(
                model="gpt-image-1-mini",
                prompt=prompt,
                size=size,  # type: ignore[arg-type]
                n=1,
            )

            b64_json = getattr(response.data[0], "b64_json", None)
            if not b64_json:
                raise ValueError("GPT Image 1 Mini returned an empty response (no b64_json)")

            await record_success(_PROVIDER_KEY)
            return f"data:image/png;base64,{b64_json}"

        except Exception:
            await record_failure(_PROVIDER_KEY)
            raise
