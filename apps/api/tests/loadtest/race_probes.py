"""Race-condition probes for Story 5-1 (D45 idempotency + Gate 7 concurrency).

These functions fire N *truly simultaneous* HTTP requests (constructed and
launched together via `asyncio.gather`, never a sequential `for` loop with
`await`) against the real, running API described in
`docs/stories/5-1-load-test-50-concurrent.md`, in order to attempt to
reproduce two specific known-accepted races against
`POST /api/content/books/{book_id}/chapters/{chapter_id}/lessons`
(`generate_chapter_lesson`, `GENERATE_LESSON_PATH`, `router.py`):

  * D45 (`docs/DEFECT-REGISTER.md#D45`) — the `(chapter_id, tier)` idempotency
    pre-check (Gate 5) is a read-then-write with no lock and no database
    UNIQUE constraint to lean on, so two concurrent identical requests can
    both observe "no existing lesson" and both insert + enqueue + bill.
  * Gate 7 — the per-user concurrency count (`max_concurrent_generations_per_user`,
    default 3) is likewise a count-then-insert with no lock, so N concurrent
    requests for N *distinct* chapters (not blocked by D45, which only
    applies to the same `(chapter_id, tier)` pair) can all observe the same
    stale count and all be admitted past the cap.

Neither probe asserts a specific outcome — a probe that reproduces the race
is a genuine finding (existing mitigations are bounded, not a hard fix, per
both defects' "Accepted"/registered status), and a probe that does not
reproduce it is equally informative: it means the accepted mitigation
(idempotent-replay for D45; the 429 concurrency gate for Gate 7) held under
real concurrent load. This module only reports the literal HTTP outcome that
occurred — it does not editorialize about whether that outcome is "good" or
"bad".

Neither function executes anything on import; both are plain async
functions meant to be awaited by a harness/runner piece that also handles
result aggregation into `ScenarioResult` (see `tests/loadtest/models.py`).
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from tests.loadtest.models import TestUser

# Generous per-request timeout: these probes measure *acceptance* behavior
# (which of N simultaneous requests got past Gate 5 / Gate 7), not pipeline
# completion time, but the request must still wait for the full synchronous
# gate-check + INSERT + ARQ-enqueue path to return its 200/202/429 status
# code before the client sees anything.
_REQUEST_TIMEOUT_S = 30.0


def _generate_lessons_url(base_url: str, book_id: str, chapter_id: str) -> str:
    return f"{base_url.rstrip('/')}/api/content/books/{book_id}/chapters/{chapter_id}/lessons"


async def _post_generate_lesson(
    client: httpx.AsyncClient,
    url: str,
    access_token: str,
    tier: str = "T2",
) -> httpx.Response:
    """One POST to the generate-lesson endpoint. Never raises on 4xx/5xx —
    callers need the actual status code, not an exception, since a 429 or a
    second 200 is an expected possible outcome, not a client error."""
    return await client.post(
        url,
        json={"tier": tier},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=_REQUEST_TIMEOUT_S,
    )


def _extract_lesson_id(resp: httpx.Response) -> str | None:
    if resp.status_code not in (200, 202):
        return None
    try:
        body: Any = resp.json()
    except ValueError:
        return None
    lesson_id = body.get("lesson_id") if isinstance(body, dict) else None
    return str(lesson_id) if lesson_id is not None else None


async def probe_d45_idempotency_race(
    base_url: str,
    user: TestUser,
    book_id: str,
    chapter_id: str,
) -> dict[str, Any]:
    """Probe DEFECT-REGISTER.md D45's `(chapter_id, tier)` idempotency TOCTOU race.

    `generate_chapter_lesson`'s Gate 5 idempotency check is a read (any
    existing non-`failed` `lessons` row for this `(chapter_id, tier, user_id)`)
    followed by a write (INSERT a new `lessons` row + enqueue), with no lock
    and no database UNIQUE constraint between the two steps. D45 predicts
    that two requests arriving close enough together can both see "nothing
    exists yet" and both create a new lesson (both 202, two different
    `lesson_id`s, double the enqueue, double the bill) — the accepted
    mitigation is only the best-effort idempotent-replay branch (the second
    request finds the first request's row already inserted and gets a 200
    with the SAME `lesson_id` instead of creating a second one).

    This fires exactly 2 requests for the SAME `(chapter_id, tier)` as the
    SAME user, launched together in one event-loop tick via `asyncio.gather`
    (not a for-loop with sequential `await`, which would not test a race at
    all — the second request would trivially see the first request's
    already-committed row).

    Deliberately uses `tier="T1"`, NOT `"T2"`: `phase_b_generate.py` submits
    every one of its 50 requests at `tier="T2"` against this SAME shared
    `chapter_id`, across all `generate_users` including whichever user this
    probe is handed — by the time this probe runs (after Phase B's own
    polling has already driven every accepted lesson to a terminal status),
    a non-failed `(chapter_id, tier="T2", user_id)` lesson already exists for
    that user. Firing this probe at `tier="T2"` too would have BOTH requests
    deterministically find that pre-existing row and both get served an
    idempotent replay — a "not reproduced" result for the wrong reason (state
    already warmed by Phase B, not the mitigation surviving a genuine
    concurrent race). `tier="T1"` is untouched by Phase B, so Gate 5 starts
    from a genuinely empty precondition for this exact
    `(chapter_id, tier, user_id)` tuple, and this probe is a real test of the
    TOCTOU race rather than a foregone idempotent replay.

    Returns a dict:
        {
            "reproduced": bool,   # True only if the race was hit: BOTH
                                   # responses are 202 AND both lesson_ids are
                                   # present and DIFFERENT from each other
                                   # (two distinct lessons rows were created
                                   # for the same (chapter_id, tier, user_id)).
                                   # False for the expected mitigated outcome
                                   # (one 202-new + one 200-replay with the
                                   # SAME lesson_id) or any other non-double-
                                   # insert outcome (e.g. both raced into a
                                   # 429/409/422 for an unrelated reason).
            "responses": [int, int],
            "lesson_ids": [str | None, str | None],
            "note": str,          # plain-language description of what
                                   # literally happened, no editorializing.
        }
    """
    url = _generate_lessons_url(base_url, book_id, chapter_id)

    async with httpx.AsyncClient() as client:
        # Both coroutines are created and handed to gather() together, so
        # both requests are in flight before either's response is awaited —
        # this is what makes it a genuine simultaneity test rather than a
        # sequential retry.
        resp_a, resp_b = await asyncio.gather(
            _post_generate_lesson(client, url, user.access_token, tier="T1"),
            _post_generate_lesson(client, url, user.access_token, tier="T1"),
        )

    responses = [resp_a.status_code, resp_b.status_code]
    lesson_ids = [_extract_lesson_id(resp_a), _extract_lesson_id(resp_b)]

    reproduced = (
        responses[0] == 202
        and responses[1] == 202
        and lesson_ids[0] is not None
        and lesson_ids[1] is not None
        and lesson_ids[0] != lesson_ids[1]
    )

    if reproduced:
        note = (
            f"D45 REPRODUCED: both concurrent requests returned 202 with distinct "
            f"lesson_ids ({lesson_ids[0]}, {lesson_ids[1]}) — two lessons rows were "
            f"created and enqueued for the same (chapter_id={chapter_id}, tier=T1, "
            f"user_id={user.user_id})."
        )
    elif responses[0] == 202 and responses[1] == 200 and lesson_ids[0] == lesson_ids[1]:
        note = (
            f"Not reproduced: first request created lesson {lesson_ids[0]} (202), "
            f"second was served the idempotent replay (200, same lesson_id) — "
            f"Gate 5's best-effort mitigation held."
        )
    elif responses[1] == 202 and responses[0] == 200 and lesson_ids[0] == lesson_ids[1]:
        note = (
            f"Not reproduced: second request created lesson {lesson_ids[1]} (202), "
            f"first was served the idempotent replay (200, same lesson_id) — "
            f"Gate 5's best-effort mitigation held."
        )
    else:
        note = (
            f"Not a double-insert; also not the expected 202+200-replay shape. "
            f"status_codes={responses}, lesson_ids={lesson_ids} — inspect directly, "
            f"this may be an unrelated failure (e.g. rate limit, book-not-ready, "
            f"chapter-not-found)."
        )

    return {
        "reproduced": reproduced,
        "responses": responses,
        "lesson_ids": lesson_ids,
        "note": note,
    }


async def probe_gate7_concurrency_race(
    base_url: str,
    user: TestUser,
    book_id: str,
    chapter_ids: list[str],
) -> dict[str, Any]:
    """Probe Gate 7's per-user concurrency count-then-insert race.

    `generate_chapter_lesson`'s Gate 7 counts the caller's currently
    `generating` lessons (`.eq("status", "generating")`, age-bounded by D53's
    staleness cutoff) and rejects with 429 only if that count is already
    `>= max_concurrent_generations_per_user` (3). The count and the
    subsequent INSERT are not wrapped in any lock or transaction, so N
    concurrent requests can all run the count query before any of their
    INSERTs land, all observe a count under the cap, and all be admitted —
    oversubscribing the concurrency cap the same TOCTOU shape as D45, but on
    a COUNT rather than a single existence check.

    Each request targets a DISTINCT `chapter_id` (same user, same tier
    'T2') specifically so this probe isolates Gate 7: a repeated
    `(chapter_id, tier)` pair would additionally engage Gate 5's idempotency
    check (D45), conflating the two races. `len(chapter_ids)` must be `>= 4`
    (strictly more than the `max_concurrent_generations_per_user = 3` cap)
    for oversubscription to even be possible to observe.

    `book_id` is a single book shared by every `chapter_id` in the list — the
    endpoint path is scoped `/books/{book_id}/chapters/{chapter_id}/lessons`,
    so a chapter id alone is not a resolvable URL; the caller is responsible
    for passing distinct chapters that all belong to this one book (e.g. from
    one `GET /books/{book_id}/chapters` listing).

    All `len(chapter_ids)` requests are launched together in one event-loop
    tick via `asyncio.gather` (not a for-loop with sequential `await`).

    Returns a dict:
        {
            "reproduced": bool,       # True only if accepted_count > 3 (the
                                       # configured cap was oversubscribed).
                                       # False if accepted_count <= 3 and the
                                       # remainder were rejected (429) —
                                       # the existing Gate 7 mitigation held.
            "accepted_count": int,    # requests that returned 200 or 202
            "rejected_count": int,    # requests that returned 429 (or any
                                       # other non-2xx status)
            "status_codes": [int, ...],
            "note": str,
        }
    """
    if len(chapter_ids) < 4:
        raise ValueError(
            "probe_gate7_concurrency_race requires len(chapter_ids) >= 4 "
            f"(strictly more than max_concurrent_generations_per_user=3 to attempt "
            f"oversubscription); got {len(chapter_ids)}"
        )

    async with httpx.AsyncClient() as client:
        coros = [
            _post_generate_lesson(
                client,
                _generate_lessons_url(base_url, book_id, chapter_id),
                user.access_token,
                tier="T2",
            )
            for chapter_id in chapter_ids
        ]
        responses_list = await asyncio.gather(*coros)

    status_codes = [resp.status_code for resp in responses_list]
    accepted_count = sum(1 for code in status_codes if code in (200, 202))
    rejected_count = len(status_codes) - accepted_count

    reproduced = accepted_count > 3

    if reproduced:
        note = (
            f"Gate 7 REPRODUCED: {accepted_count} of {len(chapter_ids)} concurrent "
            f"requests (distinct chapters, one user) were accepted (200/202), "
            f"oversubscribing max_concurrent_generations_per_user=3. "
            f"status_codes={status_codes}"
        )
    else:
        note = (
            f"Not reproduced: {accepted_count} of {len(chapter_ids)} concurrent "
            f"requests were accepted (<= cap of 3), {rejected_count} were rejected — "
            f"Gate 7's 429 concurrency gate held. status_codes={status_codes}"
        )

    return {
        "reproduced": reproduced,
        "accepted_count": accepted_count,
        "rejected_count": rejected_count,
        "status_codes": status_codes,
        "note": note,
    }
