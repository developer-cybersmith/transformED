# Story 3-35 — Session Finalization: Write ces_final and ended_at

**Sprint:** Sprint 3 (CES v2 hardening)
**Dev:** Dev 3
**Status:** ready-for-dev
**Branch:** `sprint3/s3-35-session-finalization`
**Depends on:** Story 3-34 (canonical CES formula), Story 3-24 (ces_baseline)

---

## Background

`session_end_node` in `apps/api/app/modules/tutor/state_machine/graph.py:251-256` transitions
the tutor FSM to SESSION_END by calling `_persist_state(session_id, TutorState.SESSION_END)`,
which writes the string `"SESSION_END"` to Redis key `tutor_state:{session_id}` with a 24-hour
TTL. No DB row is written.

Consequence cascade (all audit-confirmed):

1. `sessions.ended_at` — permanently NULL. Never written anywhere after the initial INSERT
   at session creation (`assessment/service.py:178-179`).
2. `sessions.ces_final` — permanently NULL. No UPDATE to the `sessions` table exists anywhere
   in the codebase.
3. `dna_fusion.fuse_learner_dna()` (`dna_fusion.py:249`) — returns `None` for every production
   call because of the guard `if session_row.get("ended_at") is None: return None`. Learner DNA
   never evolves beyond the onboarding baseline.
4. `ces_baseline.compute_and_store_ces_baseline()` (`ces_baseline.py:50`) — has zero callers in
   application code; called only from tests. Per-user intervention threshold never personalizes.

CES window history for the session lives in Redis list `session:{session_id}:ces_history`.
`ces_final` is defined as the mean of all accumulated CES windows. Dev 3 owns the DB write;
Dev 4 owns `session_end_node` (the trigger).

### Defect Record

| ID | Description | Status |
|----|-------------|--------|
| D64 | `sessions.ended_at` never written — every session permanently open | Opened by S3-35 |
| D65 | `sessions.ces_final` never written — DNA fusion, baseline, reports all broken downstream | Opened by S3-35 |

---

## Acceptance Criteria

### AC 1 — ended_at written on normal SESSION_END
When `session_end_node` fires (normal lesson completion), `sessions.ended_at` is set to
`now()` (DB server clock via `DEFAULT now()` semantics). The existing Redis state write is
unchanged; the DB write is added alongside it.

### AC 2 — ces_final computed from Redis history and written
`ces_final` is computed as `mean(all values in session:{session_id}:ces_history)`, rounded
to 2 decimal places (matching `numeric(5,2)` DB column precision). If the history list has
fewer than 5 entries OR the session elapsed time (ended_at − started_at) is less than 180 s,
`ces_final` is written as NULL with `session_flags` updated to include `{"partial_session": true}`
(partial session flag — S3-39 adds the column; S3-35 sets the flag only if the column exists,
otherwise logs a warning and omits the flag).

### AC 3 — Baseline triggered after ces_final write (non-blocking)
After a successful `ces_final` write, `compute_and_store_ces_baseline()` is called via
`asyncio.create_task()` (fire-and-forget). A failure in the baseline computation does not
propagate to the session_end_node caller. Baseline requires `ces_final IS NOT NULL` to run
(partial sessions skip baseline update).

### AC 4 — DB write is idempotent
Calling the finalization path twice for the same `session_id` does not raise an error and does
not overwrite an already-written `ended_at` with a different timestamp. Pattern:
`UPDATE sessions SET ended_at = now(), ces_final = $1 WHERE session_id = $2 AND ended_at IS NULL`.

### AC 5 — WebSocket disconnect writes partial state
When `WebSocketDisconnect` is raised in `apps/api/app/core/websocket.py`, the disconnect
handler calls the same finalization helper with whatever CES history is available. If fewer
than 5 windows exist, `ces_final = NULL` and `partial_session = true` per AC 2 logic.

### AC 6 — No ruff errors
`ruff check` reports 0 errors in all modified files.

### AC 7 — Unit tests: 20 minimum
At minimum 20 unit tests covering: normal finalization (ces_final computed), partial session
(< 5 windows → NULL), partial session (< 180 s → NULL), idempotent double-call,
Redis history empty → NULL, baseline trigger (mocked, verifying asyncio.create_task called),
and disconnect path. All pass under `pytest -m unit`.

---

## Tasks / Subtasks

- [ ] **T1** Write RED tests for session finalization helper
- [ ] **T2** Implement `finalize_session(session_id, supabase, redis)` helper in `assessment/service.py`
  - Read `session:{session_id}:ces_history` list from Redis (use `lrange(key, 0, -1)`)
  - Read `sessions.started_at` to compute elapsed seconds
  - Compute mean or NULL per AC 2 rules
  - Execute `UPDATE sessions SET ended_at = now(), ces_final = $1 WHERE session_id = $2 AND ended_at IS NULL`
  - Trigger baseline via `asyncio.create_task(...)` if ces_final is not NULL
- [ ] **T3** Update `session_end_node` (Dev 4 boundary — coordinate before merge): call `await finalize_session(...)` after `_persist_state`. The function is implemented in Dev 3 scope; Dev 4 wires the call in the node.
- [ ] **T4** Update WebSocket disconnect handler to call `await finalize_session(...)` on `WebSocketDisconnect`
- [ ] **T5** Run `ruff check` + `pytest -m unit` — all pass
- [ ] **T6** 6-agent adversarial code review

---

## Scale & Load

**Q1 — Unit of work and range:**
One `UPDATE sessions` row per session end. A session generates 1 CES history Redis list read
(up to N entries, where N = session_minutes × 12 windows/min for a 5 s window). Typical:
20–30 min lesson = 240–360 entries. Redis `lrange` on a list of 360 entries is O(N), bounded.

**Q2 — Fixed budgets vs variable input:**
`ces_history` Redis list is bounded by `ltrim` in `process_attention_signal` (must verify the
ltrim cap is set — if uncapped, a 4-hour session would accumulate ~2,880 entries; still O(N)
for the mean, but verify the cap before AC 3 merges). `numeric(5,2)` can store up to 999.99 —
CES is 0–100.0, so the column cannot overflow. The `< 5 windows` guard is a minimum, not a
cap: no session is silently truncated, it is explicitly flagged as partial.

**Q3 — Scope of every limit:**
Per-session. The Redis `ces_history` key is namespaced by `session_id`. The DB UPDATE touches
exactly one row identified by `session_id`.

**Q4 — Unbounded reads/writes:**
The `lrange(key, 0, -1)` read is unbounded by a LIMIT clause. Bounded implicitly by the
session's window count and any `ltrim` cap applied upstream. Add a `# BOUNDED:` comment
referencing the upstream ltrim cap, or add an explicit slice cap (e.g., last 1,440 entries
= 2 hours at 5 s windows) with a `logger.warning` if exceeded.

**Q5 — Inherited caps re-derived:**
The `< 5 windows AND < 180 s` rule was inherited from CLAUDE.md §11 CES v2 spec. Re-derived:
5 windows = 25 s of monitoring data — the minimum statistically meaningful sample. 180 s (3 min)
ensures enough lesson exposure for a meaningful CES. Both remain valid for a 20–60 min lesson.

**Q6 — Check-then-act under concurrency:**
The `WHERE ended_at IS NULL` predicate in the UPDATE is the concurrency guard: if two concurrent
finalization calls race (e.g., WebSocket disconnect simultaneously with an explicit session_end
event), the first writer wins and sets `ended_at`; the second writer's UPDATE matches 0 rows
and is a no-op (idempotent). No UNIQUE constraint or advisory lock needed — a conditional UPDATE
is safe under concurrent writes in PostgreSQL.

---

## Definition of Done

- [ ] Story file committed before any implementation code
- [ ] RED tests written and confirmed failing before implementation
- [ ] Implementation makes all tests GREEN (minimum 20 unit tests)
- [ ] Ruff: 0 errors in modified files
- [ ] 6-agent adversarial code review passed
- [ ] `docs/dev3-assessment-tracker.md` updated: task checked + dashboard updated
- [ ] PR merged to main

---

## Dev Notes

### The finalization helper

```python
# apps/api/app/modules/assessment/service.py

async def finalize_session(
    session_id: str,
    *,
    supabase,
    redis,
    settings,
) -> dict:
    """Write ended_at + ces_final to sessions; trigger baseline (non-blocking).

    Returns {"ces_final": float | None, "partial": bool}.
    Idempotent: WHERE ended_at IS NULL means double-calls are safe.
    """
    import asyncio, statistics
    from app.modules.assessment.ces_baseline import compute_and_store_ces_baseline

    # 1. Read CES history from Redis
    raw = await redis.lrange(f"session:{session_id}:ces_history", 0, -1)
    windows = [float(v) for v in raw if v]

    # 2. Read started_at from DB to compute elapsed
    row = (
        await supabase.table("sessions")
        .select("started_at, user_id")
        .eq("session_id", session_id)
        .maybe_single()
        .execute()
    ).data
    if not row:
        return {"ces_final": None, "partial": True}

    elapsed_s = (datetime.now(UTC) - parse_iso(row["started_at"])).total_seconds()

    # 3. Compute ces_final or NULL
    is_partial = len(windows) < 5 or elapsed_s < 180
    ces_final = None if is_partial else round(statistics.mean(windows), 2)

    # 4. Idempotent UPDATE (WHERE ended_at IS NULL)
    await supabase.table("sessions").update({
        "ended_at": "now()",
        "ces_final": ces_final,
    }).eq("session_id", session_id).is_("ended_at", None).execute()

    # 5. Trigger baseline (non-blocking, non-fatal)
    if ces_final is not None:
        asyncio.create_task(
            compute_and_store_ces_baseline(
                user_id=row["user_id"],
                session_id=session_id,
                supabase=supabase,
                redis=redis,
                settings=settings,
            )
        )

    return {"ces_final": ces_final, "partial": is_partial}
```

### Dev 4 coordination required
`session_end_node` (graph.py:251-256) is Dev 4's code. Dev 3 delivers `finalize_session()`
as a callable; Dev 4 adds the call inside `session_end_node`. Agree on the call site before
either side merges to main. The WebSocket disconnect handler
(`apps/api/app/core/websocket.py`) is also Dev 4's code — same coordination needed.

### Files to modify

- `apps/api/app/modules/assessment/service.py` — add `finalize_session()` helper
- `apps/api/app/modules/tutor/state_machine/graph.py` — Dev 4 wires call (coordinate)
- `apps/api/app/core/websocket.py` — Dev 4 wires disconnect call (coordinate)
- `apps/api/tests/test_session_finalization.py` — new test file
