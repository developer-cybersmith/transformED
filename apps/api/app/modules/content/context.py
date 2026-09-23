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
_BOOK_CONTEXT_COLUMNS = (
    "book_id,user_id,purpose,coverage_scope,expected_difficulty,deadline_depth,"
    "structure_preference,motivation,end_goal,feared_section,prior_attempt,outcome_clarity,updated_at"
)

# MCQ field → prompt label, and value → human-readable display text.
# Stored values are the compact enum strings; the prompt receives readable labels.
_MCQ_LABELS: list[tuple[str, str]] = [
    ("purpose", "Upload purpose"),
    ("coverage_scope", "Coverage scope"),
    ("expected_difficulty", "Expected difficult areas"),
    ("deadline_depth", "Deadline and depth"),
    ("structure_preference", "Teaching structure"),
]

_MCQ_DISPLAY: dict[str, dict[str, str]] = {
    "purpose": {
        "exam_prep": "Exam preparation",
        "project_job": "Project or job requirement",
        "deep_mastery": "Deep mastery",
        "quick_reference": "Quick reference",
        "recommended_reading": "Recommended reading",
    },
    "coverage_scope": {
        "complete_book": "Complete book",
        "selected_chapters": "Selected chapters",
        "difficult_sections": "Difficult sections only",
        "exam_relevant": "Exam-relevant parts",
        "ai_decide": "Let AI decide",
    },
    "expected_difficulty": {
        "theory_heavy": "Theory-heavy sections",
        "numerical_formula": "Numerical / formula sections",
        "case_studies": "Case studies",
        "dense_language": "Dense language / writing",
        "dont_know": "Unknown — AI will identify them",
    },
    "deadline_depth": {
        "urgent_2wk": "Urgent — under 2 weeks",
        "one_month": "1 month",
        "two_three_months": "2–3 months",
        "no_deadline": "No deadline",
        "key_insights_only": "Just key insights",
    },
    "structure_preference": {
        "follow_exactly": "Follow the book exactly",
        "reorganise_by_difficulty": "Reorganise by concept difficulty",
        "reorganise_by_goal": "Reorganise by learning goal",
        "hybrid": "Hybrid approach",
        "ai_choose": "Let AI choose",
    },
}

# One-liner text fields: prompt label → DB column name.
_TEXT_FIELD_LABELS: list[tuple[str, str]] = [
    ("motivation", "Motivation"),
    ("end_goal", "End goal"),
    ("feared_section", "Most worried about"),
]

# Boolean fields: DB column → prompt label.
_BOOL_LABELS: list[tuple[str, str]] = [
    ("prior_attempt", "Tried this book before and stopped"),
    ("outcome_clarity", "Can picture real-life application"),
]


async def get_book_context_prompt_context(book_id: str, user_id: str) -> str:
    """Return a formatted book-context block for prompt injection, or "" if none saved.

    Never raises — a DB error or missing row returns an empty string so a
    context fetch failure does NOT abort lesson generation (Scale & Load Q2:
    context injection is best-effort, not a hard requirement).

    Newlines inside user-supplied text fields are collapsed to spaces (F3:
    prevents prompt-injection via embedded newline + fake label sequences).
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

    lines: list[str] = ["[Book Context]"]

    # MCQ fields: map stored enum value to human-readable display label.
    # When the stored value is not a known enum member (e.g. written directly
    # via service-role client bypassing Pydantic), sanitize it the same way
    # text fields are sanitized — collapse newlines, cap length — to prevent
    # prompt injection via embedded newline + fake-label sequences.
    for col, label in _MCQ_LABELS:
        raw = row.get(col)
        if raw:
            display = _MCQ_DISPLAY.get(col, {}).get(raw)
            if display is None:
                display = " ".join(str(raw).splitlines())[:100]
            lines.append(f"{label}: {display}")

    # One-liner text fields: collapse internal newlines to prevent injection.
    for col, label in _TEXT_FIELD_LABELS:
        value = (row.get(col) or "").strip()
        if value:
            sanitised = " ".join(value.splitlines())
            lines.append(f"{label}: {sanitised}")

    # Boolean fields: only emit when not None.
    for col, label in _BOOL_LABELS:
        val = row.get(col)
        if val is not None:
            lines.append(f"{label}: {'Yes' if val else 'No'}")

    if len(lines) == 1:
        return ""

    return "\n".join(lines)


async def upsert_book_context(
    book_id: str,
    user_id: str,
    *,
    purpose: str | None,
    coverage_scope: str | None,
    expected_difficulty: str | None,
    deadline_depth: str | None,
    structure_preference: str | None,
    motivation: str | None,
    end_goal: str | None,
    feared_section: str | None,
    prior_attempt: bool | None,
    outcome_clarity: bool | None,
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
        "purpose": purpose,
        "coverage_scope": coverage_scope,
        "expected_difficulty": expected_difficulty,
        "deadline_depth": deadline_depth,
        "structure_preference": structure_preference,
        "motivation": motivation,
        "end_goal": end_goal,
        "feared_section": feared_section,
        "prior_attempt": prior_attempt,
        "outcome_clarity": outcome_clarity,
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
        raise RuntimeError("book_context upsert returned no row")
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
