---
id: "236"
title: "Narration continuity — move narration_generator after lesson_planner, add stitching node"
status: "in-progress"
sprint: null
story_points: 8
baseline_commit: "main@HEAD"
owner: Dev1
priority: P1
blocker_ref: "GitHub issue #236 (blocks #233)"
---

# Story 236 — Narration Post-Planner Ordering + Stitching (blocks #233)

## Context & Scope Boundary

**Why this story exists:** `narration_generator_node` is one of 6 "economy" nodes
`Send()`-dispatched once per section from `embed` (`_fan_out_phase1_economy_nodes`),
joining into `lesson_planner_node`. Each dispatch receives only
`_FAN_OUT_STATE_KEYS` (`lesson_id`, `user_id`, `book_id`, `tier`) plus its own
`_section`/`_section_index` — no other section's data, and no lesson outline,
because `lesson_plan` does not exist yet at the point narration runs. This is an
architectural fact, not an oversight: narration cannot callback to an earlier
section, reiterate a concept, or hold a single consistent voice across a lesson,
by construction. GitHub issue #236 is the verified, code-grounded finding; issue
#233 (mandatory 15/30/45-min fixed slide structures) is explicitly **blocked** on
this — its "single continuous transcript with slide-transition announcements and
reiteration loops" requirement cannot be built while narration runs blind
per-section.

**Why the fix cannot be "just add fields to the fan-out payload":** the payload is
built once, before any section's economy-node output (including the outline)
exists. There is no lesson plan to attach. The only fix is architectural: run
narration's fan-out AFTER `lesson_planner_node` has produced `lesson_plan`, not
alongside the other 5 economy nodes.

**What this story does:**
1. Removes `narration_generator` from the Phase-1 economy fan-out (`_ECONOMY_NODES`,
   `_PHASE1_INSTRUMENTED_NODES`) — 5 economy nodes remain, unchanged in every other
   respect.
2. Adds a new post-planner `Send()` fan-out, `_fan_out_narration_after_planning`,
   dispatched from `slide_generator` (sequential-after, smallest diff to existing
   wiring — decided with the user over the parallel-with-slide_generator
   alternative), one dispatch per section, each carrying that section's
   `lesson_plan` segment data (`segment_id`, `title`, `continuity_notes`) alongside
   the existing `_section`/`_section_index`/`_FAN_OUT_STATE_KEYS` base.
3. Adds `continuity_notes: str` to each `lesson_plan.segments[i]` entry —
   `lesson_planner_node`'s own LLM call, which already sees every segment summary
   at once, additionally names (in free text, empty string when none apply) any
   earlier segment worth a brief callback/reiteration. **Deliberately generic, not
   shaped to #233's Topic I/II grouping** — #233 itself states that "1-or-2 topics
   per lesson" needs its own not-yet-designed topic-selection step, which does not
   exist in the code today (`lesson_planner_node` is 1:1 section→segment, "never
   merge/split/omit"). Building a speculative topic-group field here would guess at
   an unbuilt spec; a later #233 story can add `topic_group` alongside this field
   without touching narration's consumption of it.
4. `narration_generator_node` reads the new per-dispatch `continuity_notes` and
   splices it into the same user-role prompt message that already carries
   `narration_style`/section body (same untrusted-content trust level). No other
   change to its checkpoint key, pacing guard, or blank-script guard.
5. Adds a new sequential node, `narration_stitch_node`, running after all
   per-section narration dispatches join, before `tts_node`: one `llm_mini` call
   over the ordered `[{segment_id, script}]` list to insert brief slide-transition
   phrasing and trim duplicate phrasing across sections, guarded by the same
   degrade-not-fabricate discipline `lesson_planner_node` uses (segment-id set/
   count/uniqueness match, or fall through to the unmodified-but-ordered scripts).
6. **Moves `_apply_narration_char_cap` from `tts_node` into `narration_stitch_node`**
   — resolving the issue's explicit "revisit this placement" ask. The cap's own
   docstring justifies its location as "the first point all segments' scripts are
   available together, immediately before the TTS spend" — that description is now
   `narration_stitch_node`, not `tts_node`. No change to the cap function itself,
   only its call site and the node that persists `node_outputs["narration_cap_applied"]`.
7. Adds `narration_scripts_final` (plain `PipelineState` field, no reducer) as the
   one output of `narration_stitch_node`; `tts_node` and `package_builder_node` are
   repointed to read it instead of `narration_scripts`.
8. Rewrites (never silently breaks) `test_phase1_economy_nodes.py`'s
   `test_economy_nodes_run_before_lesson_planner_and_fan_out_per_section`, whose
   current assertion — narration runs alongside the other 5, before
   `lesson_planner` — is exactly what this story changes.

**What this story does NOT do:**
- Does not implement any part of #233's topic-selection/Topic-I-II grouping,
  fixed slide counts, or split-screen schema — out of scope, explicitly deferred
  per #233's own text.
- Does not change `_apply_narration_char_cap`'s internal truncation/grapheme-safety
  logic — only where it's called from.
- Does not change the atomic `merge_lesson_job_node_output` RPC or
  `_read/_write_phase1_checkpoint`/`_increment_phase1_progress` — these are already
  generic (keyed by an arbitrary `f"{node}:{section_id}"` string) and are reused
  as-is for the new post-planner fan-out.
- Does not touch `packages/shared/lesson_package.schema.json` or `types/lesson.ts`
  — `continuity_notes` never leaves internal pipeline state (`package_builder_node`
  only lifts `lesson_plan.title/subject/complexity_level/total_duration_min`
  scalars into the final package), so the frozen 4-dev-reviewed contract is
  unaffected.
- Does not change `narration_generator_node`'s opportunistic cross-read of
  `segment_complexity`'s checkpoint (AC-6 from Story 2-1) — left defensive, with
  its docstring updated to note the read is now effectively always-available
  rather than best-effort, since narration runs strictly after every Phase-1 node
  joins.

## Story

**As** the content pipeline,
**I want** narration generation to run after `lesson_planner` has produced the
lesson outline, and a new stitching pass to smooth transitions across sections
before TTS synthesis,
**so that** narration can callback to earlier sections, reiterate concepts, and
read as one continuous voice — unblocking #233's single-continuous-transcript
requirement and improving every lesson generated today.

## Acceptance Criteria

### Functional

- [ ] **AC 1.** `_ECONOMY_NODES` and `_PHASE1_INSTRUMENTED_NODES` no longer contain
  `narration_generator` (5 entries each); the `embed → lesson_planner` join no
  longer includes `narration_generator`.
- [ ] **AC 2.** A new `_fan_out_narration_after_planning(state) -> list[Send]`
  router is dispatched via `add_conditional_edges` from `slide_generator`, one
  `Send("narration_generator", ...)` per entry in `state["lesson_plan"]["segments"]`
  (not per entry in `state["sections"]`, which may be longer than the actually-
  planned set if `_MAX_PHASE1_SECTIONS` truncation occurred upstream).
- [ ] **AC 3.** Each dispatch's payload correctly reconstructs the original
  `_section`/`_section_index` for its `segment_id` via a `sections_by_id` map built
  from `_derive_section_id(section, index)` over the full `state["sections"]`, and
  carries a new `_plan_segment: {"segment_id", "title", "continuity_notes"}` dict —
  not the whole `lesson_plan`.
- [ ] **AC 4.** `_fan_out_narration_after_planning` applies the same cost-ceiling
  fail-open check and empty-input guard as `_fan_out_phase1_economy_nodes` (same
  `llm_mini`-tier rationale).
- [ ] **AC 5.** `lesson_plan.segments[i].continuity_notes: str` is present on every
  segment (empty string, never null, when nothing to callback); the first segment
  in lesson order always has an empty value. Generated by extending
  `_LessonPlanSegmentLLM` and the planner prompt — no new LLM call, same call that
  already produces `title`/`duration_min`.
- [ ] **AC 6.** `narration_generator_node` reads `state["_plan_segment"]["continuity_notes"]`
  and, when non-empty, includes it in the user-role prompt message (same
  untrusted-content-guard region as `narration_style`). Checkpoint key
  (`f"narration_generator:{section_id}"`), pacing guard, and blank-script guard
  are unchanged.
- [ ] **AC 7.** New `narration_stitch_node`: runs once (not fanned out) after every
  `narration_generator` dispatch joins; sorts input via the existing
  `_segment_order_key`; makes one `llm_mini` structured-output call requesting
  transition phrasing + duplicate-phrasing trims while preserving the exact
  segment_id set/count/uniqueness (same guard shape as `lesson_planner_node`); on
  any guard failure, falls through to the unmodified-but-ordered scripts rather
  than failing the lesson.
- [ ] **AC 8.** `narration_stitch_node` applies `_apply_narration_char_cap` (moved
  verbatim from `tts_node`) to its (possibly-fallback) output and persists
  `node_outputs["narration_cap_applied"]` unconditionally, exactly as `tts_node`
  did before this story.
- [ ] **AC 9.** `narration_stitch_node` includes the `_warn_if_duplicated` canary
  (same pattern as `lesson_planner_node`/`tts_node`) since it is now a
  money-spending node consuming the `narration_scripts` fan-in reducer channel.
- [ ] **AC 10.** `narration_stitch_node` returns `{"narration_scripts_final": [...],
  "progress_pct": <milestone between slide_generator's 48.0 and tts_node's 86.0>}`
  — a new **plain** `PipelineState` field, no `operator.add` reducer (writing back
  into `narration_scripts` itself would double it per CLAUDE.md's reducer-channel
  rule, since this node runs once after the fan-in).
- [ ] **AC 11.** `tts_node` reads `narration_scripts_final` instead of
  `narration_scripts`; the `_apply_narration_char_cap` call and its degradation-
  record persistence are removed from `tts_node` (moved to AC 8).
- [ ] **AC 12.** `package_builder_node`'s two reads of `narration_scripts`
  (`_index_by_segment_id` primary index and the `_recoverable_script()` fallback)
  both become `narration_scripts_final`.
- [ ] **AC 13.** `modules/admin/router.py`'s narration-cap surfacing
  (`narration_capped` on `JobSummary`, from Story 3-37) still works — reads
  `node_outputs["narration_cap_applied"]` generically, unaffected by which node
  wrote it.
- [ ] **AC 14.** `test_phase1_economy_nodes.py::test_economy_nodes_run_before_lesson_planner_and_fan_out_per_section`
  is rewritten (with an inline comment explaining why, referencing #236) to assert:
  the 5 remaining economy nodes run before `lesson_planner`, once per section;
  `narration_generator` runs after both `lesson_planner` and `slide_generator`,
  once per section; `narration_stitch` runs exactly once, after every
  `narration_generator` call and before `tts_node`.
  `test_all_six_economy_nodes_present_in_graph` is fixed to check 5 economy names
  plus separate presence checks for `narration_generator`/`narration_stitch`.
- [ ] **AC 15.** `test_fan_out_state_keys.py` gains coverage for
  `_fan_out_narration_after_planning` mirroring its existing tier-key tests —
  every dispatched payload carries `_FAN_OUT_STATE_KEYS`, `_section`,
  `_section_index`, and `_plan_segment` (the exact class of bug this file exists
  to catch, named by the issue itself: D2's missing `"tier"` key).
- [ ] **AC 16.** `test_node_return_shape.py` (AST scan, repo-wide) passes unmodified
  — `narration_stitch_node` never spreads `**state`.
- [ ] **AC 17.** Guard-test check performed and listed here (CLAUDE.md's
  "Guard-test check before touching any module" rule): `grep -rn
  "test_.*graph\|test_.*narration\|test_no_hardcoded\|test_dunder_all"
  apps/api/tests/` run before implementation; every hit either covered by the ACs
  above or explicitly listed in the Dev Agent Record as unaffected-and-verified.
- [ ] **AC 18.** Full repo-wide regression (`tests/unit` + `tests/integration -m
  "not postgres"`, matching CI's gating scope) shows zero new failures vs. `main`.
- [ ] **AC 19.** `ruff check .`, `ruff format --check`, and `mypy app` (repo-wide,
  matching CI exactly) show zero new issues vs. `main`.

## Scale & Load

*(`docs/SCALE-CONTRACT.md` — six questions, contract-mandated on every story)*

1. **Unit of work, and its range.** One unit is one lesson's post-planner
   narration re-dispatch — same section-count range as Phase 1 today (bounded by
   `_MAX_PHASE1_SECTIONS = 60`, and in practice by whatever count actually reached
   `lesson_plan.segments`, which can only be `<=` the Phase-1 dispatched count).
   This story does not change the section-count range — it moves *when* the same
   N dispatches happen, not how many.
2. **Fixed budgets vs. variable input.** Two: (a) `_MAX_PHASE1_SECTIONS` — reused
   as-is for the new fan-out's own guard, same behavior (explicit truncation +
   warning log) as today, not silently uncapped. (b) `max_narration_chars_per_lesson`
   — the existing lesson-wide char cap, relocated but not resized or reinterpreted;
   it still produces the same explicit, surfaced degradation record
   (`node_outputs["narration_cap_applied"]`), just written by `narration_stitch_node`
   instead of `tts_node`. No new unbounded budget introduced by the stitching LLM
   call — it operates on the same already-capped-count narration list.
3. **Scope of every limit.** Per-lesson, unchanged from today — `_MAX_PHASE1_SECTIONS`
   and `max_narration_chars_per_lesson` are both keyed by the single `lesson_id`
   this pipeline run is for, not shared across users/instances.
4. **Unbounded reads/writes.** None introduced. The new fan-out router reads
   `state["sections"]` and `state["lesson_plan"]["segments"]` — both already
   in-memory pipeline state, not a new Supabase query. `narration_stitch_node`'s
   one new LLM call operates on the already-bounded `narration_scripts` list; its
   one new `node_outputs` write rides the same per-node checkpoint pattern every
   other sequential node in this file already uses (one row, keyed by `lesson_id`).
5. **Inherited caps re-derived?** `_MAX_PHASE1_SECTIONS` is inherited unchanged —
   re-derivation isn't needed because the unit of work (one section) hasn't
   changed, only the graph position of one of its consumers. `max_narration_chars_per_lesson`
   likewise: its value was re-derived against real cost data as recently as
   Story 3-45 (120,000 chars, ~80% of the $3.00 ceiling) — this story does not
   touch that number, only its enforcement location.
6. **Check-then-act under concurrency.** The new fan-out is `Send()`-dispatched
   concurrently (same as Phase 1), so narration's checkpoint write must stay on
   the atomic `merge_lesson_job_node_output` RPC path (`_write_phase1_checkpoint`)
   — verified unchanged and still called by `narration_generator_node`, since up
   to N concurrent post-planner dispatches now write to the same `lesson_jobs` row
   simultaneously, exactly the condition that RPC exists for. `narration_stitch_node`
   itself runs strictly sequentially (single node after the join, like
   `lesson_planner_node`/`slide_generator_node`), so its own checkpoint write uses
   the plain read-modify-write pattern those two nodes use — safe for the same
   reason theirs is (no concurrent writer to the same key in the same run).

**The one-line test, answered:** before this fix, a chapter's narration read as N
independent, voiceless monologues stitched together only by audio-file
concatenation — nothing was ever wrong loudly (every lesson "succeeded"), it was
wrong quietly, in narrative quality, for every lesson ever generated. After this
fix, narration generation has the lesson outline available, and a dedicated node
exists whose entire job is to make the final cross-section pass explicit and
verifiable, rather than silently absent.

## Tasks

### Task 1 — Guard-test survey (AC 17)
- [ ] 1.1 Run the CLAUDE.md-mandated grep across `apps/api/tests/` for every guard
  test touching `graph.py`/narration; list results in Dev Agent Record.

### Task 2 — RED
- [ ] 2.1 Write/update tests against the desired post-planner graph shape
  (AC 14, 15) and confirm they fail against the current (pre-fix) graph.

### Task 3 — GREEN: lesson_planner + schema
- [ ] 3.1 Add `continuity_notes` to `_LessonPlanSegmentLLM`, planner prompt, and
  `segments_out` assembly (AC 5).

### Task 4 — GREEN: graph wiring
- [ ] 4.1 Shrink `_ECONOMY_NODES`/`_PHASE1_INSTRUMENTED_NODES` to 5 (AC 1).
- [ ] 4.2 Add `_fan_out_narration_after_planning` (AC 2, 3, 4).
- [ ] 4.3 Add `PipelineState["narration_scripts_final"]`, add `narration_stitch_node`
  (AC 7, 8, 9, 10), rewire `slide_generator → narration fan-out → join →
  narration_stitch → tts_node`.
- [ ] 4.4 Update `narration_generator_node` to consume `_plan_segment` (AC 6).
- [ ] 4.5 Update `tts_node` (AC 11) and `package_builder_node` (AC 12) to read
  `narration_scripts_final`.
- [ ] 4.6 Verify `modules/admin/router.py` (AC 13).

### Task 5 — GREEN: tests
- [ ] 5.1 New `test_narration_stitch_node.py`; update `test_tts_node.py`;
  update `test_phase1_economy_nodes.py`/`test_fan_out_state_keys.py` (AC 14, 15);
  new lesson_planner `continuity_notes` coverage.
- [ ] 5.2 Full regression run, ruff/format/mypy (AC 18, 19).

### Task 6 — Review
- [ ] 6.1 6-agent `/bmad-code-review`.

### Task 7 — Commit
- [ ] 7.1 Story-first commit (this file alone).
- [ ] 7.2 Implementation commit(s).
- [ ] 7.3 `docs/dev1-tracker.md` entry referencing #236.

## Dev Agent Record

### Implementation Plan
See the approved plan at implementation time (`/Users/apple/.claude/plans/whimsical-tickling-rocket.md`
as of this story's creation) — summarized in Context & Scope Boundary above.

### Debug Log
_(filled in during implementation)_

### Completion Notes
_(filled in during implementation)_

### File List
_(filled in during implementation)_

### Change Log
- 2026-09-21: Story file created (story-first commit), branch
  `feature/236-narration-post-planner-ordering`.
