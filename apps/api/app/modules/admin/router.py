"""
Admin module router.

Provides operational visibility: job queue inspection, cost reporting,
and a deep health check (includes Redis / DB connectivity).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.dependencies import CurrentUser

router = APIRouter(tags=["admin"])


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
    by_provider: dict[str, float]
    by_user: list[dict[str, Any]]
    lessons_processed: int


class DeepHealthStatus(BaseModel):
    status: str  # "ok" | "degraded" | "down"
    redis: str
    supabase: str
    worker_queue_depth: int | None
    version: str


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get(
    "/jobs",
    response_model=list[JobSummary],
    summary="List all pipeline jobs (admin)",
)
async def list_jobs(
    current_user: CurrentUser,
    limit: int = 50,
    offset: int = 0,
    status_filter: str | None = None,
) -> list[JobSummary]:
    """Return recent pipeline jobs across all users.

    TODO (Sprint 1): Query lesson_jobs table with admin check.
    """
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet")


@router.get(
    "/jobs/{job_id}",
    response_model=JobSummary,
    summary="Get a single pipeline job (admin)",
)
async def get_job(
    job_id: str,
    current_user: CurrentUser,
) -> JobSummary:
    """Return full details for a single pipeline job.

    TODO (Sprint 1): Query lesson_jobs table.
    """
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet")


@router.get(
    "/costs",
    response_model=CostReport,
    summary="Get AI cost report (admin)",
)
async def get_cost_report(
    current_user: CurrentUser,
    period: str = "today",
) -> CostReport:
    """Return aggregated AI costs by provider and user.

    TODO (Sprint 2): Aggregate from cost_events table or Langfuse API.
    """
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet")


@router.get(
    "/health",
    response_model=DeepHealthStatus,
    summary="Deep health check — probes Redis and Supabase",
)
async def deep_health(
    current_user: CurrentUser,
) -> DeepHealthStatus:
    """Probe all downstream dependencies and report status.

    Unlike GET /health (liveness), this endpoint checks Redis ping and
    Supabase connectivity and returns a degraded/down status if any fail.

    TODO (Sprint 1): Implement actual probes.
    """
    # TODO: redis.ping(), supabase.from_("profiles").select("count").limit(1)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet")
