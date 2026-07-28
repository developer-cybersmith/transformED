---
baseline_commit: cdc984eb126c1eb9e4c3711200284b1129923935
---

# Story 2.16: Fix Content-Pipeline Over-Segmentation Blocker (structure detection + `lesson_planner`)

Status: review

> **BUG / BLOCKER story.** This is a defect fix, not a feature. It unblocks the whole team: Phase B chapter generation currently hard-fails on a common document type (step-by-step how-to PDFs), so no lesson can be produced from that content and all downstream work (player, quiz, CES demo) is stalled behind it. Priority: immediate.

## Story

As a **student (or any dev running the pipeline) who uploads a step-by-step how-to chapter**,
I want chapter generation to produce a coherent, sanely-segmented lesson instead of crashing,
so that the pipeline completes end-to-end for how-to / instructional PDFs the same way it does for prose textbook chapters.

This story fixes the production blocker reported by Dev 2 on 2026-07-22 and verified by a 5-agent adversarial code audit (3/3 root-cause findings CONFIRMED — see **Dev Notes → Root-Cause Analysis**). It touches Dev 1's content-pipeline module only:
- `apps/api/app/modules/content/pipeline/nodes/structure_detection.py` (`build_section_bodies`)
- `apps/api/app/modules/content/pipeline/graph.py` (`structure_node`, `lesson_planner_node`)
- `apps/api/app/config.py` (three new tunable settings)

## Observed Failure (reproduction)

A Windows Task Manager how-to PDF (105,248 chars) uploaded through the normal flow:

1. `structure_node` logged: `LLM sections cover 5958/105248 chars (< 90%) — rejecting LLM output, keeping rule-based sections`.
2. Rule-based detection produced **44 sections** — individual numbered instructional steps ("`1. Click End Process Tree`", "`2.3 Scroll through the counters`") were treated as structural headings.
3. All 44 segments passed Phase 1 (summarise/quiz/complexity/jargon/intervention/narration).
4. Phase 2 `lesson_planner_node` asked GPT-4o for exactly 44 outline segments in one completion; the model returned **10**; the `segment count mismatch — expected 44, got 10` guard raised `RuntimeError` and failed the whole job.

## Root-Cause Analysis (three stacked defects — all CONFIRMED by audit)

**RC-1 — Over-segmentation (root cause).** `structure_detection.py` regexes (`_CHAPTER_RE` bare-number branch `\d+\.\s+[A-Z].{3,}`, `_SECTION_RE`, `_TOPIC_RE`, all `re.MULTILINE`) match every numbered how-to step as a heading candidate, and `build_section_bodies` emits exactly one section per candidate with **no coalescing and no minimum-body floor**. Result: 44 step-level "sections."

**RC-2 — Dead LLM-validation fallback (latent).** `_build_structure_prompt` shows the LLM only `raw_text[:6000]`; the adoption guard requires `llm_total ≥ 0.9 × len(raw_text)`. For any chapter longer than **6000 / 0.9 ≈ 6,666 chars**, the LLM (having seen ≤6000 chars) can never cover ≥90% of the full text, so its output is *always* rejected and the over-segmenting rule-based path *always* wins. The LLM correction path is effectively dead code at production document sizes. **Deferred — see Scope.**

**RC-3 — Brittle strict-1:1 planner guard (latent).** Phase 1 is `Send()`-dispatched once per section, so N sections → N `segment_summaries` → `lesson_planner_node` demands a single structured completion echo back **exactly N** `segment_id`s unchanged. LLM enumeration-collapse over long lists is a well-known failure mode; the count varies run-to-run because a failed `summarise_segment` returns `[]` and is skipped. Under cost-ceiling downshift the *weaker* `llm_mini` model is asked to echo all N ids, making collapse **more** likely exactly when a lesson is already expensive.

## Scope Decision (what this story fixes vs defers)

| Layer | Decision | Rationale |
|-------|----------|-----------|
| RC-1 over-segmentation | **FIX** (AC-1) | Root cause. Text-preserving coalesce; **regexes left untouched** to avoid regressing legitimate numbered headings ("1. Introduction"). |
| RC-3 planner brittleness | **FIX** (AC-2) | Defense-in-depth so genuinely long (15–60-section) chapters are robust for all devs, without weakening any existing guard. |
| RC-2 dead LLM validation | **DEFER → Story 2-17** (AC-4) | Proper fix is a boundary-only LLM redesign (LLM returns heading offsets, Python slices bodies losslessly). Too large/risky for an urgent hotfix; **non-blocking once RC-1 bounds section count** (rule-based output is now sane). A one-line window/guard "fix" is explicitly rejected — it reintroduces silent post-6000-char data loss. |

## Acceptance Criteria

1. **AC-1 — Bounded, text-preserving section count (RC-1).** `structure_detection.py` gains a pure `coalesce_sections(sections, *, min_chars, max_sections)` pass, invoked by `structure_node` on the FINAL `sections_list` (after the LLM-vs-rule decision, so it bounds either path). It (a) merges any section whose `body` length is below `min_chars` into an adjacent kept section, and (b) if the count still exceeds `max_sections`, greedily merges adjacent sections (smallest-combined-body first) until `len(sections) ≤ max_sections`. **No text is ever dropped** — merged bodies concatenate (title of the absorbed section is folded into the body). A 44-step how-to PDF yields `≤ max_sections` sections. The regexes in `detect_headings` are NOT modified.

2. **AC-2 — Planner resilient to high segment counts (RC-3), guards intact.** `lesson_planner_node`: when `len(segment_summaries) > settings.lesson_planner_batch_size`, split the summaries into ordered batches of `≤ batch_size`, call `complete_structured` once per batch (same `settings.llm_lesson_planner` alias / provider / downshift path), and concatenate the segments before running the EXISTING degrade-not-fabricate guards on the assembled plan. When `len(segment_summaries) ≤ batch_size`, behaviour is **byte-identical to today** (a single call). Every existing guard (count-mismatch, unknown id, duplicate id, blank title/subject, non-positive/non-finite `duration_min`, empty objectives) is preserved and still `raise`s on a genuine defect — batching only makes each call small enough that faithful echo is reliable; it never fabricates (each batch echoes real input summaries).

3. **AC-3 — New settings, env-overridable, no hardcoded values.** `apps/api/app/config.py` gains: `structure_min_section_chars: int = 200`, `structure_max_sections: int = 15`, `lesson_planner_batch_size: int = 15`. All are pydantic-settings fields overridable by env var, following the existing `chunk_target_tokens` / CES-weight pattern. No model strings are hardcoded anywhere (planner still uses `settings.llm_lesson_planner` / `settings.llm_mini`).

4. **AC-4 — RC-2 documented and deferred, not silently touched.** `structure_node`'s LLM-adoption logic (6000-char prompt, 90%-coverage guard) is left functionally unchanged. A code comment references follow-up **Story 2-17 (boundary-only LLM structure validation)** and states the ≈6,666-char unsatisfiability limitation explicitly. A stub story file `docs/stories/2-17-boundary-only-structure-validation.md` (Status: backlog) is created capturing the redesign. **The window/guard one-liner (comparing against `min(len(raw_text), 6000)`) is explicitly forbidden** — it accepts LLM output covering only the first 6000 chars, silently discarding the rest, violating degrade-not-fabricate.

5. **AC-5 — Regression-safe + new coverage.** Existing test *assertions* are unchanged; three test files' settings-mock fixtures (`test_structure_node.py`, `test_lesson_planner_node.py`, `test_pipeline_tier1.py`) gain the three new numeric settings fields — a foreseen fixture-plumbing change (the `int < MagicMock` break from extending `Settings`), not an assertion/logic change, and set to no-op coalesce bounds so those tests keep exercising exactly what they did before. Coalescing defaults are calibrated so `test_ac11_multi_heading_chapter_produces_three_or_more_sections` still yields ≥3. New tests added:
   - `test_coalesce_collapses_oversegmented_howto_via_cap` / `test_coalesce_merges_subfloor_sections` — ~44 "step" sections → `≤ structure_max_sections`.
   - `test_coalesce_preserves_all_body_text_and_titles` / `test_coalesce_folds_absorbed_titles_into_body` — every original body **and title** substring survives (no data loss).
   - `test_coalesce_first_section_below_floor_folds_forward` — the sub-floor first-section forward-merge edge.
   - `test_coalesce_cap_buckets_are_contiguous` — the O(n) bucketing groups sections contiguously.
   - `test_coalesce_below_cap_and_above_floor_is_noop`, `test_coalesce_max_sections_zero_disables_cap`, `test_coalesce_single_subfloor_section_is_kept`, `test_coalesce_empty_list_returns_empty`, `test_coalesce_merged_section_spans_both_page_ranges` — no-op / degenerate branches.
   - `test_config_defaults_and_planner_batch_invariant` — defaults 200/15/15, the `structure_max_sections ≤ lesson_planner_batch_size` invariant, and the `gt=0`/`ge=1` Field guards.
   - `test_structure_node_coalesces_oversegmented_rule_based`, `test_structure_node_coalesces_adopted_llm_output`, `test_structure_node_keeps_three_headed_sections_post_coalesce` — node-level wiring on **both** the rule-based and adopted-LLM paths, plus the ≥3 calibration margin.
   - `test_planner_batches_above_threshold_produces_full_plan`, `test_planner_single_call_path_unchanged_below_threshold`, `test_planner_batch_boundaries` (n = 15/16/30), `test_planner_batched_dropped_id_still_rejected`, `test_planner_batched_duplicate_id_count_preserved_still_rejected` — batching happy path, boundaries, and both count-shrinking and count-preserving guard-integrity cases.
   - Existing `test_mismatched_segment_count_is_rejected_not_checkpointed` / `test_unknown_segment_id_is_rejected` remain green (single-call path).

6. **AC-6 — Architectural constraints preserved.** degrade-not-fabricate (all merges/batches are text-preserving and echo real content); no hardcoded models; hierarchical Chapter→Section→Topic processing (no full-chapter single call introduced); `lesson_planner_node` still receives `segment_summaries` only, never raw text (AC-1 of Story 2-6 / the 5× cost constraint); `providers/` abstraction respected (all LLM calls via `get_llm_provider` / `complete_structured`).

## Tasks / Subtasks

- [x] Task 1: Config (AC-3) — ✓ 2026-07-22
  - [x] 1.1 Added `structure_min_section_chars` (200), `structure_max_sections` (15), `lesson_planner_batch_size` (15) to `Settings` in `config.py` (pydantic `Field`, env-overridable).
- [x] Task 2: Coalesce pass (AC-1) — ✓ 2026-07-22
  - [x] 2.1 Added pure `coalesce_sections(sections, *, min_chars, max_sections)` + `_merge_two` helper to `structure_detection.py` — sub-floor merge then greedy smallest-adjacent-pair merge to cap; text-preserving (title folded into body); re-sequences `id`; merged section spans both page ranges and adopts the coarsest level.
  - [x] 2.2 Called from `structure_node` on the final `sections_list` (after LLM/rule decision, before checkpoint), logging before→after counts.
- [x] Task 3: Planner batching (AC-2) — ✓ 2026-07-22
  - [x] 3.1 Extracted `_planner_system_prompt` + `async _run_planner_batch`; added batch dispatch above `settings.lesson_planner_batch_size`; concatenated batch segments into a reassembled `_LessonPlanLLM` and ran the EXISTING guard block once on it. ≤ threshold → single call, unchanged.
- [x] Task 4: RC-2 deferral (AC-4) — ✓ 2026-07-22
  - [x] 4.1 Added the RC-2 explaining comment + Story 2-17 reference in `structure_node` (with the explicit "do NOT compare against min(len,6000)" warning).
  - [x] 4.2 Created `docs/stories/2-17-boundary-only-structure-validation.md` (Status: backlog).
- [x] Task 5: Tests (AC-5) — ✓ 2026-07-22 — new `test_coalesce_sections.py` (7), planner batch tests + node-wiring test; settings mocks extended for the new fields.
- [x] Task 6: Full-suite regression + ruff + mypy green — ✓ 2026-07-22 — 459 passed / 1 skipped; ruff check + format clean; `mypy app` = 215 (baseline, zero new). No `dev1-tracker.md` task maps to this bug story.

## Dev Notes

### Verified line references (baseline `cdc984e`)
- `structure_detection.py:24-26` regexes; `detect_headings` 29-98; `build_section_bodies` 106-155 (the 1-candidate→1-section loop at 131-153).
- `graph.py:447-455` `_build_structure_prompt` (the `raw_text[:6000]` preview); `structure_node` 459-563 (LLM adoption guard 530-540; final `sections_list` + checkpoint 550-563).
- `graph.py` `lesson_planner_node` 1039-1260 (single `complete_structured` at 1172; guard block 1184-1224; assembly 1243-1259).
- `graph.py:3490` `_MAX_PHASE1_SECTIONS = 60` fan-out cap (independent DoS bound; unchanged here — note `structure_max_sections=15` now bounds well below it).

### Coalesce design (Task 2) — must-not-lose-text
Iterate sections in order accumulating into a "kept" list: append each section's `title + "\n" + body` to a running buffer; start a new kept-section when the running body reaches `min_chars`. Then, while `len(kept) > max_sections`, merge the adjacent pair with the smallest combined body length. Re-sequence `id` as `s0..sN`; a merged section's `page_start` = first member's, `page_end` = last member's, `level` = the coarsest (chapter < section < topic) among members, `title` = first member's title. Guard the first-section-sub-floor edge (merge forward into the next kept section, or keep as sole seed if it is the only one). **Do not** merge across a genuine `chapter`-level boundary if doing so would drop below the AC-11 ≥3 expectation — calibration: with `min_chars=200`, the AC-11 test's headed sections must exceed 200 chars; verify during RED and lower the default only if that test would otherwise regress (prefer adjusting the test fixture's body length is NOT allowed — the default must accommodate the existing contract).

### Planner batching (Task 3) — preserve guard semantics exactly
Batching changes only HOW the LLM is called, not WHAT is validated. Build `messages` per batch from that batch's summaries (same system prompt, same `tier_framing`, same `_UNTRUSTED_CONTENT_GUARD`), call `complete_structured` per batch, collect `response.segments` across batches into one list, synthesize the plan-level fields (title/subject/objectives/complexity) from the FIRST batch's response (or a dedicated tiny plan-level call — implementer's choice, but do not add a second model alias). Then run the identical guard block (1184-1224) against the assembled `segments` vs the full `segment_summaries`. This guarantees a batch that drops/duplicates an id is still caught. Keep `total_duration_min = sum(...)` over the assembled segments (AC-7 of Story 2-6).

### What must be preserved (read before editing)
- `lesson_planner_node` idempotency checkpoint (node_outputs cache) and progress 38.0.
- The cost-ceiling downshift block (`over_ceiling` default-True on `check_ceiling` failure).
- `structure_node` idempotency cache + empty-`raw_text` short-circuit (line 506).
- `_fan_out_phase1_economy_nodes` behaviour is unchanged; fewer sections simply mean fewer dispatches.

### Constraints (CLAUDE.md)
No Celery / PostgresSaver; no `fitz`/PyMuPDF; providers abstraction only; pin LangGraph; `settings.llm_*` aliases only; degrade-not-fabricate; planner input is summaries only.

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-22 | Bug story created from Dev 2 blocker report + 5-agent audit (3/3 root causes CONFIRMED). Scope: fix RC-1 + RC-3, defer RC-2 to Story 2-17. | Dev 1 (BMAD create-story) |

## Senior Developer Review (AI) — 5-agent adversarial, 2026-07-22

**Outcome: APPROVE after fixes applied.** All 5 required BMAD layers ran (Story Quality, Blind Hunter/Security, Test Coverage, AC Completeness, Process Integrity).

| Layer | Verdict | Notes |
|-------|---------|-------|
| 1 — Story Quality | PASS | Story-first gate clean (`dddfb4b` story-only first, `aaea083` impl). AC-5 wording tightened; dropped-id test enumerated. Its "stale mypy baseline" note was a **false positive** — `main` is `cdc984e`, PR #76 unmerged, verified via `git`. |
| 2 — Blind Hunter (Security) | Changes requested → **fixed** | 2 Med DoS + Lows (below). |
| 3 — Test Coverage | Gaps → **fixed** | 1 High + Meds (below). |
| 4 — AC Completeness | PASS (no violations) | GAP-1 (AC-11 calibration on bypass path) closed with a node-level ≥3 test; GAP-2 (defaults untested) closed. |
| 5 — Process Integrity | PASS | All 9 locked rules clean (no hardcoded models, providers abstraction, degrade-not-fabricate, summaries-only, hierarchical, no banned deps, one-discipline, config pattern, tracker rule). |

### Action Items — resolved

- [x] **[Med, Security] `lesson_planner_batch_size ≤ 0` crashed the planner** (`range(…, 0)` / empty batches → `plan_head` None). Added `gt=0` guard; `structure_max_sections` `ge=1`; `structure_min_section_chars` `ge=0`. Test: `test_config_defaults_and_planner_batch_invariant`.
- [x] **[Med, Security] `coalesce_sections` cap was O(n²) over an uncapped section count** (adversarial-upload worker-pin). Replaced smallest-adjacent-pair search with **O(n) contiguous bucketing**. Test: `test_coalesce_cap_buckets_are_contiguous`.
- [x] **[High, Tests] first-section-below-floor forward-merge branch untested.** Added `test_coalesce_first_section_below_floor_folds_forward`.
- [x] **[Med, Tests] title-fold not asserted.** Added `test_coalesce_folds_absorbed_titles_into_body`.
- [x] **[Med, Tests] batch boundaries (n=15/16/30) untested.** Added parametrized `test_planner_batch_boundaries`.
- [x] **[Med, Tests] count-preserving duplicate-id not exercised via batches.** Added `test_planner_batched_duplicate_id_count_preserved_still_rejected`.
- [x] **[Med, Tests] coalesce on adopted-LLM path untested.** Added `test_structure_node_coalesces_adopted_llm_output`.
- [x] **[Low, Tests] degenerate `max_sections=0` / single sub-floor seed.** Added `test_coalesce_max_sections_zero_disables_cap`, `test_coalesce_single_subfloor_section_is_kept`.

### Accepted / documented (non-blocking Lows)

- **Plan-level fields from first batch only** — documented in `lesson_planner_node`; latent in default config (`structure_max_sections=15 == lesson_planner_batch_size`, so batching never triggers unless reconfigured). `total_duration_min` still sums all segments.
- **No mid-loop cost re-check across planner batches** — bounded (≤ `_MAX_PHASE1_SECTIONS`=60 calls), matches the pre-existing single-check placement; not changed.
- **RC-2 (dead LLM structure validation) + its `<90%`-rejection characterization test** — deferred to Story 2-17 (non-blocking once RC-1 bounds section count).

Post-fix verification: **471 passed / 1 skipped**; ruff check + format clean; `mypy app` = 215 (baseline, zero new).

## Dev Agent Record

### Completion Notes

Fixed RC-1 + RC-3; RC-2 deferred to Story 2-17 as planned (see Scope Decision).

- **RC-1 (over-segmentation):** `coalesce_sections` bounds the section list in two text-preserving passes (sub-floor merge → greedy adjacent-pair merge to the cap). Regexes in `detect_headings` were **not** touched (avoids regressing legitimate numbered headings like "1. Introduction"). Wired into `structure_node` on whichever section set wins (LLM or rule-based). The 44-step how-to now yields ≤ `structure_max_sections` sections with zero text loss.
- **RC-3 (planner brittleness):** `lesson_planner_node` batches summaries above `lesson_planner_batch_size`; each batch echoes a small id list reliably, results concatenate, and the **existing** degrade-not-fabricate guard block runs unchanged on the assembly (a dropped/duplicated id still raises — proven by `test_planner_batched_dropped_id_still_rejected`). At/below the threshold it's a single call, byte-identical to before.
- **No behaviour weakening:** every prior guard still raises on a genuine defect; no fabrication (batches echo real summaries, coalesce concatenates real bodies).
- **Constraints:** `settings.llm_*` aliases only (no hardcoded models); providers abstraction preserved; planner still receives summaries only; no full-chapter single call.

### Verification

- `pytest tests/unit` → **459 passed, 1 skipped** (was 459/1 before; net +11 new tests, 0 regressions).
- `ruff check .` + `ruff format --check .` (0.15.22) → clean.
- `mypy app` → **215 errors** = pre-existing baseline, **zero introduced** (`graph.py`/`structure_detection.py` contributed none; `config.py:328` unused-ignore is a pre-existing error shifted down by the inserted fields). Note: the 215 mypy debt is tracked separately by PR #76 and is not part of this branch's scope.
- Baseline branch: `main` @ `cdc984e` (does not contain PR #76's mypy helpers — code read/edited against the main version).

### Debug Log

- Extending `Settings` broke tests that fabricate a MagicMock `settings` (numeric compare `int < MagicMock`): `test_structure_node.py` (4), `test_lesson_planner_node.py` (3), `test_pipeline_tier1.py` (6 structure-guard). Foreseen exception (same class Story 2-6 documented) — added the new fields to those mocks with no-op coalesce values so the fixes don't couple those tests to coalescing behaviour (which is covered directly in `test_coalesce_sections.py` + the node-wiring test).
- Batch reassembly builds a real `_LessonPlanLLM`, so the batch test returns real model instances (single-call path stays MagicMock-compatible → existing tests untouched).

### File List

- `apps/api/app/config.py` — 3 new settings (MODIFIED)
- `apps/api/app/modules/content/pipeline/nodes/structure_detection.py` — `coalesce_sections` + `_merge_two` (MODIFIED)
- `apps/api/app/modules/content/pipeline/graph.py` — `structure_node` coalesce wiring + RC-2 comment; `_planner_system_prompt` / `_run_planner_batch` + batch dispatch in `lesson_planner_node` (MODIFIED)
- `apps/api/tests/unit/test_coalesce_sections.py` — coalesce unit tests (NEW)
- `apps/api/tests/unit/test_lesson_planner_node.py` — planner batching tests + settings-mock fields (MODIFIED)
- `apps/api/tests/unit/test_structure_node.py` — node-wiring test + settings-mock fields (MODIFIED)
- `apps/api/tests/unit/test_pipeline_tier1.py` — settings-mock fields (MODIFIED)
- `docs/stories/2-16-fix-pipeline-oversegmentation.md` — this story (NEW)
- `docs/stories/2-17-boundary-only-structure-validation.md` — deferred RC-2 follow-up (NEW)
