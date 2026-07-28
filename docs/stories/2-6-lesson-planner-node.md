---
baseline_commit: 4942b63e31a41a4d1b1693e8a628973446e07168
---

# Story 2.6: `lesson_planner` Node — Real Structured Generation (S2-7)

Status: done

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
5. **Idempotency checkpoint, matching the Phase A pattern (not Story 2-1b's Phase-1 pattern)** — on entry, read `lesson_jobs.node_outputs`; if `"lesson_planner"` key already exists, return the cached value and skip the LLM call. On success, write `{"last_node": "lesson_planner", "node_outputs": {**node_outputs, "lesson_planner": <cache>}}` via a plain client-side read-modify-write — Phase 2 is sequential (single dispatch, not `Send()`-fanned-out), so the atomic RPC merge built for Phase 1's concurrency (`_write_phase1_checkpoint`) is unnecessary machinery here; reuse the simpler pattern `embed_node`/`chunk_node` already use. **Caveat (added 2026-07-14 review):** this closes re-billing for a retry that starts strictly AFTER a prior attempt's checkpoint write succeeded — a crash/timeout between a successful (billed) LLM call and that checkpoint write still re-bills on the next retry (the exact same accepted tradeoff `embed_node` already carries). Not a "no re-billing, full stop" guarantee.
6. **Degrade-not-fabricate guards, matching Story 2-1's established house style**: if the LLM returns fewer/more `segments` entries than `segment_summaries` had, or references a `segment_id` not present in the input, or returns a blank `title`/`subject`/segment `title`, log a warning and reject the whole response (raise, do not checkpoint, let ARQ retry) rather than silently padding/truncating — unlike Phase 1's economy nodes, there is no per-section redundancy here; a partially-wrong lesson plan can't be safely patched piecemeal the way one bad quiz question can be dropped from a list.
7. **`total_duration_min` is computed by SUMMING the LLM's per-segment `duration_min` values, not asked for as a separate top-level number** — prevents the top-level total and the per-segment breakdown from silently disagreeing (an LLM asked for both independently has no self-consistency guarantee).
8. All existing tests continue to pass unmodified.

## Tasks / Subtasks

- [x] Task 1: Internal structured-output models (AC: 3, 4)
  - [x] 1.1 Added `_LessonPlanSegmentLLM` and `_LessonPlanLLM` immediately before `lesson_planner_node` in `graph.py` (co-located with the node they serve, same as `_QuizQuestionLLM`/`quiz_generator_node`).
  - [x] 1.2 Both loose (no `extra="forbid"`, no length constraints) as specified.

- [x] Task 2: Replace the `lesson_planner_node` stub body (AC: 1, 2, 4, 5)
  - [x] 2.1 Idempotency checkpoint read added, mirroring `embed_node` exactly.
  - [x] 2.2 Prompt built: system message states the task + echoes-segment_id instruction + `_UNTRUSTED_CONTENT_GUARD`; user message is the segment_summaries list only.
  - [x] 2.3 `OpenAILLMProvider(lesson_id).complete_structured(messages, settings.llm_lesson_planner, _LessonPlanLLM)`; `response is None` → `raise RuntimeError`, no checkpoint.
  - [x] 2.4 All four guards implemented: segment-count mismatch, unknown `segment_id`, duplicate `segment_id` (added defensively — not in the original AC text but a direct corollary of "echo back unchanged, no duplicates" and cheap to check), blank title/subject/segment-title.
  - [x] 2.5 `total_duration_min = sum(seg.duration_min for seg in response.segments)`.
  - [x] 2.6 `lesson_plan["segments"]` carries forward the original `summary` text via a `segment_id → summary` lookup built from `state["segment_summaries"]`.
  - [x] 2.7 Checkpoint write added, matching AC-5 exactly.
  - [x] 2.8 Returns `{**state, "lesson_plan": lesson_plan, "progress_pct": 38.0}`.
  - [x] 2.9 Stub's `TODO`/`_model = ... # noqa: F841` lines removed.

- [x] Task 3: Tests (AC: all)
  - [x] 3.1 `test_happy_path_produces_lesson_plan_matching_input_count` — `apps/api/tests/unit/test_lesson_planner_node.py`.
  - [x] 3.2 `test_prompt_never_includes_raw_chapter_text_or_sections` — confirms `chapter_content`/`sections` text never reaches the prompt even when present in `state` alongside `segment_summaries`.
  - [x] 3.3 `test_mismatched_segment_count_is_rejected_not_checkpointed`, `test_unknown_segment_id_is_rejected`, `test_blank_title_is_rejected`, `test_blank_segment_title_is_rejected` (plus `test_refusal_raises_and_does_not_checkpoint` for the `response is None` path — not originally enumerated in 3.3's text but the same "reject, don't checkpoint" guard family).
  - [x] 3.4 `test_idempotency_cache_hit_skips_llm_call`, `test_successful_run_writes_checkpoint`.
  - [x] 3.5 `test_model_used_is_settings_llm_lesson_planner`.
  - [x] 3.6 Full regression: 288/288 passes — **not** zero modifications to existing test files as 3.6 originally assumed; see Dev Agent Record for the one necessary, foreseen exception (`test_phase1_economy_nodes.py`'s AC-0 test).

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

- Red-green-refactor verified: `test_lesson_planner_node.py` written first against the still-stub `lesson_planner_node` — confirmed 10/10 failures (`AttributeError` on `app.providers.llm.openai` not yet imported into `sys.modules`, fixed by force-importing the submodule at test-file top, matching `test_phase1_economy_nodes.py`'s established convention), then implementation applied — 10/10 green.
- Full-suite run after implementation surfaced exactly 1 pre-existing failure (not introduced by new code): `test_phase1_economy_nodes.py::TestAC0GraphOrdering::test_lesson_planner_does_not_require_raw_text_or_chunks` — this test predates any real generation logic and called `lesson_planner_node` with zero provider/DB mocking, which is fundamentally incompatible with a node that now makes a real (mocked-in-other-tests) LLM call. The test's OWN docstring flagged this exact eventuality ("NOTE: this only asserts AC-0... real GPT-4o lesson planning is S2-7, a separate story"). Updated it to mock `OpenAILLMProvider` like every other node's test in the file already does, preserving its original AC-0 assertion (`total_segments` reflects real `segment_summaries` input) — this is a foreseen, documented test update, not a silent regression.
- One test-writing bug found and fixed during Task 3: `_update_job_progress` makes its OWN separate `.update()` call (`{"last_node", "status"}`) on the same mocked `lesson_jobs` table right after the checkpoint write — a test asserting on `mock.update.call_args` (the LAST call) was inspecting the wrong call. Fixed by filtering `call_args_list` for the call containing `"node_outputs"`.

### Completion Notes List

- All 3 tasks / 15 subtasks complete. 297/297 unit tests pass after the code-review patch round (0 unintentional regressions; 1 pre-existing test intentionally updated — see Debug Log; 19 new tests total in `test_lesson_planner_node.py`, up from 10 after 9 more were added for the review-round patches).
- Added one guard beyond the story's literal AC-6 text: duplicate `segment_id`s in the LLM response are also rejected (`test_mismatched_segment_count_is_rejected_not_checkpointed`'s sibling, `test_unknown_segment_id_is_rejected`, covers the unknown-ID case; a dedicated duplicate-ID check was added in the same guard block since "echo back unchanged" implies uniqueness and the check is nearly free once the ID set is already being built).
- Scope boundary held exactly as planned: no `tier` parameter, no `state.get("tier")` read, no tier-conditioned segment-count target. `lesson_plan`'s output dict has no `tier` key — S2-LM4 (a separate future story, blocked on S2-LM1's still-outstanding 4-developer sign-off) will amend this function once tier plumbing is safe to reintroduce.
- AC-1 is enforced both structurally (the function signature/body never references `state["sections"]` or `state["chapter_content"]`) and by a dedicated regression test (`test_prompt_never_includes_raw_chapter_text_or_sections`) that plants both raw-text keys in state alongside `segment_summaries` and asserts neither string appears in the actual prompt sent to `complete_structured`.
- `slide_generator_node` (the very next node in the graph) was NOT touched — it remains today's `[]`-returning stub, correctly out of scope (S2-8, a separate story).
- **Post-review patch round (2026-07-14):** applied all 6 code patches (empty-input guard, malformed-entry guard, `duration_min` validation, `objectives`/`complexity_level` validation with clamp, input-order-preserving assembly) plus 1 documentation-only fix (AC-5 wording). One test-helper bug found while adding patch tests: `_plan_llm_response()`'s default never set `.objectives`, so `MagicMock`'s default empty `__iter__` silently satisfied the NEW empty-objectives guard for every existing happy-path test — fixed by giving the helper an explicit default `objectives` list.

### File List

- `apps/api/app/modules/content/pipeline/graph.py` (modified — `lesson_planner_node` real implementation + 2 new internal Pydantic models + 6 code-review patches + `math` import added)
- `apps/api/tests/unit/test_lesson_planner_node.py` (new — 19 tests: 10 original + 9 for the code-review patches)
- `apps/api/tests/unit/test_phase1_economy_nodes.py` (modified — updated 1 pre-existing test to mock the provider, per its own anticipated-eventuality docstring)
- `docs/stories/2-6-lesson-planner-node.md` (this file — AC-5 wording corrected per review patch)

## Change Log

| Date | Change |
|------|--------|
| 2026-07-14 | Story implemented (Tasks 1-3) via `bmad-dev-story`. `lesson_planner_node` now makes a real `settings.llm_lesson_planner` structured-output call with degrade-not-fabricate guards and a Phase-A-style idempotency checkpoint. 10 new tests; 1 pre-existing test updated (foreseen in its own docstring). 288/288 total passing. |
| 2026-07-14 | 3-layer adversarial code review run (`/bmad-code-review`) — 0 decision-needed, 7 patch, 4 defer, 1 dismissed. All 7 patches applied same day: empty-input guard, malformed-entry guard, `duration_min` validation, `objectives`/`complexity_level` validation+clamp, input-order-preserving segment assembly, and an AC-5 wording correction. 9 new tests added for the patches. 297/297 total passing. |

### Review Findings (2026-07-14 — 3-layer adversarial review via the actual `/bmad-code-review` skill: Blind Hunter, Edge Case Hunter, Acceptance Auditor)

- [x] [Review][Patch] **FIXED 2026-07-14 — Empty `segment_summaries` silently produces a fully-checkpointed, fabricated empty lesson plan.** Added an explicit upfront guard: `lesson_planner_node` now raises `RuntimeError` immediately if `segment_summaries` is empty, before the LLM is ever called. [`graph.py::lesson_planner_node`] (Edge Case Hunter)
- [x] [Review][Patch] **FIXED 2026-07-14 — `duration_min` was accepted unbounded.** Added a guard rejecting any non-positive or non-finite (`NaN`/`inf`) `duration_min` per segment, raising before assembly/checkpoint. [`graph.py::lesson_planner_node`] (Blind Hunter + Edge Case Hunter, independently)
- [x] [Review][Patch] **FIXED 2026-07-14 — `complexity_level` and `objectives` weren't validated.** `objectives` empty/all-blank → reject (matches the title/subject/segment-title guard philosophy). `complexity_level` not in `low/medium/high` → clamp to `"medium"` with a warning log, mirroring `quiz_generator_node`'s existing difficulty-clamp pattern (a deliberate choice: enum-drift fields get clamped elsewhere in this codebase, not rejected outright). [`graph.py::lesson_planner_node`] (Edge Case Hunter)
- [x] [Review][Patch] **FIXED 2026-07-14 — LLM-returned segment order was trusted instead of reconciled against `segment_summaries`' original order.** `segments_out` is now assembled by iterating `segment_summaries` (input order) and looking up each LLM segment by `segment_id` via a `segment_id → LLM segment` map, not by iterating `response.segments` directly. [`graph.py::lesson_planner_node`] (Edge Case Hunter)
- [x] [Review][Patch] **FIXED 2026-07-14 — A malformed `segment_summaries` entry raised a raw `KeyError`.** Added an upfront validation loop raising a contextual `RuntimeError(f"lesson_id={{lesson_id}}: malformed segment_summaries entry missing segment_id/summary: {{s!r}}")` for any entry missing either key. [`graph.py::lesson_planner_node`] (Edge Case Hunter)
- [x] [Review][Patch] **FIXED 2026-07-14 — AC-5's text overclaimed "no re-billing on ARQ retry" with no caveat.** Reworded AC-5 above to state the guarantee precisely: closes re-billing for retries starting after a prior checkpoint write succeeded; a crash between a successful LLM call and that write still re-bills (same accepted tradeoff `embed_node` already carries). Documentation-only fix, no code change. [`docs/stories/2-6-lesson-planner-node.md` AC-5] (Blind Hunter + Edge Case Hunter, independently)
- [x] [Review][Defer] **Plain read-then-write checkpoint has a lost-update race if two executions of this node run concurrently for the same `lesson_id`** (e.g. an ARQ job-timeout-triggered retry racing an original invocation that's still in flight) — both cache-miss, both bill the LLM, last write wins with no lock/version check. This is the identical, already-accepted tradeoff `embed_node`/`chunk_node`/`structure_node` share (Phase A's whole checkpoint style, not novel to this node) — closing it properly needs an atomic RPC merge or optimistic-locking check (`WHERE last_node = ...`), a larger change than this story's scope. [`graph.py::lesson_planner_node`] (Blind Hunter + Edge Case Hunter, independently) — deferred, matches existing accepted Phase A risk.
- [x] [Review][Defer] **A `segment_summaries` entry with a blank-but-present `summary` string flows through uncaught** — root cause is upstream in `summarise_segment_node` (Story 2-1), which only guards total refusal (`response is None`), not a blank-but-parsed summary. Pre-existing gap, out of this diff's scope. [`graph.py::summarise_segment_node`] (Edge Case Hunter) — deferred to whoever next touches Story 2-1's node.
- [x] [Review][Defer] **`.single().execute()` has no explicit not-found/exception handling shown** — identical pattern already used unguarded by `embed_node`/`chunk_node`/`structure_node` throughout this file; not a regression specific to this diff. [`graph.py::lesson_planner_node`] (Blind Hunter) — deferred, codebase-wide pre-existing pattern.
- [x] [Review][Defer] **No length/size bound on LLM-controlled `objectives`/`title`/`subject` before persistence** — theoretical storage-bloat/DoS vector; low severity given this endpoint already sits behind auth, per-user rate limiting, and the pipeline's own cost ceiling. [`graph.py::_LessonPlanLLM`] (Blind Hunter) — deferred, same risk class as Story 2-2's deferred unbounded-Form-field finding.

**Dismissed (1):** the idempotency cache-hit branch also calls `_update_job_progress` (unlike `embed_node`'s cache-hit branch, which doesn't) — Acceptance Auditor's own conclusion: "harmless... not an AC violation," just a minor undocumented behavioral delta from the Dev Notes' "mirrors exactly" phrasing.
