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

from app.core.circuit_breaker import CircuitOpenError, guard_breaker, is_circuit_open
from app.core.retry import SanitizedHTTPError, with_retry
from app.providers.base import ImageProvider

logger = logging.getLogger(__name__)

_PROVIDER_KEY = "imagen"
_IMAGEN_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-fast-generate-001:predict"
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
        # Checked on EVERY attempt (Story 2-32 AC-4).
        if await is_circuit_open(_PROVIDER_KEY):
            raise CircuitOpenError(
                f"Circuit breaker OPEN for provider '{_PROVIDER_KEY}' — call rejected"
            )

        # Built inside the `except` below, raised AFTER it — see the long note
        # there. `sanitized` is the whole reason this control flow looks odd.
        sanitized: SanitizedHTTPError | None = None

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    f"{_IMAGEN_URL}?key={self._api_key}",
                    json={"instances": [{"prompt": prompt}], "parameters": {"sampleCount": 1}},
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                # Redact the key before this exception (or anything that wraps
                # it) can be logged with exc_info=True anywhere upstream —
                # httpx's own exception message/repr embeds the full request
                # URL, key included.
                #
                # Story 2-32 AC-5: SanitizedHTTPError, not a bare RuntimeError.
                # Carrying the status code lets with_retry apply the PRD §14
                # rules to a REDACTED error — previously every failure here,
                # including a retryable 429/503, was unclassifiable and
                # therefore fatal, which made this provider's @with_retry
                # decorative. The status code is metadata, not the URL.
                #
                # httpx.HTTPError also covers TimeoutException/NetworkError,
                # which have no `.response` and therefore no status. Those are
                # transport failures — the MOST common transient failure of an
                # outbound call — so they are flagged retryable explicitly
                # rather than falling into the status-less "cannot classify,
                # do not retry" branch (2026-07-29 review finding).
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                sanitized = SanitizedHTTPError(
                    f"Imagen 4 Fast request failed: {type(exc).__name__} "
                    f"(status={status_code if status_code is not None else 'n/a'})",
                    status_code=status_code,
                    network_error=isinstance(exc, httpx.TimeoutException | httpx.NetworkError),
                )

            # RAISED OUTSIDE THE `except` BLOCK, DELIBERATELY. `raise ... from
            # None` inside it would set __cause__ = None and
            # __suppress_context__ = True, but the raise statement STILL binds
            # __context__ to the httpx exception — whose str()/repr() embed the
            # key-bearing URL. Assigning __context__ = None before the raise
            # does not help; the raise re-binds it. Only raising when no
            # exception is active leaves __context__ genuinely None.
            # Guarded by test_sanitized_error_does_not_retain_the_original_via_context.
            if sanitized is not None:
                raise sanitized

            body: dict[str, Any] = response.json()

        predictions = body.get("predictions") or []
        if not predictions or not predictions[0].get("bytesBase64Encoded"):
            raise ValueError("Imagen 4 Fast returned an empty response (no predictions)")

        b64_data = predictions[0]["bytesBase64Encoded"]

        return f"data:image/png;base64,{b64_data}"
