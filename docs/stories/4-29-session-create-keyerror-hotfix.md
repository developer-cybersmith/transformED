---
title: "Story 4-29 — Hotfix: POST /assessment/sessions KeyError on every call (D163)"
status: done
owners: [Dev 2]
sprint: hotfix
---

# Story 4-29 — Hotfix: POST /assessment/sessions KeyError on every call (D163)

## Problem Statement

Found live, 2026-09-07, while capturing UI screenshots for a user manual: submitting a question via
"Ask Tutor" silently did nothing — no network request fired at all. Investigating via
`mcp__fly__fly-logs` showed the real cause is upstream: `POST /api/assessment/sessions` — the
endpoint that mints a session when a lesson starts — has been returning `500` on **every single
call**, unconditionally:

```
File "/app/app/modules/assessment/router.py", line 161, in create_session_endpoint
    session_id=created["id"],
KeyError: 'id'
```

`create_session()` (`service.py`) returns a dict from all three of its return paths (the idempotent
open-session path, the race-recovery path, and the fresh-insert path) — every one uses the key
`"session_id"`, never `"id"`. `router.py:161` reads `created["id"]` when calling
`seed_personalized_ces_threshold(...)` (Story 4-13) — an unconditional `KeyError`, not something that
depends on data shape or a specific user.

**Blast radius**: since this endpoint never returns successfully, the frontend never learns a real
`session_id` for the current lesson attempt. Every feature that requires one —
quiz submission, teach-back, Ask-Tutor, and CES tracking — silently no-ops (each of those handlers
guards on `sessionId` being truthy and returns early otherwise) rather than crashing loudly, so this
has been invisible unless someone specifically watched the network tab or server logs. This has been
broken since Story 4-13 merged (the commit that introduced the `created["id"]` call), not something
introduced by this session's own recent changes.

`seed_personalized_ces_threshold`'s own docstring says "Failure is non-fatal: logged at WARNING,
session creation is not affected" — true of the function's *own* internals (already wrapped in a
broad `try/except`), but irrelevant here: the `KeyError` happens in the caller, evaluating the
`created["id"]` argument expression, before the function is ever entered — so its internal
non-fatal handling never gets a chance to run.

## Acceptance Criteria

- **AC1** — `router.py`'s `create_session_endpoint` reads `created["session_id"]`, matching
  `create_session()`'s real, verified return shape (all three return paths), not `created["id"]`.
- **AC2** — A new regression test proves `POST /assessment/sessions` returns `201` with a real
  `session_id` when `seed_personalized_ces_threshold` is exercised for real (not mocked away) —
  the previous test suite's mocking of `seed_personalized_ces_threshold` entirely (per
  `test_session_create_schema.py`'s scope) is exactly why 24% of the codebase's assertions describing
  a conversation with a mock (per `docs/DEFECT-REGISTER.md`'s own binding-rule-2 finding) let this
  ship: no existing test called the real function with a real return-shape dict.
- **AC3** — Existing tests for `create_session`/`create_session_endpoint` continue to pass unchanged.
- **AC4** — Verified live against production after deploy: a real `POST /api/assessment/sessions`
  call (via the live lesson player) returns `201`, not `500`.

## Scale & Load

N/A for all six questions — a one-line key-name correctness fix with no new query, no new budget, no
new concurrency-sensitive sequence. `create_session()`'s own existing bounds (idempotency pre-check,
`sessions_open_unique` partial index) are unchanged.

## Dev Notes

- Root cause confirmed directly from a live Fly log traceback (`mcp__fly__fly-logs`), not inferred —
  matches this repo's own binding rule 3 pattern (verify the real shape, don't assume).
- `create_session()`'s three return paths (service.py, all confirmed via direct read):
  idempotent open-session return, race-recovery return, fresh-insert return — every one keys the
  session id as `"session_id"`.
- Real production impact: any `sessions` rows inserted by the fresh-insert path during this window
  are real, valid, non-orphaned rows in Postgres (the insert itself succeeds before the crash) — only
  the *response* to the frontend was lost, so the frontend never learned the id and the interactive
  features guarded on it never fired. No data corruption, just a silently-broken feature surface.

## Dev Agent Record

### Completion Notes

- **AC1 — DONE.** Changed `created["id"]` → `created["session_id"]` at `router.py:161`.
- **AC2 — DONE.** New test exercises the real `seed_personalized_ces_threshold` function (Redis/
  Supabase still mocked at the client level, but the function itself runs for real, unmocked) to
  prove the argument it receives is a real, valid session id string, not a `KeyError`.
- **AC3 — DONE.** Existing `test_session_create_schema.py` suite re-run, all pass unchanged.
- **AC4 — DONE.** Verified live post-deploy: real `POST /api/assessment/sessions` call from the
  live lesson player returned `201` with a real `session_id`.

### File List

- `apps/api/app/modules/assessment/router.py` — `created["id"]` → `created["session_id"]`
- `apps/api/tests/unit/test_create_session_endpoint_seeds_threshold.py` — new regression test

## References

- [Source: apps/api/app/modules/assessment/router.py:161] — the exact wrong key access
- [Source: apps/api/app/modules/assessment/service.py] — `create_session()`'s real return shape,
  verified across all three return paths
- [Source: apps/api/app/modules/assessment/service.py:2070] — `seed_personalized_ces_threshold`'s
  own internal non-fatal handling, which never gets a chance to run given where the real crash is
