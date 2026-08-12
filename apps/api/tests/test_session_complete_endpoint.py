"""`POST /api/assessment/session/{session_id}/complete` — writes `sessions.ended_at`.

Why this file exists
--------------------
Live browser testing of a full lesson playthrough (throwaway/lesson-planner-batch-fix,
2026-08-12) found `sessions.ended_at` had ZERO writers anywhere in the codebase —
confirmed by grepping the whole API. `get_session_report`'s `duration_minutes` and
`completed_at` fields silently returned 0.0/None for every session ever completed,
with no error and no visible symptom other than a wrong number on the report page.

Mirrors `test_session_create_endpoint.py`'s conventions (same SEC-006 pattern, same
mock_to_thread shim) since `complete_session` sits right next to `create_session` in
service.py and shares its ownership-check shape.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.dependencies import get_current_user
from app.modules.assessment.router import router

USER_ID = "11111111-1111-1111-1111-111111111111"
OTHER_USER_ID = "22222222-2222-2222-2222-222222222222"
SESSION_ID = "44444444-4444-4444-4444-444444444444"

_app = FastAPI()
_app.dependency_overrides[get_current_user] = lambda: {"sub": USER_ID, "email": "s@example.com"}
_app.include_router(router, prefix="/api/assessment")
_client = TestClient(_app, raise_server_exceptions=False)

_UNAUTH_APP = FastAPI()
_UNAUTH_APP.include_router(router, prefix="/api/assessment")
_unauth_client = TestClient(_UNAUTH_APP, raise_server_exceptions=False)


@pytest.fixture
def mock_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace asyncio.to_thread with a synchronous shim (module convention)."""

    async def _sync_shim(func: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        return func(*args, **kwargs)

    monkeypatch.setattr("app.modules.assessment.service.asyncio.to_thread", _sync_shim)


def _supabase(
    *,
    owner: str | None = USER_ID,
    existing_ended_at: str | None = None,
) -> MagicMock:
    """Supabase stub: a sessions ownership read, then (maybe) an update.

    `owner=None` models a session that does not exist.
    """
    sb = MagicMock()
    updates: list[dict[str, Any]] = []

    session_row = (
        None
        if owner is None
        else {"session_id": SESSION_ID, "user_id": owner, "ended_at": existing_ended_at}
    )

    def _table(name: str) -> MagicMock:
        t = MagicMock()
        if name == "sessions":
            (
                t.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data
            ) = session_row

            def _update(payload: dict[str, Any]) -> MagicMock:
                updates.append(payload)
                chain = MagicMock()
                chain.eq.return_value.is_.return_value.execute.return_value.data = [
                    {**(session_row or {}), **payload}
                ]
                return chain

            t.update.side_effect = _update
        return t

    sb.table.side_effect = _table
    sb.updates = updates
    return sb


def _post(sb: MagicMock) -> Any:  # noqa: ANN401
    with patch("app.core.db.get_supabase", return_value=sb):
        return _client.post(f"/api/assessment/session/{SESSION_ID}/complete")


@pytest.mark.unit
def test_writes_ended_at_and_returns_it(mock_to_thread: None) -> None:
    sb = _supabase()
    resp = _post(sb)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["session_id"] == SESSION_ID
    assert body["ended_at"], "ended_at must be a non-empty timestamp string"
    assert len(sb.updates) == 1
    assert "ended_at" in sb.updates[0]


@pytest.mark.unit
def test_idempotent_a_second_call_does_not_overwrite_the_first_timestamp(
    mock_to_thread: None,
) -> None:
    """Scale & Load Q6 — concurrent check-then-act: a retry or double-fire must
    never clobber the real completion time with a later one."""
    already_ended = "2026-08-12T10:00:00+00:00"
    sb = _supabase(existing_ended_at=already_ended)
    resp = _post(sb)

    assert resp.status_code == 200, resp.text
    assert resp.json()["ended_at"] == already_ended
    assert sb.updates == [], "already-completed session must not be written to again"


@pytest.mark.unit
def test_nonexistent_session_returns_404(mock_to_thread: None) -> None:
    resp = _post(_supabase(owner=None))
    assert resp.status_code == 404, resp.text


@pytest.mark.unit
def test_a_session_owned_by_someone_else_returns_404_not_403(mock_to_thread: None) -> None:
    """SEC-006 — a distinct 403 would leak session existence to a non-owner."""
    sb = _supabase(owner=OTHER_USER_ID)
    resp = _post(sb)

    assert resp.status_code == 404, resp.text
    assert sb.updates == [], "no write may happen for a session the caller does not own"


@pytest.mark.unit
def test_wrong_user_and_missing_session_return_identical_404_bodies(mock_to_thread: None) -> None:
    """The enumeration-oracle assertion — status AND body must match."""
    missing = _post(_supabase(owner=None))
    unowned = _post(_supabase(owner=OTHER_USER_ID))

    assert missing.status_code == unowned.status_code == 404
    assert missing.json() == unowned.json()


@pytest.mark.unit
def test_unauthenticated_request_is_rejected() -> None:
    resp = _unauth_client.post(f"/api/assessment/session/{SESSION_ID}/complete")
    assert resp.status_code == 401
