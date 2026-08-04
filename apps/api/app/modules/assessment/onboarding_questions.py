"""
Onboarding question → sub-dimension mapping.

20 questions map to 9 learner_dna sub-dimensions (column names in the DB).
Source: Story 3-18, Story 3-4 AC #10, CLAUDE.md Learner DNA rules.
"""

from __future__ import annotations

# Maps each question_id to its learner_dna sub-dimension column name.
QUESTION_SUBDIMENSION_MAP: dict[str, str] = {
    # Cognitive — 8 questions
    "c1": "pattern_recognition",  # learning style
    "c2": "logical_deduction",  # concept abstraction
    "c3": "logical_deduction",  # problem-solving
    "c4": "processing_speed",  # attention span
    "c5": "pattern_recognition",  # retention method
    "c6": "processing_speed",  # reading preference
    "c7": "logical_deduction",  # ambiguity tolerance
    "c8": "pattern_recognition",  # quiz format preference
    # Emotional — 5 questions
    "e1": "frustration_tolerance",  # reaction to wrong answers
    "e2": "persistence",  # encouragement response
    "e3": "frustration_tolerance",  # time pressure effect
    "e4": "help_seeking",  # confusion reaction
    "e5": "help_seeking",  # AI tracking comfort
    # Self-direction — 7 questions
    "s1": "goal_orientation",  # goal-setting frequency
    "s2": "curiosity_index",  # free-choice behaviour
    "s3": "study_independence",  # pacing preference
    "s4": "study_independence",  # setback response
    "s5": "goal_orientation",  # self-review habit
    "s6": "curiosity_index",  # study consistency
    "s7": "study_independence",  # post-lesson behaviour
}

# All 9 sub-dimension names — must match learner_dna column names in DB exactly.
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
