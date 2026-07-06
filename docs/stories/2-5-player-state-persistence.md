---
baseline_commit: "5efda8140a2d89f88cc01b8e3845bbf05978e924"
---

# Story 2-5: Player State Persistence (Session Restore)

Status: review

## Story

As a student who gets interrupted mid-lesson (refresh, tab close, browser crash),
I want the lesson player to resume from roughly where I left off instead of restarting from the beginning,
so that an accidental refresh doesn't cost me my progress or force me to re-answer quizzes I've already passed.

## Context

This is Sprint 2 task **S2-05** from `docs/dev2-sprint-tracker.md` §11 — the last remaining Sprint 2 item. Its sketch is directionally correct but underspecified on several real correctness details found by reading the live code before writing this story (do not re-derive these, they're already verified):

### What's already there to build on

- `apps/web/src/stores/player.machine.ts` — Zustand store, **no persistence middleware used anywhere in this codebase yet**. `zustand@^5.0.14` is installed and does support `zustand/middleware`'s `persist`, but it is **deliberately not used here** — see "What NOT to do" below.
- `currentSegmentIndex` (number), `audioPositionMs` (number — position *within the current segment's audio*, reset to 0 in `advanceSegment`, NOT a lesson-wide offset), `quizFiredForSegment` (a `Set<string>` of `segment_id` — **not JSON-serializable directly**, must round-trip through an array), `seekRequestMs` (queues a seek — `requestSeek(ms)` sets it, `AudioTimeline`'s effect applies `audio.currentTime = ms/1000` then clears it).
- `sessionId` is an ephemeral `crypto.randomUUID()` regenerated on every `loadLesson()` call — **not usable as a persistence key**. The task's own file path already specifies keying by `lesson_id` instead, which is correct.
- `apps/web/src/components/player/AudioTimeline.tsx` — the `<audio>` element is keyed by `segment.segment_id` and fully remounts on segment change. The existing `requestSeek`/`seekRequestMs`/`clearSeekRequest` mechanism already correctly handles seeking into a freshly-mounted audio element (same mechanism the code already relies on for the "replay a previously-quizzed segment" case). **Reuse this, don't invent a second seek pathway.**
- `apps/web/src/components/player/Player.tsx` has a mount `useEffect` that calls `loadLesson(lesson)` once (added/confirmed current as of Story 2-4). This is the natural place to also trigger a restore, immediately after `loadLesson` so `state.lesson` is populated first.

### A real correctness gap the tracker sketch missed: restored `currentSlideId` desync

`Player.tsx` renders `segment?.slides.map(slide => <SlideRenderer isActive={slide.slide_id === currentSlideId} ...>)` where `segment = lesson.segments[currentSegmentIndex]`. If restore only sets `currentSegmentIndex` to, say, segment 2, but leaves `currentSlideId` as whatever `loadLesson` set it to (segment 0's first slide id), **no slide in segment 2 will match `currentSlideId`** (slide ids are segment-scoped, e.g. `sl_2_0` vs `sl_0_0`) — the slide area renders **blank** until the student presses play and the first `timeupdate` tick corrects it (slide resolution only runs while `status === 'PLAYING'`, per `processTimeUpdate`'s own guard). This must be fixed by having the restore action also compute and set the correct `currentSlideId` via the same binary-search logic `AudioTimeline.tsx` already uses (`binarySearchTimestamps`), not left to fix itself later.

`binarySearchTimestamps` currently lives in and is only exported from `apps/web/src/components/player/AudioTimeline.tsx`. `player.machine.ts` cannot import from there (component → store → component would be circular, since `AudioTimeline.tsx` already imports `usePlayerStore`). **Extract it to a new dependency-free module `apps/web/src/lib/binarySearch.ts`**, have `AudioTimeline.tsx` re-export it from there (`export { binarySearchTimestamps } from '@/lib/binarySearch'`) so the existing test import path (`@/components/player/AudioTimeline`, used by `AudioTimeline.test.ts`) keeps working unchanged, and have `player.machine.ts` import the function directly from the new shared location.

### A real cross-feature interaction: "Study Again" (Story 2-4) vs. stale saved progress

Story 2-4's `SessionReport.tsx` "Study Again" button links to `/lesson/{lesson_id}` — **re-entering the same lesson after it's already been completed**. If this story's saved progress (`hie:session:{lesson_id}`) is never cleared on completion, a student who finishes a lesson and clicks "Study Again" would be silently resumed near the **end** of the lesson instead of restarting — directly undermining the feature Story 2-4 just shipped. **This story must clear the saved entry when the lesson reaches `ENDED`** (in the store's existing `endLesson()` action).

### Write-frequency: don't write to localStorage on every tick

`AudioTimeline.tsx`'s `onTimeUpdate` calls `updateAudioPosition` on every native `timeupdate` event (fires roughly every ~250ms per the HTML5 spec — frequent, not a fixed high rate, but still too often for an unconditional `localStorage.setItem` on every call). Given the ±3-second accuracy bar in the ACs, **throttle actual writes to at most once per ~2 real seconds** using a module-scoped timestamp guard (not a Zustand state field — this is internal bookkeeping, not application state).

## Acceptance Criteria

1. **Schema:** localStorage key `hie:session:{lesson_id}` (exact format, matches the tracker's own sketch). Stored JSON shape: `{ segmentIndex: number, audioPositionMs: number, quizFiredForSegment: string[], storedAt: number }`.
2. **`saveProgress()` action** (new, in `player.machine.ts`): writes the current `lesson.lesson_id`-keyed entry from the live state. No-op if `typeof window === 'undefined'` (this file has no prior browser-API dependency — guard defensively even though `PlayerLoader.tsx`'s `ssr:false` wrapping makes the practical risk low) or if no lesson is loaded.
3. **Throttled automatic saves:** `updateAudioPosition` triggers `saveProgress()` internally, but the actual `localStorage.setItem` only fires if at least ~2 real seconds have elapsed since the last write (module-scoped timestamp, not new Zustand state).
4. **Checkpoint saves:** `advanceSegment()` and `pause()` each call `saveProgress()` immediately (uncoditional on the throttle) — these are natural moments where losing the last couple seconds of granularity would be more noticeable.
5. **`restoreProgress(lessonId: string): boolean` action** (new): reads `hie:session:{lessonId}`. Returns `false` (and does nothing else) if: the key is missing, JSON parsing fails, any expected field has the wrong type, `Date.now() - storedAt > 24h`, or `segmentIndex` is out of bounds for the **currently loaded** `lesson.segments.length` (validated against `get().lesson`, which must already be populated — this action is only meaningful after `loadLesson` has run). A stale (>24h) or invalid entry is also removed from localStorage when detected, not just ignored.
6. **On successful restore:** sets `currentSegmentIndex` to the restored value, computes and sets `currentSlideId` via `binarySearchTimestamps` against the restored segment's `narration.timestamps` at the restored `audioPositionMs` (fixes the blank-slide gap described above), calls the existing `requestSeek(audioPositionMs)` action (reuses the existing seek mechanism — do not write a second one), and restores `quizFiredForSegment` as `new Set(quizFiredForSegment)`. Returns `true`.
7. **Wiring:** `Player.tsx`'s existing mount effect calls `usePlayerStore.getState().restoreProgress(lesson.lesson_id)` immediately after `loadLesson(lesson)`, in the same effect (synchronous — `loadLesson`'s `set()` call completes before `restoreProgress` reads `get().lesson`).
8. **Clear on completion:** `endLesson()` removes the `hie:session:{lesson_id}` entry for the current lesson, so re-entering a completed lesson (e.g. via Story 2-4's "Study Again" link) starts fresh rather than silently resuming near the end.
9. **Accuracy:** restoring resumes within ±3 seconds of the last saved position (satisfied by the ~2s throttle plus checkpoint saves).
10. **No double-quiz-fire:** a segment already in the restored `quizFiredForSegment` set does not re-trigger its quiz on resumed playback (already covered by existing `processTimeUpdate` logic — this AC just confirms restore doesn't bypass it).
11. **Shared binary-search extraction:** `binarySearchTimestamps` moved to `apps/web/src/lib/binarySearch.ts`; `AudioTimeline.tsx` re-exports it from the new location; the existing `AudioTimeline.test.ts` (which imports it from `@/components/player/AudioTimeline`) continues to pass unmodified.
12. **Tests:** unit tests for `saveProgress`/`restoreProgress` in `player.machine.test.ts` (reuse the existing `makeLesson(segmentCount)` fixture) covering: round-trip save→restore, missing key, corrupted JSON, wrong-typed fields, >24h-old entry (discarded and removed), out-of-bounds `segmentIndex` against a lesson with fewer segments than the saved snapshot, `quizFiredForSegment` correctly reconstructed as a `Set`, `currentSlideId` correctly resolved post-restore, throttling behavior (rapid `updateAudioPosition` calls within the throttle window only write once), `endLesson()` clearing the stored entry, and `pause()`/`advanceSegment()` triggering an immediate (non-throttled) save. A `binarySearch.test.ts` (or the existing test moved) for the extracted function.

## Tasks / Subtasks

- [x] Task 1: Extract `binarySearchTimestamps` to a shared module (AC: #11)
  - [x] 1.1 Created `apps/web/src/lib/binarySearch.ts` with the function moved from `AudioTimeline.tsx` (identical implementation, no behavior change)
  - [x] 1.2 `AudioTimeline.tsx` re-exports it via a local import + `export { binarySearchTimestamps }`
  - [x] 1.3 Confirmed `AudioTimeline.test.ts`/`AudioTimeline.component.test.tsx` pass unmodified (34/34), `tsc` clean
- [x] Task 2: `saveProgress` (AC: #1, #2, #3, #4)
  - [x] 2.1 Wrote failing tests first (RED) — writes correct shape/key, no-op with no lesson, throttle behavior (using `vi.useFakeTimers`), checkpoint-triggered immediate saves from `pause()`/`advanceSegment()`. `window`-undefined no-op is not testable in this jsdom-based environment (documented, not test-covered — same limitation noted elsewhere in this codebase for SSR guards)
  - [x] 2.2 Implemented `saveProgress()`, the throttle guard (module-scoped `lastSavedAt`, reset in `loadLesson()` so a stale timestamp from a prior lesson session can never suppress a new one's first save), wired into `updateAudioPosition`/`pause`/`advanceSegment` (GREEN)
- [x] Task 3: `restoreProgress` (AC: #5, #6, #10)
  - [x] 3.1 Wrote failing tests first (RED) — happy path, missing key, corrupted JSON, wrong types, >24h stale (and removed), out-of-bounds segmentIndex (and removed), `currentSlideId` resolved correctly via `binarySearchTimestamps`, `quizFiredForSegment` reconstructed as a Set, seek applied via `requestSeek`
  - [x] 3.2 Implemented `restoreProgress(lessonId)` with an `isStoredProgress` type guard (GREEN)
- [x] Task 4: Clear on completion (AC: #8)
  - [x] 4.1 Wrote a failing test first (RED) — `endLesson()` removes the stored entry
  - [x] 4.2 Implemented (GREEN)
- [x] Task 5: Wire `Player.tsx` (AC: #7)
  - [x] 5.1 Added `restoreProgress` call to the existing mount effect, immediately after `loadLesson`
  - [x] 5.2 Confirmed existing `Player.test.tsx` (Story 2-4's ENDED-screen tests) still pass; added 2 new tests for restore-on-mount (happy path + no-saved-snapshot case)
- [x] Task 6: Full verification
  - [x] 6.1 Full `apps/web` test suite green, no regressions — 300/300 passing (15 new)
  - [x] 6.2 `npx tsc --noEmit` clean
  - [x] 6.3 `npx eslint .` — 0 errors, 37 pre-existing warnings unchanged
  - [x] 6.4 Updated `docs/dev2-sprint-tracker.md` S2-05 entry to DONE; Sprint 2 dashboard row now 5/5 done, header updated to reflect Sprint 2 complete

## Dev Notes

### Files this story touches

- `apps/web/src/lib/binarySearch.ts` (NEW — extracted pure function)
- `apps/web/src/components/player/AudioTimeline.tsx` (MODIFY — re-export only, no behavior change)
- `apps/web/src/stores/player.machine.ts` (MODIFY — `saveProgress`, `restoreProgress`, throttle, hooks into `updateAudioPosition`/`pause`/`advanceSegment`/`endLesson`)
- `apps/web/src/components/player/Player.tsx` (MODIFY — one line added to the existing mount effect)
- `apps/web/src/__tests__/stores/player.machine.test.ts` (MODIFY — reuse existing `makeLesson` fixture for new tests)
- `apps/web/src/__tests__/lib/binarySearch.test.ts` (NEW, or move the existing binary-search test cases here — dev's call on which reads cleaner, as long as coverage isn't lost)

### What NOT to do

- Do NOT use `zustand/middleware`'s `persist`. It writes on every `set()` call by default (too frequent given the throttle requirement above), and correctly round-tripping `quizFiredForSegment`'s `Set` type through it needs custom `serialize`/`deserialize` plumbing that's more complex than two explicit, plain actions written in this file's existing style (every other action in `player.machine.ts` is a plain synchronous function — match that, don't introduce a new pattern for this one feature).
- Do NOT invent a second seek mechanism — reuse `requestSeek`/`seekRequestMs`/`clearSeekRequest` exactly as `AudioTimeline.tsx` already implements them.
- Do NOT clamp or trust a restored `segmentIndex` that's out of bounds for the currently-loaded lesson — discard the whole entry instead. (Browser-level `audio.currentTime` clamping already handles an out-of-range `audioPositionMs` for a given segment, so no extra clamping is needed there.)
- Do NOT skip clearing progress on `endLesson()` — this is a real, discovered regression risk against Story 2-4's "Study Again" feature, not a nice-to-have.
- Do NOT store `sessionId` as part of the persisted snapshot or use it as the storage key — it's ephemeral and regenerated every `loadLesson()` call, unrelated to cross-refresh identity. Use `lesson_id`, exactly as the tracker's own file-path sketch specifies.

### Project Structure Notes

No conflicts with `packages/shared` frozen contracts. Purely additive to `player.machine.ts`'s existing action set; no existing action's external behavior changes except `pause()`, `advanceSegment()`, and `endLesson()` gaining an additional internal side effect (a `localStorage` write/removal) — their existing state-transition behavior is unchanged.

### References

- [Source: docs/dev2-sprint-tracker.md#S2-05 — Player State Persistence (Session Restore)] (original sketch)
- [Source: apps/web/src/stores/player.machine.ts] (file this story modifies most)
- [Source: apps/web/src/components/player/AudioTimeline.tsx] (existing seek mechanism and `binarySearchTimestamps` to extract)
- [Source: apps/web/src/components/player/Player.tsx] (mount-effect wiring point)
- [Source: apps/web/src/__tests__/stores/player.machine.test.ts] (existing `makeLesson` fixture to reuse)
- [Source: docs/stories/2-4-session-report-page.md, apps/web/src/components/reports/SessionReport.tsx] ("Study Again" cross-feature interaction that motivates AC #8)

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (claude-sonnet-5)

### Debug Log References

- RED confirmed for every task before implementation: existing `AudioTimeline.test.ts` passed unmodified after Task 1's extraction (no RED needed there — pure refactor); `saveProgress is not a function`/`restoreProgress is not a function` for Tasks 2–4's 13 new store tests; missing-restore-effect for Task 5's 1 new `Player.test.tsx` test (the "starts fresh" case passed trivially since that's the pre-existing default behavior).
- A real cross-test-leakage risk was designed around, not just discovered by accident: the throttle's `lastSavedAt` bookkeeping is a module-scoped variable, not Zustand state, so it would otherwise persist across tests within the same file (and across unrelated lessons in production). Resolved by resetting it inside `loadLesson()` itself — a real design improvement (a newly loaded lesson shouldn't inherit stale save-timing from a previous, unrelated session), not merely a test workaround.
- Fake timers (`vi.useFakeTimers()`/`vi.setSystemTime()`) used throughout the new store tests to make the ~2s throttle window and the 24h staleness check deterministic.

### Completion Notes List

- Extracted `binarySearchTimestamps` from `AudioTimeline.tsx` into `lib/binarySearch.ts` to avoid a component→store→component circular import, since `restoreProgress` needs it to resolve `currentSlideId` correctly. `AudioTimeline.tsx` re-exports it so the existing test import path is unchanged.
- Found and fixed a real bug not present in the original task sketch: restoring only `currentSegmentIndex` without also resolving `currentSlideId` would render a blank slide area (segment-scoped slide ids wouldn't match the stale `currentSlideId` left over from `loadLesson`) until the student pressed play and the next `timeupdate` tick corrected it. `restoreProgress` now resolves the correct slide via the same binary-search logic `AudioTimeline.tsx` already uses.
- Found and fixed a real cross-feature interaction: without clearing saved progress on `endLesson()`, a student clicking Story 2-4's "Study Again" link would have been silently resumed near the end of the lesson instead of restarting. `endLesson()` now removes the saved entry for the completed lesson.
- Followed the story's explicit "do not use `zustand/middleware`'s `persist`" instruction — implemented `saveProgress`/`restoreProgress` as plain, explicit actions matching every other action in this file's existing style.
- Reused the existing `requestSeek` mechanism for applying a restored position — no second seek pathway was introduced.
- The `window === 'undefined'` SSR guards in `saveProgress`/`restoreProgress`/`endLesson` are not directly test-covered — not testable in this project's jsdom-based Vitest environment, consistent with how other SSR guards are handled elsewhere in this codebase. Documented in Task 2.1.
- All 6 tasks completed in strict RED → GREEN order; no task was marked done without its tests actually passing first.

### File List

**Files CREATED:**
- `apps/web/src/lib/binarySearch.ts`

**Files MODIFIED:**
- `apps/web/src/components/player/AudioTimeline.tsx` — `binarySearchTimestamps` now re-exported from `lib/binarySearch.ts` (no behavior change)
- `apps/web/src/stores/player.machine.ts` — added `saveProgress`, `restoreProgress`, throttle bookkeeping (`lastSavedAt`, reset in `loadLesson`), hooks in `updateAudioPosition`/`pause`/`advanceSegment`/`endLesson`
- `apps/web/src/__tests__/stores/player.machine.test.ts` — 13 new tests (reused existing `makeLesson` fixture), `localStorage.clear()` added to the existing `beforeEach`
- `apps/web/src/components/player/Player.tsx` — mount effect now calls `restoreProgress(lesson.lesson_id)` immediately after `loadLesson`
- `apps/web/src/__tests__/components/player/Player.test.tsx` — 2 new tests (restore happy path, no-saved-snapshot case), `localStorage.clear()` added to the existing `beforeEach`
- `docs/dev2-sprint-tracker.md` — S2-05 marked done, Sprint 2 dashboard row now 5/5, header updated to reflect Sprint 2 complete

### Change Log

- 2026-07-06: Story created — Sprint 2 Task 5 (last Sprint 2 item), `sprint2/s2-5-player-state-persistence` branch
- 2026-07-06: All 6 tasks implemented in RED→GREEN order; 15 new tests; 300/300 full suite passing; `tsc`/`eslint` clean; story marked `review`
