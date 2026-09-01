"""
ARQ job-enqueue pool singleton, for code outside the FastAPI request cycle
(Story 2-52).

`app.dependencies.get_arq_redis` already injects the pool into route handlers
via `request.app.state.arq_redis` — that only works where a `Request` object
exists. `session_end_node`'s `_finalize_session` (app/modules/tutor/
state_machine/graph.py) runs from a WebSocket-triggered LangGraph node, not a
route handler, so it has no `Request` to inject from. This module mirrors
app.core.redis's init/get singleton pattern so both call sites — the FastAPI
route DI and this direct getter — share the exact same pool object rather
than each creating their own.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from arq.connections import ArqRedis

logger = logging.getLogger(__name__)

_pool: ArqRedis | None = None


def init_arq_pool(pool: ArqRedis) -> None:
    """Register the shared ARQ pool. Must be called once during app startup,
    right after `arq.create_pool(...)` (see app.main's lifespan)."""
    global _pool  # noqa: PLW0603

    if _pool is not None:
        logger.warning("init_arq_pool() called more than once — ignoring duplicate call")
        return

    _pool = pool


def get_arq_pool() -> ArqRedis:
    """Return the shared ARQ pool for job enqueue outside a FastAPI route.

    Raises:
        RuntimeError: if init_arq_pool() has not been called yet.
    """
    if _pool is None:
        raise RuntimeError(
            "ARQ pool is not initialised. Ensure init_arq_pool() is called in the "
            "application lifespan, after arq.create_pool()."
        )
    return _pool
