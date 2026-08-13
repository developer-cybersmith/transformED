# Demo T16 — End-to-end session flow with real UUID data

**Status:** in-progress
**Sprint:** Demo Sprint
**Owner:** Dev 3
**Branch:** `dev3-demo-t16-phaseL5`
**Depends on:** T15 (real LessonPackage fixture + schema-accurate IDs established)

---

## Problem Statement

T15 validated that `grade_quiz` and `grade_teachback` handle a real LessonPackage
schema correctly in isolation. T16 validates the full end-to-end session lifecycle:
`create_session` → `grade_quiz` → `grade_teachback` → `get_session_report`, all
using the same UUID-format IDs (lesson_id, session_id, user_id) that a real student
session would produce.

This is the first test that chains all four assessment service functions together.
It catches integration failures that unit tests of individual functions cannot
surface: the session_id returned by `create_session` must be accepted by
`grade_quiz` and `grade_teachback`; the quiz and teachback data written in those
calls must aggregate correctly in `get_session_report`.

---

## User Story

As a student, when I start a lesson, submit quiz answers, submit a teach-back
response, and then view my session report — all the data from my session is
correctly recorded and reflected in the final report, with accurate CES breakdown
and formula disclosure.

---

## Acceptance Criteria

**AC1 — create_session returns DB-minted UUID session_id:**
`create_session(lesson_id=_LESSON_UUID, user_id=_USER_UUID_A)` succeeds and returns
a `session_id` that is the DB-generated UUID (not `_LESSON_UUID` or any client value).
The response dict also contains `lesson_id` and `started_at`.
Test: assert `result["session_id"]` is truthy and equals the session_uuid returned
by the DB mock; assert `result["lesson_id"] == _LESSON_UUID`.

**AC2 — create_session IDOR guard (404 on wrong owner):**
`create_session(lesson_id=_LESSON_UUID, user_id=_USER_UUID_B)` raises
`HTTPException(404)` when the lesson is owned by `_USER_UUID_A`.
Test: mock lessons query to return a row with `user_id=_USER_UUID_A`; call with
`user_id=_USER_UUID_B`; assert `exc_info.value.status_code == 404`.

**AC3 — create_session 404 on non-existent lesson:**
`create_session(lesson_id=_LESSON_UUID, user_id=_USER_UUID_A)` raises
`HTTPException(404)` when `lessons.maybe_single()` returns no row (lesson not found).
Test: mock lessons query to return empty; assert 404.

**AC4 — grade_quiz with UUID session from create_session (full chain):**
Using `_SESSION_UUID` (the DB-minted session UUID from AC1's flow), `grade_quiz`
succeeds and returns a `QuizResult` with non-zero `score` and correct `correct_count`
for the real quiz fixture from T15.
Test: reuse `_build_real_lesson_package()` from T15; mock supabase to return the
real lesson package; assert `result.correct_count >= 1`.

**AC5 — grade_teachback with UUID session: scorer receives real title + jargon:**
`grade_teachback` called with `_SESSION_UUID` and a segment from the real package
passes the segment's `title` (non-empty) and `jargon[].term` values (non-empty list)
to `score_teachback`, not empty strings.
Test: spy pattern identical to T15's AC2; assert `captured["topic"] != ""` and
`len(captured["key_concepts"]) > 0`.

**AC6 — get_session_report aggregates quiz + teachback correctly:**
`get_session_report(session_id=_SESSION_UUID, user_id=_USER_UUID_A)` returns a
`SessionReport` where:
- `quiz_score` is a non-None float (quiz rows were returned by mock)
- `teachback_score` is a non-None float (teachback rows were returned by mock)
- `formula_applied == "full_5_signal"` (both quiz and teachback present)
- `signal_coverage == 5`
- `ces_breakdown` is a dict with keys covering all 5 signals

**AC7 — get_session_report with no teachback → teachback_redistributed formula:**
When `teachback_attempts` returns 0 rows, `get_session_report` returns:
- `teachback_score is None`
- `formula_applied == "teachback_redistributed_4_signal"`
- `signal_coverage == 4`
Test: mock teachback query to return empty list; assert formula fields.

**AC8 — get_session_report with no quiz → quiz_score None:**
When `quiz_attempts` returns 0 rows, `get_session_report` returns `quiz_score is None`
and `quiz_total_questions == 0`.
Test: mock quiz query to return empty list.

**AC9 — get_session_report IDOR guard (404 on wrong owner):**
`get_session_report(session_id=_SESSION_UUID, user_id=_USER_UUID_B)` raises
`HTTPException(404)` when the session row has `user_id=_USER_UUID_A`.
Test: mock sessions query to return `user_id=_USER_UUID_A`; call with
`user_id=_USER_UUID_B`; assert `exc_info.value.status_code == 404`.

---

## Scale & Load

**Q1 — ONE unit of work and its range:**
One unit = one service call (create_session, grade_quiz, grade_teachback, or
get_session_report). These are tests only — no new DB writes or LLM calls are
introduced beyond what the service functions already do. Each test stubs all I/O.
Range is deterministic: fixed mock data, bounded call counts.

**Q2 — Fixed budgets while input varies:**
No new fixed budgets introduced. `get_session_report` has existing bounded queries
(quiz_attempts .limit(500), teachback_attempts .limit(50), session_events .limit(20),
ces_history lrange 0-9). These were already established and tested in the service.
These tests exercise the same bounds. No silent truncation: all mocks return
deterministic small sets well within every limit.

**Q3 — Scope of every limit:**
All limits are per-session (keyed by session_id in every query). No shared-state
limits introduced by these tests.

**Q4 — Unbounded reads/writes:**
None introduced. This is a tests-only diff. All service queries were already bounded
in prior stories (quiz .limit(500), teachback .limit(50), etc.).

**Q5 — Inherited caps re-derived:**
No caps inherited by this story. The service code's caps were re-derived in the
stories that introduced them (S3-29, S3-42, S3-50). This story does not change
the service code.

**Q6 — Check-then-act concurrency:**
No new check-then-act sequences. This story adds no service code, only tests.
The service's existing IDOR guards (sessions ownership checks) are exercised by
AC2, AC3, AC9 with correct isolation.

---

## Technical Requirements

- File: `apps/api/tests/test_e2e_session_flow_real_data.py` (new)
- 9 tests: AC1 through AC9 (one test per AC)
- Reuse `_build_real_lesson_package()` from T15 — import it or duplicate the builder
- UUID constants: reuse same values as T15 for cross-test traceability
  - `_LESSON_UUID = "550e8400-e29b-41d4-a716-446655440000"`
  - `_USER_UUID_A = "a0000000-0000-0000-0000-000000000001"`
  - `_USER_UUID_B = "b0000000-0000-0000-0000-000000000002"`
  - `_SESSION_UUID = "c0000000-0000-0000-0000-000000000003"`  ← DB-minted session UUID
- `asyncio.to_thread` shim (autouse): run synchronously so MagicMock chains resolve
- Settings mock (autouse): `ces_weight_quiz=0.35`, etc.
- Analytics consent mock (autouse): `AsyncMock(return_value=False)`

### create_session mock shape (AC1):
```
lessons.select → row with {lesson_id: _LESSON_UUID, user_id: _USER_UUID_A}
sessions.insert → row with {session_id: _SESSION_UUID, lesson_id: _LESSON_UUID, started_at: "2026-08-13T10:00:00+00:00"}
```

### get_session_report mock shape (AC6 — full 5-signal):
```
sessions.select → row with {session_id, user_id: _USER_UUID_A, lesson_id, ces_final: 72.5, started_at, ended_at}
lessons.select (tier) → {"tier": "T2"}
quiz_attempts.select → [{is_correct: True}, {is_correct: False}, {is_correct: True}]
teachback_attempts.select → [{score: 80.0}]
session_events (interventions) → count=1
session_events (dna_update) → []
learner_dna.select → maybe_single returns None (no DNA yet)
redis → None (redis=None path tested; graceful fallback to 0.0)
```

### get_session_report mock shape (AC7 — no teachback):
Same as AC6 but `teachback_attempts.select → []`

### get_session_report mock shape (AC8 — no quiz):
Same as AC6 but `quiz_attempts.select → []` and `teachback_attempts.select → []`

### Supabase mock builder notes:
- `get_session_report` calls `.maybe_single()` on sessions and lessons_tier queries
- `quiz_attempts` and `teachback_attempts` use `.select().eq().limit().execute()`
- `session_events` for interventions uses `count="exact"` → `resp.count` attribute
- `session_events` for dna_update uses `.select().eq().eq().limit().execute()`
- `learner_dna` uses `.maybe_single().execute()`

### Score_teachback stub (AC5):
```python
async def _spy_score_teachback(*, topic, key_concepts, response_text, provider):
    captured["topic"] = topic
    captured["key_concepts"] = key_concepts
    return {"score": 85.0, "feedback": "Good", "rubric_breakdown": {}}
monkeypatch.setattr("app.modules.assessment.service.score_teachback", _spy_score_teachback)
```

---

## Dependencies

- T15 completed: schema-accurate fixture builder pattern established
- `apps/api/app/modules/assessment/service.py` (read-only — no changes)
- `apps/api/app/modules/assessment/router.py` (read-only — SessionReport model)
- `packages/shared/lesson_package.schema.json` (read-only — UUID format validation)

---

## Tasks / Subtasks

- [ ] **T1 — RED: write 9 failing tests (one per AC)**
- [ ] **T2 — GREEN: confirm all 9 tests pass (no implementation changes needed)**
  - Note: service.py is correct; tests are the deliverable
- [ ] **T3 — VERIFY: run full assessment test suite, confirm all tests green**
- [ ] **T4 — UPDATE dev3-assessment-tracker.md**

---

## Dev Notes

### Why no service.py changes?
T16 is a validation story, not a feature story. The create_session, grade_quiz,
grade_teachback, and get_session_report functions were implemented and reviewed in
prior stories (2-35, 3-25, 3-26, 3-29, 3-42, 3-50). T16 proves they work together
end-to-end with the real UUID format that the actual database and real LessonPackage
schema require. The tests are the deliverable.

### get_session_report supabase mock complexity:
The function makes 7-9 supabase calls. The mock must return the right shape for
each call in the right order. Key shapes:
- `sessions.maybe_single().execute()` → `resp.data = {session_row}` (single dict)
- `lessons.maybe_single().execute()` → `resp.data = {"tier": "T2"}`
- `quiz_attempts.limit(500).execute()` → `resp.data = [{is_correct: True}, ...]`
- `session_events.count("exact").execute()` → `resp.count = 1` (attribute, not .data)
- `session_events.limit(20).execute()` → `resp.data = []` (dna_update events)
- `learner_dna.maybe_single().execute()` → `resp.data = None`

The asyncio.to_thread shim means each `.execute()` is called synchronously inside
a MagicMock chain. All sub-chains must have `.execute()` as the terminal call.

### _build_ces_breakdown import:
`get_session_report` calls `_build_ces_breakdown` from service.py (private). The
`ces_breakdown` dict key set depends on settings. With redis=None, behavioral/
head_pose/blink signals all default to 0.0 — so ces_breakdown is always populated.

### formula_applied logic (from service.py line 873-875):
```python
formula_applied = (
    "teachback_redistributed_4_signal" if teachback_score is None else "full_5_signal"
)
```
teachback_score is None when teachback_rows is empty (no teachback_attempts rows).

---

## Dev Agent Record

### Completion Notes
*To be filled on completion.*

### Debug Log
*Empty.*

---

## Change Log

| Date | Change |
|---|---|
| 2026-08-13 | Story created (story-first gate) |
