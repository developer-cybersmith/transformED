"""
Unit tests for Story 2-18: `_derive_section_id` sanitizes the section title so a
derived `segment_id` is always a safe single-line token, even when the rule-based
heading detector mis-picks a numbered how-to step (e.g. "5.\nJobs") as a title.

Covers docs/stories/2-18-sanitize-derived-segment-id.md AC-1..AC-5.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.content.pipeline.graph import _SECTION_ID_TITLE_MAX, _derive_section_id


@pytest.mark.unit
def test_embedded_newline_produces_single_line_id() -> None:
    """AC-1: the exact production repro — a title with an embedded newline yields
    an id with NO newline."""
    sid = _derive_section_id({"title": "5.\nJobs"}, 4)
    assert "\n" not in sid
    assert "\r" not in sid
    assert "\t" not in sid
    assert sid == "section_4_5. Jobs"


@pytest.mark.unit
@pytest.mark.parametrize(
    "title",
    ["a\nb", "a\r\nb", "a\tb", "a   b", "a\n\n\nb", "  a  b  "],
)
def test_all_whitespace_runs_collapse_to_single_space(title: str) -> None:
    """AC-1: every kind/length of whitespace run collapses to one space."""
    sid = _derive_section_id({"title": title}, 0)
    assert not any(c in sid for c in "\n\r\t")
    # the title portion after the "section_0_" prefix is single-spaced
    body = sid[len("section_0_") :]
    assert "  " not in body


@pytest.mark.unit
def test_non_printable_control_chars_stripped() -> None:
    """AC-1: non-printable/control characters are dropped, not embedded."""
    sid = _derive_section_id({"title": "A\x00B\x07C"}, 2)
    assert sid == "section_2_ABC"


@pytest.mark.unit
def test_long_title_is_capped() -> None:
    """AC-1: the title portion is bounded to _SECTION_ID_TITLE_MAX chars."""
    sid = _derive_section_id({"title": "x" * 500}, 3)
    body = sid[len("section_3_") :]
    assert len(body) <= _SECTION_ID_TITLE_MAX


@pytest.mark.unit
@pytest.mark.parametrize("title", ["", "   ", "\n\n", "\t", None, "\x00\x00"])
def test_blank_or_unusable_title_falls_back_to_section(title: Any) -> None:
    """AC-1: blank / whitespace-only / all-control / missing title -> 'section'."""
    sid = _derive_section_id({"title": title}, 7)
    assert sid == "section_7_section"


@pytest.mark.unit
def test_clean_title_unchanged_apart_from_bound() -> None:
    """AC-4: a well-formed title is unchanged (no regression)."""
    assert _derive_section_id({"title": "Introduction"}, 0) == "section_0_Introduction"


@pytest.mark.unit
def test_uniqueness_preserved_when_titles_collide_after_sanitizing() -> None:
    """AC-2: two sections whose titles collapse to the same string still get
    distinct ids because the index prefix guarantees uniqueness."""
    a = _derive_section_id({"title": "a\nb"}, 0)  # -> section_0_a b
    b = _derive_section_id({"title": "a b"}, 1)  # -> section_1_a b
    c = _derive_section_id({"title": "a\tb"}, 2)  # -> section_2_a b
    assert a != b != c and a != c
    assert len({a, b, c}) == 3


@pytest.mark.unit
def test_planner_prompt_line_count_equals_segment_count() -> None:
    """AC-3: building the planner's `summaries_text` from ids derived from messy
    titles yields exactly one line per segment — the corruption that tripped the
    `unknown segment_id` guard cannot recur."""
    sections = [
        {"title": "5.\nJobs"},
        {"title": "1. Click\r\nEnd Process"},
        {"title": "Normal Heading"},
        {"title": "2.3\tScroll counters"},
    ]
    summaries = [
        {"segment_id": _derive_section_id(s, i), "summary": f"summary {i}"}
        for i, s in enumerate(sections)
    ]
    # exact format from lesson_planner_node's summaries_text construction
    summaries_text = "\n".join(f"- segment_id={s['segment_id']}: {s['summary']}" for s in summaries)
    assert len(summaries_text.split("\n")) == len(summaries), (
        "each segment must occupy exactly one prompt line"
    )
    # and every id is echo-safe: no line-breaking characters
    for s in summaries:
        assert not any(c in s["segment_id"] for c in "\n\r\t")
