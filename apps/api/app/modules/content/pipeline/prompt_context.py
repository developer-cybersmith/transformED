"""
Shared prompt-merge helpers for per-lesson context injection
(Story S5-1/Issue #231 — book_context; Story 249/Issue #249 — chapter_context).

All prompt sites call `merge_book_context`/`merge_chapter_context` rather than
doing ad-hoc string concatenation independently. Both enforce their own
character budget with explicit, surfaced degradation — silent truncation is
never acceptable (CLAUDE.md binding rule). They share one truncation
algorithm (`_merge_context_block`) so the two budgets can never silently
drift apart in behavior, only in their (independently-derived) size.

Precedence slot per AI_Learning_Product_Final_Strategy.pdf §5:
  accuracy & safety → source content → system teaching rules → duration →
  user profile (onboarding) → **book context** ← here → **chapter
  instructions** ← here → user prompt → past performance

Book context is appended AFTER any onboarding/user-profile block and BEFORE
any chapter-level instructions; chapter context is appended after book
context. When no onboarding context is in the prompt today (it isn't — that
injection is a separate story), book context is simply the first
personalization layer.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _merge_context_block(
    base_prompt: str,
    context_block: str,
    *,
    max_chars: int,
    truncation_marker: str,
    log_label: str,
) -> tuple[str, bool]:
    """Shared truncation algorithm behind `merge_book_context`/`merge_chapter_context`.

    Returns ``(merged_prompt, was_truncated)``.

    Truncation algorithm:
    - Find the last newline within the budget so we never cut mid-field.
    - When no newline exists in the budget slice, fall back to a hard character
      cut (field boundary guarantee cannot be honoured) and log the deviation.

    ``was_truncated`` is ``True`` when ``context_block`` exceeded ``max_chars``
    and was cut. Callers MUST surface this as explicit degradation — write it
    to a durable record (e.g. ``lesson_jobs.node_outputs``) or emit a Langfuse
    warning span. A bare ``logger.warning`` is insufficient per CLAUDE.md:
    "not a logger.warning nobody reads."
    """
    if not context_block:
        return base_prompt, False

    if len(context_block) <= max_chars:
        return base_prompt + "\n\n" + context_block, False

    budget_slice = context_block[:max_chars]
    last_newline = budget_slice.rfind("\n")
    if last_newline != -1:
        truncated = budget_slice[:last_newline]
    else:
        # No newline in the budget — hard cut; field-boundary guarantee lost.
        truncated = budget_slice
        logger.warning(
            "%s: no newline in first %d chars — hard cut applied",
            log_label,
            max_chars,
        )
    logger.warning(
        "%s: context exceeded %d chars (%d chars) — "
        "truncated (%d chars kept). Surface this via Langfuse or durable record.",
        log_label,
        max_chars,
        len(context_block),
        len(truncated),
    )
    return base_prompt + "\n\n" + truncated + truncation_marker, True


# 2,000-character hard cap on the book-context block in the merged prompt.
# Derivation: GPT-4o 128k token context × ~1.5% budget ≈ 1,920 tokens.
# English text averages ~4 chars/token → 1,920 × 4 ≈ 7,680 chars of headroom.
# 2,000 is deliberately conservative: schemas.py caps each free-text field at
# 500 chars (3 fields × 500 + labels ≈ 1,948 chars max), so 2,000 is a safe
# ceiling that prevents any schema-valid input from being truncated in practice.
# If prompt structure changes (e.g. large tier-framing additions), raise this
# cap toward 7,680 — do not lower input field limits instead.
_BOOK_CONTEXT_MAX_CHARS: int = 2_000

# Marker appended when the block is truncated so the recipient knows context
# was cut — never silent (CLAUDE.md: "Silent truncation is never acceptable").
_TRUNCATION_MARKER: str = "\n[Book context truncated]"


def merge_book_context(base_prompt: str, book_context: str) -> tuple[str, bool]:
    """Append `book_context` to `base_prompt`, enforcing the 2,000-char budget.

    See `_merge_context_block`'s own docstring for the shared algorithm/contract.
    """
    return _merge_context_block(
        base_prompt,
        book_context,
        max_chars=_BOOK_CONTEXT_MAX_CHARS,
        truncation_marker=_TRUNCATION_MARKER,
        log_label="merge_book_context",
    )


# 1,300-character hard cap on the chapter-context block — Story 249 (issue
# #249), re-derived independently from book_context's 2,000 rather than
# reused unchanged (CLAUDE.md: "re-derive every inherited cap when the unit
# of work changes" — chapter_context's field SET is smaller than
# book_context's, so its cap must be too, not borrowed from a different set).
# Derivation, measured against context_chapter.py's own
# `_format_chapter_context_block`: 2 free-text fields (schemas.py caps each
# at 500 chars: specific_doubt, goal_and_skip) + 2 MCQ label lines (longest
# ~33 chars + ~24-char prefix) + 1 boolean line (~29 chars) + the
# "[Chapter Instructions]" header (~25 chars) + newline joins ≈ 1,219 chars
# measured worst case. 1,300 leaves headroom without being loose — same
# "deliberately conservative, not padded" philosophy as book_context's own
# 2,000 (which itself leaves only ~52 chars over its 1,948 measured worst case).
_CHAPTER_CONTEXT_MAX_CHARS: int = 1_300

# Distinct from book context's marker so an admin reading a truncated prompt
# can tell which of the two contexts was cut.
_CHAPTER_TRUNCATION_MARKER: str = "\n[Chapter context truncated]"


def merge_chapter_context(base_prompt: str, chapter_context: str) -> tuple[str, bool]:
    """Append `chapter_context` to `base_prompt`, enforcing its own 1,300-char budget.

    See `_merge_context_block`'s own docstring for the shared algorithm/contract.
    """
    return _merge_context_block(
        base_prompt,
        chapter_context,
        max_chars=_CHAPTER_CONTEXT_MAX_CHARS,
        truncation_marker=_CHAPTER_TRUNCATION_MARKER,
        log_label="merge_chapter_context",
    )
