---
baseline_commit: "f704a47283cd9794009371dbbae1620fd00bf3e5"
---

# Story 4-5: All 14 Tutor Transitions Wired and Tested

**Status:** in-progress

---

## Story

As Dev 4,
I want one end-to-end test per tutor FSM transition (all 14) plus a blocked-case test for each
intervention guard,
so that the Sprint 2 `all_transitions` task moves from **Partial** to **Completed** with the whole
state machine proven through the real graph (`dispatch_event`), not by inspection.

---

## Context

The s1-5 graph fix wired every transition via the conditional entry router (`route_entry` →
`route_from_<state>` → one node → END). `tests/test_tutor_graph.py` already covers **6** transitions:
IDLE→TEACHING (session_start), TEACHING→CHECKING_IN (segment_complete), TEACHING→INTERVENING
(distraction_detected, guard allows), INTERVENING→TEACHING (intervention_complete), QUIZZING→TEACH_BACK
(quiz_failed), SESSION_END→IDLE (session_reset).

This story adds the **remaining 8 transitions** + **3 guard-blocked** cases. No production code changes
expected — the transitions are already wired; this proves them.

Transition table (from `graph.py` route_from_* — authoritative):
| # | From | Event | To | Covered? |
|---|------|-------|----|---------|
| 1 | IDLE | session_start | TEACHING | ✅ |
| 2 | TEACHING | distraction_detected (guard allows) | INTERVENING | ✅ |
| 3 | TEACHING | fatigue_detected (guard allows) | INTERVENING | ❌ |
| 4 | TEACHING | segment_complete | CHECKING_IN | ✅ |
| 5 | TEACHING | quiz_trigger | QUIZZING | ❌ |
| 6 | TEACHING | lesson_complete | SESSION_END | ❌ |
| 7 | INTERVENING | intervention_complete | TEACHING | ✅ |
| 8 | CHECKING_IN | checkin_complete (default) | TEACHING | ❌ |
| 9 | CHECKING_IN | low_checkin_score | QUIZZING | ❌ |
| 10 | QUIZZING | quiz_complete (default) | TEACHING | ❌ |
| 11 | QUIZZING | quiz_failed | TEACH_BACK | ✅ |
| 12 | TEACH_BACK | teachback_complete (default) | TEACHING | ❌ |
| 13 | TEACH_BACK | teachback_failed | INTERVENING | ❌ |
| 14 | SESSION_END | session_reset | IDLE | ✅ |

---

## Acceptance Criteria

- **AC 1:** Each of the 8 uncovered transitions (#3,5,6,8,9,10,12,13) has a test driving the REAL graph
  via `dispatch_event(sid, event)` with Redis seeded to the source state, asserting `current_state` equals
  the expected target.
- **AC 2:** Guard-blocked cases proven end-to-end (event fires but the guard keeps the FSM in TEACHING):
  - distraction blocked by **active cooldown** → stays TEACHING
  - distraction blocked by **max count reached** (count == max) → stays TEACHING
  - fatigue blocked by **already-fired flag** → stays TEACHING
- **AC 3:** Transition #3 (fatigue_detected, guard allows: not yet fired) → INTERVENING.
- **AC 4:** No `GraphRecursionError` on any path; all run as a single transition.
- **AC 5:** Combined with the existing 6, all 14 transitions are covered; full suite green, no regressions.

---

## Tasks / Subtasks

- [ ] 1.1 Add a key-aware Redis helper (get by key, exists by key) + settings mock for guard tests.
- [ ] 1.2 Add the 8 transition tests (AC 1) + fatigue-allow (AC 3).
- [ ] 1.3 Add the 3 guard-blocked tests (AC 2).
- [ ] 1.4 Run test_tutor_graph.py + full regression.

---

## Dev Notes

### File to change

| File | Change | What |
|------|--------|------|
| `apps/api/tests/test_tutor_graph.py` | UPDATE | Add the missing transition + guard-blocked tests |

No production changes. If a transition test reveals a real graph defect, STOP and report (do not silently
patch production beyond what the test demands).

### Seeding & patch targets (consistent with existing tests in this file)

- `mocker.patch("app.core.redis.get_redis", return_value=<AsyncMock>)`; `redis.get` returns the seeded
  current state for `tutor_state:{sid}`.
- Guard tests need key-aware `get` + `exists` + `mocker.patch("app.config.get_settings", ...)` with
  `max_distraction_per_session`. Model on the existing
  `test_distraction_detected_routes_to_intervening_when_guard_allows`.
- `_can_intervene_distraction` reads `redis.exists("tutor_cooldown:{sid}")` then
  `redis.get("tutor_distraction_count:{sid}")` (int) vs `settings.max_distraction_per_session`.
- `_can_intervene_fatigue` reads `redis.exists("tutor_fatigue_fired:{sid}")` → allowed iff NOT present.

### Expected targets (assert `result["current_state"] == TutorState.X`)

- fatigue_detected (no fatigue flag) from TEACHING → INTERVENING
- quiz_trigger from TEACHING → QUIZZING
- lesson_complete from TEACHING → SESSION_END
- checkin_complete from CHECKING_IN → TEACHING
- low_checkin_score from CHECKING_IN → QUIZZING
- quiz_complete from QUIZZING → TEACHING
- teachback_complete from TEACH_BACK → TEACHING
- teachback_failed from TEACH_BACK → INTERVENING
- distraction_detected + cooldown(exists=1) from TEACHING → TEACHING (blocked)
- distraction_detected + count==max from TEACHING → TEACHING (blocked)
- fatigue_detected + fatigue_fired(exists=1) from TEACHING → TEACHING (blocked)

### Guard-test Redis key routing (avoid int() crash)

`redis.get` is called for BOTH `tutor_state:{sid}` (returns state string) AND
`tutor_distraction_count:{sid}` (returns a numeric string). Use a key-aware `side_effect` so the count
key returns e.g. `"3"` and the state key returns `"TEACHING"` — a single fixed return value would feed a
non-numeric string into `int()` and crash the guard.

### Conventions

- `@pytest.mark.unit`; `asyncio_mode = "auto"`; distinct `session_id` per test (MemorySaver thread isolation).
- Out of scope: full_state_machine real-logic (intervention message selection, Langfuse spans) — separate
  Sprint 2 task.

---

## Review outcome (adversarial — Blind + Edge Case Hunter, 2026-06-30)

All 14 transitions confirmed covered exactly once with correct targets; ACs 1–5 met. 25 tests green.

**Applied:**
- **[Major] Weak guard-blocked assertions.** "stays TEACHING" couldn't distinguish *blocked* from
  *event ignored*. Strengthened all 3 via `_assert_intervention_suppressed`: the guard was consulted
  (`exists` awaited) AND the intervention was suppressed (INTERVENING never persisted, no `incr`).
- **[Minor] Boundary.** Added `test_distraction_allowed_just_below_max` (count==max-1 → INTERVENING) to
  pin the `<` operator from the allow side; added `_patch_settings` to the fatigue-blocked test.

**⚠️ Flagged — REAL production bugs, NOT fixed here (need their own story/review; out of this test-only scope):**
1. **[HIGH] "NEVER interrupt mid-TEACH_BACK" is unenforced.** `_is_in_teachback` (graph.py) is **dead code
   in routing** — `route_from_teach_back` sends any non-`teachback_failed` event (including
   `distraction_detected`/`fatigue_detected`) to TEACHING via its default. A distraction during TEACH_BACK
   silently drops the FSM out of teach-back, violating CLAUDE.md §10. Belongs to `quizzing_teachback_flow`.
2. **[MED] Fatigue interventions never set the fatigue-fired flag end-to-end.** `dispatch_event` does not
   propagate `intervention_type` for `fatigue_detected`, so `intervening_node`'s `intervention_type` is
   `None` → it records neither distraction nor fatigue → `tutor_fatigue_fired` is never set on the real
   fatigue path → the fatigue-once guard can't trip in production. Belongs to `full_state_machine`.
