"""
Tutor service — CES signal processing.

Boundary mapper, weighted CES computation (PRD §11, 0–100 scale), and Redis
window/history management.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

_CES_WINDOW_TTL = 86_400  # 24 h
_CES_HISTORY_MAX = 10


# ── Domain types ──────────────────────────────────────────────────────────────


@dataclass
class NormalizedSignal:
    """Internal representation of an attention signal after boundary mapping."""

    session_id: str
    quiz_accuracy: float | None  # None when quiz not yet attempted
    teachback_score: float | None  # None when teach-back skipped
    behavioral_score: float
    head_pose_score: float
    blink_rate: float


@dataclass
class CesResult:
    """Result of processing one attention signal window."""

    session_id: str
    ces: float
    intervention_dispatched: bool


# ── Boundary mapper ───────────────────────────────────────────────────────────


def _parse_signal(payload: dict[str, Any]) -> NormalizedSignal:
    """Map a WebSocket message dict into a validated NormalizedSignal.

    Accepts both the full WsMessage envelope (``{"type": ..., "payload": {...}}``)
    and a flat dict.  Handles quiz_accuracy=None and teachback_score=None.
    """
    # Unwrap WsMessage envelope if present
    data: dict[str, Any] = payload.get("payload") or payload

    session_id = data.get("session_id")
    if not session_id:
        raise ValueError("attention_signal missing required field: session_id")

    def _require_float(key: str) -> float:
        v = data.get(key)
        if v is None:
            raise ValueError(f"attention_signal missing required field: {key}")
        try:
            f = float(v)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"attention_signal field {key!r} must be numeric") from exc
        # Reject NaN/±inf: float("nan") would propagate through compute_ces and clamp to a
        # misleading value (NaN→100 = maximally engaged), silently suppressing interventions.
        if not math.isfinite(f):
            raise ValueError(f"attention_signal field {key!r} must be a finite number")
        return f

    def _optional_float(key: str) -> float | None:
        v = data.get(key)
        if v is None:
            return None
        try:
            f = float(v)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"attention_signal field {key!r} must be numeric or null") from exc
        if not math.isfinite(f):
            raise ValueError(f"attention_signal field {key!r} must be a finite number or null")
        return f

    return NormalizedSignal(
        session_id=str(session_id),
        quiz_accuracy=_optional_float("quiz_accuracy"),
        teachback_score=_optional_float("teachback_score"),
        behavioral_score=_require_float("behavioral_score"),
        head_pose_score=_require_float("head_pose_score"),
        blink_rate=_require_float("blink_rate"),
    )


# ── CES computation ───────────────────────────────────────────────────────────


def compute_ces(signal: NormalizedSignal) -> float:
    """Weighted Cognitive Engagement Score on the 0–100 scale (PRD §11).

    ``CES = (Σ signalᵢ × weightᵢ) × 100`` using the frozen ``settings.ces_weight_*``
    weights, matching Dev 3's ``ces_contribution`` scale contract
    (assessment/service.py) so ``ces_threshold = 50`` is correct.

    Signals are 0–1 fractions; ``quiz_accuracy`` / ``teachback_score`` may be ``None``
    (not yet attempted / skipped). The weight of any ``None`` signal is redistributed
    proportionally across the present signals (each present weight ÷
    sum-of-present-weights). This generalises the §11 teachback-``None`` rule — when
    only teachback is ``None`` the present weights sum to 0.75, so each is divided by
    0.75, reproducing the §11 numbers exactly. Result is clamped to ``[0, 100]``.
    """
    from app.config import get_settings

    s = get_settings()
    # (value, weight) for every signal, dropping the None ones.
    pairs = [
        (signal.quiz_accuracy, s.ces_weight_quiz),
        (signal.teachback_score, s.ces_weight_teachback),
        (signal.behavioral_score, s.ces_weight_behavioral),
        (signal.head_pose_score, s.ces_weight_head_pose),
        (signal.blink_rate, s.ces_weight_blink),
    ]
    present = [(v, w) for (v, w) in pairs if v is not None]
    weight_sum = sum(w for _, w in present)
    if weight_sum <= 0:
        return 0.0
    ces = sum(v * (w / weight_sum) for v, w in present) * 100.0
    return max(0.0, min(100.0, ces))


# ── Learner Mode helpers ──────────────────────────────────────────────────────


def qa_phase_seconds(tier: str | None) -> int:
    """Map a learner tier string to Q&A phase duration in seconds.

    T1 (beginner) → longest Q&A window (default 600 s / 10 min)
    T2 (intermediate) → standard window (default 300 s / 5 min)
    T3 (advanced) → shortest window (default 150 s / 2.5 min)
    Unknown / None → T2 default (300 s)

    All durations are env-var tunable via ``settings.learner_tier_*_qa_seconds``.
    """
    from app.config import get_settings

    s = get_settings()
    return {
        "T1": s.learner_tier_t1_qa_seconds,
        "T2": s.learner_tier_t2_qa_seconds,
        "T3": s.learner_tier_t3_qa_seconds,
    }.get(tier or "", s.learner_tier_default_qa_seconds)


# ── Public API ────────────────────────────────────────────────────────────────


async def _quiz_deadline_expired(session_id: str, redis: Redis) -> bool:
    """Return True if the QUIZZING time limit has elapsed for this session.

    Returns False on any error — degrading safely so the session never auto-advances
    due to a Redis blip. The key absence (lesson generated without a tier) also returns
    False, leaving the student in QUIZZING until they explicitly submit.
    """
    import time as _time  # noqa: PLC0415

    try:
        raw = await redis.get(f"session:{session_id}:quiz_deadline_at")
        if not raw:
            return False
        return _time.time() > float(raw)
    except Exception:  # noqa: BLE001
        return False


async def _intervention_deadline_expired(session_id: str, redis: Redis) -> bool:
    """D63 safety net: return True if the INTERVENING timeout has elapsed for this session.

    Mirrors ``_quiz_deadline_expired``'s fail-safe: any error returns False so a Redis blip
    degrades to "stay put", never to an unwanted auto-transition. Key absence (no intervention
    has ever fired, or intervention_complete already cleared it) also returns False.

    This is a cheap, non-atomic pre-check only — used to avoid an EVAL round trip in the common
    "clearly not expired" case. The authoritative, race-safe decision is
    ``_delete_intervention_deadline_if_expired`` below; this function must never be used on its
    own to decide whether to dispatch ``intervention_complete``.

    Review finding (2026-08-11, PR #129 six-layer review, Process Integrity layer): unlike
    ``_quiz_deadline_expired``, an error here is now logged — CLAUDE.md names "timeout" as a
    covered budget type requiring a surfaced degradation, and a silent ``except: return False``
    on a sustained Redis outage would leave a session invisibly stuck in INTERVENING.
    """
    import time as _time  # noqa: PLC0415

    try:
        raw = await redis.get(f"session:{session_id}:intervention_deadline_at")
        if not raw:
            return False
        return _time.time() > float(raw)
    except Exception:  # noqa: BLE001
        logger.warning(
            "[tutor:%s] intervention_deadline_at read failed — treating as not-expired",
            session_id,
            exc_info=True,
        )
        return False


# Lua script: atomically read-compare-delete session:{sid}:intervention_deadline_at. A plain
# GET-then-DELETE (the pre-review implementation) has a race window: two concurrent connections
# on one session_id (an explicitly supported topology, per core/websocket.py's ConnectionManager)
# can both read the SAME expired deadline, but between one caller's GET and its DELETE, a
# concurrent caller can finish a full dispatch_event round trip that ends a fresh, unexpired
# INTERVENING episode under the SAME key name — the delayed DELETE then destroys that fresh
# episode instead of the stale one it read. Running the compare AND the delete inside one Lua
# script closes the window: Redis executes the whole script atomically, so no other client's
# command can interleave between the GET and the DEL.
_DELETE_IF_EXPIRED_SCRIPT = """
local raw = redis.call("GET", KEYS[1])
if not raw then
    return 0
end
local deadline = tonumber(raw)
if deadline == nil then
    return 0
end
if tonumber(ARGV[1]) > deadline then
    redis.call("DEL", KEYS[1])
    return 1
end
return 0
"""


async def _delete_intervention_deadline_if_expired(session_id: str, redis: Redis) -> bool:
    """Atomically check-and-delete ``intervention_deadline_at`` in a single Redis round trip.

    Returns True only if THIS call's script execution found the key expired and deleted it —
    the one caller "'s script run that observes ``deadline < now`` is the only one that can ever
    return True for a given deadline value, closing the cross-generation race described above.
    Fails safe: any error (including a Redis version without Lua scripting) returns False —
    never dispatches on an uncertain result; the next attention signal or client event retries.
    """
    import time as _time  # noqa: PLC0415

    try:
        result = await redis.eval(
            _DELETE_IF_EXPIRED_SCRIPT,
            1,
            f"session:{session_id}:intervention_deadline_at",
            str(int(_time.time())),
        )
        return bool(result)
    except Exception:  # noqa: BLE001
        logger.warning(
            "[tutor:%s] intervention_deadline_at compare-and-delete failed",
            session_id,
            exc_info=True,
        )
        return False


async def start_session(session_id: str) -> None:
    """Drive the IDLE → TEACHING transition for a newly started session.

    Thin service-layer entry point over the tutor state machine so callers (the
    WebSocket handler) go through the service, mirroring ``process_attention_signal``.
    """
    from app.modules.tutor.state_machine.graph import dispatch_event

    await dispatch_event(session_id, "session_start")


# Lifecycle events a CLIENT may drive via WebSocket. distraction_detected / fatigue_detected are
# excluded on purpose — those come from the server-side CES engine, not the client; session_reset is
# admin-only; session_start has its own handler.
# D63: intervention_complete added — the client dismissing an intervention overlay must be able to
# drive INTERVENING → TEACHING. Previously omitted (not deliberately excluded like the events
# above), which made route_from_intervening's only exit event undispatchable by anything.
_CLIENT_DRIVABLE_EVENTS = frozenset(
    {
        "segment_complete",
        "checkin_complete",
        "low_checkin_score",
        "quiz_trigger",
        "quiz_complete",
        "quiz_failed",
        "teachback_complete",
        "teachback_failed",
        "lesson_complete",
        "intervention_complete",
    }
)


async def advance_tutor_state(session_id: str, event: str) -> None:
    """Dispatch a client-driven lifecycle *event* into the tutor FSM.

    Allow-listed: rejects any event a client must not be able to drive (server/engine/admin events).
    """
    if event not in _CLIENT_DRIVABLE_EVENTS:
        raise ValueError(f"event not client-drivable: {event!r}")

    from app.core.redis import get_redis
    from app.modules.tutor.state_machine.graph import dispatch_event

    redis = get_redis()

    # Learner Mode: auto-advance a QUIZZING session when the Q&A time limit elapses.
    # Uses delete-before-dispatch as a double-fire guard: if two concurrent calls both
    # see an expired deadline, only the one whose delete returns 1 (key existed) fires
    # quiz_complete — the other's delete returns 0 and skips the dispatch.
    state_raw = await redis.get(f"tutor_state:{session_id}")
    if state_raw == "QUIZZING" and await _quiz_deadline_expired(session_id, redis):
        deleted = await redis.delete(f"session:{session_id}:quiz_deadline_at")
        if deleted:
            logger.info("[tutor:%s] Q&A deadline expired — auto quiz_complete", session_id)
            await dispatch_event(session_id, "quiz_complete")
        return

    # D63 safety net: self-heal a session stuck in INTERVENING past its timeout, regardless of
    # which event the client actually sent (it may never send intervention_complete at all).
    if state_raw == "INTERVENING":
        if await _intervention_deadline_expired(session_id, redis):
            # The cheap pre-check says expired — the session is (or was, per a concurrent
            # winner) leaving INTERVENING regardless of who actually performs the delete below.
            # Authoritative, race-safe check: only the caller whose atomic script actually
            # observes and deletes the expired key fires the synthetic dispatch (closes the
            # cross-generation race — see _delete_intervention_deadline_if_expired's docstring).
            if await _delete_intervention_deadline_if_expired(session_id, redis):
                logger.info(
                    "[tutor:%s] INTERVENING timeout expired — auto intervention_complete",
                    session_id,
                )
                await dispatch_event(session_id, "intervention_complete")
                if event == "intervention_complete":
                    return  # avoid a redundant re-dispatch of the event just handled above
            # Fall through unconditionally (whether this call won or lost the atomic
            # compare-and-delete): the deadline WAS confirmed expired by the cheap pre-check, so
            # the session is transitioning out of INTERVENING one way or another — replay the
            # client's real event (e.g. segment_complete) so its side effects (like the
            # segment_index increment below) are not silently dropped. dispatch_event always
            # re-reads current_state fresh from Redis, so this is correct regardless of which
            # caller actually performed the delete.
        elif event != "intervention_complete":
            # The cheap pre-check says NOT expired — the session is confidently, still genuinely
            # INTERVENING with time remaining. Any event other than the real dismiss must not
            # reach dispatch_event: route_from_intervening routes everything but
            # intervention_complete back into intervening_node, which is NOT idempotent (it
            # unconditionally re-arms intervention_deadline_at and re-sets the cooldown key) —
            # recreating the exact D63 one-way-trap shape on any ordinary lifecycle event
            # arriving while an intervention is showing. No-op instead.
            return
        # else: not (yet) expired, and event == "intervention_complete" — the real dismiss path,
        # falls through normally to dispatch_event below.

    # Completing a segment advances the student's position (used to pick the right segment's
    # pre-generated intervention messages). 24h TTL, matching the other session keys.
    if event == "segment_complete":
        await redis.incr(f"session:{session_id}:segment_index")
        await redis.expire(f"session:{session_id}:segment_index", 86_400)

    await dispatch_event(session_id, event)


async def _segment_intervention_messages(session_id: str, redis: Redis) -> dict[str, Any]:
    """Return the current segment's ``intervention_messages`` from the cached LessonPackage.

    Returns ``{}`` on any miss (no cache / parse error / no segments / bad index). Performs ONLY
    Redis reads — never a Supabase/DB round-trip — so the intervention hot path stays < 50 ms.
    """
    try:
        raw = await redis.get(f"lesson_package:{session_id}")
        if not raw:
            return {}
        pkg = json.loads(raw)
        segments = pkg.get("segments") or []
        if not segments:
            return {}
        idx_raw = await redis.get(f"session:{session_id}:segment_index")
        idx = int(idx_raw) if idx_raw else 0
        idx = max(0, min(idx, len(segments) - 1))
        # Frozen LessonPackage schema: Segment.interventions = {distraction|confusion|fatigue: [3]}.
        return segments[idx].get("interventions") or {}
    except Exception:  # noqa: BLE001 — degrade gracefully, never block the hot path
        logger.warning("intervention message lookup failed for %s", session_id, exc_info=True)
        return {}


# Public alias — callers outside this module must use this name.
segment_intervention_messages = _segment_intervention_messages


async def process_attention_signal(
    session_id: str,
    signal: dict[str, Any],
) -> CesResult:
    """Process one attention signal window for *session_id*.

    Steps
    -----
    1. Parse and validate the payload → NormalizedSignal.
    2. Compute the weighted CES (PRD §11, 0–100 scale).
    3. Persist latest CES to ``session:{session_id}:ces_window`` and
       ``tutor_ces:{session_id}`` (24 h TTL).
    4. Prepend CES to ``session:{session_id}:ces_history`` (keep last 10).
    5. Read history; if the two most-recent values are both below
       ``settings.ces_threshold`` and tutor cooldown is absent, dispatch
       ``distraction_detected`` to the tutor state machine.
    6. Return CesResult.
    """
    from app.config import get_settings
    from app.core.redis import get_redis
    from app.modules.tutor.state_machine.graph import dispatch_event

    settings = get_settings()
    redis = get_redis()

    normalized = _parse_signal(signal)
    ces = compute_ces(normalized)

    window_key = f"session:{session_id}:ces_window"
    history_key = f"session:{session_id}:ces_history"

    # Latest window
    await redis.set(window_key, ces, ex=_CES_WINDOW_TTL)
    await redis.set(f"tutor_ces:{session_id}", ces, ex=_CES_WINDOW_TTL)  # ces_computation (s3-3)

    # Prepend to history and trim to keep only the last _CES_HISTORY_MAX values
    await cast("Awaitable[int]", redis.lpush(history_key, ces))
    await cast("Awaitable[str]", redis.ltrim(history_key, 0, _CES_HISTORY_MAX - 1))
    await redis.expire(history_key, _CES_WINDOW_TTL)

    # Read history to evaluate the intervention trigger
    history_raw: list[str] = await cast(
        "Awaitable[list[Any]]", redis.lrange(history_key, 0, _CES_HISTORY_MAX - 1)
    )

    intervention_dispatched = False

    # Read tutor state once — used by both the CES intervention guard and the deadline check below.
    # CLAUDE.md §10: CES monitoring ONLY active in TEACHING state.
    state_raw = await redis.get(f"tutor_state:{session_id}")

    if len(history_raw) >= 2:
        # Index 0 is most recent (LPUSH prepends)
        recent = [float(v) for v in history_raw[:2]]
        cooldown_key = f"tutor_cooldown:{session_id}"
        in_cooldown = await redis.exists(cooldown_key)

        # Enforce CLAUDE.md §10: CES interventions only fire in TEACHING state.
        if (
            state_raw == "TEACHING"
            and all(v < settings.ces_threshold for v in recent)
            and not in_cooldown
        ):
            logger.info(
                "[tutor:%s] CES below threshold (%.3f, %.3f) — dispatching distraction_detected",
                session_id,
                recent[0],
                recent[1],
            )
            # Pass the current segment's pre-generated messages so the FSM can select one
            # (Redis reads only — no DB/LLM on this hot path).
            seg_msgs = await _segment_intervention_messages(session_id, redis)
            result = await dispatch_event(
                session_id, "distraction_detected", payload={"intervention_messages": seg_msgs}
            )
            intervention_dispatched = True

            # Deliver the selected message to the client (in-process WS hub). Best-effort: a
            # delivery failure must never break signal processing.
            msg = result.get("intervention_message")
            if result.get("current_state") == "INTERVENING" and msg:
                try:
                    from app.core.websocket import manager

                    await manager.send(
                        session_id,
                        {
                            "type": "tutor_intervene",
                            "payload": {
                                "session_id": session_id,
                                "type": result.get("intervention_type") or "distraction",
                                "message": msg,
                            },
                        },
                    )
                except Exception:
                    logger.exception("tutor_intervene delivery failed for %s", session_id)

    # Learner Mode: auto-advance a QUIZZING session when the Q&A time limit elapses.
    # This attention-signal path (fires every ~5 s) is the primary deadline enforcer
    # when the student is not actively submitting client events.
    # Delete-before-dispatch guard prevents double-fire from concurrent signals.
    # state_raw is already populated above (used for CES guard too).
    if state_raw == "QUIZZING" and await _quiz_deadline_expired(session_id, redis):
        deleted = await redis.delete(f"session:{session_id}:quiz_deadline_at")
        if deleted:
            logger.info(
                "[tutor:%s] Q&A deadline expired via attention signal — auto quiz_complete",
                session_id,
            )
            await dispatch_event(session_id, "quiz_complete")

    # D63 safety net: attention frames keep arriving from the client during INTERVENING (nothing
    # stops MediaPipe/the heartbeat when an overlay is shown), so this recurring ~5s hook is what
    # actually enforces the timeout when the client never sends intervention_complete at all.
    # Atomic check-and-delete closes the cross-generation race a plain GET-then-DELETE has when
    # two connections on one session_id race on the same key (see the helper's docstring).
    if state_raw == "INTERVENING" and await _intervention_deadline_expired(session_id, redis):
        if await _delete_intervention_deadline_if_expired(session_id, redis):
            logger.info(
                "[tutor:%s] INTERVENING timeout expired via attention signal — "
                "auto intervention_complete",
                session_id,
            )
            await dispatch_event(session_id, "intervention_complete")

    logger.debug(
        "[tutor:%s] ces=%.4f intervention_dispatched=%s",
        session_id,
        ces,
        intervention_dispatched,
    )

    return CesResult(
        session_id=session_id,
        ces=ces,
        intervention_dispatched=intervention_dispatched,
    )
