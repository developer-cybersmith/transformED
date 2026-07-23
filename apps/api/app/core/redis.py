"""
Redis connection pool singleton.

All modules obtain a Redis client via get_redis() — never create their own
ConnectionPool.  This guarantees a single shared pool across the process.
"""

from __future__ import annotations

import logging

from redis.asyncio import ConnectionPool, Redis

logger = logging.getLogger(__name__)

_pool: ConnectionPool | None = None


async def init_redis(url: str) -> None:
    """Create the global ConnectionPool from a Redis URL.

    Must be called once during application startup (inside the lifespan context).

    Args:
        url: Redis connection URL, e.g. ``redis://localhost:6379/0`` or
             ``rediss://user:pass@host:6380/0`` for TLS.
    """
    global _pool  # noqa: PLW0603

    if _pool is not None:
        logger.warning("init_redis() called more than once — ignoring duplicate call")
        return

    _pool = ConnectionPool.from_url(
        url,
        max_connections=20,
        decode_responses=True,
    )
    logger.info("Redis connection pool created (url=%s)", _mask_url(url))


async def close_redis() -> None:
    """Drain and close the global ConnectionPool.

    Must be called during application shutdown (inside the lifespan context).
    """
    global _pool  # noqa: PLW0603

    if _pool is None:
        return

    await _pool.aclose()
    _pool = None
    logger.info("Redis connection pool closed")


def get_redis() -> Redis:
    """Return a Redis client bound to the shared ConnectionPool.

    Raises:
        RuntimeError: if ``init_redis`` has not been called yet.

    Usage in FastAPI routes::

        from app.core.redis import get_redis
        from typing import Annotated
        from fastapi import Depends

        async def my_route(redis: Annotated[Redis, Depends(get_redis)]):
            await redis.set("key", "value")
    """
    if _pool is None:
        raise RuntimeError(
            "Redis pool is not initialised. "
            "Ensure init_redis() is awaited in the application lifespan."
        )

    return Redis(connection_pool=_pool)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _mask_url(url: str) -> str:
    """Redact password from Redis URL for safe logging."""
    try:
        from urllib.parse import urlparse, urlunparse

        parsed = urlparse(url)
        if parsed.password:
            netloc = f"{parsed.username}:****@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            parsed = parsed._replace(netloc=netloc)
        return urlunparse(parsed)
    except Exception:  # noqa: BLE001
        return "<redis-url>"
