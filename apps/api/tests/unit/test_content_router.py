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
    """Upload is INGESTION-ONLY as of book-scale Phase 3 (Story 1-10).

    It returns book_id, not lesson_id: a book is uploaded once and lessons are
    generated per chapter afterwards. This is the breaking half of decision D-A —
    `apps/web` Story 1-8 reads lesson_id off this response and must be updated
    when the Phase 6 generation endpoint lands.
    """
    resp = client.post(
        "/api/content/lessons",
        files={"file": ("chapter1.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["book_id"] == FAKE_BOOK_ID
    assert body["job_id"] == FAKE_JOB_ID
    assert body["status"] == "queued"
    assert "lesson_id" not in body, "upload must not mint a lesson — that is what Phase 3 removed"


@pytest.mark.unit
def test_upload_lesson_retries_a_transient_storage_write_error(client: TestClient) -> None:
    """D156: found live on load-test runs #9/#10 -- 100% of large (~19.7MB)
    book uploads failed with `httpcore.WriteError: EOF occurred in violation
    of protocol (_ssl.c:2427)` (a dropped TLS connection mid-upload), while
    every small-file upload succeeded. Root cause: the storage upload call
    was a bare, undecorated network call -- unlike every other network call
    in this codebase, it had zero retry protection, so one transient
    connection drop immediately failed the whole request with a 500.
    `httpx.WriteError` is already a retryable transient error per
    `core/retry.py`'s existing classification (`httpx.NetworkError`'s
    subclass) -- this asserts a request that hits it twice then succeeds on
    the third attempt still returns 202, not 500."""
    import httpx

    from app.dependencies import get_arq_redis, get_current_user, get_settings
    from app.main import app

    sb_mock = _make_supabase_mock()
    call_count = 0

    def _flaky_upload(**_kwargs: Any) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise httpx.WriteError("EOF occurred in violation of protocol (_ssl.c:2427)")
        return MagicMock()

    sb_mock.storage.from_.return_value.upload.side_effect = _flaky_upload
    arq_mock = _make_arq_mock()

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_arq_redis] = lambda: arq_mock
    app.dependency_overrides[get_settings] = _approved_settings

    try:
        with patch("app.modules.content.router.get_supabase", return_value=sb_mock):
            resp = client.post(
                "/api/content/lessons",
                files={"file": ("chapter1.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 202
    assert call_count == 3


@pytest.mark.unit
async def test_upload_lesson_concurrent_requests_do_not_serialize_on_blocking_io() -> None:
    """D138: `upload_lesson` calls the SYNCHRONOUS supabase-py client directly
    on the event loop (no `asyncio.to_thread`) -- on a single-process uvicorn,
    one upload's blocking network call stalls every OTHER concurrently
    in-flight upload for its own duration, not just its own request.

    This test puts a REAL blocking `time.sleep` (not `asyncio.sleep`) inside
    the mocked storage `upload()` call -- exactly what a real, slow network
    upload looks like to the event loop if it is never wrapped in
    `asyncio.to_thread`. Without that wrapping, N concurrent uploads take
    ~N * delay (fully serialized); with the fix, they overlap and the timing
    bound holds. Mirrors test_image_generator_node.py's
    test_concurrency_survives_a_slow_blocking_storage_upload (same defect
    class, D132), applied here to the upload endpoint (D138).

    Review finding (test-coverage): this test alone only exercises the
    storage-upload call site's concurrency, not the books-insert call site
    or either cleanup branch. The dedicated
    test_upload_lesson_books_insert_and_storage_upload_run_off_the_event_loop
    below covers the books-insert site (a direct, non-timing thread-identity
    check -- empirically, this ASGI test harness's own request-handling
    exhibits unrelated first-blocking-call serialization behavior that made a
    timing assertion on the insert call site unreliable even against
    correctly-fixed code, so a deterministic thread-identity check is used
    there instead); the two cleanup-branch call sites (ARQ-dedup 409, generic
    exception) are covered by their own dedicated tests below.
    """
    import asyncio
    import time

    import httpx

    from app.core.rate_limit import limiter
    from app.dependencies import get_arq_redis, get_current_user, get_settings
    from app.main import app

    limiter.reset()

    n_requests = 4
    upload_delay_s = 0.15

    sb = _make_supabase_mock()
    sb.storage.from_.return_value.upload.side_effect = lambda **_kwargs: time.sleep(upload_delay_s)

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_arq_redis] = lambda: _make_arq_mock()
    app.dependency_overrides[get_settings] = _approved_settings

    try:
        with patch("app.modules.content.router.get_supabase", return_value=sb):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                start = time.monotonic()
                responses = await asyncio.gather(
                    *(
                        ac.post(
                            "/api/content/lessons",
                            files={
                                "file": (
                                    f"c{i}.pdf",
                                    io.BytesIO(MINIMAL_PDF),
                                    "application/pdf",
                                )
                            },
                        )
                        for i in range(n_requests)
                    )
                )
                elapsed = time.monotonic() - start
    finally:
        app.dependency_overrides.clear()

    assert all(r.status_code == 202 for r in responses), [r.text for r in responses]
    serial_time = n_requests * upload_delay_s  # 0.6s if uploads serialize the loop
    assert elapsed < serial_time * 0.6, (
        f"elapsed={elapsed:.3f}s is not meaningfully faster than "
        f"{serial_time:.3f}s (fully-serialized-by-a-blocking-upload time) -- "
        f"upload_lesson's Supabase calls are blocking the event loop instead "
        f"of running in a thread"
    )


@pytest.mark.unit
async def test_upload_lesson_books_insert_and_storage_upload_run_off_the_event_loop() -> None:
    """D138: direct, deterministic proof (no concurrency/timing involved, so
    it cannot be flaky) that BOTH main-path blocking calls -- the books
    insert and the storage upload -- actually run via `asyncio.to_thread`,
    i.e. on a worker thread, never on the event loop's own thread.

    Review finding (test-coverage): the concurrency-timing test above only
    delays the storage upload; it cannot, on its own, prove the books-insert
    call site is wrapped too (and a timing assertion on that specific call
    site turned out to be unreliable in this ASGI test harness for reasons
    unrelated to the fix). Recording which OS thread actually executes each
    mocked call and asserting it differs from the event loop's own thread is
    a direct enough check that no timing threshold is needed at all.
    """
    import threading

    import httpx

    from app.core.rate_limit import limiter
    from app.dependencies import get_arq_redis, get_current_user, get_settings
    from app.main import app

    limiter.reset()
    event_loop_thread_id = threading.get_ident()
    seen_thread_ids: dict[str, int] = {}

    sb = _make_supabase_mock()
    real_insert_execute = sb.table("books").insert.return_value.execute

    def _record_insert() -> Any:
        seen_thread_ids["insert"] = threading.get_ident()
        return real_insert_execute.return_value

    sb.table("books").insert.return_value.execute.side_effect = _record_insert

    def _record_upload(**_kwargs: Any) -> None:
        seen_thread_ids["upload"] = threading.get_ident()

    sb.storage.from_.return_value.upload.side_effect = _record_upload

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_arq_redis] = lambda: _make_arq_mock()
    app.dependency_overrides[get_settings] = _approved_settings

    try:
        with patch("app.modules.content.router.get_supabase", return_value=sb):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.post(
                    "/api/content/lessons",
                    files={"file": ("c.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
                )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 202, resp.text
    assert seen_thread_ids.get("insert") is not None, "books insert mock was never called"
    assert seen_thread_ids.get("upload") is not None, "storage upload mock was never called"
    assert seen_thread_ids["insert"] != event_loop_thread_id, (
        "books insert ran ON the event-loop thread -- asyncio.to_thread wrapping is missing"
    )
    assert seen_thread_ids["upload"] != event_loop_thread_id, (
        "storage upload ran ON the event-loop thread -- asyncio.to_thread wrapping is missing"
    )


@pytest.mark.unit
async def test_upload_lesson_dedup_cleanup_does_not_serialize_on_blocking_io() -> None:
    """D138: the ARQ-dedup (409) cleanup branch has its OWN two blocking
    calls -- `storage.remove()` and `books.delete().execute()` -- distinct
    from the main path's insert/upload call sites and NOT exercised by
    `test_upload_lesson_concurrent_requests_do_not_serialize_on_blocking_io`
    (that test's happy-path mock never returns `job=None`, so it never
    enters this branch at all). Review finding (test-coverage): without a
    dedicated test, reverting `asyncio.to_thread` on just these two lines
    would ship silently. Forces `enqueue_job` to return `None` (ARQ's real
    dedup signal) so every request takes this branch, then puts real
    blocking sleeps in the mocked `remove()`/`delete()` calls.
    """
    import asyncio
    import time

    import httpx

    from app.core.rate_limit import limiter
    from app.dependencies import get_arq_redis, get_current_user, get_settings
    from app.main import app

    limiter.reset()

    n_requests = 4
    cleanup_delay_s = 0.1

    sb = _make_supabase_mock()
    sb.storage.from_.return_value.remove.side_effect = lambda *_a, **_kw: time.sleep(
        cleanup_delay_s
    )
    sb.table("books").delete.return_value.eq.return_value.execute.side_effect = lambda: time.sleep(
        cleanup_delay_s
    )

    arq_mock = AsyncMock()
    arq_mock.enqueue_job = AsyncMock(return_value=None)  # ARQ dedup -- triggers the 409 branch

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_arq_redis] = lambda: arq_mock
    app.dependency_overrides[get_settings] = _approved_settings

    try:
        with patch("app.modules.content.router.get_supabase", return_value=sb):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                start = time.monotonic()
                responses = await asyncio.gather(
                    *(
                        ac.post(
                            "/api/content/lessons",
                            files={
                                "file": (
                                    f"c{i}.pdf",
                                    io.BytesIO(MINIMAL_PDF),
                                    "application/pdf",
                                )
                            },
                        )
                        for i in range(n_requests)
                    )
                )
                elapsed = time.monotonic() - start
    finally:
        app.dependency_overrides.clear()

    assert all(r.status_code == 409 for r in responses), [r.text for r in responses]
    serial_time = n_requests * (2 * cleanup_delay_s)  # remove() + delete() per request
    assert elapsed < serial_time * 0.6, (
        f"elapsed={elapsed:.3f}s is not meaningfully faster than "
        f"{serial_time:.3f}s -- the ARQ-dedup cleanup branch's remove()/delete() "
        f"calls are blocking the event loop instead of running in a thread"
    )


@pytest.mark.unit
async def test_upload_lesson_exception_cleanup_does_not_serialize_on_blocking_io() -> None:
    """D138: the generic-exception cleanup branch has its OWN two blocking
    calls -- `storage.remove()` and `books.delete().execute()` -- distinct
    from both the main path and the ARQ-dedup branch, and not exercised by
    either of the other two tests. Review finding (test-coverage): without a
    dedicated test, reverting `asyncio.to_thread` on just these two lines
    would ship silently. Forces `enqueue_job` to raise (any post-insert
    failure lands here) so every request takes this branch, then puts real
    blocking sleeps in the mocked `remove()`/`delete()` calls.
    """
    import asyncio
    import time

    import httpx

    from app.core.rate_limit import limiter
    from app.dependencies import get_arq_redis, get_current_user, get_settings
    from app.main import app

    limiter.reset()

    n_requests = 4
    cleanup_delay_s = 0.1

    sb = _make_supabase_mock()
    sb.storage.from_.return_value.remove.side_effect = lambda *_a, **_kw: time.sleep(
        cleanup_delay_s
    )
    sb.table("books").delete.return_value.eq.return_value.execute.side_effect = lambda: time.sleep(
        cleanup_delay_s
    )

    arq_mock = AsyncMock()
    arq_mock.enqueue_job = AsyncMock(side_effect=RuntimeError("simulated ARQ/Redis failure"))

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_arq_redis] = lambda: arq_mock
    app.dependency_overrides[get_settings] = _approved_settings

    try:
        with patch("app.modules.content.router.get_supabase", return_value=sb):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                start = time.monotonic()
                responses = await asyncio.gather(
                    *(
                        ac.post(
                            "/api/content/lessons",
                            files={
                                "file": (
                                    f"c{i}.pdf",
                                    io.BytesIO(MINIMAL_PDF),
                                    "application/pdf",
                                )
                            },
                        )
                        for i in range(n_requests)
                    )
                )
                elapsed = time.monotonic() - start
    finally:
        app.dependency_overrides.clear()

    assert all(r.status_code == 500 for r in responses), [r.text for r in responses]
    serial_time = n_requests * (2 * cleanup_delay_s)  # remove() + delete() per request
    assert elapsed < serial_time * 0.6, (
        f"elapsed={elapsed:.3f}s is not meaningfully faster than "
        f"{serial_time:.3f}s -- the generic-exception cleanup branch's "
        f"remove()/delete() calls are blocking the event loop instead of "
        f"running in a thread"
    )


@pytest.mark.unit
def test_upload_creates_a_book_and_no_lesson(client: TestClient) -> None:
    """AC20 — upload stops creating `lessons` and `lesson_jobs` rows entirely.

    Before Phase 3 the order was books -> lessons -> lesson_jobs. Now it is books
    alone; a lesson is created later, per chapter.
    """
    from app.core.rate_limit import limiter
    from app.dependencies import get_arq_redis, get_current_user
    from app.main import app

    limiter.reset()
    inserted: list[str] = []
    sb = MagicMock()

    def track_table(name: str) -> MagicMock:
        t = MagicMock()
        resp = MagicMock()
        resp.data = [{"book_id": FAKE_BOOK_ID}] if name == "books" else []
        t.insert.return_value.execute.side_effect = lambda: (inserted.append(name), resp)[1]
        t.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        t.delete.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        return t

    sb.table.side_effect = track_table
    arq = MagicMock()
    arq.enqueue_job = AsyncMock(return_value=MagicMock(job_id=FAKE_JOB_ID))

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_arq_redis] = lambda: arq
    try:
        with patch("app.modules.content.router.get_supabase", return_value=sb):
            resp = client.post(
                "/api/content/lessons",
                files={"file": ("c.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
            )
        assert resp.status_code == 202
        assert inserted == ["books"], f"expected only a books insert, got {inserted}"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.unit
def test_upload_enqueues_book_ingest_not_the_generation_pipeline(client: TestClient) -> None:
    """AC20 — the 11-node pipeline is no longer triggered by upload. Detection is
    a separate, cheap job; generation happens per chapter from Phase 6."""
    from app.core.rate_limit import limiter
    from app.dependencies import get_arq_redis, get_current_user
    from app.main import app

    limiter.reset()
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.return_value = MagicMock(
        data=[{"book_id": FAKE_BOOK_ID}]
    )
    arq = MagicMock()
    arq.enqueue_job = AsyncMock(return_value=MagicMock(job_id=FAKE_JOB_ID))

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_arq_redis] = lambda: arq
    try:
        with patch("app.modules.content.router.get_supabase", return_value=sb):
            client.post(
                "/api/content/lessons",
                files={"file": ("c.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
            )
        job_name = arq.enqueue_job.call_args.args[0]
        assert job_name == "book_ingest_job", f"upload enqueued {job_name!r}"
        # storage_path is passed explicitly, not rebuilt inside the job
        assert arq.enqueue_job.call_args.args[1] == FAKE_BOOK_ID
        assert FAKE_BOOK_ID in arq.enqueue_job.call_args.args[2]
    finally:
        app.dependency_overrides.clear()


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
    # Review Finding (Story 5-4, AC Completeness): AC1's own text requires the
    # header to be "present AND parseable as an integer number of seconds" --
    # presence alone doesn't prove that. A regression that made Retry-After a
    # non-numeric or malformed string would not have been caught before this.
    retry_after_seconds = int(resp.headers["Retry-After"])
    assert retry_after_seconds >= 0


# ── Story S2-LM3: tier param ────────────────────────────────────────────────


_LIST_ROW: dict[str, Any] = {
    "lesson_id": FAKE_LESSON_ID,
    "status": "ready",
    "title": "Thermo",
    "created_at": "2026-07-28T00:00:00Z",
    # NOTE: no "completed_at" â€” it is a lesson_jobs column, not a lessons one.
    # PostgREST `->>` yields TEXT, so the duration arrives as a string.
    "subject": "Physics",
    "estimated_duration_mins": "12.5",
    # Review finding: this fixture originally had NO `content` key, which made
    # test_list_lessons_still_never_attaches_content_or_signs_urls pass for the
    # wrong reason â€” a mutation that attached and signed content per row never
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
def test_upload_rejects_tier_with_422(client: TestClient) -> None:
    """AC21 / decision D-B — `tier` is no longer accepted on upload.

    A book has no tier; it is chosen per chapter at generation time. Rejecting
    loudly rather than ignoring it: a silent drop is how a caller keeps sending T3
    and keeps getting T2, with nothing anywhere to show why. This replaces the
    three S2-LM3 tests that asserted tier was persisted onto the lesson upload
    created — there is no longer a lesson to persist it onto.

    Story 1-14 AC19 bullet 4 adds the second half. The 422 does not merely refuse
    the caller, it TELLS THEM WHERE TO GO instead, by naming the generate route.
    If that message names a path that is not the one actually served, a client
    following the error gets a 404 and has no way to discover the real route —
    and the only symptom is a support ticket. Asserting `"tier" in detail` alone
    passes with the path in the message rewritten to anything at all.

    The expected path is read off the app's OWN OpenAPI document, never retyped
    here: a literal in this test and a literal in the message can be wrong
    together, which is the entire failure mode. `app.routes` is not usable for
    this on this FastAPI version — routes added by `include_router` are lazy
    `_IncludedRouter` branches with no `.path`, so a walk of it finds none of the
    content routes and would report a correctly mounted endpoint as missing.
    """
    from app.core.rate_limit import limiter

    limiter.reset()
    resp = client.post(
        "/api/content/lessons",
        files={"file": ("c.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
        data={"tier": "T3"},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "tier" in detail.lower()

    served = _served_post_path(client.app, "generate_chapter_lesson")
    assert served, "the generate route is not registered — the 422 points at nothing"
    assert served.removeprefix("/api/content") in detail, (
        f"upload's tier-422 must name the registered generate path {served!r}; "
        f"the message says: {detail!r}"
    )


def _served_post_path(app: Any, endpoint_name: str) -> str:
    """The mounted path a POST to *endpoint_name* is served at, read out of the
    OpenAPI document (FastAPI derives each operationId from the handler name)."""
    matches = [
        path
        for path, item in app.openapi()["paths"].items()
        for method, op in item.items()
        if method == "post" and str(op.get("operationId", "")).startswith(endpoint_name)
    ]
    assert len(matches) == 1, f"expected exactly one POST for {endpoint_name}, got {matches}"
    return matches[0]


@pytest.mark.unit
def test_upload_without_tier_is_accepted(client: TestClient) -> None:
    """The rejection must be triggered by SUPPLYING tier, not by its absence —
    otherwise every upload 422s."""
    from app.core.rate_limit import limiter

    limiter.reset()
    resp = client.post(
        "/api/content/lessons",
        files={"file": ("c.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
    )
    assert resp.status_code == 202


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


# ── Story 1-14 AC17 — GET /lessons learns its chapter ────────────────────────
#
# `_LIST_COLUMNS` gained `chapter_id` and a to-ONE embed back to `chapters`, and
# `LessonStatusResponse` gained `chapter_id`, `chapter_title`, `chapter_index`.
# Nothing asserted that any of the three ever reaches the client: hardcoding all
# three to None in `_row_to_status_response` passed the whole suite, and
# `grep -rn "chapter_title" tests/` returned nothing at all. These four tests
# cover the embed's four real shapes.

FAKE_CHAPTER_ID = "44444444-4444-4444-4444-444444444444"


def _list_row_with_chapter(chapter: Any) -> dict[str, Any]:
    row = copy.deepcopy(_LIST_ROW)
    row["chapter_id"] = FAKE_CHAPTER_ID
    row["chapter"] = chapter
    return row


def _get_lessons(rows_data: list[dict[str, Any]]) -> Any:
    from app.dependencies import get_arq_redis, get_current_user
    from app.main import app

    sb = _make_list_supabase_mock(rows_data)
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_arq_redis] = lambda: _make_arq_mock()
    try:
        with patch("app.modules.content.router.get_supabase", return_value=sb):
            return TestClient(app).get("/api/content/lessons")
    finally:
        app.dependency_overrides.clear()


@pytest.mark.unit
def test_list_lessons_returns_the_chapter_id_title_and_index_from_the_embed() -> None:
    """AC17's entire client-visible payoff.

    What breaks in production if this fails: Dev 2's dashboard lists every lesson
    a student has, and after book-scale a student has many lessons from the SAME
    book. Without the chapter's title and index they are an undifferentiated list
    of rows all named after the book — the student cannot tell which lesson is
    which, and the "which chapter am I resuming?" question has no answer in the
    payload. The endpoint returns 200 the whole time.
    """
    resp = _get_lessons(
        [
            _list_row_with_chapter(
                {
                    "chapter_id": FAKE_CHAPTER_ID,
                    "title": "Kinematics Of A Particle",
                    "chapter_index": 3,
                }
            )
        ]
    )

    assert resp.status_code == 200
    body = resp.json()[0]
    assert body["chapter_id"] == FAKE_CHAPTER_ID
    assert body["chapter_title"] == "Kinematics Of A Particle"
    assert body["chapter_index"] == 3


@pytest.mark.unit
def test_list_lessons_handles_a_legacy_lesson_whose_chapter_embed_is_null() -> None:
    """Every lesson created before Phase 6 has `chapter_id IS NULL`, so PostgREST
    sends `chapter: null` for it. That is the NORMAL state for most rows in the
    table on the day this ships, not an edge case.

    What breaks in production if this fails: `GET /lessons` 500s for any student
    with even one pre-Phase-6 lesson — i.e. the dashboard is dead for exactly the
    existing users, while every new account looks fine.
    """
    row = copy.deepcopy(_LIST_ROW)
    row["chapter_id"] = None
    row["chapter"] = None

    resp = _get_lessons([row])

    assert resp.status_code == 200
    body = resp.json()[0]
    assert body["chapter_id"] is None
    assert body["chapter_title"] is None
    assert body["chapter_index"] is None


@pytest.mark.unit
def test_list_lessons_unwraps_a_list_shaped_chapter_embed() -> None:
    """`lessons_chapter_id_fkey` is to-ONE from this side and to-MANY from the
    chapters side — the SAME constraint, two JSON shapes. Confusing them is the
    single most likely mistake in this area, and PostgREST has historically
    returned a one-element array for a to-one embed depending on how the
    relationship is resolved.

    What breaks in production if the unwrap is dropped: `chapter_title` becomes
    `None` for every lesson (a dict was expected, a list arrived) or the response
    model raises and the whole list endpoint 500s — decided by a shape the API
    does not control.
    """
    resp = _get_lessons(
        [
            _list_row_with_chapter(
                [{"chapter_id": FAKE_CHAPTER_ID, "title": "Work And Energy", "chapter_index": 7}]
            )
        ]
    )

    assert resp.status_code == 200
    body = resp.json()[0]
    assert body["chapter_title"] == "Work And Energy"
    assert body["chapter_index"] == 7

    # ...and the empty relation is not an error either.
    empty = _get_lessons([_list_row_with_chapter([])])
    assert empty.status_code == 200
    assert empty.json()[0]["chapter_title"] is None


@pytest.mark.unit
def test_get_lesson_reports_chapter_id_but_not_title_or_index() -> None:
    """`get_lesson` selects `*` and carries no embed — deliberately, so a single
    lesson fetch does not cost a second round-trip. So `chapter_id` (a flat
    column) is populated and title/index are None BY DESIGN.

    Asserting it stops two opposite regressions: someone "fixing" the nulls by
    adding an embed to a hot single-row path, and someone concluding the flat
    `chapter_id` is unused and dropping it from the response — the player reads
    it to know which chapter it is showing.
    """
    from app.dependencies import get_arq_redis, get_current_user
    from app.main import app

    lesson_row = {
        "lesson_id": FAKE_LESSON_ID,
        "user_id": FAKE_USER["sub"],
        "status": "generating",
        "title": "Thermo",
        "created_at": "2026-07-28T00:00:00Z",
        # A flat column on `lessons`, present on the `select("*")` path; there
        # is deliberately no `chapter` embed here.
        "chapter_id": FAKE_CHAPTER_ID,
    }
    sb = MagicMock()
    sb.table(
        "lessons"
    ).select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = (
        lesson_row
    )

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_arq_redis] = lambda: _make_arq_mock()
    try:
        with patch("app.modules.content.router.get_supabase", return_value=sb):
            resp = TestClient(app).get(f"/api/content/lessons/{FAKE_LESSON_ID}")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["chapter_id"] == FAKE_CHAPTER_ID
    assert body["chapter_title"] is None, "get_lesson carries no embed — title must stay None"
    assert body["chapter_index"] is None


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

    Story 1-14 (AC17/AC19): `_LIST_COLUMNS` gained `chapter_id` and the embed
    `chapter:chapters!lessons_chapter_id_fkey(...)`. Two changes here, and
    NEITHER loosens the membership check:

    1. `chapter_id` was missing from `real_columns` even though it IS a real
       column (20260803000000_chapters_book_scoped.sql:73). The set was stale,
       not the loop.
    2. A naive `split(",")` shreds the embed into `...(chapter_id`, `title`,
       `chapter_index)` and fails on SYNTAX rather than on a real defect — the
       exact situation that tempts someone to delete the guard. So the split is
       now embed-aware: outer names are still checked against `lessons`, and
       names INSIDE the embed are checked against `chapters`. Strictly more is
       validated than before, never less.

    Review follow-up (binding rule 4): both sets below used to be hand-typed. A
    hand-typed set is a second copy of the schema — it can go stale in the safe
    direction (missing a real column, as `chapter_id` was) or in the fatal one
    (listing a column that was dropped, which makes this guard bless a select
    list that 42703s). They are now PARSED from `supabase/migrations/` by the
    same `_columns_of` used next door in test_book_endpoints.py, and the
    hand-typed sets are kept as an equality assertion against the parse — so the
    guard is authoritative AND a schema change that silently alters either table
    fails here rather than in production.
    """
    from app.modules.content.router import _LIST_COLUMNS
    from tests.unit.test_book_endpoints import _columns_of

    # Real columns per 20260611000000_initial_schema.sql + later ALTERs
    # (20260625000000 book_id, 20260714020000 tier, 20260803000000 chapter_id).
    real_columns = _columns_of("lessons")
    # public.chapters per 20260611000000_initial_schema.sql:128-137
    # + 20260803000000_chapters_book_scoped.sql (boundary_confidence).
    real_chapter_columns = _columns_of("chapters")

    # The sets the review reasoned about, pinned. If the migrations ever stop
    # agreeing with these, the membership loop below is checking against
    # something nobody reviewed — fail here, loudly, instead.
    assert real_columns == {
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
        "chapter_id",
    }, f"public.lessons is no longer the reviewed set: {sorted(real_columns)}"
    assert real_chapter_columns == {
        "chapter_id",
        "book_id",
        "lesson_id",
        "title",
        "page_start",
        "page_end",
        "chapter_index",
        "boundary_confidence",
        "created_at",
    }, f"public.chapters is no longer the reviewed set: {sorted(real_chapter_columns)}"

    pairs = _split_select(_LIST_COLUMNS)
    assert pairs, "_LIST_COLUMNS parsed to nothing — this guard would pass vacuously"
    for table, spec in pairs:
        real = real_columns if table == "lessons" else real_chapter_columns
        assert spec in real, (
            f"_LIST_COLUMNS references {spec!r}, which is not a column on "
            f"public.{table} — PostgREST will 42703 the entire list endpoint"
        )


@pytest.mark.unit
def test_split_select_attributes_embedded_names_to_the_embedded_table() -> None:
    """Premise assertion (binding rule 3) for `_split_select`.

    The guard above is a `for` loop over this function's output. If it returned
    `[]` — or dropped the embed, or reported the embedded names under `lessons` —
    the loop body would never run, or would check `chapters` columns against the
    `lessons` set, and the guard would pass while proving nothing. Its sibling in
    test_book_endpoints.py protects against exactly this with `assert pairs`;
    this side had no such premise at all.

    What breaks in production if the attribution is wrong: a name that exists on
    `lessons` but not on `chapters` (or vice versa) sails through the guard and
    PostgREST 42703s the whole of `GET /lessons` for every user on every request
    — D9's shape, and the reason `_LIST_COLUMNS` is asserted against SQL at all.
    """
    assert _split_select("lesson_id,status") == [("lessons", "lesson_id"), ("lessons", "status")]
    # alias + JSONB path: the real column is the head of the path
    assert _split_select("subject:content->metadata->>subject") == [("lessons", "content")]
    # the embed: inner names belong to `chapters`, outer ones still to `lessons`
    assert _split_select("chapter_id,chapter:chapters!lessons_chapter_id_fkey(title,page_end)") == [
        ("lessons", "chapter_id"),
        ("chapters", "title"),
        ("chapters", "page_end"),
    ]
    # and the real constant is neither empty nor collapsed into one table
    from app.modules.content.router import _LIST_COLUMNS

    tables = {table for table, _ in _split_select(_LIST_COLUMNS)}
    assert tables == {"lessons", "chapters"}, (
        f"_LIST_COLUMNS should resolve names on both tables, got {tables}"
    )


def _split_select(select: str) -> list[tuple[str, str]]:
    """Split a PostgREST select list into `(table, column)` pairs.

    Handles the three PostgREST features these lists actually use:
      * aliases            `alias:expr`
      * JSON path selectors `content->metadata->>subject`
      * embeds              `alias:table!constraint(col,col)` — inner names
                            belong to the EMBEDDED table, not the base table.

    The base table is reported as "lessons"; embedded names are reported under
    the embedded table's own name so the caller can pick the right column set.
    """
    pairs: list[tuple[str, str]] = []
    depth = 0
    buf = ""
    parts: list[str] = []
    for ch in select:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(buf)
            buf = ""
            continue
        buf += ch
    if buf:
        parts.append(buf)

    for part in parts:
        spec = part.strip()
        if "(" in spec:
            head, _, inner = spec.partition("(")
            inner = inner.rstrip().removesuffix(")")
            # `alias:table!constraint` → the embedded table is `table`.
            target = head.split(":", 1)[1] if ":" in head else head
            embedded = target.split("!", 1)[0].strip()
            for nested_table, nested_col in _split_select(inner):
                # Inner names have no embed of their own in these lists; the
                # recursion reports them under the placeholder base table.
                pairs.append((embedded if nested_table == "lessons" else nested_table, nested_col))
            continue
        # `alias:path->>field` — the real column is the head of the path.
        source = spec.split(":", 1)[1] if ":" in spec else spec
        pairs.append(("lessons", source.split("->", 1)[0].strip()))
    return pairs


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
