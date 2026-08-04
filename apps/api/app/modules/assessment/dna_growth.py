"""DNA growth tracking — writes dna_update events after each learner_dna upsert.

Called by fuse_learner_dna() as Step 6 after the learner_dna upsert succeeds.
Writes one session_events row per dimension (9 total) recording the old value,
new EMA-blended value, and delta. Non-fatal: returns 0 on any failure.

Separation of concerns:
  - dna_fusion.py  — EMA math, learner_dna upsert       (Story 3-25)
  - dna_profile.py — LLM profile text, profile_text upsert (Story 3-26)
  - dna_growth.py  — growth events, session_events insert  (Story 3-27)

No LLM calls. No model strings. Pure analytics write.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["record_dna_growth"]


async def record_dna_growth(
    *,
    session_id: str,
    old_dims: dict[str, float | None],
    new_dims: dict[str, float],
    supabase: Any,  # noqa: ANN401
) -> int:
    """Insert dna_update session_events rows for each dimension in new_dims.

    Builds one row per dimension with payload:
        {"dimension": str, "old_value": float|None, "new_value": float, "delta": float|None}

    delta = round(new - old, 4) when old is float; None when old is None (first session).

    Args:
        session_id: UUID of the session that just ended.
        old_dims:   {dim: old_float | None} — None means no prior DB row (first session).
        new_dims:   {dim: new_float} — EMA-blended values from fuse_learner_dna.
        supabase:   Synchronous Supabase client (service-role key).

    Returns:
        Number of rows inserted (normally 9); 0 on any failure.
    """
    if not new_dims:
        return 0

    _safe_sid = str(session_id).replace("\n", " ").replace("\r", " ")

    rows = []
    for dim, new_val in new_dims.items():
        old_val = old_dims.get(dim)
        delta = round(new_val - old_val, 4) if old_val is not None else None
        rows.append(
            {
                "session_id": session_id,
                "event_type": "dna_update",
                "payload": {
                    "dimension": dim,
                    "old_value": old_val,
                    "new_value": new_val,
                    "delta": delta,
                },
            }
        )

    from app.modules.analytics.service import write_system_events  # local import (avoids circular)

    count = await write_system_events(rows=rows, supabase=supabase)
    if count > 0:
        logger.info("DNA growth: inserted %d rows session=%s", count, _safe_sid)
    else:
        logger.warning("DNA growth: insert failed session=%s", _safe_sid)
    return count
