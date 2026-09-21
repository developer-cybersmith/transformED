"""
Unit tests for Story 236: narration_stitch_node.

Covers docs/stories/236-narration-post-planner-ordering.md's ACs:
- AC 7: one llm_mini call for transition/duplicate-phrasing polish, guarded
  exactly like lesson_planner_node's degrade-not-fabricate block; any guard
  failure (or the LLM returning nothing) falls through to the unmodified-but-
  ordered scripts.
- AC 8: _apply_narration_char_cap (moved here from tts_node, Story 3-37/
  decisionupdate.md §8) — this file inherits that story's full cap test suite,
  adapted to call narration_stitch_node and check narration_scripts_final/the
  "narration_stitch" checkpoint key instead of tts_node's.
- AC 9: _warn_if_duplicated canary on the narration_scripts fan-in input.
- AC 10: returns narration_scripts_final (plain field), never narration_scripts.

The LLM stitching call is mocked to return None in every ported Story 3-37
cap test (simulating "no stitching available") so those tests keep exercising
exactly the character-level assertions they always did, on the unmodified-but-
ordered fallback path — the cap logic itself is untouched by this story.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

FAKE_LESSON_ID = "60606060-6060-6060-6060-606060606060"

NARRATION_SCRIPTS: list[dict[str, Any]] = [
    {
        "segment_id": "sec_0",
        "script": "Welcome to the lesson.",
        "narration_style": "conversational",
        "word_count": 4,
    },
    {
        "segment_id": "sec_1",
        "script": "Here is how it works.",
        "narration_style": "explanatory",
        "word_count": 5,
    },
]


def _base_state(**overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "lesson_id": FAKE_LESSON_ID,
        "narration_scripts": NARRATION_SCRIPTS,
        "progress_pct": 48.0,
        "error": None,
    }
    state.update(overrides)
    return state


def _mock_supabase(node_outputs: dict[str, Any] | None = None) -> MagicMock:
    sb = MagicMock()
    jobs_mock = MagicMock()
    jobs_mock.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "node_outputs": node_outputs or {}
    }
    jobs_mock.update.return_value.eq.return_value.execute.return_value = MagicMock()
    sb.table.return_value = jobs_mock
    return sb


def _mock_settings_with_narration_cap(cap: int) -> MagicMock:
    """Same rationale as test_tts_node.py's (pre-#236) helper of the same
    name: pins a test-local cap so boundary tests exercise the cap mechanism
    independent of the real production default. Also carries llm_mini since
    narration_stitch_node reads it before the cap runs."""
    settings = MagicMock()
    settings.max_narration_chars_per_lesson = cap
    settings.llm_mini = "gpt-4o-mini"
    return settings


def _mock_settings(cap: int = 120_000) -> MagicMock:
    settings = MagicMock()
    settings.max_narration_chars_per_lesson = cap
    settings.llm_mini = "gpt-4o-mini"
    return settings


def _no_stitch_provider() -> AsyncMock:
    """A provider whose complete_structured call returns None — simulates
    "stitching unavailable", exercising the unmodified-but-ordered fallback
    path so ported cap tests keep their original character-level assertions."""
    provider = AsyncMock()
    provider.complete_structured.return_value = None
    return provider


# ---------------------------------------------------------------------------
# AC 7: stitching LLM call + degrade-not-fabricate guards
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_llm_refusal_falls_back_to_unstitched_ordered_scripts() -> None:
    """complete_structured returning None must not crash the node — falls
    through to the input scripts, ordered, unmodified."""
    from app.modules.content.pipeline.graph import narration_stitch_node

    sb = _mock_supabase()
    provider = _no_stitch_provider()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings", return_value=_mock_settings()),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
    ):
        result = await narration_stitch_node(_base_state())

    scripts = {e["segment_id"]: e["script"] for e in result["narration_scripts_final"]}
    assert scripts == {"sec_0": "Welcome to the lesson.", "sec_1": "Here is how it works."}
    # AC 10: progress_pct milestone between slide_generator's 48.0 and
    # tts_node's 86.0 — the specific numeric claim AC 10 makes, not just that
    # the key exists.
    assert result["progress_pct"] == 60.0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_llm_call_raising_falls_back_instead_of_crashing_the_node() -> None:
    """Scale & Load review finding: complete_structured() RAISES (not
    returns None) on a retry-exhausted rate limit, an open circuit breaker,
    or a truncated structured response — this node's own design intent
    ("never fail the lesson over a cosmetic pass") must hold for that case
    too, not just a clean None response. Every per-section narration_generator
    dispatch has already succeeded and been paid for by the time this node
    runs, so an uncaught exception here would crash an otherwise-complete
    lesson."""
    from app.modules.content.pipeline.graph import narration_stitch_node

    sb = _mock_supabase()
    provider = AsyncMock()
    provider.complete_structured.side_effect = RuntimeError("rate limited, retries exhausted")

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings", return_value=_mock_settings()),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
    ):
        result = await narration_stitch_node(_base_state())

    scripts = {e["segment_id"]: e["script"] for e in result["narration_scripts_final"]}
    assert scripts == {"sec_0": "Welcome to the lesson.", "sec_1": "Here is how it works."}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_accepted_response_replaces_scripts_and_recomputes_word_count() -> None:
    """A valid response (matching segment_id set/count/uniqueness, no blank
    script) is accepted — script AND word_count are updated from the LLM's
    output, narration_style is left untouched."""
    from app.modules.content.pipeline.graph import (
        _StitchedNarrationLLM,
        _StitchedNarrationSegmentLLM,
        narration_stitch_node,
    )

    sb = _mock_supabase()
    provider = AsyncMock()
    provider.complete_structured.return_value = _StitchedNarrationLLM(
        segments=[
            _StitchedNarrationSegmentLLM(segment_id="sec_0", script="Welcome! Let's get started."),
            _StitchedNarrationSegmentLLM(segment_id="sec_1", script="Now, here is how it works."),
        ]
    )

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings", return_value=_mock_settings()),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
    ):
        result = await narration_stitch_node(_base_state())

    by_id = {e["segment_id"]: e for e in result["narration_scripts_final"]}
    assert by_id["sec_0"]["script"] == "Welcome! Let's get started."
    assert by_id["sec_0"]["word_count"] == 4
    assert by_id["sec_0"]["narration_style"] == "conversational"
    assert by_id["sec_1"]["script"] == "Now, here is how it works."


@pytest.mark.unit
@pytest.mark.asyncio
async def test_accepted_response_in_permuted_order_still_reassembles_correctly() -> None:
    """Test Coverage review finding: the guard only checks segment_id
    SET/count/uniqueness, so a response returning the same segment_ids in a
    different order must still be accepted (not treated as a mismatch), and
    reassembly must key off segment_id (dict lookup), never trust the
    response's own order — final output stays in true lesson order regardless
    of what order the LLM echoed the segments back in."""
    from app.modules.content.pipeline.graph import (
        _StitchedNarrationLLM,
        _StitchedNarrationSegmentLLM,
        narration_stitch_node,
    )

    sb = _mock_supabase()
    provider = AsyncMock()
    # Reversed relative to the input's sec_0, sec_1 order.
    provider.complete_structured.return_value = _StitchedNarrationLLM(
        segments=[
            _StitchedNarrationSegmentLLM(segment_id="sec_1", script="Now, here is how it works."),
            _StitchedNarrationSegmentLLM(segment_id="sec_0", script="Welcome! Let's get started."),
        ]
    )

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings", return_value=_mock_settings()),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
    ):
        result = await narration_stitch_node(_base_state())

    ordered = result["narration_scripts_final"]
    assert [e["segment_id"] for e in ordered] == ["sec_0", "sec_1"], (
        "output order must follow true lesson order, not the LLM response's order"
    )
    by_id = {e["segment_id"]: e for e in ordered}
    assert by_id["sec_0"]["script"] == "Welcome! Let's get started."
    assert by_id["sec_1"]["script"] == "Now, here is how it works."


@pytest.mark.unit
@pytest.mark.asyncio
async def test_segment_count_mismatch_falls_back() -> None:
    from app.modules.content.pipeline.graph import (
        _StitchedNarrationLLM,
        _StitchedNarrationSegmentLLM,
        narration_stitch_node,
    )

    sb = _mock_supabase()
    provider = AsyncMock()
    provider.complete_structured.return_value = _StitchedNarrationLLM(
        segments=[_StitchedNarrationSegmentLLM(segment_id="sec_0", script="Only one back.")]
    )

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings", return_value=_mock_settings()),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
    ):
        result = await narration_stitch_node(_base_state())

    scripts = {e["segment_id"]: e["script"] for e in result["narration_scripts_final"]}
    assert scripts == {"sec_0": "Welcome to the lesson.", "sec_1": "Here is how it works."}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unknown_segment_id_falls_back() -> None:
    from app.modules.content.pipeline.graph import (
        _StitchedNarrationLLM,
        _StitchedNarrationSegmentLLM,
        narration_stitch_node,
    )

    sb = _mock_supabase()
    provider = AsyncMock()
    provider.complete_structured.return_value = _StitchedNarrationLLM(
        segments=[
            _StitchedNarrationSegmentLLM(segment_id="sec_0", script="A"),
            _StitchedNarrationSegmentLLM(segment_id="sec_NOT_REAL", script="B"),
        ]
    )

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings", return_value=_mock_settings()),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
    ):
        result = await narration_stitch_node(_base_state())

    scripts = {e["segment_id"]: e["script"] for e in result["narration_scripts_final"]}
    assert scripts == {"sec_0": "Welcome to the lesson.", "sec_1": "Here is how it works."}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_duplicate_segment_id_falls_back() -> None:
    from app.modules.content.pipeline.graph import (
        _StitchedNarrationLLM,
        _StitchedNarrationSegmentLLM,
        narration_stitch_node,
    )

    sb = _mock_supabase()
    provider = AsyncMock()
    provider.complete_structured.return_value = _StitchedNarrationLLM(
        segments=[
            _StitchedNarrationSegmentLLM(segment_id="sec_0", script="A"),
            _StitchedNarrationSegmentLLM(segment_id="sec_0", script="A again"),
        ]
    )

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings", return_value=_mock_settings()),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
    ):
        result = await narration_stitch_node(_base_state())

    scripts = {e["segment_id"]: e["script"] for e in result["narration_scripts_final"]}
    assert scripts == {"sec_0": "Welcome to the lesson.", "sec_1": "Here is how it works."}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_blank_script_in_response_falls_back() -> None:
    from app.modules.content.pipeline.graph import (
        _StitchedNarrationLLM,
        _StitchedNarrationSegmentLLM,
        narration_stitch_node,
    )

    sb = _mock_supabase()
    provider = AsyncMock()
    provider.complete_structured.return_value = _StitchedNarrationLLM(
        segments=[
            _StitchedNarrationSegmentLLM(segment_id="sec_0", script="   "),
            _StitchedNarrationSegmentLLM(segment_id="sec_1", script="fine"),
        ]
    )

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings", return_value=_mock_settings()),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
    ):
        result = await narration_stitch_node(_base_state())

    scripts = {e["segment_id"]: e["script"] for e in result["narration_scripts_final"]}
    assert scripts == {"sec_0": "Welcome to the lesson.", "sec_1": "Here is how it works."}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_empty_narration_scripts_skips_llm_call_entirely() -> None:
    """Nothing to stitch — no LLM call is made at all, and the cap's
    always-present record is still written (capped=False, zeros)."""
    from app.modules.content.pipeline.graph import narration_stitch_node

    sb = _mock_supabase()
    provider = AsyncMock()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings", return_value=_mock_settings()),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
    ):
        result = await narration_stitch_node(_base_state(narration_scripts=[]))

    assert result["narration_scripts_final"] == []
    provider.complete_structured.assert_not_called()


# ---------------------------------------------------------------------------
# AC 9: reducer-fan-in canary
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_duplicated_fan_in_channel_is_logged_not_crashed(caplog) -> None:
    import logging

    from app.modules.content.pipeline.graph import narration_stitch_node

    sb = _mock_supabase()
    duplicated = NARRATION_SCRIPTS + NARRATION_SCRIPTS  # same segment_ids twice

    with (
        caplog.at_level(logging.ERROR),
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings", return_value=_mock_settings()),
        patch("app.providers.llm.factory.get_llm_provider", return_value=_no_stitch_provider()),
    ):
        await narration_stitch_node(_base_state(narration_scripts=duplicated))

    assert any("narration_scripts" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_idempotency_cache_hit_skips_llm_call() -> None:
    from app.modules.content.pipeline.graph import narration_stitch_node

    cached = [{"segment_id": "sec_0", "script": "cached", "narration_style": "x", "word_count": 1}]
    sb = _mock_supabase(node_outputs={"narration_stitch": cached})
    provider = AsyncMock()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
    ):
        result = await narration_stitch_node(_base_state())

    assert result["narration_scripts_final"] == cached
    provider.complete_structured.assert_not_called()


# ---------------------------------------------------------------------------
# Story 3-37 / decisionupdate.md §8 (moved here by issue #236): narration
# hard cap. The LLM stitching call is mocked to return None throughout this
# section — these tests exercise the cap mechanism on the unmodified-but-
# ordered fallback path, exactly as they did in tts_node before this story.
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lesson_wide_narration_cap_truncates_and_zeroes_over_budget_segments() -> None:
    """4 segments of 4,000 chars each (16,000 total) exceed the 10,000-char
    lesson-wide cap. The 3rd segment (crosses the boundary at 8,000 + 4,000 >
    10,000) must be truncated to exactly the remaining 2,000-char budget; the
    4th segment must be zeroed. Sum of characters in the final output must
    never exceed the cap, and an explicit, always-present degradation record
    must be persisted."""
    from app.modules.content.pipeline.graph import narration_stitch_node

    scripts = [
        {"segment_id": "sec_0", "script": "A" * 4000, "narration_style": "x", "word_count": 1},
        {"segment_id": "sec_1", "script": "B" * 4000, "narration_style": "x", "word_count": 1},
        {"segment_id": "sec_2", "script": "C" * 4000, "narration_style": "x", "word_count": 1},
        {"segment_id": "sec_3", "script": "D" * 4000, "narration_style": "x", "word_count": 1},
    ]
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings", return_value=_mock_settings_with_narration_cap(10000)),
        patch("app.providers.llm.factory.get_llm_provider", return_value=_no_stitch_provider()),
    ):
        result = await narration_stitch_node(_base_state(narration_scripts=scripts))

    by_id = {e["segment_id"]: e["script"] for e in result["narration_scripts_final"]}
    assert by_id["sec_0"] == "A" * 4000
    assert by_id["sec_1"] == "B" * 4000
    assert by_id["sec_2"] == "C" * 2000
    assert by_id["sec_3"] == ""
    assert sum(len(s) for s in by_id.values()) <= 10000

    checkpoint_calls = [
        c.args[0]
        for c in sb.table.return_value.update.call_args_list
        if "node_outputs" in c.args[0]
    ]
    assert len(checkpoint_calls) == 1
    cap_record = checkpoint_calls[0]["node_outputs"]["narration_cap_applied"]
    assert cap_record == {
        "capped": True,
        "original_total_chars": 16000,
        "capped_total_chars": 10000,
        "affected_segment_ids": ["sec_2", "sec_3"],
    }
    assert checkpoint_calls[0]["last_node"] == "narration_stitch"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lesson_wide_narration_under_cap_is_completely_unaffected() -> None:
    """A lesson whose combined narration is well under the cap must be
    completely unaffected — capped=False, totals equal, empty affected list."""
    from app.modules.content.pipeline.graph import narration_stitch_node

    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings", return_value=_mock_settings()),
        patch("app.providers.llm.factory.get_llm_provider", return_value=_no_stitch_provider()),
    ):
        result = await narration_stitch_node(_base_state())

    by_id = {e["segment_id"]: e["script"] for e in result["narration_scripts_final"]}
    assert by_id["sec_0"] == "Welcome to the lesson."
    assert by_id["sec_1"] == "Here is how it works."
    total_chars = len("Welcome to the lesson.") + len("Here is how it works.")

    checkpoint_calls = [
        c.args[0]
        for c in sb.table.return_value.update.call_args_list
        if "node_outputs" in c.args[0]
    ]
    cap_record = checkpoint_calls[0]["node_outputs"]["narration_cap_applied"]
    assert cap_record == {
        "capped": False,
        "original_total_chars": total_chars,
        "capped_total_chars": total_chars,
        "affected_segment_ids": [],
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_narration_cap_exact_boundary_fit_is_not_truncated() -> None:
    """A segment whose length exactly exhausts the remaining budget must NOT
    be treated as truncated — only the segment AFTER it is zeroed."""
    from app.modules.content.pipeline.graph import narration_stitch_node

    scripts = [
        {"segment_id": "sec_0", "script": "A" * 10000, "narration_style": "x", "word_count": 1},
        {"segment_id": "sec_1", "script": "B" * 100, "narration_style": "x", "word_count": 1},
    ]
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings", return_value=_mock_settings_with_narration_cap(10000)),
        patch("app.providers.llm.factory.get_llm_provider", return_value=_no_stitch_provider()),
    ):
        result = await narration_stitch_node(_base_state(narration_scripts=scripts))

    by_id = {e["segment_id"]: e["script"] for e in result["narration_scripts_final"]}
    assert by_id["sec_0"] == "A" * 10000  # exact fit, unmodified
    assert by_id["sec_1"] == ""  # zeroed, budget already exhausted

    checkpoint_calls = [
        c.args[0]
        for c in sb.table.return_value.update.call_args_list
        if "node_outputs" in c.args[0]
    ]
    cap_record = checkpoint_calls[0]["node_outputs"]["narration_cap_applied"]
    assert cap_record == {
        "capped": True,
        "original_total_chars": 10100,
        "capped_total_chars": 10000,
        "affected_segment_ids": ["sec_1"],
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_narration_cap_empty_narration_scripts_list_is_uncapped_by_construction() -> None:
    """An empty narration_scripts must still get an explicit, always-present
    capped=False record — never skip the write just because there was
    nothing to cap."""
    from app.modules.content.pipeline.graph import narration_stitch_node

    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings", return_value=_mock_settings()),
        patch("app.providers.llm.factory.get_llm_provider", return_value=_no_stitch_provider()),
    ):
        result = await narration_stitch_node(_base_state(narration_scripts=[]))

    assert result["narration_scripts_final"] == []

    checkpoint_calls = [
        c.args[0]
        for c in sb.table.return_value.update.call_args_list
        if "node_outputs" in c.args[0]
    ]
    assert len(checkpoint_calls) == 1
    cap_record = checkpoint_calls[0]["node_outputs"]["narration_cap_applied"]
    assert cap_record == {
        "capped": False,
        "original_total_chars": 0,
        "capped_total_chars": 0,
        "affected_segment_ids": [],
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_narration_cap_reorders_out_of_order_fan_in_by_true_section_index() -> None:
    """narration_scripts is Annotated[list, operator.add], fed by
    Send()-dispatched calls with NO cross-call ordering guarantee. Hand-
    construct the fan-in list arriving OUT of section order — the LAST
    section by real segment_id index (section_3) must still be the one that
    gets zeroed, never whichever entry happened to land last in the
    (scrambled) list."""
    from app.modules.content.pipeline.graph import narration_stitch_node

    # Arrival order: 2, 0, 3, 1 — deliberately not lesson order.
    scripts = [
        {"segment_id": "section_2_c", "script": "C" * 4000, "narration_style": "x"},
        {"segment_id": "section_0_a", "script": "A" * 4000, "narration_style": "x"},
        {"segment_id": "section_3_d", "script": "D" * 4000, "narration_style": "x"},
        {"segment_id": "section_1_b", "script": "B" * 4000, "narration_style": "x"},
    ]
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings", return_value=_mock_settings_with_narration_cap(10000)),
        patch("app.providers.llm.factory.get_llm_provider", return_value=_no_stitch_provider()),
    ):
        result = await narration_stitch_node(_base_state(narration_scripts=scripts))

    by_id = {e["segment_id"]: e["script"] for e in result["narration_scripts_final"]}
    assert by_id["section_0_a"] == "A" * 4000
    assert by_id["section_1_b"] == "B" * 4000
    assert by_id["section_2_c"] == "C" * 2000
    assert by_id["section_3_d"] == ""

    checkpoint_calls = [
        c.args[0]
        for c in sb.table.return_value.update.call_args_list
        if "node_outputs" in c.args[0]
    ]
    cap_record = checkpoint_calls[0]["node_outputs"]["narration_cap_applied"]
    assert cap_record["affected_segment_ids"] == ["section_2_c", "section_3_d"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_narration_cap_skips_non_dict_entry_without_crashing_node() -> None:
    """A non-dict entry in narration_scripts (bare string, from a
    schema-drifted or hand-edited checkpoint) must be logged and dropped,
    never crash the whole node."""
    from app.modules.content.pipeline.graph import narration_stitch_node

    scripts: list[Any] = [
        {"segment_id": "sec_0", "script": "hello", "narration_style": "x"},
        "not-a-dict-entry",
        {"segment_id": "sec_1", "script": "world", "narration_style": "x"},
    ]
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings", return_value=_mock_settings()),
        patch("app.providers.llm.factory.get_llm_provider", return_value=_no_stitch_provider()),
    ):
        result = await narration_stitch_node(_base_state(narration_scripts=scripts))

    by_id = {e["segment_id"]: e["script"] for e in result["narration_scripts_final"]}
    assert set(by_id) == {"sec_0", "sec_1"}
    assert by_id["sec_0"] == "hello"
    assert by_id["sec_1"] == "world"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_narration_cap_truncation_does_not_split_devanagari_combining_mark() -> None:
    """A raw character-index slice can land between a base consonant and a
    dependent vowel sign (matra) — the truncation must back off to the
    nearest safe grapheme boundary instead."""
    from app.modules.content.pipeline.graph import narration_stitch_node

    devanagari_pair = "कि"  # क (KA, base) + ि (VOWEL SIGN I, combining)
    first_segment = ("A" * 9999) + devanagari_pair  # 10,001 chars total
    scripts = [
        {"segment_id": "sec_0", "script": first_segment, "narration_style": "x"},
        {"segment_id": "sec_1", "script": "B" * 100, "narration_style": "x"},
    ]
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings", return_value=_mock_settings_with_narration_cap(10000)),
        patch("app.providers.llm.factory.get_llm_provider", return_value=_no_stitch_provider()),
    ):
        result = await narration_stitch_node(_base_state(narration_scripts=scripts))

    by_id = {e["segment_id"]: e["script"] for e in result["narration_scripts_final"]}
    truncated = by_id["sec_0"]
    assert truncated == "A" * 9999
    assert not truncated.endswith("क")
    assert "ि" not in truncated
    assert len(truncated) <= 10000


@pytest.mark.unit
@pytest.mark.asyncio
async def test_production_default_does_not_truncate_a_real_world_sized_lesson() -> None:
    """D78 (Story 3-45): the REAL settings.max_narration_chars_per_lesson
    (not a mocked test-local cap) must not truncate an ordinary real
    chapter — reproduces the exact real per-segment character distribution
    from production lesson abe4e438."""
    from app.modules.content.pipeline.graph import narration_stitch_node

    real_segment_char_counts = [
        3502,
        3083,
        3357,
        1436,
        4035,
        1587,
        3251,
        2160,
        3847,
        3984,
        1161,
        2910,
        3634,
        3187,
        2659,
    ]
    assert sum(real_segment_char_counts) == 43793
    scripts = [
        {"segment_id": f"sec_{i}", "script": "A" * n, "narration_style": "x"}
        for i, n in enumerate(real_segment_char_counts)
    ]
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.factory.get_llm_provider", return_value=_no_stitch_provider()),
        # Deliberately NOT patching app.config.get_settings — this must
        # exercise the real production default.
    ):
        result = await narration_stitch_node(_base_state(narration_scripts=scripts))

    by_id = {e["segment_id"]: e["script"] for e in result["narration_scripts_final"]}
    for i, n in enumerate(real_segment_char_counts):
        assert by_id[f"sec_{i}"] == "A" * n, (
            f"sec_{i} was truncated/zeroed by the production narration cap "
            f"({len(by_id[f'sec_{i}'])} of {n} chars survived)"
        )
