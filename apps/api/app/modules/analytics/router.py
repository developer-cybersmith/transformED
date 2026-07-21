"""
Analytics module router.

Ingests real-time behavioral events (jargon_hover, tab_switch, etc.)
and provides session summary aggregations.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.dependencies import CurrentUser

router = APIRouter(tags=["analytics"])

_KNOWN_EVENT_TYPES_DESC = (
    "Known types: tab_switch | retry_after_fail | jargon_hover | quiz_skip | "
    "teachback_skip | intervention_acknowledged | segment_complete | session_start | "
    "session_end. Unknown types are accepted (logged at WARNING, not rejected)."
)


# ── Request / Response models ─────────────────────────────────────────────────


class AnalyticsEvent(BaseModel):
    session_id: str
    event_type: str = Field(description=_KNOWN_EVENT_TYPES_DESC)
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Event-specific data (e.g. {term, segment_id} for jargon_hover)",
    )
    client_timestamp_ms: int = Field(
        ge=0,
        description="Client-side Unix timestamp in milliseconds (must be non-negative)",
    )


class BatchEventsRequest(BaseModel):
    events: list[AnalyticsEvent] = Field(
        description="Batch of up to 100 events", min_length=1, max_length=100
    )


class SessionSummary(BaseModel):
    session_id: str
    user_id: str
    lesson_id: str
    ces_score: float
    avg_attention: float
    distraction_events: int
    total_blinks: int
    avg_head_pose_score: float
    page_views: int
    duration_seconds: float
    events_count: int


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post(
    "/events",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest a batch of analytics events",
)
async def ingest_events(
    body: BatchEventsRequest,
    current_user: CurrentUser,
) -> dict[str, int]:
    """Validate session ownership and bulk-insert analytics events into session_events.

    Events are written to the ``session_events`` table in a single bulk insert.
    client_timestamp_ms is stored inside the payload JSONB under key ``_client_ts_ms``.
    Unknown event types are accepted and logged at WARNING level.
    """
    from app.core.db import get_supabase
    from app.modules.analytics.service import ingest_events as _ingest_events

    return await _ingest_events(
        events=body.events,
        user_id=current_user["sub"],
        supabase=get_supabase(),
    )


@router.get(
    "/session/{session_id}/summary",
    response_model=SessionSummary,
    summary="Get the analytics summary for a session",
)
async def get_session_summary(
    session_id: str,
    current_user: CurrentUser,
) -> SessionSummary:
    """Return aggregated analytics for a completed or in-progress session.

    Aggregates from session_events and attention_events tables.
    Attention metrics default to 0.0 if the user has not consented (RLS enforces consent).
    """
    from app.core.db import get_supabase
    from app.modules.analytics.service import get_session_summary as _get_session_summary

    return await _get_session_summary(
        session_id=session_id,
        user_id=current_user["sub"],
        supabase=get_supabase(),
    )
