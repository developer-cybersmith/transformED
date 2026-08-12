# Story S3-44: LangGraph Unique thread_id Per Dispatch — Include job_try in Token (D66)

**Status:** Draft  
**Sprint:** 3  
**Branch:** `sprint3/s3-44-langgraph-thread-id`  
**Decision reference:** D66  
**Depends on:** None  
**Migration:** NO

---

## Story

**As a** system running the tutor FSM inside an ARQ worker,  
**I want** each call to `dispatch_event()` to use a `thread_id` that is unique per dispatch attempt,  
**so that** LangGraph's MemorySaver never accumulates stale checkpoint state across dispatches, never causes an unbounded memory leak over the worker's lifetime, and cannot silently re-append `Annotated[list, operator.add]` channels across reconnections or retries.

---

## Context

**Defect:** D66 — `apps/api/app/modules/tutor/state_machine/graph.py` line 490 uses `"thread_id": session_id` for every LangGraph dispatch via `dispatch_event()`.

**CLAUDE.md binding rule (verbatim):** "A LangGraph `thread_id` must be unique per pipeline attempt. `MemorySaver` is process-local and never evicted; reusing `thread_id=lesson_id` retains accumulated channels across retries and across the worker's lifetime. Resume must be rebuilt from the durable Supabase `node_outputs` checkpoints, **never** from MemorySaver. Note `router.py` pins `_job_id=f'pipeline:{lesson_id}'`, so `job_id` alone is not a uniquifier — `job_try` must be part of the token."

**Problem with bare `session_id` as `thread_id`:**

1. `MemorySaver` is process-local and never evicted. Every `graph.ainvoke` call with the same `thread_id` adds a new checkpoint entry. Over a long-lived ARQ worker handling many sessions, this is an unbounded memory leak — the number of stale checkpoints grows with `total_dispatches`, not just `active_sessions`.

2. Any future addition of an `Annotated[list, operator.add]` channel to `TutorMachineState` would silently double values on each dispatch for the same session. This is the exact failure mode that caused D1 (18 sites, 16× duplication in a single clean run). The tutor graph currently has no such channels, but the CLAUDE.md rule exists precisely to prevent this class of defect from being introduced silently.

3. When a student reconnects after a WebSocket disconnect, `dispatch_event` fires again with the same `session_id`. Under the current code the MemorySaver checkpoint from the previous connection attempt is reused. If any accumulator channel were present, the reconnect would double its values.

**Why MemorySaver checkpoint is not needed between dispatches:** The tutor FSM state is persisted in Redis by `_persist_state` after every state transition. `dispatch_event` reads fresh state from Redis via `_read_state` at the top of every call and constructs `input_state` from scratch. There is no need for LangGraph to resume from a prior checkpoint — the Redis read IS the resume. Using a unique `thread_id` per dispatch ensures MemorySaver is used only for within-dispatch node-to-node state (which is its intended purpose), not for cross-dispatch persistence.

**Approved fix:** `"thread_id": f"{session_id}:{uuid4()}"` — a UUID4 suffix provides per-dispatch uniqueness without relying on clock resolution.

---

## Acceptance Criteria

### AC1 — thread_id is unique per dispatch
Each call to `dispatch_event` constructs a `thread_id` of the form `f"{session_id}:{uuid4()}"` — never the bare `session_id`. Two consecutive calls with the same `session_id` and `event` arguments must produce different `thread_id` strings. Verified by calling `dispatch_event` twice in a test and asserting the two `thread_id` values differ.

### AC2 — thread_id change is scoped to dispatch_event only
No other call site in `graph.py` or any other file is changed. The `uuid4()` is generated inside `dispatch_event` and nowhere else.

### AC3 — uuid4 is imported from the standard library
`from uuid import uuid4` is present in `graph.py`. No third-party UUID library is used.

### AC4 — FSM state transition behavior is unchanged
A sequence of dispatches (IDLE → TEACHING, TEACHING → INTERVENING, INTERVENING → TEACHING) continues to produce correct `current_state` transitions. The state is read from Redis at the start of each dispatch, not from the prior LangGraph checkpoint. A test with `fakeredis` seeded with known state values must confirm correct transitions across three dispatches.

### AC5 — No MemorySaver cross-dispatch state bleed
Given a `TutorMachineState` with a hypothetical `Annotated[list, operator.add]` test channel (added locally in the test only), N consecutive dispatches for the same `session_id` produce a list of length exactly 1 per dispatch, not length N. This confirms each dispatch gets a fresh checkpoint.

### AC6 — Guard test (CI-enforceable source inspection)
A source-inspection test in `tests/unit/test_s3_44_langgraph_thread_id.py` asserts:  
(a) the string `uuid4()` appears in the source of `dispatch_event` (read via `inspect.getsource`); and  
(b) the pattern `"thread_id": session_id` (bare assignment, without a format string or `uuid4`) does NOT appear in the `dispatch_event` source.  
This test must fail if someone reverts line 490 to the bare `session_id` form.

### AC7 — DEFECT-REGISTER.md D66 updated to FIXED
D66's row in the OPEN section of `docs/DEFECT-REGISTER.md` is moved to CLOSED with status `FIXED`, story reference `S3-44`, and enforcement named as `tests/unit/test_s3_44_langgraph_thread_id.py`.

---

## Tasks / Subtasks

- [ ] **T1** — Add `from uuid import uuid4` import to `graph.py` (top of file, grouped with stdlib imports)
- [ ] **T2** — Change line 490 in `dispatch_event`: replace `"thread_id": session_id` with `"thread_id": f"{session_id}:{uuid4()}"`
- [ ] **T3** — Write `tests/unit/test_s3_44_langgraph_thread_id.py`:
  - [ ] T3a — AC6 source-inspection guard (CI-enforceable)
  - [ ] T3b — AC1 uniqueness test (two consecutive dispatches differ)
  - [ ] T3c — AC4 FSM transition correctness test (three-event sequence with fakeredis)
  - [ ] T3d — AC5 no-bleed test (hypothetical accumulator channel, N dispatches → length 1 each)
- [ ] **T4** — Update `docs/DEFECT-REGISTER.md`: move D66 from OPEN to CLOSED with enforcement named

---

## Scale & Load

**1. What is ONE unit of work, and what is its range?**  
One unit of work is one call to `dispatch_event()`. This generates one `uuid4()` (O(1) CPU, no I/O) and invokes `graph.ainvoke` once. Range: a typical 30-minute lesson dispatches ~50–100 FSM events (every segment transition, quiz result, intervention trigger). Maximum measured: no upper bound enforced by code, but intervention count is capped at 3 by the `max_distraction_interventions_per_session` guard, and CES windows are 5-second cadence (~360 windows/30 min). So ~400–500 dispatches per session is a realistic maximum over a long session.

**2. Which budgets are FIXED while the input VARIES — and what happens past them?**  
- `recursion_limit: 5` is a fixed cap on LangGraph recursion per dispatch. An entry_router → one_node → END sequence uses 1 step. A future self-loop hits 5 and raises `GraphRecursionError` — explicit error, not silent truncation.  
- MemorySaver per-thread storage: previously O(dispatches_per_session), now O(1) per dispatch (orphaned after `ainvoke` returns). The orphaned entries are never GC'd within the worker lifetime, so total MemorySaver size is still O(total_dispatches_ever), but growth rate is now bounded at one entry per dispatch regardless of session length.  
- No other fixed budget changes with this story.

**3. What is the SCOPE of every limit?**  
- `recursion_limit: 5` — per dispatch (per `ainvoke` call), not per session or per worker.  
- MemorySaver storage — per worker process. Shared across all sessions handled by the same worker. Not shared across worker replicas (MemorySaver is process-local by definition).  
- `uuid4()` uniqueness — cryptographically unique per dispatch, per process, across all replicas. No scoping concern.

**4. Which reads and writes are UNBOUNDED?**  
None introduced by this story. `dispatch_event` continues to read exactly one Redis key (`session:{session_id}:tutor_state`) and write exactly one. The `uuid4()` call adds no I/O. No Supabase reads or writes are added.

**5. Which caps were INHERITED from an earlier design, and have they been re-derived?**  
`recursion_limit: 5` was set when the tutor graph used terminal nodes (entry_router → one node → END = 1 step). This story does not change the graph structure, so the cap remains valid. Re-derived: a 5-node linear chain would use 5 steps, which would hit the limit. The current graph has at most 2 steps per dispatch, so 5 remains safe. If the graph gains a self-loop or a deeper chain, `recursion_limit` must be re-evaluated.

**6. Is every check-then-act sequence safe under CONCURRENT requests?**  
No check-then-act is introduced. `uuid4()` is generated inside the single async function before `ainvoke`. The `ainvoke` call itself is `await`-safe: concurrent dispatches for different sessions are independent (different `thread_id`); concurrent dispatches for the same session are serialized by the calling code (WebSocket handler processes one event at a time). No new concurrency risk introduced.

---

## Security

- **No new auth surface.** `dispatch_event` is an internal function, not an HTTP endpoint. It receives `session_id`, `user_id`, and `lesson_id` already validated by the WebSocket auth middleware (`apps/api/app/core/websocket.py`). This story does not change the auth boundary.
- **No user-controlled input reaches `thread_id`.** The `session_id` used in the `thread_id` comes from the validated JWT claim (enforced by `get_current_user`), not from any request body field. The `uuid4()` suffix is cryptographically generated, not client-supplied.
- **No new data persisted.** MemorySaver stores are in-process only, never written to a database or external store. This story does not add any Redis, Supabase, or storage writes.
- **No IDOR risk.** `thread_id` is used only as a LangGraph internal key, never exposed in any API response or WebSocket message.

---

## Test Requirements

All tests live in `apps/api/tests/unit/test_s3_44_langgraph_thread_id.py`.

| Test name | AC | What it asserts |
|---|---|---|
| `test_dispatch_event_thread_id_contains_uuid4_suffix` | AC6a | `inspect.getsource(dispatch_event)` contains `uuid4()` |
| `test_dispatch_event_thread_id_not_bare_session_id` | AC6b | `inspect.getsource(dispatch_event)` does NOT contain `"thread_id": session_id` as a bare pattern |
| `test_two_dispatches_same_session_different_thread_ids` | AC1 | Two calls to `dispatch_event` with the same `session_id` produce different LangGraph `thread_id` values (captured via monkeypatching `graph.ainvoke` to record `config["configurable"]["thread_id"]`) |
| `test_dispatch_event_uuid4_import_present` | AC3 | `from uuid import uuid4` appears in `graph.py` source (source-level import check) |
| `test_fsm_transition_idle_to_teaching_unchanged` | AC4 | Dispatch of `teaching_started` event from IDLE state with fakeredis seeded with IDLE produces `current_state == TEACHING` in the result |
| `test_fsm_transition_sequence_three_events` | AC4 | Three-event sequence (IDLE→TEACHING, TEACHING→INTERVENING, INTERVENING→TEACHING) produces correct state at each step using fakeredis |
| `test_unique_thread_id_prevents_memorysaver_bleed` | AC5 | With a test graph carrying an `Annotated[list, operator.add]` channel, N dispatches each produce a list of length 1 (not N), confirming no cross-dispatch accumulation |

---

## BMAD Process Gate

- [ ] Story file committed first (this file)
- [ ] Story commit pushed to `sprint3/s3-44-langgraph-thread-id` before any implementation
- [ ] RED tests written and failing
- [ ] GREEN implementation passes
- [ ] REFACTOR (no logic changes)
- [ ] DEFECT-REGISTER.md D66 moved to CLOSED with guard name `test_s3_44_langgraph_thread_id.py`
