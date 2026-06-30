"""Unit tests for WebSocket session lifecycle and tutor guard rules.

Covers two tracker tasks in ``apps/api/app/core/websocket.py``:
- ``session_state_init``  → ``_init_session_state()``
- ``idle_to_teaching``    → ``_handle_session_start()``

All tests are ``@pytest.mark.unit`` — no real Redis / state machine required.
``asyncio_mode = "auto"`` (see pyproject.toml) runs the async tests directly.

Patch-target note
-----------------
``_init_session_state`` lazily imports ``get_redis`` *inside* the function
(per the no-module-level-imports rule in websocket.py), so the only effective
patch target is ``app.core.redis.get_redis`` — the namespace the lazy
``from app.core.redis import get_redis`` actually resolves against. Patching
``app.core.websocket.get_redis`` would not intercept it (the name never lives
on the websocket module).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


# ── Group A — _init_session_state ──────────────────────────────────────────────


@pytest.mark.unit
async def test_a1_init_sets_tutor_state_idle(mocker):
    mock_redis = AsyncMock()
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    from app.core.websocket import _init_session_state

    await _init_session_state("sess-001")

    mock_redis.set.assert_any_call("tutor_state:sess-001", "IDLE", ex=86400)


@pytest.mark.unit
async def test_a2_init_zeros_distraction_count(mocker):
    mock_redis = AsyncMock()
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    from app.core.websocket import _init_session_state

    await _init_session_state("sess-001")

    mock_redis.set.assert_any_call("tutor_distraction_count:sess-001", "0", ex=86400)


@pytest.mark.unit
async def test_a3_init_clears_stale_cooldown_and_fatigue_keys(mocker):
    mock_redis = AsyncMock()
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    from app.core.websocket import _init_session_state

    await _init_session_state("sess-001")

    mock_redis.delete.assert_any_call("tutor_cooldown:sess-001")
    mock_redis.delete.assert_any_call("tutor_fatigue_fired:sess-001")
    mock_redis.delete.assert_any_call("session:sess-001:segment_index")  # reset segment pointer


@pytest.mark.unit
async def test_a4_init_redis_failure_does_not_raise(mocker):
    mocker.patch("app.core.redis.get_redis", side_effect=ConnectionError("down"))

    from app.core.websocket import _init_session_state

    await _init_session_state("sess-fail")  # must not raise


# ── Group B — _handle_session_start ───────────────────────────────────────────


@pytest.mark.unit
async def test_b1_session_start_dispatches_event(mocker):
    mock_dispatch = AsyncMock()
    mocker.patch("app.modules.tutor.state_machine.graph.dispatch_event", mock_dispatch)

    from app.core.websocket import _handle_session_start

    await _handle_session_start("sess-002")

    mock_dispatch.assert_called_once_with("sess-002", "session_start")


@pytest.mark.unit
async def test_b2_session_start_dispatch_failure_does_not_raise(mocker):
    mocker.patch(
        "app.modules.tutor.state_machine.graph.dispatch_event",
        side_effect=RuntimeError("FSM crash"),
    )

    from app.core.websocket import _handle_session_start

    await _handle_session_start("sess-fail")  # must not raise


# ── Group C — Cooldown guard G2 ───────────────────────────────────────────────


@pytest.mark.unit
async def test_c1_g2_cooldown_active_blocks_intervention(mocker):
    mock_redis = AsyncMock()
    mock_redis.exists = AsyncMock(return_value=1)  # in cooldown
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    mock_settings = MagicMock()
    mock_settings.max_distraction_per_session = 3
    mocker.patch("app.config.get_settings", return_value=mock_settings)

    from app.modules.tutor.state_machine.graph import _can_intervene_distraction

    result = await _can_intervene_distraction("sess-003")

    assert result is False


@pytest.mark.unit
async def test_c2_g2_no_cooldown_below_max_allows_intervention(mocker):
    mock_redis = AsyncMock()
    mock_redis.exists = AsyncMock(return_value=0)   # not in cooldown
    mock_redis.get = AsyncMock(return_value="1")    # count = 1, below max of 3
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    mock_settings = MagicMock()
    mock_settings.max_distraction_per_session = 3
    mocker.patch("app.config.get_settings", return_value=mock_settings)

    from app.modules.tutor.state_machine.graph import _can_intervene_distraction

    result = await _can_intervene_distraction("sess-003")

    assert result is True


@pytest.mark.unit
async def test_c3_g2_at_max_count_blocks_intervention(mocker):
    mock_redis = AsyncMock()
    mock_redis.exists = AsyncMock(return_value=0)   # not in cooldown
    mock_redis.get = AsyncMock(return_value="3")    # count == max of 3 → must block
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    mock_settings = MagicMock()
    mock_settings.max_distraction_per_session = 3
    mocker.patch("app.config.get_settings", return_value=mock_settings)

    from app.modules.tutor.state_machine.graph import _can_intervene_distraction

    result = await _can_intervene_distraction("sess-003")

    assert result is False


# ── Group D — TEACH_BACK guard G5 ─────────────────────────────────────────────


@pytest.mark.unit
async def test_d1_g5_teach_back_state_blocks_intervention(mocker):
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value="TEACH_BACK")
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    from app.modules.tutor.state_machine.graph import _is_in_teachback

    result = await _is_in_teachback("sess-004")

    assert result is True


@pytest.mark.unit
async def test_d2_g5_teach_back_absent_allows_intervention(mocker):
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value="TEACHING")
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    from app.modules.tutor.state_machine.graph import _is_in_teachback

    result = await _is_in_teachback("sess-004")

    assert result is False


# ── Group E — quizzing/teachback flow dispatch (s2-3) ─────────────────────────


@pytest.mark.unit
async def test_e1_flow_event_dispatches_to_fsm(mocker):
    """A client-drivable lifecycle event is dispatched into the tutor FSM."""
    mock_dispatch = AsyncMock()
    mocker.patch("app.modules.tutor.state_machine.graph.dispatch_event", mock_dispatch)

    from app.core.websocket import _handle_tutor_event

    await _handle_tutor_event("sess-q", "quiz_failed")

    mock_dispatch.assert_called_once_with("sess-q", "quiz_failed")


@pytest.mark.unit
@pytest.mark.parametrize("event", ["distraction_detected", "fatigue_detected", "session_reset"])
async def test_e2_server_only_event_rejected_by_service(event):
    """Server/engine/admin-only events must NOT be client-drivable — advance_tutor_state rejects them."""
    from app.modules.tutor.service import advance_tutor_state

    with pytest.raises(ValueError):
        await advance_tutor_state("sess-x", event)


@pytest.mark.unit
async def test_e3_tutor_event_failure_does_not_raise(mocker):
    """A transient FSM error during a flow event must be swallowed at the WS boundary (B2 analog)."""
    mocker.patch(
        "app.modules.tutor.state_machine.graph.dispatch_event",
        side_effect=RuntimeError("FSM crash"),
    )

    from app.core.websocket import _handle_tutor_event

    await _handle_tutor_event("sess-q", "quiz_failed")  # must not raise


@pytest.mark.unit
def test_e4_client_event_allowlists_match():
    """The WS-routing allow-list and the service allow-list must stay in sync (no silent drift)."""
    from app.core.websocket import _TUTOR_CLIENT_EVENTS
    from app.modules.tutor.service import _CLIENT_DRIVABLE_EVENTS

    assert _TUTOR_CLIENT_EVENTS == _CLIENT_DRIVABLE_EVENTS


# ── Group F — session restore on reconnect (s2-4) ─────────────────────────────


@pytest.mark.unit
async def test_f1_reconnect_syncs_state_and_no_reset(mocker):
    """A reconnect (tutor_state present) pushes a state_change sync and does NOT reset the session."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value="QUIZZING")
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    from app.core.websocket import ConnectionManager

    ws = AsyncMock()
    mgr = ConnectionManager()
    await mgr.connect(ws, "sess-r1")

    # On-contract ws.ts state_change (from == to, i.e. a sync, not a transition).
    ws.send_json.assert_called_once_with(
        {
            "type": "state_change",
            "payload": {"session_id": "sess-r1", "from_state": "QUIZZING", "to_state": "QUIZZING"},
        }
    )
    mock_redis.set.assert_not_called()  # reconnect must not reset state


@pytest.mark.unit
async def test_f5_reconnect_decodes_bytes_state(mocker):
    """Restore handles a bytes tutor_state (real redis without decode_responses) and any state value."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=b"TEACH_BACK")
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    from app.core.websocket import ConnectionManager

    ws = AsyncMock()
    await ConnectionManager().connect(ws, "sess-bytes")

    ws.send_json.assert_called_once_with(
        {
            "type": "state_change",
            "payload": {"session_id": "sess-bytes", "from_state": "TEACH_BACK", "to_state": "TEACH_BACK"},
        }
    )


@pytest.mark.unit
async def test_f6_reconnect_send_failure_does_not_break_connect(mocker):
    """If the reconnecting socket is already gone, the failed sync send must not break connect, and the
    dead socket is dropped from the registry (no leak)."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value="TEACHING")
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    from app.core.websocket import ConnectionManager

    ws = AsyncMock()
    ws.send_json = AsyncMock(side_effect=RuntimeError("socket closed"))
    mgr = ConnectionManager()

    await mgr.connect(ws, "sess-deadsock")  # must not raise

    # The dead socket was reaped, not left registered.
    assert "sess-deadsock" not in mgr._connections


@pytest.mark.unit
async def test_f2_new_session_inits_and_no_sync(mocker):
    """A fresh session (no prior tutor_state) initialises and sends no sync message."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    from app.core.websocket import ConnectionManager

    ws = AsyncMock()
    mgr = ConnectionManager()
    await mgr.connect(ws, "sess-new")

    mock_redis.set.assert_any_call("tutor_state:sess-new", "IDLE", ex=86400)  # fresh init
    ws.send_json.assert_not_called()  # no restore


@pytest.mark.unit
async def test_f3_reconnect_read_failure_degrades_to_init(mocker):
    """A Redis read failure on connect degrades to fresh init — never breaks the handshake."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(side_effect=ConnectionError("down"))
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    from app.core.websocket import ConnectionManager

    ws = AsyncMock()
    mgr = ConnectionManager()
    await mgr.connect(ws, "sess-fail")  # must not raise

    ws.send_json.assert_not_called()  # no sync message when state couldn't be read
