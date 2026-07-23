"""
Unit tests for Story 2-18: `_derive_section_id` slugifies the section title so a
derived `segment_id` is always a safe single-TOKEN identifier — no whitespace
(which corrupts the single-line planner/slide prompts) and no character outside
`_SAFE_SEGMENT_ID_RE` = [A-Za-z0-9_-] (which the tts/image storage-path guards
reject, silently degrading real multi-word-titled lessons to fallback).

Covers docs/stories/2-18-sanitize-derived-segment-id.md AC-1..AC-5, AC-7.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.content.pipeline.graph import (
    _SAFE_SEGMENT_ID_RE,
    _SECTION_ID_TITLE_MAX,
    _derive_section_id,
)


@pytest.mark.unit
def test_embedded_newline_produces_safe_token() -> None:
    """AC-1: the exact production repro — a title with an embedded newline yields
    a safe single-token id (no newline, no space)."""
    sid = _derive_section_id({"title": "5.\nJobs"}, 4)
    assert sid == "section_4_5-Jobs"
    assert not any(c in sid for c in "\n\r\t ")


@pytest.mark.unit
@pytest.mark.parametrize(
    "title",
    [
        "5.\nJobs",
        "The Water Cycle",
        "Cell Biology & Genetics",
        "1. Step: do X",
        "2.3\tScroll counters",
        "a\r\nb",
        "Introduction to Memory",
        "café ☕ notes",  # non-ASCII letters + emoji
        "line sep nbsp",  # unicode line-separator + NBSP
    ],
)
def test_derived_id_always_matches_storage_path_validator(title: str) -> None:
    """AC-7 (the HIGH cross-check the audit surfaced): every derived id must
    satisfy _SAFE_SEGMENT_ID_RE, because tts_node/image_generator_node build
    storage paths from it and reject anything outside [A-Za-z0-9_-]. Without this
    assertion, a real multi-word title silently disabled audio + images."""
    sid = _derive_section_id({"title": title}, 0)
    assert _SAFE_SEGMENT_ID_RE.match(sid), f"{sid!r} would be rejected by the storage-path guard"


@pytest.mark.unit
def test_non_alphanumeric_runs_collapse_to_single_dash() -> None:
    sid = _derive_section_id({"title": "A\x00B\x07C  D..E"}, 2)
    assert sid == "section_2_A-B-C-D-E"


@pytest.mark.unit
def test_long_title_capped_at_max() -> None:
    sid = _derive_section_id({"title": "x" * 500}, 3)
    body = sid[len("section_3_") :]
    assert len(body) == _SECTION_ID_TITLE_MAX


@pytest.mark.unit
def test_cap_boundary_exact_and_over() -> None:
    """AC-1 boundary: a title of exactly MAX passes through; MAX+1 truncates to MAX."""
    at = _derive_section_id({"title": "a" * _SECTION_ID_TITLE_MAX}, 0)
    over = _derive_section_id({"title": "a" * (_SECTION_ID_TITLE_MAX + 1)}, 0)
    assert at[len("section_0_") :] == "a" * _SECTION_ID_TITLE_MAX
    assert over[len("section_0_") :] == "a" * _SECTION_ID_TITLE_MAX


@pytest.mark.unit
@pytest.mark.parametrize(
    "title",
    ["", "   ", "\n\n", "\t", None, "\x00\x00", "\x07\x1b", "...", "   -  - "],
)
def test_blank_or_unusable_title_falls_back_to_section(title: Any) -> None:
    """AC-1: blank / whitespace-only / all-control / all-punctuation -> 'section'."""
    sid = _derive_section_id({"title": title}, 7)
    assert sid == "section_7_section"
    assert _SAFE_SEGMENT_ID_RE.match(sid)


@pytest.mark.unit
def test_clean_single_word_title_unchanged() -> None:
    """AC-4: a well-formed single-word title is unchanged."""
    assert _derive_section_id({"title": "Introduction"}, 0) == "section_0_Introduction"


@pytest.mark.unit
def test_uniqueness_preserved_when_titles_collide_after_slug() -> None:
    """AC-2: titles that slug to the same string still get distinct ids via index."""
    a = _derive_section_id({"title": "a\nb"}, 0)  # -> section_0_a-b
    b = _derive_section_id({"title": "a b"}, 1)  # -> section_1_a-b
    c = _derive_section_id({"title": "a.b"}, 2)  # -> section_2_a-b
    assert a == "section_0_a-b" and b == "section_1_a-b" and c == "section_2_a-b"
    assert len({a, b, c}) == 3


@pytest.mark.unit
def test_planner_prompt_line_count_equals_segment_count() -> None:
    """AC-3: building the planner's summaries_text format from ids derived from
    messy titles yields exactly one line per segment, and every id is echo-safe."""
    sections = [
        {"title": "5.\nJobs"},
        {"title": "1. Click\r\nEnd Process"},
        {"title": "The Water Cycle"},
        {"title": "2.3\tScroll counters"},
    ]
    summaries = [
        {"segment_id": _derive_section_id(s, i), "summary": f"summary {i}"}
        for i, s in enumerate(sections)
    ]
    summaries_text = "\n".join(f"- segment_id={s['segment_id']}: {s['summary']}" for s in summaries)
    assert len(summaries_text.split("\n")) == len(summaries)
    for s in summaries:
        assert _SAFE_SEGMENT_ID_RE.match(s["segment_id"])


@pytest.mark.unit
def test_slide_generator_prompt_line_count_equals_segment_count() -> None:
    """The slide_generator sink (graph.py:1537) has the same single-line-per-
    segment shape; a safe (slugified) segment_id keeps it one line per segment.
    (The title/summary halves of that line are a separate, tracked concern.)"""
    segs = [
        {"segment_id": _derive_section_id({"title": t}, i), "title": f"T{i}", "summary": f"s{i}"}
        for i, t in enumerate(["5.\nJobs", "The Water Cycle", "1. Step: do X"])
    ]
    text = "\n".join(f"- segment_id={s['segment_id']}: {s['title']} — {s['summary']}" for s in segs)
    assert len(text.split("\n")) == len(segs)
    for s in segs:
        assert _SAFE_SEGMENT_ID_RE.match(s["segment_id"])
