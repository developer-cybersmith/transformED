---
title: "Story 2-57 — Slide-Transition Pause + Manual Next Button (BR-5)"
status: done
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

## Addendum — Skip-Pause Checkbox + Ask-Tutor Intervention Button

Added 2026-09-03 after the user flagged a real UX risk in the original design (a segment with
many short slides pausing at every boundary could read as choppy) and asked for two additions,
both confirmed with the user before scoping:

**"Skip pause for this segment" checkbox.** A per-segment opt-out — when checked, AC1's
auto-pause is suppressed for the remainder of the CURRENT segment only; resets to unchecked on
every new segment (a student who found one segment's pacing fine but another's choppy isn't stuck
with a lesson-wide setting). Pure client state (`skipTransitionPauseForSegment: boolean` on
`usePlayerStore`, reset alongside the other per-segment fields `advanceSegment()` already resets).
No backend involvement.

**Ask-Tutor intervention button.** Confirmed with the user: this is a manually-triggered pause —
available at any time during playback, not tied to a slide boundary — that lets the student pause
and submit a free-text question when they don't understand something. **Confirmed scope for v1**
(the user chose this explicitly, having been told the real gap): there is no live AI Q&A backend
anywhere in this codebase today — `CLAUDE.md` lists "Tutor Q&A" under Phase 2, not built, and
every existing intervention message is pre-generated at build time specifically because "no GPT
call at intervention time" is a hard rule. **v1 is capture-and-log only** — the question is stored
with segment/timestamp context, the student sees "noted — we'll follow up," and there is no live
answer. **Confirmed ownership split**: the real backend endpoint belongs in Dev 3's assessment
module (`session_events` already exists and is exactly shaped for this — `dna_growth.py` already
writes similarly-typed rows there, so no new migration is needed, just a new `event_type` and one
new endpoint) — **this story builds the frontend against a documented stub, mirroring the exact
pattern `payment.service.ts::checkAccess` already established for D136** (Razorpay's missing
`GET /api/payments/access`): a service function that resolves a mock value with a comment citing
the register entry, so the call site never changes when the real endpoint lands.

Mechanically, this reuses the same `pauseReason` design as the slide-transition pause
(`pauseReason: 'intervention'`), with two differences: (1) it has no auto-resume timer — the
student must explicitly press Play when ready, same as any manual pause; (2) it opens a text-input
panel (new component, mirrors `TeachBackModal.tsx`'s existing typed-response pattern) for the
question itself.

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
- **AC10** — A "skip pause for this segment" checkbox, when checked, suppresses AC1's auto-pause
  for every remaining slide boundary in the current segment; resets to unchecked when
  `currentSegmentIndex` changes. Does not affect the manual Ask-Tutor button (AC11-13) — a student
  can skip auto-pauses and still manually ask a question at any time.
- **AC11** — An "Ask Tutor" button is available while `PLAYING`, or while already `PAUSED` for any
  OTHER reason (e.g. mid slide-transition auto-pause) — **revised during implementation** (review
  finding while writing this story's tests): the original "only during PLAYING" scope meant a
  student auto-paused at a slide transition couldn't ask a question without first resuming just to
  re-pause. Pressing it sets `pauseReason: 'intervention'` (canceling any in-flight transition
  auto-resume timer via that reason change) and opens a text-input panel. No auto-resume timer of
  its own — playback stays paused until the student explicitly presses Play.
- **AC12** — Submitting a question calls a new `tutorQuestionService.submitQuestion()` (mirrors
  `paymentService.checkAccess()`'s stub pattern exactly): resolves a mock `{ received: true }`
  with a comment citing this story's new register entry (the real
  `POST` endpoint does not exist on the backend yet — confirmed by grep, no route registers it in
  any module). Student sees a "noted — we'll follow up" confirmation on the mocked response; the
  call site is written so swapping the stub for a real `api.post(...)` call requires no caller
  changes.
- **AC13** — The submitted payload shape (`segment_id`, `question_text`, `audio_position_ms`) is
  documented in this story's References section as the proposed contract for Dev 3's real
  endpoint — not guessed silently, so the eventual real implementation doesn't have to
  reverse-engineer the frontend's assumption.

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

## Proposed Contract for Dev 3 (D159 — not built)

`POST /api/assessment/sessions/{session_id}/questions` (path/module a suggestion, Dev 3's call):

```json
// Request
{ "segment_id": "seg_3", "question_text": "string, student-typed", "audio_position_ms": 41200 }
// Response
{ "received": true }
```

Proposed storage: one `session_events` row, `event_type: "tutor_question"`, payload
`{segment_id, question_text, audio_position_ms}` — matches the existing typed-row convention
`dna_growth.py` already uses for `dna_update` events, no new migration.

## Dev Agent Record

### Completion Notes

- **AC1-AC10 — DONE.** Reused `PlayerStatus.PAUSED` with a new `pauseReason` field, exactly as
  designed — zero changes needed to the audio-element play/pause effect, the virtual-clock tick
  effect, or the SpeechSynthesis effect, since all three already key off `status`, not why it's
  `PAUSED`.
- **Real review finding caught while implementing, fixed same-pass**: the original design's early
  `return` after triggering `pauseForSlideTransition()` inside `processTimeUpdate` silently broke
  the quiz-boundary check whenever a slide boundary and the segment's own end boundary coincided
  on the same tick (the common case for a segment's last slide) — `enterQuiz()` itself guards on
  `status === 'PLAYING'`, so if the pause ran first, the quiz call became a silent no-op. Fixed by
  checking the segment-end/quiz condition BEFORE the slide-transition pause, not after. Caught by
  running the existing test suite immediately after the first implementation pass, not assumed
  correct — 5 pre-existing tests failed and pinpointed the exact issue.
- **Second real finding caught while writing this story's own tests**: `pauseForIntervention()`'s
  original guard (`status === 'PLAYING'` only) meant a student already auto-paused at a slide
  transition couldn't ask a question without first resuming just to re-pause. Widened to also
  accept an existing `PAUSED` state of any other reason — see AC11's revised text.
- **AC11-13 — DONE.** `AskTutorPanel.tsx` (new), `lib/assessment.ts::submitTutorQuestion()` (new
  stub, mirrors `payment.service.ts::checkAccess`'s exact D136 pattern), registered as **D159**.
- Two pre-existing tests needed updating, both named explicitly here per AC8's own requirement
  (not silently changed): `AudioTimeline.component.test.tsx`'s two virtual-clock ticking tests
  (`vi.advanceTimersByTime` across the whole segment in one call) now opt out via
  `skipTransitionPauseForSegment: true` — they test the quiz-firing mechanism specifically, not
  this story's new pause feature, which has its own dedicated tests.
- Full suite: 91 files / 1118 tests (was 89/1085 before this story — +2 new test files, +33 new
  tests), zero regressions. `tsc --noEmit` clean. `eslint` clean (one pre-existing-pattern warning
  on the new stub's unused `_payload` param, identical to `payment.service.ts::checkAccess`'s own
  `_lessonId` warning — confirmed, not a new problem).

### File List

- `apps/web/src/stores/player.machine.ts` — `PauseReason` type, `pauseReason`/
  `skipTransitionPauseForSegment` state, `pauseForSlideTransition()`/`pauseForIntervention()`/
  `setSkipTransitionPauseForSegment()` actions, `play()`/`pause()`/`advanceSegment()` updated
- `apps/web/src/components/player/AudioTimeline.tsx` — `processTimeUpdate` pause trigger
  (reordered around the quiz-boundary check, see review finding above), new auto-resume timer
  effect, `DEFAULT_SLIDE_TRANSITION_PAUSE_MS` constant
- `apps/web/src/components/player/PlayerControls.tsx` — Next-button swap, Ask Tutor button,
  skip-pause checkbox
- `apps/web/src/components/player/AskTutorPanel.tsx` — new
- `apps/web/src/components/player/Player.tsx` — mounts `AskTutorPanel`
- `apps/web/src/lib/assessment.ts` — `submitTutorQuestion()` stub (D159)
- `apps/web/src/__tests__/stores/player.machine.test.ts` — 10 new tests
- `apps/web/src/__tests__/components/player/AudioTimeline.test.ts` — 5 new tests
- `apps/web/src/__tests__/components/player/AudioTimeline.component.test.tsx` — 4 new tests, 2
  existing tests updated (opt-out, named above)
- `apps/web/src/__tests__/components/player/PlayerControls.test.tsx` — new file, 9 tests
- `apps/web/src/__tests__/components/player/AskTutorPanel.test.tsx` — 5 tests at initial
  implementation, +2 added in the pre-merge pass wiring D159 to the real D158 backend (7 total)
- `docs/DEFECT-REGISTER.md` — D159 registered

### Pre-merge review note (2026-09-05)

- **ID renumbered D149 → D159**: correct when this story registered it, but D149 was independently
  claimed by the Sarvam v3 batching fix, which merged to `main` while this branch was open.
- **A real backend now exists, and this PR now wires it up**: Story 4-28 (D158, merged 2026-09-05)
  implements `POST /assessment/session/{session_id}/questions` (singular "session" — this story's
  own proposed contract above used the plural, never verified against real router conventions).
  `submitTutorQuestion()` was the D136-pattern stub at the time this story was originally written;
  in this same pre-merge pass it now calls the real endpoint (`session_id` moved from the request
  body to the URL path), and `AskTutorPanel.tsx` renders the real `answer`/`declined` response
  instead of only ever showing a static "noted" card. D159 is closed by this change — see its
  updated `docs/DEFECT-REGISTER.md` row.

## References

- [Source: packages/shared/types/lesson.ts:42-46] — `NarrationTimestamp` (per-slide, not per-word)
- [Source: apps/web/src/components/player/AudioTimeline.tsx] — `processTimeUpdate`, the virtual
  clock and SpeechSynthesis effects this story's new effect mirrors
- [Source: apps/web/src/stores/player.machine.ts:42,193-205] — `PlayerStatus`, `play()`/`pause()`
- [Source: apps/web/src/components/player/PlayerControls.tsx:49-63] — existing Play/Pause render
  pattern
- User clarification, 2026-09-03: confirmed within-segment slide swap, not segment-to-segment
  advancement — see this session's own BR-5 disambiguation question and answer.
