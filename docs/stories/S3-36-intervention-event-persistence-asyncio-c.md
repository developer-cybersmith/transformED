---
id: "S3-36"
title: "Intervention Event Persistence — asyncio.create_task write_intervention_event on distraction/fatigue fire (D12)"
status: "Draft"
sprint: 3
story_points: 3
owner: Dev3
decisions: [D12]
defects_opened: [D66]
depends_on: ["S3-35"]
branch: implemented/ces-fallback
migration: "NO"
---

# Story S3-36 — Intervention Event Persistence

**Sprint:** Sprint 3 (CES v2 hardening)
**Dev:** Dev 3 (write helper + analytics wiring) + Dev 4 (graph.py trigger coordination)
**Status:** Draft
**Branch:** `implemented/ces-fallback`
**Depends on:** S3-35 — Session finalization (sessions.ces_final + ended_at write path must land first; intervention events reference the same session_id that finalization writes)
**Decisions covered:** D12
**Migration:** NO — uses existing session_events table (schema frozen in 20260611000000_initial_schema.sql)

---

## User Story

**As the tutor state machine**,
**I want** every distraction or fatigue intervention to write a session_events row via asyncio.create_task(write_intervention_event(...)) the moment it fires,
**so that** the intervention_triggered events exist in the DB for Learner DNA frustration_tolerance updates, analytics intervention_rate computation, and session report reconstruction — without blocking the hot Redis intervention path that must stay under 50 ms.

---

## Background

intervening_node in apps/api/app/modules/tutor/state_machine/graph.py handles both
distraction and fatigue interventions. It updates Redis keys (distraction counter, fatigue
flag, cooldown TTL) and persists the tutor FSM state. No row is written to session_events.

The "intervention_triggered" event_type is referenced in three places as if it exists:

1. apps/api/app/modules/assessment/dna_fusion.py — INTERVENTION_EVENT = "intervention_triggered"
   used in the frustration_tolerance dimension update logic; always reads count = 0.
2. apps/api/app/modules/assessment/service.py — SELECT count(*) ... WHERE event_type = 'intervention_triggered'
   always returns 0, so frustration_tolerance never decrements.
3. apps/api/app/modules/analytics/service.py — KNOWN_EVENT_TYPES does NOT include
   "intervention_triggered", so batches containing it are soft-rejected with WARNING.

Because the event is never written:
- frustration_tolerance Learner DNA dimension reads event_count = 0 on every session and
  never decreases from its onboarding baseline.
- dna_growth.py can never produce a negative delta for frustration_tolerance.
- The analytics intervention_rate metric is always 0.0.

Defect record: D66 — intervention_triggered event never written to session_events.

D12 decision: Use asyncio.create_task(write_intervention_event(session_id, type)) inside
intervening_node after Redis writes complete. If Redis intervention history is unavailable
on a later read (cache miss), reconstruct the intervention count from the DB session_events
table rather than treating the count as zero.

---

## Acceptance Criteria

### AC 1 — write_intervention_event helper exists and is importable

apps/api/app/modules/assessment/service.py exports an async function with signature:

```python
async def write_intervention_event(
    session_id: str,
    *,
    intervention_type: str,
    window_index: int,
    ces_at_trigger: float,
    message_key: str,
    supabase,
) -> None:
```

Calling `from app.modules.assessment.service import write_intervention_event` raises no
ImportError. intervention_type accepts exactly "distraction" or "fatigue".

### AC 2 — Distraction intervention writes correct payload shape

When intervening_node fires with intervention_type = "distraction", a session_events
row is inserted with event_type = "intervention_triggered" (literal string, no variable)
and payload:

```json
{
  "intervention_type": "distraction",
  "window_index": 0,
  "ces_at_trigger": 42.5,
  "message_key": "distraction_01"
}
```

All four payload keys are present. event_type is exactly "intervention_triggered" —
verified by asserting the string literal appears in the insert dict, not via string
equality on a variable that could change.

### AC 3 — Fatigue intervention writes correct payload shape

Same schema as AC 2 but payload["intervention_type"] = "fatigue". The fatigue
intervention fires at most once per session (CLAUDE.md Tutor State Machine guard);
the event must be written even in a single-fire session.

### AC 4 — Write is fire-and-forget via asyncio.create_task (non-blocking)

intervening_node uses asyncio.create_task(write_intervention_event(...)) — the
coroutine is scheduled but NOT awaited at the call site. A unit test confirms:
- asyncio.create_task is called (verified via unittest.mock.patch("asyncio.create_task")).
- The scheduled target is an AsyncMock (coroutine), not a plain MagicMock.
- The Redis intervention logic completes and returns its result even when the DB
  write mock raises an exception.

### AC 5 — DB write failure does not surface to the tutor FSM caller

If write_intervention_event raises any exception (DB unavailable, APIError, network
error), the exception is caught inside the helper and logged at ERROR level. A Sentry
capture is made. intervening_node returns normally; the intervention message is
delivered to the student. The asyncio.create_task wraps the coroutine in a try/except
so uncaught task exceptions do not produce unhandled-exception stderr output.

### AC 6 — "intervention_triggered" added to KNOWN_EVENT_TYPES

apps/api/app/modules/analytics/service.py — "intervention_triggered" is present in
KNOWN_EVENT_TYPES. A POST to /api/analytics/events with event_type = "intervention_triggered"
no longer emits a WARNING log. Verified by asserting the string is in the set before
any analytics ingestion runs.

### AC 7 — DB reconstruction on Redis cache miss

When fuse_learner_dna() or get_session_report() needs the distraction count and the
Redis counter key (session:{session_id}:distraction_count) returns None (absent or
expired), the code falls back to querying session_events:

```sql
SELECT count(*)
FROM session_events
WHERE session_id = :session_id
  AND event_type = 'intervention_triggered'
  AND payload->>'intervention_type' = 'distraction'
```

When Redis returns a non-None value, the DB is NOT queried (no redundant reads).
Both paths are exercised by separate unit tests (AC 7 and AC 7-hit).

### AC 8 — frustration_tolerance decrements correctly when interventions > 0

fuse_learner_dna() reads the distraction count via the AC 7 reconstruction path
(DB query when Redis miss) and applies the EMA-based decrement formula. A unit test:
- Mocks session_events SELECT to return count = 2 for intervention_triggered.
- Mocks Redis GET to return None (cache miss triggers DB path).
- Asserts resulting frustration_tolerance is strictly less than the baseline value
  passed in as the pre-session dimension value.

### AC 9 — Zero interventions leaves frustration_tolerance at EMA baseline

When both Redis and DB return count = 0, no decrement is applied. The resulting value
equals round(0.7 * baseline + 0.3 * 100.0, 4) — standard EMA with a 100.0 signal,
no penalty. A unit test asserts this exact value.

### AC 10 — No ruff errors in modified files

ruff check on all modified files reports 0 errors:
- apps/api/app/modules/assessment/service.py
- apps/api/app/modules/analytics/service.py
- apps/api/app/modules/tutor/state_machine/graph.py

---

## Tasks / Subtasks

### Task 1 — Story file (BMAD story-first gate)
- [ ] 1.1 Create docs/stories/S3-36-intervention-event-persistence-asyncio-c.md
- [ ] 1.2 Commit story-only to implemented/ces-fallback
- [ ] 1.3 Push to remote

### Task 2 — RED phase (failing tests)
- [ ] 2.1 Create apps/api/tests/test_intervention_event_persistence.py
- [ ] 2.2 test_write_intervention_event_is_importable
- [ ] 2.3 test_distraction_event_payload_has_correct_shape
- [ ] 2.4 test_distraction_event_type_is_exactly_intervention_triggered
- [ ] 2.5 test_fatigue_event_payload_has_correct_shape
- [ ] 2.6 test_fatigue_event_intervention_type_field_is_fatigue
- [ ] 2.7 test_intervening_node_uses_create_task_not_await
- [ ] 2.8 test_db_write_failure_does_not_raise_from_intervening_node
- [ ] 2.9 test_db_write_failure_logs_error
- [ ] 2.10 test_intervention_triggered_in_known_event_types
- [ ] 2.11 test_redis_miss_triggers_db_count_reconstruction
- [ ] 2.12 test_redis_hit_skips_db_reconstruction
- [ ] 2.13 test_frustration_tolerance_decrements_when_intervention_count_is_2
- [ ] 2.14 test_frustration_tolerance_unchanged_when_intervention_count_is_0
- [ ] 2.15 test_write_intervention_event_has_no_llm_calls
- [ ] 2.16 test_write_intervention_event_uses_session_events_table
- [ ] 2.17 Confirm all 16 tests FAIL before implementation

### Task 3 — GREEN phase (implementation)
- [ ] 3.1 Add write_intervention_event() to apps/api/app/modules/assessment/service.py
- [ ] 3.2 Add _get_distraction_count() Redis-first DB-fallback helper
- [ ] 3.3 Update fuse_learner_dna() to use _get_distraction_count() (AC 7 + AC 8 + AC 9)
- [ ] 3.4 Add asyncio.create_task(write_intervention_event(...)) in intervening_node
          in apps/api/app/modules/tutor/state_machine/graph.py after Redis writes
- [ ] 3.5 Add "intervention_triggered" to KNOWN_EVENT_TYPES in analytics/service.py
- [ ] 3.6 Confirm all 16 tests PASS

### Task 4 — REFACTOR + validation
- [ ] 4.1 ruff check on all modified files — 0 errors
- [ ] 4.2 ruff format --check — no formatting issues
- [ ] 4.3 pytest -m unit — all tests pass
- [ ] 4.4 Full Dev 3 regression suite — 0 new failures

### Task 5 — Defect register update
- [ ] 5.1 Update D66 in docs/DEFECT-REGISTER.md — move to Closed, name enforcement tests
- [ ] 5.2 Update docs/dev3-assessment-tracker.md with completion note

### Task 6 — 6-agent adversarial code review
- [ ] 6.1 Layer 1 — Story Quality
- [ ] 6.2 Layer 2 — Blind Hunter (Security)
- [ ] 6.3 Layer 3 — Test Coverage
- [ ] 6.4 Layer 4 — AC Completeness
- [ ] 6.5 Layer 5 — Process Integrity
- [ ] 6.6 Layer 6 — Scale & Load

### Task 7 — Commit + push
- [ ] 7.1 Final commit on implemented/ces-fallback
- [ ] 7.2 Push to remote

---

## Scale & Load

**Q1 — What is ONE unit of work, and what is its range?**

One unit of work is one session_events INSERT triggered by one intervention fire.
Range: minimum 0 per session (no interventions); typical 1-2 distraction events;
maximum 4 per session (3 distraction + 1 fatigue — both enforced by CLAUDE.md
Tutor State Machine Redis counters). A single INSERT is one row. The ceiling is
enforced upstream by the FSM, not by this write path.

**Q2 — Which budgets are FIXED while the input VARIES, and what happens past them?**

The asyncio.create_task envelope decouples the DB write from the hot Redis path.
If the DB is unavailable, write_intervention_event catches the exception, logs at ERROR
(Sentry capture), and returns without re-raising. The intervention is still delivered to
the student. Silent truncation is not possible: the write either succeeds (row in DB) or
fails explicitly (ERROR log + Sentry). Past the FSM ceiling of 4 events/session, the FSM
blocks further intervention dispatches before write_intervention_event is ever called —
so the ceiling is unreachable from this story's code path.

**Q3 — What is the SCOPE of every limit?**

The 3-distraction + 1-fatigue cap is per-session. Redis keys are session:{session_id}:*
— per-session, not per-user or per-deployment. Independent of worker replica count
because Redis is the shared store; every replica sees the same counters.

**Q4 — Which reads and writes are UNBOUNDED?**

None. write_intervention_event writes exactly one row per call. The DB reconstruction
query (AC 7) is:

  SELECT count(*) FROM session_events
  WHERE session_id = :session_id
    AND event_type = 'intervention_triggered'
    AND payload->>'intervention_type' = 'distraction'

This is bounded by session_id scope (a specific session, never all sessions) and by
the FSM cap (at most 4 rows per session). The session_events(session_id) index present
in 20260611000000_initial_schema.sql makes this an index scan. count(*) materialises
no rows. No .limit() is needed on a session-scoped aggregate.

**Q5 — Which caps were INHERITED from an earlier design, and have they been re-derived?**

The 3-distraction + 1-fatigue cap originates from CLAUDE.md Tutor State Machine. Rederived:
the FSM cooldown TTL (2-minute Redis NX key) and max_distraction_interventions Redis counter
make it physically impossible to fire more than 4 interventions per session across any
number of API replicas. The DB write count inherits this cap by design. No new cap is
introduced by this story.

**Q6 — Is every check-then-act sequence safe under CONCURRENT requests?**

session_events has no uniqueness constraint on (session_id, event_type, window_index).
A concurrent duplicate write is possible only if intervening_node fires twice for the same
window — prevented by the FSM cooldown TTL (Redis NX set by _can_intervene_distraction
before dispatch). If a duplicate slips through (Redis propagation race), two rows are
inserted; both are correct and the count is accurate to within +/-1. An off-by-one in a
rare concurrency race has no material UX impact. No DB-level uniqueness constraint is
required; the FSM is the concurrency guard.

---

## Security

**Session ownership:** write_intervention_event receives session_id from the tutor FSM
state, populated only after the WebSocket handler verifies JWT ownership. The helper
performs no ownership check of its own — it trusts the call chain. This is the same
pattern used by all other internal session_events writes. Document with:
  # D81-pattern: caller (intervening_node) verified session ownership via JWT.

**No cross-user data leak:** session_events RLS (20260611000000_initial_schema.sql)
ensures users can only SELECT their own rows. The write uses the service-role Supabase
client (internal API process), which bypasses RLS at write time — matching the pattern
of all other session_events writes in analytics/service.py. All payload fields are
server-side typed values (no user-supplied free text).

**No LLM calls:** write_intervention_event is a pure DB insert. Asserted by source
inspection: inspect.getsource(write_intervention_event) must not contain any LLM
provider identifier (OpenAILLMProvider, complete, complete_structured).

**Async task lifetime:** On graceful shutdown, in-flight create_task writes may be
cancelled. The intervention was already delivered; only the audit record may be absent.
Accepted trade-off for fire-and-forget on an audit-only write.

---

## Test Requirements

Exact test function names required in apps/api/tests/test_intervention_event_persistence.py:

1.  test_write_intervention_event_is_importable
2.  test_distraction_event_payload_has_correct_shape
3.  test_distraction_event_type_is_exactly_intervention_triggered
4.  test_fatigue_event_payload_has_correct_shape
5.  test_fatigue_event_intervention_type_field_is_fatigue
6.  test_intervening_node_uses_create_task_not_await
7.  test_db_write_failure_does_not_raise_from_intervening_node
8.  test_db_write_failure_logs_error
9.  test_intervention_triggered_in_known_event_types
10. test_redis_miss_triggers_db_count_reconstruction
11. test_redis_hit_skips_db_reconstruction
12. test_frustration_tolerance_decrements_when_intervention_count_is_2
13. test_frustration_tolerance_unchanged_when_intervention_count_is_0
14. test_write_intervention_event_has_no_llm_calls
15. test_write_intervention_event_uses_session_events_table
16. test_write_intervention_event_catches_all_exceptions (AC 5 — no re-raise)

Minimum 16 tests. Each must assert an observable outcome (DEFECT-REGISTER.md binding
rule 2). Where a mock is necessary, mark it:
  # MOCK-CONTRACT: covered by tests/integration/

Repo-wide pytest -m unit must pass with 0 regressions after implementation.

---

## Dev Notes

### write_intervention_event helper (assessment/service.py)

```python
async def write_intervention_event(
    session_id: str,
    *,
    intervention_type: str,
    window_index: int,
    ces_at_trigger: float,
    message_key: str,
    supabase,
) -> None:
    """Fire-and-forget insert into session_events.

    MUST be called via asyncio.create_task — never awaited directly.
    Catches all exceptions; logs at ERROR and captures to Sentry.
    # D81-pattern: caller (intervening_node) verified session ownership via JWT.
    """
    try:
        await asyncio.to_thread(
            lambda: supabase.table("session_events").insert({
                "session_id": session_id,
                "event_type": "intervention_triggered",
                "payload": {
                    "intervention_type": intervention_type,
                    "window_index": window_index,
                    "ces_at_trigger": ces_at_trigger,
                    "message_key": message_key,
                },
            }).execute()
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "write_intervention_event failed for session %s: %s",
            session_id,
            type(exc).__name__,
        )
        sentry_sdk.capture_exception(exc)
```

### DB reconstruction helper (assessment/service.py)

```python
async def _get_distraction_count(session_id: str, redis, supabase) -> int:
    """Return distraction count. Redis-first; DB on miss or error."""
    key = f"session:{session_id}:distraction_count"
    try:
        val = await redis.get(key)
        if val is not None:
            return int(val)
    except Exception:  # noqa: BLE001
        pass
    result = await asyncio.to_thread(
        lambda: supabase.table("session_events")
        .select("id", count="exact")
        .eq("session_id", session_id)
        .eq("event_type", "intervention_triggered")
        .eq("payload->>intervention_type", "distraction")
        .execute()
    )
    return result.count or 0
```

### Dev 4 wiring in intervening_node (graph.py)

```python
# After all Redis writes, before return state:
asyncio.create_task(
    write_intervention_event(
        session_id,
        intervention_type=intervention_type,  # "distraction" | "fatigue"
        window_index=state.get("window_index", 0),
        ces_at_trigger=state.get("last_ces", 0.0),
        message_key=state.get("intervention_message_key", ""),
        supabase=get_supabase(),
    )
)
```

### Files to modify

| File | Change |
|------|--------|
| apps/api/app/modules/assessment/service.py | ADD write_intervention_event() + _get_distraction_count() |
| apps/api/app/modules/analytics/service.py | ADD "intervention_triggered" to KNOWN_EVENT_TYPES |
| apps/api/app/modules/tutor/state_machine/graph.py | ADD asyncio.create_task(...) in intervening_node (Dev 4) |
| apps/api/tests/test_intervention_event_persistence.py | NEW — 16 tests minimum |
| docs/DEFECT-REGISTER.md | D66 to Closed with enforcement test names |

---

## Definition of Done

- [ ] Story file committed before any implementation code (BMAD story-first gate)
- [ ] RED tests written and confirmed failing before implementation
- [ ] GREEN: minimum 16 unit tests pass; 0 regressions in full Dev 3 suite
- [ ] ruff check + ruff format --check: 0 errors in all modified files
- [ ] D66 in docs/DEFECT-REGISTER.md updated to CLOSED with guard name
- [ ] 6-agent adversarial code review passed (6 layers per CLAUDE.md)
- [ ] docs/dev3-assessment-tracker.md updated
- [ ] PR merged to main
