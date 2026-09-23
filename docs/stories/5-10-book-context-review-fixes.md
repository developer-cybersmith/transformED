---
baseline_commit: ""
---

# Story 5-10 — Book Context Review Fixes (Dev 2 Code Review Response)

**Status:** in-progress  
**Dev:** Dev 3  
**Sprint:** Sprint 5  
**Branch:** `sprint5/s5-10-book-context-review-fixes`

---

## Story

As a developer, I need to address all 7 findings from the Dev 2 adversarial code review of
PR #244 (Stories S5-1 and S5-9) so that the book-context feature ships with no known defects,
correct production behaviour, and full CI guard coverage.

## Background

Dev 2 ran `/code-review` against the full diff of PR #244 (16 files, ~2,244 insertions) and
identified 7 findings. All 7 must be fixed before PR #244 can merge. This story captures each
as an acceptance criterion.

---

## Acceptance Criteria

### AC1 — Truncation mid-field bug fixed (F1, HIGH)
`prompt_context.py:merge_book_context`: when `last_newline == 0` (the only usable newline sits
at index 0 within the budget), `rfind()` returns 0 which is falsy, so the code falls back to a
hard character cut. Fix: use `!= -1` instead of `> 0` to distinguish "newline at position 0"
from "no newline found". After fix:
- `merge_book_context` truncates at `\n`-boundary when the last newline is at index 0
- Existing guard tests for `prompt_context.py` pass

### AC2 — Hardcoded `2_000` constant replaced (F2, HIGH)
`graph.py:lesson_planner_node` (approximately line 1891): replace the hardcoded literal `2_000`
(used for the warning log about book_context truncation threshold) with `_BOOK_CONTEXT_MAX_CHARS`
imported from `prompt_context.py`. After fix:
- No hardcoded `2_000` numeric literal remains in `lesson_planner_node`'s truncation warning log
- `settings.llm_*` aliases remain env-var-only (model strings not hardcoded) — no change there
- Guard test `test_no_hardcoded_model_strings.py` still passes

### AC3 — Dead code in `books.service.ts` removed (F3, MEDIUM)
`books.service.ts:getBookContext` (around line 394): the `catch` block checks `status === 204`,
but axios treats any 2xx as success and never throws into `catch`. This branch is unreachable.
Fix: remove the dead `status === 204` check from the `catch` block. The `try` block already
handles the 200 path; the `getChapterContext` sibling (line 448) shows the correct pattern —
checking `response.status === 204` outside `try/catch`.
After fix:
- No `status === 204` check exists inside a `catch` block in `getBookContext`
- ESLint and TypeScript type-check pass

### AC4 — Unbounded query comment added to `upsert_book_context` (F4, MEDIUM)
`context.py:upsert_book_context`: the `.upsert(...).select(...)` call carries no `.limit()`,
`.maybe_single()`, or `# BOUNDED:` annotation. The actual bound is the `UNIQUE(book_id, user_id)`
constraint on the `book_context` table (at most 1 row returned). Add a `# BOUNDED: UNIQUE
(book_id, user_id) guarantees at most one row per upsert` comment above the call, and also
add the `context.py` filename to the `test_unbounded_queries.py` guard's scope so the scan
covers it going forward.
After fix:
- The `BOUNDED:` comment is present on the upsert `.select()` call
- `tests/unit/test_unbounded_queries.py` scans `context.py` and does not flag it

### AC5 — F12 registered as D-nn in DEFECT-REGISTER (F5, MEDIUM)
The story file for S5-1 (`docs/stories/S5-1-book-context-form.md`) has an unchecked F12
("double `_validated_book_id` call in router endpoints") that has no D-nn register ID. Add
`D-nn` entry in `docs/DEFECT-REGISTER.md` and update the story file's F12 finding to include
the ID. The registered status is DEFERRED (the redundant validation is harmless) with a clear
rationale.
After fix:
- `docs/DEFECT-REGISTER.md` has a new entry for the double-validation finding
- The S5-1 story's F12 finding references the new D-nn ID

### AC6 — `merge_book_context` per-dispatch duplication noted and logged once (F6, LOW)
`graph.py:narration_generator_node` re-runs `merge_book_context` on the same `book_context`
string for every dispatched section. Because it was already removed from narration's return
dict (S5-9 fix) the truncation flag no longer duplicates. The remaining issue is the
duplicate `logger.warning` lines when truncation fires (N warnings for N sections).
Fix: read `book_context_truncated` from state in `narration_generator_node` (set by
`lesson_planner_node`) and skip the warning log when it is already `True`. The
`merge_book_context` call itself remains (narration still needs the merged string).
After fix:
- When `book_context_truncated` is already `True` in state, `narration_generator_node`
  does NOT emit a second truncation warning
- `narration_generator_node` still calls `merge_book_context` for the merged string

### AC7 — Inline import style in `context.py` made consistent (F7, LOW)
`context.py` re-imports `asyncio` inside three function bodies and imports `db_rows` mid-function.
Its own docstring says it mirrors `context_chapter.py`'s conventions, but `context_chapter.py`
imports `asyncio` once at module top-level. Move `import asyncio` to module level. The
`from app.core.db import rows as db_rows` import can be combined with the existing top-level
`from app.core.db import get_supabase, single_row` import.
After fix:
- `import asyncio` appears exactly once in `context.py`, at module top-level
- `db_rows` is imported at module top-level alongside `get_supabase` and `single_row`
- ruff I001 / E402 / format checks pass

---

## Scale & Load

1. **Unit of work**: one `merge_book_context` call per node per lesson. No change to scale.
2. **Fixed budgets**: `_BOOK_CONTEXT_MAX_CHARS` (2,000 chars) unchanged. AC1 only corrects
   an off-by-one at the `rfind==0` boundary — no budget change.
3. **Scope**: all fixes are per-request / per-node. No shared state changes.
4. **Unbounded reads**: AC4 adds the `BOUNDED:` comment to the one unannoted call. No new reads.
5. **Inherited caps**: none re-derived — no new caps introduced.
6. **Check-then-act**: no new check-then-act patterns introduced.

---

## Tasks

- [x] T1: Create story file and commit story-first
- [ ] T2: Fix AC1 — `rfind == 0` truncation edge case in `prompt_context.py`
- [ ] T3: Fix AC2 — replace hardcoded `2_000` with `_BOOK_CONTEXT_MAX_CHARS` in `graph.py`
- [ ] T4: Fix AC3 — remove dead `status === 204` from `catch` in `books.service.ts`
- [ ] T5: Fix AC4 — add `# BOUNDED:` comment + extend `test_unbounded_queries.py` scope
- [ ] T6: Fix AC5 — register F12 as D-nn in DEFECT-REGISTER and update S5-1 story file
- [ ] T7: Fix AC6 — skip duplicate truncation warning in `narration_generator_node`
- [ ] T8: Fix AC7 — move inline imports to module top-level in `context.py`
- [ ] T9: Run all guard tests locally and verify clean
- [ ] T10: Commit, push, open PR

---

## Dev Agent Record

### Implementation Plan
Address findings in severity order: bugs first (AC1-AC3), then guard/documentation (AC4-AC6),
then style (AC7). No migrations needed.

### File List
- `apps/api/app/modules/content/pipeline/prompt_context.py` (AC1)
- `apps/api/app/modules/content/pipeline/graph.py` (AC2, AC6)
- `apps/web/src/lib/books.service.ts` (AC3)
- `apps/api/app/modules/content/context.py` (AC4, AC7)
- `apps/api/tests/unit/test_unbounded_queries.py` (AC4)
- `docs/DEFECT-REGISTER.md` (AC5)
- `docs/stories/S5-1-book-context-form.md` (AC5)

### Change Log
| Date | Change |
|------|--------|
| 2026-09-23 | Story created from Dev 2 PR #244 code review findings |
