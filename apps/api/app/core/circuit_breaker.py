"""
Redis-backed circuit breaker for AI provider calls (PRD §14).

States
------
CLOSED      Normal operation.  Failures are counted.
OPEN        Provider is assumed down.  All calls fail-fast.
HALF_OPEN   Recovery probe window.  One call is allowed through.

Thresholds
----------
FAILURE_THRESHOLD   5 failures within the rolling 120 s window → circuit opens
RECOVERY_TIMEOUT   600 s (10 min) after opening → circuit moves to HALF_OPEN

Redis key schema
----------------
circuit:{provider}:state       str  "CLOSED" | "OPEN" | "HALF_OPEN"
circuit:{provider}:failures    int  sliding counter (TTL = 120 s)
circuit:{provider}:opened_at   float  Unix timestamp when circuit opened
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from enum import StrEnum

import sentry_sdk

from app.core.redis import get_redis

logger = logging.getLogger(__name__)

FAILURE_THRESHOLD: int = 5
FAILURE_WINDOW_SECONDS: int = 120
RECOVERY_TIMEOUT_SECONDS: int = 600  # 10 minutes


class CircuitState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(RuntimeError):
    """Raised when a call is rejected because the provider's circuit is OPEN.

    Story 2-32. This is a *rejection*, not a provider failure, and the two must
    be distinguishable:

    - `guard_breaker` must NOT count it via `record_failure`. Counting a
      rejection would let the breaker feed itself — every rejected call would
      extend the very failure window keeping it open, so it could never close.
    - `with_retry` must not retry it. Retrying against a breaker already known
      to be open is pure latency and spend.

    Deliberately a `RuntimeError` subclass so that broad `except RuntimeError`
    handlers elsewhere keep working. Note that `SanitizedHTTPError` and Sarvam's
    quota error are also `RuntimeError`s, so a handler that only catches
    `RuntimeError` cannot tell "breaker rejected the call" from "provider
    returned a redacted HTTP error" from "quota exhausted" — three cases with
    completely different remediation. Catch this class specifically when the
    distinction matters.
    """


def _keys(provider: str) -> tuple[str, str, str]:
    """Return the three Redis keys for a given provider."""
    base = f"circuit:{provider}"
    return f"{base}:state", f"{base}:failures", f"{base}:opened_at"


async def is_circuit_open(provider: str) -> bool:
    """Return True if the circuit is OPEN (and should fail-fast).

    Also handles the HALF_OPEN → probe transition: if the recovery
    timeout has elapsed the state is promoted to HALF_OPEN and this
    function returns False (allowing one probe attempt through).
    """
    redis = get_redis()
    state_key, _, opened_at_key = _keys(provider)

    state_raw = await redis.get(state_key)
    state = CircuitState(state_raw) if state_raw else CircuitState.CLOSED

    if state == CircuitState.CLOSED:
        return False

    if state == CircuitState.OPEN:
        opened_at_raw = await redis.get(opened_at_key)
        if opened_at_raw is not None:
            elapsed = time.time() - float(opened_at_raw)
            if elapsed >= RECOVERY_TIMEOUT_SECONDS:
                # Promote to HALF_OPEN — allow one probe
                await redis.set(state_key, CircuitState.HALF_OPEN)
                logger.info(
                    "Circuit for '%s' promoted to HALF_OPEN after %ds", provider, int(elapsed)
                )
                return False
        return True  # Still within recovery timeout

    # HALF_OPEN — allow the probe through
    return False


async def record_failure(provider: str) -> None:
    """Increment the failure counter; open the circuit when threshold is hit."""
    redis = get_redis()
    state_key, failures_key, opened_at_key = _keys(provider)

    # Increment with sliding TTL
    failures = await redis.incr(failures_key)
    if failures == 1:
        # First failure in window — set TTL
        await redis.expire(failures_key, FAILURE_WINDOW_SECONDS)

    logger.warning(
        "Circuit breaker: failure %d/%d for provider '%s'", failures, FAILURE_THRESHOLD, provider
    )

    if failures >= FAILURE_THRESHOLD:
        state_raw = await redis.get(state_key)
        current_state = CircuitState(state_raw) if state_raw else CircuitState.CLOSED

        if current_state != CircuitState.OPEN:
            now = time.time()
            await redis.set(state_key, CircuitState.OPEN)
            await redis.set(opened_at_key, str(now))

            logger.error(
                "Circuit OPENED for provider '%s' after %d failures in %ds window",
                provider,
                FAILURE_THRESHOLD,
                FAILURE_WINDOW_SECONDS,
            )

            # Alert Sentry when the circuit trips
            sentry_sdk.capture_message(
                f"Circuit breaker OPENED for AI provider '{provider}'",
                level="error",
                extras={
                    "provider": provider,
                    "failures": failures,
                    "threshold": FAILURE_THRESHOLD,
                    "opened_at": now,
                },
            )


async def record_success(provider: str) -> None:
    """Reset failure counter and close the circuit on a successful call."""
    redis = get_redis()
    state_key, failures_key, opened_at_key = _keys(provider)

    state_raw = await redis.get(state_key)
    state = CircuitState(state_raw) if state_raw else CircuitState.CLOSED

    if state in (CircuitState.HALF_OPEN, CircuitState.OPEN):
        logger.info("Circuit CLOSED for provider '%s' after successful probe", provider)

    # Reset everything
    await redis.delete(state_key, failures_key, opened_at_key)


async def guard_breaker[T](
    provider: str,
    call: Callable[[], Awaitable[T]],
) -> T:
    """Run *call* under circuit-breaker accounting — exactly ONE outcome per
    logical call, however many times *call* retries internally (Story 2-32 AC-3).

    `record_failure` used to live inside the function wrapped by `@with_retry`.
    That was invisible while OpenAI SDK exceptions were never classified as
    retryable (Story 2-32 AC-1): a 429 produced one attempt and therefore one
    recorded failure. The moment AC-1 makes those retryable, the same logical
    call records `max_attempts` failures:

        FAILURE_THRESHOLD = 5 over a 120 s window
        1 failure/call  -> breaker opens after 5 logical calls
        3 failures/call -> breaker opens after 2 logical calls

    i.e. fixing the retry classification alone would trip the breaker ~2.5x
    faster and turn a brief rate-limit into a 10-minute half-open outage. The
    threshold is not what was wrong; the accounting was. Hence this wrapper sits
    OUTSIDE the retry decorator, and the retried function keeps only the
    per-attempt `is_circuit_open` check.

    `CircuitOpenError` is re-raised WITHOUT being counted — see its docstring.

    Neither is a **client-side** error. The breaker exists to detect that a
    PROVIDER is unhealthy; a 400 content-policy rejection or a 422 validation
    error says the request was bad, not the provider. Counting those let five
    reliably-rejected uploads inside the 120s window open the shared breaker for
    every tenant — an attacker-triggerable outage. `_NON_RETRYABLE_STATUS_CODES`
    already encodes exactly this distinction; `_is_client_error` reuses it.

    Bookkeeping is best-effort. A Redis outage must never convert an already-paid-for
    provider result into an exception, nor mask the provider error that
    `with_retry` needs in order to classify the failure.
    """
    from app.core.cost_tracker import CostCeilingError

    try:
        result = await call()
    except CircuitOpenError:
        raise
    except CostCeilingError:
        # OUR budget, not the provider's health. Counting it would let the cost
        # control open the shared circuit for every lesson.
        raise
    except Exception as exc:
        if not _is_client_error(exc):
            await _safe_record(record_failure, provider, "failure")
        raise
    await _safe_record(record_success, provider, "success")
    return result


def _is_client_error(exc: BaseException) -> bool:
    """True when *exc* blames the request, not the provider.

    Kept deliberately narrow: only an explicit non-retryable HTTP status counts.
    An unknown exception is still treated as a provider failure, because failing
    to open a breaker on a real outage is worse than opening one spuriously.
    """
    from app.core.retry import _NON_RETRYABLE_STATUS_CODES

    status = getattr(exc, "status_code", None)
    if status is None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    return status in _NON_RETRYABLE_STATUS_CODES


async def _safe_record(
    fn: Callable[[str], Awaitable[None]],
    provider: str,
    label: str,
) -> None:
    """Record a breaker outcome without ever displacing the real result.

    `record_success` runs on the happy path, after the provider call has already
    been made and billed; letting a Redis error escape here would throw away a
    paid-for completion and make ARQ re-run (and re-pay for) the node. On the
    failure path an escaping Redis error would REPLACE the provider exception,
    so callers would see a Redis error instead of the 429 they must classify.
    """
    try:
        await fn(provider)
    except Exception:  # noqa: BLE001 — bookkeeping must never displace the result
        logger.warning(
            "Circuit breaker: failed to record %s for provider '%s' — breaker state may be stale",
            label,
            provider,
            exc_info=True,
        )
