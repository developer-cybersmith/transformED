---
status: done
baseline_commit: "8de117d"
---

# Story 5-19 — Fix Three PR #267 Review Findings (Re-land after Revert)

## Story

**As a** developer re-landing the Sprint 5 batch (Stories 5-13 through 5-18),
**I want** the three blocking findings from Developer-2-max's 8-layer BMAD adversarial review to be
addressed before re-merging,
**so that** the reverted work can be re-landed cleanly and the three identified defects do not
re-enter main.

## Background

PR #267 (Sprint 5 batch) was merged at `4fcb0e8`, then reverted at `4f4d8ed` (PR #269) because an
8-layer BMAD adversarial review by Developer-2-max found three issues in the merged work:

1. **Finding #1 (CRITICAL) — Story 5-17 `force=true` cost-exposure bug:** `ChapterContextForm.
   handleGenerateNow()` always called `onGenerate(true)`, bypassing Gate 5 idempotency on *every*
   "Generate Now" click regardless of whether context actually changed. Estimated ~$60/hr/user in
   redundant lesson regeneration.

2. **Finding #2 — Story 5-13 stale D-ID cross-reference:** Commit `5049c77` renamed the interloper
   D206 → D213 to avoid a collision with PR #262's D200. `schemas/lesson.py` and
   `diagnose_lesson_duration.py` were updated to D213, but `test_s5_4_duration_budget.py` line 49
   still says `See D206` — the pre-rename ID.

3. **Finding #3 — Story 5-18 CI categorization understated:** The story's "remaining 8 advisory
   failures" table omitted two named pre-existing failures:
   - `test_s3_48_lua_distraction_cap.py::test_process_attention_signal_no_dispatch_when_guard_returns_false`
   - `test_phase1_economy_nodes.py::TestAC0GraphOrdering::test_lesson_planner_does_not_require_raw_text_or_chunks`
   True remaining count is 11, not 8.

## Acceptance Criteria

### AC1 — `isDirty` replaces hardcoded `force: true` in ChapterContextForm

`ChapterContextForm.tsx` must track `savedContext` — a state variable populated from the
`getChapterContext` fetch on mount and updated after a successful `putChapterContext` call.

`isDirty` is computed as: any field in `form` differs from `savedContext`, OR `savedContext` is null
(no prior context was fetched, meaning the chapter is new or the fetch failed).

`handleGenerateNow()` must call `onGenerate(isDirty)` — not `onGenerate(true)`.

After a successful PUT, `savedContext` is updated to `{ ...form }` so that a second "Generate Now"
click without further edits sends `force: false`.

The JSDoc comment on `onGenerate` prop must be updated to reflect that `force` is computed from
`isDirty`, not always `true`.

**Observable invariants:**
- An unchanged form → `isDirty = false` → `force: false` → Gate 5 returns cached lesson ($0)
- A changed form → `isDirty = true` → `force: true` → Gate 5 regenerates with new context

### AC2 — Guard test `test_d187_force_wiring_guard.py` updated for `isDirty` pattern

`test_handle_generate_now_calls_on_generate_true` must be renamed and updated:
- Old: asserts `"onGenerate(true)" in _FORM` — REMOVE this assertion (hardcoded `true` is the bug)
- New: asserts `"onGenerate(isDirty)" in _FORM` — the call passes the computed variable
- New: asserts `"savedContext" in _FORM` — the state variable is present
- New: asserts `"isDirty" in _FORM` — the computed variable is present
- New: asserts `"onGenerate(true)" not in _FORM` — the hardcoded path is gone

### AC3 — `test_s5_4_duration_budget.py` cross-reference updated to D213

Line 49 of `apps/api/tests/unit/test_s5_4_duration_budget.py` must read `See D213.` (not `See D206.`).
D213 is the canonical ID assigned to the S5-4 headline-number reading defect after the D200-D206 →
D207-D213 renaming (commit `5049c77`).

### AC4 — Story 5-18 table updated to 11 remaining advisory failures

`docs/stories/5-18-fix-dev3-advisory-ci-failures.md` must:
- Change "remaining 8 advisory failures" → "remaining 11 advisory failures"
- Replace the vague entry "3 further tests (from CI log — pre-existing on main)" with two named
  entries in the table:
  - `test_s3_48_lua_distraction_cap.py::test_process_attention_signal_no_dispatch_when_guard_returns_false` — Dev 4 (lua distraction cap guard)
  - `test_phase1_economy_nodes.py::TestAC0GraphOrdering::test_lesson_planner_does_not_require_raw_text_or_chunks` — Dev 1 (lesson planner graph ordering)
- The count in the "Total: 30 failures addressed" context line must be accompanied by the correct
  remaining count of 11, not 8.

### AC5 — All existing guard tests pass

- `pytest apps/api/tests/unit/test_d187_force_wiring_guard.py -v` — all 6 pass
- `pytest apps/api/tests/unit/test_defect_register_no_duplicate_ids.py -v` — all 3 pass
- `pytest apps/api/tests/unit/test_node_return_shape.py apps/api/tests/unit/test_unbounded_queries.py -v` — all pass
- `ruff check apps/api/` — clean

## Tasks

- [x] Write this story file and create story-first commit
- [x] Fix Finding #1: implement `isDirty` / `savedContext` pattern in `ChapterContextForm.tsx`
- [x] Fix Finding #2: update `test_d187_force_wiring_guard.py` for `isDirty` pattern (AC2)
- [x] Fix Finding #3: update `test_s5_4_duration_budget.py` line 49 D206 → D213 (AC3)
- [x] Fix Finding #4: update `docs/stories/5-18-fix-dev3-advisory-ci-failures.md` (AC4)
- [x] Run guard tests and ruff — confirm all pass (AC5)

## Scale & Load

1. **Unit of work:** One component-state change in `ChapterContextForm.tsx` (React state),
   one Python test comment update, one Markdown doc update. Fixed set of files; no pipeline, no
   DB, no LLM.

2. **Fixed budgets:** No budgets introduced. The `force` flag already existed on the backend;
   this story changes when `force: true` is sent (from "always" to "when context changed").
   The backend rate-limit (3/min, 20/hr, 3-concurrent) is unchanged.

3. **Scope of limits:** Per-user computation in the browser (React state diff). Zero server-side
   scope changes.

4. **Unbounded reads/writes:** None. `savedContext` is a single React state value; comparing it
   to `form` is O(5) field comparisons, bounded.

5. **Inherited caps re-derived:** Gate 5 idempotency check is unchanged. The `isDirty` flag
   determines whether to bypass it. No new cap introduced.

6. **Check-then-act safety:** No CTA sequence introduced. `savedContext` is local React state —
   no concurrent access. The backend's existing D45 race (UNIQUE constraint) is unchanged and
   out of scope.

## Dev Notes

Three files change for Finding #1:
1. `apps/web/src/components/dashboard/books/ChapterContextForm.tsx` — add `savedContext` state,
   compute `isDirty`, call `onGenerate(isDirty)`.
2. `apps/api/tests/unit/test_d187_force_wiring_guard.py` — update the guard test for the new
   `isDirty` / `savedContext` pattern.

One file changes for Finding #2:
3. `apps/api/tests/unit/test_s5_4_duration_budget.py` — comment: `See D206.` → `See D213.`

One file changes for Finding #3:
4. `docs/stories/5-18-fix-dev3-advisory-ci-failures.md` — correct the remaining advisory
   failure count and name the two previously unnamed tests.

## Change Log

| Date | Change |
|------|--------|
| 2026-09-29 | Story created — three PR #267 review findings to fix |
