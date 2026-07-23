---
baseline_commit: ca7906119b0a0ee7d58b80eb96ed7240d3a4836b
---

# Story 1.7: Wire Player to Real Lesson Content (Dev 2 counterpart to Story 1-6)

Status: ready-for-dev

## Story

As a student who just generated a real lesson from an uploaded PDF,
I want the player to actually load and display that lesson,
so that "This lesson could not be loaded" stops appearing for every real (non-mock) lesson, and Learner Mode's real pipeline output is actually reachable end-to-end.

**Source:** discovered 2026-07-23 during real end-to-end pipeline testing (a real PDF was uploaded, processed through the fixed content pipeline — segment_id sanitization + over-segmentation bugs both resolved by Dev 1 this week — and completed successfully). Clicking "go to lesson" showed a permanent error, traced to `apps/web/src/services/lesson.service.ts` still calling `apps/web/src/mocks/api/lesson.ts` instead of any real backend endpoint. Dev 1 then shipped **Story 1-6** (merged to `main`, commit `ca79061`) specifically to unblock this: `GET /api/content/lessons/{lesson_id}` now returns a real `content` field with every media URL pre-signed, and wrote `docs/dev2-lesson-content-wiring-handoff.md` as the primary technical brief for this story. This story is the direct continuation of that handoff — treat it as the authoritative source for scope and edge cases; do not re-derive independently.

## Acceptance Criteria

1. **AC-1 — real endpoint wired.** `lessonService.getLessonPackage` calls the real `GET /api/content/lessons/{id}` via the shared authenticated `api` client (`@/lib/api.ts`) — the same client `upload.service.ts` already uses. `apps/web/src/mocks/api/lesson.ts::getLessonPackageById` is no longer called from anywhere in the live player path.
2. **AC-2 — `useLesson` reads `.content`, not a bare package.** The real endpoint returns `LessonStatusResponse` (`{lesson_id, status, title, error, created_at, completed_at, content}`), not a bare `LessonPackage`. `useLesson` must read `response.data.content` for the package, and must also surface `status` and `error` in its return value (not just the resolved package) — a bare `content ?? null` throws away the information `PlayerLoader` needs to distinguish states.
3. **AC-3 — `status == "generating"` shows a distinct, non-error state.** Navigating to `/lesson/{id}` for a lesson that is still generating (bookmark, refresh, or back-button mid-generation — not just the `UploadFlow.tsx` poll-then-navigate path) must show a "still generating" state, not the permanent `LessonErrorState`. This state polls (SWR `refreshInterval`) until `status` flips to `"ready"` or `"failed"`.
4. **AC-4 — `status == "failed"` surfaces the real error.** Shows the actual `error` string from the response, not the generic "This lesson could not be loaded" message. `LessonErrorState` is reserved for the true fetch-failure case (network error, 404, unowned lesson) and the failed-generation case, each distinguishable if useful, but neither may swallow `error` when it's present.
5. **AC-5 — `status == "ready"` with `content` renders the player exactly as before.** No visual or behavioral regression to the existing happy-path render (`<Player lesson={...} />`) — this is purely a data-source swap for the success case.
6. **AC-6 — `AudioTimeline` degrades gracefully when `audio_url === ""`.** This is now a real, reachable value (per-asset signing failure, degrade-not-drop — see Story 1-6 AC-3) that the mock world never sent. Today `<audio src={segment.narration.audio_url}>` has no `onError` handling at all; an empty `src` must not crash the player or leave it in a silently-broken state indistinguishable from a loading state — at minimum, detect the empty value before render and skip attempting playback for that segment's audio (visual/UX treatment is this story's call; not silently hanging is the hard requirement).
7. **AC-7 — untouched by design, confirmed not modified:**
   - `lessonService.getLesson` and `lessonService.updateProgress` stay on mocks — neither has a real backend endpoint yet (dashboard-card shape and progress-tracking respectively).
   - `apps/web/src/hooks/useLessonSocket.ts`'s `case 'lesson_ready': break;` no-op is already correct (the WS push's `payload.lesson` is unsigned, forwarded raw from Redis pub/sub — REST is the only place `audio_url`/`image_url` should ever be read from) and must not be "fixed."
   - `upload.service.ts`'s `getLessonStatus()` already calls the real endpoint and needs no functional change.
8. **AC-8 — tests.** Cover: `status == "generating"` (non-error state, polling behavior), `status == "failed"` (real error surfaced), `status == "ready"` with `content` (happy path, no regression to existing `PlayerLoader`/`Player` tests), and `audio_url === ""` in `AudioTimeline` (graceful degrade, no crash/hang). `lesson.service.test.ts` (or equivalent) asserts the real endpoint is called with no mock fallback.

## Tasks / Subtasks

- [ ] Task 1 (AC: 1): `apps/web/src/services/lesson.service.ts` — point `getLessonPackage` at `api.get<LessonStatusResponse>(`content/lessons/${id}`)` via `@/lib/api.ts`; leave `getLesson`/`updateProgress` on `lessonApi` mocks, remove the stale `[DEV1-SPRINT2-PENDING]` comment block (the blocker it describes is resolved).
  - [ ] 1.1 Write failing tests first (RED) asserting the real `api.get` is called with the correct path, no `lessonApi.getLessonPackageById` call.
  - [ ] 1.2 Implement (GREEN).
- [ ] Task 2 (AC: 2): `apps/web/src/hooks/useLesson.ts` — change the SWR fetcher/return shape to expose `content`, `status`, and `error` distinctly (exact shape is this story's call — e.g. extend `UseLessonResult` with `status: LessonStatus | undefined` and `serverError: string | null`, being careful not to collide with SWR's own `error` field, which represents a *fetch* failure, not the backend's reported generation `error`).
  - [ ] 2.1 RED: a test asserting `useLesson` surfaces `status`/`error` from a `"generating"`/`"failed"` response, not just `null`.
  - [ ] 2.2 GREEN.
- [ ] Task 3 (AC: 3, 4, 5): `apps/web/src/components/player/PlayerLoader.tsx` — branch on the new `status`/`error` fields: `"generating"` → a distinct loading/waiting state (consider reusing `PlayerSkeleton` with different copy, or a new component — this story's call), with polling until terminal; `"failed"` → show the real `error` message; `"ready"` + `content` → unchanged `<Player lesson={content} />` render; genuine fetch failure (SWR `error`, 404/network) → existing `LessonErrorState`.
  - [ ] 3.1 RED: tests for all 4 branches (generating / failed-with-real-error / ready-happy-path-unchanged / fetch-error).
  - [ ] 3.2 GREEN.
- [ ] Task 4 (AC: 6): `apps/web/src/components/player/AudioTimeline.tsx` — handle `segment.narration.audio_url === ""` without crashing/hanging (e.g. skip rendering the `<audio>` `src` or gate playback), remove the stale `[DEV1-SPRINT2-PENDING]` comment block (S2-11/package_builder has shipped).
  - [ ] 4.1 RED: a test rendering a segment with `audio_url: ""` and asserting no crash and no attempted load of an invalid source.
  - [ ] 4.2 GREEN.
- [ ] Task 5 (AC: 7): Confirm (do not modify, add a comment/reference note only if genuinely useful) that `getLesson`/`updateProgress` in `lesson.service.ts`, and `useLessonSocket.ts`'s `lesson_ready` case, remain exactly as-is.
- [ ] Task 6 (AC: 8): Full `apps/web` suite green; `tsc --noEmit` clean; `eslint` clean on every touched file.
- [ ] Task 7: Tracker update — mark this item done in `docs/dev2-sprint-tracker.md` and `docs/master-tracker.md` (the "Lesson load from real API — BLOCKED" line item, Sprint 1 section) once merged.

## Dev Notes

### Current state of every file this story touches (read directly, not assumed)

- **`apps/web/src/services/lesson.service.ts`** (3 lines of substance): all 3 functions delegate to `lessonApi` from `../mocks/api`. Only `getLessonPackage` changes.
- **`apps/web/src/mocks/api/lesson.ts::getLessonPackageById`** (lines 71-79): looks up `lessonId` in the fixture `mockLessons` array; returns `createErrorResponse('Lesson not found')` (no throw) for anything not in that fixture — this is *why* every real (UUID) lesson_id currently fails: it was never going to be found in a hardcoded mock list.
- **`apps/web/src/hooks/useLesson.ts`** (current, full file):
  ```ts
  export function useLesson(lessonId: string): UseLessonResult {
    const { data, error, isLoading } = useSWR<LessonPackage | null>(
      lessonId ? `lesson:${lessonId}` : null,
      async () => {
        const response = await lessonService.getLessonPackage(lessonId);
        return response.data;   // mock shape: response.data IS the LessonPackage
      },
      { revalidateOnFocus: false },
    );
    return { lesson: data ?? null, isLoading, error };
  }
  ```
  `{ revalidateOnFocus: false }` is intentional (documented in-file) — refocusing the tab must not refetch mid-lesson, since the player treats any new object reference as a new lesson and resets its whole state machine. **Keep this.** Any polling added for the `"generating"` state should use SWR's `refreshInterval` (which is orthogonal to `revalidateOnFocus`), not remove this flag.
- **`apps/web/src/components/player/PlayerLoader.tsx`** (full file, 59 lines): `PlayerSkeleton` (loading UI), `LessonErrorState` (generic "This lesson could not be loaded" + return-to-dashboard link), and the gating logic:
  ```tsx
  export function PlayerLoader({ lessonId }: PlayerLoaderProps) {
    const { lesson, isLoading, error } = useLesson(lessonId);
    if (error) return <LessonErrorState />;
    if (isLoading) return <PlayerSkeleton />;
    if (!lesson) return <LessonErrorState />;   // ← the problem line: content:null on "generating" hits this
    return <Player lesson={lesson} />;
  }
  ```
- **`apps/web/src/components/player/AudioTimeline.tsx`**: `<audio key={segment.segment_id} ref={audioRef} src={segment.narration.audio_url} ...>` (line 154) — no `onError` handler anywhere in the file today. `handleLoadedMetadata`/`handleTimeUpdate`/`handleEnded` are all real-audio-event-driven; an empty `src` means these events simply never fire in a working way, and nothing currently detects or surfaces that. Also carries a stale `[DEV1-SPRINT2-PENDING]` comment block (lines 12-15) referencing "Story S2-11, not yet built" — that's shipped now (Dev 1's `package_builder_node`).
- **`apps/web/src/services/upload.service.ts`**: `getLessonStatus()` (confirmed, already implemented) calls `api.get<LessonStatusResponse>(`content/lessons/${lessonId}`).then((r) => r.data)` — this is the exact real endpoint and exact `api` client pattern Task 1 should mirror for `getLessonPackage`. Its own local `LessonStatusResponse` interface does not yet have a `content` field — optional/non-blocking to add for type accuracy; `UploadFlow.tsx` only reads `.status`/`.lesson_id`/`.error` from it today, so omitting it causes no behavior change either way. This story does not require touching this file, but may add the field if convenient.
- **`apps/web/src/lib/api.ts`**: the shared authenticated axios client — attaches the Supabase JWT via a request interceptor reading `supabase.auth.getSession()`. This is the *only* client to use; do not build a second auth path.
- **`apps/web/src/components/player/Player.tsx`**: `interface PlayerProps { lesson: LessonPackage }` — requires a non-null, fully-resolved package. `PlayerLoader` must keep gating on a resolved `content` before ever rendering `<Player>` — the new generating/failed states are additional branches *before* this render, not changes to `Player` itself.
- **`packages/shared/types/lesson.ts`** (frozen): `LessonPackage`, `LessonRecord` (`content: LessonPackage | null`). No changes needed or permitted here — Story 1-6 confirmed the backend Pydantic model already matches this exactly.

### What the real endpoint actually returns (confirmed via Story 1-6, not assumed)

```json
{
  "lesson_id": "...", "status": "ready", "title": "...", "error": null,
  "created_at": "...", "completed_at": "...",
  "content": { "lesson_id": "...", "book_id": "...", "chapter_id": "...", "created_at": "...",
    "metadata": {"...": "..."}, "segments": [{"...": "...", "narration": {"audio_url": "https://<real-signed-url>", "...": "..."}, "...": "..."}],
    "glossary": ["..."] }
}
```
`content` is `null` when `status` is `"generating"` or `"failed"` — same as it always has been; the only change is that it's now populated (with all URLs already resolved server-side) when `status == "ready"`. **Do not call `GET /api/media/signed-url` from the frontend** — Dev 1's handoff is explicit that endpoint #1 already resolves every URL; calling it ourselves would be redundant, unauthenticated-for-this-purpose extra work.

### What NOT to do

- Do NOT touch `packages/shared/types/lesson.ts` or any Pydantic/backend file — this is a pure frontend wiring story, backend is already done (Story 1-6, Story 3-6).
- Do NOT change `lessonService.getLesson` or `lessonService.updateProgress` — no real backend endpoint exists for either; they stay on mocks until their own future stories.
- Do NOT touch `useLessonSocket.ts`'s `lesson_ready` case — it is already correct; "fixing" it to read `payload.lesson` directly would introduce a real bug (unsigned URLs).
- Do NOT call `/api/media/signed-url` from the frontend — URLs already arrive pre-resolved from `GET /lessons/{id}`.
- Do NOT remove or weaken `useLesson`'s `revalidateOnFocus: false` — it's an intentional, documented fix for a real prior bug (tab refocus resetting player state mid-lesson).
- Do NOT add a workaround/parallel mock path for anything this story unblocks — the whole point is retiring the stale mock dependency for `getLessonPackage`.

### Known limitation, not in scope

Signed URLs expire after 1 hour (`expires_in` defaults to 3600s server-side). A single lesson session realistically won't run that long, and `revalidateOnFocus: false` means there's no mechanism today that would re-fetch fresh URLs if a player tab is left open-but-idle past that window. This is a disclosed limitation from Dev 1's handoff, not something this story needs to solve — do not build expiry-refresh logic as part of this work.

### Project Structure Notes

Touches only: `apps/web/src/services/lesson.service.ts`, `apps/web/src/hooks/useLesson.ts`, `apps/web/src/components/player/PlayerLoader.tsx`, `apps/web/src/components/player/AudioTimeline.tsx`, and their test files. Optionally `apps/web/src/services/upload.service.ts` (non-behavioral type addition only). No new dependencies, no shared-contract changes, no backend touches.

### Testing standards

Vitest + `@testing-library/react`, matching this codebase's existing patterns in `apps/web/src/__tests__/**` — `vi.hoisted`/`vi.mock` for service-layer mocking (mock `@/lib/api`'s `get`, the same pattern `upload.service.test.ts` already uses), `fireEvent`/`act`/`waitFor` over `userEvent` where fake timers or polling intervals are involved (established preference this session, avoids timer/microtask deadlocks). Do not introduce a new mocking approach.

### References

- [Source: docs/dev2-lesson-content-wiring-handoff.md] — primary technical brief, written by Dev 1 specifically for this story
- [Source: docs/stories/1-6-lesson-content-endpoint.md] — the backend story this depends on (merged, `main`, commit `ca79061`)
- [Source: packages/shared/types/lesson.ts] — frozen `LessonPackage`/`LessonRecord` types, unchanged by this story
- [Source: apps/web/src/services/lesson.service.ts, apps/web/src/hooks/useLesson.ts, apps/web/src/components/player/PlayerLoader.tsx, apps/web/src/components/player/AudioTimeline.tsx, apps/web/src/services/upload.service.ts, apps/web/src/lib/api.ts, apps/web/src/mocks/api/lesson.ts] — all read in full this session, current state documented above

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-23 | Story created — Dev 2 counterpart to Dev 1's Story 1-6, per Dev 1's own handoff doc. Branch `sprint1/s1-7-wire-real-lesson-content` off `main`. | Dev 2 |

## Dev Agent Record

_Pending implementation._
