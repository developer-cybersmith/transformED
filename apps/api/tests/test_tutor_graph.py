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


@pytest.fixture(autouse=True)
def _stub_langfuse(mocker):
    """Stub _trace_dispatch so tests don't require app.core.langfuse to exist."""
    mocker.patch(
        "app.modules.tutor.state_machine.graph._trace_dispatch",
        return_value=None,
    )


def _redis(current_state: str | None) -> AsyncMock:
    """An AsyncMock Redis whose GET returns *current_state* (None → fresh/IDLE)."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=current_state)
    return redis


def _keyed_redis(sid: str, *, state: str, count: str | None = None, exists: int = 0) -> AsyncMock:
    """Key-aware AsyncMock Redis for guard tests.

    GET returns *state* for ``tutor_state:{sid}`` and *count* for ``tutor_distraction_count:{sid}``,
    so the guard's ``int(count_raw)`` never receives the state string. EXISTS returns *exists*
    (1 = cooldown / fatigue-fired present).
    """
    redis = AsyncMock()

    async def _get(key: str):
        if key == f"tutor_state:{sid}":
            return state
        if key == f"tutor_distraction_count:{sid}":
            return count
        return None

    redis.get = AsyncMock(side_effect=_get)
    redis.exists = AsyncMock(return_value=exists)
    return redis


def _patch_settings(mocker, *, max_distraction: int = 3) -> None:
    """Patch get_settings — required by any test whose path reaches a guard or intervening_node."""
    settings = MagicMock()
    settings.max_distraction_per_session = max_distraction
    settings.intervention_cooldown_seconds = 120
    mocker.patch("app.config.get_settings", return_value=settings)


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


# ── Remaining transitions — complete the 14 (story 4-5) ──────────────────────────


@pytest.mark.unit
async def test_fatigue_detected_routes_to_intervening(mocker) -> None:
    """TEACHING + fatigue_detected (not yet fired) → INTERVENING."""
    _patch_settings(mocker)
    mocker.patch(
        "app.core.redis.get_redis",
        return_value=_keyed_redis("s-fatigue", state="TEACHING", exists=0),
    )

    from app.modules.tutor.state_machine.graph import dispatch_event

    result = await dispatch_event("s-fatigue", "fatigue_detected")

    assert result["current_state"] == TutorState.INTERVENING


@pytest.mark.unit
async def test_quiz_trigger_routes_to_quizzing(mocker) -> None:
    """TEACHING + quiz_trigger → QUIZZING."""
    mocker.patch("app.core.redis.get_redis", return_value=_redis("TEACHING"))

    from app.modules.tutor.state_machine.graph import dispatch_event

    result = await dispatch_event("s-qtrig", "quiz_trigger")

    assert result["current_state"] == TutorState.QUIZZING


@pytest.mark.unit
async def test_lesson_complete_routes_to_session_end(mocker) -> None:
    """TEACHING + lesson_complete → SESSION_END."""
    mocker.patch("app.core.redis.get_redis", return_value=_redis("TEACHING"))

    from app.modules.tutor.state_machine.graph import dispatch_event

    result = await dispatch_event("s-lesson", "lesson_complete")

    assert result["current_state"] == TutorState.SESSION_END


@pytest.mark.unit
async def test_checkin_complete_returns_to_teaching(mocker) -> None:
    """CHECKING_IN + checkin_complete → TEACHING."""
    mocker.patch("app.core.redis.get_redis", return_value=_redis("CHECKING_IN"))

    from app.modules.tutor.state_machine.graph import dispatch_event

    result = await dispatch_event("s-checkin", "checkin_complete")

    assert result["current_state"] == TutorState.TEACHING


@pytest.mark.unit
async def test_low_checkin_score_routes_to_quizzing(mocker) -> None:
    """CHECKING_IN + low_checkin_score → QUIZZING."""
    mocker.patch("app.core.redis.get_redis", return_value=_redis("CHECKING_IN"))

    from app.modules.tutor.state_machine.graph import dispatch_event

    result = await dispatch_event("s-lowcheck", "low_checkin_score")

    assert result["current_state"] == TutorState.QUIZZING


@pytest.mark.unit
async def test_quiz_complete_returns_to_teaching(mocker) -> None:
    """QUIZZING + quiz_complete → TEACHING."""
    mocker.patch("app.core.redis.get_redis", return_value=_redis("QUIZZING"))

    from app.modules.tutor.state_machine.graph import dispatch_event

    result = await dispatch_event("s-qdone", "quiz_complete")

    assert result["current_state"] == TutorState.TEACHING


@pytest.mark.unit
async def test_teachback_complete_returns_to_teaching(mocker) -> None:
    """TEACH_BACK + teachback_complete → TEACHING."""
    mocker.patch("app.core.redis.get_redis", return_value=_redis("TEACH_BACK"))

    from app.modules.tutor.state_machine.graph import dispatch_event

    result = await dispatch_event("s-tbdone", "teachback_complete")

    assert result["current_state"] == TutorState.TEACHING


@pytest.mark.unit
async def test_teachback_failed_routes_to_intervening(mocker) -> None:
    """TEACH_BACK + teachback_failed → INTERVENING."""
    _patch_settings(mocker)
    mocker.patch("app.core.redis.get_redis", return_value=_redis("TEACH_BACK"))

    from app.modules.tutor.state_machine.graph import dispatch_event

    result = await dispatch_event("s-tbfail", "teachback_failed")

    assert result["current_state"] == TutorState.INTERVENING


# ── Guard-blocked cases (event fires, guard keeps FSM in TEACHING) ────────────────


def _assert_intervention_suppressed(redis: AsyncMock, sid: str) -> None:
    """Prove the intervention was BLOCKED, not merely that the state happened to stay TEACHING:
    the guard was consulted (exists awaited), and intervening_node never ran (no INTERVENING
    persisted, no distraction-count increment)."""
    redis.exists.assert_awaited()  # the guard actually ran
    assert not any(
        c.args[:2] == (f"tutor_state:{sid}", "INTERVENING") for c in redis.set.call_args_list
    ), "INTERVENING must never be persisted when the guard blocks"
    redis.incr.assert_not_called()  # intervening_node (which incr's the counter) did not run


@pytest.mark.unit
async def test_distraction_blocked_by_cooldown_stays_teaching(mocker) -> None:
    """distraction_detected during an active cooldown → guard blocks → stays TEACHING (suppressed)."""
    _patch_settings(mocker)
    redis = _keyed_redis("s-cool", state="TEACHING", exists=1)  # cooldown active
    mocker.patch("app.core.redis.get_redis", return_value=redis)

    from app.modules.tutor.state_machine.graph import dispatch_event

    result = await dispatch_event("s-cool", "distraction_detected")

    assert result["current_state"] == TutorState.TEACHING
    _assert_intervention_suppressed(redis, "s-cool")


@pytest.mark.unit
async def test_distraction_blocked_by_max_count_stays_teaching(mocker) -> None:
    """distraction_detected at the per-session cap (count == max) → guard blocks → stays TEACHING."""
    _patch_settings(mocker, max_distraction=3)
    redis = _keyed_redis("s-cap", state="TEACHING", count="3", exists=0)
    mocker.patch("app.core.redis.get_redis", return_value=redis)

    from app.modules.tutor.state_machine.graph import dispatch_event

    result = await dispatch_event("s-cap", "distraction_detected")

    assert result["current_state"] == TutorState.TEACHING
    _assert_intervention_suppressed(redis, "s-cap")


@pytest.mark.unit
async def test_distraction_allowed_just_below_max(mocker) -> None:
    """Boundary (allow side): count == max-1 is still below the cap → INTERVENING.

    Pairs with the count==max blocked test to pin the `<` operator from both directions.
    """
    _patch_settings(mocker, max_distraction=3)
    redis = _keyed_redis("s-belowcap", state="TEACHING", count="2", exists=0)
    mocker.patch("app.core.redis.get_redis", return_value=redis)

    from app.modules.tutor.state_machine.graph import dispatch_event

    result = await dispatch_event("s-belowcap", "distraction_detected")

    assert result["current_state"] == TutorState.INTERVENING


@pytest.mark.unit
async def test_fatigue_blocked_when_already_fired_stays_teaching(mocker) -> None:
    """fatigue_detected after fatigue already fired this session → guard blocks → stays TEACHING."""
    _patch_settings(mocker)  # consistency: future fatigue-guard changes won't crash on MagicMock attrs
    redis = _keyed_redis("s-fat2", state="TEACHING", exists=1)  # fatigue_fired present
    mocker.patch("app.core.redis.get_redis", return_value=redis)

    from app.modules.tutor.state_machine.graph import dispatch_event

    result = await dispatch_event("s-fat2", "fatigue_detected")

    assert result["current_state"] == TutorState.TEACHING
    _assert_intervention_suppressed(redis, "s-fat2")


# ── NEVER interrupt mid-TEACH_BACK (CLAUDE.md §10 guard) ─────────────────────────


@pytest.mark.unit
async def test_distraction_blocked_during_teach_back(mocker) -> None:
    """A distraction_detected event while in TEACH_BACK must NOT leave teach-back."""
    mocker.patch("app.core.redis.get_redis", return_value=_redis("TEACH_BACK"))

    from app.modules.tutor.state_machine.graph import dispatch_event

    result = await dispatch_event("s-tb-distract", "distraction_detected")

    assert result["current_state"] == TutorState.TEACH_BACK


@pytest.mark.unit
async def test_fatigue_blocked_during_teach_back(mocker) -> None:
    """A fatigue_detected event while in TEACH_BACK must NOT leave teach-back."""
    mocker.patch("app.core.redis.get_redis", return_value=_redis("TEACH_BACK"))

    from app.modules.tutor.state_machine.graph import dispatch_event

    result = await dispatch_event("s-tb-fatigue", "fatigue_detected")

    assert result["current_state"] == TutorState.TEACH_BACK


@pytest.mark.unit
async def test_teach_back_stays_on_unrelated_event(mocker) -> None:
    """Any non teach-back-outcome event keeps the FSM in TEACH_BACK (not the old default→TEACHING)."""
    mocker.patch("app.core.redis.get_redis", return_value=_redis("TEACH_BACK"))

    from app.modules.tutor.state_machine.graph import dispatch_event

    result = await dispatch_event("s-tb-noop", "noop")

    assert result["current_state"] == TutorState.TEACH_BACK


# ── Full comprehension flow step-through (CHECKING_IN → QUIZZING → TEACH_BACK → TEACHING) ──


def _stateful_redis(initial: str) -> AsyncMock:
    """Redis mock whose tutor_state GET reflects the last persisted SET — so chained dispatches
    read the evolving state (each dispatch_event is one transition)."""
    store = {"tutor_state": initial}
    redis = AsyncMock()

    async def _get(key: str):
        return store["tutor_state"] if key.startswith("tutor_state:") else None

    async def _set(key: str, value, **_kw):
        if key.startswith("tutor_state:"):
            store["tutor_state"] = value

    redis.get = AsyncMock(side_effect=_get)
    redis.set = AsyncMock(side_effect=_set)
    redis.exists = AsyncMock(return_value=0)
    return redis


@pytest.mark.unit
async def test_quiz_teachback_step_through(mocker) -> None:
    """AC5: TEACHING → CHECKING_IN → QUIZZING → TEACH_BACK → TEACHING across chained dispatches.

    None of these 4 events route through intervening_node, so no get_settings patch is needed.
    """
    mocker.patch("app.core.redis.get_redis", return_value=_stateful_redis("TEACHING"))

    from app.modules.tutor.state_machine.graph import dispatch_event

    sid = "s-flow"

    r1 = await dispatch_event(sid, "segment_complete")
    assert r1["current_state"] == TutorState.CHECKING_IN

    r2 = await dispatch_event(sid, "low_checkin_score")
    assert r2["current_state"] == TutorState.QUIZZING

    r3 = await dispatch_event(sid, "quiz_failed")
    assert r3["current_state"] == TutorState.TEACH_BACK

    r4 = await dispatch_event(sid, "teachback_complete")
    assert r4["current_state"] == TutorState.TEACHING


# ── Service-layer caller ─────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_start_session_dispatches_session_start(mocker) -> None:
    """AC6: service.start_session drives the session_start dispatch."""
    mock_dispatch = AsyncMock()
    mocker.patch("app.modules.tutor.state_machine.graph.dispatch_event", mock_dispatch)

    from app.modules.tutor.service import start_session

    await start_session("s-svc")

    mock_dispatch.assert_called_once_with("s-svc", "session_start")


# ── full_state_machine real logic: fatigue fix, message selection, Langfuse, flags (s2-1) ──


@pytest.mark.unit
async def test_fatigue_detected_sets_fatigue_fired_flag(mocker) -> None:
    """AC1/AC2: fatigue_detected now records the fatigue flag (intervention_type derived = fatigue)."""
    _patch_settings(mocker)
    redis = _keyed_redis("s-ff", state="TEACHING", exists=0)
    mocker.patch("app.core.redis.get_redis", return_value=redis)

    from app.modules.tutor.state_machine.graph import dispatch_event

    result = await dispatch_event("s-ff", "fatigue_detected")

    assert result["current_state"] == TutorState.INTERVENING
    redis.set.assert_any_call("tutor_fatigue_fired:s-ff", "1", ex=_STATE_TTL)


@pytest.mark.unit
async def test_distraction_detected_increments_count(mocker) -> None:
    """AC2: distraction_detected increments the distraction counter (intervention_type = distraction)."""
    _patch_settings(mocker)
    redis = _keyed_redis("s-dc", state="TEACHING", count="0", exists=0)
    mocker.patch("app.core.redis.get_redis", return_value=redis)

    from app.modules.tutor.state_machine.graph import dispatch_event

    result = await dispatch_event("s-dc", "distraction_detected")

    assert result["current_state"] == TutorState.INTERVENING
    redis.incr.assert_any_call("tutor_distraction_count:s-dc")


@pytest.mark.unit
async def test_intervention_message_selected_from_payload(mocker) -> None:
    """AC3: intervening_node selects the pre-generated message for the active type from the payload."""
    _patch_settings(mocker)
    redis = _keyed_redis("s-msg", state="TEACHING", exists=0)
    mocker.patch("app.core.redis.get_redis", return_value=redis)

    from app.modules.tutor.state_machine.graph import dispatch_event

    payload = {
        "intervention_messages": {
            "fatigue": ["rest your eyes", "take a break", "stretch"],
            "distraction": ["focus up"],
            "confusion": ["let's revisit"],
        }
    }
    result = await dispatch_event("s-msg", "fatigue_detected", payload=payload)

    assert result["current_state"] == TutorState.INTERVENING
    assert result["intervention_message"] == "rest your eyes"


@pytest.mark.unit
async def test_intervention_message_none_when_absent(mocker) -> None:
    """AC4: no package supplied → intervention_message is None, recording/transition still happen."""
    _patch_settings(mocker)
    redis = _keyed_redis("s-nomsg", state="TEACHING", count="0", exists=0)
    mocker.patch("app.core.redis.get_redis", return_value=redis)

    from app.modules.tutor.state_machine.graph import dispatch_event

    result = await dispatch_event("s-nomsg", "distraction_detected")

    assert result["current_state"] == TutorState.INTERVENING
    assert result["intervention_message"] is None


@pytest.mark.unit
async def test_langfuse_trace_called_on_dispatch(mocker) -> None:
    """_trace_dispatch is called once per dispatch."""
    mocker.patch("app.core.redis.get_redis", return_value=_redis(None))
    trace_spy = mocker.patch(
        "app.modules.tutor.state_machine.graph._trace_dispatch",
        return_value=None,
    )

    from app.modules.tutor.state_machine.graph import dispatch_event

    await dispatch_event("s-lf", "session_start")

    trace_spy.assert_called_once()


@pytest.mark.unit
async def test_langfuse_failure_does_not_break_dispatch(mocker) -> None:
    """A tracing failure must never break a dispatch (best-effort, try/except in dispatch_event)."""
    mocker.patch("app.core.redis.get_redis", return_value=_redis(None))
    mocker.patch(
        "app.modules.tutor.state_machine.graph._trace_dispatch",
        side_effect=RuntimeError("simulated trace failure"),
    )

    from app.modules.tutor.state_machine.graph import dispatch_event

    result = await dispatch_event("s-lf-fail", "session_start")

    assert result["current_state"] == TutorState.TEACHING


@pytest.mark.unit
async def test_teaching_clears_in_teachback(mocker) -> None:
    """AC6: teaching_node resets the in_teachback flag to False."""
    mocker.patch("app.core.redis.get_redis", return_value=_redis(None))

    from app.modules.tutor.state_machine.graph import dispatch_event

    result = await dispatch_event("s-itb-false", "session_start")

    assert result["in_teachback"] is False


@pytest.mark.unit
async def test_teach_back_sets_in_teachback(mocker) -> None:
    """AC6: teach_back_node sets the in_teachback flag True (guard signal)."""
    mocker.patch("app.core.redis.get_redis", return_value=_redis("QUIZZING"))

    from app.modules.tutor.state_machine.graph import dispatch_event

    result = await dispatch_event("s-itb-true", "quiz_failed")

    assert result["in_teachback"] is True


def _stateful_full_redis(initial: str) -> AsyncMock:
    """Stateful Redis for the full intervention cycle: live tutor_state + count='0' + no cooldown."""
    store = {"tutor_state": initial}
    redis = AsyncMock()

    async def _get(key: str):
        if key.startswith("tutor_state:"):
            return store["tutor_state"]
        if key.startswith("tutor_distraction_count:"):
            return "0"
        return None

    async def _set(key: str, value, **_kw):
        if key.startswith("tutor_state:"):
            store["tutor_state"] = value

    redis.get = AsyncMock(side_effect=_get)
    redis.set = AsyncMock(side_effect=_set)
    redis.exists = AsyncMock(return_value=0)
    return redis


@pytest.mark.unit
async def test_full_intervention_cycle_step_through(mocker) -> None:
    """AC7: IDLE → TEACHING → INTERVENING → TEACHING flows with no errors."""
    _patch_settings(mocker)
    mocker.patch("app.core.redis.get_redis", return_value=_stateful_full_redis("IDLE"))

    from app.modules.tutor.state_machine.graph import dispatch_event

    sid = "s-cycle"

    r1 = await dispatch_event(sid, "session_start")
    assert r1["current_state"] == TutorState.TEACHING

    r2 = await dispatch_event(sid, "distraction_detected")
    assert r2["current_state"] == TutorState.INTERVENING

    r3 = await dispatch_event(sid, "intervention_complete")
    assert r3["current_state"] == TutorState.TEACHING


@pytest.mark.unit
async def test_explicit_intervention_type_overrides_event_default(mocker) -> None:
    """AC1: an explicit payload intervention_type wins over the event-derived one."""
    _patch_settings(mocker)
    redis = _keyed_redis("s-override", state="TEACHING", count="0", exists=0)
    mocker.patch("app.core.redis.get_redis", return_value=redis)

    from app.modules.tutor.state_machine.graph import dispatch_event

    # Event would derive "distraction", but the caller explicitly says "confusion".
    payload = {
        "intervention_type": "confusion",
        "intervention_messages": {
            "confusion": ["clarify this"],
            "distraction": ["focus up"],
            "fatigue": ["rest"],
        },
    }
    result = await dispatch_event("s-override", "distraction_detected", payload=payload)

    assert result["current_state"] == TutorState.INTERVENING
    assert result["intervention_message"] == "clarify this"  # confusion won, not distraction


@pytest.mark.unit
async def test_intervention_message_selected_for_confusion(mocker) -> None:
    """AC3: teachback_failed (→ confusion) selects the confusion message set."""
    _patch_settings(mocker)
    redis = _keyed_redis("s-conf", state="TEACH_BACK", exists=0)
    mocker.patch("app.core.redis.get_redis", return_value=redis)

    from app.modules.tutor.state_machine.graph import dispatch_event

    payload = {
        "intervention_messages": {
            "confusion": ["let's revisit that"],
            "distraction": ["focus up"],
            "fatigue": ["rest"],
        }
    }
    result = await dispatch_event("s-conf", "teachback_failed", payload=payload)

    assert result["current_state"] == TutorState.INTERVENING
    assert result["intervention_message"] == "let's revisit that"


@pytest.mark.unit
async def test_fatigue_fires_once_then_blocked(mocker) -> None:
    """AC2 end-to-end: fatigue fires once (real flag write) → after returning, a second
    fatigue_detected is blocked by the once-guard reading that flag."""
    _patch_settings(mocker)

    store = {"tutor_state": "TEACHING", "fatigue_fired": False}
    redis = AsyncMock()

    async def _get(key: str):
        return store["tutor_state"] if key.startswith("tutor_state:") else None

    async def _set(key: str, value, **_kw):
        if key.startswith("tutor_state:"):
            store["tutor_state"] = value
        elif key.startswith("tutor_fatigue_fired:"):
            store["fatigue_fired"] = True

    async def _exists(key: str):
        if key.startswith("tutor_fatigue_fired:"):
            return 1 if store["fatigue_fired"] else 0
        return 0

    redis.get = AsyncMock(side_effect=_get)
    redis.set = AsyncMock(side_effect=_set)
    redis.exists = AsyncMock(side_effect=_exists)
    mocker.patch("app.core.redis.get_redis", return_value=redis)

    from app.modules.tutor.state_machine.graph import dispatch_event

    sid = "s-fatonce"

    r1 = await dispatch_event(sid, "fatigue_detected")
    assert r1["current_state"] == TutorState.INTERVENING  # fires the first time

    back = await dispatch_event(sid, "intervention_complete")
    assert back["current_state"] == TutorState.TEACHING

    r2 = await dispatch_event(sid, "fatigue_detected")
    assert r2["current_state"] == TutorState.TEACHING  # blocked — fatigue already fired


# ── state_change WebSocket broadcast ─────────────────────────────────────────


@pytest.mark.unit
async def test_state_change_broadcast_fires_on_real_transition(mocker) -> None:
    """dispatch_event broadcasts state_change when from_state != to_state."""
    mocker.patch("app.core.redis.get_redis", return_value=_redis(None))
    mock_send = AsyncMock()
    mocker.patch("app.core.websocket.manager.send", mock_send)

    from app.modules.tutor.state_machine.graph import dispatch_event

    await dispatch_event("s-sc1", "session_start")

    mock_send.assert_awaited_once()
    call_args = mock_send.call_args
    assert call_args[0][0] == "s-sc1"
    msg = call_args[0][1]
    assert msg["type"] == "state_change"
    assert msg["payload"]["from_state"] == "IDLE"
    assert msg["payload"]["to_state"] == "TEACHING"
    assert msg["payload"]["session_id"] == "s-sc1"


@pytest.mark.unit
async def test_state_change_broadcast_silent_on_no_transition(mocker) -> None:
    """dispatch_event does NOT broadcast when state does not change (e.g. noop from TEACHING)."""
    mocker.patch("app.core.redis.get_redis", return_value=_redis("TEACHING"))
    mock_send = AsyncMock()
    mocker.patch("app.core.websocket.manager.send", mock_send)

    from app.modules.tutor.state_machine.graph import dispatch_event

    await dispatch_event("s-sc2", "noop")

    mock_send.assert_not_awaited()


@pytest.mark.unit
async def test_state_change_broadcast_payload_matches_ws_ts_contract(mocker) -> None:
    """Payload shape must match the frozen StateChangeMessage in ws.ts exactly."""
    mocker.patch("app.core.redis.get_redis", return_value=_redis("TEACHING"))
    _patch_settings(mocker)
    mock_send = AsyncMock()
    mocker.patch("app.core.websocket.manager.send", mock_send)

    from app.modules.tutor.state_machine.graph import dispatch_event

    await dispatch_event("s-sc3", "segment_complete")

    mock_send.assert_awaited_once()
    msg = mock_send.call_args[0][1]
    payload = msg["payload"]
    assert set(payload.keys()) == {"session_id", "from_state", "to_state"}
    assert isinstance(payload["session_id"], str)
    assert isinstance(payload["from_state"], str)
    assert isinstance(payload["to_state"], str)


# ── Story 4-20: QUIZZING deadline enforcement ─────────────────────────────────


def _deadline_redis(sid: str, *, state: str = "TEACHING", qa_secs: str | None = "300") -> AsyncMock:
    """Key-aware Redis for deadline tests.

    GET returns *state* for ``tutor_state:{sid}``, *qa_secs* for
    ``session:{sid}:qa_phase_seconds``, and None for everything else.
    SET side-effect updates the tutor_state store so chained dispatches see
    the post-transition value.
    """
    store: dict[str, str] = {f"tutor_state:{sid}": state}
    redis = AsyncMock()

    async def _get(key: str):
        if key == f"session:{sid}:qa_phase_seconds":
            return qa_secs
        return store.get(key)

    async def _set(key: str, value, **kw):
        store[key] = str(value)

    redis.get = AsyncMock(side_effect=_get)
    redis.set = AsyncMock(side_effect=_set)
    return redis


@pytest.mark.unit
async def test_quizzing_node_writes_quiz_deadline_at(mocker) -> None:
    """AC1: entering QUIZZING writes quiz_deadline_at = int(time.time()) + qa_phase_seconds."""
    import time as _time

    sid = "s-qdl-write"
    before = int(_time.time())
    redis = _deadline_redis(sid, qa_secs="300")
    mocker.patch("app.core.redis.get_redis", return_value=redis)

    from app.modules.tutor.state_machine.graph import dispatch_event

    await dispatch_event(sid, "quiz_trigger")

    after = int(_time.time())
    deadline_calls = [c for c in redis.set.call_args_list if "quiz_deadline_at" in c.args[0]]
    assert len(deadline_calls) == 1, "quiz_deadline_at must be written exactly once"
    written = int(deadline_calls[0].args[1])
    assert before + 300 <= written <= after + 300
    assert deadline_calls[0].kwargs.get("ex") == 86400


@pytest.mark.unit
async def test_quizzing_node_uses_t1_qa_seconds(mocker) -> None:
    """AC1: T1 tier qa_phase_seconds (600 s) is honoured — deadline is +600 s."""
    import time as _time

    sid = "s-qdl-t1"
    before = int(_time.time())
    redis = _deadline_redis(sid, qa_secs="600")
    mocker.patch("app.core.redis.get_redis", return_value=redis)

    from app.modules.tutor.state_machine.graph import dispatch_event

    await dispatch_event(sid, "quiz_trigger")

    after = int(_time.time())
    deadline_calls = [c for c in redis.set.call_args_list if "quiz_deadline_at" in c.args[0]]
    assert len(deadline_calls) == 1
    written = int(deadline_calls[0].args[1])
    assert before + 600 <= written <= after + 600


@pytest.mark.unit
async def test_quizzing_node_fallback_300_when_qa_seconds_missing(mocker) -> None:
    """AC1: missing qa_phase_seconds key → quizzing_node falls back to 300 s (T2 default)."""
    import time as _time

    sid = "s-qdl-fb"
    before = int(_time.time())
    redis = _deadline_redis(sid, qa_secs=None)  # no qa_phase_seconds key
    mocker.patch("app.core.redis.get_redis", return_value=redis)

    from app.modules.tutor.state_machine.graph import dispatch_event

    await dispatch_event(sid, "quiz_trigger")

    after = int(_time.time())
    deadline_calls = [c for c in redis.set.call_args_list if "quiz_deadline_at" in c.args[0]]
    assert len(deadline_calls) == 1
    written = int(deadline_calls[0].args[1])
    assert before + 300 <= written <= after + 300


@pytest.mark.unit
async def test_advance_tutor_state_expired_deadline_auto_quiz_complete(mocker) -> None:
    """AC4: expired quiz_deadline_at → advance_tutor_state auto-dispatches quiz_complete via
    the REAL FSM (dispatch_event not mocked) → session lands in TEACHING."""
    import time as _time

    sid = "s-qdl-e2e"
    expired = str(int(_time.time()) - 60)

    store: dict = {"state": "QUIZZING"}
    redis = AsyncMock()

    async def _get(key: str):
        if key == f"tutor_state:{sid}":
            return store["state"]
        if key == f"session:{sid}:quiz_deadline_at":
            return expired
        return None

    async def _set(key: str, value, **kw):
        if key.startswith("tutor_state:"):
            store["state"] = str(value)

    redis.get = AsyncMock(side_effect=_get)
    redis.set = AsyncMock(side_effect=_set)
    redis.delete = AsyncMock(return_value=1)
    mocker.patch("app.core.redis.get_redis", return_value=redis)

    from app.modules.tutor.service import advance_tutor_state

    await advance_tutor_state(sid, "quiz_complete")

    assert store["state"] == "TEACHING"
    redis.delete.assert_awaited_once_with(f"session:{sid}:quiz_deadline_at")


@pytest.mark.unit
async def test_advance_tutor_state_not_expired_deadline_normal_flow(mocker) -> None:
    """AC5/AC6: deadline not yet expired → student quiz_complete dispatched normally → TEACHING."""
    import time as _time

    sid = "s-qdl-active"
    future = str(int(_time.time()) + 3600)

    store: dict = {"state": "QUIZZING"}
    redis = AsyncMock()

    async def _get(key: str):
        if key == f"tutor_state:{sid}":
            return store["state"]
        if key == f"session:{sid}:quiz_deadline_at":
            return future
        return None

    async def _set(key: str, value, **kw):
        if key.startswith("tutor_state:"):
            store["state"] = str(value)

    redis.get = AsyncMock(side_effect=_get)
    redis.set = AsyncMock(side_effect=_set)
    mocker.patch("app.core.redis.get_redis", return_value=redis)

    from app.modules.tutor.service import advance_tutor_state

    await advance_tutor_state(sid, "quiz_complete")

    assert store["state"] == "TEACHING"
    redis.delete.assert_not_called()


@pytest.mark.unit
async def test_advance_tutor_state_missing_deadline_no_auto_advance(mocker) -> None:
    """AC6: missing quiz_deadline_at → _quiz_deadline_expired returns False → normal dispatch."""
    sid = "s-qdl-none"

    store: dict = {"state": "QUIZZING"}
    redis = AsyncMock()

    async def _get(key: str):
        if key == f"tutor_state:{sid}":
            return store["state"]
        return None  # no quiz_deadline_at

    async def _set(key: str, value, **kw):
        if key.startswith("tutor_state:"):
            store["state"] = str(value)

    redis.get = AsyncMock(side_effect=_get)
    redis.set = AsyncMock(side_effect=_set)
    mocker.patch("app.core.redis.get_redis", return_value=redis)

    from app.modules.tutor.service import advance_tutor_state

    await advance_tutor_state(sid, "quiz_complete")

    assert store["state"] == "TEACHING"
    redis.delete.assert_not_called()
