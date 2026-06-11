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
                logger.info("Circuit for '%s' promoted to HALF_OPEN after %ds", provider, int(elapsed))
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

    logger.warning("Circuit breaker: failure %d/%d for provider '%s'", failures, FAILURE_THRESHOLD, provider)

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
                extras={  # type: ignore[call-arg]
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
