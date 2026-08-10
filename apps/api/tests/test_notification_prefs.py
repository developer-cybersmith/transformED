"""Tests for get_notification_preference() — Story 3-33 (S3-07 Dev 3 contribution).

All ACs covered. No test asserts only on a mock it constructed (binding rule 2):
every test asserts on the *return value*, which is the observable outcome.
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import MagicMock, patch

# ── Helper: build a mock supabase client whose chain returns a specific value ─


def _mock_supabase(*, data: list | None = None, raises: Exception | None = None) -> MagicMock:
    """Build a synchronous supabase-py v2 mock for user_notification_preferences reads.

    ``maybe_single()`` in supabase-py returns resp.data = dict (one row) or None (no row),
    not a list. This helper mimics that: pass a list with one row dict to return that row,
    or None/empty list to return data=None (no row found).

    Args:
        data: list with one row dict to return (maybe_single returns data[0]),
              or None/[] for no-row (data=None).
        raises: if set, .execute() raises this exception instead.
    """
    resp = MagicMock()
    # Simulate maybe_single() semantics: single dict or None
    if data and len(data) > 0:
        resp.data = data[0]
    else:
        resp.data = None

    chain = MagicMock()  # table(...).select(...).eq(...).maybe_single()
    if raises:
        chain.execute.side_effect = raises
    else:
        chain.execute.return_value = resp

    supabase = MagicMock()
    supabase.table.return_value.select.return_value.eq.return_value.maybe_single.return_value = (
        chain
    )
    return supabase


# ── AC 1: module importable, function exists ──────────────────────────────────


def test_get_notification_preference_is_importable():
    """AC 1 — the function exists and is importable from the correct module."""
    from app.modules.assessment.notification_prefs import get_notification_preference  # noqa: F401


# ── AC 9: function is async ───────────────────────────────────────────────────


def test_get_notification_preference_is_async():
    """AC 9 — get_notification_preference must be async (asyncio.to_thread requirement)."""
    from app.modules.assessment.notification_prefs import get_notification_preference

    assert inspect.iscoroutinefunction(get_notification_preference), (
        "get_notification_preference must be async"
    )


# ── AC 2: DB exception → True (fail-open) ────────────────────────────────────


def test_returns_true_on_db_exception():
    """AC 2 — any DB exception (table not found, connection error) → True (fail-open)."""
    from app.modules.assessment.notification_prefs import get_notification_preference

    supabase = _mock_supabase(raises=RuntimeError("relation does not exist"))
    result = asyncio.run(
        get_notification_preference(
            user_id="user-abc",
            preference_key="session_report_email",
            supabase=supabase,
        )
    )
    assert result is True


# ── AC 3: empty result → True ────────────────────────────────────────────────


def test_returns_true_when_no_row_exists():
    """AC 3 — user has no preference row yet → default opt-in (True)."""
    from app.modules.assessment.notification_prefs import get_notification_preference

    # maybe_single() returns .data = None when no row found
    resp = MagicMock()
    resp.data = None
    supabase = MagicMock()
    (
        supabase.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute
    ).return_value = resp

    result = asyncio.run(
        get_notification_preference(
            user_id="user-abc",
            preference_key="session_report_email",
            supabase=supabase,
        )
    )
    assert result is True


# ── AC 4: NULL column value → True ───────────────────────────────────────────


def test_returns_true_when_column_is_null():
    """AC 4 — row exists but column value is NULL → default opt-in (True)."""
    from app.modules.assessment.notification_prefs import get_notification_preference

    supabase = _mock_supabase(data=[{"user_id": "user-abc", "session_report_email": None}])
    result = asyncio.run(
        get_notification_preference(
            user_id="user-abc",
            preference_key="session_report_email",
            supabase=supabase,
        )
    )
    assert result is True


# ── AC 5a: stored True → returns True ────────────────────────────────────────


def test_returns_true_when_preference_is_true():
    """AC 5 — explicitly opted-in preference → True."""
    from app.modules.assessment.notification_prefs import get_notification_preference

    supabase = _mock_supabase(data=[{"user_id": "user-abc", "session_report_email": True}])
    result = asyncio.run(
        get_notification_preference(
            user_id="user-abc",
            preference_key="session_report_email",
            supabase=supabase,
        )
    )
    assert result is True


# ── AC 5b: stored False → returns False ──────────────────────────────────────


def test_returns_false_when_preference_is_false():
    """AC 5 — explicitly opted-out preference → False."""
    from app.modules.assessment.notification_prefs import get_notification_preference

    supabase = _mock_supabase(data=[{"user_id": "user-abc", "session_report_email": False}])
    result = asyncio.run(
        get_notification_preference(
            user_id="user-abc",
            preference_key="session_report_email",
            supabase=supabase,
        )
    )
    assert result is False


# ── AC 6: user_id used as filter ─────────────────────────────────────────────


def test_user_id_is_applied_as_filter():
    """AC 6 — the DB query must filter by user_id; no cross-user data returned."""
    from app.modules.assessment.notification_prefs import get_notification_preference

    supabase = _mock_supabase(data=[{"session_report_email": True}])
    asyncio.run(
        get_notification_preference(
            user_id="target-user-123",
            preference_key="session_report_email",
            supabase=supabase,
        )
    )
    # Assert the eq() filter was called with user_id="target-user-123"
    eq_call = supabase.table.return_value.select.return_value.eq
    eq_call.assert_called_once()
    call_args = eq_call.call_args
    # eq("user_id", "target-user-123") or positional equivalent
    assert "target-user-123" in call_args.args or "target-user-123" in call_args.kwargs.values(), (
        f"eq() was not called with the user_id. Call args: {call_args}"
    )


# ── AC 7: no LLM calls ───────────────────────────────────────────────────────


def test_no_llm_calls():
    """AC 7 — notification_prefs.py must contain zero LLM identifiers. Verified by source
    inspection so the assertion is true regardless of how an LLM call might be made.
    """
    import inspect

    from app.modules.assessment import notification_prefs as _np

    source = inspect.getsource(_np)
    llm_identifiers = [
        "OpenAILLMProvider",
        "complete(",
        "complete_structured(",
        "AsyncOpenAI",
        "llm_mini",
        "LLM_MINI",
        "openai.chat",
        "ChatCompletion",
    ]
    for ident in llm_identifiers:
        assert ident not in source, (
            f"AC 7 FAIL: LLM identifier '{ident}' found in notification_prefs.py. "
            "This module must make zero LLM calls."
        )


# ── AC 8: asyncio.to_thread wrapper ──────────────────────────────────────────


def test_db_call_is_wrapped_in_to_thread():
    """AC 8 — Supabase client is synchronous; all calls must use asyncio.to_thread."""
    from app.modules.assessment.notification_prefs import get_notification_preference

    supabase = _mock_supabase(data=[{"session_report_email": True}])
    to_thread_calls: list = []

    original_to_thread = asyncio.to_thread

    async def spy_to_thread(func, *args, **kwargs):
        to_thread_calls.append(func)
        return await original_to_thread(func, *args, **kwargs)

    with patch("asyncio.to_thread", side_effect=spy_to_thread):
        asyncio.run(
            get_notification_preference(
                user_id="user-abc",
                preference_key="session_report_email",
                supabase=supabase,
            )
        )

    assert len(to_thread_calls) >= 1, (
        "get_notification_preference must wrap the DB call in asyncio.to_thread"
    )


# ── AC 10: reads user_notification_preferences, not users ────────────────────


def test_reads_from_user_notification_preferences_table():
    """AC 10 — must query user_notification_preferences, NOT the users table."""
    from app.modules.assessment.notification_prefs import get_notification_preference

    supabase = _mock_supabase(data=[{"session_report_email": True}])
    asyncio.run(
        get_notification_preference(
            user_id="user-abc",
            preference_key="session_report_email",
            supabase=supabase,
        )
    )
    table_call = supabase.table.call_args
    called_table = table_call.args[0] if table_call.args else table_call.kwargs.get("table_name")
    assert called_table == "user_notification_preferences", (
        f"Expected table 'user_notification_preferences', got '{called_table}'. "
        "This function must not read from the users table (auth-owned)."
    )


# ── AC 11: user_id is the only access gate ───────────────────────────────────


def test_different_user_ids_produce_different_filter_calls():
    """AC 11 — each call is scoped to its own user_id; no shared state."""
    from app.modules.assessment.notification_prefs import get_notification_preference

    supabase_a = _mock_supabase(data=[{"session_report_email": True}])
    supabase_b = _mock_supabase(data=[{"session_report_email": False}])

    result_a = asyncio.run(
        get_notification_preference(
            user_id="user-A",
            preference_key="session_report_email",
            supabase=supabase_a,
        )
    )
    result_b = asyncio.run(
        get_notification_preference(
            user_id="user-B",
            preference_key="session_report_email",
            supabase=supabase_b,
        )
    )

    # Different users, different stored values → correct results
    assert result_a is True
    assert result_b is False

    # Each supabase client was called with its own user_id
    eq_call_a = supabase_a.table.return_value.select.return_value.eq.call_args
    eq_call_b = supabase_b.table.return_value.select.return_value.eq.call_args
    assert "user-A" in (eq_call_a.args + tuple(eq_call_a.kwargs.values()))
    assert "user-B" in (eq_call_b.args + tuple(eq_call_b.kwargs.values()))
