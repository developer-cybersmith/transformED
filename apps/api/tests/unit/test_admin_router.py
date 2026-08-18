"""
Unit tests for the admin module router (Story 2-25).

Mocks: Supabase client, Redis client, JWT auth dependency, and settings
(for the ADMIN_EMAILS allowlist). No real network I/O.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
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


@pytest.mark.unit
def test_list_jobs_400_invalid_status_filter(client_factory: ClientFactory) -> None:
    sb = MagicMock()
    client = client_factory()
    with patch("app.modules.admin.router.get_supabase", return_value=sb):
        resp = client.get("/api/admin/jobs", params={"status_filter": "not-a-real-status"})
    assert resp.status_code == 400
    sb.table.assert_not_called()


@pytest.mark.unit
@pytest.mark.parametrize("limit", [0, -1])
def test_list_jobs_422_limit_out_of_bounds(client_factory: ClientFactory, limit: int) -> None:
    sb = MagicMock()
    client = client_factory()
    with patch("app.modules.admin.router.get_supabase", return_value=sb):
        resp = client.get("/api/admin/jobs", params={"limit": limit})
    assert resp.status_code == 422


@pytest.mark.unit
def test_list_jobs_422_offset_negative(client_factory: ClientFactory) -> None:
    sb = MagicMock()
    client = client_factory()
    with patch("app.modules.admin.router.get_supabase", return_value=sb):
        resp = client.get("/api/admin/jobs", params={"offset": -1})
    assert resp.status_code == 422


# ── GET /jobs/{job_id} ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_get_job_200_admin(client_factory: ClientFactory) -> None:
    job_id = "11111111-1111-1111-1111-111111111111"
    sb = MagicMock()
    row = {
        "job_id": job_id,
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
        resp = client.get(f"/api/admin/jobs/{job_id}")
    assert resp.status_code == 200
    assert resp.json()["job_id"] == job_id


@pytest.mark.unit
def test_get_job_404_not_found(client_factory: ClientFactory) -> None:
    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.eq.return_value.maybe_single.return_value
    chain.execute.return_value.data = None
    client = client_factory()
    with patch("app.modules.admin.router.get_supabase", return_value=sb):
        resp = client.get("/api/admin/jobs/22222222-2222-2222-2222-222222222222")
    assert resp.status_code == 404


@pytest.mark.unit
def test_get_job_404_malformed_uuid_never_hits_db(client_factory: ClientFactory) -> None:
    """Story 2-25 code review: a non-UUID job_id must 404 cleanly, matching
    the established pattern in content/router.py:get_lesson, instead of
    risking an unhandled 500 from Postgres's uuid type cast."""
    sb = MagicMock()
    client = client_factory()
    with patch("app.modules.admin.router.get_supabase", return_value=sb):
        resp = client.get("/api/admin/jobs/does-not-exist")
    assert resp.status_code == 404
    sb.table.assert_not_called()


# ── narration_capped (Story 3-37 Round-2 review, Scale & Load Hunter) ──────────


@pytest.mark.unit
def test_list_jobs_surfaces_narration_capped_true(client_factory: ClientFactory) -> None:
    """Before this field existed, node_outputs['narration_cap_applied'] was
    fetched (select("*")) but always discarded — no admin response ever
    distinguished a lesson with silently-zeroed trailing narration segments
    from a fully-narrated one. Must now surface as narration_capped=True."""
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
        "node_outputs": {
            "narration_cap_applied": {
                "capped": True,
                "original_total_chars": 16000,
                "capped_total_chars": 10000,
                "affected_segment_ids": ["section_2_x", "section_3_y"],
            }
        },
    }
    chain = sb.table.return_value.select.return_value.order.return_value.range.return_value
    chain.execute.return_value.data = [row]
    client = client_factory()
    with patch("app.modules.admin.router.get_supabase", return_value=sb):
        resp = client.get("/api/admin/jobs")
    assert resp.status_code == 200
    assert resp.json()[0]["narration_capped"] is True


@pytest.mark.unit
@pytest.mark.parametrize(
    "node_outputs",
    [
        None,
        {},
        {"narration_cap_applied": {"capped": False, "affected_segment_ids": []}},
        {"narration_cap_applied": "not-a-dict"},
        {"tts_node": []},  # job never reached the cap-writing code at all
    ],
)
def test_list_jobs_narration_capped_false_when_absent_or_not_capped(
    client_factory: ClientFactory, node_outputs: dict[str, Any] | None
) -> None:
    sb = MagicMock()
    row = {
        "job_id": "job-1",
        "lesson_id": "lesson-1",
        "status": "completed",
        "created_at": "2026-07-27T00:00:00Z",
        "started_at": None,
        "completed_at": None,
        "error": None,
        "cost_usd": None,
        "lessons": {"user_id": "user-1"},
        "node_outputs": node_outputs,
    }
    chain = sb.table.return_value.select.return_value.order.return_value.range.return_value
    chain.execute.return_value.data = [row]
    client = client_factory()
    with patch("app.modules.admin.router.get_supabase", return_value=sb):
        resp = client.get("/api/admin/jobs")
    assert resp.status_code == 200
    assert resp.json()[0]["narration_capped"] is False


@pytest.mark.unit
def test_get_job_surfaces_narration_capped(client_factory: ClientFactory) -> None:
    job_id = "11111111-1111-1111-1111-111111111111"
    sb = MagicMock()
    row = {
        "job_id": job_id,
        "lesson_id": "lesson-1",
        "status": "completed",
        "created_at": "2026-07-27T00:00:00Z",
        "started_at": "2026-07-27T00:00:01Z",
        "completed_at": "2026-07-27T00:05:00Z",
        "error": None,
        "cost_usd": 0.5,
        "lessons": {"user_id": "user-1"},
        "node_outputs": {"narration_cap_applied": {"capped": True}},
    }
    chain = sb.table.return_value.select.return_value.eq.return_value.maybe_single.return_value
    chain.execute.return_value.data = row
    client = client_factory()
    with patch("app.modules.admin.router.get_supabase", return_value=sb):
        resp = client.get(f"/api/admin/jobs/{job_id}")
    assert resp.status_code == 200
    assert resp.json()["narration_capped"] is True


# ── GET /costs ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_get_cost_report_aggregates_by_user(client_factory: ClientFactory) -> None:
    # Story 2-25 code review: filtering is now server-side (an inner join +
    # .gte on the embedded resource), so every row the mock returns is
    # already "in period" — there is no client-side date exclusion to test
    # here anymore (see test_get_cost_report_filters_server_side below for
    # that behavior).
    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.gte.return_value.limit.return_value
    chain.execute.return_value.data = [
        {"cost_usd": 1.0, "lesson_id": "l1", "lessons": {"user_id": "u1"}},
        {"cost_usd": 2.0, "lesson_id": "l2", "lessons": {"user_id": "u1"}},
        {"cost_usd": 5.0, "lesson_id": "l3", "lessons": {"user_id": "u2"}},
    ]
    client = client_factory()
    with patch("app.modules.admin.router.get_supabase", return_value=sb):
        resp = client.get("/api/admin/costs", params={"period": "today"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_cost_usd"] == pytest.approx(8.0)
    assert body["lessons_processed"] == 3
    assert "by_provider" not in body
    assert body["truncated"] is False
    by_user = {row["user_id"]: row["cost_usd"] for row in body["by_user"]}
    assert by_user == {"u1": pytest.approx(3.0), "u2": pytest.approx(5.0)}


@pytest.mark.unit
def test_get_cost_report_filters_server_side_via_inner_join(client_factory: ClientFactory) -> None:
    """Story 2-25 code review fix: the period filter must be pushed to
    PostgREST via `lessons!inner(...)` + `.gte("lessons.created_at", ...)`,
    not fetched unbounded and filtered in Python."""
    sb = MagicMock()
    select_chain = sb.table.return_value.select
    chain = select_chain.return_value.gte.return_value.limit.return_value
    chain.execute.return_value.data = []
    client = client_factory()
    with patch("app.modules.admin.router.get_supabase", return_value=sb):
        resp = client.get("/api/admin/costs", params={"period": "this_week"})
    assert resp.status_code == 200
    select_chain.assert_called_once_with("cost_usd, lesson_id, lessons!inner(user_id, created_at)")
    gte_call = select_chain.return_value.gte.call_args
    assert gte_call.args[0] == "lessons.created_at"


@pytest.mark.unit
def test_get_cost_report_applies_row_limit(client_factory: ClientFactory) -> None:
    """D59(a): the query must carry `.limit(_COST_REPORT_ROW_LIMIT)` after
    `.gte(...)` — this is the fix for the previously-unbounded materialise-every-
    row-for-the-period query flagged in docs/DEFECT-REGISTER.md."""
    from app.modules.admin.router import _COST_REPORT_ROW_LIMIT

    sb = MagicMock()
    gte_chain = sb.table.return_value.select.return_value.gte
    gte_chain.return_value.limit.return_value.execute.return_value.data = []
    client = client_factory()
    with patch("app.modules.admin.router.get_supabase", return_value=sb):
        resp = client.get("/api/admin/costs", params={"period": "today"})
    assert resp.status_code == 200
    gte_chain.return_value.limit.assert_called_once_with(_COST_REPORT_ROW_LIMIT)


@pytest.mark.unit
def test_get_cost_report_not_truncated_when_under_limit(client_factory: ClientFactory) -> None:
    """D59(a): fewer rows than the limit -> truncated=False (the common,
    real-scale case today)."""
    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.gte.return_value.limit.return_value
    chain.execute.return_value.data = [
        {"cost_usd": 1.0, "lesson_id": "l1", "lessons": {"user_id": "u1"}},
    ]
    client = client_factory()
    with patch("app.modules.admin.router.get_supabase", return_value=sb):
        resp = client.get("/api/admin/costs", params={"period": "today"})
    assert resp.status_code == 200
    assert resp.json()["truncated"] is False


@pytest.mark.unit
def test_get_cost_report_truncated_when_row_limit_hit(client_factory: ClientFactory) -> None:
    """D59(a): exactly `_COST_REPORT_ROW_LIMIT` rows returned -> truncated=True,
    the explicit surfaced-degradation signal (never a silent drop) that more
    rows may exist beyond the fetch limit and the report may under-report
    real spend."""
    from app.modules.admin.router import _COST_REPORT_ROW_LIMIT

    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.gte.return_value.limit.return_value
    chain.execute.return_value.data = [
        {"cost_usd": 1.0, "lesson_id": f"l{i}", "lessons": {"user_id": "u1"}}
        for i in range(_COST_REPORT_ROW_LIMIT)
    ]
    client = client_factory()
    with patch("app.modules.admin.router.get_supabase", return_value=sb):
        resp = client.get("/api/admin/costs", params={"period": "today"})
    assert resp.status_code == 200
    assert resp.json()["truncated"] is True


@pytest.mark.unit
@pytest.mark.parametrize("period", ["this_week", "this_month"])
def test_get_cost_report_boundary_periods_do_not_error(
    client_factory: ClientFactory, period: str
) -> None:
    """Story 2-25 code review: this_week/this_month had zero test coverage."""
    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.gte.return_value.limit.return_value
    chain.execute.return_value.data = []
    client = client_factory()
    with patch("app.modules.admin.router.get_supabase", return_value=sb):
        resp = client.get("/api/admin/costs", params={"period": period})
    assert resp.status_code == 200
    assert resp.json()["period"] == period


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


# ── POST /jobs/{job_id}/retry (Story 3-58, S3-4) ────────────────────────────────
#
# MOCK-CONTRACT: every test below asserts real, observable outcomes (real
# response status/body fields, the exact SQL filter arguments passed to a
# mocked Supabase client, the exact _job_id string passed to a mocked ARQ
# pool) — not bare "was this called" checks. No real-dependency (integration)
# test exists yet for this endpoint end-to-end against real Supabase/ARQ —
# matching every other endpoint already in this file (list_jobs, get_job,
# get_cost_report, deep_health), none of which have one either. A real
# integration test is out of scope for this router's existing test
# conventions, not a gap this story introduces.


def _arq_pool(*, dedup: bool = False, raises: bool = False) -> AsyncMock:
    """Mock ARQ pool. By default `enqueue_job` succeeds and returns a Job
    whose `.job_id` echoes back the `_job_id` kwarg it was called with —
    matching real ARQ semantics (the returned `Job.job_id` IS the id you
    passed in). `dedup=True` simulates ARQ deduplicating the job (returns
    None). `raises=True` simulates `enqueue_job` itself raising."""
    pool = AsyncMock()
    if raises:
        pool.enqueue_job = AsyncMock(side_effect=RuntimeError("redis connection reset"))
    elif dedup:
        pool.enqueue_job = AsyncMock(return_value=None)
    else:

        async def _enqueue(*args: Any, **kwargs: Any) -> MagicMock:
            job = MagicMock()
            job.job_id = kwargs.get("_job_id")
            return job

        pool.enqueue_job = AsyncMock(side_effect=_enqueue)
    return pool


def _retry_supabase(
    job_row: dict[str, Any] | None,
    concurrent_jobs: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """Table-aware Supabase mock for retry_job — `lessons` and `lesson_jobs`
    get genuinely separate mock objects (not one shared `.table.return_value`),
    so a test can tell which table an update() call actually targeted. Review
    finding: the original single-shared-mock version could not distinguish a
    lessons update from a lesson_jobs update, so a table-name swap bug would
    have passed every existing test."""
    sb = MagicMock()
    lessons_table = MagicMock()
    lesson_jobs_table = MagicMock()

    lookup_chain = lesson_jobs_table.select.return_value.eq.return_value.maybe_single.return_value
    lookup_chain.execute.return_value.data = job_row

    concurrent_chain = (
        lesson_jobs_table.select.return_value.eq.return_value.neq.return_value.in_.return_value
    )
    concurrent_chain.execute.return_value.data = concurrent_jobs or []

    def _table(name: str) -> MagicMock:
        if name == "lessons":
            return lessons_table
        if name == "lesson_jobs":
            return lesson_jobs_table
        return MagicMock()

    sb.table.side_effect = _table
    sb.lessons_table = lessons_table
    sb.lesson_jobs_table = lesson_jobs_table
    return sb


@contextmanager
def _arq_override(pool: AsyncMock) -> Iterator[None]:
    """FastAPI resolves ALL declared dependencies before the endpoint body
    runs, so retry_job's required `arq_redis: ArqRedis` param must be
    overridden even for requests that never reach the enqueue call (e.g. the
    404/409 early-exit paths) — otherwise get_arq_redis's real 503
    ("Job queue unavailable", no app.state.arq_redis in tests) wins over
    whatever status the test is actually trying to exercise."""
    from app.dependencies import get_arq_redis
    from app.main import app

    app.dependency_overrides[get_arq_redis] = lambda: pool
    try:
        yield
    finally:
        del app.dependency_overrides[get_arq_redis]


@pytest.mark.unit
def test_retry_job_403_non_admin(client_factory: ClientFactory) -> None:
    client = client_factory(user=NON_ADMIN_USER)
    resp = client.post("/api/admin/jobs/11111111-1111-1111-1111-111111111111/retry")
    assert resp.status_code == 403


@pytest.mark.unit
def test_retry_job_404_malformed_uuid_never_hits_db(client_factory: ClientFactory) -> None:
    sb = MagicMock()
    client = client_factory()
    pool = _arq_pool()
    with patch("app.modules.admin.router.get_supabase", return_value=sb), _arq_override(pool):
        resp = client.post("/api/admin/jobs/does-not-exist/retry")
    assert resp.status_code == 404
    sb.table.assert_not_called()


@pytest.mark.unit
def test_retry_job_404_not_found(client_factory: ClientFactory) -> None:
    sb = _retry_supabase(None)
    client = client_factory()
    pool = _arq_pool()
    with patch("app.modules.admin.router.get_supabase", return_value=sb), _arq_override(pool):
        resp = client.post("/api/admin/jobs/22222222-2222-2222-2222-222222222222/retry")
    assert resp.status_code == 404


@pytest.mark.unit
@pytest.mark.parametrize("current_status", ["pending", "running", "completed"])
def test_retry_job_409_when_not_failed(client_factory: ClientFactory, current_status: str) -> None:
    job_id = "33333333-3333-3333-3333-333333333333"
    sb = _retry_supabase(
        {
            "job_id": job_id,
            "lesson_id": "lesson-1",
            "status": current_status,
            "lessons": {"user_id": "user-1"},
        }
    )
    client = client_factory()
    pool = _arq_pool()
    with patch("app.modules.admin.router.get_supabase", return_value=sb), _arq_override(pool):
        resp = client.post(f"/api/admin/jobs/{job_id}/retry")
    assert resp.status_code == 409
    assert current_status in resp.json()["detail"]


@pytest.mark.unit
@pytest.mark.parametrize("concurrent_status", ["running", "pending"])
def test_retry_job_409_when_another_job_for_lesson_is_active(
    client_factory: ClientFactory, concurrent_status: str
) -> None:
    """Review finding (Scale & Load Hunter): without this check, two
    concurrent retries (or a retry racing the original still-finishing run)
    both pass the 'failed' check, both enqueue, and content_pipeline.py's
    unconditional clear_lesson_cost() lets whichever finishes first silently
    reset the $3.00 ceiling for the other — a real cost-ceiling bypass, not
    just wasted compute. This test pins the mitigation: reject up front if
    another job for the same lesson is already active."""
    job_id = "66666666-6666-6666-6666-666666666666"
    lesson_id = "lesson-66"
    sb = _retry_supabase(
        {
            "job_id": job_id,
            "lesson_id": lesson_id,
            "status": "failed",
            "lessons": {"user_id": "user-1"},
        },
        concurrent_jobs=[{"job_id": "other-job-id", "status": concurrent_status}],
    )
    client = client_factory()
    pool = _arq_pool()
    with patch("app.modules.admin.router.get_supabase", return_value=sb), _arq_override(pool):
        resp = client.post(f"/api/admin/jobs/{job_id}/retry")
    assert resp.status_code == 409
    assert "already running or pending" in resp.json()["detail"]
    pool.enqueue_job.assert_not_awaited()
    sb.lessons_table.update.assert_not_called()
    sb.lesson_jobs_table.update.assert_not_called()


@pytest.mark.unit
def test_retry_job_202_happy_path_resets_status_and_enqueues_fresh_job_id(
    client_factory: ClientFactory,
) -> None:
    job_id = "44444444-4444-4444-4444-444444444444"
    lesson_id = "lesson-44"
    sb = _retry_supabase(
        {
            "job_id": job_id,
            "lesson_id": lesson_id,
            "status": "failed",
            "error": "boom",
            "lessons": {"user_id": "user-1"},
        }
    )
    pool = _arq_pool()
    client = client_factory()
    with patch("app.modules.admin.router.get_supabase", return_value=sb), _arq_override(pool):
        resp = client.post(f"/api/admin/jobs/{job_id}/retry")

    assert resp.status_code == 202
    body = resp.json()
    assert body["lesson_id"] == lesson_id
    assert body["status"] == "pending"
    # The response's job_id is the DB row id; arq_job_id is the id actually
    # enqueued with ARQ — the two are never the same value, and only the
    # latter can be used to look up the running job.
    assert body["arq_job_id"] != body["job_id"]

    # lessons and lesson_jobs are now genuinely separate mocks (review fix —
    # a single shared mock could not have caught a table-name swap).
    lessons_calls = list(sb.lessons_table.update.call_args_list)
    assert len(lessons_calls) == 1
    assert lessons_calls[0].args[0] == {"status": "generating"}

    jobs_calls = list(sb.lesson_jobs_table.update.call_args_list)
    assert len(jobs_calls) == 1
    assert jobs_calls[0].args[0] == {"status": "pending", "error": None}
    # The lesson_jobs write must be scoped by job_id (the real primary key),
    # never lesson_id (no unique constraint — D45 already documents
    # concurrent duplicate lesson_jobs rows for one lesson as real).
    sb.lesson_jobs_table.update.return_value.eq.assert_called_once_with("job_id", job_id)

    # node_outputs/last_node must never be touched by any update call — that
    # would silently discard the checkpoint-resume state and re-bill
    # already-completed nodes.
    all_payloads = [c.args[0] for c in lessons_calls + jobs_calls]
    assert not any("node_outputs" in p for p in all_payloads)
    assert not any("last_node" in p for p in all_payloads)

    # The ARQ _job_id must NOT be the bare "pipeline:{lesson_id}" string — a
    # fresh id per retry is what keeps the LangGraph thread_id unique
    # regardless of ARQ's own job_try reset behavior on a fresh enqueue.
    pool.enqueue_job.assert_awaited_once()
    _, kwargs = pool.enqueue_job.call_args
    assert kwargs["_job_id"] != f"pipeline:{lesson_id}"
    assert kwargs["_job_id"].startswith(f"pipeline:{lesson_id}:retry:")
    assert body["arq_job_id"] == kwargs["_job_id"]


@pytest.mark.unit
def test_retry_job_500_when_arq_deduplicates(client_factory: ClientFactory) -> None:
    job_id = "55555555-5555-5555-5555-555555555555"
    lesson_id = "lesson-55"
    sb = _retry_supabase(
        {
            "job_id": job_id,
            "lesson_id": lesson_id,
            "status": "failed",
            "lessons": {"user_id": "user-1"},
        }
    )
    pool = _arq_pool(dedup=True)  # enqueue_job returns None (deduplicated)
    client = client_factory()
    with patch("app.modules.admin.router.get_supabase", return_value=sb), _arq_override(pool):
        resp = client.post(f"/api/admin/jobs/{job_id}/retry")

    assert resp.status_code == 500
    # Must not leave the job silently stuck showing "pending" with nothing
    # actually enqueued — status is reverted to failed.
    jobs_calls = list(sb.lesson_jobs_table.update.call_args_list)
    assert any(c.args[0].get("status") == "failed" for c in jobs_calls), (
        "lesson_jobs.status must revert to 'failed' when ARQ deduplicates"
    )
    lessons_calls = list(sb.lessons_table.update.call_args_list)
    assert any(c.args[0].get("status") == "failed" for c in lessons_calls), (
        "lessons.status must revert to 'failed' when ARQ deduplicates"
    )


@pytest.mark.unit
def test_retry_job_500_when_enqueue_raises(client_factory: ClientFactory) -> None:
    """Review finding (Edge Case Hunter): enqueue_job can raise, not just
    return None — e.g. a Redis connection drop mid-call. Before this fix,
    status was already reset to generating/pending by the time that raises,
    and nothing caught it — the job would sit forever showing 'pending' with
    no worker ever picking it up, and future retries would 409 since status
    is no longer 'failed'."""
    job_id = "77777777-aaaa-bbbb-cccc-777777777777"
    lesson_id = "lesson-77"
    sb = _retry_supabase(
        {
            "job_id": job_id,
            "lesson_id": lesson_id,
            "status": "failed",
            "lessons": {"user_id": "user-1"},
        }
    )
    pool = _arq_pool(raises=True)
    client = client_factory()
    with patch("app.modules.admin.router.get_supabase", return_value=sb), _arq_override(pool):
        resp = client.post(f"/api/admin/jobs/{job_id}/retry")

    assert resp.status_code == 500
    jobs_calls = list(sb.lesson_jobs_table.update.call_args_list)
    assert any(c.args[0].get("status") == "failed" for c in jobs_calls), (
        "lesson_jobs.status must revert to 'failed' when enqueue_job raises, "
        "not stay stuck at 'pending'"
    )
    lessons_calls = list(sb.lessons_table.update.call_args_list)
    assert any(c.args[0].get("status") == "failed" for c in lessons_calls), (
        "lessons.status must revert to 'failed' when enqueue_job raises"
    )
