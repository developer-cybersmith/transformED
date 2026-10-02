# Story 5-20 — Fix Three PR #271 Review Findings

**Sprint:** 5  
**Owner:** Dev 3  
**Branch:** sprint5/s5-19-fix-pr267-review-findings (continuing on existing branch)  
**Created:** 2026-10-02  
**Status:** In Progress

---

## Context

Developer-2-max's 8-layer BMAD adversarial review of PR #271 (the re-land of Sprint 5 batch
with Story 5-19 fixes) surfaced three new findings that Story 5-19 did not address:

1. **Finding #1 — Missing behavioral test:** No test exercises the `isDirty=false` path
   (form pre-populated, student clicks Generate Now without editing → `force` must be absent
   from the POST body). The existing test only exercises `savedContext=null` (isDirty=true).
2. **Finding #2 — graph.py D206 comments wrong + D187 register entry stale:** Three comment
   blocks in `graph.py` that were originally `# D192` (Story-249 internal tracking labels for
   narration-truncation fan-out keys) were erroneously renamed to `# D206` in commit `67924f8`.
   D206 in the register is canonically the Sidebar collapsed-state expand toggle bug (Dev 2) —
   completely unrelated. Additionally, the D187 DEFECT-REGISTER entry still describes the code
   as calling `onGenerate(true)`, which Story 5-19 changed to `onGenerate(isDirty)`.
3. **Finding #3 — Story 5-18 count arithmetic error:** Story 5-18's "remaining 11 advisory
   failures" is wrong: 3+3+2+1+1 = 10, not 11. The "8 + 2 newly named = 11" calculation
   was also wrong (8 + 2 = 10).

---

## Acceptance Criteria

### AC1 — Behavioral test: isDirty=false path sends no force
A new test in `ChapterGenerateControl.test.tsx` must:
- Override the GET `/content/books/:bookId/chapters/:chapterId/context` handler to return
  200 with a non-null context row (e.g. `depth_duration: "standard_30_45m"`).
- Open the tier picker, choose a tier, wait for `ChapterContextForm` to mount and load its
  data (savedContext is now non-null and equals the fetched data).
- Click "Generate Now" without editing any field (isDirty=false).
- Assert the POST body equals `{ tier: "T2" }` — no `force` field.

This test proves the isDirty=false path correctly omits `force`, preventing redundant
regeneration at ~$0.60/click for an unchanged context.

### AC2 — graph.py: revert D206 comments to D192
The three comment blocks in `graph.py` that reference `# D206` in the context of narration
fan-out state key declarations must be reverted to `# D192`:
- The comment before the `book_context_truncated`/`chapter_context_truncated` setdefault block
  in `_fan_out_phase1_economy_nodes` (line ~7946).
- The comment before the narration truncation keys in `_FAN_OUT_NARRATION_STATE_KEYS`
  (line ~7821).
- The comment before the `book_context_truncated`/`chapter_context_truncated` setdefault block
  in `_fan_out_narration_generator_nodes` (line ~8102).

D206 in the DEFECT-REGISTER is the Sidebar expand toggle bug (Dev 2). Using it as an internal
label for unrelated narration fan-out code creates a false cross-reference that will confuse
any future reader linking comments to register entries.

### AC3 — DEFECT-REGISTER D187 entry updated to reflect isDirty fix
The D187 entry must be updated to:
- Reflect that `ChapterContextForm.handleGenerateNow()` now calls `onGenerate(isDirty)`, not
  `onGenerate(true)` (fixed by Story 5-19).
- Update the enforcement section: the guard test (`test_d187_force_wiring_guard.py`) now
  asserts `onGenerate(isDirty)` in form handler and `onGenerate(true)` NOT present, not the
  old `onGenerate(true)` assertion.
- Update the browser integration test description: "Generate Now path includes force: true"
  becomes "Generate Now path sends force only when context is dirty" since isDirty determines
  whether force is sent.

### AC4 — Story 5-18 count corrected to 10
`docs/stories/5-18-fix-dev3-advisory-ci-failures.md` line 29 must read "remaining **10**
advisory failures" (table sums: 3+3+2+1+1=10, not 11).

### AC5 — Guard tests pass
All existing guard tests for affected modules still pass after this story:
- `tests/unit/test_d187_force_wiring_guard.py` (6 tests — isDirty assertions)
- `tests/unit/test_defect_register_no_duplicate_ids.py`
- `tests/unit/test_s5_4_duration_budget.py`
- `tests/unit/test_node_return_shape.py`
- `tests/unit/test_unbounded_queries.py`

### AC6 — ruff format + check clean
All modified Python files pass `ruff format --check` and `ruff check` with zero errors.

---

## Scale & Load

1. **One unit of work:** One test run; one graph.py comment block update; two document
   line changes. No code path changes that execute at runtime.
2. **Fixed budgets vs variable input:** N/A — no runtime budget changes.
3. **Scope of every limit:** N/A — test and documentation changes only; no query or limit
   modifications.
4. **Unbounded reads/writes:** None introduced — this story does not add any DB queries.
5. **Inherited caps re-derived:** N/A — no caps changed.
6. **Check-then-act concurrency:** N/A — test/documentation changes only.

---

## Implementation Notes

- All changes on existing branch `sprint5/s5-19-fix-pr267-review-findings`.
- graph.py changes are comment-only (no logic change) — `# D206` → `# D192` at three sites.
- The behavioral test uses MSW `server.use()` to override the default 204 GET handler
  with a 200 response carrying context data, ensuring `savedContext` is populated before
  the Generate Now click.
- D187 register update touches only the Decision and Enforcement columns, not the defect
  description or severity.
