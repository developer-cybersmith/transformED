---
baseline_commit: 4942b63e31a41a4d1b1693e8a628973446e07168
---

# Story 2.6: `lesson_planner` Node — Real Structured Generation (S2-7)

Status: ready-for-dev

## Story

As a **student who has just uploaded a chapter**,
I want the pipeline to turn my chapter's per-section summaries into a coherent lesson plan (title, learning objectives, and an ordered outline of segments with durations),
so that `slide_generator` (S2-8, a separate story) has a real structure to build slides from, instead of the current empty placeholder.

This story implements the REAL generation logic for `lesson_planner_node` — tracker task **S2-7** in `docs/dev1-tracker.md`, corresponding to Epic 1's Node 11 (`docs/bmad/epics/epic-1-content-pipeline.md`). The node function and its place in the graph already exist as a wiring-proof stub (Story 2-1 AC-0) — this story replaces the stub body with a real `settings.llm_lesson_planner` (GPT-4o) call.

**Scope boundary — tier-aware slide counts are NOT part of this story.** Epic 1's node table (line 73) describes `lesson_planner` as eventually tier-aware (T1 20–25 / T2 12–15 / T3 6–8 target segments), and `docs/dev1-tracker.md`'s S2-LM4 entry says tier logic should land "together with" this node's base implementation. **That is not possible right now**: Story 2-2 (Learner Mode infra) implemented `POST /lessons`'s tier param and `PipelineState["tier"]` threading, but both were **reverted** on 2026-07-14 pending the still-outstanding 4-developer sign-off on the frozen `tier` contract field (see `docs/stories/2-2-learner-mode-infra.md`'s Change Log). `state` currently has no `tier` key at all. Building tier-aware logic against a `tier` key that doesn't exist would mean re-guessing a default or silently reintroducing the reverted plumbing — both are worse than deferring cleanly. **This story builds a tier-agnostic `lesson_planner` targeting a single default plan density (the T2 range, 12–15 segments-worth of coverage, achieved implicitly by NOT collapsing/splitting sections — see AC-2).** S2-LM4 becomes a follow-up story that amends this node once S2-LM1's sign-off unblocks tier plumbing again — flag this explicitly to the user, don't silently build partial tier logic.

## Acceptance Criteria

1. **Input is segment summaries, never raw chapter text** — `lesson_planner_node` reads `state["segment_summaries"]` (list of `{segment_id, summary}`, produced by Story 2-1's `summarise_segment_node`). It must NOT read `state["sections"]`, `state["chapter_content"]`, or any other raw-text field. This is the single most cost-critical constraint in the whole pipeline (CLAUDE.md, Epic 1 line 84) — violating it silently 5×s generation cost.
2. **One pedagogical segment per input summary (1:1, no merge/split in this story)** — the LLM is asked to produce exactly one outline entry per `segment_summaries` entry, echoing back the same `segment_id`s it was given (not inventing new ones). Merging/splitting sections into differently-bounded pedagogical segments (mentioned as a future possibility in Story 2-1's Dev Notes) is explicitly OUT of scope here — keeps this story's validation surface small and matches the "tier-agnostic single density" scope decision above.
3. **Output shape is internal (not the frozen `LessonMetadata`/`Segment` contract) but field-name-compatible with it** — `state["lesson_plan"]` becomes a dict: `{"title": str, "subject": str, "objectives": list[str], "complexity_level": str, "total_segments": int, "total_duration_min": float, "segments": [{"segment_id": str, "title": str, "summary": str, "duration_min": float}, ...]}`. `title`/`subject`/`complexity_level`/`total_segments` (renamed from the schema's `estimated_duration_mins` to `total_duration_min` at the plan level — see Dev Notes) share field names with `app.schemas.lesson.LessonMetadata` so a future `package_builder` (S2-11) can build `LessonMetadata` from this dict with minimal reshaping, mirroring how `quiz_generator_node`'s output dict is already shaped for zero-reshaping `QuizQuestion.model_validate()`.
4. **Model call follows the established provider pattern exactly** — `OpenAILLMProvider(lesson_id).complete_structured(messages, settings.llm_lesson_planner, <internal Pydantic model>)`. Cost accumulation, cost-ceiling enforcement, circuit-breaker check, Langfuse tracing, and retry (`@with_retry(max_attempts=3)`) are ALL already handled transparently inside `complete_structured()` (see Dev Notes) — this node must NOT duplicate any of that logic itself.
5. **Idempotency checkpoint, matching the Phase A pattern (not Story 2-1b's Phase-1 pattern)** — on entry, read `lesson_jobs.node_outputs`; if `"lesson_planner"` key already exists, return the cached value and skip the LLM call (no re-billing on ARQ retry). On success, write `{"last_node": "lesson_planner", "node_outputs": {**node_outputs, "lesson_planner": <cache>}}` via a plain client-side read-modify-write — Phase 2 is sequential (single dispatch, not `Send()`-fanned-out), so the atomic RPC merge built for Phase 1's concurrency (`_write_phase1_checkpoint`) is unnecessary machinery here; reuse the simpler pattern `embed_node`/`chunk_node` already use.
6. **Degrade-not-fabricate guards, matching Story 2-1's established house style**: if the LLM returns fewer/more `segments` entries than `segment_summaries` had, or references a `segment_id` not present in the input, or returns a blank `title`/`subject`/segment `title`, log a warning and reject the whole response (raise, do not checkpoint, let ARQ retry) rather than silently padding/truncating — unlike Phase 1's economy nodes, there is no per-section redundancy here; a partially-wrong lesson plan can't be safely patched piecemeal the way one bad quiz question can be dropped from a list.
7. **`total_duration_min` is computed by SUMMING the LLM's per-segment `duration_min` values, not asked for as a separate top-level number** — prevents the top-level total and the per-segment breakdown from silently disagreeing (an LLM asked for both independently has no self-consistency guarantee).
8. All existing tests continue to pass unmodified.

## Tasks / Subtasks

- [ ] Task 1: Internal structured-output models (AC: 3, 4)
  - [ ] 1.1 In `apps/api/app/modules/content/pipeline/graph.py`, near the other internal `_...LLM` models (e.g. `_SegmentSummaryLLM`, `_QuizQuestionLLM`), add:
        ```python
        class _LessonPlanSegmentLLM(BaseModel):
            segment_id: str
            title: str
            duration_min: float

        class _LessonPlanLLM(BaseModel):
            title: str
            subject: str
            objectives: list[str]
            complexity_level: str
            segments: list[_LessonPlanSegmentLLM]
        ```
  - [ ] 1.2 These are deliberately NOT the frozen `LessonMetadata`/`Segment` models — no `extra="forbid"`, no field-count constraints — so this node's own guard logic (Task 3) runs before any strict validation, mirroring `_SegmentComplexityLLM`'s and `_QuizQuestionLLM`'s documented rationale for staying loose.

- [ ] Task 2: Replace the `lesson_planner_node` stub body (AC: 1, 2, 4, 5)
  - [ ] 2.1 Add the idempotency checkpoint read at the top of the function (AC-5) — mirror `embed_node`'s exact `supabase.table("lesson_jobs").select("node_outputs").eq("lesson_id", lesson_id).single().execute()` pattern (`apps/api/app/modules/content/pipeline/graph.py:678-693`). Cache hit → `return {**state, "lesson_plan": cached, "progress_pct": 38.0}`.
  - [ ] 2.2 Build the prompt: system message states the task (produce a lesson plan outline from segment summaries), explicitly instructs "return exactly one segment per summary provided, echoing back each summary's `segment_id` unchanged" (AC-2), includes `_UNTRUSTED_CONTENT_GUARD` (segment summaries are themselves LLM output from untrusted section text — same guard class every other Phase 1 node's prompt already uses). User message: the `segment_summaries` list (id + text pairs), NOT raw `state["sections"]`/`state["chapter_content"]` (AC-1 — do not read those keys at all in this function).
  - [ ] 2.3 Call `OpenAILLMProvider(lesson_id).complete_structured(messages, settings.llm_lesson_planner, _LessonPlanLLM)` (AC-4). If `response is None` (refusal/parse failure), log a warning and `raise RuntimeError(...)` — do NOT checkpoint, do NOT return a placeholder; let ARQ's job-level retry re-attempt (this premium call has no per-section redundancy to fall back on, unlike Phase 1).
  - [ ] 2.4 Validate (AC-6): `len(response.segments) == len(segment_summaries)`; every `response.segments[i].segment_id` is a member of the input segment_id set with no duplicates; no blank `title`/`subject`/any segment `title`. On any violation: log a warning with specifics (counts, offending IDs) and raise — do not checkpoint a partial/wrong plan.
  - [ ] 2.5 Compute `total_duration_min = sum(seg.duration_min for seg in response.segments)` (AC-7) — never ask the LLM for this number directly.
  - [ ] 2.6 Assemble the `lesson_plan` dict per AC-3's exact shape, using each `_LessonPlanSegmentLLM`'s `segment_id` to look up and carry forward the ORIGINAL summary text from `state["segment_summaries"]` (not the LLM's own paraphrase, if any — the LLM model has no `summary` field to paraphrase into, by design, per Task 1.1).
  - [ ] 2.7 Write the checkpoint (AC-5): `supabase.table("lesson_jobs").update({"last_node": "lesson_planner", "node_outputs": {**node_outputs, "lesson_planner": lesson_plan}}).eq("lesson_id", lesson_id).execute()`.
  - [ ] 2.8 Return `{**state, "lesson_plan": lesson_plan, "progress_pct": 38.0}` — unchanged from the stub's existing progress value.
  - [ ] 2.9 Remove the stub's `# TODO (S2-7): ...` comment and the now-dead `_model = settings.llm_lesson_planner  # noqa: F841` placeholder line (the model is now actually used).

- [ ] Task 3: Tests (AC: all)
  - [ ] 3.1 Happy path: N segment summaries in → `lesson_plan` with N segments out, correct `total_segments`/`total_duration_min` (sum, not LLM-supplied), original summary text preserved verbatim per segment.
  - [ ] 3.2 AC-1 regression guard: assert the prompt sent to `complete_structured` contains ONLY the segment summaries' text — never `state["chapter_content"]` or raw section bodies, even when both are present in `state` alongside `segment_summaries` (simulates the exact 5×-cost-overrun bug this constraint exists to prevent).
  - [ ] 3.3 AC-2/AC-6 guards: LLM returns a mismatched segment count → rejected (raises, not checkpointed); LLM references an unknown `segment_id` → rejected; LLM returns a blank title/subject/segment-title → rejected.
  - [ ] 3.4 AC-5 idempotency: pre-existing `node_outputs["lesson_planner"]` checkpoint → cache hit, zero calls to `complete_structured`.
  - [ ] 3.5 AC-4: confirm `settings.llm_lesson_planner` (not `llm_mini` or any hardcoded string) is the model passed to `complete_structured`.
  - [ ] 3.6 Full regression: `pytest tests/unit/` — 278/278 (current baseline) still passes with zero modifications to existing test files.

## Dev Notes

### The node and its place in the graph already exist — this story replaces the stub body only

`apps/api/app/modules/content/pipeline/graph.py:868-903` is the CURRENT stub (quoted in full):
```python
async def lesson_planner_node(state: PipelineState) -> PipelineState:
    """Node 5 (Phase 2 Premium): generate a structured lesson plan. ...
    AC-0 SCOPE NOTE (Story 2-1): this node's real GPT-4o generation logic is
    S2-7, a separate story — not implemented here. ...
    """
    from app.config import get_settings
    settings = get_settings()
    _model = settings.llm_lesson_planner  # noqa: F841 (used by S2-7, not yet implemented)

    lesson_id = state["lesson_id"]
    segment_summaries = state.get("segment_summaries", [])
    logger.info(...)
    await _update_job_progress(lesson_id, 30.0, "lesson_planner")

    # TODO (S2-7): OpenAILLMProvider(lesson_id).complete_structured(messages, model, LessonPlan)
    lesson_plan: dict[str, Any] = {
        "title": "TODO: LLM-generated title", "objectives": [], "segments": [],
        "total_segments": len(segment_summaries), "total_duration_min": 0,
    }
    return {**state, "lesson_plan": lesson_plan, "progress_pct": 38.0}
```
The graph wiring (`_build_pipeline_graph()`, `graph.py:2205-2212`) already joins all 6 Phase 1 economy nodes → `lesson_planner` → `slide_generator` → `tts_node` → `image_generator` → `package_builder` → `END` — this was Story 2-1 AC-0's fix. **Nothing about the graph topology changes in this story** — only `lesson_planner_node`'s function body. `slide_generator_node` (`graph.py:906-917`) is a separate stub for a separate story (S2-8) — do not touch it here.

### `complete_structured()` already handles cost, ceiling, circuit breaker, retry, and tracing — do not duplicate any of it

`apps/api/app/providers/llm/openai.py:132-219`, quoted for the parts that matter:
```python
@with_retry(max_attempts=3)
async def complete_structured(
    self, messages: list[dict[str, str]], model: str, response_format: type, **kwargs: Any,
) -> Any:
    """Return a structured completion parsed into *response_format* (a Pydantic model)."""
    if await is_circuit_open(_PROVIDER_KEY):
        raise RuntimeError(f"Circuit breaker OPEN for provider '{_PROVIDER_KEY}' — call rejected")
    ...
    response = await self._client.beta.chat.completions.parse(
        model=model, messages=messages, response_format=response_format, **kwargs,
    )
    parsed = response.choices[0].message.parsed
    if response.usage:
        ...
        await self._maybe_accumulate_cost(model, response.usage.prompt_tokens, response.usage.completion_tokens)
    await record_success(_PROVIDER_KEY)
    return parsed
    ...

async def _maybe_accumulate_cost(self, model: str, input_tokens: int, output_tokens: int) -> None:
    ...
    total = await accumulate_cost(self._lesson_id, cost)
    if await check_ceiling(self._lesson_id):
        raise RuntimeError(f"Lesson {self._lesson_id} exceeded cost ceiling at ${total:.4f} — pipeline aborted")
```
`response is None` (refusal/parse failure, same convention every Story 2-1 node already follows — e.g. `summarise_segment_node`'s `if response is None: ... return {"segment_summaries": []}`) is the ONLY case this node needs to handle explicitly; everything else (cost overage, circuit-open, retries) already raises from inside `complete_structured()` itself and should be allowed to propagate. `_COST_PER_1K` (`openai.py:33-36`) already has pricing for `"gpt-4o"` (the current `llm_lesson_planner` default, `apps/api/app/config.py:91-94`) — no pricing-table change needed.

### `segment_summaries` shape (Story 2-1's `summarise_segment_node` output)

`PipelineState.segment_summaries: Annotated[list[dict[str, Any]], operator.add]  # [{segment_id, summary}]` (`graph.py:105`). Each entry is exactly `{"segment_id": section_id, "summary": summary_text}` (`summarise_segment_node`, `graph.py` — the `result` dict it checkpoints and returns). This is the ONLY Phase 1 output this node needs to read for its core function — `complexity_scores`, `glossary`, etc. are separate keys other later nodes/`package_builder` consume, not inputs to `lesson_planner`.

### Untrusted-content guard applies here too

`segment_summaries` text is itself LLM-derived from untrusted section content (the same chain `_UNTRUSTED_CONTENT_GUARD` — `graph.py:960-965` — was written to defend against for every Phase 1 node's prompt). Use the same guard text in this node's system message; do not treat it as a new/different threat model.

### Checkpoint pattern to copy: `embed_node`'s (not Story 2-1b's atomic-RPC one)

`graph.py:677-693` (embed_node's idempotency read) and `graph.py:859-862` (its write) are the exact pattern to mirror:
```python
jobs_resp = (
    supabase.table("lesson_jobs").select("node_outputs").eq("lesson_id", lesson_id).single().execute()
)
node_outputs: dict[str, Any] = (jobs_resp.data or {}).get("node_outputs") or {}
if "embed" in node_outputs:
    cached = node_outputs["embed"]
    ...
    return {**state, "embeddings_stored": True}
...
supabase.table("lesson_jobs").update({
    "last_node": "embed",
    "node_outputs": {**node_outputs, "embed": embed_cache},
}).eq("lesson_id", lesson_id).execute()
```
Story 2-1b's `_read_phase1_checkpoint`/`_write_phase1_checkpoint` (atomic Postgres RPC merge, `graph.py:1002-1083`) exist specifically because up to 6×N **concurrent** `Send()`-dispatched calls can share one `lesson_jobs` row — `lesson_planner` is a single sequential dispatch (no concurrent siblings writing the same row at the same time), so that machinery is unnecessary complexity here. Using the simpler Phase-A pattern is the correct choice, not a shortcut.

### Scope boundary — do not build S2-LM4 (tier-aware slide counts) here

See the Story section above for the full reasoning. Concretely: do not add a `tier` parameter, do not read `state.get("tier")` (the key doesn't exist post-revert), do not vary segment count targets by any tier logic. `LessonMetadata.tier` already defaults to `"T2"` (Story 2-2) — this node's dict output simply has no `tier` key at all, and whichever future code builds `LessonMetadata` from it will get the Pydantic default. When S2-LM1's sign-off eventually lands and S2-LM3/S2-LM4 are re-implemented, S2-LM4 will amend THIS function to read `state["tier"]` and vary its targets — that is out of scope now.

### Branch

Single shared branch for all of Sprint 2: `sprint2/phase-b-generation-nodes` — do not create a new branch. Story-first gate still applies: this file is committed alone and pushed before any implementation commit.

### Testing standards

pytest, matching `apps/api/tests/unit/test_phase1_economy_nodes.py`'s conventions (mock `OpenAILLMProvider.complete_structured` via `AsyncMock`, mock `get_supabase()` for the checkpoint read/write, assert on the exact messages/model passed). Add tests to a new `apps/api/tests/unit/test_lesson_planner_node.py` (parallel to how Story 2-1's economy nodes got their own dedicated test file) rather than growing `test_phase1_economy_nodes.py` (that file is Phase 1-specific; this is the first Phase 2 node).

### Project Structure Notes

No new modules. Edits confined to `lesson_planner_node` and its two new internal Pydantic models inside `apps/api/app/modules/content/pipeline/graph.py`. One new test file.

### References

- [Source: docs/dev1-tracker.md — Sprint 2 section, S2-7]
- [Source: docs/bmad/epics/epic-1-content-pipeline.md — Node 11 spec, lines 73, 84]
- [Source: apps/api/app/modules/content/pipeline/graph.py:868-917 — current stub + slide_generator stub (not touched)]
- [Source: apps/api/app/modules/content/pipeline/graph.py:2170-2218 — graph wiring, already correct]
- [Source: apps/api/app/modules/content/pipeline/graph.py:677-693, 859-862 — embed_node checkpoint pattern to mirror]
- [Source: apps/api/app/modules/content/pipeline/graph.py:105 — segment_summaries PipelineState field + reducer]
- [Source: apps/api/app/providers/llm/openai.py:33-36, 132-219 — complete_structured(), cost/ceiling/breaker/tracing all internal]
- [Source: apps/api/app/config.py:91-94 — llm_lesson_planner setting]
- [Source: apps/api/app/schemas/lesson.py:46-54 — LessonMetadata field names this story's output dict aligns with]
- [Source: docs/stories/2-2-learner-mode-infra.md — Change Log, why tier plumbing was reverted]
- [Source: docs/stories/2-1-phase1-economy-nodes.md — established node patterns: _UNTRUSTED_CONTENT_GUARD, degrade-not-fabricate, internal loose Pydantic models]

## Dev Agent Record

### Agent Model Used

claude-sonnet-5

### Debug Log References

### Completion Notes List

### File List
