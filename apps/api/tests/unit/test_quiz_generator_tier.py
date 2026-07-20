"""
Story 3-28 — Tier-aware quiz question count in quiz_generator_node.

RED-phase tests written before implementation. All tests are expected to FAIL
against the current single-question quiz_generator_node implementation and PASS
after the _QuizBatchLLM / _TIER_QUIZ_COUNT_BAND changes are applied.

Acceptance criteria covered:
  AC 1  — T1 produces 3-5 questions
  AC 2  — T2 produces 2-3 questions
  AC 3  — T3 produces 1-2 questions
  AC 4  — _TIER_QUIZ_COUNT_BAND constant with correct values
  AC 5  — question_id has 0-indexed suffix
  AC 6  — all per-question validation guards apply to each batch item
  AC 7  — zero valid questions degrades gracefully
  AC 8  — partial batch accepted; below N_min warns, does not discard
  AC 9  — old single-question checkpoint treated as cache-miss
  AC 10 — NOT tested here; covered by updated TestAC3QuizGenerator in test_phase1_economy_nodes.py
  AC 11 — package_builder unchanged (no test needed — architecture test)
  AC 12 — shared types unchanged (no test needed — read-only)
  AC 13 — settings.llm_mini used, not hardcoded
  AC 14 — unknown tier falls back to T2
  AC 15 — exactly one LLM call per segment regardless of tier
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.providers.llm.openai as openai_provider_module  # noqa: F401  — forces submodule into sys.modules

FAKE_LESSON_ID = "30303030-3030-3030-3030-303030303030"
FAKE_USER_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
FAKE_BOOK_ID = "22222222-2222-2222-2222-222222222222"

_SECTION_0: dict[str, Any] = {
    "title": "Spaced Repetition",
    "body": "prose about spaced repetition. " * 20,
    "page_start": 1,
    "page_end": 3,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_q(
    question: str = "What is X?",
    options: list[str] | None = None,
    correct_index: int = 0,
    explanation: str = "X is correct.",
    difficulty: str = "medium",
) -> Any:
    """Return a _QuizQuestionLLM-shaped mock object (plain Python object)."""
    return type(
        "Q",
        (),
        {
            "question": question,
            "options": options if options is not None else ["A", "B", "C", "D"],
            "correct_index": correct_index,
            "explanation": explanation,
            "difficulty": difficulty,
        },
    )()


def _make_batch(*questions: Any) -> Any:
    """Return a _QuizBatchLLM-shaped mock object containing the given questions."""
    return type("Batch", (), {"questions": list(questions)})()


def _state(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "lesson_id": FAKE_LESSON_ID,
        "user_id": FAKE_USER_ID,
        "book_id": FAKE_BOOK_ID,
        "sections": [_SECTION_0],
        "progress_pct": 0.0,
        "error": None,
        "_section": _SECTION_0,
        "_section_index": 0,
    }
    base.update(overrides)
    return base


def _valid_question_data(section_id: str, idx: int = 0) -> dict[str, Any]:
    """A valid question checkpoint entry for a given section_id and 0-based index."""
    return {
        "segment_id": section_id,
        "data": {
            "question_id": f"quiz_{section_id}_{idx}",
            "type": "mcq",
            "question": "What is spaced repetition?",
            "options": ["Option A", "Option B", "Option C", "Option D"],
            "correct_index": 1,
            "explanation": "Spaced repetition improves long-term retention.",
            "difficulty": "medium",
        },
    }


# ---------------------------------------------------------------------------
# Autouse: no-op checkpoint infra (same philosophy as test_phase1_economy_nodes)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_checkpoint_infra():
    """Prevent real Supabase/Redis calls. The DB mock purposely does NOT pre-load
    any checkpoint data, so every test starts with a cache-miss unless it
    overrides the mock explicitly."""
    mock_jobs_table = MagicMock()
    mock_jobs_table.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {
        "node_outputs": {}
    }
    mock_supabase = MagicMock()
    mock_supabase.table.return_value = mock_jobs_table
    mock_supabase.rpc.return_value.execute.return_value = MagicMock()

    mock_redis = AsyncMock()
    mock_redis.get.return_value = None

    with (
        patch("app.core.db.get_supabase", return_value=mock_supabase),
        patch("app.core.redis.get_redis", return_value=mock_redis),
    ):
        yield


# ---------------------------------------------------------------------------
# AC 4: _TIER_QUIZ_COUNT_BAND constant exists with correct values
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_tier_quiz_count_band_constant_has_correct_values() -> None:
    """AC 4: T1→(3,5), T2→(2,3), T3→(1,2)."""
    from app.modules.content.pipeline.graph import _TIER_QUIZ_COUNT_BAND  # type: ignore[attr-defined]

    assert _TIER_QUIZ_COUNT_BAND["T1"] == (3, 5)
    assert _TIER_QUIZ_COUNT_BAND["T2"] == (2, 3)
    assert _TIER_QUIZ_COUNT_BAND["T3"] == (1, 2)
    assert set(_TIER_QUIZ_COUNT_BAND.keys()) == {"T1", "T2", "T3"}


# ---------------------------------------------------------------------------
# AC 1–3: tier-correct question counts
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_t1_tier_produces_correct_question_count() -> None:
    """AC 1: T1 default band (3-5); mock returns 4 questions → expect 4 back."""
    from app.modules.content.pipeline.graph import quiz_generator_node

    batch = _make_batch(*[_make_q(question=f"Q{i}?") for i in range(4)])
    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = batch

    with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
        result = await quiz_generator_node(_state(tier="T1"))

    assert len(result["quiz_questions"]) == 4


@pytest.mark.unit
@pytest.mark.asyncio
async def test_t2_tier_produces_correct_question_count() -> None:
    """AC 2: T2 default band (2-3); mock returns 2 questions → expect 2 back."""
    from app.modules.content.pipeline.graph import quiz_generator_node

    batch = _make_batch(_make_q(question="Q1?"), _make_q(question="Q2?"))
    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = batch

    with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
        result = await quiz_generator_node(_state(tier="T2"))

    assert len(result["quiz_questions"]) == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_t3_tier_produces_correct_question_count() -> None:
    """AC 3: T3 default band (1-2); mock returns 1 question → expect 1 back."""
    from app.modules.content.pipeline.graph import quiz_generator_node

    batch = _make_batch(_make_q(question="Q1?"))
    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = batch

    with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
        result = await quiz_generator_node(_state(tier="T3"))

    assert len(result["quiz_questions"]) == 1


# ---------------------------------------------------------------------------
# AC 5: question_id has 0-indexed suffix
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_question_ids_have_0_indexed_suffix() -> None:
    """AC 5: question_id for 3 questions should be quiz_{section_id}_0/1/2."""
    from app.modules.content.pipeline.graph import _derive_section_id, quiz_generator_node

    section_id = _derive_section_id(_SECTION_0, 0)
    batch = _make_batch(*[_make_q(question=f"Q{i}?") for i in range(3)])
    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = batch

    with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
        result = await quiz_generator_node(_state(tier="T1"))

    ids = [q["data"]["question_id"] for q in result["quiz_questions"]]
    assert ids == [
        f"quiz_{section_id}_0",
        f"quiz_{section_id}_1",
        f"quiz_{section_id}_2",
    ]


# ---------------------------------------------------------------------------
# AC 6: all existing per-question guards apply to each batch item
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_question_with_too_few_options_is_rejected_from_batch() -> None:
    """AC 6: a question with < 4 options is rejected; the rest of the batch is kept."""
    from app.modules.content.pipeline.graph import quiz_generator_node

    good = _make_q(question="Good?")
    bad = _make_q(question="Bad?", options=["X", "Y"])  # only 2 options
    batch = _make_batch(good, bad, _make_q(question="Also good?"))
    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = batch

    with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
        result = await quiz_generator_node(_state(tier="T1"))

    assert len(result["quiz_questions"]) == 2
    questions = [q["data"]["question"] for q in result["quiz_questions"]]
    assert "Good?" in questions
    assert "Also good?" in questions
    assert "Bad?" not in questions


@pytest.mark.unit
@pytest.mark.asyncio
async def test_question_with_out_of_range_correct_index_is_rejected_from_batch() -> None:
    """AC 6: correct_index out of range rejects that question; others kept."""
    from app.modules.content.pipeline.graph import quiz_generator_node

    good = _make_q(question="Valid?")
    bad = _make_q(question="Invalid index?", correct_index=99)
    batch = _make_batch(good, bad)
    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = batch

    with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
        result = await quiz_generator_node(_state(tier="T2"))

    assert len(result["quiz_questions"]) == 1
    assert result["quiz_questions"][0]["data"]["question"] == "Valid?"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_question_with_duplicate_options_is_rejected_from_batch() -> None:
    """AC 6: duplicate options (normalized) reject that question."""
    from app.modules.content.pipeline.graph import quiz_generator_node

    good = _make_q(question="Good?")
    bad = _make_q(
        question="Dupes?",
        options=["Spaced Repetition", "spaced repetition", "SPACED REPETITION", "D"],
    )
    batch = _make_batch(good, bad)
    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = batch

    with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
        result = await quiz_generator_node(_state(tier="T2"))

    assert len(result["quiz_questions"]) == 1
    assert result["quiz_questions"][0]["data"]["question"] == "Good?"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_question_with_blank_option_is_rejected_from_batch() -> None:
    """AC 6: any blank option string rejects that question."""
    from app.modules.content.pipeline.graph import quiz_generator_node

    good = _make_q(question="Good?")
    bad = _make_q(question="Blank opt?", options=["A", "   ", "C", "D"])
    batch = _make_batch(good, bad)
    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = batch

    with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
        result = await quiz_generator_node(_state(tier="T2"))

    assert len(result["quiz_questions"]) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_question_with_blank_question_text_is_rejected_from_batch() -> None:
    """AC 6: blank question text rejects that question."""
    from app.modules.content.pipeline.graph import quiz_generator_node

    good = _make_q(question="Good?")
    bad = _make_q(question="   ", explanation="Explanation.")
    batch = _make_batch(good, bad)
    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = batch

    with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
        result = await quiz_generator_node(_state(tier="T2"))

    assert len(result["quiz_questions"]) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_5_options_in_batch_question_are_truncated_to_4() -> None:
    """AC 6: 5-option question in batch is truncated to 4 (not rejected)."""
    from app.modules.content.pipeline.graph import quiz_generator_node

    q_5opts = _make_q(question="Five opts?", options=["A", "B", "C", "D", "E"])
    batch = _make_batch(q_5opts)
    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = batch

    with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
        result = await quiz_generator_node(_state(tier="T3"))

    assert len(result["quiz_questions"]) == 1
    assert len(result["quiz_questions"][0]["data"]["options"]) == 4


# ---------------------------------------------------------------------------
# AC 7: all invalid → graceful empty return
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_all_invalid_batch_returns_empty_list() -> None:
    """AC 7: if every question fails validation, return [] without crashing."""
    from app.modules.content.pipeline.graph import quiz_generator_node

    batch = _make_batch(
        _make_q(question="   ", explanation="Explanation."),   # blank question
        _make_q(question="Q?", options=["X", "Y"]),            # < 4 options
    )
    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = batch

    with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
        result = await quiz_generator_node(_state(tier="T2"))

    assert result["quiz_questions"] == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_none_response_returns_empty_list() -> None:
    """AC 7: LLM returning None degrades gracefully (same as before)."""
    from app.modules.content.pipeline.graph import quiz_generator_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = None

    with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
        result = await quiz_generator_node(_state(tier="T1"))

    assert result["quiz_questions"] == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_empty_questions_list_in_batch_returns_empty_list() -> None:
    """AC 7: LLM returning a batch with an empty questions list degrades gracefully."""
    from app.modules.content.pipeline.graph import quiz_generator_node

    batch = _make_batch()  # no questions
    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = batch

    with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
        result = await quiz_generator_node(_state(tier="T1"))

    assert result["quiz_questions"] == []


# ---------------------------------------------------------------------------
# AC 8: partial batch accepted when below N_min
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_partial_batch_below_n_min_keeps_valid_questions() -> None:
    """AC 8: T1 (N_min=3) but only 1 valid question → keep it, don't discard."""
    from app.modules.content.pipeline.graph import quiz_generator_node

    good = _make_q(question="Only valid question?")
    bad = _make_q(question="   ")  # blank — will be rejected
    batch = _make_batch(good, bad)
    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = batch

    with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
        result = await quiz_generator_node(_state(tier="T1"))

    # Partial success: 1 question kept even though T1 expects 3-5
    assert len(result["quiz_questions"]) == 1
    assert result["quiz_questions"][0]["data"]["question"] == "Only valid question?"


# ---------------------------------------------------------------------------
# AC 9: checkpoint shape change — old checkpoint is a cache-miss
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_quiz_batch_is_valid_shape_rejects_old_single_question_shape() -> None:
    """AC 9: the old {"segment_id": ..., "data": {...}} shape fails the new validator."""
    from app.modules.content.pipeline.graph import _quiz_batch_is_valid_shape  # type: ignore[attr-defined]

    old_shape = {
        "segment_id": "sec_1",
        "data": {
            "question_id": "quiz_sec_1",
            "type": "mcq",
            "question": "What is X?",
            "options": ["A", "B", "C", "D"],
            "correct_index": 0,
            "explanation": "Correct.",
            "difficulty": "medium",
        },
    }
    assert not _quiz_batch_is_valid_shape(old_shape)


@pytest.mark.unit
def test_quiz_batch_is_valid_shape_rejects_missing_questions_key() -> None:
    """AC 9 / Task 6.12: validator rejects dict without 'questions' key."""
    from app.modules.content.pipeline.graph import _quiz_batch_is_valid_shape  # type: ignore[attr-defined]

    assert not _quiz_batch_is_valid_shape({"segment_id": "sec_1"})
    assert not _quiz_batch_is_valid_shape({})


@pytest.mark.unit
def test_quiz_batch_is_valid_shape_rejects_empty_questions_list() -> None:
    """AC 9 / Task 6.13: validator rejects {"questions": []} (empty batch)."""
    from app.modules.content.pipeline.graph import _quiz_batch_is_valid_shape  # type: ignore[attr-defined]

    assert not _quiz_batch_is_valid_shape({"segment_id": "sec_1", "questions": []})


@pytest.mark.unit
def test_quiz_batch_is_valid_shape_accepts_valid_batch() -> None:
    """AC 9: validator accepts a properly-shaped batch checkpoint."""
    from app.modules.content.pipeline.graph import _quiz_batch_is_valid_shape  # type: ignore[attr-defined]

    valid_batch = {
        "segment_id": "sec_1",
        "questions": [
            {
                "segment_id": "sec_1",
                "data": {
                    "question_id": "quiz_sec_1_0",
                    "type": "mcq",
                    "question": "What is X?",
                    "options": ["A", "B", "C", "D"],
                    "correct_index": 0,
                    "explanation": "Correct.",
                    "difficulty": "medium",
                },
            }
        ],
    }
    assert _quiz_batch_is_valid_shape(valid_batch)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_batch_checkpoint_cache_hit_skips_llm_call() -> None:
    """AC 9: on a valid batch cache hit, the LLM is NOT called and all cached questions returned."""
    from app.modules.content.pipeline.graph import _derive_section_id, quiz_generator_node

    section_id = _derive_section_id(_SECTION_0, 0)
    cached_questions = [
        _valid_question_data(section_id, 0),
        _valid_question_data(section_id, 1),
    ]
    cached_batch = {
        "segment_id": section_id,
        "questions": cached_questions,
    }

    mock_jobs_table = MagicMock()
    mock_jobs_table.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {
        "node_outputs": {
            f"quiz_generator:{section_id}": cached_batch,
        }
    }
    mock_supabase = MagicMock()
    mock_supabase.table.return_value = mock_jobs_table
    mock_supabase.rpc.return_value.execute.return_value = MagicMock()

    mock_provider = AsyncMock()

    with (
        patch("app.core.db.get_supabase", return_value=mock_supabase),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        result = await quiz_generator_node(_state(tier="T1"))

    assert mock_provider.complete_structured.call_count == 0, "LLM must not be called on cache hit"
    assert len(result["quiz_questions"]) == 2
    assert result["quiz_questions"] == cached_questions


# ---------------------------------------------------------------------------
# AC 13 + 15: one LLM call; uses settings.llm_mini
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_exactly_one_llm_call_per_segment_regardless_of_tier() -> None:
    """AC 15: single LLM call per Send()-dispatch regardless of N_min/N_max."""
    from app.modules.content.pipeline.graph import quiz_generator_node

    batch = _make_batch(_make_q(), _make_q(question="Q2?"), _make_q(question="Q3?"))
    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = batch

    with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
        await quiz_generator_node(_state(tier="T1"))

    assert mock_provider.complete_structured.call_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_complete_structured_called_with_llm_mini_not_hardcoded_string() -> None:
    """AC 13: the second argument to complete_structured is settings.llm_mini."""
    from app.config import get_settings
    from app.modules.content.pipeline.graph import quiz_generator_node

    batch = _make_batch(_make_q(), _make_q(question="Q2?"))
    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = batch

    with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
        await quiz_generator_node(_state(tier="T2"))

    call_args = mock_provider.complete_structured.call_args
    assert call_args is not None
    _, model_arg, _ = call_args.args  # (messages, model, schema)
    settings = get_settings()
    assert model_arg == settings.llm_mini, (
        f"Expected settings.llm_mini ({settings.llm_mini!r}), got {model_arg!r}. "
        "Never hardcode the model string."
    )


# ---------------------------------------------------------------------------
# AC 14: unknown tier falls back to T2 band
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unknown_tier_falls_back_to_t2_band() -> None:
    """AC 14: state with tier='INVALID' falls back to T2 band (2-3 questions)."""
    from app.modules.content.pipeline.graph import quiz_generator_node

    # Mock returns 2 questions — within T2 band (2-3)
    batch = _make_batch(_make_q(), _make_q(question="Q2?"))
    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = batch

    with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
        result = await quiz_generator_node(_state(tier="INVALID_TIER"))

    # 2 valid questions returned (T2 fallback accepted them)
    assert len(result["quiz_questions"]) == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_missing_tier_falls_back_to_t2_band() -> None:
    """AC 14: state with no 'tier' key falls back to T2 (DEFAULT_TIER)."""
    from app.modules.content.pipeline.graph import quiz_generator_node

    batch = _make_batch(_make_q(), _make_q(question="Q2?"))
    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = batch

    with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
        result = await quiz_generator_node(_state())  # no tier key

    assert len(result["quiz_questions"]) == 2


# ---------------------------------------------------------------------------
# AC 5: all questions share the same segment_id in state output
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_all_questions_carry_correct_segment_id() -> None:
    """Each entry in quiz_questions must have segment_id == section_id."""
    from app.modules.content.pipeline.graph import _derive_section_id, quiz_generator_node

    section_id = _derive_section_id(_SECTION_0, 0)
    batch = _make_batch(_make_q(), _make_q(question="Q2?"))
    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = batch

    with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
        result = await quiz_generator_node(_state(tier="T2"))

    for entry in result["quiz_questions"]:
        assert entry["segment_id"] == section_id


# ---------------------------------------------------------------------------
# P1 patch: prompt system message contains tier-specific n_min/n_max values
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_t1_prompt_contains_tier_specific_n_min_n_max() -> None:
    """P1 patch: system message must contain 'Write 3 to 5' for T1 tier."""
    from app.modules.content.pipeline.graph import quiz_generator_node

    batch = _make_batch(_make_q(), _make_q(question="Q2?"), _make_q(question="Q3?"))
    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = batch

    with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
        await quiz_generator_node(_state(tier="T1"))

    call_args = mock_provider.complete_structured.call_args
    messages, *_ = call_args.args
    system_content = messages[0]["content"]
    assert "Write 3 to 5" in system_content, (
        f"T1 system prompt must contain 'Write 3 to 5', got: {system_content!r}"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_t2_prompt_contains_tier_specific_n_min_n_max() -> None:
    """P1 patch: system message must contain 'Write 2 to 3' for T2 tier."""
    from app.modules.content.pipeline.graph import quiz_generator_node

    batch = _make_batch(_make_q(), _make_q(question="Q2?"))
    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = batch

    with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
        await quiz_generator_node(_state(tier="T2"))

    call_args = mock_provider.complete_structured.call_args
    messages, *_ = call_args.args
    system_content = messages[0]["content"]
    assert "Write 2 to 3" in system_content, (
        f"T2 system prompt must contain 'Write 2 to 3', got: {system_content!r}"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_t3_prompt_contains_tier_specific_n_min_n_max() -> None:
    """P1 patch: system message must contain 'Write 1 to 2' for T3 tier."""
    from app.modules.content.pipeline.graph import quiz_generator_node

    batch = _make_batch(_make_q(question="Q1?"))
    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = batch

    with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
        await quiz_generator_node(_state(tier="T3"))

    call_args = mock_provider.complete_structured.call_args
    messages, *_ = call_args.args
    system_content = messages[0]["content"]
    assert "Write 1 to 2" in system_content, (
        f"T3 system prompt must contain 'Write 1 to 2', got: {system_content!r}"
    )


# ---------------------------------------------------------------------------
# P2 patch: n_max truncation — LLM over-supplying questions is capped at n_max
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_t1_nmax_truncation_discards_extra_questions() -> None:
    """P2 patch: T1 n_max=5; LLM returning 6 valid questions → only 5 kept."""
    from app.modules.content.pipeline.graph import quiz_generator_node

    batch = _make_batch(*[_make_q(question=f"Q{i}?") for i in range(6)])
    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = batch

    with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
        result = await quiz_generator_node(_state(tier="T1"))

    assert len(result["quiz_questions"]) == 5, (
        f"T1 n_max=5; 6 input questions should be truncated to 5, got {len(result['quiz_questions'])}"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_t2_nmax_truncation_discards_extra_questions() -> None:
    """P2 patch: T2 n_max=3; LLM returning 4 valid questions → only 3 kept."""
    from app.modules.content.pipeline.graph import quiz_generator_node

    batch = _make_batch(*[_make_q(question=f"Q{i}?") for i in range(4)])
    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = batch

    with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
        result = await quiz_generator_node(_state(tier="T2"))

    assert len(result["quiz_questions"]) == 3, (
        f"T2 n_max=3; 4 input questions should be truncated to 3, got {len(result['quiz_questions'])}"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_t3_nmax_truncation_discards_extra_questions() -> None:
    """P2 patch: T3 n_max=2; LLM returning 3 valid questions → only 2 kept."""
    from app.modules.content.pipeline.graph import quiz_generator_node

    batch = _make_batch(_make_q(), _make_q(question="Q2?"), _make_q(question="Q3?"))
    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = batch

    with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
        result = await quiz_generator_node(_state(tier="T3"))

    assert len(result["quiz_questions"]) == 2, (
        f"T3 n_max=2; 3 input questions should be truncated to 2, got {len(result['quiz_questions'])}"
    )


# ---------------------------------------------------------------------------
# P3 patch: AC-6 blank explanation guard
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_question_with_blank_explanation_is_rejected_from_batch() -> None:
    """P3 patch (AC 6): blank explanation text rejects that question; others kept."""
    from app.modules.content.pipeline.graph import quiz_generator_node

    good = _make_q(question="Good?")
    bad = _make_q(question="Blank explanation?", explanation="   ")
    batch = _make_batch(good, bad)
    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = batch

    with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
        result = await quiz_generator_node(_state(tier="T2"))

    assert len(result["quiz_questions"]) == 1
    assert result["quiz_questions"][0]["data"]["question"] == "Good?"


# ---------------------------------------------------------------------------
# P4 patch: AC-6 correct_index=4 after 5→4 option truncation is rejected
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_correct_index_invalidated_by_option_truncation_is_rejected() -> None:
    """P4 patch (AC 6): 5 options + correct_index=4 → truncate to 4 → index out of range → rejected.

    This tests the guard ordering: truncation (line 1929) before range check (line 1939).
    If order were swapped, correct_index=4 would pass the pre-truncation check and a
    dangling index would be written to the output.
    """
    from app.modules.content.pipeline.graph import quiz_generator_node

    q = _make_q(
        question="5opt correct at last?",
        options=["A", "B", "C", "D", "E"],
        correct_index=4,
    )
    batch = _make_batch(q)
    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = batch

    with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
        result = await quiz_generator_node(_state(tier="T3"))

    assert result["quiz_questions"] == [], (
        "A question with 5 options and correct_index=4 must be rejected after "
        "truncation to 4 options makes the index out of range."
    )


# ---------------------------------------------------------------------------
# P5 patch: AC-6 difficulty clamping to "medium"
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_invalid_difficulty_is_clamped_to_medium() -> None:
    """P5 patch (AC 6): difficulty not in ('easy','medium','hard') is clamped to 'medium'."""
    from app.modules.content.pipeline.graph import quiz_generator_node

    q = _make_q(question="What is the capital?", difficulty="genius")
    batch = _make_batch(q)
    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = batch

    with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
        result = await quiz_generator_node(_state(tier="T3"))

    assert len(result["quiz_questions"]) == 1
    assert result["quiz_questions"][0]["data"]["difficulty"] == "medium", (
        "An invalid difficulty value must be clamped to 'medium', not passed through."
    )
