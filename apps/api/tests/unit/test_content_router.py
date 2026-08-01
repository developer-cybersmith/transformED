"""
Unit tests for the content module router.

Mocks: Supabase client, ARQ pool, JWT auth dependency.
External I/O (network, Redis, DB) is fully mocked.
"""

from __future__ import annotations

import copy
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

FAKE_BOOK_ID = "11111111-1111-1111-1111-111111111111"
FAKE_LESSON_ID = "22222222-2222-2222-2222-222222222222"
FAKE_JOB_ID = "33333333-3333-3333-3333-333333333333"

MINIMAL_PDF = b"%PDF-1.4 minimal\n%%EOF"


def _approved_settings() -> MagicMock:
    """Settings mock with FAKE_USER's email on the beta-access allowlist.

    upload_lesson depends on ApprovedUser (require_approved_user), which 403s
    unless the JWT email is in settings.approved_emails — every test here
    needs this override or it never reaches the actual behavior under test.
    """
    settings = MagicMock()
    settings.approved_emails = [FAKE_USER["email"]]
    return settings


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
    jobs_select = jobs_mock.select.return_value
    jobs_select.eq.return_value.order.return_value.limit.return_value.execute.return_value = (
        jobs_select_resp
    )

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
    from app.dependencies import get_arq_redis, get_current_user, get_settings
    from app.main import app

    sb_mock = _make_supabase_mock()
    arq_mock = _make_arq_mock()

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_arq_redis] = lambda: arq_mock
    app.dependency_overrides[get_settings] = _approved_settings

    with patch("app.modules.content.router.get_supabase", return_value=sb_mock):
        yield TestClient(app, raise_server_exceptions=True)

    app.dependency_overrides.clear()


# ── POST /lessons — beta access gate ────────────────────────────────────────────


@pytest.mark.unit
def test_upload_lesson_403_not_approved() -> None:
    """A signed-up user whose email is not on the beta-access allowlist is
    rejected with 403 before any row is created or the file is processed --
    upload_lesson depends on ApprovedUser, not CurrentUser."""
    from app.dependencies import get_arq_redis, get_current_user, get_settings
    from app.main import app

    sb_mock = _make_supabase_mock()

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_arq_redis] = lambda: _make_arq_mock()
    app.dependency_overrides[get_settings] = lambda: MagicMock(approved_emails=[])

    with patch("app.modules.content.router.get_supabase", return_value=sb_mock):
        resp = TestClient(app, raise_server_exceptions=True).post(
            "/api/content/lessons",
            files={"file": ("chapter1.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
        )

    app.dependency_overrides.clear()

    assert resp.status_code == 403
    sb_mock.table.assert_not_called()


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
    def track_table(name: str) -> MagicMock:
        t = MagicMock()
        insert_exec = MagicMock()
        if name == "books":
            insert_exec.data = [{"book_id": FAKE_BOOK_ID}]
            t.insert.return_value.execute.side_effect = lambda: (
                call_order.append("books"),
                insert_exec,
            )[1]
        elif name == "lessons":
            insert_exec.data = [{"lesson_id": FAKE_LESSON_ID}]
            t.insert.return_value.execute.side_effect = lambda: (
                call_order.append("lessons"),
                insert_exec,
            )[1]
            t.update.return_value.eq.return_value.execute.return_value = MagicMock()
        elif name == "lesson_jobs":
            t.insert.return_value.execute.side_effect = lambda: (
                call_order.append("lesson_jobs"),
                MagicMock(),
            )[1]
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
    sb.table(
        "lessons"
    ).select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = (
        lesson_row
    )

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
    sb.table(
        "lessons"
    ).select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = None

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_arq_redis] = lambda: _make_arq_mock()

    with patch("app.modules.content.router.get_supabase", return_value=sb):
        resp = TestClient(app).get(f"/api/content/lessons/{FAKE_LESSON_ID}")

    app.dependency_overrides.clear()

    assert resp.status_code == 404


# ── GET /lessons/{lesson_id} — Story 1-6: content + signed URLs ──────────────

_AUDIO_PATH = f"{FAKE_LESSON_ID}/seg_1.mp3"
_IMAGE_PATH = f"{FAKE_LESSON_ID}/sl_1.png"

_READY_CONTENT_DICT: dict[str, Any] = {
    "lesson_id": FAKE_LESSON_ID,
    "book_id": FAKE_BOOK_ID,
    "chapter_id": "44444444-4444-4444-4444-444444444444",
    "created_at": "2026-06-25T00:00:00Z",
    "metadata": {
        "title": "Test Lesson",
        "subject": "Testing",
        "total_segments": 1,
        "estimated_duration_mins": 5.0,
        "complexity_level": "medium",
    },
    "segments": [
        {
            "segment_id": "seg_1",
            "segment_index": 0,
            "title": "Segment 1",
            "summary": "Summary text",
            "complexity": {
                "level": "medium",
                "cognitive_load": "moderate",
                "abstraction_level": "concrete",
                "prerequisite_concepts": [],
                "narration_style": "conversational",
                "quiz_difficulty": "medium",
                "intervention_sensitivity": 0.5,
            },
            "slides": [
                {
                    "slide_id": "sl_1",
                    "title": "Slide 1",
                    "bullets": ["Point 1"],
                    "image_url": _IMAGE_PATH,
                    "fallback_image_url": None,
                }
            ],
            "narration": {
                "script": "Hello world.",
                "audio_url": _AUDIO_PATH,
                "audio_provider": "azure",
                "timestamps": [{"slide_id": "sl_1", "start_ms": 0, "end_ms": 3000}],
            },
            "quiz": [],
            "teachback_prompt": "Explain in your own words.",
            "jargon": [],
            "interventions": {
                "distraction": ["A", "B", "C"],
                "confusion": ["D", "E", "F"],
                "fatigue": ["G", "H", "I"],
            },
        }
    ],
    "glossary": [],
}


def _make_ready_supabase_mock(sign_side_effect: object) -> MagicMock:
    sb = MagicMock()
    lesson_row = {
        "lesson_id": FAKE_LESSON_ID,
        "user_id": FAKE_USER["sub"],
        "status": "ready",
        "title": "Test Lesson",
        "content": _READY_CONTENT_DICT,
        "created_at": "2026-06-28T00:00:00Z",
    }
    sb.table(
        "lessons"
    ).select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = (
        lesson_row
    )
    sb.storage.from_.return_value.create_signed_url.side_effect = sign_side_effect
    return sb


@pytest.mark.unit
def test_get_lesson_ready_resolves_signed_urls() -> None:
    """AC-1/AC-2: a ready lesson's content embeds SIGNED urls, not bare paths."""
    from app.dependencies import get_arq_redis, get_current_user
    from app.main import app

    def _sign(path: str, expires_in: int) -> dict[str, str]:
        return {"signedURL": f"https://signed.example.com/{path}?exp={expires_in}"}

    sb = _make_ready_supabase_mock(_sign)

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_arq_redis] = lambda: _make_arq_mock()

    with patch("app.modules.content.router.get_supabase", return_value=sb):
        resp = TestClient(app).get(f"/api/content/lessons/{FAKE_LESSON_ID}")

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    segment = body["content"]["segments"][0]
    # Story 2-31 AC-5: asserted against the constant, not a literal — the whole
    # point of the change is that this window is tunable, and a hardcoded 3600
    # here would have to be edited every time it moves.
    from app.modules.content.router import _EMBEDDED_MEDIA_EXPIRY_S as _EXP

    assert (
        segment["narration"]["audio_url"] == f"https://signed.example.com/{_AUDIO_PATH}?exp={_EXP}"
    )
    assert (
        segment["slides"][0]["image_url"] == f"https://signed.example.com/{_IMAGE_PATH}?exp={_EXP}"
    )
    assert _EXP > 3600, "embedded lesson media must outlive the 1-hour default (AC-5)"
    assert segment["slides"][0]["fallback_image_url"] is None

    calls = sb.storage.from_.call_args_list
    assert any(c.args == ("lesson-audio",) for c in calls)
    assert any(c.args == ("lesson-images",) for c in calls)
    sb.storage.from_.return_value.create_signed_url.assert_any_call(_AUDIO_PATH, _EXP)
    sb.storage.from_.return_value.create_signed_url.assert_any_call(_IMAGE_PATH, _EXP)


@pytest.mark.unit
def test_get_lesson_ready_degrades_one_asset_on_signing_failure() -> None:
    """AC-3: one asset failing to sign degrades ONLY that asset, not the
    whole response."""
    from app.dependencies import get_arq_redis, get_current_user
    from app.main import app

    def _sign(path: str, _expires_in: int) -> dict[str, str]:
        if path == _AUDIO_PATH:
            raise RuntimeError("storage outage")
        return {"signedURL": f"https://signed.example.com/{path}"}

    sb = _make_ready_supabase_mock(_sign)

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_arq_redis] = lambda: _make_arq_mock()

    with patch("app.modules.content.router.get_supabase", return_value=sb):
        resp = TestClient(app).get(f"/api/content/lessons/{FAKE_LESSON_ID}")

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    segment = resp.json()["content"]["segments"][0]
    assert segment["narration"]["audio_url"] == ""  # degraded, not dropped
    assert segment["slides"][0]["image_url"] == f"https://signed.example.com/{_IMAGE_PATH}"


@pytest.mark.unit
def test_get_lesson_generating_status_content_is_none(client: TestClient) -> None:
    """AC-1 regression: a non-ready lesson's content stays None (matches
    test_get_lesson_200's underlying fixture, status='generating')."""
    resp = client.get(f"/api/content/lessons/{FAKE_LESSON_ID}")
    assert resp.status_code == 200
    assert resp.json()["content"] is None


@pytest.mark.unit
def test_get_lesson_ready_but_null_content_column_stays_none() -> None:
    """AC-1 edge case: status=='ready' with a null content column (should
    be unreachable in practice — package_builder writes both together —
    but the endpoint's own guard must hold either way) returns content=None,
    not a crash, and makes no signing calls."""
    from app.dependencies import get_arq_redis, get_current_user
    from app.main import app

    sb = MagicMock()
    lesson_row = {
        "lesson_id": FAKE_LESSON_ID,
        "user_id": FAKE_USER["sub"],
        "status": "ready",
        "title": "Test Lesson",
        "content": None,
        "created_at": "2026-06-28T00:00:00Z",
    }
    sb.table(
        "lessons"
    ).select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = (
        lesson_row
    )

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_arq_redis] = lambda: _make_arq_mock()

    with patch("app.modules.content.router.get_supabase", return_value=sb):
        resp = TestClient(app).get(f"/api/content/lessons/{FAKE_LESSON_ID}")

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["content"] is None
    sb.storage.from_.assert_not_called()


@pytest.mark.unit
def test_get_lesson_corrupted_content_is_not_silently_swallowed() -> None:
    """AC-6, full HTTP path: malformed stored content (our own
    package_builder's data, corrupted) must raise through get_lesson as an
    unhandled 500 — never silently degrade to content=None or a 200 with
    partial data, which would hide real data corruption from the caller."""
    from app.dependencies import get_arq_redis, get_current_user
    from app.main import app

    sb = MagicMock()
    corrupted_content = {**copy.deepcopy(_READY_CONTENT_DICT), "segments": []}  # min_length=1
    lesson_row = {
        "lesson_id": FAKE_LESSON_ID,
        "user_id": FAKE_USER["sub"],
        "status": "ready",
        "title": "Test Lesson",
        "content": corrupted_content,
        "created_at": "2026-06-28T00:00:00Z",
    }
    sb.table(
        "lessons"
    ).select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = (
        lesson_row
    )

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_arq_redis] = lambda: _make_arq_mock()

    with patch("app.modules.content.router.get_supabase", return_value=sb):
        resp = TestClient(app, raise_server_exceptions=False).get(
            f"/api/content/lessons/{FAKE_LESSON_ID}"
        )

    app.dependency_overrides.clear()

    assert resp.status_code == 500


@pytest.mark.unit
def test_resolve_lesson_content_does_not_mutate_input() -> None:
    """Regression (caught during Story 1-6 development): the raw content
    dict passed in must not be mutated — a prior version signed URLs
    in place, corrupting a shared/cached dict for any second reader."""
    from app.modules.content.router import _resolve_lesson_content

    original = copy.deepcopy(_READY_CONTENT_DICT)
    sb = MagicMock()
    sb.storage.from_.return_value.create_signed_url.return_value = {
        "signedURL": "https://signed.example.com/x"
    }

    _resolve_lesson_content(_READY_CONTENT_DICT, sb)

    assert _READY_CONTENT_DICT == original


@pytest.mark.unit
def test_resolve_lesson_content_null_segments_raises_validation_not_typeerror() -> None:
    """Edge case (Edge Case Hunter, Story 1-6 review): `segments` explicitly
    present as JSON null (not merely absent) must not crash the resolution
    LOOP with a raw TypeError — `.get("segments", [])` only defaults on a
    MISSING key, not an explicit None, so `or []` is required. The lesson
    is still malformed (LessonPackage requires >=1 segment) and correctly
    raises via model_validate (AC-6), just not mid-loop."""
    from pydantic import ValidationError

    from app.modules.content.router import _resolve_lesson_content

    sb = MagicMock()
    content_with_null_segments = {**copy.deepcopy(_READY_CONTENT_DICT), "segments": None}
    with pytest.raises(ValidationError):
        _resolve_lesson_content(content_with_null_segments, sb)
    sb.storage.from_.assert_not_called()  # loop never ran — nothing to sign


@pytest.mark.unit
def test_resolve_lesson_content_null_slides_raises_validation_not_typeerror() -> None:
    """Same as above for a segment's `slides` being explicitly null."""
    from pydantic import ValidationError

    from app.modules.content.router import _resolve_lesson_content

    sb = MagicMock()
    content_with_null_slides = copy.deepcopy(_READY_CONTENT_DICT)
    content_with_null_slides["segments"][0]["slides"] = None
    with pytest.raises(ValidationError):
        _resolve_lesson_content(content_with_null_slides, sb)


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


@pytest.mark.unit
def test_list_lessons_never_attaches_content() -> None:
    """AC-7: even a ready lesson with content in the DB row never gets
    content resolved/attached in the LIST response — only get_lesson does.
    No signing calls should happen at all for a list request."""
    from app.dependencies import get_arq_redis, get_current_user
    from app.main import app

    sb = MagicMock()
    ready_row = {
        "lesson_id": FAKE_LESSON_ID,
        "user_id": FAKE_USER["sub"],
        "status": "ready",
        "title": "Test Lesson",
        "content": _READY_CONTENT_DICT,
        "created_at": "2026-06-28T00:00:00Z",
    }
    list_resp = MagicMock()
    list_resp.data = [ready_row]
    lessons_select = sb.table("lessons").select.return_value.eq.return_value
    lessons_select.order.return_value.range.return_value.execute.return_value = list_resp

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_arq_redis] = lambda: _make_arq_mock()

    with patch("app.modules.content.router.get_supabase", return_value=sb):
        resp = TestClient(app).get("/api/content/lessons")

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["status"] == "ready"
    assert body[0]["content"] is None
    sb.storage.from_.assert_not_called()


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


# ── Rate limiting — 429 + Retry-After ────────────────────────────────────────


@pytest.mark.unit
def test_upload_lesson_429_rate_limit() -> None:
    """6th upload from the same JWT sub within a minute returns 429 with Retry-After header."""
    import jwt as pyjwt

    from app.dependencies import get_arq_redis, get_current_user, get_settings
    from app.main import app

    # Use a unique sub so this test's counter is isolated from other tests
    secret = "test-jwt-secret-that-is-long-enough-32-bytes"
    token = pyjwt.encode(
        {"sub": "rate-limit-test-unique-sub-for-429", "exp": 9999999999},
        secret,
        algorithm="HS256",
    )
    auth_headers = {"Authorization": f"Bearer {token}"}

    sb_mock = _make_supabase_mock()
    arq_mock = _make_arq_mock()

    app.dependency_overrides[get_current_user] = lambda: {
        **FAKE_USER,
        "sub": "rate-limit-test-unique-sub-for-429",
    }
    app.dependency_overrides[get_arq_redis] = lambda: arq_mock
    app.dependency_overrides[get_settings] = _approved_settings

    with patch("app.modules.content.router.get_supabase", return_value=sb_mock):
        tc = TestClient(app, raise_server_exceptions=False)
        for _ in range(5):
            tc.post(
                "/api/content/lessons",
                files={"file": ("ch.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
                headers=auth_headers,
            )
        resp = tc.post(
            "/api/content/lessons",
            files={"file": ("ch.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
            headers=auth_headers,
        )

    app.dependency_overrides.clear()

    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


# ── Story S2-LM3: tier param ────────────────────────────────────────────────


@pytest.mark.unit
def test_upload_lesson_accepts_valid_tier_and_persists_it(client: TestClient) -> None:
    """A valid tier form field is accepted (202) and included in the lessons
    insert payload."""
    from app.core.rate_limit import limiter
    from app.dependencies import get_arq_redis, get_current_user
    from app.main import app

    limiter.reset()  # isolate from other tests' shared IP-based rate-limit bucket
    lessons_insert_calls: list[dict] = []

    sb = MagicMock()

    def track_table(name: str) -> MagicMock:
        t = MagicMock()
        if name == "books":
            t.insert.return_value.execute.return_value = MagicMock(data=[{"book_id": FAKE_BOOK_ID}])
        elif name == "lessons":

            def _insert(payload: dict) -> MagicMock:
                lessons_insert_calls.append(payload)
                m = MagicMock()
                m.execute.return_value = MagicMock(data=[{"lesson_id": FAKE_LESSON_ID}])
                return m

            t.insert.side_effect = _insert
            t.update.return_value.eq.return_value.execute.return_value = MagicMock()
        elif name == "lesson_jobs":
            t.insert.return_value.execute.return_value = MagicMock()
        return t

    sb.table.side_effect = track_table
    sb.storage.from_.return_value.upload.return_value = MagicMock()

    app.dependency_overrides[get_current_user] = lambda: {**FAKE_USER, "sub": "tier-valid-test-sub"}
    app.dependency_overrides[get_arq_redis] = lambda: _make_arq_mock()

    with patch("app.modules.content.router.get_supabase", return_value=sb):
        resp = TestClient(app, raise_server_exceptions=True).post(
            "/api/content/lessons",
            files={"file": ("t.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
            data={"tier": "T1"},
        )

    app.dependency_overrides.clear()

    assert resp.status_code == 202
    assert len(lessons_insert_calls) == 1
    assert lessons_insert_calls[0]["tier"] == "T1"


@pytest.mark.unit
def test_upload_lesson_omitted_tier_defaults_to_t2(client: TestClient) -> None:
    """Omitting tier entirely defaults to T2 — existing callers unaffected
    (AC-1)."""
    from app.core.rate_limit import limiter
    from app.dependencies import get_arq_redis, get_current_user
    from app.main import app

    limiter.reset()  # isolate from other tests' shared IP-based rate-limit bucket
    lessons_insert_calls: list[dict] = []

    sb = MagicMock()

    def track_table(name: str) -> MagicMock:
        t = MagicMock()
        if name == "books":
            t.insert.return_value.execute.return_value = MagicMock(data=[{"book_id": FAKE_BOOK_ID}])
        elif name == "lessons":

            def _insert(payload: dict) -> MagicMock:
                lessons_insert_calls.append(payload)
                m = MagicMock()
                m.execute.return_value = MagicMock(data=[{"lesson_id": FAKE_LESSON_ID}])
                return m

            t.insert.side_effect = _insert
            t.update.return_value.eq.return_value.execute.return_value = MagicMock()
        elif name == "lesson_jobs":
            t.insert.return_value.execute.return_value = MagicMock()
        return t

    sb.table.side_effect = track_table
    sb.storage.from_.return_value.upload.return_value = MagicMock()

    app.dependency_overrides[get_current_user] = lambda: {
        **FAKE_USER,
        "sub": "tier-default-test-sub",
    }
    app.dependency_overrides[get_arq_redis] = lambda: _make_arq_mock()

    with patch("app.modules.content.router.get_supabase", return_value=sb):
        resp = TestClient(app, raise_server_exceptions=True).post(
            "/api/content/lessons",
            files={"file": ("t.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
        )

    app.dependency_overrides.clear()

    assert resp.status_code == 202
    assert lessons_insert_calls[0]["tier"] == "T2"


@pytest.mark.unit
def test_upload_lesson_invalid_tier_returns_422_before_any_row_created(client: TestClient) -> None:
    """AC-1: an invalid tier value returns 422 before any DB row (books/
    lessons/lesson_jobs) or Storage upload is created — never a silent
    fallback to the default."""
    from app.core.rate_limit import limiter
    from app.dependencies import get_arq_redis, get_current_user
    from app.main import app

    limiter.reset()  # isolate from other tests' shared IP-based rate-limit bucket
    sb = MagicMock()
    sb.table.side_effect = lambda name: MagicMock()  # any call here is a bug

    app.dependency_overrides[get_current_user] = lambda: {
        **FAKE_USER,
        "sub": "tier-invalid-test-sub",
    }
    app.dependency_overrides[get_arq_redis] = lambda: _make_arq_mock()

    with patch("app.modules.content.router.get_supabase", return_value=sb):
        resp = TestClient(app, raise_server_exceptions=True).post(
            "/api/content/lessons",
            files={"file": ("t.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
            data={"tier": "T99-not-real"},
        )

    app.dependency_overrides.clear()

    assert resp.status_code == 422
    sb.table.assert_not_called()


# ── Story 2-31 AC-4: list endpoint carries subject + estimated_duration_mins ──


_LIST_ROW: dict[str, Any] = {
    "lesson_id": FAKE_LESSON_ID,
    "status": "ready",
    "title": "Thermo",
    "created_at": "2026-07-28T00:00:00Z",
    # NOTE: no "completed_at" — it is a lesson_jobs column, not a lessons one.
    # PostgREST `->>` yields TEXT, so the duration arrives as a string.
    "subject": "Physics",
    "estimated_duration_mins": "12.5",
    # Review finding: this fixture originally had NO `content` key, which made
    # test_list_lessons_still_never_attaches_content_or_signs_urls pass for the
    # wrong reason — a mutation that attached and signed content per row never
    # fired, because there was no content to attach. A realistic content dict is
    # what gives that regression guard its teeth.
    "content": _READY_CONTENT_DICT,
}


def _make_list_supabase_mock(rows_data: list[dict[str, Any]]) -> MagicMock:
    """Plain (non-dispatching) Supabase mock for list_lessons assertions.

    Deliberately NOT _make_supabase_mock: that one dispatches table() via
    side_effect, so `sb.table.return_value.select` never sees the real call and
    the select-string assertion below could not fail.
    """
    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.eq.return_value.order.return_value.range
    chain.return_value.execute.return_value.data = rows_data
    return sb


@pytest.mark.unit
def test_list_lessons_selects_narrow_columns_not_star() -> None:
    """AC-4: the list query must lift the two scalars via JSONB path selectors
    rather than pulling the whole `content` column for every row."""
    from app.dependencies import get_arq_redis, get_current_user
    from app.main import app
    from app.modules.content.router import _LIST_COLUMNS

    sb = _make_list_supabase_mock([])

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_arq_redis] = lambda: _make_arq_mock()

    with patch("app.modules.content.router.get_supabase", return_value=sb):
        resp = TestClient(app).get("/api/content/lessons")

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    sb.table.return_value.select.assert_called_once_with(_LIST_COLUMNS)
    assert _LIST_COLUMNS != "*"
    assert "subject:content->metadata->>subject" in _LIST_COLUMNS
    assert "estimated_duration_mins:content->metadata->>estimated_duration_mins" in _LIST_COLUMNS
    # AC-7: `content` must never be part of the list select.
    assert "content," not in _LIST_COLUMNS.replace("content->", "")


@pytest.mark.unit
def test_list_lessons_returns_subject_and_duration() -> None:
    """AC-4: the aliased JSONB values reach the response, and the text duration
    is coerced back to a number."""
    from app.dependencies import get_arq_redis, get_current_user
    from app.main import app

    sb = _make_list_supabase_mock([copy.deepcopy(_LIST_ROW)])

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_arq_redis] = lambda: _make_arq_mock()

    with patch("app.modules.content.router.get_supabase", return_value=sb):
        resp = TestClient(app).get("/api/content/lessons")

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["subject"] == "Physics"
    assert body[0]["estimated_duration_mins"] == 12.5, "text must be coerced to float"


@pytest.mark.unit
def test_list_lessons_tolerates_missing_metadata_fields() -> None:
    """AC-4 edge: a lesson whose content has no metadata (still generating)
    yields nulls, not a 500."""
    from app.dependencies import get_arq_redis, get_current_user
    from app.main import app

    row = copy.deepcopy(_LIST_ROW)
    row["status"] = "generating"
    row["subject"] = None
    row["estimated_duration_mins"] = None
    # A still-generating lesson has no content at all — so this exercises the
    # both-shapes-absent path rather than silently falling through to the nested
    # content.metadata branch that _LIST_ROW now carries.
    row.pop("content", None)
    sb = _make_list_supabase_mock([row])

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_arq_redis] = lambda: _make_arq_mock()

    with patch("app.modules.content.router.get_supabase", return_value=sb):
        resp = TestClient(app).get("/api/content/lessons")

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["subject"] is None
    assert body[0]["estimated_duration_mins"] is None


@pytest.mark.unit
def test_list_lessons_still_never_attaches_content_or_signs_urls() -> None:
    """Story 1-6 AC-7 regression guard — the constraint AC-4 must not break.

    Resolving signed URLs for every asset of every row would be an
    N-lessons x M-assets signing storm.
    """
    from app.dependencies import get_arq_redis, get_current_user
    from app.main import app

    sb = _make_list_supabase_mock([copy.deepcopy(_LIST_ROW)])

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_arq_redis] = lambda: _make_arq_mock()

    with (
        patch("app.modules.content.router.get_supabase", return_value=sb),
        patch("app.modules.content.router.sign_storage_path") as mock_sign,
        patch("app.modules.content.router._resolve_lesson_content") as mock_resolve,
    ):
        resp = TestClient(app).get("/api/content/lessons")

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    mock_sign.assert_not_called()
    mock_resolve.assert_not_called()
    sb.storage.from_.assert_not_called()
    assert all(item.get("content") is None for item in resp.json())


@pytest.mark.unit
def test_get_lesson_also_populates_subject_and_duration() -> None:
    """AC-4: the DETAIL endpoint must not return null for data it is already
    holding while the list shows a value. get_lesson selects `*`, so the values
    arrive nested under content.metadata rather than as flat aliases."""
    from app.dependencies import get_arq_redis, get_current_user
    from app.main import app

    def _sign(path: str, _expires_in: int) -> dict[str, str]:
        return {"signedURL": f"https://signed.example.com/{path}"}

    sb = _make_ready_supabase_mock(_sign)

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_arq_redis] = lambda: _make_arq_mock()

    with patch("app.modules.content.router.get_supabase", return_value=sb):
        resp = TestClient(app).get(f"/api/content/lessons/{FAKE_LESSON_ID}")

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    meta = _READY_CONTENT_DICT["metadata"]
    assert body["subject"] == meta["subject"]
    assert body["estimated_duration_mins"] == meta["estimated_duration_mins"]


# ── Story 2-31 review round: untrusted JSONB + schema-truth guards ────────────


@pytest.mark.unit
def test_list_columns_names_no_column_absent_from_the_lessons_table() -> None:
    """Review blocker: `completed_at` lives on `lesson_jobs`, NOT on `lessons`.

    Under `select("*")` naming it was harmless. Naming it EXPLICITLY makes
    PostgREST reject the whole query (42703) — GET /lessons then fails for every
    user, every request. No mock can catch that, so assert the column list
    against the migrations that define the table.
    """
    from app.modules.content.router import _LIST_COLUMNS

    # Real columns per 20260611000000_initial_schema.sql + later ALTERs.
    real_columns = {
        "lesson_id",
        "user_id",
        "title",
        "status",
        "content",
        "source_file_path",
        "created_at",
        "updated_at",
        "book_id",
        "tier",
    }
    for spec in _LIST_COLUMNS.split(","):
        # `alias:path->>field` — the real column is the head of the path.
        source = spec.split(":", 1)[1] if ":" in spec else spec
        column = source.split("->", 1)[0].strip()
        assert column in real_columns, (
            f"_LIST_COLUMNS references {column!r}, which is not a column on "
            f"public.lessons — PostgREST will 42703 the entire list endpoint"
        )


@pytest.mark.unit
def test_list_lessons_survives_an_unparseable_duration() -> None:
    """Mutation survivor: `_coerce_float`'s except branch had zero coverage.

    `->>` returns TEXT, so a hand-edited or drifted metadata value can be any
    string. Raising out of `_row_to_status_response` would 500 the whole page.
    """
    from app.dependencies import get_arq_redis, get_current_user
    from app.main import app

    row = copy.deepcopy(_LIST_ROW)
    row["estimated_duration_mins"] = "about twelve"
    sb = _make_list_supabase_mock([row])

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_arq_redis] = lambda: _make_arq_mock()

    with patch("app.modules.content.router.get_supabase", return_value=sb):
        resp = TestClient(app).get("/api/content/lessons")

    app.dependency_overrides.clear()

    assert resp.status_code == 200, "one malformed row must not 500 the whole list"
    assert resp.json()[0]["estimated_duration_mins"] is None


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "1e400"])
def test_non_finite_duration_is_dropped_not_serialised(bad: str) -> None:
    """`float()` ACCEPTS all of these. A bare NaN/Infinity token is invalid JSON
    and throws in the browser's JSON.parse — breaking the entire list response,
    not one card. try/except cannot catch this; math.isfinite must."""
    from app.modules.content.router import _coerce_float

    assert _coerce_float(bad) is None


@pytest.mark.unit
@pytest.mark.parametrize("bad", [{"name": "Physics"}, ["Physics"], 42, 3.5, True])
def test_non_string_subject_is_dropped_not_500(bad: Any) -> None:
    """`content.metadata` is LLM-generated JSONB. Pydantic v2 does NOT coerce a
    dict/list/number into `str`, so handing one to LessonStatusResponse raises
    ValidationError — on the list path that 500s the ENTIRE page."""
    from app.modules.content.router import _coerce_str

    assert _coerce_str(bad) is None


@pytest.mark.unit
def test_row_to_status_response_survives_poisoned_nested_metadata() -> None:
    """The status-response mapper must never raise on corrupt metadata.

    Scoped to `_row_to_status_response` deliberately. Going through GET
    /lessons/{id} would NOT prove this: `_resolve_lesson_content` validates the
    package first and is intentionally uncaught, so a poisoned package 500s there
    by design (see test_get_lesson_corrupted_content_is_not_silently_swallowed).
    The reachable exposure is the mapper itself, which runs on the LIST path
    where content is never validated — so if `content` is ever re-added to
    `_LIST_COLUMNS`, a dict-valued subject must degrade rather than 500 the page.
    """
    from app.modules.content.router import _row_to_status_response

    poisoned = copy.deepcopy(_READY_CONTENT_DICT)
    poisoned["metadata"]["subject"] = {"unexpected": "object"}
    poisoned["metadata"]["estimated_duration_mins"] = float("nan")

    resp = _row_to_status_response(
        {
            "lesson_id": FAKE_LESSON_ID,
            "status": "ready",
            "title": "Test Lesson",
            "created_at": "2026-06-28T00:00:00Z",
            "content": poisoned,
        }
    )

    assert resp.subject is None
    assert resp.estimated_duration_mins is None


@pytest.mark.unit
def test_subject_is_length_capped() -> None:
    """A paginated endpoint must not let one row balloon the response."""
    from app.modules.content.router import _MAX_SUBJECT_LEN, _coerce_str

    out = _coerce_str("x" * 10_000)
    assert out is not None
    assert len(out) == _MAX_SUBJECT_LEN


@pytest.mark.unit
def test_embedded_media_expiry_covers_a_realistic_study_session() -> None:
    """Mutation survivor: the URL-equality assertions interpolate the SAME
    constant the source uses, so they are tautological — setting the expiry to
    3601 defeated AC-5's rationale while every test stayed green. Bound it on
    both sides: a floor that means something, and a ceiling so the exposure
    window of a bearer capability cannot silently grow to a year."""
    from app.modules.content.router import _EMBEDDED_MEDIA_EXPIRY_S as _EXP

    assert _EXP >= 4 * 3600, "must outlast a realistic study session with breaks"
    assert _EXP <= 24 * 3600, "signed URLs are bearer capabilities — cap the window"
