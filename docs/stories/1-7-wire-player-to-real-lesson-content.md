---
baseline_commit: ca7906119b0a0ee7d58b80eb96ed7240d3a4836b
---

# Story 1.7: Wire Player to Real Lesson Content (Dev 2 counterpart to Story 1-6)

Status: done

## Story

As a student who just generated a real lesson from an uploaded PDF,
I want the player to actually load and display that lesson,
so that "This lesson could not be loaded" stops appearing for every real (non-mock) lesson, and Learner Mode's real pipeline output is actually reachable end-to-end.

**Source:** discovered 2026-07-23 during real end-to-end pipeline testing (a real PDF was uploaded, processed through the fixed content pipeline — segment_id sanitization + over-segmentation bugs both resolved by Dev 1 this week — and completed successfully). Clicking "go to lesson" showed a permanent error, traced to `apps/web/src/services/lesson.service.ts` still calling `apps/web/src/mocks/api/lesson.ts` instead of any real backend endpoint. Dev 1 then shipped **Story 1-6** (merged to `main`, commit `ca79061`) specifically to unblock this: `GET /api/content/lessons/{lesson_id}` now returns a real `content` field with every media URL pre-signed, and wrote `docs/dev2-lesson-content-wiring-handoff.md` as the primary technical brief for this story. This story is the direct continuation of that handoff — treat it as the authoritative source for scope and edge cases; do not re-derive independently.

## Acceptance Criteria

1. **AC-1 — real endpoint wired.** `lessonService.getLessonPackage` calls the real `GET /api/content/lessons/{id}` via the shared authenticated `api` client (`@/lib/api.ts`) — the same client `upload.service.ts` already uses. `apps/web/src/mocks/api/lesson.ts::getLessonPackageById` is no longer called from anywhere in the live player path.
2. **AC-2 — `useLesson` reads `.content`, not a bare package.** The real endpoint returns `LessonStatusResponse` (`{lesson_id, status, title, error, created_at, completed_at, content}`), not a bare `LessonPackage`. `useLesson` must read `response.data.content` for the package, and must also surface `status` and `error` in its return value (not just the resolved package) — a bare `content ?? null` throws away the information `PlayerLoader` needs to distinguish states.
3. **AC-3 — `status == "running"` (or `"queued"`) shows a distinct, non-error state.** Navigating to `/lesson/{id}` for a lesson that is still generating (`status == "running"`, or `"queued"` defensively — bookmark, refresh, or back-button mid-generation, not just the `UploadFlow.tsx` poll-then-navigate path) must show a "still generating" state, not the permanent `LessonErrorState`. This state polls (SWR `refreshInterval`) until `status` flips to `"ready"` or `"failed"`. **Note the wire value is `"running"`, NOT `"generating"`** — the DB column value is `"generating"` (matches `packages/shared/types/lesson.ts`'s `LessonRecord.status`), but `content/router.py`'s `_map_status()` translates it to `"running"` for the actual API response (`_STATUS_MAP = {"generating": "running", "ready": "ready", "failed": "failed"}`, default `"queued"`) — this is the exact same value space `upload.service.ts`'s existing `LessonStatus` type and `UploadFlow.tsx`'s polling logic (`!== 'queued' && !== 'running'`) already use. Match that established convention exactly; do not introduce a second, incompatible status vocabulary.
4. **AC-4 — `status == "failed"` surfaces the real error.** Shows the actual `error` string from the response, not the generic "This lesson could not be loaded" message. `LessonErrorState` is reserved for the true fetch-failure case (network error, 404, unowned lesson) and the failed-generation case, each distinguishable if useful, but neither may swallow `error` when it's present.
5. **AC-5 — `status == "ready"` with `content` renders the player exactly as before.** No visual or behavioral regression to the existing happy-path render (`<Player lesson={...} />`) — this is purely a data-source swap for the success case.
6. **AC-6 — `AudioTimeline` degrades gracefully when `audio_url === ""`.** This is now a real, reachable value (per-asset signing failure, degrade-not-drop — see Story 1-6 AC-3) that the mock world never sent. Today `<audio src={segment.narration.audio_url}>` has no `onError` handling at all; an empty `src` must not crash the player or leave it in a silently-broken state indistinguishable from a loading state — at minimum, detect the empty value before render and skip attempting playback for that segment's audio (visual/UX treatment is this story's call; not silently hanging is the hard requirement).
7. **AC-7 — untouched by design, confirmed not modified:**
   - `lessonService.getLesson` and `lessonService.updateProgress` stay on mocks — neither has a real backend endpoint yet (dashboard-card shape and progress-tracking respectively).
   - `apps/web/src/hooks/useLessonSocket.ts`'s `case 'lesson_ready': break;` no-op is already correct (the WS push's `payload.lesson` is unsigned, forwarded raw from Redis pub/sub — REST is the only place `audio_url`/`image_url` should ever be read from) and must not be "fixed."
   - `upload.service.ts`'s `getLessonStatus()` already calls the real endpoint and needs no functional change.
8. **AC-8 — tests.** Cover: `status == "running"` (or `"queued"`) (non-error state, polling behavior), `status == "failed"` (real error surfaced), `status == "ready"` with `content` (happy path, no regression to existing `PlayerLoader`/`Player` tests), and `audio_url === ""` in `AudioTimeline` (graceful degrade, no crash/hang). `lesson.service.test.ts` (or equivalent) asserts the real endpoint is called with no mock fallback.

## Tasks / Subtasks

- [x] Task 1 (AC: 1): `apps/web/src/services/lesson.service.ts` — point `getLessonPackage` at `api.get<LessonStatusResponse>(`content/lessons/${id}`)` via `@/lib/api.ts`; leave `getLesson`/`updateProgress` on `lessonApi` mocks, remove the stale `[DEV1-SPRINT2-PENDING]` comment block (the blocker it describes is resolved).
  - [x] 1.1 Write failing tests first (RED) asserting the real `api.get` is called with the correct path, no `lessonApi.getLessonPackageById` call.
  - [x] 1.2 Implement (GREEN).
- [x] Task 2 (AC: 2): `apps/web/src/hooks/useLesson.ts` — change the SWR fetcher/return shape to expose `content`, `status`, and `error` distinctly (extended `UseLessonResult` with `status: LessonStatus | undefined` and `serverError: string | null`, keeping SWR's own `error` field as the fetch-failure signal, distinct from the backend's reported generation `error`/`serverError`).
  - [x] 2.1 RED: a test asserting `useLesson` surfaces `status`/`error` from a `"running"`/`"failed"` response, not just `null`.
  - [x] 2.2 GREEN.
- [x] Task 3 (AC: 3, 4, 5): `apps/web/src/components/player/PlayerLoader.tsx` — branch on the new `status`/`serverError` fields: `"running"`/`"queued"` → new `LessonGeneratingState` component, polling until terminal via `useLesson`'s `refreshInterval`; `"failed"` → `LessonErrorState` shows the real `serverError` message; `"ready"` + `content` → unchanged `<Player lesson={content} />` render; genuine fetch failure (SWR `error`, 404/network) → existing generic `LessonErrorState`.
  - [x] 3.1 RED: tests for all branches (running / queued / failed-with-real-error / ready-happy-path-unchanged / fetch-error / loading).
  - [x] 3.2 GREEN.
- [x] Task 4 (AC: 6): `apps/web/src/components/player/AudioTimeline.tsx` — handle `segment.narration.audio_url === ""` without crashing/hanging (omit the `<audio>` `src` attribute entirely and skip the play/pause effect when there's no audio), removed the stale `[DEV1-SPRINT2-PENDING]` comment block (S2-11/package_builder has shipped).
  - [x] 4.1 RED: a test rendering a segment with `audio_url: ""` and asserting no crash and no attempted load of an invalid source.
  - [x] 4.2 GREEN.
- [x] Task 5 (AC: 7): Confirmed (not modified) — `getLesson`/`updateProgress` in `lesson.service.ts` still delegate to `lessonApi` mocks (regression-tested); `useLessonSocket.ts`'s `lesson_ready` case is untouched (not opened by this story's diff at all).
- [x] Task 6 (AC: 8): Full `apps/web` suite green (339/339, 42 files); `tsc --noEmit` clean; `eslint` clean on every touched file (0 new warnings — 2 pre-existing warnings in `PlayerLoader.test.tsx`'s unrelated `next/dynamic` mock stub, not introduced by this story).
- [x] Task 7: Tracker update — `docs/master-tracker.md`'s "Lesson load from real API" line checked off; `docs/dev2-sprint-tracker.md` gained a dated cross-team note referencing this story and Story 1-6.

### Review Findings

5-agent adversarial review (Blind Hunter, Edge Case Hunter, Acceptance Auditor) run against branch `sprint1/s1-7-wire-real-lesson-content` vs `main`, 2026-07-23.

- [x] [Review][Patch] `AudioTimeline.tsx`'s `audio_url === ''` degrade prevents a broken player but doesn't prevent a *stuck* one — since `<audio>` never has a `src`, `timeupdate`/`ended` never fire, so `processTimeUpdate`'s quiz-boundary check and `handleEnded`'s advance/quiz logic never run; a student lands on that segment and the lesson never progresses. This is the AC-6 "not silently hanging" requirement, not yet met — 3-way corroborated by Blind Hunter, Edge Case Hunter, and the Acceptance Auditor independently. [apps/web/src/components/player/AudioTimeline.tsx:79-85,114-158] (blind+edge+auditor)
- [x] [Review][Patch] `PlayerLoader.tsx` checks the generic SWR `error` before the `status`-derived branches — a single transient revalidation failure during polling (SWR retains the last good `data`/`status` across a failed poll by default) flashes a lesson that's still genuinely `running`/`queued` to the permanent error page instead of staying on "still generating." [apps/web/src/components/player/PlayerLoader.tsx:67] (blind+edge)
- [x] [Review][Patch] `PlayerLoader.tsx` renders `<Player>` on bare `lesson` truthiness, not gated on `status === 'ready'` — an unrecognized/future status value with a non-null `content` would render the player unconditionally. Not reachable via the real backend's own contract (content is only ever populated atomically with `status === 'ready'`, per Story 1-6), but cheap to guard defensively. [apps/web/src/components/player/PlayerLoader.tsx:67-74] (edge)
- [x] [Review][Patch] `useLesson.ts`'s `POLL_INTERVAL_MS` (3000ms) doesn't match `UploadFlow.tsx`'s existing, already-shipped real-polling-interval convention (5000ms) — align for consistency. Backoff/jitter beyond a flat interval was also raised but dismissed: matches this codebase's existing `UploadFlow.tsx` polling precedent exactly, not a new anti-pattern. [apps/web/src/hooks/useLesson.ts] (blind)
- [x] [Review][Patch] No test proves a backend contract violation (`status: 'ready'` with `content: null`) degrades to the generic error state rather than crashing — add one regression test. [apps/web/src/__tests__/components/player/PlayerLoader.test.tsx] (blind)
- [x] [Review][Defer] No ceiling on how long `PlayerLoader` will keep polling a `running`/`queued` lesson — a stuck backend job polls forever with only a spinner, no "this is taking longer than usual" fallback. Real gap, but the exact policy (timeout duration, UX/copy) is a product decision outside this story's stated scope — disclosed here as a known limitation, matching this same story's existing signed-URL-expiry disclosure, rather than either building it unprompted or blocking on a decision for a non-blocking gap. [apps/web/src/components/player/PlayerLoader.tsx] (blind+edge)

**Dismissed as noise/false-positive (9):** "endpoint path documentation mismatch" — refuted, the comment's shorthand ("GET /lessons/{id}") matches the FastAPI route's own literal path suffix before its `/content` prefix mount, not a real inconsistency. No runtime schema validation of the API response — pre-existing, codebase-wide convention (every service in this codebase trusts TS types only), not introduced or worsened here. Pending-seek effect not audited for `hasAudio` — confirmed a harmless no-op on a src-less `<audio>` in both real browsers and jsdom. `refreshIntervalFor` "only tests wiring not behavior" — matches this suite's established fully-mocked-SWR unit-test convention throughout `useLesson.test.ts`. Module cohesion (`LessonStatus`/`LessonStatusResponse` living in `upload.service.ts`) — the story's own Dev Notes explicitly chose this reuse to avoid a second hand-duplicated interface; moving it is unrequested refactoring beyond scope. "Cross-team coordination comments deleted, not resolved" — false; refuted by full context the Blind Hunter didn't have access to (Dev 1's Story 1-6 + explicit handoff doc IS the resolution). Test-suite churn (no fixture/override factory for `mockUseLesson`) — stylistic preference, a new test-fixture pattern would be scope creep. `lesson.service.ts`'s `lessonId` not URL-encoded — pre-existing pattern, identical to the sibling `upload.service.ts::getLessonStatus` this story was explicitly told to mirror; fixing only one side would be inconsistent and fixing both is out of scope here. `onLoadedMetadata` never firing on a no-audio segment (stale duration) — same root cause as the first patch above; once that auto-advances the segment, the stale value's window shrinks to negligible and isn't worth a separate fix.



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
| 2026-07-23 | Corrected AC-3/Dev Notes during implementation: the wire status value is `"running"` (and `"queued"`), NOT `"generating"` as originally drafted — `content/router.py`'s `_map_status()` translates the DB column value `"generating"` to the wire value `"running"`; matched `upload.service.ts`'s/`UploadFlow.tsx`'s existing convention exactly rather than inventing a second status vocabulary. | Dev 2 |
| 2026-07-23 | All 7 tasks implemented in strict RED→GREEN order. 8 new/updated tests across 4 files; full `apps/web` suite 339/339 passing (42 files); `tsc --noEmit` clean; `eslint` clean (0 new warnings). Tracker updated. Story marked `review`. | Dev 2 |
| 2026-07-23 | 5-agent adversarial review run against `sprint1/s1-7-wire-real-lesson-content` vs `main`; 5 patches applied (stuck-segment fix, transient-poll-error reorder, ready-gate tightening, poll-interval alignment, contract-violation test), 1 deferred (polling ceiling, disclosed), 9 dismissed. Full suite 342/342 passing, `tsc --noEmit` and `eslint` clean; story marked `done`. | Dev 2 |

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (claude-sonnet-5)

### Debug Log References

- `npx vitest run src/__tests__/services/lesson.service.test.ts` — RED: 3/5 failed (new file didn't exist as a real-endpoint test yet; `getLessonPackage` still called the mock, so `getMock` was never invoked and `getLessonPackageByIdMock` was). GREEN after implementation: 5/5 passed.
- `npx vitest run src/__tests__/hooks/useLesson.test.ts` — RED: 4/6 failed (`result.current.status`/`serverError` were `undefined` since the hook didn't expose them yet; `refreshInterval` wasn't a function since the option didn't exist). GREEN after implementation: 6/6 passed.
- `npx vitest run src/__tests__/components/player/PlayerLoader.test.tsx` — RED: 3/9 failed (the 3 new running/queued/failed-message tests; confirmed the 6 pre-existing tests passed unmodified both before and after, since none of them set `status`, exercising the intentionally-unchanged fallback path). GREEN after implementation: 9/9 passed.
- `npx vitest run src/__tests__/components/player/AudioTimeline.component.test.tsx` — RED: 1/5 failed (`playMock` was called once even with `audio_url: ''`, since nothing gated playback on it yet). GREEN after implementation: 5/5 passed.
- Full suite: `npx vitest run` — 339/339 passing across 42 files (this branch is off `main` pre-`sprint2-master`/`feature-learner-mode` merge, so `UploadFlow.test.tsx` shows its pre-Learner-Mode 9-test baseline here, not the 16-test count from those still-unmerged branches — expected, not a regression).
- `npx tsc --noEmit -p tsconfig.json` — clean.
- `npx eslint` on every touched file — 0 errors; 2 pre-existing warnings in `PlayerLoader.test.tsx`'s unrelated `next/dynamic` mock stub (unused `importFn`/`opts` params), present before this story's diff, not introduced by it.
- No HALT conditions hit — no new dependencies, no ambiguous requirements, no 3-consecutive-failure loop. One self-caught correction during implementation (see Change Log): the story's own AC-3 draft used the wrong wire status value (`"generating"` instead of `"running"`), caught by reading `content/router.py`'s actual `_map_status()` before writing `useLesson.ts`, not after shipping a dead branch.

**Review Round (2026-07-23):** 5 patches applied (3-way corroborated stuck-segment fix, transient-poll-error branch reorder, ready-gate tightening, poll-interval alignment, contract-violation regression test), 1 deferred (polling ceiling — disclosed as a known limitation, matching this story's own signed-URL-expiry precedent), 9 dismissed as noise/false-positive/out-of-scope. All 5 patches verified via RED→GREEN: the stuck-segment fix's RED confirmed `status` stayed `'PLAYING'` forever without the fix (`handleEnded()` never invoked); the transient-poll-error fix's RED confirmed the old branch order rendered the permanent error page instead of the generating state. Full `apps/web` suite: 342/342 passing across 42 files after all 5 patches (up from this story's pre-review 339); `tsc --noEmit` clean; `eslint` clean (0 new warnings) on every file touched this round.

### Completion Notes List

- `lesson.service.ts`: `getLessonPackage` now calls `api.get<LessonStatusResponse>(`content/lessons/${id}`)` via the shared authenticated client — same client/pattern `upload.service.ts` already used. `getLesson`/`updateProgress` untouched (still mock-backed, regression-tested). Removed the stale `[DEV1-SPRINT2-PENDING]` comment block.
- `upload.service.ts`: added `content: LessonPackage | null` to the shared `LessonStatusResponse` interface (both `lesson.service.ts` and `useLesson.ts` import this type now, avoiding a second hand-duplicated interface) — non-behavioral for `UploadFlow.tsx`, which only reads `.status`/`.lesson_id`/`.error`.
- `useLesson.ts`: SWR now fetches the whole `LessonStatusResponse`, not a bare package. Returns `lesson: data?.content ?? null`, `status: data?.status`, `serverError: data?.error ?? null`, alongside the existing `isLoading`/`error` (SWR fetch-failure signal, kept distinct from `serverError`). Added `refreshInterval` (3s) that's active only while `status` is `'queued'`/`'running'`, `0` (disabled) once terminal — `revalidateOnFocus: false` preserved unchanged.
- `PlayerLoader.tsx`: added `LessonGeneratingState` (new, spinner + "still generating" copy) for `status === 'running' || status === 'queued'`; `LessonErrorState` gained an optional `message` prop, used to surface the real `serverError` on `status === 'failed'` instead of the generic copy. The pre-existing `error`/`isLoading`/`!lesson` branches and their ordering are unchanged — verified by the 6 pre-existing tests passing with zero modification.
- `AudioTimeline.tsx`: derived `hasAudio = Boolean(segment?.narration.audio_url)`; the `<audio>` element's `src` is now `undefined` (attribute omitted entirely) rather than `""` when there's no audio, and the play/pause effect's guard clause returns early when `!hasAudio`, added to its dependency array. Removed the stale `[DEV1-SPRINT2-PENDING]` comment block.
- No changes to `lesson.service.ts`'s `getLesson`/`updateProgress`, `useLessonSocket.ts`, `Player.tsx`, or any `packages/shared` frozen contract.
- Tracker: `docs/master-tracker.md`'s "Lesson load from real API" line checked off; `docs/dev2-sprint-tracker.md` gained a dated cross-team note. Sprint 2's stale dashboard numbers in `docs/dev2-sprint-tracker.md` were intentionally left untouched — they reconcile whenever `sprint2-master`/`feature-learner-mode` (still separate, unmerged branches) land on `main`, which is outside this Sprint-1-scoped story.

**Review Round completion notes:**
- `AudioTimeline.tsx`: the play/pause effect now short-circuits when `!hasAudio` — if `status === 'PLAYING'`, it calls `handleEnded()` (hoisted function declaration, safe to call before its textual definition) immediately instead of waiting for an `ended` event that can never fire on a src-less `<audio>` element. Reuses `handleEnded`'s existing, already-tested advance/quiz logic rather than duplicating it.
- `PlayerLoader.tsx`: reordered so `status`-derived branches (`running`/`queued`/`failed`/`ready`) are checked before the generic SWR `error`/`isLoading` fallbacks — SWR retains the last good `data` (and therefore `status`) across a failed background revalidation, so this ordering keeps a still-generating lesson on the generating state through a transient poll blip instead of flashing to the permanent error page. The `ready` render is now gated on `status === 'ready' && lesson`, not bare `lesson` truthiness (defensive-only; not reachable via the real backend's own atomic status/content contract).
- `useLesson.ts`: `POLL_INTERVAL_MS` changed from 3000 to 5000 to match `UploadFlow.tsx`'s established polling cadence exactly.
- `PlayerLoader.test.tsx`: 2 new tests (transient-poll-error-during-running regression; ready+null-content contract-violation regression).
- `AudioTimeline.component.test.tsx`: 1 new test (no-audio segment auto-advances/quizzes rather than freezing).
- Deferred (not fixed): the polling-ceiling gap, documented in `docs/stories/deferred-work.md` and in this story's own Review Findings above.

### File List

**Files MODIFIED:**
- `apps/web/src/services/lesson.service.ts` — `getLessonPackage` now calls the real endpoint; stale comment removed
- `apps/web/src/services/upload.service.ts` — added `content: LessonPackage | null` to `LessonStatusResponse`
- `apps/web/src/hooks/useLesson.ts` — reads `.content`, surfaces `status`/`serverError`, adds `refreshInterval` polling
- `apps/web/src/components/player/PlayerLoader.tsx` — new `LessonGeneratingState`, `LessonErrorState` gained a `message` prop, new running/queued/failed branches
- `apps/web/src/components/player/AudioTimeline.tsx` — graceful `audio_url === ''` handling; stale comment removed
- `apps/web/src/__tests__/hooks/useLesson.test.ts` — 4 new tests (ready/running/failed/refreshInterval)
- `apps/web/src/__tests__/components/player/PlayerLoader.test.tsx` — 3 new tests (running, queued, failed-message); 5 pre-existing tests updated only to add the new `status`/`serverError` fields to their mock return values (no behavioral change)
- `apps/web/src/__tests__/components/player/AudioTimeline.component.test.tsx` — 1 new test (empty `audio_url` degrade)
- `docs/master-tracker.md` — "Lesson load from real API" line checked off
- `docs/dev2-sprint-tracker.md` — dated cross-team note added

**Files CREATED:**
- `apps/web/src/__tests__/services/lesson.service.test.ts` — new, 5 tests (real endpoint call, no mock fallback, rejection propagation, `getLesson`/`updateProgress` regression)
- `docs/stories/1-7-wire-player-to-real-lesson-content.md` — this file

**Files MODIFIED (Review Round):**
- `apps/web/src/components/player/AudioTimeline.tsx` — no-audio segment now drives `handleEnded()` immediately instead of hanging forever
- `apps/web/src/components/player/PlayerLoader.tsx` — status-derived branches reordered before the generic error fallback; ready-render gated on `status === 'ready' && lesson`
- `apps/web/src/hooks/useLesson.ts` — `POLL_INTERVAL_MS` aligned to 5000 (matches `UploadFlow.tsx`)
- `apps/web/src/__tests__/components/player/AudioTimeline.component.test.tsx` — 1 new regression test
- `apps/web/src/__tests__/components/player/PlayerLoader.test.tsx` — 2 new regression tests
- `docs/stories/deferred-work.md` — 1 new deferred entry (polling ceiling)
