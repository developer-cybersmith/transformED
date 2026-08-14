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

D74 (Story 3-42): two compounding defects found live during the L1
acceptance run, neither previously known because every test mocks
SarvamTTSProvider at the call site (tts_node's tests) rather than exercising
this module's real HTTP-response handling:

1. Sarvam hard-limits each `inputs[]` string to 500 characters (server
   -validated: a real 400 names "String should have at most 500 characters").
   Real narration segments run 1,351-4,069 chars -- every one over the limit.
   `_chunk_narration_text` splits on sentence boundaries (falling back to
   word boundaries for a single oversized sentence) to respect this.
2. The endpoint's real response is `Content-Type: application/json` --
   `{"request_id": ..., "audios": ["<base64 WAV>", ...]}` -- NOT a raw audio
   byte stream. The pre-fix code returned `response.content` (the raw JSON
   text) as "audio_bytes", confirmed live via header + byte inspection.
   Fixed to decode `response.json()["audios"][i]` per item.

A third constraint (found while designing the fix, not assumed from docs):
`inputs[]` also caps at 3 items per request (a real 400 names "List should
have at most 3 items"). A long segment therefore needs multiple BATCHED
requests, each ≤3 chunks, all within one logical `synthesize()` call --
still exactly one circuit-breaker outcome (Story 2-32 AC-3 unchanged).
Every batch's decoded WAV clips are concatenated via the `wave` module
(real PCM-frame concatenation under one header, not naive byte concatenation
of multiple complete WAV files, which produces an invalid multi-header file).

D89 (Story 3-52): a real stakeholder reported narration speed as "very fast"
in real generated-lesson playback. Sarvam's real `pace` request parameter
(default 1.0, valid range 0.3-3.0 for bulbul:v2) was never sent, so every
lesson synthesized at Sarvam's raw 1.0 default. Fixed by sending
`settings.sarvam_narration_pace` (default 0.85, tunable via env var, no
code change) as `pace` on every synthesize request.
"""

from __future__ import annotations

import base64
import contextlib
import io
import logging
import re
import wave
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

# Sarvam's own server-validated limits (D74) -- confirmed live via the API's
# own 400 error bodies, not assumed from docs. Neither is documented in
# Sarvam's public API reference at the time these were found.
_SARVAM_MAX_CHARS_PER_INPUT = 500
_SARVAM_MAX_INPUTS_PER_REQUEST = 3

# Sarvam Bulbul v2 pricing (USD per character) — same figure tts_node's own
# cost-tracking uses (graph.py's _synthesize_with_fallback imports this
# constant rather than keeping a private duplicate, so there is one number,
# not two that can drift). Documented placeholder, not a verified invoiced
# rate — same caveat as every other provider's cost constant in this codebase.
COST_PER_CHAR = 0.00002


def _chunk_narration_text(text: str, max_chars: int = _SARVAM_MAX_CHARS_PER_INPUT) -> list[str]:
    """Split *text* into chunks of at most *max_chars*, preferring sentence
    boundaries so each chunk is spoken as complete sentences where possible.

    Falls back to word-boundary splitting for any single sentence exceeding
    max_chars on its own — narration text is LLM-generated and not
    guaranteed to respect any particular sentence-length convention.

    Never drops or duplicates characters other than normalising the
    whitespace AT chunk boundaries (a run of whitespace between two
    sentences/words becomes a single space) — cost accounting
    (COST_PER_CHAR) is computed against the ORIGINAL text length, so this
    function's job is only to make Sarvam accept the text, not to change
    what gets billed.
    """
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current = ""

    def _flush() -> None:
        nonlocal current
        if current:
            chunks.append(current)
            current = ""

    for sentence in sentences:
        if len(sentence) > max_chars:
            _flush()
            # Oversized single sentence: split on word boundaries instead.
            words = sentence.split(" ")
            piece = ""
            for word in words:
                candidate = f"{piece} {word}".strip()
                if len(candidate) > max_chars:
                    if piece:
                        chunks.append(piece)
                    piece = word
                else:
                    piece = candidate
            current = piece
            continue

        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) > max_chars:
            _flush()
            current = sentence
        else:
            current = candidate

    _flush()
    return chunks


def _batched(items: list[str], batch_size: int) -> list[list[str]]:
    """Split *items* into consecutive groups of at most *batch_size*."""
    return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]


def _concatenate_wav_clips(wav_clips: list[bytes]) -> bytes:
    """Concatenate multiple complete WAV files into one continuous WAV file.

    Naive byte concatenation of complete WAV files produces an INVALID
    multi-header file — most players stop after the first clip's own
    declared length, since the RIFF header's size field only covers that
    first clip. Decodes each clip's real PCM frames via the stdlib `wave`
    module and re-wraps them under one header carrying the correct combined
    length.
    """
    frames: list[bytes] = []
    params: wave._wave_params | None = None
    for wav_bytes in wav_clips:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            if params is None:
                params = wf.getparams()
            frames.append(wf.readframes(wf.getnframes()))

    output = io.BytesIO()
    with wave.open(output, "wb") as wf:
        assert params is not None  # wav_clips is never empty when this is called
        wf.setparams(params)
        for frame_data in frames:
            wf.writeframes(frame_data)
    return output.getvalue()


class SarvamTTSProvider(TTSProvider):
    """Primary TTS provider — Sarvam AI Bulbul v2."""

    def __init__(self, lesson_id: str | None = None) -> None:
        from app.config import get_settings

        settings = get_settings()
        self._api_key = settings.sarvam_api_key
        # D89: real stakeholder report -- Sarvam's raw 1.0 `pace` default read
        # as "very fast" in real playback. Read once here (same established
        # pattern as self._api_key above), not re-read per call.
        self._narration_pace = settings.sarvam_narration_pace
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
            # D74: chunk to respect Sarvam's real 500-char-per-input limit,
            # then batch to respect its real 3-inputs-per-request limit. Both
            # confirmed live via the API's own 400 bodies, not assumed.
            # Sequential, not concurrent (Scale & Load Q6, Story 3-42) — a
            # shared per-key rate limit means firing all batches at once only
            # raises the odds of a 429 for no latency benefit at this scale.
            chunks = _chunk_narration_text(text)
            if not chunks:
                # tts_node's caller already guards empty script text before
                # ever calling synthesize() (graph.py's `if not script:`
                # branch) -- this is a defensive guard for synthesize()'s
                # OTHER callers, not the expected path, so it raises loudly
                # rather than reaching _concatenate_wav_clips with nothing
                # to concatenate.
                raise ValueError("SarvamTTSProvider.synthesize() called with empty text")
            b64_clips: list[str] = []
            async with httpx.AsyncClient(timeout=30.0) as client:
                for batch in _batched(chunks, _SARVAM_MAX_INPUTS_PER_REQUEST):
                    response = await client.post(
                        _SARVAM_TTS_URL,
                        headers={"API-Subscription-Key": self._api_key},
                        json={
                            "inputs": batch,
                            "speaker": voice_id,
                            "target_language_code": "en-IN",
                            # D89: Sarvam's real `pace` param -- lower is
                            # slower; unset previously synthesized every
                            # lesson at Sarvam's raw 1.0 default.
                            "pace": self._narration_pace,
                        },
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
                    # D74: the real response is JSON ({"audios": [...]}), not
                    # a raw audio byte stream — response.content here is text,
                    # confirmed live via Content-Type + byte inspection (see
                    # module docstring). Each batch returns one clip per input,
                    # in order.
                    batch_audios = response.json().get("audios") or []
                    if len(batch_audios) != len(batch):
                        raise RuntimeError(
                            f"Sarvam TTS returned {len(batch_audios)} audio clips for "
                            f"{len(batch)} inputs — response shape mismatch"
                        )
                    b64_clips.extend(batch_audios)

            wav_clips = [base64.b64decode(clip) for clip in b64_clips]
            audio_bytes = _concatenate_wav_clips(wav_clips)

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
