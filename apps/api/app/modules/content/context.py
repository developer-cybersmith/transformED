"""
Book-context service for the content module (Story S5-1, Issue #231).

Reads `book_context` rows and formats them into a prompt-ready text block.
The block is injected into lesson-generation prompts at the "book context"
precedence slot (after user profile, before chapter instructions) per
AI_Learning_Product_Final_Strategy.pdf §5.

This module is a content-module concern — it must NOT import from the
assessment module. The pattern mirrors assessment/service.py::get_learner_context
but is intentionally independent (different table, different precedence slot).
"""

from __future__ import annotations

import logging

from app.core.db import get_supabase
from app.core.db import single_row

logger = logging.getLogger(__name__)

# Column list — verified against supabase/migrations/20260921000000_book_context.sql.
# user_id is included so the post-fetch ownership double-check is possible
# (mirrors _fetch_owned_book's belt-and-braces pattern).
_BOOK_CONTEXT_COLUMNS = (
    "book_id,user_id,why_uploaded,what_to_achieve,complete_or_selected,"
    "important_sections,deadline_and_depth,follow_or_reorganize,updated_at"
)

# Human-readable labels matching the §4.2 field questions (abbreviated for
# the prompt block — the full question wording is used in the UI, not here).
_FIELD_LABELS: list[tuple[str, str]] = [
    ("why_uploaded", "Why uploaded"),
    ("what_to_achieve", "Goal"),
    ("complete_or_selected", "Scope"),
    ("important_sections", "Focus areas"),
    ("deadline_and_depth", "Deadline / depth"),
    ("follow_or_reorganize", "Teaching approach"),
]


async def get_book_context_prompt_context(book_id: str, user_id: str) -> str:
    """Return a formatted book-context block for prompt injection, or "" if none saved.

    Never raises — a DB error or missing row returns an empty string so a
    context fetch failure does NOT abort lesson generation (Scale & Load Q2:
    context injection is best-effort, not a hard requirement).

    The returned block is ready for `merge_book_context` in
    `apps/api/app/modules/content/pipeline/prompt_context.py`.
    """
    if not book_id or not user_id:
        return ""

    try:
        import asyncio

        supabase = get_supabase()
        resp = await asyncio.to_thread(
            lambda: (
                supabase.table("book_context")
                .select(_BOOK_CONTEXT_COLUMNS)
                .eq("book_id", book_id)
                .eq("user_id", user_id)
                .maybe_single()
                .execute()
            )
        )
        row: dict | None = single_row(resp)
    except Exception:
        logger.warning(
            "[book_context] fetch failed for book_id=%s — returning empty context",
            book_id,
            exc_info=True,
        )
        return ""

    if row is None:
        return ""

    # Build the text block: only include fields with a non-empty value.
    lines: list[str] = ["[Book Context]"]
    for db_col, label in _FIELD_LABELS:
        value = (row.get(db_col) or "").strip()
        if value:
            lines.append(f"{label}: {value}")

    # If the student filled nothing in, the block would be just "[Book Context]"
    # with no real content — return empty string instead.
    if len(lines) == 1:
        return ""

    return "\n".join(lines)


async def upsert_book_context(
    book_id: str,
    user_id: str,
    *,
    why_uploaded: str | None,
    what_to_achieve: str | None,
    complete_or_selected: str | None,
    important_sections: str | None,
    deadline_and_depth: str | None,
    follow_or_reorganize: str | None,
) -> dict:
    """Upsert one book_context row and return the saved row dict.

    Uses ON CONFLICT (book_id, user_id) DO UPDATE SET — atomic at Postgres
    level, no check-then-act race (Scale & Load Q6). Never raises 409.
    """
    import asyncio
    from datetime import UTC, datetime

    supabase = get_supabase()
    payload: dict = {
        "book_id": book_id,
        "user_id": user_id,
        "why_uploaded": why_uploaded,
        "what_to_achieve": what_to_achieve,
        "complete_or_selected": complete_or_selected,
        "important_sections": important_sections,
        "deadline_and_depth": deadline_and_depth,
        "follow_or_reorganize": follow_or_reorganize,
        "updated_at": datetime.now(UTC).isoformat(),
    }

    resp = await asyncio.to_thread(
        lambda: (
            supabase.table("book_context")
            .upsert(payload, on_conflict="book_id,user_id")
            .select(_BOOK_CONTEXT_COLUMNS)
            .execute()
        )
    )
    from app.core.db import rows as db_rows

    saved_rows = db_rows(resp)
    if not saved_rows:
        raise RuntimeError(f"book_context upsert returned no row for book_id={book_id}")
    return saved_rows[0]


async def get_book_context_row(book_id: str, user_id: str) -> dict | None:
    """Fetch the raw book_context row or None if not saved."""
    import asyncio

    if not book_id or not user_id:
        return None

    supabase = get_supabase()
    resp = await asyncio.to_thread(
        lambda: (
            supabase.table("book_context")
            .select(_BOOK_CONTEXT_COLUMNS)
            .eq("book_id", book_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
    )
    return single_row(resp)
