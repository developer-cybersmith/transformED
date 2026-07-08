"""Analytics service — event ingestion into session_events table."""

from __future__ import annotations

import asyncio
import logging
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
