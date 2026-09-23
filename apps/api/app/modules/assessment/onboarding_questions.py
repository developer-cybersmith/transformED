"""
Onboarding question specs — 30-question redesign (Story 235).

The 20-question form's QUESTION_SUBDIMENSION_MAP (question -> one of 9 learner_dna
behavioral columns) is retired: the new 30-question taxonomy (Goal/Level/Language/
Tone/... A-J categories, Section 4.1 of the source spec) does not map cleanly onto
those 9 dimensions (confirmed during Story 235's design — see the story file's
Problem Statement). Forcing that mapping would fabricate scores from answers never
designed to produce them.

ALL_NINE_DIMENSIONS / BADGE_THRESHOLD / BADGE_THRESHOLDS are KEPT — dna_fusion.py's
session-driven EMA path still uses them; only the onboarding-time *scoring* of those
9 dimensions from question answers is removed (dna_fusion.py never read this module
in the first place — it computes signals from session behavior, not onboarding
answers, so nothing there needs to change).

Source of truth for question content: docs/proposals/source-specs/
2026-09-hie-lecture-format-45min-and-onboarding-pack.pdf, Section 4.1.
"""

from __future__ import annotations

from typing import Literal

QuestionFormat = Literal["mcq", "one_liner", "true_false"]

# Maps each of the 30 question_ids to its answer format. Q1-Q20 are MCQ, Q21-Q25 are
# one-liner free text, Q26-Q30 are true/false. The backend only needs format + (for
# MCQ) option count for input validation — question TEXT/options live in the
# frontend's questions.ts, matching how the 20-question form already split this.
Q_SPEC: dict[str, QuestionFormat] = {
    **{f"q{i}": "mcq" for i in range(1, 21)},
    **{f"q{i}": "one_liner" for i in range(21, 26)},
    **{f"q{i}": "true_false" for i in range(26, 31)},
}

# Per-question MCQ option count. All 5-option except Q6/Q7 (Bilingual Bridge inner-
# voice/translation-gap questions), which the source PDF gives only 4 options each.
MCQ_OPTION_COUNTS: dict[str, int] = {f"q{i}": (4 if i in (6, 7) else 5) for i in range(1, 21)}

# The exact 30 valid question_ids — used to validate a submission is neither missing
# nor carrying unknown/duplicate ids.
ALL_QUESTION_IDS: frozenset[str] = frozenset(Q_SPEC)

# ── Tier B: Penta-Intelligence baseline (Q16-Q20), the PDF's own "(scored)" section ──
#
# Per-option score (0-100), keyed by 0-indexed selected_index. Sourced from the PDF's
# answer key — see the story file's "Source verification" table for the full
# PDF-text-to-score trace (which scores are PDF-exact vs. this story's own
# quantization of a stated qualitative rank).
PENTA_SCORING: dict[str, dict[int, float]] = {
    "q16": {0: 0.0, 1: 100.0, 2: 25.0, 3: 25.0, 4: 25.0},  # CRT: b) correct=100, a) trap=0
    "q17": {0: 0.0, 1: 100.0, 2: 60.0, 3: 0.0, 4: 60.0},  # EQ scenario: b) highest
    "q18": {0: 0.0, 1: 50.0, 2: 100.0, 3: 85.0, 4: 50.0},  # SQ dilemma: c) highest, d) also high
    "q19": {0: 0.0, 1: 0.0, 2: 100.0, 3: 0.0, 4: 0.0},  # CTQ fact-vs-opinion: c) correct
    "q20": {0: 25.0, 1: 25.0, 2: 75.0, 3: 100.0, 4: 25.0},  # RRQ research: d) highest, c) second
}

# The 5 new learner_dna columns this story adds (Design §2 migration), in Q16-Q20 order.
PENTA_DIMENSIONS: tuple[str, ...] = ("penta_iq", "penta_eq", "penta_sq", "penta_ctq", "penta_rrq")

# question_id -> learner_dna column name.
PENTA_QUESTION_MAP: dict[str, str] = {
    "q16": "penta_iq",
    "q17": "penta_eq",
    "q18": "penta_sq",
    "q19": "penta_ctq",
    "q20": "penta_rrq",
}

# Score threshold (inclusive) to award a Penta badge — same convention as BADGE_THRESHOLD.
PENTA_BADGE_THRESHOLD = 70.0

# Maps penta dimension -> plain-English badge label. No raw IQ/EQ/SQ language on any
# student-facing surface (CLAUDE.md rule) — these are what actually get shown/prompted.
PENTA_BADGE_THRESHOLDS: dict[str, str] = {
    "penta_iq": "Sharp Reasoner",
    "penta_eq": "Empathetic Responder",
    "penta_sq": "Principled Decision-Maker",
    "penta_ctq": "Fact-Checker",
    "penta_rrq": "Deep Researcher",
}

# All 9 sub-dimension names — must match learner_dna column names in DB exactly.
# Still used by dna_fusion.py's session-driven EMA path (unchanged by this story).
ALL_NINE_DIMENSIONS: tuple[str, ...] = (
    "pattern_recognition",
    "logical_deduction",
    "processing_speed",
    "frustration_tolerance",
    "persistence",
    "help_seeking",
    "goal_orientation",
    "curiosity_index",
    "study_independence",
)

# Score threshold (inclusive) to award a badge for a sub-dimension.
BADGE_THRESHOLD = 70.0

# Maps sub-dimension → plain English badge label (no IQ/EQ/SQ language per CLAUDE.md).
BADGE_THRESHOLDS: dict[str, str] = {
    "pattern_recognition": "Pattern Thinker",
    "logical_deduction": "Logical Reasoner",
    "processing_speed": "Quick Processor",
    "frustration_tolerance": "Resilient Learner",
    "persistence": "Persistent Achiever",
    "help_seeking": "Collaborative Learner",
    "goal_orientation": "Goal-Oriented",
    "curiosity_index": "Curious Explorer",
    "study_independence": "Self-Directed Learner",
}
