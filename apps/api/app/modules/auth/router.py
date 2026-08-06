"""
Auth module router.

Handles user sign-up, sign-in, profile retrieval, onboarding completion,
and notification preference management.
JWT verification is always done locally via PyJWT — no remote auth calls.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, model_validator

from app.dependencies import CurrentUser

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])

# ── Notification preference constants ─────────────────────────────────────────

_NOTIF_TABLE = "user_notification_preferences"

# Table defaults — all opt-in. Used when a user has no existing row.
# Mirrors the migration DEFAULT clauses in 20260806000000_user_notification_preferences.sql
_NOTIF_DEFAULTS: dict[str, bool] = {
    "session_report_email": True,
    "lesson_ready_email": True,
    "weekly_progress_email": True,
    "streak_reminders": True,
}


# ── Request / Response models ─────────────────────────────────────────────────


class SignUpRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str


class SignInRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105
    user: dict[str, Any]


class OnboardingRequest(BaseModel):
    grade_level: str
    subjects: list[str]
    learning_style: str | None = None
    goals: list[str] = []


class NotificationPatchRequest(BaseModel):
    """Request body for PATCH /api/auth/notifications.

    All four preference fields are optional — at least one must be supplied.
    Extra fields (e.g. ``user_id``) are **rejected** with 422 (``extra='forbid'``);
    the handler always derives user_id from the JWT sub claim.

    Scale: bounded to 4 optional booleans; no variable-size input.
    """

    model_config = ConfigDict(extra="forbid")

    session_report_email: bool | None = None
    lesson_ready_email: bool | None = None
    weekly_progress_email: bool | None = None
    streak_reminders: bool | None = None

    @model_validator(mode="after")
    def at_least_one_field_required(self) -> NotificationPatchRequest:
        """Reject empty PATCH bodies — there is nothing to update."""
        if all(
            v is None
            for v in (
                self.session_report_email,
                self.lesson_ready_email,
                self.weekly_progress_email,
                self.streak_reminders,
            )
        ):
            raise ValueError("At least one notification preference field must be provided")
        return self


class NotificationPreferencesResponse(BaseModel):
    """Response shape for PATCH /api/auth/notifications.

    Returns the full row after the upsert so the client has a consistent view.
    """

    user_id: str
    session_report_email: bool
    lesson_ready_email: bool
    weekly_progress_email: bool
    streak_reminders: bool
    updated_at: str


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post(
    "/signup",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
async def signup(
    body: SignUpRequest,
) -> AuthResponse:
    """Create a new user via Supabase Auth.

    TODO (Sprint 1): Delegate to auth service layer.
    """
    # TODO: call supabase.auth.sign_up(email=body.email, password=body.password)
    # TODO: create profile row in public.profiles
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet")


@router.post(
    "/signin",
    response_model=AuthResponse,
    summary="Sign in with email and password",
)
async def signin(
    body: SignInRequest,
) -> AuthResponse:
    """Exchange credentials for a Supabase JWT.

    TODO (Sprint 1): Delegate to auth service layer.
    """
    # TODO: call supabase.auth.sign_in_with_password(...)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet")


@router.get(
    "/me",
    summary="Get the current user's profile",
)
async def get_me(
    current_user: CurrentUser,
) -> dict[str, Any]:
    """Return the authenticated user's profile data.

    The JWT payload is verified locally — no remote call.
    """
    return {
        "id": current_user.get("sub"),
        "email": current_user.get("email"),
        "role": current_user.get("role"),
        "app_metadata": current_user.get("app_metadata", {}),
        "user_metadata": current_user.get("user_metadata", {}),
    }


@router.post(
    "/onboarding/complete",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mark onboarding as complete and save preferences",
)
async def complete_onboarding(
    current_user: CurrentUser,
    body: OnboardingRequest,
) -> None:
    """Persist the user's onboarding answers and set onboarding_complete=true.

    TODO (Sprint 1): Delegate to profile service layer.
    """
    # TODO: update profiles set onboarding_complete = true, preferences = body
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet")


@router.patch(
    "/notifications",
    response_model=NotificationPreferencesResponse,
    summary="Update notification preferences",
)
async def patch_notifications(
    body: NotificationPatchRequest,
    current_user: CurrentUser,
) -> NotificationPreferencesResponse:
    """Update the authenticated user's notification preferences.

    Implements a read-merge-upsert pattern for correct partial-update semantics:
    1. Read the existing row (or use table defaults when no row exists yet).
       Read failure → 503 (never fail-open: merging defaults over stored prefs corrupts data).
    2. Merge only the fields provided in the request body.
    3. Upsert the full merged row (PRIMARY KEY user_notification_preferences.user_id).
    4. Return the updated row.

    Security: ``user_id`` is always taken from the JWT ``sub`` claim — never from
    the request body.

    Scale (docs/SCALE-CONTRACT.md):
    - Unit of work: one read (≤1 row via .maybe_single()) + one upsert (1 row).
    - Input is bounded at the Pydantic schema layer (4 optional bools).
    - Per-user isolation: user_id from JWT gates both SELECT and upsert.
    - Read query uses .maybe_single() — satisfies test_unbounded_queries.py.
    - TOCTOU: last-writer-wins on concurrent PATCHes; acceptable for preferences.
    """
    from app.core.db import get_supabase  # lazy — prevents circular import at module load

    supabase = get_supabase()
    user_id: str = str(current_user["sub"])

    # ── Step 1: Read existing preferences (fail-open to defaults on any DB error) ──
    try:
        read_resp = await asyncio.to_thread(
            lambda: (
                supabase.table(_NOTIF_TABLE)
                .select(
                    "session_report_email,lesson_ready_email,weekly_progress_email,streak_reminders"
                )
                .eq("user_id", user_id)
                .maybe_single()  # BOUNDED: PRIMARY KEY ensures ≤1 row per user
                .execute()
            )
        )
        current_prefs: dict[str, bool] = (
            dict(read_resp.data) if read_resp.data else dict(_NOTIF_DEFAULTS)
        )
    except Exception as exc:  # noqa: BLE001
        # Do NOT fall back to defaults here — merging defaults over the user's stored
        # non-default preferences would silently corrupt their data.  Return 503 so
        # the caller can retry once the DB is healthy.
        logger.error(
            "notifications: read failed for user=%s: %s",
            user_id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Notification preferences temporarily unavailable — please retry",
        ) from exc

    # ── Step 2: Merge — only override fields explicitly provided in the request ──
    patch_fields = body.model_dump(exclude_none=True)
    merged: dict[str, Any] = {
        **current_prefs,
        **patch_fields,
        "user_id": user_id,
        "updated_at": datetime.now(UTC).isoformat(),
    }

    # ── Step 3: Upsert the merged row ──────────────────────────────────────────
    try:
        upsert_resp = await asyncio.to_thread(
            lambda: supabase.table(_NOTIF_TABLE).upsert(merged, on_conflict="user_id").execute()
        )
    except Exception as exc:
        logger.error(
            "notifications: upsert failed for user=%s: %s",
            user_id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update notification preferences",
        ) from exc

    # Guard: upsert may have committed but returned no RETURNING rows (client config or
    # version difference).  Raise distinctly so the caller knows the write succeeded but
    # the read-back failed — avoids IndexError and misleading "Failed to update" message.
    if not upsert_resp.data:
        logger.error(
            "notifications: upsert returned empty response for user=%s — "
            "row was likely written; client configuration may suppress RETURNING",
            user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve updated notification preferences",
        )
    row = upsert_resp.data[0]

    # timestamptz is returned as a datetime object by supabase-py; use .isoformat() to
    # produce a T-separated ISO 8601 string rather than the space-separated str() default.
    updated_at_raw = row["updated_at"]
    updated_at_str = (
        updated_at_raw.isoformat() if hasattr(updated_at_raw, "isoformat") else str(updated_at_raw)
    )

    return NotificationPreferencesResponse(
        user_id=str(row["user_id"]),
        session_report_email=bool(row["session_report_email"]),
        lesson_ready_email=bool(row["lesson_ready_email"]),
        weekly_progress_email=bool(row["weekly_progress_email"]),
        streak_reminders=bool(row["streak_reminders"]),
        updated_at=updated_at_str,
    )
