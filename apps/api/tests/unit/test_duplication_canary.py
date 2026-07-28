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
