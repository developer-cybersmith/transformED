"""
60db.ai TTS provider implementation — new primary tier (Story 232).

Responsibilities
----------------
- Implements TTSProvider using 60db.ai's REST `/tts-synthesize` endpoint.
- Returns (audio_bytes, word_timestamps) tuples — timestamps always empty.
  CONFIRMED (not deferred, not assumed): a live call to `/tts-synthesize`
  (2026-09-21, real key + voice_id) returned a response with exactly two
  top-level keys, `audioContent` and `conditioning` — no timing/timestamp
  field of any kind. GitHub issue #232's "60db returns word-level timestamps
  natively" claim traced back to public-web research and does not hold up
  against the live API. See docs/stories/232-sixtydb-tts-tier.md.
- Response shape: the same live call returned `audioContent` (base64 LINEAR16
  PCM) at the TOP LEVEL of the JSON object — not nested under `result`, as
  this skill's own (otherwise more-reliable-than-public-docs) reference
  described. Only one live shape has been observed; `_extract_audio_content`
  therefore checks the verified top-level key first and falls back to the
  documented `result.audioContent` nesting defensively, raising loudly if
  neither is present rather than silently returning empty audio.
- 60db's real, server-documented limit is 5000 chars per `text` field (10x
  Sarvam's 500-char limit) — chunked the same way Sarvam is (sentence
  boundary preferred, word boundary fallback), one request per chunk,
  sequential (shared per-key rate limit — same reasoning as Sarvam).
- Output is raw LINEAR16 PCM, not a WAV file (`output_format` is documented
  as ignored by this endpoint) — every chunk's decoded PCM bytes are
  concatenated directly (valid for raw PCM, unlike concatenating complete WAV
  files) and wrapped in exactly one WAV header at the end, at REST's native
  48000 Hz / mono / 16-bit (the REST endpoint takes no `sample_rate` request
  field — confirmed against the skill's own request-body table).
- Applies circuit breaker ("sixtydb" provider key) and retry decorator, same
  shape as sarvam.py/azure.py.
- Cost: 60db publishes no per-character price (wallet-credit billing only).
  COST_PER_CHAR below is Sarvam's rate used as an explicit, documented,
  UNCONFIRMED placeholder — registered as D168 in docs/DEFECT-REGISTER.md
  per CLAUDE.md binding rule 5.
"""

from __future__ import annotations

import io
import json
import logging
import re
import wave
from base64 import b64decode
from typing import Any

import httpx
from langfuse import Langfuse

from app.core.circuit_breaker import CircuitOpenError, guard_breaker, is_circuit_open
from app.core.langfuse import deterministic_trace_context, get_langfuse, safe_trace
from app.core.retry import with_retry
from app.providers.base import TTSProvider

logger = logging.getLogger(__name__)

_PROVIDER_KEY = "sixtydb"
_SIXTYDB_TTS_URL = "https://api.60db.ai/tts-synthesize"

# Server-documented limit (skill references/tts.md): "text ≤ 5000 chars. Over
# that -> split + concatenate WAVs." Not independently re-confirmed live in
# this story (the verification call used a short sentence) — treated as
# authoritative because it is the one figure the skill's docs and the 413
# "Payload too large" error code table agree on.
_SIXTYDB_MAX_CHARS_PER_REQUEST = 5000

# 60db's native REST output rate — see module docstring. Only the WAV header
# this provider writes; not a request parameter.
_SIXTYDB_SAMPLE_RATE_HZ = 48000
_SIXTYDB_CHANNELS = 1
_SIXTYDB_SAMPLE_WIDTH_BYTES = 2  # 16-bit LINEAR16

# D168 (docs/DEFECT-REGISTER.md): unconfirmed placeholder, matches Sarvam's
# documented per-char rate — 60db publishes no per-character price.
COST_PER_CHAR = 0.00002


def _chunk_text(text: str, max_chars: int = _SIXTYDB_MAX_CHARS_PER_REQUEST) -> list[str]:
    """Split *text* into chunks of at most *max_chars*, preferring sentence
    boundaries, falling back to word boundaries for an oversized single
    sentence — same approach as sarvam.py's `_chunk_narration_text`, reused
    at 60db's much larger 5000-char limit (this path triggers far less often
    in practice than Sarvam's 500-char chunking does).

    Deliberately a separate copy, not a shared import from sarvam.py (review
    finding, accepted not fixed — registered as D171 in DEFECT-REGISTER.md):
    this story's stated scope explicitly keeps
    Sarvam's own provider file untouched, and every provider file in
    providers/tts/ is already independently self-contained by this
    codebase's own established pattern (providers/llm/factory.py's docstring:
    "adding a new vendor is a pure addition — one new branch + one new
    provider file"). Extracting a shared chunker would mean editing sarvam.py,
    which this story does not do. If the chunking algorithm needs a future
    fix, it must be applied to both this function and sarvam.py's.
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


def _extract_audio_content(line_obj: dict[str, Any]) -> str:
    """Return the base64 `audioContent` value from one parsed response line.

    Checks the VERIFIED live shape first (`audioContent` at the top level),
    falling back to the documented-but-unverified `result.audioContent`
    nesting. Raises `RuntimeError` if neither shape yields a value — never
    silently returns empty audio for an unrecognized shape (Scale & Load's
    "quiet wrongness" concern in the story file).
    """
    top_level = line_obj.get("audioContent")
    if isinstance(top_level, str) and top_level:
        return top_level

    result = line_obj.get("result")
    if isinstance(result, dict):
        nested = result.get("audioContent")
        if isinstance(nested, str) and nested:
            return nested

    raise RuntimeError(
        "60db TTS response line had no recognizable 'audioContent' field "
        f"(top-level or result-nested) — keys present: {sorted(line_obj.keys())}"
    )


def _wrap_pcm_as_wav(pcm_bytes: bytes) -> bytes:
    """Wrap raw LINEAR16 PCM bytes in a single WAV header.

    Unlike Sarvam's `_concatenate_wav_clips` (which decodes and re-wraps
    already-complete WAV files), 60db's chunks are raw PCM with no header at
    all — direct byte concatenation of the PCM payloads is valid before this
    function is called once on the combined result.
    """
    output = io.BytesIO()
    with wave.open(output, "wb") as wf:
        wf.setnchannels(_SIXTYDB_CHANNELS)
        wf.setsampwidth(_SIXTYDB_SAMPLE_WIDTH_BYTES)
        wf.setframerate(_SIXTYDB_SAMPLE_RATE_HZ)
        wf.writeframes(pcm_bytes)
    return output.getvalue()


class SixtyDbTTSProvider(TTSProvider):
    """New primary TTS provider — 60db.ai (Story 232)."""

    def __init__(self, lesson_id: str | None = None) -> None:
        from app.config import get_settings

        settings = get_settings()
        self._api_key = settings.sixtydb_api_key
        self._voice_id_default = settings.sixtydb_voice_id
        self._model = settings.sixtydb_model
        self._speed = settings.sixtydb_speed
        self._enhance = settings.sixtydb_enhance
        self._lesson_id = lesson_id
        self._langfuse: Langfuse | None
        try:
            self._langfuse = get_langfuse()
        except Exception:
            logger.warning(
                "Langfuse init failed — tracing disabled for SixtyDbTTSProvider",
                exc_info=True,
            )
            self._langfuse = None

    async def synthesize(
        self,
        text: str,
        voice_id: str,
    ) -> tuple[bytes, list[dict[str, Any]]]:
        """Synthesise *text* with 60db.ai, recording exactly one breaker
        outcome per logical call (same accounting discipline as
        sarvam.py/azure.py — Story 2-32 AC-3).

        Config-precondition checks (missing api_key/voice_id) run BEFORE
        `guard_breaker` is entered, deliberately outside its accounting —
        review finding: an unconfigured deployment (the documented, intended
        default state for this new tier — AC 6) would otherwise record a
        real circuit-breaker failure on every call, tripping the breaker and
        firing a Sentry "Circuit breaker OPENED" alert within 120s of any
        lesson with 5+ segments, misreporting a deployment choice as a
        provider outage.
        """
        if not self._api_key:
            raise ValueError("SixtyDbTTSProvider: settings.sixtydb_api_key is not configured")
        effective_voice_id = voice_id or self._voice_id_default
        if not effective_voice_id:
            raise ValueError("SixtyDbTTSProvider: no voice_id configured or passed")
        # Review finding: this check previously lived inside the guard_breaker-
        # wrapped body, so an empty-text call recorded a real breaker failure
        # for what is a caller bug, not a provider outage — same class of
        # issue as the api_key/voice_id checks above, fixed the same way.
        chunks = _chunk_text(text)
        if not chunks:
            raise ValueError("SixtyDbTTSProvider.synthesize() called with empty text")

        return await guard_breaker(
            _PROVIDER_KEY, lambda: self._synthesize_inner(chunks, text, effective_voice_id)
        )

    async def _synthesize_inner(
        self,
        chunks: list[str],
        text: str,
        voice_id: str,
    ) -> tuple[bytes, list[dict[str, Any]]]:
        """Body of `synthesize`, wrapped by guard_breaker. Records NO breaker
        outcome directly — that happens once, in guard_breaker, based on
        whether this whole call raises.

        NOT itself `@with_retry`-decorated (review finding, HIGH severity,
        fixed): retrying this entire multi-chunk loop as one unit meant a
        transient failure on chunk N re-sent (and, per 60db's wallet-credit
        billing, re-billed) chunks 1..N-1 which had ALREADY succeeded — while
        cost accounting below still counts `len(text)` exactly once,
        silently undercounting real spend against the $3.00/lesson ceiling
        (Scale & Load Hunter finding, confirmed with concrete arithmetic:
        one retried chunk on a real ~4,000-char segment underclaims real
        cost by ~2x). Fixed by retrying only the individual failing chunk —
        see `_post_chunk` — so already-succeeded chunks are never resent.

        Args:
            chunks:   Pre-chunked text (from `_chunk_text`, computed once in
                      `synthesize()` so both the empty-text guard and this
                      call share the same chunking, not two separate calls).
            text:     Original, unchunked narration text (for cost accounting
                      — `len(text)`, not `len(chunk)` summed, matching every
                      other provider's cost formula in this codebase).
            voice_id: 60db voice id (from `GET /voices`).

        Returns:
            ``(audio_bytes, [])`` — see module docstring: confirmed, not
            deferred, that 60db's TTS response carries no timing data.
        """
        generation = None
        langfuse = self._langfuse
        if langfuse is not None:
            generation = safe_trace(
                lambda: langfuse.start_observation(
                    # Same observation name as sarvam.py/azure.py — see
                    # sarvam.py's comment for why (one stable name across the
                    # whole fallback chain for dashboards/evaluators).
                    name="synthesize-speech",
                    as_type="generation",
                    model=self._model,
                    input=f"{len(text)} chars, voice={voice_id}",
                    metadata={"voice_id": voice_id, "lesson_id": self._lesson_id},
                    trace_context=deterministic_trace_context(langfuse, self._lesson_id),
                )
            )

        try:
            pcm_chunks: list[bytes] = []
            # D172 (DEFECT-REGISTER.md): this loop has no overall elapsed-time
            # budget across all chunks — each `_post_chunk` call has its own
            # 30s timeout + up to 3 retries, but a segment needing many
            # chunks (up to 24 at the 120,000-char lesson-wide narration cap)
            # could still take tens of minutes worst-case before this whole
            # call fails and falls through to Sarvam. Registered, not fixed
            # here — an overall timeout is a broader design decision shared
            # with sarvam.py's identical gap (worse there, at its 500-char
            # limit), out of this file's scope to decide unilaterally.
            async with httpx.AsyncClient(timeout=30.0) as client:
                for chunk in chunks:
                    pcm_chunks.extend(await self._post_chunk(client, chunk, voice_id))

            combined_pcm = b"".join(pcm_chunks)
            # Review finding: an odd/misaligned PCM byte length (a truncated
            # or corrupted chunk) previously passed silently into `wave` —
            # writeframes does not validate frame alignment, so a corrupted
            # buffer produced a "valid-looking" but subtly wrong WAV file
            # with no error. Raise loudly instead.
            frame_size = _SIXTYDB_CHANNELS * _SIXTYDB_SAMPLE_WIDTH_BYTES
            if len(combined_pcm) % frame_size != 0:
                raise RuntimeError(
                    f"60db TTS returned {len(combined_pcm)} bytes of PCM, not a multiple "
                    f"of {frame_size} (channels*sample_width) — refusing to wrap "
                    "misaligned/corrupted audio into a WAV file"
                )
            audio_bytes = _wrap_pcm_as_wav(combined_pcm)

            if generation is not None:
                cost = len(text) * COST_PER_CHAR
                safe_trace(
                    lambda: generation.update(
                        output=f"{len(audio_bytes)} bytes audio",
                        usage_details={"characters": len(text)},
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

    @with_retry(max_attempts=3)
    async def _post_chunk(
        self,
        client: httpx.AsyncClient,
        chunk: str,
        voice_id: str,
    ) -> list[bytes]:
        """POST one chunk and return its decoded PCM piece(s) (usually one,
        potentially more if the response is genuinely multi-line NDJSON).

        Retried independently PER CHUNK (review finding — see
        `_synthesize_inner`'s docstring for why retrying the whole multi-chunk
        loop as one unit was wrong): a transient failure here re-sends only
        THIS chunk, never one that already succeeded. `is_circuit_open` is
        checked on every attempt of every chunk (Story 2-32 AC-4's "checked
        on every attempt" pattern, at chunk granularity — strictly finer than
        Sarvam/Azure's whole-call granularity, and correct: a circuit that
        opens mid-loop must stop the NEXT chunk, not let it start and race
        past a now-known-unhealthy provider).
        """
        if await is_circuit_open(_PROVIDER_KEY):
            raise CircuitOpenError(
                f"Circuit breaker OPEN for provider '{_PROVIDER_KEY}' — call rejected"
            )

        response = await client.post(
            _SIXTYDB_TTS_URL,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={
                "text": chunk,
                "voice_id": voice_id,
                "model": self._model,
                "enhance": self._enhance,
                "speed": self._speed,
            },
        )
        response.raise_for_status()

        pcm_pieces: list[bytes] = []
        for line in response.text.splitlines():
            line = line.strip()
            if not line:
                continue
            line_obj = json.loads(line)
            audio_b64 = _extract_audio_content(line_obj)
            # Review finding: b64decode() without validate=True silently
            # DROPS non-base64-alphabet characters instead of raising —
            # a corrupted/garbled response would decode to wrong-length
            # garbage PCM rather than fail loudly.
            pcm_pieces.append(b64decode(audio_b64, validate=True))

        if not pcm_pieces:
            # Review finding: a 200 OK with an empty/whitespace-only body
            # previously fell through silently — no audio appended, no error
            # raised, and _wrap_pcm_as_wav still produced a valid-looking
            # (but silent) WAV header that `if audio_bytes:` in
            # _synthesize_with_fallback cannot detect. Raise loudly instead —
            # exactly the "quiet wrongness" this story's Scale & Load section
            # names.
            raise RuntimeError(
                "60db TTS response contained zero parseable NDJSON lines "
                "for one chunk — refusing to return silently-empty audio"
            )
        return pcm_pieces
