---
baseline_commit: da7dcfdd248cc4792bbab3b50e555116e7064774
---

# Story 2.26: Audio Buffering + Playback-Error Retry States

Status: ready-for-dev

## Story

As a student,
I want the player to show me when narration audio is buffering or has failed to load, with a way to retry,
so that a slow network or a transient asset failure doesn't leave me staring at a frozen slide with no explanation or way out.

**Source:** PR #71 (`sprint1-master`, opened 2026-07-08 by Dev 2 as "S1-11 player loading/error states") sat open for ~3 weeks and diverged too far from `main` to merge cleanly — investigated and closed (see PR #71's closing comment). It added real, still-missing functionality (`isBuffering`/`audioError`/`retryAudio()` state) to `player.machine.ts`, but its `PlayerLoader.tsx`/`AudioTimeline.tsx` changes predate the real backend integration (Stories 1-6/1-7/S2-06) and would have regressed the current, better `status`-field-based loading/error handling if merged as-is. This story re-implements only the still-missing piece — mid-playback audio buffering/stall and playback-error retry — against the current player architecture, instead of reviving the stale branch.

**Current state, confirmed by reading every file this story touches:**

- `apps/web/src/stores/player.machine.ts` has no buffering/error state at all today. It has `status`, `audioDurationMs`, `seekRequestMs`, `playbackRate`, `wsSendControl`, etc. — nothing tracks whether the `<audio>` element is stalled or has thrown a load/decode error mid-segment.
- `apps/web/src/components/player/AudioTimeline.tsx` renders a single `sr-only` (visually hidden) `<audio>` element keyed on `segment.segment_id`, with `onLoadedMetadata`/`onTimeUpdate`/`onEnded` handlers. It has **no** `onWaiting`/`onPlaying`/`onError` handlers today. A `hasAudio` check already exists and is load-bearing: when a segment's `narration.audio_url` is `""` (a real, reachable per-asset signing-failure value from Story 1-6's degrade-not-drop design), the effect immediately calls `handleEnded()` instead of ever attempting to load `<audio>` — this is a distinct, already-correct, already-tested fallback path and **must not** be confused with a genuine mid-playback error on an audio element that *did* have a real URL.
- `apps/web/src/components/player/Player.tsx` renders `<AudioTimeline />` (hidden) plus the visible slide area, quiz/teach-back overlays, and the `ENDED` screen — there is currently no buffering spinner or playback-error affordance anywhere in this tree.
- None of `AudioTimeline`, `Player`, or `player.machine` reference `isBuffering`/`audioError`/`retryAudio` today (confirmed via repo-wide grep) — this is 100% new functionality, not a regression fix.

## Acceptance Criteria

1. **AC-1** — `player.machine.ts` gains `isBuffering: boolean` (default `false`), `audioError: boolean` (default `false`), and `audioRetryCount: number` (default `0`) state, plus `setBuffering(b: boolean)`, `setAudioError(b: boolean)`, and `retryAudio()` actions. `retryAudio()` sets `audioError: false` and increments `audioRetryCount`. All three reset to their defaults in `loadLesson()` (new lesson) and in `advanceSegment()` (new segment) — a stall/error on segment N must not leak into segment N+1.
2. **AC-2** — `AudioTimeline.tsx`'s `<audio>` element gains `onWaiting` (→ `setBuffering(true)`), `onPlaying` and `onCanPlay` (→ `setBuffering(false)`), and `onError` (→ `setAudioError(true)`, only reachable when `hasAudio` is `true` — the existing `hasAudio === false` degrade-to-`handleEnded()` path is untouched and takes priority, per the Dev Notes warning above).
3. **AC-3** — The `<audio>` element's `key` includes `audioRetryCount` (e.g. `` `${segment.segment_id}-${audioRetryCount}` ``) so calling `retryAudio()` forces React to remount the element and re-attempt loading the same `src` from scratch, rather than relying on the browser to retry a failed load on its own.
4. **AC-4** — `Player.tsx` renders a buffering indicator (small centered spinner overlay, non-blocking, only visible when `isBuffering && status === 'PLAYING'`) and a playback-error state (message + a "Retry" button calling `retryAudio()`, visible when `audioError` regardless of `status`) layered over the slide area, in the same z-index tier as `CheckingInTransition`. Both are purely additive — they must not affect `QUIZ`/`TEACH_BACK`/`ENDED` overlay rendering or hide the tier badge.
5. **AC-5** — No regression to the existing `hasAudio === false` per-asset degrade path (Story 1-6/1-7): a segment with an empty `audio_url` must continue to skip straight to `handleEnded()` without ever setting `audioError` or `isBuffering`.
6. **AC-6** — Tests: `player.machine.test.ts` covers the 3 new state fields, all 3 new actions, and the reset-on-`loadLesson`/`advanceSegment` behavior. `AudioTimeline.test.ts`/`AudioTimeline.component.test.tsx` cover `onWaiting`/`onPlaying`/`onCanPlay`/`onError` wiring and the retry-count-in-key behavior. `Player.test.tsx` covers both new UI states rendering/not-rendering under the right conditions.
7. **AC-7** — No regressions: full `apps/web` suite green, `tsc --noEmit` clean, `eslint` clean on every touched file.

## Tasks / Subtasks

- [ ] Task 1 (AC: 1, 6): Add `isBuffering`/`audioError`/`audioRetryCount` state + `setBuffering`/`setAudioError`/`retryAudio` actions to `player.machine.ts`, with resets wired into `loadLesson`/`advanceSegment`.
  - [ ] 1.1 RED: write failing tests for initial defaults, each action, and the two reset points.
  - [ ] 1.2 GREEN: implement.
- [ ] Task 2 (AC: 2, 3, 5, 6): Wire `onWaiting`/`onPlaying`/`onCanPlay`/`onError` on `AudioTimeline.tsx`'s `<audio>` element; extend the element `key` with `audioRetryCount`.
  - [ ] 2.1 RED: write failing tests asserting the handlers call the right store actions, that `onError` is not wired to fire when `hasAudio` is false, and that the key changes when `audioRetryCount` changes.
  - [ ] 2.2 GREEN: implement.
- [ ] Task 3 (AC: 4, 6): Add the buffering spinner overlay and playback-error-with-retry UI to `Player.tsx`.
  - [ ] 3.1 RED: write failing tests for both states' visibility conditions.
  - [ ] 3.2 GREEN: implement.
- [ ] Task 4 (AC: 7): Full `apps/web` suite green; `tsc --noEmit` clean; `eslint` clean on every touched file.

## Dev Notes

### What NOT to do

- Do NOT resurrect PR #71's `PlayerLoader.tsx` changes (`isValidLessonPackage()` type-guard, `LessonParseErrorState`) — that problem is already solved better by the current `status`-field branching in `PlayerLoader.tsx`, which this story does not touch at all.
- Do NOT let `onError` fire `setAudioError(true)` when `hasAudio` is `false` — there is no `src` in that case, so no `<audio>` element load is even attempted; the existing immediate-`handleEnded()` fallback already handles it correctly and takes priority.
- Do NOT wire `retryAudio()` to fire a WebSocket message or backend call — this is a purely client-side "try loading this same URL again" affordance, no `wsSendControl` involvement.

### Testing standards

Vitest + Testing Library, matching existing conventions in `apps/web/src/__tests__/stores/player.machine.test.ts`, `apps/web/src/__tests__/components/player/AudioTimeline.test.ts` (handler-level, calls `processTimeUpdate`/exported handlers directly where existing tests already do this), `AudioTimeline.component.test.tsx` (render-level), and `Player.test.tsx`.

### References

- [Source: PR #71 (closed) — `sprint1-master`] — origin of the `isBuffering`/`audioError`/`audioRetryCount` concept; re-implemented fresh here against current `main`, not merged.
- [Source: apps/web/src/components/player/AudioTimeline.tsx] — current `hasAudio` degrade path this story must not regress.
- [Source: docs/stories/1-7-wire-player-to-real-lesson-content.md] — established the `hasAudio`/empty-`audio_url` degrade-not-drop precedent this story builds alongside, not over.

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-27 | Story created after closing stale PR #71 — re-scoping its still-valuable audio buffering/error-retry feature as fresh work against current `main` instead of a risky manual merge. Branch `sprint2/s2-26-audio-buffer-retry` off `main`. | Dev 2 |
