"""
Tutor state machine — LangGraph implementation.

States (7)
----------
IDLE            Session not yet started
TEACHING        Actively delivering lesson content
INTERVENING     Running an intervention overlay (distraction / fatigue)
CHECKING_IN     Brief comprehension check-in
QUIZZING        Formal quiz block
TEACH_BACK      Student explains concept back to the tutor
SESSION_END     Session complete

Transitions (14, per PRD §10)
------------------------------
IDLE         → TEACHING         on: session_start
TEACHING     → INTERVENING      on: distraction_detected (CES < threshold, distraction count < max)
TEACHING     → INTERVENING      on: fatigue_detected     (fires once per session)
TEACHING     → CHECKING_IN      on: segment_complete
TEACHING     → QUIZZING         on: quiz_trigger
TEACHING     → SESSION_END      on: lesson_complete
INTERVENING  → TEACHING         on: intervention_complete
CHECKING_IN  → TEACHING         on: checkin_complete
CHECKING_IN  → QUIZZING         on: low_checkin_score
QUIZZING     → TEACHING         on: quiz_complete
QUIZZING     → TEACH_BACK       on: quiz_failed
TEACH_BACK   → TEACHING         on: teachback_complete
TEACH_BACK   → INTERVENING      on: teachback_failed
SESSION_END  → IDLE             on: session_reset

Guard rules
-----------
- CES monitoring only applies in TEACHING state
- 2-minute cooldown between successive interventions (Redis TTL key)
- Max 3 distraction interventions per session (Redis counter)
- Fatigue fires at most once per session (Redis flag)
- Teach-back in progress blocks ALL interventions

Redis key schema (24 h TTL on all keys)
-----------------------------------------
tutor_state:{session_id}              str   current state name
tutor_ces:{session_id}                float running CES score
tutor_distraction_count:{session_id}  int   number of distraction interventions fired
tutor_fatigue_fired:{session_id}      "1"   present if fatigue has already fired
tutor_cooldown:{session_id}           "1"   present (with TTL) during cooldown window
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any, TypedDict, cast

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

logger = logging.getLogger(__name__)

_STATE_TTL = 86_400  # 24 h

# Maps an intervention-triggering event to the intervention_type it records / selects a message for.
# Used by dispatch_event so the FSM records the RIGHT intervention (the fatigue path previously left
# intervention_type=None → tutor_fatigue_fired was never set). Valid types match the LessonPackage
# intervention_messages schema: distraction | confusion | fatigue.
_EVENT_INTERVENTION_TYPE = {
    "distraction_detected": "distraction",
    "fatigue_detected": "fatigue",
    "teachback_failed": "confusion",
}


# ── State definitions ─────────────────────────────────────────────────────────


class TutorState(StrEnum):
    IDLE = "IDLE"
    TEACHING = "TEACHING"
    INTERVENING = "INTERVENING"
    CHECKING_IN = "CHECKING_IN"
    QUIZZING = "QUIZZING"
    TEACH_BACK = "TEACH_BACK"
    SESSION_END = "SESSION_END"


class TutorMachineState(TypedDict, total=False):
    """LangGraph state bag for the tutor state machine."""

    session_id: str
    user_id: str
    lesson_id: str
    current_state: str  # TutorState value
    ces_score: float
    distraction_count: int
    fatigue_fired: bool
    in_teachback: bool  # guard: never interrupt TEACH_BACK
    event: str  # the triggering event name
    event_payload: dict[str, Any]
    intervention_type: str | None
    intervention_message: str | None  # pre-generated message selected at intervention time
    error: str | None


# ── Guard functions ───────────────────────────────────────────────────────────


async def _can_intervene_distraction(session_id: str) -> bool:
    """Guard: distraction intervention allowed only if:
    - Currently in cooldown? → No
    - Distraction count < max? → Yes
    """
    from app.config import get_settings
    from app.core.redis import get_redis

    settings = get_settings()
    redis = get_redis()

    cooldown_key = f"tutor_cooldown:{session_id}"
    count_key = f"tutor_distraction_count:{session_id}"

    in_cooldown = await redis.exists(cooldown_key)
    if in_cooldown:
        return False

    count_raw = await redis.get(count_key)
    count = int(count_raw) if count_raw else 0
    return count < settings.max_distraction_per_session


async def _can_intervene_fatigue(session_id: str) -> bool:
    """Guard: fatigue fires at most once per session."""
    from app.core.redis import get_redis

    redis = get_redis()
    fatigue_key = f"tutor_fatigue_fired:{session_id}"
    already_fired = await redis.exists(fatigue_key)
    return not bool(already_fired)


async def _is_in_teachback(session_id: str) -> bool:
    """Guard: return True if the session is currently in TEACH_BACK state."""
    from app.core.redis import get_redis

    redis = get_redis()
    state_key = f"tutor_state:{session_id}"
    state_raw = await redis.get(state_key)
    return bool(state_raw == TutorState.TEACH_BACK)


# ── Node implementations ──────────────────────────────────────────────────────


async def idle_node(state: TutorMachineState) -> TutorMachineState:
    """IDLE state: session not yet started."""
    logger.debug("[tutor:%s] → IDLE", state.get("session_id"))
    await _persist_state(state.get("session_id", ""), TutorState.IDLE)
    return {**state, "current_state": TutorState.IDLE}


async def teaching_node(state: TutorMachineState) -> TutorMachineState:
    """TEACHING state: actively delivering lesson content."""
    session_id = state.get("session_id", "")
    logger.debug("[tutor:%s] → TEACHING", session_id)
    await _persist_state(session_id, TutorState.TEACHING)
    return {**state, "current_state": TutorState.TEACHING, "in_teachback": False}


async def intervening_node(state: TutorMachineState) -> TutorMachineState:
    """INTERVENING state: overlay intervention is displayed."""
    session_id = state.get("session_id", "")
    intervention_type = state.get("intervention_type", "distraction")
    logger.info("[tutor:%s] → INTERVENING (type=%s)", session_id, intervention_type)

    from app.config import get_settings
    from app.core.redis import get_redis

    settings = get_settings()
    redis = get_redis()

    # Record the intervention
    if intervention_type == "distraction":
        await redis.incr(f"tutor_distraction_count:{session_id}")
        await redis.expire(f"tutor_distraction_count:{session_id}", _STATE_TTL)

    elif intervention_type == "fatigue":
        await redis.set(f"tutor_fatigue_fired:{session_id}", "1", ex=_STATE_TTL)

    # Start cooldown window
    cooldown_key = f"tutor_cooldown:{session_id}"
    await redis.set(cooldown_key, "1", ex=settings.intervention_cooldown_seconds)

    # Select the pre-generated intervention message for this type from the segment's
    # intervention_messages (supplied via the event payload). The DB/Redis LessonPackage fetch and
    # WS delivery to the client are the intervention_selection task; here we just pick the message.
    messages = (state.get("event_payload") or {}).get("intervention_messages") or {}
    chosen = messages.get(intervention_type) or []
    intervention_message = chosen[0] if chosen else None

    await _persist_state(session_id, TutorState.INTERVENING)
    return {
        **state,
        "current_state": TutorState.INTERVENING,
        "intervention_message": intervention_message,
    }


async def checking_in_node(state: TutorMachineState) -> TutorMachineState:
    """CHECKING_IN state: brief comprehension check."""
    session_id = state.get("session_id", "")
    logger.debug("[tutor:%s] → CHECKING_IN", session_id)
    await _persist_state(session_id, TutorState.CHECKING_IN)
    return {**state, "current_state": TutorState.CHECKING_IN}


async def quizzing_node(state: TutorMachineState) -> TutorMachineState:
    """QUIZZING state: formal quiz block."""
    session_id = state.get("session_id", "")
    logger.debug("[tutor:%s] → QUIZZING", session_id)
    await _persist_state(session_id, TutorState.QUIZZING)
    return {**state, "current_state": TutorState.QUIZZING}


async def teach_back_node(state: TutorMachineState) -> TutorMachineState:
    """TEACH_BACK state: student explains concept back to the system."""
    session_id = state.get("session_id", "")
    logger.debug("[tutor:%s] → TEACH_BACK", session_id)
    await _persist_state(session_id, TutorState.TEACH_BACK)
    return {**state, "current_state": TutorState.TEACH_BACK, "in_teachback": True}


async def session_end_node(state: TutorMachineState) -> TutorMachineState:
    """SESSION_END state: cleanup and final scoring."""
    session_id = state.get("session_id", "")
    logger.info("[tutor:%s] → SESSION_END", session_id)
    await _persist_state(session_id, TutorState.SESSION_END)
    return {**state, "current_state": TutorState.SESSION_END}


# ── Routing (conditional edges) ───────────────────────────────────────────────


async def route_from_teaching(state: TutorMachineState) -> str:
    """Decide next node from TEACHING based on the incoming event + guards."""
    session_id = state.get("session_id", "")
    event = state.get("event", "")

    if event == "distraction_detected":
        # Guard: cooldown and max-distraction check
        if await _can_intervene_distraction(session_id):
            return "intervening"
        logger.debug("[tutor:%s] distraction_detected but guard blocked intervention", session_id)
        return "teaching"  # Stay in TEACHING — cooldown or max reached

    if event == "fatigue_detected":
        if await _can_intervene_fatigue(session_id):
            return "intervening"
        logger.debug("[tutor:%s] fatigue_detected but already fired this session", session_id)
        return "teaching"

    if event == "segment_complete":
        return "checking_in"

    if event == "quiz_trigger":
        return "quizzing"

    if event == "lesson_complete":
        return "session_end"

    return "teaching"  # Default: stay teaching


async def route_from_checking_in(state: TutorMachineState) -> str:
    """Route out of CHECKING_IN based on the check-in result event."""
    event = state.get("event", "")
    if event == "low_checkin_score":
        return "quizzing"
    return "teaching"


async def route_from_quizzing(state: TutorMachineState) -> str:
    """Route out of QUIZZING based on quiz result."""
    event = state.get("event", "")
    if event == "quiz_failed":
        return "teach_back"
    return "teaching"


async def route_from_teach_back(state: TutorMachineState) -> str:
    """Route out of TEACH_BACK.

    CLAUDE.md §10 — NEVER interrupt mid-TEACH_BACK: only an explicit teach-back outcome leaves this
    state. Any other event (including ``distraction_detected`` / ``fatigue_detected``) is
    suppressed — the FSM stays in TEACH_BACK. This is the authoritative routing-level enforcement
    of the guard.
    """
    event = state.get("event", "")
    if event == "teachback_complete":
        return "teaching"
    if event == "teachback_failed":
        return "intervening"
    return "teach_back"  # guard: interventions blocked during teach-back


async def route_from_session_end(state: TutorMachineState) -> str:
    """SESSION_END → IDLE on session_reset, otherwise end."""
    event = state.get("event", "")
    if event == "session_reset":
        return "idle"
    return END


async def route_from_idle(state: TutorMachineState) -> str:
    """IDLE → TEACHING on session_start; otherwise stay IDLE."""
    return "teaching" if state.get("event") == "session_start" else "idle"


async def route_from_intervening(state: TutorMachineState) -> str:
    """INTERVENING → TEACHING on intervention_complete; otherwise stay INTERVENING."""
    return "teaching" if state.get("event") == "intervention_complete" else "intervening"


# Transition table: current state → its routing function. dispatch_event applies exactly
# ONE transition per call (entry router → one node → END), so the graph never self-loops.
_ROUTE_BY_STATE = {
    TutorState.IDLE: route_from_idle,
    TutorState.TEACHING: route_from_teaching,
    TutorState.INTERVENING: route_from_intervening,
    TutorState.CHECKING_IN: route_from_checking_in,
    TutorState.QUIZZING: route_from_quizzing,
    TutorState.TEACH_BACK: route_from_teach_back,
    TutorState.SESSION_END: route_from_session_end,
}


async def route_entry(state: TutorMachineState) -> str:
    """Conditional entry point: route from the CURRENT state based on the event.

    This is what makes the FSM apply one transition per dispatch instead of running to
    completion. ``current_state`` is seeded from Redis by ``dispatch_event``.

    A corrupt or stale persisted state (a value not in ``TutorState``) must never crash a
    dispatch — fall back to IDLE so the session self-heals rather than wedging the tutor.
    """
    raw = state.get("current_state") or TutorState.IDLE
    try:
        current = TutorState(raw)
    except ValueError:
        logger.warning(
            "[tutor:%s] unknown persisted state %r — defaulting to IDLE",
            state.get("session_id", ""),
            raw,
        )
        current = TutorState.IDLE
    router = _ROUTE_BY_STATE.get(current, route_from_idle)
    return await router(state)


# ── Graph construction ────────────────────────────────────────────────────────


def _build_tutor_graph() -> Any:  # noqa: ANN401
    """Build and compile the tutor state machine graph.

    Uses MemorySaver — PostgresSaver is BANNED per PRD §24.
    """
    checkpointer = MemorySaver()  # PostgresSaver is BANNED per PRD §24

    graph: StateGraph[Any] = StateGraph(TutorMachineState)

    # Register all 7 state nodes
    graph.add_node("idle", idle_node)
    graph.add_node("teaching", teaching_node)
    graph.add_node("intervening", intervening_node)
    graph.add_node("checking_in", checking_in_node)
    graph.add_node("quizzing", quizzing_node)
    graph.add_node("teach_back", teach_back_node)
    graph.add_node("session_end", session_end_node)

    # Conditional ENTRY: route from the current state based on the event, run that one
    # node, then END. One transition per dispatch — no self-loops, no run-to-completion.
    graph.set_conditional_entry_point(
        route_entry,
        {
            "idle": "idle",
            "teaching": "teaching",
            "intervening": "intervening",
            "checking_in": "checking_in",
            "quizzing": "quizzing",
            "teach_back": "teach_back",
            "session_end": "session_end",
            END: END,
        },
    )

    # Every node is terminal: it persists its state and the run ends.
    for node in (
        "idle",
        "teaching",
        "intervening",
        "checking_in",
        "quizzing",
        "teach_back",
        "session_end",
    ):
        graph.add_edge(node, END)

    return graph.compile(checkpointer=checkpointer)


_compiled_tutor_graph: Any | None = None


def get_tutor_graph() -> Any:  # noqa: ANN401
    """Return the cached compiled tutor state machine graph."""
    global _compiled_tutor_graph  # noqa: PLW0603
    if _compiled_tutor_graph is None:
        _compiled_tutor_graph = _build_tutor_graph()
    return _compiled_tutor_graph


# ── Public API ────────────────────────────────────────────────────────────────


async def dispatch_event(
    session_id: str,
    event: str,
    payload: dict[str, Any] | None = None,
    user_id: str = "",
    lesson_id: str = "",
) -> TutorMachineState:
    """Dispatch an event into the tutor state machine.

    Args:
        session_id: Live session UUID.
        event:      Event name (e.g. "distraction_detected", "segment_complete").
        payload:    Optional event-specific data.
        user_id:    User UUID (for context only).
        lesson_id:  Lesson UUID (for context only).

    Returns:
        The updated TutorMachineState after the event is processed.
    """
    graph = get_tutor_graph()

    current_raw = await _read_state(session_id)
    current_state_val = current_raw or TutorState.IDLE

    input_state: TutorMachineState = {
        "session_id": session_id,
        "user_id": user_id,
        "lesson_id": lesson_id,
        "current_state": current_state_val,
        "ces_score": 0.0,
        "distraction_count": 0,
        "fatigue_fired": False,
        "in_teachback": current_state_val == TutorState.TEACH_BACK,
        "event": event,
        "event_payload": payload or {},
        # Derive intervention_type from the event when the caller didn't set it explicitly. Without
        # this, fatigue_detected/distraction_detected (dispatched without a payload) left it None
        # and intervening_node recorded neither branch (the fatigue-once flag never got set).
        "intervention_type": (payload.get("intervention_type") if payload else None)
        or _EVENT_INTERVENTION_TYPE.get(event),
        "error": None,
    }

    # recursion_limit is a regression tripwire: with terminal nodes a dispatch is
    # entry-router → one node → END (1 step). Any future self-loop fails fast here
    # with GraphRecursionError instead of hanging.
    config = {"configurable": {"thread_id": session_id}, "recursion_limit": 5}
    result: TutorMachineState = await graph.ainvoke(input_state, config=config)
    _trace_dispatch(session_id, event, result)
    return result


def _trace_dispatch(session_id: str, event: str, result: TutorMachineState | None) -> None:
    """Best-effort Langfuse trace of one dispatch. Observability must NEVER break the FSM, so any
    Langfuse/config failure is swallowed."""
    try:
        from app.core.langfuse import get_langfuse

        # langfuse 4.x removed the client-level `.trace()` method (attr-defined);
        # this whole block is best-effort and any AttributeError is swallowed by
        # the surrounding except, so behavior is unchanged. Types-only suppression.
        get_langfuse().trace(  # type: ignore[attr-defined]
            name="tutor.dispatch_event",
            session_id=session_id,
            input={"event": event},
            output={"current_state": str(result.get("current_state")) if result else None},
        )
    except Exception:  # noqa: BLE001 — tracing is best-effort
        logger.debug("langfuse trace skipped for %s/%s", session_id, event, exc_info=True)


# ── Redis helpers ─────────────────────────────────────────────────────────────


async def _persist_state(session_id: str, state: TutorState) -> None:
    """Write the current tutor state to Redis with a 24 h TTL."""
    try:
        from app.core.redis import get_redis

        redis = get_redis()
        await redis.set(f"tutor_state:{session_id}", state.value, ex=_STATE_TTL)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to persist tutor state for session %s", session_id)


async def _read_state(session_id: str) -> str | None:
    """Read the current tutor state from Redis."""
    try:
        from app.core.redis import get_redis

        redis = get_redis()
        return cast("str | None", await redis.get(f"tutor_state:{session_id}"))
    except Exception:  # noqa: BLE001
        logger.warning("Failed to read tutor state for session %s", session_id)
        return None
