"""
Content module router.

Handles PDF upload → lesson pipeline dispatch and lesson status/retrieval.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel
from slowapi.errors import RateLimitExceeded

from app.core.rate_limit import _get_user_key, limiter
from app.core.db import get_supabase
from app.dependencies import ArqRedis, CurrentUser

logger = logging.getLogger(__name__)

router = APIRouter(tags=["content"])

MAX_PDF_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


# ── Response models ───────────────────────────────────────────────────────────


class LessonUploadResponse(BaseModel):
    lesson_id: str
    job_id: str
    status: str  # "queued"


class LessonStatusResponse(BaseModel):
    lesson_id: str
    status: str  # queued | running | ready | failed
    title: str | None = None
    error: str | None = None
    created_at: str | None = None
    completed_at: str | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

_STATUS_MAP: dict[str, str] = {
    "generating": "running",
    "ready": "ready",
    "failed": "failed",
}


def _map_status(db_status: str) -> str:
    return _STATUS_MAP.get(db_status, "queued")


def _row_to_status_response(
    lesson: dict[str, Any],
    error: str | None = None,
) -> LessonStatusResponse:
    return LessonStatusResponse(
        lesson_id=str(lesson["lesson_id"]),
        status=_map_status(lesson.get("status", "generating")),
        title=lesson.get("title"),
        error=error,
        created_at=str(lesson["created_at"]) if lesson.get("created_at") else None,
        completed_at=None,
    )


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post(
    "/lessons",
    response_model=LessonUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a PDF and enqueue the content pipeline",
)
@limiter.limit("5/minute", key_func=_get_user_key)
async def upload_lesson(
    request: Request,
    current_user: CurrentUser,
    arq_redis: ArqRedis,
    file: UploadFile = File(..., description="PDF file to process (max 50 MB)"),
) -> LessonUploadResponse:
    """Accept a PDF upload, store it in Supabase Storage, enqueue ARQ job.

    Returns immediately with lesson_id + job_id; client polls GET /lessons/{id}.

    DB insert order: books → lessons → lesson_jobs (FK constraint order).
    PDF bytes are stored in Supabase Storage; extraction happens in the
    ARQ worker's extract_node in an isolated subprocess (CLAUDE.md §18).
    """
    user_id: str = current_user["sub"]
    supabase = get_supabase()

    # ── Size check (fast path before reading body) ────────────────────────────
    if file.size and file.size > MAX_PDF_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 50 MB limit")

    # ── Magic bytes: first 4 bytes must be %PDF ───────────────────────────────
    first_bytes = await file.read(4)
    await file.seek(0)
    if first_bytes != b"%PDF":
        raise HTTPException(status_code=422, detail="File is not a valid PDF")

    # ── MIME type check ───────────────────────────────────────────────────────
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=422, detail="Invalid content type — expected application/pdf")

    # ── Read full body ────────────────────────────────────────────────────────
    pdf_bytes = await file.read()
    if len(pdf_bytes) > MAX_PDF_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 50 MB limit")

    filename = file.filename or "upload.pdf"

    book_id: str | None = None
    lesson_id: str | None = None

    try:
        # ── 1. books row ──────────────────────────────────────────────────────
        books_resp = supabase.table("books").insert({
            "user_id": user_id,
            "filename": filename,
        }).execute()
        book_id = books_resp.data[0]["book_id"]

        # ── 2. lessons row ────────────────────────────────────────────────────
        lessons_resp = supabase.table("lessons").insert({
            "user_id": user_id,
            "book_id": book_id,
            "status": "generating",
        }).execute()
        lesson_id = lessons_resp.data[0]["lesson_id"]

        # ── 3. Storage upload ─────────────────────────────────────────────────
        storage_path = f"{user_id}/{book_id}/{filename}"
        supabase.storage.from_("source-pdfs").upload(
            path=storage_path,
            file=pdf_bytes,
            file_options={"content-type": "application/pdf"},
        )

        # ── 4. Write storage path back to lessons ─────────────────────────────
        supabase.table("lessons").update(
            {"source_file_path": storage_path}
        ).eq("lesson_id", lesson_id).execute()

        # ── 5. lesson_jobs row ────────────────────────────────────────────────
        supabase.table("lesson_jobs").insert({
            "lesson_id": lesson_id,
            "status": "pending",
        }).execute()

        # ── 6. Enqueue ARQ job ────────────────────────────────────────────────
        job = await arq_redis.enqueue_job("content_pipeline_job", lesson_id)
        if job is None:
            raise RuntimeError("ARQ returned None for enqueue_job — possible duplicate job key")
        job_id: str = job.job_id

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("upload_lesson failed for user_id=%s filename=%s", user_id, filename)
        if lesson_id:
            try:
                supabase.table("lesson_jobs").update({"status": "failed", "error": str(exc)[:2000]}).eq("lesson_id", lesson_id).execute()
                supabase.table("lessons").update({"status": "failed"}).eq("lesson_id", lesson_id).execute()
            except Exception:  # noqa: BLE001
                pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create lesson — please retry",
        ) from exc

    return LessonUploadResponse(lesson_id=lesson_id, job_id=job_id, status="queued")


@router.get(
    "/lessons/{lesson_id}",
    response_model=LessonStatusResponse,
    summary="Get the status and metadata of a lesson",
)
async def get_lesson(
    lesson_id: str,
    current_user: CurrentUser,
) -> LessonStatusResponse:
    """Return current status of a lesson.

    Returns 404 if not found or user does not own the lesson.
    """
    user_id: str = current_user["sub"]
    supabase = get_supabase()

    lesson_resp = supabase.table("lessons").select("*").eq("lesson_id", lesson_id).maybe_single().execute()
    lesson: dict[str, Any] | None = lesson_resp.data

    if not lesson or lesson.get("user_id") != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found")

    # Fetch error from lesson_jobs if present
    error: str | None = None
    if lesson.get("status") == "failed":
        jobs_resp = supabase.table("lesson_jobs").select("error").eq("lesson_id", lesson_id).order("created_at", desc=True).limit(1).execute()
        if jobs_resp.data:
            error = jobs_resp.data[0].get("error")

    return _row_to_status_response(lesson, error=error)


@router.get(
    "/lessons",
    response_model=list[LessonStatusResponse],
    summary="List all lessons for the current user",
)
async def list_lessons(
    current_user: CurrentUser,
    limit: int = 20,
    offset: int = 0,
) -> list[LessonStatusResponse]:
    """Return paginated lessons for the authenticated user, newest first."""
    user_id: str = current_user["sub"]
    supabase = get_supabase()

    resp = (
        supabase.table("lessons")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    rows: list[dict[str, Any]] = resp.data or []
    return [_row_to_status_response(row) for row in rows]
