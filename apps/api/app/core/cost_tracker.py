"""
Per-lesson AI cost tracker backed by Redis.

All ARQ workers and LangGraph nodes write here so the cost ceiling is
enforced across the full distributed pipeline.

Redis key: ``cost:{lesson_id}``  (float stored as string)
TTL: 24 hours — auto-expires after a lesson day to prevent stale data.
"""

from __future__ import annotations

import logging

from app.config import get_settings
from app.core.redis import get_redis

logger = logging.getLogger(__name__)

_COST_KEY_TTL_SECONDS: int = 86_400  # 24 h


def _key(lesson_id: str) -> str:
    return f"cost:{lesson_id}"


async def accumulate_cost(lesson_id: str, cost_usd: float) -> float:
    """Add *cost_usd* to the running total for *lesson_id*.

    Uses ``INCRBYFLOAT`` for atomic increment — safe under concurrent workers.

    Args:
        lesson_id: UUID string identifying the lesson pipeline run.
        cost_usd:  Cost delta to add (must be positive).

    Returns:
        The new cumulative cost after adding *cost_usd*.
    """
    if cost_usd < 0:
        raise ValueError(f"cost_usd must be non-negative, got {cost_usd}")

    redis = get_redis()
    key = _key(lesson_id)

    new_total: float = await redis.incrbyfloat(key, cost_usd)

    # Refresh TTL on every write so long-running lessons don't expire mid-flight
    await redis.expire(key, _COST_KEY_TTL_SECONDS)

    logger.debug("Lesson %s — accumulated cost +$%.6f → total $%.6f", lesson_id, cost_usd, new_total)
    return new_total


async def check_ceiling(lesson_id: str) -> bool:
    """Return True if the lesson has hit or exceeded the cost ceiling.

    Callers should mark ``lesson_jobs.status='failed'`` with an
    ``error`` prefixed ``cost_ceiling_exceeded:`` when this returns True —
    ``cost_limit_exceeded`` is NOT a legal status (schema CHECK allows only
    pending/running/completed/failed). Downshift-and-complete is S2-13.
    """
    settings = get_settings()
    current = await get_cost(lesson_id)
    over = current >= settings.max_lesson_cost_usd

    if over:
        logger.warning(
            "Lesson %s hit cost ceiling: $%.4f >= $%.2f",
            lesson_id,
            current,
            settings.max_lesson_cost_usd,
        )

    return over


async def get_cost(lesson_id: str) -> float:
    """Return the current accumulated cost for *lesson_id* (0.0 if unknown)."""
    redis = get_redis()
    raw: str | None = await redis.get(_key(lesson_id))
    return float(raw) if raw is not None else 0.0


async def clear_lesson_cost(lesson_id: str) -> None:
    """Delete the cost key for *lesson_id*.

    Call this when a lesson pipeline run is fully complete and the cost
    has been persisted to the DB, or when aborting a run entirely.
    """
    redis = get_redis()
    await redis.delete(_key(lesson_id))
    logger.debug("Cost key cleared for lesson %s", lesson_id)
