"""
Unit tests for Story 2-19: `_estimate_slide_timestamps` — package_builder
synthesizes a contiguous {slide_id, start_ms, end_ms} track so the player can
sync slides and fire the segment-end quiz (tts_node ships timestamps=[]).

Covers docs/stories/2-19-narration-timestamps.md AC-1..AC-3, AC-6.
"""

from __future__ import annotations

import pytest

from app.modules.content.pipeline.graph import _estimate_slide_timestamps

WPM = 150
DEFAULT_MS = 5000


def _slides(n: int) -> list[dict[str, str]]:
    return [{"slide_id": f"slide_{i}"} for i in range(n)]


def _assert_valid_track(ts: list[dict[str, object]]) -> None:
    """AC-2 invariants: contiguous, monotonic, first start 0, non-degenerate,
    and each entry is the exact {slide_id, start_ms, end_ms} contract shape."""
    assert ts, "track must be non-empty"
    assert ts[0]["start_ms"] == 0
    for a, b in zip(ts, ts[1:], strict=False):
        assert a["end_ms"] == b["start_ms"], "contiguous"
    for t in ts:
        assert set(t.keys()) == {"slide_id", "start_ms", "end_ms"}
        assert isinstance(t["start_ms"], int) and isinstance(t["end_ms"], int)
        assert t["start_ms"] >= 0
        assert t["start_ms"] < t["end_ms"], "non-degenerate window"


@pytest.mark.unit
def test_one_timestamp_per_slide_in_order() -> None:
    ts = _estimate_slide_timestamps(
        _slides(3), "word " * 30, words_per_minute=WPM, default_ms_per_slide=DEFAULT_MS
    )
    assert [t["slide_id"] for t in ts] == ["slide_0", "slide_1", "slide_2"]
    _assert_valid_track(ts)


@pytest.mark.unit
def test_duration_estimated_from_word_count() -> None:
    # 60 words / 150 wpm = 0.4 min = 24_000 ms, split across 4 slides
    ts = _estimate_slide_timestamps(
        _slides(4), "word " * 60, words_per_minute=WPM, default_ms_per_slide=DEFAULT_MS
    )
    _assert_valid_track(ts)
    assert ts[-1]["end_ms"] == 24_000
    assert [t["end_ms"] for t in ts] == [6_000, 12_000, 18_000, 24_000]


@pytest.mark.unit
def test_empty_script_falls_back_to_default_per_slide() -> None:
    ts = _estimate_slide_timestamps(
        _slides(2), "", words_per_minute=WPM, default_ms_per_slide=DEFAULT_MS
    )
    _assert_valid_track(ts)
    assert ts[-1]["end_ms"] == 2 * DEFAULT_MS
    assert ts[0] == {"slide_id": "slide_0", "start_ms": 0, "end_ms": 5_000}


@pytest.mark.unit
def test_single_slide() -> None:
    ts = _estimate_slide_timestamps(
        _slides(1), "word " * 15, words_per_minute=WPM, default_ms_per_slide=DEFAULT_MS
    )
    _assert_valid_track(ts)
    assert len(ts) == 1
    assert ts[0]["start_ms"] == 0


@pytest.mark.unit
def test_no_slides_returns_empty() -> None:
    assert (
        _estimate_slide_timestamps(
            [], "some words", words_per_minute=WPM, default_ms_per_slide=DEFAULT_MS
        )
        == []
    )


@pytest.mark.unit
@pytest.mark.parametrize("word_count", [0, 1, 3, 7, 100, 1000])
@pytest.mark.parametrize("n_slides", [1, 2, 5, 8])
def test_track_invariants_hold_for_any_shape(word_count: int, n_slides: int) -> None:
    """Property: no combination of word count and slide count produces a
    degenerate/non-contiguous track (the pathological-rounding regime)."""
    ts = _estimate_slide_timestamps(
        _slides(n_slides),
        "w " * word_count,
        words_per_minute=WPM,
        default_ms_per_slide=DEFAULT_MS,
    )
    assert len(ts) == n_slides
    _assert_valid_track(ts)


@pytest.mark.unit
@pytest.mark.parametrize("n_slides", [3, 8, 50])
def test_track_valid_at_duration_floor(n_slides: int) -> None:
    """Force total_ms to the >=1ms/slide floor (tiny word count vs huge wpm) so
    the `max(total_ms, n)` clamp actually fires — proves the track stays valid in
    the pathological small-duration regime (the regime the wpm=150 sweep can't
    reach)."""
    ts = _estimate_slide_timestamps(
        _slides(n_slides), "w", words_per_minute=1_000_000_000, default_ms_per_slide=DEFAULT_MS
    )
    assert len(ts) == n_slides
    _assert_valid_track(ts)
    assert ts[-1]["end_ms"] == n_slides, "total_ms clamped to n (>=1ms per slide)"


@pytest.mark.unit
def test_config_defaults_and_gt0_guards() -> None:
    """AC-4: defaults 150/5000 and the gt=0 guards are present on the settings."""
    from app.config import Settings

    fields = Settings.model_fields
    assert fields["narration_words_per_minute"].default == 150
    assert fields["default_ms_per_slide"].default == 5000
    assert any(getattr(m, "gt", None) == 0 for m in fields["narration_words_per_minute"].metadata)
    assert any(getattr(m, "gt", None) == 0 for m in fields["default_ms_per_slide"].metadata)
