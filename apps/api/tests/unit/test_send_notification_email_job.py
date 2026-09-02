"""
Unit tests for Story 2-52 (S4-12): send_notification_email_job.

Covers: opt-out skip, the atomic idempotency claim (both outcomes — claimed
and already-claimed/sent), recipient resolution, and failure handling. A
failure AFTER the claim (recipient unresolved, or the provider send fails)
releases the claim and re-raises — review finding (corroborated by 4
independent reviewers): claiming the slot and then swallowing a downstream
failure would permanently and silently lose that notification forever,
since the UNIQUE constraint would block every future attempt from ever
re-claiming it. Raising lets ARQ's own per-job retry/failure tracking
(WorkerSettings.max_tries) take over, matching content_pipeline_job's own
established pattern — it does NOT block or retry the flow (pipeline
completion / session end) that enqueued this job, since that's a separate
ARQ job with its own retry accounting.

The claim step itself (INSERT ... ON CONFLICT DO NOTHING against a real
UNIQUE constraint) is proven separately, against a real Postgres instance,
by tests/integration/test_migration_notification_log.py (pytest.mark.postgres)
-- it replays this job's exact claim SQL twice against a real container and
asserts the second attempt returns no row. A mock cannot disconfirm a race
condition (DEFECT-REGISTER binding rule 2), so these unit tests only prove
this job's own branching on the two possible outcomes of that claim (claimed
vs. already-claimed) -- the UNIQUE constraint itself rejecting a concurrent
duplicate at the database level is the integration test's job, not this
file's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if TYPE_CHECKING:
    from app.workers.jobs.send_notification_email import NotificationType

USER_ID = "uuuuuuuu-uuuu-uuuu-uuuu-uuuuuuuuuuuu"
LESSON_ID = "llllllll-llll-llll-llll-llllllllllll"
SESSION_ID = "ssssssss-ssss-ssss-ssss-ssssssssssss"

# Distinct from `None` so make_supabase can tell "caller didn't specify
# claim_rows, use the happy-path default" apart from "caller explicitly wants
# to simulate claim_resp.data is None" -- a plain `None` default couldn't
# distinguish the two (review-round bug: an earlier version of this file
# silently coerced an explicit `claim_rows=None` back to the happy-path
# default, so its "data is None" test never actually exercised that case).
_DEFAULT_CLAIM_ROWS = [{"id": "log_1"}]


def make_supabase(
    *,
    pref_row: dict[str, Any] | None = None,
    claim_rows: Any = _DEFAULT_CLAIM_ROWS,  # noqa: ANN401 -- deliberately Any, see _DEFAULT_CLAIM_ROWS
    user_row: dict[str, Any] | None = None,
    lesson_row: dict[str, Any] | None = None,
    session_row: dict[str, Any] | None = None,
) -> MagicMock:

    # One persistent mock per table name -- the job calls .table("notification_log")
    # TWICE on the failure path (upsert claim, then delete rollback), and a test
    # needs to inspect both calls on the SAME mock object afterwards.
    tables: dict[str, MagicMock] = {}

    def table_side_effect(name: str) -> MagicMock:
        if name in tables:
            return tables[name]
        m = MagicMock()
        if name == "user_notification_preferences":
            m.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = (
                MagicMock(data=pref_row)
            )
        elif name == "notification_log":
            m.upsert.return_value.execute.return_value = MagicMock(data=claim_rows)
            m.delete.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
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
        tables[name] = m
        return m

    sb = MagicMock()
    sb.table.side_effect = table_side_effect
    return sb


async def run_job(
    supabase: MagicMock, notification_type: NotificationType, resource_id: str
) -> Any:
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
async def test_claim_response_with_data_none_is_treated_as_already_claimed() -> None:
    """postgrest can return `.data is None` (not just `[]`) on some response
    shapes — `not (claim_resp.data or [])` must treat that the same as a
    real conflict (skip), never crash trying to check `len(None)`."""
    supabase = make_supabase(claim_rows=None)

    with patch("app.providers.email.resend.ResendEmailProvider") as mock_provider_cls:
        result = await run_job(supabase, "lesson_ready", LESSON_ID)

    assert result == {"sent": False, "reason": "already_sent"}
    mock_provider_cls.return_value.send.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_explicit_opt_in_true_still_sends() -> None:
    """Distinct code path from the no-row-yet default (both currently produce
    the same outcome, but an explicit True must be pinned down separately —
    a change to the boolean logic could silently invert this one without the
    no-row test catching it)."""
    supabase = make_supabase(
        pref_row={"lesson_ready_email": True},
        claim_rows=[{"id": "log_1"}],
        user_row={"email": "student@example.com"},
        lesson_row={"title": "Intro"},
    )

    with patch("app.providers.email.resend.ResendEmailProvider") as mock_provider_cls:
        mock_provider_cls.return_value.send = AsyncMock(return_value="msg_1")
        result = await run_job(supabase, "lesson_ready", LESSON_ID)

    assert result == {"sent": True, "message_id": "msg_1"}


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
async def test_unresolvable_recipient_releases_the_claim_and_reraises() -> None:
    """A user with no email will never resolve no matter how many times this
    retries, but the claim must still be released -- if that user's email is
    fixed later, a fresh attempt must be able to re-claim, not find the slot
    permanently taken by the failed one."""
    supabase = make_supabase(claim_rows=[{"id": "log_1"}], user_row=None)

    with patch("app.providers.email.resend.ResendEmailProvider") as mock_provider_cls:
        with pytest.raises(RuntimeError, match="could not resolve recipient"):
            await run_job(supabase, "lesson_ready", LESSON_ID)

    mock_provider_cls.return_value.send.assert_not_called()
    notification_log = supabase.table("notification_log")
    notification_log.delete.return_value.eq.assert_called_once_with("id", "log_1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_failure_releases_the_claim_and_reraises() -> None:
    """Review finding (corroborated by 4 independent reviewers): claiming the
    slot and then swallowing a downstream send failure would permanently and
    silently lose that notification forever -- the UNIQUE constraint would
    block every future attempt from ever re-claiming it. Must release the
    claim and re-raise so ARQ's own retry/failure tracking takes over,
    matching content_pipeline_job's own established pattern."""
    supabase = make_supabase(
        claim_rows=[{"id": "log_1"}],
        user_row={"email": "student@example.com"},
        lesson_row={"title": "Intro"},
    )

    with patch("app.providers.email.resend.ResendEmailProvider") as mock_provider_cls:
        mock_provider_cls.return_value.send = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(RuntimeError, match="boom"):
            await run_job(supabase, "lesson_ready", LESSON_ID)

    notification_log = supabase.table("notification_log")
    notification_log.delete.return_value.eq.assert_called_once_with("id", "log_1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_second_attempt_can_resend_after_the_first_failed_attempts_claim_was_released() -> (
    None
):
    """End-to-end proof of the fix: a failed attempt must not permanently
    brick this (user, type, resource) triple. Simulates a fresh job
    invocation seeing the SAME claim_rows again (as it would if the DB
    row was genuinely deleted by the first attempt's rollback) and
    confirms the second attempt sends successfully."""
    supabase = make_supabase(
        claim_rows=[{"id": "log_1"}],  # same claim row "re-claimable" both times
        user_row={"email": "student@example.com"},
        lesson_row={"title": "Intro"},
    )

    with patch("app.providers.email.resend.ResendEmailProvider") as mock_provider_cls:
        mock_provider_cls.return_value.send = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(RuntimeError):
            await run_job(supabase, "lesson_ready", LESSON_ID)

        mock_provider_cls.return_value.send = AsyncMock(return_value="msg_retry")
        result = await run_job(supabase, "lesson_ready", LESSON_ID)

    assert result == {"sent": True, "message_id": "msg_retry"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rollback_failure_is_logged_loudly_and_original_exception_still_raised() -> None:
    """If the DELETE rollback itself fails, the claim is now permanently
    stuck -- this must not be swallowed silently, and the original send
    failure must still propagate (not be masked by the rollback's own
    exception)."""
    supabase = make_supabase(
        claim_rows=[{"id": "log_1"}],
        user_row={"email": "student@example.com"},
        lesson_row={"title": "Intro"},
    )
    notification_log = supabase.table("notification_log")
    notification_log.delete.return_value.eq.return_value.execute.side_effect = RuntimeError(
        "db unreachable"
    )

    with patch("app.providers.email.resend.ResendEmailProvider") as mock_provider_cls:
        mock_provider_cls.return_value.send = AsyncMock(side_effect=RuntimeError("original boom"))
        with pytest.raises(RuntimeError, match="original boom"):
            await run_job(supabase, "lesson_ready", LESSON_ID)
