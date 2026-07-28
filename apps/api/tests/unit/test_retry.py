"""
Unit tests for app.core.retry.with_retry — the PRD §14 exponential-backoff
retry decorator.

2026-07-20 code-review finding (Test Coverage layer): the decorator had NO
dedicated test and only the 429 branch was ever exercised anywhere in the
suite. The 5xx retry set, the network-timeout branch, the unclassified-status
branch, exhaustion re-raise, and the backoff schedule were all uncovered — a
regression removing 503 from the retryable set (or sleeping after the final
attempt) would have passed every test. This file closes that gap.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.retry import with_retry

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


def _status_error(code: int) -> httpx.HTTPStatusError:
    """Build a real httpx.HTTPStatusError carrying an HTTP status code."""
    request = httpx.Request("GET", "https://provider.example/v1/thing")
    response = httpx.Response(code, request=request)
    return httpx.HTTPStatusError(f"HTTP {code}", request=request, response=response)


class _Counter:
    """A callable that fails with `exc` for its first `fail_times` calls, then
    returns `ok`. Records how many times it was actually invoked."""

    def __init__(self, exc: BaseException | None, fail_times: int, ok: str = "ok") -> None:
        self.exc = exc
        self.fail_times = fail_times
        self.ok = ok
        self.calls = 0
        # with_retry logs func.__qualname__/__name__ on retry/abort paths; a
        # bare callable instance needs these as INSTANCE attributes (a class-
        # level __qualname__ is consumed by Python's class machinery and is not
        # visible on instances).
        self.__name__ = "counter"
        self.__qualname__ = "counter"

    async def __call__(self, *args: object, **kwargs: object) -> str:
        self.calls += 1
        if self.exc is not None and self.calls <= self.fail_times:
            raise self.exc
        return self.ok


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Replace asyncio.sleep with a recorder so tests never actually wait and
    can assert on the backoff schedule."""
    slept: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("app.core.retry.asyncio.sleep", _fake_sleep)
    # Make jitter deterministic so backoff values are exactly (2**attempt) + 0.5.
    monkeypatch.setattr("app.core.retry.random.random", lambda: 0.5)
    return slept


# ── Retryable HTTP status codes: retried, then succeed ──────────────────────


@pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
async def test_retryable_status_is_retried_then_succeeds(code: int) -> None:
    fn = _Counter(_status_error(code), fail_times=1)
    wrapped = with_retry(max_attempts=3)(fn)
    result = await wrapped()
    assert result == "ok"
    assert fn.calls == 2  # failed once, retried, succeeded


# ── Non-retryable / unclassified statuses: raise immediately, no retry ──────


@pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
async def test_non_retryable_status_is_not_retried(code: int) -> None:
    fn = _Counter(_status_error(code), fail_times=10)
    wrapped = with_retry(max_attempts=3)(fn)
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await wrapped()
    assert exc_info.value.response.status_code == code
    assert fn.calls == 1  # aborted immediately, never retried


@pytest.mark.parametrize("code", [418, 405, 451])
async def test_unclassified_status_is_not_retried(code: int) -> None:
    """A status in neither the retryable nor non-retryable set must NOT be
    retried (conservative default) — catches a regression that let an
    unclassified code fall through to the retry path."""
    fn = _Counter(_status_error(code), fail_times=10)
    wrapped = with_retry(max_attempts=3)(fn)
    with pytest.raises(httpx.HTTPStatusError):
        await wrapped()
    assert fn.calls == 1


# ── Network/timeout exceptions: the most common real failure — must retry ───


@pytest.mark.parametrize(
    "exc",
    [
        httpx.TimeoutException("read timed out"),
        httpx.ConnectTimeout("connect timed out"),
        httpx.NetworkError("connection reset"),
        TimeoutError("asyncio timeout"),
    ],
)
async def test_network_and_timeout_errors_are_retried(exc: BaseException) -> None:
    fn = _Counter(exc, fail_times=1)
    wrapped = with_retry(max_attempts=3)(fn)
    result = await wrapped()
    assert result == "ok"
    assert fn.calls == 2


# ── Unknown exceptions: never retried ───────────────────────────────────────


async def test_unknown_exception_is_not_retried() -> None:
    fn = _Counter(ValueError("bad payload"), fail_times=10)
    wrapped = with_retry(max_attempts=3)(fn)
    with pytest.raises(ValueError):
        await wrapped()
    assert fn.calls == 1


async def test_bare_raise_preserves_redacted_cause() -> None:
    """The unknown-exception branch must use a bare `raise` so a provider's
    deliberate `raise ... from None` (secret redaction) is preserved — not
    clobbered into being its own __cause__."""

    async def redacting() -> str:
        raise RuntimeError("redacted") from None

    wrapped = with_retry(max_attempts=3)(redacting)
    with pytest.raises(RuntimeError) as exc_info:
        await wrapped()
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True


# ── Exhaustion: re-raise the last exception after all attempts ──────────────


async def test_exhaustion_reraises_last_exception() -> None:
    err = _status_error(503)
    fn = _Counter(err, fail_times=10)
    wrapped = with_retry(max_attempts=3)(fn)
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await wrapped()
    assert exc_info.value is err
    assert fn.calls == 3  # exactly max_attempts


async def test_optional_node_uses_two_attempts(_no_real_sleep: list[float]) -> None:
    """max_attempts=2 (optional nodes) must attempt exactly twice and sleep
    exactly once between them."""
    fn = _Counter(_status_error(500), fail_times=10)
    wrapped = with_retry(max_attempts=2)(fn)
    with pytest.raises(httpx.HTTPStatusError):
        await wrapped()
    assert fn.calls == 2
    assert len(_no_real_sleep) == 1  # one backoff between the two attempts


# ── Backoff schedule: sleep between attempts only, never after the last ─────


async def test_backoff_schedule_and_no_sleep_after_final_attempt(
    _no_real_sleep: list[float],
) -> None:
    fn = _Counter(_status_error(500), fail_times=10)
    wrapped = with_retry(max_attempts=3)(fn)
    with pytest.raises(httpx.HTTPStatusError):
        await wrapped()
    # 3 attempts → 2 backoffs (after attempt 0 and 1), none after the last.
    # With deterministic jitter 0.5: (2**0)+0.5=1.5, (2**1)+0.5=2.5
    assert _no_real_sleep == [1.5, 2.5]


async def test_success_first_try_never_sleeps(_no_real_sleep: list[float]) -> None:
    fn = _Counter(None, fail_times=0)
    wrapped = with_retry(max_attempts=3)(fn)
    assert await wrapped() == "ok"
    assert fn.calls == 1
    assert _no_real_sleep == []


# ── Story 2-32 AC-1/AC-2: OpenAI SDK exception classification ────────────────
#
# The OpenAI SDK does NOT raise httpx exceptions. Verified against the installed
# SDK: openai.APIError -> OpenAIError -> Exception, with ZERO httpx.HTTPError in
# any MRO. So before this story every OpenAI failure — including a plain 429
# rate-limit, the most common transient failure in this system — fell into
# with_retry's unknown-exception branch and was never retried, contradicting
# PRD §14 ("Retry on: 429, 500, 502, 503, 504").


def _openai_status_error(code: int, cls: type | None = None) -> Exception:
    """Build a real openai.APIStatusError (or subclass) carrying a status code."""
    import openai

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(code, request=request)
    return (cls or openai.APIStatusError)(f"OpenAI {code}", response=response, body=None)


async def test_openai_exceptions_are_not_httpx_derived() -> None:
    """Pins the premise of this whole AC. If a future SDK release makes these
    httpx-derived, the classification below becomes redundant rather than
    wrong — but we want to KNOW, not silently keep dead code."""
    import openai

    for name in ("APIError", "APIStatusError", "APIConnectionError", "RateLimitError"):
        cls = getattr(openai, name)
        assert not issubclass(cls, httpx.HTTPError), (
            f"openai.{name} is now httpx-derived — revisit with_retry's classification"
        )


@pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
async def test_openai_retryable_status_is_retried_then_succeeds(code: int) -> None:
    """PRD §14 retryable set, raised as the SDK really raises it."""
    counter = _Counter(_openai_status_error(code), fail_times=1)
    wrapped = with_retry(max_attempts=3)(counter)

    assert await wrapped() == "ok"
    assert counter.calls == 2, f"OpenAI {code} must be retried"


async def test_openai_rate_limit_error_subclass_is_retried() -> None:
    """RateLimitError is the concrete class the SDK raises for 429 — assert on
    the subclass, not just the base, so a classification keyed on exact type
    cannot pass this by accident."""
    import openai

    counter = _Counter(_openai_status_error(429, openai.RateLimitError), fail_times=2)
    wrapped = with_retry(max_attempts=3)(counter)

    assert await wrapped() == "ok"
    assert counter.calls == 3


async def test_openai_internal_server_error_subclass_is_retried() -> None:
    import openai

    counter = _Counter(_openai_status_error(500, openai.InternalServerError), fail_times=1)
    wrapped = with_retry(max_attempts=3)(counter)

    assert await wrapped() == "ok"
    assert counter.calls == 2


async def test_openai_network_class_errors_are_retried() -> None:
    """APITimeoutError subclasses APIConnectionError; both are network-class and
    carry no status code, so they must be classified by type, not by status."""
    import openai

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    for exc in (
        openai.APITimeoutError(request=request),
        openai.APIConnectionError(request=request),
    ):
        counter = _Counter(exc, fail_times=1)
        wrapped = with_retry(max_attempts=3)(counter)

        assert await wrapped() == "ok"
        assert counter.calls == 2, f"{type(exc).__name__} must be retried"


@pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
async def test_openai_non_retryable_status_is_not_retried(code: int) -> None:
    """AC-2: PRD §14 'Never retry: 400, 401'. The non-retryable set must still
    win after the classification widens."""
    import openai

    counter = _Counter(_openai_status_error(code), fail_times=99)
    wrapped = with_retry(max_attempts=3)(counter)

    with pytest.raises(openai.APIStatusError):
        await wrapped()
    assert counter.calls == 1, f"OpenAI {code} must NOT be retried"


@pytest.mark.parametrize("code", [418, 451])
async def test_openai_unclassified_status_is_not_retried(code: int) -> None:
    """An unknown status is not assumed safe to replay."""
    import openai

    counter = _Counter(_openai_status_error(code), fail_times=99)
    wrapped = with_retry(max_attempts=3)(counter)

    with pytest.raises(openai.APIStatusError):
        await wrapped()
    assert counter.calls == 1


async def test_openai_apierror_without_status_is_not_retried() -> None:
    """A bare APIError carries no status_code. Without one there is nothing to
    classify, so it must fall through to the conservative no-retry branch
    rather than being retried on the strength of its module alone."""
    import openai

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    counter = _Counter(openai.APIError("boom", request=request, body=None), fail_times=99)
    wrapped = with_retry(max_attempts=3)(counter)

    with pytest.raises(openai.APIError):
        await wrapped()
    assert counter.calls == 1


async def test_retry_module_imports_and_still_classifies_httpx_without_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-1: the openai import must be GUARDED. core/retry.py is core
    infrastructure; it must not hard-depend on a provider SDK. Simulate the SDK
    being absent, reimport, and prove httpx classification still works."""
    import builtins
    import importlib
    import sys

    real_import = builtins.__import__

    def _no_openai(name: str, *args: object, **kwargs: object) -> object:
        if name == "openai" or name.startswith("openai."):
            raise ModuleNotFoundError("No module named 'openai'")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "openai", raising=False)
    monkeypatch.setattr(builtins, "__import__", _no_openai)

    import app.core.retry as retry_mod

    reloaded = importlib.reload(retry_mod)
    try:
        counter = _Counter(_status_error(503), fail_times=1)
        wrapped = reloaded.with_retry(max_attempts=3)(counter)

        assert await wrapped() == "ok"
        assert counter.calls == 2, "httpx classification must survive a missing openai SDK"
    finally:
        # Restore the real module for every subsequent test in the session.
        monkeypatch.undo()
        importlib.reload(retry_mod)


async def test_guarded_import_ignores_a_non_class_openai_stub() -> None:
    """Regression: an ImportError guard alone is NOT enough.

    Parts of the suite install `sys.modules["openai"] = MagicMock()`. If the
    guarded import binds those Mock attributes into the `except (...)` tuple,
    every provider call raises `TypeError: catching classes that do not inherit
    from BaseException` — converting a transient 429 into a hard TypeError at
    the worst possible moment. `_exception_classes` filters non-classes so a
    stubbed SDK degrades to httpx-only classification instead.
    """
    from unittest.mock import MagicMock

    from app.core.retry import _exception_classes

    stub = MagicMock()
    assert _exception_classes(stub.APIError) == ()
    assert _exception_classes(stub.APIError, ValueError) == (ValueError,)
    assert _exception_classes(object) == (), "a plain class is not an exception class"

    # Every element of the real tuples must be usable in an `except` clause.
    from app.core.retry import _OPENAI_API_ERRORS, _OPENAI_NETWORK_ERRORS

    for tup in (_OPENAI_API_ERRORS, _OPENAI_NETWORK_ERRORS):
        for cls in tup:
            assert isinstance(cls, type) and issubclass(cls, BaseException)
        try:
            raise ValueError("probe")
        except tup:  # must not raise TypeError
            pytest.fail("ValueError should not match the OpenAI tuples")
        except ValueError:
            pass
