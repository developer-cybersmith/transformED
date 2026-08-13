---
id: "S3-53"
title: "CES production closure — canonical formula, guard tests, finalization, TTL, and dead code"
status: "In Progress"
sprint: 3
story_points: 8
owner: Dev3
decisions: [D1, D2, D4, D6, D7, D9, D12, D14, D15, D17, D18, D19, D63, D64, D65]
depends_on: [S3-35, S3-37, S3-38, S3-39, S3-40, S3-42, S3-45, S3-48, S3-50, S3-51, S3-52]
branch: sprint3/s3-53-ces-closure
migration: "NO"
---

# Story S3-53 — CES Production Closure

**Sprint:** Sprint 3
**Dev:** Dev 3
**Status:** In Progress
**Decisions covered:** D1, D4, D6, D9, D14, D15, D19, D63, D64, D65
**Migration:** NO — Redis logic, formula unification, test coverage, dead code removal only

---

## User Story

**As the CES engine**,
**I want** one canonical formula implementation, complete guard coverage, correct finalization
for short sessions, TTL-gated per-signal histories, and zero dead production code,
**so that** the live CES path and the session-report path produce identical results, no silent
behaviours exist, and all audit findings from the S3 BMAD review are closed.

---

## Context — Items Identified by BMAD Audit (2026-08-12)

Nine implementation gaps were surfaced by the post-S3-52 adversarial code review:

| # | Gap | Severity |
|---|-----|----------|
| D1/D62 | Two divergent `compute_ces` implementations — `assessment/ces.py` is dead production code | HIGH (BLOCKING) |
| D64 | `behavioral_history`, `head_pose_history`, `blink_history` have no Redis TTL | MEDIUM |
| D15 | `nx=True` on `session_start_ts` write is untested — removing it would fail nothing | MEDIUM |
| D65 | Positive distraction trigger path (TEACHING + 2 low-CES + dispatch) has no unit test | MEDIUM |
| Empty history | `_finalize_session` writes `ces_final=0.0` for empty history — indistinguishable from zero engagement | MEDIUM |
| Legacy bare-float | When both CES history entries are legacy bare-floats (t=0), `abs(0-0)=0` correctly passes the gap check — this is actually correct behaviour, but needs a test to lock it in | LOW |
| D61 | `session_start_ts` write has no retry — single Redis blip permanently disables fatigue | MEDIUM |
| D19 | `intervention_messages_used` semantically aliases `interventions_count` — no docstring clarifying the distinction | LOW |
| D63 | `_get_distraction_count` in `assessment/service.py` is fully implemented but never called — dead code | LOW |

---

## Acceptance Criteria

### AC 1 — Canonical `compute_ces` in `assessment/ces.py` (D1/D62)
`assessment/ces.py:compute_ces` accepts **all five signals as `float | None`** and applies
proportional weight redistribution for **any** None signal (generalising the §11 teachback-None
rule to cover MediaPipe dropouts and pre-quiz windows).

The formula:
```
present = [(v, w) for (v, w) in pairs if v is not None]
weight_sum = sum(w for _, w in present)
CES = sum(v × (w / weight_sum) for v, w in present) × 100
```
Edge: all signals None → CES = 0.0 (weight_sum = 0 guard).

### AC 2 — `tutor/service.py` delegates to `assessment/ces.py` (D1/D62)
`tutor/service.py:compute_ces(NormalizedSignal)` is a thin wrapper that delegates to
`assessment.ces.compute_ces`. It contains **no** formula arithmetic — no `ces_weight_*` references.

### AC 3 — CI guard prevents formula duplication (D1/D62)
A source-scan test asserts that `ces_weight_quiz` (a formula-logic marker) appears **only**
inside `assessment/ces.py`. Any second file defining weighted CES arithmetic fails CI.

### AC 4 — `quiz_accuracy=None` redistribution verified by test (D1/D62)
A test constructs `compute_ces(quiz_accuracy=None, behavioral=0.8, head_pose=0.8, blink=0.8,
teachback_score=None, settings=...)` and asserts the result is strictly greater than
`compute_ces(quiz_accuracy=0.0, behavioral=0.8, head_pose=0.8, blink=0.8, teachback_score=None, ...)`.
This proves redistribution, not zero-substitution.

### AC 5 — Per-signal histories have Redis TTL (D64)
`redis.expire()` is called immediately after each `ltrim` for `behavioral_history`,
`head_pose_history`, and `blink_history`, with TTL = `_CES_WINDOW_TTL`.

### AC 6 — `nx=True` on `session_start_ts` is asserted by test (D15)
An existing or new test asserts `redis.set` was called with `nx=True` for
`session:{session_id}:session_start_ts`. Removing `nx=True` from production code fails CI.

### AC 7 — Positive distraction trigger has a behavioral test (D65)
A test exercises the full path: state=TEACHING, two sub-50 CES history entries with valid gap
(abs(t0-t1) ≤ 2×cadence), `_can_intervene_distraction` returns True → `dispatch_event` is
called with `distraction_detected`. Asserts `result.intervention_dispatched is True`.

### AC 8 — Empty `ces_history` at session end writes `ces_final=None` (finalization)
`_finalize_session`: when `history_raw` is empty after parsing, `ces_final=None` is written
to the sessions table. `None` is distinguished from 0.0 (zero engagement) by the data model.

### AC 9 — Legacy bare-float history entries: both-zero gap is valid (D4 backward-compat)
A test seeds `ces_history` with two legacy bare-float entries (no `{"v":…,"t":…}` JSON wrapper).
Both parse to `t=0`. `abs(0-0)=0 ≤ 2×cadence` → `gap_ok=True`. If CES values are both < 50,
distraction dispatch is attempted. Test asserts this path is reachable (no permanent suppression
for all-legacy history).

### AC 10 — `_get_distraction_count` removed from `assessment/service.py` (D63)
The function is deleted. `dna_fusion.py` already computes `frustration_tolerance` from
`event_counts["intervention_triggered"]` (DB read at session end) — no caller needs the
Redis-first fallback function.

### AC 11 — `session_start_ts` write retries on transient Redis failure (D61)
`_init_session_state` retries the `session_start_ts` SET up to 3 times with exponential
backoff before logging a WARNING. A single-attempt Redis blip no longer permanently disables
fatigue for the entire session.

### AC 12 — `intervention_messages_used` has semantic documentation (D19)
The `SessionReport` model field carries a docstring (or `Field(description=...)`) clarifying:
"Counts `intervention_triggered` events in `session_events` (DB). Measures trigger events,
not WebSocket delivery confirmations."

### AC 13 — All new tests are `@pytest.mark.unit`, GREEN in CI

---

## Tasks

- [x] T1: Create story file (this file) — story-first commit
- [ ] T2: Fix `assessment/ces.py:compute_ces` — all signals nullable, proportional redistribution
- [ ] T3: Refactor `tutor/service.py:compute_ces` to delegate — no formula arithmetic
- [ ] T4: Add D64 `redis.expire()` for per-signal histories in `tutor/service.py`
- [ ] T5: Fix `graph.py:_finalize_session` — empty history → `ces_final=None`
- [ ] T6: Fix `websocket.py:_init_session_state` — retry session_start_ts write (D61)
- [ ] T7: Delete `assessment/service.py:_get_distraction_count` (D63)
- [ ] T8: Add `Field(description=...)` to `intervention_messages_used` (D19)
- [ ] T9: Write test_s3_53_ces_production_closure.py covering AC 3-9
- [ ] T10: Add nx=True assertion to `test_s3_45_fatigue_trigger.py` (AC 6)
- [ ] T11: Run full CES test suite — all GREEN
- [ ] T12: Run final adversarial BMAD audit

---

## Scale & Load

1. **Unit of work / range:** `compute_ces` — pure synchronous O(5) arithmetic; no I/O.
   Per-signal expire: 3 additional O(1) Redis SET-EX calls per 5-second window (appended to existing lpush+ltrim sequence). Retry: at most 3 sequential Redis calls for session_start_ts at WS connect time (amortised over the session). None of these change the per-request bottleneck.

2. **Fixed budgets / variable inputs:** TTL for per-signal histories = `_CES_WINDOW_TTL` (fixed env var). Retry count = 3 (fixed constant). ces_final=None for empty history — no budget change.

3. **Scope:** All Redis keys are `session:{session_id}:*` — per-session scope. Railway Redis is shared; all instances see the same TTL'd keys.

4. **Unbounded reads:** None added. All lrange calls already bounded at `_CES_HISTORY_MAX-1`. `_finalize_session` reads `lrange 0..9` (unchanged).

5. **Inherited caps:** `_CES_WINDOW_TTL` for per-signal histories — re-derived: signal histories are only useful while the session is active (within the session TTL window). Matching `_CES_WINDOW_TTL` is correct.

6. **Concurrent safety:** `compute_ces` is pure and stateless — no concurrency issue. The `session_start_ts` retry adds `asyncio.sleep` between attempts; this is in `_init_session_state` which runs once per WS connect, not in the signal hot path.
