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
from langfuse import Langfuse

from app.core.circuit_breaker import CircuitOpenError, guard_breaker, is_circuit_open
from app.core.langfuse import deterministic_trace_context, get_langfuse, safe_trace
from app.core.retry import SanitizedHTTPError, with_retry
from app.providers.base import ImageProvider

logger = logging.getLogger(__name__)

_PROVIDER_KEY = "imagen"
# D121 (2026-08-18) — OPEN, NOT FIXED, flagged not silently patched: Google's
# own docs (ai.google.dev/gemini-api/docs/imagen, fetched 2026-08-18) state
# plainly "Imagen models are deprecated and will shut down on August 17,
# 2026" — i.e. AS OF YESTERDAY relative to this finding, this exact endpoint
# (imagen-4.0-fast-generate-001) returns HARD ERRORS, not a future warning.
# Google's recommended replacement (Gemini 2.5/3.1 Flash Image, "Nano
# Banana") is explicitly "not a simple model-ID swap... different generation
# interface, accepts more input types and charges by output resolution" —
# this needs a real migration, not a one-line endpoint change, and is a
# "Locked Technology Stack" (CLAUDE.md) decision requiring sign-off, not
# something to change unilaterally here. Until migrated, this fallback tier
# of the GPT Image -> Imagen -> text-only chain is effectively DEAD: every
# call trips the circuit breaker on repeated hard failures and every slide
# that reaches this tier degrades straight to text-only. See
# docs/DEFECT-REGISTER.md D121.
_IMAGEN_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-fast-generate-001:predict"
)

# Imagen 4 Fast pricing (USD per image) — documented placeholder, not a
# verified invoiced rate (same caveat as OpenAIImageProvider's estimate).
# Also now moot per D121 above until this provider is migrated.
COST_PER_IMAGE = 0.015

# D118 (2026-08-17): translates the same pixel-dimension `size` strings
# OpenAIImageProvider takes into Imagen's own `aspectRatio` request
# parameter (documented API field: "1:1", "3:4", "4:3", "9:16", "16:9" —
# confirmed 2026-08-18 against ai.google.dev's own Imagen docs). Before this,
# `size` was accepted for interface compatibility only and silently
# discarded, so this fallback provider always returned a square 1:1 image
# regardless of what the caller asked for.
#
# D122 (2026-08-18): this was originally a hardcoded {size: ratio} dict, and
# by this point it had ALREADY silently gone stale twice in one day — once
# when D120 corrected OpenAIImageProvider's real sizes out from under it,
# and it would have happened a THIRD time the moment graph.py's
# `_SLIDE_IMAGE_SIZE` moved to gpt-image-2's "1280x720". Replaced with a
# computed nearest-match: parse whatever "WxH" string the caller actually
# sends, compute its real ratio, and pick Imagen's closest enum value by
# numeric distance. This cannot go stale — there is no size-specific table
# left to forget to update.
_IMAGEN_ASPECT_RATIOS: dict[str, float] = {
    "1:1": 1.0,
    "3:4": 3 / 4,
    "4:3": 4 / 3,
    "9:16": 9 / 16,
    "16:9": 16 / 9,
}
_DEFAULT_ASPECT_RATIO = "1:1"


def _closest_aspect_ratio(size: str) -> str:
    """ "WxH" -> Imagen's nearest valid `aspectRatio` enum value.

    Falls back to `_DEFAULT_ASPECT_RATIO` on anything unparseable — this is
    the FALLBACK provider; a malformed size degrading to square (wrong
    shape, right content) beats failing the whole slide."""
    try:
        w_str, h_str = size.lower().split("x")
        ratio = int(w_str) / int(h_str)
    except (ValueError, ZeroDivisionError):
        return _DEFAULT_ASPECT_RATIO
    return min(_IMAGEN_ASPECT_RATIOS, key=lambda k: abs(_IMAGEN_ASPECT_RATIOS[k] - ratio))


class ImagenProvider(ImageProvider):
    """Fallback image provider — Google Imagen 4 Fast."""

    def __init__(self, lesson_id: str | None = None) -> None:
        from app.config import get_settings

        settings = get_settings()
        self._api_key = settings.google_api_key
        self._lesson_id = lesson_id
        self._langfuse: Langfuse | None
        try:
            self._langfuse = get_langfuse()
        except Exception:
            logger.warning(
                "Langfuse init failed — tracing disabled for ImagenProvider",
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
        """Generate an image with Imagen 4 Fast and return a data: URI.

        Args:
            prompt: Natural-language description.
            size:   Any "WxH" pixel-dimension string, same contract as
                    OpenAIImageProvider. Imagen 4 Fast's predict endpoint
                    takes an `aspectRatio` request parameter, not raw pixel
                    dimensions — translated via `_closest_aspect_ratio`
                    (D118, made size-agnostic in D122). An unparseable size
                    string falls back to `_DEFAULT_ASPECT_RATIO` ("1:1")
                    rather than raising — this is the FALLBACK provider, and
                    a request for a landscape image degrading to square
                    (correct content, wrong shape) beats a total failure.

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

        # Langfuse: started BEFORE the request so a failure is traced too.
        # CRITICAL — this provider's whole design exists to keep the API key
        # (embedded in the request URL, see class docstring) out of any log or
        # trace. `generation.update(..., status_message=...)` below ONLY ever
        # sees `str(exc)` on the SANITIZED SanitizedHTTPError this function
        # already raises — never the raw httpx exception, never `exc_info`.
        # Do not change that without re-reading the docstring above.
        generation = None
        langfuse = self._langfuse
        if langfuse is not None:
            generation = safe_trace(
                lambda: langfuse.start_observation(
                    # Same name as openai_image.py's primary observation
                    # (verb-first, provider-agnostic per Langfuse naming
                    # guidance) — `model="imagen-4-fast"` vs
                    # `"gpt-image-2"` distinguishes primary vs fallback.
                    name="generate-image",
                    as_type="generation",
                    model="imagen-4-fast",
                    input=prompt,
                    metadata={"size": size, "lesson_id": self._lesson_id},
                    trace_context=deterministic_trace_context(langfuse, self._lesson_id),
                )
            )

        try:
            # Built inside the `except` below, raised AFTER it — see the long
            # note there. `sanitized` is the whole reason this control flow
            # looks odd.
            sanitized: SanitizedHTTPError | None = None

            aspect_ratio = _closest_aspect_ratio(size)
            async with httpx.AsyncClient(timeout=30.0) as client:
                try:
                    response = await client.post(
                        f"{_IMAGEN_URL}?key={self._api_key}",
                        json={
                            "instances": [{"prompt": prompt}],
                            "parameters": {"sampleCount": 1, "aspectRatio": aspect_ratio},
                        },
                    )
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    # Redact the key before this exception (or anything that
                    # wraps it) can be logged with exc_info=True anywhere
                    # upstream — httpx's own exception message/repr embeds the
                    # full request URL, key included.
                    #
                    # Story 2-32 AC-5: SanitizedHTTPError, not a bare
                    # RuntimeError. Carrying the status code lets with_retry
                    # apply the PRD §14 rules to a REDACTED error — previously
                    # every failure here, including a retryable 429/503, was
                    # unclassifiable and therefore fatal, which made this
                    # provider's @with_retry decorative. The status code is
                    # metadata, not the URL.
                    #
                    # httpx.HTTPError also covers TimeoutException/NetworkError,
                    # which have no `.response` and therefore no status. Those
                    # are transport failures — the MOST common transient
                    # failure of an outbound call — so they are flagged
                    # retryable explicitly rather than falling into the
                    # status-less "cannot classify, do not retry" branch
                    # (2026-07-29 review finding).
                    status_code = getattr(getattr(exc, "response", None), "status_code", None)
                    sanitized = SanitizedHTTPError(
                        f"Imagen 4 Fast request failed: {type(exc).__name__} "
                        f"(status={status_code if status_code is not None else 'n/a'})",
                        status_code=status_code,
                        network_error=isinstance(exc, httpx.TimeoutException | httpx.NetworkError),
                    )

                # RAISED OUTSIDE THE `except` BLOCK, DELIBERATELY. `raise ...
                # from None` inside it would set __cause__ = None and
                # __suppress_context__ = True, but the raise statement STILL
                # binds __context__ to the httpx exception — whose
                # str()/repr() embed the key-bearing URL. Assigning
                # __context__ = None before the raise does not help; the
                # raise re-binds it. Only raising when no exception is active
                # leaves __context__ genuinely None.
                # Guarded by test_sanitized_error_does_not_retain_the_original_via_context.
                if sanitized is not None:
                    raise sanitized

                body: dict[str, Any] = response.json()

            predictions = body.get("predictions") or []
            if not predictions or not predictions[0].get("bytesBase64Encoded"):
                raise ValueError("Imagen 4 Fast returned an empty response (no predictions)")

            b64_data = predictions[0]["bytesBase64Encoded"]

            if generation is not None:
                safe_trace(
                    lambda: generation.update(
                        output="1 image generated",
                        usage_details={"images": 1},
                        cost_details={"input": COST_PER_IMAGE},
                    )
                )

            return f"data:image/png;base64,{b64_data}"

        except Exception as exc:
            # `str(exc)` here is safe: by this point the only exceptions that
            # can reach this frame are SanitizedHTTPError (already redacted),
            # CircuitOpenError, or ValueError — never the raw httpx exception,
            # which is fully consumed inside the except block above.
            if generation is not None:
                error_message = str(exc)
                safe_trace(lambda: generation.update(level="ERROR", status_message=error_message))
            raise

        finally:
            if generation is not None:
                safe_trace(generation.end)
