"""
Media module router.

Provides signed URL generation for Supabase Storage assets so the frontend
never needs the service-role key.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

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
    to prevent insecure direct object reference (IDOR).

    TODO (Sprint 1):
    1. Validate that bucket is in _ALLOWED_BUCKETS.
    2. Parse lesson_id from path prefix and verify ownership.
    3. Call supabase.storage.from_(bucket).create_signed_url(path, expires_in).
    """
    if bucket not in _ALLOWED_BUCKETS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Bucket '{bucket}' is not allowed. Valid buckets: {sorted(_ALLOWED_BUCKETS)}",
        )

    # TODO: ownership check + actual signing
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet")
