"""
DALL-E 3 image generation provider implementation.

Responsibilities
----------------
- Implements ImageProvider using OpenAI's DALL-E 3 endpoint.
- Applies circuit breaker (``dalle`` provider key).
- Returns the CDN URL returned by OpenAI — callers are responsible for
  downloading and re-uploading to Supabase Storage for persistence.
"""

from __future__ import annotations

import logging
from typing import Literal

from openai import AsyncOpenAI

from app.core.circuit_breaker import is_circuit_open, record_failure, record_success
from app.core.retry import with_retry
from app.providers.base import ImageProvider

logger = logging.getLogger(__name__)

_PROVIDER_KEY = "dalle"

ImageSize = Literal["1024x1024", "1792x1024", "1024x1792"]
ImageQuality = Literal["standard", "hd"]


class DalleImageProvider(ImageProvider):
    """Production image provider backed by OpenAI DALL-E 3."""

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
        quality: ImageQuality = "standard",
        style: Literal["vivid", "natural"] = "vivid",
    ) -> str:
        """Generate an image with DALL-E 3 and return the CDN URL.

        Args:
            prompt:  Natural-language description (max ~4000 chars for DALL-E 3).
            size:    One of ``"1024x1024"``, ``"1792x1024"``, ``"1024x1792"``.
            quality: ``"standard"`` or ``"hd"`` (hd doubles cost).
            style:   ``"vivid"`` (hyper-real) or ``"natural"`` (less dramatic).

        Returns:
            Temporary OpenAI CDN URL — expires after ~1 hour.  Download and
            upload to Supabase Storage before persisting.
        """
        if await is_circuit_open(_PROVIDER_KEY):
            raise RuntimeError(f"Circuit breaker OPEN for provider '{_PROVIDER_KEY}' — call rejected")

        try:
            response = await self._client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size=size,  # type: ignore[arg-type]
                quality=quality,
                style=style,
                n=1,
            )

            url = response.data[0].url
            if not url:
                raise ValueError("DALL-E 3 returned an empty URL")

            logger.debug("DALL-E 3 image generated for lesson=%s  size=%s", self._lesson_id, size)

            # Accumulate cost ($0.04 standard 1024x1024, $0.08 hd)
            await self._maybe_accumulate_cost(size, quality)

            await record_success(_PROVIDER_KEY)
            return url

        except Exception:
            await record_failure(_PROVIDER_KEY)
            raise

    async def _maybe_accumulate_cost(self, size: str, quality: ImageQuality) -> None:
        if self._lesson_id is None:
            return

        # DALL-E 3 pricing (USD per image, as of 2024-Q4)
        cost_map: dict[str, dict[ImageQuality, float]] = {
            "1024x1024": {"standard": 0.040, "hd": 0.080},
            "1792x1024": {"standard": 0.080, "hd": 0.120},
            "1024x1792": {"standard": 0.080, "hd": 0.120},
        }
        cost = cost_map.get(size, {}).get(quality, 0.040)

        from app.core.cost_tracker import accumulate_cost, check_ceiling  # lazy

        total = await accumulate_cost(self._lesson_id, cost)
        if await check_ceiling(self._lesson_id):
            raise RuntimeError(
                f"Lesson {self._lesson_id} exceeded cost ceiling at ${total:.4f} — pipeline aborted"
            )
