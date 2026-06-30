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
