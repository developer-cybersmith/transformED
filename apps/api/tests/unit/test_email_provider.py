"""
Unit tests for Story 2-52 (S4-12): ResendEmailProvider.

Mirrors test_tts_providers.py's conventions — all HTTP calls mocked via a
fake httpx.AsyncClient, no real network I/O.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


def _make_httpx_response(status_code: int, json_body: dict[str, Any] | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_success_returns_message_id() -> None:
    from app.providers.email.resend import ResendEmailProvider

    mock_response = _make_httpx_response(200, json_body={"id": "msg_123"})
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.return_value.resend_api_key = "test-key"
        mock_settings.return_value.resend_from_email = "notifications@hieiq.ai"
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = ResendEmailProvider()
        message_id = await provider.send(to="student@example.com", subject="Hi", html="<p>Hi</p>")

    assert message_id == "msg_123"
    call_kwargs = mock_client.post.call_args.kwargs
    assert call_kwargs["json"]["to"] == ["student@example.com"]
    assert call_kwargs["json"]["from"] == "notifications@hieiq.ai"
    assert call_kwargs["headers"]["Authorization"] == "Bearer test-key"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_raises_runtime_error_when_api_key_missing() -> None:
    """An unconfigured account is a setup gap, not a transient failure —
    must raise immediately, never retried, never a silent no-op send."""
    from app.providers.email.resend import ResendEmailProvider

    with patch("app.config.get_settings") as mock_settings:
        mock_settings.return_value.resend_api_key = None
        mock_settings.return_value.resend_from_email = "notifications@hieiq.ai"
        provider = ResendEmailProvider()
        with pytest.raises(RuntimeError, match="RESEND_API_KEY"):
            await provider.send(to="student@example.com", subject="Hi", html="<p>Hi</p>")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_401_is_not_retried() -> None:
    from app.providers.email.resend import ResendEmailProvider

    mock_response = _make_httpx_response(401)
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.return_value.resend_api_key = "test-key"
        mock_settings.return_value.resend_from_email = "notifications@hieiq.ai"
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = ResendEmailProvider()
        with pytest.raises(httpx.HTTPStatusError):
            await provider.send(to="student@example.com", subject="Hi", html="<p>Hi</p>")

    assert mock_client.post.call_count == 1, "401 must not be retried"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_429_is_retried_up_to_max_attempts() -> None:
    from app.providers.email.resend import ResendEmailProvider

    mock_response = _make_httpx_response(429)
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("httpx.AsyncClient") as mock_client_cls,
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        mock_settings.return_value.resend_api_key = "test-key"
        mock_settings.return_value.resend_from_email = "notifications@hieiq.ai"
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = ResendEmailProvider()
        with pytest.raises(httpx.HTTPStatusError):
            await provider.send(to="student@example.com", subject="Hi", html="<p>Hi</p>")

    assert mock_client.post.call_count == 3, "429 must be retried up to max_attempts=3"
