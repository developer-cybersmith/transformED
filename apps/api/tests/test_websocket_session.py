"""Unit tests for WebSocket session lifecycle wiring (Dev 4, Sprint 1).

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

from app.core.websocket import _handle_session_start, _init_session_state


# ── Task 1 — _init_session_state ───────────────────────────────────────────────


@pytest.mark.unit
async def test_init_session_state_sets_and_clears_keys(mocker) -> None:
    """Happy path: IDLE + zeroed counter set with 24 h TTL; stale flags cleared."""
    mock_redis = MagicMock()
    mock_redis.set = AsyncMock()
    mock_redis.delete = AsyncMock()
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    await _init_session_state("test-session-id")

    mock_redis.set.assert_any_call("tutor_state:test-session-id", "IDLE", ex=86400)
    mock_redis.set.assert_any_call("tutor_distraction_count:test-session-id", "0", ex=86400)
    mock_redis.delete.assert_any_call("tutor_cooldown:test-session-id")
    mock_redis.delete.assert_any_call("tutor_fatigue_fired:test-session-id")


@pytest.mark.unit
async def test_init_session_state_swallows_redis_failure(mocker) -> None:
    """A Redis failure must never propagate out of accept() handshake wiring."""
    mocker.patch("app.core.redis.get_redis", side_effect=ConnectionError("redis down"))

    # Must not raise — best-effort init.
    await _init_session_state("any-id")


# ── Task 2 — _handle_session_start ─────────────────────────────────────────────


@pytest.mark.unit
async def test_handle_session_start_dispatches_event(mocker) -> None:
    """session_start message dispatches the session_start event exactly once."""
    mock_dispatch = mocker.patch(
        "app.modules.tutor.state_machine.graph.dispatch_event",
        new=AsyncMock(),
    )

    await _handle_session_start("test-session-id")

    mock_dispatch.assert_called_once_with("test-session-id", "session_start")


@pytest.mark.unit
async def test_handle_session_start_swallows_dispatch_failure(mocker) -> None:
    """A state-machine dispatch error must never propagate out of the handler."""
    mocker.patch(
        "app.modules.tutor.state_machine.graph.dispatch_event",
        new=AsyncMock(side_effect=RuntimeError("state machine error")),
    )

    # Must not raise — mirrors _handle_attention_signal's error contract.
    await _handle_session_start("test-id")
