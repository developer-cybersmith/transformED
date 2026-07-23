---
baseline_commit: caff943977a001c2b34da3e3a3f338cb83fcba83
---

# Story 3.6: Media signed-URL layer (finish `GET /api/media/signed-url`)

Status: ready-for-dev

## Story

As the content pipeline (Dev 1) and the lesson player (Dev 2),
I want `GET /api/media/signed-url` to actually resolve a private-bucket storage path to a time-limited signed URL, with ownership verified before signing,
so that the bare storage paths `package_builder_node` stores in `audio_url`/`image_url` (`{lesson_id}/{segment_id}.mp3` in `lesson-audio`, `{lesson_id}/{slide_id}.png` in `lesson-images`) are resolvable, and no caller can sign an object belonging to another user's lesson (IDOR).

**Source:** 2026-07-22 Dev1↔Dev2 audit (`docs/reports/audit-dev1-dev2-2026-07-22.md`), HIGH finding #3 — *"`audio_url`/`image_url` are bare private-bucket paths; no signing layer... will 404 the moment real content is wired."*

## Acceptance Criteria

1. **AC-1 — ownership-verified signing.** Given a `path` of the form `{lesson_id}/{filename}`, the handler looks up `lessons` by the parsed `lesson_id` and 404s (`"Lesson not found"`, same message/shape as `content/router.py:get_lesson`) if the lesson doesn't exist or `lessons.user_id != current_user["sub"]` — never a 403/401 that would leak existence to a non-owner (IDOR prevention, matching the existing `get_lesson` pattern).
2. **AC-2 — malformed path handling.** A `path` with no `/` (no parseable lesson_id prefix), or a lesson_id segment that isn't a valid UUID, returns `404` (not a 500) — same non-leaking posture as AC-1, and consistent with `get_lesson`'s `uuid.UUID(lesson_id)` → 404-on-`ValueError` pattern (`content/router.py:292-297`).
3. **AC-3 — real signing call.** On a valid, owned path, calls `supabase.storage.from_(bucket).create_signed_url(path, expires_in)` and returns `SignedUrlResponse(signed_url=..., expires_in=expires_in)`. If the storage call itself raises (object doesn't exist in the bucket, or any other storage error), return `404` — do not let a raw storage exception surface as an unhandled 500.
4. **AC-4 — existing behavior preserved.** The bucket allowlist check (already implemented, `_ALLOWED_BUCKETS`) still runs first and still 400s on an unlisted bucket, unchanged. `expires_in` bounds (`ge=60, le=86400`, default `3600`) unchanged.
5. **AC-5 — backend-only scope.** No changes to `apps/web/src/**` (player, `lesson.service.ts`, `useLessonSocket`). Those files carry an explicit `[DEV1-SPRINT2-PENDING] ... ping Dev 1 before changing this shape` marker from Dev 2, and there is no real "GET lesson content" REST endpoint wiring a real `LessonPackage` to the player yet — the player still runs entirely on `apps/web/src/mocks/`. Wiring the player to call this endpoint is out of scope here; note it as a follow-up in Dev Notes.
6. **AC-6 — tests, no live network.** New unit tests in `apps/api/tests/unit/test_media_router.py` cover: unowned lesson (404), lesson not found (404), malformed path (404), disallowed bucket (400, regression-only — already covered, keep green), and successful signing (200, asserting the mocked `create_signed_url` was called with `(path, expires_in)` and the response echoes its result). Supabase client is mocked — no real network/storage calls. `ruff` + `mypy` clean.

## Tasks / Subtasks

- [ ] Task 1 (AC: 1, 2): Add a `_parse_lesson_id(path: str) -> str | None` helper — split on first `/`, validate the prefix as a UUID, return `None` on any failure.
- [ ] Task 2 (AC: 1, 3): Implement the ownership check (`supabase.table("lessons").select("user_id").eq("lesson_id", ...).maybe_single().execute()`) and the real `create_signed_url` call in `get_signed_url`, replacing the `501` stub. Wrap the storage call in a try/except → 404 on any exception (do not leak storage error internals).
- [ ] Task 3 (AC: 6): `apps/api/tests/unit/test_media_router.py` — new file, mocking `app.core.db.get_supabase` and `CurrentUser`.
- [ ] Task 4 (AC: 4, 6): Full unit suite green; `ruff`/`mypy` clean; confirm no `apps/web` files touched (`git diff --stat` scoped to `apps/api` + `docs/`).

## Dev Notes

- **Current state of `apps/api/app/modules/media/router.py`:** route shape, `SignedUrlResponse` model, and `_ALLOWED_BUCKETS` allowlist already exist and are correct (per the audit, this is the *only* endpoint in this module). The handler 501s immediately after the bucket check — the docstring's own two-step TODO (ownership check + signing call) is what this story implements.
- **Reference pattern — `get_lesson`** (`apps/api/app/modules/content/router.py:284-307`): `uuid.UUID(lesson_id)` in a try/except → 404 on `ValueError`; then `lessons` table lookup by `lesson_id`; `if not lesson or lesson.get("user_id") != user_id: raise 404`. Mirror this exactly for the ownership check — same non-distinguishing 404 for "doesn't exist" vs "not yours".
- **Storage paths this unblocks** (from `apps/api/app/modules/content/pipeline/graph.py`): `audio_path = f"{lesson_id}/{segment_id}.mp3"` (bucket `lesson-audio`, graph.py:3046) and `image_path = f"{lesson_id}/{slide_id}.png"` (bucket `lesson-images`, graph.py:3300). Both already pass the `_ALLOWED_BUCKETS` check.
- **Why bare paths are stored, not signed URLs (do not "fix" this the other way):** `apps/api/app/schemas/lesson.py:89-95` and `package_builder_node`'s docstring (graph.py:3458-3462) are explicit — baking a signed URL into `lessons.content` JSONB at build time would expire (Supabase max ~7 days) before a lesson is necessarily viewed. Resolving at view time via this endpoint is the correct place; do not move signing into `package_builder_node`.
- **Frontend follow-up (explicitly NOT this story — AC-5):** there is currently no real REST endpoint serving a real `LessonPackage` to the player (`apps/web/src/services/lesson.service.ts` and the player components all run on `apps/web/src/mocks/`; the only real delivery path today is the `lesson_ready` WebSocket push + a 24h Redis cache, `apps/api/app/core/pubsub.py:97`). Whoever builds the real "GET lesson content" path next should either (a) have the player call `GET /api/media/signed-url` per asset before rendering `<audio src>`/`<img src>`, or (b) resolve signed URLs server-side when serving lesson content — either is compatible with this story's endpoint; picking between them is that future story's call, not this one's.
- **Testing standards:** mirror the mocking style of existing router tests (e.g. `apps/api/tests/unit/test_bucket_manifest.py` or `content` router tests) — mock `app.core.db.get_supabase`, override `CurrentUser` via FastAPI `app.dependency_overrides`, use `TestClient`/`httpx.AsyncClient` per whatever the existing test files already use (check `apps/api/tests/unit/conftest.py` for the established fixture pattern before writing new ones).

### Project Structure Notes

- Touches only `apps/api/app/modules/media/router.py` (existing file, UPDATE) and adds `apps/api/tests/unit/test_media_router.py` (NEW). No schema, migration, or frozen-contract changes — `SignedUrlResponse` shape is unchanged.

### References

- [Source: docs/reports/audit-dev1-dev2-2026-07-22.md#Part 2 — Confirmed lurking bugs (ranked), HIGH #3]
- [Source: apps/api/app/modules/media/router.py]
- [Source: apps/api/app/modules/content/router.py#get_lesson]
- [Source: apps/api/app/modules/content/pipeline/graph.py#package_builder_node]
- [Source: apps/api/app/schemas/lesson.py#Slide, Narration]

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-23 | Story created from the 2026-07-22 audit's HIGH #3 finding. | Dev 1 |

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (Sonnet 5 session default)

### Debug Log References

### Completion Notes List

### File List
