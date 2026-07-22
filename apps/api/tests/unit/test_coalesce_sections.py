"""
Unit tests for Story 2-16 (RC-1): coalesce_sections — bound an over-segmented
section list without losing any source text.

Covers docs/stories/2-16-fix-pipeline-oversegmentation.md AC-1 / AC-5:
- a step-by-step how-to PDF over-segmented into ~44 sections collapses to the cap,
- no source body text is ever dropped (text-preserving merges),
- a list already within bounds is returned unchanged.
"""

from __future__ import annotations

from typing import Any

import pytest


def _sections(bodies: list[str], *, level: str = "chapter") -> list[dict[str, Any]]:
    return [
        {
            "id": f"s{i}",
            "title": f"{i}. Step {i}",
            "level": level,
            "body": body,
            "page_start": i + 1,
            "page_end": i + 1,
        }
        for i, body in enumerate(bodies)
    ]


@pytest.mark.unit
def test_coalesce_collapses_oversegmented_howto_via_cap() -> None:
    """44 above-floor 'step' sections (the how-to failure shape) are merged down
    to structure_max_sections, and every original body survives."""
    from app.modules.content.pipeline.nodes.structure_detection import coalesce_sections

    bodies = ["x" * 260 + f" step-{i}-marker" for i in range(44)]
    out = coalesce_sections(_sections(bodies), min_chars=200, max_sections=15)

    assert len(out) == 15, "should be capped at max_sections"
    joined = " ".join(s["body"] for s in out)
    for i in range(44):
        assert f"step-{i}-marker" in joined, f"body {i} was dropped — text loss!"
    assert [s["id"] for s in out] == [f"s{i}" for i in range(len(out))], "ids re-sequenced"


@pytest.mark.unit
def test_coalesce_merges_subfloor_sections() -> None:
    """Sub-floor (short) sections — the numbered how-to steps mis-detected as
    headings — fold into a neighbour rather than each standing alone."""
    from app.modules.content.pipeline.nodes.structure_detection import coalesce_sections

    bodies = [f"Press the button labelled {i} now." for i in range(44)]  # ~34 chars each
    out = coalesce_sections(_sections(bodies), min_chars=200, max_sections=15)

    assert len(out) < 44, "sub-floor steps must be coalesced"
    joined = " ".join(s["body"] for s in out)
    for i in range(44):
        assert f"labelled {i} now" in joined, f"step {i} body was dropped — text loss!"


@pytest.mark.unit
def test_coalesce_preserves_all_body_text_and_titles() -> None:
    """Every original body token survives even when all sections merge into one."""
    from app.modules.content.pipeline.nodes.structure_detection import coalesce_sections

    bodies = [f"UNIQUE_BODY_TOKEN_{i}" for i in range(10)]
    out = coalesce_sections(_sections(bodies, level="topic"), min_chars=10_000, max_sections=15)

    joined = "\n".join(s["body"] for s in out)
    for i in range(10):
        assert f"UNIQUE_BODY_TOKEN_{i}" in joined
    assert len(out) >= 1


@pytest.mark.unit
def test_coalesce_below_cap_and_above_floor_is_noop() -> None:
    """A small list of substantial sections is returned unchanged (ids/bodies)."""
    from app.modules.content.pipeline.nodes.structure_detection import coalesce_sections

    sections = _sections(["x" * 300, "y" * 300])
    out = coalesce_sections(sections, min_chars=200, max_sections=15)

    assert len(out) == 2
    assert out[0]["body"] == "x" * 300
    assert out[1]["body"] == "y" * 300
    assert [s["id"] for s in out] == ["s0", "s1"]


@pytest.mark.unit
def test_coalesce_empty_list_returns_empty() -> None:
    from app.modules.content.pipeline.nodes.structure_detection import coalesce_sections

    assert coalesce_sections([], min_chars=200, max_sections=15) == []


@pytest.mark.unit
def test_coalesce_merged_section_spans_both_page_ranges() -> None:
    """A merged section's page span covers all its members (no page-range loss)."""
    from app.modules.content.pipeline.nodes.structure_detection import coalesce_sections

    sections = [
        {
            "id": "s0",
            "title": "A",
            "level": "section",
            "body": "short",
            "page_start": 3,
            "page_end": 4,
        },
        {
            "id": "s1",
            "title": "B",
            "level": "chapter",
            "body": "short",
            "page_start": 5,
            "page_end": 9,
        },
    ]
    out = coalesce_sections(sections, min_chars=1000, max_sections=15)

    assert len(out) == 1
    assert out[0]["page_start"] == 3
    assert out[0]["page_end"] == 9
    assert out[0]["level"] == "chapter", "merged section adopts the coarsest level"
