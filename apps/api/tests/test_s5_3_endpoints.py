"""HTTP-level tests for S5-3: /context endpoints (AC9, AC10, IDOR, auth).

These are integration-style tests that use FastAPI's TestClient to exercise
the router layer, including ownership validation and auth guards.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

BOOK_ID = "11111111-1111-1111-1111-111111111111"
CHAPTER_ID = "22222222-2222-2222-2222-222222222222"
USER_ID = "33333333-3333-3333-3333-333333333333"
OTHER_USER_ID = "44444444-4444-4444-4444-444444444444"

_VALID_CONTEXT_BODY = {
    "depth_duration": "standard_30_45m",
    "learning_need": "examples_analogies",
    "specific_doubt": "Why does integration by parts work?",
    "goal_and_skip": "Solve definite integrals. Skip: proofs.",
    "prerequisites_done": True,
}

_SAVED_ROW = {
    "chapter_id": CHAPTER_ID,
    "user_id": USER_ID,
    "depth_duration": "standard_30_45m",
    "learning_need": "examples_analogies",
    "specific_doubt": "Why does integration by parts work?",
    "goal_and_skip": "Solve definite integrals. Skip: proofs.",
    "prerequisites_done": True,
    "updated_at": "2026-09-21T10:00:00+00:00",
}


def _make_client_with_user(user_id: str) -> TestClient:
    """Build a TestClient with the dependency overrides needed for auth."""
    from app.main import create_app
    from app.dependencies import get_current_user

    app = create_app()

    async def _override_user():
        return {"sub": user_id, "role": "authenticated"}

    app.dependency_overrides[get_current_user] = _override_user
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# PUT /context tests
# ---------------------------------------------------------------------------

class TestPutChapterContext:
    """AC9: PUT returns 200 with saved row; IDOR returns 404; unauthed returns 401."""

    @patch("app.modules.content.router.get_supabase")
    @patch("app.modules.content.router.upsert_chapter_context", new_callable=AsyncMock)
    @patch("app.modules.content.router.get_chapter_context_row", new_callable=AsyncMock)
    def test_put_valid_context_returns_200(
        self, mock_get_row, mock_upsert, mock_db
    ) -> None:
        # _resolve_chapter_for_context needs a chapter row
        chapter_row_resp = MagicMock()
        chapter_row_resp.data = [{"chapter_id": CHAPTER_ID, "book_id": BOOK_ID}]
        mock_db.return_value.table.return_value.select.return_value \
            .eq.return_value.eq.return_value.limit.return_value.execute.return_value = chapter_row_resp
        mock_get_row.return_value = _SAVED_ROW

        client = _make_client_with_user(USER_ID)
        resp = client.put(
            f"/api/content/books/{BOOK_ID}/chapters/{CHAPTER_ID}/context",
            json=_VALID_CONTEXT_BODY,
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["chapter_id"] == CHAPTER_ID
        assert data["depth_duration"] == "standard_30_45m"

    @patch("app.modules.content.router.get_supabase")
    def test_put_chapter_belonging_to_other_user_returns_404(self, mock_db) -> None:
        """IDOR: chapter not owned by this user → 404, not the row data."""
        chapter_row_resp = MagicMock()
        chapter_row_resp.data = []  # chapter not found for this (book_id, user_id)
        mock_db.return_value.table.return_value.select.return_value \
            .eq.return_value.eq.return_value.limit.return_value.execute.return_value = chapter_row_resp

        client = _make_client_with_user(OTHER_USER_ID)
        resp = client.put(
            f"/api/content/books/{BOOK_ID}/chapters/{CHAPTER_ID}/context",
            json=_VALID_CONTEXT_BODY,
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_put_unauthenticated_returns_401(self) -> None:
        """No JWT → 401/403 before any DB call."""
        from app.main import create_app
        client = TestClient(create_app(), raise_server_exceptions=False)
        resp = client.put(
            f"/api/content/books/{BOOK_ID}/chapters/{CHAPTER_ID}/context",
            json=_VALID_CONTEXT_BODY,
        )
        assert resp.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )


# ---------------------------------------------------------------------------
# GET /context tests
# ---------------------------------------------------------------------------

class TestGetChapterContext:
    """AC10: GET returns 200 with row; 204 when no row; 404 on cross-user; 401 without auth."""

    @patch("app.modules.content.router.get_supabase")
    @patch("app.modules.content.router.get_chapter_context_row", new_callable=AsyncMock)
    def test_get_existing_context_returns_200(self, mock_get_row, mock_db) -> None:
        chapter_row_resp = MagicMock()
        chapter_row_resp.data = [{"chapter_id": CHAPTER_ID, "book_id": BOOK_ID}]
        mock_db.return_value.table.return_value.select.return_value \
            .eq.return_value.eq.return_value.limit.return_value.execute.return_value = chapter_row_resp
        mock_get_row.return_value = _SAVED_ROW

        client = _make_client_with_user(USER_ID)
        resp = client.get(
            f"/api/content/books/{BOOK_ID}/chapters/{CHAPTER_ID}/context"
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["depth_duration"] == "standard_30_45m"

    @patch("app.modules.content.router.get_supabase")
    @patch("app.modules.content.router.get_chapter_context_row", new_callable=AsyncMock)
    def test_get_no_context_returns_204(self, mock_get_row, mock_db) -> None:
        """AC10: no existing row → 204 No Content."""
        chapter_row_resp = MagicMock()
        chapter_row_resp.data = [{"chapter_id": CHAPTER_ID, "book_id": BOOK_ID}]
        mock_db.return_value.table.return_value.select.return_value \
            .eq.return_value.eq.return_value.limit.return_value.execute.return_value = chapter_row_resp
        mock_get_row.return_value = None

        client = _make_client_with_user(USER_ID)
        resp = client.get(
            f"/api/content/books/{BOOK_ID}/chapters/{CHAPTER_ID}/context"
        )
        assert resp.status_code == status.HTTP_204_NO_CONTENT

    @patch("app.modules.content.router.get_supabase")
    def test_get_cross_user_returns_404(self, mock_db) -> None:
        """IDOR: chapter not owned by requesting user → 404."""
        chapter_row_resp = MagicMock()
        chapter_row_resp.data = []
        mock_db.return_value.table.return_value.select.return_value \
            .eq.return_value.eq.return_value.limit.return_value.execute.return_value = chapter_row_resp

        client = _make_client_with_user(OTHER_USER_ID)
        resp = client.get(
            f"/api/content/books/{BOOK_ID}/chapters/{CHAPTER_ID}/context"
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_get_unauthenticated_returns_401(self) -> None:
        from app.main import create_app
        client = TestClient(create_app(), raise_server_exceptions=False)
        resp = client.get(
            f"/api/content/books/{BOOK_ID}/chapters/{CHAPTER_ID}/context"
        )
        assert resp.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )
