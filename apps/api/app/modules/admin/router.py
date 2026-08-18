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

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.core.db import get_supabase, rows, single_row
from app.core.redis import get_redis
from app.dependencies import AdminUser, ArqRedis

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin"])

__version__ = "0.1.0"

_VALID_JOB_STATUSES = frozenset({"pending", "running", "completed", "failed"})
_REDIS_PING_TIMEOUT_SECONDS = 3.0
# D59(a): cost report row ceiling. Sized generously above any realistic
# near-term admin report volume (real scale today is ~23 lessons total).
# `CostReport.truncated` is set True when a response hits this exactly —
# see that field's docstring for why this must be an explicit surfaced
# signal, not a silent drop.
_COST_REPORT_ROW_LIMIT = 10_000


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
    # Story 3-37 Round-2 review (Scale & Load Hunter): tts_node always writes
    # node_outputs["narration_cap_applied"] (a "capped" bool + totals + the
    # affected segment_ids), but until this field existed nothing ever read
    # it back out — a lesson could ship with its later narration segments
    # silently zeroed and no admin response distinguished it from a fully-
    # narrated one. `select("*")` already fetches node_outputs on every row
    # this endpoint touches; this only stops discarding it. False (not None)
    # when absent — a job that hasn't reached tts_node yet has, as far as
    # this admin view is concerned, nothing capped, same as `completed_at`
    # being genuinely absent is distinct from "we don't know".
    narration_capped: bool


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
    # D59(a): True means the query hit `_COST_REPORT_ROW_LIMIT` — more
    # lesson_jobs rows exist for this period than were fetched, so this
    # report may be missing rows and UNDER-reporting real spend. Narrow
    # the period or raise the limit.
    truncated: bool = False


class JobRetryResponse(BaseModel):
    job_id: str
    lesson_id: str
    # The real ARQ job id that was actually enqueued (e.g.
    # "pipeline:{lesson_id}:retry:{token}") — NOT lesson_jobs.job_id above,
    # which identifies the DB row, not the running ARQ job. Needed to look up
    # or correlate the retried run.
    arq_job_id: str
    status: str  # always "pending" — the state just written, matching JobSummary's vocabulary


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
    node_outputs = row.get("node_outputs")
    narration_cap = (
        node_outputs.get("narration_cap_applied") if isinstance(node_outputs, dict) else None
    )
    narration_capped = (
        bool(narration_cap.get("capped")) if isinstance(narration_cap, dict) else False
    )
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
        narration_capped=narration_capped,
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
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status_filter: str | None = None,
) -> list[JobSummary]:
    """Return recent pipeline jobs across all users, newest first."""
    if status_filter is not None and status_filter not in _VALID_JOB_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"status_filter must be one of: {sorted(_VALID_JOB_STATUSES)}",
        )
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
    try:
        uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found") from None

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


@router.post(
    "/jobs/{job_id}/retry",
    response_model=JobRetryResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Retry a failed pipeline job (admin)",
)
async def retry_job(
    job_id: str,
    current_user: AdminUser,
    arq_redis: ArqRedis,
) -> JobRetryResponse:
    """Re-enqueue a failed job's pipeline run, resuming from its last checkpoint.

    Story 3-58 (S3-4). Only `failed` jobs are retryable. `content_pipeline_job`
    takes only `lesson_id` and re-fetches everything else from `lessons`, so
    retrying never needs to re-validate ownership/chapter/page-span — those
    were already checked when the lesson was first created.

    `node_outputs`/`last_node` are deliberately NOT touched: `run_pipeline`
    reads them to resume from the last completed node (CLAUDE.md's checkpoint
    pattern) — clearing them would silently re-run and re-bill already-paid-for
    nodes. Only `status` (and `error`, cosmetically) are reset here.

    A fresh ARQ `_job_id` is minted per retry rather than reusing the original
    `f"pipeline:{lesson_id}"` — content_pipeline.py's own comment on this exact
    trap: `ctx["job_id"]` alone is not a uniquifier, and reusing it risks a
    stale/duplicate LangGraph `thread_id` if ARQ's `job_try` counter does not
    reset the way this story assumes for a job re-enqueued after the original
    already concluded. A fresh id sidesteps the question entirely.

    Post-review fixes (BMAD retroactive review, 2026-08-14 — see Story 3-58's
    Review Findings section):
    - The status-reset write is scoped by `job_id` (the real primary key), not
      `lesson_id` (no unique constraint — D45 already documents concurrent
      duplicate `lesson_jobs` rows for the same lesson as a real scenario).
      Scoping by `lesson_id` could have silently reset an unrelated running or
      completed job for the same lesson.
    - A retry is rejected (409) if another `lesson_jobs` row for the same
      `lesson_id` is already `running`/`pending` — closes the concurrent-
      execution window that let `content_pipeline.py`'s unconditional
      `clear_lesson_cost()` silently bypass the $3.00 ceiling (Scale & Load
      Hunter finding — the story's own original claim that this was merely
      "a cost nuisance" was wrong; it is a real ceiling bypass). D109 in
      `docs/DEFECT-REGISTER.md` covers the narrow residual TOCTOU window this
      mitigation does not fully close.
    - `enqueue_job` failure is caught and reverts status to `failed` instead of
      leaving the job stuck showing `pending` with nothing actually enqueued.
    - The response returns the real ARQ job id that was enqueued, not the
      pre-existing `lesson_jobs.job_id` — the latter can't be used to look up
      or correlate the retried run.
    """
    try:
        uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found") from None

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

    current_status = row["status"]
    if current_status != "failed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job status is '{current_status}' — only failed jobs can be retried",
        )

    lesson_id = row["lesson_id"]

    # Reject if another job row for this lesson is already active — closes
    # the concurrent-execution window that let clear_lesson_cost() silently
    # bypass the cost ceiling (see docstring above, D109).
    concurrent_resp = (
        supabase.table("lesson_jobs")
        .select("job_id")
        .eq("lesson_id", lesson_id)
        .neq("job_id", job_id)
        .in_("status", ["running", "pending"])
        .execute()
    )
    if rows(concurrent_resp):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another job for this lesson is already running or pending — wait for it",
        )

    # Reset both status columns to the same state generate_chapter_lesson
    # writes at initial creation — node_outputs/last_node/cost_usd untouched.
    # Both writes are scoped by job_id (the real primary key on lesson_jobs),
    # never lesson_id — see docstring.
    supabase.table("lessons").update({"status": "generating"}).eq("lesson_id", lesson_id).execute()
    supabase.table("lesson_jobs").update({"status": "pending", "error": None}).eq(
        "job_id", job_id
    ).execute()

    retry_token = uuid.uuid4().hex[:8]
    arq_job_id = f"pipeline:{lesson_id}:retry:{retry_token}"
    try:
        job = await arq_redis.enqueue_job("content_pipeline_job", lesson_id, _job_id=arq_job_id)
    except Exception:
        logger.warning(
            "retry_job:%s — enqueue_job raised, reverting to failed", job_id, exc_info=True
        )
        supabase.table("lesson_jobs").update(
            {"status": "failed", "error": "Failed to enqueue retry"}
        ).eq("job_id", job_id).execute()
        supabase.table("lessons").update({"status": "failed"}).eq("lesson_id", lesson_id).execute()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue retry",
        ) from None

    if job is None:
        # Not truly unreachable — arq_job_id is fresh per call, which makes a
        # dedup collision astronomically unlikely, not impossible. Still
        # never silently claim a retry that ARQ actually deduplicated away.
        supabase.table("lesson_jobs").update(
            {"status": "failed", "error": "ARQ deduplicated the retry job"}
        ).eq("job_id", job_id).execute()
        supabase.table("lessons").update({"status": "failed"}).eq("lesson_id", lesson_id).execute()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue retry — ARQ deduplicated the job",
        )

    return JobRetryResponse(
        job_id=job_id, lesson_id=lesson_id, arq_job_id=job.job_id, status="pending"
    )


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
    the period window. The period filter is applied server-side via an
    embedded-resource filter on the inner-joined `lessons.created_at`
    (`!inner` hint — without it, PostgREST filters only the embedded rows,
    not the top-level `lesson_jobs` rows). This avoids an unbounded full-table
    fetch (Story 2-25 code review) and means every row Python sees already
    has a non-null `lessons` join, so no per-row date parsing/guard is needed.
    Grouping by user is done in Python — PostgREST has no server-side GROUP BY.
    """
    start = _period_start(period)
    supabase = get_supabase()
    resp = (
        supabase.table("lesson_jobs")
        .select("cost_usd, lesson_id, lessons!inner(user_id, created_at)")
        .gte("lessons.created_at", start.isoformat())
        .limit(_COST_REPORT_ROW_LIMIT)
        .execute()
    )
    matching = rows(resp)
    # D59(a): exactly hitting the limit is the real signal more rows may
    # exist beyond it (not a guess) — PostgREST returned precisely what was
    # asked for, which is indistinguishable from "there could be more"
    # without a second query. Surfaced on the response, never dropped silently.
    truncated = len(matching) == _COST_REPORT_ROW_LIMIT

    totals_by_user: dict[str, float] = {}
    total_cost = 0.0
    for row in matching:
        cost = float(row.get("cost_usd") or 0.0)
        user_id = row["lessons"]["user_id"]
        totals_by_user[user_id] = totals_by_user.get(user_id, 0.0) + cost
        total_cost += cost

    return CostReport(
        period=period,
        total_cost_usd=total_cost,
        by_user=[
            {"user_id": user_id, "cost_usd": cost} for user_id, cost in totals_by_user.items()
        ],
        lessons_processed=len({row["lesson_id"] for row in matching}),
        truncated=truncated,
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
        await asyncio.wait_for(redis.ping(), timeout=_REDIS_PING_TIMEOUT_SECONDS)
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
