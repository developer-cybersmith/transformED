"""
Google Gemini "Nano Banana" image generation provider implementation —
PRIMARY tier as of Story 5-8b (D121 migration).

Responsibilities
----------------
- Implements ImageProvider using Gemini's `generateContent` endpoint with
  `generationConfig.responseModalities: ["IMAGE"]` — a different request/
  response shape than Imagen's `predict`/`instances`/`predictions` (this is
  NOT a model-ID swap of the old ImagenProvider; see D121's own note that
  this "is not a simple model-ID swap").
- Returns a data:image/...;base64,... URI — the response embeds inline
  base64 image data at candidates[0].content.parts[*].inlineData.data (same
  reasoning as the other two providers: never a bare URL to re-fetch).
- Applies circuit breaker ("nano_banana" provider key) and retry decorator,
  same convention as OpenAIImageProvider/ImagenProvider.
- Authenticated via the `x-goog-api-key` HEADER (Gemini's documented
  convention) — UNLIKE ImagenProvider, which had to authenticate via a URL
  query parameter and therefore needed to sanitize the key out of every
  httpx exception's message before it could reach a log/trace. Because the
  key here never appears in the request URL, that whole sanitization dance
  is not needed — httpx exception messages embed the URL, not headers.
- Deliberately does NOT accumulate cost itself — same reasoning as the other
  two providers (see openai_image.py's module docstring): cost is recorded
  by the caller (image_generator_node) only after a successful Supabase
  upload, not here.

VERIFICATION NOTE (same caveat this codebase already carries for every cost
estimate and API assumption elsewhere — e.g. imagen.py's COST_PER_IMAGE,
D120's original size-literal bug): the exact request/response field names
below (`generationConfig.responseModalities`, `generationConfig.imageConfig
.aspectRatio`) are this migration's best-verified understanding of Gemini's
current image-generation API, cross-checked against two independent sources
at implementation time, but have NOT been exercised against a live API call
in this codebase. Confirm with one real live call before this reaches
production traffic — the same class of gap D121 itself flagged for the
Imagen endpoint it replaces ("nothing here calls it live").
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from langfuse import Langfuse

from app.core.circuit_breaker import CircuitOpenError, guard_breaker, is_circuit_open
from app.core.langfuse import deterministic_trace_context, get_langfuse, safe_trace
from app.core.retry import with_retry
from app.providers.base import ImageProvider

logger = logging.getLogger(__name__)

_PROVIDER_KEY = "nano_banana"

# Gemini's documented "workhorse" image-generation tier as of this migration
# (Story 5-8b) — see module docstring's verification note. Kept as a single
# named constant so a tier change (e.g. to gemini-3-pro-image for higher
# quality, or gemini-3.1-flash-lite-image for lower cost) is a one-line edit.
_NANO_BANANA_MODEL = "gemini-3.1-flash-image"
_NANO_BANANA_URL = (
    f"https://generativelanguage.googleapis.com/v1/models/{_NANO_BANANA_MODEL}:generateContent"
)

# Nano Banana pricing (USD per image) — documented placeholder, not a
# verified invoiced rate (same caveat as the other two providers' estimates).
# Keyed by size string to match OpenAIImageProvider's COST_PER_IMAGE shape
# (graph.py's cost-accounting branch looks this up the same way for both).
COST_PER_IMAGE: dict[str, float] = {"1280x720": 0.067}
_DEFAULT_COST_PER_IMAGE = 0.067

# Same aspect-ratio enum and nearest-match approach as ImagenProvider's
# _closest_aspect_ratio (D118/D122) — Gemini's image config also takes an
# aspect-ratio enum, not raw pixel dimensions. Reusing the identical
# well-tested computed-nearest-match technique rather than a second
# hardcoded {size: ratio} table that could go stale independently.
_ASPECT_RATIOS: dict[str, float] = {
    "1:1": 1.0,
    "3:4": 3 / 4,
    "4:3": 4 / 3,
    "9:16": 9 / 16,
    "16:9": 16 / 9,
}
_DEFAULT_ASPECT_RATIO = "1:1"


def _closest_aspect_ratio(size: str) -> str:
    """ "WxH" -> Gemini's nearest valid aspect-ratio enum value.

    Falls back to `_DEFAULT_ASPECT_RATIO` on anything unparseable — a
    malformed size degrading to square (wrong shape, right content) beats
    failing the whole slide, same reasoning as the fallback tier this
    provider replaces as primary."""
    try:
        w_str, h_str = size.lower().split("x")
        ratio = int(w_str) / int(h_str)
    except (ValueError, ZeroDivisionError):
        return _DEFAULT_ASPECT_RATIO
    return min(_ASPECT_RATIOS, key=lambda k: abs(_ASPECT_RATIOS[k] - ratio))


class NanoBananaProvider(ImageProvider):
    """Primary image provider — Google Gemini "Nano Banana" (Story 5-8b)."""

    def __init__(self, lesson_id: str | None = None) -> None:
        from app.config import get_settings

        settings = get_settings()
        self._api_key = settings.google_api_key
        # Explicit httpx.Timeout, NEVER a bare float — a bare float sets
        # connect= to the same value, destroying the 5s connect guard and
        # making a connect hang strictly worse (same rationale as
        # openai_image.py's identical comment; review finding, Story 5-8b:
        # this file originally copied imagen.py's bare `timeout=30.0`
        # verbatim, which was fine for an occasional fallback call but not
        # for this file's new PRIMARY role, hit on every slide).
        self._timeout = httpx.Timeout(settings.google_image_request_timeout_s, connect=5.0)
        self._lesson_id = lesson_id
        self._langfuse: Langfuse | None
        try:
            self._langfuse = get_langfuse()
        except Exception:
            logger.warning(
                "Langfuse init failed — tracing disabled for NanoBananaProvider",
                exc_info=True,
            )
            self._langfuse = None

    async def generate(
        self,
        prompt: str,
        size: str = "1024x1024",
    ) -> str:
        """Generate an image, recording exactly one breaker outcome (same
        contract as the other two providers). See `_generate_inner` for the
        full contract."""
        return await guard_breaker(_PROVIDER_KEY, lambda: self._generate_inner(prompt, size))

    @with_retry(max_attempts=2)
    async def _generate_inner(
        self,
        prompt: str,
        size: str = "1024x1024",
    ) -> str:
        """Generate an image with Gemini "Nano Banana" and return a data: URI.

        Args:
            prompt: Natural-language description.
            size:   Any "WxH" pixel-dimension string, same contract as the
                    other two providers. Translated to Gemini's own
                    aspect-ratio enum via `_closest_aspect_ratio`. An
                    unparseable size string falls back to "1:1" rather than
                    raising.

        Returns:
            ``data:image/png;base64,<...>``.

        Raises:
            RuntimeError: on any non-2xx response or transport failure.
            ValueError: if the response has no image data.
        """
        # Checked on EVERY attempt, same as the other two providers.
        if await is_circuit_open(_PROVIDER_KEY):
            raise CircuitOpenError(
                f"Circuit breaker OPEN for provider '{_PROVIDER_KEY}' — call rejected"
            )

        generation = None
        langfuse = self._langfuse
        if langfuse is not None:
            generation = safe_trace(
                lambda: langfuse.start_observation(
                    name="generate-image",
                    as_type="generation",
                    model=_NANO_BANANA_MODEL,
                    input=prompt,
                    metadata={"size": size, "lesson_id": self._lesson_id},
                    trace_context=deterministic_trace_context(langfuse, self._lesson_id),
                )
            )

        try:
            aspect_ratio = _closest_aspect_ratio(size)
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    _NANO_BANANA_URL,
                    headers={"x-goog-api-key": self._api_key or ""},
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {
                            "responseModalities": ["IMAGE"],
                            "imageConfig": {"aspectRatio": aspect_ratio},
                        },
                    },
                )
                response.raise_for_status()
                body: dict[str, Any] = response.json()

            candidates = body.get("candidates") or []
            parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
            inline_data = next((p.get("inlineData") for p in parts if p.get("inlineData")), None)
            if not inline_data or not inline_data.get("data"):
                raise ValueError("Nano Banana returned an empty response (no image data)")

            b64_data = inline_data["data"]
            mime_type = inline_data.get("mimeType", "image/png")

            if generation is not None:
                safe_trace(
                    lambda: generation.update(
                        output="1 image generated",
                        usage_details={"images": 1},
                        cost_details={"input": COST_PER_IMAGE.get(size, _DEFAULT_COST_PER_IMAGE)},
                    )
                )

            return f"data:{mime_type};base64,{b64_data}"

        except Exception as exc:
            if generation is not None:
                error_message = str(exc)
                safe_trace(lambda: generation.update(level="ERROR", status_message=error_message))
            raise

        finally:
            if generation is not None:
                safe_trace(generation.end)
