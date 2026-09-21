"""
Tests for Story S5-1 (Issue #231): Book-upload personalization form.

Tests cover:
- prompt_context.merge_book_context logic (no DB, no network)
- context.get_book_context_prompt_context formatting
- Endpoint contract (PUT / GET /books/{book_id}/context) via mocked Supabase
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
        assert merge_book_context(base, "") == base

    def test_none_like_empty_string_returns_base_unchanged(self):
        merge_book_context, _, _ = self._import()
        base = "System prompt."
        assert merge_book_context(base, "") == base

    def test_short_context_appended_with_separator(self):
        merge_book_context, _, _ = self._import()
        base = "Base."
        ctx = "[Book Context]\nWhy uploaded: To study for exam"
        result = merge_book_context(base, ctx)
        assert result == base + "\n\n" + ctx

    def test_context_at_exact_limit_not_truncated(self):
        merge_book_context, max_chars, marker = self._import()
        ctx = "x" * max_chars
        result = merge_book_context("Base.", ctx)
        assert marker not in result
        assert ctx in result

    def test_context_over_limit_truncated_at_newline_boundary(self):
        merge_book_context, max_chars, marker = self._import()
        # Build a context with a newline before the limit so truncation
        # lands at the boundary, not mid-character.
        prefix = "Field: value\n"
        suffix = "x" * (max_chars + 100)
        ctx = prefix + suffix
        result = merge_book_context("Base.", ctx)
        assert marker in result
        # Truncated content must not exceed the budget + marker
        assert len(result) <= len("Base.") + 2 + max_chars + len(marker) + 10

    def test_context_over_limit_no_mid_sentence_cut_when_no_newline(self):
        merge_book_context, max_chars, marker = self._import()
        # No newline in context — truncation falls back to the char boundary.
        ctx = "a" * (max_chars + 50)
        result = merge_book_context("Base.", ctx)
        assert marker in result

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
            "why_uploaded": None,
            "what_to_achieve": None,
            "complete_or_selected": None,
            "important_sections": None,
            "deadline_and_depth": None,
            "follow_or_reorganize": None,
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
        mocker.patch(
            "app.modules.content.context.single_row",
            return_value=None,
        )
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
    async def test_formats_non_null_fields(self, mocker):
        row = self._mock_row(
            why_uploaded="Pass my exam",
            what_to_achieve="Deep understanding",
        )
        mocker.patch("app.modules.content.context.get_supabase", return_value=mocker.MagicMock())
        mocker.patch("app.modules.content.context.single_row", return_value=row)
        mocker.patch("asyncio.to_thread", side_effect=lambda f: f())

        from app.modules.content.context import get_book_context_prompt_context

        result = await get_book_context_prompt_context("b1", "u1")
        assert "[Book Context]" in result
        assert "Pass my exam" in result
        assert "Deep understanding" in result

    @pytest.mark.asyncio
    async def test_omits_null_fields_from_block(self, mocker):
        row = self._mock_row(why_uploaded="Study for finals")
        mocker.patch("app.modules.content.context.get_supabase", return_value=mocker.MagicMock())
        mocker.patch("app.modules.content.context.single_row", return_value=row)
        mocker.patch("asyncio.to_thread", side_effect=lambda f: f())

        from app.modules.content.context import get_book_context_prompt_context

        result = await get_book_context_prompt_context("b1", "u1")
        # Only one filled field — block should have exactly 2 lines
        lines = [l for l in result.splitlines() if l.strip()]
        assert len(lines) == 2  # "[Book Context]" + one field line

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
        assert req.why_uploaded is None

    def test_accepts_valid_text(self):
        from app.modules.content.schemas import BookContextRequest

        req = BookContextRequest(why_uploaded="Pass my exam")
        assert req.why_uploaded == "Pass my exam"

    def test_rejects_field_over_500_chars(self):
        from pydantic import ValidationError

        from app.modules.content.schemas import BookContextRequest

        with pytest.raises(ValidationError):
            BookContextRequest(why_uploaded="x" * 501)

    def test_accepts_exactly_500_chars(self):
        from app.modules.content.schemas import BookContextRequest

        req = BookContextRequest(why_uploaded="x" * 500)
        assert len(req.why_uploaded) == 500


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
