"""
Unit tests for Story 2-14 (S2-14): eval harness scoring (AC-3, AC-7).

Pure-function tests over plain LessonPackage-shaped dicts — no mocking,
no live services, matching scoring.py's own no-I/O design.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.evals.scoring import score_quiz_relevance, score_slide_quality


def _well_formed_slide(slide_id: str = "slide_0") -> dict[str, Any]:
    return {
        "slide_id": slide_id,
        "title": "Cellular Respiration Overview",
        "bullets": ["The mitochondrion produces ATP", "Electron transport chain converts nutrients"],
    }


def _well_formed_quiz(question_id: str = "q_0") -> dict[str, Any]:
    return {
        "question_id": question_id,
        "type": "mcq",
        "question": "What organelle is the primary site of cellular respiration?",
        "options": ["Nucleus", "Mitochondrion", "Ribosome", "Golgi apparatus"],
        "correct_index": 1,
        "explanation": "The mitochondrion produces ATP via the electron transport chain.",
        "difficulty": "medium",
    }


def _well_formed_segment(segment_id: str = "sec_0") -> dict[str, Any]:
    return {
        "segment_id": segment_id,
        "title": "Cellular Respiration",
        "summary": "How the mitochondrion converts nutrients into ATP.",
        "slides": [_well_formed_slide()],
        "quiz": [_well_formed_quiz()],
    }


def _package(segments: list[dict[str, Any]]) -> dict[str, Any]:
    return {"segments": segments}


@pytest.mark.unit
def test_slide_quality_well_formed_scores_perfect() -> None:
    package = _package([_well_formed_segment()])
    result = score_slide_quality(package)
    assert result.value == 1.0
    assert result.issues == []


@pytest.mark.unit
def test_slide_quality_empty_bullets_slide_lowers_score_and_reports_issue() -> None:
    segment = _well_formed_segment()
    segment["slides"].append({"slide_id": "slide_1", "title": "Empty", "bullets": []})
    package = _package([segment])
    result = score_slide_quality(package)
    assert result.value == 0.5  # 1 of 2 slides pass
    assert any("zero bullets" in issue for issue in result.issues)


@pytest.mark.unit
def test_slide_quality_over_8_slides_in_a_segment_reports_issue_and_lowers_score() -> None:
    """2026-07-17 review fix (Blind Hunter + Acceptance Auditor): a band
    violation must actually lower the score, not just log an issue string —
    otherwise 9 otherwise-perfect slides scored a perfect 1.0 despite
    violating the very band this function claims to check."""
    segment = _well_formed_segment()
    segment["slides"] = [_well_formed_slide(f"slide_{i}") for i in range(9)]  # over the 1-8 band
    package = _package([segment])
    result = score_slide_quality(package)
    assert any("outside the 1-8 band" in issue for issue in result.issues)
    assert result.value == 0.0  # every slide in the violating segment fails


@pytest.mark.unit
def test_slide_quality_wall_of_text_bullet_flagged() -> None:
    segment = _well_formed_segment()
    segment["slides"] = [
        {"slide_id": "slide_wall", "title": "Dense", "bullets": ["x" * 250]}
    ]
    package = _package([segment])
    result = score_slide_quality(package)
    assert result.value == 0.0
    assert any("wall of text" in issue for issue in result.issues)


@pytest.mark.unit
def test_slide_quality_no_segments_scores_zero() -> None:
    result = score_slide_quality({"segments": []})
    assert result.value == 0.0
    assert result.issues


@pytest.mark.unit
def test_quiz_relevance_well_formed_scores_perfect() -> None:
    package = _package([_well_formed_segment()])
    result = score_quiz_relevance(package)
    assert result.value == 1.0
    assert result.issues == []


@pytest.mark.unit
def test_quiz_relevance_three_options_lowers_score_and_reports_issue() -> None:
    segment = _well_formed_segment()
    segment["quiz"][0]["options"] = ["A", "B", "C"]
    package = _package([segment])
    result = score_quiz_relevance(package)
    assert result.value == 0.0
    assert any("expected 4" in issue for issue in result.issues)


@pytest.mark.unit
def test_quiz_relevance_out_of_range_correct_index_reports_issue() -> None:
    segment = _well_formed_segment()
    segment["quiz"][0]["correct_index"] = 99
    package = _package([segment])
    result = score_quiz_relevance(package)
    assert any("out of range" in issue for issue in result.issues)


@pytest.mark.unit
def test_quiz_relevance_no_keyword_overlap_reports_issue() -> None:
    segment = _well_formed_segment()
    segment["quiz"][0]["question"] = "Unrelated question about astrophysics and black holes"
    package = _package([segment])
    result = score_quiz_relevance(package)
    assert result.value == 0.0
    assert any("no keyword overlap" in issue for issue in result.issues)


@pytest.mark.unit
def test_quiz_relevance_no_segments_scores_zero() -> None:
    result = score_quiz_relevance({"segments": []})
    assert result.value == 0.0
    assert result.issues


@pytest.mark.unit
def test_slide_quality_malformed_segments_key_does_not_raise() -> None:
    result = score_slide_quality({"segments": "not-a-list"})
    assert result.value == 0.0


@pytest.mark.unit
def test_quiz_relevance_malformed_segments_key_does_not_raise() -> None:
    result = score_quiz_relevance({"segments": "not-a-list"})
    assert result.value == 0.0
