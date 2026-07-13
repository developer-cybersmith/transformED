---
baseline_commit: 7f7c0bcab564d9505281aa6305cc30b7ad8d7d5c
---

# Story 2.2: Learner Mode Infra (tier contract, migration, endpoint)

Status: ready-for-dev

## Story

As a **developer building the tier-aware pipeline (S2-LM4/S2-LM5)**,
I want the lesson content-depth **tier** to be a validated, first-class field on the frozen lesson contract, the `lessons` table, and `POST /lessons`,
so that `lesson_planner`/`slide_generator` can read `state["tier"]` with no additional plumbing, and the 4-developer contract review that gates this isn't blocking the actual tier-aware generation logic later.

This story is **infra only** — it does not implement tier-driven slide counts or content depth (that is S2-LM4/S2-LM5, a separate story amending S2-7/S2-8). It corresponds to tracker tasks **S2-LM1, S2-LM2, S2-LM3** in `docs/dev1-tracker.md`, inserted between Sprint 2's Phase 1 and Phase 2 sections, and to the Learner Mode amendment made today (2026-07-13) to `docs/bmad/epics/epic-1-content-pipeline.md`.

## Acceptance Criteria

1. **Frozen contract** — `tier: "T1" | "T2" | "T3"` added to `LessonMetadata` in all three mirrors: `packages/shared/lesson_package.schema.json`, `packages/shared/types/lesson.ts`, `apps/api/app/schemas/lesson.py`. All three agree byte-for-byte on the enum values. **Requires 4-developer PR review per `CLAUDE.md` §16 before merge** — do not let Tasks 3/4 get ahead of this sign-off.
2. **Migration** — new file under `supabase/migrations/` (timestamp after the latest applied migration, `20260710000000_storage_buckets.sql` — do not reuse or edit any existing migration file) adding `lessons.tier text NOT NULL DEFAULT 'T2' CHECK (tier IN ('T1','T2','T3'))`. Existing rows backfill to `T2` with no manual data migration step.
3. **`POST /lessons`** accepts an optional `tier` multipart field. Omitted → defaults `"T2"` (existing upload flow and frontend mocks keep working unchanged). Invalid value (not `T1`/`T2`/`T3`) → `422`, not a silent fallback. Valid tier is written to the `lessons` row at insert time.
4. **Pipeline plumbing** — `content_pipeline_job`'s existing lesson-row lookup is extended to also select `tier`; `run_pipeline()` gains a `tier: str = "T2"` parameter; `PipelineState` TypedDict gains a `tier: str` field; the initial state built by `run_pipeline()` includes it. No ARQ job-payload change is needed (see Dev Notes — this corrects the tracker's original S2-LM3 wording).
5. All existing tests continue to pass unmodified — every change here is additive with a `T2` default, so no existing fixture, schema-validation test, or upload-flow test should need updating to a specific tier value.

## Tasks / Subtasks

- [ ] Task 1: Add `tier` to the frozen lesson contract (AC: 1)
  - [ ] 1.1 `packages/shared/lesson_package.schema.json`: add `"tier"` to both `required` and `properties` under `definitions.LessonMetadata` (enum `["T1","T2","T3"]`) — this object has `additionalProperties: false`, so it must be added to both places or Pydantic serialization will be actively rejected by schema validation
  - [ ] 1.2 `packages/shared/types/lesson.ts`: add `export type LessonTier = 'T1' | 'T2' | 'T3';` near the existing `AudioProvider`/`QuizType` type aliases, add `tier: LessonTier;` to the `LessonMetadata` interface
  - [ ] 1.3 `apps/api/app/schemas/lesson.py`: add `LessonTier = Literal["T1", "T2", "T3"]` next to the existing `_STRICT`-adjacent type aliases, add `tier: LessonTier` to `LessonMetadata`
  - [ ] 1.4 Flag the PR for 4-developer review per the Interface Contracts table in `CLAUDE.md` §16 — do not merge on a 1-developer approval

- [ ] Task 2: `lessons.tier` migration (AC: 2)
  - [ ] 2.1 Create `supabase/migrations/{new-timestamp}_add_lesson_tier.sql` — assign a real timestamp after `20260710000000`, do not backdate
  - [ ] 2.2 `ALTER TABLE public.lessons ADD COLUMN tier text NOT NULL DEFAULT 'T2' CHECK (tier IN ('T1','T2','T3'));`
  - [ ] 2.3 Confirm none of the 7 already-applied migrations are touched

- [ ] Task 3: Accept `tier` on `POST /lessons` (AC: 3)
  - [ ] 3.1 `apps/api/app/modules/content/router.py`: add `Form` to the `fastapi` import (currently `File, HTTPException, Query, Request, Response, UploadFile, status` — no `Form` yet)
  - [ ] 3.2 Add `tier: str | None = Form(default=None)` parameter to `upload_lesson()`; validate against `{"T1","T2","T3"}` — raise `HTTPException(422, ...)` if provided and invalid; resolve to `"T2"` if omitted
  - [ ] 3.3 Include the resolved tier in the `lessons` table insert (currently `{"user_id": user_id, "book_id": book_id, "status": "generating"}` at router.py — add `"tier": tier`)
  - [ ] 3.4 Do not add `tier` to `LessonUploadResponse` — that response shape is frozen and this AC doesn't require echoing it back

- [ ] Task 4: Thread `tier` through the pipeline (AC: 4)
  - [ ] 4.1 `apps/api/app/workers/jobs/content_pipeline.py`: extend the existing lessons SELECT (`"user_id, source_file_path, book_id"`) to also select `tier`; extract `tier: str = lesson_row.get("tier", "T2")`
  - [ ] 4.2 Pass `tier=tier` into the existing `run_pipeline(...)` call
  - [ ] 4.3 `apps/api/app/modules/content/pipeline/graph.py`: add `tier: str = "T2"` parameter to `run_pipeline()`; add `"tier": tier` to the `initial_state` dict it builds
  - [ ] 4.4 Add `tier: str` to the `PipelineState` TypedDict's input section (alongside `lesson_id`, `user_id`, `book_id`, `source_pdf_path`, `chapter_content`)

- [ ] Task 5: Tests (AC: all)
  - [ ] 5.1 Schema round-trip: `LessonMetadata`/`LessonPackage` validates for each of `T1`/`T2`/`T3`; once `tier` is required, a fixture missing it fails validation (update any fixture that doesn't already default-carry a tier)
  - [ ] 5.2 Migration: CHECK constraint rejects a value outside `T1/T2/T3`; a pre-migration row backfills to `T2` with no manual step
  - [ ] 5.3 Router: omitted `tier` → row persisted with `T2`; invalid string → `422`; valid `T1`/`T3` → persisted verbatim
  - [ ] 5.4 Pipeline: `run_pipeline()`/`content_pipeline_job` — `PipelineState["tier"]` is populated correctly from the `lessons` row for a lesson created with a non-default tier

## Dev Notes

### This corrects the tracker's own wording on how tier reaches the pipeline

`docs/dev1-tracker.md`'s S2-LM3 task says "pass into ARQ job" — but the actual established pattern (verified by reading `content_pipeline_job`) does **not** pass extra positional args through `arq_redis.enqueue_job(...)`. `router.py`'s `upload_lesson()` calls `arq_redis.enqueue_job("content_pipeline_job", lesson_id, _job_id=f"pipeline:{lesson_id}")` — only `lesson_id`. `content_pipeline_job(ctx, lesson_id)` then re-fetches `user_id, source_file_path, book_id` from the `lessons` table by `lesson_id` in a single `SELECT`. Tier must be added to that **same** `SELECT`, not threaded as a new ARQ argument — doing the latter would diverge from how every other per-lesson field already reaches the job. `[Source: apps/api/app/workers/jobs/content_pipeline.py#L60-70, apps/api/app/modules/content/router.py#L174-178]`

### `run_pipeline()` builds `PipelineState` directly from kwargs — tier follows the same pattern

```python
async def run_pipeline(
    lesson_id: str,
    chapter_content: str = "",
    user_id: str = "",
    source_pdf_path: str = "",
    book_id: str = "",
) -> dict[str, Any]:
    ...
    initial_state: PipelineState = {
        "lesson_id": lesson_id,
        "user_id": user_id,
        "book_id": book_id,
        "chapter_content": chapter_content,
        "source_pdf_path": source_pdf_path,
        "progress_pct": 0.0,
        "error": None,
    }
```
Add `tier: str = "T2"` as a new kwarg with the same default-preserving pattern as the existing four, and add `"tier": tier` to `initial_state`. Existing test callers that invoke `run_pipeline()` without a `tier` argument keep working unchanged. `[Source: apps/api/app/modules/content/pipeline/graph.py#L1055-1089]`

### `PipelineState`'s input section is a flat `TypedDict(total=False)`

The relevant block (top of `graph.py`) already lists `lesson_id`, `user_id`, `book_id`, `source_pdf_path`, `chapter_content` under an `# Input` comment — add `tier: str` there, not near the Node 5+ output fields further down. `[Source: apps/api/app/modules/content/pipeline/graph.py#L44-52]`

### The JSON schema's `additionalProperties: false` is a trap for this exact change

`LessonMetadata` in `lesson_package.schema.json` has `"additionalProperties": false` (line 61) with its own `"required"` array (lines 54-59). Adding `tier` only to `properties` and not to `required` will validate fine for existing fixtures but silently allow a `LessonPackage` with no tier once one starts appearing elsewhere — add it to both. `[Source: packages/shared/lesson_package.schema.json#L52-69]`

### `router.py` has no `Form` import yet

Current import line: `from fastapi import APIRouter, File, HTTPException, Query, Request, Response, UploadFile, status` — `Form` must be added. The existing `upload_lesson()` signature takes only `file: UploadFile = File(...)` as a body param; `tier` is a sibling multipart field, not JSON body (this endpoint is `multipart/form-data` for the file, so `tier` must also come in via `Form(...)`, not a JSON body field). `[Source: apps/api/app/modules/content/router.py#L15, #L84-90]`

### Insert order and where tier actually gets written

`upload_lesson()`'s DB writes go `books` → `lessons` → storage upload → `lessons.source_file_path` update → `lesson_jobs` → ARQ enqueue (lines 137-178). Tier belongs on the **initial** `lessons` insert (line ~146-150, currently `{"user_id": user_id, "book_id": book_id, "status": "generating"}`), not a later update — there's no reason to defer it the way `source_file_path` is deferred (that one is deferred only because the storage path isn't known until after the storage upload; tier is known immediately from the request). `[Source: apps/api/app/modules/content/router.py#L136-153]`

### Scope boundary — do not build S2-LM4/LM5 here

This story only makes `tier` readable as `state["tier"]` inside `lesson_planner`/`slide_generator`. It does **not** implement tier-aware slide-count ranges (T1 20–25 / T2 12–15 / T3 6–8) or the T3 content-depth prompt variant — those are S2-LM4 and S2-LM5, a separate story that amends S2-7/S2-8 directly. Implementing any tier-conditioned generation logic in this story is scope creep; keep this story to contract + migration + endpoint + plumbing only.

### Branch

Single shared branch for all of Sprint 2: `sprint2/phase-b-generation-nodes` (explicit user directive, 2026-07-13) — do not create a new branch for this story. Story-first gate still applies: this file is committed alone and pushed before any implementation commit.

### Testing standards

pytest, matching the existing `apps/api/tests/unit/` conventions (e.g. `test_lesson_schema.py` for Pydantic/JSON-schema round-trips, `test_queue_symmetry.py`-style constant/contract assertions for the router/pipeline plumbing). No new test framework or pattern needed.

### Project Structure Notes

No new modules — this story only edits existing files (`lesson_package.schema.json`, `lesson.ts`, `schemas/lesson.py`, `router.py`, `content_pipeline.py`, `graph.py`) plus one new migration file. No variance from the established structure.

### References

- [Source: docs/dev1-tracker.md — Sprint 2 section, S2-LM1/S2-LM2/S2-LM3]
- [Source: docs/bmad/epics/epic-1-content-pipeline.md — Learner Mode amendment, 2026-07-13]
- [Source: apps/api/app/modules/content/router.py#L1-238]
- [Source: apps/api/app/workers/jobs/content_pipeline.py#L1-90]
- [Source: apps/api/app/modules/content/pipeline/graph.py#L44-52, #L1055-1099]
- [Source: apps/api/app/schemas/lesson.py#L33-53]
- [Source: packages/shared/lesson_package.schema.json#L52-69]
- [Source: packages/shared/types/lesson.ts#L1-18]
- [Source: supabase/migrations/ directory listing — latest applied `20260710000000_storage_buckets.sql`]

## Dev Agent Record

### Agent Model Used

claude-sonnet-5

### Debug Log References

### Completion Notes List

### File List
