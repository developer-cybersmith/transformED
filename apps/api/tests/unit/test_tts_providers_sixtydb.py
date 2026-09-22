"""
Unit tests for Story 232: SixtyDbTTSProvider.

Covers docs/stories/232-sixtydb-tts-tier.md's ACs:
- AC 1: TTSProvider implementation, circuit breaker, retry.
- AC 2: >5000-char text is chunked and multiple requests are made.
- AC 3: dual-shape response parsing (verified top-level `audioContent`,
  fallback `result.audioContent`), RuntimeError on an unrecognized shape.
- AC 4: raw PCM chunks are concatenated and wrapped in exactly one WAV header.
- AC 5: timestamps are always [] (confirmed absent, not deferred).
- AC 6: missing api_key/voice_id raises a clear ValueError.

Same conventions as test_tts_providers.py: patch targets are the CONSUMER
module (app.providers.tts.sixtydb), no real network I/O, real WAV round-trips
via the stdlib `wave` module rather than hand-typed byte strings.
"""

from __future__ import annotations

import base64
import io
import json
import wave
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


def _make_raw_pcm(num_frames: int = 50) -> bytes:
    """Raw 16-bit mono PCM silence, no WAV header — matches what 60db's
    real REST endpoint actually returns (confirmed live, Story 232)."""
    return b"\x00\x00" * num_frames


def _make_sixtydb_response(
    status_code: int,
    lines: list[dict[str, Any]] | None = None,
    raw_text: str | None = None,
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    if raw_text is not None:
        resp.text = raw_text
    else:
        resp.text = "\n".join(json.dumps(line) for line in (lines or []))
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


def _top_level_line(pcm: bytes) -> dict[str, Any]:
    """Verified live shape (2026-09-21): audioContent + conditioning at the
    top level, no `result` wrapper."""
    return {
        "audioContent": base64.b64encode(pcm).decode("ascii"),
        "conditioning": {"reference_mode": "language_reference"},
    }


def _result_wrapped_line(pcm: bytes) -> dict[str, Any]:
    """Documented (unverified) shape — defensive fallback only."""
    return {"result": {"audioContent": base64.b64encode(pcm).decode("ascii")}}


def _patch_settings(
    mock_settings: MagicMock,
    *,
    api_key: str | None = "test-key",
    voice_id: str | None = "test-voice",
) -> None:
    mock_settings.return_value.sixtydb_api_key = api_key
    mock_settings.return_value.sixtydb_voice_id = voice_id
    mock_settings.return_value.sixtydb_model = "60db-quality"
    mock_settings.return_value.sixtydb_speed = 1.0
    mock_settings.return_value.sixtydb_enhance = True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sixtydb_top_level_shape_returns_wav_and_empty_timestamps() -> None:
    """Verified live shape: audioContent at the top level of the response."""
    from app.providers.tts.sixtydb import SixtyDbTTSProvider

    pcm = _make_raw_pcm(50)
    mock_response = _make_sixtydb_response(200, lines=[_top_level_line(pcm)])
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.tts.sixtydb.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        _patch_settings(mock_settings)
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = SixtyDbTTSProvider()
        audio_bytes, timestamps = await provider.synthesize("Hello world", "test-voice")

    with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
        assert wf.getnframes() == 50
        assert wf.getframerate() == 48000
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
    assert timestamps == [], "60db's TTS response carries no timing data — confirmed, not deferred"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sixtydb_synthesize_falls_back_to_result_wrapped_shape() -> None:
    """Documented (unverified) shape must still parse — defensive fallback."""
    from app.providers.tts.sixtydb import SixtyDbTTSProvider

    pcm = _make_raw_pcm(30)
    mock_response = _make_sixtydb_response(200, lines=[_result_wrapped_line(pcm)])
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.tts.sixtydb.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        _patch_settings(mock_settings)
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = SixtyDbTTSProvider()
        audio_bytes, _ = await provider.synthesize("Hello world", "test-voice")

    with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
        assert wf.getnframes() == 30


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sixtydb_unrecognized_response_shape_raises_runtime_error() -> None:
    """Neither top-level nor result-wrapped audioContent present — must raise
    loudly, never silently return empty/wrong audio (Scale & Load concern)."""
    from app.providers.tts.sixtydb import SixtyDbTTSProvider

    mock_response = _make_sixtydb_response(200, lines=[{"unexpected": "shape"}])
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.tts.sixtydb.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        _patch_settings(mock_settings)
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = SixtyDbTTSProvider()
        with pytest.raises(RuntimeError, match="no recognizable 'audioContent'"):
            await provider.synthesize("Hello world", "test-voice")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sixtydb_empty_response_body_raises_instead_of_silent_empty_audio() -> None:
    """Review finding: a 200 OK with an empty/whitespace-only body previously
    fell through silently (zero lines to iterate -> nothing appended -> no
    error), producing a valid-looking but silent WAV that
    `_synthesize_with_fallback`'s `if audio_bytes:` check cannot detect."""
    from app.providers.tts.sixtydb import SixtyDbTTSProvider

    mock_response = _make_sixtydb_response(200, raw_text="")
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.tts.sixtydb.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        _patch_settings(mock_settings)
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = SixtyDbTTSProvider()
        with pytest.raises(RuntimeError, match="zero parseable NDJSON lines"):
            await provider.synthesize("Hello world", "test-voice")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sixtydb_unconfigured_raises_before_guard_breaker_no_failure_recorded() -> None:
    """Review finding: missing api_key/voice_id must NOT trip the circuit
    breaker — checked before guard_breaker is entered, so is_circuit_open and
    record_failure are never called for this deliberately-expected state."""
    from app.providers.tts.sixtydb import SixtyDbTTSProvider

    mock_is_open = AsyncMock(return_value=False)
    mock_record_failure = AsyncMock()

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.tts.sixtydb.is_circuit_open", new=mock_is_open),
        patch("app.core.circuit_breaker.record_failure", new=mock_record_failure),
    ):
        _patch_settings(mock_settings, api_key=None)
        provider = SixtyDbTTSProvider()
        with pytest.raises(ValueError, match="sixtydb_api_key is not configured"):
            await provider.synthesize("Hello world", "test-voice")

    mock_is_open.assert_not_called()
    mock_record_failure.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sixtydb_long_text_makes_multiple_requests_and_concatenates_pcm() -> None:
    """AC 2/AC 4: text over 5000 chars is chunked into multiple requests;
    every chunk's raw PCM is concatenated (not just the first chunk's)."""
    from app.providers.tts.sixtydb import SixtyDbTTSProvider, _chunk_text

    long_text = ("This is one real sentence about narration synthesis. " * 200).strip()
    expected_chunk_count = len(_chunk_text(long_text))
    assert expected_chunk_count > 1, "test text must span multiple requests to be meaningful"

    call_count = 0

    async def _fake_post(*_args: object, **_kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        return _make_sixtydb_response(200, lines=[_top_level_line(_make_raw_pcm(10))])

    mock_client = AsyncMock()
    mock_client.post.side_effect = _fake_post

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.tts.sixtydb.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        _patch_settings(mock_settings)
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = SixtyDbTTSProvider()
        audio_bytes, _ = await provider.synthesize(long_text, "test-voice")

    assert call_count == expected_chunk_count
    with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
        assert wf.getnframes() == expected_chunk_count * 10, (
            "final audio must be every chunk's PCM concatenated, not just the first"
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sixtydb_circuit_open_raises_before_any_http_call() -> None:
    from app.providers.tts.sixtydb import SixtyDbTTSProvider

    mock_client = AsyncMock()

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.tts.sixtydb.is_circuit_open", new=AsyncMock(return_value=True)),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        _patch_settings(mock_settings)
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = SixtyDbTTSProvider()
        with pytest.raises(RuntimeError, match="Circuit breaker OPEN"):
            await provider.synthesize("Hello world", "test-voice")

    mock_client.post.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sixtydb_missing_api_key_raises_value_error() -> None:
    """AC 6: no crash for an unconfigured deployment — a clear ValueError,
    caught by _synthesize_with_fallback's except-and-fall-through."""
    from app.providers.tts.sixtydb import SixtyDbTTSProvider

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.tts.sixtydb.is_circuit_open", new=AsyncMock(return_value=False)),
    ):
        _patch_settings(mock_settings, api_key=None)
        provider = SixtyDbTTSProvider()
        with pytest.raises(ValueError, match="sixtydb_api_key is not configured"):
            await provider.synthesize("Hello world", "test-voice")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sixtydb_missing_voice_id_raises_value_error() -> None:
    """Review finding (Test Coverage layer): parity with the api_key sibling
    test — must also assert this branch doesn't trip the circuit breaker."""
    from app.providers.tts.sixtydb import SixtyDbTTSProvider

    mock_is_open = AsyncMock(return_value=False)
    mock_record_failure = AsyncMock()

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.tts.sixtydb.is_circuit_open", new=mock_is_open),
        patch("app.core.circuit_breaker.record_failure", new=mock_record_failure),
    ):
        _patch_settings(mock_settings, voice_id=None)
        provider = SixtyDbTTSProvider()
        with pytest.raises(ValueError, match="no voice_id configured"):
            await provider.synthesize("Hello world", "")

    mock_is_open.assert_not_called()
    mock_record_failure.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sixtydb_403_is_not_retried() -> None:
    from app.providers.tts.sixtydb import SixtyDbTTSProvider

    mock_response = _make_sixtydb_response(403, raw_text="forbidden")
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.tts.sixtydb.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        _patch_settings(mock_settings)
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = SixtyDbTTSProvider()
        with pytest.raises(httpx.HTTPStatusError):
            await provider.synthesize("Hello world", "test-voice")

    assert mock_client.post.call_count == 1, "403 must not be retried"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sixtydb_429_is_retried_then_succeeds() -> None:
    from app.providers.tts.sixtydb import SixtyDbTTSProvider

    call_count = 0

    async def _fake_post(*_args: object, **_kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return _make_sixtydb_response(429, raw_text="rate limited")
        return _make_sixtydb_response(200, lines=[_top_level_line(_make_raw_pcm(5))])

    mock_client = AsyncMock()
    mock_client.post.side_effect = _fake_post

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.tts.sixtydb.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        _patch_settings(mock_settings)
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = SixtyDbTTSProvider()
        audio_bytes, _ = await provider.synthesize("Hello world", "test-voice")

    assert call_count == 3
    with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
        assert wf.getnframes() == 5


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sixtydb_empty_text_raises_before_guard_breaker_no_failure_recorded() -> None:
    """Review finding: empty text must NOT trip the circuit breaker either —
    same class of fix as the missing-api_key/voice_id case."""
    from app.providers.tts.sixtydb import SixtyDbTTSProvider

    mock_is_open = AsyncMock(return_value=False)
    mock_record_failure = AsyncMock()

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.tts.sixtydb.is_circuit_open", new=mock_is_open),
        patch("app.core.circuit_breaker.record_failure", new=mock_record_failure),
    ):
        _patch_settings(mock_settings)
        provider = SixtyDbTTSProvider()
        with pytest.raises(ValueError, match="called with empty text"):
            await provider.synthesize("", "test-voice")

    mock_is_open.assert_not_called()
    mock_record_failure.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sixtydb_retry_on_second_chunk_does_not_resend_first_chunk() -> None:
    """Review finding (HIGH, confirmed by Scale & Load Hunter + Edge Case
    Hunter independently): retrying the whole multi-chunk loop as one unit
    previously re-sent (and would re-bill) already-succeeded chunks. Proves
    the fix: chunk 1 must be POSTed exactly once even though chunk 2 fails
    once before succeeding."""
    from app.providers.tts.sixtydb import SixtyDbTTSProvider

    # Force exactly 2 chunks by using a max_chars small enough to split this
    # text, via monkeypatching the module's chunk-size constant indirectly:
    # simplest is to build text that naturally splits into 2 sentences under
    # a small chunk cap. Instead, patch _chunk_text's default via the module
    # constant is overkill — call chunking directly is enough to prove intent,
    # but we need synthesize() to actually see 2 chunks. Patch _chunk_text.
    with patch(
        "app.providers.tts.sixtydb._chunk_text",
        return_value=["First chunk.", "Second chunk."],
    ):
        calls_per_text: dict[str, int] = {}

        async def _fake_post(*_args: object, **kwargs: object) -> MagicMock:
            sent_text = kwargs["json"]["text"]  # type: ignore[index]
            calls_per_text[sent_text] = calls_per_text.get(sent_text, 0) + 1
            if sent_text == "Second chunk." and calls_per_text[sent_text] == 1:
                return _make_sixtydb_response(503, raw_text="transient")
            return _make_sixtydb_response(200, lines=[_top_level_line(_make_raw_pcm(5))])

        mock_client = AsyncMock()
        mock_client.post.side_effect = _fake_post

        with (
            patch("app.config.get_settings") as mock_settings,
            patch("app.providers.tts.sixtydb.is_circuit_open", new=AsyncMock(return_value=False)),
            patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
            patch("httpx.AsyncClient") as mock_client_cls,
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            _patch_settings(mock_settings)
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            provider = SixtyDbTTSProvider()
            audio_bytes, _ = await provider.synthesize("irrelevant (chunks mocked)", "test-voice")

    assert calls_per_text["First chunk."] == 1, (
        "the already-succeeded first chunk must NEVER be resent when only "
        "the second chunk needed a retry"
    )
    assert calls_per_text["Second chunk."] == 2, "second chunk: 1 failure + 1 successful retry"
    with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
        assert wf.getnframes() == 10, "both chunks' PCM must still be present exactly once"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sixtydb_partial_spend_raised_when_later_chunk_fails_permanently() -> None:
    """Human reviewer finding, PR #240 (Developer-2-max, real bug, fixed):
    when chunk 1 succeeds (real wallet spend) and chunk 2 exhausts all
    retries, the real cost of chunk 1 must not be silently dropped —
    `synthesize()` must raise `SixtyDbPartialSpendError` carrying that
    partial cost, not a bare exception with no cost information at all."""
    from app.providers.tts.sixtydb import (
        COST_PER_CHAR,
        SixtyDbPartialSpendError,
        SixtyDbTTSProvider,
    )

    with patch(
        "app.providers.tts.sixtydb._chunk_text",
        return_value=["First chunk.", "Second chunk."],
    ):

        async def _fake_post(*_args: object, **kwargs: object) -> MagicMock:
            sent_text = kwargs["json"]["text"]  # type: ignore[index]
            if sent_text == "First chunk.":
                return _make_sixtydb_response(200, lines=[_top_level_line(_make_raw_pcm(5))])
            return _make_sixtydb_response(503, raw_text="persistent outage")

        mock_client = AsyncMock()
        mock_client.post.side_effect = _fake_post

        with (
            patch("app.config.get_settings") as mock_settings,
            patch("app.providers.tts.sixtydb.is_circuit_open", new=AsyncMock(return_value=False)),
            patch("app.core.circuit_breaker.record_failure", new=AsyncMock()),
            patch("httpx.AsyncClient") as mock_client_cls,
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            _patch_settings(mock_settings)
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            provider = SixtyDbTTSProvider()
            with pytest.raises(SixtyDbPartialSpendError) as exc_info:
                await provider.synthesize("irrelevant (chunks mocked)", "test-voice")

    expected_partial_cost = len("First chunk.") * COST_PER_CHAR
    assert exc_info.value.partial_cost_usd == pytest.approx(expected_partial_cost)
    assert exc_info.value.__cause__ is not None, "original failure must be preserved as __cause__"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sixtydb_misaligned_pcm_length_raises_runtime_error() -> None:
    """Review finding: a truncated/corrupted PCM buffer whose byte length
    isn't a multiple of channels*sample_width must raise, not silently
    produce a subtly-wrong WAV file."""
    from app.providers.tts.sixtydb import SixtyDbTTSProvider

    odd_pcm = b"\x00" * 51  # not a multiple of 2 (mono, 16-bit)
    line = {"audioContent": base64.b64encode(odd_pcm).decode("ascii")}
    mock_response = _make_sixtydb_response(200, lines=[line])
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.tts.sixtydb.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        _patch_settings(mock_settings)
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = SixtyDbTTSProvider()
        with pytest.raises(RuntimeError, match="not a multiple of"):
            await provider.synthesize("Hello world", "test-voice")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sixtydb_two_misaligned_pieces_that_cancel_out_still_raise() -> None:
    """Human reviewer finding, PR #240 (Developer-2-max, real bug, fixed):
    the misalignment check used to run only on the FINAL concatenated
    buffer, so two independently truncated pieces whose lengths sum to an
    exact multiple of frame_size (51 + 49 = 100) passed silently even though
    BOTH pieces are individually corrupted. Each piece is now validated
    immediately after decoding, so this can no longer cancel out."""
    from app.providers.tts.sixtydb import SixtyDbTTSProvider

    piece_a = b"\x00" * 51  # misaligned on its own
    piece_b = b"\x00" * 49  # misaligned on its own — 51+49=100 is NOT
    line = {
        "audioContent": base64.b64encode(piece_a).decode("ascii"),
    }
    line2 = {
        "audioContent": base64.b64encode(piece_b).decode("ascii"),
    }
    # Both pieces arrive in the SAME response (multi-line NDJSON), so the
    # old combined-buffer-only check would have summed them before ever
    # looking at either piece individually.
    raw_text = json.dumps(line) + "\n" + json.dumps(line2)
    mock_response = _make_sixtydb_response(200, raw_text=raw_text)
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.tts.sixtydb.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        _patch_settings(mock_settings)
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = SixtyDbTTSProvider()
        with pytest.raises(RuntimeError, match="not a multiple of"):
            await provider.synthesize("Hello world", "test-voice")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sixtydb_invalid_base64_raises_instead_of_silently_dropping_chars() -> None:
    """Review finding: b64decode() without validate=True silently drops
    non-base64 characters instead of raising — a corrupted response would
    decode to wrong-length garbage PCM rather than fail loudly."""
    from app.providers.tts.sixtydb import SixtyDbTTSProvider

    line = {"audioContent": "not-valid-base64!!!@@@"}
    mock_response = _make_sixtydb_response(200, lines=[line])
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.tts.sixtydb.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        _patch_settings(mock_settings)
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = SixtyDbTTSProvider()
        with pytest.raises(Exception, match="base64"):
            await provider.synthesize("Hello world", "test-voice")
