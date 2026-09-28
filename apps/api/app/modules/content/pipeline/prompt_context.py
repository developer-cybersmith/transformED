"""
Shared prompt-merge helpers for per-lesson context injection
(Story S5-1/Issue #231 — book_context; Story 249/Issue #249 —
chapter_context; docs handoff 2026-09-28 — onboarding_context).

All prompt sites call `merge_onboarding_context`/`merge_book_context`/
`merge_chapter_context` rather than doing ad-hoc string concatenation
independently. All three enforce their own character budget with explicit,
surfaced degradation — silent truncation is never acceptable (CLAUDE.md
binding rule). They share one truncation algorithm (`_merge_context_block`)
so the three budgets can never silently drift apart in behavior, only in
their (independently-derived) size.

Precedence slot per AI_Learning_Product_Final_Strategy.pdf §5:
  accuracy & safety → source content → system teaching rules → duration →
  **user profile (onboarding)** ← here → **book context** ← here → **chapter
  instructions** ← here → user prompt → past performance

Onboarding context is appended first (the user-profile personalization
layer), then book context, then chapter context — matching this precedence
order exactly at all three call sites that merge more than one of them
(`_planner_system_prompt`, `slide_generator_node`, `narration_generator_node`).
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


# 5,500-character hard cap on the onboarding-context block in the merged
# prompt (docs handoff 2026-09-28). Derivation, independent of book_context's
# 2,000 and chapter_context's 1,300 (CLAUDE.md: re-derive every inherited
# cap): OnboardingAnswer.response_text is Pydantic-capped at 1,000 chars for
# EVERY format including 'mcq' (unlike book_context's MCQ fields, which are
# closed Python Literal enums with no possible length growth, onboarding's
# response_text has no matching-known-option-text validation at the DB/API
# layer — see content/context_onboarding.py's own comment). 5 fields × 1,000
# chars + 5 field labels (~70 chars total) + newlines (~5) + a badges line
# (5 fixed backend-owned badge strings, ~121 chars worst case) + the
# "[Onboarding Context]" header (~21 chars) ≈ 5,217 measured worst case.
# 5,500 leaves ~5.4% headroom, in line with book_context's ~2.6% and
# chapter_context's ~6.6% margins.
_ONBOARDING_CONTEXT_MAX_CHARS: int = 5_500

# Distinct from book/chapter's own markers so an admin reading a truncated
# prompt can tell which context was cut.
_ONBOARDING_TRUNCATION_MARKER: str = "\n[Onboarding context truncated]"


def merge_onboarding_context(base_prompt: str, onboarding_context: str) -> tuple[str, bool]:
    """Append `onboarding_context` to `base_prompt`, enforcing its own
    5,500-char budget.

    See `_merge_context_block`'s own docstring for the shared algorithm/contract.
    """
    return _merge_context_block(
        base_prompt,
        onboarding_context,
        max_chars=_ONBOARDING_CONTEXT_MAX_CHARS,
        truncation_marker=_ONBOARDING_TRUNCATION_MARKER,
        log_label="merge_onboarding_context",
    )


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
