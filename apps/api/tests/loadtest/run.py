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
# Phase A previously reused the 3 real, non-disposable APPROVED_EMAILS
# accounts -- the code review flagged this as a real-account-pollution risk
# even with cleanup added. Phase A now gets its own disposable pool instead,
# same mechanism as Phase B's generate_users, offset past Phase B's index
# range (0-16) so the two pools never collide on the same loadtest-N email.
_PHASE_A_USER_COUNT = 15
_PHASE_A_USER_OFFSET = _GENERATE_USER_COUNT
# Bounds how many per-user fixture uploads (real PDF upload + poll + real
# ingestion job) run concurrently during SETUP -- confirmed live that firing
# all 17 fully concurrently against a single local uvicorn process + single
# ARQ worker produced a real httpx.ReadTimeout (the single-process dev
# environment genuinely couldn't keep up with 17 truly-simultaneous real
# uploads+ingestions). This throttles fixture SETUP only -- Phase A's and
# Phase B's own scenario concurrency (the actual thing Story 5-1 measures)
# is untouched.
_FIXTURE_SETUP_CONCURRENCY = 5

# apps/api/tests/loadtest/run.py -> parents[2] == apps/api
_API_ROOT = Path(__file__).resolve().parents[2]
_REPORT_PATH = _API_ROOT.parent.parent / "docs" / "reports" / "load-test-5-1-results.md"


def _base_url() -> str:
    return os.environ.get("LOADTEST_BASE_URL", _DEFAULT_BASE_URL)


async def _setup_fixtures_bounded(base_url: str, users: list[TestUser]) -> list[tuple[str, str]]:
    """Run `ensure_book_chapter_fixture` for every user in `users`, bounded to
    `_FIXTURE_SETUP_CONCURRENCY` concurrent uploads+ingestions at a time --
    confirmed live (4th full-run attempt) that firing all 17 fully
    concurrently produced a real `httpx.ReadTimeout` against a single local
    uvicorn process + single ARQ worker. Order of the returned list matches
    `users`, same contract `asyncio.gather` gave callers before this change."""
    semaphore = asyncio.Semaphore(_FIXTURE_SETUP_CONCURRENCY)

    async def _one(user: TestUser) -> tuple[str, str]:
        async with semaphore:
            return await ensure_book_chapter_fixture(base_url, user)

    return await asyncio.gather(*(_one(u) for u in users))


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
        # Ownership of books/chapters is enforced per-user at the application
        # layer (generate_chapter_lesson 404s for a book/chapter the caller
        # doesn't own) -- a single SHARED fixture across many distinct users
        # is not viable, so every user gets their OWN real, uploaded, ready
        # book+chapter. This requires each generate_user's email to also be
        # on APPROVED_EMAILS (upload_lesson's allowlist), not just a valid
        # JWT -- see apps/api/.env's loadtest-{n}-deleteme@seed.test entries.
        # Only the users this run's round-robin will ACTUALLY use need a
        # fixture (min(total_requests, len(generate_users)) distinct users),
        # keeping the smoke test cheap rather than provisioning all 17.
        users_needing_fixtures = generate_users[: min(_SMOKE_TOTAL_REQUESTS, len(generate_users))]
        logger.info(
            "Smoke run: uploading %d per-user book+chapter fixtures (real ingestion each)",
            len(users_needing_fixtures),
        )
        fixture_pairs = await _setup_fixtures_bounded(base_url, users_needing_fixtures)
        user_fixtures = {
            u.user_id: pair for u, pair in zip(users_needing_fixtures, fixture_pairs, strict=True)
        }

        logger.info("Smoke run: Phase B, %d concurrent generate requests", _SMOKE_TOTAL_REQUESTS)
        phase_b_result = await run_phase_b(
            base_url=base_url,
            generate_users=generate_users,
            user_fixtures=user_fixtures,
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
    # Phase A also gets its own disposable pool now (offset past Phase B's
    # index range -- see _PHASE_A_USER_OFFSET). Both pools are cleaned up in
    # `finally` below; since these are disposable auth.users rows, deleting
    # them cascades away any books/chapters/chunks they created too (see
    # provisioning.py's cleanup_generate_test_users docstring) -- no separate
    # book-only cleanup is needed the way it was for the old real-account
    # design.
    phase_a_users: list[TestUser] = []
    try:
        logger.info("Full run: provisioning %d disposable Phase A users", _PHASE_A_USER_COUNT)
        phase_a_users = await provision_generate_test_users(
            _PHASE_A_USER_COUNT, offset=_PHASE_A_USER_OFFSET
        )

        logger.info(
            "Full run: Phase A, %d concurrent upload requests (mixing the small "
            "synthetic fixture with a real ~19.7MB book)",
            _FULL_TOTAL_REQUESTS,
        )
        phase_a_result = await run_phase_a(
            base_url=base_url,
            approved_users=phase_a_users,
            concurrency=_FULL_TOTAL_REQUESTS,
        )

        # Ownership of books/chapters is enforced per-user at the application
        # layer (generate_chapter_lesson 404s for a book/chapter the caller
        # doesn't own) -- a single SHARED fixture across 17 distinct users is
        # not viable, so every user gets their OWN real, uploaded, ready
        # book+chapter (each generate_user's email is also on
        # APPROVED_EMAILS -- see apps/api/.env's loadtest-{n}-deleteme@seed.test
        # entries -- so each can use the real upload endpoint themselves).
        # This is 17 real ingestion runs before Phase B even starts -- slower
        # and more real-cost than a single shared fixture, a deliberate
        # tradeoff for a more realistic end-to-end test (chosen explicitly
        # over directly seeding rows via service-role).
        logger.info(
            "Full run: uploading %d per-user book+chapter fixtures (real ingestion each)",
            len(generate_users),
        )
        fixture_pairs = await _setup_fixtures_bounded(base_url, generate_users)
        user_fixtures = {
            u.user_id: pair for u, pair in zip(generate_users, fixture_pairs, strict=True)
        }

        logger.info(
            "Full run: Phase B, %d concurrent generate requests across %d users",
            _FULL_TOTAL_REQUESTS,
            len(generate_users),
        )
        phase_b_result = await run_phase_b(
            base_url=base_url,
            generate_users=generate_users,
            user_fixtures=user_fixtures,
            total_requests=_FULL_TOTAL_REQUESTS,
        )

        # Both race probes run AFTER Phase A/B's real load has already
        # completed and produced valid, reportable data -- each is wrapped in
        # its own try/except so a probe-side failure (e.g. a disposable
        # user's token expiring, a transient network error) can never
        # propagate out of `_run_full` and discard that already-collected
        # Phase A/B data. Found the hard way on run #8 (2026-09-03): a bare
        # `RuntimeError` from `_list_all_chapter_ids` on a 401 propagated
        # uncaught all the way out of `_main_async`, so the script exited 1
        # BEFORE `build_report`/`_write_report` ever ran -- a fully successful
        # 50-concurrent Phase A/B run was silently lost with no report at
        # all. Each except below turns that failure into an "error"-shaped
        # probe dict instead (see `report._render_race` / `_race_summary_label`),
        # so the report always gets written and states plainly that the
        # probe itself failed -- never confused with "ran and did not
        # reproduce the race".
        race_d45: dict[str, Any]
        try:
            d45_user = generate_users[0]
            d45_book_id, d45_chapter_id = user_fixtures[d45_user.user_id]
            logger.info("Full run: D45 idempotency race probe")
            race_d45 = await probe_d45_idempotency_race(
                base_url=base_url,
                user=d45_user,
                book_id=d45_book_id,
                chapter_id=d45_chapter_id,
            )
        except Exception as exc:  # noqa: BLE001 -- deliberately broad, see comment above
            logger.warning("D45 race probe failed with an unexpected error: %s", exc)
            race_d45 = {"reproduced": False, "error": str(exc)}

        race_gate7: dict[str, Any]
        try:
            gate7_user = generate_users[1]
            gate7_book_id, gate7_chapter_id = user_fixtures[gate7_user.user_id]
            logger.info("Full run: listing chapters for the Gate-7 race probe")
            all_chapter_ids = await _list_all_chapter_ids(base_url, gate7_user, gate7_book_id)
            # Exclude the ONE chapter Phase B already used for gate7_user (that
            # user's own Phase-B request already submitted a
            # (gate7_chapter_id, tier="T2") generate request against it) -- if
            # that chapter were left in the candidate list, one of the 4
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
            chapter_ids = [c for c in all_chapter_ids if c != gate7_chapter_id]
            if len(chapter_ids) < _GATE7_MIN_CHAPTERS:
                logger.warning(
                    "Gate-7 race probe SKIPPED: fixture book %s has only %d detected "
                    "chapter(s) other than the one Phase B already used, need >= %d "
                    "distinct, untouched chapters to attempt oversubscription without "
                    "risking an idempotent-replay false positive. Upload a larger "
                    "fixture book to enable this probe.",
                    gate7_book_id,
                    len(chapter_ids),
                    _GATE7_MIN_CHAPTERS,
                )
                race_gate7 = {}
            else:
                race_gate7 = await probe_gate7_concurrency_race(
                    base_url=base_url,
                    user=gate7_user,
                    book_id=gate7_book_id,
                    chapter_ids=chapter_ids[:_GATE7_MIN_CHAPTERS],
                )
        except Exception as exc:  # noqa: BLE001 -- deliberately broad, see comment above
            logger.warning("Gate-7 race probe failed with an unexpected error: %s", exc)
            race_gate7 = {"reproduced": False, "error": str(exc)}

        return [phase_a_result, phase_b_result], race_d45, race_gate7
    finally:
        # Both pools are cleaned up even if one fails, and even if the `try`
        # block above raised partway through -- a disposable user (and,
        # via cascade, everything they created) leaking onto the real
        # project must not depend on the rest of the run succeeding.
        try:
            await cleanup_generate_test_users(generate_users)
        finally:
            if phase_a_users:
                await cleanup_generate_test_users(phase_a_users)


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
