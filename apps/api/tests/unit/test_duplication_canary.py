"""Story 2-28 AC-8: pre-spend duplication canaries.

`_warn_if_duplicated` fires at the top of the two nodes that spend real money
on their input — `lesson_planner_node` (GPT-4o) and `tts_node` (TTS vendor) —
so a re-emitted reducer channel is caught BEFORE the spend, not discovered in
the delivered package.
"""

from __future__ import annotations

import logging

import pytest


@pytest.mark.unit
def test_canary_fires_on_duplicated_channel(caplog: pytest.LogCaptureFixture) -> None:
    from app.modules.content.pipeline.graph import _warn_if_duplicated

    # 2 distinct segments, each appearing 3x — the shape real duplication takes.
    entries = [{"segment_id": sid, "summary": "s"} for sid in ("a", "b") for _ in range(3)]

    with caplog.at_level(logging.ERROR):
        _warn_if_duplicated("lesson-1", "lesson_planner", "segment_summaries", entries)

    assert any("3.0x duplication" in r.getMessage() for r in caplog.records), (
        f"expected a duplication ERROR, got: {[r.getMessage() for r in caplog.records]}"
    )


@pytest.mark.unit
def test_canary_silent_on_a_healthy_channel(caplog: pytest.LogCaptureFixture) -> None:
    """A healthy run must log NOTHING — LoggingIntegration(event_level=ERROR)
    turns every ERROR into a Sentry issue, so a noisy canary is worse than none."""
    from app.modules.content.pipeline.graph import _warn_if_duplicated

    entries = [{"segment_id": f"s{i}", "summary": "x"} for i in range(8)]

    with caplog.at_level(logging.ERROR):
        _warn_if_duplicated("lesson-1", "tts_node", "narration_scripts", entries)

    assert not caplog.records, f"canary must be silent when healthy: {caplog.records}"


@pytest.mark.unit
def test_canary_tolerates_empty_and_malformed_entries(caplog: pytest.LogCaptureFixture) -> None:
    """Never raise — a canary that crashes the pipeline is a regression, and
    degraded nodes legitimately emit empty channels."""
    from app.modules.content.pipeline.graph import _warn_if_duplicated

    with caplog.at_level(logging.ERROR):
        _warn_if_duplicated("lesson-1", "tts_node", "narration_scripts", [])
        _warn_if_duplicated("lesson-1", "tts_node", "narration_scripts", ["not-a-dict"])  # type: ignore[list-item]
        _warn_if_duplicated("lesson-1", "tts_node", "narration_scripts", [{}, {}])

    assert not caplog.records, "malformed/empty input must not trip the canary"


@pytest.mark.unit
def test_canary_never_raises_on_unhashable_segment_id(caplog: pytest.LogCaptureFixture) -> None:
    """Regression: an unhashable segment_id must not crash the pipeline.

    The canary is the FIRST statement of lesson_planner_node and tts_node, so
    an exception here fails the lesson before any work is attempted. A
    checkpoint row whose JSONB segment_id deserialised to a list/dict would
    raise `TypeError: unhashable type: 'list'` on the internal set().
    Found by the Story 2-28 review; the docstring promised "never raises"
    while the code could.
    """
    from app.modules.content.pipeline.graph import _warn_if_duplicated

    entries = [{"segment_id": ["a"]}, {"segment_id": ["a"]}]

    with caplog.at_level(logging.ERROR):
        _warn_if_duplicated("lesson-1", "tts_node", "narration_scripts", entries)  # must not raise

    # Coerced via str(), so the duplication is still DETECTED, not just survived.
    assert any("duplication" in r.getMessage() for r in caplog.records), (
        "unhashable ids should still be counted, not silently skipped"
    )


@pytest.mark.unit
def test_residual_canary_fires_on_exact_duplicate_pairs(caplog: pytest.LogCaptureFixture) -> None:
    """AC-8 third canary: the ONLY runtime detector for quiz_questions/glossary.

    lesson_planner's canary runs before the four doubling nodes and so can only
    see Phase-1-origin duplication; tts_node's covers narration_scripts alone.
    AC-7's e2e assertions are CI-time on a fixture — they cannot observe a real
    student's lesson. This is what covers the channels Dev 2 actually saw
    duplicated.
    """
    from app.modules.content.pipeline.graph import _warn_if_exact_duplicates

    entries = [
        {"segment_id": "s1", "data": {"question_id": "q1"}},
        {"segment_id": "s1", "data": {"question_id": "q1"}},  # exact duplicate
        {"segment_id": "s1", "data": {"question_id": "q2"}},
    ]
    with caplog.at_level(logging.ERROR):
        _warn_if_exact_duplicates("lesson-1", "quiz_questions", entries, "question_id")

    assert any("3 entries for only 2 distinct" in r.getMessage() for r in caplog.records), (
        f"expected an exact-duplicate ERROR, got: {[r.getMessage() for r in caplog.records]}"
    )


@pytest.mark.unit
def test_residual_canary_silent_on_legitimate_multi_per_segment(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No count bands: several DISTINCT questions per segment is normal, and
    jargon has no per-segment cap at all. A band would fire on healthy lessons
    and every ERROR becomes a Sentry issue."""
    from app.modules.content.pipeline.graph import _warn_if_exact_duplicates

    many = [{"segment_id": "s1", "data": {"question_id": f"q{n}"}} for n in range(12)]
    terms = [{"segment_id": "s1", "term": f"t{n}"} for n in range(20)]

    with caplog.at_level(logging.ERROR):
        _warn_if_exact_duplicates("lesson-1", "quiz_questions", many, "question_id")
        _warn_if_exact_duplicates("lesson-1", "glossary", terms, "term")

    assert not caplog.records, f"must stay silent on healthy lessons: {caplog.records}"


@pytest.mark.unit
def test_residual_canary_never_raises() -> None:
    """Runs AFTER the whole lesson is paid for — crashing would discard it."""
    from app.modules.content.pipeline.graph import _warn_if_exact_duplicates

    for bad in ([{"segment_id": ["x"], "data": {"question_id": ["y"]}}] * 2, ["nope"], [{}], []):
        _warn_if_exact_duplicates("lesson-1", "quiz_questions", bad, "question_id")  # type: ignore[arg-type]


@pytest.mark.unit
def test_both_paid_nodes_call_the_canary() -> None:
    """Source guard: the canary is only useful where the money is spent."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "modules"
        / "content"
        / "pipeline"
        / "graph.py"
    ).read_text(encoding="utf-8-sig")

    assert '_warn_if_duplicated(lesson_id, "lesson_planner", "segment_summaries"' in src
    assert '_warn_if_duplicated(lesson_id, "tts_node", "narration_scripts"' in src
