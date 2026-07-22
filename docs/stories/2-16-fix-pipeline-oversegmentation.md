---
baseline_commit: cdc984eb126c1eb9e4c3711200284b1129923935
---

# Story 2.16: Fix Content-Pipeline Over-Segmentation Blocker (structure detection + `lesson_planner`)

Status: ready-for-dev

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

5. **AC-5 — Regression-safe + new coverage.** All existing unit tests pass **unmodified** (the batching threshold and single-call path guarantee the ≤-threshold tests are unaffected; coalescing defaults are calibrated so `test_ac11_multi_heading_chapter_produces_three_or_more_sections` still yields ≥3). New tests added:
   - `test_coalesce_collapses_oversegmented_howto` — ~44 short "step" sections → `≤ structure_max_sections`.
   - `test_coalesce_preserves_all_body_text` — concatenation of coalesced bodies contains every original body substring (no data loss).
   - `test_coalesce_below_cap_is_noop` — a small, above-floor section list is returned unchanged.
   - `test_planner_batches_above_threshold_produces_full_plan` — `batch_size + N` summaries → assembled plan has exactly that many segments, 1:1, all ids present.
   - `test_planner_single_call_path_unchanged_below_threshold` — ≤ threshold → exactly one `complete_structured` call (existing behaviour).
   - Existing `test_mismatched_segment_count_is_rejected_not_checkpointed` / `test_unknown_segment_id_is_rejected` remain green (single-call path).

6. **AC-6 — Architectural constraints preserved.** degrade-not-fabricate (all merges/batches are text-preserving and echo real content); no hardcoded models; hierarchical Chapter→Section→Topic processing (no full-chapter single call introduced); `lesson_planner_node` still receives `segment_summaries` only, never raw text (AC-1 of Story 2-6 / the 5× cost constraint); `providers/` abstraction respected (all LLM calls via `get_llm_provider` / `complete_structured`).

## Tasks / Subtasks

- [ ] Task 1: Config (AC-3)
  - [ ] 1.1 Add `structure_min_section_chars`, `structure_max_sections`, `lesson_planner_batch_size` to `Settings` in `config.py` with defaults 200 / 15 / 15 and env aliases.
- [ ] Task 2: Coalesce pass (AC-1)
  - [ ] 2.1 Add pure `coalesce_sections(sections, *, min_chars, max_sections)` to `structure_detection.py` — sub-floor merge then greedy adjacent merge to cap; text-preserving; preserves `id` re-sequencing and `page_start`/`page_end` spans of merged ranges.
  - [ ] 2.2 Call it in `structure_node` on the final `sections_list` (after the LLM/rule decision, before the checkpoint write), logging before/after counts.
- [ ] Task 3: Planner batching (AC-2)
  - [ ] 3.1 Extract the single-call body into a helper; add batching dispatch above `settings.lesson_planner_batch_size`; assemble then run the existing guard block once on the concatenated response.
- [ ] Task 4: RC-2 deferral (AC-4)
  - [ ] 4.1 Add the explaining comment + Story 2-17 reference in `structure_node`.
  - [ ] 4.2 Create `docs/stories/2-17-boundary-only-structure-validation.md` (Status: backlog).
- [ ] Task 5: Tests (AC-5) — RED first, then implement.
- [ ] Task 6: Full-suite regression + ruff + mypy green; update `docs/dev1-tracker.md`.

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

## Dev Agent Record

_(to be completed during `dev-story`)_
