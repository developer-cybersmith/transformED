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
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
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
# D118 (2026-08-17): `size` was accepted for interface compatibility only and
# silently discarded — Imagen always returned a square 1:1 image regardless
# of what the caller asked for, the one place a landscape request could not
# actually reach a landscape image even after image_generator_node started
# asking for one.
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_imagen_translates_landscape_size_to_the_matching_aspect_ratio() -> None:
    from app.providers.image.imagen import ImagenProvider

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"predictions": [{"bytesBase64Encoded": "ZmFrZQ=="}]}
    mock_response.raise_for_status.return_value = None
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.image.imagen.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.return_value.google_api_key = "test-key"
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = ImagenProvider(lesson_id="lesson-1")
        # D122: "1280x720" is the REAL current production value
        # (graph.py's `_SLIDE_IMAGE_SIZE`, gpt-image-2's landscape preset)
        # and is itself already EXACT 16:9 (1280*9 == 720*16), so this also
        # proves `_closest_aspect_ratio` picks an exact match at distance 0,
        # not just "closest of a bad lot".
        await provider.generate("A friendly robot teaching a class", size="1280x720")

    sent_body = mock_client.post.call_args.kwargs["json"]
    assert sent_body["parameters"]["aspectRatio"] == "16:9"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_imagen_computes_the_nearest_ratio_for_a_size_never_seen_before() -> None:
    """D122: `_closest_aspect_ratio` is computed, not a lookup table -- it
    must handle a size string NO ONE has ever hardcoded a mapping for
    (unlike the old `_SIZE_TO_ASPECT_RATIO` dict, which silently fell back
    to "1:1" square for anything not listed, and had already gone stale
    twice by the time it was replaced). 3000x2000 = 1.5:1, numerically
    closer to "4:3" (1.333, distance 0.167) than "16:9" (1.778, distance
    0.278) or "1:1" (0.5) -- proving real nearest-match arithmetic, not a
    hardcoded default."""
    from app.providers.image.imagen import ImagenProvider

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"predictions": [{"bytesBase64Encoded": "ZmFrZQ=="}]}
    mock_response.raise_for_status.return_value = None
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.image.imagen.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.return_value.google_api_key = "test-key"
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = ImagenProvider(lesson_id="lesson-1")
        result = await provider.generate("A friendly robot", size="3000x2000")

    assert result == "data:image/png;base64,ZmFrZQ=="
    sent_body = mock_client.post.call_args.kwargs["json"]
    assert sent_body["parameters"]["aspectRatio"] == "4:3"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_imagen_unparseable_size_degrades_to_square_rather_than_raising() -> None:
    """This is the FALLBACK provider — a genuinely malformed size string
    (can't even be split into WxH) must still produce an image (wrong
    shape, right content) rather than fail the whole slide."""
    from app.providers.image.imagen import ImagenProvider

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"predictions": [{"bytesBase64Encoded": "ZmFrZQ=="}]}
    mock_response.raise_for_status.return_value = None
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch("app.config.get_settings") as mock_settings,
        patch("app.providers.image.imagen.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.return_value.google_api_key = "test-key"
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = ImagenProvider(lesson_id="lesson-1")
        result = await provider.generate("A friendly robot", size="not-a-size")

    assert result == "data:image/png;base64,ZmFrZQ=="
    sent_body = mock_client.post.call_args.kwargs["json"]
    assert sent_body["parameters"]["aspectRatio"] == "1:1"


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
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.return_value.google_api_key = "SUPER-SECRET-KEY-VALUE"
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        provider = ImagenProvider(lesson_id="lesson-1")
        with pytest.raises(RuntimeError) as exc_info:
            await provider.generate("A friendly robot", size="1024x1024")

    assert "SUPER-SECRET-KEY-VALUE" not in str(exc_info.value)
    assert "SUPER-SECRET-KEY-VALUE" not in repr(exc_info.value)
    # Neither chaining slot may hold the raw httpx exception, whose str()/repr()
    # embed the key-bearing request URL.
    assert exc_info.value.__cause__ is None
    # 2026-07-29 review: this previously asserted `__suppress_context__ is True`,
    # which pinned the MECHANISM (`raise ... from None`) rather than the
    # property. That mechanism was never sufficient — `from None` leaves
    # `__context__` populated, so anything walking the chain directly (structlog,
    # custom formatters, ad-hoc repr debugging) still saw the key. The provider
    # now raises outside the `except` block so `__context__` is genuinely None,
    # which is strictly stronger and makes the suppress flag irrelevant.
    assert exc_info.value.__context__ is None, (
        "the original httpx exception must not be reachable via __context__ — "
        "its str()/repr() embed the API key"
    )
