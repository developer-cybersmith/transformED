---
id: "233"
title: "Topic-selection step — collapse chapter sections into 1 or 2 topics by duration"
status: "in-progress"
sprint: null
story_points: 8
baseline_commit: "dd9ea51"
owner: Dev1
priority: P1
blocker_ref: "GitHub issue #233 (piece 1 of 4; blocked-on issue #236 is closed)"
---

# Story 233 — Topic-Selection Step (piece 1 of 4 of issue #233)

## Context & Scope Boundary

**Why this story exists:** Issue #233 (mandatory 15/30/45-min fixed slide structures +
transcript protocol) requires every lesson to teach exactly **1 topic** (15-min, tier T3) or
**2 topics** (30/45-min, tiers T2/T1) — never "however many sections the chapter happens to
have." Today's pipeline is strictly 1:1: `structure_node` produces N sections (bounded by
`structure_max_sections=15`), and `lesson_planner_node` turns those into N outline segments,
"never merge/split/omit" (its own docstring, unchanged by issue #230/S5-4's duration work).
Issue #233's own author flagged this as a separate, foundational, not-yet-designed piece —
this story is exactly that piece, the first of the 4 the issue's own text recommends splitting
into (topic-selection step, split-screen schema, continuous transcript, per-duration slide
tables) — chosen first because nothing else in #233 can proceed without it.

**Formal blocker status:** issue #236 (narration continuity) was #233's only GitHub-tracked
blocker — closed 2026-09-21 (merged PR #237). No other issue formally blocks #233.

**Design decision (made with the user, after considering two options):** collapse the
`sections` list itself, early in the pipeline (**Option A**), rather than leaving all N
sections intact and only attaching a `topic_group` label near the end (Option B). Option A
means every downstream node (summaries, quizzes, complexity, jargon, interventions, narration,
`lesson_planner_node`) naturally operates on 1-2 big topics with **zero code changes of its
own** — it just sees a shorter `state["sections"]` list. Option B would have been a smaller
diff, but keeps content generation fine-grained per-original-section (arguably not truly
"collapsing to 1-2 topics" as the issue's own wording describes), and is a better fit for
piece #4 (per-duration slide generation) than for this step.

**Critical placement finding (research done before design, not assumed):**
`chunk_node`'s output (`chunks` Supabase rows, later embedded) is cached **per `chapter_id`,
reused verbatim across different lessons of the same chapter regardless of tier** — confirmed
via `chunk_node`'s own docstring ("Chunk embeddings at ingestion only — never regenerate...
ANOTHER lesson already chunked this same chapter... reused verbatim"). If topic-selection ran
*before* `chunk`/`embed` and changed `sections` based on tier, a lesson requested later at a
*different* tier would find chunks already exist (built for a *different* tier's topic
boundaries) and silently reuse them — a real correctness bug, not a style choice. **This story
places `topic_selection_node` after `embed`, not before it** — which also cleanly matches
CLAUDE.md's existing Phase A (chapter-level, tier-agnostic ingestion) vs Phase B (lesson-level,
tier-aware generation) boundary: topic-selection is the first Phase B step, not a Phase A one.

**What this story does:**
1. New `TIER_TOPIC_COUNT` mapping (`apps/api/app/schemas/lesson.py`): T1/T2 → 2 topics, T3 → 1
   topic — reusing the tier meaning #230/S5-4 already established (duration, not depth).
2. New public helper `merge_section_range()` in `structure_detection.py`, built on the
   existing, already-tested `_merge_two` (text-preserving: no source text ever dropped) —
   the same primitive `coalesce_sections` already uses, not new merge logic.
3. New `topic_selection_node`, inserted `embed → topic_selection → <existing Phase-1
   fan-out>`: for the 1-topic case, merges all sections with zero LLM calls; for the 2-topic
   case, one cheap `llm_mini` call (section index + title + ~200-char preview only, never the
   full chapter) asking for a single split index — sections are linear, so a single split
   point is the only pedagogically sound shape, and it's a one-int response trivial to guard.
   Any invalid/missing/out-of-range response or exception degrades to a deterministic
   midpoint-by-body-length split — never hard-fails, matches this file's universal
   degrade-not-fabricate convention.
4. Overwrites `state["sections"]` with the resulting 1-2 topic dicts under the *same* key —
   zero changes needed anywhere downstream (Phase-1 fan-out, `_derive_section_id`,
   `lesson_planner_node`, narration, all read `state["sections"]` exactly as before).
5. Checkpoints an explicit, admin-visible record of which original sections folded into which
   topic — following the `section_truncations` (Story 3-39) precedent: a real reduction in
   granularity is a surfaced fact, never silently invisible.
6. Re-derives `section_body_max_chars` (see Scale & Load below) — real, necessary work, not
   optional cleanup: leaving it at its old per-small-section value would silently truncate
   away most of a merged topic's content, defeating this story's entire purpose.

**What this story does NOT do:**
- Does not implement any other piece of #233 — no split-screen slide schema, no fixed 7/10-slide
  generation, no continuous-transcript/slide-transition wiring, no personalization-hook
  changes. `slide_generator_node`'s existing duration-proportional `_tier_slide_budget_per_segment`
  logic is untouched — with only 1-2 (much bigger) segments, it will allocate close to its
  existing per-segment MAX (8 slides) to each, an accepted **interim** state (not exactly the
  mandated 7/10 total) until piece #4 lands. Documented as a known, temporary gap, not silently
  left unexplained.
- Does not resolve the "auto-selected Scheduler agent vs. explicit user choice" duration-
  selection conflict #233 flags against #230 — not needed here: `tier` already arrives as an
  explicit value from the existing request path (`GenerateLessonRequest.tier`, chosen via
  `ModeSelection.tsx` before generation starts); this story only *consumes* whatever tier value
  arrives, regardless of how upstream ever decides to set it.
- Does not touch `chunk_node`/`embed_node` or their per-chapter chunk/embedding reuse
  semantics — confirmed safe by placement (see above).
- Does not touch the frozen `packages/shared` contracts.

## Story

**As** the content pipeline,
**I want** a chapter's raw sections collapsed into exactly 1 or 2 topics depending on the
lesson's duration, before any per-section content generation begins,
**so that** every downstream node produces deep, coherent, topic-level content instead of many
thin per-section pieces — the structural prerequisite for #233's mandated fixed slide
structures and continuous transcript.

## Acceptance Criteria

### Functional

- [ ] **AC 1.** `TIER_TOPIC_COUNT` exists in `apps/api/app/schemas/lesson.py`: `{"T1": 2, "T2": 2, "T3": 1}`.
- [ ] **AC 2.** `merge_section_range(sections: list[dict]) -> dict` exists in
  `structure_detection.py`, built on `_merge_two` via a left-fold over an arbitrary-length
  list. Text-preserving (every original title + body appears in the merged body), keeps the
  first section's title, the coarsest `level` among inputs, and the union of all page ranges —
  identical contract to `_merge_two`/`coalesce_sections`'s existing behavior, not new rules.
- [ ] **AC 3.** New `topic_selection_node(state) -> state` in `graph.py`, registered in
  `_build_pipeline_graph()` between `embed` and the existing Phase-1 fan-out entry point
  (`embed → topic_selection → <fan-out>`, was `embed → <fan-out>` directly).
- [ ] **AC 4.** When `len(state["sections"]) <= TIER_TOPIC_COUNT[tier]`: no-op — `sections`
  passes through unchanged (never fabricates a 2nd topic from insufficient material).
- [ ] **AC 5.** 1-topic case (T3): all sections merged into one via `merge_section_range`, zero
  LLM calls.
- [ ] **AC 6.** 2-topic case (T1/T2): one `settings.llm_mini` structured-output call, input is
  section index + title + a short body preview only (never full section bodies, never the
  whole chapter) — asking for a single `split_index: int`. Guard: response must be a valid
  index in `[1, len(sections)-1]`; any invalid value, missing/None response, or exception
  degrades to a deterministic midpoint-by-cumulative-body-length split — never raises.
- [ ] **AC 7.** `state["sections"]` is overwritten (same key) with the resulting topic dicts,
  each shaped identically to a normal section dict (`title`, `body`, `level`, `page_start`,
  `page_end`) — verified by confirming the existing Phase-1 fan-out and `_derive_section_id`
  require zero code changes to keep working.
- [ ] **AC 8.** An explicit, admin-visible checkpoint record is written
  (`node_outputs["topic_selection"]`, or a sibling key) naming which original section
  indices/titles folded into which resulting topic — always present, including the AC-4 no-op
  case (recording "no collapse needed").
- [ ] **AC 9.** `settings.section_body_max_chars`'s default is re-derived (raised) with the
  arithmetic justification written into the field's own `description=`, per Scale & Load Q5
  below — not left at its old per-small-section value.
- [ ] **AC 10.** Idempotent: a second invocation with `node_outputs["topic_selection"]` already
  present returns the cached result, no LLM call, matching `structure_node`/`chunk_node`'s
  existing Phase-A-style plain-checkpoint pattern (no atomic RPC needed — single sequential
  node, not Send()-fanned-out).
- [ ] **AC 11.** `chunk_node`/`embed_node` are verified unaffected — they still run on the
  full, un-collapsed section list, preserving per-chapter (not per-tier) chunk/embedding reuse
  exactly as today.
- [ ] **AC 12.** Guard-test survey (CLAUDE.md's "before touching any module" rule) performed
  and listed in the Dev Agent Record before any edit; every hit either covered by the ACs above
  or explicitly noted as unaffected-and-verified.
- [ ] **AC 13.** Full repo-wide regression (`tests/unit` + `tests/integration -m "not
  postgres"`) shows zero new failures vs. `main`.
- [ ] **AC 14.** `ruff check .`, `ruff format --check`, and `mypy app` (repo-wide) show zero
  new issues vs. `main`.

## Scale & Load

*(`docs/SCALE-CONTRACT.md` — six questions, contract-mandated on every story)*

1. **Unit of work, and its range.** One unit is one topic-selection pass over one chapter's
   already-structure-detected section list — input range 1 to `structure_max_sections` (60)
   sections (that cap is enforced upstream, unchanged by this story); output is always exactly
   1 or 2 topics (or fewer, in the AC-4 no-op case). The 2-topic LLM call's own input is
   bounded independently of section body size (index + title + ~200-char preview per section,
   never full bodies) — so even at the 60-section ceiling, the split-decision call's cost is
   small and roughly constant, not proportional to chapter size.
2. **Fixed budgets vs. variable input.** Two: (a) `TIER_TOPIC_COUNT`'s output (1 or 2) is a
   hard structural target, not a soft guideline — the AC-4 no-op guard is the explicit,
   surfaced behavior when the chapter has fewer sections than the target (never fabricated).
   (b) `section_body_max_chars` — the fixed budget that meets a now-much-larger variable input
   (a merged topic body vs. one small section). **This is the real substance of this story's
   Scale & Load answer, not an N/A**: re-derived from 6,000 to a new default computed as
   `old_value × (structure_max_sections / target_topic_count)` — worst case ×15 (1-topic) or
   ×7.5 (2-topic) — landing in the 40,000-45,000 range. Documented as a first-cut, reasoned
   estimate (not claimed final) in the field's own description, matching this codebase's
   established pattern of shipping a computed number and empirically re-tuning later (e.g. the
   narration char cap's own D76→D78 history: 10,000 → 17,000 → 120,000 as real data came in).
   The existing truncation-surfacing machinery (`section_truncations`, `source_was_truncated`
   in `lesson_planner_node`'s duration report) already distinguishes "genuinely short content"
   from "our own cap was the real limit" — confirmed via a direct code comment already
   anticipating exactly this risk class for coalesced sections — so no new surfacing code is
   needed, only the cap value itself.
3. **Scope of every limit.** Per-lesson-generation-run (i.e., per pipeline invocation, keyed by
   `lesson_id`) — `TIER_TOPIC_COUNT` and `section_body_max_chars` are both global settings, not
   shared mutable state across concurrent lessons; no cross-lesson interaction.
4. **Unbounded reads/writes.** None introduced. `topic_selection_node` reads only
   `state["sections"]` (already in-memory, already bounded upstream) and `state["tier"]`; its
   one new LLM call and one new checkpoint write both ride the same bounded, already-established
   patterns every other Phase-A-style sequential node in this file uses.
5. **Inherited caps re-derived?** Yes — `section_body_max_chars` is the direct answer to this
   question (see Q2). `structure_max_sections` (15) is inherited unchanged: the unit it bounds
   (raw section count into the pipeline) hasn't changed: this story runs *after* that cap is
   already enforced, only changing what happens to the *result*.
6. **Check-then-act under concurrency.** `topic_selection_node` runs strictly sequentially
   (single node, not Send()-fanned-out — same class as `structure_node`/`chunk_node`), so its
   own plain-checkpoint read-modify-write carries the same (already-accepted, pre-existing)
   theoretical concurrent-duplicate-run exposure those nodes already have, no new exposure
   introduced.

**The one-line test, answered:** before this fix, "1 or 2 topics per lesson" was pure PDF
prose with nothing behind it — every lesson silently generated however many sections the
chapter happened to produce, with no code able to notice or report the mismatch against the
spec. After this fix, the mismatch either can't occur (sections are actually collapsed to the
target count) or is explicitly recorded when it can't be met (the AC-4 no-op case) — loud, not
silent, and the specific new failure mode this story introduces (a merged topic's content
getting truncated by an unrevised size cap) is closed by re-deriving that cap with the
arithmetic shown, not left as a latent, undocumented risk.

## Tasks

### Task 1 — Guard-test survey (AC 12)
- [x] 1.1 Run the CLAUDE.md-mandated grep across `apps/api/tests/` for guard tests touching
  `structure_node`/`structure_detection`/`graph.py`'s Phase-1 fan-out; list results in Dev
  Agent Record.

### Task 2 — RED
- [x] 2.1 Write tests against the desired `topic_selection_node`/`merge_section_range`
  behavior and confirm they fail against the current (pre-fix) code.

### Task 3 — GREEN: schema + structure_detection
- [x] 3.1 Add `TIER_TOPIC_COUNT` (AC 1).
- [x] 3.2 Add `merge_section_range` (AC 2).
- [x] 3.3 Re-derive `section_body_max_chars` (AC 9).

### Task 4 — GREEN: graph wiring
- [x] 4.1 Add `topic_selection_node` (AC 4, 5, 6, 7, 8, 10).
- [x] 4.2 Rewire `_build_pipeline_graph()` (AC 3).
- [x] 4.3 Verify `chunk_node`/`embed_node` unaffected (AC 11).
- [x] 4.4 Update module docstring's node-order diagram.

### Task 5 — GREEN: tests
- [x] 5.1 New `test_topic_selection_node.py`; new `merge_section_range` tests.
- [x] 5.2 Full regression run, ruff/format/mypy (AC 13, 14).

### Task 6 — Review
- [ ] 6.1 Parallel adversarial agent review (all 6 CLAUDE.md layers), same approach used for
  issue #236's PR #237.

### Task 7 — Commit
- [x] 7.1 Story-first commit (this file alone) — `1f43589`, pushed.
- [ ] 7.2 Implementation commit(s).
- [ ] 7.3 `docs/dev1-tracker.md` entry referencing #233.

## Dev Agent Record

### Implementation Plan
See the approved plan at implementation time
(`/Users/apple/.claude/plans/whimsical-tickling-rocket.md` as of this story's creation) —
summarized in Context & Scope Boundary above. Implemented exactly as planned; no design
deviations.

### Debug Log

**Guard-test survey (Task 1)**, `grep -rln "test_.*structure\|test_.*graph\|test_no_hardcoded\|test_dunder_all\|test_node_return_shape\|test_unbounded_queries" apps/api/tests/`, narrowed to
what this story's files actually touch:
- `test_node_return_shape.py`, `test_unbounded_queries.py` — repo-wide guards, re-run clean.
- `test_structure_no_llm.py` — investigated; its only `__all__` assertion is about
  `app.schemas.DocumentStructure`, unrelated to `structure_detection.py` (which has no
  `__all__` at all) — no allowlist update needed for `merge_section_range`.
- `test_structure_node.py`, `test_coalesce_sections.py` — direct coverage of the merge
  primitives `merge_section_range` is built on; new tests appended to the latter.
- `test_fan_out_state_keys.py`, `test_phase1_economy_nodes.py`,
  `test_phase1_checkpoint_idempotency.py` — Phase-1 fan-out shape; one test in
  `test_phase1_economy_nodes.py` needed `topic_selection_node` added to its sequential-node
  stub list (see below).
- `test_pipeline_tier1.py`, `test_s5_4_duration_wiring.py` — tier-driven behavior; one test in
  the latter needed its hardcoded assertion bound recomputed from the live (now-changed)
  `section_body_max_chars` value.
- `test_chunk_node.py` — re-run clean, confirms `chunk_node`/`embed_node` unaffected (AC 11).

**Real regressions found and fixed while making the guard-test/full-suite runs pass (all
expected, direct consequences of collapsing sections into 1-2 topics before Phase 1 —
not defects in the change itself):**
1. `test_oversized_section_cannot_take_the_whole_quiz_budget`
   (`test_s5_4_duration_wiring.py`) — hardcoded `counts[0] <= 6` assumed the old 6,000-char
   cap; rewrote the bound to compute from the live `section_body_max_chars` so it stays
   correct if this value is re-tuned again later, instead of hardcoding a new magic number.
2. `test_economy_nodes_run_before_lesson_planner_and_fan_out_per_section`
   (`test_phase1_economy_nodes.py`) — the real `topic_selection_node` was running
   un-stubbed inside this end-to-end graph test, collapsing its 3-section fixture to 2
   topics and breaking the "one call per section" assertion. Added
   `topic_selection_node` to the test's existing sequential-node pass-through stub list —
   this test verifies fan-out mechanics, not topic-collapsing (that's this story's own
   test file's job).
3. `test_tier_changes_the_delivered_package` (`test_tier_differentiation_and_cost.py`) —
   asserted `len(set(seg_counts.values())) == 1` (segment count must be identical across
   tiers), a premise this story exists to break. Replaced with the actual new contract:
   `T3 == 1 topic, T1/T2 == 2 topics`, verified end-to-end through the real graph — turns a
   stale check into a positive regression test for `TIER_TOPIC_COUNT`.
4. Both integration tests' fake LLM router (`test_howto_pipeline_e2e.py`) had no case for
   the new `_StructureTopicSplitLLM` — added one (parses the requested section count from
   the prompt, returns a middle split). This also surfaced that the fake's quiz-batch size
   (previously 3, tuned for ~15 small per-section allocations) was now the binding
   constraint once allocations concentrate on 1-2 much-larger topics — raised to a new
   shared `_QUIZ_FAKE_BATCH_SIZE = 20` constant (comfortably above the largest real tier
   lesson-total budget), referenced (not re-hardcoded) everywhere it's checked.
5. One pre-existing, unrelated failure confirmed on this branch's base commit before any
   of this story's changes (`test_effective_wpm_is_not_the_raw_rate`,
   `test_s5_4_duration_budget.py`) — verified via `git stash` that it fails identically
   with zero implementation changes applied. Not touched; not in scope.

### Completion Notes
All 14 ACs implemented and verified:
- `TIER_TOPIC_COUNT` (`schemas/lesson.py`), `merge_section_range` (`structure_detection.py`,
  18/18 tests including the 6 new ones), `section_body_max_chars` re-derived 6,000 → 45,000
  with the arithmetic in its own `description=` (`config.py`).
- `topic_selection_node`, `_StructureTopicSplitLLM`, `_topic_selection_llm_split`,
  `_topic_selection_midpoint_split` in `graph.py`, wired `embed -> topic_selection ->
  <Phase-1 fan-out>`; module docstring's 17-node diagram updated.
- 12 new tests in `test_topic_selection_node.py` (no-op both tiers, 1-topic merge, 2-topic
  LLM split, 3 distinct degrade-not-fabricate fallback paths, section-shape contract,
  checkpoint-always-written, idempotent cache-hit).
- Full regression: 1,663 unit tests + 20 integration tests passing (1 pre-existing,
  unrelated failure noted above — not a regression from this change). `ruff check .` and
  `ruff format --check .` clean repo-wide. `mypy app`: 4 pre-existing errors, all in
  `providers/llm|stt|image|embeddings` (httpx/OpenAI typing), none in any file this story
  touched.
- Not yet done: Task 6 (6-layer adversarial review) and Task 7.2/7.3 (implementation
  commit, dev1-tracker entry) — next steps.

### File List
- `apps/api/app/config.py` — `section_body_max_chars` default + description re-derived.
- `apps/api/app/schemas/lesson.py` — new `TIER_TOPIC_COUNT`.
- `apps/api/app/modules/content/pipeline/nodes/structure_detection.py` — new
  `merge_section_range`.
- `apps/api/app/modules/content/pipeline/graph.py` — new `topic_selection_node`,
  `_StructureTopicSplitLLM`, `_topic_selection_llm_split`,
  `_topic_selection_midpoint_split`; `_build_pipeline_graph()` rewired; module docstring
  updated.
- `apps/api/tests/unit/test_topic_selection_node.py` — new file, 12 tests.
- `apps/api/tests/unit/test_coalesce_sections.py` — 6 new `merge_section_range` tests.
- `apps/api/tests/unit/test_s5_4_duration_wiring.py` — 1 test's hardcoded bound made
  dynamic (regression fix #1 above).
- `apps/api/tests/unit/test_phase1_economy_nodes.py` — `topic_selection_node` added to a
  stub list (regression fix #2 above).
- `apps/api/tests/integration/test_tier_differentiation_and_cost.py` — stale invariant
  replaced with the real new contract (regression fix #3 above).
- `apps/api/tests/integration/test_howto_pipeline_e2e.py` — new
  `_StructureTopicSplitLLM` mock case, new shared `_QUIZ_FAKE_BATCH_SIZE` constant
  (regression fix #4 above), one stale comment corrected.

### Change Log
- 2026-09-24: Story file created (story-first commit), branch `feature/233-topic-selection-step`.
- 2026-09-25: Implementation complete (Tasks 1-5) — see Dev Agent Record above. Full
  regression green. Task 6 (adversarial review) and Task 7.2/7.3 next.
