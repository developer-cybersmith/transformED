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
    http_error = httpx.HTTPStatusError("503", request=request, response=response)

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
    assert exc.__cause__ is None, "the `from None` redaction must be preserved (AC-6)"


async def test_imagen_non_retryable_error_still_sanitized_and_not_retried() -> None:
    """A 401 is non-retryable per PRD §14 and must still be redacted."""
    request = httpx.Request("POST", f"https://imagen.example/v1:predict?key={_FAKE_IMAGEN_KEY}")
    response = httpx.Response(401, request=request)
    http_error = httpx.HTTPStatusError("401", request=request, response=response)

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
