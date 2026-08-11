# Story 3-36 — Intervention Event Persistence

**Sprint:** Sprint 3 (CES v2 hardening)
**Dev:** Dev 3 (write path) + Dev 4 (trigger coordination)
**Status:** ready-for-dev
**Branch:** `sprint3/s3-36-intervention-event-persistence`
**Depends on:** Story 3-35 (session finalization — sessions must exist before events)

---

## Background

`intervening_node` in `apps/api/app/modules/tutor/state_machine/graph.py:167-203` handles
both `distraction` and `fatigue` interventions. It updates Redis keys (distraction counter,
fatigue flag, cooldown TTL) and persists the tutor FSM state. No row is ever written to
`session_events`.

The `"intervention_triggered"` event_type is referenced in three places as if it exists:

1. `apps/api/app/modules/assessment/dna_fusion.py:43` — string constant
   `INTERVENTION_EVENT = "intervention_triggered"` used in the dimension update logic
2. `apps/api/app/modules/assessment/service.py:787` — `SELECT count(*) FROM session_events
   WHERE session_id = $1 AND event_type = 'intervention_triggered'` — always returns 0
3. `apps/api/app/modules/analytics/service.py:14-26` — `KNOWN_EVENT_TYPES` does NOT include
   `"intervention_triggered"`, so batches containing it would be soft-rejected with a WARNING

Because the event is never written:
- `frustration_tolerance` DNA dimension (`dna_fusion.py`) reads event_count = 0 on every
  session and never decreases from its starting value
- `dna_growth.py` can never produce a negative delta for `frustration_tolerance`
- The analytics `intervention_rate` metric is always 0.0

### Defect Record

| ID | Description | Status |
|----|-------------|--------|
| D66 | `intervention_triggered` event never written to session_events | Opened by S3-36 |

---

## Acceptance Criteria

### AC 1 — intervention_triggered written when distraction intervention fires
When `intervening_node` fires with `intervention_type = "distraction"`, a `session_events`
row is inserted with:
```
event_type = "intervention_triggered"
payload = {
  "intervention_type": "distraction",
  "window_index": <int>,       # CES window number that triggered the intervention
  "ces_at_trigger": <float>,   # CES value that breached threshold
  "message_key": <str>         # key of the pre-generated intervention message used
}
```

### AC 2 — intervention_triggered written when fatigue intervention fires
Same as AC 1, but `intervention_type = "fatigue"`. The fatigue intervention fires at most once
per session (CLAUDE.md §Tutor State Machine guard); the event must be written even so.

### AC 3 — Write is fire-and-forget (non-blocking)
The DB insert must not block or slow the Redis intervention logic. Use `asyncio.create_task()`
so that a DB write failure does not prevent the intervention message from being shown.

### AC 4 — intervention_triggered added to KNOWN_EVENT_TYPES
`apps/api/app/modules/analytics/service.py` — add `"intervention_triggered"` to
`KNOWN_EVENT_TYPES` so future batch analytics ingestion accepts it without a WARNING.

### AC 5 — frustration_tolerance now decrements correctly
After the AC 1–3 writes are live, verify that `fuse_learner_dna()` correctly reads the
intervention count from DB and decrements `frustration_tolerance` when count > 0.
Unit test: mock `session_events` to return count=2 for `intervention_triggered` and assert
`frustration_tolerance` is below the pre-session baseline.

### AC 6 — No ruff errors
`ruff check` reports 0 errors in all modified files.

### AC 7 — Unit tests: 15 minimum
At minimum 15 unit tests covering: distraction event write (AC 1 payload shape),
fatigue event write (AC 2), fire-and-forget (asyncio.create_task called, not awaited),
KNOWN_EVENT_TYPES includes the type (AC 4), and frustration_tolerance decrement (AC 5).

---

## Tasks / Subtasks

- [ ] **T1** Write RED tests
- [ ] **T2** Implement `write_intervention_event(session_id, intervention_type, payload, supabase)` helper in `assessment/service.py`
- [ ] **T3** Coordinate with Dev 4: add `asyncio.create_task(write_intervention_event(...))` call inside `intervening_node` in `graph.py` after Redis writes
- [ ] **T4** Add `"intervention_triggered"` to `KNOWN_EVENT_TYPES` in `analytics/service.py`
- [ ] **T5** Verify `fuse_learner_dna()` unit tests include non-zero intervention count path
- [ ] **T6** Run `ruff check` + `pytest -m unit` — all pass
- [ ] **T7** 6-agent adversarial code review

---

## Scale & Load

**Q1 — Unit of work and range:**
One `session_events` INSERT per intervention. CLAUDE.md §Tutor State Machine: max 3 distraction
interventions per session + 1 fatigue intervention = max 4 events per session. Not unbounded.

**Q2 — Fixed budgets vs variable input:**
Max 4 intervention events per session. The INSERT is a single row. No batch; no unbounded
write. The `asyncio.create_task` envelope means the write is non-blocking but still bounded
in count.

**Q3 — Scope of every limit:**
Per-session limit (3 distractions + 1 fatigue) is enforced by the tutor FSM Redis counters
owned by Dev 4. This story writes the DB record; the FSM is the rate limiter.

**Q4 — Unbounded reads/writes:**
None. The helper writes one row per call. The analytics SELECT in `service.py:787` uses
`WHERE session_id = $1 AND event_type = 'intervention_triggered'` — bounded by session scope
and already carries an index on `session_events(session_id)`.

**Q5 — Inherited caps re-derived:**
The "max 3 distraction + 1 fatigue" cap comes from CLAUDE.md §Tutor State Machine. Confirmed
still valid — the FSM enforces it via Redis. The DB write merely mirrors what Redis already
tracks, so the per-session cap is guaranteed upstream.

**Q6 — Check-then-act under concurrency:**
The INSERT has no uniqueness constraint on (session_id, event_type, window_index). Concurrent
duplicate writes are theoretically possible only if `intervening_node` fires twice for the
same window, which the FSM cooldown TTL prevents. No additional DB constraint is needed; if
a duplicate slips through, two rows are harmless (count is still accurate).

---

## Definition of Done

- [ ] Story file committed before any implementation code
- [ ] RED tests written and confirmed failing before implementation
- [ ] Implementation makes all tests GREEN (minimum 15 unit tests)
- [ ] Ruff: 0 errors in modified files
- [ ] 6-agent adversarial code review passed
- [ ] `docs/dev3-assessment-tracker.md` updated
- [ ] PR merged to main

---

## Dev Notes

### The write helper

```python
# apps/api/app/modules/assessment/service.py

async def write_intervention_event(
    session_id: str,
    *,
    intervention_type: str,   # "distraction" | "fatigue"
    window_index: int,
    ces_at_trigger: float,
    message_key: str,
    supabase,
) -> None:
    """Fire-and-forget insert; call via asyncio.create_task."""
    await supabase.table("session_events").insert({
        "session_id": session_id,
        "event_type": "intervention_triggered",
        "payload": {
            "intervention_type": intervention_type,
            "window_index": window_index,
            "ces_at_trigger": ces_at_trigger,
            "message_key": message_key,
        },
    }).execute()
```

### Dev 4 wiring (graph.py:intervening_node)

```python
# After Redis writes in intervening_node, add:
asyncio.create_task(
    write_intervention_event(
        session_id,
        intervention_type=intervention_type,
        window_index=state.get("window_index", 0),
        ces_at_trigger=state.get("last_ces", 0.0),
        message_key=state.get("intervention_message_key", ""),
        supabase=get_supabase(),
    )
)
```

### Files to modify

- `apps/api/app/modules/assessment/service.py` — add `write_intervention_event()`
- `apps/api/app/modules/analytics/service.py` — add to `KNOWN_EVENT_TYPES`
- `apps/api/app/modules/tutor/state_machine/graph.py` — Dev 4 wires call
- `apps/api/tests/test_intervention_event_persistence.py` — new test file
