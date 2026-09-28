"""
Onboarding-context service for the content module (docs handoff, 2026-09-28).

Reads Q1-Q5 headline preferences + Penta-Intelligence badge labels — the
onboarding-time, well-defined subset (see
`2026-09-28-handoff-onboarding-form-30q.md` §3 for why the remaining 25
onboarding questions are excluded for now) — and formats them into a
prompt-ready text block. Injected at the "user profile (onboarding)"
precedence slot per AI_Learning_Product_Final_Strategy.pdf §5 — BEFORE
book_context and chapter_context (see `prompt_context.py`'s own precedence
docstring).

This module needs data owned by the ASSESSMENT module
(`onboarding_answers_v2`, `learner_dna`) — CLAUDE.md's one-discipline rule
("modules communicate only through service layer, never via direct DB access
into another module's tables") is honoured by calling
`assessment.service.get_onboarding_lesson_context`, a public function, never
querying either table directly from here. Pattern otherwise mirrors
`context.py` (book_context) / `context_chapter.py` (chapter_context), which
are intentionally independent of each other and of this module.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# OnboardingLessonContext attribute -> prompt label, in Q1-Q5's own order.
_PREF_LABELS: list[tuple[str, str]] = [
    ("stated_goal", "Stated goal"),
    ("current_level", "Level"),
    ("preferred_language", "Language preference"),
    ("preferred_tone", "Tone preference"),
    ("schooling_level", "Schooling"),
]


async def get_onboarding_context_prompt_context(user_id: str) -> str:
    """Return a formatted onboarding-context block for prompt injection, or
    "" if the student has no onboarding data on file.

    Never raises — a DB error or missing data returns an empty string so a
    context fetch failure does NOT abort lesson generation (mirrors
    `get_book_context_prompt_context`/`get_chapter_context_prompt_block`'s
    own never-raises contract).
    """
    if not user_id:
        return ""

    try:
        from app.modules.assessment.service import get_onboarding_lesson_context

        ctx = await get_onboarding_lesson_context(user_id)
    except Exception:
        logger.warning(
            "[onboarding_context] fetch failed for user_id=%s — returning empty context",
            user_id,
            exc_info=True,
        )
        return ""

    lines: list[str] = ["[Onboarding Context]"]

    # Defensive sanitisation (collapse newlines) matching context.py's own
    # posture for its MCQ fields — these are frontend-selected option text,
    # not free-typed input, but onboarding_answers_v2.response_text has no
    # DB/Pydantic constraint tying it to the real option strings (Scale &
    # Load Q2 in the story), so treat it the same as untrusted text.
    for attr, label in _PREF_LABELS:
        value = getattr(ctx, attr, None)
        if value:
            sanitised = " ".join(str(value).splitlines())
            lines.append(f"{label}: {sanitised}")

    if ctx.penta_badge_labels:
        # Badge labels are backend-owned fixed strings (PENTA_BADGE_THRESHOLDS
        # .values()), not user-supplied — no sanitisation needed.
        lines.append(f"Learning style badges: {', '.join(ctx.penta_badge_labels)}")

    if len(lines) == 1:
        return ""

    return "\n".join(lines)
