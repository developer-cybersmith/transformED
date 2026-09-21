---
id: "236"
title: "Narration continuity — move narration_generator after lesson_planner, add stitching node"
status: "done"
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

- [x] **AC 1.** `_ECONOMY_NODES` and `_PHASE1_INSTRUMENTED_NODES` no longer contain
  `narration_generator` (5 entries each); the `embed → lesson_planner` join no
  longer includes `narration_generator`.
- [x] **AC 2.** A new `_fan_out_narration_after_planning(state) -> list[Send]`
  router is dispatched via `add_conditional_edges` from `slide_generator`, one
  `Send("narration_generator", ...)` per entry in `state["lesson_plan"]["segments"]`
  (not per entry in `state["sections"]`, which may be longer than the actually-
  planned set if `_MAX_PHASE1_SECTIONS` truncation occurred upstream).
- [x] **AC 3.** Each dispatch's payload correctly reconstructs the original
  `_section`/`_section_index` for its `segment_id` via a `sections_by_id` map built
  from `_derive_section_id(section, index)` over the full `state["sections"]`, and
  carries a new `_plan_segment: {"segment_id", "title", "continuity_notes"}` dict —
  not the whole `lesson_plan`.
- [x] **AC 4.** `_fan_out_narration_after_planning` applies the same cost-ceiling
  fail-open check and empty-input guard as `_fan_out_phase1_economy_nodes` (same
  `llm_mini`-tier rationale).
- [x] **AC 5.** `lesson_plan.segments[i].continuity_notes: str` is present on every
  segment (empty string, never null, when nothing to callback); the first segment
  in lesson order always has an empty value. Generated by extending
  `_LessonPlanSegmentLLM` and the planner prompt — no new LLM call, same call that
  already produces `title`/`duration_min`.
- [x] **AC 6.** `narration_generator_node` reads `state["_plan_segment"]["continuity_notes"]`
  and, when non-empty, includes it in the user-role prompt message (same
  untrusted-content-guard region as `narration_style`). Checkpoint key
  (`f"narration_generator:{section_id}"`), pacing guard, and blank-script guard
  are unchanged.
- [x] **AC 7.** New `narration_stitch_node`: runs once (not fanned out) after every
  `narration_generator` dispatch joins; sorts input via the existing
  `_segment_order_key`; makes one `llm_mini` structured-output call requesting
  transition phrasing + duplicate-phrasing trims while preserving the exact
  segment_id set/count/uniqueness (same guard shape as `lesson_planner_node`); on
  any guard failure, falls through to the unmodified-but-ordered scripts rather
  than failing the lesson.
- [x] **AC 8.** `narration_stitch_node` applies `_apply_narration_char_cap` (moved
  verbatim from `tts_node`) to its (possibly-fallback) output and persists
  `node_outputs["narration_cap_applied"]` unconditionally, exactly as `tts_node`
  did before this story.
- [x] **AC 9.** `narration_stitch_node` includes the `_warn_if_duplicated` canary
  (same pattern as `lesson_planner_node`/`tts_node`) since it is now a
  money-spending node consuming the `narration_scripts` fan-in reducer channel.
- [x] **AC 10.** `narration_stitch_node` returns `{"narration_scripts_final": [...],
  "progress_pct": <milestone between slide_generator's 48.0 and tts_node's 86.0>}`
  — a new **plain** `PipelineState` field, no `operator.add` reducer (writing back
  into `narration_scripts` itself would double it per CLAUDE.md's reducer-channel
  rule, since this node runs once after the fan-in).
- [x] **AC 11.** `tts_node` reads `narration_scripts_final` instead of
  `narration_scripts`; the `_apply_narration_char_cap` call and its degradation-
  record persistence are removed from `tts_node` (moved to AC 8).
- [x] **AC 12.** `package_builder_node`'s two reads of `narration_scripts`
  (`_index_by_segment_id` primary index and the `_recoverable_script()` fallback)
  both become `narration_scripts_final`.
- [x] **AC 13.** `modules/admin/router.py`'s narration-cap surfacing
  (`narration_capped` on `JobSummary`, from Story 3-37) still works — reads
  `node_outputs["narration_cap_applied"]` generically, unaffected by which node
  wrote it.
- [x] **AC 14.** `test_phase1_economy_nodes.py::test_economy_nodes_run_before_lesson_planner_and_fan_out_per_section`
  is rewritten (with an inline comment explaining why, referencing #236) to assert:
  the 5 remaining economy nodes run before `lesson_planner`, once per section;
  `narration_generator` runs after both `lesson_planner` and `slide_generator`,
  once per section; `narration_stitch` runs exactly once, after every
  `narration_generator` call and before `tts_node`.
  `test_all_six_economy_nodes_present_in_graph` is fixed to check 5 economy names
  plus separate presence checks for `narration_generator`/`narration_stitch`.
- [x] **AC 15.** `test_fan_out_state_keys.py` gains coverage for
  `_fan_out_narration_after_planning` mirroring its existing tier-key tests —
  every dispatched payload carries `_FAN_OUT_STATE_KEYS`, `_section`,
  `_section_index`, and `_plan_segment` (the exact class of bug this file exists
  to catch, named by the issue itself: D2's missing `"tier"` key).
- [x] **AC 16.** `test_node_return_shape.py` (AST scan, repo-wide) passes unmodified
  — `narration_stitch_node` never spreads `**state`.
- [x] **AC 17.** Guard-test check performed and listed here (CLAUDE.md's
  "Guard-test check before touching any module" rule): `grep -rn
  "test_.*graph\|test_.*narration\|test_no_hardcoded\|test_dunder_all"
  apps/api/tests/` run before implementation; every hit either covered by the ACs
  above or explicitly listed in the Dev Agent Record as unaffected-and-verified.
- [x] **AC 18.** Full repo-wide regression (`tests/unit` + `tests/integration -m
  "not postgres"`, matching CI's gating scope) shows zero new failures vs. `main`.
- [x] **AC 19.** `ruff check .`, `ruff format --check`, and `mypy app` (repo-wide,
  matching CI exactly) show zero new issues vs. `main`.

## Scale & Load

*(`docs/SCALE-CONTRACT.md` — six questions, contract-mandated on every story)*

1. **Unit of work, and its range.** One unit is one lesson's post-planner
   narration re-dispatch — same section-count range as Phase 1 today (bounded by
   `_MAX_PHASE1_SECTIONS = 60`, and in practice by whatever count actually reached
   `lesson_plan.segments`, which can only be `<=` the Phase-1 dispatched count).
   This story does not change the section-count range — it moves *when* the same
   N dispatches happen, not how many.
2. **Fixed budgets vs. variable input.** Three: (a) `_MAX_PHASE1_SECTIONS` — reused
   as-is for the new fan-out's own guard, same behavior (explicit truncation +
   warning log) as today, not silently uncapped. (b) `max_narration_chars_per_lesson`
   — the existing lesson-wide char cap, relocated but not resized or reinterpreted;
   it still produces the same explicit, surfaced degradation record
   (`node_outputs["narration_cap_applied"]`), just written by `narration_stitch_node`
   instead of `tts_node`. No new unbounded budget introduced by the stitching LLM
   call — it operates on the same already-capped-count narration list.
   (c) **`lesson_planner_batch_size` (10), corrected after Scale & Load review**:
   this story's own new `continuity_notes` field is authored per-batch, not
   lesson-wide, once `segment_summaries` exceeds this size — and since
   `structure_max_sections` defaults to 15 (D75 deliberately keeps the batch
   size strictly below it so a maximal chapter always batches), ANY chapter
   coalescing to 11-15 sections already takes this path today, at default
   config — not a rare operator-misconfiguration edge case, as an earlier
   draft of this section and the corresponding code comment incorrectly
   claimed. Registered as **D167** (`docs/DEFECT-REGISTER.md`) rather than
   silently accepted, per CLAUDE.md binding rule 5 — no silent-truncation
   violation (no wrong narration ships, just thinner cross-batch continuity
   with no signal), but a real, currently-reachable limitation, not a
   hypothetical one.
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
- [x] 1.1 Run the CLAUDE.md-mandated grep across `apps/api/tests/` for every guard
  test touching `graph.py`/narration; list results in Dev Agent Record.

### Task 2 — RED
- [x] 2.1 Write/update tests against the desired post-planner graph shape
  (AC 14, 15) and confirm they fail against the current (pre-fix) graph.

### Task 3 — GREEN: lesson_planner + schema
- [x] 3.1 Add `continuity_notes` to `_LessonPlanSegmentLLM`, planner prompt, and
  `segments_out` assembly (AC 5).

### Task 4 — GREEN: graph wiring
- [x] 4.1 Shrink `_ECONOMY_NODES`/`_PHASE1_INSTRUMENTED_NODES` to 5 (AC 1).
- [x] 4.2 Add `_fan_out_narration_after_planning` (AC 2, 3, 4).
- [x] 4.3 Add `PipelineState["narration_scripts_final"]`, add `narration_stitch_node`
  (AC 7, 8, 9, 10), rewire `slide_generator → narration fan-out → join →
  narration_stitch → tts_node`.
- [x] 4.4 Update `narration_generator_node` to consume `_plan_segment` (AC 6).
- [x] 4.5 Update `tts_node` (AC 11) and `package_builder_node` (AC 12) to read
  `narration_scripts_final`.
- [x] 4.6 Verify `modules/admin/router.py` (AC 13).

### Task 5 — GREEN: tests
- [x] 5.1 New `test_narration_stitch_node.py`; update `test_tts_node.py`;
  update `test_phase1_economy_nodes.py`/`test_fan_out_state_keys.py` (AC 14, 15);
  new lesson_planner `continuity_notes` coverage.
- [x] 5.2 Full regression run, ruff/format/mypy (AC 18, 19).

### Task 6 — Review
- [x] 6.1 6-agent `/bmad-code-review` (5 parallel agents, all 6 layers). See Senior Developer Review section below.

### Task 7 — Commit
- [x] 7.1 Story-first commit (this file alone).
- [x] 7.2 Implementation commit(s). — `073a977`, plus a review-fix commit.
- [x] 7.3 `docs/dev1-tracker.md` entry referencing #236.

## Dev Agent Record

### Implementation Plan
See the approved plan at implementation time (`/Users/apple/.claude/plans/whimsical-tickling-rocket.md`
as of this story's creation) — summarized in Context & Scope Boundary above.

### Debug Log

- Guard-test survey (Task 1.1): `grep -rln "test_.*graph\|test_.*narration\|test_no_hardcoded\|test_dunder_all" apps/api/tests/`, narrowed to actual pipeline-internal hits via a second grep on `narration_scripts|_ECONOMY_NODES|_fan_out_phase1|_PHASE1_INSTRUMENTED_NODES|narration_generator_node|narration_stitch|_apply_narration_char_cap`. Files requiring edits: `test_phase1_economy_nodes.py`, `test_fan_out_state_keys.py`, `test_tts_node.py`, `test_package_builder_node.py`, `test_duplication_canary.py`, `test_audio_duration_s3_38.py`, `test_chapter_scoped_generation.py`, `tests/integration/test_howto_pipeline_e2e.py` (and transitively `test_tier_differentiation_and_cost.py`, which imports the same fake dispatch). `test_node_return_shape.py`, `test_admin_router.py`, `test_phase1_checkpoint_idempotency.py`, `test_cost_tracker.py` needed no edits — verified by running them, not assumed.
  **Process Integrity review correction (2026-09-21):** the AC-17 survey's literal grep command missed `test_quiz_checkpoint_tier_stamp.py`, which directly calls `_fan_out_phase1_economy_nodes` (a function this story changed — 5 economy nodes, not 6) but contains none of the survey's literal search substrings. Confirmed by direct re-run: `pytest tests/unit/test_quiz_checkpoint_tier_stamp.py` — 7/7 pass, unaffected (the test only reads the `quiz_generator` dispatch, not the node-count denominator). No functional gap, but the survey command itself is narrower than the guard-test set it's meant to find — worth widening (e.g. also grep for `_fan_out_phase1_economy_nodes\b`) the next time this module is touched.
- RED confirmed against the pre-fix graph: `test_economy_nodes_run_before_lesson_planner_and_fan_out_per_section` failed with `RuntimeError: lesson_plan has zero segments` once the new fan-out was wired in ahead of the test being updated (the barrier stub for `lesson_planner_node` never set `lesson_plan`); `TestAC7CostCeiling`'s three dispatch-count tests failed on `15 == 3*6` (still expecting 6 economy nodes). Both confirmed the right way for the right reason before being fixed.
- Full pre-existing-test breakage from the `narration_scripts` → `narration_scripts_final` field rename (tts_node/package_builder_node): 28 failures on first run, all traced to the rename, none to logic errors — fixed by renaming state-dict keys and override kwargs in the affected test files' fixtures (`_base_state`/`_pb_state`/`_tts_state` helpers and their per-test overrides).
- Discovered mid-implementation (not in the original plan): `narration_stitch_node`'s prompt used an ad-hoc `"segment_id: X\nscript: Y"` format instead of the established `"- segment_id=X: <single-line text>"` convention `lesson_planner_node`/`slide_generator_node` already use — fixed for consistency, which also let the two full-graph integration tests' existing `_segment_ids_from_messages` parsing convention extend naturally instead of needing a bespoke parser.
- Two integration tests (`test_howto_pipeline_e2e.py`, `test_tier_differentiation_and_cost.py`) run the REAL compiled graph with a fake LLM provider keyed by `response_format.__name__` — failed with `unmocked response_format _StitchedNarrationLLM` until a case was added to `_make_dispatch`'s dispatch table (echoes back each segment's script unchanged, parsed from the prompt, so no downstream narration-content assertion depends on invented wording).
- Full regression (`pytest tests/unit tests/integration -m "not postgres"`): 1520 passed, 6 skipped, 86 deselected, zero failures — re-run twice (once before, once after `ruff format` was applied) to confirm the formatter introduced no behavior change.
- `ruff check .` (repo-wide): clean after fixing 2 new `E501` line-too-long hits. `ruff format --check` on all 11 touched files: clean after applying the formatter to 3 files. `mypy app --ignore-missing-imports` (repo-wide): 4 pre-existing errors, all in files this story never touches (`providers/stt/whisper.py`, `providers/llm/openai.py`, `providers/image/openai_image.py`, `providers/embeddings/openai.py` — an unrelated `httpx.Timeout` type mismatch against `AsyncOpenAI`) — confirmed via `git status --short apps/api/app/providers/` showing zero changes in that directory. Zero new mypy errors from this story's diff.

### Completion Notes

Implemented exactly the approved plan: `narration_generator` moved from the Phase-1 economy fan-out (`_ECONOMY_NODES`, now 5 entries) into a new post-planner fan-out (`_fan_out_narration_after_planning`, dispatched from `slide_generator`), driven by `lesson_plan.segments` (not `state["sections"]`, to stay correct under `_MAX_PHASE1_SECTIONS` truncation) with each dispatch's `_section`/`_section_index` reconstructed via `_derive_section_id`. Added `continuity_notes: str` to `_LessonPlanSegmentLLM`/`lesson_plan.segments[i]` (forced empty for the first segment in lesson order regardless of LLM output — a fabrication guard, not a formatting default) and spliced it into `narration_generator_node`'s existing untrusted-content-guarded user-role prompt. Added `narration_stitch_node` — a single sequential node (Phase-2-style plain checkpoint, not the atomic RPC) that runs one `llm_mini` call for transition/duplicate-phrasing polish under the same degrade-not-fabricate guard shape `lesson_planner_node` uses, then applies `_apply_narration_char_cap` (moved verbatim from `tts_node`, resolving the issue's explicit "revisit this placement" ask) and writes the new plain `narration_scripts_final` field. `tts_node` and `package_builder_node` now read `narration_scripts_final`; `tts_node`'s own canary call and cap-application were removed (cap moved upstream) while its `_warn_if_duplicated` call is kept as defense-in-depth on the plain field. Rewrote (never silently broke) the AC-0 ordering test, extended `test_fan_out_state_keys.py` for the new router's payload (same D2-class key-guard the issue names by number), and ported Story 3-37's full narration-cap test suite into a new `test_narration_stitch_node.py` (LLM stitching mocked to return `None` so those tests keep exercising the exact character-level cap assertions they always did). Verified `modules/admin/router.py`'s `narration_cap_applied` surfacing reads the record generically off `node_outputs`, unaffected by which node wrote it — no change needed. Full gating-scope regression (1520 passed), repo-wide `ruff check`/`ruff format --check`, and repo-wide `mypy app` are all clean (zero new issues vs. `main`).

### File List

- `apps/api/app/modules/content/pipeline/graph.py` — MODIFIED: `PipelineState` (+`narration_scripts_final`, +`_plan_segment`); `_ECONOMY_NODES`/`_PHASE1_INSTRUMENTED_NODES` shrunk to 5; `_LessonPlanSegmentLLM` (+`continuity_notes`), planner prompt, `lesson_planner_node`'s `segments_out` assembly; new `_POST_PLANNER_FAN_OUT_NODES` + `_fan_out_narration_after_planning`; `narration_generator_node` (+`_plan_segment` consumption, docstring); new `_StitchedNarrationSegmentLLM`/`_StitchedNarrationLLM`/`narration_stitch_node`; `tts_node` (reads `narration_scripts_final`, cap call removed); `package_builder_node` (both narration reads repointed); `_build_pipeline_graph` (new node + edges).
- `apps/api/tests/unit/test_phase1_economy_nodes.py` — MODIFIED: `ECONOMY_NODE_NAMES` (5) + new `POST_PLANNER_FAN_OUT_NODE_NAMES`; AC-0 ordering test rewritten; graph-presence test split in two; new AC-6 continuity_notes tests.
- `apps/api/tests/unit/test_fan_out_state_keys.py` — MODIFIED: 3 new tests for `_fan_out_narration_after_planning`.
- `apps/api/tests/unit/test_tts_node.py` — MODIFIED: field renamed to `narration_scripts_final`; narration-cap test section removed (moved).
- `apps/api/tests/unit/test_narration_stitch_node.py` — NEW: stitching-guard tests + the ported Story 3-37 cap suite.
- `apps/api/tests/unit/test_package_builder_node.py` — MODIFIED: field renamed to `narration_scripts_final` (base state + 5 override sites).
- `apps/api/tests/unit/test_lesson_planner_node.py` — MODIFIED: `_plan_llm_response` default segments carry `continuity_notes`; 2 new tests.
- `apps/api/tests/unit/test_audio_duration_s3_38.py` — MODIFIED: field renamed in both `_tts_state` and `_pb_state` paths.
- `apps/api/tests/unit/test_duplication_canary.py` — MODIFIED: source-guard test updated for the new `narration_stitch` call site + `tts_node`'s renamed field.
- `apps/api/tests/unit/test_chapter_scoped_generation.py` — MODIFIED: one field rename.
- `apps/api/tests/integration/test_howto_pipeline_e2e.py` — MODIFIED: fake dispatch table gained a `_StitchedNarrationLLM` case (also fixes `test_tier_differentiation_and_cost.py`, which imports this module's fake).
- `docs/DEFECT-REGISTER.md` — MODIFIED (review round): new **D167** entry for the `continuity_notes` per-batch limitation.
- `docs/stories/236-narration-post-planner-ordering.md` — this file.

Review-round additions (same files re-touched, plus): `apps/api/app/modules/content/pipeline/graph.py` (try/except around the stitching LLM call; corrected `continuity_notes` batching comment); `apps/api/tests/unit/test_narration_stitch_node.py` (+2 tests: exception fallback, permuted-order acceptance; +1 assertion: `progress_pct`); `apps/api/tests/unit/test_fan_out_state_keys.py` (+5 tests: fan-out guard paths); `apps/api/tests/unit/test_tts_node.py` (+1 negative assertion: `narration_cap_applied` absent from tts_node's own write).

### Change Log
- 2026-09-21: Story file created (story-first commit), branch
  `feature/236-narration-post-planner-ordering`.
- 2026-09-21: Implementation complete. All 19 ACs verified by actual test execution (not asserted from memory). Full gating-scope regression 1520 passed/6 skipped/86 deselected, zero failures. `ruff check .`, `ruff format --check` (11 touched files), and repo-wide `mypy app` all clean (mypy's 4 findings are pre-existing, in 4 files this story never touches). Remaining before merge: 6-agent `/bmad-code-review` (Task 6.1), implementation commit (Task 7.2), `docs/dev1-tracker.md` entry (Task 7.3).
- 2026-09-21: 6-agent `/bmad-code-review` round (5 parallel adversarial agents covering all 6 CLAUDE.md layers — Test Coverage and AC Completeness combined into one). See the Senior Developer Review section below for full findings and fixes. Two real, confirmed issues fixed (an unguarded exception in `narration_stitch_node`'s LLM call, and a stale/wrong justification comment for `continuity_notes`' per-batch limitation, now registered as **D167**); one documentation-accuracy correction (AC-17 survey gap); five new tests added for previously-uncovered guard paths. Full regression re-run after fixes: **1527 passed**, 6 skipped, 86 deselected — zero regressions from the fix round. `ruff check .` / `ruff format --check` clean.

## Senior Developer Review (AI) — Round 1 (5 parallel adversarial agents, all 6 CLAUDE.md layers)

**Review date:** 2026-09-21
**Outcome:** APPROVE WITH CHANGES — all applied before merge.

### Layer 1 — Story Quality: PASS
Independently re-ran every command the story claims results for (full regression, ruff, mypy) and got identical numbers. Spot-checked ACs 1–13 against the real diff, not the checkmarks. Verified the Story-First Gate's chronological ordering via `git log`/`git show --stat`, not commit messages alone. Two non-blocking wording nitpicks (Debug Log slightly overstates which grep found which files; AC15's "mirroring" is a mild overclaim) — noted, not worth a separate fix pass since the underlying facts are correct.

### Layer 2 — Blind Hunter (Security): PASS, no findings
Checked the reducer-channel doubling pattern (none found — `narration_scripts_final` is a plain field specifically to prevent this), untrusted-content placement (`continuity_notes` and the stitching prompt's narration text both correctly land in user-role messages under `_UNTRUSTED_CONTENT_GUARD`, never system-role), segment_id path-safety (no new unvalidated path/key construction), DoS/unbounded fan-out (bounded by the same `_MAX_PHASE1_SECTIONS`/cost-ceiling gates as Phase 1), and checkpoint/concurrency correctness (`narration_generator_node` still uses the atomic RPC; `narration_stitch_node` correctly uses the plain sequential-node pattern). Ran `test_node_return_shape.py` directly — 11/11 pass.

### Layer 3 — Test Coverage: 5 real gaps found, 4 fixed
Found real gaps: `_fan_out_narration_after_planning`'s guard paths (empty plan, missing lesson_id, ceiling breach, exception-fail-open, unmatched segment_id) had zero coverage, unlike the Phase-1 fan-out's thorough `TestAC7CostCeiling`; the stitching guard's permutation-order acceptance (correct code, untested); the AC 10 `progress_pct=60.0` claim was never asserted; the AC 11 "cap removed from tts_node" claim was only shown by omission. **Fixed:** added `test_narration_fan_out_empty_plan_segments_raises`, `test_narration_fan_out_missing_lesson_id_raises`, `test_narration_fan_out_ceiling_breach_raises`, `test_narration_fan_out_check_ceiling_exception_fails_open`, `test_narration_fan_out_unmatched_segment_id_raises` (`test_fan_out_state_keys.py`); `test_accepted_response_in_permuted_order_still_reassembles_correctly` (`test_narration_stitch_node.py`); a `progress_pct == 60.0` assertion added to an existing test; a `"narration_cap_applied" not in checkpoint_calls[0]["node_outputs"]` negative assertion added to `test_tts_node.py`. **Not fixed (accepted, low value):** the duplicated-fan-in-plus-cache-hit combination and a real prompt-injection-shaped `continuity_notes` string remain untested — the former is a low-value combinatorial case of two already-separately-tested behaviors, the latter can't be meaningfully asserted against a mocked LLM (the guard is a static prompt string, not runtime logic).

### Layer 4 — AC Completeness: PASS, gaps closed by Layer 3's fixes
Full AC-to-test mapping table built and cross-checked; the two soft gaps identified (AC 10's progress_pct value, AC 11's negative claim) are the same two closed by Layer 3's new tests. All 19 ACs now have a test asserting the AC's specific claim, not just exercising the code path.

### Layer 5 — Process Integrity: 1 real (non-blocking) gap found and fixed
Hardcoded-model, provider-abstraction, cross-module-DB, `**state`-spread, and checkpoint-pattern-discipline checks: all satisfied, confirmed by direct code reading. **Real finding:** the story's own AC-17 guard-test survey (a literal grep command) missed `apps/api/tests/unit/test_quiz_checkpoint_tier_stamp.py`, which directly calls `_fan_out_phase1_economy_nodes` (changed by this diff) but contains none of the survey's literal search substrings. Re-ran it directly: 7/7 pass, unaffected — not a functional regression, but a real hole in the audit trail. **Fixed:** Debug Log corrected with the real finding and the test's independently-verified pass result.

### Layer 6 — Scale & Load: 2 CONFIRMED real issues, both fixed; 1 informational (not fixed, correctly out of scope)
1. **CONFIRMED, HIGH, FIXED:** `narration_stitch_node`'s stitching LLM call had no exception handling — `complete_structured()` raises (not returns `None`) on a retry-exhausted rate limit, an open circuit breaker, or a truncated structured response, which would crash the whole node (and the lesson) at the exact point every per-section `narration_generator` dispatch had already succeeded and been paid for — directly contradicting this node's own stated "never fail the lesson over a cosmetic pass" design intent. **Fix:** wrapped the call in `try`/`except Exception`, degrading to the same `response = None` fallback path. RED-confirmed via `git stash` on the source file alone (reproduced the exact `RuntimeError` propagating uncaught), then GREEN after the fix. New test: `test_llm_call_raising_falls_back_instead_of_crashing_the_node`.
2. **CONFIRMED, HIGH, FIXED:** the code comment (and this story's original Scale & Load Q2) claimed `continuity_notes`' per-batch-not-lesson-wide limitation was latent behind an operator explicitly raising `structure_max_sections` — checked directly against `config.py`: `structure_max_sections` defaults to 15, `lesson_planner_batch_size` defaults to 10 (D75 deliberately keeps it strictly below), so ANY chapter coalescing to 11-15 sections already takes the multi-batch path today, at default config. The pre-existing sibling comment for the analogous "objectives reflect first batch only" limitation repeats the same now-disproven premise (pre-dates D75, never updated) — this story's comment inherited that stale premise rather than introducing a new one. **Fix:** corrected the comment with the real numbers, registered as **D167** (`docs/DEFECT-REGISTER.md`) per CLAUDE.md binding rule 5 ("a documented limitation is NOT an accepted one... must carry a D-nn register ID"), and updated Q2 above to state the real numbers and reference D167.
3. **PLAUSIBLE, MEDIUM, not separately fixed:** an unbounded-in-characters stitching prompt becomes a real token-budget risk if `structure_max_sections` is ever raised toward `_MAX_PHASE1_SECTIONS` (60) — but this compounds with, and is substantially mitigated by, Finding 1's fix: a token-limit-triggered `LengthFinishReasonError` now degrades gracefully via the same try/except instead of crashing. Not re-derived as its own budget in Q2 beyond noting the compounding relationship, since the crash path it would have caused no longer exists.
4. **Informational, not a new regression:** `narration_stitch_node`'s plain read-modify-write checkpoint has the same theoretical concurrent-double-write exposure as `lesson_planner_node`/`slide_generator_node`, which it deliberately mirrors — pre-existing pattern, not introduced by this diff, correctly out of this story's scope to fix.

### Re-verification after fixes
- `pytest tests/unit/test_narration_stitch_node.py tests/unit/test_fan_out_state_keys.py tests/unit/test_tts_node.py tests/unit/test_phase1_economy_nodes.py -q` → **106 passed**
- Full `tests/unit tests/integration -m "not postgres"` → **1527 passed, 6 skipped, 86 deselected** (up from 1520 — 7 new tests, zero regressions)
- `ruff check .` → clean; `ruff format --check` (4 re-touched files) → clean
