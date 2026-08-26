"""
Unit tests for Story 2-52 (S4-12): send_notification_email_job.

Covers: opt-out skip, the atomic idempotency claim (both outcomes — claimed
and already-claimed/sent), recipient resolution, and send-failure handling
(must never raise — a failed send must not crash the ARQ worker or retry the
flow that enqueued it).

The claim step itself (INSERT ... ON CONFLICT DO NOTHING against a real
UNIQUE constraint) is additionally proven under genuine concurrency by
tests/integration/test_migration_notification_log.py against a real
Postgres instance — a mock cannot disconfirm a race condition (DEFECT-
REGISTER binding rule 2), so these unit tests only prove this job's own
branching on the two possible outcomes of that claim.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

USER_ID = "uuuuuuuu-uuuu-uuuu-uuuu-uuuuuuuuuuuu"
LESSON_ID = "llllllll-llll-llll-llll-llllllllllll"
SESSION_ID = "ssssssss-ssss-ssss-ssss-ssssssssssss"


def make_supabase(
    *,
    pref_row: dict[str, Any] | None = None,
    claim_rows: list[dict[str, Any]] | None = None,
    user_row: dict[str, Any] | None = None,
    lesson_row: dict[str, Any] | None = None,
    session_row: dict[str, Any] | None = None,
) -> MagicMock:
    if claim_rows is None:
        claim_rows = [{"id": "log_1"}]

    def table_side_effect(name: str) -> MagicMock:
        m = MagicMock()
        if name == "user_notification_preferences":
            m.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = (
                MagicMock(data=pref_row)
            )
        elif name == "notification_log":
            m.upsert.return_value.execute.return_value = MagicMock(data=claim_rows)
        elif name == "users":
            m.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = (
                MagicMock(data=user_row)
            )
        elif name == "lessons":
            m.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = (
                MagicMock(data=lesson_row)
            )
        elif name == "sessions":
            m.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = (
                MagicMock(data=session_row)
            )
        return m

    sb = MagicMock()
    sb.table.side_effect = table_side_effect
    return sb


async def run_job(supabase: MagicMock, notification_type: str, resource_id: str) -> Any:
    from app.workers.jobs.send_notification_email import send_notification_email_job

    with patch("app.core.db.get_supabase", return_value=supabase):
        return await send_notification_email_job({}, USER_ID, notification_type, resource_id)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_opted_out_user_is_skipped_without_calling_the_provider() -> None:
    supabase = make_supabase(pref_row={"lesson_ready_email": False})

    with patch("app.providers.email.resend.ResendEmailProvider") as mock_provider_cls:
        result = await run_job(supabase, "lesson_ready", LESSON_ID)

    assert result == {"sent": False, "reason": "opted_out"}
    mock_provider_cls.return_value.send.assert_not_called()
    # The opt-out check must short-circuit before ever attempting the claim.
    assert "notification_log" not in [c.args[0] for c in supabase.table.call_args_list]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_preference_row_defaults_to_sending_not_opting_out() -> None:
    """A user who has never touched a toggle has no row yet — matches
    useNotificationPreferences.ts's own default-true convention, not an
    opt-out (only an explicit False is an opt-out)."""
    supabase = make_supabase(
        pref_row=None,
        claim_rows=[{"id": "log_1"}],
        user_row={"email": "student@example.com"},
        lesson_row={"title": "Intro to Thermodynamics"},
    )

    with patch("app.providers.email.resend.ResendEmailProvider") as mock_provider_cls:
        mock_provider_cls.return_value.send = AsyncMock(return_value="msg_1")
        result = await run_job(supabase, "lesson_ready", LESSON_ID)

    assert result == {"sent": True, "message_id": "msg_1"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_already_claimed_skips_send_without_calling_the_provider() -> None:
    """An empty claim response (ON CONFLICT DO NOTHING conflicted) means this
    exact (user, type, resource) was already sent or claimed by a concurrent
    invocation — must skip, not send a duplicate."""
    supabase = make_supabase(claim_rows=[])

    with patch("app.providers.email.resend.ResendEmailProvider") as mock_provider_cls:
        result = await run_job(supabase, "lesson_ready", LESSON_ID)

    assert result == {"sent": False, "reason": "already_sent"}
    mock_provider_cls.return_value.send.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_successful_claim_sends_lesson_ready_email() -> None:
    supabase = make_supabase(
        claim_rows=[{"id": "log_1"}],
        user_row={"email": "student@example.com"},
        lesson_row={"title": "Intro to Thermodynamics"},
    )

    with patch("app.providers.email.resend.ResendEmailProvider") as mock_provider_cls:
        mock_provider_cls.return_value.send = AsyncMock(return_value="msg_42")
        result = await run_job(supabase, "lesson_ready", LESSON_ID)

    assert result == {"sent": True, "message_id": "msg_42"}
    send_kwargs = mock_provider_cls.return_value.send.call_args.kwargs
    assert send_kwargs["to"] == "student@example.com"
    assert "Intro to Thermodynamics" in send_kwargs["html"]
    assert LESSON_ID in send_kwargs["html"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_successful_claim_sends_session_report_email_resolving_lesson_via_session() -> None:
    supabase = make_supabase(
        claim_rows=[{"id": "log_2"}],
        user_row={"email": "student@example.com"},
        session_row={"lesson_id": LESSON_ID},
        lesson_row={"title": "Intro to Thermodynamics"},
    )

    with patch("app.providers.email.resend.ResendEmailProvider") as mock_provider_cls:
        mock_provider_cls.return_value.send = AsyncMock(return_value="msg_43")
        result = await run_job(supabase, "session_report", SESSION_ID)

    assert result == {"sent": True, "message_id": "msg_43"}
    send_kwargs = mock_provider_cls.return_value.send.call_args.kwargs
    assert SESSION_ID in send_kwargs["html"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unresolvable_recipient_aborts_without_calling_the_provider() -> None:
    supabase = make_supabase(claim_rows=[{"id": "log_1"}], user_row=None)

    with patch("app.providers.email.resend.ResendEmailProvider") as mock_provider_cls:
        result = await run_job(supabase, "lesson_ready", LESSON_ID)

    assert result == {"sent": False, "reason": "recipient_unresolved"}
    mock_provider_cls.return_value.send.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_failure_is_caught_and_never_raised() -> None:
    """AC-4: a failed send must never crash the ARQ worker or propagate to
    retry the flow (pipeline/session-end) that enqueued this job — that flow
    already succeeded independently of whether this email goes out."""
    supabase = make_supabase(
        claim_rows=[{"id": "log_1"}],
        user_row={"email": "student@example.com"},
        lesson_row={"title": "Intro"},
    )

    with patch("app.providers.email.resend.ResendEmailProvider") as mock_provider_cls:
        mock_provider_cls.return_value.send = AsyncMock(side_effect=RuntimeError("boom"))
        result = await run_job(supabase, "lesson_ready", LESSON_ID)  # must not raise

    assert result == {"sent": False, "reason": "send_failed"}
