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

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Coroutine[Any, Any, Any]])

# HTTP status codes that are safe to retry
_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

# HTTP status codes that must NEVER be retried
_NON_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({400, 401, 403, 404, 422})


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
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
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

                except (httpx.TimeoutException, httpx.NetworkError, TimeoutError) as exc:
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
                    wait = (2**attempt) + random.random()
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
