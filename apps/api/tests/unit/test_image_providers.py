"""
Unit tests for Story 2-9 (S2-10): OpenAIImageProvider, and Story 5-8b:
NanoBananaProvider.

Covers docs/stories/2-9-image-generator-node.md's ACs:
- AC-4: OpenAIImageProvider (GPT Image 2, now the FALLBACK tier per Story
  5-8b) — circuit breaker, retry, base64 response decoded into a data: URI.

Covers docs/stories/5-8b-nano-banana-migration.md's ACs:
- AC2: NanoBananaProvider (Gemini "Nano Banana", now the PRIMARY tier) —
  circuit breaker, retry, real HTTP call, base64 response decoded into a
  data: URI. Replaces ImagenProvider (Imagen 4 Fast), deleted per D121 —
  its endpoint was shut down by Google 2026-08-17.

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
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
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
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()),
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
    — proving the optional-node retry budget. (GPT Image 2 is now the FALLBACK
    tier per Story 5-8b; the caller degrades to text-only from here, since
    nothing is tried after it.)"""
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
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()),
        patch("app.providers.image.openai_image.AsyncOpenAI", return_value=mock_client),
        patch("app.core.retry.asyncio.sleep", new=AsyncMock()),  # no real backoff wait
    ):
        mock_settings.return_value.openai_api_key = "test-key"
        provider = OpenAIImageProvider(lesson_id="lesson-1")
        with pytest.raises(httpx.HTTPStatusError):
            await provider.generate("A friendly robot", size="1024x1024")

    assert mock_client.images.generate.call_count == 2  # exactly max_attempts=2


# ---------------------------------------------------------------------------
# D122 (2026-08-18): `_validate_size` — gpt-image-2's real custom-size
# constraints, checked BEFORE any network call so a bad size raises with a
# specific reason instead of surfacing as an opaque API 400 two layers down.
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("size", ["1024x1024", "1280x720", "2048x1152", "3840x2160"])
def test_validate_size_accepts_every_known_valid_size(size: str) -> None:
    from app.providers.image.openai_image import _validate_size

    _validate_size(size)  # must not raise


@pytest.mark.unit
def test_validate_size_rejects_malformed_string() -> None:
    from app.providers.image.openai_image import _validate_size

    with pytest.raises(ValueError, match="malformed size string"):
        _validate_size("not-a-size")


@pytest.mark.unit
def test_validate_size_rejects_edge_over_the_max() -> None:
    from app.providers.image.openai_image import _validate_size

    with pytest.raises(ValueError, match="max edge"):
        _validate_size("4096x2304")  # 4096 > 3840, both still mult of 16


@pytest.mark.unit
def test_validate_size_rejects_an_edge_not_a_multiple_of_16() -> None:
    from app.providers.image.openai_image import _validate_size

    with pytest.raises(ValueError, match="multiples of 16"):
        _validate_size("1000x720")  # 1000 is not a multiple of 16


@pytest.mark.unit
def test_validate_size_rejects_a_long_short_ratio_over_3_to_1() -> None:
    from app.providers.image.openai_image import _validate_size

    # 3840x1024: ratio 3.75, exceeds 3:1; both edges are multiples of 16 and
    # under the max edge, so this isolates the ratio check specifically.
    with pytest.raises(ValueError, match="ratio"):
        _validate_size("3840x1024")


@pytest.mark.unit
def test_validate_size_rejects_too_few_total_pixels() -> None:
    from app.providers.image.openai_image import _validate_size

    with pytest.raises(ValueError, match="total px"):
        _validate_size("256x144")  # far below the 655,360 floor


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generate_raises_before_any_network_call_on_an_invalid_size() -> None:
    """Integration proof: the real `generate()` path calls `_validate_size`
    first — a bad size must never reach the circuit breaker or the API
    client at all."""
    from app.providers.image.openai_image import OpenAIImageProvider

    mock_client = AsyncMock()

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.image.openai_image.AsyncOpenAI", return_value=mock_client),
    ):
        mock_settings.return_value.openai_api_key = "test-key"
        provider = OpenAIImageProvider(lesson_id="lesson-1")
        with pytest.raises(ValueError, match="malformed size string"):
            await provider.generate("A friendly robot", size="bogus")

    mock_client.images.generate.assert_not_called()


# ---------------------------------------------------------------------------
# NanoBananaProvider (Story 5-8b — Gemini "Nano Banana", PRIMARY as of D121's
# migration; replaces the dead ImagenProvider fallback tier, and becomes
# primary rather than fallback per team preference for Gemini's image
# quality). Raw httpx against Google's generateContent endpoint, same as
# ImagenProvider was — mirrors its mocking pattern, not OpenAIImageProvider's
# SDK pattern. Authenticates via the `x-goog-api-key` HEADER (Gemini's
# documented convention), NOT a URL query parameter like Imagen did — so the
# URL-embeds-the-key leak class of bug ImagenProvider guards against does
# not apply here the same way; still tested defensively below.
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nano_banana_success_returns_data_uri() -> None:
    from app.providers.image.nano_banana import NanoBananaProvider

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [{"inlineData": {"mimeType": "image/png", "data": "ZmFrZWltYWdlbg=="}}]
                }
            }
        ]
    }
    mock_response.raise_for_status.return_value = None
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.image.nano_banana.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.return_value.google_api_key = "test-key"
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = NanoBananaProvider(lesson_id="lesson-1")
        result = await provider.generate("A friendly robot teaching a class", size="1280x720")

    assert result == "data:image/png;base64,ZmFrZWltYWdlbg=="


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nano_banana_circuit_open_raises_before_any_http_call() -> None:
    from app.providers.image.nano_banana import NanoBananaProvider

    mock_client = AsyncMock()

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.image.nano_banana.is_circuit_open", new=AsyncMock(return_value=True)),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.return_value.google_api_key = "test-key"
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = NanoBananaProvider(lesson_id="lesson-1")
        with pytest.raises(RuntimeError, match="Circuit breaker OPEN"):
            await provider.generate("A friendly robot", size="1024x1024")

    mock_client.post.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nano_banana_authenticates_via_header_not_url_query_param() -> None:
    """Gemini's documented auth convention is the `x-goog-api-key` header —
    unlike Imagen's `?key=...` query param, the key must never appear in the
    request URL at all (not just "never leak via an exception")."""
    from app.providers.image.nano_banana import NanoBananaProvider

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [
            {"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": "ZmFrZQ=="}}]}}
        ]
    }
    mock_response.raise_for_status.return_value = None
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.image.nano_banana.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.return_value.google_api_key = "SUPER-SECRET-KEY-VALUE"
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = NanoBananaProvider(lesson_id="lesson-1")
        await provider.generate("A friendly robot", size="1024x1024")

    call = mock_client.post.call_args
    assert "SUPER-SECRET-KEY-VALUE" not in call.args[0], (
        "API key must not appear in the request URL"
    )
    sent_headers = call.kwargs.get("headers") or {}
    assert sent_headers.get("x-goog-api-key") == "SUPER-SECRET-KEY-VALUE"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nano_banana_translates_landscape_size_to_the_matching_aspect_ratio() -> None:
    """Mirrors D118's Imagen fix — Gemini's image config also takes an
    aspect-ratio enum, not raw pixel dimensions, so the same "WxH" ->
    nearest-enum translation is needed here too."""
    from app.providers.image.nano_banana import NanoBananaProvider

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [
            {"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": "ZmFrZQ=="}}]}}
        ]
    }
    mock_response.raise_for_status.return_value = None
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.image.nano_banana.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.return_value.google_api_key = "test-key"
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = NanoBananaProvider(lesson_id="lesson-1")
        # "1280x720" is the real current production value (graph.py's
        # _SLIDE_IMAGE_SIZE) and is itself exact 16:9.
        await provider.generate("A friendly robot teaching a class", size="1280x720")

    sent_body = mock_client.post.call_args.kwargs["json"]
    assert sent_body["generationConfig"]["imageConfig"]["aspectRatio"] == "16:9"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nano_banana_unparseable_size_degrades_to_square_rather_than_raising() -> None:
    from app.providers.image.nano_banana import NanoBananaProvider

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [
            {"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": "ZmFrZQ=="}}]}}
        ]
    }
    mock_response.raise_for_status.return_value = None
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.image.nano_banana.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.return_value.google_api_key = "test-key"
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = NanoBananaProvider(lesson_id="lesson-1")
        result = await provider.generate("A friendly robot", size="not-a-size")

    assert result == "data:image/png;base64,ZmFrZQ=="
    sent_body = mock_client.post.call_args.kwargs["json"]
    assert sent_body["generationConfig"]["imageConfig"]["aspectRatio"] == "1:1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nano_banana_empty_response_raises_value_error() -> None:
    """No candidates / no inlineData part must raise, not silently return a
    None-shaped success — the caller (_generate_image_with_fallback) treats
    any exception here as "try the next tier", never a false success."""
    from app.providers.image.nano_banana import NanoBananaProvider

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"candidates": []}
    mock_response.raise_for_status.return_value = None
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.image.nano_banana.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.return_value.google_api_key = "test-key"
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = NanoBananaProvider(lesson_id="lesson-1")
        with pytest.raises(ValueError, match="empty response"):
            await provider.generate("A friendly robot", size="1024x1024")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nano_banana_retryable_error_retries_exactly_twice_then_raises() -> None:
    """Mirrors test_openai_image_retryable_error_retries_exactly_twice_then_raises
    (openai_image.py's pattern): a retryable error propagates as its OWN
    exception type (httpx.HTTPStatusError), not wrapped — unlike
    ImagenProvider's SanitizedHTTPError, which exists ONLY because Imagen's
    key lived in the URL. Nano Banana authenticates via a header, so there
    is nothing to redact and no wrapping is needed."""
    from app.providers.image.nano_banana import NanoBananaProvider

    request = httpx.Request("POST", "https://generativelanguage.googleapis.com/v1/models/x")
    err_response = httpx.Response(503, request=request)
    err = httpx.HTTPStatusError("503", request=request, response=err_response)
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = err
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.image.nano_banana.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
        patch("app.core.retry.asyncio.sleep", new=AsyncMock()),
    ):
        mock_settings.return_value.google_api_key = "test-key"
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = NanoBananaProvider(lesson_id="lesson-1")
        with pytest.raises(httpx.HTTPStatusError):
            await provider.generate("A friendly robot", size="1024x1024")

    assert mock_client.post.call_count == 2, "with_retry(max_attempts=2) must retry exactly once"
