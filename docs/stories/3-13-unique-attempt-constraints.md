---
Status: ready-for-dev
baseline_commit: ""
---

# Story 3-13: Unique Attempt Constraints (DB Migration + 409 Handling)

**Epic:** Sprint 1 Assessment API — Remediation
**Branch:** `sprint1/s1-13-unique-attempt-constraints`
**Audit source:** F-001 (side-effect — without unique constraints, duplicate attempt rows possible)
**Depends on:** Story 3-12 (`sprint1/s1-12-quiz-attempt-number-fix`) merged first

## User Story

As a system administrator,
I want the database to enforce that no two quiz or teach-back attempts share the same (session, segment, attempt_number) combination,
so that data integrity is guaranteed at the storage layer even if a race condition or retry bug occurs.

## Acceptance Criteria

### AC 1 — Migration file created (user applies manually)
- A new migration file `supabase/migrations/20260630000000_unique_attempt_constraints.sql` is created
- Content adds UNIQUE constraints on both tables (see exact SQL below)
- This file is committed to the branch but **never applied autonomously** — user runs it manually

### AC 2 — quiz_attempts UNIQUE constraint
```sql
ALTER TABLE quiz_attempts
  ADD CONSTRAINT uq_quiz_attempt
  UNIQUE (session_id, question_id, attempt_number);
```
- Prevents two rows for the same (session, question, attempt) triple
- Uses question_id (not segment_id) because each question is individually tracked

### AC 3 — teachback_attempts UNIQUE constraint
```sql
ALTER TABLE teachback_attempts
  ADD CONSTRAINT uq_teachback_attempt
  UNIQUE (session_id, segment_id, attempt_number);
```
- Prevents two rows for the same (session, segment, attempt) triple

### AC 4 — grade_quiz handles 409 Conflict on duplicate insert
- If the `quiz_attempts` bulk insert returns an error containing "duplicate" or "unique" (case-insensitive),
  `grade_quiz()` raises `HTTPException(status_code=409, detail="Duplicate quiz attempt detected.")`
- This is a separate branch from the generic 500 already present for other insert errors

### AC 5 — grade_teachback handles 409 Conflict on duplicate insert
- Same pattern as AC 4 applied to the `teachback_attempts` insert in `grade_teachback()`
- Error check: if error message contains "duplicate" or "unique" → 409, else → 500

### AC 6 — New tests for 409 path
- `test_quiz_duplicate_attempt_returns_409`: mock insert returns error with "duplicate key" message → assert 409
- `test_teachback_duplicate_attempt_returns_409`: same for teachback
- Both tests are unit tests (no actual DB needed — mock the insert error)

### AC 7 — Existing 500 tests still pass
- `test_insert_error_raises_500` (quiz) still passes — mock error message "constraint violation" (not "unique")
- `test_teachback_insert_error_raises_500` — same

## Tasks

- [ ] Task 1: Write migration SQL file `supabase/migrations/20260630000000_unique_attempt_constraints.sql`
- [ ] Task 2: Write test_quiz_duplicate_attempt_returns_409 (RED — fails before implementation)
- [ ] Task 3: Write test_teachback_duplicate_attempt_returns_409 (RED)
- [ ] Task 4: Add 409 branch to grade_quiz() insert error check in service.py
- [ ] Task 5: Add 409 branch to grade_teachback() insert error check in service.py
- [ ] Task 6: Run `pytest -m unit -v` — all tests green including 2 new 409 tests
- [ ] Task 7: Commit all changes

## Dev Notes

### Migration file — exact content to write
```sql
-- Migration: 20260630000000_unique_attempt_constraints.sql
-- Adds UNIQUE constraints to prevent duplicate attempt rows.
-- Applied after Story 3-12 (attempt_number computed dynamically).
-- NEVER MODIFY applied migrations. Apply this migration manually:
--   supabase db push  (local)   OR   supabase migration up  (remote)

ALTER TABLE quiz_attempts
  ADD CONSTRAINT uq_quiz_attempt
  UNIQUE (session_id, question_id, attempt_number);

ALTER TABLE teachback_attempts
  ADD CONSTRAINT uq_teachback_attempt
  UNIQUE (session_id, segment_id, attempt_number);
```

### DB POLICY — user applies migration manually
NEVER run `supabase db push` or any migration tool autonomously.
Commit the SQL file only. Tell the user: "Apply migration manually with `supabase db push` after merging."

### Error detection pattern for 409 vs 500
```python
# In grade_quiz() after bulk insert:
insert_error = getattr(insert_resp, "error", None)
if insert_error:
    err_msg = str(insert_error).lower()
    if "duplicate" in err_msg or "unique" in err_msg:
        raise HTTPException(status_code=409, detail="Duplicate quiz attempt detected.")
    raise HTTPException(status_code=500, detail="Failed to persist quiz attempt.")

# Same pattern in grade_teachback():
insert_error = getattr(insert_resp, "error", None)
if insert_error:
    err_msg = str(insert_error).lower()
    if "duplicate" in err_msg or "unique" in err_msg:
        raise HTTPException(status_code=409, detail="Duplicate teach-back attempt detected.")
    raise HTTPException(status_code=500, detail="Failed to persist teach-back attempt.")
```

### Files to modify
| File | Change |
|------|--------|
| `supabase/migrations/20260630000000_unique_attempt_constraints.sql` | NEW — migration SQL |
| `apps/api/app/modules/assessment/service.py` | 409 branch in grade_quiz + grade_teachback |
| `apps/api/tests/test_quiz_endpoint.py` | 2 new 409 tests |
| `apps/api/tests/test_teachback_endpoint.py` | 1 new 409 test |

### BMAD development sequence
1. **RED**: Write the 2 new 409 tests (fail before implementation)
2. **GREEN**: Add 409 branch to service.py (both functions)
3. **REFACTOR**: Ensure error check pattern is consistent across both functions
4. **TEST**: Full suite passes
5. **COMMIT**: Include migration file + service changes + tests
6. **USER ACTION REQUIRED**: After PR merged, apply migration manually

---

## Dev Agent Record

### Completion Notes
_(fill after implementation)_

### File List
_(fill after implementation)_

### Change Log
- 2026-06-30: Story created (story-first gate commit)
