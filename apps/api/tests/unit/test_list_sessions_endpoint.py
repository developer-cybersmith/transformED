"""Story 2-58 (BR-7) — GET /assessment/sessions, backing the /reports index page.

`Sidebar.tsx`'s "Reports" nav link has pointed at `/reports` since the sidebar
was first built, with no backend list and no index route behind it (404 from
the beginning). This is the read that closes that gap.

Covers: ownership scoping (Scale & Load Q3 — never another user's rows via
this query), the row cap (Q2 — `_SESSION_LIST_LIMIT`), and the response
shape (`_session_row_to_summary`'s mapping, including the embedded
`lessons(title, tier)` PostgREST resource and its defensive tier fallback).
All external dependencies (Supabase) are mocked — no real network/DB call
anywhere in this file, same convention as `test_tutor_question_endpoint.py`
for this module.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.dependencies import get_current_user
from app.modules.assessment.router import router
from app.modules.assessment.schemas import SessionSummary
from app.modules.assessment.service import _SESSION_LIST_LIMIT, list_sessions

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _mock_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace asyncio.to_thread with a synchronous shim (matches
    test_tutor_question_endpoint.py's established pattern for this module)."""

    async def _sync_shim(func, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        return func(*args, **kwargs)

    monkeypatch.setattr("app.modules.assessment.service.asyncio.to_thread", _sync_shim)


def _chain_mock(rows: list[dict]) -> MagicMock:
    """A `supabase.table("sessions").select(...).eq(...).order(...).limit(...)`
    chain whose `.execute().data` is *rows* — each fluent call returns a
    distinct, independently-assertable MagicMock so a test can check exactly
    which arguments reached `.eq()`/`.order()`/`.limit()`."""
    supabase = MagicMock()
    select_call = supabase.table.return_value.select
    eq_call = select_call.return_value.eq
    order_call = eq_call.return_value.order
    limit_call = order_call.return_value.limit
    limit_call.return_value.execute.return_value.data = rows
    return supabase


_ROW_ANSWERED = {
    "session_id": "sess-001",
    "lesson_id": "lesson-001",
    "ces_final": 82.5,
    "started_at": "2026-09-01T10:00:00+00:00",
    "ended_at": "2026-09-01T10:20:00+00:00",
    "lessons": {"title": "Photosynthesis", "tier": "T1"},
}

_ROW_IN_PROGRESS = {
    "session_id": "sess-002",
    "lesson_id": "lesson-002",
    "ces_final": None,
    "started_at": "2026-09-02T09:00:00+00:00",
    "ended_at": None,
    "lessons": {"title": "Cell Division", "tier": "T3"},
}


# ── Ownership scoping (Scale & Load Q3) ─────────────────────────────────────────


async def test_scopes_the_query_to_the_calling_users_own_id() -> None:
    """The service-role Supabase client bypasses RLS — ownership must be an
    explicit `.eq("user_id", ...)` in the query itself, same pattern
    `get_session_report` already uses for a single session."""
    supabase = _chain_mock([_ROW_ANSWERED])

    await list_sessions(user_id="user-001", supabase=supabase)

    supabase.table.return_value.select.return_value.eq.assert_called_once_with(
        "user_id", "user-001"
    )


async def test_never_returns_another_users_row_even_if_the_mock_would_allow_it() -> None:
    """Belt-and-braces: even if a test double's `.eq()` were a no-op, the
    mapped rows returned are exactly what the (correctly-scoped) query
    returned — no client-side re-filtering masking a missing server-side
    scope."""
    supabase = _chain_mock([_ROW_ANSWERED])

    result = await list_sessions(user_id="user-001", supabase=supabase)

    assert [r.session_id for r in result] == ["sess-001"]


# ── Row cap (Scale & Load Q2) ────────────────────────────────────────────────────


async def test_query_is_bounded_by_the_session_list_limit() -> None:
    supabase = _chain_mock([])

    await list_sessions(user_id="user-001", supabase=supabase)

    order_call = supabase.table.return_value.select.return_value.eq.return_value.order
    order_call.assert_called_once_with("started_at", desc=True)
    order_call.return_value.limit.assert_called_once_with(_SESSION_LIST_LIMIT)


async def test_session_list_limit_is_a_real_positive_cap() -> None:
    """Premise: the constant this endpoint bounds against is a real, sane
    number — not 0 (which would silently return nothing) and not unset."""
    assert isinstance(_SESSION_LIST_LIMIT, int)
    assert 0 < _SESSION_LIST_LIMIT <= 500


# ── Response shape (`_session_row_to_summary`) ──────────────────────────────────


async def test_maps_a_completed_answered_row_correctly() -> None:
    supabase = _chain_mock([_ROW_ANSWERED])

    result = await list_sessions(user_id="user-001", supabase=supabase)

    assert len(result) == 1
    summary = result[0]
    assert isinstance(summary, SessionSummary)
    assert summary.session_id == "sess-001"
    assert summary.lesson_id == "lesson-001"
    assert summary.lesson_title == "Photosynthesis"
    assert summary.tier == "T1"
    assert summary.tier_label == "Full-Depth"
    assert summary.started_at == "2026-09-01T10:00:00+00:00"
    assert summary.ended_at == "2026-09-01T10:20:00+00:00"
    assert summary.completed is True
    assert summary.ces_score == 82.5


async def test_maps_an_in_progress_unfinished_row_correctly() -> None:
    """`ended_at`/`ces_final` both null (session started, never completed) —
    `completed` must be False and `ces_score` must be None, never 0.0
    (0.0 is a real, meaningfully-different CES value)."""
    supabase = _chain_mock([_ROW_IN_PROGRESS])

    result = await list_sessions(user_id="user-001", supabase=supabase)

    summary = result[0]
    assert summary.ended_at is None
    assert summary.completed is False
    assert summary.ces_score is None
    assert summary.tier_label == "Refresher"


async def test_missing_or_unrecognized_tier_falls_back_to_t2_standard() -> None:
    """Same defensive fallback `get_session_report` already applies when a
    lesson's tier is missing/unrecognized — never crash the whole list over
    one row's bad tier value."""
    row = {**_ROW_ANSWERED, "lessons": {"title": "Untiered Lesson", "tier": "bogus"}}
    supabase = _chain_mock([row])

    result = await list_sessions(user_id="user-001", supabase=supabase)

    assert result[0].tier == "T2"
    assert result[0].tier_label == "Standard"


async def test_missing_lessons_embed_does_not_crash_the_row() -> None:
    """A session whose lesson embed comes back empty (defensive — should not
    happen given the FK, but the embed is still just untyped JSON over the
    wire) degrades to a title-less, T2 row rather than raising."""
    row = {**_ROW_ANSWERED, "lessons": None}
    supabase = _chain_mock([row])

    result = await list_sessions(user_id="user-001", supabase=supabase)

    assert result[0].lesson_title is None
    assert result[0].tier == "T2"


async def test_empty_result_returns_an_empty_list_not_an_error() -> None:
    supabase = _chain_mock([])

    result = await list_sessions(user_id="user-001", supabase=supabase)

    assert result == []


async def test_preserves_the_orders_row_order() -> None:
    """The endpoint trusts the DB's own `.order("started_at", desc=True)` —
    it must not silently re-sort or drop rows on the way to the response."""
    supabase = _chain_mock([_ROW_ANSWERED, _ROW_IN_PROGRESS])

    result = await list_sessions(user_id="user-001", supabase=supabase)

    assert [r.session_id for r in result] == ["sess-001", "sess-002"]


# ── HTTP-layer wiring (router -> service, matches
# test_tutor_question_endpoint.py's own HTTP-layer coverage for this module) ────


async def _fake_user() -> dict:
    return {"sub": "user-001", "email": "test@example.com"}


def test_router_wires_get_sessions_to_list_sessions_with_correct_args() -> None:
    """HTTP-layer smoke test: the route exists at `GET /sessions`, DI
    (CurrentUser) resolves, and the real service function is called with the
    caller's own user id — business logic itself is already covered
    service-level above, not re-tested here."""
    app = FastAPI()
    app.dependency_overrides[get_current_user] = _fake_user
    app.include_router(router, prefix="/api/assessment")
    client = TestClient(app, raise_server_exceptions=False)

    fake_result = [
        SessionSummary(
            session_id="sess-001",
            lesson_id="lesson-001",
            lesson_title="Photosynthesis",
            tier="T1",
            tier_label="Full-Depth",
            started_at="2026-09-01T10:00:00+00:00",
            ended_at="2026-09-01T10:20:00+00:00",
            completed=True,
            ces_score=82.5,
        )
    ]
    with patch(
        "app.modules.assessment.service.list_sessions",
        new=AsyncMock(return_value=fake_result),
    ) as mock_list:
        response = client.get("/api/assessment/sessions")

    assert response.status_code == 200
    assert response.json()[0]["session_id"] == "sess-001"
    mock_list.assert_called_once()
    _args, kwargs = mock_list.call_args
    assert kwargs["user_id"] == "user-001"
