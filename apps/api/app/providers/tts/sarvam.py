"""
Sarvam AI Bulbul v2 TTS provider implementation.

Responsibilities
----------------
- Implements TTSProvider using Sarvam's Bulbul v2 text-to-speech HTTP API.
- Returns (audio_bytes, word_timestamps) tuples — timestamps always empty
  (Story 2-8 scope decision: slide-level timestamp mapping is deferred to a
  follow-up story; Narration.timestamps has no min_length constraint).
- Applies circuit breaker ("sarvam" provider key) and retry decorator.
- A 429 response body is inspected: "insufficient_quota_error" is NOT
  retryable (raised as a plain RuntimeError so with_retry's catch-all
  no-retry branch applies); any other 429 (e.g. "rate_limit_exceeded_error")
  is left to propagate as httpx.HTTPStatusError, which with_retry's default
  status-code classification already retries.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

import httpx
from langfuse import Langfuse

from app.core.circuit_breaker import CircuitOpenError, guard_breaker, is_circuit_open
from app.core.langfuse import deterministic_trace_context, get_langfuse, safe_trace
from app.core.retry import with_retry
from app.providers.base import TTSProvider

logger = logging.getLogger(__name__)

_PROVIDER_KEY = "sarvam"
_SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"

# Sarvam Bulbul v2 pricing (USD per character) — same figure tts_node's own
# cost-tracking uses (graph.py's _synthesize_with_fallback imports this
# constant rather than keeping a private duplicate, so there is one number,
# not two that can drift). Documented placeholder, not a verified invoiced
# rate — same caveat as every other provider's cost constant in this codebase.
COST_PER_CHAR = 0.00002


class SarvamTTSProvider(TTSProvider):
    """Primary TTS provider — Sarvam AI Bulbul v2."""

    def __init__(self, lesson_id: str | None = None) -> None:
        from app.config import get_settings

        settings = get_settings()
        self._api_key = settings.sarvam_api_key
        self._lesson_id = lesson_id
        # AC-3-equivalent never-fail clause (matches providers/llm/openai.py):
        # a bad LANGFUSE_* env must degrade to no-tracing, never crash the
        # provider mid-job.
        self._langfuse: Langfuse | None
        try:
            self._langfuse = get_langfuse()
        except Exception:
            logger.warning(
                "Langfuse init failed — tracing disabled for SarvamTTSProvider",
                exc_info=True,
            )
            self._langfuse = None

    async def synthesize(
        self,
        text: str,
        voice_id: str,
    ) -> tuple[bytes, list[dict[str, Any]]]:
        """Synthesise *text* with Sarvam Bulbul v2, recording exactly one breaker
        outcome per logical call (Story 2-32 AC-3).

        This provider's httpx errors were ALWAYS classified correctly, so unlike
        the OpenAI providers it always retried — and therefore always recorded
        `max_attempts` failures for a single logical call, tripping the breaker
        ~3x too fast. That is a pre-existing defect, not one introduced by
        Story 2-32; the accounting fix applies here for the same reason.
        The quota/rate-limit distinction below is unchanged.
        """
        return await guard_breaker(_PROVIDER_KEY, lambda: self._synthesize_inner(text, voice_id))

    @with_retry(max_attempts=3)
    async def _synthesize_inner(
        self,
        text: str,
        voice_id: str,
    ) -> tuple[bytes, list[dict[str, Any]]]:
        """Retried body of `synthesize`. Records NO breaker outcome.

        Args:
            text:     Narration text (one segment's script).
            voice_id: Sarvam speaker name (e.g. "meera").

        Returns:
            ``(audio_bytes, [])`` — Sarvam alignment data is not parsed into
            word timestamps in this story (see module docstring).
        """
        # Checked on EVERY attempt (Story 2-32 AC-4).
        if await is_circuit_open(_PROVIDER_KEY):
            raise CircuitOpenError(
                f"Circuit breaker OPEN for provider '{_PROVIDER_KEY}' — call rejected"
            )

        # Langfuse: one generation-type observation per attempt, matching
        # providers/llm/openai.py's existing tracing level (inside the
        # @with_retry body, so a retried call gets one observation per real
        # HTTP attempt, not one for the whole logical call). Best-effort —
        # self._langfuse is None when init failed; every Langfuse call below
        # goes through safe_trace so a tracing failure can never fail synthesis.
        generation = None
        langfuse = self._langfuse
        if langfuse is not None:
            generation = safe_trace(
                lambda: langfuse.start_observation(
                    # Same name as azure.py's fallback observation
                    # (verb-first, provider-agnostic per Langfuse naming
                    # guidance) — `model="bulbul-v2"` vs `"azure-neural-tts"`
                    # is what distinguishes primary vs fallback in the UI,
                    # so both TTS calls across the whole fallback chain
                    # group under ONE stable name for dashboards/evaluators.
                    name="synthesize-speech",
                    as_type="generation",
                    model="bulbul-v2",
                    input=f"{len(text)} chars, voice={voice_id}",
                    metadata={"voice_id": voice_id, "lesson_id": self._lesson_id},
                    trace_context=deterministic_trace_context(langfuse, self._lesson_id),
                )
            )

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    _SARVAM_TTS_URL,
                    headers={"API-Subscription-Key": self._api_key},
                    json={"inputs": [text], "speaker": voice_id, "target_language_code": "en-IN"},
                )
                if response.status_code == 429:
                    body: dict[str, Any] = {}
                    with contextlib.suppress(Exception):
                        body = response.json()
                    error_code = (body.get("error") or {}).get("code", "")
                    if error_code == "insufficient_quota_error":
                        # Story 2-32: record_failure removed — guard_breaker
                        # records exactly one outcome for this logical call.
                        # The RuntimeError (and its non-retryability) is
                        # deliberate and UNCHANGED.
                        raise RuntimeError(
                            f"Sarvam TTS insufficient_quota_error — not retryable: {body}"
                        )
                    # Any other 429 (e.g. rate_limit_exceeded_error) — let
                    # raise_for_status() raise the normal HTTPStatusError so
                    # with_retry's default 429-is-retryable path applies.
                response.raise_for_status()
                audio_bytes = response.content

            if generation is not None:
                cost = len(text) * COST_PER_CHAR
                safe_trace(
                    lambda: generation.update(
                        output=f"{len(audio_bytes)} bytes audio",
                        usage_details={"characters": len(text)},
                        # Ingested directly (never inferred): Sarvam isn't a
                        # tokenizer-priced model Langfuse has a definition
                        # for, and this is the SAME per-char rate tts_node's
                        # own cost_tracker accumulation uses (COST_PER_CHAR
                        # above), so the two numbers can be cross-checked in
                        # the Langfuse UI rather than silently disagreeing.
                        cost_details={"input": cost},
                    )
                )

            return audio_bytes, []

        except Exception as exc:
            if generation is not None:
                error_message = str(exc)
                safe_trace(lambda: generation.update(level="ERROR", status_message=error_message))
            raise

        finally:
            if generation is not None:
                safe_trace(generation.end)
