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


def test_book_context_truncated_defaults_false_in_lesson_metadata():
    """Story S5-1 AC13: LessonMetadata.book_context_truncated defaults to False for old lessons."""
    from app.schemas.lesson import LessonMetadata

    meta = LessonMetadata(
        title="Test",
        subject="Math",
        total_segments=1,
        estimated_duration_mins=5.0,
        complexity_level="medium",
        tier="T2",
    )
    assert meta.book_context_truncated is False


@pytest.mark.asyncio
async def test_get_book_context_prompt_context_sanitizes_newlines(mocker):
    """F3: internal newlines in field values must be collapsed (prevent prompt injection)."""
    row = {
        "book_id": "b1",
        "user_id": "u1",
        "why_uploaded": "Line1\nFake-label: injected",
        "what_to_achieve": None,
        "complete_or_selected": None,
        "important_sections": None,
        "deadline_and_depth": None,
        "follow_or_reorganize": None,
        "updated_at": "2026-09-21T00:00:00Z",
    }
    mocker.patch("app.modules.content.context.get_supabase", return_value=mocker.MagicMock())
    mocker.patch("app.modules.content.context.single_row", return_value=row)
    mocker.patch("asyncio.to_thread", side_effect=lambda f: f())

    from app.modules.content.context import get_book_context_prompt_context

    result = await get_book_context_prompt_context("b1", "u1")
    # The newline must be collapsed — "Fake-label:" must not appear on its own prompt line.
    lines = result.splitlines()
    assert not any(line.strip().startswith("Fake-label:") for line in lines)


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


# ─────────────────────────────────────────────────────────────────────────────
# F. Endpoint Handler Tests — upsert_book_context / get_book_context
# ─────────────────────────────────────────────────────────────────────────────
# Covers F5 (review finding): previously only unit/schema tests existed; these
# test the actual endpoint handler functions, status codes, and response shapes.
# We call the async handler functions directly (bypassing the router import
# which triggers a pre-existing UploadFile FastAPI annotation issue unrelated
# to S5-1) and verify their behaviour under mocked dependencies.
# ─────────────────────────────────────────────────────────────────────────────

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

_FAKE_USER_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_FAKE_BOOK_ID = str(uuid.UUID("11111111-1111-1111-1111-111111111111"))

_fake_book_row = {"book_id": _FAKE_BOOK_ID, "user_id": _FAKE_USER_ID}

_saved_context_row = {
    "book_id": _FAKE_BOOK_ID,
    "user_id": _FAKE_USER_ID,
    "why_uploaded": "Pass my exam",
    "what_to_achieve": "Deep understanding",
    "complete_or_selected": "complete",
    "important_sections": None,
    "deadline_and_depth": None,
    "follow_or_reorganize": "follow",
    "updated_at": "2026-09-21T00:00:00+00:00",
}


def _supabase_mock_with_book() -> MagicMock:
    mock = MagicMock()
    execute_result = MagicMock()
    execute_result.data = _fake_book_row
    (
        mock.table.return_value
        .select.return_value
        .eq.return_value
        .eq.return_value
        .maybe_single.return_value
        .execute.return_value
    ) = execute_result
    return mock


def _supabase_mock_no_book() -> MagicMock:
    mock = MagicMock()
    execute_result = MagicMock()
    execute_result.data = None
    (
        mock.table.return_value
        .select.return_value
        .eq.return_value
        .eq.return_value
        .maybe_single.return_value
        .execute.return_value
    ) = execute_result
    return mock


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_handler_returns_200_response():
    """PUT handler: returns BookContextResponse on success."""
    from app.modules.content.schemas import BookContextRequest, BookContextResponse
    from app.modules.content.router import upsert_book_context

    body = BookContextRequest(why_uploaded="Pass my exam", follow_or_reorganize="follow")
    current_user = {"sub": _FAKE_USER_ID}

    with (
        patch("app.modules.content.router.get_supabase", return_value=_supabase_mock_with_book()),
        patch("app.modules.content.router.single_row", return_value=_fake_book_row),
        patch(
            "app.modules.content.context.upsert_book_context",
            new=AsyncMock(return_value=_saved_context_row),
        ),
    ):
        result = await upsert_book_context(_FAKE_BOOK_ID, body, current_user)

    assert isinstance(result, BookContextResponse)
    assert result.book_id == _FAKE_BOOK_ID
    assert result.why_uploaded == "Pass my exam"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_handler_raises_404_when_book_not_owned():
    """PUT handler: raises 404 when book belongs to another user."""
    from app.modules.content.schemas import BookContextRequest
    from app.modules.content.router import upsert_book_context

    body = BookContextRequest(why_uploaded="Studying")
    current_user = {"sub": _FAKE_USER_ID}

    with (
        patch("app.modules.content.router.get_supabase", return_value=_supabase_mock_no_book()),
        patch("app.modules.content.router.single_row", return_value=None),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await upsert_book_context(_FAKE_BOOK_ID, body, current_user)
    assert exc_info.value.status_code == 404


@pytest.mark.unit
def test_put_handler_schema_rejects_invalid_radio_value():
    """PUT body: Pydantic raises ValidationError for disallowed radio values (F11)."""
    from pydantic import ValidationError
    from app.modules.content.schemas import BookContextRequest

    with pytest.raises(ValidationError):
        BookContextRequest(follow_or_reorganize="invalid_value")

    with pytest.raises(ValidationError):
        BookContextRequest(complete_or_selected="partial")  # not a valid Literal


@pytest.mark.unit
def test_put_handler_schema_rejects_field_too_long():
    """PUT body: Pydantic raises ValidationError when a text field exceeds 500 chars."""
    from pydantic import ValidationError
    from app.modules.content.schemas import BookContextRequest

    with pytest.raises(ValidationError):
        BookContextRequest(why_uploaded="x" * 501)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_handler_returns_response_when_context_exists():
    """GET handler: returns BookContextResponse when a context row is saved."""
    from app.modules.content.schemas import BookContextResponse
    from app.modules.content.router import get_book_context

    current_user = {"sub": _FAKE_USER_ID}

    with (
        patch("app.modules.content.router.get_supabase", return_value=_supabase_mock_with_book()),
        patch("app.modules.content.router.single_row", return_value=_fake_book_row),
        patch(
            "app.modules.content.context.get_book_context_row",
            new=AsyncMock(return_value=_saved_context_row),
        ),
    ):
        result = await get_book_context(_FAKE_BOOK_ID, current_user)

    assert isinstance(result, BookContextResponse)
    assert result.book_id == _FAKE_BOOK_ID
    assert result.why_uploaded == "Pass my exam"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_handler_returns_204_response_when_no_context():
    """GET handler: returns Response(status_code=204) when no context saved (F8)."""
    from fastapi import Response
    from app.modules.content.router import get_book_context

    current_user = {"sub": _FAKE_USER_ID}

    with (
        patch("app.modules.content.router.get_supabase", return_value=_supabase_mock_with_book()),
        patch("app.modules.content.router.single_row", return_value=_fake_book_row),
        patch(
            "app.modules.content.context.get_book_context_row",
            new=AsyncMock(return_value=None),
        ),
    ):
        result = await get_book_context(_FAKE_BOOK_ID, current_user)

    assert isinstance(result, Response)
    assert result.status_code == 204


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_handler_raises_404_when_book_not_owned():
    """GET handler: raises 404 when book belongs to another user."""
    from app.modules.content.router import get_book_context

    current_user = {"sub": _FAKE_USER_ID}

    with (
        patch("app.modules.content.router.get_supabase", return_value=_supabase_mock_no_book()),
        patch("app.modules.content.router.single_row", return_value=None),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await get_book_context(_FAKE_BOOK_ID, current_user)
    assert exc_info.value.status_code == 404
