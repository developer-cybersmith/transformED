"""Session report email delivery stub — Story 4-8 (D60 guard).

D60 guard: `user_notification_preferences.session_report_email = false`
causes `send_session_report_email` to return without sending.

No email provider is in the locked technology stack as of Sprint 4.
The send path is stubbed — it logs a notice and returns.
When a provider is added (Sprint 5+), replace the stub log with the
actual send call. The preference guard here does not need to change.
"""

from __future__ import annotations

import logging
from typing import Any

from app.modules.assessment.notification_prefs import get_notification_preference

logger = logging.getLogger(__name__)

__all__ = ["send_session_report_email"]


async def send_session_report_email(
    *,
    user_id: str,
    session_id: str,
    supabase: Any,  # noqa: ANN401
) -> None:
    """Send a session report email — or skip if the user opted out (D60 guard).

    Calls `get_notification_preference` as its FIRST action. If the user has
    `session_report_email = false`, returns immediately. Otherwise proceeds to
    the send path (currently a stub — no provider configured).

    Args:
        user_id:    UUID of the authenticated user (from JWT sub claim).
        session_id: UUID of the completed session.
        supabase:   Supabase service-role client (synchronous v2).
    """
    should_send = await get_notification_preference(
        user_id=user_id,
        preference_key="session_report_email",
        supabase=supabase,
    )
    if not should_send:
        logger.info(
            "[session:%s user:%s] session report email skipped — user opted out",
            session_id,
            user_id,
        )
        return

    # Email provider not yet in the locked stack (CLAUDE.md Sprint 4).
    # Wire the real provider here when it lands; guard above stays unchanged.
    logger.info(
        "[session:%s user:%s] session report email: provider not configured — skipped",
        session_id,
        user_id,
    )
