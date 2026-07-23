"""
Media module router.

Provides signed URL generation for Supabase Storage assets so the frontend
never needs the service-role key.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.core.db import get_supabase, single_row
from app.core.storage import sign_storage_path
from app.dependencies import CurrentUser

router = APIRouter(tags=["media"])

# Allowed buckets (allowlist — never let callers specify arbitrary bucket names)
_ALLOWED_BUCKETS: frozenset[str] = frozenset(
    {
        "source-pdfs",
        "lesson-slides",
        "lesson-audio",
        "lesson-images",
        "avatar-clips",
    }
)


class SignedUrlResponse(BaseModel):
    signed_url: str
    expires_in: int  # seconds


def _parse_lesson_id(path: str) -> str | None:
    """Extract and validate the `{lesson_id}/...` prefix of a storage path.

    Returns None (caller 404s) on any malformed input — no `/` separator,
    empty prefix, or a prefix that isn't a valid UUID. Never raises.
    """
    prefix = path.split("/", 1)[0] if "/" in path else ""
    if not prefix:
        return None
    try:
        uuid.UUID(prefix)
    except ValueError:
        return None
    return prefix


@router.get(
    "/signed-url",
    response_model=SignedUrlResponse,
    summary="Generate a signed URL for a Supabase Storage asset",
)
async def get_signed_url(
    current_user: CurrentUser,
    bucket: str = Query(..., description="Storage bucket name"),
    path: str = Query(..., description="Object path within the bucket"),
    expires_in: int = Query(default=3600, ge=60, le=86400, description="Expiry in seconds"),
) -> SignedUrlResponse:
    """Return a time-limited signed URL for a storage object.

    Validates that the caller owns the referenced lesson before signing
    to prevent insecure direct object reference (IDOR). Mirrors the
    ownership-check pattern in `content/router.py:get_lesson` — a
    nonexistent lesson and an unowned lesson return the identical 404,
    never distinguishing which (would leak existence to a non-owner).
    """
    if bucket not in _ALLOWED_BUCKETS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Bucket '{bucket}' is not allowed. Valid buckets: {sorted(_ALLOWED_BUCKETS)}",
        )

    lesson_id = _parse_lesson_id(path)
    if lesson_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found")

    supabase = get_supabase()
    lesson_resp = (
        supabase.table("lessons")
        .select("user_id")
        .eq("lesson_id", lesson_id)
        .maybe_single()
        .execute()
    )
    lesson = single_row(lesson_resp)
    user_id: str = current_user["sub"]
    if not lesson or lesson.get("user_id") != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found")

    signed_url = sign_storage_path(supabase, bucket, path, expires_in)
    if signed_url is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Storage object not found"
        )

    return SignedUrlResponse(signed_url=signed_url, expires_in=expires_in)
