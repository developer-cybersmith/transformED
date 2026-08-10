"""Notification preference read-helper — Story 3-33 (S3-07 Dev 3 contribution).

Reads a single boolean notification preference for a user from the
``user_notification_preferences`` table (created by a future Dev 1 / Dev 4 migration).

Fails open: returns True on any DB error, missing table, missing row, or NULL value.
Existing users have no preference row yet, so the default opt-in is intentional —
they signed up to receive updates and have not yet opted out.

This module makes zero LLM calls and makes no writes. It is safe to call from any
async context in the assessment module.

Future consumers:
    - Session report email delivery (assessment module, future sprint)
    - Any other Dev 3 path that needs to check a notification toggle before acting

What this module does NOT do:
    - Create or migrate the user_notification_preferences table (Dev 1 responsibility)
    - Implement PATCH /api/users/notifications (Dev 4 responsibility)
    - Send emails (no email provider in the locked stack — future scope)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["get_notification_preference"]

_TABLE = "user_notification_preferences"


async def get_notification_preference(
    *,
    user_id: str,
    preference_key: str,
    supabase: Any,  # noqa: ANN401
) -> bool:
    """Read a single boolean notification preference for the user.

    Queries ``user_notification_preferences`` by ``user_id`` and returns the
    value of ``preference_key``.  Fails open on any error, missing row, or NULL
    so that existing users continue to receive notifications until they opt out.

    SECURITY NOTE: ``user_id`` must come from the JWT-decoded subject (caller's
    responsibility).  The service-role Supabase client bypasses RLS; the
    ``.eq("user_id", user_id)`` filter is the only access gate in this function.

    Args:
        user_id:        UUID of the authenticated user (from JWT sub claim).
        preference_key: Column name in user_notification_preferences to read
                        (e.g. ``"session_report_email"``).
        supabase:       Synchronous supabase-py v2 client (service-role key).

    Returns:
        The stored boolean value, or ``True`` if the table / row / column is
        absent or any error occurs (fail-open default opt-in).
    """
    try:
        resp = await asyncio.to_thread(
            lambda: (
                supabase.table(_TABLE)
                .select(preference_key)
                .eq("user_id", user_id)
                .maybe_single()
                .execute()
            )
        )
        row = resp.data
        if row is None:
            # No row for this user — default opt-in
            return True
        value = row.get(preference_key)
        if value is None:
            # Row exists but column is NULL — default opt-in
            return True
        return bool(value)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "notification_prefs: preference read failed user=%s key=%s: %s",
            user_id,
            preference_key,
            exc,
        )
        return True  # fail-open: never suppress notifications on infrastructure error
