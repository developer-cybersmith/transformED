---
title: "Story 2-57 — Slide-Transition Pause + Manual Next Button (BR-5)"
status: ready-for-dev
owners: [Dev 2]
sprint: bug-resolution
---

# Story 2-57 — Configurable Slide-Transition Pause + Manual Next Button

## Problem Statement

BR-5's own wording ("pause between slide transitions... currently transitions are fully
automatic") was ambiguous between two distinct mechanisms in this codebase: within-segment slide
swaps (driven by `AudioTimeline.tsx`'s `processTimeUpdate`, timestamp-boundary-based, no pause,
no user control today) vs. segment-to-segment advancement (already gated by a quiz in the normal
flow). **Confirmed with the user 2026-09-03: this story is about the within-segment slide
swap** — one segment plays one continuous narration track; the visible slide silently changes
underneath it as playback crosses each `NarrationTimestamp` boundary
(`packages/shared/types/lesson.ts`'s `{slide_id, start_ms, end_ms}`), with zero pause today.

## Design

Reuses the existing `PlayerStatus` enum (`'IDLE'|'PLAYING'|'PAUSED'|'QUIZ'|'TEACH_BACK'|'ENDED'`,
`player.machine.ts:42`) rather than inventing a parallel pause mechanism — a slide-transition
pause **is** a real `PAUSED` state, just one the player entered itself rather than the student.
A new `pauseReason: 'manual' | 'slide-transition' | null` field distinguishes them for the UI
only; every existing `status === 'PAUSED'` gate (audio-element pause, `processTimeUpdate`'s
`if (status !== 'PLAYING') return`, the virtual-clock tick effect, the SpeechSynthesis effect)
already does the correct thing with zero changes, because they all already key off `status`, not
off *why* it's `PAUSED`.

Flow:
1. `processTimeUpdate` detects `targetSlideId !== currentSlideId` **and** `currentSlideId` is not
   `null` (excludes the segment's very first slide reveal — that's an initial reveal, not a
   transition, and must not pause).
2. Calls `setCurrentSlide(targetSlideId)` immediately (the new slide becomes visible right away —
   only *continued playback* is held, not the visual reveal) and a new action
   `pauseForSlideTransition()`: sets `status: 'PAUSED'`, `pauseReason: 'slide-transition'`.
   Deliberately does **not** call the existing `pause()` action or its `saveProgress()` side
   effect — this fires at every slide boundary and a `saveProgress()` write per boundary is
   unnecessary I/O for a transient, sub-3-second auto-pause.
3. A `useEffect` in `AudioTimeline.tsx` (mirrors the existing virtual-clock/SpeechSynthesis effect
   pattern already in that file) watches `pauseReason === 'slide-transition'`: starts a
   `setTimeout(DEFAULT_SLIDE_TRANSITION_PAUSE_MS)` — **2000ms**, a named constant — that calls
   `play()` on expiry. Cleans up the timeout if `status`/`pauseReason` changes before it fires
   (student manually intervenes, seeks, or clicks Next first).
4. `play()` (existing action, `player.machine.ts:193`) is reused verbatim as the resume path —
   both the timer's expiry and the new manual **Next** button call the exact same action. `play()`
   needs one addition: clear `pauseReason` back to `null` on any transition out of `PAUSED`
   (whether via timer, Next button, or the existing manual Play button — all must clear it, since
   a student resuming an unrelated later manual pause must not inherit a stale `'slide-transition'`
   reason).
5. **Manual Next button**: rendered only while `pauseReason === 'slide-transition'` (not a
   general-purpose skip-ahead control — that's a different, unscoped feature). Calls `play()`
   directly — functionally identical to the timer firing early. Lives in `PlayerControls.tsx`,
   swapped in place of the Play/Pause button for the duration of the pause (mirrors that
   component's existing `isPlaying ? pause : play` conditional-render pattern).

**"Configurable"**: scoped to a single named constant (`DEFAULT_SLIDE_TRANSITION_PAUSE_MS = 2000`
in `AudioTimeline.tsx`, matching this file's existing constant convention, e.g. `WORDS_PER_LINE`
in `CaptionOverlay.tsx`), not a student- or admin-facing settings UI — flagging this explicitly
since "configurable" could also mean the latter; confirm with the team if a real settings surface
is wanted before or after this ships.

**Fallback-path coverage (real risk, not edge-case padding):** the pause must work identically on
all three playback mechanisms this file already supports — the real `<audio>` element, the
virtual clock (`Segment` with a recovered script but no audio, S2-33), and the SpeechSynthesis
browser-voice overlay (S2-34) — a fix that only covers the primary `<audio>` path would silently
not work in either fallback mode, the same class of gap this codebase's own binding rules call out
for silent truncation.

## Acceptance Criteria

- **AC1** — Crossing a within-segment slide boundary during normal forward playback pauses
  playback (audio element / virtual clock / SpeechSynthesis, whichever is active) and sets
  `pauseReason: 'slide-transition'`; the new slide is visible immediately, only continued
  narration is held.
- **AC2** — Playback auto-resumes after `DEFAULT_SLIDE_TRANSITION_PAUSE_MS` (2000ms) with no
  student action, resuming exactly where it left off (no position loss, no skip).
- **AC3** — A manual "Next" button, visible only during a `'slide-transition'` pause, resumes
  playback immediately when clicked — identical outcome to the timer expiring.
- **AC4** — The segment's very first slide reveal (entering from segment start, or landing on a
  slide via a seek) never triggers a pause — confirmed via `currentSlideId !== null` gating and a
  test asserting `syncSlideToPosition` (the seek path) never calls `pauseForSlideTransition`.
- **AC5** — A genuine student-initiated manual pause during a `'slide-transition'` pause window is
  indistinguishable in outcome from any other manual pause (student must explicitly press Play to
  resume; the auto-resume timer must not fire once status has left `'PAUSED'` for a reason other
  than expiry, and must not fire at all if the student paused first).
- **AC6** — Verified on all three playback mechanisms: real `<audio>`, the virtual clock (no-audio
  script fallback), and the SpeechSynthesis browser-voice path — a new test per mechanism, not
  just the primary path.
- **AC7** — `saveProgress()` is NOT called by `pauseForSlideTransition()` (only by the existing
  manual `pause()` action) — a regression test asserting call count stays at 0 across N synthetic
  slide-boundary crossings in one segment.
- **AC8** — Existing `AudioTimeline.test.ts`/`AudioTimeline.component.test.tsx`/
  `player.machine.test.ts`/`PlayerControls` tests still pass unmodified except where this story's
  own new behavior requires an update (e.g., any test that asserted zero pause at a slide
  boundary as the CURRENT/expected behavior needs updating to reflect the new intended behavior,
  named explicitly in the PR, not silently changed).
- **AC9** — `tsc --noEmit` and targeted `eslint` clean; full frontend suite green.

## Scale & Load

1. **Unit of work / range**: one slide-boundary crossing, per segment, per lesson playback. Range:
   0 (a single-slide segment) to N (as many slides as `package_builder_node` assembled for that
   segment) transitions per segment — already bounded upstream by lesson generation, not a new
   bound introduced here.
2. **Fixed budgets vs variable input**: the 2000ms pause itself is the one new fixed value this
   story introduces, applied uniformly regardless of segment length or slide count — no variable
   input can make it silently wrong (it either pauses every real boundary crossing or it doesn't;
   there's no partial/truncated case).
3. **Scope of limits**: N/A — purely client-side player state, per-viewer, no server-side or
   per-instance concern.
4. **Unbounded reads/writes**: none — no new Supabase read/write; explicitly REMOVES a write
   (`saveProgress()`) from this path relative to reusing the existing `pause()` action, addressed
   directly in AC7 rather than left as an assumption.
5. **Inherited caps re-derived**: N/A — no cap inherited or reused from elsewhere.
6. **Check-then-act under concurrency**: N/A — single-client, single-threaded React state; no
   shared mutable state or race between concurrent actors (the timer-vs-manual-intervention race
   described in AC5 is a real ordering concern but not a concurrency one — both paths run on the
   same JS event loop, resolved by the timer's own cleanup function per React's effect-cleanup
   contract, not by a lock).

## Dev Notes

- `player.machine.ts:42` — `PlayerStatus` enum this story reuses, no new top-level status added.
- `player.machine.ts:193-205` — existing `play()`/`pause()` actions; `play()` gains the
  `pauseReason` clear, `pause()` is untouched (manual pause still calls `saveProgress()`).
- `AudioTimeline.tsx`'s existing virtual-clock (S2-33) and SpeechSynthesis (S2-34) `useEffect`s are
  this story's direct pattern reference for where the new transition-pause timer effect belongs.
- `PlayerControls.tsx:62-63` (`isPlaying`/`canControl`) — the conditional-render pattern the new
  Next-button swap mirrors.
- Real, stated UX risk, not solved here: pausing at every slide boundary in a segment with many
  short slides could read as choppy. Flagged for the team to sanity-check against a real
  multi-slide segment before/shortly after this ships — not a reason to hold the story, since the
  mechanism itself (a single named constant) makes tuning or disabling trivial later.

## References

- [Source: packages/shared/types/lesson.ts:42-46] — `NarrationTimestamp` (per-slide, not per-word)
- [Source: apps/web/src/components/player/AudioTimeline.tsx] — `processTimeUpdate`, the virtual
  clock and SpeechSynthesis effects this story's new effect mirrors
- [Source: apps/web/src/stores/player.machine.ts:42,193-205] — `PlayerStatus`, `play()`/`pause()`
- [Source: apps/web/src/components/player/PlayerControls.tsx:49-63] — existing Play/Pause render
  pattern
- User clarification, 2026-09-03: confirmed within-segment slide swap, not segment-to-segment
  advancement — see this session's own BR-5 disambiguation question and answer.
