---
baseline_commit: 68b23fe0da4fa13fc750284b0c30d841e918d3e9
---

# Story 2.7: `slide_generator` Node — Real Structured Generation (S2-8)

Status: ready-for-dev

## Story

As a **student whose chapter now has a real lesson plan** (Story 2-6/S2-7),
I want the pipeline to turn each pedagogical segment's outline into a real slide deck (title + bullets per slide),
so that `tts_node`/`image_generator`/`package_builder` (S2-9/S2-10/S2-11, separate stories) have real slide content to attach audio, images, and final assembly to — instead of the current empty placeholder.

This story implements the REAL generation logic for `slide_generator_node` — tracker task **S2-8** in `docs/dev1-tracker.md`, Epic 1's Node 12. The node function and its place in the graph already exist as a stub (`graph.add_edge("lesson_planner", "slide_generator")` is already wired) — this story replaces the stub body only.

**Scope boundary — tier-aware slide counts (S2-LM4) are NOT part of this story**, for the identical reason Story 2-6 excluded them: `state` has no `tier` key post-revert (see `docs/stories/2-2-learner-mode-infra.md`'s Change Log). This node targets a single tier-agnostic slide-count heuristic (2–6 slides per segment, LLM's judgment within that band) rather than any tier-conditioned range. S2-LM4 becomes a follow-up story that amends both this node and `lesson_planner` once S2-LM1's sign-off unblocks tier plumbing again.

**Design decision — ONE structured-output call for the whole plan, not one call per segment.** `lesson_planner_node` (Story 2-6) made exactly this choice for the same reason: `llm_slide_generator` is a premium model (`gpt-4o` by default, same cost tier as `llm_lesson_planner`), and Phase 2 is already sequential (not `Send()`-fanned) — N separate per-segment calls would N-x the cost of this node for no benefit a single call asking for "one slide-set per segment_id" doesn't already achieve. This mirrors `lesson_planner_node`'s exact "1:1, one call" pattern from the same story, just one level deeper (segments → slides instead of sections → segments).

## Acceptance Criteria

1. **Input is `state["lesson_plan"]["segments"]` only** — each entry's `segment_id`, `title`, and `summary` (produced by Story 2-6's `lesson_planner_node`) are fed to the LLM. Never re-reads `state["segment_summaries"]`, `state["sections"]`, or `state["chapter_content"]` directly (this node is one hop further from raw text than `lesson_planner`, and must stay that way).
2. **One slide-set per lesson-plan segment (1:1, no merge/split)** — the LLM returns exactly one slide-set entry per input segment, echoing back the same `segment_id`s unchanged (identical discipline to Story 2-6 AC-2, one level deeper).
3. **Each slide validates against the frozen `app.schemas.lesson.Slide` model** — `Slide.model_validate(...)` is called on every assembled slide dict inside this node (not deferred to `package_builder`), catching a shape violation immediately rather than downstream. `image_url`/`fallback_image_url` are always `None` at this node (images are S2-10's job — AC explicitly allows nullable).
4. **At least 1, at most 8 slides per segment** — the AC's literal "at least 1 slide per segment" floor, paired with a ceiling (8) to bound this premium node's own cost/output size now that there's no tier-derived range to lean on (see Story's Design Decision section — 8 is a conservative single-tier ceiling, not a tier-specific number).
5. **Output shape is internal (nested `{segment_id, data}`, not a bare `Slide` list)** — `state["slides"]` becomes `list[{"segment_id": str, "data": {slide_id, title, bullets, image_url: None, fallback_image_url: None}}]`, mirroring `quiz_generator_node`'s/`jargon_extractor_node`'s established nested pattern (Story 2-1) for the identical reason: `Slide` is frozen with `extra="forbid"` and has no `segment_id` field, but `package_builder` (S2-11) needs to know which segment each slide belongs to once results are in a flat list. `slide_id` is generated deterministically as `f"slide_{segment_id}_{index}"` (not LLM-supplied — nothing about slide identity needs LLM judgment, and a deterministic ID removes an entire class of duplicate/malformed-ID guard this node would otherwise need).
6. **Model call follows the established provider pattern exactly** — `OpenAILLMProvider(lesson_id).complete_structured(messages, settings.llm_slide_generator, _SlideDeckLLM)`. Cost accumulation, cost-ceiling enforcement, circuit-breaker check, Langfuse tracing, and retry are ALL already handled transparently inside `complete_structured()` (Story 2-6 Dev Notes — same provider, same guarantee) — this node must NOT duplicate any of that logic.
7. **Degrade-not-fabricate guards, matching Story 2-6's established house style**: segment-set mismatch (wrong count, unknown segment_id, duplicate segment_id), any segment with zero or >8 slides, any blank slide title, or any slide with zero bullets → reject the whole response (raise, do not checkpoint, let ARQ retry) — no per-segment redundancy exists here either, same reasoning as Story 2-6 AC-6.
8. **Idempotency checkpoint, Phase-A style (same as Story 2-6, not Story 2-1b's Phase-1 pattern)** — read `lesson_jobs.node_outputs`; `"slide_generator"` key present → return cached, skip the LLM call. On success, plain client-side read-modify-write (single sequential dispatch, no concurrency to guard against — identical reasoning to Story 2-6 AC-5).
9. All existing tests continue to pass unmodified.

## Tasks / Subtasks

- [ ] Task 1: Internal structured-output models (AC: 3, 5, 6)
  - [ ] 1.1 In `graph.py`, immediately before `slide_generator_node`, add:
        ```python
        class _SlideLLM(BaseModel):
            title: str
            bullets: list[str]

        class _SegmentSlidesLLM(BaseModel):
            segment_id: str
            slides: list[_SlideLLM]

        class _SlideDeckLLM(BaseModel):
            segments: list[_SegmentSlidesLLM]
        ```
  - [ ] 1.2 Deliberately loose (no `extra="forbid"`, no length constraints on `slides`/`bullets`) — this node's own guards (Task 2) run before any strict validation, same rationale as `_LessonPlanLLM`/`_QuizQuestionLLM`.

- [ ] Task 2: Replace the `slide_generator_node` stub body (AC: 1, 2, 4, 6, 7, 8)
  - [ ] 2.1 Idempotency checkpoint read at function top (AC-8), identical structure to `lesson_planner_node`'s (`graph.py`, added in Story 2-6) — read `node_outputs`, cache hit → `return {**state, "slides": cached, "progress_pct": 48.0}`.
  - [ ] 2.2 Read `lesson_plan = state.get("lesson_plan") or {}` and `plan_segments = lesson_plan.get("segments", [])` (AC-1) — do NOT read `state["segment_summaries"]`/`state["sections"]`/`state["chapter_content"]` anywhere in this function.
  - [ ] 2.3 Guard: if `plan_segments` is empty, raise `RuntimeError` before calling the LLM (mirrors Story 2-6's empty-`segment_summaries` guard, applied one level deeper — a lesson_plan with zero segments is itself a bug from the upstream node, not something to paper over here).
  - [ ] 2.4 Build the prompt: system message states the task (produce 1-8 slides per lesson-plan segment, each with a title and bullet points), instructs "return exactly one slide-set per segment provided, echoing back each segment's segment_id UNCHANGED", includes `_UNTRUSTED_CONTENT_GUARD` (segment titles/summaries are themselves LLM-derived from untrusted section content, same guard class as every other node's prompt). User message: the plan segments' `segment_id`/`title`/`summary` triples.
  - [ ] 2.5 Call `OpenAILLMProvider(lesson_id).complete_structured(messages, settings.llm_slide_generator, _SlideDeckLLM)` (AC-6). `response is None` → `raise RuntimeError(...)`, no checkpoint (AC-7).
  - [ ] 2.6 Validate (AC-2, AC-4, AC-7): segment count/ID match (count mismatch, unknown segment_id, duplicate segment_id — identical guard family to Story 2-6's, applied to `response.segments` against `plan_segments`); each segment has `1 <= len(slides) <= 8`; no blank slide title; no slide with an empty `bullets` list.
  - [ ] 2.7 Assemble output (AC-3, AC-5): for each plan segment (iterating INPUT order, not LLM response order — same "input order wins" discipline as Story 2-6's own review-round patch), build `slide_id = f"slide_{segment_id}_{index}"`, then `Slide.model_validate({"slide_id": ..., "title": ..., "bullets": ..., "image_url": None, "fallback_image_url": None})` — let a `ValidationError` here propagate as a clear signal this node's own assembly is wrong, don't swallow it.
  - [ ] 2.8 Write the checkpoint (AC-8): `supabase.table("lesson_jobs").update({"last_node": "slide_generator", "node_outputs": {**node_outputs, "slide_generator": slides_out}}).eq("lesson_id", lesson_id).execute()`.
  - [ ] 2.9 Return `{**state, "slides": slides_out, "progress_pct": 48.0}` (unchanged progress value from the stub).
  - [ ] 2.10 Remove the stub's `# TODO: ...` comment. Correct the stale `PipelineState.slides` field comment (`graph.py` — currently `# [{id, title, body, speaker_notes, layout}]`, which matches neither the frozen `Slide` schema nor this story's nested output shape) to `# [{segment_id, data: {slide_id, title, bullets, image_url, fallback_image_url}}]`.

- [ ] Task 3: Tests (AC: all)
  - [ ] 3.1 Happy path: N plan segments in → N-entry `slides` list out, each entry's `data` validates against `Slide`, `slide_id` deterministic (`slide_{segment_id}_{index}` pattern), `image_url`/`fallback_image_url` both `None`.
  - [ ] 3.2 AC-1 regression guard: assert the prompt never contains `state["segment_summaries"]`/`state["sections"]`/`state["chapter_content"]` text, even when all three are present in state alongside `lesson_plan`.
  - [ ] 3.3 AC-2/AC-7 guards: segment-set mismatch (count/unknown-id/duplicate-id) → rejected; a segment with 0 slides → rejected; a segment with >8 slides → rejected; a blank slide title → rejected; a slide with empty `bullets` → rejected. Mirror Story 2-6's test structure (one test per guard).
  - [ ] 3.4 AC-8 idempotency: pre-existing `node_outputs["slide_generator"]` checkpoint → cache hit, zero calls to `complete_structured`.
  - [ ] 3.5 AC-6: confirm `settings.llm_slide_generator` (not `llm_lesson_planner`/`llm_mini`) is the model passed to `complete_structured`.
  - [ ] 3.6 Empty `lesson_plan["segments"]` → rejected before any LLM call (AC per Task 2.3).
  - [ ] 3.7 Full regression: `pytest tests/unit/` — 297/297 (current baseline) still passes; if any pre-existing test needs updating for the same reason Story 2-6 had to update one (a test calling this node with zero mocking), update it the same documented way — check `test_phase1_economy_nodes.py`'s `TestAC0GraphOrdering` class for a `slide_generator`-adjacent test before assuming none exists.

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

### Completion Notes List

### File List
