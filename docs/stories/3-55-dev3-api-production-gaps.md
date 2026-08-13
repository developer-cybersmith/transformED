---
status: in-progress
baseline_commit: 6405593
---

# Story 3-55 — Close Dev 3 Assessment API production gaps (D71/D72 closures + D92/D93/D94 fixes)

**Sprint:** Sprint 3 · **Owner:** Dev 3 · **Branch:** `sprint3/s3-55-learner-dna-production-gaps`

## Problem

Dev 3's Assessment API has five outstanding production-readiness issues. Two (D71, D72) are already fixed in code but unrecorded as closed in `docs/DEFECT-REGISTER.md`. Three are unregistered defects with no CI guard:

- **D71** — Onboarding LLM failure permanently locks user out. Fixed in `service.py:1166-1199` (try/except + row rollback + HTTPException 503 so router cleanup fires). All 7 enforcement tests pass in `test_onboarding_llm_failure.py`.
- **D72** — Stale "TransformED" brand in DPDP disclaimer and onboarding prompt. Fixed in `prompts.py` (HIE throughout) + migration `20260813000000_learner_dna_rebrand.sql`. Enforcement tests pass.
- **D92** — `session_events` SELECT in `dna_fusion.py` has no `.limit()`. A student generating many events in a single session materialises an unbounded result set on the session-end path. (The same shape as Scale Contract Q4 defect class.)
- **D93** — `dna_fusion.py` is excluded from `test_unbounded_queries.py`'s scanner scope (`REQUEST_PATH_FILENAMES` is `("router.py", "service.py")`). Any future unbounded read added to a standalone function in `dna_fusion.py` is invisible to CI.
- **D94** — `SessionCreate.lesson_id: str` has no UUID validator. Any non-UUID string (including a 1-char typo) passes Pydantic validation and 500s at the Postgres UUID cast with no actionable error message.

**D95** (EMA `session_count` Python read-modify-write race) is registered in the defect register with this story and explicitly deferred to Sprint 4. It requires a Supabase RPC migration for an atomic DB-side increment — too complex for a patch story; harmless for MVP single-user load.

## Acceptance Criteria

1. `docs/DEFECT-REGISTER.md` entry for **D71** is updated to `~~D71~~` CLOSED with this story number and date. Enforcement: `test_onboarding_llm_failure.py` (7 tests, already passing).
2. `docs/DEFECT-REGISTER.md` entry for **D72** is updated to `~~D72~~` CLOSED with this story number and date. Enforcement: same file.
3. `docs/DEFECT-REGISTER.md` gains a new entry **D92** (unbounded `session_events` SELECT, Dev 3, closed by this story) with `test_dna_fusion_session_events_is_bounded` as enforcement.
4. `dna_fusion.py` `session_events` SELECT carries `.limit(10_000)` on its chain (or the lookbehind line) so the scanner would flag a removal.
5. `quiz_attempts` and `teachback_attempts` SELECTs in `dna_fusion.py` each carry a `# BOUNDED:` comment explaining why their row count is naturally capped (per-session, bounded by lesson structure).
6. `docs/DEFECT-REGISTER.md` gains a new entry **D93** (CI scan gap, `dna_fusion.py` missing from scope, Dev 3, closed by this story) with the premise test as enforcement.
7. `REQUEST_PATH_FILENAMES` in `test_unbounded_queries.py` includes `"dna_fusion.py"`.
8. A new premise test `test_dna_fusion_is_in_scan_scope` asserts that `assessment/dna_fusion.py` is returned by `request_path_modules()`.
9. `docs/DEFECT-REGISTER.md` gains a new entry **D94** (lesson_id UUID validation gap, Dev 3, closed by this story) with `test_session_create_validates_uuid_format` as enforcement.
10. `SessionCreate.lesson_id` accepts a valid UUID string and raises `ValidationError` for any non-UUID input (`"x"`, `""`, `"not-a-uuid"`, `"123"`).
11. The existing `body.lesson_id` usage in `router.py` continues to work unchanged (string type preserved through the validator).
12. `docs/DEFECT-REGISTER.md` gains a new entry **D95** (EMA session_count race, deferred Sprint 4, Dev 3) with DISCIPLINE enforcement and a comment explaining the Sprint 4 RPC path.
13. All new tests are `@pytest.mark.unit` and pass without a real Supabase or Redis connection.
14. `python -m pytest apps/api/tests/unit/test_unbounded_queries.py apps/api/tests/test_onboarding_llm_failure.py apps/api/tests/unit/test_session_create_schema.py -v -p no:warnings` exits 0.

## Scale & Load

1. **Unit of work:** One call to `fuse_learner_dna` per session end. One `POST /sessions` request per lesson start.
2. **Fixed budgets:** D92's `.limit(10_000)` caps event rows per fusion call. Per-session event count at scale (many hover/skip events) — beyond the limit, older events are silently ignored; this is an acceptable approximation (signal already computed from counts, not raw rows).  D93's CI guard has no runtime cost. D94 fails fast at Pydantic validation before any DB call.
3. **Scope:** D92 limit is per-session call (not per user, not per deployment). D93 is a CI-only change. D94 is per-request.
4. **Unbounded reads:** D92 is the unbounded read being fixed. After the fix, all three `dna_fusion.py` SELECTs are bounded.
5. **Inherited caps:** `.limit(10_000)` is derived from observed event volumes (jargon hover, skip, help — typically < 100/session) with a 100× safety margin. Re-derive if sessions routinely exceed 1,000 events.
6. **Concurrency:** D94 validation is stateless; no race. D93 is a test-only file change.

## Tasks

- [x] T1: Close D71 and D72 in defect register (write-only to register — code already fixed)
- [x] T2: Write failing test for D92 (`test_dna_fusion_session_events_is_bounded`) — RED
- [x] T3: Fix D92 — add `.limit(10_000)` to `session_events` SELECT; add `# BOUNDED:` to `quiz_attempts` and `teachback_attempts` — GREEN
- [x] T4: Write failing test for D93 (`test_dna_fusion_is_in_scan_scope`) — RED
- [x] T5: Fix D93 — add `"dna_fusion.py"` to `REQUEST_PATH_FILENAMES` — GREEN
- [x] T6: Write failing tests for D94 (`test_session_create_validates_uuid_format`) — RED
- [x] T7: Fix D94 — add `@field_validator("lesson_id")` to `SessionCreate` — GREEN
- [x] T8: Register D92/D93/D94 as CLOSED + D95 as OPEN/DEFERRED in defect register
- [x] T9: Run full test suite; confirm no regressions
- [x] T10: Update `docs/dev3-assessment-tracker.md`

## Dev Notes

- `dna_fusion.py` is in `app.modules.assessment.dna_fusion` — it is on the request path (`service.py` imports and calls `fuse_learner_dna`), so the unbounded query CI guard SHOULD cover it.
- The `_function_scope_bounds` leniency in `test_unbounded_queries.py` means `fuse_learner_dna`'s unbounded selects are currently masked by the `.maybe_single()` on the `learner_dna` read. After D92's fix adds `.limit(10_000)`, the session_events select is genuinely bounded regardless.
- D93's premise test addition goes in `test_unbounded_queries.py` alongside the existing `test_request_path_modules_are_where_we_think_they_are` test.
- D94: Use `@field_validator("lesson_id", mode="before")` + `uuid.UUID(v)` — keeps the `str` type so downstream callers (`body.lesson_id` in `router.py`) need no changes.
- D95 (EMA race): The fix would require a Postgres function `increment_learner_dna_session_count(p_user_id uuid) RETURNS int` + `supabase.rpc(...)` call, replacing the Python `old_session_count + 1`. Not in scope here; register only.
- The defect register's closure format: change `| **Dnn** |` to `| ~~Dnn~~ |` and prepend `**CLOSED YYYY-MM-DD (Story 3-55)**. ` to the description.

## Dev Agent Record

### Implementation Notes

- D71 fix confirmed present at `service.py:1166-1199`; all 7 `test_onboarding_llm_failure.py` tests pass.
- D72 fix confirmed: `prompts.py:120` shows "HIE"; migration `20260813000000_learner_dna_rebrand.sql` exists.
- `REQUEST_PATH_FILENAMES` currently `("router.py", "service.py")` at `test_unbounded_queries.py:121`.
- `session_events` SELECT in `dna_fusion.py` at lines 289-299 has no `.limit()`.
- `quiz_attempts` SELECT at lines 263-272: naturally bounded (per-session, ≤ 15 segs × 10 Q = 150 rows max).
- `teachback_attempts` SELECT at lines 276-285: naturally bounded (per-session, ≤ 15 segs × 5 retries = 75 rows max).
- `SessionCreate.lesson_id: str` at `schemas.py:53` — no validator, no `min_length`.

### File List

- `docs/DEFECT-REGISTER.md` — close D71/D72; add D92/D93/D94 (closed) + D95 (deferred)
- `apps/api/app/modules/assessment/dna_fusion.py` — D92: add `.limit(10_000)` + `# BOUNDED:` comments
- `apps/api/tests/unit/test_unbounded_queries.py` — D93: add `"dna_fusion.py"` to `REQUEST_PATH_FILENAMES`; add premise test
- `apps/api/app/modules/assessment/schemas.py` — D94: add UUID field validator to `SessionCreate.lesson_id`
- `apps/api/tests/unit/test_session_create_schema.py` — D92/D93/D94 enforcement tests
- `docs/dev3-assessment-tracker.md` — mark task complete
