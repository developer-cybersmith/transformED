---
Status: ready-for-dev
baseline_commit: ""
---

# Story 3-12: Quiz attempt_number Dynamic Computation

**Epic:** Sprint 1 Assessment API — Remediation
**Branch:** `sprint1/s1-12-quiz-attempt-number-fix`
**Audit source:** F-001 (attempt_number hardcoded to 1 in grade_quiz)
**Depends on:** `sprint1/s1-1-quiz-endpoint-v2` merged to main first

## User Story

As a student retaking a quiz,
I want each quiz attempt to be recorded with an accurate attempt number,
so that retry analytics and learning progression are tracked correctly.

## Acceptance Criteria

### AC 1 — Hardcoded default removed from grade_quiz signature
- `grade_quiz()` in `service.py` no longer has `attempt_number: int = 1` in its parameter list
- The docstring line "Defaults to 1" is removed
- `router.py` is verified not to pass `attempt_number` explicitly (it does not — confirm)

### AC 2 — SELECT COUNT query added before grading logic
- `grade_quiz()` queries `quiz_attempts` for existing rows matching `session_id` AND `segment_id`
- Uses `.select("id", count="exact")` wrapped in `asyncio.to_thread`, mirroring lines 287–294 of `grade_teachback()`
- `attempt_number: int = (count_resp.count or 0) + 1` is set from the query result
- Query is placed at Step 5 (before Step 6 — grading loop), numbered consistently with existing step comments

### AC 3 — First attempt returns attempt_number=1
- When no prior rows exist (`count_resp.count = 0`), computed `attempt_number == 1`
- Existing behaviour for first-time quiz takers is unchanged (no regression)

### AC 4 — Retry returns attempt_number=N+1
- When N rows exist, computed `attempt_number == N + 1`
- Bulk insert uses the dynamically computed value, not 1

### AC 5 — Test mock expanded from 3-call to 4-call side_effect
- `_build_supabase()` helper in `test_quiz_endpoint.py` updated:
  - Old: `side_effect = [session_resp, lesson_resp, insert_resp]`
  - New: `side_effect = [session_resp, lesson_resp, count_resp, insert_resp]`
- `count_resp.count = 0` for all existing tests (first attempt, no prior rows)
- All 28 existing tests continue to pass after mock expansion

### AC 6 — New test: test_attempt_number_increments_on_retry
- Mock `count_resp.count = 2` (2 prior attempts exist)
- Call `grade_quiz()` with an all-correct submission
- Assert `result` contains `attempt_number == 3` (or verify the inserted row dict has `attempt_number=3`)
- This test FAILS on main (hardcoded `1`) and PASSES after fix

### AC 7 — New test: test_first_attempt_uses_attempt_number_1
- Mock `count_resp.count = 0`
- Assert computed attempt_number written to insert row == 1
- Confirms no regression for first-time takers

## Tasks

- [ ] Task 1: Write test_attempt_number_increments_on_retry (RED — fails on main)
- [ ] Task 2: Write test_first_attempt_uses_attempt_number_1 (RED — currently implicit, now explicit)
- [ ] Task 3: Update `_build_supabase()` to 4-call side_effect in all tests (prerequisite for GREEN)
- [ ] Task 4: Remove `attempt_number: int = 1` from `grade_quiz()` signature and docstring
- [ ] Task 5: Add SELECT COUNT query at Step 5 position (mirror grade_teachback pattern exactly)
- [ ] Task 6: Run `pytest tests/test_quiz_endpoint.py -v` — all ≥30 tests green
- [ ] Task 7: Run full suite `pytest -m unit -v` — zero regressions
- [ ] Task 8: Commit with message `fix(dev3/sprint1): S3-12 — compute attempt_number from DB count`

## Dev Notes

### Files to modify
| File | Change |
|------|--------|
| `apps/api/app/modules/assessment/service.py` | Remove param default, add COUNT query |
| `apps/api/tests/test_quiz_endpoint.py` | Expand mock, add 2 new tests |

### grade_teachback COUNT pattern to mirror exactly (lines 287–294 of service.py)
```python
# Step 5 — Query existing attempt count to compute attempt_number
count_resp = await asyncio.to_thread(
    lambda: supabase.table("quiz_attempts")
    .select("id", count="exact")
    .eq("session_id", session_id)
    .eq("segment_id", segment_id)
    .execute()
)
attempt_number: int = (count_resp.count or 0) + 1
```

### grade_quiz current signature (lines 20–27 of service.py — BEFORE fix)
```python
async def grade_quiz(
    *,
    session_id: str,
    lesson_id: str,
    segment_id: str,
    answers: list[QuizAnswer],
    attempt_number: int = 1,   # ← REMOVE THIS LINE
    user_id: str,
    supabase: Any,
) -> QuizResult:
```

### _build_supabase() mock expansion pattern
```python
def _build_supabase(session=None, lesson=None, count=0, insert_response=None):
    """Build a mock Supabase client with 4-call side_effect."""
    # ... build session_resp, lesson_resp, insert_resp as before ...
    count_resp = MagicMock()
    count_resp.count = count

    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value \
        .eq.return_value.eq.return_value.execute.return_value = count_resp
    mock_client.table.side_effect = [session_resp, lesson_resp, count_resp_table, insert_resp_table]
    # Note: exact mock chain depends on how _build_supabase is currently structured
    # Mirror the _build_supabase_tb() pattern in test_teachback_endpoint.py which already does 4 calls
    return mock_client
```

### CRITICAL: router.py passes no attempt_number
Verify in `apps/api/app/modules/assessment/router.py` — the call to `grade_quiz()` must NOT pass
`attempt_number`. It currently does not. Do NOT add it.

### BMAD development sequence
1. **RED**: Write tests 1 and 2 (they MUST fail before implementation)
2. **GREEN**: Update mock to 4-call, then implement the service change
3. **REFACTOR**: Ensure step comment numbering is accurate
4. **TEST**: Full suite passes
5. **COMMIT**: One commit per phase is ideal; one combined commit is acceptable
6. **CODE REVIEW**: 5-agent adversarial review before PR

---

## Dev Agent Record

### Completion Notes
_(fill after implementation)_

### File List
_(fill after implementation)_

### Change Log
- 2026-06-30: Story created (story-first gate commit)
