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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cost_ceiling_reached_skips_llm_call_falls_back_to_midpoint() -> None:
    """Review finding (Story 233 round, Blind Hunter): every other paid call
    site in this file gates on check_ceiling() first — the split LLM call
    didn't. A lesson already over budget must fall to the free deterministic
    split rather than pay for a call, matching narration_generator_node's
    established per-dispatch degrade pattern."""
    from app.modules.content.pipeline.graph import topic_selection_node

    sections = _sections([f"TOKEN_{i}" for i in range(6)])
    provider = AsyncMock()
    with (
        patch("app.core.db.get_supabase", return_value=_mock_supabase()),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=True)),
    ):
        result = await topic_selection_node(_base_state(sections, tier="T2"))

    assert len(result["sections"]) == 2
    for topic in result["sections"]:
        assert topic["body"]
    provider.complete_structured.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_check_ceiling_failure_fails_open_and_calls_llm() -> None:
    """A transient check_ceiling() error (e.g. Redis blip) must not abort
    topic selection — fail open, same convention as every other check_ceiling
    call site in this file."""
    from app.modules.content.pipeline.graph import topic_selection_node

    sections = _sections([f"TOKEN_{i}" for i in range(6)])
    provider = AsyncMock()
    provider.complete_structured.return_value = _split_response(3)
    with (
        patch("app.core.db.get_supabase", return_value=_mock_supabase()),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
        patch(
            "app.core.cost_tracker.check_ceiling",
            new=AsyncMock(side_effect=RuntimeError("redis down")),
        ),
    ):
        result = await topic_selection_node(_base_state(sections, tier="T2"))

    assert len(result["sections"]) == 2
    provider.complete_structured.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_two_topic_case_missing_split_index_falls_back_to_midpoint() -> None:
    """AC 6 degrade-not-fabricate: a response whose split_index is missing/
    None (not just out-of-range) must never raise and never produce an empty
    topic. `_StructureTopicSplitLLM` is a real Pydantic model that would
    reject a None int at construction, so this uses a bare object to
    reproduce what an actually malformed/unexpected provider response looks
    like from topic_selection_node's own perspective (it only ever reads
    `response.split_index`, never isinstance-checks the response type)."""
    from types import SimpleNamespace

    from app.modules.content.pipeline.graph import topic_selection_node

    sections = _sections([f"TOKEN_{i}" for i in range(6)])
    provider = AsyncMock()
    provider.complete_structured.return_value = SimpleNamespace(split_index=None)
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
async def test_two_topic_case_non_int_split_index_falls_back_to_midpoint() -> None:
    """Same as above for a non-integer (e.g. string) split_index."""
    from types import SimpleNamespace

    from app.modules.content.pipeline.graph import topic_selection_node

    sections = _sections([f"TOKEN_{i}" for i in range(6)])
    provider = AsyncMock()
    provider.complete_structured.return_value = SimpleNamespace(split_index="three")
    with (
        patch("app.core.db.get_supabase", return_value=_mock_supabase()),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
    ):
        result = await topic_selection_node(_base_state(sections, tier="T2"))

    assert len(result["sections"]) == 2
    for topic in result["sections"]:
        assert topic["body"]


@pytest.mark.unit
def test_midpoint_split_zero_total_body_length_does_not_divide_by_zero() -> None:
    """The `_topic_selection_midpoint_split` fallback's own zero-total guard
    (`if total <= 0`) has no test reaching it — every other fallback test uses
    non-empty TOKEN_i bodies. All-empty bodies must still return a valid,
    in-range split index, never raise ZeroDivisionError."""
    from app.modules.content.pipeline.graph import _topic_selection_midpoint_split

    sections = _sections(["", "", "", "", "", ""])
    split_index = _topic_selection_midpoint_split(sections)

    assert 1 <= split_index <= len(sections) - 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_two_topic_case_all_empty_bodies_via_llm_exception_path() -> None:
    """Same zero-total-length edge case, exercised end-to-end through
    topic_selection_node's real degrade path (LLM failure -> midpoint
    fallback), not just the pure helper in isolation."""
    from app.modules.content.pipeline.graph import topic_selection_node

    sections = _sections(["", "", "", "", "", ""])
    provider = AsyncMock()
    provider.complete_structured.side_effect = RuntimeError("boom")
    with (
        patch("app.core.db.get_supabase", return_value=_mock_supabase()),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
    ):
        result = await topic_selection_node(_base_state(sections, tier="T2"))

    assert len(result["sections"]) == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_two_topic_llm_prompt_excludes_full_section_bodies() -> None:
    """AC 6: input to the split LLM call is index + title + a short (~200
    char) preview only — never full section bodies, never the whole chapter.
    True only 'by construction' with nothing that previously caught a
    regression — inspect the actual prompt content sent to the provider."""
    from app.modules.content.pipeline.graph import topic_selection_node

    long_marker = "FULL_BODY_TAIL_MARKER_MUST_NOT_APPEAR_IN_PROMPT"
    long_body = ("x" * 500) + long_marker  # tail sits well past any ~200-char preview
    sections = _sections([long_body for _ in range(6)])
    provider = AsyncMock()
    provider.complete_structured.return_value = _split_response(3)
    with (
        patch("app.core.db.get_supabase", return_value=_mock_supabase()),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
    ):
        await topic_selection_node(_base_state(sections, tier="T2"))

    provider.complete_structured.assert_called_once()
    messages = provider.complete_structured.call_args.args[0]
    full_prompt_text = " ".join(m["content"] for m in messages)
    assert long_marker not in full_prompt_text, (
        "the LLM prompt included text past the ~200-char preview window — "
        "AC 6 requires bounded input, never full section bodies"
    )


@pytest.mark.unit
def test_section_body_max_chars_description_states_the_arithmetic() -> None:
    """AC 9: the re-derivation's arithmetic must live IN the field's own
    description, not just the numeric value be in range — a regression that
    kept the value correct but stripped the justification text would
    otherwise go uncaught."""
    from app.config import Settings

    description = Settings.model_fields["section_body_max_chars"].description or ""
    assert "structure_max_sections" in description
    assert "TIER_TOPIC_COUNT" in description
    assert "45,000" in description or "45000" in description


@pytest.mark.unit
@pytest.mark.asyncio
async def test_realistic_oversized_t3_chapter_still_surfaces_truncation_end_to_end() -> None:
    """Review-round finding (independent audit round): D185's residual gap is
    that a T3 chapter above section_body_max_chars gets truncated at every
    downstream LLM call, and no test exercised a realistically oversized
    (>cap) single-merged T3 chapter through topic_selection_node to prove the
    surfacing mechanism (_get_section_body/section_truncations) still fires
    correctly post-collapse — every existing test used tiny synthetic bodies.

    This does not change the cap value (that needs real usage data, per
    config.py's own description) — it proves the ALREADY-TESTED, cap-agnostic
    truncation-surfacing mechanism (test_phase1_economy_nodes.py's
    TestSectionTruncationSurfaced) is genuinely still reachable end-to-end
    through topic_selection_node's merge path, not just at the unit level."""
    from app.config import get_settings
    from app.modules.content.pipeline.graph import _get_section_body, topic_selection_node

    cap = get_settings().section_body_max_chars
    # A realistic textbook chapter (per graph.py's own structure_node comment:
    # "30,000-100,000" chars) split into several sections whose combined body
    # exceeds the cap once topic_selection_node merges them all into one T3 topic.
    per_section = (cap // 4) + 1000
    sections = _sections([f"S{i} " + ("word " * (per_section // 5)) for i in range(6)])
    assert sum(len(s["body"]) for s in sections) > cap, "fixture must exceed the cap once merged"

    provider = AsyncMock()
    with (
        patch("app.core.db.get_supabase", return_value=_mock_supabase()),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
    ):
        result = await topic_selection_node(_base_state(sections, tier="T3"))

    assert len(result["sections"]) == 1
    merged_topic = result["sections"][0]
    assert len(merged_topic["body"]) > cap, "merge_section_range must not itself truncate anything"

    section_body = _get_section_body(
        merged_topic, lesson_id=FAKE_LESSON_ID, section_id="section_0_merged"
    )
    assert section_body.was_truncated is True
    assert len(section_body.body) == cap


@pytest.mark.unit
def test_slide_budget_per_segment_known_interim_gap_d188() -> None:
    """Review-round finding (independent audit round), registered as D188
    (docs/DEFECT-REGISTER.md): `_tier_slide_budget_per_segment` was never
    re-derived for topic_selection_node's 1-2 (much larger) topics — with
    only 1-2 segments, it allocates well past issue #233's own mandated fixed
    totals (7 slides for T3, 10 for T1/T2), not exactly them. This test does
    NOT assert the mandated totals (that's piece #4's job, not this story's)
    — it PINS today's actual interim output for a realistic post-collapse
    duration split, so a future accidental change to this function's math
    is caught here instead of silently drifting further from both the old
    and the new target with nobody noticing (the gap this whole finding was
    about: the existing integration test already computes these numbers but
    never asserts on them, per D188's own test-coverage note)."""
    from app.modules.content.pipeline.graph import _tier_slide_budget_per_segment

    # Realistic near-equal duration split of each tier's narration budget
    # across topic_selection_node's collapsed topic count (2 for T1/T2, 1 for
    # T3) — see TIER_MIN_NARRATION_MINUTES for the source numbers (S5-5
    # replaced the SEAT_TIME_SHARES table these once came from).
    t1 = _tier_slide_budget_per_segment("T1", [14.6, 14.6])
    t2 = _tier_slide_budget_per_segment("T2", [9.75, 9.75])
    t3 = _tier_slide_budget_per_segment("T3", [9.75])

    t1_total = sum(seg_max for _, seg_max in t1)
    t2_total = sum(seg_max for _, seg_max in t2)
    t3_total = sum(seg_max for _, seg_max in t3)

    # Today's actual behavior (pinned, not endorsed): T1/T2 over-deliver past
    # the mandated 10-slide total; T3 under-delivers past the mandated 7.
    assert t1_total > 10, (
        f"T1 no longer exceeds its mandated total ({t1_total}) — re-check this pin"
    )
    assert t2_total > 10, (
        f"T2 no longer exceeds its mandated total ({t2_total}) — re-check this pin"
    )
    assert t3_total < 7, (
        f"T3 no longer falls short of its mandated total ({t3_total}) — re-check this pin"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_two_topic_prompt_never_renders_a_none_title_as_literal_none() -> None:
    """External review finding (Developer-2-max, PR #252): `s.get('title', '')`
    only substitutes when the key is ABSENT, not when it's explicitly `None`
    — every other title-touching spot in this file guards with `or ""`
    (`_derive_section_id`, `_merge_two`), this one didn't. A section with
    `title: None` (the rule-based heading detector can produce these) would
    render as the literal string "None" in the split-index prompt."""
    from app.modules.content.pipeline.graph import topic_selection_node

    sections = _sections([f"TOKEN_{i}" for i in range(6)])
    sections[2]["title"] = None
    provider = AsyncMock()
    provider.complete_structured.return_value = _split_response(3)
    with (
        patch("app.core.db.get_supabase", return_value=_mock_supabase()),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
    ):
        await topic_selection_node(_base_state(sections, tier="T2"))

    provider.complete_structured.assert_called_once()
    messages = provider.complete_structured.call_args.args[0]
    user_message = next(m["content"] for m in messages if m["role"] == "user")
    assert "2: None —" not in user_message, "a None title leaked as the literal string 'None'"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_collapse_purges_stale_phase1_checkpoints_reused_by_merged_topics() -> None:
    """External review finding (Developer-2-max, PR #252, verified): a merged
    topic's derived section_id (index + title-slug) can collide with a
    checkpoint written under the OLD (pre-topic_selection) per-original-
    section keying — guaranteed for index 0, since merge_section_range keeps
    sections[0]'s title verbatim. An in-flight job retried across this
    feature's deploy would otherwise silently serve the OLD, narrow
    checkpoint as if it were e.g. the summary for the new, much larger
    merged topic. The stale entry (and its section_truncation sibling) must
    be purged from node_outputs when a collapse actually happens."""
    from app.modules.content.pipeline.graph import _derive_section_id, topic_selection_node

    sections = _sections([f"TOKEN_{i}" for i in range(6)])
    # merge_section_range keeps sections[0]'s title verbatim for the merged
    # topic at index 0 -- so its derived id is IDENTICAL to what a pre-merge
    # run would have computed for original section 0 alone.
    stale_id = _derive_section_id(sections[0], 0)
    stale_key = f"summarise_segment:{stale_id}"
    stale_truncation_key = f"section_truncation:summarise_segment:{stale_id}"
    unrelated_key = "structure"  # must survive the purge untouched
    node_outputs = {
        stale_key: {"segment_id": stale_id, "summary": "STALE pre-collapse summary"},
        stale_truncation_key: {"original_chars": 999, "capped_chars": 500},
        unrelated_key: {"sections": sections},
    }
    sb = _mock_supabase(node_outputs)
    provider = AsyncMock()
    provider.complete_structured.return_value = _split_response(3)
    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
    ):
        await topic_selection_node(_base_state(sections, tier="T2"))

    checkpoint_calls = [
        c.args[0]
        for c in sb.table.return_value.update.call_args_list
        if "node_outputs" in c.args[0]
    ]
    assert len(checkpoint_calls) == 1
    written_node_outputs = checkpoint_calls[0]["node_outputs"]
    assert stale_key not in written_node_outputs, "stale checkpoint survived the collapse"
    assert stale_truncation_key not in written_node_outputs, "stale truncation record survived"
    assert unrelated_key in written_node_outputs, "purge must not touch unrelated entries"
    assert "topic_selection" in written_node_outputs


@pytest.mark.unit
@pytest.mark.asyncio
async def test_noop_path_does_not_purge_anything() -> None:
    """The AC-4 no-op path leaves `sections` (and therefore every derived id)
    unchanged, so there is nothing stale to purge — confirms the purge is
    scoped to the actual-collapse paths only."""
    from app.modules.content.pipeline.graph import _derive_section_id, topic_selection_node

    sections = _sections(["only body"])
    existing_id = _derive_section_id(sections[0], 0)
    existing_key = f"summarise_segment:{existing_id}"
    node_outputs = {existing_key: {"segment_id": existing_id, "summary": "real, still valid"}}
    sb = _mock_supabase(node_outputs)
    with patch("app.core.db.get_supabase", return_value=sb):
        await topic_selection_node(_base_state(sections, tier="T3"))

    checkpoint_calls = [
        c.args[0]
        for c in sb.table.return_value.update.call_args_list
        if "node_outputs" in c.args[0]
    ]
    assert existing_key in checkpoint_calls[0]["node_outputs"]
