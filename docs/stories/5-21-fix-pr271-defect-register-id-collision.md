# Story 5-21 — Fix DEFECT-REGISTER ID Collision (PR #271 Review Finding)

**Sprint:** 5
**Owner:** Dev 3
**Branch:** sprint5/s5-19-fix-pr267-review-findings (continuing on existing PR #271 branch)
**Created:** 2026-10-08
**Status:** In Progress

---

## Context

Developer-2-max's re-check of PR #271 (commits 8c02220, 413704f) found that Story 5-20's
"bonus" D200/D201 collision fix would silently corrupt main if merged as-is:

1. **Story 5-20's audit banner was wrong.** It claimed `D200 = CaptionOverlay karaoke dead-zone`
   and `D201 = lesson_planner segments_out sort` — but those entries are at **D166** and **D168**
   on main (moved there by Story 5-13, commits 0cbf96a/5049c77). The branch never picked up
   those moves because the Oct 1 merge (`a1157fd`) resolved the DEFECT-REGISTER conflict by
   keeping this branch's stale content rather than main's corrected IDs.

2. **D214/D215 are wrong.** Story 5-20 renamed PR #270's slide_generator entries from D200→D214
   and D201→D215 — but D200/D201 are the CORRECT IDs for those slide_generator entries on main
   (confirmed: `origin/main` has D200/D201 as slide_generator table rows at max after PR #270
   merged to main). D214/D215 are redundant, shadow the slide_generator content, and would
   land as a second copy on merge.

3. **Stale D200/D201 rows on this branch would overwrite main's slide_generator entries.**
   When this branch merges into main, git sees D200=CaptionOverlay on this branch as the "new"
   content and overwrites main's D200=slide_generator silently (no conflict — git merges at
   line level and the surrounding context differs enough that neither side detects the collision).

4. **Pre-existing main duplicates (independent of this PR, per reviewer):** D166 appears twice
   on main (CaptionOverlay + `scripts/dna_profile_quality_check.py` .limit(500) issue) and D168
   appears twice (lesson_planner segments_out + `SixtyDbTTSProvider.COST_PER_CHAR` placeholder).
   These predate PR #271 and are not its fault, but must be resolved so the guard test passes
   after the merge.

---

## Acceptance Criteria

### AC1 — Stale D200/D201 rows removed from this branch
`docs/DEFECT-REGISTER.md` must NOT contain table rows for:
- D200 = CaptionOverlay karaoke dead-zone (this belongs at D166, as on main)
- D201 = lesson_planner segments_out sort (this belongs at D168, as on main)

After the merge with main, D200 = slide_generator single-call token-budget risk and
D201 = slide_generator cache-hit truncations — exactly what main already has.

### AC2 — D214 and D215 removed
`docs/DEFECT-REGISTER.md` must NOT contain table rows for D214 or D215. These were wrong
renaming artifacts from Story 5-20. The slide_generator entries are correctly at D200/D201.

### AC3 — Sixth-occurrence audit banner corrected
The "⚠️ ID COLLISION, sixth occurrence, 2026-10-02" banner in `docs/DEFECT-REGISTER.md` must
be updated to accurately describe what happened:
- The collision was NOT D200=CaptionOverlay vs. slide_generator — CaptionOverlay is D166
- Story 5-20's attempt to fix it was itself wrong (renaming D200→D214, D201→D215)
- Story 5-21 is the actual fix: re-deriving the correct IDs against today's main

### AC4 — Pre-existing D166/D168 duplicates renumbered
After merging main, the second occurrences of D166 and D168 (pre-existing duplicates on main
that predate this PR) must be given new unique IDs:
- Second D166 (`scripts/dna_profile_quality_check.py` .limit(500) — D166 duplicate) → **D216**
- Second D168 (`SixtyDbTTSProvider.COST_PER_CHAR` — D168 duplicate) → **D217**

### AC5 — `slide-bullets-complete-sentences.md` references D200/D201 (not D214/D215)
`docs/stories/slide-bullets-complete-sentences.md` must reference D200 and D201 for the
slide_generator findings — matching main's assignment. If this branch's version references
D214/D215 (Story 5-20's wrong renaming), restore to D200/D201.

### AC6 — Guard test clean
`tests/unit/test_defect_register_no_duplicate_ids.py` must pass (3/3) against the branch tip.
No duplicate D-IDs anywhere in DEFECT-REGISTER.md after the merge and cleanup.

### AC7 — ruff and CI advisory checks
All modified Python files pass `ruff check` and `ruff format --check`. The branch must be
safe to merge into main (no guard-test regressions, no duplicate IDs).

---

## Scale & Load

1. **One unit of work:** Document-only edits to DEFECT-REGISTER.md, story file, and one
   related story reference file. No runtime code paths modified.
2. **Fixed budgets vs variable input:** N/A — no runtime budget changes introduced.
3. **Scope of every limit:** N/A — test and documentation changes only.
4. **Unbounded reads/writes:** None — this story adds no DB queries or LLM calls.
5. **Inherited caps re-derived:** N/A — no caps changed.
6. **Check-then-act concurrency:** N/A — documentation changes only.

---

## Implementation Notes

- Continue on `sprint5/s5-19-fix-pr267-review-findings` — this is a direct continuation of
  fixing PR #271 review findings; creating a new branch would require a new PR.
- Sequence: story file commit first → merge origin/main → resolve DEFECT-REGISTER conflicts
  (take main's D200/D201) → remove stale D200/D201 rows → remove D214/D215 → renumber second
  D166→D216 and second D168→D217 → fix audit banner → update story file.
- `test_defect_register_no_duplicate_ids.py` is the authoritative guard. Run it after every
  edit. A clean 3/3 confirms no duplicate IDs remain.
- The `slide-bullets-complete-sentences.md` story file change is a revert of Story 5-20's
  wrong D214/D215 references back to the correct D200/D201.
