"""
Unit tests for the media module router (`GET /api/media/signed-url`).

Mocks: Supabase client, JWT auth dependency. External I/O (network, storage)
is fully mocked — no real Supabase Storage call is ever made.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

ClientFactory = Callable[..., TestClient]

FAKE_USER: dict[str, Any] = {
    "sub": "550e8400-e29b-41d4-a716-446655440000",
    "email": "test@example.com",
    "role": "authenticated",
}
OTHER_USER: dict[str, Any] = {**FAKE_USER, "sub": "other-user-uuid-not-a-real-uuid"}

FAKE_LESSON_ID = "22222222-2222-2222-2222-222222222222"
FAKE_PATH = f"{FAKE_LESSON_ID}/seg-01.mp3"


def _make_supabase_mock(
    lesson_owner: str = FAKE_USER["sub"],
    lesson_exists: bool = True,
    signed_url: str = "https://supabase.example.com/storage/v1/object/sign/lesson-audio/seg-01.mp3?token=abc",
) -> MagicMock:
    lessons_mock = MagicMock()
    row = {"user_id": lesson_owner} if lesson_exists else None
    lessons_select = lessons_mock.select.return_value.eq.return_value.maybe_single
    lessons_select.return_value.execute.return_value.data = row

    sb = MagicMock()
    sb.table.side_effect = lambda name: {"lessons": lessons_mock}.get(name, MagicMock())
    sb.storage.from_.return_value.create_signed_url.return_value = {"signedURL": signed_url}
    return sb


@pytest.fixture()
def client_factory() -> Iterator[ClientFactory]:
    from app.dependencies import get_current_user
    from app.main import app

    def _make(sb_mock: MagicMock, user: dict[str, Any] = FAKE_USER) -> TestClient:
        app.dependency_overrides[get_current_user] = lambda: user
        return TestClient(app, raise_server_exceptions=True)

    yield _make
    app.dependency_overrides.clear()


# ── Bucket allowlist (existing behavior — regression only) ────────────────────


@pytest.mark.unit
def test_signed_url_400_disallowed_bucket(client_factory: ClientFactory) -> None:
    sb = _make_supabase_mock()
    client = client_factory(sb)
    with patch("app.modules.media.router.get_supabase", return_value=sb):
        resp = client.get(
            "/api/media/signed-url", params={"bucket": "not-a-real-bucket", "path": FAKE_PATH}
        )
    assert resp.status_code == 400


# ── AC-1: ownership-verified signing ──────────────────────────────────────────


@pytest.mark.unit
def test_signed_url_404_wrong_owner(client_factory: ClientFactory) -> None:
    sb = _make_supabase_mock(lesson_owner=FAKE_USER["sub"])
    client = client_factory(sb, user=OTHER_USER)
    with patch("app.modules.media.router.get_supabase", return_value=sb):
        resp = client.get(
            "/api/media/signed-url", params={"bucket": "lesson-audio", "path": FAKE_PATH}
        )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Lesson not found"


@pytest.mark.unit
def test_signed_url_404_lesson_not_found(client_factory: ClientFactory) -> None:
    sb = _make_supabase_mock(lesson_exists=False)
    client = client_factory(sb)
    with patch("app.modules.media.router.get_supabase", return_value=sb):
        resp = client.get(
            "/api/media/signed-url", params={"bucket": "lesson-audio", "path": FAKE_PATH}
        )
    assert resp.status_code == 404
    # Identical message/shape to the wrong-owner case (AC-1) — never
    # distinguish "doesn't exist" from "not yours" (would leak existence).
    assert resp.json()["detail"] == "Lesson not found"


# ── AC-2: malformed path handling ─────────────────────────────────────────────


@pytest.mark.unit
def test_signed_url_404_no_slash_in_path(client_factory: ClientFactory) -> None:
    sb = _make_supabase_mock()
    client = client_factory(sb)
    with patch("app.modules.media.router.get_supabase", return_value=sb):
        resp = client.get(
            "/api/media/signed-url", params={"bucket": "lesson-audio", "path": "no-slash-here.mp3"}
        )
    assert resp.status_code == 404
    sb.table.assert_not_called()


@pytest.mark.unit
def test_signed_url_404_non_uuid_lesson_id_prefix(client_factory: ClientFactory) -> None:
    sb = _make_supabase_mock()
    client = client_factory(sb)
    with patch("app.modules.media.router.get_supabase", return_value=sb):
        resp = client.get(
            "/api/media/signed-url",
            params={"bucket": "lesson-audio", "path": "not-a-uuid/seg-01.mp3"},
        )
    assert resp.status_code == 404
    sb.table.assert_not_called()


# ── AC-3: real signing call ───────────────────────────────────────────────────


@pytest.mark.unit
def test_signed_url_200_success(client_factory: ClientFactory) -> None:
    sb = _make_supabase_mock()
    client = client_factory(sb)
    with patch("app.modules.media.router.get_supabase", return_value=sb):
        resp = client.get(
            "/api/media/signed-url",
            params={"bucket": "lesson-audio", "path": FAKE_PATH, "expires_in": 1800},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert (
        body["signed_url"]
        == "https://supabase.example.com/storage/v1/object/sign/lesson-audio/seg-01.mp3?token=abc"
    )
    assert body["expires_in"] == 1800
    sb.storage.from_.return_value.create_signed_url.assert_called_once_with(FAKE_PATH, 1800)


@pytest.mark.unit
def test_signed_url_404_storage_object_missing(client_factory: ClientFactory) -> None:
    """The storage backend raising (object doesn't exist) surfaces as 404, not 500."""
    sb = _make_supabase_mock()
    sb.storage.from_.return_value.create_signed_url.side_effect = RuntimeError("Object not found")
    client = client_factory(sb)
    with patch("app.modules.media.router.get_supabase", return_value=sb):
        resp = client.get(
            "/api/media/signed-url", params={"bucket": "lesson-audio", "path": FAKE_PATH}
        )
    assert resp.status_code == 404


@pytest.mark.unit
def test_signed_url_404_storage_response_none_signed_url(
    client_factory: ClientFactory,
) -> None:
    """A storage response with a None-valued key 404s rather than
    returning a null signed_url as if it were success."""
    sb = _make_supabase_mock()
    sb.storage.from_.return_value.create_signed_url.return_value = {"signedURL": None}
    client = client_factory(sb)
    with patch("app.modules.media.router.get_supabase", return_value=sb):
        resp = client.get(
            "/api/media/signed-url", params={"bucket": "lesson-audio", "path": FAKE_PATH}
        )
    assert resp.status_code == 404


@pytest.mark.unit
def test_signed_url_404_storage_response_missing_signed_url_key(
    client_factory: ClientFactory,
) -> None:
    """A storage response entirely missing the expected key raises KeyError
    internally, caught by the broad except and 404'd rather than
    surfacing as an unhandled 500."""
    sb = _make_supabase_mock()
    sb.storage.from_.return_value.create_signed_url.return_value = {}
    client = client_factory(sb)
    with patch("app.modules.media.router.get_supabase", return_value=sb):
        resp = client.get(
            "/api/media/signed-url", params={"bucket": "lesson-audio", "path": FAKE_PATH}
        )
    assert resp.status_code == 404


# ── AC-4: existing expires_in bounds unchanged ────────────────────────────────


@pytest.mark.unit
def test_signed_url_422_expires_in_out_of_bounds(client_factory: ClientFactory) -> None:
    sb = _make_supabase_mock()
    client = client_factory(sb)
    with patch("app.modules.media.router.get_supabase", return_value=sb):
        resp = client.get(
            "/api/media/signed-url",
            params={"bucket": "lesson-audio", "path": FAKE_PATH, "expires_in": 100000},
        )
    assert resp.status_code == 422
