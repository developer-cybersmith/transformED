"""
Tutor module router.

Exposes the session state machine state and allows server-side intervention
triggering (e.g. from admin dashboard or test harness).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from redis.asyncio import Redis

from app.core.redis import get_redis
from app.core.websocket import manager
from app.dependencies import CurrentUser
from app.modules.tutor.service import segment_intervention_messages
from app.modules.tutor.state_machine.graph import dispatch_event

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tutor"])


# ── Request / Response models ─────────────────────────────────────────────────


class TutorSessionState(BaseModel):
    session_id: str
    state: str  # IDLE | TEACHING | INTERVENING | CHECKING_IN | QUIZZING | TEACH_BACK | SESSION_END
    ces_score: float
    distraction_count: int
    intervention_cooldown_remaining_seconds: int
    fatigue_fired: bool
    current_slide_index: int | None = None  # D69: not yet persisted in Redis; always None
    last_intervention_type: str | None = None  # D69: not yet persisted in Redis; always None


class InterventionRequest(BaseModel):
    intervention_type: Literal["distraction", "fatigue", "confusion"]
    force: bool = False  # override cooldown (admin / demo use only)


# ── Event map ─────────────────────────────────────────────────────────────────

_INTERVENTION_EVENT: dict[str, str] = {
    "distraction": "distraction_detected",
    "fatigue": "fatigue_detected",
    "confusion": "teachback_failed",
}


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get(
    "/session/{session_id}/state",
    response_model=TutorSessionState,
    summary="Get the current state of the tutor state machine for a session",
)
async def get_session_state(
    session_id: str,
    current_user: CurrentUser,
    redis: Annotated[Redis, Depends(get_redis)],
) -> TutorSessionState:
    """Return the full tutor state for a live session.

    All fields are read from Redis point lookups (O(1) each). Returns 404 when
    the session has never been initialised. Missing optional keys (CES, counters,
    flags) degrade to zero-values rather than 500. Full Redis failure → 503.
    """
    try:
        state_raw = await redis.get(f"tutor_state:{session_id}")
        if not state_raw:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found.",
            )

        ces_raw = await redis.get(f"tutor_ces:{session_id}")
        count_raw = await redis.get(f"tutor_distraction_count:{session_id}")
        fatigue_raw = await redis.exists(f"tutor_fatigue_fired:{session_id}")
        # TTL returns -2 when key is absent, -1 when key has no TTL, else seconds remaining.
        # BOUNDED: tutor_cooldown TTL is naturally bounded to [0, intervention_cooldown_seconds].
        ttl = await redis.ttl(f"tutor_cooldown:{session_id}")
        cooldown_remaining = max(0, ttl) if ttl > 0 else 0
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Redis unavailable in get_session_state for %s: %s", session_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Session service temporarily unavailable.",
        ) from exc

    return TutorSessionState(
        session_id=session_id,
        state=state_raw.decode() if isinstance(state_raw, bytes) else str(state_raw),
        ces_score=float(ces_raw) if ces_raw else 0.0,
        distraction_count=int(count_raw) if count_raw else 0,
        fatigue_fired=bool(fatigue_raw),
        intervention_cooldown_remaining_seconds=cooldown_remaining,
    )


@router.post(
    "/session/{session_id}/intervene",
    status_code=status.HTTP_200_OK,
    summary="Manually trigger a tutor intervention for a session (admin / demo use)",
)
async def trigger_intervention(
    session_id: str,
    body: InterventionRequest,
    current_user: CurrentUser,
    redis: Annotated[Redis, Depends(get_redis)],
) -> dict[str, Any]:
    """Dispatch a tutor intervention event through the LangGraph FSM.

    Respects all guard rules (distraction cap, fatigue-once flag) by default.
    With ``force=true``, the cooldown key is deleted before dispatch so the
    cooldown guard is bypassed — the distraction cap and fatigue-once flag are
    still honoured (safety invariants, not admin overrides).

    Returns ``{"dispatched": true}`` when the FSM transitioned to INTERVENING,
    or ``{"dispatched": false, "reason": "guard_blocked"}`` when a guard blocked.
    Also sends the ``tutor_intervene`` WebSocket message directly when dispatched,
    so the intervention overlay renders immediately without waiting for the next
    attention signal.
    """
    try:
        state_raw = await redis.get(f"tutor_state:{session_id}")
        if not state_raw:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found.",
            )

        # force=True bypasses the cooldown only (not the distraction cap or fatigue-once flag)
        if body.force:
            await redis.delete(f"tutor_cooldown:{session_id}")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Redis unavailable in trigger_intervention for %s: %s", session_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Session service temporarily unavailable.",
        ) from exc

    event = _INTERVENTION_EVENT[body.intervention_type]

    # Fetch pre-generated intervention messages from the cached lesson package
    seg_msgs = await segment_intervention_messages(session_id, redis)

    try:
        result = await dispatch_event(
            session_id, event, payload={"intervention_messages": seg_msgs}
        )
    except Exception as exc:
        logger.error("dispatch_event failed for %s event=%s: %s", session_id, event, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Intervention could not be dispatched.",
        ) from exc

    to_state = str(result.get("current_state", ""))
    dispatched = to_state == "INTERVENING"

    if dispatched:
        msg = result.get("intervention_message")
        if msg:
            try:
                await manager.send(
                    session_id,
                    {
                        "type": "tutor_intervene",
                        "payload": {
                            "session_id": session_id,
                            "type": body.intervention_type,
                            "message": msg,
                        },
                    },
                )
            except Exception:  # noqa: BLE001 — WS delivery is best-effort
                logger.exception(
                    "tutor_intervene WS delivery failed for %s (POST /intervene)", session_id
                )

    return {
        "dispatched": dispatched,
        "to_state": to_state,
        "reason": None if dispatched else "guard_blocked",
    }
