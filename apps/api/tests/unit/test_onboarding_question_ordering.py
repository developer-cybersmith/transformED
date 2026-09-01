"""Guard: onboarding question option ORDER is the Learner DNA scoring contract.

Scoring formula (service.py _compute_dimension_scores):
    normalized = (selected_index / 3) * 100
Option at index 0 → score 0.  Option at index 3 → score 100.
A silent reorder of any options array corrupts every sub-dimension score
for the affected questions from the moment of merge.

To update this snapshot legitimately:
1. Change EXPECTED_OPTIONS below.
2. Add a comment on the changed question explaining the intended gradient
   direction (which end of the spectrum is index-0, which is index-3).
3. Get a 4-dev PR review — this is a scoring-contract change, not a copy edit.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

QUESTIONS_TS = (
    Path(__file__).resolve().parents[4]
    / "apps"
    / "web"
    / "src"
    / "components"
    / "onboarding"
    / "questions.ts"
)

# Golden snapshot.  Key = question_id.  Value = options in scored order.
# Gradient convention per sub-dimension (index 0 = score 0, index 3 = score 100):
#   processing_speed      slowest/most-effort → fastest/most-immediate
#   pattern_recognition   rote/repetition → narrative/pattern-based
#   logical_deduction     (see question text for gradient direction)
#   frustration_tolerance best coping → worst coping / avoidance
#   persistence           least persistent (give-up) → most persistent (keep-trying)
#   help_seeking          self-directed → seeks external help
#   curiosity_index       stay-focused (least curious) → explores tangents (most curious)
#   study_independence    most autonomous → most guided
#   goal_orientation      most systematic → least systematic
EXPECTED_OPTIONS: dict[str, list[str]] = {
    # ── Cognitive — 8 ────────────────────────────────────────────────────
    # c1 · pattern_recognition: big-picture first → pattern-discovery
    "c1": [
        "See the big picture first, then details",
        "Start with specific examples, then generalise",
        "Work through step-by-step instructions",
        "Discover patterns on my own",
    ],
    # c2 · logical_deduction: visual/diagram → prior-knowledge linking
    "c2": [
        "Explained with diagrams or visuals",
        "Explained with real-world analogies",
        "Broken into numbered steps",
        "Linked to prior knowledge I already have",
    ],
    # c3 · logical_deduction: structured sub-problems → trial-and-error
    "c3": [
        "Break it into smaller sub-problems",
        "Look for a similar problem I've solved before",
        "Think about it holistically before diving in",
        "Try different approaches until one works",
    ],
    # c4 · processing_speed: needs-many-passes (slow) → immediate (fast)
    "c4": [
        "Only after practising with it multiple times",
        "After a second pass or worked example",
        "After one full reading or explanation",
        "Immediately — I connect it to what I know within the first pass",
    ],
    # c5 · pattern_recognition: rote-repetition → narrative/story connection
    "c5": [
        "Repetition and practice",
        "Teaching it to someone else",
        "Making notes in my own words",
        "Connecting it to a story or narrative",
    ],
    # c6 · processing_speed: dense/detailed → narrative/minimal-jargon
    "c6": [
        "Dense, detailed explanations",
        "Concise summaries with key points",
        "Examples and code/math alongside theory",
        "Narrative writing with minimal jargon",
    ],
    # c7 · logical_deduction: very comfortable with ambiguity → strongly prefers certainty
    "c7": [
        "Very comfortable — I work well with open-ended problems",
        "Somewhat comfortable",
        "I prefer clear answers but can tolerate some uncertainty",
        "I strongly prefer clear, definite answers",
    ],
    # c8 · pattern_recognition: rote recall → real-world application/pattern
    "c8": [
        "Multiple-choice recall",
        "Short written explanation",
        "Problem-solving / worked example",
        "Real-world application scenario",
    ],
    # ── Emotional — 5 ────────────────────────────────────────────────────
    # e1 · frustration_tolerance: motivated-to-improve → indifferent (best coping at 0)
    "e1": [
        "Motivated to understand why",
        "Briefly discouraged, then I move on",
        "Quite frustrated",
        "Indifferent — I focus on the next question",
    ],
    # e2 · persistence: give-up/move-on → keep-trying (least persistent at 0)
    "e2": [
        "Move on to a different topic and return later (or not at all)",
        "Lower the difficulty and build up gradually",
        "Take a break and return with fresh eyes",
        "Keep trying with different approaches until I succeed",
    ],
    # e3 · frustration_tolerance: stay-with-it (best) → move-on/hope (worst)
    "e3": [
        "Stay with it — I know persistence will pay off",
        "Feel frustrated but push through",
        "Take a break before returning to it",
        "Move on and hope it becomes clearer later",
    ],
    # e4 · help_seeking: self-directed curiosity → overwhelmed/skip-ahead
    "e4": [
        "Curiosity — I want to dig deeper",
        "A bit uneasy, but I push through",
        "I feel stuck and need a hint",
        "Overwhelmed — I'd rather skip ahead",
    ],
    # e5 · help_seeking: self-directed search → ask external help
    "e5": [
        "Search for the answer or explanation yourself",
        "Re-read the material more carefully",
        "Take a break and come back to it",
        "Ask a classmate, tutor, or AI tool",
    ],
    # ── Self-Direction — 7 ───────────────────────────────────────────────
    # s1 · goal_orientation: always-detailed-plans → rarely-or-never
    "s1": [
        "Always — I make detailed plans",
        "Usually",
        "Occasionally",
        "Rarely or never",
    ],
    # s2 · curiosity_index: structured-dive → define-scope-before-exploring
    "s2": [
        "Dive in immediately with a structured plan",
        "Explore broadly before focusing",
        "Wait for specific guidance",
        "Prefer to define a clear scope before exploring",
    ],
    # s3 · study_independence: full-autonomy → fully-guided
    "s3": [
        "I want full control over pacing",
        "Guided pacing with ability to override",
        "Mostly guided, with occasional choices",
        "Fully guided — tell me what comes next",
    ],
    # s4 · study_independence: decide-myself → follow-exactly
    "s4": [
        "To decide the order and depth of topics yourself",
        "A recommended path with freedom to skip or dive deeper",
        "A set sequence with clear checkpoints",
        "To follow exactly what the system suggests",
    ],
    # s5 · goal_orientation: regular-self-testing → almost-never
    "s5": [
        "Regularly, through self-testing",
        "Occasionally, when I feel uncertain",
        "Rarely — I rely on external tests",
        "Almost never",
    ],
    # s6 · curiosity_index: stays-focused → follows-tangents
    "s6": [
        "Stay focused — extra reading is not something I usually do",
        "Finish the required material first, then explore if time allows",
        "Note it for later but stay on the lesson path",
        "Follow tangential links and explore further on your own",
    ],
    # s7 · study_independence: immediately-review → rarely-does-anything
    "s7": [
        "Immediately review and summarise notes",
        "Reflect briefly, then move on",
        "Check off a to-do and move on",
        "Rarely do anything after finishing",
    ],
}


def _parse_ts_string(raw: str) -> str:
    """Unescape TypeScript single-quoted string content to a Python string."""
    return raw.replace("\\'", "'").replace("\\\\", "\\")


def _extract_questions(ts_content: str) -> dict[str, list[str]]:
    """Parse each question's options array from questions.ts line by line."""
    result: dict[str, list[str]] = {}
    for line in ts_content.splitlines():
        m_id = re.search(r"id: '(\w+)'", line)
        if not m_id:
            continue
        qid = m_id.group(1)
        m_opts = re.search(r"options: \[(.+)\] \}", line)
        if not m_opts:
            continue
        raw = m_opts.group(1)
        options: list[str] = []
        i = 0
        while i < len(raw):
            if raw[i] == "'":
                j = i + 1
                while j < len(raw):
                    if raw[j] == "\\" and j + 1 < len(raw):
                        j += 2
                    elif raw[j] == "'":
                        options.append(_parse_ts_string(raw[i + 1 : j]))
                        i = j + 1
                        break
                    else:
                        j += 1
                else:
                    break
            else:
                i += 1
        if options:
            result[qid] = options
    return result


@pytest.mark.skipif(
    not QUESTIONS_TS.exists(),
    reason="Frontend not present in this environment — skipping option-order guard",
)
def test_question_option_order_matches_scoring_contract() -> None:
    """Option position IS the Learner DNA scoring contract.

    Failed? Option ordering in questions.ts changed.
    Update EXPECTED_OPTIONS only after a 4-dev review that documents the
    intended scoring gradient for each changed question.
    """
    content = QUESTIONS_TS.read_text(encoding="utf-8")
    actual = _extract_questions(content)

    missing = [qid for qid in EXPECTED_OPTIONS if qid not in actual]
    assert not missing, f"Questions missing from questions.ts: {missing}"

    mismatches: list[str] = []
    for qid, expected_opts in EXPECTED_OPTIONS.items():
        actual_opts = actual.get(qid, [])
        if actual_opts != expected_opts:
            mismatches.append(
                f"\n  {qid!r}:\n    expected: {expected_opts}\n    actual:   {actual_opts}"
            )
    detail = "".join(mismatches)
    assert not mismatches, (
        "Option ordering changed — this silently corrupts Learner DNA scores.\n"
        "Update EXPECTED_OPTIONS only after a 4-dev PR review documenting the "
        f"intended gradient direction for each changed question.{detail}"
    )
