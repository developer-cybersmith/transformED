"""
ARQ cron job: reap_stale_generating_lessons

D53: nothing but content_pipeline_job itself ever transitions a `lessons` row
out of `status='generating'`. A worker killed mid-run (OOM per D50, a deploy,
a container eviction) leaves a row that nothing clears. router.py's
_generating_cutoff_iso() and its two call sites (the idempotency pre-check
and the per-user concurrency count) already stop such a row from blocking a
new generation or consuming a concurrency slot -- but the row itself never
actually becomes `failed`, so GET /lessons/{that exact id} and list_lessons
show a phantom `generating` entry forever. This job closes that gap: it
periodically finds lessons stuck past the SAME staleness bound the query-level
workaround already uses, and marks them `failed` for real.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# BOUNDED: a real stuck-row count anywhere near this in one 10-minute window
# is its own incident, not something this job should try to silently drain
# unbounded in a single pass -- the next scheduled run picks up the rest.
_REAP_BATCH_LIMIT = 100


async def reap_stale_generating_lessons(ctx: dict[str, Any]) -> dict[str, Any]:
    """Mark lessons stuck in `generating` past the ARQ job timeout as `failed`.

    Reuses content_pipeline_job's own _update_lesson_status helper -- the
    SAME path every other failure transition in this codebase goes through,
    already extended by D86 to persist whatever real cost had accumulated in
    Redis before the worker died (never a fabricated 0). A reaped row and a
    genuinely-failed row are therefore indistinguishable to every downstream
    reader.

    Args:
        ctx: ARQ worker context dict (unused here -- no shared resource this
             job needs beyond what get_supabase()/get_redis() already provide).

    Returns:
        {"reaped_count": int, "reaped_lesson_ids": list[str]}
    """
    from app.core.db import get_supabase, rows
    from app.modules.content.router import _generating_cutoff_iso
    from app.workers.jobs.content_pipeline import _update_lesson_status

    supabase = get_supabase()
    stale_before = _generating_cutoff_iso()

    resp = (
        supabase.table("lessons")
        .select("lesson_id, created_at")
        .eq("status", "generating")
        .lt("created_at", stale_before)
        .limit(_REAP_BATCH_LIMIT)
        .execute()
    )
    stale_rows = rows(resp)

    reaped: list[str] = []
    for row in stale_rows:
        lesson_id = row["lesson_id"]
        try:
            await _update_lesson_status(
                supabase,
                lesson_id,
                "failed",
                error=(
                    "reaped: stuck in 'generating' past the job timeout (D53) "
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
