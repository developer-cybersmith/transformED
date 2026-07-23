---
baseline_commit: caff943977a001c2b34da3e3a3f338cb83fcba83
---

# Story 3.6: Media signed-URL layer (finish `GET /api/media/signed-url`)

Status: done

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

- [x] Task 1 (AC: 1, 2): Add a `_parse_lesson_id(path: str) -> str | None` helper — split on first `/`, validate the prefix as a UUID, return `None` on any failure.
- [x] Task 2 (AC: 1, 3): Implement the ownership check (`supabase.table("lessons").select("user_id").eq("lesson_id", ...).maybe_single().execute()`) and the real `create_signed_url` call in `get_signed_url`, replacing the `501` stub. Wrap the storage call in a try/except → 404 on any exception (do not leak storage error internals).
- [x] Task 3 (AC: 6): `apps/api/tests/unit/test_media_router.py` — new file, mocking `app.core.db.get_supabase` and `CurrentUser`.
- [x] Task 4 (AC: 4, 6): Full unit suite green; `ruff`/`mypy` clean; confirm no `apps/web` files touched (`git diff --stat` scoped to `apps/api` + `docs/`).

## Dev Notes

- **Current state of `apps/api/app/modules/media/router.py`:** route shape, `SignedUrlResponse` model, and `_ALLOWED_BUCKETS` allowlist already exist and are correct (per the audit, this is the *only* endpoint in this module). The handler 501s immediately after the bucket check — the docstring's own two-step TODO (ownership check + signing call) is what this story implements.
- **Reference pattern — `get_lesson`** (`apps/api/app/modules/content/router.py:284-307`): `uuid.UUID(lesson_id)` in a try/except → 404 on `ValueError`; then `lessons` table lookup by `lesson_id`; `if not lesson or lesson.get("user_id") != user_id: raise 404`. Mirror this exactly for the ownership check — same non-distinguishing 404 for "doesn't exist" vs "not yours".
- **Storage paths this unblocks** (from `apps/api/app/modules/content/pipeline/graph.py`): `audio_path = f"{lesson_id}/{segment_id}.mp3"` (bucket `lesson-audio`, graph.py:3046) and `image_path = f"{lesson_id}/{slide_id}.png"` (bucket `lesson-images`, graph.py:3300). Both already pass the `_ALLOWED_BUCKETS` check.
- **Why bare paths are stored, not signed URLs (do not "fix" this the other way):** `apps/api/app/schemas/lesson.py:89-95` and `package_builder_node`'s docstring (graph.py:3458-3462) are explicit — baking a signed URL into `lessons.content` JSONB at build time would expire (Supabase max ~7 days) before a lesson is necessarily viewed. Resolving at view time via this endpoint is the correct place; do not move signing into `package_builder_node`.
- **Frontend follow-up (explicitly NOT this story — AC-5):** there is currently no real REST endpoint serving a real `LessonPackage` to the player (`apps/web/src/services/lesson.service.ts` and the player components all run on `apps/web/src/mocks/`; the only real delivery path today is the `lesson_ready` WebSocket push + a 24h Redis cache, `apps/api/app/core/pubsub.py:97`). Whoever builds the real "GET lesson content" path next should either (a) have the player call `GET /api/media/signed-url` per asset before rendering `<audio src>`/`<img src>`, or (b) resolve signed URLs server-side when serving lesson content — either is compatible with this story's endpoint; picking between them is that future story's call, not this one's.
- **Pre-existing, disclosed gap — 2 of the 5 allowlisted buckets don't follow the `{lesson_id}/...` path convention this endpoint assumes** (found during code review, verified against actual upload sites, not introduced by this story): `source-pdfs` objects are keyed `{user_id}/{book_id}/{filename}` (`content/router.py:209-214` — first segment is a `user_id`, not a `lesson_id`) and `avatar-clips` objects are lesson-independent static keys like `clips/intro_default.mp4` (`providers/avatar/heygen.py:37-40`, which self-signs internally and never calls this endpoint). Both already fail closed (404, non-leaking) via this endpoint rather than succeeding incorrectly — `source-pdfs`'s UUID-shaped `user_id` prefix passes `_parse_lesson_id` but then fails the `lessons` table lookup; `avatar-clips`' literal `"clips"` prefix isn't a UUID and 404s before any DB call. No lesson ever loses access through this endpoint because of it — but if a future story wants `source-pdfs` signing through this endpoint (e.g. a "download my original PDF" feature), it will need bucket-specific ownership logic (check against `books.user_id`, not `lessons.user_id`), not a naive reuse of `_parse_lesson_id`. `lesson-slides` has no producer code anywhere in the repo yet — its real path format is undetermined.
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
| 2026-07-23 | Implemented (RED→GREEN): ownership check + real signing call, replacing the 501 stub. 8 new tests, 553/553+1 skipped full suite green, ruff+mypy clean, zero `apps/web` touches. | Dev 1 |
| 2026-07-23 | Addressed 5-agent code review (Blind Hunter, Edge Case Hunter, Acceptance Auditor): fixed signed-URL key extraction to match the codebase's established single-key pattern (`heygen.py`'s `result["signedURL"]`) instead of guessing 3 key spellings, and closed the uncaught-`AttributeError`/`KeyError` gap on a malformed storage response. 1 new regression test (9 total). Path-traversal and non-lesson-bucket concerns investigated and either refuted (traversal — object-key store, not filesystem) or disclosed as a pre-existing, non-regressing gap (bucket/path-convention mismatch) in Dev Notes. | Dev 1 |

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (Sonnet 5 session default)

### Debug Log References

- `uv run pytest tests/unit/test_media_router.py -q` — RED: 8 failed (`AttributeError: ... does not have the attribute 'get_supabase'` — module didn't import it pre-implementation).
- `uv run pytest tests/unit/test_media_router.py -q` — GREEN: 8 passed after implementation.
- `uv run pytest tests/unit tests/integration -q` — 553 passed, 1 skipped (no regressions).
- `uv run ruff check .` / `uv run mypy app/` — both clean, repo-wide.

### Completion Notes List

- `_parse_lesson_id` splits `path` on the first `/`, validates the prefix as a UUID via `uuid.UUID(...)`, returns `None` on any malformed input (no slash, empty prefix, non-UUID) — caller maps `None` to 404 without ever touching the DB (`sb.table.assert_not_called()` asserted in both malformed-path tests).
- Ownership check mirrors `content/router.py:get_lesson` exactly: same non-distinguishing 404 for "lesson not found" vs "lesson owned by someone else" (AC-1/AC-2 — no IDOR existence leak).
- `create_signed_url`'s return dict key is defensively read as `signedURL` / `signedUrl` / `signed_url` (storage3 2.31.0 pinned per `uv.lock`; guards against minor client-version key drift without adding a hard dependency on internals) — any exception from the storage call, or a response missing all three keys, maps to 404 (AC-3).
- Confirmed via `git status --short` that only `apps/api/app/modules/media/router.py` (UPDATE) and `apps/api/tests/unit/test_media_router.py` (NEW) changed — no `apps/web/**` files touched (AC-5). An unrelated `uv.lock` drift (pyjwt `crypto` extra, picked up incidentally by `uv run`) was reverted before commit — out of this story's scope.
- Frontend wiring (player calling this endpoint, or a future "GET lesson content" endpoint resolving signed URLs server-side) remains an explicit follow-up per AC-5/Dev Notes — not implemented here.
- **Code review (5-agent gate) findings and disposition:**
  - **FIXED** — signed-URL key extraction guessed 3 possible key spellings (`signedURL`/`signedUrl`/`signed_url`) instead of the codebase's one established, evidenced key (`heygen.py:80`'s `result["signedURL"]`); also left a `None`/malformed-response path uncaught outside the `try` (AttributeError/KeyError → unhandled 500). Fixed by moving the key access inside the `try` and using the single canonical key. New regression test added.
  - **REFUTED** — path traversal via `..` in `path` (e.g. `{owned_lesson_id}/../{other}/audio.mp3`): investigated; Supabase Storage is a flat object-key store with no filesystem traversal semantics, and `path` is never passed to a local filesystem API — the malformed key simply fails to match any real object (404). Not exploitable; no fix needed.
  - **DISCLOSED, not fixed (pre-existing, not a regression)** — `source-pdfs` and `avatar-clips` buckets don't follow the `{lesson_id}/...` convention this endpoint assumes; both already fail closed (404) rather than leaking, so no story ACs are violated. See Dev Notes for detail and the fix a future story would need.
  - **NOT ACTIONED (spec-mandated or out of scope)** — broad `except Exception` on the storage call is required by AC-3 itself; DB-query exception handling intentionally mirrors `get_lesson`'s existing unwrapped behavior per Dev Notes ("mirror exactly"); rate limiting / RLS defense-in-depth are project-wide, cross-cutting concerns tracked separately (not introduced or worsened by this story).

### File List

- `apps/api/app/modules/media/router.py` (UPDATE) — implemented `_parse_lesson_id`, ownership check, real `create_signed_url` call, replacing the `501` stub.
- `apps/api/tests/unit/test_media_router.py` (NEW) — 9 tests covering AC-1 through AC-4/AC-6, including the review-driven regression test.
- `docs/stories/3-6-media-signed-url-layer.md` (this file).
- `docs/dev1-tracker.md` (UPDATE, story-first commit) — added S3-6 entry + dashboard totals.
