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
    from app.core.cost_tracker import clear_lesson_cost
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
            .select("user_id, source_file_path, book_id, tier")
            .eq("lesson_id", lesson_id)
            .single()
            .execute()
        )
        lesson_row: dict[str, Any] = single_row(result) or {}

        user_id: str = lesson_row.get("user_id", "")
        source_pdf_path: str = lesson_row.get("source_file_path", "")
        book_id: str = lesson_row.get("book_id", "")
        # S2-LM3: tier reaches the pipeline via this SAME lessons-table
        # re-fetch, not a separate ARQ job-payload argument (corrects the
        # tracker's original "thread into the ARQ job" wording, per Story
        # 2-2's Dev Notes). lessons.tier defaults 'T2' at the DB level
        # (migration 20260714020000), so this is never missing in practice —
        # the "T2" fallback here only matters for a row from before that
        # migration or a malformed select response.
        tier: str = lesson_row.get("tier") or "T2"
        # session_id is the WebSocket routing key; falls back to lesson_id until
        # the upload route stores it (Sprint 2 — Dev 4 coordinates)
        session_id: str = lesson_row.get("session_id") or lesson_id

        # lesson_package is the REAL, schema-validated LessonPackage produced by
        # package_builder_node (Story 2-11, landed 2026-07-16) —
        # package.model_dump(mode="json"). Top-level keys: lesson_id/book_id/
        # chapter_id/created_at/metadata/segments/glossary. It is republished
        # verbatim below (already validated by package_builder_node itself).
        # ── 3. Run LangGraph pipeline ─────────────────────────────────────────
        lesson_package = await run_pipeline(
            lesson_id=lesson_id,
            user_id=user_id,
            source_pdf_path=source_pdf_path,
            book_id=book_id,
            tier=tier,
        )

        # ── 4a. Mark job completed ────────────────────────────────────────────
        # Schema note: lesson_jobs has NO lesson_package/progress_pct columns and
        # its status CHECK allows only pending/running/completed/failed — the
        # previous write ('ready' + lesson_package) failed with PGRST204 at the
        # end of every otherwise-successful run. The full LessonPackage is
        # persisted to lessons.content by package_builder (S2-11).
        from datetime import datetime

        supabase.table("lesson_jobs").update(
            {
                "status": "completed",
                "completed_at": datetime.now(tz=UTC).isoformat(),
            }
        ).eq("lesson_id", lesson_id).execute()

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
        channel = f"lesson_ready:{session_id}"
        # payload matches packages/shared/types/ws.ts's LessonReadyMessage
        # exactly ({lesson_id, lesson}) — session_id is already the pub/sub
        # channel suffix / WebSocket routing key, it does not need to be
        # duplicated inside the payload too (2026-07-16 review finding,
        # Story 2-12 — the subscriber in app/core/pubsub.py already extracts
        # session_id from the CHANNEL name, never read it from the payload).
        message = {
            "type": "lesson_ready",
            "payload": {
                "lesson_id": lesson_id,
                "lesson": lesson_package,
            },
        }
        await redis.publish(channel, json.dumps(message))
        logger.info("content_pipeline_job PUBLISHED lesson_ready channel=%s", channel)

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
) -> None:
    """Update lesson_jobs.status (and optionally error), and mirror onto
    lessons.status — GET /api/content/lessons/{id} (router.py) reads lessons,
    not lesson_jobs, so both must be kept in sync (CROSS-TEAM NOTE 2026-07-13,
    flagged to Dev 1: confirmed via live testing that lessons.status was never
    written here at all, so the polling endpoint could never report anything
    but the initial 'generating', for any lesson, success or failure)."""
    try:
        payload: dict[str, Any] = {"status": status}
        if error:
            payload["error"] = error[:2000]  # Truncate to avoid DB column overflow

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
