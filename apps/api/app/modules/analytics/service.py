"""Analytics service — event ingestion and session summary aggregation."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

KNOWN_EVENT_TYPES: frozenset[str] = frozenset({
    "tab_switch",
    "retry_after_fail",
    "jargon_hover",
    "quiz_skip",
    "teachback_skip",
    "intervention_acknowledged",
    "segment_complete",
    "session_start",
    "session_end",
})


async def ingest_events(
    *,
    events: list[Any],
    user_id: str,
    supabase: Any,
) -> dict[str, int]:
    """Validate session ownership and bulk-insert a batch of analytics events.

    Args:
        events: List of AnalyticsEvent instances (validated by router Pydantic model).
        user_id: Authenticated user's UUID from JWT sub claim.
        supabase: Synchronous supabase-py v2 client.

    Returns:
        {"ingested": N} where N is the number of rows written.

    Raises:
        HTTPException 403: Any event's session_id is not owned by user_id, or does not exist.
        HTTPException 500: Bulk insert fails.
    """
    # Step 1 — Ownership check: single query for all unique session_ids
    session_ids: list[str] = list({str(e.session_id) for e in events})

    ownership_resp = await asyncio.to_thread(
        lambda: supabase.table("sessions")
        .select("session_id")
        .in_("session_id", session_ids)
        .eq("user_id", user_id)
        .execute()
    )
    authorized_ids: set[str] = {str(r["session_id"]) for r in (ownership_resp.data or [])}
    requested_ids: set[str] = set(session_ids)

    if authorized_ids != requested_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="One or more sessions not found or access denied.",
        )

    # Step 2 — Soft-validate event types (log unknown, never reject)
    for event in events:
        if event.event_type not in KNOWN_EVENT_TYPES:
            logger.warning(
                "analytics: unknown event_type=%r session=%r user=%r",
                event.event_type,
                event.session_id,
                user_id,
            )

    # Step 3 — Build rows: merge client_timestamp_ms into payload JSONB as _client_ts_ms
    rows: list[dict[str, Any]] = [
        {
            "session_id": str(event.session_id),
            "event_type": event.event_type,
            "payload": {**event.payload, "_client_ts_ms": event.client_timestamp_ms},
        }
        for event in events
    ]

    # Step 4 — Single bulk insert
    insert_resp = await asyncio.to_thread(
        lambda: supabase.table("session_events").insert(rows).execute()
    )
    insert_error = getattr(insert_resp, "error", None)
    if insert_error:
        safe_err = str(insert_error).replace("\n", " ").replace("\r", " ")
        logger.error(
            "analytics: session_events bulk insert failed user=%r error=%s",
            user_id,
            safe_err,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist analytics events.",
        )

    return {"ingested": len(rows)}


async def get_session_summary(
    *,
    session_id: str,
    user_id: str,
    supabase: Any,
) -> dict[str, Any]:
    """Return aggregated analytics for a session.

    Args:
        session_id: UUID of the session to summarise.
        user_id: Authenticated user's UUID from JWT sub claim.
        supabase: Synchronous supabase-py v2 client.

    Returns:
        Dict matching SessionSummary schema (router validates via response_model).

    Raises:
        HTTPException 404: Session not found OR session owned by a different user
            (SEC-006 anti-enumeration: both paths return identical 404 detail).
    """
    # Step 1 — Ownership check (SEC-006: identical 404 for missing and IDOR)
    session_resp = await asyncio.to_thread(
        lambda: supabase.table("sessions")
        .select("session_id, user_id, lesson_id, ces_final, started_at, ended_at")
        .eq("session_id", session_id)
        .maybe_single()
        .execute()
    )
    if session_resp.data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    if str(session_resp.data["user_id"]) != str(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")

    session_row = session_resp.data

    # Step 2 — Single session_events query; aggregate all three metrics in Python
    events_resp = await asyncio.to_thread(
        lambda: supabase.table("session_events")
        .select("event_type")
        .eq("session_id", session_id)
        .execute()
    )
    events_rows = events_resp.data or []
    events_count = len(events_rows)
    distraction_events = sum(
        1 for r in events_rows
        if r.get("event_type") in {"tab_switch", "intervention_acknowledged"}
    )
    page_views = sum(
        1 for r in events_rows
        if r.get("event_type") == "segment_complete"
    )

    # Step 3 — Attention events (RLS enforces attention_consent; 0 rows if no consent)
    attn_resp = await asyncio.to_thread(
        lambda: supabase.table("attention_events")
        .select("gaze_score, head_pose_score, blink_rate")
        .eq("session_id", session_id)
        .execute()
    )
    attn_rows = attn_resp.data or []

    gaze_vals = [float(r["gaze_score"]) for r in attn_rows if r.get("gaze_score") is not None]
    head_vals = [float(r["head_pose_score"]) for r in attn_rows if r.get("head_pose_score") is not None]
    blink_vals = [float(r["blink_rate"]) for r in attn_rows if r.get("blink_rate") is not None]

    avg_attention = round(sum(gaze_vals) / len(gaze_vals), 4) if gaze_vals else 0.0
    avg_head_pose_score = round(sum(head_vals) / len(head_vals), 4) if head_vals else 0.0
    total_blinks = int(round(sum(blink_vals))) if blink_vals else 0

    # Step 4 — Duration in seconds (0.0 if either timestamp is absent)
    def _parse_ts(val: Any) -> datetime | None:
        if val is None:
            return None
        if isinstance(val, str):
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        return val

    started_at = _parse_ts(session_row.get("started_at"))
    ended_at = _parse_ts(session_row.get("ended_at"))
    duration_seconds = (
        round((ended_at - started_at).total_seconds(), 2)
        if ended_at and started_at
        else 0.0
    )

    return {
        "session_id": str(session_row["session_id"]),
        "user_id": str(session_row["user_id"]),
        "lesson_id": str(session_row["lesson_id"]),
        "ces_score": float(session_row.get("ces_final") or 0.0),
        "avg_attention": avg_attention,
        "distraction_events": distraction_events,
        "total_blinks": total_blinks,
        "avg_head_pose_score": avg_head_pose_score,
        "page_views": page_views,
        "duration_seconds": duration_seconds,
        "events_count": events_count,
    }
