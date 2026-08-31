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

import asyncio
import logging
from enum import StrEnum
from typing import Any, TypedDict, cast

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

logger = logging.getLogger(__name__)

_STATE_TTL = 86_400  # 24 h

# ── Lua script for atomic distraction cap check+increment (D6) ───────────────
# Redis Lua scripts execute atomically in Redis's single-threaded Lua VM, so
# concurrent requests cannot race between the EXISTS/GET read and the INCR write.
#
# KEYS[1] = tutor_cooldown:{session_id}
# KEYS[2] = tutor_distraction_count:{session_id}
# ARGV[1] = max_distraction_per_session (string representation)
# ARGV[2] = TTL for count key in seconds (string representation, matches _STATE_TTL)
_DISTRACTION_GUARD_LUA = """
local in_cooldown = redis.call('EXISTS', KEYS[1])
if in_cooldown == 1 then return 'cooldown' end
local count = tonumber(redis.call('GET', KEYS[2])) or 0
if count >= tonumber(ARGV[1]) then return 'max_reached' end
redis.call('INCR', KEYS[2])
redis.call('EXPIRE', KEYS[2], tonumber(ARGV[2]))
return 'ok'
"""

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
    # NOTE (mypy fix, no behavior change): these two are read via state.get(...) in
    # intervening_node below but no caller currently populates them on dispatch_event's
    # input_state (see service.py's distraction_detected/fatigue_detected dispatch calls) —
    # write_intervention_event today always receives window_index=0 / ces_at_trigger=0.0.
    # Flagged separately; not fixed here (out of scope for a type-annotation pass).
    window_index: int
    last_ces: float


# ── Guard functions ───────────────────────────────────────────────────────────


async def _can_intervene_distraction(  # noqa: ANN401
    session_id: str,
    redis: Any,  # noqa: ANN401
    settings: Any,  # noqa: ANN401
) -> bool:
    """Guard: atomically check-and-increment the distraction cap via Lua (D6).

    Replaces the non-atomic EXISTS + GET two-step with a single redis.eval call.
    Redis executes Lua scripts atomically in its single-threaded VM, so concurrent
    requests cannot race between the read and the increment.

    Returns True only when the Lua script returns 'ok' (meaning: not in cooldown,
    not at cap, and the count was incremented as part of this atomic check).
    Returns False (fail-closed) on any Redis error.
    """
    cooldown_key = f"tutor_cooldown:{session_id}"
    count_key = f"tutor_distraction_count:{session_id}"
    try:
        result = await redis.eval(
            _DISTRACTION_GUARD_LUA,
            2,
            cooldown_key,
            count_key,
            str(settings.max_distraction_per_session),
            str(_STATE_TTL),
        )
        return result in (b"ok", "ok")
    except Exception:  # noqa: BLE001
        logger.warning(
            "[tutor:%s] _can_intervene_distraction redis.eval failed — fail-closed", session_id
        )
        return False


async def _can_intervene_fatigue(session_id: str, redis: Any = None) -> bool:  # noqa: ANN401
    """Gate for fatigue — checks cooldown THEN sets the once-per-session flag atomically.

    PRD §10: a 2-minute cooldown applies after ANY intervention (distraction or fatigue).
    This function checks ``tutor_cooldown:{session_id}`` FIRST (fast-fail) before
    attempting SET-NX on ``tutor_fatigue_fired:{session_id}``, so fatigue cannot fire
    within the 2-minute window of a preceding distraction intervention.

    Sequence:
      1. EXISTS tutor_cooldown:{session_id}  → if True, return False (cooldown active)
      2. SET NX tutor_fatigue_fired:{session_id}  → returns True only for the winning caller

    NOTE: callers MUST NOT separately write ``tutor_fatigue_fired:{session_id}``
    after this returns True — the flag is already set here.

    The EXISTS → SET-NX pair is NOT fully atomic (two Redis round-trips).  In the
    extremely narrow race window where a concurrent intervening_node sets the cooldown
    key between step 1 and step 2, fatigue and a new intervention could both start.
    This is accepted and documented in S3-52 Scale & Load §6: the window is < 1 ms,
    fatigue fires once per session anyway (SET-NX is atomic), and intervening_node
    immediately starts a new cooldown TTL.  If this race is unacceptable in future,
    replace with a single Lua script (EXISTS + SET NX in one eval call).
    """
    if redis is None:
        from app.core.redis import get_redis  # noqa: PLC0415

        redis = get_redis()

    cooldown_key = f"tutor_cooldown:{session_id}"
    fatigue_key = f"tutor_fatigue_fired:{session_id}"

    # Step 1: PRD §10 cooldown check — fast-fail if any intervention is still in window.
    if await redis.exists(cooldown_key):
        return False

    # Step 2: once-per-session atomic gate — only one concurrent caller can win.
    was_set = await redis.set(fatigue_key, "1", ex=_STATE_TTL, nx=True)
    return was_set is not None


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
    return {"current_state": TutorState.IDLE}


async def teaching_node(state: TutorMachineState) -> TutorMachineState:
    """TEACHING state: actively delivering lesson content."""
    session_id = state.get("session_id", "")
    logger.debug("[tutor:%s] → TEACHING", session_id)
    await _persist_state(session_id, TutorState.TEACHING)
    return {"current_state": TutorState.TEACHING, "in_teachback": False}


async def intervening_node(state: TutorMachineState) -> TutorMachineState:
    """INTERVENING state: overlay intervention is displayed."""
    session_id = state.get("session_id", "")
    intervention_type = state.get("intervention_type") or "distraction"
    logger.info("[tutor:%s] → INTERVENING (type=%s)", session_id, intervention_type)

    import time as _time  # noqa: PLC0415

    from app.config import get_settings
    from app.core.redis import get_redis

    settings = get_settings()
    redis = get_redis()

    # Record the intervention.
    # Distraction: count was already incremented atomically by the Lua guard in
    # _can_intervene_distraction (D6). No second INCR here — that would double-count.
    # For fatigue, the flag was already set atomically by _can_intervene_fatigue
    # in service.py (SET NX returned True → we won the race and entered here).
    # Do NOT re-write it: the SET-NX in _can_intervene_fatigue IS the guard.

    # Start cooldown window.
    # nx=True: prevent a concurrent intervention from resetting an already-running cooldown
    # (last-writer-wins would shorten the window; NX keeps the first writer's TTL).
    cooldown_key = f"tutor_cooldown:{session_id}"
    await redis.set(cooldown_key, "1", ex=settings.intervention_cooldown_seconds, nx=True)

    # D63 safety net: independent timeout so a session cannot be trapped in INTERVENING forever
    # if intervention_complete is never dispatched (dropped WS message, or the client not yet
    # implementing dismiss). Read by _intervention_deadline_expired (service.py) from
    # process_attention_signal / advance_tutor_state — same shape as the QUIZZING
    # quiz_deadline_at pattern. Independent of the cooldown key above (that governs time BETWEEN
    # interventions; this governs time WITHIN one).
    deadline = int(_time.time()) + settings.intervention_timeout_seconds
    await redis.set(f"session:{session_id}:intervention_deadline_at", str(deadline), ex=_STATE_TTL)

    # Select the pre-generated intervention message for this type from the segment's
    # intervention_messages (supplied via the event payload). The DB/Redis LessonPackage fetch and
    # WS delivery to the client are the intervention_selection task; here we just pick the message.
    messages = (state.get("event_payload") or {}).get("intervention_messages") or {}
    chosen = messages.get(intervention_type) or []
    intervention_message = chosen[0] if chosen else None
    message_key = chosen[0] if chosen else None  # same value; named for write_intervention_event

    # S3-37 (D12): fire-and-forget DB event write — never blocks the Redis path.
    # Wrapped in try/except so get_supabase() failures (e.g. DB unavailable on startup)
    # are logged and swallowed rather than crashing the FSM transition.
    try:
        import asyncio  # noqa: PLC0415

        from app.core.db import get_supabase  # noqa: PLC0415
        from app.modules.assessment.service import write_intervention_event  # noqa: PLC0415

        asyncio.create_task(
            write_intervention_event(
                session_id,
                intervention_type=intervention_type,
                window_index=int(state.get("window_index") or 0),
                ces_at_trigger=float(state.get("last_ces") or 0.0),
                message_key=message_key,
                supabase=get_supabase(),
            )
        )
    except Exception:
        logger.exception("[tutor:%s] write_intervention_event create_task failed", session_id)

    await _persist_state(session_id, TutorState.INTERVENING)
    return {
        "current_state": TutorState.INTERVENING,
        "intervention_message": intervention_message,
    }


async def checking_in_node(state: TutorMachineState) -> TutorMachineState:
    """CHECKING_IN state: brief comprehension check."""
    session_id = state.get("session_id", "")
    logger.debug("[tutor:%s] → CHECKING_IN", session_id)
    await _persist_state(session_id, TutorState.CHECKING_IN)
    return {"current_state": TutorState.CHECKING_IN}


async def quizzing_node(state: TutorMachineState) -> TutorMachineState:
    """QUIZZING state: formal quiz block."""
    session_id = state.get("session_id", "")
    logger.debug("[tutor:%s] → QUIZZING", session_id)
    await _persist_state(session_id, TutorState.QUIZZING)

    # Record tier-based Q&A deadline (best-effort; never crash the transition).
    try:
        import time as _time  # noqa: PLC0415

        from app.core.redis import get_redis  # noqa: PLC0415

        redis = get_redis()
        qa_raw = await redis.get(f"session:{session_id}:qa_phase_seconds")
        qa_secs = int(qa_raw) if qa_raw else 300  # T2 default
        qa_secs = max(
            30, min(3600, qa_secs)
        )  # clamp: prevent deadline backdating via Redis injection
        deadline = int(_time.time()) + qa_secs
        await redis.set(f"session:{session_id}:quiz_deadline_at", str(deadline), ex=86400)
        logger.info("[tutor:%s] QUIZZING deadline set: +%ds", session_id, qa_secs)
    except Exception:  # noqa: BLE001
        logger.warning(
            "[tutor:%s] quiz_deadline_at write failed — proceeding without deadline", session_id
        )

    return {"current_state": TutorState.QUIZZING}


async def teach_back_node(state: TutorMachineState) -> TutorMachineState:
    """TEACH_BACK state: student explains concept back to the system."""
    session_id = state.get("session_id", "")
    logger.debug("[tutor:%s] → TEACH_BACK", session_id)
    await _persist_state(session_id, TutorState.TEACH_BACK)
    return {"current_state": TutorState.TEACH_BACK, "in_teachback": True}


async def session_end_node(state: TutorMachineState) -> TutorMachineState:
    """SESSION_END state: cleanup and final scoring."""
    import asyncio  # noqa: PLC0415

    session_id = state.get("session_id", "")
    logger.info("[tutor:%s] → SESSION_END", session_id)
    await _persist_state(session_id, TutorState.SESSION_END)

    # S3-35 (D3): fire-and-forget ces_final + ended_at write — never blocks FSM transition.
    try:
        from app.core.db import get_supabase  # noqa: PLC0415
        from app.core.redis import get_redis  # noqa: PLC0415

        asyncio.create_task(
            _finalize_session(session_id, redis=get_redis(), supabase=get_supabase())
        )
    except Exception:
        logger.exception("[tutor:%s] _finalize_session create_task failed", session_id)

    return {"current_state": TutorState.SESSION_END}


# ── Routing (conditional edges) ───────────────────────────────────────────────


async def route_from_teaching(state: TutorMachineState) -> str:
    """Decide next node from TEACHING based on the incoming event + guards."""
    event = state.get("event", "")

    if event == "distraction_detected":
        # Guard already enforced atomically in service.py via _can_intervene_distraction
        # (Lua script checked cooldown + cap and incremented the count before dispatch).
        # route_from_teaching is only reached when the guard passed.
        return "intervening"

    if event == "fatigue_detected":
        # _can_intervene_fatigue already fired atomically in service.py (SET-NX) before
        # dispatch_event was called — routing here means the race was already won.
        return "intervening"

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
    # D116: lesson_complete is a universal terminal event — always route to session_end
    # regardless of current FSM state. complete_session (REST) dispatches this after writing
    # ended_at, making it the reliable trigger for ces_final from any state the student is in
    # when their lesson ends (IDLE if WS never connected, TEACHING normally, or mid-QUIZZING/
    # TEACH_BACK if they finish while a check-in is in progress).
    if state.get("event") == "lesson_complete":
        return "session_end"

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
    try:
        _trace_dispatch(session_id, event, result)
    except Exception:  # noqa: BLE001 — tracing is best-effort; never break the FSM
        logger.debug("_trace_dispatch raised for %s/%s", session_id, event, exc_info=True)

    to_state = result["current_state"]
    if current_state_val != to_state:
        from app.core.websocket import manager  # lazy — avoids circular import

        await manager.send(
            session_id,
            {
                "type": "state_change",
                "payload": {
                    "session_id": session_id,
                    "from_state": str(current_state_val),
                    "to_state": str(to_state),
                },
            },
        )

    return result


def _trace_dispatch(session_id: str, event: str, result: TutorMachineState | None) -> None:
    """Best-effort Langfuse trace of one dispatch. Observability must NEVER break the FSM, so any
    Langfuse/config failure is swallowed.

    Langfuse-skill review round: this previously called the client-level
    `.trace()` method, which Langfuse 4.x removed — every single dispatch has
    been silently untraced since the 4.x upgrade, and the only visible trace
    of that was a DEBUG-level log line nobody reads in production (this
    project's own convention elsewhere is WARNING for a swallowed
    observability failure, precisely so it stays visible). Fixed to this
    pinned SDK version's (4.14.3) real API: `create_event(...)` — a single
    FSM dispatch is a discrete, instantaneous event, not a duration-spanning
    `span` and not a cost-bearing `generation`; `start_observation` has no
    `as_type="event"` overload in this version (confirmed against the
    installed SDK's actual type stubs, not assumed from docs — the docs
    describe a capability this pinned version doesn't have; `create_event`
    is the dedicated method it exposes instead, and takes input/output
    directly since an event has no separate start/end to update between).

    Langfuse-skill self-audit round (fetched best-practices.md +
    sessions.md fresh): the FIRST fix reused `deterministic_trace_context`
    keyed on `session_id`, copying the pipeline's `lesson_id` pattern — that
    was wrong for this call site. A tutor session can run for an hour-plus
    with dozens of dispatches (state checks, interventions, quiz turns);
    forcing every one of them into a single ever-growing trace_id is exactly
    what best-practices.md warns against ("If multiple [units of work] happen
    in sequence... that's where sessions come in. Each step is its own
    trace, and the session ties them together... the per-turn model keeps
    traces small and easy to navigate"). A lesson-generation pipeline run
    IS "one self-contained unit of work" (the doc's own example — "one
    pipeline execution"), so `lesson_id`-seeded `deterministic_trace_context`
    stays correct there; a tutor dispatch is a turn within an ongoing
    session, not a self-contained unit on its own.

    Fixed: each dispatch is now its own trace (no `trace_context` — a fresh
    random trace_id, matching "one trace per turn"), grouped into one
    Langfuse Session via `propagate_attributes(session_id=...)` — the SDK's
    only documented mechanism for setting the first-class `session_id`
    trace attribute (verified against the real reference signatures:
    `start_observation`/`create_event` take no `session_id` kwarg directly;
    `propagate_attributes` is a context manager that sets it via contextvars
    for every observation created within the `with` block, not only ones
    parented through `start_as_current_observation`).
    """
    try:
        from langfuse import propagate_attributes

        from app.core.langfuse import get_langfuse, safe_trace

        langfuse = get_langfuse()
        with propagate_attributes(session_id=session_id):
            safe_trace(
                lambda: langfuse.create_event(
                    name="dispatch-tutor-event",
                    input={"event": event},
                    output={"current_state": str(result.get("current_state")) if result else None},
                    metadata={"session_id": session_id},
                )
            )
    except Exception:  # noqa: BLE001 — tracing is best-effort
        # WARNING, not DEBUG (matches every other provider's swallow pattern)
        # — an observability outage must stay visible in prod logs even
        # though it never breaks the FSM.
        logger.warning("langfuse trace skipped for %s/%s", session_id, event, exc_info=True)


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


# ── S3-35 (D3) — Session finalization ────────────────────────────────────────


async def _finalize_session(session_id: str, *, redis: Any, supabase: Any) -> None:  # noqa: ANN401
    """Write ces_final to the sessions table at SESSION_END.

    Called via asyncio.create_task from session_end_node — fire-and-forget.
    DB failures are logged at ERROR and captured to Sentry — never re-raised.

    ces_final = average of the Redis ces_history values (rounded to 2 dp).
    If history is empty, ces_final = None (distinguishable from zero engagement).
    BOUNDED: lrange 0..9 reads at most _CES_HISTORY_MAX=10 entries.

    D116: ended_at is intentionally NOT written here. complete_session (REST) owns
    that field and has already written it before dispatching lesson_complete. Writing
    it again here would clobber the real completion timestamp with a ~100ms-later value.
    """
    import json  # noqa: PLC0415

    try:
        history_raw: list[str] = await redis.lrange(f"session:{session_id}:ces_history", 0, 9)
        values: list[float] = []
        for raw in history_raw:
            try:
                parsed = json.loads(raw)
                values.append(float(parsed["v"]))
            except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                try:
                    values.append(float(raw))
                except (ValueError, TypeError):
                    pass

        # Empty history → None (distinguishable from zero engagement).
        # numeric(5,2) column accepts NULL; 0.0 would incorrectly signal "student scored zero".
        ces_final: float | None = round(sum(values) / len(values), 2) if values else None

        await asyncio.to_thread(
            lambda: (
                supabase.table("sessions")
                .update({"ces_final": ces_final})
                .eq("session_id", session_id)
                .execute()
            )
        )
        logger.info(
            "[tutor:%s] session finalized: ces_final=%s",
            session_id,
            ces_final,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("[tutor:%s] _finalize_session DB write failed: %s", session_id, exc)
        try:
            import sentry_sdk  # noqa: PLC0415

            sentry_sdk.capture_exception(exc)
        except Exception:  # noqa: BLE001
            # Best-effort error reporting only — the primary failure is already
            # logged above, so a Sentry capture failure here is not actionable.
            logger.debug(
                "[tutor:%s] sentry_sdk.capture_exception failed", session_id, exc_info=True
            )
