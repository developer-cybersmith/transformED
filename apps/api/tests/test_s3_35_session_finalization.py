"""RED tests for S3-35 (D3): _finalize_session writes ces_final + ended_at to sessions table.

Written RED-first — they fail until _finalize_session is added to graph.py and
called from session_end_node via asyncio.create_task.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_redis(history: list[dict] | None = None) -> AsyncMock:
    """Async Redis mock with controllable ces_history entries."""
    redis = AsyncMock()
    entries = [json.dumps(e) for e in (history or [])]
    redis.lrange = AsyncMock(return_value=entries)
    return redis


def _make_supabase() -> MagicMock:
    """Supabase mock that records UPDATE calls."""
    supabase = MagicMock()
    supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = (
        MagicMock()
    )
    return supabase


# ---------------------------------------------------------------------------
# AC 1 — DB UPDATE called with ces_final and ended_at
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_finalize_session_updates_sessions_table():
    """AC1: _finalize_session calls supabase UPDATE on 'sessions' with ces_final + ended_at."""
    from app.modules.tutor.state_machine.graph import _finalize_session  # noqa: PLC0415

    redis = _make_redis(history=[{"v": 60.0, "t": 1000}, {"v": 80.0, "t": 1005}])
    supabase = _make_supabase()

    with patch("asyncio.to_thread", side_effect=lambda f, *a, **kw: f()):
        await _finalize_session("ses-35", redis=redis, supabase=supabase)

    supabase.table.assert_called_with("sessions")
    update_call = supabase.table.return_value.update.call_args
    payload = update_call[0][0]
    assert "ces_final" in payload, "ces_final must be in UPDATE payload"
    assert "ended_at" in payload, "ended_at must be in UPDATE payload"


# ---------------------------------------------------------------------------
# AC 2 — ces_final is the average of Redis history values
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_finalize_session_ces_final_is_avg_of_history():
    """AC2: ces_final = avg({v: 60, v: 80}) = 70.0 (rounded to 2dp)."""
    from app.modules.tutor.state_machine.graph import _finalize_session  # noqa: PLC0415

    redis = _make_redis(history=[{"v": 60.0, "t": 1000}, {"v": 80.0, "t": 1005}])
    supabase = _make_supabase()

    with patch("asyncio.to_thread", side_effect=lambda f, *a, **kw: f()):
        await _finalize_session("ses-35b", redis=redis, supabase=supabase)

    update_call = supabase.table.return_value.update.call_args
    payload = update_call[0][0]
    assert payload["ces_final"] == pytest.approx(70.0, abs=0.01), (
        f"Expected ces_final=70.0 (avg of 60+80), got {payload['ces_final']}"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_finalize_session_ces_final_zero_when_no_history():
    """AC2: ces_final = 0.0 when Redis ces_history is empty."""
    from app.modules.tutor.state_machine.graph import _finalize_session  # noqa: PLC0415

    redis = _make_redis(history=[])
    supabase = _make_supabase()

    with patch("asyncio.to_thread", side_effect=lambda f, *a, **kw: f()):
        await _finalize_session("ses-35c", redis=redis, supabase=supabase)

    update_call = supabase.table.return_value.update.call_args
    payload = update_call[0][0]
    assert payload["ces_final"] == pytest.approx(0.0, abs=0.01)


# ---------------------------------------------------------------------------
# AC 4 — DB failure is non-fatal
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_finalize_session_db_failure_is_nonfatal():
    """AC4: _finalize_session catches DB exceptions and does NOT re-raise."""
    from app.modules.tutor.state_machine.graph import _finalize_session  # noqa: PLC0415

    redis = _make_redis(history=[{"v": 50.0, "t": 1000}])
    supabase = MagicMock()
    supabase.table.return_value.update.return_value.eq.return_value.execute.side_effect = (
        RuntimeError("DB down")
    )

    with (
        patch("asyncio.to_thread", side_effect=lambda f, *a, **kw: f()),
        patch("sentry_sdk.capture_exception"),
    ):
        # Must not raise
        await _finalize_session("ses-35d", redis=redis, supabase=supabase)


# ---------------------------------------------------------------------------
# AC 5 — session_end_node calls _finalize_session via asyncio.create_task
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_end_node_schedules_finalize_via_create_task(mocker):
    """AC5: session_end_node uses asyncio.create_task(finalize) not await."""
    from app.modules.tutor.state_machine.graph import session_end_node  # noqa: PLC0415

    mocker.patch(
        "app.modules.tutor.state_machine.graph._persist_state",
        new_callable=AsyncMock,
    )
    fake_redis = AsyncMock()
    fake_redis.lrange = AsyncMock(return_value=[])
    mocker.patch("app.core.redis.get_redis", return_value=fake_redis)
    fake_supabase = MagicMock()
    fake_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = (
        MagicMock()
    )
    mocker.patch("app.core.db.get_supabase", return_value=fake_supabase)

    captured = []

    def fake_create_task(coro):
        captured.append(coro)
        try:
            coro.close()
        except Exception:  # noqa: BLE001
            pass
        return MagicMock()

    with patch("asyncio.create_task", side_effect=fake_create_task):
        state = {"session_id": "ses-35e"}
        result = await session_end_node(state)

    assert len(captured) == 1, "create_task must be called exactly once from session_end_node"
    assert "current_state" in result
