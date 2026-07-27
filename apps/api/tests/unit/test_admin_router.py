"""
Unit tests for the admin module router (Story 2-25).

Mocks: Supabase client, Redis client, JWT auth dependency, and settings
(for the ADMIN_EMAILS allowlist). No real network I/O.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

ClientFactory = Callable[..., TestClient]

ADMIN_USER: dict[str, Any] = {
    "sub": "550e8400-e29b-41d4-a716-446655440000",
    "email": "admin@transformed.ai",
    "role": "authenticated",
}
NON_ADMIN_USER: dict[str, Any] = {
    "sub": "660e8400-e29b-41d4-a716-446655440001",
    "email": "student@example.com",
    "role": "authenticated",
}
NO_EMAIL_USER: dict[str, Any] = {"sub": "no-email-user", "role": "authenticated"}


def _make_settings(admin_emails: list[str] | None = None) -> MagicMock:
    settings = MagicMock()
    settings.admin_emails = admin_emails if admin_emails is not None else ["admin@transformed.ai"]
    return settings


@pytest.fixture()
def client_factory() -> Iterator[ClientFactory]:
    from app.config import get_settings
    from app.dependencies import get_current_user
    from app.main import app

    def _make(
        user: dict[str, Any] = ADMIN_USER,
        admin_emails: list[str] | None = None,
    ) -> TestClient:
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_settings] = lambda: _make_settings(admin_emails)
        return TestClient(app, raise_server_exceptions=True)

    yield _make
    app.dependency_overrides.clear()


# ── require_admin gate ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_list_jobs_403_non_admin(client_factory: ClientFactory) -> None:
    client = client_factory(user=NON_ADMIN_USER)
    resp = client.get("/api/admin/jobs")
    assert resp.status_code == 403


@pytest.mark.unit
def test_list_jobs_403_no_email_claim(client_factory: ClientFactory) -> None:
    client = client_factory(user=NO_EMAIL_USER)
    resp = client.get("/api/admin/jobs")
    assert resp.status_code == 403


@pytest.mark.unit
def test_health_403_non_admin(client_factory: ClientFactory) -> None:
    client = client_factory(user=NON_ADMIN_USER)
    resp = client.get("/api/admin/health")
    assert resp.status_code == 403


# ── GET /jobs ──────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_list_jobs_200_admin(client_factory: ClientFactory) -> None:
    sb = MagicMock()
    row = {
        "job_id": "job-1",
        "lesson_id": "lesson-1",
        "status": "completed",
        "created_at": "2026-07-27T00:00:00Z",
        "started_at": "2026-07-27T00:00:01Z",
        "completed_at": "2026-07-27T00:05:00Z",
        "error": None,
        "cost_usd": 1.23,
        "lessons": {"user_id": "user-1"},
    }
    chain = sb.table.return_value.select.return_value.order.return_value.range.return_value
    chain.execute.return_value.data = [row]
    client = client_factory()
    with patch("app.modules.admin.router.get_supabase", return_value=sb):
        resp = client.get("/api/admin/jobs")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["user_id"] == "user-1"
    assert body[0]["job_id"] == "job-1"


@pytest.mark.unit
def test_list_jobs_applies_status_filter(client_factory: ClientFactory) -> None:
    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.order.return_value.range.return_value
    chain.eq.return_value.execute.return_value.data = []
    client = client_factory()
    with patch("app.modules.admin.router.get_supabase", return_value=sb):
        resp = client.get("/api/admin/jobs", params={"status_filter": "failed"})
    assert resp.status_code == 200
    chain.eq.assert_called_once_with("status", "failed")


# ── GET /jobs/{job_id} ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_get_job_200_admin(client_factory: ClientFactory) -> None:
    sb = MagicMock()
    row = {
        "job_id": "job-1",
        "lesson_id": "lesson-1",
        "status": "running",
        "created_at": "2026-07-27T00:00:00Z",
        "started_at": "2026-07-27T00:00:01Z",
        "completed_at": None,
        "error": None,
        "cost_usd": 0.5,
        "lessons": {"user_id": "user-1"},
    }
    chain = sb.table.return_value.select.return_value.eq.return_value.maybe_single.return_value
    chain.execute.return_value.data = row
    client = client_factory()
    with patch("app.modules.admin.router.get_supabase", return_value=sb):
        resp = client.get("/api/admin/jobs/job-1")
    assert resp.status_code == 200
    assert resp.json()["job_id"] == "job-1"


@pytest.mark.unit
def test_get_job_404_not_found(client_factory: ClientFactory) -> None:
    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.eq.return_value.maybe_single.return_value
    chain.execute.return_value.data = None
    client = client_factory()
    with patch("app.modules.admin.router.get_supabase", return_value=sb):
        resp = client.get("/api/admin/jobs/does-not-exist")
    assert resp.status_code == 404


# ── GET /costs ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_get_cost_report_aggregates_by_user(client_factory: ClientFactory) -> None:
    import datetime as _dt

    now_iso = _dt.datetime.now(_dt.UTC).isoformat()
    old_iso = "2020-01-01T00:00:00Z"
    sb = MagicMock()
    sb.table.return_value.select.return_value.execute.return_value.data = [
        {"cost_usd": 1.0, "lesson_id": "l1", "lessons": {"user_id": "u1", "created_at": now_iso}},
        {"cost_usd": 2.0, "lesson_id": "l2", "lessons": {"user_id": "u1", "created_at": now_iso}},
        {"cost_usd": 5.0, "lesson_id": "l3", "lessons": {"user_id": "u2", "created_at": now_iso}},
        # Outside the "today" window — must be excluded.
        {"cost_usd": 99.0, "lesson_id": "l4", "lessons": {"user_id": "u1", "created_at": old_iso}},
    ]
    client = client_factory()
    with patch("app.modules.admin.router.get_supabase", return_value=sb):
        resp = client.get("/api/admin/costs", params={"period": "today"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_cost_usd"] == pytest.approx(8.0)
    assert body["lessons_processed"] == 3
    assert "by_provider" not in body
    by_user = {row["user_id"]: row["cost_usd"] for row in body["by_user"]}
    assert by_user == {"u1": pytest.approx(3.0), "u2": pytest.approx(5.0)}


@pytest.mark.unit
def test_get_cost_report_400_invalid_period(client_factory: ClientFactory) -> None:
    sb = MagicMock()
    client = client_factory()
    with patch("app.modules.admin.router.get_supabase", return_value=sb):
        resp = client.get("/api/admin/costs", params={"period": "this_decade"})
    assert resp.status_code == 400


# ── GET /health ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_deep_health_ok(client_factory: ClientFactory) -> None:
    redis_mock = AsyncMock()
    sb = MagicMock()
    sb.table.return_value.select.return_value.limit.return_value.execute.return_value = MagicMock()
    client = client_factory()
    with (
        patch("app.modules.admin.router.get_redis", return_value=redis_mock),
        patch("app.modules.admin.router.get_supabase", return_value=sb),
    ):
        resp = client.get("/api/admin/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["redis"] == "ok"
    assert body["supabase"] == "ok"
    assert body["worker_queue_depth"] is None


@pytest.mark.unit
def test_deep_health_degraded_when_redis_down(client_factory: ClientFactory) -> None:
    redis_mock = AsyncMock()
    redis_mock.ping.side_effect = ConnectionError("redis unreachable")
    sb = MagicMock()
    sb.table.return_value.select.return_value.limit.return_value.execute.return_value = MagicMock()
    client = client_factory()
    with (
        patch("app.modules.admin.router.get_redis", return_value=redis_mock),
        patch("app.modules.admin.router.get_supabase", return_value=sb),
    ):
        resp = client.get("/api/admin/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["redis"] == "down"
    assert body["supabase"] == "ok"


@pytest.mark.unit
def test_deep_health_down_when_both_fail(client_factory: ClientFactory) -> None:
    redis_mock = AsyncMock()
    redis_mock.ping.side_effect = ConnectionError("redis unreachable")
    sb = MagicMock()
    sb.table.return_value.select.return_value.limit.return_value.execute.side_effect = RuntimeError(
        "supabase unreachable"
    )
    client = client_factory()
    with (
        patch("app.modules.admin.router.get_redis", return_value=redis_mock),
        patch("app.modules.admin.router.get_supabase", return_value=sb),
    ):
        resp = client.get("/api/admin/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "down"
    assert body["redis"] == "down"
    assert body["supabase"] == "down"
