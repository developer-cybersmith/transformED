---
id: "S3-37"
title: "Wire write_intervention_event into intervening_node via asyncio.create_task (D12)"
status: "Draft"
sprint: 3
story_points: 2
owner: Dev4
decisions: [D12]
depends_on: ["S3-36"]
branch: sprint3/s3-37-intervention-event-wiring
migration: "NO"
---

# Story S3-37 — Intervention Event Wiring

**Sprint:** Sprint 3 (CES v2 hardening)
**Dev:** Dev 4 (graph.py trigger) + Dev 3 (write_intervention_event helper, S3-36)
**Status:** Draft
**Branch:** `sprint3/s3-37-intervention-event-wiring`
**Depends on:** S3-36 — `write_intervention_event` helper must exist in assessment/service.py
**Decisions covered:** D12
**Migration:** NO — uses existing session_events table

---

## User Story

**As the tutor state machine**,
**I want** `intervening_node` in `graph.py` to schedule `write_intervention_event(...)` via
`asyncio.create_task` immediately after Redis writes complete,
**so that** every intervention fires a DB event row — even when the DB is slow — without
blocking the sub-50 ms Redis path or blocking the FSM state transition.

---

## Background

S3-36 delivered `write_intervention_event(session_id, *, intervention_type, window_index,
ces_at_trigger, message_key, supabase)` in `assessment/service.py`. It is DB-only, catches
all exceptions, and never re-raises.

`intervening_node` currently handles Redis writes (distraction counter via Lua guard,
fatigue flag, cooldown TTL) and returns the FSM state. It does NOT call
`write_intervention_event`.

D12 mandates fire-and-forget via `asyncio.create_task` — NOT `await` — so the DB write
never blocks the Redis hot path.

---

## Acceptance Criteria

### AC 1 — `asyncio.create_task` is used (not `await`)
`intervening_node` calls `asyncio.create_task(write_intervention_event(...))`, not
`await write_intervention_event(...)`. The AC4 test in `test_intervention_event_persistence.py`
verifies this at runtime.

### AC 2 — Correct arguments forwarded
`window_index` comes from `state.get("window_index", 0)`.
`ces_at_trigger` comes from `state.get("last_ces", 0.0)`.
`message_key` comes from the chosen intervention message key (or None).

### AC 3 — get_supabase failure is non-fatal
If `get_supabase()` raises during `create_task` setup, the exception is caught and logged;
`intervening_node` returns normally. The AC4 DB-failure test verifies this.

### AC 4 — No LLM calls introduced
`intervening_node` must not call any LLM provider after this change.

### AC 5 — All 18 S3-36/S3-37 tests pass GREEN

---

## Tasks

- [ ] Wire `asyncio.create_task(write_intervention_event(...))` in `intervening_node`
- [ ] Extract `window_index` and `last_ces` from state dict
- [ ] Wrap `get_supabase()` call in try/except (non-fatal)
- [ ] Run full test suite (18 tests + regressions)

---

## Scale & Load

1. **One unit of work:** One `create_task` call per intervention. At most 3 distraction + 1
   fatigue = 4 tasks per session. Range: 0–4.
2. **Fixed budgets vs variable input:** `create_task` is non-blocking — no budget consumed
   on the calling path. The DB write executes in the background event loop.
3. **Scope of every limit:** Per session. The distraction cap (max 3) is enforced by the
   Lua guard upstream; this story does not introduce a new limit.
4. **Unbounded reads/writes:** None. This is a single-row insert per call.
5. **Inherited caps re-derived:** `create_task` back-pressure: if the event loop is
   saturated with background tasks, new tasks queue in the Python runtime. No explicit
   cap is needed — `write_intervention_event` completes in milliseconds.
6. **Concurrent safety:** `create_task` is safe to call from an async context. The
   `asyncio.to_thread` inside `write_intervention_event` uses the thread pool — safe under
   concurrent signals.
