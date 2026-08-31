"""CLI entrypoint for the Story 5-1 load-testing harness.

    python -m tests.loadtest.run --scale smoke
    python -m tests.loadtest.run --scale full

`--scale smoke` (3 concurrent) is D129's own recommended first step: a cheap,
minimal-cost sanity check that runs ONLY Phase B (`generate_chapter_lesson`)
against 3 requests, to prove the harness itself works end-to-end against the
real pipeline before anyone commits to the full, real-cost run. Phase A and
the two race probes are deliberately skipped at smoke scale.

`--scale full` (50 concurrent) is the real AC-2/AC-3 target: Phase A upload
(concurrency=50), Phase B generate (total_requests=50), and both race probes
(D45 needs one user + one chapter; Gate 7 needs one user + >= 4 distinct
chapters -- skipped with a clear warning, not a crash, if the fixture book
does not have enough).

This module makes real HTTP calls and real Supabase Admin API calls the
moment `main()` actually runs -- per this build step's own instructions, it
is written to run correctly but is NOT invoked here beyond a basic
import/argparse sanity check. A real run requires a human to actually type
the command above against a running `uvicorn` + local Redis, per Story
5-1's "separate human go-ahead" for any cost-incurring execution.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any

import httpx

from tests.loadtest.fixtures import ensure_book_chapter_fixture
from tests.loadtest.models import ScenarioResult, TestUser
from tests.loadtest.phase_a_upload import run_phase_a
from tests.loadtest.phase_b_generate import run_phase_b
from tests.loadtest.provisioning import (
    cleanup_generate_test_users,
    cleanup_uploaded_books,
    get_approved_test_users,
    provision_generate_test_users,
)
from tests.loadtest.race_probes import (
    probe_d45_idempotency_race,
    probe_gate7_concurrency_race,
)
from tests.loadtest.report import build_report

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "http://localhost:8000"

_SMOKE_TOTAL_REQUESTS = 3
_FULL_TOTAL_REQUESTS = 50
_GENERATE_USER_COUNT = 17
_GATE7_MIN_CHAPTERS = 4

# apps/api/tests/loadtest/run.py -> parents[2] == apps/api
_API_ROOT = Path(__file__).resolve().parents[2]
_REPORT_PATH = _API_ROOT.parent.parent / "docs" / "reports" / "load-test-5-1-results.md"


def _base_url() -> str:
    return os.environ.get("LOADTEST_BASE_URL", _DEFAULT_BASE_URL)


def _local_topology(max_jobs: int = 5) -> dict[str, Any]:
    """Topology for a local single-process `uvicorn` + single ARQ worker run
    (this build step's expected execution environment, per the task
    instructions). AC-9 requires every field be STATED, never assumed --
    a run against a different (e.g. Railway multi-replica) environment must
    pass its own real replica counts instead of calling this helper."""
    return {"api_replicas": 1, "worker_replicas": 1, "max_jobs": max_jobs}


async def _run_smoke(base_url: str) -> tuple[list[ScenarioResult], dict[str, Any], dict[str, Any]]:
    """Smoke scale: Phase B ONLY, 3 concurrent requests. Skips Phase A and
    both race probes entirely -- the smoke test's whole purpose is a cheap,
    minimal-cost check that the harness works end-to-end against the real
    pipeline, not a full drill (per this build step's instructions)."""
    logger.info("Smoke run: provisioning %d disposable Phase B users", _GENERATE_USER_COUNT)
    generate_users = await provision_generate_test_users(_GENERATE_USER_COUNT)
    try:
        approved_users = await get_approved_test_users()
        uploader = approved_users[0]
        logger.info("Smoke run: ensuring book+chapter fixture")
        book_id, chapter_id = await ensure_book_chapter_fixture(base_url, uploader)

        logger.info(
            "Smoke run: Phase B, %d concurrent generate requests", _SMOKE_TOTAL_REQUESTS
        )
        phase_b_result = await run_phase_b(
            base_url=base_url,
            generate_users=generate_users,
            book_id=book_id,
            chapter_id=chapter_id,
            total_requests=_SMOKE_TOTAL_REQUESTS,
        )
        return [phase_b_result], {}, {}
    finally:
        await cleanup_generate_test_users(generate_users)


async def _run_full(base_url: str) -> tuple[list[ScenarioResult], dict[str, Any], dict[str, Any]]:
    """Full scale: Phase A (50 concurrent uploads), Phase B (50 concurrent
    generates across >= 17 users), then both race probes. The Gate-7 probe
    is skipped (with a logged warning, not a crash) if the fixture book has
    fewer than `_GATE7_MIN_CHAPTERS` distinct chapters."""
    logger.info("Full run: provisioning %d disposable Phase B users", _GENERATE_USER_COUNT)
    generate_users = await provision_generate_test_users(_GENERATE_USER_COUNT)
    # Populated once Phase A actually runs (below); cleaned up in `finally`
    # alongside `generate_users` regardless of what happens afterward. Phase
    # A reuses REAL, non-disposable `APPROVED_EMAILS` accounts (see
    # `phase_a_upload.py`'s docstring) -- unlike `generate_users`, these
    # accounts themselves must NOT be deleted, only the specific books this
    # run created on them (`cleanup_uploaded_books`), or every full run
    # leaves permanent residue on real accounts with no other cleanup path.
    created_books: list[dict[str, str]] = []
    try:
        approved_users = await get_approved_test_users()
        uploader = approved_users[0]
        logger.info("Full run: ensuring book+chapter fixture")
        book_id, chapter_id = await ensure_book_chapter_fixture(base_url, uploader)

        logger.info(
            "Full run: Phase A, %d concurrent upload requests", _FULL_TOTAL_REQUESTS
        )
        phase_a_result = await run_phase_a(
            base_url=base_url,
            approved_users=approved_users,
            concurrency=_FULL_TOTAL_REQUESTS,
        )
        created_books = phase_a_result.extra.get("created_books", [])

        logger.info(
            "Full run: Phase B, %d concurrent generate requests across %d users",
            _FULL_TOTAL_REQUESTS,
            len(generate_users),
        )
        phase_b_result = await run_phase_b(
            base_url=base_url,
            generate_users=generate_users,
            book_id=book_id,
            chapter_id=chapter_id,
            total_requests=_FULL_TOTAL_REQUESTS,
        )

        logger.info("Full run: D45 idempotency race probe")
        race_d45 = await probe_d45_idempotency_race(
            base_url=base_url,
            user=generate_users[0],
            book_id=book_id,
            chapter_id=chapter_id,
        )

        logger.info("Full run: listing chapters for the Gate-7 race probe")
        all_chapter_ids = await _list_all_chapter_ids(base_url, uploader, book_id)
        # Exclude the ONE chapter Phase B just used (every one of the 17
        # generate_users, including generate_users[1] below, already
        # submitted a (chapter_id, tier="T2") generate request against it) --
        # if that chapter were left in the candidate list, one of the 4
        # "distinct chapter" probe requests could land on a chapter where
        # this user already has a non-failed lesson from Phase B, so Gate 5's
        # idempotency check would short-circuit it to a 200 idempotent
        # replay. `probe_gate7_concurrency_race` counts any 200 OR 202 as
        # "accepted" (matching the real client-visible outcome), so that
        # replay would be miscounted as a fresh Gate-7 admission -- inflating
        # `accepted_count` and risking a FALSE "Gate 7 REPRODUCED" verdict
        # that is actually just an unrelated idempotent replay, not a real
        # oversubscription of the concurrency cap. Filtering this chapter out
        # keeps every one of the 4 probe requests targeting chapters this
        # user has genuinely never touched before.
        chapter_ids = [c for c in all_chapter_ids if c != chapter_id]
        race_gate7: dict[str, Any]
        if len(chapter_ids) < _GATE7_MIN_CHAPTERS:
            logger.warning(
                "Gate-7 race probe SKIPPED: fixture book %s has only %d detected "
                "chapter(s) other than the one Phase B already used, need >= %d "
                "distinct, untouched chapters to attempt oversubscription without "
                "risking an idempotent-replay false positive. Upload a larger "
                "fixture book to enable this probe.",
                book_id,
                len(chapter_ids),
                _GATE7_MIN_CHAPTERS,
            )
            race_gate7 = {}
        else:
            race_gate7 = await probe_gate7_concurrency_race(
                base_url=base_url,
                user=generate_users[1],
                book_id=book_id,
                chapter_ids=chapter_ids[:_GATE7_MIN_CHAPTERS],
            )

        return [phase_a_result, phase_b_result], race_d45, race_gate7
    finally:
        # Both cleanups are attempted even if one fails, and even if the
        # `try` block above raised partway through -- a book upload leaking
        # onto a real account, or a disposable user leaking onto the real
        # project, must not depend on the rest of the run succeeding.
        try:
            await cleanup_generate_test_users(generate_users)
        finally:
            if created_books:
                await cleanup_uploaded_books(created_books)


async def _list_all_chapter_ids(base_url: str, uploader: TestUser, book_id: str) -> list[str]:
    """Real `GET /books/{book_id}/chapters` (the same endpoint
    `fixtures._first_chapter_via_api` uses), returning every detected
    chapter's id -- needed here (not just the first one) because the Gate-7
    probe requires `>= 4` DISTINCT chapters to attempt oversubscription."""
    headers = {"Authorization": f"Bearer {uploader.access_token}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{base_url.rstrip('/')}/api/content/books/{book_id}/chapters",
            headers=headers,
        )
    if resp.status_code != 200:
        raise RuntimeError(
            f"chapter list failed for book {book_id}: {resp.status_code} {resp.text[:300]}"
        )
    chapters: list[dict[str, Any]] = resp.json()
    return [str(c["chapter_id"]) for c in chapters if c.get("chapter_id")]


async def _main_async(scale: str) -> str:
    base_url = _base_url()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger.info("Story 5-1 load test starting: scale=%s base_url=%s", scale, base_url)

    if scale == "smoke":
        results, race_d45, race_gate7 = await _run_smoke(base_url)
    elif scale == "full":
        results, race_d45, race_gate7 = await _run_full(base_url)
    else:  # pragma: no cover -- argparse `choices` already prevents this
        raise ValueError(f"unknown scale: {scale!r}")

    topology = _local_topology()
    report = build_report(
        results=results,
        race_d45=race_d45,
        race_gate7=race_gate7,
        topology=topology,
    )
    return report


def _write_report(report: str) -> None:
    _REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _REPORT_PATH.write_text(report, encoding="utf-8")
    logger.info("Report written to %s", _REPORT_PATH)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tests.loadtest.run",
        description=(
            "Story 5-1 load-testing harness. '--scale smoke' (3 concurrent, "
            "Phase B only) is D129's recommended first step; '--scale full' "
            "(50 concurrent, both phases + both race probes) is the real "
            "AC-2/AC-3 target. Both make real HTTP + real Supabase Admin API "
            "calls against LOADTEST_BASE_URL -- run only with explicit human "
            "go-ahead."
        ),
    )
    parser.add_argument(
        "--scale",
        choices=("smoke", "full"),
        required=True,
        help="'smoke' = 3 concurrent (cheap sanity check); 'full' = 50 concurrent (real target).",
    )
    args = parser.parse_args(argv)

    report = asyncio.run(_main_async(args.scale))
    print(report)
    _write_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
