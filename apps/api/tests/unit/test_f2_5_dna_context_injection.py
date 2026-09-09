"""Unit tests for Story F2-5 — inject Learner DNA context into content-generation prompts.

Covers:
  AC1 — get_dna_prompt_context (assessment/service.py): graceful "" degradation,
        real formatted text when a learner_dna row exists, no raw floats leak.
  AC2 — fetch_learner_context_node (content pipeline graph.py): idempotency
        cache-hit, checkpoint-write shape, delegates to get_dna_prompt_context.
  AC3 — dna_context reaches all three target nodes via _FAN_OUT_STATE_KEYS.
  AC4/AC5 — lesson_planner/slide_generator/narration_generator system prompts
        include dna_context when non-empty, are byte-identical when empty.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_USER_ID = "aaaaaaaa-0000-0000-0000-000000000001"
_LESSON_ID = "dddddddd-0000-0000-0000-000000000004"

_DNA_ROW = {
    "pattern_recognition": 78.0,
    "logical_deduction": 62.5,
    "processing_speed": 55.0,
    "frustration_tolerance": 48.0,
    "persistence": 80.0,
    "help_seeking": 43.0,
    "goal_orientation": 70.0,
    "curiosity_index": 88.0,
    "study_independence": 66.0,
    "badge_labels": ["Pattern Thinker"],
    "profile_text": "You tend to learn through patterns. — Pursuant to DPDP Act 2023.",
    "session_count": 4,
}


def _mock_dna_supabase(dna_row: dict | None) -> MagicMock:
    """Mirrors test_f2_1_learner_context.py's _chain_dna() mocking pattern."""
    supabase = MagicMock()
    chain = MagicMock()
    chain.eq.return_value = chain
    execute_resp = MagicMock()
    execute_resp.data = [dna_row] if dna_row else []
    chain.maybe_single.return_value.execute.return_value = execute_resp
    supabase.table.return_value.select.return_value = chain
    return supabase


# ══════════════════════════════════════════════════════════════════════════════
# AC1 — get_dna_prompt_context
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
@patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn())
@patch("app.modules.assessment.service.single_row")
async def test_get_dna_prompt_context_returns_empty_string_when_no_dna_row(
    mock_single_row, mock_to_thread
):
    """AC1/AC5: a new student with no learner_dna row gets "" — never raises, never None."""
    mock_single_row.side_effect = lambda resp: resp.data[0] if resp.data else None
    from app.modules.assessment.service import get_dna_prompt_context

    result = await get_dna_prompt_context(user_id=_USER_ID, supabase=_mock_dna_supabase(None))

    assert result == ""


@pytest.mark.unit
@patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn())
@patch("app.modules.assessment.service.single_row")
async def test_get_dna_prompt_context_returns_real_formatted_text_when_row_exists(
    mock_single_row, mock_to_thread
):
    """AC1: a real learner_dna row produces non-empty, descriptive-language text."""
    mock_single_row.side_effect = lambda resp: resp.data[0] if resp.data else None
    from app.modules.assessment.service import get_dna_prompt_context

    result = await get_dna_prompt_context(user_id=_USER_ID, supabase=_mock_dna_supabase(_DNA_ROW))

    assert result != ""
    assert "Pattern Thinker" in result
    assert "Student Learning Profile" in result


@pytest.mark.unit
@patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn())
@patch("app.modules.assessment.service.single_row")
async def test_get_dna_prompt_context_never_leaks_raw_numeric_dimension_values(
    mock_single_row, mock_to_thread
):
    """AC1: raw floats (e.g. "78.0", "62.5") must never appear — bands only."""
    mock_single_row.side_effect = lambda resp: resp.data[0] if resp.data else None
    from app.modules.assessment.service import get_dna_prompt_context

    result = await get_dna_prompt_context(user_id=_USER_ID, supabase=_mock_dna_supabase(_DNA_ROW))

    assert "78.0" not in result
    assert "62.5" not in result


# ══════════════════════════════════════════════════════════════════════════════
# AC2 — fetch_learner_context_node idempotency + checkpoint
# ══════════════════════════════════════════════════════════════════════════════


def _mock_jobs_supabase(node_outputs: dict) -> MagicMock:
    supabase = MagicMock()
    select_chain = MagicMock()
    select_chain.eq.return_value = select_chain
    execute_resp = MagicMock()
    execute_resp.data = {"node_outputs": node_outputs}
    select_chain.single.return_value.execute.return_value = execute_resp

    update_chain = MagicMock()
    update_chain.eq.return_value.execute.return_value = MagicMock()

    def _table(name: str):
        m = MagicMock()
        m.select.return_value = select_chain
        m.update.return_value = update_chain
        return m

    supabase.table.side_effect = _table
    return supabase, update_chain


@pytest.mark.unit
@patch("app.modules.content.pipeline.graph.single_row")
async def test_fetch_learner_context_node_cache_hit_skips_requery(mock_single_row):
    """AC2/AC6: an ARQ retry with an existing checkpoint must not re-fetch DNA."""
    from app.modules.content.pipeline.graph import fetch_learner_context_node

    mock_single_row.side_effect = lambda resp: resp.data if resp.data else None
    supabase, update_chain = _mock_jobs_supabase(
        {"fetch_learner_context": {"dna_context": "cached text"}}
    )

    with (
        patch("app.core.db.get_supabase", return_value=supabase),
        patch(
            "app.modules.assessment.service.get_dna_prompt_context", new_callable=AsyncMock
        ) as mock_get_dna,
    ):
        result = await fetch_learner_context_node({"lesson_id": _LESSON_ID, "user_id": _USER_ID})

    assert result == {"dna_context": "cached text"}
    mock_get_dna.assert_not_called()
    update_chain.eq.assert_not_called()


@pytest.mark.unit
@patch("app.modules.content.pipeline.graph.single_row")
async def test_fetch_learner_context_node_fresh_run_fetches_and_checkpoints(mock_single_row):
    """AC2: a fresh run calls get_dna_prompt_context once and writes the checkpoint."""
    from app.modules.content.pipeline.graph import fetch_learner_context_node

    mock_single_row.side_effect = lambda resp: resp.data if resp.data else None
    supabase, update_chain = _mock_jobs_supabase({})

    with (
        patch("app.core.db.get_supabase", return_value=supabase),
        patch(
            "app.modules.assessment.service.get_dna_prompt_context",
            new_callable=AsyncMock,
            return_value="fresh dna text",
        ) as mock_get_dna,
    ):
        result = await fetch_learner_context_node({"lesson_id": _LESSON_ID, "user_id": _USER_ID})

    assert result == {"dna_context": "fresh dna text"}
    mock_get_dna.assert_called_once_with(user_id=_USER_ID, supabase=supabase)
    update_chain.eq.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════════
# AC3 — _FAN_OUT_STATE_KEYS carries dna_context to narration_generator's dispatch
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_fan_out_state_keys_includes_dna_context():
    """AC3: dna_context must be forwarded into every Send() dispatch payload,
    mirroring this file's own established regression pattern for "tier"."""
    from app.modules.content.pipeline.graph import _FAN_OUT_STATE_KEYS

    assert "dna_context" in _FAN_OUT_STATE_KEYS


# ══════════════════════════════════════════════════════════════════════════════
# AC4/AC5 — system prompts include dna_context when present, unchanged when empty
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_planner_system_prompt_includes_dna_context_when_present():
    from app.modules.content.pipeline.graph import _planner_system_prompt

    prompt = _planner_system_prompt(tier_framing="", dna_context="Student Learning Profile: X")

    assert "Student Learning Profile: X" in prompt


_PLANNER_BASE_PROMPT = (
    "Produce a lesson plan outline from the section summaries below. "
    "Return an overall title, subject, 2-5 learning objectives, an "
    "overall complexity_level (low/medium/high), and return EXACTLY "
    "one outline segment per summary provided, echoing back each "
    "summary's segment_id UNCHANGED — do not invent, merge, split, "
    "omit, or reorder segment_ids. For each segment, provide a short "
    "title and an estimated duration_min (minutes of narration/slide "
    "time for that segment)."
)


@pytest.mark.unit
def test_planner_system_prompt_unchanged_when_dna_context_empty():
    """Pins the exact pre-F2-5 text, not just "two calls agree with each
    other" (which would pass even if dna_context were unconditionally
    appended, since both calls default to the same empty value)."""
    from app.modules.content.pipeline.graph import _planner_system_prompt

    prompt = _planner_system_prompt(tier_framing="", dna_context="")

    assert prompt.startswith(_PLANNER_BASE_PROMPT)
    assert "\n\n" not in prompt
