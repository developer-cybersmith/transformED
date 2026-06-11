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
from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

logger = logging.getLogger(__name__)

_STATE_TTL = 86_400  # 24 h


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
    return state_raw == TutorState.TEACH_BACK


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

    await _persist_state(session_id, TutorState.INTERVENING)
    return {**state, "current_state": TutorState.INTERVENING}


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
    """Route out of TEACH_BACK. Interventions during TEACH_BACK are blocked."""
    event = state.get("event", "")
    if event == "teachback_failed":
        return "intervening"
    return "teaching"


async def route_from_session_end(state: TutorMachineState) -> str:
    """SESSION_END → IDLE on session_reset, otherwise end."""
    event = state.get("event", "")
    if event == "session_reset":
        return "idle"
    return END  # type: ignore[return-value]


# ── Graph construction ────────────────────────────────────────────────────────


def _build_tutor_graph() -> Any:
    """Build and compile the tutor state machine graph.

    Uses MemorySaver — PostgresSaver is BANNED per PRD §24.
    """
    checkpointer = MemorySaver()  # PostgresSaver is BANNED per PRD §24

    graph: StateGraph = StateGraph(TutorMachineState)

    # Register all 7 state nodes
    graph.add_node("idle", idle_node)
    graph.add_node("teaching", teaching_node)
    graph.add_node("intervening", intervening_node)
    graph.add_node("checking_in", checking_in_node)
    graph.add_node("quizzing", quizzing_node)
    graph.add_node("teach_back", teach_back_node)
    graph.add_node("session_end", session_end_node)

    # Entry point
    graph.set_entry_point("idle")

    # Simple (unconditional) edges
    # IDLE → TEACHING on session_start (handled via conditional from idle)
    graph.add_edge("idle", "teaching")  # session_start always moves to TEACHING

    # INTERVENING → TEACHING (intervention_complete)
    graph.add_edge("intervening", "teaching")

    # All conditional routing
    graph.add_conditional_edges(
        "teaching",
        route_from_teaching,
        {
            "teaching": "teaching",
            "intervening": "intervening",
            "checking_in": "checking_in",
            "quizzing": "quizzing",
            "session_end": "session_end",
        },
    )

    graph.add_conditional_edges(
        "checking_in",
        route_from_checking_in,
        {
            "teaching": "teaching",
            "quizzing": "quizzing",
        },
    )

    graph.add_conditional_edges(
        "quizzing",
        route_from_quizzing,
        {
            "teaching": "teaching",
            "teach_back": "teach_back",
        },
    )

    graph.add_conditional_edges(
        "teach_back",
        route_from_teach_back,
        {
            "teaching": "teaching",
            "intervening": "intervening",
        },
    )

    graph.add_conditional_edges(
        "session_end",
        route_from_session_end,
        {
            "idle": "idle",
            END: END,
        },
    )

    return graph.compile(checkpointer=checkpointer)


_compiled_tutor_graph: Any | None = None


def get_tutor_graph() -> Any:
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
        "intervention_type": payload.get("intervention_type") if payload else None,
        "error": None,
    }

    config = {"configurable": {"thread_id": session_id}}
    result: TutorMachineState = await graph.ainvoke(input_state, config=config)
    return result


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
        return await redis.get(f"tutor_state:{session_id}")
    except Exception:  # noqa: BLE001
        logger.warning("Failed to read tutor state for session %s", session_id)
        return None
