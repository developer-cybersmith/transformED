---
baseline_commit: ef855ea26ec86092cc297ffe326a3b11c816d9b3
---

# Story 2.11: `package_builder` Node — Final Assembly, Validation, DB Write (S2-11)

Status: ready-for-dev

## Story

As a **student whose chapter has now generated a lesson plan, slides, quiz questions, audio, images, and glossary/intervention content across 10 prior pipeline nodes**,
I want all of that scattered per-node state assembled into one validated `LessonPackage`, written to the database as `ready`,
so that the lesson player has a single, schema-guaranteed-correct JSONB document to render — this is Epic 1's terminal node, the one that turns 10 nodes' worth of partial state into an actual deliverable lesson.

This story implements the REAL body of `package_builder_node` — tracker task **S2-11** in `docs/dev1-tracker.md`, Epic 1's Node 15 (final node). The node function and its place in the graph already exist as a stub — this story replaces the stub body.

**Two scope boundaries, deliberately narrow — read before implementing:**

1. **The WebSocket `lesson_ready` push is explicitly OUT OF SCOPE for this story.** The tracker lists it as sub-step 5 under S2-11's own entry, but ALSO as its own separate line item, **S2-12**, both annotated "coordinate with Dev 4 before implementing." This story implements steps 1–4 only (assemble, validate, write `lessons`, write `lesson_jobs` completion) — no WebSocket code, no `app/core/websocket.py` changes. S2-12 is Dev 4's follow-up story.
2. **Signed-URL generation for stored images/audio is explicitly OUT OF SCOPE.** `Slide.image_url` was originally typed `AnyHttpUrl`, which would force this node to mint a signed URL for every stored image — but a signed URL baked into `lessons.content` JSONB expires (Supabase max ~7 days) while a generated lesson may be viewed weeks later, silently breaking playback. Per a project-level decision, **this story instead relaxes the frozen contract** (Task 1) so `image_url`/`fallback_image_url` store the bare Supabase Storage path (a `str`, matching `Narration.audio_url`'s existing type) — URL resolution at view time is a separate future component's responsibility, not this node's.

## Acceptance Criteria

1. **Frozen contract change (Task 1, do first): `Slide.image_url`/`Slide.fallback_image_url` relaxed from `AnyHttpUrl | None` to `str | None`** in `apps/api/app/schemas/lesson.py`, and `packages/shared/lesson_package.schema.json`'s matching `"format": "uri"` constraint removed (kept as a plain nullable string). `packages/shared/types/lesson.ts` needs NO change — it already types both fields as `string | null`. This is a frozen-contract edit (PRD §16) — flag it explicitly in the PR/commit message as needing sign-off from all 4 developers, mirroring Story 2-2/S2-LM1's precedent for the `tier` field (implemented, tracked as pending cross-team sign-off, not blocking).
2. **`chapter_id` resolved from the existing `chunk_node` checkpoint** — `node_outputs["chunk"]["chapter_id"]` (written by `chunk_node`, already read the same way by `embed_node`) — NOT a new `PipelineState` field, NOT a placeholder. `PipelineState` has no `chapter_id` key; do not add one — read it from the checkpoint exactly like `embed_node` already does.
3. **`LessonMetadata` built from `state["lesson_plan"]`** — `title`, `subject`, `total_segments`, `complexity_level` copied directly; `estimated_duration_mins` = `lesson_plan["total_duration_min"]`; `tier` left at its Pydantic default (`"T2"`) — tier plumbing is blocked on S2-LM1's pending sign-off (see `docs/dev1-tracker.md`'s S2-LM1..LM5 entries), do not attempt to thread a real tier value through.
4. **Each `Segment` assembled by iterating `state["lesson_plan"]["segments"]`** (the authoritative order and id set, same discipline `lesson_planner_node`/`slide_generator_node` already established), correlating every other per-segment list by `segment_id`:
   - `complexity` ← `state["complexity_scores"]` entry matching `segment_id` (already flat-shaped: `level`/`cognitive_load`/`abstraction_level`/`prerequisite_concepts`/`narration_style`/`quiz_difficulty`/`intervention_sensitivity` — maps 1:1 onto `SegmentComplexity`, no unwrapping needed).
   - `slides` ← every `state["slides"]` entry whose `segment_id` matches, taking each entry's `data` (already `Slide`-shaped except `image_url` is always `None` at this point) and overlaying the real value from `state["slide_images"]` (a FLAT `{slide_id, image_url}` list — Story 2-9's deliberate flat design — correlate by `slide_id`, NOT `segment_id`). `fallback_image_url` stays `None` — no node produces it yet, do not fabricate a value.
   - `narration` ← the single `state["audio_assets"]` entry matching `segment_id`, taking its `data` (already `Narration`-shaped: `script`/`audio_url`/`audio_provider`/`timestamps`).
   - `quiz` ← every `state["quiz_questions"]` entry matching `segment_id`, taking each entry's `data` (already `QuizQuestion`-shaped).
   - `jargon` ← every `state["glossary"]` entry matching `segment_id`, taking each entry's `data` (already `JargonEntry`-shaped: `term`/`definition`).
   - `interventions` ← the single `state["intervention_prompts"]` entry matching `segment_id`, taking its `data` (already `SegmentInterventions`-shaped).
   - `teachback_prompt` ← **PLACEHOLDER, explicitly provisional** (see AC-8) — a deterministic template, no LLM call.
   - `segment_index` ← the segment's 0-based position in `lesson_plan["segments"]`'s own order.
5. **Per-segment graceful degradation, matching this pipeline's established "one bad item never crashes the whole node" philosophy** — a segment missing its `complexity`, `narration`, `interventions` entry, OR with zero matched `slides`, is a segment this node CANNOT validly assemble (all four are non-optional/non-empty fields on the frozen `Segment` model). Log a clear warning citing the missing piece and **skip that segment entirely** from the assembled package — do not crash the whole node over one degraded upstream section. `quiz`/`jargon` may legitimately be empty lists for a segment (no `min_length` constraint on either field) — an empty match there is NOT a reason to skip the segment.
6. **If EVERY segment gets skipped (the resulting `segments` list is empty), raise `RuntimeError`** — `LessonPackage.segments` has `Field(min_length=1)`; a lesson with zero usable segments is a genuine pipeline failure, not a degradable case, and must surface as a failed job rather than silently write an unusable "ready" lesson.
7. **Top-level `LessonPackage.glossary` is a deduplicated aggregate across ALL segments' `jargon` entries** — not a copy of any single segment's list. Dedup key: `term.strip().lower()` (same normalization style as `quiz_generator_node`'s existing `_normalize_option` duplicate-detection precedent) — first occurrence wins, keep its original-cased term/definition.
8. **`teachback_prompt` placeholder is clearly marked provisional in both code and story** — e.g. a comment/docstring stating this is a deterministic placeholder pending confirmation from whoever owns the teach-back feature (Dev 3, per `CLAUDE.md`'s team ownership table), not a finalized design. Suggested template: `f"In your own words, explain what you learned about {segment_title}."` — no LLM call, zero cost, trivially swappable later.
9. **`LessonPackage.model_validate(assembled)` called and allowed to raise** — a schema violation must surface immediately as a node failure (bubbling up to ARQ retry/failure handling), never be caught and silently degraded. This is the single sentence the tracker's own AC insists on; do not wrap it in a broad `try/except` that would defeat it.
10. **On success: `lessons.content = package.model_dump(mode="json")`, `lessons.status = "ready"`, `lessons.title = package.metadata.title`** (the `lessons` table already has a `title` column, currently always `NULL` from every prior node — this is the first node that can populate it). **`lesson_jobs.status = "completed"`, `lesson_jobs.completed_at` set to the current UTC time (ISO-8601)** — no existing helper does this; every prior node's `_update_job_progress()` only ever sets `status="running"`.
11. **Idempotency checkpoint, Phase-A style** (same pattern as the other Phase 2/3 nodes) — read `lesson_jobs.node_outputs`; `"package_builder"` key present → return the cached `lesson_package` directly, skip all reassembly and skip re-writing `lessons`/`lesson_jobs` (a completed lesson must not be re-validated/re-written on an ARQ retry that reaches this node again). On success, write the checkpoint.
12. **No WebSocket code of any kind** (see Story scope note — S2-12's job, not this story's).
13. **No signed-URL/Supabase Storage calls of any kind** in this node — `image_url`/`audio_url` are copied through as the bare paths already stored by `image_generator_node`/`tts_node`, unmodified (see Story scope note).
14. All existing tests continue to pass unmodified (aside from the 2-3 tests noted in Dev Notes that assert against the pre-relaxation `Slide` field type, if any exist).

## Tasks / Subtasks

- [ ] Task 1: Relax the frozen `Slide.image_url`/`fallback_image_url` contract (AC: 1)
  - [ ] 1.1 `apps/api/app/schemas/lesson.py`: change both fields from `AnyHttpUrl | None` to `str | None`; remove the now-unused `AnyHttpUrl` import (grep first to confirm nothing else in the file uses it).
  - [ ] 1.2 `packages/shared/lesson_package.schema.json`: remove `"format": "uri"` from both `Slide.image_url`/`fallback_image_url` (keep `oneOf [{"type": "string"}, {"type": "null"}]` or simplify to `{"type": ["string", "null"]}` — either is schema-equivalent, pick whichever matches the file's existing style elsewhere).
  - [ ] 1.3 Confirm `packages/shared/types/lesson.ts` needs no change (already `string | null` for both fields) — do not edit it.
  - [ ] 1.4 Run the existing schema/slide test suite (`test_lesson_schema.py`, `test_slide_generator_node.py`) to confirm nothing asserted URL-format validation (Dev Notes below already confirms this via a pre-implementation grep — verify it still holds).

- [ ] Task 2: Replace the `package_builder_node` stub body — assembly (AC: 2, 3, 4, 5, 6, 7, 8)
  - [ ] 2.1 Idempotency checkpoint read added (Phase-A style), returning cached `lesson_package` on a `"package_builder"` cache hit.
  - [ ] 2.2 `chapter_id` resolved from `node_outputs["chunk"]["chapter_id"]` (mirror `embed_node`'s exact read pattern).
  - [ ] 2.3 `LessonMetadata` fields mapped from `state["lesson_plan"]` per AC-3.
  - [ ] 2.4 Per-segment assembly loop over `lesson_plan["segments"]`, correlating `complexity_scores`/`slides`+`slide_images`/`audio_assets`/`quiz_questions`/`glossary`/`intervention_prompts` by `segment_id` (and `slide_images` by `slide_id`) per AC-4.
  - [ ] 2.5 Degrade-and-skip logic for segments missing `complexity`/`narration`/`interventions`/any `slides`, with a clear warning log per AC-5; `RuntimeError` if the resulting segment list is empty per AC-6.
  - [ ] 2.6 Top-level deduplicated `glossary` aggregation per AC-7.
  - [ ] 2.7 `teachback_prompt` placeholder per AC-8, clearly commented as provisional.

- [ ] Task 3: Validation + DB writes (AC: 9, 10, 11)
  - [ ] 3.1 `LessonPackage.model_validate(assembled)` called, uncaught.
  - [ ] 3.2 `lessons` table updated: `content`, `status="ready"`, `title`.
  - [ ] 3.3 `lesson_jobs` table updated: `status="completed"`, `completed_at` (current UTC ISO-8601).
  - [ ] 3.4 Idempotency checkpoint written on success (`node_outputs["package_builder"] = lesson_package`).
  - [ ] 3.5 Return `{**state, "lesson_package": lesson_package, "progress_pct": 100.0}` (matches the stub's existing return shape).

- [ ] Task 4: Tests (AC: all)
  - [ ] 4.1 New `test_package_builder_node.py`: happy path (all 10 upstream outputs present, 2+ segments) produces a `LessonPackage.model_validate()`-passing dict; `lessons`/`lesson_jobs` tables updated correctly; checkpoint written.
  - [ ] 4.2 Segment missing `complexity`/`narration`/`interventions`/all `slides` → that segment skipped, others still assembled, warning logged.
  - [ ] 4.3 ALL segments missing required data → `RuntimeError` raised, no `lessons`/`lesson_jobs` write attempted.
  - [ ] 4.4 `slide_images` correlation is by `slide_id`, not `segment_id` — a slide's `image_url` populated correctly even though `slide_images` has no `segment_id` field at all.
  - [ ] 4.5 Top-level `glossary` dedup: two segments each contributing a jargon entry with the same term (differing case/whitespace) → one entry in the final `glossary`, first occurrence's casing preserved.
  - [ ] 4.6 Idempotency cache-hit: `node_outputs["package_builder"]` already present → cached value returned, no re-validation, no `lessons`/`lesson_jobs` write.
  - [ ] 4.7 `LessonPackage.model_validate()` failure (deliberately malformed assembled dict) propagates as an uncaught exception — regression guard proving AC-9 isn't accidentally wrapped in a swallowing `try/except`.
  - [ ] 4.8 No test asserts any WebSocket or Supabase Storage (`create_signed_url`/`upload`) call from this node — a `Mock`/spy assertion that Storage/WS clients are never touched, guarding against scope creep back into AC-12/13's explicit exclusions.
  - [ ] 4.9 Full regression suite passes.

## Dev Notes

### The node and its place in the graph already exist — this story replaces the stub body only

Current stub (`graph.py`, quoted in full):
```python
async def package_builder_node(state: PipelineState) -> PipelineState:
    """Node 15: Assemble all outputs into the final lesson JSON package."""
    lesson_id = state["lesson_id"]
    logger.info("[%s] package_builder_node: assembling lesson package", lesson_id)
    await _update_job_progress(lesson_id, 95.0, "package_builder")

    lesson_package: dict[str, Any] = {
        "lesson_id": lesson_id,
        "lesson_plan": state.get("lesson_plan", {}),
        "slides": state.get("slides", []),
        "audio_assets": state.get("audio_assets", []),
        "slide_images": state.get("slide_images", []),
        "quiz_questions": state.get("quiz_questions", []),
        "glossary": state.get("glossary", []),
        "intervention_prompts": state.get("intervention_prompts", []),
        "segment_summaries": state.get("segment_summaries", []),
    }

    # Final DB update
    await _update_job_progress(lesson_id, 100.0, "complete")

    return {**state, "lesson_package": lesson_package, "progress_pct": 100.0}
```
This stub's shape is NOT the `LessonPackage` schema at all (it's a flat dump of raw state, no `metadata`/`segments` structure) — this story replaces it wholesale, not incrementally.

### Exact per-node output shapes as of baseline commit `ef855ea` — read before writing the correlation logic

| State key | Shape | Correlation key |
|---|---|---|
| `state["lesson_plan"]` | single dict: `{title, subject, objectives, complexity_level, total_segments, total_duration_min, segments: [{segment_id, title, summary, duration_min}]}` | — (this IS the authoritative segment order/id set) |
| `state["complexity_scores"]` | flat list: `[{segment_id, level, cognitive_load, abstraction_level, prerequisite_concepts, narration_style, quiz_difficulty, intervention_sensitivity}]` | `segment_id` |
| `state["slides"]` | list: `[{segment_id, data: {slide_id, title, bullets, image_url: None, fallback_image_url: None}}]` — MULTIPLE entries share the same `segment_id` (1-8 slides per segment) | `segment_id` (grouping), `slide_id` (image correlation, see below) |
| `state["slide_images"]` | **FLAT** list, deliberately no `segment_id` at all (Story 2-9's design): `[{slide_id, image_url}]` | `slide_id` ONLY |
| `state["audio_assets"]` | list, ONE entry per segment: `[{segment_id, data: {script, audio_url, audio_provider, timestamps: []}}]` | `segment_id` |
| `state["quiz_questions"]` | list: `[{segment_id, data: {question_id, type, question, options, correct_index, explanation, difficulty}}]` | `segment_id` |
| `state["glossary"]` | list, MULTIPLE entries per segment possible: `[{segment_id, data: {term, definition}}]` | `segment_id` |
| `state["intervention_prompts"]` | list, ONE entry per segment: `[{segment_id, data: {distraction: [3 str], confusion: [3 str], fatigue: [3 str]}}]` | `segment_id` |

The inconsistency between flat (`complexity_scores`, `audio_assets`'s outer shape uses `data` wrapper — actually check carefully) and nested (`quiz_questions`, `glossary`, `intervention_prompts`, `slides` all wrap the payload in a `data` key) shapes is NOT a bug to fix in this story — it's each sibling story's own established, already-reviewed convention (see each story's own Dev Notes for why). This node's job is to correlate across these inconsistent shapes correctly, not to normalize them retroactively.

### `chapter_id` — read from the existing checkpoint, do not invent a new field

`chunk_node` (`graph.py`, Sprint 1) creates the `chapters` table row and stores `chapter_id` in its OWN checkpoint: `node_outputs["chunk"]["chapter_id"]`. `embed_node` already reads it back the identical way:
```python
chapter_id: str = (node_outputs.get("chunk") or {}).get("chapter_id", "")
```
Mirror this exactly. `PipelineState` has no `chapter_id` TypedDict key and this story does not add one — the checkpoint read is already the established pattern for cross-node data that isn't part of the main state flow.

### Signed URLs — explicitly not this node's job (project decision, see Story's scope note)

Both `image_url` (from `image_generator_node`, path shape `{lesson_id}/{slide_id}.png` in the private `lesson-images` bucket) and `audio_url` (from `tts_node`, path shape `{lesson_id}/{segment_id}.mp3` in the private `lesson-audio` bucket, or `""` for browser-fallback/failed generation) are stored as BARE PATHS, not signed URLs, and this node must NOT call `supabase.storage.from_(...).create_signed_url(...)` or any other Storage API — copy the paths through unchanged. This is why Task 1 relaxes `Slide.image_url`'s type: a bare path is not a valid `AnyHttpUrl`. `Narration.audio_url` was already typed as plain `str`, so no schema change was needed on that side — it was already storing a bare path with no complaint from Pydantic, it just wasn't a *documented* choice until this story's Dev Notes made it explicit.

### Degrade-and-skip is a full-segment decision, matching the pipeline's `image_generator_node`/`tts_node` per-item philosophy — applied at the RIGHT granularity here

Every prior media/premium node degrades at the SLIDE or SEGMENT level (never crashing the whole node over one bad item) — but this node is the first one that must reconcile FIVE separate per-segment lists into one non-optional `Segment` object. A segment that's missing a required field (no matching `complexity_scores`/`audio_assets`/`intervention_prompts` entry, or zero matched `slides`) cannot become a valid `Segment` — but that's still just ONE segment's worth of data, not a reason to fail the whole lesson. Skip it, log why, keep going — exactly the same shape of decision Story 2-8/2-9's per-slide `try/except` already established, just applied at the per-segment assembly level instead of per-provider-call level.

### `teachback_prompt` — provisional placeholder, not a finalized design (read before assuming this is done)

No node anywhere in the 15-node pipeline (confirmed against `docs/bmad/epics/epic-1-content-pipeline.md`'s own node table) generates a teach-back prompt — `Segment.teachback_prompt: str` is a REQUIRED field on the frozen schema with no producing node. This story fills it with a deterministic, zero-cost template (see AC-8) SPECIFICALLY so `package_builder` can be built and the pipeline can produce complete lessons now — but this is explicitly flagged as provisional pending confirmation from whoever owns the teach-back feature (Dev 3 per `CLAUDE.md`'s team ownership table: "Dev 3 owns Quiz API, teachback scorer, CES formula, Learner DNA"). Do not present this as a finished design decision in the Dev Agent Record — present it as an open item, matching how `docs/dev1-tracker.md` already tracks other cross-team-blocked items (S2-LM1..LM5) as PARTIAL rather than done.

### Top-level `glossary` dedup — new logic, no existing precedent to copy verbatim

Unlike `quiz_generator_node`'s duplicate-OPTION detection within a single question (a precedent for the *normalization style* — `.strip().lower()` — not the *aggregation* itself), no existing node deduplicates across the WHOLE lesson. Build this fresh: iterate all segments' `jargon` entries in segment order, keep a `seen: set[str]` of normalized terms, append to the top-level `glossary` only on first occurrence.

### Branch

Single shared branch for all of Sprint 2: `sprint2/phase-b-generation-nodes` — do not create a new branch. Story-first gate still applies.

### Testing standards

pytest, matching sibling stories' conventions. New test file: `apps/api/tests/unit/test_package_builder_node.py`.

### Project Structure Notes

`apps/api/app/schemas/lesson.py` modified (Task 1 — frozen contract relaxation, flagged for 4-dev sign-off), `packages/shared/lesson_package.schema.json` modified (Task 1, same flag), `package_builder_node` real implementation in `graph.py`, one new test file. `packages/shared/types/lesson.ts` explicitly NOT modified (already correct).

### References

- [Source: docs/dev1-tracker.md — Sprint 2 section, S2-11, S2-12 (WebSocket push, explicitly out of scope here), S2-LM1..LM5 (tier, explicitly out of scope here)]
- [Source: docs/bmad/epics/epic-1-content-pipeline.md — Node 15 spec; confirms no teach-back-prompt-producing node exists anywhere in the 15-node table]
- [Source: apps/api/app/schemas/lesson.py — `LessonPackage`/`Segment`/`Slide`/`Narration`/etc. frozen contract]
- [Source: packages/shared/lesson_package.schema.json, packages/shared/types/lesson.ts — sibling frozen-contract files]
- [Source: apps/api/app/modules/content/pipeline/graph.py — `chunk_node`/`embed_node`'s `chapter_id` checkpoint pattern; every Phase 1/2/3 node's exact output shape this story correlates against]
- [Source: supabase/migrations/20260611000000_initial_schema.sql — `lessons`/`lesson_jobs`/`chapters` table columns]
- [Source: CLAUDE.md — team ownership table (Dev 3 owns teach-back); PRD §16 frozen-contract sign-off requirement]

## Dev Agent Record

### Agent Model Used

_To be filled by bmad-dev-story._

### Debug Log References

_To be filled by bmad-dev-story._

### Completion Notes List

_To be filled by bmad-dev-story._

### File List

_To be filled by bmad-dev-story._

## Change Log

| Date | Change |
|------|--------|
| 2026-07-16 | Story created via `bmad-create-story`. |
