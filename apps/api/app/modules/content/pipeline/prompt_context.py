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


def merge_book_context(base_prompt: str, book_context: str) -> tuple[str, bool]:
    """Append `book_context` to `base_prompt`, enforcing the 2,000-char budget.

    Returns ``(merged_prompt, was_truncated)``.

    ``was_truncated`` is ``True`` when ``book_context`` exceeded the budget and
    was cut.  Callers MUST surface this as explicit degradation — write it to
    a durable record (e.g. ``lesson_jobs.node_outputs``) or emit a Langfuse
    warning span.  A bare ``logger.warning`` is insufficient per CLAUDE.md:
    "not a logger.warning nobody reads."

    Truncation algorithm:
    - Find the last newline within the budget so we never cut mid-field.
    - When no newline exists in the budget slice, fall back to a hard character
      cut (field boundary guarantee cannot be honoured) and log the deviation.
    """
    if not book_context:
        return base_prompt, False

    if len(book_context) <= _BOOK_CONTEXT_MAX_CHARS:
        return base_prompt + "\n\n" + book_context, False

    budget_slice = book_context[:_BOOK_CONTEXT_MAX_CHARS]
    last_newline = budget_slice.rfind("\n")
    if last_newline != -1:
        truncated = budget_slice[:last_newline]
    else:
        # No newline in the budget — hard cut; field-boundary guarantee lost.
        truncated = budget_slice
        logger.warning(
            "merge_book_context: no newline in first %d chars — hard cut applied",
            _BOOK_CONTEXT_MAX_CHARS,
        )
    logger.warning(
        "merge_book_context: book_context exceeded %d chars (%d chars) — "
        "truncated (%d chars kept). Surface this via Langfuse or durable record.",
        _BOOK_CONTEXT_MAX_CHARS,
        len(book_context),
        len(truncated),
    )
    return base_prompt + "\n\n" + truncated + _TRUNCATION_MARKER, True
