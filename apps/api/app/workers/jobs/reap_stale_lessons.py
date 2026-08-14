"""
ARQ cron job: reap_stale_generating_lessons

D53: nothing but content_pipeline_job itself ever transitions a `lessons` row
out of `status='generating'`. A worker killed mid-run (OOM per D50, a deploy,
a container eviction) leaves a row that nothing clears. router.py's
_generating_cutoff_iso() and its two call sites (the idempotency pre-check
and the per-user concurrency count) already stop such a row from blocking a
new generation or consuming a concurrency slot -- but the row itself never
actually became `failed`, so GET /lessons/{that exact id} and list_lessons
show a phantom `generating` entry forever. This job closes that gap: it
periodically finds lessons stuck past a real staleness bound, and marks them
`failed` for real.

D91: the original version used `lessons.created_at` (row-insert time, BEFORE
the job is even enqueued) as its only staleness signal -- the same known
limitation `_generating_cutoff_iso()`'s own docstring already named and
deliberately deferred at D53's close ("the durable fix is the D53 reaper
plus a real started_at"). Observed live: a real job whose ARQ retry was
delayed ~32 minutes before even being dequeued (a separate, pre-existing
event-loop-blocking issue) got reaped by the OLD logic while still actually
running, leaving lessons.status='failed' and lesson_jobs.status='running'
permanently inconsistent -- exactly the harm a false-positive reap causes.
Now uses lesson_jobs.started_at (written by content_pipeline.py's
_update_lesson_status on the 'running' transition, D91) as the precise
run-time-only signal when available, falling back to a more GENEROUS
queue-wait-inclusive bound via lesson_jobs.created_at only for jobs that
have not started running at all yet.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# BOUNDED: a real stuck-row count anywhere near this in one 10-minute window
# is its own incident, not something this job should try to silently drain
# unbounded in a single pass -- the next scheduled run picks up whatever's
# left.
_REAP_BATCH_LIMIT = 100

# D91: a job that has not started running yet (started_at still null) may
# simply be sitting in queue behind others -- max_concurrent_generations_per_user
# bounds how many can plausibly stack up, but queue-wait is real time a job
# can legitimately spend alive without yet touching content_pipeline_job's
# own started_at write. 2x arq_job_timeout_s is a reasoned, generous margin
# for that case, not an exact derivation -- erring toward NOT falsely
# reaping a merely-queued job, since a false reap is the harmful direction.
_QUEUE_WAIT_MULTIPLIER = 2


async def reap_stale_generating_lessons(ctx: dict[str, Any]) -> dict[str, Any]:
    """Mark lessons stuck in `generating` past a real staleness bound as `failed`.

    Reuses content_pipeline_job's own _update_lesson_status helper -- the
    SAME path every other failure transition in this codebase goes through,
    already extended by D86 to persist whatever real cost had accumulated in
    Redis before the worker died (never a fabricated 0). A reaped row and a
    genuinely-failed row are therefore indistinguishable to every downstream
    reader.

    Args:
        ctx: ARQ worker context dict (unused here -- no shared resource this
             job needs beyond what get_supabase() already provides).

    Returns:
        {"reaped_count": int, "reaped_lesson_ids": list[str]}
    """
    from app.config import get_settings
    from app.core.db import get_supabase, rows
    from app.workers.jobs.content_pipeline import _update_lesson_status

    supabase = get_supabase()
    settings = get_settings()
    now = datetime.now(tz=UTC)
    run_cutoff = (now - timedelta(seconds=settings.arq_job_timeout_s)).isoformat()
    queue_cutoff = (
        now - timedelta(seconds=settings.arq_job_timeout_s * _QUEUE_WAIT_MULTIPLIER)
    ).isoformat()

    # Query lesson_jobs directly (not lessons) -- it is the table that
    # actually carries status/started_at/created_at at the granularity this
    # job needs, and lesson_jobs.status is never 'pending'/'running' once a
    # lesson has genuinely completed (the success path writes 'completed'
    # directly), so no separate lessons.status filter is needed to avoid
    # touching an already-finished lesson.
    #
    # The query's own .lt() uses the MORE GENEROUS queue_cutoff -- a real
    # superset of what's actually stale, refined precisely in Python below
    # via each row's own started_at. This keeps the query itself simple and
    # bounded while the two-tier precision lives where it's easy to reason
    # about and test.
    resp = (
        supabase.table("lesson_jobs")
        .select("lesson_id, started_at, created_at")
        .in_("status", ["pending", "running"])
        .lt("created_at", queue_cutoff)
        .limit(_REAP_BATCH_LIMIT)
        .execute()
    )
    candidates: list[dict[str, Any]] = rows(resp)

    stale_lesson_ids: list[str] = []
    for row in candidates:
        started_at = row.get("started_at")
        if started_at:
            # Real run-time signal: this specific attempt actually started
            # executing at started_at -- precise arq_job_timeout_s bound.
            if str(started_at) < run_cutoff:
                stale_lesson_ids.append(row["lesson_id"])
        else:
            # Never started running (still queued, or the worker died before
            # reaching content_pipeline_job's own "running" write) -- already
            # known older than the generous queue_cutoff via the query above.
            stale_lesson_ids.append(row["lesson_id"])

    reaped: list[str] = []
    for lesson_id in stale_lesson_ids:
        try:
            await _update_lesson_status(
                supabase,
                lesson_id,
                "failed",
                error=(
                    "reaped: stuck in 'generating' past the job timeout (D53/D91) "
                    "-- the worker likely crashed, was OOM-killed, or was "
                    "evicted before it could record a terminal status"
                ),
            )
            reaped.append(lesson_id)
        except Exception:  # noqa: BLE001 -- one bad row must not stop the batch
            logger.exception("D53 reaper: failed to reap lesson_id=%s", lesson_id)

    if reaped:
        logger.warning(
            "D53 reaper: marked %d stale 'generating' lesson(s) failed: %s",
            len(reaped),
            reaped,
        )

    return {"reaped_count": len(reaped), "reaped_lesson_ids": reaped}
