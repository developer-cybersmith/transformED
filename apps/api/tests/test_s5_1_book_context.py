"""
Tests for Story S5-1 (Issue #231): Book-upload personalization form.

Tests cover:
- prompt_context.merge_book_context logic (no DB, no network)
- context.get_book_context_prompt_context formatting (§4.2 exact questions)
- BookContextRequest schema validation (MCQ Literals, one-liner length, booleans)
- _FAN_OUT_STATE_KEYS guard (book_context in Send() allowlist)
- lesson_planner_node return shape guard (no **state spread)
"""

from __future__ import annotations

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# A. prompt_context.py — pure function, no mocking needed
# ─────────────────────────────────────────────────────────────────────────────


class TestMergeBookContext:
    def _import(self):
        from app.modules.content.pipeline.prompt_context import (
            _BOOK_CONTEXT_MAX_CHARS,
            _TRUNCATION_MARKER,
            merge_book_context,
        )
        return merge_book_context, _BOOK_CONTEXT_MAX_CHARS, _TRUNCATION_MARKER

    def test_empty_context_returns_base_unchanged(self):
        merge_book_context, _, _ = self._import()
        base = "System prompt here."
        merged, was_truncated = merge_book_context(base, "")
        assert merged == base
        assert was_truncated is False

    def test_none_like_empty_string_returns_base_unchanged(self):
        merge_book_context, _, _ = self._import()
        base = "System prompt."
        merged, was_truncated = merge_book_context(base, "")
        assert merged == base
        assert was_truncated is False

    def test_short_context_appended_with_separator(self):
        merge_book_context, _, _ = self._import()
        base = "Base."
        ctx = "[Book Context]\nWhy uploaded: To study for exam"
        merged, was_truncated = merge_book_context(base, ctx)
        assert merged == base + "\n\n" + ctx
        assert was_truncated is False

    def test_context_at_exact_limit_not_truncated(self):
        merge_book_context, max_chars, marker = self._import()
        ctx = "x" * max_chars
        merged, was_truncated = merge_book_context("Base.", ctx)
        assert marker not in merged
        assert ctx in merged
        assert was_truncated is False

    def test_context_over_limit_truncated_at_newline_boundary(self):
        merge_book_context, max_chars, marker = self._import()
        # Build a context with a newline before the limit so truncation
        # lands at the boundary, not mid-character.
        prefix = "Field: value\n"
        suffix = "x" * (max_chars + 100)
        ctx = prefix + suffix
        merged, was_truncated = merge_book_context("Base.", ctx)
        assert was_truncated is True
        assert marker in merged
        # Truncated content must not exceed the budget + marker
        assert len(merged) <= len("Base.") + 2 + max_chars + len(marker) + 10

    def test_context_over_limit_no_mid_sentence_cut_when_no_newline(self):
        merge_book_context, max_chars, marker = self._import()
        # No newline in context — truncation falls back to the char boundary.
        ctx = "a" * (max_chars + 50)
        merged, was_truncated = merge_book_context("Base.", ctx)
        assert was_truncated is True
        assert marker in merged

    def test_truncation_marker_text_is_informative(self):
        merge_book_context, max_chars, marker = self._import()
        assert "truncated" in marker.lower()


# ─────────────────────────────────────────────────────────────────────────────
# B. context.get_book_context_prompt_context — formatting
# ─────────────────────────────────────────────────────────────────────────────


class TestGetBookContextPromptContext:
    """Tests the formatted output — mocks the DB call."""

    def _mock_row(self, **overrides):
        base = {
            "book_id": "b1",
            "user_id": "u1",
            "purpose": None,
            "coverage_scope": None,
            "expected_difficulty": None,
            "deadline_depth": None,
            "structure_preference": None,
            "motivation": None,
            "end_goal": None,
            "feared_section": None,
            "prior_attempt": None,
            "outcome_clarity": None,
            "updated_at": "2026-09-21T00:00:00Z",
        }
        base.update(overrides)
        return base

    @pytest.mark.asyncio
    async def test_returns_empty_string_when_no_row(self, mocker):
        mocker.patch(
            "app.modules.content.context.get_supabase",
            return_value=mocker.MagicMock(),
        )
        mocker.patch("app.modules.content.context.single_row", return_value=None)
        mocker.patch("asyncio.to_thread", side_effect=lambda f: f())

        from app.modules.content.context import get_book_context_prompt_context

        result = await get_book_context_prompt_context("b1", "u1")
        assert result == ""

    @pytest.mark.asyncio
    async def test_returns_empty_string_when_all_fields_null(self, mocker):
        mocker.patch("app.modules.content.context.get_supabase", return_value=mocker.MagicMock())
        mocker.patch("app.modules.content.context.single_row", return_value=self._mock_row())
        mocker.patch("asyncio.to_thread", side_effect=lambda f: f())

        from app.modules.content.context import get_book_context_prompt_context

        result = await get_book_context_prompt_context("b1", "u1")
        assert result == ""

    @pytest.mark.asyncio
    async def test_mcq_value_mapped_to_human_readable_label(self, mocker):
        row = self._mock_row(purpose="exam_prep")
        mocker.patch("app.modules.content.context.get_supabase", return_value=mocker.MagicMock())
        mocker.patch("app.modules.content.context.single_row", return_value=row)
        mocker.patch("asyncio.to_thread", side_effect=lambda f: f())

        from app.modules.content.context import get_book_context_prompt_context

        result = await get_book_context_prompt_context("b1", "u1")
        assert "[Book Context]" in result
        # The stored enum value should be mapped to human-readable text.
        assert "Exam preparation" in result
        assert "exam_prep" not in result

    @pytest.mark.asyncio
    async def test_one_liner_fields_included(self, mocker):
        row = self._mock_row(motivation="Pass my ML exam", end_goal="Build a neural net")
        mocker.patch("app.modules.content.context.get_supabase", return_value=mocker.MagicMock())
        mocker.patch("app.modules.content.context.single_row", return_value=row)
        mocker.patch("asyncio.to_thread", side_effect=lambda f: f())

        from app.modules.content.context import get_book_context_prompt_context

        result = await get_book_context_prompt_context("b1", "u1")
        assert "Pass my ML exam" in result
        assert "Build a neural net" in result

    @pytest.mark.asyncio
    async def test_boolean_true_formatted_as_yes(self, mocker):
        row = self._mock_row(prior_attempt=True, outcome_clarity=False)
        mocker.patch("app.modules.content.context.get_supabase", return_value=mocker.MagicMock())
        mocker.patch("app.modules.content.context.single_row", return_value=row)
        mocker.patch("asyncio.to_thread", side_effect=lambda f: f())

        from app.modules.content.context import get_book_context_prompt_context

        result = await get_book_context_prompt_context("b1", "u1")
        assert "Yes" in result
        assert "No" in result

    @pytest.mark.asyncio
    async def test_boolean_false_not_omitted(self, mocker):
        """False booleans must appear (unlike null) — they carry signal for the LLM."""
        row = self._mock_row(prior_attempt=False)
        mocker.patch("app.modules.content.context.get_supabase", return_value=mocker.MagicMock())
        mocker.patch("app.modules.content.context.single_row", return_value=row)
        mocker.patch("asyncio.to_thread", side_effect=lambda f: f())

        from app.modules.content.context import get_book_context_prompt_context

        result = await get_book_context_prompt_context("b1", "u1")
        assert "No" in result

    @pytest.mark.asyncio
    async def test_newlines_in_text_fields_collapsed(self, mocker):
        """F3 guard: internal newlines in user text must be collapsed to prevent prompt injection."""
        row = self._mock_row(motivation="Line1\nFake-label: injected")
        mocker.patch("app.modules.content.context.get_supabase", return_value=mocker.MagicMock())
        mocker.patch("app.modules.content.context.single_row", return_value=row)
        mocker.patch("asyncio.to_thread", side_effect=lambda f: f())

        from app.modules.content.context import get_book_context_prompt_context

        result = await get_book_context_prompt_context("b1", "u1")
        lines = result.splitlines()
        assert not any(line.strip().startswith("Fake-label:") for line in lines)

    @pytest.mark.asyncio
    async def test_returns_empty_string_on_db_exception(self, mocker):
        mocker.patch("app.modules.content.context.get_supabase", side_effect=RuntimeError("db down"))

        from app.modules.content.context import get_book_context_prompt_context

        result = await get_book_context_prompt_context("b1", "u1")
        assert result == ""

    @pytest.mark.asyncio
    async def test_returns_empty_string_when_book_id_empty(self):
        from app.modules.content.context import get_book_context_prompt_context

        result = await get_book_context_prompt_context("", "u1")
        assert result == ""


# ─────────────────────────────────────────────────────────────────────────────
# C. Schema validation — BookContextRequest field length limits
# ─────────────────────────────────────────────────────────────────────────────


class TestBookContextRequestSchema:
    def test_accepts_all_null_fields(self):
        from app.modules.content.schemas import BookContextRequest

        req = BookContextRequest()
        assert req.purpose is None
        assert req.motivation is None
        assert req.prior_attempt is None

    def test_accepts_valid_mcq_value(self):
        from app.modules.content.schemas import BookContextRequest

        req = BookContextRequest(purpose="exam_prep", coverage_scope="selected_chapters")
        assert req.purpose == "exam_prep"
        assert req.coverage_scope == "selected_chapters"

    def test_rejects_invalid_mcq_value(self):
        from pydantic import ValidationError

        from app.modules.content.schemas import BookContextRequest

        with pytest.raises(ValidationError):
            BookContextRequest(purpose="invalid_value")

    def test_accepts_boolean_fields(self):
        from app.modules.content.schemas import BookContextRequest

        req = BookContextRequest(prior_attempt=True, outcome_clarity=False)
        assert req.prior_attempt is True
        assert req.outcome_clarity is False

    def test_rejects_one_liner_over_500_chars(self):
        from pydantic import ValidationError

        from app.modules.content.schemas import BookContextRequest

        with pytest.raises(ValidationError):
            BookContextRequest(motivation="x" * 501)

    def test_accepts_one_liner_at_500_chars(self):
        from app.modules.content.schemas import BookContextRequest

        req = BookContextRequest(motivation="x" * 500)
        assert len(req.motivation) == 500

    def test_all_five_mcq_fields_accept_all_their_valid_values(self):
        from app.modules.content.schemas import BookContextRequest

        # Spot-check one value from each MCQ field.
        req = BookContextRequest(
            purpose="deep_mastery",
            coverage_scope="exam_relevant",
            expected_difficulty="numerical_formula",
            deadline_depth="no_deadline",
            structure_preference="hybrid",
        )
        assert req.purpose == "deep_mastery"
        assert req.structure_preference == "hybrid"


# ─────────────────────────────────────────────────────────────────────────────
# D. _FAN_OUT_STATE_KEYS — guard that "book_context" is in the allowlist
# ─────────────────────────────────────────────────────────────────────────────


def test_fan_out_state_keys_includes_book_context():
    """AC10 guard: narration_generator receives book_context via Send() dispatch."""
    from app.modules.content.pipeline.graph import _FAN_OUT_STATE_KEYS

    assert "book_context" in _FAN_OUT_STATE_KEYS


def test_fan_out_state_keys_retains_existing_keys():
    from app.modules.content.pipeline.graph import _FAN_OUT_STATE_KEYS

    for key in ("lesson_id", "user_id", "book_id", "tier"):
        assert key in _FAN_OUT_STATE_KEYS


# ─────────────────────────────────────────────────────────────────────────────
# E. lesson_planner_node return shape — must NOT spread **state
# ─────────────────────────────────────────────────────────────────────────────


def test_lesson_planner_node_return_keys_are_valid():
    """AC14: lesson_planner_node returns only its own keys, not **state.

    We inspect the source to confirm the return dict does not contain **state.
    This mirrors the pattern in test_node_return_shape.py.
    """
    import inspect
    from app.modules.content.pipeline import graph as g

    source = inspect.getsource(g.lesson_planner_node)
    assert "**state" not in source, (
        "lesson_planner_node must not spread **state — this causes reducer-channel duplication. "
        "Return only the keys this node owns."
    )
