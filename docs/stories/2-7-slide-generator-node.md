---
baseline_commit: 68b23fe0da4fa13fc750284b0c30d841e918d3e9
---

# Story 2.7: `slide_generator` Node — Real Structured Generation (S2-8)

Status: done

## Story

As a **student whose chapter now has a real lesson plan** (Story 2-6/S2-7),
I want the pipeline to turn each pedagogical segment's outline into a real slide deck (title + bullets per slide),
so that `tts_node`/`image_generator`/`package_builder` (S2-9/S2-10/S2-11, separate stories) have real slide content to attach audio, images, and final assembly to — instead of the current empty placeholder.

This story implements the REAL generation logic for `slide_generator_node` — tracker task **S2-8** in `docs/dev1-tracker.md`, Epic 1's Node 12. The node function and its place in the graph already exist as a stub (`graph.add_edge("lesson_planner", "slide_generator")` is already wired) — this story replaces the stub body only.

**Scope boundary — tier-aware slide counts (S2-LM4) are NOT part of this story**, for the identical reason Story 2-6 excluded them: `state` has no `tier` key post-revert (see `docs/stories/2-2-learner-mode-infra.md`'s Change Log). This node targets a single tier-agnostic slide-count heuristic (1–8 slides per segment, LLM's judgment within that band) rather than any tier-conditioned range. S2-LM4 becomes a follow-up story that amends both this node and `lesson_planner` once S2-LM1's sign-off unblocks tier plumbing again.

**Design decision — ONE structured-output call for the whole plan, not one call per segment.** `lesson_planner_node` (Story 2-6) made exactly this choice for the same reason: `llm_slide_generator` is a premium model (`gpt-4o` by default, same cost tier as `llm_lesson_planner`), and Phase 2 is already sequential (not `Send()`-fanned) — N separate per-segment calls would N-x the cost of this node for no benefit a single call asking for "one slide-set per segment_id" doesn't already achieve. This mirrors `lesson_planner_node`'s exact "1:1, one call" pattern from the same story, just one level deeper (segments → slides instead of sections → segments).

## Acceptance Criteria

1. **Input is `state["lesson_plan"]["segments"]` only** — each entry's `segment_id`, `title`, and `summary` (produced by Story 2-6's `lesson_planner_node`) are fed to the LLM. Never re-reads `state["segment_summaries"]`, `state["sections"]`, or `state["chapter_content"]` directly (this node is one hop further from raw text than `lesson_planner`, and must stay that way).
2. **One slide-set per lesson-plan segment (1:1, no merge/split)** — the LLM returns exactly one slide-set entry per input segment, echoing back the same `segment_id`s unchanged (identical discipline to Story 2-6 AC-2, one level deeper).
3. **Each slide validates against the frozen `app.schemas.lesson.Slide` model** — `Slide.model_validate(...)` is called on every assembled slide dict inside this node (not deferred to `package_builder`), catching a shape violation immediately rather than downstream. `image_url`/`fallback_image_url` are always `None` at this node (images are S2-10's job — AC explicitly allows nullable).
4. **At least 1, at most 8 slides per segment** — the AC's literal "at least 1 slide per segment" floor, paired with a ceiling (8) to bound this premium node's own cost/output size now that there's no tier-derived range to lean on (see Story's Design Decision section — 8 is a conservative single-tier ceiling, not a tier-specific number).
5. **Output shape is internal (nested `{segment_id, data}`, not a bare `Slide` list)** — `state["slides"]` becomes `list[{"segment_id": str, "data": {slide_id, title, bullets, image_url: None, fallback_image_url: None}}]`, mirroring `quiz_generator_node`'s/`jargon_extractor_node`'s established nested pattern (Story 2-1) for the identical reason: `Slide` is frozen with `extra="forbid"` and has no `segment_id` field, but `package_builder` (S2-11) needs to know which segment each slide belongs to once results are in a flat list. `slide_id` is generated deterministically as `f"slide_{segment_id}_{index}"` (not LLM-supplied — nothing about slide identity needs LLM judgment, and a deterministic ID removes an entire class of duplicate/malformed-ID guard this node would otherwise need).
6. **Model call follows the established provider pattern exactly** — `OpenAILLMProvider(lesson_id).complete_structured(messages, settings.llm_slide_generator, _SlideDeckLLM)`. Cost accumulation, cost-ceiling enforcement, circuit-breaker check, Langfuse tracing, and retry are ALL already handled transparently inside `complete_structured()` (Story 2-6 Dev Notes — same provider, same guarantee) — this node must NOT duplicate any of that logic.
7. **Degrade-not-fabricate guards, matching Story 2-6's established house style**: segment-set mismatch (wrong count, unknown segment_id, duplicate segment_id), any segment with zero or >8 slides, any blank slide title, or any slide with zero bullets → reject the whole response (raise, do not checkpoint, let ARQ retry) — no per-segment redundancy exists here either, same reasoning as Story 2-6 AC-6.
8. **Idempotency checkpoint, Phase-A style (same as Story 2-6, not Story 2-1b's Phase-1 pattern)** — read `lesson_jobs.node_outputs`; `"slide_generator"` key present → return cached, skip the LLM call. On success, plain client-side read-modify-write (single sequential dispatch, no concurrency to guard against — identical reasoning to Story 2-6 AC-5). **Caveat (added 2026-07-15 review):** this closes re-billing for a retry that starts strictly AFTER a prior attempt's checkpoint write succeeded — a crash/timeout between a successful (billed) LLM call and that checkpoint write still re-bills on the next retry (the exact same accepted tradeoff `lesson_planner_node`/`embed_node` already carry). Not a "no re-billing, full stop" guarantee.
9. All existing tests continue to pass unmodified.

## Tasks / Subtasks

- [x] Task 1: Internal structured-output models (AC: 3, 5, 6)
  - [x] 1.1 Added `_SlideLLM`, `_SegmentSlidesLLM`, `_SlideDeckLLM` immediately before `slide_generator_node`.
  - [x] 1.2 All loose (no `extra="forbid"`, no length constraints), as specified.

- [x] Task 2: Replace the `slide_generator_node` stub body (AC: 1, 2, 4, 6, 7, 8)
  - [x] 2.1 Idempotency checkpoint read added, mirroring `lesson_planner_node` exactly.
  - [x] 2.2 Reads `state["lesson_plan"]["segments"]` only; never touches `segment_summaries`/`sections`/`chapter_content`.
  - [x] 2.3 Empty `plan_segments` → `raise RuntimeError` before the LLM call.
  - [x] 2.4 Prompt built per spec: task + echo-segment_id instruction + `_UNTRUSTED_CONTENT_GUARD`; user message is the plan segments' `segment_id`/`title`/`summary` only.
  - [x] 2.5 `complete_structured(messages, settings.llm_slide_generator, _SlideDeckLLM)`; `response is None` → raise, no checkpoint.
  - [x] 2.6 All guards implemented: count mismatch, unknown segment_id, duplicate segment_id, `1 <= len(slides) <= 8` per segment, blank slide title, empty `bullets`.
  - [x] 2.7 Assembly iterates `plan_segments` (input order); `Slide.model_validate(...)` called on every slide before appending.
  - [x] 2.8 Checkpoint write added, matching AC-8 exactly.
  - [x] 2.9 Returns `{**state, "slides": slides_out, "progress_pct": 48.0}`.
  - [x] 2.10 Stub `TODO` comment removed; `PipelineState.slides` field comment corrected to the nested `{segment_id, data: {...}}` shape.

- [x] Task 3: Tests (AC: all) — new file `apps/api/tests/unit/test_slide_generator_node.py`, 15 tests
  - [x] 3.1 `test_happy_path_produces_nested_slide_entries_matching_segments` — note: `slides` is a FLAT per-slide list (not per-segment), so a fixture with one segment carrying 2 slides produces 4 total entries, not 3 — this was a test-authoring bug caught immediately when writing the test (fixed before it ever reached the implementation), not an implementation defect.
  - [x] 3.2 `test_prompt_never_includes_raw_summaries_or_sections`.
  - [x] 3.3 One test per guard: `test_mismatched_segment_count_is_rejected_not_checkpointed`, `test_unknown_segment_id_is_rejected`, `test_duplicate_segment_id_is_rejected` (not originally enumerated in 3.3's text but the same guard family, mirrors Story 2-6's own added duplicate-ID guard), `test_zero_slides_for_a_segment_is_rejected`, `test_too_many_slides_for_a_segment_is_rejected`, `test_blank_slide_title_is_rejected`, `test_empty_bullets_is_rejected`, plus `test_refusal_raises_and_does_not_checkpoint` for the `response is None` path.
  - [x] 3.4 `test_idempotency_cache_hit_skips_llm_call`, `test_successful_run_writes_checkpoint`.
  - [x] 3.5 `test_model_used_is_settings_llm_slide_generator`.
  - [x] 3.6 `test_empty_lesson_plan_segments_rejected_before_llm_call`.
  - [x] 3.7 Full regression: 312/312 passes. **No pre-existing test needed updating this time** — `test_phase1_economy_nodes.py`'s `TestAC0GraphOrdering` class fully mocks `slide_generator_node` via `patch.object` in its barrier-stub list, so it was never at risk (unlike Story 2-6's situation with `lesson_planner_node`). Also added `test_segment_order_follows_input_not_llm_response_order`, not originally enumerated but directly ported from Story 2-6's own review-round patch — proactively applied here rather than caught by a separate review round.

## Dev Notes

### The node and its place in the graph already exist — this story replaces the stub body only

Current stub (`graph.py`, quoted in full):
```python
async def slide_generator_node(state: PipelineState) -> PipelineState:
    """Node 6: Generate slide deck JSON from the lesson plan.

    Uses llm_slide_generator model (gpt-4o by default).
    """
    lesson_id = state["lesson_id"]
    logger.info("[%s] slide_generator_node: generating slides", lesson_id)
    await _update_job_progress(lesson_id, 40.0, "slide_generator")

    # TODO: OpenAILLMProvider(lesson_id).complete_structured(messages, model, SlideDeck)
    slides: list[dict[str, Any]] = []
    return {**state, "slides": slides, "progress_pct": 48.0}
```
The graph wiring (`_build_pipeline_graph()`) already has `graph.add_edge("lesson_planner", "slide_generator")` and `graph.add_edge("slide_generator", "tts_node")` — nothing about graph topology changes in this story, only this function's body. `tts_node`/`image_generator`/`package_builder` remain stubs for separate stories (S2-9/S2-10/S2-11) — do not touch them here.

### `lesson_plan["segments"]` shape (Story 2-6's `lesson_planner_node` output)

Each entry: `{"segment_id": str, "title": str, "summary": str, "duration_min": float}` (see `docs/stories/2-6-lesson-planner-node.md` AC-3 for the full `lesson_plan` dict shape). This node reads `segment_id`, `title`, and `summary` from each entry — `duration_min` is not needed here (it's a pacing hint for `tts_node`'s narration, not slide count).

### `Slide` frozen schema (`app/schemas/lesson.py`)

```python
class Slide(BaseModel):
    model_config = _STRICT  # extra="forbid"
    slide_id: str
    title: str
    bullets: list[str]
    image_url: AnyHttpUrl | None
    fallback_image_url: AnyHttpUrl | None
```
`image_url`/`fallback_image_url` are typed `AnyHttpUrl | None` — passing `None` for both (this story's job) is the only value this node can supply; do not pass an empty string (fails `AnyHttpUrl` validation) — `None` is correct and required.

### Nested `{segment_id, data}` output pattern — established by Story 2-1, reused here one level deeper

`quiz_generator_node`/`jargon_extractor_node` (Story 2-1) already solved the identical problem: a frozen per-item model with `extra="forbid"` and no correlation-ID field, but the `PipelineState` list it's collected into needs that correlation ID to survive. Their solution — nest as `{"segment_id": ..., "data": {...frozen-model-shaped dict...}}` so `package_builder` can later do `Slide.model_validate(entry["data"])` with zero reshaping — is the exact pattern this story reuses, NOT a new invention.

### Provider call, cost, circuit breaker, tracing — identical to Story 2-6, no changes needed there

`OpenAILLMProvider.complete_structured()` (`apps/api/app/providers/llm/openai.py`) already handles circuit-breaker check, cost accumulation (`_maybe_accumulate_cost`), cost-ceiling enforcement (raises if breached), Langfuse tracing, and retry (`@with_retry(max_attempts=3)`) — see Story 2-6's Dev Notes for the full quoted method. `settings.llm_slide_generator` defaults to `"gpt-4o"` (`apps/api/app/config.py`), already priced in `_COST_PER_1K`. Nothing about this infrastructure needs touching.

### Checkpoint pattern to copy: `lesson_planner_node`'s (Story 2-6), not Story 2-1b's atomic RPC

Same reasoning as Story 2-6 AC-5/Dev Notes: this is a single sequential dispatch (no `Send()` fan-out), so the plain `embed_node`-style read-then-write checkpoint is correct, not Story 2-1b's atomic RPC merge (built for Phase 1's genuine concurrency). Copy `lesson_planner_node`'s exact checkpoint read/write block, substituting the `"slide_generator"` key.

### Scope boundary — do not build S2-LM4 (tier-aware slide counts) here

Identical reasoning to Story 2-6's own scope-boundary section. `state` has no `tier` key. This node targets a fixed, tier-agnostic 1–8 slides/segment band. When S2-LM1's sign-off lands and S2-LM3/S2-LM4 are re-implemented, S2-LM4 will amend both `lesson_planner_node` (to set a tier-derived per-segment slide-count target) and THIS function (to respect that target instead of its own fixed 1–8 band) — out of scope now.

### Branch

Single shared branch for all of Sprint 2: `sprint2/phase-b-generation-nodes` — do not create a new branch. Story-first gate still applies: this file committed alone and pushed before any implementation commit.

### Testing standards

pytest, matching `apps/api/tests/unit/test_lesson_planner_node.py`'s conventions exactly (same file will likely be renamed/generalized in spirit, but per Story 2-6's own Testing Standards note, use a NEW dedicated file `apps/api/tests/unit/test_slide_generator_node.py` rather than growing the lesson-planner-specific one).

### Project Structure Notes

No new modules. Edits confined to `slide_generator_node` + 3 new internal Pydantic models in `apps/api/app/modules/content/pipeline/graph.py`, plus the stale `PipelineState.slides` comment fix. One new test file.

### References

- [Source: docs/dev1-tracker.md — Sprint 2 section, S2-8]
- [Source: docs/bmad/epics/epic-1-content-pipeline.md — Node 12 spec]
- [Source: docs/stories/2-6-lesson-planner-node.md — sibling story this one directly follows; established patterns: internal loose Pydantic models, degrade-not-fabricate guards, input-order-preserving assembly, Phase-A checkpoint style, tier-agnostic scope boundary]
- [Source: apps/api/app/modules/content/pipeline/graph.py — slide_generator_node current stub, lesson_planner_node's checkpoint pattern to copy, PipelineState.slides field]
- [Source: apps/api/app/schemas/lesson.py — Slide frozen model]
- [Source: apps/api/app/providers/llm/openai.py — complete_structured(), unchanged from Story 2-6]
- [Source: apps/api/app/config.py — llm_slide_generator setting]
- [Source: docs/stories/2-1-phase1-economy-nodes.md — origin of the nested {segment_id, data} output pattern]

## Dev Agent Record

### Agent Model Used

claude-sonnet-5

### Debug Log References

- Red-green-refactor verified: `test_slide_generator_node.py` written first against the still-stub `slide_generator_node` — confirmed 15/15 failures, then implementation applied — 14/15 green on first pass, 1 failure (`test_happy_path_produces_nested_slide_entries_matching_segments`) traced to a test-authoring bug (asserted `len(slides) == 3` treating the flat per-slide output list as per-segment, when the fixture's `sec_1` carries 2 slides making the real correct total 4) — fixed the test assertion, not the implementation, then 15/15 green.
- Full-suite run after implementation: 312/312 pass, zero pre-existing tests needed updating (unlike Story 2-6, where `test_phase1_economy_nodes.py`'s AC-0 test called the node with zero mocking — the equivalent check here, `TestAC0GraphOrdering`, already fully mocks `slide_generator_node` via `patch.object` in its barrier-stub list, so it was never exercising the real function body).

### Completion Notes List

- All 3 tasks / 19 subtasks complete (corrected 2026-07-15 review — Completion Notes originally miscounted this as 13; actual count is 2 in Task 1 + 10 in Task 2 + 7 in Task 3 = 19). 314/314 unit tests pass after the code-review patch round (0 regressions; 17 tests total in `test_slide_generator_node.py`, up from 15 after 2 more were added for the review-round patches).
- Applied Story 2-6's own review-round lesson proactively rather than waiting for this story's own review to catch it: assembly iterates `plan_segments` (input order), not `response.segments` (LLM order) — `test_segment_order_follows_input_not_llm_response_order` covers this directly, ported near-verbatim from Story 2-6's post-review test of the same name.
- Design decision confirmed as planned: ONE `complete_structured()` call for the whole plan (not one call per segment) — same cost-conscious pattern `lesson_planner_node` established, for the identical reason (premium model, sequential dispatch).
- Scope boundary held exactly as planned: no `tier` parameter, no `state.get("tier")` read, fixed 1-8 slides/segment band — no tier-conditioned range. S2-LM4 (blocked on S2-LM1's still-outstanding 4-developer sign-off) will amend both this node and `lesson_planner_node` once tier plumbing is safe to reintroduce.
- AC-1 enforced both structurally (function never references `state["segment_summaries"]`/`state["sections"]`/`state["chapter_content"]`) and by `test_prompt_never_includes_raw_summaries_or_sections`, which plants all three in state alongside `lesson_plan` and asserts none of their content reaches the prompt.
- Each assembled slide is validated via `Slide.model_validate(...)` inside this node itself (AC-3), not deferred to `package_builder` — a shape bug in this node's own assembly surfaces immediately as a `ValidationError`, not silently downstream.
- `tts_node`/`image_generator`/`package_builder_node` (S2-9/S2-10/S2-11, the next nodes in the graph) were NOT touched — all remain today's stubs, correctly out of scope.

### File List

- `apps/api/app/modules/content/pipeline/graph.py` (modified — `slide_generator_node` real implementation + 3 new internal Pydantic models + `PipelineState.slides` comment fix)
- `apps/api/tests/unit/test_slide_generator_node.py` (new — 15 tests)

## Change Log

| Date | Change |
|------|--------|
| 2026-07-15 | Story implemented (Tasks 1-3) via `bmad-dev-story`. `slide_generator_node` now makes a real `settings.llm_slide_generator` structured-output call (one call for the whole plan) with degrade-not-fabricate guards and a Phase-A-style idempotency checkpoint. 15 new tests, 0 pre-existing tests needed updating. 312/312 total passing. |
| 2026-07-15 | 3-layer adversarial code review run via multi-agent Workflow orchestration — 0 decision-needed, 5 patch, 3 defer, 0 dismissed. All 5 patches applied same day: per-bullet blank check, malformed-segment guard, AC-8 wording caveat, "2-6"→"1-8" story-text fix, subtask-count correction. 2 new tests added for the code patches. 314/314 total passing. |

### Review Findings (2026-07-15 — 3-layer adversarial review via multi-agent Workflow orchestration: Blind Hunter, Edge Case Hunter, Acceptance Auditor)

- [x] [Review][Patch] **FIXED 2026-07-15 — Individual bullet strings were never checked for blank/whitespace-only content.** Guard now rejects if any bullet is blank/whitespace-only, not just an empty list (`if not slide.bullets or any(not b.strip() for b in slide.bullets):`). [`graph.py::slide_generator_node`] (Blind Hunter + Edge Case Hunter, independently)
- [x] [Review][Patch] **FIXED 2026-07-15 — A malformed `lesson_plan["segments"]` entry raised a raw `KeyError`.** Added an upfront validation loop raising a contextual `RuntimeError` for any entry missing `segment_id`/`title`/`summary`, mirroring `lesson_planner_node`'s identical fix. [`graph.py::slide_generator_node`] (Blind Hunter + Edge Case Hunter + Acceptance Auditor — all three, independently)
- [x] [Review][Patch] **FIXED 2026-07-15 — AC-8 didn't disclose the re-billing crash-window caveat.** Reworded AC-8 above with the same caveat Story 2-6 added to its AC-5. Documentation-only fix, no code change. [`docs/stories/2-7-slide-generator-node.md` AC-8] (Edge Case Hunter)
- [x] [Review][Patch] **FIXED 2026-07-15 — Story narrative said "2–6 slides per segment" instead of the correct 1–8 band.** Corrected the Scope Boundary paragraph to match AC-4/the implementation. [`docs/stories/2-7-slide-generator-node.md`, Story section] (Acceptance Auditor)
- [x] [Review][Patch] **FIXED 2026-07-15 — Dev Agent Record miscounted subtasks as 13 instead of 19.** Corrected in Completion Notes List. [`docs/stories/2-7-slide-generator-node.md`, Completion Notes List] (Acceptance Auditor)
- [x] [Review][Defer] **No upper bound on bullet count or string length per slide** — a malformed/adversarial LLM response could return one slide with thousands of huge bullet strings, bloating the `lesson_jobs.node_outputs` JSONB column. Theoretical DoS/storage-bloat vector, same risk class as Story 2-6's deferred "no length bound on objectives/title/subject" finding — low severity given this endpoint sits behind the pipeline's own auth/rate-limit/cost-ceiling. [`graph.py::_SlideLLM`] (Blind Hunter) — deferred, same risk class as Story 2-6.
- [x] [Review][Defer] **TOCTOU race: two concurrent executions of this node for the same `lesson_id` (e.g. an ARQ retry racing a straggler) would both cache-miss, both bill the premium model, and the last checkpoint write wins with no lock/version check.** Identical, already-accepted tradeoff `lesson_planner_node`/`embed_node`/`chunk_node`/`structure_node` all share (Phase A's whole checkpoint style) — closing it properly needs an atomic RPC merge or optimistic-locking check, larger scope than this story. [`graph.py::slide_generator_node`] (Blind Hunter + Edge Case Hunter, independently) — deferred, matches existing accepted Phase A risk (same as Story 2-6's identical deferred finding).
- [x] [Review][Defer] **`.single().execute()` has no explicit not-found/multiple-rows exception handling.** Identical pattern already used unguarded by every other node in this file (`embed_node`, `chunk_node`, `structure_node`, `lesson_planner_node`) — not a regression specific to this diff. [`graph.py::slide_generator_node`] (Blind Hunter) — deferred, codebase-wide pre-existing pattern (same as Story 2-6's identical deferred finding).

**Dismissed (0):** no findings were classified as noise this round — all three reviewers' findings were substantive (patch or defer).
