---
id: "3-36"
title: "package_builder Defensive Fixes — D32 fix, D33 register correction"
status: "ready-for-dev"
sprint: 3
story_points: 2
baseline_commit: ""
owner: Dev1
priority: P2
blocker_ref: "D32, D33"
---

# Story 3-36 — package_builder Defensive Fixes (D32 + D33)

## Context & Scope Boundary

**Why this story exists:** two register entries bundled together because both live in
`package_builder_node` — the **last** pipeline node, after 100% of a lesson's LLM/TTS/image
spend — and both are about a malformed upstream entry crashing that node instead of degrading.

**What was found during story prep, before writing a line of code — and why it changes this
story's scope:**

- **D32 is real and unfixed.** `_group_by_segment_id` (currently `graph.py:4049-4068`, moved
  from the register's cited `:3856` — same line-drift class the register already warns about
  for D31/ci.yml) does a raw `item["data"]` subscript at line 4067, and does not check
  `isinstance(item, dict)` before calling `.get()` at line 4057 either. Its docstring claims
  *"Same defensive-skip philosophy as `_index_by_segment_id`"* — that sibling function (fixed in
  Story 2-31) really does check both; `_group_by_segment_id` checks neither. One malformed
  `slides`/`quiz_questions`/`glossary` entry crashes the node. No test exists for this today —
  confirmed by grep, zero hits for `_group_by_segment_id` or a malformed-entry scenario in
  `tests/unit/test_package_builder_node.py`.
- **D33 is already fixed — verified by `git blame`, not assumed.** The register describes
  `book_id`/`chapter_id` defaulting to `""` against `UUID`-typed fields as still open. Reading
  the current code (`graph.py:3930-3953`) shows explicit `RuntimeError`s naming exactly what's
  missing and why, with a comment literally reading `# D33 (AC7): no "" default...`. `git blame`
  traces this to commit `1c4360b1`, 2026-08-04, Story 1-13 ("chapter-scoped generation — Phase 5
  Implemented") — landed over a week before this story started. Three tests already cover it
  by name: `test_missing_chapter_id_raises_diagnostic_not_model_validate_failure`,
  `test_missing_book_id_raises_diagnostic_not_model_validate_failure`,
  `test_chunk_present_but_missing_chapter_id_key_behaves_like_chunk_absent`.

  **This is the inverse of the mistake Story 3-35 caught in itself** (a task marked done in a
  story before the underlying edit existed). Here the code and tests are real and have been for
  a week; only `docs/DEFECT-REGISTER.md` never got the closing edit. Re-implementing D33 would
  violate "don't reinvent what exists" for no reason — the correct action is closing the
  register entry to match reality, with a pointer to the commit and the tests that already
  prove it, not new code.

**What this story does:**
1. Fix D32 for real — harden `_group_by_segment_id` to match its own docstring's claim.
2. Close D33 in `docs/DEFECT-REGISTER.md`, pointing at commit `1c4360b1` and the three existing
   tests, instead of writing new code for something already shipped.

**What this story does NOT do:**
- Does not touch `_index_by_segment_id` (already correct, Story 2-31).
- Does not add new UUID validation beyond what commit `1c4360b1` already shipped for D33.
- Does not change `_group_by_segment_id`'s callers (`slides_by_segment`, `quiz_by_segment`,
  `jargon_by_segment` at `graph.py:4070-4072`) — the fix is inside the shared helper, so all
  three callers get it for free, matching how `_index_by_segment_id`'s Story 2-31 fix covered
  all of *its* four callers without touching any of them individually.

## Story

**As** the content pipeline,
**I want** `_group_by_segment_id` to skip a malformed `slides`/`quiz_questions`/`glossary` entry
the same way `_index_by_segment_id` already skips a malformed `complexity_scores`/`audio_assets`
entry,
**so that** one bad item degrades a single segment instead of crashing `package_builder_node`
after every LLM/TTS/image call in the lesson has already been billed.

## Acceptance Criteria

### Functional

- [ ] **AC 1.** `_group_by_segment_id` checks `isinstance(item, dict)` before calling `.get()`,
  mirroring `_index_by_segment_id`'s existing check (`graph.py:3977-3985`). A non-dict item
  (e.g. a bare string) is logged and skipped, not a crash. (D32)
- [ ] **AC 2.** `_group_by_segment_id` reads `item.get("data")` instead of the raw `item["data"]`
  subscript. A dict item missing the `"data"` key is logged and skipped, not a `KeyError`. (D32)
- [ ] **AC 3.** A `"data"` value that is present but not itself a dict (e.g. a string) is logged
  and skipped, mirroring `_index_by_segment_id`'s value-type check (`graph.py:4015-4027`). (D32)
- [ ] **AC 4.** All three of `_group_by_segment_id`'s callers (`slides_by_segment`,
  `quiz_by_segment`, `jargon_by_segment`) inherit the fix with zero changes to their own call
  sites — the fix is entirely inside the shared helper.
- [ ] **AC 5.** `docs/DEFECT-REGISTER.md`'s D33 entry is closed, referencing commit `1c4360b1`
  and the three existing tests that already prove it, with an explicit note that the fix
  predates this story and this entry corrects a register/reality mismatch, not new work.

### Non-functional / regression-guard

- [ ] **AC 6.** New tests in `apps/api/tests/unit/test_package_builder_node.py` reproduce all
  three D32 failure modes (non-dict item, missing `"data"` key, non-dict `"data"` value) against
  `slides` — RED-confirmed against pre-fix code (each must actually crash the node with a real
  `AttributeError` or `KeyError` before the fix lands), GREEN after.
- [ ] **AC 7.** No behavior change to any currently-passing test in
  `test_package_builder_node.py` — re-run the full file unmodified, confirm still green,
  including `test_segment_with_zero_slides_is_skipped` (a segment whose only slide gets
  skipped by the new defensive check must still be dropped from the final package the same way
  a segment with zero slides already is — same downstream behavior, new upstream cause).

## Scale & Load

*(`docs/SCALE-CONTRACT.md` — six questions, contract-mandated on every story)*

1. **Unit of work, and its range.** One unit is one upstream node's output list for one lesson
   (`slides`/`quiz_questions`/`glossary`), fed into `_group_by_segment_id` once per
   `package_builder_node` run. Range: 4–12 segments measured per lesson (per
   `docs/handoffs/lesson-delivery-dev1.md`), with 1+ slide/quiz/glossary entries per segment —
   no fixed count; this fix does not change the range, only what happens to one malformed
   entry within it.
2. **Fixed budget vs. variable input.** N/A — this fix removes a *crash* on malformed input, it
   does not introduce a new budget/cap. The change is a degrade path (skip + log), not a limit.
3. **Scope of every limit.** N/A — no limit is introduced or changed.
4. **Unbounded reads/writes.** None introduced. The fix is a pure in-memory loop over an
   already-fetched list; no new Supabase calls.
5. **Inherited caps re-derived?** N/A — no caps involved.
6. **Check-then-act under concurrency.** N/A — `package_builder_node` runs once per lesson
   generation job; this fix touches no shared/concurrent state.

**Why five of six are N/A, stated plainly:** this is a pure defensive-coding fix inside a single
node's in-memory helper function — it has no request-path budget, scope, or concurrency
dimension. The one place the Scale Contract's spirit actually applies is the failure mode
itself: **before this fix, a malformed entry produced a loud crash (an `AttributeError`/
`KeyError`), which is the *opposite* of the Contract's Q2 failure signature (silent wrong
answers)** — this fix keeps it loud where a crash is correct (nothing recoverable to build from)
and converts it to a **logged, explicit degradation** exactly where `_index_by_segment_id`'s
precedent already established that's the right choice (one bad item shouldn't sink the whole
lesson after full spend).

## Tasks

### Task 1 — D32: harden `_group_by_segment_id`
- [ ] 1.1 Add `isinstance(item, dict)` check (AC 1)
- [ ] 1.2 Replace `item["data"]` with `.get("data")` (AC 2)
- [ ] 1.3 Add non-dict `"data"` value check (AC 3)
- [ ] 1.4 Write RED tests for all three failure modes (AC 6)
- [ ] 1.5 Re-run full `test_package_builder_node.py`, confirm unmodified tests still green
  (AC 7)

### Task 2 — D33: register correction (no new code)
- [ ] 2.1 Verify via `git blame` that D33's fix and tests already exist (done in story prep,
  recorded above)
- [ ] 2.2 Close D33 in `docs/DEFECT-REGISTER.md`, pointing at commit `1c4360b1` and the 3
  existing tests (AC 5)

### Task 3 — Tracker + dashboard
- [ ] 3.1 Update `docs/dev1-tracker.md` (header date + narrative entry, matching the
  established Story 2-31/2-32/3-35 convention — this bundled story isn't one of the tracker's
  60 enumerated tasks, so the Quick Status Dashboard is not touched, same reasoning as 3-35)

### Task 4 — Review
- [ ] 4.1 6-layer adversarial review

### Task 5 — Commit + push
- [ ] 5.1 Final commit on `sprint3/s3-36-package-builder-defensive-fixes`
- [ ] 5.2 Push to remote

## Dev Agent Record

### Implementation Plan
*(populated during implementation)*

### Debug Log
*(populated during implementation)*

### Completion Notes
*(populated during implementation)*

### File List
*(populated during implementation)*

### Change Log

- 2026-08-11: Story file created (story-first commit, branch
  `sprint3/s3-36-package-builder-defensive-fixes`). D33 scope corrected during prep — verified
  already fixed (commit `1c4360b1`) before writing any AC assuming otherwise.
