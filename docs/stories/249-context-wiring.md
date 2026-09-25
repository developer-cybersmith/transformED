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

- [x] **AC 1.** `PipelineState` (`graph.py`) gains `chapter_context: str` and
  `chapter_context_truncated: bool` fields, matching `book_context`'s existing pair exactly in
  shape and convention.
- [x] **AC 2.** `lesson_planner_node` returns `chapter_context` (the raw fetched block, pre-merge)
  in its state dict on both the cache-hit and fresh-computation paths, matching how it already
  returns `book_context` today.
- [x] **AC 3.** `prompt_context.py` gains a `merge_chapter_context()` function with the same
  contract as `merge_book_context()` (last-newline-safe truncation, explicit `was_truncated`
  return, a distinct `_TRUNCATION_MARKER` string so the two truncation events are distinguishable
  in a prompt) — implemented via a shared private helper so the two public functions don't
  duplicate the truncation algorithm (CLAUDE.md binding rule 6).
- [x] **AC 4.** `_CHAPTER_CONTEXT_MAX_CHARS` is derived from the real field set (2 free-text fields
  × 500 chars + MCQ/bool labels + the `[Chapter Instructions]` header — worked arithmetic in the
  constant's own comment, not copied from `book_context`'s 2,000), landing at **1,300**.
- [x] **AC 5.** `lesson_planner_node`'s existing raw `+ chapter_context` string concatenation
  (`graph.py:1638`) is replaced with a call to `merge_chapter_context()`, so it gets the same
  explicit-degradation guarantee `book_context` already has at that exact call site.
- [x] **AC 6.** `slide_generator_node` reads `state.get("chapter_context")` and merges it into its
  system prompt via `merge_chapter_context()`, alongside its existing `book_context` merge.
- [x] **AC 7.** `chapter_context` is added to `_FAN_OUT_STATE_KEYS` so `narration_generator_node`
  (Send()-dispatched post-planner) receives it; `narration_generator_node` merges it into its
  system prompt via `merge_chapter_context()`, alongside its existing `book_context` merge.
- [x] **AC 8.** `chapter_context_truncated` is set and surfaced the same way
  `book_context_truncated` already is (written into state on truncation, read into the admin-visible
  `duration_report`/checkpoint record where `book_context_truncated` already appears).
- [x] **AC 9.** The 5 Phase-1 economy nodes remain unchanged — confirmed by an explicit test that
  none of them reference `chapter_context` or `book_context` in their prompt-building code (a
  regression guard, not new behavior).
- [x] **AC 10.** A new Defect Register entry documents the Phase-1-node question (deferred, not
  silently decided) — names exactly which 5 nodes are affected, why moving the fetch earlier was
  judged out of scope for this piece, and what a real fix would require.
- [x] **AC 11.** (Added Round 2 review — CLAUDE.md binding rule: "a story that touches any pipeline
  node file is incomplete if it does not name that module's guard tests as an AC.") Existing guard
  tests for `graph.py` pass: `apps/api/tests/unit/test_node_return_shape.py` (this story adds
  return-dict keys to `lesson_planner_node`/`slide_generator_node`, exactly what that guard exists
  to catch a violation of). Verified green throughout, see Completion Notes.

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
   **(Added Round 2 review — combined-budget question.)** `book_context` (2,000 cap) and
   `chapter_context` (1,300 cap) are now both merged into the SAME prompt at two of the three call
   sites (`slide_generator_node`, `narration_generator_node`), each enforcing its own budget
   independently — no combined/total ceiling across the two was ever stated. Worst case both maxed
   simultaneously: 3,300 chars ≈ ~825 tokens, against GPT-4o/GPT-4o-mini's 128k-token context
   window (≈0.6%) — nowhere near a real ceiling today, so not worth a third combined-budget
   constant. Named explicitly here rather than left unanswered, per the Scale Contract's own
   "N/A is valid only with a reason" rule — the reason is the 200x-plus headroom, not that the
   question doesn't apply.
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
- [x] 2.1 Write tests against the desired `merge_chapter_context`/wiring behavior; confirm they
  fail against the current (pre-fix) code.

### Task 3 — GREEN: prompt_context.py + PipelineState
- [x] 3.1 Add the new Defect Register entry for the deferred Phase-1-node question (AC 10) —
  do this before implementation, since it's a scope decision, not a code change.
- [x] 3.2 Add `chapter_context`/`chapter_context_truncated` to `PipelineState` (AC 1).
- [x] 3.3 Refactor `prompt_context.py`: extract the shared truncation algorithm, add
  `merge_chapter_context()` with `_CHAPTER_CONTEXT_MAX_CHARS = 1_300` (AC 3, AC 4).

### Task 4 — GREEN: graph wiring
- [x] 4.1 `lesson_planner_node`: return `chapter_context` in state (AC 2); replace the raw
  concatenation with `merge_chapter_context()` (AC 5).
- [x] 4.2 `slide_generator_node`: read + merge `chapter_context` (AC 6).
- [x] 4.3 Add `chapter_context` to `_FAN_OUT_STATE_KEYS`; `narration_generator_node`: read + merge
  `chapter_context` (AC 7).
- [x] 4.4 Surface `chapter_context_truncated` the same way `book_context_truncated` already is
  (AC 8).

### Task 5 — GREEN: tests
- [x] 5.1 New tests for `merge_chapter_context` (mirroring `test_s5_1_book_context.py`'s own
  `merge_book_context` tests: under-budget no-op, over-budget truncates at a newline boundary,
  no-newline-in-budget hard-cut fallback, empty-input no-op).
- [x] 5.2 New tests proving `chapter_context` text actually appears in `slide_generator_node`'s and
  `narration_generator_node`'s constructed prompts (mirroring how Story 233's review added a
  bounded-prompt-content test — assert on the real prompt string, not just that a mock was called).
- [x] 5.3 Regression guard (AC 9): the 5 Phase-1 economy nodes' prompt-building code contains
  neither `chapter_context` nor `book_context`.
- [x] 5.4 Full regression run, ruff/format/mypy.

### Task 6 — Review
- [ ] 6.1 Parallel adversarial agent review (all 6 CLAUDE.md layers).

### Task 7 — Commit
- [x] 7.1 Story-first commit (this file alone) — `1b60c46c`, pushed.
- [ ] 7.2 Implementation commit(s).
- [ ] 7.3 `docs/dev1-tracker.md` entry referencing #249.

## Dev Agent Record

### Implementation Plan
Derived directly from GitHub issue #249's own "Scope — pinpoint fixes" section (re-verified
against current `main` at `60eefc22` before writing this story — zero drift from when the issue
was filed, since `feature/233-topic-selection-step` has not yet merged and touches none of these
files).

### Debug Log

**Mid-implementation main merge.** After Task 3 (PipelineState fields + `prompt_context.py`
refactor) and before Task 4, PR #252 (issue #233, `topic_selection_node`) merged into `main` —
this story's own baseline assumption ("`feature/233-topic-selection-step` has not yet merged and
touches none of these files") stopped holding mid-work. Committed the Task 3 progress as a
checkpoint, then merged `origin/main` in immediately (before any more `graph.py` edits) rather
than deferring the reconciliation to a bigger conflict later. `graph.py` auto-merged cleanly (the
two branches' edits landed in different regions of the file). `docs/DEFECT-REGISTER.md` had one
positional conflict — this story's own new `D189` entry and #233's `D188` entry were both
inserted at the same anchor point (end of file, right after `D187`) — resolved by keeping both,
in numeric order; no actual ID collision, since `D189` was deliberately chosen anticipating `D188`
was already taken on the (then-unmerged) `feature/233-topic-selection-step` branch. Re-ran the RED
suite immediately after the merge to confirm nothing was lost — confirmed clean (9/11 passing,
exactly the 2 still-RED tests for the not-yet-done Task 4 work, matching pre-merge state exactly).

**`lesson_planner_node`'s chapter-context fetch moved earlier.** AC 2 required `chapter_context`
returned on both the cache-hit and fresh-computation paths, matching `book_context`. The existing
fetch (`chapter_ctx_block = await get_chapter_context_prompt_block(...)`) ran AFTER the
idempotency cache-hit check — meaning it was never fetched at all on a cache hit. Moved the fetch
itself to right after `book_context`'s own fetch (before the cache-hit check), mirroring
`book_context`'s exact placement and its own comment's rationale; left the `has_chapter_context`
computation and its Langfuse span logic at their original location (they only need the
already-fetched string, no need to move them too).

**`_planner_system_prompt`'s return signature kept unchanged.** Considered extending it to
`tuple[str, bool, bool]` (prompt, book-truncated, chapter-truncated) so `_run_planner_batch` could
log chapter-context truncation in real time, matching book_context's per-batch warning. Judged not
worth the signature churn across both call sites for a value the caller can already compute
independently — `lesson_planner_node` recomputes `chapter_context_truncated` via the same
direct-recomputation pattern already used for `book_context_truncated`
(`len(chapter_ctx_block) > _CHAPTER_CONTEXT_MAX_CHARS`), which is exactly how `book_context`'s own
final state-level flag is computed too (independently of `_planner_system_prompt`'s return value).

**`narration_generator_node` does NOT return `chapter_context_truncated`.** Mirrors
`book_context_truncated`'s own documented exclusion exactly: this node is `Send()`-dispatched (N
concurrent invocations per lesson), and LangGraph raises `InvalidUpdateError` on concurrent writes
to a non-reducer state channel. `lesson_planner_node` (sequential, runs first) already sets both
flags from the same source strings.

**Minor accepted cosmetic quirk, not fixed:** `chapter_ctx_block`'s own formatter
(`_format_chapter_context_block` in `context_chapter.py`) already prefixes its output with
`"\n\n[Chapter Instructions]\n"`, designed for the old raw-concatenation call site. Routing it
through `merge_chapter_context` (which also prepends `"\n\n"`) now produces a doubled blank line
before the chapter block. Left as-is — LLMs are insensitive to extra whitespace, this story's ACs
don't require exact formatting, and `_format_chapter_context_block` has its own existing tests
this story's guard-test survey explicitly scoped out of touching ("this story only changes what
*consumes* the already-tested formatted block, not how it's built").

### Senior Developer Review — Round 1 (2026-09-25, 6-agent Workflow, partial failure + fixes)

**Process note — a real tooling failure, not swept under the rug.** Launched a 6-agent
`Workflow` (Story Quality / Blind Hunter / Test Coverage / AC Completeness / Process Integrity /
Scale & Load, per CLAUDE.md's 6-layer gate). 5 of 6 agents ignored their assigned review prompt
entirely and instead each independently re-answered an unrelated, already-resolved question from
several turns earlier in the parent conversation ("check the main once again if it is updated or
not"), reasoning that a stale relayed message overrode their actual task. Only the `testCoverage`
agent performed its assigned review. This is a genuine subagent context-confusion bug in the
Workflow tool, not a review-design mistake — filed via `SendFeedback` (bug,
`failure_mode: context_and_memory`) with the reproduction. The 5 failed layers (Story Quality,
Blind Hunter, AC Completeness, Process Integrity, Scale & Load) did not run their intended review
this round; that coverage gap is open, not closed — see Task 6 follow-up below.

**`testCoverage`'s findings — all independently re-verified against real code before fixing, per
this repo's standing rule never to trust a reviewer's claim at face value:**

1. **(HIGH, CONFIRMED) AC 8 gap — `chapter_context_truncated` computed but never persisted.**
   `package_builder_node`'s Supabase `node_outputs` update wrote `book_context_truncated` as a
   sibling key but had no matching `chapter_context_truncated` line — the flag lived only in
   transient `PipelineState`, never reaching the durable, admin-visible record. This is exactly
   the "silent truncation is never acceptable" failure class CLAUDE.md names directly. **Fixed:**
   added `"chapter_context_truncated": state.get("chapter_context_truncated", False)` immediately
   after the existing `book_context_truncated` line. Two new tests added
   (`test_chapter_context_truncated_reaches_persisted_admin_record`,
   `test_chapter_context_truncated_defaults_false_when_absent`), calling the real
   `package_builder_node` and asserting on the actual `jobs_update_kwargs["node_outputs"]` dict.
2. **(HIGH, CONFIRMED) No test exercised the real `lesson_planner_node`/`slide_generator_node`
   return dict for these two keys** — only the private `_planner_system_prompt` helper and the
   pure `merge_chapter_context` function were tested; a regression dropping either key from a
   return-dict literal would have passed the whole suite undetected. **Fixed:** added
   `test_lesson_planner_node_returns_chapter_context_fresh_computation_path` and
   `test_lesson_planner_node_returns_chapter_context_on_cache_hit_path` (both call the real async
   node, patching `get_chapter_context_prompt_block` to return a unique marker, asserting on the
   returned dict directly on both idempotency paths), plus
   `test_slide_generator_node_returns_chapter_context_truncated_in_dict`.
3. **(MEDIUM, CONFIRMED) No test proved `book_context` and `chapter_context` compose correctly
   together** when both are non-empty in the same prompt — each was only ever tested in
   isolation. A regression re-feeding the pre-book-merge base prompt into `merge_chapter_context`
   would silently drop `book_context` whenever `chapter_context` is also present, and nothing
   would catch it. **Fixed:** added
   `test_book_and_chapter_context_both_reach_slide_prompt_uncorrupted` — asserts both unique
   markers reach the real prompt, in the documented book-then-chapter order, with both truncation
   flags correctly `False`.
4. **(LOW, CONFIRMED) `PipelineState`'s new fields were never asserted to exist** — minor, since
   `TypedDict` has no runtime enforcement, but unverified by the suite in isolation. **Fixed:**
   added `test_pipeline_state_declares_chapter_context_fields`, using `typing.get_type_hints()`
   (not raw `__annotations__`, which are unresolved `ForwardRef`s under this file's
   `from __future__ import annotations`).

All 4 findings fixed; 7 new tests added (20 total in the file, up from 13); full regression
re-run green (see Completion Notes below).

### Senior Developer Review — Round 2 (2026-09-25, 6 independent Agent-tool reviewers, all 6 CLAUDE.md layers)

**Process note.** Round 1 used the `Workflow` tool and 5 of 6 agents were derailed by a stale
relayed message (see Round 1 above). For Round 2, dispatched 6 independent, fully self-contained
`Agent` tool calls directly (not `Workflow`) — one per BMAD layer (Story Quality, Blind Hunter/
Security, Test Coverage, AC Completeness, Process Integrity, Scale & Load), each blind to the
others and to this story's own prior review rounds. All 6 completed and did their assigned job
this time. Every finding below was independently re-verified against the real code (never taken at
face value) before being triaged as CONFIRMED (fixed) or NOT-A-DEFECT (left as-is, with reasoning)
— per this repo's standing rule that an agent's claim is a lead, not a fact.

**Findings, independently re-verified and fixed:**

1. **(MEDIUM, CONFIRMED — triangulated independently by 3 of the 6 reviewers: Story Quality,
   Blind Hunter, Test Coverage.)** `_planner_system_prompt` was the only one of the three
   context-merging call sites that merged `chapter_context` BEFORE `_UNTRUSTED_CONTENT_GUARD` and
   `book_context` AFTER it — an asymmetric prompt-injection exposure (chapter_context's free-text
   fields sat outside the guard's literal "treat as untrusted" scope while book_context sat inside
   it), and it also contradicted both `prompt_context.py`'s documented §5 precedence order (book
   context before chapter instructions) and `slide_generator_node`'s/`narration_generator_node`'s
   own `guard → book → chapter` order. Re-verified directly against the code at all three call
   sites before fixing. **Fixed:** reordered `_planner_system_prompt` to `guard → merge_book_context
   → merge_chapter_context`, matching the other two nodes exactly; return signature unchanged
   (`was_book_context_truncated` now captured from the (no-longer-last) `merge_book_context` call
   instead of being the bare return value). New test
   `test_planner_system_prompt_merges_book_before_chapter_uncorrupted` proves the order and that
   neither merge corrupts the other.
2. **(HIGH, CONFIRMED, Story Quality.)** The story's AC list omitted the CLAUDE.md-required AC
   naming `graph.py`'s guard tests — binding rule: "a story that touches any pipeline node file is
   incomplete if it does not name that module's guard tests as an AC." **Fixed:** added AC 11
   naming `test_node_return_shape.py` explicitly (this story adds return-dict keys to two node
   functions, exactly what that guard exists to catch a violation of).
3. **(HIGH, CONFIRMED, Test Coverage.)** No test asserted on `narration_generator_node`'s REAL
   returned dict to confirm it excludes `book_context_truncated`/`chapter_context_truncated` — the
   exact `InvalidUpdateError` hazard the code's own comment names (Send()-dispatched N-way
   concurrently; LangGraph raises on concurrent writes to a non-reducer channel). A future edit
   copying `slide_generator_node`'s return-dict line here would have passed the whole suite green,
   then broken every real concurrent lesson job. **Fixed:** added
   `test_narration_generator_node_return_dict_excludes_both_truncated_flags`.
4. **(MEDIUM, CONFIRMED, Test Coverage.)** The `if chapter_id_for_ctx and user_id_for_ctx:` guard
   in `lesson_planner_node` had zero coverage of "only one set" — every existing test set both or
   neither, unable to distinguish `and` from a weaker `or`. **Fixed:** added
   `test_lesson_planner_node_skips_chapter_fetch_when_only_chapter_id_set` and the symmetric
   `..._only_user_id_set`, both asserting the fetch function is never called.
5. **(MEDIUM, CONFIRMED, Test Coverage.)** No test fed both `book_context` and `chapter_context`
   oversized simultaneously — every truncation test oversized only one with the other empty.
   **Fixed:** added `test_book_and_chapter_context_both_truncated_simultaneously_independent`
   (`slide_generator_node`, both markers present exactly once, both flags `True`).
6. **(MEDIUM, CONFIRMED, Scale & Load.)** `specific_doubt`/`goal_and_skip` (the two free-text
   fields `_CHAPTER_CONTEXT_MAX_CHARS`'s derivation depends on) have no DB `CHECK` constraint —
   the identical defect class already registered as **D178** for `book_context`'s sibling columns,
   reintroduced here without a mirroring entry. Verified directly against
   `supabase/migrations/20260921010000_chapter_context.sql` (the follow-up
   `..._check_constraints.sql` adds `CHECK` only for the two MCQ enum columns, not these two).
   **Fixed:** registered **D190**, referencing D178, same resolution path.
7. **(LOW, CONFIRMED, AC Completeness.)** `test_budget_is_independently_derived_not_copied_from_book_context`
   (AC 4) only range-checked `1_000 <= chapter_max_chars <= 1_500`, never the exact `1,300` AC 4
   literally claims. **Fixed:** added an exact-value assertion.
8. **(LOW, CONFIRMED, Scale & Load.)** No test asserted the REAL worst-case
   `_format_chapter_context_block` output against the 1,300 cap — only a range check on the
   constant. **Fixed:** added `test_real_worst_case_chapter_context_block_fits_the_derived_budget`,
   computing the worst case dynamically from the real label dictionaries (not hardcoded strings),
   so a future label/max_length change erodes the margin loudly, not silently.
9. **(LOW, CONFIRMED, AC Completeness.)** `test_lesson_planner_node_returns_chapter_context_on_cache_hit_path`'s
   own docstring claimed the cache-hit branch "must still return... `chapter_context_truncated`",
   but the test never asserted on it — and on inspection, the REAL cache-hit return dict does not
   include either truncated flag at all (a real, pre-existing gap inherited from `book_context`'s
   own identical cache-hit behavior, not introduced by this story — see new finding below).
   **Fixed:** corrected the docstring and added explicit assertions pinning the real (gap-carrying)
   behavior, rather than the behavior the docstring had incorrectly assumed.
10. **(NEW FINDING, discovered while fixing #9 above, not flagged by name by any of the 6 reviewers
    — surfaced during independent re-verification, registered per binding rule 5 rather than
    silently fixed.)** `lesson_planner_node`'s cache-hit branch returns the raw `book_context`/
    `chapter_context` strings but never their `_truncated` flags — on an ARQ-retried job where
    attempt 1 completed `lesson_planner_node` (with real truncation) but failed before
    `package_builder_node` ever persisted it, attempt 2's cache-hit skips recompute and the
    persisted admin record silently shows `False` for both flags regardless of the true state.
    Pre-existing for `book_context` since Story S5-1 — Story 249 inherited it by design (AC 2's own
    stated goal: "matching how it already returns `book_context` today"), did not introduce it new.
    **Registered as D191, not fixed here** — fixing it means changing already-shipped
    S5-1 node behavior for both contexts together (fixing only `chapter_context` while leaving
    `book_context`'s identical gap would itself violate binding rule 6), which is outside a wiring
    story's clean scope. `test_lesson_planner_node_returns_chapter_context_on_cache_hit_path` pins
    today's real behavior explicitly so this doesn't regress further unnoticed.
11. **(LOW, CONFIRMED, AC Completeness.)** The original `test_context_over_limit_truncated_at_newline_boundary`
    used a single early newline (`"Field: value\n"` at char ~13), so the cut landed at the same
    position regardless of the budget boundary — identical in shape to the no-newline hard-cut test,
    unable to prove a REAL newline-boundary cut distinct from an always-hard-cut regression.
    **Fixed:** rewrote using many short newline-separated fields so the boundary genuinely falls
    near the budget edge, with explicit assertions that every kept field is complete (never cut
    mid-field).
12. **(LOW, CONFIRMED, AC Completeness.)** No oversized-input test proved `narration_generator_node`
    uses the real `merge_chapter_context()` (vs. raw concatenation) — the return-dict trick used for
    `slide_generator_node` isn't available here (narration deliberately never returns
    `chapter_context_truncated`, see finding 3). **Fixed:** added
    `test_narration_generator_node_uses_real_merge_not_raw_concat`, mirroring AC 5's own
    marker-in-prompt technique.
13. **(LOW, CONFIRMED, Story Quality.)** D189's citation `graph.py:7191` was stale by ~400 lines
    (post-merge line drift, never updated) — pointed at unrelated S5-4 code. **Fixed:** corrected to
    the verified-current `graph.py:7607`.
14. **(LOW, CONFIRMED, Process Integrity.)** The `chapter_context_truncated`/`book_context_truncated`
    field comments in `PipelineState` inaccurately claimed `narration_generator_node` sets them,
    when it deliberately never does (finding 3). **Fixed:** corrected both comments to name the
    actual setters and explain the Send()-concurrency exclusion.
15. **(LOW, informational, Scale & Load.)** `book_context` (2,000) + `chapter_context` (1,300) can
    now both appear in the same prompt, with no combined budget ever stated — worst case 3,300
    chars (~825 tokens) against a 128k-token window (~0.6%), not dangerous today but an unanswered
    letter of the Scale Contract. **Fixed (documentation only):** added an explicit answer to the
    story's own Scale & Load Q2, naming the combined worst case and why it's safely bounded rather
    than leaving the question unaddressed.

**Findings independently re-verified and judged NOT a defect requiring a fix (left as-is, with
reasoning):** Blind Hunter's IDOR check (traced `chapter_id`/`user_id` provenance three hops back
through `router.py`/`content_pipeline_job`/`run_pipeline` — confirmed server-derived, never
client-suppliable, no exploit path); the shared `_sanitize()` newline-only mitigation (identical to
`book_context`'s own, not a regression); the bounded-query guard's documented pipeline-scope
exclusion (pre-existing, not introduced here); AC 10's "NOT COVERED" verdict (a documentation AC —
inherently not test-backed by nature, correctly assessed as such by AC Completeness itself); D189's
trigger wording being "comparatively vague" (a real but genuinely subjective LOW note, judged not
worth further engineering beyond the citation fix already made).

**15 findings fixed, 1 new defect discovered and registered (D190, D191) rather than silently
fixed, 2 code changes (`_planner_system_prompt` reorder, `PipelineState` comment accuracy), 1 story
AC added (AC 11), 7 new tests added (27 total in `test_249_context_wiring.py`, up from 20).**

### Completion Notes
All 10 ACs implemented and verified:
- `PipelineState` gains `chapter_context`/`chapter_context_truncated` (AC 1).
- `lesson_planner_node` fetches chapter context alongside book context (before the cache-hit
  check) and returns it on both paths (AC 2).
- `prompt_context.py` refactored: shared `_merge_context_block` extracted from
  `merge_book_context`'s old body; new `merge_chapter_context` with its own independently-derived
  `_CHAPTER_CONTEXT_MAX_CHARS = 1,300` and distinct `_CHAPTER_TRUNCATION_MARKER` (AC 3, AC 4).
- `lesson_planner_node`'s raw `+ chapter_context` concatenation replaced with a real
  `merge_chapter_context()` call (AC 5).
- `slide_generator_node` and `narration_generator_node` both merge `chapter_context` into their
  prompts, alongside their existing `book_context` merges (AC 6, AC 7); `_FAN_OUT_STATE_KEYS`
  extended (AC 7); both fan-out dispatch payload builders (`_fan_out_phase1_economy_nodes`,
  narration's own post-planner dispatch) get a matching `setdefault("chapter_context", "")`.
- `chapter_context_truncated` surfaced identically to `book_context_truncated` — set by
  `lesson_planner_node`/`slide_generator_node`, deliberately NOT returned by
  `narration_generator_node` (AC 8); persisted into `package_builder_node`'s durable
  `node_outputs` record alongside `book_context_truncated` (review Finding 1, fixed).
- `D189` registered (Task 3.1) documenting the deferred Phase-1-economy-node question, per AC 10.
- 20 tests in `test_249_context_wiring.py`: 8 for `merge_chapter_context` (mirroring
  `TestMergeBookContext` exactly), 1 proving `_planner_system_prompt` uses the real merge (not raw
  concatenation), 1 for `_FAN_OUT_STATE_KEYS`, 1 regression guard proving the 5 Phase-1 nodes
  reference neither context (AC 9), 2 proving `chapter_context` text reaches
  `slide_generator_node`'s/`narration_generator_node`'s real constructed prompts, 2 proving
  `chapter_context_truncated` reaches the real persisted admin record, 2 calling the real
  `lesson_planner_node` (fresh + cache-hit paths) and asserting on its returned dict directly,
  1 proving `slide_generator_node`'s real returned dict carries `chapter_context_truncated`,
  1 proving `book_context`+`chapter_context` compose correctly together in the same prompt
  (order, no dropping, no duplication), and 1 asserting `PipelineState`'s new fields via
  `typing.get_type_hints()` — those 7 added in Round 1 review to close findings 1-4 above. Round 2
  added 7 more: the real `_planner_system_prompt` book-before-chapter ordering proof, the
  `narration_generator_node` return-dict key-exclusion proof, its own oversized-input real-merge
  proof, both `chapter_id`/`user_id`-guard "only one set" branches, the both-contexts-truncated-
  simultaneously composition test, and the real-worst-case-vs-budget invariant test — 27 total.
- Full regression: 27/27 new tests + 48/48 mandatory guard tests (`test_ces.py`,
  `test_node_return_shape.py`, `test_unbounded_queries.py`) + full `tests/unit` + `tests/integration
  -m "not postgres"` suite, all green (1 pre-existing, unrelated failure —
  `test_effective_wpm_is_not_the_raw_rate`, already confirmed pre-existing during Story 233's own
  work). `ruff check .`: clean. `mypy` on both touched app files: clean (3 pre-existing errors
  elsewhere, unrelated httpx/httpx2 OpenAI-client typing, confirmed present on this branch's own
  last commit before today's edits — not a regression).
- Round 1's coverage gap (5 of 6 layers failed to run via the `Workflow` tool) is closed — Round 2
  used direct `Agent` tool calls instead and all 6 layers ran and reported real findings, see
  Senior Developer Review — Round 2 above. AC 11 added for the guard-test requirement Round 2's
  Story Quality layer flagged. D190 and D191 registered for two real, deliberately-deferred gaps
  Round 2 found (DB CHECK constraints on `chapter_context` free-text columns; cache-hit path not
  surfacing either truncated flag) — neither blocks this story, both are pre-existing-pattern gaps
  this story inherited rather than introduced.

### File List
- `apps/api/app/modules/content/pipeline/graph.py` — `PipelineState` gains `chapter_context`/
  `chapter_context_truncated` (comments corrected Round 2 to name the real setters);
  `_planner_system_prompt` uses `merge_chapter_context`, reordered Round 2 to
  `guard → book → chapter` matching the other two nodes; `lesson_planner_node`'s chapter-context
  fetch moved earlier + returns it on both paths + computes `chapter_context_truncated`;
  `slide_generator_node`/`narration_generator_node` merge `chapter_context`; `_FAN_OUT_STATE_KEYS`
  extended; both fan-out payload builders get a `chapter_context` `setdefault`;
  `package_builder_node` persists `chapter_context_truncated` into `node_outputs` (Round 1 review
  fix).
- `apps/api/app/modules/content/pipeline/prompt_context.py` — shared `_merge_context_block`
  extracted; new `merge_chapter_context`/`_CHAPTER_CONTEXT_MAX_CHARS`/`_CHAPTER_TRUNCATION_MARKER`.
- `apps/api/tests/test_249_context_wiring.py` — new file, 27 tests.
- `docs/DEFECT-REGISTER.md` — `D189` (new in Round 1, line citation fixed in Round 2); `D190`, `D191`
  new in Round 2.
- `docs/stories/249-context-wiring.md` — AC 11 added; Scale & Load Q2 extended with the combined
  book+chapter budget answer.

### Change Log
- 2026-09-25: Story file created (story-first commit), branch `feature/249-context-wiring`, based
  on `main` at `60eefc22`.
- 2026-09-25: Implementation complete (Tasks 1-5) — see Dev Agent Record above, including the
  mid-work `main` merge (PR #252/issue #233 landed) and its resolution. Full regression green.
- 2026-09-25: Round 1 review (5 of 6 agent layers failed to run due to a Workflow tool subagent
  context-confusion bug, reported separately; `testCoverage` layer's 4 findings all independently
  re-verified and fixed, 7 new tests added).
- 2026-09-25: Round 2 review — 6 independent `Agent` tool calls (all 6 layers ran this time,
  bypassing the Workflow tool bug). 15 findings fixed (1 real code-behavior fix — the
  `_planner_system_prompt` ordering/guard asymmetry, triangulated by 3 reviewers — plus test/doc/
  register fixes), 1 new defect discovered during fix verification and registered rather than
  silently fixed (D191), D190 registered for a Scale & Load finding, AC 11 added, 7 new tests
  (27 total). Full regression green. Task 7.2/7.3 (dev1-tracker entry, PR) next.
