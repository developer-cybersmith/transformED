---
id: "249"
title: "Wire book_context and chapter_context into slide_generator_node and narration_generator_node"
status: "in-progress"
sprint: null
story_points: 5
baseline_commit: "60eefc22"
owner: Dev1
priority: P2
blocker_ref: "GitHub issue #249 — no formal blockers"
---

# Story 249 — Context Wiring (book_context + chapter_context parity)

## Context & Scope Boundary

**Why this story exists:** two real, already-shipped onboarding forms collect real personalization
data from students — the book-level form (`BookContextForm.tsx`, 10 questions: purpose, deadline,
feared section, etc.) and the chapter-level form (`ChapterContextForm.tsx`, 5 questions: depth
wanted, named doubt, what to skip, prerequisites). Verified by reading every relevant code path
line-by-line (issue #249's own body — not inferred from the forms' existence alone):

| Node | `book_context` | `chapter_context` |
|---|---|---|
| `lesson_planner_node` | ✅ | ✅ |
| `slide_generator_node` | ✅ | ❌ |
| `narration_generator_node` | ✅ | ❌ |
| 5 Phase-1 economy nodes (quiz, complexity, jargon, interventions, summarise) | ❌ (always `""` — they run before the fetch) | ❌ |

`chapter_context` reaches only 1 of 8 content-generating nodes today, versus `book_context`'s 3 of
8 — not because anyone decided that, but because `chapter_context` has no `PipelineState` field to
travel through (it's fetched fresh inside `lesson_planner_node`, used once, discarded), while
`book_context` was deliberately given a state field specifically so it could reach `slide_generator`
and `narration_generator` too.

**What this story does:**
1. Give `chapter_context` a real `PipelineState` slot (`chapter_context: str` +
   `chapter_context_truncated: bool`), mirroring `book_context`'s existing pair.
2. Give `chapter_context` the same explicit-degradation truncation guard `book_context` already has
   (`merge_book_context()`'s 2,000-char budget + surfaced truncation flag) — today it's raw string
   concatenation (`graph.py:1638`, `+ chapter_context`) with no budget and no surfaced flag at all.
   Re-derives the cap honestly for `chapter_context`'s own (smaller) field set rather than reusing
   `book_context`'s 2,000 unchanged — see Scale & Load Q5.
3. Wire `chapter_context` into `slide_generator_node`'s prompt, alongside the existing
   `book_context` merge.
4. Wire `chapter_context` into `narration_generator_node`'s prompt, alongside the existing
   `book_context` merge — requires adding `chapter_context` to `_FAN_OUT_STATE_KEYS`, the same route
   `book_context` already uses to reach narration's post-planner `Send()` fan-out.

**What this story explicitly does NOT do:**
- Does **not** wire `book_context`/`chapter_context` into the 5 Phase-1 economy nodes (quiz,
  complexity, jargon, interventions, summarise). They run *before* `lesson_planner_node` ever
  fetches either context, so reaching them requires moving the fetch earlier in the pipeline — a
  real structural change (a new dedicated fetch step, or folding it into an existing early node),
  not a wiring fix. Judged not worth the risk/complexity for this piece: it is unclear either form
  meaningfully improves quiz/jargon/complexity/intervention quality, unlike slides and narration
  which plainly benefit from knowing the student's named doubt or feared topic. **Registered as a
  new Defect Register entry** (Task 3.1) rather than silently decided either way, per issue #249's
  own explicit instruction not to silently skip this question.
- Does **not** build the 30-question personal-profile onboarding form, or wire the existing,
  unrelated `onboarding_responses`/`OnboardingFlow.tsx` signup data into any prompt — that belongs
  to issue #231. Not depended on by this story.
- Does **not** touch the fixed 7/10/10-slide structure, split-screen slide schema, live
  Penta-Intelligence Q&A scoring, or the Scheduler agent — all issue #233 piece 4 / other pieces.
- Does **not** touch `feature/233-topic-selection-step`, `topic_selection_node`, or `TIER_TOPIC_COUNT`
  — independent branch, independent code paths, no overlap.
- Does **not** modify the frozen `packages/shared` contracts.

## Story

**As** the content pipeline,
**I want** the chapter-level onboarding form's answers to reach `slide_generator_node` and
`narration_generator_node`, with the same explicit-degradation safety net `book_context` already
has,
**so that** a student's named doubt, skip-list, and desired depth actually shape the slides and
narration they receive — not just the lesson outline — matching what already works for the
book-level form.

## Acceptance Criteria

### Functional

- [ ] **AC 1.** `PipelineState` (`graph.py`) gains `chapter_context: str` and
  `chapter_context_truncated: bool` fields, matching `book_context`'s existing pair exactly in
  shape and convention.
- [ ] **AC 2.** `lesson_planner_node` returns `chapter_context` (the raw fetched block, pre-merge)
  in its state dict on both the cache-hit and fresh-computation paths, matching how it already
  returns `book_context` today.
- [ ] **AC 3.** `prompt_context.py` gains a `merge_chapter_context()` function with the same
  contract as `merge_book_context()` (last-newline-safe truncation, explicit `was_truncated`
  return, a distinct `_TRUNCATION_MARKER` string so the two truncation events are distinguishable
  in a prompt) — implemented via a shared private helper so the two public functions don't
  duplicate the truncation algorithm (CLAUDE.md binding rule 6).
- [ ] **AC 4.** `_CHAPTER_CONTEXT_MAX_CHARS` is derived from the real field set (2 free-text fields
  × 500 chars + MCQ/bool labels + the `[Chapter Instructions]` header — worked arithmetic in the
  constant's own comment, not copied from `book_context`'s 2,000), landing at **1,300**.
- [ ] **AC 5.** `lesson_planner_node`'s existing raw `+ chapter_context` string concatenation
  (`graph.py:1638`) is replaced with a call to `merge_chapter_context()`, so it gets the same
  explicit-degradation guarantee `book_context` already has at that exact call site.
- [ ] **AC 6.** `slide_generator_node` reads `state.get("chapter_context")` and merges it into its
  system prompt via `merge_chapter_context()`, alongside its existing `book_context` merge.
- [ ] **AC 7.** `chapter_context` is added to `_FAN_OUT_STATE_KEYS` so `narration_generator_node`
  (Send()-dispatched post-planner) receives it; `narration_generator_node` merges it into its
  system prompt via `merge_chapter_context()`, alongside its existing `book_context` merge.
- [ ] **AC 8.** `chapter_context_truncated` is set and surfaced the same way
  `book_context_truncated` already is (written into state on truncation, read into the admin-visible
  `duration_report`/checkpoint record where `book_context_truncated` already appears).
- [ ] **AC 9.** The 5 Phase-1 economy nodes remain unchanged — confirmed by an explicit test that
  none of them reference `chapter_context` or `book_context` in their prompt-building code (a
  regression guard, not new behavior).
- [ ] **AC 10.** A new Defect Register entry documents the Phase-1-node question (deferred, not
  silently decided) — names exactly which 5 nodes are affected, why moving the fetch earlier was
  judged out of scope for this piece, and what a real fix would require.

## Scale & Load

*(`docs/SCALE-CONTRACT.md` — six questions, contract-mandated on every story)*

1. **Unit of work, and its range.** One unit is one `chapter_context` merge into one node's system
   prompt — happens at most 3 times per lesson-generation run (lesson_planner, slide_generator,
   narration_generator's Send() dispatch reads the same string once per dispatched segment, but the
   merge computation itself is cheap string work, not a new fetch — only fetched once, inside
   `lesson_planner_node`, exactly as `book_context` already is). Input range: 0 chars (no chapter
   form saved — the common case today, since the form is optional) to `_CHAPTER_CONTEXT_MAX_CHARS`
   (1,300) by construction, since `_format_chapter_context_block` itself is built from
   Pydantic-capped fields (500 chars × 2, both enforced at the API boundary — `schemas.py:41,43`)
   — the only way to exceed 1,300 is a future change to those caps without revisiting this one
   (exactly the re-derivation trap Q5 below exists to name).
2. **Fixed budgets vs. variable input.** `_CHAPTER_CONTEXT_MAX_CHARS` (1,300) is the fixed budget;
   `chapter_context`'s formatted length is the variable input. Past the budget: explicit,
   surfaced degradation — `chapter_context_truncated=True`, persisted the same way
   `book_context_truncated` already is, never a silent cut. In practice unreachable today (Q1), but
   the guard exists so it degrades loudly the day the input caps change, not silently.
3. **Scope of every limit.** Per-lesson-generation-run, keyed by `lesson_id` — `chapter_context` is
   fetched once per run from the `chapter_context` table (already keyed by `(chapter_id, user_id)`,
   unchanged by this story) and carried in that run's own `PipelineState`; no cross-lesson or
   cross-user sharing, identical scope to `book_context` today.
4. **Unbounded reads/writes.** None introduced. The one new read this story adds anywhere
   (`get_chapter_context_prompt_block`, called from `lesson_planner_node`) already exists today —
   this story does not add a new fetch, only a new *destination* (`PipelineState`) for the fetch's
   existing result and two new *consumers* of that value.
5. **Inherited caps re-derived?** Yes — this is the substantive part of this story's Scale & Load
   answer. `book_context`'s 2,000-char cap was derived for `book_context`'s OWN field set (3
   free-text fields × 500 + labels ≈ 1,948). Reusing 2,000 unchanged for `chapter_context` (2
   free-text fields × 500 + labels ≈ 1,219) would be exactly the un-re-derived-inherited-cap
   pattern CLAUDE.md's own binding rule warns about — a looser cap than the actual worst case
   requires, "borrowed" from a different field set instead of computed for this one. `merge_chapter_context()`
   gets its own constant, `_CHAPTER_CONTEXT_MAX_CHARS = 1_300`, with the arithmetic in its own
   comment (matching `_BOOK_CONTEXT_MAX_CHARS`'s own convention).
6. **Check-then-act under concurrency.** No new check-then-act sequence. `chapter_context` is
   fetched once (read-only) inside `lesson_planner_node`, which is a single sequential node — same
   concurrency shape `book_context`'s existing fetch already has there. No new writes to
   `chapter_context`/`book_context` tables from this story (those are owned by the existing
   `context.py`/`context_chapter.py` upsert endpoints, untouched here).

**The one-line test, answered:** before this fix, a student who filled in "I'm stuck on this
concept, skip the historical background" on the chapter form got that acknowledged in the lesson
*outline* but never saw it reflected in the actual *slides* or *narration* they watched — a
personalization feature that silently only half-worked, with nothing that would tell you it was
incomplete. After this fix, it reaches both; the one thing that still doesn't see it (the 5
Phase-1 nodes) is named explicitly in the Defect Register (AC 10), not silently absent.

## Tasks

### Task 1 — Guard-test survey (already done, listed here)
- [x] 1.1 `grep -rln "test_.*graph\|test_no_hardcoded\|test_dunder_all\|test_node_return_shape\|test_unbounded_queries" apps/api/tests/`
  narrowed to what this story touches:
  - `test_node_return_shape.py` — repo-wide guard; `lesson_planner_node`/`slide_generator_node`/
    `narration_generator_node`'s return dicts are being extended with a new key, must stay
    narrow (no `**state` spread introduced).
  - `test_s5_1_book_context.py` — direct coverage of `merge_book_context`/`book_context` wiring,
    the pattern this story mirrors; must stay green, and its own conventions are the model for
    this story's new tests.
  - `test_s5_3_chapter_context.py`, `test_chapter_context_exceptions_premise.py` — direct
    coverage of the existing `chapter_context` fetch/format path (`context_chapter.py`), untouched
    by this story but must stay green (this story only changes what *consumes* the already-tested
    formatted block, not how it's built).
  - `test_phase1_economy_nodes.py` — covers `_FAN_OUT_STATE_KEYS` and the Phase-1 dispatch shape;
    relevant since `chapter_context` is being added to `_FAN_OUT_STATE_KEYS` (AC 7). AC 9's
    regression guard belongs alongside this file's existing Phase-1 tests.
  - `test_howto_pipeline_e2e.py` — real-graph integration test; must confirm it still passes with
    the new fan-out key and merged prompts (no fake-provider updates expected, since neither
    `merge_book_context` nor `merge_chapter_context` involve an LLM call).

### Task 2 — RED
- [ ] 2.1 Write tests against the desired `merge_chapter_context`/wiring behavior; confirm they
  fail against the current (pre-fix) code.

### Task 3 — GREEN: prompt_context.py + PipelineState
- [ ] 3.1 Add the new Defect Register entry for the deferred Phase-1-node question (AC 10) —
  do this before implementation, since it's a scope decision, not a code change.
- [ ] 3.2 Add `chapter_context`/`chapter_context_truncated` to `PipelineState` (AC 1).
- [ ] 3.3 Refactor `prompt_context.py`: extract the shared truncation algorithm, add
  `merge_chapter_context()` with `_CHAPTER_CONTEXT_MAX_CHARS = 1_300` (AC 3, AC 4).

### Task 4 — GREEN: graph wiring
- [ ] 4.1 `lesson_planner_node`: return `chapter_context` in state (AC 2); replace the raw
  concatenation with `merge_chapter_context()` (AC 5).
- [ ] 4.2 `slide_generator_node`: read + merge `chapter_context` (AC 6).
- [ ] 4.3 Add `chapter_context` to `_FAN_OUT_STATE_KEYS`; `narration_generator_node`: read + merge
  `chapter_context` (AC 7).
- [ ] 4.4 Surface `chapter_context_truncated` the same way `book_context_truncated` already is
  (AC 8).

### Task 5 — GREEN: tests
- [ ] 5.1 New tests for `merge_chapter_context` (mirroring `test_s5_1_book_context.py`'s own
  `merge_book_context` tests: under-budget no-op, over-budget truncates at a newline boundary,
  no-newline-in-budget hard-cut fallback, empty-input no-op).
- [ ] 5.2 New tests proving `chapter_context` text actually appears in `slide_generator_node`'s and
  `narration_generator_node`'s constructed prompts (mirroring how Story 233's review added a
  bounded-prompt-content test — assert on the real prompt string, not just that a mock was called).
- [ ] 5.3 Regression guard (AC 9): the 5 Phase-1 economy nodes' prompt-building code contains
  neither `chapter_context` nor `book_context`.
- [ ] 5.4 Full regression run, ruff/format/mypy.

### Task 6 — Review
- [ ] 6.1 Parallel adversarial agent review (all 6 CLAUDE.md layers).

### Task 7 — Commit
- [ ] 7.1 Story-first commit (this file alone).
- [ ] 7.2 Implementation commit(s).
- [ ] 7.3 `docs/dev1-tracker.md` entry referencing #249.

## Dev Agent Record

### Implementation Plan
Derived directly from GitHub issue #249's own "Scope — pinpoint fixes" section (re-verified
against current `main` at `60eefc22` before writing this story — zero drift from when the issue
was filed, since `feature/233-topic-selection-step` has not yet merged and touches none of these
files).

### Debug Log
_(filled in during implementation)_

### Completion Notes
_(filled in during implementation)_

### File List
_(filled in during implementation)_

### Change Log
- 2026-09-25: Story file created (story-first commit), branch `feature/249-context-wiring`, based
  on `main` at `60eefc22`.
