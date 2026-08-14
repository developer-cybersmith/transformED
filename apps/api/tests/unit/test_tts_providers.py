"""
Unit tests for Story 2-8 (S2-9): SarvamTTSProvider and AzureTTSProvider.

Covers docs/stories/2-8-tts-node.md's ACs:
- AC-3: SarvamTTSProvider — circuit breaker, retry, 429-body-inspection split
  (rate_limit_exceeded_error retryable, insufficient_quota_error not).
- AC-4: AzureTTSProvider — circuit breaker, real HTTP call.

Both providers import is_circuit_open/record_success/record_failure at
module top level (same convention as app.providers.llm.openai) — patch
targets are the CONSUMER module (app.providers.tts.sarvam / .azure), not the
source app.core.circuit_breaker (see test_provider_tracing_resilience.py for
the established precedent).

All HTTP calls are mocked via a fake httpx.AsyncClient — no real network I/O.

D74 (Story 3-42) correction: the pre-fix version of
test_sarvam_synthesize_success_returns_audio_and_empty_timestamps mocked
`resp.content = b"FAKEAUDIO"` and asserted the code returns it verbatim —
literally encoding the bug (response.content is the raw JSON body, not
decoded audio) as the test's expected behavior. The json_body's own
`"audios": ["base64ignored"]` value admitted as much. Fixed to mock a
REAL base64-encoded WAV clip in the `audios` field and assert the DECODED
result, which is what the real Sarvam API actually returns and what the
real code path now actually reads.
"""

from __future__ import annotations

import base64
import io
import wave
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


def _make_httpx_response(
    status_code: int, json_body: dict[str, Any] | None = None, content: bytes = b""
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    resp.json.return_value = json_body or {}
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


def _make_wav_bytes(num_frames: int = 100, framerate: int = 22050) -> bytes:
    """Build a real, valid, tiny WAV file — mono 16-bit PCM silence — so
    tests exercise the actual `wave` module round-trip (decode + read back),
    not a hand-typed byte string that happens to start with b"RIFF"."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(framerate)
        wf.writeframes(b"\x00\x00" * num_frames)
    return buf.getvalue()


def _make_sarvam_json_response(num_clips: int = 1, frames_per_clip: int = 100) -> MagicMock:
    """A Sarvam-shaped 200 response: real base64-encoded WAV clips in
    `audios`, Content-Type application/json — matching the real API,
    confirmed live during Story 3-42 (see sarvam.py's module docstring)."""
    clips = [
        base64.b64encode(_make_wav_bytes(frames_per_clip)).decode("ascii") for _ in range(num_clips)
    ]
    return _make_httpx_response(
        200,
        json_body={"request_id": "test-request", "audios": clips},
        # response.content deliberately looks like JSON TEXT, not audio —
        # the real API's Content-Type is application/json. Any test that
        # accidentally reads response.content as audio again would see
        # this and fail loudly instead of silently passing.
        content=b'{"request_id": "test-request", "audios": [...]}',
    )


# ---------------------------------------------------------------------------
# SarvamTTSProvider
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sarvam_synthesize_success_returns_real_decoded_audio_and_empty_timestamps() -> None:
    """D74: the real API returns a JSON body with base64-encoded WAV clips
    in `audios` — this asserts the code DECODES that, not that it returns
    the raw response.content (which is JSON text, not audio)."""
    from app.providers.tts.sarvam import SarvamTTSProvider

    mock_response = _make_sarvam_json_response(num_clips=1, frames_per_clip=50)
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.tts.sarvam.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.return_value.sarvam_api_key = "test-key"
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = SarvamTTSProvider()
        audio_bytes, timestamps = await provider.synthesize("Hello world", "anushka")

    # Real, valid WAV — not the mocked response.content JSON text, and not
    # the base64 string either. Read back via `wave` to prove it's a real
    # playable file, matching what package_builder/tinytag will do downstream.
    assert audio_bytes != b'{"request_id": "test-request", "audios": [...]}'
    with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
        assert wf.getnframes() == 50
    assert timestamps == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sarvam_long_segment_makes_multiple_batched_requests_and_concatenates() -> None:
    """D74's full end-to-end shape: a long segment (>3 chunks worth of text)
    must make MULTIPLE HTTP requests (Sarvam's 3-items-per-request cap), and
    the final audio must be the concatenation of every batch's every clip —
    not just the first request's result."""
    from app.providers.tts.sarvam import SarvamTTSProvider, _chunk_narration_text

    long_text = ("This is one real sentence about machine learning models. " * 40).strip()
    expected_chunk_count = len(_chunk_narration_text(long_text))
    assert expected_chunk_count > 3, "test text must span multiple batches to be meaningful"

    call_count = 0

    async def _fake_post(*_args: object, **kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        num_inputs = len(kwargs["json"]["inputs"])  # type: ignore[index]
        return _make_sarvam_json_response(num_clips=num_inputs, frames_per_clip=10)

    mock_client = AsyncMock()
    mock_client.post.side_effect = _fake_post

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.tts.sarvam.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.return_value.sarvam_api_key = "test-key"
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = SarvamTTSProvider()
        audio_bytes, _ = await provider.synthesize(long_text, "anushka")

    assert call_count >= 2, "a long segment must span multiple batched requests"
    # Every request's inputs stayed within Sarvam's real per-request cap.
    for call in mock_client.post.call_args_list:
        assert len(call.kwargs["json"]["inputs"]) <= 3
        for chunk in call.kwargs["json"]["inputs"]:
            assert len(chunk) <= 500

    # Final audio is every clip from every batch concatenated, not just the
    # first request's result — one clip per chunk, 10 frames/clip.
    with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
        assert wf.getnframes() == expected_chunk_count * 10


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sarvam_circuit_open_raises_before_any_http_call() -> None:
    from app.providers.tts.sarvam import SarvamTTSProvider

    mock_client = AsyncMock()

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.tts.sarvam.is_circuit_open", new=AsyncMock(return_value=True)),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.return_value.sarvam_api_key = "test-key"
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = SarvamTTSProvider()
        with pytest.raises(RuntimeError, match="Circuit breaker OPEN"):
            await provider.synthesize("Hello world", "meera")

    mock_client.post.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sarvam_403_is_not_retried() -> None:
    """403 is Sarvam's auth-failure status — with_retry's existing
    _NON_RETRYABLE_STATUS_CODES already covers this, verify it holds."""
    from app.providers.tts.sarvam import SarvamTTSProvider

    mock_response = _make_httpx_response(403, json_body={"error": {"code": "auth_failure"}})
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.tts.sarvam.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.return_value.sarvam_api_key = "test-key"
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = SarvamTTSProvider()
        with pytest.raises(httpx.HTTPStatusError):
            await provider.synthesize("Hello world", "meera")

    assert mock_client.post.call_count == 1, "403 must not be retried"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sarvam_429_rate_limit_exceeded_is_retried() -> None:
    """A 429 with a rate_limit_exceeded_error body is retryable — with_retry's
    default 429 handling applies, verify it's exercised (3 attempts total)."""
    from app.providers.tts.sarvam import SarvamTTSProvider

    mock_response = _make_httpx_response(
        429, json_body={"error": {"code": "rate_limit_exceeded_error"}}
    )
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.tts.sarvam.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        mock_settings.return_value.sarvam_api_key = "test-key"
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = SarvamTTSProvider()
        with pytest.raises(httpx.HTTPStatusError):
            await provider.synthesize("Hello world", "meera")

    assert mock_client.post.call_count == 3, (
        "rate_limit_exceeded_error must be retried up to max_attempts"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sarvam_429_insufficient_quota_is_not_retried() -> None:
    """A 429 with an insufficient_quota_error body must NOT be retried —
    the body-inspection split this AC requires."""
    from app.providers.tts.sarvam import SarvamTTSProvider

    mock_response = _make_httpx_response(
        429, json_body={"error": {"code": "insufficient_quota_error"}}
    )
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.tts.sarvam.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        mock_settings.return_value.sarvam_api_key = "test-key"
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = SarvamTTSProvider()
        with pytest.raises(RuntimeError, match="insufficient_quota"):
            await provider.synthesize("Hello world", "meera")

    assert mock_client.post.call_count == 1, "insufficient_quota_error must NOT be retried"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sarvam_synthesize_request_includes_configured_pace() -> None:
    """D89: a real stakeholder reported narration speed as "very fast" in
    real playback -- Sarvam's raw `pace` default (1.0) was never overridden.
    The real synthesize request payload must include the configured
    `sarvam_narration_pace` value as `"pace"`."""
    from app.providers.tts.sarvam import SarvamTTSProvider

    mock_response = _make_sarvam_json_response(num_clips=1, frames_per_clip=10)
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.tts.sarvam.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.return_value.sarvam_api_key = "test-key"
        mock_settings.return_value.sarvam_narration_pace = 0.85
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = SarvamTTSProvider()
        await provider.synthesize("Hello world", "anushka")

    assert mock_client.post.call_count == 1
    sent_json = mock_client.post.call_args.kwargs["json"]
    assert sent_json["pace"] == 0.85


# ---------------------------------------------------------------------------
# AzureTTSProvider
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_azure_synthesize_success_returns_audio_and_empty_timestamps() -> None:
    from app.providers.tts.azure import AzureTTSProvider

    mock_response = _make_httpx_response(200, content=b"FAKEAUDIOAZURE")
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.tts.azure.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.return_value.azure_tts_key = "test-key"
        mock_settings.return_value.azure_tts_region = "centralindia"
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = AzureTTSProvider()
        audio_bytes, timestamps = await provider.synthesize("Hello world", "en-IN-NeerjaNeural")

    assert audio_bytes == b"FAKEAUDIOAZURE"
    assert timestamps == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_azure_circuit_open_raises_before_any_http_call() -> None:
    from app.providers.tts.azure import AzureTTSProvider

    mock_client = AsyncMock()

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.tts.azure.is_circuit_open", new=AsyncMock(return_value=True)),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.return_value.azure_tts_key = "test-key"
        mock_settings.return_value.azure_tts_region = "centralindia"
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = AzureTTSProvider()
        with pytest.raises(RuntimeError, match="Circuit breaker OPEN"):
            await provider.synthesize("Hello world", "en-IN-NeerjaNeural")

    mock_client.post.assert_not_called()
