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


@pytest.mark.unit
def test_coalesce_first_section_below_floor_folds_forward() -> None:
    """Story 2-16 (RC-1) edge: a sub-floor FIRST section cannot merge backwards,
    so it is folded forward into the next kept section — no text lost, correct
    page span."""
    from app.modules.content.pipeline.nodes.structure_detection import coalesce_sections

    sections = [
        {
            "id": "s0",
            "title": "H0",
            "level": "chapter",
            "body": "tiny",
            "page_start": 1,
            "page_end": 1,
        },
        {
            "id": "s1",
            "title": "H1",
            "level": "section",
            "body": "x" * 300,
            "page_start": 2,
            "page_end": 4,
        },
        {
            "id": "s2",
            "title": "H2",
            "level": "section",
            "body": "y" * 300,
            "page_start": 5,
            "page_end": 6,
        },
    ]
    out = coalesce_sections(sections, min_chars=200, max_sections=15)

    assert len(out) == 2, "sub-floor first section folds forward, leaving 2"
    assert "tiny" in out[0]["body"], "the sub-floor first body must survive"
    assert "x" * 300 in out[0]["body"], "it folds into the next section's body"
    assert out[0]["page_start"] == 1 and out[0]["page_end"] == 4, "merged page span"


@pytest.mark.unit
def test_coalesce_folds_absorbed_titles_into_body() -> None:
    """`_merge_two` folds an absorbed section's TITLE into the survivor's body so
    heading text is not lost — assert the folded titles survive."""
    from app.modules.content.pipeline.nodes.structure_detection import coalesce_sections

    sections = [
        {
            "id": f"s{i}",
            "title": f"TITLE_SENTINEL_{i}",
            "level": "topic",
            "body": "b",
            "page_start": 1,
            "page_end": 1,
        }
        for i in range(6)
    ]
    out = coalesce_sections(sections, min_chars=10_000, max_sections=15)  # all -> 1

    assert len(out) == 1
    combined = out[0]["title"] + "\n" + out[0]["body"]
    for i in range(6):
        assert f"TITLE_SENTINEL_{i}" in combined, f"title {i} was dropped on merge"


@pytest.mark.unit
def test_coalesce_cap_buckets_are_contiguous() -> None:
    """The cap pass buckets sections contiguously (order-preserving), not by an
    arbitrary pairing — adjacent inputs land in the same output bucket."""
    from app.modules.content.pipeline.nodes.structure_detection import coalesce_sections

    bodies = ["z" * 260 + f" m{i}" for i in range(6)]  # all above floor
    out = coalesce_sections(_sections(bodies), min_chars=200, max_sections=3)

    assert len(out) == 3
    # 6 into 3 even buckets -> [m0,m1] [m2,m3] [m4,m5]
    assert "m0" in out[0]["body"] and "m1" in out[0]["body"]
    assert "m2" in out[1]["body"] and "m3" in out[1]["body"]
    assert "m4" in out[2]["body"] and "m5" in out[2]["body"]


@pytest.mark.unit
def test_coalesce_max_sections_zero_disables_cap() -> None:
    """max_sections < 1 disables the cap pass (no-op), returning all sections."""
    from app.modules.content.pipeline.nodes.structure_detection import coalesce_sections

    bodies = ["x" * 300 for _ in range(5)]  # all above floor, so floor pass is a no-op too
    out = coalesce_sections(_sections(bodies), min_chars=200, max_sections=0)
    assert len(out) == 5


@pytest.mark.unit
def test_coalesce_single_subfloor_section_is_kept() -> None:
    """A lone sub-floor section has no neighbour to merge into and is kept."""
    from app.modules.content.pipeline.nodes.structure_detection import coalesce_sections

    out = coalesce_sections(_sections(["short"]), min_chars=200, max_sections=15)
    assert len(out) == 1
    assert "short" in out[0]["body"]


@pytest.mark.unit
def test_config_defaults_and_planner_batch_invariant() -> None:
    """AC-3: defaults are 200/15/15; the coalesce cap must never exceed the
    planner's single-call batch size (else batching would be forced by default).
    Also verify the batch-size Field carries the gt=0 guard (Blind Hunter)."""
    from app.config import Settings

    fields = Settings.model_fields
    assert fields["structure_min_section_chars"].default == 200
    assert fields["structure_max_sections"].default == 15
    assert fields["lesson_planner_batch_size"].default == 15
    assert (
        fields["structure_max_sections"].default <= fields["lesson_planner_batch_size"].default
    ), "coalesced section count must fit a single planner call in the default config"
    # gt=0 guard present on lesson_planner_batch_size (rejects 0 / negative)
    assert any(getattr(m, "gt", None) == 0 for m in fields["lesson_planner_batch_size"].metadata)
    assert any(getattr(m, "ge", None) == 1 for m in fields["structure_max_sections"].metadata)
