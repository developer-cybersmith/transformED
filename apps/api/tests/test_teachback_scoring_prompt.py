"""Unit tests for the teach-back rubric prompt module.
All tests are @pytest.mark.unit — no real OpenAI API key required.
"""
from __future__ import annotations

import ast
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.modules.assessment.prompts import (
    TEACHBACK_SYSTEM_PROMPT,
    TeachbackScoreResult,
    build_teachback_user_prompt,
    score_teachback,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LLM_MINI = Settings.model_fields["llm_mini"].default  # avoids hardcoding "gpt-4o-mini"

def _mock_provider(return_value: TeachbackScoreResult) -> MagicMock:
    p = MagicMock()
    p.complete_structured = AsyncMock(return_value=return_value)
    return p

def _good_result(**overrides: object) -> TeachbackScoreResult:
    defaults = dict(
        score=75,
        praise="Good explanation of the main concepts.",
        correction="You could expand on the feedback loop mechanism.",
        concepts_hit=["photosynthesis"],
        concepts_missed=["ATP synthesis"],
    )
    defaults.update(overrides)
    return TeachbackScoreResult(**defaults)


# ---------------------------------------------------------------------------
# Model field tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_model_has_five_fields() -> None:
    fields = set(TeachbackScoreResult.model_fields.keys())
    assert fields == {"score", "praise", "correction", "concepts_hit", "concepts_missed"}

@pytest.mark.unit
def test_score_range_rejects_above_100() -> None:
    with pytest.raises(Exception):
        TeachbackScoreResult(score=101, praise="", correction="", concepts_hit=[], concepts_missed=[])

@pytest.mark.unit
def test_score_range_rejects_below_0() -> None:
    with pytest.raises(Exception):
        TeachbackScoreResult(score=-1, praise="", correction="", concepts_hit=[], concepts_missed=[])

@pytest.mark.unit
def test_concepts_fields_are_lists() -> None:
    r = _good_result()
    assert isinstance(r.concepts_hit, list)
    assert isinstance(r.concepts_missed, list)

@pytest.mark.unit
def test_score_boundary_0_is_valid() -> None:
    r = TeachbackScoreResult(score=0, praise="", correction="Missed everything.", concepts_hit=[], concepts_missed=["concept"])
    assert r.score == 0

@pytest.mark.unit
def test_score_boundary_100_is_valid() -> None:
    r = TeachbackScoreResult(score=100, praise="Excellent!", correction="", concepts_hit=["concept"], concepts_missed=[])
    assert r.score == 100

@pytest.mark.unit
def test_model_validator_clears_correction_when_score_gte_90() -> None:
    r = TeachbackScoreResult(score=92, praise="Great!", correction="This should be cleared.", concepts_hit=["concept"], concepts_missed=[])
    assert r.correction == "", f"Expected empty string, got {r.correction!r}"

@pytest.mark.unit
def test_model_validator_clears_correction_at_exact_boundary_90() -> None:
    r = TeachbackScoreResult(score=90, praise="Excellent!", correction="Should be cleared at boundary.", concepts_hit=["concept"], concepts_missed=[])
    assert r.correction == "", f"score=90 should clear correction, got {r.correction!r}"

@pytest.mark.unit
def test_model_validator_retains_correction_below_boundary_89() -> None:
    r = TeachbackScoreResult(score=89, praise="Good.", correction="Expand on the mechanism.", concepts_hit=["concept"], concepts_missed=["detail"])
    assert r.correction == "Expand on the mechanism.", f"score=89 must NOT clear correction, got {r.correction!r}"

# ---------------------------------------------------------------------------
# User prompt builder tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_user_prompt_contains_topic() -> None:
    p = build_teachback_user_prompt(topic="Photosynthesis", key_concepts=[], response_text="test")
    assert "Photosynthesis" in p

@pytest.mark.unit
def test_user_prompt_contains_all_key_concepts() -> None:
    p = build_teachback_user_prompt(
        topic="Biology",
        key_concepts=["chlorophyll", "ATP synthesis", "light reaction"],
        response_text="test",
    )
    assert "chlorophyll" in p
    assert "ATP synthesis" in p
    assert "light reaction" in p

@pytest.mark.unit
def test_user_prompt_contains_response_text() -> None:
    p = build_teachback_user_prompt(topic="Topic", key_concepts=[], response_text="Student wrote this.")
    assert "Student wrote this." in p

@pytest.mark.unit
def test_user_prompt_handles_empty_key_concepts() -> None:
    p = build_teachback_user_prompt(topic="Topic", key_concepts=[], response_text="Response.")
    assert "Topic" in p
    assert "(no key concepts specified)" in p

# ---------------------------------------------------------------------------
# System prompt content tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_system_prompt_has_accuracy_weight() -> None:
    assert "40%" in TEACHBACK_SYSTEM_PROMPT or "0.40" in TEACHBACK_SYSTEM_PROMPT

@pytest.mark.unit
def test_system_prompt_has_completeness_weight() -> None:
    assert "35%" in TEACHBACK_SYSTEM_PROMPT or "0.35" in TEACHBACK_SYSTEM_PROMPT

@pytest.mark.unit
def test_system_prompt_has_clarity_weight() -> None:
    assert "25%" in TEACHBACK_SYSTEM_PROMPT or "0.25" in TEACHBACK_SYSTEM_PROMPT

@pytest.mark.unit
def test_system_prompt_specifies_empty_correction_rule() -> None:
    assert '""' in TEACHBACK_SYSTEM_PROMPT or "empty string" in TEACHBACK_SYSTEM_PROMPT.lower()

@pytest.mark.unit
def test_system_prompt_no_iq_eq_sq_language() -> None:
    # Check for full banned phrases — avoid bare "iq" which false-positives on "technique"
    banned = ["iq score", "eq score", "intelligence quotient", "emotional quotient", "social quotient"]
    lower = TEACHBACK_SYSTEM_PROMPT.lower()
    for term in banned:
        assert term not in lower, f"Banned term '{term}' in system prompt"
    # Also guard against standalone " iq " (with spaces) to avoid false positives on "technique"
    import re
    assert not re.search(r"\biq\b", lower), "Standalone 'IQ' abbreviation found in system prompt"

# ---------------------------------------------------------------------------
# score_teachback() behaviour tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
async def test_score_teachback_calls_complete_structured_not_complete() -> None:
    expected = _good_result()
    provider = _mock_provider(expected)
    mock_settings = MagicMock()
    mock_settings.llm_mini = _LLM_MINI

    with patch("app.modules.assessment.prompts.get_settings", return_value=mock_settings):
        result = await score_teachback(
            topic="Photosynthesis",
            key_concepts=["chlorophyll"],
            response_text="Plants use sunlight.",
            provider=provider,
        )

    provider.complete_structured.assert_called_once()
    provider.complete.assert_not_called()
    assert result == expected

@pytest.mark.unit
async def test_score_teachback_uses_llm_mini_not_hardcoded_string() -> None:
    provider = _mock_provider(_good_result())
    mock_settings = MagicMock()
    mock_settings.llm_mini = _LLM_MINI

    with patch("app.modules.assessment.prompts.get_settings", return_value=mock_settings):
        await score_teachback(
            topic="Topic",
            key_concepts=[],
            response_text="Response.",
            provider=provider,
        )

    call_kwargs = provider.complete_structured.call_args.kwargs
    assert call_kwargs["model"] == _LLM_MINI, f"Expected {_LLM_MINI!r}, got {call_kwargs['model']!r}"

@pytest.mark.unit
async def test_score_teachback_passes_response_format() -> None:
    provider = _mock_provider(_good_result())
    mock_settings = MagicMock()
    mock_settings.llm_mini = _LLM_MINI

    with patch("app.modules.assessment.prompts.get_settings", return_value=mock_settings):
        await score_teachback(
            topic="Topic",
            key_concepts=[],
            response_text="Response.",
            provider=provider,
        )

    call_kwargs = provider.complete_structured.call_args.kwargs
    assert call_kwargs["response_format"] is TeachbackScoreResult

@pytest.mark.unit
async def test_score_teachback_messages_have_system_and_user_turns() -> None:
    provider = _mock_provider(_good_result())
    mock_settings = MagicMock()
    mock_settings.llm_mini = _LLM_MINI

    with patch("app.modules.assessment.prompts.get_settings", return_value=mock_settings):
        await score_teachback(
            topic="Topic",
            key_concepts=["concept"],
            response_text="My response.",
            provider=provider,
        )

    messages = provider.complete_structured.call_args.kwargs["messages"]
    roles = [m["role"] for m in messages]
    assert "system" in roles
    assert "user" in roles

@pytest.mark.unit
def test_no_asyncopenai_direct_import_in_prompts_module() -> None:
    # Resolve path relative to this test file (tests/ -> apps/api/ -> app/modules/assessment/)
    prompts_path = pathlib.Path(__file__).parent.parent / "app" / "modules" / "assessment" / "prompts.py"
    source = prompts_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "openai":
                for alias in node.names:
                    assert alias.name != "AsyncOpenAI", "Direct AsyncOpenAI import found — BANNED per CLAUDE.md"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "openai", f"Direct 'import openai' found — use provider abstraction"
