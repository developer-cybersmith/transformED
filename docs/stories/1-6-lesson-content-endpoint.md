---
baseline_commit: 70a73264983607db3bb5a79b7957e21501d77c17
---

# Story 1.6: `GET /api/content/lessons/{id}` returns real `content` (Sprint 1 gap-fix)

Status: done

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

- [x] Task 1 (AC: 4): `apps/api/app/core/storage.py` — new module, `sign_storage_path(supabase, bucket, path, expires_in=3600) -> str | None`.
- [x] Task 2 (AC: 4): Refactor `media/router.py:get_signed_url` to call `sign_storage_path()` instead of its inline try/except — zero behavior change, existing 10 tests pass unmodified.
- [x] Task 3 (AC: 1, 2, 3, 5, 6): `content/router.py` — add `content` field to `LessonStatusResponse`; add a `_resolve_lesson_content(content: dict, supabase) -> LessonPackage` helper; wire it into `get_lesson` only, gated on `status == "ready"` and non-null `content`.
- [x] Task 4 (AC: 7): Confirm `list_lessons` is untouched (it calls the same `_row_to_status_response` — verify that helper does NOT call `_resolve_lesson_content`; only `get_lesson` does, as an explicit extra step after the shared helper).
- [x] Task 5 (AC: 8): New tests in `test_content_router.py`; re-run `test_media_router.py` to confirm zero regressions from the DRY refactor.
- [x] Task 6 (AC: 8): Full unit suite green; `ruff check .`, `ruff format --check .`, `mypy app/` all clean. Confirm zero `apps/web/**` touches.

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
| 2026-07-23 | Implemented (RED→GREEN): shared `sign_storage_path()` helper, media/router.py refactored onto it (zero behavior change), `content` wired into `get_lesson` only. 16 new tests, 564/564+1 skipped full suite green, ruff+format+mypy clean, zero `apps/web` touches. | Dev 1 |
| 2026-07-23 | Addressed 5-agent code review (Blind Hunter, Edge Case Hunter, Acceptance Auditor, Story Quality, Process Integrity, Test Coverage): added logging on signing failure, fixed a `segments`/`slides`-explicitly-null crash (`.get(k, [])` → `.get(k) or []`), and closed 2 Test Coverage gaps (ready+null-content edge case; corruption-not-swallowed over the full HTTP path). 5 new regression tests (26 total in test_content_router.py's Story 1-6 section + storage_helper.py). 569/569+1 skipped full suite green. | Dev 1 |

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (Sonnet 5 session default)

### Debug Log References

- `uv run pytest tests/unit/test_storage_helper.py -q` — RED: 5 failed (`ImportError: cannot import name 'sign_storage_path'`). GREEN after implementation: 5 passed.
- `uv run pytest tests/unit/test_content_router.py -q -k "ready or content"` — RED: 4 failed (`KeyError: 'content'`). GREEN after implementation: all passed.
- **Self-caught bug during GREEN**: `_resolve_lesson_content` initially mutated its `content` dict argument in place; the second new test's fixture (reusing the same module-level `_READY_CONTENT_DICT` object) came back double-signed, revealing the mutation. Fixed with `copy.deepcopy(content)` at the top of the function — now a pure function, matches how `lesson["content"]` arrives fresh per-request in production anyway, but avoids the footgun for any future caller that might share/cache the dict.
- `uv run pytest tests/unit/test_media_router.py -q` — 10/10 still pass, unmodified, after the DRY refactor onto `sign_storage_path()` (AC-4 zero-behavior-change requirement).
- `uv run pytest tests/unit tests/integration -q` — one unrelated regression caught and fixed: `test_bucket_manifest.py`'s static scanner flagged `core/storage.py:bucket` as a new unresolvable dynamic bucket reference (the `.storage.from_(bucket)` call moved out of `media/router.py` into the new shared helper) and flagged the old `modules/media/router.py:bucket` allowlist entry as stale. Updated `_MANUAL_DYNAMIC_REFERENCES` accordingly with a justification reflecting the actual call sites (media router's already-allowlisted `bucket`; content router's hardcoded `"lesson-audio"`/`"lesson-images"` literals only). 564 passed, 1 skipped after the fix.
- `uv run ruff check .` / `ruff format --check .` / `uv run mypy app/` — all clean, repo-wide.

### Completion Notes List

- `sign_storage_path()` in `apps/api/app/core/storage.py` (appended to the existing bucket-provisioning module, not a new file — `core/storage.py` already existed with `assert_required_buckets`/`REQUIRED_BUCKETS` from Story 2-0) is the single implementation of "call `create_signed_url`, pull the `signedURL` key, catch any failure → `None`" — used by both `media/router.py` (Story 3-6, refactored) and `content/router.py` (this story).
- `get_lesson` resolves `content` only when `status == "ready"` and the JSONB column is non-null; `list_lessons` shares the same `LessonStatusResponse` model but never calls `_resolve_lesson_content` — verified by a dedicated regression test asserting `sb.storage.from_.assert_not_called()` on a list request even with a ready-with-content row (AC-7).
- Per-asset signing failures degrade only that asset (`""` for `audio_url`, `None` for `image_url`) without failing the rest of the response (AC-3) — verified by a test where `create_signed_url` raises for the audio path only.
- `Slide.fallback_image_url` is never touched by the resolution logic, matching the confirmed fact that no pipeline node ever sets it to anything but `None`.
- Disclosed, not fixed (per Dev Notes / AC out of scope): one-asset-at-a-time signing (N+M calls per lesson view) rather than a hypothetical Supabase batch-signing endpoint — a future perf pass once real usage volume is known.
- Frontend handoff unblocked: Dev 2 can now swap `apps/web/src/mocks/data/lessonPackage.ts` for a real call to `GET /api/content/lessons/{id}` and get pre-signed URLs with no new frontend logic — confirmed zero `apps/web/**` files touched by this story.
- **Code review (5-agent gate) findings and disposition:**
  - **FIXED** — `sign_storage_path()` swallowed every signing failure with zero observability; added `logger.warning(..., exc_info=True)` on the except path so a real storage outage is diagnosable, not indistinguishable from a legitimate not-found.
  - **FIXED** — `_resolve_lesson_content` used `content.get("segments", [])` / `segment.get("slides", [])`, whose default only applies on a *missing* key, not an explicit JSON `null`; an explicitly-null `segments`/`slides` would crash the loop with a raw `TypeError` before reaching `LessonPackage.model_validate`'s clean `ValidationError`. Fixed to `.get(k) or []`; 2 new regression tests confirm a clean `ValidationError` (not a `TypeError`) and that the loop makes zero signing calls when it never runs.
  - **FIXED (Test Coverage gap)** — added a test for `status == "ready"` with a null `content` column (should be unreachable in practice since `package_builder` writes both together atomically, but the endpoint's own guard is now directly tested rather than only inferred).
  - **FIXED (Test Coverage gap)** — added a full-HTTP-path test proving corrupted stored content raises a `500` through `get_lesson` rather than being silently swallowed (AC-6 was previously only tested by calling `_resolve_lesson_content` directly, not through the actual endpoint).
  - **REFUTED** — "no test coverage for `sign_storage_path`/`_resolve_lesson_content`" (Blind Hunter): false: the reviewer was given only the production-code diff, not the test diffs; both are covered (`test_storage_helper.py`'s 5 tests, `test_content_router.py`'s Story 1-6 section).
  - **REFUTED** — "unbounded `expires_in` lets a caller mint long-lived signed URLs" (Blind Hunter): doesn't apply to this story's code path — `_resolve_lesson_content` never passes a caller-controlled `expires_in` to `sign_storage_path`, it always uses the function's fixed default (3600s); `media/router.py`'s pre-existing, unchanged `expires_in` query param is already bounded `ge=60, le=86400`.
  - **NOT ACTIONED (deliberate, spec-mandated design)** — "corrupted content takes down the whole status-reporting endpoint, not just content" and "empty-string `audio_url` has no format validation": both are AC-6's and the pipeline's existing degrade-not-drop convention working exactly as designed, not defects. N+M sequential signing calls / no URL caching: explicitly disclosed as an out-of-scope future perf pass in Dev Notes, not a defect.
  - **NOT ACTIONED (low-value, structurally evident)** — Test Coverage's third gap ("no test proving the media router's HTTP endpoint/ownership-check isn't re-invoked") — the code path structurally cannot reach that endpoint (content/router.py calls `sign_storage_path()` directly, never imports or calls into `modules/media/router.py`); an artificial test asserting an import-graph fact would be low value.

### File List

- `apps/api/app/core/storage.py` (UPDATE) — added `sign_storage_path()` (with failure logging) to the existing bucket-provisioning module.
- `apps/api/app/modules/media/router.py` (UPDATE) — refactored `get_signed_url` onto the shared helper; zero behavior change.
- `apps/api/app/modules/content/router.py` (UPDATE) — `content` field on `LessonStatusResponse`; `_resolve_lesson_content()` helper (null-safe `segments`/`slides` handling); wired into `get_lesson` only.
- `apps/api/tests/unit/test_storage_helper.py` (NEW) — 5 tests for `sign_storage_path()`.
- `apps/api/tests/unit/test_content_router.py` (UPDATE) — 9 new tests total (signed-URL resolution, degrade-on-failure, non-ready regression, list-never-attaches regression, input-mutation regression, null-segments/null-slides edge cases, ready+null-content edge case, corruption-not-swallowed full-HTTP-path test).
- `apps/api/tests/unit/test_bucket_manifest.py` (UPDATE) — `_MANUAL_DYNAMIC_REFERENCES` updated to reflect the refactor (removed stale entry, added the new shared-helper entry with justification).
- `docs/stories/1-6-lesson-content-endpoint.md` (this file).
- `docs/dev1-tracker.md` (UPDATE, story-first commit) — Sprint 1 status note.

## Senior Developer Review (AI)

**Date:** 2026-07-23 · **Outcome:** Approve

5 adversarial layers per the BMAD Code Review Gate:

1. **Story Quality** — Pass. All 8 ACs objectively testable; story-first commit (`2b332b7`) verified chronologically first, touching only the story file + tracker; implementation scope matches stated ACs exactly, no creep.
2. **Blind Hunter (Security)** — 2 findings fixed (silent-failure observability gap; the `.get(k, [])` vs `.get(k) or []` null-safety gap, shared with Edge Case Hunter below). Several findings refuted or deferred as deliberate/out-of-scope design (see Completion Notes for the full disposition list).
3. **Test Coverage** — 2 gaps found and closed (ready+null-content edge case; corruption-not-swallowed over the full HTTP path, not just the helper function directly). One low-value gap (proving no HTTP re-invocation of the media router) explicitly not actioned — structurally evident from the code, not worth an artificial test.
4. **AC Completeness** (Acceptance Auditor) — Pass, no violations. All 8 ACs independently confirmed satisfied against the diff and the full test suite; confirmed `test_media_router.py`'s 10 tests are genuinely unmodified (AC-4).
5. **Process Integrity** — Pass. No LLM/model calls in this module (pure Supabase Storage signing + JSONB serving); story-first gate honored; branch naming (`fix/s1-lesson-content-endpoint`) matches the established `fix/s{N}-{slug}` precedent for retroactive gap-fixes (distinct from `sprint{N}/s{N}-{M}-{slug}` for new tasks); tracker updated via narrative status-line note (matching how Sprint 2's audit batch was handled), not a misleading new checkbox on an already-"COMPLETE" sprint.

**Action items:** none outstanding — all findings from layers 2–3 were fixed in this review round; layers 1, 4, and 5 raised no findings.
