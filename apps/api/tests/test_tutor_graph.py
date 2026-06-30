"""End-to-end tests for the tutor state machine graph (Dev 4 — Sprint 1 idle_to_teaching).

Unlike test_websocket_session.py (which mocks ``dispatch_event``), these drive the REAL compiled
LangGraph via ``dispatch_event`` with only Redis mocked — proving the IDLE → TEACHING transition
actually applies one transition and terminates, instead of recursing on the old teaching→teaching
self-loop (which raised GraphRecursionError).

``_read_state`` / ``_persist_state`` lazy-import ``get_redis`` from ``app.core.redis``, so the patch
target is ``app.core.redis.get_redis``. ``@pytest.mark.unit``; ``asyncio_mode = "auto"``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.tutor.state_machine.graph import TutorState

_STATE_TTL = 86_400  # mirrors graph._STATE_TTL


def _redis(current_state: str | None) -> AsyncMock:
    """An AsyncMock Redis whose GET returns *current_state* (None → fresh/IDLE)."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=current_state)
    return redis


# ── IDLE → TEACHING (the task) ──────────────────────────────────────────────────


@pytest.mark.unit
async def test_session_start_transitions_idle_to_teaching(mocker) -> None:
    """AC1: a fresh session + session_start lands in TEACHING (no recursion)."""
    mocker.patch("app.core.redis.get_redis", return_value=_redis(None))

    from app.modules.tutor.state_machine.graph import dispatch_event

    result = await dispatch_event("s-idle", "session_start")

    assert result["current_state"] == TutorState.TEACHING


@pytest.mark.unit
async def test_session_start_persists_teaching_state(mocker) -> None:
    """AC2: the transition persists tutor_state = TEACHING with the 24 h TTL."""
    redis = _redis(None)
    mocker.patch("app.core.redis.get_redis", return_value=redis)

    from app.modules.tutor.state_machine.graph import dispatch_event

    await dispatch_event("s-persist", "session_start")

    redis.set.assert_any_call("tutor_state:s-persist", "TEACHING", ex=_STATE_TTL)
    # Exactly one transition: only teaching_node runs and persists once (idle_node does NOT
    # run — entry routes straight to teaching). Guards against a sub-recursion-limit self-loop.
    assert redis.set.call_count == 1


@pytest.mark.unit
async def test_no_graph_recursion_error_on_session_start(mocker) -> None:
    """AC1/AC5: session_start must NOT raise GraphRecursionError (self-loop regression guard)."""
    from langgraph.errors import GraphRecursionError

    mocker.patch("app.core.redis.get_redis", return_value=_redis(None))

    from app.modules.tutor.state_machine.graph import dispatch_event

    try:
        result = await dispatch_event("s-norecurse", "session_start")
    except GraphRecursionError:  # pragma: no cover - the bug this story fixes
        pytest.fail("session_start recursed — teaching→teaching self-loop regression")

    assert result["current_state"] == TutorState.TEACHING


# ── Termination / no self-loop ────────────────────────────────────────────────


@pytest.mark.unit
async def test_unrecognized_event_from_teaching_stays_and_terminates(mocker) -> None:
    """AC3: an unrecognised event from TEACHING stays TEACHING and terminates (no recursion)."""
    mocker.patch("app.core.redis.get_redis", return_value=_redis("TEACHING"))

    from app.modules.tutor.state_machine.graph import dispatch_event

    result = await dispatch_event("s-noop", "noop")

    assert result["current_state"] == TutorState.TEACHING


@pytest.mark.unit
async def test_idle_stays_idle_on_unrecognized_event(mocker) -> None:
    """route_from_idle default: a non-session_start event from IDLE stays IDLE."""
    mocker.patch("app.core.redis.get_redis", return_value=_redis(None))

    from app.modules.tutor.state_machine.graph import dispatch_event

    result = await dispatch_event("s-idle-noop", "noop")

    assert result["current_state"] == TutorState.IDLE


# ── Live-state routing (entry uses current_state from Redis) ─────────────────────


@pytest.mark.unit
async def test_routes_on_live_redis_state_not_stale_default(mocker) -> None:
    """AC4: routing uses the live current_state from Redis, not always-IDLE.

    QUIZZING + quiz_failed → TEACH_BACK is reachable ONLY via the QUIZZING router. If the entry
    ignored current_state (always IDLE), quiz_failed would hit route_from_idle → stay IDLE, never
    reaching TEACH_BACK — so this proves the live state drives routing.
    """
    mocker.patch("app.core.redis.get_redis", return_value=_redis("QUIZZING"))

    from app.modules.tutor.state_machine.graph import dispatch_event

    result = await dispatch_event("s-quiz", "quiz_failed")

    assert result["current_state"] == TutorState.TEACH_BACK


# ── Robustness: corrupt persisted state ──────────────────────────────────────────


@pytest.mark.unit
async def test_corrupt_persisted_state_defaults_to_idle(mocker) -> None:
    """A non-enum Redis state value must NOT crash dispatch — route_entry falls back to IDLE.

    With the IDLE fallback, session_start still drives → TEACHING (the session self-heals).
    """
    mocker.patch("app.core.redis.get_redis", return_value=_redis("BOGUS-STATE"))

    from app.modules.tutor.state_machine.graph import dispatch_event

    result = await dispatch_event("s-corrupt", "session_start")

    assert result["current_state"] == TutorState.TEACHING


# ── Other transitions through the new entry topology ──────────────────────────────


@pytest.mark.unit
async def test_intervening_complete_returns_to_teaching(mocker) -> None:
    """route_from_intervening: INTERVENING + intervention_complete → TEACHING."""
    mocker.patch("app.core.redis.get_redis", return_value=_redis("INTERVENING"))

    from app.modules.tutor.state_machine.graph import dispatch_event

    result = await dispatch_event("s-interv", "intervention_complete")

    assert result["current_state"] == TutorState.TEACHING


@pytest.mark.unit
async def test_segment_complete_routes_to_checking_in(mocker) -> None:
    """TEACHING + segment_complete → CHECKING_IN (simple transition under the new entry routing)."""
    mocker.patch("app.core.redis.get_redis", return_value=_redis("TEACHING"))

    from app.modules.tutor.state_machine.graph import dispatch_event

    result = await dispatch_event("s-seg", "segment_complete")

    assert result["current_state"] == TutorState.CHECKING_IN


@pytest.mark.unit
async def test_distraction_detected_routes_to_intervening_when_guard_allows(mocker) -> None:
    """Guarded path under the new entry topology: TEACHING + distraction_detected → INTERVENING
    when not in cooldown and below the per-session cap. Proves the guard (which reads Redis +
    settings) still runs correctly now that routing happens at entry."""
    sid = "s-distract"
    redis = AsyncMock()

    async def _get(key: str):
        if key == f"tutor_state:{sid}":
            return "TEACHING"
        if key == f"tutor_distraction_count:{sid}":
            return "0"
        return None

    redis.get = AsyncMock(side_effect=_get)
    redis.exists = AsyncMock(return_value=0)  # no cooldown
    mocker.patch("app.core.redis.get_redis", return_value=redis)

    mock_settings = MagicMock()
    mock_settings.max_distraction_per_session = 3
    mocker.patch("app.config.get_settings", return_value=mock_settings)

    from app.modules.tutor.state_machine.graph import dispatch_event

    result = await dispatch_event(sid, "distraction_detected")

    assert result["current_state"] == TutorState.INTERVENING


@pytest.mark.unit
async def test_session_reset_returns_to_idle(mocker) -> None:
    """SESSION_END + session_reset → IDLE."""
    mocker.patch("app.core.redis.get_redis", return_value=_redis("SESSION_END"))

    from app.modules.tutor.state_machine.graph import dispatch_event

    result = await dispatch_event("s-reset", "session_reset")

    assert result["current_state"] == TutorState.IDLE


@pytest.mark.unit
async def test_session_end_noop_terminates_without_running_a_node(mocker) -> None:
    """SESSION_END + unrecognised event → entry routes straight to END; no crash, stays SESSION_END."""
    mocker.patch("app.core.redis.get_redis", return_value=_redis("SESSION_END"))

    from app.modules.tutor.state_machine.graph import dispatch_event

    result = await dispatch_event("s-end", "noop")

    assert result["current_state"] == TutorState.SESSION_END


# ── Service-layer caller ─────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_start_session_dispatches_session_start(mocker) -> None:
    """AC6: service.start_session drives the session_start dispatch."""
    mock_dispatch = AsyncMock()
    mocker.patch("app.modules.tutor.state_machine.graph.dispatch_event", mock_dispatch)

    from app.modules.tutor.service import start_session

    await start_session("s-svc")

    mock_dispatch.assert_called_once_with("s-svc", "session_start")
