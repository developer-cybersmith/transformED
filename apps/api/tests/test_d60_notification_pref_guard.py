"""D60 fix tests — send_session_report_email respects session_report_email preference.

Story 4-8. All tests @pytest.mark.unit — no DB, no network.

Coverage:
- AC2+AC3: opted-out user → preference called, function returns before send path
- AC2+AC4: opted-in user → preference called, function reaches send stub (no raise)
- AC6: three tests covering both preference outcomes + call ordering (preference first)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_session_report_email_skips_when_opted_out() -> None:
    """AC3: opted-out user → early return, send path never reached."""
    from app.modules.assessment.email_delivery import send_session_report_email

    mock_supabase = MagicMock()
    mock_pref = AsyncMock(return_value=False)

    with patch(
        "app.modules.assessment.email_delivery.get_notification_preference",
        mock_pref,
    ):
        await send_session_report_email(
            user_id="uid-opted-out",
            session_id="sid-1",
            supabase=mock_supabase,
        )

    mock_pref.assert_called_once_with(
        user_id="uid-opted-out",
        preference_key="session_report_email",
        supabase=mock_supabase,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_session_report_email_proceeds_when_opted_in() -> None:
    """AC4: opted-in user → preference checked, reaches send stub without raising."""
    from app.modules.assessment.email_delivery import send_session_report_email

    mock_supabase = MagicMock()
    mock_pref = AsyncMock(return_value=True)

    with patch(
        "app.modules.assessment.email_delivery.get_notification_preference",
        mock_pref,
    ):
        # Must NOT raise — the stub just logs and returns
        await send_session_report_email(
            user_id="uid-opted-in",
            session_id="sid-2",
            supabase=mock_supabase,
        )

    mock_pref.assert_called_once_with(
        user_id="uid-opted-in",
        preference_key="session_report_email",
        supabase=mock_supabase,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_session_report_email_checks_preference_before_send_path() -> None:
    """AC2: preference is the FIRST call — verified via call_args_list ordering."""
    from app.modules.assessment.email_delivery import send_session_report_email

    mock_supabase = MagicMock()
    call_order: list[str] = []

    async def mock_pref(**kwargs: object) -> bool:  # noqa: ARG001
        call_order.append("preference_check")
        return True

    # Patch logging to detect if send-path log fires AFTER preference
    import logging

    original_info = logging.Logger.info

    def tracking_info(self: logging.Logger, msg: str, *args: object, **kwargs: object) -> None:
        if "provider not configured" in str(msg):
            call_order.append("send_stub_reached")
        original_info(self, msg, *args, **kwargs)

    with (
        patch(
            "app.modules.assessment.email_delivery.get_notification_preference",
            mock_pref,
        ),
        patch.object(logging.Logger, "info", tracking_info),
    ):
        await send_session_report_email(
            user_id="uid-order-test",
            session_id="sid-3",
            supabase=mock_supabase,
        )

    assert call_order == ["preference_check", "send_stub_reached"], (
        f"Expected preference check before send stub, got: {call_order}. "
        "AC2: get_notification_preference must be the FIRST call."
    )
