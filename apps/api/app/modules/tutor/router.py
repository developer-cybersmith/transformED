"""
Tutor module router.

Exposes the session state machine state and allows server-side intervention
triggering (e.g. from admin dashboard or test harness).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.dependencies import CurrentUser

router = APIRouter(tags=["tutor"])


# ── Response / Request models ─────────────────────────────────────────────────


class TutorSessionState(BaseModel):
    session_id: str
    state: str  # IDLE | TEACHING | INTERVENING | CHECKING_IN | QUIZZING | TEACH_BACK | SESSION_END
    ces_score: float
    distraction_count: int
    intervention_cooldown_remaining_seconds: int
    fatigue_fired: bool
    current_slide_index: int | None = None
    last_intervention_type: str | None = None


class InterventionRequest(BaseModel):
    # distraction | confusion | fatigue (+ admin prompt types: quiz_prompt | teachback_prompt)
    intervention_type: str
    force: bool = False  # override cooldown (admin / test use only)


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get(
    "/session/{session_id}/state",
    response_model=TutorSessionState,
    summary="Get the current state of the tutor state machine for a session",
)
async def get_session_state(
    session_id: str,
    current_user: CurrentUser,
) -> TutorSessionState:
    """Return the full tutor state for a live session.

    State is read from Redis key ``tutor_state:{session_id}``.

    TODO (Sprint 2): Delegate to tutor service layer.
    """
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet")


@router.post(
    "/session/{session_id}/intervene",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Manually trigger a tutor intervention for a session",
)
async def trigger_intervention(
    session_id: str,
    body: InterventionRequest,
    current_user: CurrentUser,
) -> dict[str, Any]:
    """Trigger a tutor intervention for debugging / admin use.

    Respects cooldown unless ``force=true`` (admin only).

    TODO (Sprint 2): Delegate to tutor state machine.
    """
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet")
