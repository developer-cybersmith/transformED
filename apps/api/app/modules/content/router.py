"""
Content module router.

Handles PDF upload → lesson pipeline dispatch and lesson status/retrieval.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.dependencies import CurrentUser

router = APIRouter(tags=["content"])


# ── Response models ───────────────────────────────────────────────────────────


class LessonUploadResponse(BaseModel):
    lesson_id: str
    status: str  # "queued"


class LessonStatusResponse(BaseModel):
    lesson_id: str
    status: str  # queued | running | ready | failed | cost_limit_exceeded
    title: str | None = None
    progress_pct: float | None = None
    error: str | None = None
    created_at: str | None = None
    completed_at: str | None = None


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post(
    "/lessons",
    response_model=LessonUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a PDF and enqueue the content pipeline",
)
async def upload_lesson(
    current_user: CurrentUser,
    file: UploadFile = File(..., description="PDF file to process (max 50 MB)"),
) -> LessonUploadResponse:
    """Accept a PDF upload, store it in Supabase Storage, enqueue ARQ job.

    Returns immediately with a ``lesson_id`` that the client can poll.

    TODO (Sprint 1):
    1. Validate file size / MIME type.
    2. Upload PDF to Supabase Storage (``source-pdfs`` bucket).
    3. Insert row into ``lesson_jobs`` table (status=queued).
    4. Enqueue ``content_pipeline_job`` via ARQ.
    """
    lesson_id = str(uuid.uuid4())

    # TODO: implement storage upload + ARQ enqueue
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet")


@router.get(
    "/lessons/{lesson_id}",
    response_model=LessonStatusResponse,
    summary="Get the status and metadata of a lesson pipeline run",
)
async def get_lesson(
    lesson_id: str,
    current_user: CurrentUser,
) -> LessonStatusResponse:
    """Return the current status of a lesson (polls lesson_jobs table).

    TODO (Sprint 1): Query lesson_jobs table via Supabase.
    """
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet")


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
    """Return paginated lessons for the authenticated user.

    TODO (Sprint 1): Query lesson_jobs filtered by user_id.
    """
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet")
