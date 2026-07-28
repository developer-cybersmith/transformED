---
baseline_commit: ef855ea26ec86092cc297ffe326a3b11c816d9b3
---

# Story 2.11: `package_builder` Node — Final Assembly, Validation, DB Write (S2-11)

Status: done

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

- [x] Task 1: Relax the frozen `Slide.image_url`/`fallback_image_url` contract (AC: 1)
  - [x] 1.1 `apps/api/app/schemas/lesson.py`: changed both fields from `AnyHttpUrl | None` to `str | None`; removed the now-unused `AnyHttpUrl` import (confirmed via grep — no other use in the file).
  - [x] 1.2 `packages/shared/lesson_package.schema.json`: removed `"format": "uri"` from both `Slide.image_url`/`fallback_image_url`, kept `oneOf [{"type": "string"}, {"type": "null"}]` (matches file's existing style).
  - [x] 1.3 Confirmed `packages/shared/types/lesson.ts` needs no change (already `string | null` for both fields) — not edited.
  - [x] 1.4 Ran `test_lesson_schema.py` + `test_slide_generator_node.py`: 46/46 passed, confirming no test asserted URL-format validation.

- [x] Task 2: Replace the `package_builder_node` stub body — assembly (AC: 2, 3, 4, 5, 6, 7, 8)
  - [x] 2.1 Idempotency checkpoint read added (Phase-A style), returning cached `lesson_package` on a `"package_builder"` cache hit — no re-writes of any kind on cache hit.
  - [x] 2.2 `chapter_id` resolved from `node_outputs["chunk"]["chapter_id"]`, mirroring `embed_node`'s exact read pattern.
  - [x] 2.3 `LessonMetadata` fields mapped from `state["lesson_plan"]` per AC-3 (`tier` left at Pydantic default).
  - [x] 2.4 Per-segment assembly loop over `lesson_plan["segments"]`, correlating `complexity_scores`/`slides`+`slide_images`/`audio_assets`/`quiz_questions`/`glossary`/`intervention_prompts` by `segment_id` (`slide_images` by `slide_id` only, confirmed via a dedicated regression test).
  - [x] 2.5 Degrade-and-skip logic for segments missing `complexity`/`narration`/`interventions`/any `slides`, with a clear warning log listing exactly which field(s) were missing; `RuntimeError` if the resulting segment list is empty.
  - [x] 2.6 Top-level deduplicated `glossary` aggregation (`.strip().lower()` normalization, first occurrence's casing kept) — confirmed via a test with a same-term-different-case entry across two segments.
  - [x] 2.7 `teachback_prompt` placeholder implemented with an inline comment explicitly marking it PROVISIONAL, pending confirmation from whoever owns the teach-back feature.

- [x] Task 3: Validation + DB writes (AC: 9, 10, 11)
  - [x] 3.1 `LessonPackage.model_validate(assembled)` called, uncaught — confirmed via a regression test (missing `chapter_id` → UUID validation error propagates).
  - [x] 3.2 `lessons` table updated: `content`, `status="ready"`, `title`.
  - [x] 3.3 `lesson_jobs` table updated: `status="completed"`, `completed_at` (current UTC ISO-8601) — this is the first explicit completion write; the pre-existing `_update_job_progress()` helper only ever sets `status="running"` and was never capable of this (the stub's final `_update_job_progress(lesson_id, 100.0, "complete")` call — which would have wrongly reset status back to "running" — was removed, not just left in place).
  - [x] 3.4 Idempotency checkpoint written on success (`node_outputs["package_builder"] = lesson_package`), merged with the existing `node_outputs` dict (preserves `chunk`'s `chapter_id` entry and every other prior node's checkpoint).
  - [x] 3.5 Returns `{**state, "lesson_package": lesson_package, "progress_pct": 100.0}` (matches the stub's existing return shape).

- [x] Task 4: Tests (AC: all) — `test_package_builder_node.py`, 11 tests
  - [x] 4.1 Happy path (all 7 upstream outputs present, 2 segments) produces a `LessonPackage.model_validate()`-passing dict; `lessons`/`lesson_jobs` tables updated correctly; checkpoint written.
  - [x] 4.2 Three separate tests: segment missing `complexity`/`narration`/`interventions` each individually skipped (one test per field), plus a segment with zero matched `slides` skipped — others still assembled in each case.
  - [x] 4.3 ALL segments missing required data → `RuntimeError` raised, matched on message; `lessons` table never written; `lesson_jobs`'s only call is the pre-raise 95%-progress marker (`status="running"`), never a `status="completed"` write.
  - [x] 4.4 Dedicated test: `slide_images` correlation is by `slide_id`, not `segment_id` — one slide gets its real path, the other (whose image generation returned `None`) stays `None`.
  - [x] 4.5 Top-level `glossary` dedup test: `"Entropy"` (sec_0) and `"entropy "` (sec_1, differing case/whitespace) collapse to one entry, `"Entropy"`'s original casing preserved; a distinct term (`"Conduction"`) still appears separately.
  - [x] 4.6 Idempotency cache-hit: cached dict returned verbatim, zero `lessons`/`lesson_jobs` update calls of any kind.
  - [x] 4.7 `LessonPackage.model_validate()` failure (missing `chapter_id` checkpoint → invalid UUID) propagates as an uncaught exception; `lessons` table never written.
  - [x] 4.8 Dedicated test asserting `supabase.storage.from_` is never called by this node.
  - [x] 4.9 Full regression suite: 375/376 passed (1 pre-existing unrelated skip), 0 regressions.

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

claude-sonnet-5

### Debug Log References

- Red-green-refactor: `test_package_builder_node.py` (11 tests) written first against the pre-existing flat-dict stub — confirmed 10/11 failures (the 11th, no-Storage-calls, trivially passed against the stub too since the stub never touched Storage either). Implemented the real body; one test (`test_all_segments_missing_data_raises_runtime_error_and_writes_nothing`) needed its own assertion corrected — it originally asserted `jobs_table.update.assert_not_called()`, which was too strict: the 95%-progress marker (`status="running"`) legitimately fires before the `RuntimeError` raises, and only the *completion* write (`status="completed"`) plus the `lessons` table write must never happen. Fixed the assertion to check the specific `status` value per call rather than "never called at all." 11/11 green after.
- Task 1 (frozen contract relaxation) run and verified in isolation first (46/46 on `test_lesson_schema.py` + `test_slide_generator_node.py`) before starting Task 2/3's implementation, confirming the type change was safe before building on top of it.
- Full suite run after all tasks: 375/376 passed (1 pre-existing unrelated skip), 0 regressions.

### Completion Notes List

- All 4 tasks / 25 subtasks complete. Frozen `Slide.image_url`/`fallback_image_url` relaxed from `AnyHttpUrl` to `str` in both `app/schemas/lesson.py` and `packages/shared/lesson_package.schema.json` (flagged for 4-dev sign-off per PRD §16, mirroring Story 2-2/S2-LM1's precedent — NOT blocking, same as that precedent). `packages/shared/types/lesson.ts` needed no change (already `string | null`).
- `package_builder_node` now assembles a real `LessonPackage`: `chapter_id` resolved from `chunk_node`'s existing checkpoint (no new `PipelineState` field added), `LessonMetadata` mapped from `lesson_plan`, and each `Segment` correlated by `segment_id` across `complexity_scores`/`slides`/`audio_assets`/`quiz_questions`/`glossary`/`intervention_prompts` — with `slide_images` correlated separately by `slide_id` (its own deliberately flat shape from Story 2-9). A segment missing any of `complexity`/`narration`/`interventions`/`slides` is skipped with a warning (never crashes the whole node); if every segment gets skipped, the node raises — matching the "one bad item degrades, but a structural minimum must still be met" precedent from `image_generator_node`/`tts_node`, applied at the per-segment level for the first time.
- Top-level `glossary` is now a genuinely NEW piece of logic (no prior node aggregates across the whole lesson) — deduplicates jargon terms by `.strip().lower()`, first occurrence's casing kept.
- `teachback_prompt` is filled by an explicitly-marked-provisional deterministic template (no LLM call) — flagged in code comments and this story as an OPEN item pending confirmation from whoever owns the teach-back feature (Dev 3 per CLAUDE.md's team ownership table), not a finalized design decision. This mirrors how `docs/dev1-tracker.md` already tracks other cross-team-blocked items (S2-LM1..LM5) as provisional rather than fully resolved.
- `lessons.content`/`status`/`title` and `lesson_jobs.status`/`completed_at` are now written by this node — the FIRST node in the whole pipeline to write to the `lessons` table at all (every prior node only touched `lesson_jobs`). The stub's previous final call, `_update_job_progress(lesson_id, 100.0, "complete")`, was a latent bug (it only ever sets `status="running"`, meaning the old stub would have reset a completed job's status back to "running") — removed entirely, replaced with an explicit, correct completion write.
- Explicitly NOT built, per the story's scope boundaries: any WebSocket `lesson_ready` push (S2-12, Dev 4's story) and any Supabase Storage/signed-URL call (image/audio paths are copied through as bare storage paths, matching the Task 1 contract relaxation's rationale). A dedicated test (`test_no_storage_or_websocket_calls_made`) guards against scope creep back into either.
- **Patch round (2026-07-16):** a 3-layer adversarial review (Blind Hunter, Edge Case Hunter, Acceptance Auditor) found 1 HIGH (Blind Hunter — non-atomic two-table write, deferred), 2 MEDIUM findings converging on the SAME root cause from two independent reviewers (direct `entry["key"]` subscripting instead of `.get()` could crash the whole node on a malformed upstream entry — the exact opposite of AC-5's own guarantee), plus 4 additional MEDIUM/LOW coverage gaps from Edge Case Hunter, and a false-positive CRITICAL from Acceptance Auditor (flagging the implementation as "uncommitted" — expected mid-review-cycle state per this session's own commit-after-review workflow, not a real defect). All patchable findings fixed; the two deferred findings are documented below with their rationale.

### File List

- `apps/api/app/schemas/lesson.py` (modified — `Slide.image_url`/`fallback_image_url` relaxed to `str | None`, unused `AnyHttpUrl` import removed)
- `packages/shared/lesson_package.schema.json` (modified — matching `"format": "uri"` constraint removed)
- `apps/api/app/modules/content/pipeline/graph.py` (modified — `package_builder_node` real implementation + patch round; `datetime`/`timezone` import added)
- `apps/api/tests/unit/test_package_builder_node.py` (new, then patched — 17 tests after patch round)

## Change Log

| Date | Change |
|------|--------|
| 2026-07-16 | Story created via `bmad-create-story`. |
| 2026-07-16 | Implemented via `bmad-dev-story`: relaxed the frozen `Slide.image_url`/`fallback_image_url` contract (flagged for 4-dev sign-off), replaced the `package_builder_node` stub with real assembly/validation/DB-write logic, added 11 new tests. 375/376 total tests passing (1 pre-existing unrelated skip), 0 regressions. teachback_prompt filled with an explicitly-provisional placeholder pending Dev 3 confirmation. No WebSocket push or Storage calls (explicitly out of scope — S2-12 and a future view-time URL-resolution component, respectively). Status → review. |
| 2026-07-16 | Code review patch round: replaced direct `entry["key"]` subscripting with defensive `.get()`-based lookups across every correlation/grouping step (a malformed upstream entry now logs and is skipped instead of crashing the whole node — HIGH-confidence finding, confirmed independently by 2 reviewers); added a warning log for duplicate `segment_id` overwrites and for orphaned upstream data not present in `lesson_plan["segments"]`; added 6 new tests covering these fixes plus 3 pre-existing coverage gaps (zero quiz/jargon segment, chunk-present-without-chapter_id, missing book_id, slide entirely absent from slide_images). Deferred the non-atomic two-table write (real, but the current write ordering is already the safer of the two possible orderings per Blind Hunter's own analysis, and a proper fix means an atomic RPC — matches this pipeline's existing deferred-pattern precedent) and the relaxed-`str`-type residual risk (inherent to the project-level decision already made for this story, responsibility pushed to a future view-time URL-resolution component). 381/382 tests passing (1 pre-existing unrelated skip), 0 regressions. Status → done. |

### Review Findings (2026-07-16 — 3-layer adversarial review: Blind Hunter, Edge Case Hunter, Acceptance Auditor)

- [x] [Review][Patch] **FIXED 2026-07-16 — MEDIUM — Direct `entry["key"]` subscripting across every correlation/grouping step could raise an uncaught `KeyError` on a malformed upstream entry, crashing the whole node — the exact opposite of AC-5's "one bad item never crashes the whole node" guarantee.** Confirmed independently by two reviewers (Blind Hunter + Edge Case Hunter), covering `complexity_by_id`/`audio_by_id`/`interventions_by_id` construction, the `slides`/`quiz_questions`/`glossary` grouping loops, `slide_images`' `slide_id` lookup, and `lesson_plan["segments"]`'s own `segment_id`/`title`/`summary` fields. Fixed by introducing two small defensive helpers (`_index_by_segment_id`, `_group_by_segment_id`) that use `.get("segment_id")` and log-and-skip a malformed entry rather than raising, plus `.get()` with sensible fallbacks everywhere else a dict key was previously subscripted directly. [`graph.py::package_builder_node`] (Blind Hunter + Edge Case Hunter, independently)
- [x] [Review][Patch] **FIXED 2026-07-16 — MEDIUM — A duplicate `segment_id` across `complexity_scores`/`audio_assets`/`intervention_prompts` (e.g. a retried Send() dispatch) was silently resolved "last one wins" with zero log trace.** `_index_by_segment_id()` now logs a warning naming the duplicate `segment_id` and the source list before overwriting. Verified by a new test asserting both the last-one-wins behavior AND the warning log. [`graph.py::package_builder_node`] (Edge Case Hunter)
- [x] [Review][Patch] **FIXED 2026-07-16 — MEDIUM — Segment data present in an upstream list but absent from `lesson_plan["segments"]` (upstream drift) was silently discarded with zero diagnostics.** Added an explicit orphaned-id computation (union of all per-segment maps' keys, minus the plan's own segment_id set) with a warning log listing exactly which `segment_id`(s) were ignored — the plan remains authoritative (AC-4 unchanged), this only makes the drop visible. Verified by a new test. [`graph.py::package_builder_node`] (Edge Case Hunter)
- [x] [Review][Patch] **FIXED 2026-07-16 — MEDIUM (test coverage gap) — No test proved a segment with zero `quiz`/`jargon` entries still survives, despite AC-5 explicitly requiring it.** Added `test_segment_with_zero_quiz_and_jargon_still_included`. [`tests/unit/test_package_builder_node.py`] (Edge Case Hunter)
- [x] [Review][Patch] **FIXED 2026-07-16 — LOW (test coverage gaps) — Three untested `.get()`-fallback branches: `chunk` present but missing its `chapter_id` key, a missing `book_id`, and a `slide_id` entirely absent from `slide_images` (as opposed to present with an explicit `None`).** Added `test_chunk_present_but_missing_chapter_id_key_behaves_like_chunk_absent`, `test_missing_book_id_fails_model_validate`, `test_slide_entirely_absent_from_slide_images_degrades_same_as_explicit_none`. [`tests/unit/test_package_builder_node.py`] (Edge Case Hunter)
- [ ] [Review][Defer] **HIGH — The `lessons` table write and the `lesson_jobs` completion write are two separate, non-atomic REST calls; a crash between them leaves `lessons.status="ready"` (with full content) while `lesson_jobs` is still `status="running"` with no checkpoint.** Confirmed self-healing: a retry correctly cache-misses (since the checkpoint was never written) and safely re-runs/re-writes the whole node. Blind Hunter's own analysis confirms the CURRENT ordering (public data first, checkpoint second) is the SAFER of the two possible orderings — reversing it would risk a false cache-hit that never actually writes `lessons` at all. The residual risk is narrower than "data corruption": a future S2-12 WebSocket push keyed off `lesson_jobs.status` could miss the ready signal during the crash window. Deferred rather than fixed now — a proper fix means wrapping both writes in one atomic Postgres RPC, a bigger structural change matching this pipeline's existing deferred-pattern precedent (the `.single()`-unguarded-read gap deferred identically across Stories 2-6/2-7/2-8/2-9). Flag for whoever builds S2-12 to revisit before relying on `lesson_jobs.status` as the sole "is it really ready" signal. [`graph.py::package_builder_node`] (Blind Hunter) — deferred, real but self-healing, matches existing accepted pattern.
- [ ] [Review][Defer] **LOW-MEDIUM — Relaxing `Slide.image_url`/`fallback_image_url` from `AnyHttpUrl` to plain `str` removes schema-level protection against a malformed or malicious path (e.g. `javascript:`, an absolute external URL, `../` traversal).** No live exploit path today (`image_generator_node` only ever writes a fixed `{lesson_id}/{slide_id}.png` template), but `LessonPackage.model_validate()` will now silently accept any string here. This is inherent to the project-level decision already made for this story (store the bare path, resolve to a real URL at view time — see Story scope note) rather than a defect introduced by the implementation; the residual risk is explicitly the responsibility of whichever future component resolves these paths to signed URLs, which MUST allow-list/validate the path shape before rendering it as a URL. Deferred as a requirement for that future component, not fixed here. [`app/schemas/lesson.py`] (Blind Hunter) — deferred, inherent to the deliberate design decision, not a regression.
- [x] [Review][Dismiss] **CRITICAL (false positive) — Acceptance Auditor flagged the implementation as "uncommitted" as if it were a process violation.** This is expected mid-review-cycle state: this session's established workflow runs the adversarial review BEFORE asking the user whether to commit, specifically so patches land in the same commit as the initial implementation rather than requiring a separate fix-up commit. Not a defect — dismissed. (Acceptance Auditor) — dismissed, reviewer lacked context on the session's commit-after-review workflow.
