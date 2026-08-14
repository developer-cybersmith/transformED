"""
Tutor service — CES signal processing.

Boundary mapper, weighted CES computation (PRD §11, 0–100 scale), and Redis
window/history management.
"""

from __future__ import annotations

import json
import logging
import math
import time as _time
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
    behavioral_score: float | None  # None on MediaPipe frame drop (S3-38 D13)
    head_pose_score: float | None  # None on MediaPipe frame drop (S3-38 D13)
    blink_rate: float | None  # None on MediaPipe frame drop (S3-38 D13)


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
        # Reject out-of-range: ws.ts SYNC-B freeze (Story 4-27) locks the scale to [0.0, 1.0].
        # ces.py clamps downstream, but catching here surfaces producer bugs immediately.
        if f < 0.0 or f > 1.0:
            raise ValueError(
                f"attention_signal field {key!r} must be in [0.0, 1.0], got {f!r}"
            )
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
        # Reject out-of-range: ws.ts SYNC-B freeze (Story 4-27) locks the scale to [0.0, 1.0].
        # ces.py clamps downstream, but catching here surfaces producer bugs immediately.
        if f < 0.0 or f > 1.0:
            raise ValueError(
                f"attention_signal field {key!r} must be in [0.0, 1.0] or null, got {f!r}"
            )
        return f

    return NormalizedSignal(
        session_id=str(session_id),
        quiz_accuracy=_optional_float("quiz_accuracy"),
        teachback_score=_optional_float("teachback_score"),
        behavioral_score=_optional_float("behavioral_score"),  # S3-38 D13: MediaPipe may drop
        head_pose_score=_optional_float("head_pose_score"),  # S3-38 D13: MediaPipe may drop
        blink_rate=_optional_float("blink_rate"),  # S3-38 D13: MediaPipe may drop
    )


# ── CES computation ───────────────────────────────────────────────────────────


def compute_ces(signal: NormalizedSignal) -> float:
    """NormalizedSignal wrapper for the canonical CES formula in assessment/ces.py.

    Formula arithmetic lives exclusively in ``assessment.ces.compute_ces`` (D1/D62).
    This wrapper preserves the NormalizedSignal-based API used internally by
    ``process_attention_signal`` without duplicating the weighted-sum logic.

    SYNC-A resolved (Story 4-27, 2026-08-13): ``assessment/ces.py`` is the single
    canonical implementation. This wrapper is the only permitted caller outside the
    assessment module. The CI guard ``test_ces_formula_defined_in_one_place`` (in
    ``test_s3_53_ces_production_closure.py``) enforces this: any second formula
    definition fails the build.
    """
    from app.config import get_settings
    from app.modules.assessment.ces import compute_ces as _canonical

    return _canonical(
        quiz_accuracy=signal.quiz_accuracy,
        teachback_score=signal.teachback_score,
        behavioral=signal.behavioral_score,
        head_pose=signal.head_pose_score,
        blink=signal.blink_rate,
        settings=get_settings(),
    )


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
# above), which made route_from_intervening's only exit event undispatchable by anything:
# TutorInterventionCard.tsx's dismiss (30s auto-dismiss and manual x) only cleared local React
# state, never told the server, so every session's FIRST intervention permanently stuck the FSM in
# INTERVENING — useAttentionMonitor.ts's flushWindow gates on `tutorStateRef.current ===
# 'TEACHING'`, so CES monitoring silently died for the rest of the session. TutorInterventionCard.tsx
# sends this event on dismiss.
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
    1. Read tutor state (CLAUDE.md §10, D14): CES monitoring ONLY active in TEACHING.
    2. If TEACHING: parse signal → compute CES → update Redis window/history → check trigger.
    3. If QUIZZING: check Q&A deadline (separate concern, not CES-related).
    4. Return CesResult.
    """
    from app.config import get_settings
    from app.core.redis import get_redis
    from app.modules.tutor.state_machine.graph import dispatch_event

    settings = get_settings()
    redis = get_redis()

    # D14 (S3-39): read tutor state FIRST — compute_ces and history writes run ONLY in TEACHING.
    # History accumulated in non-TEACHING states (QUIZZING, INTERVENING, TEACH_BACK) would
    # create false low-CES pairs and trigger spurious interventions when TEACHING resumes.
    state_raw = await redis.get(f"tutor_state:{session_id}")

    ces: float = 0.0
    intervention_dispatched = False

    if state_raw == "TEACHING":
        normalized = _parse_signal(signal)
        ces = compute_ces(normalized)

        window_key = f"session:{session_id}:ces_window"
        history_key = f"session:{session_id}:ces_history"

        # Latest window
        await redis.set(window_key, ces, ex=_CES_WINDOW_TTL)
        await redis.set(f"tutor_ces:{session_id}", ces, ex=_CES_WINDOW_TTL)

        # Prepend to history (D4: JSON {"v": CES float, "t": Unix seconds int}).
        # BOUNDED: ltrim cap of _CES_HISTORY_MAX=10 applied at write time.
        _entry = json.dumps({"v": ces, "t": int(_time.time())})
        await cast("Awaitable[int]", redis.lpush(history_key, _entry))
        await cast("Awaitable[str]", redis.ltrim(history_key, 0, _CES_HISTORY_MAX - 1))
        await redis.expire(history_key, _CES_WINDOW_TTL)

        # S3-42 (D9): per-signal histories for get_session_report accuracy.
        # Only written when the signal is not None (MediaPipe may drop frames — S3-38 D13).
        # BOUNDED: ltrim cap of _CES_HISTORY_MAX=10 applied at write time.
        if normalized.behavioral_score is not None:
            await redis.lpush(
                f"session:{session_id}:behavioral_history", normalized.behavioral_score
            )
            await redis.ltrim(
                f"session:{session_id}:behavioral_history", 0, _CES_HISTORY_MAX - 1
            )
            await redis.expire(f"session:{session_id}:behavioral_history", _CES_WINDOW_TTL)  # D64
        if normalized.head_pose_score is not None:
            await redis.lpush(
                f"session:{session_id}:head_pose_history", normalized.head_pose_score
            )
            await redis.ltrim(
                f"session:{session_id}:head_pose_history", 0, _CES_HISTORY_MAX - 1
            )
            await redis.expire(f"session:{session_id}:head_pose_history", _CES_WINDOW_TTL)  # D64
        if normalized.blink_rate is not None:
            await redis.lpush(f"session:{session_id}:blink_history", normalized.blink_rate)
            await redis.ltrim(f"session:{session_id}:blink_history", 0, _CES_HISTORY_MAX - 1)
            await redis.expire(f"session:{session_id}:blink_history", _CES_WINDOW_TTL)  # D64

        # Bug fix: nothing anywhere ever sent the frozen `ces_update` message
        # (packages/shared/types/ws.ts) -- the frontend's CESIndicator has always
        # had complete, correct handling for it (useLessonSocket.ts's 'ces_update'
        # case), but this function only ever emitted `attention_ack` (no score,
        # deliberately, per PRD §18) and `tutor_intervene` (only when an
        # intervention actually fires). `compute_ces` returns the 0-100 scale
        # (PRD §11) but useLessonSocket.ts's ces_update handler validates
        # `ces in [0,1]` and silently drops anything outside that range -- scaled
        # by /100 here to match what the frontend expects. window_index must be
        # monotonically increasing per session (the frontend rejects an
        # out-of-order frame) -- a dedicated counter, not history length, since
        # history is capped at _CES_HISTORY_MAX and would not keep increasing
        # past that. Gated inside `state_raw == "TEACHING"` — CLAUDE.md §10.
        try:
            from app.core.websocket import manager  # noqa: PLC0415

            window_index = await cast(
                "Awaitable[int]", redis.incr(f"session:{session_id}:ces_window_index")
            )
            await redis.expire(f"session:{session_id}:ces_window_index", _CES_WINDOW_TTL)
            await manager.send(
                session_id,
                {
                    "type": "ces_update",
                    "payload": {
                        "session_id": session_id,
                        "ces": ces / 100.0,
                        "window_index": window_index,
                    },
                },
            )
        except Exception:
            logger.exception("ces_update delivery failed for %s", session_id)

        # Read history to evaluate the intervention trigger.
        # BOUNDED: ltrim cap of _CES_HISTORY_MAX=10 applied at write time.
        history_raw: list[str] = await cast(
            "Awaitable[list[Any]]", redis.lrange(history_key, 0, _CES_HISTORY_MAX - 1)
        )

        if len(history_raw) >= 2:
            # D4: parse JSON entries {"v": float, "t": int}.  Backward-compat fallback: a legacy
            # bare-float string gets t=0 so the gap check always fails for that pair — no false
            # intervention on a mixed old/new history (abs(now - 0) >> 2*cadence).
            def _parse_history_entry(raw: str) -> tuple[float, int]:
                try:
                    parsed = json.loads(raw)
                    return float(parsed["v"]), int(parsed["t"])
                except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                    try:
                        return float(raw), 0  # legacy bare float — timestamp unknown
                    except (ValueError, TypeError):
                        return 0.0, 0  # fully corrupt — safe sentinel

            v0, t0 = _parse_history_entry(history_raw[0])  # most recent (LPUSH prepends)
            v1, t1 = _parse_history_entry(history_raw[1])  # second most recent

            # D4 gap check: reject stale history from signal gaps / MediaPipe restarts.
            gap_ok = abs(t0 - t1) <= 2 * settings.ces_cadence_seconds

            # D6: _can_intervene_distraction uses a Lua script to atomically check cooldown +
            # distraction cap and increment the count — no separate EXISTS+GET two-step.
            if gap_ok and v0 < settings.ces_threshold and v1 < settings.ces_threshold:
                from app.modules.tutor.state_machine.graph import (  # noqa: PLC0415
                    _can_intervene_distraction,
                )

                can_dispatch = await _can_intervene_distraction(session_id, redis, settings)
                if can_dispatch:
                    logger.info(
                        "[tutor:%s] CES below threshold (%.3f, %.3f) — dispatching"
                        " distraction_detected",
                        session_id,
                        v0,
                        v1,
                    )
                    # Pass the current segment's pre-generated messages so the FSM can select one
                    # (Redis reads only — no DB/LLM on this hot path).
                    seg_msgs = await _segment_intervention_messages(session_id, redis)
                    result = await dispatch_event(
                        session_id,
                        "distraction_detected",
                        payload={"intervention_messages": seg_msgs},
                    )
                    intervention_dispatched = True

                    # Deliver the selected message to the client (in-process WS hub).
                    # Best-effort: a delivery failure must never break signal processing.
                    msg = result.get("intervention_message")
                    if result.get("current_state") == "INTERVENING" and msg:
                        try:
                            from app.core.websocket import manager  # noqa: PLC0415

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
                            logger.exception(
                                "tutor_intervene delivery failed for %s", session_id
                            )

    # ── Fatigue trigger (D7, S3-45) ──────────────────────────────────────────
    # Only evaluate when TEACHING and no intervention already dispatched this signal.
    # Primary: blink+head_pose both below thresholds for 2 consecutive windows AND
    #   session duration >= ces_fatigue_min_session_seconds.
    # Exhaustion fallback: all three MediaPipe signals None AND duration floor met.
    # Once-per-session: _can_intervene_fatigue checks tutor_fatigue_fired:{session_id}.
    if state_raw == "TEACHING" and not intervention_dispatched:
        # _time is imported at module level; no local re-import needed
        session_start_ts_raw = await redis.get(f"session:{session_id}:session_start_ts")
        if session_start_ts_raw is None:
            # D-nn: key missing (Redis was unavailable at WS connect time, or session init
            # was bypassed). Fatigue detection is silently disabled for the entire session.
            # Surfaced here as a warning so ops can detect the gap without crashing the path.
            logger.warning(
                "[tutor:%s] session_start_ts missing — fatigue detection disabled for session",
                session_id,
            )
        if session_start_ts_raw is not None:
            try:
                duration_s = _time.time() - float(session_start_ts_raw)
            except (TypeError, ValueError):
                duration_s = 0.0
            if duration_s >= settings.ces_fatigue_min_session_seconds:
                # BOUNDED: end=1 → at most 2 entries (CLAUDE.md unbounded-query rule)
                blink_hist = await cast(
                    "Awaitable[list[Any]]",
                    redis.lrange(f"session:{session_id}:blink_history", 0, 1),
                )
                hp_hist = await cast(
                    "Awaitable[list[Any]]",
                    redis.lrange(f"session:{session_id}:head_pose_history", 0, 1),
                )
                primary_trigger = (
                    len(blink_hist) >= 2
                    and all(
                        float(v) < settings.ces_fatigue_blink_threshold for v in blink_hist
                    )
                    and len(hp_hist) >= 2
                    and all(
                        float(v) < settings.ces_fatigue_head_pose_threshold for v in hp_hist
                    )
                )
                exhaustion_fallback = (
                    normalized.blink_rate is None
                    and normalized.head_pose_score is None
                    and normalized.behavioral_score is None
                )
                if primary_trigger or exhaustion_fallback:
                    from app.modules.tutor.state_machine.graph import (  # noqa: PLC0415
                        _can_intervene_fatigue,
                    )

                    if await _can_intervene_fatigue(session_id):
                        logger.info(
                            "[tutor:%s] fatigue trigger (primary=%s exhaustion=%s)"
                            " — dispatching fatigue_detected",
                            session_id,
                            primary_trigger,
                            exhaustion_fallback,
                        )
                        seg_msgs = await _segment_intervention_messages(session_id, redis)
                        fatigue_result = await dispatch_event(
                            session_id,
                            "fatigue_detected",
                            payload={"intervention_messages": seg_msgs},
                        )
                        intervention_dispatched = True
                        fatigue_msg = fatigue_result.get("intervention_message")
                        if (
                            fatigue_result.get("current_state") == "INTERVENING" and fatigue_msg
                        ):
                            try:
                                from app.core.websocket import manager  # noqa: PLC0415

                                await manager.send(
                                    session_id,
                                    {
                                        "type": "tutor_intervene",
                                        "payload": {
                                            "session_id": session_id,
                                            "type": "fatigue",
                                            "message": fatigue_msg,
                                        },
                                    },
                                )
                            except Exception:
                                logger.exception(
                                    "tutor_intervene (fatigue) delivery failed for %s",
                                    session_id,
                                )

    # ── Fatigue trigger (D7, S3-45) ──────────────────────────────────────────
    # Only evaluate when TEACHING and no intervention already dispatched this signal.
    # Primary: blink+head_pose both below thresholds for 2 consecutive windows AND
    #   session duration >= ces_fatigue_min_session_seconds.
    # Exhaustion fallback: all three MediaPipe signals None AND duration floor met.
    # Once-per-session: _can_intervene_fatigue checks tutor_fatigue_fired:{session_id}.
    if state_raw == "TEACHING" and not intervention_dispatched:
        import time as _time  # noqa: PLC0415

        session_start_ts_raw = await redis.get(f"session:{session_id}:session_start_ts")
        if session_start_ts_raw is not None:
            try:
                duration_s = _time.time() - float(session_start_ts_raw)
            except (TypeError, ValueError):
                duration_s = 0.0
            if duration_s >= settings.ces_fatigue_min_session_seconds:
                # BOUNDED: end=1 → at most 2 entries (AC12 / CLAUDE.md unbounded-query rule)
                blink_hist = await cast(
                    "Awaitable[list[Any]]",
                    redis.lrange(f"session:{session_id}:blink_history", 0, 1),
                )
                hp_hist = await cast(
                    "Awaitable[list[Any]]",
                    redis.lrange(f"session:{session_id}:head_pose_history", 0, 1),
                )
                primary_trigger = (
                    len(blink_hist) >= 2
                    and all(float(v) < settings.ces_fatigue_blink_threshold for v in blink_hist)
                    and len(hp_hist) >= 2
                    and all(float(v) < settings.ces_fatigue_head_pose_threshold for v in hp_hist)
                )
                exhaustion_fallback = (
                    normalized.blink_rate is None
                    and normalized.head_pose_score is None
                    and normalized.behavioral_score is None
                )
                if primary_trigger or exhaustion_fallback:
                    from app.modules.tutor.state_machine.graph import _can_intervene_fatigue

                    if await _can_intervene_fatigue(session_id):
                        logger.info(
                            "[tutor:%s] fatigue trigger (primary=%s exhaustion=%s)"
                            " — dispatching fatigue_detected",
                            session_id,
                            primary_trigger,
                            exhaustion_fallback,
                        )
                        seg_msgs = await _segment_intervention_messages(session_id, redis)
                        fatigue_result = await dispatch_event(
                            session_id,
                            "fatigue_detected",
                            payload={"intervention_messages": seg_msgs},
                        )
                        intervention_dispatched = True
                        fatigue_msg = fatigue_result.get("intervention_message")
                        if fatigue_result.get("current_state") == "INTERVENING" and fatigue_msg:
                            try:
                                from app.core.websocket import manager

                                await manager.send(
                                    session_id,
                                    {
                                        "type": "tutor_intervene",
                                        "payload": {
                                            "session_id": session_id,
                                            "type": "fatigue",
                                            "message": fatigue_msg,
                                        },
                                    },
                                )
                            except Exception:
                                logger.exception(
                                    "tutor_intervene (fatigue) delivery failed for %s",
                                    session_id,
                                )

    # Learner Mode: auto-advance a QUIZZING session when the Q&A time limit elapses.
    # This attention-signal path (fires every ~5 s) is the primary deadline enforcer.
    # Delete-before-dispatch guard prevents double-fire from concurrent signals.
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
