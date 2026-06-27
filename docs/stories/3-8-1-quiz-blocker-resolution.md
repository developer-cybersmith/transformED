---
baseline_commit: ""
---

# Story 3-8-1: Quiz Endpoint Blocker Resolution

**Status:** ready-for-dev

---

## Story

As Dev 3 (tannmayygupta),
I want all fixable BLOCKERs from the BMAD audit of Story 3-8 resolved,
so that POST /api/assessment/quiz is production-safe, fully tested, and passes BMAD review.

---

## Context

Story 3-8 (quiz grading endpoint) was audited by 5 parallel BMAD agents. The synthesis returned
BLOCKED with 13 BLOCKERs across security, correctness, test coverage, and process dimensions.

This story is written FIRST (before any implementation) to restore BMAD story-first compliance.
The two PROCESS BLOCKERs from story 3-8 (story created concurrently with code; no red-green trail)
are acknowledged but cannot be retroactively fixed in git. THIS story demonstrates compliance going
forward.

The RLS BLOCKER (service-role key bypasses RLS globally) is a project-wide infra concern owned by
Dev 1. This story adds application-layer IDOR defense-in-depth. Full RLS fix tracked as Sprint 2 item.

---

## Acceptance Criteria

**Security:**
- AC 1: `QuizAnswer.response_index` has `Field(ge=0)` — Pydantic rejects negative values with HTTP 422
- AC 2: `QuizAnswer.response_time_ms` has `Field(default=0, ge=0)` — negative values rejected with HTTP 422
- AC 3: After session ownership check, `session.lesson_id` is cross-checked against request `lesson_id`; mismatch raises HTTP 403

**Correctness:**
- AC 4: `ces_contribution = quiz_accuracy × settings.ces_weight_quiz × 100` — result in [0, 35] on 0-100 CES scale
- AC 5: Supabase insert return value captured; if `insert_resp.error` is set, raise HTTP 500

**Test coverage (8 missing paths from audit):**
- AC 6: Test asserts `ces_contribution` at 50% accuracy equals `pytest.approx(0.5 × ces_weight_quiz × 100)`
- AC 7: Test asserts HTTP 404 when lesson row is entirely absent (`lesson_resp.data is None`)
- AC 8: Test verifies `response_index` is written to DB insert row
- AC 9: Test verifies `is_correct` is written to DB insert row
- AC 10: Test verifies `segment_id` is written to DB insert row
- AC 11: Test verifies `correct_index=99` (out of range) → `correct_option=None` in feedback, no IndexError
- AC 12: Test verifies `response_index=99` (out of range of options, but ge=0) → `selected_option=None`, no IndexError
- AC 13: HTTP-layer test verifies unauthenticated request (no token) → 403

**Existing tests updated:**
- AC 14: All existing CES tests updated to expect `× 100` scale (was: `1.0 × 0.35`, now: `1.0 × 0.35 × 100`)

**IDOR coverage:**
- AC 15: Test verifies that `lesson_id` mismatching `session.lesson_id` → HTTP 403

---

## Tasks / Subtasks

### Task 1 — Fix schemas.py
- [ ] 1.1 Import `Field` from `pydantic`; add `Field(ge=0)` to `response_index`
- [ ] 1.2 Add `Field(default=0, ge=0)` to `response_time_ms`

### Task 2 — Fix service.py
- [ ] 2.1 IDOR guard: after user ownership check, assert `session.lesson_id == lesson_id`; raise HTTP 403 on mismatch
- [ ] 2.2 CES scale: multiply `quiz_accuracy × ces_weight_quiz × 100`
- [ ] 2.3 Insert check: capture `insert_resp`; raise HTTP 500 if `insert_resp.error` is set

### Task 3 — Add 9 missing tests and update 1 existing test
- [ ] 3.0 Update `test_ces_contribution_uses_quiz_weight` — expected value × 100
- [ ] 3.1 Add `test_ces_contribution_at_partial_accuracy`
- [ ] 3.2 Add `test_raises_404_when_lesson_row_absent`
- [ ] 3.3 Add `test_db_rows_contain_correct_fields` (covers ACs 8, 9, 10)
- [ ] 3.4 Add `test_feedback_correct_option_none_for_out_of_range_correct_index`
- [ ] 3.5 Add `test_feedback_selected_option_none_for_out_of_range_response_index`
- [ ] 3.6 Add `test_http_layer_authentication_is_enforced`
- [ ] 3.7 Add `test_raises_403_when_lesson_id_mismatches_session`

---

## Dev Notes

### Files to Change
- `apps/api/app/modules/assessment/schemas.py` — Field validators
- `apps/api/app/modules/assessment/service.py` — IDOR guard, CES scale, insert check
- `apps/api/tests/test_quiz_endpoint.py` — test updates and additions

### schemas.py — exact changes
Import Field alongside BaseModel. Apply to both fields:
```
response_index: int = Field(ge=0)
response_time_ms: int = Field(default=0, ge=0)
```

### service.py — IDOR guard placement
Insert immediately after the existing `str(session_resp.data["user_id"]) != str(user_id)` block
(after line that raises HTTP 403 for wrong user). The guard must use `.get("lesson_id", "")` to
handle sessions that pre-date the lesson_id column.

### service.py — CES scale
`ces_weight_quiz` default is 0.35 (fraction). CES threshold is 50 on 0-100 scale. Correct formula:
`ces_contribution = round(quiz_accuracy * settings.ces_weight_quiz * 100, 4)`
Max contribution for quiz: 1.0 × 0.35 × 100 = 35 points.

### service.py — insert check
Capture the asyncio.to_thread return value. `supabase-py` v2 returns an object with `.error`
attribute on failure. Use `getattr(insert_resp, "error", None)` to safely check.

### test_quiz_endpoint.py — _build_supabase for lesson_row_absent
`_build_supabase(session_data=_SESSION_ROW, lesson_data=None, insert_data=[])` — the helper's
"all None = default" guard only fires when ALL three args are None, so passing session_data
explicitly bypasses it and sets lesson_resp.data = None.

### test_quiz_endpoint.py — DB field capture pattern
Use the same pattern as `test_response_time_ms_written_to_db`: a `_capture` side_effect function
that extends a list, then assert the captured rows contain the expected fields.

### test_quiz_endpoint.py — unauthenticated test
`HTTPBearer(auto_error=True)` raises HTTP 403 when no Authorization header is present.
This fires before `get_settings` is called, so no settings mock is needed.
Create a bare FastAPI app with `router` included but NO `dependency_overrides`.

### Process Note
Story 3-8 process violations (story-first, red-green trail) are acknowledged BLOCKER-class
issues that exist in the git history and cannot be retroactively remediated. THIS story (3-8-1)
is committed in a dedicated commit before any implementation begins, satisfying BMAD story-first.
The implementation commit will reference this story by number.

---

## Senior Developer Review (AI)
(To be filled after implementation)

---

## Dev Agent Record

**Status:** ready-for-dev

**Debug Log:** (to be filled during implementation)

**Completion Notes:** (to be filled on completion)
