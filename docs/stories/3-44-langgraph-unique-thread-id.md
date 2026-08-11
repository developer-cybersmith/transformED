# Story 3-44: LangGraph Unique thread_id Per Dispatch (D66)

## Story

**As a** system,  
**I want** each tutor FSM event dispatch to use a unique LangGraph `thread_id`,  
**so that** MemorySaver never accumulates stale checkpoint state across dispatches, never causes a memory leak over the worker's lifetime, and cannot bleed state across retries.

## Context

**Defect:** D66 — `graph.py:dispatch_event` (line 490) uses `"thread_id": session_id` for every LangGraph dispatch. Because `MemorySaver` is process-local and never evicted, each call to `graph.ainvoke` with the same `thread_id` adds another checkpoint entry that is never cleared. Over a long-lived worker lifetime with many sessions, this is an unbounded memory leak. It also means any future addition of an `Annotated[list, operator.add]` accumulator to `TutorMachineState` would silently double values on each dispatch — the same failure mode that caused D1 (18 sites, 16× duplication in one clean run).

**CLAUDE.md binding rule (verbatim):** "A LangGraph `thread_id` must be unique per pipeline attempt. `MemorySaver` is process-local and never evicted; reusing `thread_id=lesson_id` retains accumulated channels across retries and across the worker's lifetime. Resume must be rebuilt from the durable Supabase `node_outputs` checkpoints, **never** from MemorySaver."

**Why MemorySaver checkpoint is not needed between dispatches:** The tutor FSM state is already persisted in Redis by `_persist_state` after every state transition. `dispatch_event` reads fresh state from Redis via `_read_state` at the top of every call and constructs `input_state` from scratch. There is no need for LangGraph to resume from a prior checkpoint — the Redis read IS the resume. Using a unique `thread_id` per dispatch ensures MemorySaver is used only for within-dispatch node-to-node state (which is its intended purpose), not for cross-dispatch persistence.

**Approved fix:** `"thread_id": f"{session_id}:{uuid4()}"` in `dispatch_event`.

## Acceptance Criteria

### AC1 — thread_id is unique per dispatch
Each call to `dispatch_event` uses a `thread_id` of the form `f"{session_id}:{uuid4()}"` — never the bare `session_id`. Two consecutive calls with the same `session_id` must produce different `thread_id` values.

### AC2 — thread_id change is scoped to dispatch_event only
No other call site in `graph.py` is changed. The `uuid4()` is generated inside `dispatch_event` and nowhere else.

### AC3 — uuid4 is imported from the standard library
`from uuid import uuid4` is used, not any third-party library.

### AC4 — FSM state transition behavior is unchanged
A sequence of dispatches (IDLE → TEACHING, TEACHING → INTERVENING) continues to produce correct state transitions. The state is read from Redis, not from the prior LangGraph checkpoint.

### AC5 — No MemorySaver checkpoint growth
The MemorySaver does NOT accumulate entries across N dispatches for the same session — each dispatch creates a new thread, so the checkpoint for the old thread is orphaned (never re-read).

### AC6 — Guard test (CI-enforceable)
A source-inspection test confirms `dispatch_event` contains `uuid4()` and does NOT contain `"thread_id": session_id` as a bare assignment (i.e., `session_id` alone, not `f"{session_id}:{uuid4()}"`).

### AC7 — DEFECT-REGISTER.md updated
D66 status updated to FIXED with story reference S3-44 and guard name.

## Scale & Load

1. **Unit of work and range:** One `uuid4()` call per FSM event dispatch. Range: N events per session (N ≤ ~50 over a typical lesson), across all concurrent sessions. `uuid4()` is O(1) CPU + 0 network.
2. **Fixed budget while input varies:** MemorySaver's per-thread storage is now bounded at one checkpoint per dispatch (orphaned immediately after). No persistent growth. Previous behavior: one thread per session, growing indefinitely.
3. **Scope of limit:** Per-process (MemorySaver is process-local). Orphaned threads are never GC'd within the worker lifetime, but since each is one dispatch, not one session, the growth rate drops from O(dispatches_per_session × sessions) to O(total_dispatches) — same quantity, but the old approach made session-level accumulation unbounded for long sessions.
4. **Unbounded reads/writes:** None introduced. Each dispatch still reads once from Redis and writes once. `uuid4()` adds no I/O.
5. **Inherited caps re-derived:** `recursion_limit: 5` is unchanged and still correct (entry_router → one_node → END = 1 step, hard cap at 5 to catch future self-loops). No inherited caps affected.
6. **Check-then-act safety:** No check-then-act involved. `uuid4()` is generated inside the single-threaded async function before the `ainvoke` call, which is await-safe.

## Dev Notes

- File to change: `apps/api/app/modules/tutor/state_machine/graph.py`
- Line 490 (on `main`): `config = {"configurable": {"thread_id": session_id}, "recursion_limit": 5}`
- Fix: `config = {"configurable": {"thread_id": f"{session_id}:{uuid4()}"}, "recursion_limit": 5}`
- Import to add: `from uuid import uuid4` at the top of the file
- Do NOT change any other line in graph.py
- Guard test: source inspection that (a) `uuid4` appears in `dispatch_event`'s source and (b) `"thread_id": session_id` (bare, without uuid4) does NOT appear in the dispatch_event source

## BMAD Process Gate

- [x] Story file committed first
- [x] Story commit pushed to `sprint3/s3-44-langgraph-thread-id` before any implementation
- [x] RED tests written and failing
- [x] GREEN implementation passes
- [x] REFACTOR (no logic changes)
- [x] DEFECT-REGISTER.md D66 updated to FIXED + guard name

## Status

Done
