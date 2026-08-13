---
id: "S3-35"
title: "Session finalization — write ces_final and ended_at to sessions table (D3)"
status: "Draft"
sprint: 3
story_points: 3
owner: Dev4
decisions: [D3]
depends_on: []
branch: sprint3/s3-35-session-finalization
migration: "NO"
---

# Story S3-35 — Session Finalization

**Sprint:** Sprint 3 (CES v2 hardening)
**Dev:** Dev 4
**Status:** Draft
**Decisions covered:** D3
**Migration:** NO — uses existing sessions table (ces_final, ended_at columns exist)

---

## User Story

**As the session report system**,
**I want** `session_end_node` to compute the final CES from the Redis history and write
`ces_final` and `ended_at` to the `sessions` table,
**so that** `get_session_report` can read a real `ces_score` (instead of always 0.0)
and `duration_minutes` (instead of always 0.0).

---

## Background

`get_session_report` reads `sessions.ces_final` and `sessions.ended_at`. Currently
these columns are never written after session creation — `session_end_node` in `graph.py`
calls `_persist_state` but does NOT update the sessions row.

The CES history (last 10 windows, JSON {v, t}) is already in Redis at
`session:{id}:ces_history`. The average of those values is a reasonable approximation
of the final CES (exact per-signal aggregate is covered by S3-42).

---

## Acceptance Criteria

### AC 1 — `ces_final` is written to sessions on SESSION_END
`sessions.update({"ces_final": computed_ces, "ended_at": utcnow_iso}).eq(session_id).execute()`
is called from `session_end_node` (or a helper called by it).

### AC 2 — `ces_final` is the average of the Redis ces_history values
If no history exists, `ces_final = 0.0`. Value is rounded to 2 decimal places.

### AC 3 — `ended_at` is a UTC ISO-8601 string
Format: `datetime.utcnow().isoformat() + "Z"` or equivalent.

### AC 4 — DB write is best-effort (non-fatal)
A DB failure must not crash `session_end_node`. Failure is logged at ERROR and captured
to Sentry. The FSM transition to SESSION_END completes regardless.

### AC 5 — Ownership: user_id verified before write
Before updating, verify `sessions.user_id` matches the session's user to prevent IDOR.
Use the session_id as the primary key — the RLS policy enforces user ownership at DB level.

### AC 6 — `get_session_report` ces_score is non-zero after session end
Integration: if Redis ces_history has values, `SessionReport.ces_score` is > 0.0.

---

## Tasks

- [ ] Add `_finalize_session(session_id, redis, supabase)` async helper to `graph.py`
- [ ] Call `asyncio.create_task(_finalize_session(...))` from `session_end_node`
- [ ] Write 3 RED tests (AC1 DB write structure, AC2 CES average, AC4 non-fatal)
- [ ] Run full test suite GREEN

---

## Scale & Load

1. **One unit of work:** One DB UPDATE per session on SESSION_END. Range: exactly once.
2. **Fixed budgets:** None. Single UPDATE to a known row. ces_history capped at 10 entries.
3. **Scope:** Per session. No cross-session writes.
4. **Unbounded reads/writes:** None. lrange 0..9 is bounded by _CES_HISTORY_MAX=10.
5. **Inherited caps re-derived:** ces_history max 10 entries — avg over at most 10 floats.
6. **Concurrent safety:** Two concurrent SESSION_END events for the same session_id would
   both try to UPDATE the same row. Supabase UPDATE is idempotent for the same data.
   The RLS policy prevents cross-user writes. No TOCTOU risk on the final write path.
