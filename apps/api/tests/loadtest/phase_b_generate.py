"""Phase B (generate) load scenario for Story 5-1.

Fires `total_requests` truly-concurrent
`POST /api/content/books/{book_id}/chapters/{chapter_id}/lessons`
requests (`generate_chapter_lesson`, `GENERATE_LESSON_PATH`, `router.py:1057`),
cycling round-robin through `generate_users`, then polls every accepted
`lesson_id` (`GET /api/content/lessons/{lesson_id}`) concurrently to a
terminal status. Reports submission latency and completion duration as two
separate lists in `ScenarioResult` -- never merged into one number -- per the
story's AC-3 and its Dev Notes ("a SLA miss caused by queuing is never
confused with a SLA miss caused by a slow node").

This module is HTTP-only by design (Story 5-1 AC-1): it imports nothing from
`app/` and drives the real running server via `httpx.AsyncClient`. The eval
harness's in-process `run_pipeline()` shortcut bypasses the HTTP layer, the
rate limiter, Gate 7, and the ARQ enqueue entirely, so it cannot stand in for
this -- see `tests/evals/runner.py` and the story's Dev Notes.

AC-3's explicit floor: `max_concurrent_generations_per_user = 3`
(`config.py`) means fewer than 17 distinct users cannot reach 50
simultaneously-`generating` lessons without 429s from Gate 7
(`router.py:1308-1324`) measuring the concurrency gate instead of real
pipeline load -- `run_phase_b` raises rather than silently running an
under-provisioned scenario. With `total_requests=50` spread round-robin
across >=17 users, each user gets ~3 requests -- right at the cap -- so a
share of real 429s here is an EXPECTED, honestly-reported outcome, not a
scenario bug; they are tallied in `extra["status_code_counts"]` like every
other real response, never retried or discarded.
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from typing import Any

import httpx

from tests.loadtest.models import ScenarioResult, TestUser

_GENERATE_MIN_USERS = 17
_TIER = "T2"

# Matches `arq_job_timeout_s = 1800` (`config.py`) -- ARQ itself will not
# cancel a job before this, so a lesson still legitimately in flight at 25
# minutes is not a harness bug; only past this ceiling do we stop polling and
# record `never_terminal_timeout` (a real, reportable finding per AC-3's
# "no job left silently stuck" requirement -- the harness itself must not be
# the thing that silently stops watching).
_POLL_TIMEOUT_S = 1800.0
_POLL_INTERVAL_S = 3.0

# Generous relative to the request itself: the synchronous path this
# endpoint runs (Gate 5/6/7 checks, one INSERT, one ARQ enqueue) is fast by
# design, but a slow/contended Redis connection pool (Scale & Load Q2, AC-4)
# should show up as elevated latency in the measurement, not a timed-out
# request misreported as a transport error.
_SUBMIT_TIMEOUT_S = 30.0
_POLL_REQUEST_TIMEOUT_S = 15.0

_TERMINAL_STATUSES = frozenset({"ready", "failed"})


def _generate_lessons_url(base_url: str, book_id: str, chapter_id: str) -> str:
    return f"{base_url.rstrip('/')}/api/content/books/{book_id}/chapters/{chapter_id}/lessons"


def _lesson_status_url(base_url: str, lesson_id: str) -> str:
    return f"{base_url.rstrip('/')}/api/content/lessons/{lesson_id}"


async def _submit_one(
    client: httpx.AsyncClient,
    url: str,
    user: TestUser,
) -> dict[str, Any]:
    """Fire one generate request; never raises on a non-2xx HTTP response.

    Returns a dict with:
        status_code: int | None (None only for a transport-level failure --
            no HTTP response was ever received)
        latency_ms: float -- wall-clock from just-before-the-request to
            response-received. This is a CLIENT-OBSERVED, black-box proxy for
            AC-3's "P99 time from HTTP request received to
            arq_redis.enqueue_job() returning" target, not a direct
            measurement of it -- true server-side received-to-enqueued
            timing would need instrumentation inside `generate_chapter_lesson`
            itself (a response header or a server-side log timestamp diff),
            which this harness does not add. Any report built from this
            number must label it "client-observed submission latency
            (proxy)", never claim server-side enqueue precision.
        lesson_id: str | None -- present only on a 200/202 with a parseable
            body containing one.
        error: str | None -- short, non-traceback description of any
            non-2xx response or transport exception. 429 (Gate 7 or the
            3/minute;20/hour rate limiter), 404, 422, 5xx are all real,
            expected-to-happen-sometimes outcomes at this concurrency and are
            recorded here as data, never retried or discarded.
    """
    start = time.monotonic()
    try:
        resp = await client.post(
            url,
            json={"tier": _TIER},
            headers={"Authorization": f"Bearer {user.access_token}"},
            timeout=_SUBMIT_TIMEOUT_S,
        )
    except httpx.HTTPError as exc:
        latency_ms = (time.monotonic() - start) * 1000
        return {
            "status_code": None,
            "latency_ms": latency_ms,
            "lesson_id": None,
            "error": f"{type(exc).__name__}: {exc}",
        }

    latency_ms = (time.monotonic() - start) * 1000

    if resp.status_code in (200, 202):
        lesson_id: str | None = None
        error: str | None = None
        try:
            body: Any = resp.json()
            raw_id = body.get("lesson_id") if isinstance(body, dict) else None
            lesson_id = str(raw_id) if raw_id is not None else None
        except ValueError as exc:
            error = f"unparseable JSON body on HTTP {resp.status_code}: {exc}"
        if lesson_id is None and error is None:
            error = f"HTTP {resp.status_code} had no lesson_id in body"
        return {
            "status_code": resp.status_code,
            "latency_ms": latency_ms,
            "lesson_id": lesson_id,
            "error": error,
        }

    # Non-2xx: real outcome, recorded, never raised.
    snippet = resp.text[:200] if resp.text else ""
    return {
        "status_code": resp.status_code,
        "latency_ms": latency_ms,
        "lesson_id": None,
        "error": f"HTTP {resp.status_code}: {snippet}",
    }


async def _poll_one_lesson(
    client: httpx.AsyncClient,
    base_url: str,
    lesson_id: str,
    submitted_at: float,
    token: str,
) -> dict[str, Any]:
    """Poll one `lesson_id` every `_POLL_INTERVAL_S` until a terminal status
    (`ready`/`failed`) or `_POLL_TIMEOUT_S` elapses, whichever comes first.

    Runs as one coroutine per lesson_id -- callers `asyncio.gather` many of
    these concurrently so 50 in-flight lessons are watched in parallel, not
    one at a time (Story 5-1 Task 4).

    Returns a dict:
        lesson_id: str
        terminal_status: 'ready' | 'failed' | 'never_terminal_timeout'
        duration_s: float | None -- wall-clock from `submitted_at` to the
            terminal poll response; None only for `never_terminal_timeout`.
        error: str | None -- last transient polling error observed, if any
            (a single dropped poll is not itself terminal -- polling
            continues -- but the last one is surfaced for the report).
    """
    url = _lesson_status_url(base_url, lesson_id)
    deadline = submitted_at + _POLL_TIMEOUT_S
    last_error: str | None = None

    while True:
        now = time.monotonic()
        if now >= deadline:
            return {
                "lesson_id": lesson_id,
                "terminal_status": "never_terminal_timeout",
                "duration_s": None,
                "error": last_error,
            }

        try:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=_POLL_REQUEST_TIMEOUT_S,
            )
        except httpx.HTTPError as exc:
            last_error = f"poll transport error: {type(exc).__name__}: {exc}"
            await asyncio.sleep(_POLL_INTERVAL_S)
            continue

        if resp.status_code in (401, 403, 404):
            # Not a transient failure -- auth/ownership is either broken for
            # this lesson_id/token pair or will never resolve itself by
            # waiting. Fail fast rather than burning the full
            # _POLL_TIMEOUT_S (30 min) retrying an error that cannot change
            # on its own (this bug shape -- silently retrying a
            # non-transient error for the full deadline -- is exactly what
            # burned 30 real minutes on this harness's own first live run).
            return {
                "lesson_id": lesson_id,
                "terminal_status": "never_terminal_timeout",
                "duration_s": None,
                "error": (
                    f"poll HTTP {resp.status_code} (non-transient, stopped early): "
                    f"{resp.text[:200]}"
                ),
            }

        if resp.status_code != 200:
            last_error = f"poll HTTP {resp.status_code}: {resp.text[:200]}"
            await asyncio.sleep(_POLL_INTERVAL_S)
            continue

        try:
            body: Any = resp.json()
        except ValueError as exc:
            last_error = f"poll unparseable JSON: {exc}"
            await asyncio.sleep(_POLL_INTERVAL_S)
            continue

        lesson_status = body.get("status") if isinstance(body, dict) else None
        if lesson_status in _TERMINAL_STATUSES:
            return {
                "lesson_id": lesson_id,
                "terminal_status": lesson_status,
                "duration_s": time.monotonic() - submitted_at,
                "error": None,
            }

        # queued | running (or 'generating', whichever label the live status
        # read uses) -- not terminal yet, keep polling.
        await asyncio.sleep(_POLL_INTERVAL_S)


_MAX_DEDUPED_ERRORS = 40


def _record_error(errors: list[str], msg: str) -> None:
    """Append a short, deduped error string, capped so `errors` cannot grow
    unbounded across 50+ requests plus their polling loops (this harness's
    own `errors` list is not a Supabase query and so is out of
    `test_unbounded_queries.py`'s scan scope by definition -- see the
    story's Scale & Load Q4 -- but gets the same discipline anyway: capped
    size, truncated message, never a full traceback kept in memory)."""
    short = msg[:300]
    if short not in errors and len(errors) < _MAX_DEDUPED_ERRORS:
        errors.append(short)


async def run_phase_b(
    base_url: str,
    generate_users: list[TestUser],
    user_fixtures: dict[str, tuple[str, str]],
    total_requests: int,
) -> ScenarioResult:
    """Run the Story 5-1 Phase B (generate) load scenario end-to-end:
    concurrent submission, then concurrent polling to a terminal status.

    Args:
        base_url: e.g. `http://localhost:8000` (`LOADTEST_BASE_URL`).
        generate_users: real, JWT-authenticated test accounts, freshly
            created disposable users (`generate_chapter_lesson` requires
            only `CurrentUser`, no `APPROVED_EMAILS` allowlist, unlike
            Phase A's upload endpoint -- though Phase A now also uses its
            own disposable pool at a non-overlapping index offset). Must
            contain >= 17 distinct users -- see AC-3's explicit floor below.
        user_fixtures: maps each generate_users[i].user_id to that SAME
            user's own real, `ready` (book_id, chapter_id) pair. Ownership of
            `books`/`chapters` is enforced at the application layer
            (`generate_chapter_lesson` returns 404 for a book/chapter the
            caller doesn't own -- confirmed directly against
            `app/modules/content/router.py`'s own docstring), so a single
            SHARED book+chapter across many distinct users is not viable --
            each user must generate from a chapter they themselves uploaded.
            Because each user submits against their OWN chapter, this
            deliberately does NOT engage Gate 5/D45's idempotency check
            across users (that requires the SAME user AND SAME chapter --
            see `race_probes.probe_d45_idempotency_race` for that dedicated
            probe) -- it does legitimately engage Gate 7's per-user
            concurrency count once a given user's ~3 round-robin requests
            (against their own chapter) are in flight together.
        total_requests: target concurrent request count (Story 5-1 target:
            50). Distributed round-robin across `generate_users`.

    Returns:
        ScenarioResult(scenario="phase_b_generate", ...) with per-request
        submission latency in `latencies_ms` (a black-box proxy for AC-3's
        enqueue-latency target -- see `_submit_one`'s docstring) and, in
        `extra`:
            status_code_counts: {str(status_code): count, ...} (including a
                "no_response" bucket for transport-level failures)
            terminal_status_counts: {'ready': N, 'failed': N,
                'never_terminal_timeout': N}
            completion_durations_s: [float, ...] -- one entry per lesson
                that reached a terminal status, submission-to-terminal
                wall-clock seconds. Kept entirely separate from
                `latencies_ms` (submission latency) per AC-3 / Scale & Load
                Q2: a queuing delay must never be reported as if it were
                enqueue latency, and vice versa.

    Raises:
        ValueError: if `generate_users` has fewer than 17 distinct users, or
            `total_requests` < 1.
    """
    if len(generate_users) < _GENERATE_MIN_USERS:
        raise ValueError(
            f"run_phase_b requires >= {_GENERATE_MIN_USERS} distinct generate_users "
            f"(Story 5-1 AC-3's explicit floor: at "
            f"max_concurrent_generations_per_user=3, fewer than {_GENERATE_MIN_USERS} "
            f"users cannot reach {total_requests} simultaneously-'generating' lessons "
            f"without 429s from Gate 7 measuring the concurrency gate instead of real "
            f"pipeline load), got {len(generate_users)}"
        )
    if total_requests < 1:
        raise ValueError("total_requests must be >= 1")
    # Only the users round-robin will ACTUALLY index into
    # (generate_users[i % len(generate_users)] for i in range(total_requests))
    # need a fixture -- at total_requests < len(generate_users) (e.g. the
    # smoke scale's 3-of-17), most of generate_users is never touched, so
    # requiring a fixture for the whole list would reject a deliberately
    # cheap smoke run.
    actually_used_ids = {
        generate_users[i % len(generate_users)].user_id for i in range(total_requests)
    }
    missing = [uid for uid in actually_used_ids if uid not in user_fixtures]
    if missing:
        raise ValueError(
            f"user_fixtures is missing an entry for {len(missing)} of "
            f"{len(actually_used_ids)} users this run will actually use "
            f"(e.g. {missing[:3]}) -- every user this round-robin indexes into "
            f"must have their own (book_id, chapter_id) pair, since ownership is "
            f"enforced per-user at the application layer, not shared"
        )

    # A generous connection pool so `asyncio.gather` produces true
    # concurrency at the transport level too (mirrors phase_a_upload.py's
    # same reasoning) -- one shared client, not one per user, so this
    # harness exercises the SAME kind of connection reuse a real client
    # would rather than manufacturing `total_requests` fresh TCP
    # connections no real caller pattern would produce.
    limits = httpx.Limits(
        max_connections=total_requests + 10,
        max_keepalive_connections=total_requests,
    )
    async with httpx.AsyncClient(timeout=_SUBMIT_TIMEOUT_S, limits=limits) as client:
        def _url_for(user: TestUser) -> str:
            book_id, chapter_id = user_fixtures[user.user_id]
            return _generate_lessons_url(base_url, book_id, chapter_id)

        submitting_users = [generate_users[i % len(generate_users)] for i in range(total_requests)]
        submit_tasks = [
            _submit_one(client, _url_for(user), user) for user in submitting_users
        ]
        # Fire every submission truly concurrently (Story 5-1 AC-1: HTTP
        # load, not a sequential for-loop like the eval harness).
        submit_results = await asyncio.gather(*submit_tasks)

        # Each accepted lesson gets its OWN submitted_at timestamp (captured
        # per-request, not one shared batch-start time) so completion
        # duration reflects that specific request's real submission moment,
        # even though every request was launched in the same event-loop
        # tick. GET /lessons/{id} requires CurrentUser (the same auth as the
        # generate call, not a shared/anonymous read), so each poll must use
        # the SAME user's token that submitted that specific lesson_id --
        # zipping by index (submit_results preserves submitting_users' order)
        # rather than dropping the association, which previously made every
        # poll 401 regardless of which real user's token was used.
        accepted_now = time.monotonic()
        poll_targets: list[tuple[str, float, str]] = [
            (str(r["lesson_id"]), accepted_now, user.access_token)
            for r, user in zip(submit_results, submitting_users, strict=True)
            if r["lesson_id"] is not None
        ]

        poll_tasks = [
            _poll_one_lesson(client, base_url, lesson_id, submitted_at, token)
            for lesson_id, submitted_at, token in poll_targets
        ]
        # Concurrent polling for every in-flight lesson (one coroutine per
        # lesson_id via asyncio.gather), not sequential.
        poll_results = list(await asyncio.gather(*poll_tasks)) if poll_tasks else []

    latencies_ms: list[float] = []
    status_code_counts: Counter[str] = Counter()
    errors: list[str] = []
    succeeded = 0
    failed = 0

    for r in submit_results:
        latencies_ms.append(r["latency_ms"])
        code_key = str(r["status_code"]) if r["status_code"] is not None else "no_response"
        status_code_counts[code_key] += 1
        if r["status_code"] in (200, 202):
            succeeded += 1
        else:
            failed += 1
        if r["error"]:
            _record_error(errors, r["error"])

    terminal_status_counts: dict[str, int] = {
        "ready": 0,
        "failed": 0,
        "never_terminal_timeout": 0,
    }
    completion_durations_s: list[float] = []
    for pr in poll_results:
        terminal_status_counts[pr["terminal_status"]] += 1
        if pr["duration_s"] is not None:
            completion_durations_s.append(pr["duration_s"])
        if pr["error"]:
            _record_error(errors, f"poll lesson_id={pr['lesson_id']}: {pr['error']}")

    return ScenarioResult(
        scenario="phase_b_generate",
        total_requests=total_requests,
        succeeded=succeeded,
        failed=failed,
        errors=errors,
        latencies_ms=latencies_ms,
        extra={
            "status_code_counts": dict(status_code_counts),
            "terminal_status_counts": terminal_status_counts,
            "completion_durations_s": completion_durations_s,
            "submission_latency_note": (
                "latencies_ms is a client-observed black-box proxy for AC-3's "
                "'HTTP request received to arq_redis.enqueue_job() returning' P99 "
                "target -- true server-side enqueue timing was not instrumented by "
                "this harness; report this as submission latency, not server-side "
                "enqueue precision."
            ),
            "per_user_fixtures": {uid: list(pair) for uid, pair in user_fixtures.items()},
            "tier": _TIER,
            "num_generate_users": len(generate_users),
            "accepted_count": len(poll_targets),
        },
    )
