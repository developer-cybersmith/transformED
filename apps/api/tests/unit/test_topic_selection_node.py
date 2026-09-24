"""Story 233 (piece 1 of 4) — topic-selection step.

Collapses a chapter's `structure_node`-produced sections into exactly 1 topic
(15-min lessons, tier T3) or 2 topics (30/45-min lessons, tiers T1/T2), inserted
`embed -> topic_selection -> <Phase 1 fan-out>`. See
docs/stories/233-topic-selection-step.md for the full ACs and Scale & Load
section.

RED before implementation, GREEN after. `merge_section_range` itself (the
text-preserving merge primitive this node is built on) is covered in
test_coalesce_sections.py, not duplicated here.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

FAKE_LESSON_ID = "44444444-4444-4444-4444-444444444444"


def _sections(bodies: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "id": f"s{i}",
            "title": f"Section {i}",
            "level": "section",
            "body": body,
            "page_start": i + 1,
            "page_end": i + 1,
        }
        for i, body in enumerate(bodies)
    ]


def _mock_supabase(node_outputs: dict[str, Any] | None = None) -> MagicMock:
    jobs_mock = MagicMock()
    (
        jobs_mock.select.return_value.eq.return_value.single.return_value.execute.return_value.data
    ) = {"node_outputs": node_outputs or {}}
    jobs_mock.update.return_value.eq.return_value.execute.return_value = MagicMock()

    sb = MagicMock()
    sb.table.return_value = jobs_mock
    return sb


def _base_state(sections: list[dict[str, Any]], tier: str = "T2") -> dict[str, Any]:
    return {"lesson_id": FAKE_LESSON_ID, "sections": sections, "tier": tier}


def _split_response(split_index: int) -> Any:
    from app.modules.content.pipeline.graph import _StructureTopicSplitLLM

    return _StructureTopicSplitLLM(split_index=split_index)


@pytest.mark.unit
def test_tier_topic_count_mapping() -> None:
    """AC 1: T1/T2 -> 2 topics (30/45-min), T3 -> 1 topic (15-min)."""
    from app.schemas.lesson import TIER_TOPIC_COUNT

    assert TIER_TOPIC_COUNT == {"T1": 2, "T2": 2, "T3": 1}


@pytest.mark.unit
def test_section_body_max_chars_re_derived_for_topic_merge() -> None:
    """AC 9 / Scale & Load Q5: section_body_max_chars was sized (6000) for one
    of up to 15 small sections. Once sections collapse to 1-2 topics, a topic
    can be far larger than that cap was ever tuned for — raised to the
    40,000-45,000 range per the story's Scale & Load arithmetic
    (old_value * structure_max_sections / target_topic_count), not left
    silently unrevisited."""
    from app.config import Settings

    fields = Settings.model_fields
    default = fields["section_body_max_chars"].default
    assert 40_000 <= default <= 45_000, (
        f"section_body_max_chars={default} was not re-derived for the "
        "topic-selection unit-of-work change (docs/stories/233-topic-selection-step.md)"
    )
    assert any(getattr(m, "gt", None) == 0 for m in fields["section_body_max_chars"].metadata)


# ═══════════════════════════════════════════════════════════════════════════
# topic_selection_node — inserted embed -> topic_selection -> <Phase 1 fan-out>
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
@pytest.mark.asyncio
async def test_noop_when_sections_at_or_below_target_t3() -> None:
    """AC 4: T3 (target=1) with exactly 1 section passes through unchanged."""
    from app.modules.content.pipeline.graph import topic_selection_node

    sections = _sections(["only body"])
    with patch("app.core.db.get_supabase", return_value=_mock_supabase()):
        result = await topic_selection_node(_base_state(sections, tier="T3"))

    assert result["sections"] == sections


@pytest.mark.unit
@pytest.mark.asyncio
async def test_noop_when_sections_at_or_below_target_t2() -> None:
    """AC 4: T2 (target=2) with exactly 2 sections passes through unchanged —
    never fabricates a 2nd topic split from material that's already at the
    target count."""
    from app.modules.content.pipeline.graph import topic_selection_node

    sections = _sections(["body a", "body b"])
    with patch("app.core.db.get_supabase", return_value=_mock_supabase()):
        result = await topic_selection_node(_base_state(sections, tier="T2"))

    assert result["sections"] == sections


@pytest.mark.unit
@pytest.mark.asyncio
async def test_one_topic_case_merges_all_sections_with_zero_llm_calls() -> None:
    """AC 5: T3 collapses N>1 sections into exactly 1 topic, no LLM call."""
    from app.modules.content.pipeline.graph import topic_selection_node

    sections = _sections([f"UNIQUE_TOKEN_{i} " * 20 for i in range(5)])
    provider = AsyncMock()
    with (
        patch("app.core.db.get_supabase", return_value=_mock_supabase()),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
    ):
        result = await topic_selection_node(_base_state(sections, tier="T3"))

    assert len(result["sections"]) == 1
    provider.complete_structured.assert_not_called()
    merged_body = result["sections"][0]["body"]
    for i in range(5):
        assert f"UNIQUE_TOKEN_{i}" in merged_body, f"section {i} text was dropped"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_two_topic_case_uses_llm_split_index() -> None:
    """AC 6: T2/T1 collapses N sections into exactly 2 topics using the LLM's
    split_index, respecting original section order on each side."""
    from app.modules.content.pipeline.graph import topic_selection_node

    sections = _sections([f"TOKEN_{i}" for i in range(6)])
    provider = AsyncMock()
    provider.complete_structured.return_value = _split_response(4)
    with (
        patch("app.core.db.get_supabase", return_value=_mock_supabase()),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
    ):
        result = await topic_selection_node(_base_state(sections, tier="T2"))

    assert len(result["sections"]) == 2
    topic_i, topic_ii = result["sections"]
    for i in range(4):
        assert f"TOKEN_{i}" in topic_i["body"]
    for i in range(4, 6):
        assert f"TOKEN_{i}" in topic_ii["body"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_two_topic_case_out_of_range_index_falls_back_to_midpoint() -> None:
    """AC 6 degrade-not-fabricate: an out-of-range split_index never raises,
    never produces an empty topic — falls back to the deterministic split."""
    from app.modules.content.pipeline.graph import topic_selection_node

    sections = _sections([f"TOKEN_{i}" for i in range(6)])
    provider = AsyncMock()
    provider.complete_structured.return_value = _split_response(99)
    with (
        patch("app.core.db.get_supabase", return_value=_mock_supabase()),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
    ):
        result = await topic_selection_node(_base_state(sections, tier="T2"))

    assert len(result["sections"]) == 2
    for topic in result["sections"]:
        assert topic["body"], "no topic may end up empty from a bad split_index"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_two_topic_case_zero_index_falls_back_to_midpoint() -> None:
    """split_index=0 would make Topic I empty — must be rejected as out of range."""
    from app.modules.content.pipeline.graph import topic_selection_node

    sections = _sections([f"TOKEN_{i}" for i in range(6)])
    provider = AsyncMock()
    provider.complete_structured.return_value = _split_response(0)
    with (
        patch("app.core.db.get_supabase", return_value=_mock_supabase()),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
    ):
        result = await topic_selection_node(_base_state(sections, tier="T2"))

    assert len(result["sections"]) == 2
    assert result["sections"][0]["body"], "Topic I must not be empty"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_two_topic_case_llm_exception_falls_back_to_midpoint() -> None:
    """AC 6 degrade-not-fabricate: an LLM call failure never raises."""
    from app.modules.content.pipeline.graph import topic_selection_node

    sections = _sections([f"TOKEN_{i}" for i in range(6)])
    provider = AsyncMock()
    provider.complete_structured.side_effect = RuntimeError("boom")
    with (
        patch("app.core.db.get_supabase", return_value=_mock_supabase()),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
    ):
        result = await topic_selection_node(_base_state(sections, tier="T2"))

    assert len(result["sections"]) == 2
    for topic in result["sections"]:
        assert topic["body"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_result_sections_keep_the_same_dict_shape() -> None:
    """AC 7: downstream nodes (Phase 1 fan-out, _derive_section_id) require
    zero changes — the merged topic dicts must keep the normal section shape."""
    from app.modules.content.pipeline.graph import topic_selection_node

    sections = _sections([f"body {i}" for i in range(4)])
    provider = AsyncMock()
    provider.complete_structured.return_value = _split_response(2)
    with (
        patch("app.core.db.get_supabase", return_value=_mock_supabase()),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
    ):
        result = await topic_selection_node(_base_state(sections, tier="T1"))

    for topic in result["sections"]:
        assert {"id", "title", "level", "body", "page_start", "page_end"} <= topic.keys()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_checkpoint_is_written_including_noop_case() -> None:
    """AC 8: an admin-visible record is always written, including the no-op
    (AC-4) case."""
    from app.modules.content.pipeline.graph import topic_selection_node

    sections = _sections(["only body"])
    sb = _mock_supabase()
    with patch("app.core.db.get_supabase", return_value=sb):
        await topic_selection_node(_base_state(sections, tier="T3"))

    # _update_job_progress makes its own separate .update() call afterwards
    # (no node_outputs key) — find the checkpoint-carrying call specifically,
    # not just the most recent one.
    checkpoint_calls = [
        c.args[0]
        for c in sb.table.return_value.update.call_args_list
        if "node_outputs" in c.args[0]
    ]
    assert len(checkpoint_calls) == 1
    assert checkpoint_calls[0]["last_node"] == "topic_selection"
    assert "topic_selection" in checkpoint_calls[0]["node_outputs"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_idempotent_cache_hit_skips_llm_call() -> None:
    """AC 10: a second invocation with the checkpoint already present returns
    the cached result — no LLM call, matching structure_node/chunk_node's
    existing Phase-A-style plain-checkpoint pattern."""
    from app.modules.content.pipeline.graph import topic_selection_node

    cached_sections = _sections(["cached topic body"])
    node_outputs = {"topic_selection": {"sections": cached_sections}}
    provider = AsyncMock()
    with (
        patch("app.core.db.get_supabase", return_value=_mock_supabase(node_outputs)),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
    ):
        result = await topic_selection_node(_base_state(_sections(["a", "b", "c"]), tier="T2"))

    assert result["sections"] == cached_sections
    provider.complete_structured.assert_not_called()
