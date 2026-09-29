---
baseline_commit: ""
---

# Story 5-12 — Fix Stale Defect Register ID References in S5-9 Story File

**Status:** in-progress
**Dev:** Dev 3
**Sprint:** Sprint 5
**Branch:** `sprint5/s5-9-book-context-processing-ux` (applied directly to PR #244)

---

## Story

As a developer reviewing PR #244, I need every cross-reference to DEFECT-REGISTER.md
IDs in the S5-9 story file to use the correct post-renumbering IDs (D174–D178), so
that the register remains internally consistent after merge and reviewers can trace
findings to the correct register entries.

## Background

Story 5-11 renumbered 6 colliding DEFECT-REGISTER entries (D154–D158, D167 →
D174–D179) and updated two cross-reference sites:
1. `docs/DEFECT-REGISTER.md` heading entries — ✅ updated
2. `docs/stories/S5-1-book-context-form.md` F12 line — ✅ updated

A third cross-reference site was missed: `docs/stories/5-9-book-context-processing-ux.md`
contains 4 occurrences of the pre-renumbering IDs (D154–D158), discovered by Dev 2 in
their re-review of PR #244. Dev 2 reported "3 stale references" but the full grep
against the file reveals 4:

| Line | Old text |
|------|----------|
| 75   | `D154 (PII in Langfuse), D155 (missing TestClient tests), D156 (branch stacking), D157 (no rate limit on upsert), D158 (no DB CHECK constraints)` |
| 133  | `D154–D158` |
| 146  | `D154 (PII Langfuse), D155 (missing TestClient tests), D156 (branch stacking process note), D157 (rate limiting), D158 (DB CHECK constraints)` |
| 161  | `D154–D158` |

No Supabase migration is required — this is a documentation-only fix.

---

## Acceptance Criteria

### AC1 — All 4 stale references updated in `docs/stories/5-9-book-context-processing-ux.md`

After fix:
- `grep "D15[4-8]" docs/stories/5-9-book-context-processing-ux.md` → zero matches
- Lines 75, 133, 146, 161 all reference D174–D178 (or the appropriate individual IDs)

### AC2 — New IDs are correct and internally consistent

The replacements follow the mapping established in Story 5-11:
- D154 → D174, D155 → D175, D156 → D176, D157 → D177, D158 → D178

After fix:
- Every occurrence of `D174`–`D178` in the S5-9 story matches the corresponding
  DEFECT-REGISTER.md heading descriptions (Langfuse DPDP, TestClient tests, branch
  stacking, rate limiting, DB CHECK constraints — same order, same label text)

### AC3 — No new stale references introduced elsewhere

After fix:
- `grep -r "D15[4-8]" docs/stories/` → zero matches across ALL story files
  (S5-1 was already fixed in 5-11; this closes the last remaining gap)

### AC4 — No Supabase migration needed

This is a documentation-only change. No migration, no DB schema change, no MCP call.
The Supabase MCP is confirmed not applicable.

---

## Scale & Load

1. **Unit of work:** One markdown file, 4 text substitutions. N/A for scale.
2. **Fixed budgets:** N/A — documentation-only.
3. **Scope:** Per-repository document. N/A.
4. **Unbounded reads/writes:** N/A.
5. **Inherited caps:** N/A.
6. **Check-then-act:** N/A — no DB or concurrent state.

---

## Tasks

- [x] T1: Create story file and commit story-first
- [ ] T2: Replace all 4 stale references in `docs/stories/5-9-book-context-processing-ux.md`
- [ ] T3: Verify `grep "D15[4-8]" docs/stories/` → zero matches across all story files
- [ ] T4: Commit, push to PR #244, add PR comment

---

## Dev Agent Record

### Change Log
| Date | Change |
|------|--------|
| 2026-09-23 | Story created — 4 stale D154-D158 references found in S5-9 story, missed during S5-11 renumbering pass |
