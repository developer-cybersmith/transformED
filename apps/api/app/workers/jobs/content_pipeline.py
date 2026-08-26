"""
ARQ job: content_pipeline_job

Runs the full 14-node LangGraph content pipeline for a single lesson.

ARQ context (ctx) keys provided by WorkerSettings.on_startup:
    ctx["redis"]    — arq Redis connection (arq.connections.ArqRedis)
    ctx["settings"] — app Settings instance

Celery is BANNED per PRD §24 — this job uses ARQ exclusively.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC
from typing import Any

logger = logging.getLogger(__name__)


async def content_pipeline_job(ctx: dict[str, Any], lesson_id: str) -> dict[str, Any]:
    """Execute the content pipeline for *lesson_id*.

    Lifecycle
    ---------
    1. Mark lesson_jobs status → "running"
    2. Fetch source PDF path from lesson_jobs table
    3. Run LangGraph pipeline (run_pipeline)
    4. On success: mark status → "completed", send WebSocket "lesson_ready" event
    5. On failure: mark status → "failed", log error, re-raise for ARQ retry

    Args:
        ctx:       ARQ worker context dict (redis, settings).
        lesson_id: UUID string of the lesson to process.

    Returns:
        Dict with ``{"lesson_id": ..., "status": "completed", "package_summary": {...}}``
        on success.  ARQ stores this as the job result.

    Raises:
        Exception: Any unhandled error causes ARQ to mark the job as failed and
                   retry up to ``WorkerSettings.max_tries`` times.
    """
    from app.core.cost_tracker import clear_lesson_cost, get_cost
    from app.core.db import get_supabase, single_row
    from app.modules.content.pipeline.graph import run_pipeline

    logger.info("content_pipeline_job START lesson_id=%s", lesson_id)

    supabase = get_supabase()

    # ── 1. Transition to "running" ────────────────────────────────────────────
    await _update_lesson_status(supabase, lesson_id, "running")

    try:
        # ── 2. Fetch lesson metadata from lessons table ───────────────────────
        result = (
            supabase.table("lessons")
            .select("user_id, source_file_path, book_id, chapter_id, tier")
            .eq("lesson_id", lesson_id)
            .single()
            .execute()
        )
        lesson_row: dict[str, Any] = single_row(result) or {}

        user_id: str = lesson_row.get("user_id", "")
        source_pdf_path: str = lesson_row.get("source_file_path", "")
        book_id: str = lesson_row.get("book_id", "")
        # Story 1-13 (book-scale Phase 5): `lessons.chapter_id` — added by
        # migration 20260803000000 and, until this line, read by NOTHING in the
        # codebase. It names the ONE chapter this lesson is generated from;
        # extract_node turns it into a page range so the pipeline sees ~40
        # pages instead of the whole 1,151-page book.
        #
        # `or ""` here is NOT a D33-style silent default: the column is
        # nullable, and this is the boundary that converts "column is NULL" to
        # "argument is empty". extract_node then raises a diagnostic naming
        # both ids rather than extracting the whole document. Phase 6's
        # generate endpoint is what sets the column at lesson creation.
        chapter_id: str = lesson_row.get("chapter_id") or ""
        # S2-LM3: tier reaches the pipeline via this SAME lessons-table
        # re-fetch, not a separate ARQ job-payload argument (corrects the
        # tracker's original "thread into the ARQ job" wording, per Story
        # 2-2's Dev Notes). lessons.tier defaults 'T2' at the DB level
        # (migration 20260714020000), so this is never missing in practice —
        # the "T2" fallback here only matters for a row from before that
        # migration or a malformed select response.
        tier: str = lesson_row.get("tier") or "T2"
        # Story 2-37 / D23: there is deliberately NO session_id here.
        #
        # This used to read `lesson_row.get("session_id") or lesson_id`. `lessons`
        # has no `session_id` column, so the fallback ALWAYS fired — the channel
        # was right by accident, and one unrelated migration adding that column
        # would have silently changed the publish key under Dev 4's routing with
        # no test failing. See `tests/unit/test_lesson_ready_routing_key.py`.
        #
        # The routing key is the LESSON, decided by Dev 4 (handoff 2026-07-29 §2,
        # option A): generation completion is a property of the lesson, not of a
        # viewer — a lesson is generated once and can be watched in many sessions.
        # Dev 4 keeps a `lesson_waiters:{lesson_id}` set and fans out to every
        # waiting session, so this side must never key on a viewer.

        # lesson_package is the REAL, schema-validated LessonPackage produced by
        # package_builder_node (Story 2-11, landed 2026-07-16) —
        # package.model_dump(mode="json"). Top-level keys: lesson_id/book_id/
        # chapter_id/created_at/metadata/segments/glossary. It is republished
        # verbatim below (already validated by package_builder_node itself).
        # ── 3. Run LangGraph pipeline ─────────────────────────────────────────
        # Story 2-28 AC-5: `attempt` must uniquify the LangGraph thread_id per
        # ARQ try. TRAP: ctx["job_id"] alone is NOT a uniquifier — router.py
        # pins _job_id=f"pipeline:{lesson_id}" for enqueue-dedup, so it is
        # byte-identical on every retry. job_try is what actually varies.
        # This scopes ONLY the LangGraph thread_id — never the
        # merge_lesson_job_node_output key space, which must stay
        # f"{node}:{section_id}" or every section re-bills on retry.
        attempt = f"{ctx.get('job_id', 'nojob')}:{ctx.get('job_try', 1)}"
        lesson_package = await run_pipeline(
            lesson_id=lesson_id,
            user_id=user_id,
            source_pdf_path=source_pdf_path,
            book_id=book_id,
            chapter_id=chapter_id,
            tier=tier,
            attempt=attempt,
        )

        # ── 4a. Mark job completed ────────────────────────────────────────────
        # Schema note: lesson_jobs has NO lesson_package/progress_pct columns and
        # its status CHECK allows only pending/running/completed/failed — the
        # previous write ('ready' + lesson_package) failed with PGRST204 at the
        # end of every otherwise-successful run. The full LessonPackage is
        # persisted to lessons.content by package_builder (S2-11).
        from datetime import datetime

        # D86: lesson_jobs.cost_usd (numeric(10,4), initial_schema.sql) was
        # never written by anything — clear_lesson_cost()'s own docstring
        # promises "the cost has been persisted to the DB" before the Redis
        # key is deleted below, but that persistence step was never built.
        # Read the REAL accumulated Redis total here, BEFORE clear_lesson_cost
        # deletes it, and fold it into this SAME completion write (no second
        # DB round trip). A Redis read failure must degrade — never crash an
        # otherwise-successful pipeline run over a secondary tracking concern
        # — matching _update_lesson_status's own try/except-and-degrade below.
        completion_payload: dict[str, Any] = {
            "status": "completed",
            "completed_at": datetime.now(tz=UTC).isoformat(),
        }
        try:
            current_cost = await get_cost(lesson_id)
            completion_payload["cost_usd"] = round(current_cost, 4)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to read accumulated cost for lesson_id=%s; cost_usd left unset",
                lesson_id,
            )

        supabase.table("lesson_jobs").update(completion_payload).eq(
            "lesson_id", lesson_id
        ).execute()

        # CROSS-TEAM NOTE (2026-07-13, flagged to Dev 1 — this file's owner):
        # GET /api/content/lessons/{id} (router.py) reads lessons.status, NOT
        # lesson_jobs.status — but nothing in this job ever wrote to `lessons`.
        # Confirmed via live testing: a completed/failed job left lessons.status
        # stuck at its initial 'generating' forever, so the polling endpoint
        # could never report 'ready' or 'failed' to the client for ANY lesson.
        # No completed_at here — `lessons` (initial_schema.sql, frozen) has no
        # such column, only created_at/updated_at (updated_at is trigger-managed).
        supabase.table("lessons").update({"status": "ready"}).eq("lesson_id", lesson_id).execute()

        # ── 4b. Notify client via Redis pub/sub ──────────────────────────────
        import json

        from app.core.redis import get_redis

        redis = get_redis()
        channel = f"lesson_ready:{lesson_id}"
        # payload matches packages/shared/types/ws.ts's LessonReadyMessage
        # exactly ({lesson_id, lesson}).
        #
        # Story 2-37 corrects the note that used to sit here. It said the payload
        # need not carry session_id because session_id "is already the channel
        # suffix". After D23 the channel suffix is the LESSON id, and no session
        # is known on this side at all — Dev 4 resolves waiting sessions from
        # `lesson_waiters:{lesson_id}` at delivery time. Leaving the old wording
        # would have actively misled the next reader about the routing contract.
        message = {
            "type": "lesson_ready",
            "payload": {
                "lesson_id": lesson_id,
                "lesson": lesson_package,
            },
        }
        await redis.publish(channel, json.dumps(message))
        logger.info("content_pipeline_job PUBLISHED lesson_ready channel=%s", channel)

        # ── 4b-2. Enqueue the "lesson ready" notification email (Story 2-52) ──
        # ctx["redis"] is the ArqRedis job-enqueue pool (same process, no
        # cross-process hop needed here — contrast session_end_node's
        # _finalize_session, which DOES need one via app.core.arq_pool).
        # A failure to enqueue must not fail the pipeline job itself, which
        # has already fully succeeded at this point.
        try:
            await ctx["redis"].enqueue_job(
                "send_notification_email_job",
                user_id,
                "lesson_ready",
                lesson_id,
                _job_id=f"notify:lesson_ready:{lesson_id}",
            )
        except Exception:
            logger.exception(
                "content_pipeline_job: failed to enqueue lesson_ready notification "
                "lesson_id=%s",
                lesson_id,
            )

        # ── 4c. Clear cost tracker ────────────────────────────────────────────
        await clear_lesson_cost(lesson_id)

        logger.info("content_pipeline_job COMPLETE lesson_id=%s", lesson_id)
        # lesson_package is the REAL nested LessonPackage (Story 2-11) —
        # slides_count/quiz_count are aggregated per-segment (Segment.slides,
        # Segment.quiz); audio_count is the segment count itself, since
        # package_builder_node guarantees exactly one narration per assembled
        # segment (2026-07-16 fix, Story 2-12 — the previous
        # .get("slides"/"quiz_questions"/"audio_assets", []) calls read
        # top-level keys that only existed on the old flat stub shape and
        # have silently returned 0/0/0 since Story 2-11 landed).
        # 2026-07-16 review finding (Edge Case Hunter): .get("segments", [])
        # only degrades when the key is MISSING — an explicit non-list value
        # (e.g. None) would still crash here, AFTER the WS publish above has
        # already succeeded. Unreachable today (lesson_package is always a
        # validated LessonPackage.model_dump()), but the failure mode is bad
        # enough (client already notified, job then raises and may retry) to
        # guard cheaply against regardless.
        segments = lesson_package.get("segments", [])
        if not isinstance(segments, list):
            segments = []
        return {
            "lesson_id": lesson_id,
            "status": "completed",
            "package_summary": {
                "slides_count": sum(len(seg.get("slides", [])) for seg in segments),
                "quiz_count": sum(len(seg.get("quiz", [])) for seg in segments),
                "audio_count": len(segments),
            },
        }

    except RuntimeError as exc:
        # RuntimeError includes cost ceiling exceeded — mark as specific status
        error_msg = str(exc)
        if "cost ceiling" in error_msg:
            # lesson_jobs.status CHECK allows only pending/running/completed/failed —
            # a 'cost_limit_exceeded' literal is silently rejected and the row sticks
            # at 'running'. Record 'failed' with a distinguishing error prefix instead.
            # Full downshift-and-complete cost-ceiling behavior is S2-13.
            error = f"cost_ceiling_exceeded: {error_msg}"[:2000]
            await _update_lesson_status(supabase, lesson_id, "failed", error=error)
            logger.warning("content_pipeline_job COST_LIMIT lesson_id=%s: %s", lesson_id, error_msg)
            return {"lesson_id": lesson_id, "status": "failed", "error": error}

        await _update_lesson_status(supabase, lesson_id, "failed", error=error_msg)
        logger.exception("content_pipeline_job FAILED lesson_id=%s", lesson_id)
        raise  # Let ARQ retry

    except asyncio.CancelledError:
        # ARQ job_timeout or worker shutdown cancelled us — record the failure
        # so the lesson row never sits in "running" forever (AC-5, Story 2-0).
        # asyncio.shield lets the status write complete even though this task
        # is already cancelled; the write itself is best-effort.
        try:
            await asyncio.shield(
                _update_lesson_status(
                    supabase,
                    lesson_id,
                    "failed",
                    error="job cancelled (ARQ timeout or worker shutdown)",
                )
            )
        except BaseException:  # noqa: BLE001 — a re-delivered cancellation is
            # BaseException, not Exception: a second cancel arriving while the
            # shielded write runs must not mask the original cancellation (we
            # still re-raise the outer CancelledError below).
            logger.warning("Failed to record cancellation for lesson_id=%s", lesson_id)
        logger.warning("content_pipeline_job CANCELLED lesson_id=%s", lesson_id)
        raise  # Cancellation must always propagate

    except Exception as exc:
        error_msg = str(exc)
        await _update_lesson_status(supabase, lesson_id, "failed", error=error_msg)
        logger.exception("content_pipeline_job FAILED lesson_id=%s", lesson_id)
        raise  # Let ARQ retry


# ── Helpers ───────────────────────────────────────────────────────────────────


# lesson_jobs.status ('pending'|'running'|'completed'|'failed') -> the
# lessons.status this helper is ever called with ('generating'|'failed' only
# — 'completed' is written directly at the pipeline's success site instead).
_LESSON_JOBS_TO_LESSONS_STATUS: dict[str, str] = {
    "running": "generating",
    "failed": "failed",
}


async def _update_lesson_status(
    supabase: Any,  # noqa: ANN401
    lesson_id: str,
    status: str,
    error: str | None = None,
    cost_usd: float | None = None,
) -> None:
    """Update lesson_jobs.status (and optionally error/cost_usd), and mirror
    onto lessons.status — GET /api/content/lessons/{id} (router.py) reads
    lessons, not lesson_jobs, so both must be kept in sync (CROSS-TEAM NOTE
    2026-07-13, flagged to Dev 1: confirmed via live testing that
    lessons.status was never written here at all, so the polling endpoint
    could never report anything but the initial 'generating', for any lesson,
    success or failure).

    D86: every path that marks a lesson job "failed" must also persist
    whatever real Redis-accumulated cost had built up before the failure —
    not 0, and not silently absent. When *cost_usd* isn't passed explicitly,
    fetch it here (once, only for the 'failed' status — the 'running'
    transition has no accumulated cost yet and a cost read there would be
    pure waste). A Redis read failure degrades to leaving cost_usd unset
    rather than raising: this is a secondary tracking concern and must never
    break the primary status write below (matches the try/except-and-degrade
    pattern this function already applies to its own Supabase writes).

    D91: the 'running' transition also writes lesson_jobs.started_at — the
    REAL moment this attempt began executing, not lessons.created_at (when
    the row was inserted, before the job was even enqueued). D53's reaper
    used created_at as its only staleness signal, which conflates queue-wait
    time with run time: a job that sits queued for a while before a worker
    picks it up gets less real run-time budget than arq_job_timeout_s before
    being reaped, even though it may still be genuinely alive and working.
    Observed live: a real job whose retry was delayed ~32 minutes before ARQ
    even dequeued it got reaped while still actually running, leaving
    lessons.status='failed' and lesson_jobs.status='running' inconsistent.
    Every retry attempt overwrites started_at with ITS OWN start time, which
    is correct — a fresh attempt deserves a fresh staleness clock, not the
    original row's creation time or an earlier attempt's start."""
    if status == "failed" and cost_usd is None:
        try:
            from app.core.cost_tracker import get_cost

            cost_usd = await get_cost(lesson_id)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to read accumulated cost for lesson_id=%s; cost_usd left unset",
                lesson_id,
            )

    try:
        payload: dict[str, Any] = {"status": status}
        if error:
            payload["error"] = error[:2000]  # Truncate to avoid DB column overflow
        if cost_usd is not None:
            payload["cost_usd"] = round(cost_usd, 4)
        if status == "running":
            from datetime import datetime

            payload["started_at"] = datetime.now(tz=UTC).isoformat()

        supabase.table("lesson_jobs").update(payload).eq("lesson_id", lesson_id).execute()
    except Exception:  # noqa: BLE001
        logger.warning(
            "Failed to update lesson status for lesson_id=%s status=%s", lesson_id, status
        )

    lessons_status = _LESSON_JOBS_TO_LESSONS_STATUS.get(status)
    if lessons_status is None:
        return
    try:
        # lessons has no `error` column (initial_schema.sql) — the error detail
        # lives on lesson_jobs.error only; router.py's get_lesson() already
        # reads it from there when lessons.status == 'failed'.
        supabase.table("lessons").update({"status": lessons_status}).eq(
            "lesson_id", lesson_id
        ).execute()
    except Exception:  # noqa: BLE001
        logger.warning(
            "Failed to update lessons.status for lesson_id=%s status=%s", lesson_id, lessons_status
        )
