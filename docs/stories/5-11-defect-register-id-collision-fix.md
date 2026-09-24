---
baseline_commit: ""
---

# Story 5-11 — Defect Register ID Collision Fix

**Status:** in-progress
**Dev:** Dev 3
**Sprint:** Sprint 5
**Branch:** `sprint5/s5-9-book-context-processing-ux` (applied directly to PR #244)

---

## Story

As a developer merging PR #244, I need every DEFECT-REGISTER entry added by
this branch to carry an ID that is not already taken on `main`, so that the
register remains unambiguous after merge and the binding rule against duplicate
IDs (Defect Register §"Binding rules" rule 5) is not violated.

## Background

Dev 2's re-review of PR #244 (2026-09-23) flagged that the D167 we registered
for the double `_validated_book_id` call collides with an existing D167 on
`main` (lesson_planner_node continuity_notes per-batch gap, PR #237).

Audit of the full branch diff against `main` reveals five additional collisions:
our branch's heading-format entries `## D154`–`## D158` all collide with
existing table-format entries on `main` (D154 = per-node timeout budget, D155 =
load-test cleanup, D156 = upload retry, D157 = flyctl secrets casing, D158 =
Ask Tutor stub — none are the book-context defects our branch registers under
those IDs).

`main`'s highest ID is D172. PR #239 (unmerged) claims D173. The next six free
IDs are D174–D179.

---

## Acceptance Criteria

### AC1 — All six colliding IDs renumbered in DEFECT-REGISTER.md

| Old ID | Content | New ID |
|--------|---------|--------|
| D154   | Langfuse DPDP gap — book-context in traces | D174 |
| D155   | No TestClient integration tests for book-context endpoints | D175 |
| D156   | Branch stacked on S5-1 rather than `main` (process) | D176 |
| D157   | No rate limiting on `PUT /books/{book_id}/context` | D177 |
| D158   | No DB `CHECK` constraints on text columns | D178 |
| D167   | Double `_validated_book_id` call in router endpoints | D179 |

After fix:
- No heading `## D154`–`## D158` or `## D167` exists in the branch diff (those
  numbers are owned by `main`'s entries)
- Six new headings `## D174`–`## D179` appear in the diff instead

### AC2 — All cross-references updated

Internal cross-references to the renamed IDs:
- `docs/DEFECT-REGISTER.md`: D179's resolution path referenced "Add the D155
  integration tests first" → updated to "Add the D175 integration tests first"
- `docs/stories/S5-1-book-context-form.md` F12 finding: "D167" → "D179"

After fix:
- `grep -r "## D15[4-8]\|## D167" docs/DEFECT-REGISTER.md` → no matches
- `grep "D155\|D167" docs/stories/S5-1-book-context-form.md` → no matches for
  the old IDs (D175 reference is the only occurrence)

### AC3 — No new collisions introduced

After fix:
- The six new IDs (D174–D179) do not exist anywhere in `main`'s
  DEFECT-REGISTER.md
- D173 (claimed by PR #239) is not used

---

## Scale & Load

1. **Unit of work:** One DEFECT-REGISTER.md file, six heading renames. N/A for scale.
2. **Fixed budgets:** N/A — documentation-only change.
3. **Scope:** Per-repository document. N/A.
4. **Unbounded reads/writes:** N/A.
5. **Inherited caps:** N/A.
6. **Check-then-act:** N/A — no DB or concurrent state involved.

---

## Tasks

- [x] T1: Create story file and commit story-first
- [ ] T2: Rename D154→D174, D155→D175, D156→D176, D157→D177, D158→D178 in DEFECT-REGISTER.md
- [ ] T3: Rename D167→D179 in DEFECT-REGISTER.md and fix D179's internal D155→D175 reference
- [ ] T4: Update S5-1 story F12 cross-reference from D167 to D179
- [ ] T5: Verify no old IDs remain in the branch diff; push; add PR comment

---

## Dev Agent Record

### Change Log
| Date | Change |
|------|--------|
| 2026-09-23 | Story created — 6 ID collisions identified from Dev 2 re-review + full diff audit |
