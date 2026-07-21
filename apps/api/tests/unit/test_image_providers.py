"""
Unit tests for Story 2-9 (S2-10): OpenAIImageProvider and ImagenProvider.

Covers docs/stories/2-9-image-generator-node.md's ACs:
- AC-4: OpenAIImageProvider (GPT Image 1 Mini) — circuit breaker, retry,
  base64 response decoded into a data: URI.
- AC-5: ImagenProvider (Imagen 4 Fast) — circuit breaker, retry, real HTTP
  call, base64 response decoded into a data: URI.

Both providers import is_circuit_open/record_success/record_failure at
module top level (same convention as app.providers.llm.openai and Story
2-8's TTS providers) — patch targets are the CONSUMER module.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# ---------------------------------------------------------------------------
# OpenAIImageProvider
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_openai_image_success_returns_data_uri() -> None:
    from app.providers.image.openai_image import OpenAIImageProvider

    mock_response = MagicMock()
    mock_response.data = [MagicMock(b64_json="ZmFrZWJhc2U2NA==")]
    mock_client = AsyncMock()
    mock_client.images.generate.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch(
            "app.providers.image.openai_image.is_circuit_open", new=AsyncMock(return_value=False)
        ),
        patch("app.providers.image.openai_image.record_success", new=AsyncMock()),
        patch("app.providers.image.openai_image.AsyncOpenAI", return_value=mock_client),
    ):
        mock_settings.return_value.openai_api_key = "test-key"
        provider = OpenAIImageProvider(lesson_id="lesson-1")
        result = await provider.generate("A friendly robot teaching a class", size="1024x1024")

    assert result == "data:image/png;base64,ZmFrZWJhc2U2NA=="


@pytest.mark.unit
@pytest.mark.asyncio
async def test_openai_image_circuit_open_raises_before_any_call() -> None:
    from app.providers.image.openai_image import OpenAIImageProvider

    mock_client = AsyncMock()

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.image.openai_image.is_circuit_open", new=AsyncMock(return_value=True)),
        patch("app.providers.image.openai_image.AsyncOpenAI", return_value=mock_client),
    ):
        mock_settings.return_value.openai_api_key = "test-key"
        provider = OpenAIImageProvider(lesson_id="lesson-1")
        with pytest.raises(RuntimeError, match="Circuit breaker OPEN"):
            await provider.generate("A friendly robot", size="1024x1024")

    mock_client.images.generate.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_openai_image_missing_b64_json_raises_value_error() -> None:
    """2026-07-15 review finding (Blind Hunter + Edge Case Hunter): the
    speculative `url`-fallback branch was removed entirely (it was the one
    live path that could return an undecodable value) — a missing b64_json
    now always raises, with no alternate success path."""
    from app.providers.image.openai_image import OpenAIImageProvider

    mock_response = MagicMock()
    mock_response.data = [MagicMock(b64_json=None)]
    mock_client = AsyncMock()
    mock_client.images.generate.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch(
            "app.providers.image.openai_image.is_circuit_open", new=AsyncMock(return_value=False)
        ),
        patch("app.providers.image.openai_image.record_failure", new=AsyncMock()),
        patch("app.providers.image.openai_image.AsyncOpenAI", return_value=mock_client),
    ):
        mock_settings.return_value.openai_api_key = "test-key"
        provider = OpenAIImageProvider(lesson_id="lesson-1")
        with pytest.raises(ValueError, match="empty"):
            await provider.generate("A friendly robot", size="1024x1024")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_openai_image_retryable_error_retries_exactly_twice_then_raises() -> None:
    """2026-07-20 review finding (Test Coverage layer): the fallback chain was
    only ever exercised with NON-retryable errors (instant abort), so the
    @with_retry(max_attempts=2) 'optional node' contract was unverified. A
    retryable 503 must cause exactly TWO attempts (one retry) before exhausting
    — proving the optional-node retry budget, and the caller (node) then
    cascades to Imagen."""
    from app.providers.image.openai_image import OpenAIImageProvider

    request = httpx.Request("POST", "https://api.openai.com/v1/images/generations")
    err = httpx.HTTPStatusError(
        "503", request=request, response=httpx.Response(503, request=request)
    )
    mock_client = AsyncMock()
    mock_client.images.generate.side_effect = err

    with (
        patch("app.config.get_settings") as mock_settings,
        patch(
            "app.providers.image.openai_image.is_circuit_open",
            new=AsyncMock(return_value=False),
        ),
        patch("app.providers.image.openai_image.record_failure", new=AsyncMock()),
        patch("app.providers.image.openai_image.AsyncOpenAI", return_value=mock_client),
        patch("app.core.retry.asyncio.sleep", new=AsyncMock()),  # no real backoff wait
    ):
        mock_settings.return_value.openai_api_key = "test-key"
        provider = OpenAIImageProvider(lesson_id="lesson-1")
        with pytest.raises(httpx.HTTPStatusError):
            await provider.generate("A friendly robot", size="1024x1024")

    assert mock_client.images.generate.call_count == 2  # exactly max_attempts=2


# ---------------------------------------------------------------------------
# ImagenProvider
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_imagen_success_returns_data_uri() -> None:
    from app.providers.image.imagen import ImagenProvider

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"predictions": [{"bytesBase64Encoded": "ZmFrZWltYWdlbg=="}]}
    mock_response.raise_for_status.return_value = None
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.image.imagen.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.providers.image.imagen.record_success", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.return_value.google_api_key = "test-key"
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = ImagenProvider(lesson_id="lesson-1")
        result = await provider.generate("A friendly robot teaching a class", size="1024x1024")

    assert result == "data:image/png;base64,ZmFrZWltYWdlbg=="


@pytest.mark.unit
@pytest.mark.asyncio
async def test_imagen_circuit_open_raises_before_any_http_call() -> None:
    from app.providers.image.imagen import ImagenProvider

    mock_client = AsyncMock()

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.image.imagen.is_circuit_open", new=AsyncMock(return_value=True)),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.return_value.google_api_key = "test-key"
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = ImagenProvider(lesson_id="lesson-1")
        with pytest.raises(RuntimeError, match="Circuit breaker OPEN"):
            await provider.generate("A friendly robot", size="1024x1024")

    mock_client.post.assert_not_called()


# ---------------------------------------------------------------------------
# 2026-07-15 code review patches
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_imagen_http_error_does_not_leak_api_key_in_exception() -> None:
    """CRITICAL review finding (Blind Hunter): an HTTP error must never
    surface the raw httpx exception (whose message embeds the full request
    URL, including the ?key=... query param) — only a redacted RuntimeError
    with no key in it."""
    from app.providers.image.imagen import ImagenProvider

    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "429 rate limited for url 'https://generativelanguage.googleapis.com/v1beta/models/"
        "imagen-4.0-fast-generate-001:predict?key=SUPER-SECRET-KEY-VALUE'",
        request=MagicMock(),
        response=mock_response,
    )
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.image.imagen.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.providers.image.imagen.record_failure", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.return_value.google_api_key = "SUPER-SECRET-KEY-VALUE"
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = ImagenProvider(lesson_id="lesson-1")
        with pytest.raises(RuntimeError) as exc_info:
            await provider.generate("A friendly robot", size="1024x1024")

    assert "SUPER-SECRET-KEY-VALUE" not in str(exc_info.value)
    assert "SUPER-SECRET-KEY-VALUE" not in repr(exc_info.value)
    # __cause__ must not be the raw httpx exception with the key embedded —
    # `from None` suppresses it from any exc_info=True traceback formatting.
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True
