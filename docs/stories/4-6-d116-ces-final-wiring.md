---
status: done
---

# Story 4-6 — D116: Wire complete_session to dispatch_event so ces_final is written

**Sprint:** 4 · **Owner:** Dev 3 (assessment/service.py) + Dev 4 (graph.py routing + _finalize_session)  
**Defect:** D116 (DEFECT-REGISTER.md) — `complete_session` and `_finalize_session` were never connected  
**Detected:** 2026-08-29 (Sprint 4 Task 1 CES calibration analysis)

## User Story

As the system, when a student completes a lesson, I want `sessions.ces_final` to be written automatically so that CES calibration, weight tuning, and Learner DNA fusion all have the data they depend on.

## Background

`ces_final` has been NULL on every session ever run (117 sessions, 0 ces_final). Root cause: two code paths were built independently:

- `complete_session` (assessment/service.py) — writes `ended_at` only; called by `Player.tsx` on ENDED
- `_finalize_session` (tutor/state_machine/graph.py) — writes `ces_final`+`ended_at`; only reachable via `dispatch_event("lesson_complete")` over WebSocket — an event the frontend never sends

Additionally, `lesson_complete` only routes to `session_end` from TEACHING state. From IDLE, CHECKING_IN, QUIZZING, TEACH_BACK, or INTERVENING it routes incorrectly (stays in current state or returns to teaching), so even a direct WS dispatch would fail from non-TEACHING states.

## Acceptance Criteria

- **AC1:** After `POST /api/assessment/sessions/{id}/complete` returns 200, a subsequent `SELECT ces_final FROM sessions WHERE session_id = ?` returns a non-NULL value (when at least one CES window existed in Redis)
- **AC2:** After `complete_session` returns on a session with empty Redis `ces_history`, `ces_final` is NULL (None — distinguishable from zero engagement; correct behaviour unchanged)
- **AC3:** Calling `complete_session` twice on the same session dispatches `lesson_complete` exactly once (idempotency: second call hits the `ended_at` early-return guard before dispatch)
- **AC4:** `dispatch_event("lesson_complete")` routes to `session_end` node from ALL FSM states: IDLE, TEACHING, INTERVENING, CHECKING_IN, QUIZZING, TEACH_BACK (not just TEACHING)
- **AC5:** `_finalize_session` no longer writes `ended_at` — only `ces_final`. `complete_session` is the sole writer of `ended_at`
- **AC6:** A `dispatch_event` failure inside `complete_session` does NOT raise an HTTP error — `ended_at` is already written; the failure is logged at ERROR and captured to Sentry
- **AC7:** All existing CES and assessment tests pass with no regressions

## Scale & Load

1. **Unit of work:** One `complete_session` call → one `dispatch_event` call → one LangGraph invocation (runs `session_end_node`) → one `asyncio.create_task(_finalize_session)` → one Supabase `.update({"ces_final": ...})`. Range: identical for sessions of any length.
2. **Fixed budgets while input varies:** `_finalize_session` reads `lrange 0..9` from Redis (BOUNDED: `_CES_HISTORY_MAX=10`). No change to this bound. `complete_session` adds one async Python call (`await dispatch_event`) — latency impact ~50–200ms; acceptable for a session-terminal endpoint.
3. **Scope of each limit:** Per-session (one dispatch per session_id). MemorySaver is process-local and accumulates per thread_id=session_id — fine because all channels in TutorMachineState are scalar (no `Annotated[list, operator.add]`).
4. **Unbounded reads/writes:** None introduced. The new `dispatch_event` call adds no DB reads/writes beyond what `session_end_node` already did.
5. **Inherited caps re-derived:** `_CES_HISTORY_MAX=10` — unchanged. MemorySaver thread_id=session_id is unique per session attempt (not per lesson) — CLAUDE.md rule satisfied.
6. **Concurrent check-then-act safety:** `complete_session` has `.is_("ended_at", "null")` guard on the Supabase UPDATE (line 259) and an early return at line 249–251 if `ended_at` is already set. Only the first concurrent call writes and dispatches. Idempotent by construction — verified against Scale & Load Q6.

## Tasks

- [x] T1: Create story file (this file), commit alone, push
- [x] T2: Fix `route_entry` in graph.py — add universal `lesson_complete → session_end` guard before state dispatch
- [x] T3: Fix `_finalize_session` in graph.py — remove `ended_at` from update payload; `complete_session` owns that write
- [x] T4: Fix `complete_session` in assessment/service.py — add `await dispatch_event("lesson_complete")` with try/except after the ended_at write
- [x] T5: Write tests for AC1–AC6 (`test_d116_ces_final_wiring.py`) — 11 tests, all pass
- [x] T6: Run full test suite — 184 Dev 3 tests pass, 0 regressions
- [x] T7: Run ruff + mypy — lint clean

## Dev Notes

### Import strategy (no circular dependency)
`dispatch_event` lives in `app.modules.tutor.state_machine.graph`. That module does NOT import from `app.modules.assessment`, so the import is safe. Use a lazy import inside `complete_session` body (same pattern as `session_end_node` uses for `get_supabase`/`get_redis`) — avoids coupling at module level and keeps the assessment service independent of the tutor module at import time.

### Why `route_entry` not individual routing functions
`lesson_complete` is a terminal event that must route to `session_end` from ANY state. Adding the check to `route_entry` (before state-specific dispatch) is the minimal, non-duplicated fix. Six routing functions do not need to change.

### _finalize_session ownership split
`complete_session` owns `ended_at` (with idempotency guard). `_finalize_session` owns `ces_final`. Removes the double-write where `_finalize_session` overwrote `ended_at` ~100ms after `complete_session` wrote it. Note: if `session_end_node` is ever reached via a future WS `lesson_complete` dispatch without `complete_session` being called (e.g. a direct API test), `ended_at` will stay NULL. This is acceptable for MVP — `Player.tsx` always calls `complete_session` on lesson end.

### Test strategy
- Unit tests mock `dispatch_event`, `_read_state`, `_persist_state`, supabase
- Do NOT assert on MemorySaver internals — assert on observable outcomes (state returned, supabase calls made)
- The binding rule from DEFECT-REGISTER.md §binding rule 3: any `except` clause needs an executable premise assertion. No new exception type assumptions introduced here.

## Change Log

| Date | Author | Change |
|---|---|---|
| 2026-08-29 | Dev 3 | Story file created |
