---
baseline_commit: 70a73264983607db3bb5a79b7957e21501d77c17
---

# Story 1.6: `GET /api/content/lessons/{id}` returns real `content` (Sprint 1 gap-fix)

Status: ready-for-dev

## Story

As the content pipeline (Dev 1) and Dev 2 (frontend, waiting to migrate off mocks),
I want `GET /api/content/lessons/{lesson_id}` to actually return the generated `content` (with signed media URLs) once a lesson is ready,
so that the endpoint fulfills the frozen contract it's had since Sprint 1, and Dev 2 has a real endpoint to point the player at instead of `apps/web/src/mocks/`.

**Source:** discovered 2026-07-23 while building Story 3-6 (media signed-URL layer). `docs/dev1-tracker.md`'s frozen endpoint table tags this endpoint **S1** and says *"Returns `LessonRecord` (status + content when ready)"*; the **frozen** `packages/shared/types/lesson.ts:104` `LessonRecord` type has had `content: LessonPackage | null` since Week 1; there's even a fully-defined, tested, but **completely unused** Python mirror `LessonRecord` (`apps/api/app/schemas/lesson.py:225-238`). The actual `get_lesson` endpoint has silently never returned `content` — a Sprint 1 gap that's stood the whole project, not new Sprint 3+ scope.

## Acceptance Criteria

1. **AC-1 — `content` attached when ready.** `LessonStatusResponse` (used by `GET /lessons/{id}`) gains `content: LessonPackage | None = None`. When `lesson.status == "ready"` and `lesson.content` (the JSONB column) is non-null, the response's `content` is populated; for `"generating"`/`"failed"` (or a null `content` column), `content` stays `None` — unchanged from today.
2. **AC-2 — media URLs are signed, not bare paths.** Every `Narration.audio_url` and `Slide.image_url` inside the returned `content` is a real signed URL (via the shared `sign_storage_path()` helper — see AC-4), never the bare `{lesson_id}/{file}` storage path `package_builder_node` actually stores. `Slide.fallback_image_url` passes through unchanged (it is always `None` in the current pipeline — no producer ever sets it, confirmed in `graph.py:1657`).
3. **AC-3 — degrade-not-drop on a per-asset signing failure.** If signing one specific asset fails, only that asset degrades to its established "no media" fallback value (`""` for `audio_url` — it's a required non-optional `str`; `None` for `image_url` — optional) — the rest of the lesson (all other segments/slides, and the response itself) is unaffected. Matches the pipeline's existing degrade-not-drop convention (`tts_node`'s `audio_url: ""` fallback, `image_generator_node`'s `image_url: None` fallback).
4. **AC-4 — DRY signing helper, zero behavior change to Story 3-6's endpoint.** Extract the "call `create_signed_url`, pull the `signedURL` key, catch any exception → `None`" logic (currently inline in `media/router.py:get_signed_url`, Story 3-6) into a new `apps/api/app/core/storage.py::sign_storage_path(supabase, bucket, path, expires_in=3600) -> str | None`. Refactor `media/router.py` to call it — a pure refactor; its existing 10 tests (`test_media_router.py`) must pass unmodified, asserting identical behavior (ownership check untouched, still 404s the same way).
5. **AC-5 — no redundant ownership re-check.** `get_lesson` already verifies `lesson.user_id == current_user["sub"]` once, before this new logic runs. Per-asset signing calls `sign_storage_path()` directly — they do NOT re-invoke the media router's endpoint or its ownership check (that would be a pointless N+1 re-verification of ownership already established for the whole lesson).
6. **AC-6 — trusted internal data, no silent corruption-swallowing.** After resolving URLs in the raw content dict, it's validated via `LessonPackage.model_validate(...)` before being attached to the response. This is our own `package_builder`-written data — a validation failure here indicates real corruption and should raise/500, not be silently caught.
7. **AC-7 — `list_lessons` never attaches `content`.** The shared `LessonStatusResponse` model gains the new field, but `list_lessons` (`GET /lessons`, paginated, up to 200 rows) must never populate it — resolving signed URLs for every asset of every lesson in a list response would be an N-lessons × M-assets signing storm. Only the single-lesson `get_lesson` path resolves and attaches `content`.
8. **AC-8 — tests, no live network.** New tests in `apps/api/tests/unit/test_content_router.py`: (a) ready lesson with content → response embeds signed URLs, asserting `create_signed_url` was called with the correct `(bucket, path)` pairs; (b) one asset's signing failing degrades only that asset (`""`/`None`), not the whole response; (c) `"generating"`/`"failed"` status still returns `content=None` (regression); (d) `list_lessons` never attaches `content` even for a ready lesson (regression). `test_media_router.py`'s 10 existing tests stay green, unmodified in behavior, after the DRY refactor.

## Tasks / Subtasks

- [ ] Task 1 (AC: 4): `apps/api/app/core/storage.py` — new module, `sign_storage_path(supabase, bucket, path, expires_in=3600) -> str | None`.
- [ ] Task 2 (AC: 4): Refactor `media/router.py:get_signed_url` to call `sign_storage_path()` instead of its inline try/except — zero behavior change, existing 10 tests pass unmodified.
- [ ] Task 3 (AC: 1, 2, 3, 5, 6): `content/router.py` — add `content` field to `LessonStatusResponse`; add a `_resolve_lesson_content(content: dict, supabase) -> LessonPackage` helper; wire it into `get_lesson` only, gated on `status == "ready"` and non-null `content`.
- [ ] Task 4 (AC: 7): Confirm `list_lessons` is untouched (it calls the same `_row_to_status_response` — verify that helper does NOT call `_resolve_lesson_content`; only `get_lesson` does, as an explicit extra step after the shared helper).
- [ ] Task 5 (AC: 8): New tests in `test_content_router.py`; re-run `test_media_router.py` to confirm zero regressions from the DRY refactor.
- [ ] Task 6 (AC: 8): Full unit suite green; `ruff check .`, `ruff format --check .`, `mypy app/` all clean. Confirm zero `apps/web/**` touches.

## Dev Notes

- **Current state of `get_lesson`** (`apps/api/app/modules/content/router.py:284-324`): fetches `lessons` row via `.select("*").eq("lesson_id", lesson_id).maybe_single().execute()` — so `lesson["content"]` (the JSONB dict) is *already fetched* today, just never read or returned. No new DB query needed, only using data already in hand.
- **`package_builder_node` writes** (`graph.py:3785-3791`): `supabase.table("lessons").update({"content": lesson_package, "status": "ready", "title": ...})` where `lesson_package = package.model_dump(mode="json")` (a `LessonPackage.model_dump(mode="json")` dict — UUIDs as strings, etc.). This is exactly the dict shape `lesson["content"]` will be when fetched back.
- **Storage path formats to resolve** (unchanged from Story 3-6): `Narration.audio_url` is `f"{lesson_id}/{segment_id}.mp3"` in bucket `"lesson-audio"` (`graph.py:3046-3047`); `Slide.image_url` is `f"{lesson_id}/{slide_id}.png"` in bucket `"lesson-images"` (`graph.py:3300-3301`). Both already pass `_ALLOWED_BUCKETS` in `media/router.py` (unaffected by this story, that allowlist isn't used here — this story calls the storage client directly via the new shared helper, not through the media router's HTTP layer).
- **`Slide.fallback_image_url` is always `None`** — confirmed via `graph.py:1657` (`"fallback_image_url": None`) with no other producer anywhere in the pipeline. Do not attempt to sign it; pass through unchanged.
- **Reference the exact key-extraction pattern from Story 3-6's `media/router.py`** (post-review): `signed = supabase.storage.from_(bucket).create_signed_url(path, expires_in); signed_url = signed["signedURL"]`, wrapped in one `try/except Exception` that treats any failure (raised exception, missing key, `None` value) uniformly. The new `sign_storage_path()` helper should be this exact logic, parameterized, returning `None` on any failure instead of raising an `HTTPException` (the HTTP-specific 404 stays in `media/router.py`'s endpoint; `content/router.py` maps a `None` to the `""`/`None` degrade value instead, per AC-3 — different callers, different failure-handling needs, same core signing call).
- **Frontend handoff (once this lands — NOT part of this story):** Dev 2's remaining work becomes swapping `apps/web/src/mocks/data/lessonPackage.ts` for a real call to this endpoint — no new URL-signing logic needed frontend-side, since URLs arrive pre-resolved. Do not touch `apps/web/**` in this story.
- **Known, disclosed, out-of-scope follow-up:** this resolves one asset at a time (N segments' audio + M slides' images = N+M `create_signed_url` calls per lesson view). Supabase Storage may support a bulk/batch signing call in the pinned `storage3==2.31.0` client — worth investigating in a future perf pass once real usage volume is known. Not blocking this fix; the existing `media/router.py` endpoint already established the one-at-a-time pattern.

### Project Structure Notes

- Touches: `apps/api/app/core/storage.py` (NEW), `apps/api/app/modules/media/router.py` (UPDATE — refactor only), `apps/api/app/modules/content/router.py` (UPDATE), `apps/api/tests/unit/test_content_router.py` (UPDATE — new tests), `apps/api/tests/unit/test_media_router.py` (verify unmodified/green). No schema, migration, or frozen-contract *shape* changes — `LessonPackage`/`lesson_package.schema.json`/`lesson.ts` are unchanged; only the already-frozen `content` field (which existed in the TS type and unused Python `LessonRecord` all along) is finally being populated.

### References

- [Source: docs/dev1-tracker.md#API Endpoints (Frozen)] — `GET /api/content/lessons/{lesson_id}` tagged S1, "Returns LessonRecord (status + content when ready)"
- [Source: packages/shared/types/lesson.ts#LessonRecord]
- [Source: apps/api/app/schemas/lesson.py#LessonRecord] (unused, tested, matches TS type)
- [Source: apps/api/app/modules/content/router.py#get_lesson, list_lessons, LessonStatusResponse]
- [Source: apps/api/app/modules/content/pipeline/graph.py#package_builder_node]
- [Source: apps/api/app/modules/media/router.py#get_signed_url] (Story 3-6, post-review shape to extract from)
- [Source: docs/stories/3-6-media-signed-url-layer.md] (Story 3-6 — this story's direct predecessor/dependency)

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-23 | Story created — Sprint 1 gap discovered while building Story 3-6. | Dev 1 |

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (Sonnet 5 session default)

### Debug Log References

### Completion Notes List

### File List
