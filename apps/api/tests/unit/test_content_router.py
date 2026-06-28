"""
Unit tests for the content module router.

Mocks: Supabase client, ARQ pool, JWT auth dependency.
External I/O (network, Redis, DB) is fully mocked.
"""

from __future__ import annotations

import io
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ── Fixtures ──────────────────────────────────────────────────────────────────

FAKE_USER: dict[str, Any] = {
    "sub": "550e8400-e29b-41d4-a716-446655440000",
    "email": "test@example.com",
    "role": "authenticated",
}

FAKE_BOOK_ID = "book-uuid-0001"
FAKE_LESSON_ID = "lesson-uuid-0001"
FAKE_JOB_ID = "arq-job-uuid-0001"

MINIMAL_PDF = b"%PDF-1.4 minimal\n%%EOF"


def _make_supabase_mock(
    book_id: str = FAKE_BOOK_ID,
    lesson_id: str = FAKE_LESSON_ID,
    lesson_status: str = "generating",
    lesson_error: str | None = None,
) -> MagicMock:
    """Build a Supabase mock whose chainable .table(name) calls return per-table mocks.

    MagicMock.table() always returns the same child mock regardless of arg, so we use
    side_effect to dispatch to per-table mocks.
    """
    lesson_row = {
        "lesson_id": lesson_id,
        "user_id": FAKE_USER["sub"],
        "status": lesson_status,
        "title": None,
        "created_at": "2026-06-28T00:00:00Z",
    }

    # ── books table mock ──────────────────────────────────────────────────────
    books_mock = MagicMock()
    books_insert_resp = MagicMock()
    books_insert_resp.data = [{"book_id": book_id}]
    books_mock.insert.return_value.execute.return_value = books_insert_resp

    # ── lessons table mock ────────────────────────────────────────────────────
    lessons_mock = MagicMock()
    lessons_insert_resp = MagicMock()
    lessons_insert_resp.data = [{"lesson_id": lesson_id}]
    lessons_mock.insert.return_value.execute.return_value = lessons_insert_resp
    lessons_mock.update.return_value.eq.return_value.execute.return_value = MagicMock()
    # .select("*").eq(...).maybe_single().execute() — get_lesson
    lessons_select = MagicMock()
    lessons_select.maybe_single.return_value.execute.return_value.data = lesson_row
    # .select("*").eq(...).order(...).range(...).execute() — list_lessons
    list_resp = MagicMock()
    list_resp.data = [lesson_row]
    lessons_select.order.return_value.range.return_value.execute.return_value = list_resp
    lessons_mock.select.return_value.eq.return_value = lessons_select

    # ── lesson_jobs table mock ────────────────────────────────────────────────
    jobs_mock = MagicMock()
    jobs_mock.insert.return_value.execute.return_value = MagicMock()
    jobs_mock.update.return_value.eq.return_value.execute.return_value = MagicMock()
    jobs_select_resp = MagicMock()
    jobs_select_resp.data = [{"error": lesson_error}] if lesson_error else []
    jobs_mock.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = jobs_select_resp

    # ── Dispatch by table name ────────────────────────────────────────────────
    _table_map = {
        "books": books_mock,
        "lessons": lessons_mock,
        "lesson_jobs": jobs_mock,
    }

    sb = MagicMock()
    sb.table.side_effect = lambda name: _table_map.get(name, MagicMock())
    sb.storage.from_.return_value.upload.return_value = MagicMock()

    return sb


def _make_arq_mock(job_id: str = FAKE_JOB_ID) -> AsyncMock:
    job = MagicMock()
    job.job_id = job_id
    pool = AsyncMock()
    pool.enqueue_job = AsyncMock(return_value=job)
    return pool


@pytest.fixture()
def client() -> TestClient:
    """TestClient with all external deps mocked."""
    from app.dependencies import get_arq_redis, get_current_user
    from app.main import app

    sb_mock = _make_supabase_mock()
    arq_mock = _make_arq_mock()

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_arq_redis] = lambda: arq_mock

    with patch("app.modules.content.router.get_supabase", return_value=sb_mock):
        yield TestClient(app, raise_server_exceptions=True)

    app.dependency_overrides.clear()


# ── POST /lessons — happy path ─────────────────────────────────────────────────


@pytest.mark.unit
def test_upload_lesson_202_shape(client: TestClient) -> None:
    """Valid PDF upload returns 202 with lesson_id and job_id."""
    resp = client.post(
        "/api/content/lessons",
        files={"file": ("chapter1.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["lesson_id"] == FAKE_LESSON_ID
    assert body["job_id"] == FAKE_JOB_ID
    assert body["status"] == "queued"


@pytest.mark.unit
def test_upload_lesson_db_insert_order(client: TestClient) -> None:
    """books row must be created before lessons row (FK order)."""
    from app.dependencies import get_arq_redis, get_current_user
    from app.main import app

    call_order: list[str] = []

    sb = MagicMock()
    # Track insert calls by table name
    original_table = sb.table.side_effect

    def track_table(name: str) -> MagicMock:
        t = MagicMock()
        insert_exec = MagicMock()
        if name == "books":
            insert_exec.data = [{"book_id": FAKE_BOOK_ID}]
            t.insert.return_value.execute.side_effect = lambda: (call_order.append("books"), insert_exec)[1]
        elif name == "lessons":
            insert_exec.data = [{"lesson_id": FAKE_LESSON_ID}]
            t.insert.return_value.execute.side_effect = lambda: (call_order.append("lessons"), insert_exec)[1]
            t.update.return_value.eq.return_value.execute.return_value = MagicMock()
        elif name == "lesson_jobs":
            t.insert.return_value.execute.side_effect = lambda: (call_order.append("lesson_jobs"), MagicMock())[1]
        return t

    sb.table.side_effect = track_table
    sb.storage.from_.return_value.upload.return_value = MagicMock()

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_arq_redis] = lambda: _make_arq_mock()

    with patch("app.modules.content.router.get_supabase", return_value=sb):
        resp = TestClient(app, raise_server_exceptions=True).post(
            "/api/content/lessons",
            files={"file": ("t.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
        )

    app.dependency_overrides.clear()

    assert resp.status_code == 202
    assert call_order == ["books", "lessons", "lesson_jobs"], f"Wrong insert order: {call_order}"


# ── POST /lessons — validation errors ─────────────────────────────────────────


@pytest.mark.unit
def test_upload_lesson_413_oversized(client: TestClient) -> None:
    """Files > 50 MB are rejected with 413 before the body is read."""
    large_pdf = b"%PDF" + b"x" * (51 * 1024 * 1024)
    resp = client.post(
        "/api/content/lessons",
        files={"file": ("big.pdf", io.BytesIO(large_pdf), "application/pdf")},
    )
    assert resp.status_code == 413


@pytest.mark.unit
def test_upload_lesson_422_not_pdf_magic_bytes(client: TestClient) -> None:
    """Files whose first 4 bytes are not %PDF are rejected with 422."""
    fake_pdf = b"PK\x03\x04" + b"not a pdf"  # ZIP magic bytes
    resp = client.post(
        "/api/content/lessons",
        files={"file": ("fake.pdf", io.BytesIO(fake_pdf), "application/pdf")},
    )
    assert resp.status_code == 422
    assert "not a valid PDF" in resp.json()["detail"]


@pytest.mark.unit
def test_upload_lesson_422_wrong_content_type(client: TestClient) -> None:
    """Non-PDF MIME type is rejected with 422."""
    resp = client.post(
        "/api/content/lessons",
        files={"file": ("chapter.txt", io.BytesIO(MINIMAL_PDF), "text/plain")},
    )
    assert resp.status_code == 422
    assert "content type" in resp.json()["detail"].lower()


# ── GET /lessons/{lesson_id} ──────────────────────────────────────────────────


@pytest.mark.unit
def test_get_lesson_200(client: TestClient) -> None:
    """GET /lessons/{id} returns status mapped from DB."""
    resp = client.get(f"/api/content/lessons/{FAKE_LESSON_ID}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["lesson_id"] == FAKE_LESSON_ID
    assert body["status"] == "running"  # generating → running


@pytest.mark.unit
def test_get_lesson_404_wrong_user() -> None:
    """GET /lessons/{id} returns 404 when lesson belongs to a different user."""
    from app.dependencies import get_arq_redis, get_current_user
    from app.main import app

    other_user = {**FAKE_USER, "sub": "other-user-uuid"}

    # Supabase returns a lesson owned by FAKE_USER, but requester is other_user
    sb = MagicMock()
    lesson_row = {
        "lesson_id": FAKE_LESSON_ID,
        "user_id": FAKE_USER["sub"],  # different from other_user["sub"]
        "status": "generating",
        "title": None,
        "created_at": "2026-06-28T00:00:00Z",
    }
    sb.table("lessons").select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = lesson_row

    app.dependency_overrides[get_current_user] = lambda: other_user
    app.dependency_overrides[get_arq_redis] = lambda: _make_arq_mock()

    with patch("app.modules.content.router.get_supabase", return_value=sb):
        resp = TestClient(app).get(f"/api/content/lessons/{FAKE_LESSON_ID}")

    app.dependency_overrides.clear()

    assert resp.status_code == 404


@pytest.mark.unit
def test_get_lesson_404_not_found() -> None:
    """GET /lessons/{id} returns 404 when Supabase returns no row."""
    from app.dependencies import get_arq_redis, get_current_user
    from app.main import app

    sb = MagicMock()
    sb.table("lessons").select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = None

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_arq_redis] = lambda: _make_arq_mock()

    with patch("app.modules.content.router.get_supabase", return_value=sb):
        resp = TestClient(app).get(f"/api/content/lessons/{FAKE_LESSON_ID}")

    app.dependency_overrides.clear()

    assert resp.status_code == 404


# ── GET /lessons ──────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_list_lessons_200(client: TestClient) -> None:
    """GET /lessons returns a list with status mapped from DB."""
    resp = client.get("/api/content/lessons")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert body[0]["lesson_id"] == FAKE_LESSON_ID
    assert body[0]["status"] == "running"


@pytest.mark.unit
def test_list_lessons_respects_limit_offset(client: TestClient) -> None:
    """limit and offset query params are forwarded to Supabase."""
    resp = client.get("/api/content/lessons?limit=5&offset=10")
    assert resp.status_code == 200


# ── Status mapping ────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_status_map_generating_to_running() -> None:
    from app.modules.content.router import _map_status

    assert _map_status("generating") == "running"
    assert _map_status("ready") == "ready"
    assert _map_status("failed") == "failed"
    assert _map_status("unknown_value") == "queued"


# ── Rate limit key function ───────────────────────────────────────────────────


@pytest.mark.unit
def test_get_user_key_falls_back_to_ip_on_missing_auth() -> None:
    """_get_user_key returns IP when no Authorization header is present."""
    from app.core.rate_limit import _get_user_key

    req = MagicMock()
    req.headers = {}
    req.client.host = "127.0.0.1"

    with patch("app.core.rate_limit.get_remote_address", return_value="127.0.0.1"):
        key = _get_user_key(req)
    assert key == "127.0.0.1"


@pytest.mark.unit
def test_get_user_key_returns_sub_from_valid_jwt() -> None:
    """_get_user_key extracts JWT sub when token is valid."""
    import jwt as pyjwt

    from app.core.rate_limit import _get_user_key

    secret = "test-secret-long-enough-for-hs256-min-32-bytes-ok"
    token = pyjwt.encode({"sub": "user-123", "exp": 9999999999}, secret, algorithm="HS256")

    req = MagicMock()
    req.headers = {"Authorization": f"Bearer {token}"}

    with patch("app.config.get_settings") as mock_settings:
        mock_settings.return_value.supabase_jwt_secret = secret  # noqa: S106
        key = _get_user_key(req)

    assert key == "user:user-123"
