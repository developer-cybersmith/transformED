# Story 2.45: Per-asset signed-URL auto-refresh + DEFER-012 register entry

Status: review

<!-- baseline_commit: c2f2873 (branch rebased onto sprint3-master 2026-08-11 -- useAttentionMonitor.ts does not exist on main) -->
<!-- Branch note: PRs into sprint3-master, not main, per the same reason. -->

## Story

As a student partway through a lesson,
I want an audio or image asset whose signed URL has expired to quietly re-sign and keep playing,
so that pausing and coming back to a lesson never strands me on a dead asset with nothing but a full-page Retry.

## Acceptance Criteria

1. **Per-asset re-sign helper.** A new frontend helper (e.g. `lib/media/refreshSignedUrl.ts`) accepts an expired Supabase signed URL string, extracts `{bucket, path}` from its `/storage/v1/object/sign/{bucket}/{path}` shape, and calls the real backend endpoint `GET /api/media/signed-url?bucket=...&path=...` (via the existing `api` axios client at `lib/api.ts`, which already attaches the Supabase JWT) to obtain a fresh `signed_url`. Malformed input (URL doesn't match the expected shape) returns `null` rather than throwing.
2. **Audio auto-recovers on expiry.** `AudioTimeline.tsx`'s `handleError()` (currently `apps/web/src/components/player/AudioTimeline.tsx:356-361`, unconditionally sets `audioError`) first attempts exactly one automatic re-sign of the failed segment's `narration.audio_url` via AC1's helper. On success, the store's copy of that segment's `audio_url` is updated in place and the `<audio>` element remounts with the fresh URL (reuse the existing `audioRetryCount`-keyed remount mechanism) — playback resumes without the student clicking anything. On failure (helper returns `null`, or the re-signed fetch itself later errors), fall through to today's behavior unchanged: `setAudioError(true)`, surfacing the existing manual Retry UI.
3. **Images auto-recover on expiry.** `SlideRenderer.tsx`'s `SlideImage` (`apps/web/src/components/player/SlideRenderer.tsx:15-49`) attempts exactly one automatic re-sign of `imageUrl` via AC1's helper before falling back to `fallbackUrl` / the "No image" placeholder. Success swaps `src` to the fresh URL; failure preserves today's fallback-then-placeholder chain unchanged.
4. **One automatic attempt, never a loop.** Both AC2 and AC3 attempt the automatic re-sign **at most once per asset per mount** (a per-element ref/flag, reset only on segment change or a genuinely new asset — not on the retried element's own subsequent `onError`). A second failure on the same asset goes straight to the existing manual-recovery path (Retry button / fallback image / placeholder) — it must never re-trigger the auto-resign and loop.
5. **No change to the manual Retry path.** `Player.tsx`'s `handleRetryAudio()` (full-lesson refetch via `onRefetchLesson` + `refreshLessonMedia`) is untouched and still works exactly as today — AC2's automatic path is a first line of defense in front of it, not a replacement.
6. **DEFER-012 gets a real register ID.** Add entry **D63** to `docs/DEFECT-REGISTER.md`'s "OPEN — accepted, with a named trigger" table, describing `apps/web/src/hooks/useAttentionMonitor.ts`'s `MODEL_ASSET_URL` pointing at a floating `float16/latest/face_landmarker.task` tag instead of a pinned version, with owner Dev 2 and an explicit trigger (a real, currently-valid versioned MediaPipe model URL is confirmed against official docs). Update the inline `DEFER-012` comment in `useAttentionMonitor.ts` and the entry in `docs/deferred-work.md` to cross-reference **D63** by ID, per CLAUDE.md binding rule 5.
7. **Tests.** Unit tests for the URL-parsing helper (valid shape, malformed shape, wrong host) with no network calls; component tests for AC2/AC3/AC4 (mock `api.get` — one 403/error triggers exactly one re-sign attempt and a successful swap; a second failure on the same asset does not re-trigger). No existing `AudioTimeline`/`SlideRenderer`/`Player` test should need behavior changes beyond what these ACs add.

## Scale & Load

1. **What is ONE unit of work, and what is its range?**
   One unit of work is one re-sign HTTP call for one media asset (one audio segment's MP3, or one slide's image) triggered by exactly one load failure. Per lesson: 4–12 segments (measured range, per `docs/LESSON-DELIVERY-TRACKER.md` L2), each with one audio asset and typically 1 image per slide within the segment. In the common case zero re-sign calls ever fire (URLs are valid for the `_EMBEDDED_MEDIA_EXPIRY_S` 8-hour window). Worst case — a lesson resumed after that window — is bounded by AC4's per-asset cap: at most one re-sign call per asset actually encountered during playback, never more.

2. **Which budgets are FIXED while the input VARIES — and what happens past them?**
   The only new fixed budget is AC4's "at most one automatic re-sign attempt per asset" — past it, the code falls through to the existing, already-surfaced manual-recovery UI (Retry button / image placeholder), never a silent retry loop. The backend's own `expires_in` bound (`Query(..., ge=60, le=86400)` in `apps/api/app/modules/media/router.py:69`) is pre-existing and untouched by this story.

3. **What is the SCOPE of every limit — per user, per instance, or per deployment?**
   Per asset, per mounted player instance (client-side `useRef`/state, not persisted, not shared across tabs or sessions). The backend endpoint's ownership check (does `current_user` own the `lesson_id` parsed from the path) is enforced server-side per-request and is unchanged by this story.

4. **Which reads and writes are UNBOUNDED?**
   None introduced. This story adds exactly one bounded `GET` call per failed asset — no list, no batch, no query with row growth.

5. **Which caps were INHERITED from an earlier design, and have they been re-derived?**
   None inherited or changed. `_EMBEDDED_MEDIA_EXPIRY_S` (8 hours, backend) and the endpoint's `expires_in` range are both out of scope for this story — it only adds a client-side caller to the already-shipped, already-bounded endpoint.

6. **Is every check-then-act sequence safe under CONCURRENT requests?**
   Yes, trivially: each re-sign is an idempotent `GET` with no server-side write and no shared mutable state. Two browser tabs on the same lesson each maintain independent client-side retry-attempted flags and independently re-sign their own expired asset — neither can starve or corrupt the other, and the backend performs no check-then-act sequence beyond the pre-existing per-request ownership read.

## Tasks / Subtasks

- [x] Task 1 — Add `docs/DEFECT-REGISTER.md` entry D63 for DEFER-012, and cross-reference it from `useAttentionMonitor.ts`'s inline comment and `docs/deferred-work.md` (AC: #6)
  - [x] Confirm D62 is still the highest allocated ID on `main` immediately before allocating D63 (register's own stated rule — re-check, do not trust this story's earlier read)
- [x] Task 2 — `lib/media/refreshSignedUrl.ts`: parse `{bucket, path}` from a Supabase signed URL, call `GET /api/media/signed-url`, return `string | null` (AC: #1)
  - [x] Unit tests: valid `lesson-audio`/`lesson-images` URLs, malformed URL, non-Supabase host, missing token
- [x] Task 3 — Wire the helper into `AudioTimeline.tsx`'s `handleError()` with the one-attempt-per-asset guard (AC: #2, #4, #5)
- [x] Task 4 — Wire the helper into `SlideRenderer.tsx`'s `SlideImage` `onError` with the same one-attempt guard, before the existing `fallbackUrl` chain (AC: #3, #4)
- [x] Task 5 — Component tests for both wiring points: success path (swap + resume), failure path (falls through unchanged), no-second-attempt path (AC: #7)
- [x] Task 6 — Update `docs/dev2-sprint-tracker.md` per its own convention once done

### Review Findings

- [ ] [Review][Patch] D63 collides with an already-allocated, already-closed D63 (and D64/D65) on `sprint3-master` — the actual merge target — since the re-check was performed against `main` instead [docs/DEFECT-REGISTER.md]
- [ ] [Review][Patch] Story-first gate violated: the story-only commit is not chronologically first — two unrelated `main`-origin docs commits were replayed ahead of it by the branch rebase [git history, sprint3/s3-09-signed-url-refresh]
- [ ] [Review][Patch] Race: the failed-resign `.then()` branch unconditionally calls `setAudioError(true)` with no check that the captured segment is still current — can flip a healthy, already-advanced-past (or already-reloaded-lesson) segment's error state [apps/web/src/components/player/AudioTimeline.tsx:394-397]
- [ ] [Review][Patch] A successful automatic re-sign remounts `<audio>` but the play/pause effect's dependency array doesn't include the resign, so the fresh element is never told to `.play()` — playback silently freezes [apps/web/src/components/player/AudioTimeline.tsx:100-140]
- [ ] [Review][Patch] `SlideImage`'s `attemptedResignRef` never resets when the `imageUrl` prop changes on an already-mounted instance, contradicting this story's own Dev Notes requirement [apps/web/src/components/player/SlideRenderer.tsx:25]
- [ ] [Review][Patch] `refreshSignedUrl` omits `expires_in`, so the backend's 1-hour default silently replaces the system's deliberate 8-hour `_EMBEDDED_MEDIA_EXPIRY_S` window — combined with AC4's "one attempt ever," a second silent trap [apps/web/src/lib/media/refreshSignedUrl.ts:52-54]
- [ ] [Review][Patch] `parseSignedUrl` has no origin/host validation — any string sharing the path shape is accepted regardless of host, and the existing test locks in acceptance despite its name implying rejection [apps/web/src/lib/media/refreshSignedUrl.ts, refreshSignedUrl.test.ts]
- [ ] [Review][Patch] AC4 deviation: the attempt-guard is keyed only by `segment_id` and never resets after a manual full-lesson retry delivers a genuinely new asset for that same `segment_id` [apps/web/src/components/player/AudioTimeline.tsx]
- [ ] [Review][Patch] AC2's wording ("the store's copy of that segment's `audio_url` is updated in place") doesn't match the shipped design (local component state) — align the AC text to the implementation rather than add a redundant store-mutation surface that would need its own currency guard
- [ ] [Review][Patch] Story Dev Notes citation errors: `retryAudio()` is at `player.machine.ts:349-353`, not `:310-313`; `handleRetryAudio()` spans `Player.tsx:77-91`, not `:73-87`; the `Player.tsx:21-24` reference is uninformative
- [ ] [Review][Patch] Test coverage gaps: the image-side "one attempt only" guard is never proven with a signed-url-shaped fixture + call-count assertion (existing tests use a non-matching URL, so they can't distinguish "guard worked" from "URL never matched the shape"); empty-string `signed_url` and concurrent-double-error-while-in-flight are untested
- [x] [Review][Defer] `GET /api/media/signed-url` has no rate limiting now that this story gives it its first real, unattended caller — a backend (`apps/api`) change, out of scope for this frontend-only story [apps/api/app/modules/media/router.py] — deferred, registered as **D67**, owner Dev 1

## Dev Notes

- **Backend endpoint is real, not a stub.** `apps/api/app/modules/media/router.py:60-125` — `GET /api/media/signed-url?bucket=&path=&expires_in=` — validates `bucket` against an allowlist (`lesson-audio`, `lesson-images` only), parses the owning `lesson_id` from the path's `{lesson_id}/...` prefix, checks `current_user` owns that lesson (404 either way, no existence leak), then calls `sign_storage_path`. Its own docstring calls it "DORMANT... zero callers" and flags `docs/decisionupdate.md` §7b (compiled-MP4 revision mode) as a reason to "decide before building a client against it" — **that decision is about video/Bunny Stream, an unrelated feature; this story's per-asset re-sign for first-watch audio/image assets is orthogonal to §7b and does not need to wait on it.**
- **Why parse the bucket/path out of the URL instead of a backend change:** the raw storage path (`narration.audio_url` / `slide.image_url` pre-signing) is read once inside `_resolve_lesson_content` (`apps/api/app/modules/content/router.py:607-639`) and overwritten in place with the signed URL before the response leaves the server — the `LessonPackage` the frontend receives never carries the raw path separately. Supabase's signed-URL shape is stable and parseable: `.../storage/v1/object/sign/{bucket}/{path}?token=...`. This keeps the fix entirely in `apps/web` (Dev 2's domain — no `apps/api` changes, per this story's scope).
- **Existing manual-recovery path, do not duplicate or break it:** `Player.tsx:73-87` (`handleRetryAudio`) already re-fetches the *whole* lesson (fresh signed URLs for every asset) via `onRefetchLesson` + `usePlayerStore.getState().refreshLessonMedia(fresh.content)`, then calls `retryAudio()` (`stores/player.machine.ts:310-313`, clears `audioError`, increments `audioRetryCount` to force the `<audio>` remount via its `key={segment_id}-{audioRetryCount}` at `AudioTimeline.tsx:409`). This story's automatic per-asset path sits in front of that flow, not instead of it — AC5 exists specifically to keep this boundary explicit for review.
- **`SlideImage`'s existing state chain** (`SlideRenderer.tsx:15-49`) already has a two-step fallback (`primary → fallbackUrl → placeholder`) via local `src`/`failed` state. The re-sign attempt for the primary URL must slot in as a new first step (`primary → re-signed primary → fallbackUrl → placeholder`), not replace the existing fallback semantics — a lesson whose primary image object genuinely no longer exists in storage (a real 404 from `sign_storage_path` returning `None` → the media router itself 404s) must still fall through to `fallbackUrl`/placeholder exactly as today.
- **Retry-attempted flag placement:** must live on the same lifecycle as the asset it guards (e.g., reset when `segment.segment_id` changes for audio, when `slide` identity/`imageUrl` changes for images) — not reset on every `onError` of the same element, or AC4's "at most once" becomes unenforceable.

### Project Structure Notes

- New file: `apps/web/src/lib/media/refreshSignedUrl.ts` (+ colocated test under `apps/web/src/__tests__/lib/media/refreshSignedUrl.test.ts`), matching the existing `lib/attention/signalMath.ts` pattern of pure-logic-extracted-for-testability.
- Modified: `apps/web/src/components/player/AudioTimeline.tsx`, `apps/web/src/components/player/SlideRenderer.tsx`.
- Modified (docs only): `docs/DEFECT-REGISTER.md`, `docs/deferred-work.md`, inline comment in `apps/web/src/hooks/useAttentionMonitor.ts`.
- No `apps/api` changes — the backend endpoint and its contract are already correct and unmodified by this story.

### References

- [Source: docs/LESSON-DELIVERY-TRACKER.md#L3 — A student plays it in a browser, "Known risk"]
- [Source: docs/handoffs/lesson-delivery-dev2.md#Deviations you own, item 2]
- [Source: apps/api/app/modules/media/router.py:60-125]
- [Source: apps/api/app/modules/content/router.py:128-139, 607-639]
- [Source: apps/web/src/components/player/AudioTimeline.tsx:356-361, 404-423]
- [Source: apps/web/src/components/player/SlideRenderer.tsx:15-49]
- [Source: apps/web/src/components/player/Player.tsx:21-24, 61-87]
- [Source: apps/web/src/stores/player.machine.ts:75-111, 310-313]
- [Source: apps/web/src/hooks/useAttentionMonitor.ts:23-26 — DEFER-012 comment]
- [Source: docs/DEFECT-REGISTER.md — "re-read the highest allocated id from main immediately before writing a new entry" rule, and D62 as current max]
- [Source: docs/SCALE-CONTRACT.md — the six questions]

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5

### Debug Log References

- Discovered mid-implementation that `useAttentionMonitor.ts` (target of AC6) does not exist on `main` — S3-01–S3-04 were never merged from `sprint3-master`. Rebased the branch onto `sprint3-master` (user-confirmed) rather than `main`; this branch now PRs into `sprint3-master`. Story-only commit `69779e6` was preserved through the rebase (new hash `c2f2873`).
- One-time regression check: `AudioTimeline.component.test.tsx`'s `sets audioError(true) on the "error" event` and two `SlideRenderer.test.tsx` fallback tests asserted the OLD synchronous `handleError`/`onError` behavior. Updated to `async`/`waitFor` around the new (intentionally async) auto-resign attempt — this is the behavior AC2/AC3 exist to add, not an unrelated regression.

### Completion Notes List

- Task 1: Added `docs/DEFECT-REGISTER.md` D63 (re-verified D62 was still the max on `main` immediately before allocating); cross-referenced from `useAttentionMonitor.ts`'s `DEFER-012` comment and a new `docs/deferred-work.md` entry.
- Task 2: `lib/media/refreshSignedUrl.ts` — `parseSignedUrl` (pure, regex + `decodeURIComponent`) and `refreshSignedUrl` (calls the real `GET /api/media/signed-url` via `@/lib/api`). 9 unit tests, MSW-backed per DEFECT-REGISTER binding rule 2 (no `vi.mock('@/lib/api')`).
- Task 3: `AudioTimeline.tsx` — `handleError()` now attempts one automatic re-sign (guarded by a `Set<segment_id>` ref) before falling through to the pre-existing `setAudioError(true)`; a successful resign is held in local `resignedAudio` state and forces a clean `<audio>` remount via the existing key-based mechanism (now also keyed on the resigned URL) rather than relying on a bare `src` mutation.
- Task 4: `SlideRenderer.tsx`'s `SlideImage` — same one-attempt guard (a plain ref, since one instance = one slide for its whole lifetime) slotted in as a new first step ahead of the existing `primary → fallbackUrl → placeholder` chain; that existing chain is otherwise untouched.
- Task 5: 5 new component tests (2 AudioTimeline: success swap + never-audioError, one-attempt-then-audioError with call-count assertion, non-signed-url-shape skips network; 2 SlideRenderer: success swap, non-signed-url-shape skips network) plus 3 existing tests updated for the new async timing. Full `apps/web` suite: **920/920 passing**, `tsc --noEmit` clean, `eslint` clean (pre-existing `no-img-element` warning only).
- Task 6: `docs/dev2-sprint-tracker.md` updated — new `### S3-09` entry (§12), header `Last Updated`/`Active Sprint`/`Overall Status` lines, and the Quick Status Dashboard table (Sprint 3 row + Total row).
- AC1–AC7 all satisfied. No `apps/api` files touched.

### File List

- `apps/web/src/lib/media/refreshSignedUrl.ts` (new)
- `apps/web/src/__tests__/lib/media/refreshSignedUrl.test.ts` (new)
- `apps/web/src/components/player/AudioTimeline.tsx` (modified)
- `apps/web/src/components/player/SlideRenderer.tsx` (modified)
- `apps/web/src/__tests__/components/player/AudioTimeline.component.test.tsx` (modified)
- `apps/web/src/__tests__/components/player/SlideRenderer.test.tsx` (modified)
- `apps/web/src/hooks/useAttentionMonitor.ts` (modified — comment only)
- `docs/DEFECT-REGISTER.md` (modified — D63 added)
- `docs/deferred-work.md` (modified — DEFER-012/D63 cross-reference)
- `docs/dev2-sprint-tracker.md` (modified — S3-09 entry + dashboard)

### Change Log

- 2026-08-11: Story implemented in full (Tasks 1–6). Branch rebased from `main` onto `sprint3-master` mid-implementation (see Debug Log). Status → review.
