---
id: "S3-52"
title: "CES production hardening — fatigue cooldown bypass, D4 gap-check test, non-TEACHING dispatch guards"
status: "Draft"
sprint: 3
story_points: 3
owner: Dev3/Dev4
decisions: [D4, D6, D7, D8]
depends_on: [S3-39, S3-42, S3-45, S3-48]
branch: sprint3/s3-52-ces-hardening
migration: "NO"
---

# Story S3-52 — CES Production Hardening

**Sprint:** Sprint 3 (CES v2 hardening)
**Dev:** Dev 3 / Dev 4
**Status:** Draft
**Decisions covered:** D4, D6, D7, D8
**Migration:** NO — all changes in Redis logic and tests only

---

## User Story

**As the live-session tutor engine**,
**I want** every CES guard rule (cooldown, state-gate, timestamp validity) enforced
without gaps,
**so that** no learner receives a double-intervention within the 2-minute cooldown
window and no intervention fires on stale or non-TEACHING-state signals.

---

## Context — Three Production Gaps Identified by BMAD Review

Three gaps were found when the CES scenario matrix was audited against the
codebase (BMAD code review, 2026-08-12):

**Gap A (Scenario 5 — BLOCKING):** `_can_intervene_fatigue` in
`graph.py` checks only the once-per-session `tutor_fatigue_fired` flag. It
does NOT check `tutor_cooldown:{session_id}`. PRD §10 requires a 2-minute
cooldown after **any** intervention. A distraction fires → 120 s cooldown
starts → 1 s later fatigue conditions are met → fatigue fires because the
cooldown key is not consulted. The learner receives two interventions within
seconds of each other.

**Gap B (Scenario 3 partial — D4):** The D4 timestamp gap-check in
`process_attention_signal` rejects two stale CES history entries whose
timestamps are > 2× cadence apart (i.e., `abs(t0-t1) > 10 s`). Every
existing test uses `t=0` for both entries so the check always passes.
The non-dispatch path (stale timestamps) has zero test coverage, meaning
it is silently broken if the formula changes.

**Gap C (Scenarios 16/18 — non-TEACHING dispatch guards):** State-gate
tests exist for `ces_history` non-write in non-TEACHING states, but no
test asserts `dispatch_event.assert_not_called()` when state is QUIZZING
or INTERVENING with pre-seeded low-CES history. Similarly, no test asserts
`behavioral_history`/`head_pose_history`/`blink_history` lpush is NOT called
when state is QUIZZING.

---

## Acceptance Criteria

### AC 1 — Fatigue checks the cooldown key before dispatching (Gap A fix)
`_can_intervene_fatigue` must:
1. Check `tutor_cooldown:{session_id}` EXISTS before attempting SET-NX on
   `tutor_fatigue_fired`.
2. Return `False` if the cooldown key exists (intervention in-cooldown window).
3. Only proceed to SET-NX on `tutor_fatigue_fired` if cooldown is clear.

**Invariant:** The once-per-session flag and the cooldown check are both
required. Order: check cooldown FIRST (fast-fail), then SET-NX.

### AC 2 — Fatigue fired during active distraction cooldown → blocked
Given: a distraction intervention has just fired (cooldown key present).
When: all fatigue conditions are met (blink+head_pose below threshold, ≥900 s).
Then: `_can_intervene_fatigue` returns `False` — no dispatch.

### AC 3 — Fatigue fired after cooldown expires → allowed (if flag not set)
Given: cooldown has expired (no cooldown key).
When: once-per-session flag not yet set + fatigue conditions met.
Then: `_can_intervene_fatigue` returns `True` — dispatch proceeds.

### AC 4 — D4 timestamp gap-check non-dispatch path is tested (Gap B)
A test must exercise the case where two CES history entries have timestamps
`abs(t0 - t1) > 2 × ces_cadence_seconds` (default: `> 10 s`).
Expected outcome: distraction is NOT dispatched despite both CES values being
below the 50-threshold.

### AC 5 — dispatch_event NOT called when state is non-TEACHING with low CES history (Gap C)
Tests must assert `dispatch_event.assert_not_called()` for at least two
non-TEACHING states (QUIZZING and INTERVENING) when:
- Two sub-threshold CES entries are pre-seeded in `ces_history`.
- A new attention signal arrives.
Expected: no dispatch in either state.

### AC 6 — Per-signal history lpush NOT called when state is non-TEACHING (Gap C)
Tests must assert `redis.lpush` is NOT called for `behavioral_history`,
`head_pose_history`, and `blink_history` when state is QUIZZING.
Covers the implicit behaviour that is currently only assumed from the code
structure.

### AC 7 — All new tests are registered with `@pytest.mark.unit` and pass in CI

---

## Tasks

- [ ] T1: Write FAILING tests for AC 1–3 (fatigue cooldown check)
- [ ] T2: Implement cooldown check in `_can_intervene_fatigue` (graph.py)
- [ ] T3: Write FAILING tests for AC 4 (D4 stale-timestamp non-dispatch)
- [ ] T4: Add timestamp gap test to appropriate test file (test_tutor_service or test_s3_45)
- [ ] T5: Write FAILING tests for AC 5 (dispatch_event.assert_not_called in non-TEACHING)
- [ ] T6: Write FAILING tests for AC 6 (lpush not called in non-TEACHING)
- [ ] T7: Verify AC 5 and AC 6 pass with no production code change (state gate already exists — tests are new)
- [ ] T8: Run full CES test suite — all GREEN
- [ ] T9: Update DEFECT-REGISTER.md (close Scenario 5 gap; update Gap B and C as FIXED-GUARDED)

---

## Scale & Load

1. **Unit of work:** One `_can_intervene_fatigue(session_id)` call per fatigue-condition evaluation.
   Min: 1 Redis EXISTS call + 1 Redis SET (cooldown clear, flag not set).
   Typical: 1 Redis EXISTS call only (cooldown active → early return False, no SET).
   Largest: same — 2 Redis calls max per evaluation.
   Beyond: no fan-out; O(1) regardless of session length.

2. **Budgets:** Two Redis round-trips per call (EXISTS then SET-NX). Both are
   O(1) key operations. No cursor, no scan, no list materialisation.
   The cooldown TTL (120 s) and the fatigue flag TTL (_STATE_TTL) are fixed
   env-var values — no variable budget.

3. **Scope:** Per session (`session_id` scoped keys). Railway Redis is shared
   across instances; all instances see the same cooldown key — no per-replica
   state ambiguity.

4. **Unbounded reads:** None. EXISTS on a single key is always O(1). No lrange,
   no scan.

5. **Inherited caps:** Cooldown TTL inherited from `settings.intervention_cooldown_seconds`
   (default 120 s). Re-derived: the 2-minute window is PRD §10. Fatigue TTL
   inherited from `_STATE_TTL` (24 h). Re-derived: a session cannot span > 24 h,
   so the flag naturally expires before the next day's session. Both correct.

6. **Concurrent safety:** EXISTS → SET-NX is still a two-step sequence.
   Race: Thread A sees no cooldown, Thread B concurrently sets the cooldown key
   (from an intervening node completing), Thread A then proceeds to SET-NX and
   wins the fatigue gate. This is an extremely narrow window (< 1 ms) in
   which both fatigue and a new intervention start simultaneously — acceptable
   because: (a) the new intervention would immediately start a new cooldown TTL
   anyway, and (b) the fatigue intervention cooldown is set by `intervening_node`
   after it runs. Making the check+SET atomic would require a Lua script; given
   that fatigue fires at most once per session and the race window is sub-millisecond,
   this is accepted and documented. If a future story converts to Lua, the
   EXISTS+SET-NX pattern here is the target to replace.
   The once-per-session SET-NX for the fatigue flag itself remains atomic
   (a single Redis command). Only the cooldown pre-check is non-atomic.
