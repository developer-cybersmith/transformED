"""
Admin module router.

Provides operational visibility: job queue inspection, cost reporting,
and a deep health check (includes Redis / DB connectivity).

All routes are gated by ``require_admin`` (Story 2-25) — a static
``ADMIN_EMAILS`` allowlist checked against the caller's JWT `email` claim.
No DB migration/role table involved; see
docs/stories/2-25-sprint2-audit-gapfix-dev1-items.md Dev Notes for why.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.core.db import get_supabase, rows, single_row
from app.core.redis import get_redis
from app.dependencies import AdminUser

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin"])

__version__ = "0.1.0"


# ── Response models ───────────────────────────────────────────────────────────


class JobSummary(BaseModel):
    job_id: str
    lesson_id: str
    status: str
    user_id: str
    created_at: str
    started_at: str | None
    completed_at: str | None
    error: str | None
    cost_usd: float | None


class CostReport(BaseModel):
    period: str  # "today" | "this_week" | "this_month"
    total_cost_usd: float
    # by_provider intentionally omitted — cost_tracker.py tracks a single
    # running total per lesson (Redis key `cost:{lesson_id}`), never broken
    # out per-provider anywhere in the system. Faking an always-empty dict
    # would look like real (if currently zero) data; an honest gap is better.
    # Revisit once Epic 3 Story 3.3 (Langfuse cost attribution) lands.
    by_user: list[dict[str, float | str]]
    lessons_processed: int


class DeepHealthStatus(BaseModel):
    status: str  # "ok" | "degraded" | "down"
    redis: str
    supabase: str
    # ARQ's ArqRedis doesn't expose a simple "jobs queued" call without
    # reaching into its internal Redis key structure — left None rather
    # than faked. See Story 2-25 Dev Notes.
    worker_queue_depth: int | None
    version: str


def _job_row_to_summary(row: dict[str, Any]) -> JobSummary:
    lesson = row.get("lessons") or {}
    return JobSummary(
        job_id=row["job_id"],
        lesson_id=row["lesson_id"],
        status=row["status"],
        user_id=lesson.get("user_id", ""),
        created_at=row["created_at"],
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
        error=row.get("error"),
        cost_usd=row.get("cost_usd"),
    )


def _period_start(period: str) -> datetime:
    now = datetime.now(UTC)
    if period == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "this_week":
        start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start_of_today - timedelta(days=start_of_today.weekday())
    if period == "this_month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="period must be one of: today, this_week, this_month",
    )


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get(
    "/jobs",
    response_model=list[JobSummary],
    summary="List all pipeline jobs (admin)",
)
async def list_jobs(
    current_user: AdminUser,
    limit: int = 50,
    offset: int = 0,
    status_filter: str | None = None,
) -> list[JobSummary]:
    """Return recent pipeline jobs across all users, newest first."""
    supabase = get_supabase()
    query = (
        supabase.table("lesson_jobs")
        .select("*, lessons(user_id)")
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
    )
    if status_filter is not None:
        query = query.eq("status", status_filter)
    resp = query.execute()
    return [_job_row_to_summary(row) for row in rows(resp)]


@router.get(
    "/jobs/{job_id}",
    response_model=JobSummary,
    summary="Get a single pipeline job (admin)",
)
async def get_job(
    job_id: str,
    current_user: AdminUser,
) -> JobSummary:
    """Return full details for a single pipeline job."""
    supabase = get_supabase()
    resp = (
        supabase.table("lesson_jobs")
        .select("*, lessons(user_id)")
        .eq("job_id", job_id)
        .maybe_single()
        .execute()
    )
    row = single_row(resp)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return _job_row_to_summary(row)


@router.get(
    "/costs",
    response_model=CostReport,
    summary="Get AI cost report (admin)",
)
async def get_cost_report(
    current_user: AdminUser,
    period: str = "today",
) -> CostReport:
    """Return aggregated AI costs for the given period, grouped by user.

    Aggregates `lesson_jobs.cost_usd` for jobs whose lesson was created within
    the period window. Grouping is done in Python — Supabase's PostgREST
    layer has no server-side GROUP BY for this query shape.
    """
    start = _period_start(period)
    supabase = get_supabase()
    resp = (
        supabase.table("lesson_jobs")
        .select("cost_usd, lesson_id, lessons(user_id, created_at)")
        .execute()
    )
    matching = [
        row
        for row in rows(resp)
        if (lesson := (row.get("lessons") or {}))
        and lesson.get("created_at")
        and datetime.fromisoformat(lesson["created_at"].replace("Z", "+00:00")) >= start
    ]

    totals_by_user: dict[str, float] = {}
    total_cost = 0.0
    for row in matching:
        cost = float(row.get("cost_usd") or 0.0)
        user_id = (row.get("lessons") or {}).get("user_id", "unknown")
        totals_by_user[user_id] = totals_by_user.get(user_id, 0.0) + cost
        total_cost += cost

    return CostReport(
        period=period,
        total_cost_usd=total_cost,
        by_user=[
            {"user_id": user_id, "cost_usd": cost} for user_id, cost in totals_by_user.items()
        ],
        lessons_processed=len({row["lesson_id"] for row in matching}),
    )


@router.get(
    "/health",
    response_model=DeepHealthStatus,
    summary="Deep health check — probes Redis and Supabase",
)
async def deep_health(
    current_user: AdminUser,
) -> DeepHealthStatus:
    """Probe all downstream dependencies and report status.

    Unlike GET /health (liveness), this endpoint checks Redis ping and
    Supabase connectivity and returns a degraded/down status if either fails.
    """
    redis_ok = True
    try:
        redis = get_redis()
        await redis.ping()
    except Exception:
        logger.warning("Deep health check: Redis ping failed", exc_info=True)
        redis_ok = False

    supabase_ok = True
    try:
        supabase = get_supabase()
        supabase.table("lessons").select("lesson_id").limit(1).execute()
    except Exception:
        logger.warning("Deep health check: Supabase probe failed", exc_info=True)
        supabase_ok = False

    if redis_ok and supabase_ok:
        overall = "ok"
    elif redis_ok or supabase_ok:
        overall = "degraded"
    else:
        overall = "down"

    return DeepHealthStatus(
        status=overall,
        redis="ok" if redis_ok else "down",
        supabase="ok" if supabase_ok else "down",
        worker_queue_depth=None,
        version=__version__,
    )
