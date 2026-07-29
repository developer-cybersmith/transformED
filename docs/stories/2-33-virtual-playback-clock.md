---
baseline_commit: 3900ae6324ca93fae943dbc7d9e850d38a36b01c
---

# Story 2.33: Virtual Playback Clock + Retry Re-Fetch on Media Error

Status: ready-for-dev

## Story

As a student,
I want a segment with a recovered narration script but no playable audio to still advance through its slides in real time (not instantly), and a "Retry" on a playback error to actually fetch a fresh media URL instead of retrying a dead one,
so that the "quiz fires at 0:00" symptom is genuinely fixed, not just half-fixed on the backend, and a Retry click has a real chance of working when the original failure was an expired signed URL.

**Source:** `docs/dev2-narration-playback-handoff.md` (Dev 1, 2026-07-28), written after Dev 1 fixed both of our reported pipeline bugs on `main`:

- **Bug 1 (quiz duplication)** — fixed for real, PR #100 (Story 2-28). Root cause was not ARQ retries (max_tries=3, so 16 retries was never possible) — it was every downstream node's `return {**state, ...}` re-spreading already-accumulated `operator.add` reducer fields, causing `2⁴ = 16×` duplication in a single clean run. Verified directly in the merged diff: all node returns changed from `{**state, "field": value}` to `{"field": value}`.
- **Bug 2 (TTS fallback), backend half** — fixed, PR #101 (Story 2-31). `_fallback_narration()` now recovers the real script from `state["narration_scripts"]` before falling back to blank. Verified directly in the merged diff.

**Bug 2's user-visible symptom is NOT fixed by the backend patch alone.** Traced through the current frontend code (still true after Story 2-31 landed): `AudioTimeline.tsx`'s `!hasAudio` branch calls `handleEnded()` immediately regardless of whether a script is present — `'timeupdate'` never fires, `narration.timestamps` are never read, and the quiz fires at 0:00 exactly as before. A non-empty script alone changes nothing on screen. This story builds the missing piece: a virtual playback clock that drives the same `processTimeUpdate` boundary logic on a synthetic timer when there's a script but no real audio.

Dev 1's handoff also flagged two of our own recent gaps while re-verifying `main`:
- `retryAudio()` (Story 2-26) remounts the `<audio>` element with the exact same `src` — if the original failure was an expired signed URL (audio/image signed URLs are `_EMBEDDED_MEDIA_EXPIRY_S`-bounded, confirmed via `apps/api/app/modules/content/router.py::_resolve_lesson_content`, which re-signs every `audio_url`/`image_url` fresh on every `GET /api/content/lessons/{id}` call), every retry fails identically.
- `session_id` is client-generated with no backend round-trip — **explicitly out of scope for this story**, a joint decision with Dev 4, not a unilateral frontend fix.

Browser `SpeechSynthesis` (Dev 1's "Story 2b") is explicitly labeled an enhancement in the handoff, not required to close Bug 2 — also out of scope here.

## Acceptance Criteria

1. **AC-1** — `AudioTimeline.tsx` branches three ways instead of two: `hasAudio` (today's real `<audio>` path, unchanged) | `!hasAudio && script.trim()` (**new** — virtual clock) | `!hasAudio && !script` (today's immediate-`handleEnded()` path, unchanged).
2. **AC-2** — The virtual clock is a `setInterval(..., 100)` that calls `processTimeUpdate(audioPositionMs + 100)` (reading the current position fresh from the store on every tick, not a stale closure value), active only while `status === 'PLAYING'` for the current segment. It is torn down (interval cleared) on segment change, on `hasAudio`/`hasScript` becoming false, or on `status` leaving `PLAYING`.
3. **AC-3** — The virtual clock **never calls `handleEnded()`** — `processTimeUpdate`'s own segment-boundary check already fires the quiz; a second, independent call to `handleEnded()` would double-fire past an open quiz (matches the existing guard rationale already documented for the real-audio path).
4. **AC-4** — On entering virtual-clock mode for a segment, `setAudioDuration(timestamps.at(-1).end_ms)` is called so the scrubber shows a real total duration instead of 0 (timestamps always exist here — Story 2-19's estimation — independent of whether audio/script exist).
5. **AC-5** — A pending `seekRequestMs` is absorbed in virtual-clock mode: applied via an immediate `processTimeUpdate(seekRequestMs)` call (there is no real `<audio>` element to set `.currentTime` on), then cleared, mirroring the real-audio seek path's effect on state.
6. **AC-6** — `retryAudio`'s call site (the "Retry" button in `Player.tsx`) re-fetches the lesson content (via `useLesson`'s SWR revalidation, threaded down through `PlayerLoader.tsx`) before remounting the `<audio>` element, so an expired signed URL gets a fresh one instead of retrying the dead one. A new `refreshLessonMedia(pkg)` store action replaces `lesson` with the freshly-fetched package **without** resetting playback progress (`currentSegmentIndex`, `audioPositionMs`, `quizFiredForSegment`, etc.) — unlike `loadLesson()`, which is only for starting a lesson from scratch.
7. **AC-7** — No regression to the existing two-way branch's behavior for `hasAudio` and `!hasAudio && !script` segments.
8. **AC-8** — Per Dev 1's handoff heads-up: the existing S2-26 test asserting a segment with `audio_url: ''` and mock `mockLessonPackage`'s real 60-word script synchronously reaches `'QUIZ'` on mount will now go through the new virtual-clock branch instead (a timer, not synchronous) — re-point that specific test to an empty-script fixture, which still exercises the untouched `!hasAudio && !script` immediate-advance path.
9. **AC-9** — Tests: virtual clock ticking/boundary-firing/teardown, duration-setting, seek-absorption, and the retry-refetch flow all have dedicated tests. Full `apps/web` suite green, `tsc --noEmit` clean, `eslint` clean on every touched file.

## Tasks / Subtasks

- [ ] Task 1 (AC: 1, 2, 3, 4, 7): Add the virtual playback clock to `AudioTimeline.tsx` — three-way branch, ticking effect, duration-setting effect.
  - [ ] 1.1 RED: failing tests for the new branch's ticking behavior, boundary-firing via `processTimeUpdate` (not `handleEnded`), and duration-setting.
  - [ ] 1.2 GREEN: implement.
- [ ] Task 2 (AC: 5): Extend the seek-absorption effect to handle the no-real-audio-element case.
  - [ ] 2.1 RED, 2.2 GREEN.
- [ ] Task 3 (AC: 8): Re-point the existing S2-26 "no audio, advances immediately" test to an empty-script fixture; add a new test confirming the *original* fixture (real script, no audio) now goes through the virtual clock instead.
- [ ] Task 4 (AC: 6): Add `refreshLessonMedia` to `player.machine.ts`; expose SWR `mutate` from `useLesson.ts` as `refetch`; thread it through `PlayerLoader.tsx` → `Player.tsx`; wire the Retry button to refetch-then-retry.
  - [ ] 4.1 RED, 4.2 GREEN.
- [ ] Task 5 (AC: 9): Full `apps/web` suite green; `tsc --noEmit` clean; `eslint` clean on every touched file.

## Dev Notes

### What NOT to do

- Do NOT implement `session_id` backend round-trip — explicitly a joint decision with Dev 4, out of scope here (see Dev 1's handoff §3).
- Do NOT implement browser `SpeechSynthesis` — explicitly labeled an enhancement in Dev 1's handoff, not required to close Bug 2.
- Do NOT call `handleEnded()` from the virtual clock under any circumstance — see AC-3's rationale.
- Do NOT reset playback progress (`currentSegmentIndex`, `audioPositionMs`, `quizFiredForSegment`) when refreshing lesson media on retry — that's what `loadLesson()` is for; this story needs a distinct, narrower action.

### Testing standards

Vitest + fake timers (`vi.useFakeTimers()`/`vi.advanceTimersByTime()`) for the virtual clock's `setInterval` behavior, matching this codebase's existing fake-timer usage in `player.machine.test.ts`'s `saveProgress` throttle tests. Matches existing conventions in `AudioTimeline.test.ts` (handler-level) and `AudioTimeline.component.test.tsx` (render-level).

### References

- [Source: docs/dev2-narration-playback-handoff.md] — the handoff this story implements.
- [Source: docs/stories/2-28-pipeline-state-duplication-fix.md, docs/stories/2-31-narration-recovery-and-tier-cleanup.md] — the two backend fixes this story's frontend half completes.
- [Source: apps/api/app/modules/content/router.py::_resolve_lesson_content] — confirms re-fetching the lesson genuinely produces a fresh signed URL, verified directly before writing AC-6.
- [Source: apps/web/src/components/player/AudioTimeline.tsx, apps/web/src/stores/player.machine.ts] — current two-way branch and retry mechanism this story extends.
