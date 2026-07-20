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
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


def _make_httpx_response(status_code: int, json_body: dict[str, Any] | None = None, content: bytes = b"") -> MagicMock:
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


# ---------------------------------------------------------------------------
# SarvamTTSProvider
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sarvam_synthesize_success_returns_audio_and_empty_timestamps() -> None:
    from app.providers.tts.sarvam import SarvamTTSProvider

    mock_response = _make_httpx_response(200, json_body={"audios": ["base64ignored"]}, content=b"FAKEAUDIO")
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.tts.sarvam.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.providers.tts.sarvam.record_success", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.return_value.sarvam_api_key = "test-key"
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = SarvamTTSProvider()
        audio_bytes, timestamps = await provider.synthesize("Hello world", "meera")

    assert audio_bytes == b"FAKEAUDIO"
    assert timestamps == []


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
        patch("app.providers.tts.sarvam.record_failure", new=AsyncMock()),
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

    mock_response = _make_httpx_response(429, json_body={"error": {"code": "rate_limit_exceeded_error"}})
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.tts.sarvam.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.providers.tts.sarvam.record_failure", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        mock_settings.return_value.sarvam_api_key = "test-key"
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = SarvamTTSProvider()
        with pytest.raises(httpx.HTTPStatusError):
            await provider.synthesize("Hello world", "meera")

    assert mock_client.post.call_count == 3, "rate_limit_exceeded_error must be retried up to max_attempts"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sarvam_429_insufficient_quota_is_not_retried() -> None:
    """A 429 with an insufficient_quota_error body must NOT be retried —
    the body-inspection split this AC requires."""
    from app.providers.tts.sarvam import SarvamTTSProvider

    mock_response = _make_httpx_response(429, json_body={"error": {"code": "insufficient_quota_error"}})
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.tts.sarvam.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.providers.tts.sarvam.record_failure", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        mock_settings.return_value.sarvam_api_key = "test-key"
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = SarvamTTSProvider()
        with pytest.raises(RuntimeError, match="insufficient_quota"):
            await provider.synthesize("Hello world", "meera")

    assert mock_client.post.call_count == 1, "insufficient_quota_error must NOT be retried"


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
        patch("app.providers.tts.azure.record_success", new=AsyncMock()),
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
