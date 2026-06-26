---
baseline_commit: a99972f033fea6376d2ee026053d650abad506c8
---

# Story 3.8: POST /api/assessment/quiz — Quiz Grading Endpoint Live

Status: done

---

## Story

As Dev 3 (tannmayygupta),
I want a working POST /api/assessment/quiz endpoint that grades student answers against the lesson JSONB,
so that Sprint 1 delivers real quiz scoring with DB writes and CES contribution data flowing end-to-end.

---

## Acceptance Criteria

AC 1: POST /api/assessment/quiz returns HTTP 200 (not 501) with a QuizResult body
AC 2: grade_quiz() service function exists in apps/api/app/modules/assessment/service.py
AC 3: Session ownership is validated — HTTP 403 if session belongs to a different user
AC 4: HTTP 404 returned if session_id not found in DB
AC 5: HTTP 404 returned if lesson not found or lesson.content is None
AC 6: HTTP 404 returned if segment_id not in lesson.segments
AC 7: HTTP 422 returned if answer.question_id not found in the segment's quiz
AC 8: is_correct is True when response_index == QuizQuestion.correct_index, False otherwise
AC 9: All answers are written to quiz_attempts table (one row per QuizAnswer)
AC 10: response_time_ms from each answer is written to quiz_attempts.response_time_ms
AC 11: ces_contribution = (correct_count / total_count) * settings.ces_weight_quiz
AC 12: feedback list includes question text, correct_option text, and explanation for each answer
AC 13: test_assessment_stub_contracts.py no longer tests quiz endpoint for 501 (quiz is now live)
AC 14: pytest -m unit exits 0 with no regressions — minimum 13 new unit tests in test_quiz_endpoint.py

---

## Tasks / Subtasks

- [x] Task 1: Write story file — AC: all — ✓ in-progress
  - [x] 1.1 Create docs/stories/3-8-quiz-endpoint-live.md

- [x] Task 2: Create apps/api/app/modules/assessment/service.py with grade_quiz() — AC: #2-#12
  - [x] 2.1 Session ownership validation (HTTP 403/404)
  - [x] 2.2 Lesson JSONB load and segment lookup (HTTP 404)
  - [x] 2.3 Question lookup dict from segment.quiz (HTTP 422 on unknown question_id)
  - [x] 2.4 Answer grading loop (is_correct = response_index == correct_index)
  - [x] 2.5 Bulk insert to quiz_attempts via asyncio.to_thread
  - [x] 2.6 Compute quiz_accuracy, ces_contribution, and QuizResult feedback

- [x] Task 3: Update apps/api/app/modules/assessment/router.py — AC: #1
  - [x] 3.1 Replace 501 stub with delegation to grade_quiz() using lazy import

- [x] Task 4: Update apps/api/tests/test_assessment_stub_contracts.py — AC: #13
  - [x] 4.1 Remove test_quiz_endpoint_returns_501 (quiz is now live)
  - [x] 4.2 Update module docstring to reflect 4 stubs remain (not 5)

- [x] Task 5: Create apps/api/tests/test_quiz_endpoint.py — AC: #14
  - [x] 5.1 asyncio.to_thread shim fixture (mock_to_thread) + _mock_settings autouse fixture
  - [x] 5.2 _build_supabase() helper with side_effect chain
  - [x] 5.3 Tests: correct/wrong/mixed grading, score=100/0/50
  - [x] 5.4 Tests: ces_contribution uses settings.ces_weight_quiz
  - [x] 5.5 Tests: response_time_ms written to DB, attempt_number written to DB
  - [x] 5.6 Tests: feedback has correct_option + explanation
  - [x] 5.7 Error tests: 404 no session, 403 wrong user, 404 no lesson, 404 no segment, 422 bad question_id

- [x] Task 6: Run tests and verify — AC: #14
  - [x] 6.1 pytest tests/test_quiz_endpoint.py → 15 passed, 0 failures
  - [x] 6.2 No regressions — 163 passing (7 pre-existing Dev 4/1 failures unchanged)

---

## Dev Notes

### NON-NEGOTIABLE RULES (PR rejection if violated)
- NEVER import openai.AsyncOpenAI() in service.py (quiz grading uses NO LLM — pure logic)
- NEVER hardcode model names — quiz grading doesn't call any LLM at all
- NEVER call get_supabase() at module level — inject it as a parameter to grade_quiz()
- NEVER block the async event loop — wrap ALL sync supabase calls in asyncio.to_thread
- NEVER gate lesson progress on teachback score
- Use lazy import inside submit_quiz() route to avoid circular import:
  from app.modules.assessment.service import grade_quiz  (inside function body only)

### Supabase Client Pattern (CRITICAL)
The Supabase client in this codebase is SYNCHRONOUS (supabase-py v2, sync Client).
get_supabase() returns Client (NOT AsyncClient).
All DB calls MUST be wrapped in asyncio.to_thread to avoid blocking the async event loop:

  session_resp = await asyncio.to_thread(
      lambda: supabase.table("sessions")
          .select("session_id, user_id, lesson_id")
          .eq("session_id", session_id)
          .maybe_single()
          .execute()
  )

  .maybe_single().execute() → .data is None if row not found, dict if found.
  .insert(rows_list).execute() → bulk insert, no return value needed.

### Lesson JSONB Access Pattern
lessons.content is a JSONB column storing a LessonPackage object.
Quiz questions are at: content["segments"][i]["quiz"][j]
Each QuizQuestion: {"question_id", "type", "question", "options": [str×4], "correct_index": int, "explanation", "difficulty"}
Grading: is_correct = (answer.response_index == question["correct_index"])

### Circular Import Prevention
service.py DOES import from router.py (for QuizAnswer, QuizResult models).
router.py MUST import service.py lazily (inside function body).
This is the established pattern — see websocket.py for reference.

service.py imports at module level (OK, no circular):
  from app.modules.assessment.router import QuizAnswer, QuizResult

router.py submit_quiz route body (lazy, prevents circular):
  from app.core.db import get_supabase
  from app.modules.assessment.service import grade_quiz

### asyncio.to_thread Mocking Pattern for Tests
The shim fixture to use in test_quiz_endpoint.py:
  @pytest.fixture
  def mock_to_thread(monkeypatch):
      async def _sync_shim(func, *args, **kwargs):
          return func(*args, **kwargs)
      monkeypatch.setattr("app.modules.assessment.service.asyncio.to_thread", _sync_shim)

### Supabase Mock Chain Pattern
Use side_effect list for ordered calls (sessions → lessons → insert):
  session_mock.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {...}
  lesson_mock.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {"content": {...}}
  insert_mock.insert.return_value.execute.return_value.data = []
  supabase.table.side_effect = [session_mock, lesson_mock, insert_mock]

### QuizQuestion constants for tests
_QUESTION_1 = {
    "question_id": "q1", "type": "mcq",
    "question": "What is the powerhouse of the cell?",
    "options": ["Nucleus", "Mitochondria", "Ribosome", "Golgi apparatus"],
    "correct_index": 1, "explanation": "Mitochondria produces ATP.", "difficulty": "easy"
}

---

## Dev Agent Record

### Agent Model Used
claude-sonnet-4-6

### Debug Log References
(to be filled during implementation)

### Completion Notes List
(to be filled during implementation)

### File List
- docs/stories/3-8-quiz-endpoint-live.md — CREATED
- apps/api/app/modules/assessment/service.py — CREATED
- apps/api/app/modules/assessment/router.py — MODIFIED (submit_quiz route)
- apps/api/tests/test_assessment_stub_contracts.py — MODIFIED (remove quiz 501 test)
- apps/api/tests/test_quiz_endpoint.py — CREATED

### Change Log
(to be filled during implementation)

---

## Senior Developer Review (AI)

(to be filled by code review agent)
