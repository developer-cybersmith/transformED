"""
Shared prompt-merge helper for per-lesson context injection (Story S5-1, Issue #231).

All three prompt sites (lesson_planner, slide_generator, narration_generator) call
`merge_book_context` rather than doing ad-hoc string concatenation independently.
This single function enforces the 2,000-character budget with explicit, surfaced
degradation — silent truncation is never acceptable (CLAUDE.md binding rule).

Precedence slot per AI_Learning_Product_Final_Strategy.pdf §5:
  accuracy & safety → source content → system teaching rules → duration →
  user profile (onboarding) → **book context** ← here → chapter instructions →
  user prompt → past performance

Book context is appended AFTER any onboarding/user-profile block and BEFORE
any chapter-level instructions. When no onboarding context is in the prompt
today (it isn't — that injection is a separate story), book context is simply
the first personalization layer.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 2,000-character hard cap on the book-context block in the merged prompt.
# Derivation: GPT-4o 128k token context × ~1.5% budget for book context ≈
# 1,920 tokens × ~1 char/token average ≈ 2,000 chars. Re-derive if prompt
# structure changes significantly (e.g. large tier-framing additions).
_BOOK_CONTEXT_MAX_CHARS: int = 2_000

# Marker appended when the block is truncated so the recipient knows context
# was cut — never silent (CLAUDE.md: "Silent truncation is never acceptable").
_TRUNCATION_MARKER: str = "\n[Book context truncated]"


def merge_book_context(base_prompt: str, book_context: str) -> str:
    """Append `book_context` to `base_prompt`, enforcing the 2,000-char budget.

    Returns `base_prompt` unchanged when `book_context` is empty.

    If `book_context` exceeds `_BOOK_CONTEXT_MAX_CHARS`, it is truncated at the
    last newline boundary before the limit, and `_TRUNCATION_MARKER` is appended.
    The truncation is logged at WARNING level so it appears in Langfuse traces
    alongside the lesson_id (callers must include lesson_id in their log context).

    This function is PURE (no DB calls, no side effects) — callers that need to
    persist a truncation flag on the `lessons` row must detect the marker
    themselves (e.g. `"[Book context truncated]" in merged`).
    """
    if not book_context:
        return base_prompt

    # Normalize: strip leading/trailing whitespace so a leading "\n" does not
    # cause rfind("\n") to return 0 and fall back to a char-boundary cut (F15).
    book_context = book_context.strip()
    if not book_context:
        return base_prompt

    if len(book_context) <= _BOOK_CONTEXT_MAX_CHARS:
        return base_prompt + "\n\n" + book_context

    # Truncate at the last newline within the budget so we never cut mid-field.
    budget_slice = book_context[:_BOOK_CONTEXT_MAX_CHARS]
    last_newline = budget_slice.rfind("\n")
    truncated = budget_slice[:last_newline] if last_newline > 0 else budget_slice
    logger.warning(
        "merge_book_context: book_context exceeded %d chars (%d chars) — "
        "truncated at field boundary (%d chars kept). "
        "Callers should persist book_context_truncated=true on the lessons row.",
        _BOOK_CONTEXT_MAX_CHARS,
        len(book_context),
        len(truncated),
    )
    return base_prompt + "\n\n" + truncated + _TRUNCATION_MARKER
