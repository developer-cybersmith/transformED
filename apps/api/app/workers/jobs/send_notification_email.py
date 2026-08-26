"""
ARQ job: send_notification_email_job (Story 2-52 / S4-12)

Sends a transactional email for a lesson-ready or session-report event, if
the student's preference allows it and it has not already been sent.

Idempotency (Scale & Load Q6): claims the send via
`INSERT ... ON CONFLICT (user_id, notification_type, resource_id) DO NOTHING
RETURNING id` (Supabase `upsert(..., ignore_duplicates=True)`) against
notification_log's UNIQUE constraint. This is an atomic claim-before-send,
NOT a SELECT-then-INSERT check — that exact shape is D45 (a check-then-act
race with no UNIQUE constraint backing it, letting concurrent duplicates
both bill). Only the caller that gets a row back proceeds to send.

Celery is BANNED per PRD §24 — this job uses ARQ exclusively.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

logger = logging.getLogger(__name__)

NotificationType = Literal["lesson_ready", "session_report"]

_PREFERENCE_COLUMN: dict[str, str] = {
    "lesson_ready": "lesson_ready_email",
    "session_report": "session_report_email",
}


async def send_notification_email_job(
    ctx: dict[str, Any],
    user_id: str,
    notification_type: NotificationType,
    resource_id: str,
) -> dict[str, Any]:
    """Send a notification email, if opted-in and not already sent.

    Args:
        ctx:                ARQ worker context dict (unused here — no shared
                             resource from on_startup is needed, unlike
                             content_pipeline_job).
        user_id:            Recipient's user UUID.
        notification_type:  ``"lesson_ready"`` or ``"session_report"``.
        resource_id:        The lesson_id (lesson_ready) or session_id
                             (session_report) this notification is about.

    Returns:
        ``{"sent": bool, "reason": str}`` on skip, or
        ``{"sent": True, "message_id": str}`` on success. Never raises —
        a failure to send must not block or retry the flow that enqueued
        this job (AC-4).
    """
    from app.core.db import get_supabase, single_row

    supabase = get_supabase()

    # ── 1. Preference check ───────────────────────────────────────────────
    pref_column = _PREFERENCE_COLUMN[notification_type]
    pref_resp = await asyncio.to_thread(
        lambda: (
            supabase.table("user_notification_preferences")
            .select(pref_column)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
    )
    pref_row = single_row(pref_resp)
    # No row = a user who has never touched a toggle -- matches
    # useNotificationPreferences.ts's own default-true convention, not an
    # opt-out. A row present with the column explicitly false IS a real
    # opt-out.
    if pref_row is not None and pref_row.get(pref_column) is False:
        logger.info(
            "send_notification_email_job SKIP (opted out) user=%s type=%s resource=%s",
            user_id,
            notification_type,
            resource_id,
        )
        return {"sent": False, "reason": "opted_out"}

    # ── 2. Atomic idempotency claim ───────────────────────────────────────
    claim_resp = await asyncio.to_thread(
        lambda: (
            supabase.table("notification_log")
            .upsert(
                {
                    "user_id": user_id,
                    "notification_type": notification_type,
                    "resource_id": resource_id,
                },
                on_conflict="user_id,notification_type,resource_id",
                ignore_duplicates=True,
            )
            .execute()
        )
    )
    if not (claim_resp.data or []):
        logger.info(
            "send_notification_email_job SKIP (already sent/claimed) user=%s type=%s resource=%s",
            user_id,
            notification_type,
            resource_id,
        )
        return {"sent": False, "reason": "already_sent"}

    # ── 3. Resolve recipient + render content ─────────────────────────────
    to_email, subject, html = await _build_email(supabase, notification_type, resource_id, user_id)
    if to_email is None:
        logger.warning(
            "send_notification_email_job ABORT (could not resolve recipient) "
            "user=%s type=%s resource=%s",
            user_id,
            notification_type,
            resource_id,
        )
        return {"sent": False, "reason": "recipient_unresolved"}

    # ── 4. Send ────────────────────────────────────────────────────────────
    from app.providers.email.resend import ResendEmailProvider

    provider = ResendEmailProvider()
    try:
        message_id = await provider.send(to=to_email, subject=subject, html=html)
    except Exception as exc:
        # AC-4: never crash the worker or block the flow that enqueued this
        # job -- that flow (pipeline completion / session end) already
        # succeeded independently. Logged loudly, never silently swallowed,
        # and captured to Sentry when available (best-effort — a Sentry
        # failure here must not mask the original send failure already
        # logged above).
        logger.error(
            "send_notification_email_job SEND FAILED user=%s type=%s resource=%s: %s",
            user_id,
            notification_type,
            resource_id,
            exc,
        )
        try:
            import sentry_sdk

            sentry_sdk.capture_exception(exc)
        except Exception:
            logger.debug("sentry_sdk.capture_exception failed", exc_info=True)
        return {"sent": False, "reason": "send_failed"}

    logger.info(
        "send_notification_email_job SENT user=%s type=%s resource=%s message_id=%s",
        user_id,
        notification_type,
        resource_id,
        message_id,
    )
    return {"sent": True, "message_id": message_id}


async def _build_email(
    supabase: Any,  # noqa: ANN401
    notification_type: NotificationType,
    resource_id: str,
    user_id: str,
) -> tuple[str | None, str, str]:
    """Resolve the recipient address and render the (subject, html) body.

    Returns:
        ``(None, "", "")`` if the recipient's email could not be resolved.
    """
    from app.config import get_settings
    from app.core.db import single_row
    from app.modules.notifications.templates import (
        render_lesson_ready_email,
        render_session_report_email,
    )

    settings = get_settings()

    user_resp = await asyncio.to_thread(
        lambda: (
            supabase.table("users").select("email").eq("id", user_id).maybe_single().execute()
        )
    )
    user_row = single_row(user_resp)
    to_email = (user_row or {}).get("email")
    if not to_email:
        return None, "", ""

    if notification_type == "lesson_ready":
        lesson_row = await _fetch_lesson_title(supabase, resource_id)
        title = lesson_row or "Your lesson"
        url = f"{settings.frontend_url}/lesson/{resource_id}"
        subject, html = render_lesson_ready_email(lesson_title=title, lesson_url=url)
        return to_email, subject, html

    # notification_type == "session_report"
    session_resp = await asyncio.to_thread(
        lambda: (
            supabase.table("sessions")
            .select("lesson_id")
            .eq("session_id", resource_id)
            .maybe_single()
            .execute()
        )
    )
    session_row = single_row(session_resp)
    lesson_id = (session_row or {}).get("lesson_id")
    title = "Your lesson"
    if lesson_id:
        title = await _fetch_lesson_title(supabase, lesson_id) or title
    url = f"{settings.frontend_url}/reports/{resource_id}"
    subject, html = render_session_report_email(lesson_title=title, report_url=url)
    return to_email, subject, html


async def _fetch_lesson_title(supabase: Any, lesson_id: str) -> str | None:  # noqa: ANN401
    from app.core.db import single_row

    resp = await asyncio.to_thread(
        lambda: (
            supabase.table("lessons")
            .select("title")
            .eq("lesson_id", lesson_id)
            .maybe_single()
            .execute()
        )
    )
    row = single_row(resp)
    return (row or {}).get("title")
