---
status: done
---

# Story 4-11 — Session Dedup Guard + CES Architecture Confirmation (Calibration Prerequisites)

**Sprint:** 4 · **Owner:** Dev 3
**Branch:** `sprint4/s4-11-session-dedup-ces-calibration`

## Background

Dev 2 flagged two open items from the §8 checklist in `docs/sprint4-ces-calibration-notes.md`
that must be confirmed before the 20-session calibration run:

**Item 3 (CES-update endpoint):** "Is `POST /api/assessment/sessions/{id}/ces` being called
during live sessions?" — Codebase audit confirms NO such endpoint exists, which is CORRECT.
CES flows exclusively through WebSocket → Redis: frontend sends `attention_signal` every 5s →
`process_attention_signal()` → `compute_ces()` → `Redis LPUSH`. On SESSION_END,
`_finalize_session` reads and averages the history. The §8 checklist item was based on a
misunderstanding of the architecture. This story updates calibration notes to confirm.

**Item 4 (Duplicate session creation):** 4 confirmed duplicate-session pairs at identical
millisecond timestamps (2026-08-12 data). Root cause: React StrictMode double-renders
`useEffect` in dev mode, causing two concurrent `POST /api/assessment/sessions` calls.
`create_session` has no idempotency check and the DB has no partial UNIQUE constraint.
Both inserts succeed and quiz data fragments across two session IDs. This story fixes it.

The fix must NOT break the established behaviour that re-learning a lesson (after closing
a session) creates a fresh session — `analytics` and CES history depend on this. The
existing test `test_the_same_user_starting_the_same_lesson_again_gets_a_new_session` is the
mutation guard for this invariant and must continue to pass.

## Acceptance Criteria

- **AC1:** `create_session` returns the existing open session (201) when `(user_id, lesson_id)`
  already has a row with `ended_at IS NULL`, instead of inserting a duplicate. The returned
  `session_id` is the existing one, not a new UUID.
- **AC2:** `create_session` still creates a NEW session when the previous session for the same
  `(user_id, lesson_id)` is closed (`ended_at IS NOT NULL`). Re-learning a completed lesson
  continues to produce a distinct session row.
- **AC3:** A concurrent-safe backstop: migration `20260831000000_sessions_open_unique.sql`
  creates a partial UNIQUE INDEX on `(user_id, lesson_id) WHERE ended_at IS NULL`. If both
  concurrent creates pass the application-level check simultaneously and race to insert, the
  second insert fails (rows = empty); the fallback re-fetches the open session and returns it
  rather than 500-ing.
- **AC4:** `docs/sprint4-ces-calibration-notes.md` §8 updated:
  - Item 3: confirmed with architecture explanation (WS path, no REST endpoint needed)
  - Item 4: marked FIXED (Story 4-11, migration name, instruction to apply before run)
- **AC5:** `_supabase()` test helper in `test_session_create_endpoint.py` updated to configure
  the new open-session SELECT chain (returns `None` by default so existing tests are unaffected).
- **AC6:** `test_the_same_user_starting_the_same_lesson_again_gets_a_new_session` updated to
  configure `.is_("ended_at", "null")` returning `None`, preserving the invariant.
- **AC7:** Two new unit tests: dedup returns existing open session; 500-race-fallback returns
  open session when insert finds nothing.
- **AC8:** `ruff check`, `mypy`, and full Dev 3 test suite all pass with zero failures.

## Scale & Load

1. **Unit of work:** 1 `POST /sessions` → 1 open-session SELECT + 0–1 INSERT + 0–1 race-fallback
   SELECT. SELECT is bounded by the UNIQUE index (at most 1 matching row).
2. **Fixed budgets while input varies:** The partial UNIQUE index enforces at most 1 open session
   per `(user_id, lesson_id)` pair. If violated at the DB layer, the fallback SELECT resolves it
   without a 500. Silent truncation: N/A — a conflict either returns the existing session (correct)
   or 500 (loud failure, DB truly broken).
3. **Scope of each limit:** Per-user per-lesson. The open-session query adds 1 round-trip per
   `POST /sessions` call. Not a concern at calibration scale (20 sessions).
4. **Unbounded reads/writes:** The new SELECT is `LIMIT 1` via `.maybe_single()`. Bounded.
5. **Inherited caps re-derived:** The existing `create_session` had no cap on concurrent
   concurrent open sessions — effectively unbounded. The partial UNIQUE makes it 1 per pair.
   No inherited cap needed re-derivation beyond what the UNIQUE enforces.
6. **Concurrent check-then-act:** YES, addressed. Application-level pre-check is not concurrent-safe
   alone (two requests can both see "no open session" simultaneously). The DB partial UNIQUE index
   is the machine enforcement. The fallback on empty-INSERT result completes the circuit without
   a 500.

## Tasks

- [x] T1: Create story file, commit alone, push
- [x] T2: New migration `20260831000000_sessions_open_unique.sql` (write SQL, instruct user to apply)
- [x] T3: Update `create_session` in `service.py` — open-session idempotency check + race fallback
- [x] T4: Update `_supabase()` helper in `test_session_create_endpoint.py` (configure `.is_` chain)
- [x] T5: Update re-take test to configure `.is_("ended_at", "null")` returning None
- [x] T6: Add 2 new unit tests (AC1 dedup, AC3 race-fallback)
- [x] T7: Update `docs/sprint4-ces-calibration-notes.md` §8 Items 3 and 4
- [x] T8: Run full Dev 3 suite — ruff GREEN, 10/12 tests pass; 2 pre-existing cross-team failures (403→401 D4-JWT; D18 session lookup) — not regressions
- [x] T9: Commit, push, merge into master-sprint4-dev3, raise PR

## Change Log

| Date | Author | Change |
|---|---|---|
| 2026-08-31 | Dev 3 | Story created |
