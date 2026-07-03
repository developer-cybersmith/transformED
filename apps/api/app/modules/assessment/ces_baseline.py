"""Per-learner CES baseline computation.

Reads the last N completed sessions' CES finals from Supabase, computes a
rolling average, and caches the result in Redis under
user:{user_id}:ces_baseline.

Dev 4 calls compute_and_store_ces_baseline() at session end, after writing
ces_final to the sessions table, to refresh the cached baseline for the next
session and to supply the current baseline for Learner DNA delta direction.

Redis key pattern: user:{user_id}:ces_baseline  (consistent with
user:{user_id}:dna and user:{user_id}:onboarding_done from the initial schema).
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from app.config import Settings

logger = logging.getLogger(__name__)

__all__ = ["compute_and_store_ces_baseline"]

_KEY_PREFIX = "user"
_KEY_SUFFIX = "ces_baseline"


def _redis_key(user_id: str) -> str:
    """Return the Redis key for a user's CES baseline."""
    return f"{_KEY_PREFIX}:{user_id}:{_KEY_SUFFIX}"


def _compute_baseline(scores: list[float]) -> float | None:
    """Return the simple average of scores rounded to 4 d.p., or None if empty."""
    if not scores:
        return None
    return round(sum(scores) / len(scores), 4)


async def compute_and_store_ces_baseline(
    *,
    user_id: str,
    supabase: Any,
    redis: "Redis",
    settings: "Settings",
) -> float | None:
    """Compute and cache the rolling CES baseline for a user.

    Reads the most recent completed sessions (those with non-NULL ces_final
    and non-NULL ended_at) ordered by ended_at DESC from the sessions table.
    Computes the simple average of the most recent
    settings.ces_baseline_window scores, rounds to 4 d.p., and writes the
    result to Redis under user:{user_id}:ces_baseline with a TTL of
    settings.ces_baseline_ttl_seconds seconds.

    Args:
        user_id:  UUID string of the learner.
        supabase: Synchronous supabase-py v2 client (wrapped in asyncio.to_thread).
        redis:    Async Redis client from app.core.redis.get_redis().
        settings: App settings carrying ces_baseline_window and
                  ces_baseline_ttl_seconds.

    Returns:
        The baseline as a float in [0.0, 100.0] rounded to 4 d.p., or None if
        the user has no completed sessions with a recorded CES final.

    Raises:
        HTTPException 503: If the Supabase sessions query fails.
    """
    from fastapi import HTTPException, status  # local import avoids circular dependency

    # Fetch extra rows to account for rows that have ended_at but no ces_final.
    fetch_limit = settings.ces_baseline_window * 3

    try:
        resp = await asyncio.to_thread(
            lambda: supabase.table("sessions")
            .select("ces_final, ended_at")
            .eq("user_id", user_id)
            .order("ended_at", desc=True)
            .limit(fetch_limit)
            .execute()
        )
    except Exception as exc:
        logger.error(
            "CES baseline DB query failed user=%s: %s", user_id, exc, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not read session history.",
        )

    rows: list[dict] = resp.data or []

    # Keep only rows where both fields are non-NULL, take window most-recent.
    scores: list[float] = [
        float(r["ces_final"])
        for r in rows
        if r.get("ces_final") is not None and r.get("ended_at") is not None
    ][: settings.ces_baseline_window]

    baseline = _compute_baseline(scores)
    if baseline is None:
        return None

    # Write to Redis — failure is non-fatal: Redis is a cache, not source of truth.
    key = _redis_key(user_id)
    try:
        await redis.set(key, str(baseline), ex=settings.ces_baseline_ttl_seconds)
    except Exception as exc:
        logger.warning(
            "CES baseline Redis write failed user=%s key=%s: %s",
            user_id,
            key,
            exc,
        )

    return baseline
