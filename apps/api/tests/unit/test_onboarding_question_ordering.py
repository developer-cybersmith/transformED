"""Guard: Penta-Intelligence (Q16-Q20) option order IS the scoring contract.

Story 235 replaced the old 20-question gradient-scoring model (every question's
option position fed `(selected_index / 3) * 100`) with a narrower one: only
Q16-Q20 (the source PDF's "(scored)" Penta-Intelligence section) have a real
per-option answer key (PENTA_SCORING in onboarding_questions.py). Q1-15 are
"no wrong answer" preference questions — position carries no scoring meaning
for them. Q21-30 aren't scored at all yet (deferred, Tier C).

A silent reorder of Q16-Q20's options in questions.ts (frontend) would desync
from PENTA_SCORING's index-keyed answer key (backend) — the option shown as
"correct"/"highest" to the student would no longer be the one actually scored
as such. This guard cross-checks the two stay in sync.

To update this snapshot legitimately:
1. Change EXPECTED_PENTA_OPTIONS below to match the new questions.ts text.
2. Update PENTA_SCORING in onboarding_questions.py to match the new option order.
3. Get review — this is the scoring contract for the story's one real,
   spec-derived initial Learner DNA seed (Tier B).
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

# Golden snapshot — option text in PDF/questions.ts order for the 5 scored questions.
# Sourced verbatim from docs/proposals/source-specs/
# 2026-09-hie-lecture-format-45min-and-onboarding-pack.pdf, Section 4.1, Q16-Q20.
EXPECTED_PENTA_OPTIONS: dict[str, list[str]] = {
    "q16": [
        "₹10",
        "₹5",
        "₹15",
        "₹1",
        "₹2.50",
    ],
    "q17": [
        "Snap back immediately",
        "Assume they're having a bad day and check on them later",
        "Ignore them for days",
        "Confront them aggressively in front of others",
        "Feel hurt but say nothing and overthink",
    ],
    "q18": [
        "Keep the cash — finder's luck",
        "Return it and hope for a reward",
        "Return it anonymously",
        "Hand it to the police / authority",
        "Post about it to look good",
    ],
    "q19": [
        "'This policy is a disaster'",
        "'Everyone knows this is true'",
        "'Unemployment rose from 4.1% to 5.3% in the report'",
        "'Any fool can see the truth'",
        "'Experts agree without question'",
    ],
    "q20": [
        "First Google result",
        "Wikipedia summary",
        "Compare 3+ independent sources",
        "Go to primary sources / papers",
        "Ask AI and accept the answer",
    ],
}


def _parse_ts_string(raw: str) -> str:
    """Unescape TypeScript single-quoted string content to a Python string."""
    return raw.replace("\\'", "'").replace("\\\\", "\\")


def _extract_questions(ts_content: str) -> dict[str, list[str]]:
    """Parse each question's options array from questions.ts.

    Format-agnostic: each question object may be single-line or multi-line
    (one field per line) — finds every `id: 'qN'` occurrence, then scans the
    substring up to the NEXT `id:` occurrence (or end of file) for that
    question's own `options: [...]` array, so field order/line-wrapping
    doesn't matter.
    """
    id_matches = list(re.finditer(r"id:\s*'(\w+)'", ts_content))
    result: dict[str, list[str]] = {}
    for idx, m_id in enumerate(id_matches):
        qid = m_id.group(1)
        block_start = m_id.end()
        block_end = id_matches[idx + 1].start() if idx + 1 < len(id_matches) else len(ts_content)
        block = ts_content[block_start:block_end]

        m_opts = re.search(r"options:\s*\[(.*?)\]", block, re.DOTALL)
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
def test_penta_question_option_order_matches_scoring_contract() -> None:
    """Option position for Q16-Q20 IS the Penta-Intelligence scoring contract.

    Failed? Option ordering for one of the 5 scored questions changed in
    questions.ts without a matching PENTA_SCORING update. Update
    EXPECTED_PENTA_OPTIONS only after also updating PENTA_SCORING to match.
    """
    content = QUESTIONS_TS.read_text(encoding="utf-8")
    actual = _extract_questions(content)

    missing = [qid for qid in EXPECTED_PENTA_OPTIONS if qid not in actual]
    assert not missing, f"Scored questions missing from questions.ts: {missing}"

    mismatches: list[str] = []
    for qid, expected_opts in EXPECTED_PENTA_OPTIONS.items():
        actual_opts = actual.get(qid, [])
        if actual_opts != expected_opts:
            mismatches.append(
                f"\n  {qid!r}:\n    expected: {expected_opts}\n    actual:   {actual_opts}"
            )
    detail = "".join(mismatches)
    assert not mismatches, (
        "Q16-Q20 option ordering changed — this desyncs from PENTA_SCORING's "
        f"index-keyed answer key in onboarding_questions.py.{detail}"
    )


@pytest.mark.unit
def test_penta_scoring_answer_key_matches_pdf_correct_answers() -> None:
    """Cross-check PENTA_SCORING's highest-scored index against the PDF's stated
    correct/highest answer for each of Q16-Q20 (Answer Key, Section 4.1)."""
    from app.modules.assessment.onboarding_questions import PENTA_SCORING

    # index -> expected "highest score" option, per the PDF's own answer key.
    expected_top_index = {
        "q16": 1,  # b) ₹5 — correct
        "q17": 1,  # b) — highest EQ
        "q18": 2,  # c) — highest SQ
        "q19": 2,  # c) — verifiable fact
        "q20": 3,  # d) — highest RRQ
    }
    for qid, top_index in expected_top_index.items():
        scores = PENTA_SCORING[qid]
        assert scores[top_index] == max(scores.values()), (
            f"{qid}: PDF's stated top answer (index {top_index}) is not the "
            f"highest-scored option in PENTA_SCORING. Scores: {scores}"
        )
