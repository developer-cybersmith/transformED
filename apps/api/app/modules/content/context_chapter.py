"""Chapter-context service for the content module (Story S5-3).

Reads `chapter_context` rows and formats them into a prompt-ready text block.
Injected into lesson_planner_node at the "chapter instructions" precedence slot
(§5 of AI_Learning_Product_Final_Strategy.pdf — after book context, before user prompt).

Pattern mirrors context.py (S5-1 book context) but is intentionally independent.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from app.core.db import get_supabase

logger = logging.getLogger(__name__)

# Column list — verified against supabase/migrations/20260921010000_chapter_context.sql.
_CHAPTER_CONTEXT_COLUMNS = (
    "chapter_id,user_id,depth_duration,learning_need,specific_doubt,goal_and_skip,"
    "prerequisites_done,updated_at"
)

_DEPTH_DISPLAY: dict[str, str] = {
    "quick_15_20m": "Quick overview (15–20 minutes)",
    "standard_30_45m": "Standard session (30–45 minutes)",
    "deep_60_90m": "Deep dive (60–90 minutes)",
    "mastery_multi": "Full mastery — multiple sessions",
    "ai_decide": "Let AI decide",
}

_LEARNING_NEED_DISPLAY: dict[str, str] = {
    "examples_analogies": "Examples and analogies",
    "formulas_derivations": "Formulas and derivations",
    "diagrams_visuals": "Diagrams and visuals",
    "practice_questions": "Practice questions",
    "adaptive_mix": "Adaptive mix (let AI decide)",
}


def _sanitize(text: str | None) -> str | None:
    """Collapse internal newlines to spaces to prevent prompt injection (AC6, S5-1 pattern F3)."""
    if text is None:
        return None
    return " ".join(text.splitlines())


def _format_chapter_context_block(
    *,
    depth_duration: str | None,
    learning_need: str | None,
    specific_doubt: str | None,
    goal_and_skip: str | None,
    prerequisites_done: bool | None,
) -> str:
    """Format a chapter context row into a prompt-ready block string.

    Returns "" when all fields are None (AC4). Only includes lines for non-None
    values. MCQ values are mapped to human-readable labels (AC5). Boolean False
    emits "No" — never omitted (AC, mirrors S5-1 review finding for booleans).
    """
    lines: list[str] = []

    if depth_duration is not None:
        label = _DEPTH_DISPLAY.get(depth_duration)
        if label is None:
            logger.warning(
                "chapter_context: unknown depth_duration value %r — omitting from prompt",
                depth_duration,
            )
        else:
            lines.append(f"Depth and time needed: {label}")

    if learning_need is not None:
        label = _LEARNING_NEED_DISPLAY.get(learning_need)
        if label is None:
            logger.warning(
                "chapter_context: unknown learning_need value %r — omitting from prompt",
                learning_need,
            )
        else:
            lines.append(f"Primary learning need: {label}")

    if specific_doubt is not None:
        # Labelled as "student-supplied" so the LLM treats this as user metadata,
        # not as a system instruction — limits prompt injection surface.
        lines.append(f"Student-supplied doubt: {_sanitize(specific_doubt)}")

    if goal_and_skip is not None:
        lines.append(f"Student-supplied goal/skip: {_sanitize(goal_and_skip)}")

    if prerequisites_done is not None:
        lines.append(f"Prerequisites completed: {'Yes' if prerequisites_done else 'No'}")

    if not lines:
        return ""

    return "\n\n[Chapter Instructions]\n" + "\n".join(lines)


async def upsert_chapter_context(
    chapter_id: str,
    user_id: str,
    *,
    depth_duration: str | None,
    learning_need: str | None,
    specific_doubt: str | None,
    goal_and_skip: str | None,
    prerequisites_done: bool | None,
) -> dict[str, Any]:
    """Upsert a chapter_context row for (chapter_id, user_id). Returns the written row.

    Sanitizes text fields on write path. Non-blocking: wrapped in asyncio.to_thread.
    """
    db: Any = get_supabase()
    resp = await asyncio.to_thread(
        lambda: (
            db.table("chapter_context")
            .upsert(
                {
                    "chapter_id": chapter_id,
                    "user_id": user_id,
                    "depth_duration": depth_duration,
                    "learning_need": learning_need,
                    "specific_doubt": _sanitize(specific_doubt),
                    "goal_and_skip": _sanitize(goal_and_skip),
                    "prerequisites_done": prerequisites_done,
                    "updated_at": datetime.now(UTC).isoformat(),
                },
                on_conflict="chapter_id,user_id",
            )
            # BOUNDED: single-row upsert into (chapter_id, user_id) UNIQUE key
            .select(_CHAPTER_CONTEXT_COLUMNS)
            .execute()
        )
    )
    written_rows = resp.data or []
    return written_rows[0] if written_rows else {}


async def get_chapter_context_row(chapter_id: str, user_id: str) -> dict[str, Any] | None:
    """Return the chapter_context row for (chapter_id, user_id), or None."""
    db: Any = get_supabase()
    resp = await asyncio.to_thread(
        lambda: (
            db.table("chapter_context")
            .select(_CHAPTER_CONTEXT_COLUMNS)
            .eq("chapter_id", chapter_id)
            .eq("user_id", user_id)
            # BOUNDED: single-row by (chapter_id, user_id) UNIQUE constraint
            .limit(1)
            .execute()
        )
    )
    fetched = resp.data or []
    return fetched[0] if fetched else None


async def get_chapter_context_prompt_block(chapter_id: str, user_id: str) -> str:
    """Fetch chapter context and return a formatted prompt block.

    Returns "" when no row exists or all fields are None.
    Never raises — callers (lesson_planner_node) must not fail on a missing context.
    """
    try:
        row = await get_chapter_context_row(chapter_id, user_id)
        if row is None:
            return ""
        return _format_chapter_context_block(
            depth_duration=row.get("depth_duration"),
            learning_need=row.get("learning_need"),
            specific_doubt=row.get("specific_doubt"),
            goal_and_skip=row.get("goal_and_skip"),
            prerequisites_done=row.get("prerequisites_done"),
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "chapter_context: failed to fetch for chapter_id=%s — continuing with empty context",
            chapter_id,
            exc_info=True,
        )
        return ""
