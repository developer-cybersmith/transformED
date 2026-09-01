"""
GPT Image 2 image generation provider implementation.

Responsibilities
----------------
- Implements ImageProvider using OpenAI's GPT Image 2 endpoint.
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

D122 (2026-08-18): migrated from gpt-image-1-mini to gpt-image-2, decided by
the team, not a silent side effect of a bug fix. Two independent reasons,
either alone would have justified it:
  1. gpt-image-1-mini is scheduled for API removal 2026-12-01 (confirmed
     directly against developers.openai.com/api/docs/deprecations) — the
     SAME retirement pattern that already killed DALL-E 3 on this codebase
     once (CLAUDE.md's own "DALL-E 3 DEAD" note).
  2. gpt-image-1-mini's `size` parameter only ever offered 3 fixed presets
     (1024x1024, 1536x1024, 1024x1536), none of them exactly 16:9 — every
     slide image needed a post-generation crop (`_crop_to_16_9` in
     graph.py) to reach the aspect ratio the player actually wants.
     gpt-image-2 supports genuinely custom/arbitrary dimensions (confirmed:
     max edge <=3840px, both edges multiples of 16px, long:short ratio
     <=3:1, total pixels 655,360-8,294,400) — "1280x720" satisfies all four
     constraints AND is exactly 16:9 (1280*9 == 720*16), so the crop step
     becomes a no-op on the primary path and only matters for whatever the
     fallback provider returns.
"""

from __future__ import annotations

import logging

import httpx
from langfuse import Langfuse
from openai import AsyncOpenAI

from app.core.circuit_breaker import CircuitOpenError, guard_breaker, is_circuit_open
from app.core.langfuse import deterministic_trace_context, get_langfuse, safe_trace
from app.core.retry import with_retry
from app.providers.base import ImageProvider

logger = logging.getLogger(__name__)

_PROVIDER_KEY = "gpt_image"
_MODEL = "gpt-image-2"

# gpt-image-2's documented custom-size constraints (confirmed directly
# against developers.openai.com/api/docs/guides/image-generation,
# 2026-08-18) — validated BEFORE the request goes out, not discovered as an
# API 400 mid-call. "Never clamp silently" (this repo's own convention,
# e.g. extract_subprocess.py's page-range contract): an out-of-bounds size
# is a caller bug and must raise, not be coerced into something that
# happens to fit.
_MAX_EDGE_PX = 3840
_EDGE_MULTIPLE_PX = 16
_MAX_LONG_SHORT_RATIO = 3.0
_MIN_TOTAL_PX = 655_360
_MAX_TOTAL_PX = 8_294_400


def _validate_size(size: str) -> tuple[int, int]:
    """Parse and validate a "WxH" size string against gpt-image-2's real
    constraints. Returns (width, height) on success; raises ValueError
    naming exactly which constraint failed, never silently clamped."""
    try:
        w_str, h_str = size.lower().split("x")
        width, height = int(w_str), int(h_str)
    except ValueError as exc:
        raise ValueError(f"malformed size string (expected 'WxH'): {size!r}") from exc
    if width <= 0 or height <= 0:
        raise ValueError(f"size dimensions must be positive: {size!r}")
    if max(width, height) > _MAX_EDGE_PX:
        raise ValueError(f"size {size!r} exceeds max edge {_MAX_EDGE_PX}px")
    if width % _EDGE_MULTIPLE_PX or height % _EDGE_MULTIPLE_PX:
        raise ValueError(f"size {size!r} edges must both be multiples of {_EDGE_MULTIPLE_PX}px")
    if max(width, height) / min(width, height) > _MAX_LONG_SHORT_RATIO:
        raise ValueError(f"size {size!r} exceeds max long:short ratio {_MAX_LONG_SHORT_RATIO}:1")
    total = width * height
    if not (_MIN_TOTAL_PX <= total <= _MAX_TOTAL_PX):
        raise ValueError(
            f"size {size!r} has {total} total px, outside [{_MIN_TOTAL_PX}, {_MAX_TOTAL_PX}]"
        )
    return width, height


# GPT Image 2 pricing (USD per image, "medium" quality) — an ESTIMATE, NOT a
# verified invoiced rate (same caveat this codebase already carries for
# every other cost table: TTS, and this file's own prior D120 correction).
# gpt-image-2 bills per TOKEN, not per discrete size/quality cell like
# gpt-image-1-mini did, and this environment cannot reach a live billing
# call or the official calculator to confirm an exact figure for
# "1280x720" specifically. $0.05 is a deliberately conservative (rounded
# UP, not down) estimate derived from published medium-quality figures for
# similarly-sized outputs (~$0.041-0.053 at ~1M-1.5M px) — revisit against
# a real invoice before trusting this near a genuinely tight budget.
COST_PER_IMAGE: dict[str, float] = {
    "1280x720": 0.05,
}
_DEFAULT_COST_PER_IMAGE = 0.05


class OpenAIImageProvider(ImageProvider):
    """Primary image provider — OpenAI GPT Image 2 (D122, migrated from
    GPT Image 1 Mini 2026-08-18)."""

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
        """Generate an image with GPT Image 2 and return a data: URI.

        Args:
            prompt: Natural-language description.
            size:   A "WxH" pixel-dimension string satisfying gpt-image-2's
                    real constraints — validated up front by `_validate_size`
                    (D122) so a bad value raises HERE, with a specific
                    reason, rather than surfacing as an opaque API 400 two
                    layers down.

        Returns:
            ``data:image/png;base64,<...>`` — see module docstring.

        Raises:
            ValueError: an invalid `size` (see `_validate_size`), or if the
                response has no usable image data. 2026-07-15 review finding
                (Blind Hunter + Edge Case Hunter): a prior version fell back
                to a speculative, untested `url` field ("in case a future
                API revision returns one") — that field is not decodable by
                the node's data-URI-only decoder and would have silently
                "succeeded" with a 0-byte image. GPT Image's documented
                behavior is `b64_json` only; removed the untested alternate
                path rather than leave a latent bug for a hypothetical case.
        """
        _validate_size(size)  # raises before any circuit-breaker/network work

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
                    model=_MODEL,
                    input=prompt,
                    metadata={"size": size, "lesson_id": self._lesson_id},
                    trace_context=deterministic_trace_context(langfuse, self._lesson_id),
                )
            )

        try:
            response = await self._client.images.generate(  # type: ignore[call-overload]
                model=_MODEL,
                prompt=prompt,
                size=size,
                quality="medium",  # D122: explicit, not the SDK's ambiguous
                # default — keeps COST_PER_IMAGE's estimate meaningful
                # (pricing varies 4-8x across low/medium/high) rather than
                # tracking spend against a tier nobody actually chose.
                n=1,
            )

            # response.data is typed Optional by the OpenAI SDK; None/empty means
            # no usable image data — same ValueError the b64 check raises below.
            data = response.data
            if data is None:
                raise ValueError(f"{_MODEL} returned an empty response (no b64_json)")

            b64_json = getattr(data[0], "b64_json", None)
            if not b64_json:
                raise ValueError(f"{_MODEL} returned an empty response (no b64_json)")

            if generation is not None:
                # Trace-only annotation, NOT the real cost accumulation (that
                # deliberately stays in image_generator_node, only after a
                # successful Storage upload -- see module docstring). Same
                # COST_PER_IMAGE the node itself uses, so the two never disagree.
                image_cost = COST_PER_IMAGE.get(size, _DEFAULT_COST_PER_IMAGE)
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
