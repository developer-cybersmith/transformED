"""Tests for S5-3: Chapter Context Form (§4.3 — 5 questions per session).

Covers:
- Schema validation: MCQ Literal types reject invalid values, 500-char text cap
- Prompt block formatting: all-None → empty string, partial row, injection guards
- MCQ display: stored enum → human-readable label
- Boolean False emits "No" (not omitted)
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.content.schemas import ChapterContextRequest
from app.modules.content.context_chapter import (
    _format_chapter_context_block,
    _DEPTH_DISPLAY,
    _LEARNING_NEED_DISPLAY,
)


class TestChapterContextRequestSchema:
    """AC8: Pydantic schema validation for ChapterContextRequest."""

    def test_all_none_is_valid(self) -> None:
        req = ChapterContextRequest()
        assert req.depth_duration is None
        assert req.learning_need is None
        assert req.specific_doubt is None
        assert req.goal_and_skip is None
        assert req.prerequisites_done is None

    def test_valid_depth_duration_values(self) -> None:
        for val in ("quick_15_20m", "standard_30_45m", "deep_60_90m", "mastery_multi", "ai_decide"):
            req = ChapterContextRequest(depth_duration=val)
            assert req.depth_duration == val

    def test_invalid_depth_duration_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ChapterContextRequest(depth_duration="invalid_value")

    def test_valid_learning_need_values(self) -> None:
        for val in ("examples_analogies", "formulas_derivations", "diagrams_visuals", "practice_questions", "adaptive_mix"):
            req = ChapterContextRequest(learning_need=val)
            assert req.learning_need == val

    def test_invalid_learning_need_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ChapterContextRequest(learning_need="anything_else")

    def test_text_field_max_length_enforced(self) -> None:
        with pytest.raises(ValidationError):
            ChapterContextRequest(specific_doubt="x" * 501)

    def test_text_field_max_length_boundary_ok(self) -> None:
        req = ChapterContextRequest(specific_doubt="x" * 500)
        assert req.specific_doubt == "x" * 500

    def test_goal_and_skip_max_length_enforced(self) -> None:
        with pytest.raises(ValidationError):
            ChapterContextRequest(goal_and_skip="y" * 501)


class TestChapterContextPromptBlock:
    """AC4: _format_chapter_context_block formatting correctness."""

    def test_all_none_returns_empty_string(self) -> None:
        block = _format_chapter_context_block(
            depth_duration=None,
            learning_need=None,
            specific_doubt=None,
            goal_and_skip=None,
            prerequisites_done=None,
        )
        assert block == ""

    def test_partial_row_includes_only_set_fields(self) -> None:
        block = _format_chapter_context_block(
            depth_duration="standard_30_45m",
            learning_need=None,
            specific_doubt="Why does the chain rule work?",
            goal_and_skip=None,
            prerequisites_done=None,
        )
        assert "[Chapter Instructions]" in block
        assert "standard" in block.lower() or "30" in block  # human-readable label
        assert "Why does the chain rule work?" in block
        # None fields must NOT appear
        assert "Primary learning need" not in block
        assert "Goal and skip" not in block
        assert "Prerequisites" not in block

    def test_false_prerequisites_emits_no(self) -> None:
        """AC: False carries signal (student hasn't done prerequisites). Must NOT be omitted."""
        block = _format_chapter_context_block(
            depth_duration=None,
            learning_need=None,
            specific_doubt=None,
            goal_and_skip=None,
            prerequisites_done=False,
        )
        assert "No" in block

    def test_true_prerequisites_emits_yes(self) -> None:
        block = _format_chapter_context_block(
            depth_duration=None,
            learning_need=None,
            specific_doubt=None,
            goal_and_skip=None,
            prerequisites_done=True,
        )
        assert "Yes" in block

    def test_newline_injection_collapsed_in_specific_doubt(self) -> None:
        """AC6: internal newlines collapsed to spaces to prevent prompt injection."""
        block = _format_chapter_context_block(
            depth_duration=None,
            learning_need=None,
            specific_doubt="First line\nSecond line\r\nThird",
            goal_and_skip=None,
            prerequisites_done=None,
        )
        assert "\n" not in block.split("[Chapter Instructions]")[1].split("Specific doubt:")[1].split("\n")[0]
        # The value must be in a single line
        assert "First line Second line" in block or "First line\n" not in block

    def test_newline_injection_collapsed_in_goal_and_skip(self) -> None:
        block = _format_chapter_context_block(
            depth_duration=None,
            learning_need=None,
            specific_doubt=None,
            goal_and_skip="Understand integrals\nSkip: series expansion",
            prerequisites_done=None,
        )
        # After "Goal and skip:" the value must be single-line
        assert "Understand integrals Skip: series expansion" in block or \
               "Understand integrals\nSkip" not in block

    def test_mcq_display_mapping_depth(self) -> None:
        """AC5: stored enum values mapped to human-readable labels in prompt."""
        block = _format_chapter_context_block(
            depth_duration="examples_analogies" if False else "standard_30_45m",
            learning_need=None,
            specific_doubt=None,
            goal_and_skip=None,
            prerequisites_done=None,
        )
        # Should NOT contain the raw enum string
        assert "standard_30_45m" not in block
        # Should contain a readable label
        readable = _DEPTH_DISPLAY["standard_30_45m"]
        assert readable in block

    def test_mcq_display_mapping_learning_need(self) -> None:
        block = _format_chapter_context_block(
            depth_duration=None,
            learning_need="examples_analogies",
            specific_doubt=None,
            goal_and_skip=None,
            prerequisites_done=None,
        )
        assert "examples_analogies" not in block
        readable = _LEARNING_NEED_DISPLAY["examples_analogies"]
        assert readable in block

    def test_full_row_block_structure(self) -> None:
        """All 5 fields set → block has header and all 5 lines."""
        block = _format_chapter_context_block(
            depth_duration="deep_60_90m",
            learning_need="formulas_derivations",
            specific_doubt="What is divergence?",
            goal_and_skip="Explain Maxwell. Skip: history.",
            prerequisites_done=True,
        )
        assert "[Chapter Instructions]" in block
        assert "Depth and time" in block
        assert "Primary learning need" in block
        assert "Specific doubt" in block
        assert "Goal and skip" in block
        assert "Prerequisites completed" in block
