"""
Google Imagen 4 Fast image generation provider implementation — fallback tier.

Responsibilities
----------------
- Implements ImageProvider using Google's Generative Language API Imagen 4
  Fast predict endpoint.
- Returns a data:image/png;base64,... URI — Imagen's REST response is also
  base64-encoded, not a URL (same reasoning as OpenAIImageProvider).
- Applies circuit breaker ("imagen" provider key) and retry decorator.
- Authenticated via an API-key QUERY PARAMETER (Google's documented pattern
  for this API) — NOT an Authorization header.
- 2026-07-15 review finding (Blind Hunter, CRITICAL): because the API key
  lives in the request URL, any httpx exception (HTTPStatusError, network
  errors) embeds the full URL — including the live key — in its message.
  This provider catches httpx-level exceptions and re-raises a SANITIZED
  RuntimeError with the key stripped, so the raw exception (and its key)
  never reaches the caller's logs (this codebase logs provider failures with
  exc_info=True, which would otherwise ship the key to Sentry/Langfuse/OTel
  on the very first real HTTP error — a routine occurrence, not an edge case).
- Deliberately does NOT accumulate cost itself — see openai_image.py's
  module docstring for why (2026-07-15 review finding).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.circuit_breaker import is_circuit_open, record_failure, record_success
from app.core.retry import with_retry
from app.providers.base import ImageProvider

logger = logging.getLogger(__name__)

_PROVIDER_KEY = "imagen"
_IMAGEN_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "imagen-4.0-fast-generate-001:predict"
)

# Imagen 4 Fast pricing (USD per image) — documented placeholder, not a
# verified invoiced rate (same caveat as OpenAIImageProvider's estimate).
COST_PER_IMAGE = 0.015


class ImagenProvider(ImageProvider):
    """Fallback image provider — Google Imagen 4 Fast."""

    def __init__(self, lesson_id: str | None = None) -> None:
        from app.config import get_settings

        settings = get_settings()
        self._api_key = settings.google_api_key
        self._lesson_id = lesson_id

    @with_retry(max_attempts=2)
    async def generate(
        self,
        prompt: str,
        size: str = "1024x1024",
    ) -> str:
        """Generate an image with Imagen 4 Fast and return a data: URI.

        Args:
            prompt: Natural-language description.
            size:   Accepted for ImageProvider interface compatibility;
                    Imagen 4 Fast's predict endpoint does not take an
                    explicit size parameter in this request shape.

        Returns:
            ``data:image/png;base64,<...>``.

        Raises:
            RuntimeError: with the API key redacted — see module docstring.
        """
        if await is_circuit_open(_PROVIDER_KEY):
            raise RuntimeError(f"Circuit breaker OPEN for provider '{_PROVIDER_KEY}' — call rejected")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                try:
                    response = await client.post(
                        f"{_IMAGEN_URL}?key={self._api_key}",
                        json={"instances": [{"prompt": prompt}], "parameters": {"sampleCount": 1}},
                    )
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    # Redact the key before this exception (or anything that
                    # wraps it) can be logged with exc_info=True anywhere
                    # upstream — httpx's own exception message/repr embeds
                    # the full request URL, key included.
                    raise RuntimeError(
                        f"Imagen 4 Fast request failed: {type(exc).__name__} "
                        f"(status={getattr(getattr(exc, 'response', None), 'status_code', 'n/a')})"
                    ) from None

                body: dict[str, Any] = response.json()

            predictions = body.get("predictions") or []
            if not predictions or not predictions[0].get("bytesBase64Encoded"):
                raise ValueError("Imagen 4 Fast returned an empty response (no predictions)")

            b64_data = predictions[0]["bytesBase64Encoded"]

            await record_success(_PROVIDER_KEY)
            return f"data:image/png;base64,{b64_data}"

        except Exception:
            await record_failure(_PROVIDER_KEY)
            raise
