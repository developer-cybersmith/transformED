---
Status: ready-for-dev
baseline_commit: ""
---

# Story 3-10: Quiz Endpoint Security Hardening

**Epic:** Sprint 1 Assessment API — Remediation  
**Branch:** `sprint1/s1-10-quiz-security-hardening`  
**Depends on:** `sprint1/s1-1-quiz-endpoint-v2` merged to main  
**Audit source:** Sprint 1 BMAD Audit findings SEC-001, SEC-006, SEC-008, SEC-009, TQ-003, TQ-007, INT-03

## User Story

As a platform operator running TransformED AI,  
I want the quiz submission endpoint to reject malformed or malicious inputs and produce clean logs,  
so that the system is robust against DoS attacks, score manipulation, and session enumeration.

## Acceptance Criteria

### AC 1 — Bounded answers list (SEC-001)
- `QuizSubmission.answers` has `Field(min_length=1, max_length=50)` in `schemas.py`
- HTTP 422 returned for `len(answers) > 50`
- HTTP 422 returned for `len(answers) == 0` (declarative; existing service-level guard is defense-in-depth)
- Error detail for overflow: `"answers list must have at most 50 items."`

### AC 2 — response_index upper bound validation (SEC-008)
- In `grade_quiz()` grading loop, after loading the question dict, validate:
  `if not (0 <= ans.response_index < len(question["options"]))`
- HTTP 422 returned for out-of-range index
- Error detail: `f"response_index {ans.response_index} is out of range for question {ans.question_id!r}."`
- Note: `Field(ge=0)` lower-bound is already present from Story 3-8 re-impl; this adds upper bound

### AC 3 — Duplicate question_id guard (TQ-007)
- In `grade_quiz()`, before the grading loop, check for duplicate `question_id` values:
  `seen: set[str] = set()` — raise 422 if `ans.question_id in seen` before adding to seen
- HTTP 422 returned with detail: `f"Duplicate question_id {ans.question_id!r} in submission."`

### AC 4 — Session enumeration oracle fix (SEC-006)
- `grade_quiz()` session wrong-owner path (line ~68 in service.py): change HTTP 403 → HTTP 404
- Detail for wrong-owner: `"Session not found or access denied."` (same as missing-session detail)
- **IMPORTANT:** The IDOR lesson_id mismatch guard (line ~71) REMAINS HTTP 403 — this is intentional
- Only the user-ownership check changes to 404

### AC 5 — Log injection prevention (SEC-009)
- In `grade_quiz()` insert error log path, sanitize before logging:
  `safe_err = str(insert_resp.error).replace('\n', ' ').replace('\r', ' ')`
- Log: `logger.error("quiz_attempts insert failed: session=%s error=%s", session_id, safe_err)`

### AC 6 — CES SCALE CONTRACT comment (INT-03)
- Add comment block immediately after the CES formula line in `grade_quiz()` Step 8:
  ```python
  # CES SCALE CONTRACT (communicate to Dev 4):
  # ces_contribution is on the 0–100 POINT scale.
  # ces_weight_quiz (0.35 default) = max 35.0 pts at full accuracy.
  # Dev 4's ces.py must SUM component contributions directly — do NOT multiply by 100 again.
  ```

### AC 7 — Existing test updated: all-correct CES assertion (TQ-003)
- In `test_all_correct_gives_score_100` (currently line 167 in test_quiz_endpoint.py):
  Add assertion: `assert result.ces_contribution == pytest.approx(35.0)`
- This asserts the 2-answer all-correct case produces exactly 35.0 CES points

### AC 8 — Existing test updated: wrong-owner now 404 (SEC-006)
- `test_raises_403_when_session_belongs_to_other_user` (line 335): rename to `test_session_wrong_user_returns_404`
- Assert HTTP 404 (not 403), assert detail contains "not found or access denied"

### AC 9 — 7 new unit tests (minimum)
All tests in `apps/api/tests/test_quiz_endpoint.py` marked `@pytest.mark.unit`:

1. `test_too_many_answers_rejected` — submit 51 QuizAnswer items → assert HTTP 422
2. `test_answers_at_max_length_accepted` — submit exactly 50 QuizAnswer items → assert HTTP 200
3. `test_response_index_upper_bound_rejected` — response_index=99 for a 4-option question → assert HTTP 422
4. `test_response_index_at_max_valid` — response_index=3 for a 4-option question → assert HTTP 200, is_correct correct
5. `test_duplicate_question_id_rejected` — two QuizAnswer items with same question_id → assert HTTP 422
6. `test_insert_error_log_sanitized` — insert_resp.error contains newline char → assert logger.error called with no newlines in safe_err arg
7. `test_session_wrong_user_returns_404` — wrong user_id for session → assert HTTP 404

### AC 10 — Full test suite
- `pytest apps/api/tests/test_quiz_endpoint.py -m unit` exits 0
- Minimum 35 tests in test_quiz_endpoint.py (28 existing + 7 new)
- No regressions in `pytest apps/api/tests/ -m unit`

## Tasks / Subtasks

- [ ] Task 1: `schemas.py` — AC 1: Add `Field(min_length=1, max_length=50)` to `QuizSubmission.answers`
  - [ ] 1.1 Change `answers: list[QuizAnswer]` to `answers: list[QuizAnswer] = Field(min_length=1, max_length=50)`
- [ ] Task 2: `service.py` — AC 2: Add response_index upper bound check in grading loop
  - [ ] 2.1 After `question = question_map[ans.question_id]`, add bounds check raising 422
- [ ] Task 3: `service.py` — AC 3: Add duplicate question_id guard before grading loop
  - [ ] 3.1 Initialize `seen: set[str] = set()` before loop; raise 422 if duplicate detected
- [ ] Task 4: `service.py` — AC 4: Wrong-owner path: 403 → 404
  - [ ] 4.1 Change `status.HTTP_403_FORBIDDEN` → `status.HTTP_404_NOT_FOUND` for user_id mismatch
  - [ ] 4.2 Change detail to `"Session not found or access denied."`
- [ ] Task 5: `service.py` — AC 5: Sanitize log error string
  - [ ] 5.1 Add `safe_err = str(insert_resp.error).replace('\n', ' ').replace('\r', ' ')` before logger.error
- [ ] Task 6: `service.py` — AC 6: Add CES SCALE CONTRACT comment
  - [ ] 6.1 Add comment block after CES formula computation
- [ ] Task 7: `test_quiz_endpoint.py` — AC 7: Add CES assertion to test_all_correct_gives_score_100
- [ ] Task 8: `test_quiz_endpoint.py` — AC 8: Update wrong-user test to assert 404
- [ ] Task 9: `test_quiz_endpoint.py` — AC 9: Write 7 new unit tests
  - [ ] 9.1 test_too_many_answers_rejected
  - [ ] 9.2 test_answers_at_max_length_accepted
  - [ ] 9.3 test_response_index_upper_bound_rejected
  - [ ] 9.4 test_response_index_at_max_valid
  - [ ] 9.5 test_duplicate_question_id_rejected
  - [ ] 9.6 test_insert_error_log_sanitized
  - [ ] 9.7 test_session_wrong_user_returns_404 (renamed from wrong_user_returns_403)
- [ ] Task 10: Run full unit test suite — 0 failures

## Dev Notes

### File locations (relative to project root)
- `apps/api/app/modules/assessment/schemas.py` — QuizSubmission at line 22
- `apps/api/app/modules/assessment/service.py` — grade_quiz function starts at line 20
- `apps/api/tests/test_quiz_endpoint.py` — 28 tests currently, will become 35

### Current code state (after sprint1/s1-1-quiz-endpoint-v2 merged to main)
`schemas.py` QuizSubmission (line 22–26):
```python
class QuizSubmission(BaseModel):
    session_id: str
    lesson_id: str
    segment_id: str
    answers: list[QuizAnswer]  # ← add Field(min_length=1, max_length=50) here
```

`service.py` session check (lines 58–72):
```python
if session_resp.data is None:
    raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found.")
if str(session_resp.data["user_id"]) != str(user_id):
    raise HTTPException(status_code=403, detail="Session does not belong to this user.")  # ← change to 404
if str(session_resp.data.get("lesson_id", "")) != str(lesson_id):
    raise HTTPException(status_code=403, detail="Session does not belong to this lesson.")  # ← KEEP 403
```

`service.py` grading loop (lines ~122–141) — add upper bound check after question load:
```python
question = question_map[ans.question_id]
# ADD HERE: upper bound check
if not (0 <= ans.response_index < len(question["options"])):
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"response_index {ans.response_index} is out of range for question {ans.question_id!r}."
    )
```

### Mock structure for new tests
New tests use `_build_supabase()` helper. For tests where insert is not reached (422 before insert),
use only session_mock and lesson_mock. For tests that reach insert, use full 3-mock side_effect.

Test pattern for Field validation (answers max_length):
```python
@pytest.mark.unit
async def test_too_many_answers_rejected() -> None:
    answers = [QuizAnswer(question_id=f"q{i}", response_index=0, response_time_ms=0) for i in range(51)]
    with pytest.raises(ValidationError):  # Pydantic raises before service call
        QuizSubmission(session_id="s", lesson_id="l", segment_id="seg", answers=answers)
```
OR test at HTTP layer if Field validation is expected to return 422 from FastAPI.

### BMAD Development Sequence
1. RED: Write all failing tests (Tasks 7–9) in one commit BEFORE any implementation
2. GREEN: Implement minimal code (Tasks 1–6) to pass tests
3. REFACTOR: Non-behavioral cleanup only (rename vars, improve comments)
4. 5-agent code review via /bmad-code-review
5. PR → main after BLOCKER resolution

## Senior Developer Review (AI)

_To be completed after implementation by running /bmad-code-review with 5 agents:_
_Story Quality · Blind Hunter (Security) · Test Coverage · AC Completeness · Process Integrity_

## Dev Agent Record

### Completion Notes
_TBD_

### File List
_TBD_

### Change Log
- 2026-06-29: Story 3-10 created — BMAD Phase 1 story-first commit
