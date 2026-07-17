---
baseline_commit: 1c8a5195090c69364b267832e3d56ad2e7631090
---

# Story 2.13: Cost Ceiling Enforcement Wired Into All Sprint 2 Nodes (S2-13)

Status: review

## Story

As a **platform operator**,
I want every premium/media pipeline node to check the per-lesson cost ceiling and downshift to the cheapest available provider instead of aborting when it's breached,
so that a lesson generation run never fails outright over cost — matching CLAUDE.md §14 / PRD's explicit rule ("downshift to cheapest providers on breach, complete the lesson, flag in admin").

**This is a wiring/completion story, not new infrastructure.** `apps/api/app/core/cost_tracker.py`'s `accumulate_cost()`/`check_ceiling()` already exist and are already correctly used by `complete_structured()` (LLM cost, verified not duplicated in nodes) and by `tts_node`/`image_generator_node` (cost accumulation only). What's missing is the ceiling *check* in the 3 of 4 Sprint 2 premium/media nodes that don't have one yet, and the downshift behavior itself.

**Current state, verified by reading the code (not the tracker's prior notes) before writing this story:**

1. `lesson_planner_node` (`graph.py:897`) — **no `check_ceiling()` call at all.** Always calls `settings.llm_lesson_planner` (the premium model) regardless of cost state.
2. `slide_generator_node` (`graph.py:1112`) — **no `check_ceiling()` call at all.** Always calls `settings.llm_slide_generator` (the premium model).
3. `tts_node` (`graph.py:2411`, fallback chain in `_synthesize_with_fallback` at `graph.py:2362`) — accumulates cost after a successful Sarvam/Azure synthesis, but **never checks the ceiling before attempting Sarvam/Azure** — it always tries the paid providers first regardless of cost state, only falling back to free Browser Speech on a provider *failure*, never on a cost *breach*.
4. `image_generator_node` (`graph.py:2598`) — **already correct, no changes needed.** Story 2-9 already added a proactive per-slide `check_ceiling()` pre-check (`graph.py:2686`) that skips straight to `image_url=None` (free, text-only) when over ceiling, before calling any provider. This story's job for this node is verification only.
5. `_fan_out_phase1_economy_nodes` (`graph.py:3014`) — already gates Phase 1 dispatch on `check_ceiling()` (Story 2-1 AC-7), but **terminates the pipeline** (`status="failed"`, `cost_ceiling_exceeded:` error prefix) rather than downshifting, because `settings.llm_mini` (already the cheapest LLM tier) has no cheaper model to downshift *to*. **This story does NOT change Phase 1's behavior** — it was a deliberate, already-reviewed decision (Story 2-1 AC-7's own note), and there is no cheaper LLM tier available to downshift Phase 1 into. Changing "no cheaper tier exists → terminate" into "accept unlimited overage → never abort" is a real cost-safety tradeoff this story does not have the authority to make unilaterally; it is flagged in Dev Notes as a known, accepted gap against the literal PRD wording, not silently left inconsistent.

**No admin panel exists yet** (S3-4, Sprint 3, not started) to "flag in admin" against. This story's interpretation of that requirement: write a durable, queryable downshift record into `lesson_jobs.node_outputs["_cost_downshifts"]` (an additive, non-breaking JSONB key alongside the existing per-node checkpoint keys) so a future S3-4 admin panel has something real to read — not a literal UI flag, which doesn't exist to write to yet.

## Acceptance Criteria

1. **`lesson_planner_node` checks `check_ceiling(lesson_id)` before calling the LLM.** If over ceiling: use `get_llm_provider(settings.llm_mini, lesson_id)` + `settings.llm_mini` as the model string instead of `settings.llm_lesson_planner`, log a warning, and record a downshift entry (AC-5). The node completes normally otherwise — never raises solely because of a ceiling breach.
2. **`slide_generator_node` checks `check_ceiling(lesson_id)` before calling the LLM.** Identical downshift pattern: `settings.llm_slide_generator` → `settings.llm_mini` when over ceiling.
3. **`tts_node` checks `check_ceiling(lesson_id)` once per segment, before calling `_synthesize_with_fallback`.** If over ceiling: skip straight to the Browser Speech fallback (`audio_bytes=None`, `audio_provider="browser"`, `cost=0.0`) for that segment — do not attempt Sarvam or Azure. Record a downshift entry (AC-5) the first time this fires for a given lesson (not once per segment — avoid flooding `node_outputs` with a duplicate entry per segment in a long chapter).
4. **`image_generator_node` is verified unchanged and already correct** — its existing per-slide `check_ceiling()` pre-check (Story 2-9 AC-3, `graph.py:2686`) already satisfies this story's intent. No code change; a regression test confirms the behavior is still present.
5. **Downshift recorded for admin visibility**: each of the 3 nodes above, on its first ceiling-triggered downshift for a given lesson, appends one entry to `lesson_jobs.node_outputs["_cost_downshifts"]` — `{"node": "<node_name>", "from_model_or_provider": "...", "to_model_or_provider": "...", "at": "<ISO-8601 UTC>"}`. This key is additive JSONB, never overwrites existing per-node checkpoint keys, and its own presence/absence has zero effect on any node's idempotency-checkpoint logic (it's not itself a checkpoint key another node's cache-hit check reads).
6. **No pipeline run fails solely because of a cost-ceiling breach in `lesson_planner_node`/`slide_generator_node`/`tts_node`/`image_generator_node`** — a simulated over-ceiling run through each of these 4 nodes completes that node successfully (degraded, not aborted). Phase 1's existing pre-dispatch terminate-on-breach behavior (`_fan_out_phase1_economy_nodes`) is explicitly OUT of this AC's scope (see Dev Notes) and is asserted unchanged by a regression test, not newly passing this AC.
7. All existing tests continue to pass unmodified (except the file(s) this story explicitly touches).

## Tasks / Subtasks

- [x] Task 1: Shared downshift-recording helper (AC: 5)
  - [x] 1.1 Add `_record_cost_downshift(lesson_id, node_name, from_value, to_value)` in `graph.py`, near `_update_job_progress` — reads current `node_outputs`, appends to `node_outputs.get("_cost_downshifts", [])`, writes back via a plain `.update()` (Phase-A style, matching every other node's checkpoint write — no atomic-merge RPC needed here, this key has no concurrent-writer risk since each node's downshift check runs once for premium nodes and is dedup'd within `tts_node`'s own loop).
  - [x] 1.2 Helper never raises — wrap its own Supabase write in try/except and log-and-continue on failure (recording a downshift must never itself become a new way for the pipeline to fail).

- [x] Task 2: `lesson_planner_node` downshift (AC: 1)
  - [x] 2.1 Before `provider = get_llm_provider(settings.llm_lesson_planner, lesson_id)`, call `await check_ceiling(lesson_id)`.
  - [x] 2.2 If over ceiling: set `model = settings.llm_mini`, `provider = get_llm_provider(model, lesson_id)`; else `model = settings.llm_lesson_planner`, existing provider line. Pass `model` (not the hardcoded `settings.llm_lesson_planner`) into both `get_llm_provider(...)` and `provider.complete_structured(messages, model, _LessonPlanLLM)`.
  - [x] 2.3 On downshift, log a warning and call `_record_cost_downshift(lesson_id, "lesson_planner", settings.llm_lesson_planner, settings.llm_mini)`.

- [x] Task 3: `slide_generator_node` downshift (AC: 2)
  - [x] 3.1 Identical pattern to Task 2, substituting `settings.llm_slide_generator` for `settings.llm_lesson_planner`.

- [x] Task 4: `tts_node` per-segment ceiling pre-check (AC: 3)
  - [x] 4.1 Inside the per-segment loop (the non-cache-hit branch, `graph.py:2467` onward), before calling `_synthesize_with_fallback`, call `await check_ceiling(lesson_id)`.
  - [x] 4.2 If over ceiling: skip the call entirely, set `audio_bytes, audio_provider, cost = None, "browser", 0.0` directly (mirrors what `_synthesize_with_fallback` itself returns on total failure — no new code path shape, just skipping straight to its existing terminal branch).
  - [x] 4.3 Track whether a downshift has already been recorded for this lesson (a local `bool` set before the loop) so `_record_cost_downshift` fires at most once per `tts_node` invocation, not once per segment.

- [x] Task 5: Verify `image_generator_node` unchanged (AC: 4)
  - [x] 5.1 No code change. Add/confirm a regression test asserting the existing `check_ceiling()` pre-check at `graph.py:2686` still short-circuits to `image_url=None` without calling either image provider.

- [x] Task 6: Tests (AC: 1, 2, 3, 4, 6, 7)
  - [x] 6.1 `tests/unit/test_lesson_planner_node.py` — new test: `check_ceiling` mocked `True` → provider constructed with `settings.llm_mini`, `complete_structured` called with `settings.llm_mini` as the model arg, node completes and returns a valid `lesson_plan`, downshift entry recorded.
  - [x] 6.2 `tests/unit/test_slide_generator_node.py` — mirror of 6.1 for `slide_generator_node`.
  - [x] 6.3 `tests/unit/test_tts_node.py` — new test: `check_ceiling` mocked `True` for one segment → `SarvamTTSProvider`/`AzureTTSProvider` never constructed/called for that segment, `Narration.audio_provider == "browser"`, `cost == 0.0`; a second test with 2 segments confirms the downshift record is written exactly once, not twice.
  - [x] 6.4 `tests/unit/test_image_generator_node.py` (or wherever Story 2-9's existing ceiling test lives — locate first, extend if present rather than duplicating) — confirm still passing / add if genuinely missing.
  - [x] 6.5 Full regression suite run before and after — record pass/fail counts in Dev Agent Record, matching every prior Sprint 2 story's convention.

## Dev Notes

### Why Phase 1 (economy nodes) is explicitly out of scope

`_fan_out_phase1_economy_nodes` (`graph.py:3014`) already calls `check_ceiling()` before dispatching `Send()` for Phase 1, and terminates the pipeline on breach with a `cost_ceiling_exceeded:` prefixed error (see `content_pipeline_job`'s `except RuntimeError` branch, `apps/api/app/workers/jobs/content_pipeline.py:134-145`). This was Story 2-1 AC-7's own deliberate, already-reviewed decision, for a concrete reason: `settings.llm_mini` (`gpt-4o-mini`) is already the cheapest LLM tier configured anywhere in this pipeline — there is nothing to downshift a Phase 1 economy node *to*. The only way to literally satisfy "never abort" for Phase 1 would be to accept unlimited cost overage past the $3.00 ceiling, which is a real, consequential safety tradeoff (a runaway/malicious upload could otherwise generate unbounded LLM spend) that this story does not have standing to decide unilaterally. Documented here as a known, accepted gap against the PRD's literal wording — not something silently left half-done. If the team wants Phase 1 changed too, that's a separate, explicit decision (with its own AC on "how much overage is acceptable"), not a byproduct of this story.

### `lesson_planner_node` — exact insertion point

Current (`graph.py:961-962, 985`):
```python
settings = get_settings()
provider = get_llm_provider(settings.llm_lesson_planner, lesson_id)
...
response = await provider.complete_structured(messages, settings.llm_lesson_planner, _LessonPlanLLM)
```
Becomes (shape, not final code):
```python
from app.core.cost_tracker import check_ceiling

settings = get_settings()
model = settings.llm_lesson_planner
if await check_ceiling(lesson_id):
    logger.warning("[%s] lesson_planner_node: cost ceiling reached, downshifting %s -> %s",
                    lesson_id, settings.llm_lesson_planner, settings.llm_mini)
    model = settings.llm_mini
    await _record_cost_downshift(lesson_id, "lesson_planner", settings.llm_lesson_planner, settings.llm_mini)
provider = get_llm_provider(model, lesson_id)
...
response = await provider.complete_structured(messages, model, _LessonPlanLLM)
```
`slide_generator_node` is the identical shape substituting `llm_slide_generator`.

### `tts_node` — exact insertion point

Current per-segment body starts at `graph.py:2477` (`try: script = entry["script"] ...`), and calls `_synthesize_with_fallback` at `graph.py:2486`. Insert the `check_ceiling()` branch immediately before that call, inside the existing `try` block (so a ceiling-check failure is caught by the same per-segment `except Exception` that already exists, rather than needing new error handling) — the assignment target (`audio_bytes, audio_provider, cost`) is unchanged either way, so the rest of the function (Storage upload, `Narration.model_validate`, checkpoint write) needs zero changes.

### `image_generator_node` — confirm, don't touch

Story 2-9's existing check (`graph.py:2684-2692`) is architecturally identical to what this story adds to `tts_node` — a proactive per-item pre-check before any provider call, degrading to the free option. Use it as the reference pattern; do not modify this node.

### `_record_cost_downshift` placement and shape

Sibling to `_update_job_progress` (search for that function's definition in `graph.py` for the exact read-modify-write pattern to mirror — read `node_outputs`, merge the new key in, `.update()` the row). This is a Phase-A style plain read-then-write, not Story 2-1b's atomic RPC — there's no concurrent-writer risk here (each of the 3 call sites runs once, or in `tts_node`'s case, is dedup'd to fire at most once per node invocation via a local flag before the write happens).

### Testing standards

pytest, matching sibling stories' conventions — mock `app.core.cost_tracker.check_ceiling` (not the underlying Redis calls) at each node's own import site, same as existing tests mock `accumulate_cost`. Extend the existing per-node test files rather than creating new ones (`test_lesson_planner_node.py`, `test_slide_generator_node.py`, `test_tts_node.py` all already exist).

### Branch

Single shared branch for all of Sprint 2: `sprint2/phase-b-generation-nodes` — do not create a new branch. Story-first gate still applies: this story file is committed alone before any implementation commit.

### Project Structure Notes

`apps/api/app/modules/content/pipeline/graph.py` modified (`lesson_planner_node`, `slide_generator_node`, `tts_node`, plus one new helper `_record_cost_downshift`; `image_generator_node` untouched). Test files extended: `tests/unit/test_lesson_planner_node.py`, `tests/unit/test_slide_generator_node.py`, `tests/unit/test_tts_node.py`, and whichever file already covers `image_generator_node`'s Story 2-9 ceiling check (verify only).

### References

- [Source: docs/dev1-tracker.md — Sprint 2 section, S2-13]
- [Source: CLAUDE.md — Failure Modes §14: "Cost ceiling: $3.00/lesson — downshift to cheapest providers on breach, complete lesson, flag in admin"]
- [Source: apps/api/app/core/cost_tracker.py — `accumulate_cost()`/`check_ceiling()`, already anticipates this story: `check_ceiling()`'s own docstring says "Downshift-and-complete is S2-13"]
- [Source: docs/stories/2-1-phase1-economy-nodes.md — AC-7, the deliberate Phase-1 terminate-on-breach decision this story does not reopen]
- [Source: docs/stories/2-9-image-generator-node.md — AC-3, the reference pattern this story mirrors for `tts_node`]
- [Source: apps/api/app/modules/content/pipeline/graph.py — `lesson_planner_node` (897), `slide_generator_node` (1112), `tts_node` (2411)/`_synthesize_with_fallback` (2362), `image_generator_node` (2598), `_fan_out_phase1_economy_nodes` (3014)]

## Dev Agent Record

### Agent Model Used

claude-sonnet-5

### Debug Log References

- Ran the 3 affected node test files before any code change to confirm baseline: 48 passed. After wiring `check_ceiling()` unconditionally into all 3 nodes, re-ran and got 34 new failures — all `RuntimeError: Redis pool is not initialised`, because none of the pre-existing tests mocked `check_ceiling`/Redis. Fixed by adding an `autouse=True` pytest fixture per file patching `app.core.cost_tracker.check_ceiling` to `AsyncMock(return_value=False)` by default — restores all 48 pre-existing tests to green with zero per-test edits, and downshift-specific new tests override the default explicitly.
- Full-suite baseline check: re-ran `pytest tests -q` (not just `tests/unit`) after implementation — 945 passed, 48 pre-existing failures, 2 skipped. Confirmed the 48 failing files are exactly the same 5 files Story 2-12 already documented as pre-existing/unrelated (`test_auth.py`, `test_dna_fusion.py`, `test_dna_growth.py`, `test_onboarding_content.py`, `test_tutor_service.py` — all Dev 3/Dev 4 owned) — zero new failures introduced by this story.
- Verified `image_generator_node`'s existing ceiling check (Story 2-9 AC-3) already has a dedicated test (`tests/unit/test_image_generator_node.py:159`, `check_ceiling` mocked `True`) — Task 5 required no new code or test.

### Completion Notes List

- All 6 tasks / 15 subtasks complete. Added `_record_cost_downshift()` helper (`graph.py`, sibling to `_update_job_progress`) — appends a durable `{node, from_model_or_provider, to_model_or_provider, at}` entry to `lesson_jobs.node_outputs["_cost_downshifts"]` (additive JSONB, never touches per-node checkpoint keys), for a future S3-4 admin panel to read.
- `lesson_planner_node` and `slide_generator_node` now call `check_ceiling(lesson_id)` before selecting a provider; over ceiling, both downshift `settings.llm_lesson_planner`/`settings.llm_slide_generator` → `settings.llm_mini` for both provider selection and the `complete_structured()` model argument, and record one downshift entry. Neither node raises solely for a ceiling breach — this satisfies CLAUDE.md §14's "downshift... complete the lesson" for the two nodes that previously had zero ceiling awareness.
- `tts_node` now checks `check_ceiling(lesson_id)` once per segment inside the existing per-segment loop, mirroring `image_generator_node`'s established Story 2-9 pattern exactly — over ceiling, skips `_synthesize_with_fallback` (Sarvam/Azure) entirely and degrades straight to the free browser fallback for that segment. A local `downshift_recorded` flag ensures the downshift entry is written at most once per node invocation, not once per over-ceiling segment.
- `image_generator_node` verified unchanged and already correct (Story 2-9 AC-3's existing per-slide pre-check) — no code change, existing test coverage confirmed sufficient.
- **Phase 1 economy nodes' terminate-on-breach behavior (`_fan_out_phase1_economy_nodes`) is explicitly and deliberately left unchanged** — documented in this story's Dev Notes as a known, accepted gap against the PRD's literal "never abort" wording: `settings.llm_mini` is already the cheapest configured LLM tier, so there is nothing to downshift Phase 1 *to*. Changing this to "accept unlimited cost overage" is a real safety tradeoff outside this story's authority to decide unilaterally.
- New tests: 1 downshift test each for `lesson_planner_node` and `slide_generator_node` (assert model swap + downshift record + node completes normally), 1 downshift test for `tts_node` (assert Sarvam/Azure classes never constructed, downshift recorded exactly once across 2 segments, not twice).
- Full regression suite: 945 passed (up from a 942-test baseline established by Story 2-12, +3 for this story's new tests), same 48 pre-existing unrelated failures (5 files, all Dev 3/Dev 4 owned), 2 skipped — 0 regressions introduced.

### File List

- `apps/api/app/modules/content/pipeline/graph.py` (modified — new `_record_cost_downshift()` helper; `lesson_planner_node`, `slide_generator_node`, `tts_node` each wired with a `check_ceiling()` pre-check and downshift; `image_generator_node` unchanged)
- `apps/api/tests/unit/test_lesson_planner_node.py` (modified — autouse `check_ceiling=False` fixture, 1 new downshift test)
- `apps/api/tests/unit/test_slide_generator_node.py` (modified — autouse `check_ceiling=False` fixture, 1 new downshift test)
- `apps/api/tests/unit/test_tts_node.py` (modified — autouse `check_ceiling=False` fixture, 1 new downshift test)

## Change Log

| Date | Change |
|------|--------|
| 2026-07-17 | Story created via `bmad-create-story`. |
| 2026-07-17 | Implemented via `bmad-dev-story`: wired `check_ceiling()` + downshift-to-`llm_mini`/browser into `lesson_planner_node`, `slide_generator_node`, `tts_node`; added `_record_cost_downshift()` helper; verified `image_generator_node` already correct (Story 2-9). 945 passed / 48 pre-existing unrelated failures (unchanged from Story 2-12's baseline) / 2 skipped in the full `tests` suite — 0 regressions. Status → review. |
