"""Phase A (book upload) load scenario for Story 5-1.

Fires `concurrency` truly-concurrent `POST /api/content/lessons` requests
(real multipart PDF upload, `upload_lesson`, `router.py:686`), cycling
round-robin through `approved_users`. Reports submission latency and a
status-code tally as a `ScenarioResult` (`docs/stories/5-1-load-test-50-concurrent.md`
AC-2).

This module is HTTP-only by design (Story 5-1 AC-1): it issues requests
against a running server via `httpx.AsyncClient` and imports nothing from
`app/`. The eval harness's in-process `run_pipeline()` shortcut bypasses the
HTTP layer, the rate limiter, and the ARQ enqueue entirely, so it cannot
stand in for this -- see `tests/evals/runner.py` and the story's Dev Notes.

Only 3 real accounts are on `APPROVED_EMAILS` today (`upload_lesson` requires
`ApprovedUser`, not just any authenticated user). Story 5-1's AC-2 does not
require distinct users the way AC-3 does, so Phase A deliberately cycles
through those 3 existing approved accounts rather than expanding the
allowlist -- at concurrency=50 each fires ~17 concurrent uploads against a
`5/minute` per-user rate limiter (`router.py:692`), so a large share of 429s
is the expected, honest result of this design, not a scenario failure. Only
a transport-level exception (timeout, connection reset) is treated as an
unexpected error; every HTTP response, 2xx or not, is recorded and returned.
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from pathlib import Path

import httpx

from tests.loadtest.models import ScenarioResult, TestUser

_UPLOAD_PATH = "/api/content/lessons"
_FIXTURE_PDF = (
    Path(__file__).resolve().parent.parent / "fixtures" / "eval_pdfs" / "short_10page.pdf"
)
# Uploads read+store a real (small) PDF body; generous relative to the 5s scale
# of the P95<2s target so a slow-but-real response is measured, not timed out
# and misreported as a transport error.
_REQUEST_TIMEOUT_S = 60.0


async def _one_upload(
    client: httpx.AsyncClient,
    base_url: str,
    user: TestUser,
    pdf_bytes: bytes,
) -> tuple[float, int, str | None, str | None]:
    """Fire one upload request; never raises on a non-2xx HTTP response.

    Returns (latency_ms, status_code, error_or_None, book_id_or_None).
    `status_code` is 0 only for a transport-level failure (no HTTP response
    was ever received) -- every real response, including 429/413/422/5xx, is
    returned with its real status code and a short error string, not raised.

    `book_id` is populated only on a 202 with a parseable body carrying one.
    This harness reuses only 3 REAL `APPROVED_EMAILS` accounts for Phase A
    (see module docstring) -- every successful upload creates a real, live
    `books` row (+ a real storage object + a real ingestion job) on one of
    those accounts. Unlike Phase B's disposable users, these accounts are
    NOT deleted afterward, so `book_id` must be captured here and fed to
    `provisioning.cleanup_uploaded_books` by the caller -- otherwise every
    full-scale run permanently accumulates load-test books on real,
    non-disposable accounts with no cleanup path at all.
    """
    files = {"file": ("short_10page.pdf", pdf_bytes, "application/pdf")}
    headers = {"Authorization": f"Bearer {user.access_token}"}
    start = time.monotonic()
    try:
        resp = await client.post(
            f"{base_url}{_UPLOAD_PATH}",
            files=files,
            headers=headers,
            timeout=_REQUEST_TIMEOUT_S,
        )
    except httpx.HTTPError as exc:
        latency_ms = (time.monotonic() - start) * 1000
        return latency_ms, 0, f"{type(exc).__name__}: {exc}", None

    latency_ms = (time.monotonic() - start) * 1000
    if resp.status_code == 202:
        book_id: str | None = None
        try:
            body: dict[str, object] = resp.json()
            raw_id = body.get("book_id") if isinstance(body, dict) else None
            book_id = str(raw_id) if raw_id is not None else None
        except ValueError:
            book_id = None
        return latency_ms, resp.status_code, None, book_id

    # Non-202 (429 from the rate limiter is the expected common case at this
    # concurrency with only 3 approved users -- see module docstring): record
    # it as an honest, non-raised failure with a short body snippet, never the
    # full response body (could be large or binary).
    snippet = resp.text[:200] if resp.text else ""
    return latency_ms, resp.status_code, f"HTTP {resp.status_code}: {snippet}", None


async def run_phase_a(
    base_url: str,
    approved_users: list[TestUser],
    concurrency: int,
) -> ScenarioResult:
    """Run the Phase A (upload) load scenario.

    Fires `concurrency` truly-simultaneous `POST {base_url}/api/content/lessons`
    requests via `asyncio.gather`, cycling round-robin through
    `approved_users` (real PDF bytes from
    `tests/fixtures/eval_pdfs/short_10page.pdf`, real `Authorization: Bearer`
    tokens). 202 counts as `succeeded`; every other outcome (429, 413, 422,
    5xx, or a transport-level exception) counts as `failed`, with the status
    code recorded in both `errors` and `extra['status_code_counts']` -- never
    raised, per the story's AC-2 requirement to measure and report the rate
    limiter's real behavior under this concurrency, not treat it as a bug in
    the harness.

    Args:
        base_url: e.g. `http://localhost:8000` (`LOADTEST_BASE_URL`).
        approved_users: real `ApprovedUser`-allowlisted accounts (today: the 3
            accounts on `APPROVED_EMAILS`). Must be non-empty; cycled
            round-robin so `concurrency` may exceed `len(approved_users)`.
        concurrency: number of truly-concurrent upload requests to fire.

    Returns:
        ScenarioResult(scenario="phase_a_upload", ...) with per-request
        submission latency in `latencies_ms` and a status-code tally at
        `extra["status_code_counts"]`.
    """
    if not approved_users:
        raise ValueError("approved_users must be non-empty")
    if concurrency < 1:
        raise ValueError("concurrency must be >= 1")

    pdf_bytes = _FIXTURE_PDF.read_bytes()

    # A generous connection pool so `asyncio.gather` produces true concurrency
    # at the transport level too -- httpx's default pool (100 connections) is
    # already >= 50, but this makes the intent explicit and scales past 50 if
    # a future run raises `concurrency`.
    limits = httpx.Limits(
        max_connections=concurrency + 10,
        max_keepalive_connections=concurrency,
    )
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_S, limits=limits) as client:
        tasks = [
            _one_upload(client, base_url, approved_users[i % len(approved_users)], pdf_bytes)
            for i in range(concurrency)
        ]
        outcomes = await asyncio.gather(*tasks)

    latencies_ms: list[float] = []
    raw_errors: list[str] = []
    status_counts: Counter[str] = Counter()
    succeeded = 0
    failed = 0
    # Every real book created on a REUSED (real, non-disposable) approved
    # account -- see `_one_upload`'s docstring. The caller MUST pass this to
    # `provisioning.cleanup_uploaded_books` after the run, or every
    # successful upload this scenario makes becomes permanent residue on a
    # real account with no other cleanup path.
    created_books: list[dict[str, str]] = []
    for i, (latency_ms, status_code, error, book_id) in enumerate(outcomes):
        latencies_ms.append(latency_ms)
        status_counts[str(status_code)] += 1
        if status_code == 202:
            succeeded += 1
            if book_id is not None:
                created_books.append(
                    {
                        "book_id": book_id,
                        "user_id": approved_users[i % len(approved_users)].user_id,
                        "filename": "short_10page.pdf",
                    }
                )
        else:
            failed += 1
            if error is not None:
                raw_errors.append(error)

    # Cap/dedupe per the ScenarioResult contract ("short error strings,
    # capped/deduped, not full tracebacks") -- 50 concurrent 429s should not
    # produce 50 near-identical lines.
    deduped_errors = sorted(set(raw_errors))[:20]

    return ScenarioResult(
        scenario="phase_a_upload",
        total_requests=concurrency,
        succeeded=succeeded,
        failed=failed,
        errors=deduped_errors,
        latencies_ms=latencies_ms,
        extra={
            "status_code_counts": dict(status_counts),
            "created_books": created_books,
        },
    )
