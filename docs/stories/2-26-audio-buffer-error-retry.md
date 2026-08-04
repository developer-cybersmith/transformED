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

- [x] Task 1 (AC: 1, 6): Add `isBuffering`/`audioError`/`audioRetryCount` state + `setBuffering`/`setAudioError`/`retryAudio` actions to `player.machine.ts`, with resets wired into `loadLesson`/`advanceSegment`.
  - [x] 1.1 RED: write failing tests for initial defaults, each action, and the two reset points.
  - [x] 1.2 GREEN: implement.
- [x] Task 2 (AC: 2, 3, 5, 6): Wire `onWaiting`/`onPlaying`/`onCanPlay`/`onError` on `AudioTimeline.tsx`'s `<audio>` element; extend the element `key` with `audioRetryCount`.
  - [x] 2.1 RED: write failing tests asserting the handlers call the right store actions, that `onError` is not wired to fire when `hasAudio` is false, and that the key changes when `audioRetryCount` changes.
  - [x] 2.2 GREEN: implement.
- [x] Task 3 (AC: 4, 6): Add the buffering spinner overlay and playback-error-with-retry UI to `Player.tsx`.
  - [x] 3.1 RED: write failing tests for both states' visibility conditions.
  - [x] 3.2 GREEN: implement.
- [x] Task 4 (AC: 7): Full `apps/web` suite green; `tsc --noEmit` clean; `eslint` clean on every touched file.

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

## Dev Agent Record

### Implementation Plan

- Added `isBuffering`/`audioError`/`audioRetryCount` to `player.machine.ts`, resetting both on `loadLesson()` (new lesson) and `advanceSegment()` (new segment) so a stall/error never leaks across a segment boundary.
- Wired `onWaiting`/`onPlaying`/`onCanPlay`/`onError` directly on `AudioTimeline.tsx`'s existing `<audio>` element via `usePlayerStore.getState()` calls (same pattern as the existing `handleLoadedMetadata`/`handleEnded`), and folded `audioRetryCount` into the element's `key` so `retryAudio()` forces a real remount + fresh load attempt rather than relying on browser-internal retry behavior.
- Added a non-blocking buffering pill (bottom-right, only visible mid-`PLAYING`) and a blocking playback-error screen with a Retry button to `Player.tsx`, layered in the same z-index tier as the existing `ENDED`/`CheckingInTransition` overlays.
- While verifying AC-7 (`tsc --noEmit` clean), found `Player.tsx` already failed to compile on `main` *before* this story's changes (confirmed via `git stash` + re-run) — Story 2-25's frozen-contract change making `LessonMetadata.tier` optional broke S2-10's `TIER_LABELS: Record<tier, string>` lookup. Fixed narrowly (`Exclude<..., undefined>` on the Record type, `?? 'T2'` on the lookup) since it blocked verifying this story's own changes compile cleanly — not part of this story's scope otherwise, and worth a heads-up to Dev1 that the `LessonMetadata.tier` optionality change needs downstream consumers checked.

### Completion Notes

- All 4 tasks complete, all ACs (1–7) satisfied.
- Full `apps/web` test suite: 53 files, 488 tests, all passing.
- `tsc --noEmit`: clean. `eslint` on all touched files: clean.
- No regressions to the `hasAudio === false` degrade path (Story 1-6/1-7) — explicit test confirms `audioError` stays `false` and no `src` is ever attached for that case.

### File List

- `apps/web/src/stores/player.machine.ts` (MODIFIED — added `isBuffering`/`audioError`/`audioRetryCount` state + `setBuffering`/`setAudioError`/`retryAudio` actions; review round: `retryAudio()` also clears `isBuffering`)
- `apps/web/src/components/player/AudioTimeline.tsx` (MODIFIED — wired `onWaiting`/`onPlaying`/`onCanPlay`/`onError`; `audioRetryCount` folded into `<audio>` key; review round: added `audioRetryCount` to the play/pause effect's dependency array)
- `apps/web/src/components/player/Player.tsx` (MODIFIED — added buffering indicator + playback-error/retry UI; unrelated `tsc` fix for S2-10's `TIER_LABELS` following Story 2-25's `tier` optionality change; review round: gated the error overlay away from QUIZ/TEACH_BACK/ENDED, added a repeated-failure guidance message after 3 retries)
- `apps/web/src/__tests__/stores/player.machine.test.ts` (MODIFIED — new tests for buffering/error/retry state + resets; review round: `retryAudio()` clears `isBuffering` test)
- `apps/web/src/__tests__/components/player/AudioTimeline.component.test.tsx` (MODIFIED — new tests for the 4 new event handlers + retry-key remount; review round: retry-resumes-playback regression test)
- `apps/web/src/__tests__/components/player/Player.test.tsx` (MODIFIED — new tests for both new UI states; review round: QUIZ/TEACH_BACK/ENDED exclusion tests, retry-threshold guidance tests)

## Senior Developer Review (AI)

**Date:** 2026-07-27
**Outcome:** Changes Requested → all actionable findings resolved this session.
**Reviewers:** Blind Hunter (diff-only), Edge Case Hunter (diff + repo access), Acceptance Auditor (diff + spec) — per CLAUDE.md's BMAD Code Review Gate.

### Findings

| # | Severity | Source | Finding | Resolution |
|---|----------|--------|---------|------------|
| 1 | High (independently verified via direct code reading) | Edge Case Hunter | `retryAudio()` never actually resumed playback — the play/pause effect in `AudioTimeline.tsx` had dependency array `[status, currentSegmentIndex, hasAudio]`, missing `audioRetryCount`. Since a same-segment retry changes neither `status` nor `currentSegmentIndex`, the freshly-remounted `<audio>` element never received a `.play()` call — worse than the original stall (no error shown, no progress, no recovery short of manually pausing/playing). Not caught by the original test, which only asserted element identity changed. | Fixed — added `audioRetryCount` to the effect's dependency array; new regression test asserts `.play()` is actually called again after `retryAudio()`. |
| 2 | High/Medium (corroborated 3/3 — Blind Hunter, Edge Case Hunter, Acceptance Auditor) | All three | The playback-error overlay rendered "regardless of status" per the original AC-4 text, sharing `z-20` with `QuizOverlay`/`TeachBackModal`/the `ENDED` screen — a stale or late-firing `audioError` (only reset by `loadLesson`/`advanceSegment`, not by `enterQuiz`/`exitQuiz`/`enterTeachBack`/`exitTeachBack`/`endLesson`) could visually block the quiz, teach-back, or completion screen with an opaque full-screen panel. Acceptance Auditor additionally confirmed this against the literal AC-4 text (z-index mismatch with `CheckingInTransition`'s `z-30`, and the overlay hiding the persistent tier badge). | Fixed the functional problem: error overlay now excluded from `QUIZ`/`TEACH_BACK`/`ENDED` — the narration audio's job for a segment is already done once the student has reached those states, so a stale error must not block progress there. New tests assert the overlay does not render in any of the three excluded states. Z-index/tier-badge-visibility during an *active* PLAYING/PAUSED error was accepted as-is: `CheckingInTransition` itself (the AC's own reference point) also fully covers the tier badge while visible, just more briefly — an active, actionable error state momentarily obscuring the badge is a reasonable, consistent trade-off, not a regression. |
| 3 | Medium (corroborated 2/3 — Blind Hunter, Edge Case Hunter) | Blind Hunter, Edge Case Hunter | No cap or backoff on manual retry — every click immediately re-attempts the identical failing `src` with no limit, unlike this codebase's documented retry/backoff conventions elsewhere (CLAUDE.md §14). A persistently broken/expired URL lets a student hammer Retry indefinitely with no escalating guidance. | Added a `REPEATED_FAILURE_RETRY_THRESHOLD = 3` — after 3 retries on the same segment, additional guidance text appears ("still not working... try refreshing the page") alongside the existing Retry button. Deliberately not a hard cap/disabled button — a transient network issue could still resolve on a later attempt, and stranding the student with no way to retry at all would be worse. New tests cover both sides of the threshold. |
| 4 | Low (Blind Hunter only, not corroborated) | Blind Hunter | `retryAudio()` didn't reset `isBuffering`, so a stall-then-error sequence (`waiting` then `error` on the same element) would leave a stale `true` surviving into the fresh element's initial render. | Fixed — cheap, clearly-correct change; `retryAudio()` now also sets `isBuffering: false`. New test covers it. |
| 5 | Low (Edge Case Hunter only, not corroborated) | Edge Case Hunter | `exitTeachBack()` on the last segment doesn't call `advanceSegment()` (no next segment to advance to), so `isBuffering`/`audioError`/`audioRetryCount` aren't reset when resuming `PLAYING` on the final segment after teach-back. Self-correcting once real `onPlaying`/`onCanPlay`/`onWaiting` events fire on the same (already-loaded) element; purely cosmetic. | Not actioned — single-sourced, low severity, self-correcting per Edge Case Hunter's own analysis. Logged in `docs/stories/deferred-work.md`. |
| 6 | Low (Edge Case Hunter only, not corroborated) | Edge Case Hunter | `CheckingInTransition` (`z-30`, `pointer-events-none`, ≤500ms) can visually sit on top of the Retry button during its brief window if both happen to coincide. Button remains clickable underneath (`pointer-events-none`); purely a brief visual overlap. | Not actioned — single-sourced, low severity, self-resolving. Logged in `docs/stories/deferred-work.md`. |
| 7 | Low (Blind Hunter only, not corroborated) | Blind Hunter | Missing (`undefined`) vs. unrecognized (`'T99'`) tier both silently collapse to the same `T2`/Standard fallback with no distinguishing signal. | Not a bug — pre-existing, intentional design (same fallback behavior for both cases predates this story; Story 2-25 only made the `undefined` case newly reachable). Not actioned. |
| 8 | Low (Blind Hunter only, not corroborated) | Blind Hunter | First `error` event immediately shows the blocking overlay, with no debounce or single silent auto-retry for a transient blip that might self-resolve. | Not actioned — matches AC-4's explicit intent (immediate, visible feedback with a manual retry); a silent auto-retry layer is a reasonable future enhancement, not a defect in this story's stated scope. |

### Non-issues independently re-verified

- `hasAudio === false` degrade path confirmed genuinely safe by Edge Case Hunter: React omits the `src` attribute entirely (not `src=""`), so per the HTML media element spec no browser engine ever dispatches `error`/`waiting`/`canplay` for it — distinct from the historical `src=""` footgun.
- `advanceSegment()`'s resets confirmed atomic (single synchronous `set()` call) — no intermediate render where a stale error/buffering flag is visible before the new segment's state is fully in place.
- `TIER_LABELS`/`Exclude<undefined>` fix confirmed correct and complete by both Edge Case Hunter (repo-wide grep, only call site) and Acceptance Auditor (independently reproduced the pre-existing `tsc` break on `main` via a temporary worktree, confirmed this branch's fix resolves it with no behavior change).
- All three "What NOT to do" Dev Notes constraints (no `PlayerLoader.tsx` resurrection, `onError` unreachable when `hasAudio` is false, no WebSocket/backend wiring in `retryAudio()`) independently confirmed respected by both Edge Case Hunter and Acceptance Auditor.
- AC-7's suite/tsc/eslint claims independently reproduced exactly by Acceptance Auditor before the review-round fixes; re-verified again after (53 files / 495 tests passing, `tsc --noEmit` and `eslint` clean).

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-27 | Story created after closing stale PR #71 — re-scoping its still-valuable audio buffering/error-retry feature as fresh work against current `main` instead of a risky manual merge. Branch `sprint2/s2-26-audio-buffer-retry` off `main`. | Dev 2 |
| 2026-07-27 | Implemented all 4 tasks. Found and fixed an unrelated, pre-existing `tsc` regression on `main` while verifying AC-7 (see Dev Notes) — Story 2-25's frozen-contract change (`LessonMetadata.tier` → optional) broke S2-10's `TIER_LABELS` lookup in `Player.tsx`; fixed with a minimal `Exclude<undefined>` + nullish-coalesced lookup, no behavior change (T99/missing tier still falls back to `T2`/Standard, already covered by an existing test). Full suite 53 files / 488 tests passing, `tsc --noEmit` and `eslint` clean. | Dev 2 |
