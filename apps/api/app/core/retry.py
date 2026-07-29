"""
Retry decorator with exponential backoff for AI provider calls.

Design rules (PRD §14):
- Critical nodes:  max_attempts=3
- Optional nodes:  max_attempts=2
- Retryable:       HTTP 429, 500, 502, 503, 504, network timeouts
- Non-retryable:   HTTP 400, 401 (never retry client errors or auth failures)
- Backoff formula: wait = (2 ** attempt) + random.random()  (full jitter)
"""

from __future__ import annotations

import asyncio
import functools
import logging
import random
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

import httpx

from app.core.circuit_breaker import CircuitOpenError

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Coroutine[Any, Any, Any]])

# HTTP status codes that are safe to retry
_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

# HTTP status codes that must NEVER be retried
_NON_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({400, 401, 403, 404, 422})


# ── OpenAI SDK exception classification (Story 2-32) ──────────────────────────
#
# The OpenAI SDK does NOT raise httpx exceptions. Verified against the installed
# SDK: `openai.APIError -> OpenAIError -> Exception`, with ZERO `httpx.HTTPError`
# anywhere in the MRO. Before this story every OpenAI failure — including a plain
# 429 rate-limit, the most common transient failure in this system — fell through
# to the unknown-exception branch below and was never retried, directly
# contradicting PRD §14 ("Retry on: 429, 500, 502, 503, 504").
#
# The import is GUARDED on purpose. `core/` is infrastructure and must not
# hard-depend on a provider SDK; if `openai` is absent these tuples are empty,
# `except ()` never matches, and httpx classification is unaffected.
class SanitizedHTTPError(RuntimeError):
    """An HTTP failure whose original exception could not be allowed to escape.

    Some providers must redact before re-raising: Imagen puts the API key in the
    request URL, and httpx embeds the full URL in its exception message and
    repr, so any `exc_info=True` upstream would log the credential. Those
    providers therefore catch `httpx.HTTPError` and re-raise `... from None`.

    Before Story 2-32 they re-raised a bare `RuntimeError`, which `with_retry`
    could not classify — so a retryable 429/503 became permanently fatal and
    `@with_retry` on those providers was decorative. Carrying `status_code`
    lets the decorator apply the exact PRD §14 rules to a redacted error, so
    redaction and retryability are no longer mutually exclusive.

    A `RuntimeError` subclass so existing `except RuntimeError` handlers behave
    unchanged. NEVER put the original message, URL, or `__cause__` on it.

    **`raise ... from None` is NOT sufficient, and raisers must not rely on it.**
    `from None` sets `__cause__ = None` and `__suppress_context__ = True`, but the
    `raise` statement still binds `__context__` to the exception being handled —
    and for a real `response.raise_for_status()` that object's `str()`/`repr()`
    embed the full request URL, key included. Assigning `__context__ = None`
    before the raise does not help either; the raise re-binds it. The only
    reliable pattern is to BUILD the sanitized error inside the `except` block
    and RAISE IT AFTER the block has exited, when no exception is active. See
    `providers/image/imagen.py` for the reference implementation, and
    `test_sanitized_error_does_not_retain_the_original_via_context`.

    `network_error=True` marks a transport-level failure (timeout, connection
    reset) that carries no status code but is still retryable — without it, the
    most common transient failure mode of an outbound HTTP call would be
    classified as permanently fatal.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        network_error: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.network_error = network_error


def _exception_classes(*candidates: Any) -> tuple[type[BaseException], ...]:  # noqa: ANN401
    """Keep only real exception classes, dropping anything else.

    `except` requires genuine BaseException subclasses — handing it anything
    else raises `TypeError: catching classes that do not inherit from
    BaseException`, which would convert every provider error into a TypeError
    at the worst possible moment. A guard on ImportError alone is NOT enough:
    `openai` may be present in `sys.modules` as a test double (parts of the
    suite install a `MagicMock` via `sys.modules.setdefault`), whose attributes
    are Mocks rather than classes. Filtering here means a stubbed SDK silently
    degrades to httpx-only classification instead of breaking the decorator.
    """
    return tuple(c for c in candidates if isinstance(c, type) and issubclass(c, BaseException))


_OPENAI_API_ERRORS: tuple[type[BaseException], ...]
_OPENAI_NETWORK_ERRORS: tuple[type[BaseException], ...]
try:
    import openai as _openai

    # APIStatusError (has .status_code) and APIConnectionError/APITimeoutError
    # (network-class, no status) are both APIError subclasses — catch the base
    # and dispatch on what the instance actually carries.
    _OPENAI_API_ERRORS = _exception_classes(_openai.APIError)
    _OPENAI_NETWORK_ERRORS = _exception_classes(_openai.APIConnectionError)  # APITimeoutError too
except (ImportError, AttributeError):
    # AttributeError as well as ImportError: a circular import can hand back a
    # partially-initialised `openai` module whose `.APIError` does not exist yet.
    # Degrading is correct; failing to import `app.core.retry` entirely is not.
    _OPENAI_API_ERRORS = ()
    _OPENAI_NETWORK_ERRORS = ()

# ── Redis exception classification (Story 2-36, D19) ─────────────────────────
#
# `redis.exceptions` defines its OWN `TimeoutError` and `ConnectionError` which
# SHADOW the builtins by name and inherit from `RedisError`, NOT from them.
# Verified by execution in `test_redis_exceptions_are_not_the_builtins`:
#
#     redis.exceptions.TimeoutError is builtins.TimeoutError            -> False
#     issubclass(redis.exceptions.TimeoutError, builtins.TimeoutError)  -> False
#
# So `except (..., TimeoutError)` below reads as though it covers redis and
# never matched a single redis error. Every one fell through to the catch-all
# and was re-raised WITHOUT a retry.
#
# This is not theoretical: `is_circuit_open()` is the first statement of every
# function wrapped by this decorator (providers/llm/openai.py:111 and the same
# line in embeddings/ and both image providers), and it talks to Redis. A
# momentary Redis blip therefore killed the node before the provider was ever
# contacted — and killed it permanently.
#
# `ConnectionError` covers `BusyLoadingError` (a subclass), which Redis raises
# while loading a dataset from disk — the definition of "retry in a moment".
_REDIS_TRANSIENT_ERRORS: tuple[type[BaseException], ...]
try:
    import redis.exceptions as _redis_exc

    _REDIS_TRANSIENT_ERRORS = _exception_classes(
        _redis_exc.TimeoutError,
        _redis_exc.ConnectionError,
    )
except (ImportError, AttributeError):
    _REDIS_TRANSIENT_ERRORS = ()

# ── httpx protocol errors (Story 2-36, D20) ──────────────────────────────────
#
# `RemoteProtocolError` is neither `NetworkError` nor `TimeoutException` — it is
# a sibling under `TransportError` — so it fell through to the catch-all too. It
# means the SERVER violated the protocol or closed the connection mid-response:
# routine behaviour from a loaded provider, and exactly what retry is for.
#
# ⚠️ Named EXPLICITLY, and deliberately not by its parent. `httpx.ProtocolError`
# is also the parent of `LocalProtocolError`, which means THIS PROCESS built a
# malformed request — a code defect that cannot succeed on attempt two.
# Widening to `ProtocolError` (or worse, `TransportError`, which also covers
# `UnsupportedProtocol`) would turn one clear client-side error into three plus
# ~7s of backoff. `test_client_side_protocol_errors_are_not_retried` is the only
# test in the suite that fails if someone takes that shortcut.
_HTTPX_TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
)

# The single tuple the decorator catches on. Assembled here rather than unpacked
# inline at the `except`: mypy rejects a starred unpack there with
# "Exception type must be derived from BaseException", whereas a named tuple of
# the declared type checks cleanly — the same reason `_OPENAI_API_ERRORS` is a
# constant. `TimeoutError` is the BUILTIN (asyncio), listed last and separately
# because `redis.exceptions.TimeoutError` shadows its NAME without inheriting
# from it. Both entries are required; neither implies the other. That confusion
# IS D19.
_TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    *_HTTPX_TRANSIENT_ERRORS,
    *_REDIS_TRANSIENT_ERRORS,
    TimeoutError,
)

if not _REDIS_TRANSIENT_ERRORS:
    logger.warning(
        "Redis exception classification is DISABLED — redis.exceptions was not importable "
        "as real exception classes. A Redis blip will NOT be retried."
    )

if not _OPENAI_API_ERRORS:
    # Story 2-32 review: without this, a production image built without the SDK
    # importable (or with it stubbed) silently reverts to the pre-story behaviour
    # where every OpenAI 429 is fatal, and NOTHING anywhere says so.
    logger.warning(
        "OpenAI exception classification is DISABLED — the SDK was not importable "
        "as real exception classes. OpenAI 429/5xx responses will NOT be retried."
    )


def with_retry(max_attempts: int = 3) -> Callable[[F], F]:
    """Decorator factory: wrap an async function with exponential-backoff retry.

    Args:
        max_attempts: Total number of attempts (including the first).  Use 3 for
            critical pipeline nodes and 2 for optional/auxiliary nodes.

    Example::

        @with_retry(max_attempts=3)
        async def call_openai(prompt: str) -> str:
            ...

    Raises:
        The last exception raised after all attempts are exhausted.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            last_exc: BaseException | None = None

            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)

                except httpx.HTTPStatusError as exc:
                    status_code = exc.response.status_code

                    if status_code in _NON_RETRYABLE_STATUS_CODES:
                        logger.warning(
                            "Non-retryable HTTP %s from %s — aborting immediately",
                            status_code,
                            func.__qualname__,
                        )
                        raise

                    if status_code not in _RETRYABLE_STATUS_CODES:
                        logger.warning(
                            "Unclassified HTTP %s from %s — not retrying",
                            status_code,
                            func.__qualname__,
                        )
                        raise

                    last_exc = exc

                except _TRANSIENT_ERRORS as exc:
                    # Transport-level failures with no status to classify on:
                    # httpx timeouts/network/remote-protocol (Story 2-36 D20),
                    # redis timeouts/connection errors (D19), and the BUILTIN
                    # TimeoutError from asyncio.
                    #
                    # The builtin is listed separately and last precisely because
                    # `redis.exceptions.TimeoutError` shadows its NAME without
                    # inheriting from it — the confusion that caused D19. Both
                    # are needed; neither implies the other.
                    last_exc = exc

                except CircuitOpenError:
                    # Story 2-32 review: a breaker rejection is a DELIBERATE,
                    # expected fail-fast — not an unknown bug. Without this branch
                    # it fell to the catch-all below and was logged via
                    # logger.exception() at ERROR with a full traceback, which
                    # Sentry's default LoggingIntegration (event_level=ERROR)
                    # turns into an issue for EVERY rejected call. During a real
                    # outage that is hundreds of tracebacks over the 600s recovery
                    # window — exactly when the log needs to stay readable.
                    # Still not retried: hammering an open breaker is pure latency.
                    logger.warning(
                        "Circuit open — %s rejected without calling the provider",
                        func.__qualname__,
                    )
                    raise

                except SanitizedHTTPError as exc:
                    # Story 2-32 AC-5: a redacted HTTP failure, classified by the
                    # status the provider preserved. Same PRD §14 rules as the
                    # httpx branch — the message is redacted, the semantics are not.
                    if exc.network_error:
                        # Transport-level failure: no status to classify on, but
                        # retryable by nature — same treatment as the httpx
                        # TimeoutException/NetworkError branch above.
                        last_exc = exc
                    elif exc.status_code is None:
                        logger.warning(
                            "Sanitized error with no status from %s — not retrying",
                            func.__qualname__,
                        )
                        raise
                    elif exc.status_code in _NON_RETRYABLE_STATUS_CODES:
                        logger.warning(
                            "Non-retryable sanitized HTTP %s from %s — aborting immediately",
                            exc.status_code,
                            func.__qualname__,
                        )
                        raise
                    elif exc.status_code not in _RETRYABLE_STATUS_CODES:
                        logger.warning(
                            "Unclassified sanitized HTTP %s from %s — not retrying",
                            exc.status_code,
                            func.__qualname__,
                        )
                        raise
                    else:
                        last_exc = exc

                except _OPENAI_API_ERRORS as exc:
                    # Story 2-32. Mirrors the httpx branches above, but the SDK
                    # exposes the status on the exception rather than on a
                    # response object, and its network-class errors carry no
                    # status at all.
                    # Distinct name: `status_code` is already bound as `int` by the
                    # httpx branch above, and mypy narrows per-function, not per-branch.
                    sdk_status: int | None = getattr(exc, "status_code", None)

                    if sdk_status is None:
                        if isinstance(exc, _OPENAI_NETWORK_ERRORS):
                            # APIConnectionError / APITimeoutError — transient by
                            # nature, classified by type since there is no status.
                            last_exc = exc
                        else:
                            # A bare APIError with no status: nothing to classify
                            # on, so take the conservative branch rather than
                            # replaying a call on the strength of its module.
                            logger.warning(
                                "OpenAI %s with no status_code from %s — not retrying",
                                type(exc).__name__,
                                func.__qualname__,
                            )
                            raise
                    elif sdk_status in _NON_RETRYABLE_STATUS_CODES:
                        logger.warning(
                            "Non-retryable OpenAI %s from %s — aborting immediately",
                            sdk_status,
                            func.__qualname__,
                        )
                        raise
                    elif sdk_status not in _RETRYABLE_STATUS_CODES:
                        logger.warning(
                            "Unclassified OpenAI %s from %s — not retrying",
                            sdk_status,
                            func.__qualname__,
                        )
                        raise
                    else:
                        last_exc = exc

                except Exception:
                    # Unknown exception — do not retry. Bare `raise` preserves
                    # whatever __cause__/__suppress_context__ the original
                    # exception already carries (e.g. a provider's deliberate
                    # `raise ... from None` to redact a secret) — `raise exc
                    # from exc` previously clobbered it by making the
                    # exception its own __cause__, defeating that redaction
                    # (2026-07-15 review finding, image_generator_node).
                    logger.exception("Unexpected error in %s — not retrying", func.__qualname__)
                    raise

                # Compute backoff and log before sleeping
                if attempt < max_attempts - 1:
                    wait = (2**attempt) + random.random()  # noqa: S311
                    logger.warning(
                        "Retry %d/%d for %s after %.2fs (error: %s)",
                        attempt + 1,
                        max_attempts - 1,
                        func.__qualname__,
                        wait,
                        last_exc,
                    )
                    await asyncio.sleep(wait)

            # All attempts exhausted
            logger.error(
                "All %d attempts exhausted for %s",
                max_attempts,
                func.__qualname__,
            )
            assert last_exc is not None  # noqa: S101
            raise last_exc

        return wrapper  # type: ignore[return-value]

    return decorator
