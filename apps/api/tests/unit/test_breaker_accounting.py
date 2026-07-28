"""Story 2-32 AC-3/AC-4: the circuit breaker counts LOGICAL calls, not attempts.

Why this file exists
--------------------
`record_failure()` used to be called INSIDE the function wrapped by
`@with_retry`. While OpenAI SDK exceptions were never classified (Story 2-32
AC-1), that was invisible: a 429 produced exactly one attempt and therefore one
recorded failure.

The moment AC-1 makes those exceptions retryable, one logical call becomes
`max_attempts` attempts and therefore `max_attempts` recorded failures:

    FAILURE_THRESHOLD = 5, FAILURE_WINDOW_SECONDS = 120

    before: 1 failure/call  -> breaker opens after 5 logical calls
    naive:  3 failures/call -> breaker opens after 2 logical calls

i.e. shipping AC-1 alone would make the breaker trip ~2.5x faster and convert a
brief rate-limit into a 10-minute half-open outage across every lesson in
flight. **AC-1 is only safe to ship together with AC-3.** These tests are what
enforce that.

Chosen mid-retry semantics (AC-4)
---------------------------------
`is_circuit_open` is checked on EVERY attempt, inside the retried function. If
the breaker opens mid-retry — because other concurrent calls tripped it — the
remaining attempts short-circuit immediately instead of continuing to hammer a
provider already known to be down. That rejection raises `CircuitOpenError`,
which the accounting wrapper deliberately does NOT count as a failure: counting
a rejection as a failure would let the breaker feed itself and never close.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

FAKE_LESSON_ID = "55555555-5555-5555-5555-555555555555"


def _openai_429() -> Exception:
    import openai

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    return openai.RateLimitError(
        "rate limited", response=httpx.Response(429, request=request), body=None
    )


def _chat_response(content: str = "hello") -> MagicMock:
    resp = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    resp.choices = [choice]
    resp.usage.prompt_tokens = 1
    resp.usage.completion_tokens = 1
    return resp


def _llm_patches(
    *,
    side_effect: Any = None,
    return_value: Any = None,
    circuit_open: Any = False,
) -> tuple[Any, ...]:
    """Patch set for app.providers.llm.openai, with breaker calls observable."""
    client = MagicMock()
    if side_effect is not None:
        client.chat.completions.create = AsyncMock(side_effect=side_effect)
    else:
        client.chat.completions.create = AsyncMock(return_value=return_value or _chat_response())

    mod = "app.providers.llm.openai"
    open_mock = (
        AsyncMock(side_effect=circuit_open)
        if isinstance(circuit_open, list)
        else AsyncMock(return_value=circuit_open)
    )
    return (
        patch(f"{mod}.AsyncOpenAI", return_value=client),
        patch(f"{mod}.get_langfuse", MagicMock(return_value=None)),
        patch(f"{mod}.is_circuit_open", new=open_mock),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()),
        patch("asyncio.sleep", new=AsyncMock()),  # no real backoff waits
        # Cost accumulation touches Redis on the success path; irrelevant here.
        patch("app.core.cost_tracker.accumulate_cost", new=AsyncMock(return_value=0.0)),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch("app.core.cost_tracker.get_cost", new=AsyncMock(return_value=0.0)),
    )


async def _run_complete(patches: tuple[Any, ...]) -> Any:  # noqa: ANN401
    from app.providers.llm.openai import OpenAILLMProvider

    provider = OpenAILLMProvider(lesson_id=FAKE_LESSON_ID)
    return await provider.complete([{"role": "user", "content": "hi"}], "gpt-4o-mini")


# ── AC-3: one logical call -> at most one record_failure ─────────────────────


async def test_retried_call_records_exactly_one_failure() -> None:
    """THE test this story exists for.

    A 429 that exhausts all 3 attempts is ONE logical failure. Recording it 3
    times silently retunes FAILURE_THRESHOLD from 5 logical calls to 2.
    """
    import openai

    p = _llm_patches(side_effect=_openai_429())
    with p[0], p[1], p[2], p[3], p[4] as record_failure, p[5], p[6], p[7], p[8]:
        with pytest.raises(openai.RateLimitError):
            await _run_complete(p)

    assert record_failure.await_count == 1, (
        f"expected 1 failure per logical call, got {record_failure.await_count} — "
        "the breaker would trip 3x too fast"
    )


async def test_retry_actually_happened_in_that_scenario() -> None:
    """Guards the test above from passing for the wrong reason: if the 429 were
    not retried at all, record_failure would trivially be 1."""
    import openai

    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=_openai_429())
    mod = "app.providers.llm.openai"

    with (
        patch(f"{mod}.AsyncOpenAI", return_value=client),
        patch(f"{mod}.get_langfuse", MagicMock(return_value=None)),
        patch(f"{mod}.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()),
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        from app.providers.llm.openai import OpenAILLMProvider

        provider = OpenAILLMProvider(lesson_id=FAKE_LESSON_ID)
        with pytest.raises(openai.RateLimitError):
            await provider.complete([{"role": "user", "content": "hi"}], "gpt-4o-mini")

    assert client.chat.completions.create.await_count == 3, (
        "AC-1 must retry a 429 three times — otherwise AC-3 proves nothing"
    )


async def test_transient_failure_then_success_records_no_failure() -> None:
    """A call that fails once and then succeeds is a SUCCESS, not a failure.
    Recording a failure for it would drift the breaker toward opening on a
    provider that is working."""
    p = _llm_patches(side_effect=[_openai_429(), _chat_response("recovered")])
    with p[0], p[1], p[2], p[3] as record_success, p[4] as record_failure, p[5], p[6], p[7], p[8]:
        result = await _run_complete(p)

    assert result == "recovered"
    assert record_failure.await_count == 0, "a recovered call is not a failure"
    record_success.assert_awaited_once()


async def test_success_records_exactly_one_success() -> None:
    p = _llm_patches()
    with p[0], p[1], p[2], p[3] as record_success, p[4] as record_failure, p[5], p[6], p[7], p[8]:
        await _run_complete(p)

    record_success.assert_awaited_once()
    assert record_failure.await_count == 0


async def test_complete_structured_also_records_one_failure_per_logical_call() -> None:
    """complete_structured is a second @with_retry call site — the accounting
    fix has to cover it too, not just complete()."""
    import openai
    from pydantic import BaseModel

    class _Out(BaseModel):
        value: str

    client = MagicMock()
    client.beta.chat.completions.parse = AsyncMock(side_effect=_openai_429())
    mod = "app.providers.llm.openai"

    with (
        patch(f"{mod}.AsyncOpenAI", return_value=client),
        patch(f"{mod}.get_langfuse", MagicMock(return_value=None)),
        patch(f"{mod}.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()) as record_failure,
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        from app.providers.llm.openai import OpenAILLMProvider

        provider = OpenAILLMProvider(lesson_id=FAKE_LESSON_ID)
        with pytest.raises(openai.RateLimitError):
            await provider.complete_structured(
                [{"role": "user", "content": "hi"}], "gpt-4o-mini", _Out
            )

    assert record_failure.await_count == 1


# ── AC-4: circuit-open behaviour ─────────────────────────────────────────────


async def test_circuit_open_rejection_is_not_counted_as_a_failure() -> None:
    """If a rejection counted as a failure, the breaker would feed itself: every
    rejected call would extend the very window keeping it open, and it could
    never close."""
    from app.core.circuit_breaker import CircuitOpenError

    p = _llm_patches(circuit_open=True)
    with p[0], p[1], p[2], p[3], p[4] as record_failure, p[5], p[6], p[7], p[8]:
        with pytest.raises(CircuitOpenError):
            await _run_complete(p)

    assert record_failure.await_count == 0, "a rejection is not a provider failure"


async def test_circuit_open_rejection_is_not_retried() -> None:
    """Retrying against a breaker that is already open is pure latency. This was
    today's behaviour via the unknown-exception branch; it must survive AC-1
    widening the classification."""
    from app.core.circuit_breaker import CircuitOpenError

    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_chat_response())
    mod = "app.providers.llm.openai"
    is_open = AsyncMock(return_value=True)

    with (
        patch(f"{mod}.AsyncOpenAI", return_value=client),
        patch(f"{mod}.get_langfuse", MagicMock(return_value=None)),
        patch(f"{mod}.is_circuit_open", new=is_open),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()),
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        from app.providers.llm.openai import OpenAILLMProvider

        provider = OpenAILLMProvider(lesson_id=FAKE_LESSON_ID)
        with pytest.raises(CircuitOpenError):
            await provider.complete([{"role": "user", "content": "hi"}], "gpt-4o-mini")

    assert is_open.await_count == 1, "an open circuit must be checked once, not retried against"
    client.chat.completions.create.assert_not_awaited()


async def test_circuit_opening_mid_retry_short_circuits_remaining_attempts() -> None:
    """AC-4, documented semantics: the breaker is checked on EVERY attempt. If
    concurrent traffic trips it while we are backing off, stop rather than
    finish the remaining attempts against a provider known to be down.

    Sequence: attempt 1 sees a closed circuit and gets a 429; before attempt 2
    the circuit is open, so attempt 2 rejects without calling the provider.
    """
    from app.core.circuit_breaker import CircuitOpenError

    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=_openai_429())
    mod = "app.providers.llm.openai"
    # closed on attempt 1, open from attempt 2 onward
    is_open = AsyncMock(side_effect=[False, True, True])

    with (
        patch(f"{mod}.AsyncOpenAI", return_value=client),
        patch(f"{mod}.get_langfuse", MagicMock(return_value=None)),
        patch(f"{mod}.is_circuit_open", new=is_open),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()) as record_failure,
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        from app.providers.llm.openai import OpenAILLMProvider

        provider = OpenAILLMProvider(lesson_id=FAKE_LESSON_ID)
        with pytest.raises(CircuitOpenError):
            await provider.complete([{"role": "user", "content": "hi"}], "gpt-4o-mini")

    assert client.chat.completions.create.await_count == 1, (
        "attempt 2 must not reach the provider once the circuit opened"
    )
    assert record_failure.await_count == 0, (
        "the terminal outcome was a rejection, not a provider failure"
    )


async def test_circuit_open_error_is_a_runtimeerror_subclass() -> None:
    """Existing handlers catch RuntimeError (e.g. sarvam's `except RuntimeError:
    raise` guard). Keeping CircuitOpenError a RuntimeError subclass means this
    story does not silently change their behaviour."""
    from app.core.circuit_breaker import CircuitOpenError

    assert issubclass(CircuitOpenError, RuntimeError)


# ── AC-3 across the other refactored @with_retry call sites ──────────────────


async def test_embeddings_records_one_failure_per_logical_call() -> None:
    """embed_texts is a third @with_retry call site (max_attempts=3)."""
    import openai

    client = MagicMock()
    client.embeddings.create = AsyncMock(side_effect=_openai_429())
    mod = "app.providers.embeddings.openai"

    with (
        patch(f"{mod}.AsyncOpenAI", return_value=client),
        patch(f"{mod}.get_langfuse", MagicMock(return_value=None)),
        patch(f"{mod}.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()) as record_failure,
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        from app.providers.embeddings.openai import OpenAIEmbeddingsProvider

        provider = OpenAIEmbeddingsProvider()
        with pytest.raises(openai.RateLimitError):
            await provider.embed_texts(["a"])

    assert client.embeddings.create.await_count == 3, "AC-1: the 429 must be retried"
    assert record_failure.await_count == 1, "AC-3: one logical call, one recorded failure"


async def test_image_provider_records_one_failure_per_logical_call() -> None:
    """generate() is the fourth call site, and uses max_attempts=2 — proving the
    fix is not accidentally coupled to a hardcoded attempt count of 3."""
    import openai

    client = MagicMock()
    client.images.generate = AsyncMock(side_effect=_openai_429())
    mod = "app.providers.image.openai_image"

    with (
        patch(f"{mod}.AsyncOpenAI", return_value=client),
        patch(f"{mod}.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()) as record_failure,
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        from app.providers.image.openai_image import OpenAIImageProvider

        provider = OpenAIImageProvider()
        with pytest.raises(openai.RateLimitError):
            await provider.generate("a cat")

    assert client.images.generate.await_count == 2, "max_attempts=2 for this provider"
    assert record_failure.await_count == 1


# ── AC-5: Imagen retries again WITHOUT leaking the API key ───────────────────

_FAKE_IMAGEN_KEY = "AIzaSy-SUPER-SECRET-KEY-do-not-log"


async def test_imagen_retryable_error_is_retried_and_never_leaks_the_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC-5. imagen.py catches httpx.HTTPError and re-raises a SANITIZED
    RuntimeError because the API key travels in the request URL and httpx
    embeds the full URL in its exception repr. The redaction is correct and must
    stay — but it converted retryable 429/503 into a class `with_retry` would
    never retry, making `@with_retry(max_attempts=2)` decorative.

    Both properties are asserted together on purpose: a fix that restores retry
    by dropping the sanitization would pass a retry-only test.
    """
    import logging

    request = httpx.Request("POST", f"https://imagen.example/v1:predict?key={_FAKE_IMAGEN_KEY}")
    response = httpx.Response(503, request=request)
    # 2026-07-29 review: this used to be HTTPStatusError("503", ...), whose str()
    # is literally "503" — the key lived only in request.url. That made all three
    # no-leak assertions VACUOUS: deleting the sanitization entirely left them
    # green. Real `response.raise_for_status()` embeds the full URL in the
    # message, so the fixture must too or the test cannot fail for the right reason.
    http_error = httpx.HTTPStatusError(
        f"Server error '503 Service Unavailable' for url '{request.url}'",
        request=request,
        response=response,
    )
    assert _FAKE_IMAGEN_KEY in str(http_error), "fixture must be able to leak, or it proves nothing"

    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(side_effect=http_error)

    mod = "app.providers.image.imagen"
    with (
        caplog.at_level(logging.DEBUG),
        patch(f"{mod}.httpx.AsyncClient", return_value=client),
        patch(f"{mod}.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()) as record_failure,
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        from app.providers.image.imagen import ImagenProvider

        provider = ImagenProvider()
        provider._api_key = _FAKE_IMAGEN_KEY  # noqa: SLF001
        with pytest.raises(Exception) as excinfo:  # noqa: PT011
            await provider.generate("a cat")

    exc = excinfo.value
    assert client.post.await_count == 2, (
        "a retryable 503 must be retried — max_attempts=2 for this provider"
    )
    assert record_failure.await_count == 1, "AC-3 still holds on the retried path"

    # AC-5: the key must appear nowhere a human or Sentry could read it.
    assert _FAKE_IMAGEN_KEY not in str(exc)
    assert _FAKE_IMAGEN_KEY not in repr(exc)
    assert _FAKE_IMAGEN_KEY not in caplog.text
    assert exc.__cause__ is None, "the redaction must be preserved (AC-6)"
    assert exc.__context__ is None, (
        "__context__ must be cleared too — `from None` alone leaves the httpx "
        "exception reachable, and its str()/repr() embed the key-bearing URL"
    )


async def test_imagen_non_retryable_error_still_sanitized_and_not_retried() -> None:
    """A 401 is non-retryable per PRD §14 and must still be redacted."""
    request = httpx.Request("POST", f"https://imagen.example/v1:predict?key={_FAKE_IMAGEN_KEY}")
    response = httpx.Response(401, request=request)
    http_error = httpx.HTTPStatusError(
        f"Client error '401 Unauthorized' for url '{request.url}'",
        request=request,
        response=response,
    )

    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(side_effect=http_error)

    mod = "app.providers.image.imagen"
    with (
        patch(f"{mod}.httpx.AsyncClient", return_value=client),
        patch(f"{mod}.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()),
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        from app.providers.image.imagen import ImagenProvider

        provider = ImagenProvider()
        provider._api_key = _FAKE_IMAGEN_KEY  # noqa: SLF001
        with pytest.raises(Exception) as excinfo:  # noqa: PT011
            await provider.generate("a cat")

    assert client.post.await_count == 1, "401 must NOT be retried"
    assert _FAKE_IMAGEN_KEY not in str(excinfo.value)


# ── AC-3 on the TTS providers — a PRE-EXISTING defect, not one this story caused ─
#
# Sarvam and Azure use raw httpx, so `with_retry` always classified their errors
# correctly and they ALWAYS retried. That means they have always recorded
# max_attempts failures for one logical call — the breaker for the TTS chain has
# been tripping ~3x too fast in production, independent of Story 2-32's AC-1.
# Measured before the fix: 3 post attempts -> 3 record_failure calls.
#
# This is why the accounting fix was applied here too, despite AC-7's "no
# production change to sarvam.py": AC-7's testable content is the quota/rate-limit
# BEHAVIOUR, which the two tests below and the pre-existing
# test_sarvam_429_* tests all pin, and which is unchanged.


def _sarvam_429(code: str) -> MagicMock:
    """A 429 response whose JSON body carries *code*."""
    request = httpx.Request("POST", "https://api.sarvam.ai/text-to-speech")
    resp = MagicMock()
    resp.status_code = 429
    resp.json = MagicMock(return_value={"error": {"code": code}})
    resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "429", request=request, response=httpx.Response(429, request=request)
        )
    )
    return resp


def _httpx_client(response: MagicMock) -> MagicMock:
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=response)
    return client


async def test_sarvam_rate_limit_retries_but_records_one_failure() -> None:
    """AC-3 + AC-7 together: a non-quota 429 is STILL retried (unchanged
    behaviour), but the three attempts now count as one logical failure."""
    client = _httpx_client(_sarvam_429("rate_limit_exceeded_error"))
    mod = "app.providers.tts.sarvam"

    with (
        patch(f"{mod}.httpx.AsyncClient", return_value=client),
        patch(f"{mod}.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()) as record_failure,
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        from app.providers.tts.sarvam import SarvamTTSProvider

        provider = SarvamTTSProvider()
        with pytest.raises(httpx.HTTPStatusError):
            await provider.synthesize("hello", "meera")

    assert client.post.await_count == 3, "AC-7: a non-quota 429 must still be retried"
    assert record_failure.await_count == 1, (
        "AC-3: 3 attempts is ONE logical failure — this was 3 before the fix"
    )


async def test_sarvam_insufficient_quota_still_not_retried_and_records_one_failure() -> None:
    """AC-7: the deliberate quota branch is unchanged — one attempt, no retry —
    and it still records exactly one failure now that guard_breaker owns it."""
    client = _httpx_client(_sarvam_429("insufficient_quota_error"))
    mod = "app.providers.tts.sarvam"

    with (
        patch(f"{mod}.httpx.AsyncClient", return_value=client),
        patch(f"{mod}.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()) as record_failure,
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        from app.providers.tts.sarvam import SarvamTTSProvider

        provider = SarvamTTSProvider()
        with pytest.raises(RuntimeError, match="insufficient_quota"):
            await provider.synthesize("hello", "meera")

    assert client.post.await_count == 1, "AC-7: quota exhaustion must NOT be retried"
    assert record_failure.await_count == 1, "counted once, not zero and not twice"


async def test_tts_providers_no_longer_record_breaker_outcomes_themselves() -> None:
    """Structural guard: accounting must live ONLY in guard_breaker. If a future
    edit re-adds record_failure to a provider module, that provider silently
    goes back to counting attempts instead of logical calls — the exact defect
    this story fixed, and one no behavioural test would obviously catch."""
    import inspect

    import app.providers.embeddings.openai as emb
    import app.providers.image.imagen as imagen
    import app.providers.image.openai_image as oai_img
    import app.providers.llm.openai as llm
    import app.providers.tts.azure as azure
    import app.providers.tts.sarvam as sarvam

    for mod in (llm, emb, oai_img, imagen, sarvam, azure):
        for name in ("record_failure", "record_success"):
            assert not hasattr(mod, name), (
                f"{mod.__name__} imports {name} directly — breaker accounting must "
                "go through guard_breaker so it counts logical calls, not attempts"
            )
        # Negative assertions alone are not enough: deleting the guard_breaker
        # wrapper entirely also satisfies them, leaving the provider with ZERO
        # accounting. And an aliased call (`from app.core import circuit_breaker`
        # then `circuit_breaker.record_failure(...)`) evades hasattr while
        # reintroducing the exact per-attempt defect. Source inspection catches both.
        source = inspect.getsource(mod)
        assert "guard_breaker(" in source, (
            f"{mod.__name__} no longer routes through guard_breaker — it has no "
            "breaker accounting at all"
        )
        assert "record_failure(" not in source and "record_success(" not in source, (
            f"{mod.__name__} calls a record_* function directly (possibly via an "
            "aliased module import) — accounting must live only in guard_breaker"
        )


# ── Review round: gaps the first pass left ───────────────────────────────────


async def test_azure_retries_but_records_one_failure() -> None:
    """AC-3 for Azure — the one refactored provider with no behavioural test.

    A mutation reinstating per-attempt `record_failure` in `azure.py` (via an
    aliased module import, which evades the structural hasattr guard) left the
    ENTIRE suite green. Azure is the production TTS fallback; a regression here
    would have shipped silently.
    """
    request = httpx.Request("POST", "https://region.tts.speech.microsoft.com/v1")
    resp = MagicMock()
    resp.status_code = 503
    resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "503", request=request, response=httpx.Response(503, request=request)
        )
    )
    client = _httpx_client(resp)
    mod = "app.providers.tts.azure"

    with (
        patch(f"{mod}.httpx.AsyncClient", return_value=client),
        patch(f"{mod}.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()) as record_failure,
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        from app.providers.tts.azure import AzureTTSProvider

        provider = AzureTTSProvider()
        with pytest.raises(httpx.HTTPStatusError):
            await provider.synthesize("hello", "en-IN-NeerjaNeural")

    assert client.post.await_count == 3, "a 503 must still be retried"
    assert record_failure.await_count == 1, "AC-3: 3 attempts is ONE logical failure"


async def test_sanitized_error_does_not_retain_the_original_via_context() -> None:
    """The `__context__` leak.

    `raise ... from None` sets `__cause__ = None` and `__suppress_context__ =
    True`, but the raise statement STILL binds `__context__` to the httpx
    exception — whose str()/repr() embed the key-bearing URL. Default traceback
    formatting honours the suppress flag, but anything walking the chain
    directly (structlog, custom formatters, ad-hoc repr debugging) reproduces
    the exact leak the redaction exists to prevent.
    """
    request = httpx.Request("POST", f"https://imagen.example/v1:predict?key={_FAKE_IMAGEN_KEY}")
    response = httpx.Response(503, request=request)
    http_error = httpx.HTTPStatusError(
        f"Server error 503 for url {request.url}", request=request, response=response
    )
    assert _FAKE_IMAGEN_KEY in str(http_error), "premise: the real error DOES carry the key"

    client = _httpx_client(MagicMock())
    client.post = AsyncMock(side_effect=http_error)
    mod = "app.providers.image.imagen"

    with (
        patch(f"{mod}.httpx.AsyncClient", return_value=client),
        patch(f"{mod}.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()),
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        from app.providers.image.imagen import ImagenProvider

        provider = ImagenProvider()
        provider._api_key = _FAKE_IMAGEN_KEY  # noqa: SLF001
        with pytest.raises(Exception) as excinfo:  # noqa: PT011
            await provider.generate("a cat")

    exc = excinfo.value
    assert exc.__cause__ is None
    assert exc.__context__ is None, (
        "__context__ must be cleared — build the sanitized error inside the "
        "except block and raise it AFTER the block exits"
    )
    assert _FAKE_IMAGEN_KEY not in str(exc)
    assert _FAKE_IMAGEN_KEY not in repr(exc)


async def test_imagen_network_error_is_retried() -> None:
    """AC-5 was only half-met: a transport failure (timeout / connection reset)
    carries no status code, so it fell into the "cannot classify, do not retry"
    branch — leaving the MOST common transient failure of an outbound call
    permanently fatal, which is exactly what `@with_retry` exists to handle."""
    request = httpx.Request("POST", f"https://imagen.example/v1:predict?key={_FAKE_IMAGEN_KEY}")
    client = _httpx_client(MagicMock())
    client.post = AsyncMock(side_effect=httpx.ConnectTimeout("timed out", request=request))
    mod = "app.providers.image.imagen"

    with (
        patch(f"{mod}.httpx.AsyncClient", return_value=client),
        patch(f"{mod}.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()) as record_failure,
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        from app.providers.image.imagen import ImagenProvider

        provider = ImagenProvider()
        provider._api_key = _FAKE_IMAGEN_KEY  # noqa: SLF001
        with pytest.raises(Exception) as excinfo:  # noqa: PT011
            await provider.generate("a cat")

    assert client.post.await_count == 2, "a transport failure must be retried (max_attempts=2)"
    assert record_failure.await_count == 1
    assert _FAKE_IMAGEN_KEY not in str(excinfo.value)


async def test_cost_ceiling_abort_does_not_count_against_the_provider() -> None:
    """Hitting OUR $3.00 budget is not evidence the provider is unhealthy.

    Counting it meant five ceiling breaches across concurrent lessons would open
    the SHARED "openai" circuit for ten minutes for every lesson — a
    self-inflicted outage caused by the cost control working correctly.
    """
    from app.core.circuit_breaker import guard_breaker
    from app.core.cost_tracker import CostCeilingError

    async def _over_budget() -> None:
        raise CostCeilingError("Lesson x exceeded cost ceiling at $3.0100 — pipeline aborted")

    with (
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()) as record_failure,
        pytest.raises(CostCeilingError),
    ):
        await guard_breaker("openai", _over_budget)

    assert record_failure.await_count == 0
    # content_pipeline_job branches on this substring — it must keep working.
    assert "cost ceiling" in str(CostCeilingError("exceeded cost ceiling at $3.01"))


async def test_client_side_errors_do_not_count_against_the_provider() -> None:
    """A 400/422 says the REQUEST was bad, not that the provider is down.
    Counting them let five reliably-rejected uploads open the shared breaker for
    every tenant — an attacker-triggerable outage."""
    import openai

    from app.core.circuit_breaker import guard_breaker

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")

    for code in (400, 422):

        async def _client_error(code: int = code) -> None:
            raise openai.APIStatusError(
                f"bad request {code}",
                response=httpx.Response(code, request=request),
                body=None,
            )

        with (
            patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
            patch("app.core.circuit_breaker.record_failure", new=AsyncMock()) as record_failure,
            pytest.raises(openai.APIStatusError),
        ):
            await guard_breaker("openai", _client_error)

        assert record_failure.await_count == 0, f"{code} must not count as provider ill-health"


async def test_provider_errors_still_count() -> None:
    """The exclusions above must not gut the breaker: a real 500 still counts."""
    import openai

    from app.core.circuit_breaker import guard_breaker

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")

    async def _server_error() -> None:
        raise openai.InternalServerError(
            "boom", response=httpx.Response(500, request=request), body=None
        )

    with (
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()) as record_failure,
        pytest.raises(openai.InternalServerError),
    ):
        await guard_breaker("openai", _server_error)

    assert record_failure.await_count == 1


async def test_breaker_bookkeeping_failure_never_displaces_the_result() -> None:
    """Redis is best-effort. On success it must not throw away an already-billed
    completion; on failure it must not REPLACE the provider exception that
    `with_retry` needs in order to classify."""
    from app.core.circuit_breaker import guard_breaker

    async def _ok() -> str:
        return "value"

    async def _boom() -> str:
        raise ValueError("provider exploded")

    redis_down = AsyncMock(side_effect=RuntimeError("Redis pool is not initialised"))

    with patch("app.core.circuit_breaker.record_success", new=redis_down):
        assert await guard_breaker("openai", _ok) == "value"

    with (
        patch("app.core.circuit_breaker.record_failure", new=redis_down),
        pytest.raises(ValueError, match="provider exploded"),
    ):
        await guard_breaker("openai", _boom)


async def test_openai_clients_disable_sdk_retries_and_set_explicit_timeouts() -> None:
    """The trap this story originally walked straight into.

    The SDK defaults to `max_retries=2`, so `with_retry(max_attempts=3)` layered
    on top is 3 x 3 = NINE HTTP requests per logical call, with two independent
    backoff schedules and a 600s default read timeout — tens of minutes against
    `arq_job_timeout_s`. `core/retry.py` is the only layer that knows the PRD
    §14 rules and the breaker state, so it owns retry exclusively.

    The timeout must be an explicit `httpx.Timeout(..., connect=5.0)`: passing a
    bare float sets `connect` to the same value, replacing the SDK's 5s connect
    guard and making a connect hang strictly WORSE than the default.
    """
    import httpx as _httpx

    from app.config import get_settings

    settings = get_settings()
    captured: list[dict[str, object]] = []

    def _capture(**kwargs: object) -> MagicMock:
        captured.append(kwargs)
        return MagicMock()

    from app.providers.embeddings.openai import OpenAIEmbeddingsProvider
    from app.providers.image.openai_image import OpenAIImageProvider
    from app.providers.llm.openai import OpenAILLMProvider

    cases = (
        ("app.providers.llm.openai", OpenAILLMProvider, settings.openai_request_timeout_s),
        (
            "app.providers.embeddings.openai",
            OpenAIEmbeddingsProvider,
            settings.openai_request_timeout_s,
        ),
        (
            "app.providers.image.openai_image",
            OpenAIImageProvider,
            settings.openai_image_request_timeout_s,
        ),
    )

    for mod, cls, expected_timeout in cases:
        captured.clear()
        with (
            patch(f"{mod}.AsyncOpenAI", side_effect=_capture),
            patch(f"{mod}.get_langfuse", MagicMock(return_value=None), create=True),
        ):
            cls()

        assert captured, f"{mod}: AsyncOpenAI was not constructed"
        kwargs = captured[0]
        assert kwargs.get("max_retries") == 0, (
            f"{mod}: SDK retries must be OFF — otherwise with_retry multiplies them"
        )
        timeout = kwargs.get("timeout")
        assert isinstance(timeout, _httpx.Timeout), (
            f"{mod}: timeout must be an explicit httpx.Timeout, never a bare float — "
            "a bare float also overwrites connect=, destroying the 5s connect guard"
        )
        assert timeout.connect == 5.0, f"{mod}: connect guard must stay at 5s"
        assert timeout.read == expected_timeout, f"{mod}: read timeout mismatch"
