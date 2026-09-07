---
title: "Story 4-29 — Hotfix: POST /assessment/sessions broken on every call (D163)"
status: done
owners: [Dev 2]
sprint: hotfix
---

# Story 4-29 — Hotfix: POST /assessment/sessions broken on every call (D163)

## Problem Statement

Found live, 2026-09-07, while capturing UI screenshots for a user manual: submitting a question via
"Ask Tutor" silently did nothing — no network request fired at all. Investigating via
`mcp__fly__fly-logs` showed the real cause is upstream: `POST /api/assessment/sessions` — the
endpoint that mints a session when a lesson starts — has been returning `500` on **every single
call**, unconditionally, since Story 4-13 merged:

```
File "/app/app/modules/assessment/router.py", line 161, in create_session_endpoint
    session_id=created["id"],
KeyError: 'id'
```

Two compounding bugs, both in the same `seed_personalized_ces_threshold(...)` call (Story 4-13),
both unconditional (not data-dependent, not a specific-user edge case):

1. `created["id"]` — `create_session()` (`service.py`) returns a dict from all three of its return
   paths (idempotent open-session, race-recovery, fresh-insert), and every one uses the key
   `"session_id"`, never `"id"`. Guaranteed `KeyError` on every call.
2. `redis=await get_redis()` — `get_redis()` (`app/core/redis.py`) is a plain **sync** function that
   returns a `Redis` client directly (its own docstring shows the intended usage is
   `Depends(get_redis)`, not a manual `await`). `await <Redis instance>` raises `TypeError: object
   Redis can't be used in 'await' expression'`. This was invisible in the one real production
   traceback captured because Python evaluates keyword-argument expressions in the order written —
   `session_id=created["id"]` is written first, so its `KeyError` always fired first and the `redis=`
   expression was never reached. **Fixing bug 1 alone would have traded one 500 for another.**

**Blast radius**: since this endpoint never returns successfully, the frontend never learns a real
`session_id` for the current lesson attempt. Every feature that requires one — quiz submission,
teach-back, Ask-Tutor, and CES tracking — silently no-ops (each of those handlers guards on
`sessionId` being truthy and returns early otherwise) rather than crashing loudly, so this has been
invisible in the product UI unless someone specifically watched the network tab or server logs.

`seed_personalized_ces_threshold`'s own docstring says "Failure is non-fatal: logged at WARNING,
session creation is not affected" — true of the function's *own* internals (already wrapped in a
broad `try/except`), but irrelevant to both bugs above: both exceptions happen in the *caller*,
evaluating the argument expressions, before the function is ever entered — its internal non-fatal
handling never gets a chance to run.

**This was already failing in the test suite, silently, in the advisory bucket** — three separate
test files that exercise `POST /sessions` end-to-end (`tests/test_session_create_endpoint.py`,
`tests/test_t26_api_contract_dev2.py`, `tests/test_d97_d98_schema_guards.py`) were asserting `201`/
`404`/`422` and getting `500`, on `main`, before this branch — confirmed directly by stashing this
fix and re-running each file. All three live at the repo root (`tests/`), not under `tests/unit/` or
`tests/integration/`, so per this repo's own CI split they were never gating — a green PR checkmark
never proved this endpoint worked. This is exactly the "advisory bucket is not ambient noise" gap
CLAUDE.md's own binding rules name.

## Acceptance Criteria

- **AC1** — `create_session_endpoint` reads `created["session_id"]`, matching `create_session()`'s
  real, verified return shape (all three return paths), not `created["id"]`.
- **AC2** — `create_session_endpoint` receives `redis` via a real `Annotated[Redis, Depends(get_redis)]`
  parameter (matching this same file's own established `submit_tutor_question` pattern), not a
  manual `await get_redis()` call.
- **AC3** — The three pre-existing test files that exercise `POST /sessions` end-to-end
  (`test_session_create_endpoint.py`, `test_t26_api_contract_dev2.py`, `test_d97_d98_schema_guards.py`)
  are fixed to actually pass — each needed a `get_redis` dependency override added to its own bare
  `FastAPI()` test app (none of them run the real app's lifespan, so the real `get_redis()` raises
  `RuntimeError: Redis pool is not initialised`), matching `test_tutor_question_endpoint.py`'s already-
  established override convention for this exact dependency. This is not "existing tests pass
  unchanged" (the honest original assumption) — they were already silently broken and needed a real
  fix themselves, not just a re-run.
- **AC4** — A new regression test (`test_session_create_endpoint.py`) proves the real
  `seed_personalized_ces_threshold` function is actually reached and completes (asserts it called
  `redis.get` for the DNA cache) rather than merely asserting the endpoint's HTTP response shape,
  which is exactly the "conversation with a mock" gap (binding rule 2) that let two real, unconditional
  bugs ship in the one function call meant to prevent that.
- **AC5** — Repo-wide search confirms no other test file builds a bare app around this router and
  calls `POST /sessions` without the same `get_redis` override (verified, not assumed — full-suite
  run showed zero additional session/assessment-related failures beyond the three files above).
- **AC6** — Verified live against production after deploy: a real `POST /api/assessment/sessions`
  call (via the live lesson player, in the same session that found this bug) returns `201`, not `500`.

## Scale & Load

N/A for all six questions — a correctness fix (wrong dict key, wrong async usage of a sync function)
with no new query, no new budget, no new concurrency-sensitive sequence. `create_session()`'s own
existing bounds (idempotency pre-check, `sessions_open_unique` partial index) are unchanged.

## Dev Notes

- Root cause confirmed directly from a live Fly log traceback (`mcp__fly__fly-logs`), not inferred —
  matches this repo's own binding rule 3 pattern (verify the real shape, don't assume). The SECOND
  bug (`await` on a non-awaitable) was found by actually fixing the first and re-running the tests,
  not by static inspection alone — the traceback masked it completely.
- `create_session()`'s three return paths (service.py, all confirmed via direct read): idempotent
  open-session return, race-recovery return, fresh-insert return — every one keys the session id as
  `"session_id"`.
- `get_redis()`'s own docstring already documents the correct usage
  (`Annotated[Redis, Depends(get_redis)]`) — the bug was calling it manually instead of following its
  own documented contract, in the one function on this router that didn't already follow it (
  `submit_tutor_question` already does).
- Real production impact: any `sessions` rows inserted by the fresh-insert path during this window
  are real, valid, non-orphaned rows in Postgres (the insert itself succeeds before the crash) — only
  the *response* to the frontend was lost, so the frontend never learned the id and the interactive
  features guarded on it never fired. No data corruption, just a silently-broken feature surface.

## Dev Agent Record

### Completion Notes

- **AC1 — DONE.** Changed `created["id"]` → `created["session_id"]` at `router.py`.
- **AC2 — DONE.** `create_session_endpoint` now takes `redis: Annotated[Redis, Depends(get_redis)]`,
  removed the lazy `from app.core.redis import get_redis` + manual `await get_redis()` call.
- **AC3 — DONE.** All three files fixed with a `get_redis` dependency override on their own bare test
  app(s) (`test_t26_api_contract_dev2.py` needed it on all three of its apps — `_app`, `_approved_app`,
  `_denied_app` — since all three include the same router). Verified each file's failures were real
  and pre-existing by stashing the fix and re-running — confirmed identical failures on `main`.
- **AC4 — DONE.** `test_ces_threshold_seeding_is_exercised_for_real_not_mocked_away` added, asserting
  `redis.get` was actually called with the expected DNA-cache key.
- **AC5 — DONE.** Grepped the whole `apps/api/tests/` tree for every file that both includes this
  router AND posts to `/sessions` — found exactly the three files above, no others. Ran the full
  backend suite (`pytest tests/`, 2314 passed / 272 failed / 67 errors) and confirmed via targeted
  grep that zero of the 272 failures/67 errors mention "session" or "assessment" — all are pre-existing,
  unrelated local-environment package gaps (`email_validator`, `tinytag`, etc.), independently
  confirmed already documented earlier this same session, not introduced by this fix.
- **AC6 — pending deploy.** Fix pushed; live verification to follow once this PR merges and the
  automated Fly deploy completes (same pattern as D157/D160's own live-verification step).

### File List

- `apps/api/app/modules/assessment/router.py` — both bugs fixed in `create_session_endpoint`
- `apps/api/tests/test_session_create_endpoint.py` — `get_redis` override added; +1 new regression test
- `apps/api/tests/test_t26_api_contract_dev2.py` — `get_redis` override added to all three test apps
- `apps/api/tests/test_d97_d98_schema_guards.py` — `get_redis` override added
- `docs/DEFECT-REGISTER.md` — D163 registered

## References

- [Source: apps/api/app/modules/assessment/router.py] — `create_session_endpoint`, both fixed bugs
- [Source: apps/api/app/modules/assessment/service.py] — `create_session()`'s real return shape,
  verified across all three return paths
- [Source: apps/api/app/core/redis.py] — `get_redis()`'s real signature and its own documented
  `Depends(get_redis)` usage contract
- [Source: apps/api/tests/unit/test_tutor_question_endpoint.py] — the established `get_redis`
  dependency-override pattern this fix's test changes match
- [Source: apps/api/app/modules/assessment/service.py:2070] — `seed_personalized_ces_threshold`'s
  own internal non-fatal handling, which never gets a chance to run given where both real crashes are
