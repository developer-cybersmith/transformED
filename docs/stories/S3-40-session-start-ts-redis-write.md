---
id: "S3-40"
title: "Write session_start_ts to Redis in _init_session_state (D15)"
status: "Draft"
sprint: 3
story_points: 1
owner: Dev4
decisions: [D15]
depends_on: []
branch: sprint3/s3-40-session-start-ts
migration: "NO"
---

# Story S3-40 — Session Start Timestamp

**Sprint:** Sprint 3 (CES v2 hardening)
**Dev:** Dev 4
**Status:** Draft
**Decisions covered:** D15
**Migration:** NO

---

## User Story

**As the fatigue detection system (S3-45)**,
**I want** the session start timestamp written to Redis at `session:{id}:session_start_ts`
when a WebSocket session initializes,
**so that** `process_attention_signal` can compute session duration and gate the 15-minute
fatigue trigger without any DB round-trip on the hot signal path.

---

## Background

`_init_session_state` in `apps/api/app/core/websocket.py` initializes the per-session Redis
keys (tutor_state=IDLE, distraction_count=0, clears cooldown/fatigue/segment_index).
It does NOT write `session:{id}:session_start_ts`.

`process_attention_signal` (S3-45) needs this key to compute `session_duration_s`:
```python
start_ts = await redis.get(f"session:{session_id}:session_start_ts")
session_duration_s = time.time() - float(start_ts) if start_ts else 0
```

Without this key, the 15-minute fatigue duration gate is impossible, so fatigue never fires.

---

## Acceptance Criteria

### AC 1 — `session:{id}:session_start_ts` is written in `_init_session_state`
Key is set to `str(int(time.time()))` with `nx=True` (first-connect wins;
reconnect does not reset the clock) and `ex=86400`.

### AC 2 — Write uses `nx=True` (idempotent on reconnect)
A reconnecting client must not reset the session start timestamp.

### AC 3 — Write is inside the try/except block (non-fatal on Redis failure)
A Redis failure during init must not crash the WebSocket accept handshake.

### AC 4 — Key value is parseable as float (for duration computation)
`float(start_ts)` must succeed when the key exists.

---

## Tasks

- [ ] Add `session_start_ts` write to `_init_session_state` in `websocket.py`
- [ ] Write 2 RED tests confirming the key is set with correct nx/ex semantics
- [ ] Run regression suite GREEN

---

## Scale & Load

1. **One unit of work:** One SET NX per session. Range: once per session lifetime.
2. **Fixed budgets:** None introduced. Single Redis SET NX is O(1).
3. **Scope:** Per session. Key TTL = 86400 s (24 h), same as other session keys.
4. **Unbounded reads/writes:** None. Single key write.
5. **Inherited caps re-derived:** 24 h TTL same as tutor_state key — sessions longer
   than 24 h would lose the timestamp, but no session is expected to exceed that.
6. **Concurrent safety:** `nx=True` guarantees only the first writer succeeds.
   Concurrent reconnects leave the original timestamp intact.
