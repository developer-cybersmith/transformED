---
id: "S3-35"
title: "Session finalization — write ces_final and ended_at via finalize_session in session_end_node (D11)"
status: Draft
sprint: 3
story_points: 3
owner: Dev3
branch: implemented/ces-fallback
decisions: D11, D15
depends_on: S3-42, S3-43, S3-44
migration: NO
---

# Story S3-35 — Session finalization: write ces_final and ended_at via finalize_session in session_end_node

## User Story

**As the system,**
**I want** `session_end_node` to call `finalize_session(session_id, supabase, redis)` when a
learner's lesson completes,
**so that** `sessions.ces_final` and `sessions.ended_at` are durably written exactly once —
enabling Learner DNA fusion, CES baseline computation, and accurate session reports for every
completed session.

## Context

`session_end_node` (`apps/api/app/modules/tutor/state_machine/graph.py:251-256`) currently
writes only the string `"SESSION_END"` to the Redis key `tutor_state:{session_id}` with a 24 h
TTL. It makes no DB write. The consequence cascade is audit-confirmed:

1. `sessions.ended_at` — permanently NULL. `dna_fusion.fuse_learner_dna()` guards on
   `ended_at IS NULL` and returns `None`, so Learner DNA never evolves beyond the onboarding
   baseline.
2. `sessions.ces_final` — permanently NULL. `get_session_report` returns `ces_score = 0.0`
   for every session. CES baseline (`ces_baseline.py`) has zero callers in application code;
   it is called only from tests because `ces_final` is always NULL.

**Decision D11:** The write pattern is
`UPDATE sessions SET ces_final = X, ended_at = NOW() WHERE session_id = Y AND ended_at IS NULL`.
The `WHERE ended_at IS NULL` predicate is the DB-level idempotency guard. A Redis NX
`session:{session_id}:finalize_lock` key is acquired first as a fast-path that prevents the DB
UPDATE from being attempted if another call has already finalized this session.

**Decision D15:** `compute_ces_from_session_aggregates(session_id, redis, settings)` is a shared
utility function called by both `finalize_session` and `get_session_report`. This ensures the
`ces_final` written to the DB and the `ces_score` returned in the session report are computed by
identical logic from the same Redis data.

**Merge dependencies (D16):** S3-42, S3-43, and S3-44 must merge to `main` before
`implemented/ces-fallback` (which contains this story's implementation) merges to `main`. S3-42
specifically populates the behavioral/head_pose/blink Redis history keys used by the CES
breakdown; S3-43 and S3-44 close security and correctness defects that are prerequisites for
the branch to be merge-ready.

## Acceptance Criteria

### AC1 — finalize_session is importable from assessment/service.py
`from app.modules.assessment.service import finalize_session` does not raise `ImportError`.
The function signature is `async def finalize_session(session_id: str, *, supabase, redis) -> dict[str, Any]`.
It must not accept positional arguments for `supabase` or `redis` (keyword-only enforced by `*`).

### AC2 — Redis NX finalize_lock acquired before any DB write
The first action inside `finalize_session` (after argument validation) is:
```
result = await redis.set(f"session:{session_id}:finalize_lock", "1", nx=True, ex=300)
```
If `result` is `None` or falsy (key already existed — NX semantics), `finalize_session` returns
immediately with `{"ces_final": None, "partial": False, "already_finalized": True}` and makes no
DB call. The lock TTL is exactly 300 s (not configurable in this story; no env var).

### AC3 — compute_ces_from_session_aggregates exists and is callable by both callers
`from app.modules.assessment.service import compute_ces_from_session_aggregates` does not
raise `ImportError`. Signature: `async def compute_ces_from_session_aggregates(session_id: str, redis, settings) -> float | None`.
The function reads `session:{session_id}:ces_history` via `redis.lrange(key, 0, -1)`, converts
entries to floats, and returns `round(statistics.mean(windows), 2)` when `len(windows) >= 5`,
or `None` when `len(windows) < 5` (including 0). Both `finalize_session` and `get_session_report`
call this function — not an inline reimplementation in each caller.

### AC4 — Partial session writes NULL ces_final but still sets ended_at
When `compute_ces_from_session_aggregates` returns `None` (fewer than 5 CES windows), the DB
UPDATE executes with `ces_final = NULL` and `ended_at = NOW()`. `ended_at` is always written on
SESSION_END — a partial session still has a recorded end time. The returned dict contains
`{"partial": True, "ces_final": None, "already_finalized": False}`.

### AC5 — DB UPDATE uses WHERE ended_at IS NULL predicate
The Supabase UPDATE call is:
```
supabase.table("sessions")
    .update({"ces_final": ces_final_value, "ended_at": "now()"})
    .eq("session_id", session_id)
    .is_("ended_at", None)
    .execute()
```
This is the DB-level fallback idempotency guard. When `ended_at` is already set (e.g., the Redis
lock expired after 300 s and a second call reached the DB), the UPDATE matches 0 rows and returns
without error. The function returns `{"ces_final": None, "partial": False, "already_finalized": True}`.

### AC6 — All Supabase calls in finalize_session are wrapped in asyncio.to_thread
Every Supabase client call inside `finalize_session` is wrapped in `asyncio.to_thread(lambda: ...)`
consistent with the established pattern throughout `assessment/service.py`. Calling the Supabase
sync client directly on the async event loop is a correctness defect (blocks the loop under load).

### AC7 — session_end_node calls finalize_session after _persist_state
In `session_end_node` (`graph.py:251-256`), after the existing
`await _persist_state(session_id, TutorState.SESSION_END)` call, a try/except block calls
`await finalize_session(session_id, supabase=..., redis=...)`. Any exception raised by
`finalize_session` is caught, logged at ERROR level with the session_id, and swallowed — the
FSM transition to SESSION_END is not rolled back. The `supabase` and `redis` clients are obtained
via `get_supabase()` / `get_redis()` lazy imports inside the node (same pattern as other nodes).

### AC8 — get_session_report calls compute_ces_from_session_aggregates for live CES
The `# Step 7` block in `get_session_report` (currently reading `row.get("ces_final")`) is
updated to: if `sessions.ces_final` is non-NULL, use the stored value; if NULL (session ongoing or
partial), fall back to `await compute_ces_from_session_aggregates(session_id, redis, settings)`.
The fallback result (or 0.0 when None) is the `ces_score` in the report. This ensures the live
CES breakdown and the finalized score are computed by the same function.

### AC9 — Unit test count: minimum 15, all passing under pytest -m unit
All 15 tests listed in the Test Requirements section exist in
`apps/api/tests/test_session_finalization.py` and pass under `pytest -m unit`.

### AC10 — ruff check 0 errors in modified files
`ruff check apps/api/app/modules/assessment/service.py apps/api/app/modules/tutor/state_machine/graph.py`
exits 0 with no errors or warnings.

## Tasks / Subtasks

- [ ] **T1** Write failing RED tests (all 15 from Test Requirements section)
- [ ] **T2** Implement `compute_ces_from_session_aggregates(session_id, redis, settings)` in `assessment/service.py`
  - Read `session:{session_id}:ces_history` via `lrange(key, 0, -1)`
  - Convert bytes/strings to float; guard against empty/corrupt entries
  - Return `round(statistics.mean(windows), 2)` if `len >= 5`, else `None`
  - Add `# BOUNDED: ltrim cap of _CES_HISTORY_MAX applied upstream in process_attention_signal` comment on the lrange call
- [ ] **T3** Implement `finalize_session(session_id, *, supabase, redis)` in `assessment/service.py`
  - Acquire `session:{session_id}:finalize_lock` via Redis SET NX (ex=300); return early with `already_finalized=True` if lock was not acquired
  - Call `compute_ces_from_session_aggregates(session_id, redis, get_settings())`
  - Execute UPDATE sessions via asyncio.to_thread with `.is_("ended_at", None)` predicate
  - Return `{"ces_final": ..., "partial": ..., "already_finalized": False}`
- [ ] **T4** Update `session_end_node` in `graph.py` to call `finalize_session` after `_persist_state`
  - Wrap in try/except; log ERROR and swallow; do not re-raise
  - Obtain supabase/redis clients via lazy imports inside the node
- [ ] **T5** Update `get_session_report` Step 7 to call `compute_ces_from_session_aggregates` as fallback
  - Use stored `ces_final` if non-NULL; fall back to computed value if NULL
- [ ] **T6** Run `ruff check` + `pytest -m unit` — confirm all pass
- [ ] **T7** 6-agent adversarial code review (Story Quality, Blind Hunter, Test Coverage, AC Completeness, Process Integrity, Scale & Load)

## Scale & Load

**Q1 — Unit of work and range:**
One unit = one call to `finalize_session` for one session. Per-call Redis operations: one SET NX
(`finalize_lock`) + one lrange (`ces_history`, bounded by `_CES_HISTORY_MAX = 10` entries). Per-call
DB operations: one SELECT (`started_at` — omitted if not needed for partial check) and one UPDATE.
Typical: 1 call per session end. Min: 0 calls (session never completes). Max: 2 concurrent calls
at exactly the same instant (handled by NX guard; see Q6). The UPDATE touches exactly 1 row.

**Q2 — Fixed budgets while input varies:**
`session:{session_id}:ces_history` is bounded by `_CES_HISTORY_MAX = 10` entries via `ltrim` in
`process_attention_signal` (`tutor/service.py:307`). The `lrange(0, -1)` read therefore reads at
most 10 entries regardless of session length. Explicit: `# BOUNDED: ltrim cap of _CES_HISTORY_MAX=10`
comment required on the lrange call. `sessions.ces_final` is `numeric(5,2)` — stores 0.00–100.00
without overflow (CES is clamped to [0, 100]). `finalize_lock` TTL is 300 s — hard-coded, not
configurable. If the lock expires before the UPDATE completes (Redis blip > 300 s), the DB
predicate `WHERE ended_at IS NULL` is the fallback guard; no silent wrong result occurs.

**Q3 — Scope of every limit:**
All limits are per-session. `finalize_lock` key is `session:{session_id}:finalize_lock`
(session-scoped). `ces_history` is `session:{session_id}:ces_history` (session-scoped). The DB
UPDATE is bounded by `WHERE session_id = <id>`. Worker-count independent: Redis is the shared
store across all FastAPI replicas.

**Q4 — Unbounded reads/writes:**
`lrange(key, 0, -1)` reads the full history list. Bounded by upstream `ltrim` cap of 10 entries.
Add `# BOUNDED: ltrim cap of _CES_HISTORY_MAX=10 applied upstream in process_attention_signal`
comment on the lrange call. No unbounded DB reads: the UPDATE targets exactly one row by primary
key (`session_id`). `get_session_report` already has `.maybe_single()` bounds on its reads.

**Q5 — Inherited caps re-derived:**
`_CES_HISTORY_MAX = 10` was sized in `tutor/service.py` for the real-time intervention trigger
(rolling window of last 10 CES values = 50 s at 5 s cadence). For finalization, this same cap
means `ces_final` is the mean of the last 50 s of a session — not the full-session mean. This is
accepted: at 5 s cadence, a 30-min lesson accumulates 360 windows, but ltrim retains only 10.
The semantics of `ces_final` are therefore "mean of the final 50 s of engagement" not "session
average". This is explicitly documented in the function docstring. The `< 5 windows → NULL` rule
(25 s minimum sample) is re-derived: fewer than 5 windows at session end means the session
produced < 25 s of CES data before SESSION_END fired, i.e., effectively no monitoring data.
`NULL` is the correct sentinel — not a fabricated score from 1-4 windows. The lock TTL of 300 s
is new and sized as 60× the expected UPDATE round-trip latency (< 5 s under normal load,
< 30 s under Railway cold-start; 300 s allows for extreme degradation without permanent lock).

**Q6 — Check-then-act under concurrency:**
Two callers can reach `finalize_session` simultaneously for the same session (e.g., WebSocket
disconnect fires at the same instant as an explicit `lesson_complete` event). Redis SET NX is
atomic: exactly one caller receives a truthy result; the other gets `None` and returns immediately
with `already_finalized=True`. If Redis is unavailable (NX call raises), the fast-path is skipped
and both callers reach the DB UPDATE. PostgreSQL's row-level locking and the `WHERE ended_at IS NULL`
predicate ensure only the first UPDATE modifies the row; the second matches 0 rows and is a no-op.
No advisory lock, UNIQUE constraint, or application-level mutex is needed beyond these two layers.
The `WHERE ended_at IS NULL` predicate is a safe check-then-act because the check and act are the
same SQL statement — there is no window between them.

## Security

- `session_id` is validated at the WebSocket route boundary by `_SESSION_ID_RE` (UUID format,
  `websocket.py:37`) before any Redis or DB operation. `finalize_session` trusts this validation
  and does not re-validate. The function is called only from server-side code (`session_end_node`,
  WebSocket disconnect handler) — never directly from client input.
- `finalize_session` writes only to the single `sessions` row identified by `session_id`. The
  Supabase UPDATE uses the service-role client (bypasses RLS), which is correct for server-side
  session lifecycle writes. Confirm the client passed to `session_end_node` is the service-role
  client, not the user JWT-scoped client.
- `ces_final` is a computed float derived from the Redis `ces_history` list populated by
  `process_attention_signal`. The CES history contains only numeric values pushed by server-side
  code; no user-controlled string reaches `ces_final`. There is no injection surface.
- The `finalize_lock` key uses a fixed literal value `"1"`. No user input reaches the lock value.
- `compute_ces_from_session_aggregates` reads only numeric float values from Redis (CES window
  history). A corrupt Redis entry (non-numeric) must be silently skipped (guarded by try/except
  float conversion) so that one corrupt window does not break finalization for the entire session.

## Test Requirements

All tests in `apps/api/tests/test_session_finalization.py`:

1. `test_finalize_session_importable` — `from app.modules.assessment.service import finalize_session` raises no ImportError; `inspect.iscoroutinefunction(finalize_session)` is True.
2. `test_compute_ces_from_session_aggregates_importable` — shared utility is importable and is `async`.
3. `test_finalize_session_acquires_nx_lock_and_writes_db` — mock redis.set returns truthy (NX acquired); mock lrange returns 10 window values; asserts Supabase UPDATE called with `ces_final` = mean rounded to 2 d.p. and `.is_("ended_at", None)` predicate.
4. `test_finalize_session_returns_already_finalized_when_lock_exists` — mock redis.set returns None (NX not acquired); asserts Supabase UPDATE is NOT called; return dict has `already_finalized=True`.
5. `test_finalize_session_partial_null_ces_final_with_ended_at_set` — mock lrange returns 4 entries (< 5); asserts Supabase UPDATE called with `ces_final=None`; return dict has `partial=True` and `ces_final=None`.
6. `test_finalize_session_partial_when_history_empty` — mock lrange returns empty list; asserts `ces_final=None`, `partial=True`, Supabase UPDATE still called.
7. `test_finalize_session_db_idempotent_zero_rows_updated` — mock UPDATE returns response with count 0 (ended_at already set); asserts no exception raised; return has `already_finalized=True`.
8. `test_finalize_session_supabase_calls_wrapped_in_to_thread` — assert `asyncio.to_thread` is used for the Supabase UPDATE call (inspect or mock to_thread).
9. `test_compute_ces_from_session_aggregates_returns_mean_for_10_windows` — call with 10 windows [50.0]*10; asserts return is 50.0.
10. `test_compute_ces_from_session_aggregates_returns_none_for_4_windows` — call with 4 windows; asserts return is None.
11. `test_compute_ces_from_session_aggregates_returns_none_for_empty_history` — call with empty lrange; asserts return is None.
12. `test_compute_ces_from_session_aggregates_skips_corrupt_entries` — lrange returns ["75.0", "not_a_number", "80.0", "70.0", "65.0", "60.0"]; asserts corrupt entry skipped, result = mean of 5 valid values.
13. `test_finalize_lock_ttl_is_300s` — capture args to redis.set; assert `ex=300` was passed.
14. `test_session_end_node_logs_and_swallows_finalize_session_exception` — patch `finalize_session` to raise RuntimeError; invoke `session_end_node`; assert FSM state is SESSION_END; assert no exception propagates; assert logger.error called.
15. `test_finalize_session_return_dict_shape` — successful call; assert return dict has exactly the keys `ces_final`, `partial`, `already_finalized`; assert types are (float|None, bool, bool).

## Decision References

- **D11** (this story): `UPDATE sessions SET ces_final=X, ended_at=NOW() WHERE session_id=Y AND ended_at IS NULL`; Redis NX finalize_lock as fast-path against double writes
- **D15**: Shared utility `compute_ces_from_session_aggregates(session_id, redis, settings) -> float | None`; called identically by both `finalize_session` and `get_session_report` so the stored score and the reported score are computed by the same code path

## Dependencies

- **S3-42** (CES breakdown accuracy, D72): populates `session:{session_id}:behavioral_history`,
  `head_pose_history`, `blink_history` Redis keys used by `get_session_report` Step 5 (ces_breakdown).
  Must merge to `main` before `implemented/ces-fallback` per D16.
- **S3-43** (JWT HS256 algorithm pin, D80): security prerequisite. Must merge to `main` before
  `implemented/ces-fallback` per D16.
- **S3-44** (LangGraph unique thread_id per dispatch, D66): correctness prerequisite for the tutor FSM.
  Must merge to `main` before `implemented/ces-fallback` per D16.

## Migration

**NO** — no new DB migration required. Both `sessions.ces_final` (nullable `numeric(5,2)`) and
`sessions.ended_at` (nullable `timestamptz`) exist in
`supabase/migrations/20260611000000_initial_schema.sql` (lines 178, 180). No schema change needed.

## BMAD Process Gate

- [ ] Story file committed first (this file, before any implementation)
- [ ] Story commit pushed to `implemented/ces-fallback` before any implementation
- [ ] RED tests written and failing before implementation
- [ ] GREEN implementation — all 15 tests pass
- [ ] REFACTOR — ruff 0 errors; no logic changes
- [ ] 6-agent adversarial code review completed
- [ ] `docs/dev3-assessment-tracker.md` updated

## Status

Draft
