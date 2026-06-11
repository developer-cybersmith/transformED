"""
ARQ job: content_pipeline_job

Runs the full 14-node LangGraph content pipeline for a single lesson.

ARQ context (ctx) keys provided by WorkerSettings.on_startup:
    ctx["redis"]    — arq Redis connection (arq.connections.ArqRedis)
    ctx["settings"] — app Settings instance

Celery is BANNED per PRD §24 — this job uses ARQ exclusively.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def content_pipeline_job(ctx: dict[str, Any], lesson_id: str) -> dict[str, Any]:
    """Execute the content pipeline for *lesson_id*.

    Lifecycle
    ---------
    1. Mark lesson_jobs status → "running"
    2. Fetch source PDF path from lesson_jobs table
    3. Run LangGraph pipeline (run_pipeline)
    4. On success: mark status → "ready", send WebSocket "lesson_ready" event
    5. On failure: mark status → "failed", log error, re-raise for ARQ retry

    Args:
        ctx:       ARQ worker context dict (redis, settings).
        lesson_id: UUID string of the lesson to process.

    Returns:
        Dict with ``{"lesson_id": ..., "status": "ready", "package_summary": {...}}``
        on success.  ARQ stores this as the job result.

    Raises:
        Exception: Any unhandled error causes ARQ to mark the job as failed and
                   retry up to ``WorkerSettings.max_tries`` times.
    """
    from app.core.cost_tracker import clear_lesson_cost
    from app.core.db import get_supabase
    from app.core.websocket import manager
    from app.modules.content.pipeline.graph import run_pipeline

    logger.info("content_pipeline_job START lesson_id=%s", lesson_id)

    supabase = get_supabase()

    # ── 1. Transition to "running" ────────────────────────────────────────────
    await _update_lesson_status(supabase, lesson_id, "running")

    try:
        # ── 2. Fetch lesson metadata ──────────────────────────────────────────
        result = supabase.table("lesson_jobs").select("*").eq("lesson_id", lesson_id).single().execute()
        lesson_row: dict[str, Any] = result.data or {}

        user_id: str = lesson_row.get("user_id", "")
        chapter_content: str = lesson_row.get("extracted_text", "")  # pre-extracted or empty

        if not chapter_content and lesson_row.get("source_pdf_path"):
            # PDF not yet extracted — extract inline
            # TODO (Sprint 1): call PDF extraction utility
            chapter_content = ""
            logger.warning("lesson_id=%s has PDF path but no pre-extracted text — extraction TODO", lesson_id)

        # ── 3. Run LangGraph pipeline ─────────────────────────────────────────
        lesson_package = await run_pipeline(
            lesson_id=lesson_id,
            chapter_content=chapter_content,
            user_id=user_id,
        )

        # ── 4a. Persist final package ─────────────────────────────────────────
        supabase.table("lesson_jobs").update(
            {
                "status": "ready",
                "progress_pct": 100.0,
                "lesson_package": lesson_package,
            }
        ).eq("lesson_id", lesson_id).execute()

        # ── 4b. Notify client via WebSocket ───────────────────────────────────
        await manager.send(
            session_id=lesson_id,  # lesson_id doubles as the WS session for upload flow
            message={
                "type": "lesson_ready",
                "lesson_id": lesson_id,
                "title": lesson_package.get("lesson_plan", {}).get("title", ""),
            },
        )

        # ── 4c. Clear cost tracker ────────────────────────────────────────────
        await clear_lesson_cost(lesson_id)

        logger.info("content_pipeline_job COMPLETE lesson_id=%s", lesson_id)
        return {
            "lesson_id": lesson_id,
            "status": "ready",
            "package_summary": {
                "slides_count": len(lesson_package.get("slides", [])),
                "quiz_count": len(lesson_package.get("quiz_questions", [])),
                "audio_count": len(lesson_package.get("audio_assets", [])),
            },
        }

    except RuntimeError as exc:
        # RuntimeError includes cost ceiling exceeded — mark as specific status
        error_msg = str(exc)
        if "cost ceiling" in error_msg:
            await _update_lesson_status(supabase, lesson_id, "cost_limit_exceeded", error=error_msg)
            logger.warning("content_pipeline_job COST_LIMIT lesson_id=%s: %s", lesson_id, error_msg)
            return {"lesson_id": lesson_id, "status": "cost_limit_exceeded", "error": error_msg}

        await _update_lesson_status(supabase, lesson_id, "failed", error=error_msg)
        logger.exception("content_pipeline_job FAILED lesson_id=%s", lesson_id)
        raise  # Let ARQ retry

    except Exception as exc:
        error_msg = str(exc)
        await _update_lesson_status(supabase, lesson_id, "failed", error=error_msg)
        logger.exception("content_pipeline_job FAILED lesson_id=%s", lesson_id)
        raise  # Let ARQ retry


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _update_lesson_status(
    supabase: Any,
    lesson_id: str,
    status: str,
    error: str | None = None,
) -> None:
    """Update lesson_jobs.status (and optionally error) in Supabase."""
    try:
        payload: dict[str, Any] = {"status": status}
        if error:
            payload["error"] = error[:2000]  # Truncate to avoid DB column overflow

        supabase.table("lesson_jobs").update(payload).eq("lesson_id", lesson_id).execute()
    except Exception:  # noqa: BLE001
        logger.warning("Failed to update lesson status for lesson_id=%s status=%s", lesson_id, status)
