---
title: "Story 2-66 — Ask Tutor: Cancel Restores the Prior Pause Instead of Forcing Resume (BR-11)"
status: done
owners: [Dev 2]
sprint: bug-resolution
---

# Story 2-66 — Ask Tutor: Cancel Restores the Prior Pause Instead of Forcing Resume (BR-11)

## Problem Statement

Direct user feedback: *"there is not way to go back in popup modal's ask tutor. once clicked ask
tutor, no option to abort that or cancelled."*

Confirmed by reading `player.machine.ts` directly: `pauseForIntervention()` can be triggered from
`PLAYING`, from a manual pause, **or from `SlideTransitionPauseModal` (Story 2-65/BR-10)**, and in
every case it unconditionally overwrites `pauseReason` to `'intervention'` with no memory of what
it was before. `AskTutorPanel.tsx`'s only way out before submitting is a "Resume without asking"
button that calls `play()` directly — which **always** resumes playback, with no path back to
whatever pause the student was actually in when they clicked Ask Tutor. Concretely: a student
paused at a slide transition (deciding whether to click Next) who curiously clicks Ask Tutor, then
wants to back out, is forced straight into `PLAYING` — skipping the deliberate pause/Next moment
they were in the middle of. That is a real side effect a genuine "cancel" must not have, not just a
labeling problem.

## Design

New store field `preInterventionPauseReason: PauseReason` (reuses the existing `PauseReason` type,
`null` meaning "was `PLAYING`, not paused, when Ask Tutor was clicked"). `pauseForIntervention()`
captures the current `pauseReason` into it before overwriting to `'intervention'`. A new action,
`cancelIntervention()`, is the real "back out" path: if `preInterventionPauseReason` is `null`, it
behaves exactly like today (`play()`, resume) — the student asked while playing, so there is
nothing to "go back" to except playing. Otherwise, it restores `status: 'PAUSED'` with the
captured prior `pauseReason` **without** touching `pauseReason` to `null` first, so
`SlideTransitionPauseModal` (or the normal paused-player UI, for a prior manual pause) remounts
exactly as it was.

**Deliberately unchanged**: the post-*submission* "Continue" button still calls `play()` directly,
not `cancelIntervention()` — after actually asking and getting a response, resuming the lesson
normally is the correct next step, not returning to a stale pre-question pause screen. Only the
pre-submission "cancel" path changes. The error-path `catch` (API unavailable) also still calls
`play()` directly, unchanged — a failed submission degrading straight to "keep playing" is the
existing, correct never-strand-the-student behavior, and re-showing the modal it can't submit to
again isn't obviously better.

The pre-submission button is relabeled from "Resume without asking" to **"Cancel"** — the old label
asserted an outcome ("resume") that is no longer always true once it can also restore a paused
state; "Cancel" is accurate regardless of destination.

## Acceptance Criteria

- **AC1** — New `preInterventionPauseReason: PauseReason` state field, initialized to `null`, reset
  to `null` in `loadLesson()` and `advanceSegment()` (mirrors `skipTransitionPauseForSegment`'s own
  existing per-segment/per-lesson reset convention), and defensively cleared by `play()`.
- **AC2** — `pauseForIntervention()` captures the pre-call `pauseReason` into
  `preInterventionPauseReason` in the same `set()` call that switches to `'intervention'` — no
  intermediate render can observe a mismatched pair.
- **AC3** — New `cancelIntervention()` action: if `preInterventionPauseReason === null`, calls
  `play()` (unchanged resume behavior). Otherwise, sets `status: 'PAUSED'`,
  `pauseReason: preInterventionPauseReason`, and clears `preInterventionPauseReason` back to
  `null` — restoring the exact prior pause, not merely "some" paused state.
- **AC4** — `AskTutorPanel.tsx`'s pre-submission exit button calls `cancelIntervention()` (not
  `play()`), relabeled "Cancel".
- **AC5** — Canceling out of an Ask-Tutor pause that was entered from a slide-transition pause
  re-mounts `SlideTransitionPauseModal` (verified via a `Player.test.tsx` integration test, not
  just the store action in isolation) — the concrete scenario from the user's own report.
- **AC6** — Canceling out of an Ask-Tutor pause entered from `PLAYING` (no prior pause) resumes
  playback exactly as before this story — a regression guard, since this is the one path whose
  observable behavior must NOT change.
- **AC7** — The post-submission "Continue" button and the error-path `catch` are both confirmed
  unchanged (still call `play()` directly) — explicit tests, not just absence-of-a-diff.
- **AC8** — `tsc --noEmit` and targeted `eslint` clean; full frontend suite green, zero
  regressions.

## Scale & Load

N/A for all six questions — one new client-side-only state field capturing a single enum value
already in scope (`pauseReason`, itself a closed 4-value union), reset on the same existing
per-segment/per-lesson boundaries `skipTransitionPauseForSegment` already uses. No new network
call, no new query, no concurrency-sensitive sequence (single-client React state).

## Dev Notes

- `player.machine.ts:247-259` (`pauseForIntervention`) and the store's `play()`/`loadLesson()`/
  `advanceSegment()` are the only places touched in the store.
- `AskTutorPanel.tsx`'s pre-submission view is the only UI touched — the post-submission
  ("submitted") view and its "Continue" button are unchanged.
- `SlideTransitionPauseModal.tsx` itself needs no changes — it already mounts/unmounts purely off
  `status === 'PAUSED' && pauseReason === 'slide-transition'`, so restoring that exact pair via
  `cancelIntervention()` is sufficient to bring it back with no new wiring.

## Dev Agent Record

### Completion Notes

- `player.machine.ts`: added `preInterventionPauseReason: PauseReason` (default `null`), reset to
  `null` in `loadLesson()`, `play()`, and `advanceSegment()`. `pauseForIntervention()` now captures
  the pre-call `pauseReason` into it in the same `set()` that overwrites to `'intervention'`, guarded
  by `pauseReason !== 'intervention'` so a defensive double-call can't clobber the captured value with
  `'intervention'` itself (self-found while writing tests, not reachable through the real UI today
  since `canAskTutor` already excludes it). New `cancelIntervention()` action: `play()` when
  `preInterventionPauseReason === null`, otherwise restores `status: 'PAUSED'` +
  `pauseReason: preInterventionPauseReason` and clears the captured field back to `null`.
- `AskTutorPanel.tsx`: pre-submission exit button now calls `cancelIntervention()` and is relabeled
  "Cancel". Post-submission "Continue" and the error-path `catch` both deliberately still call
  `play()` directly, unchanged (AC7).
- Tests: `player.machine.test.ts` gained a dedicated `cancelIntervention` describe block (10 tests,
  covering AC1/AC2/AC3/AC5/AC6 plus the double-call regression guard) — 94/94 passing.
  `AskTutorPanel.test.tsx`'s old "Resume without asking" test was replaced with an equivalent
  "Cancel" test plus new AC4 (slide-transition and manual restore) and AC7 (Continue / catch
  unchanged) coverage — 11/11 passing. `Player.test.tsx` gained the AC5 integration test: full
  `Player` render → slide-transition pause → modal's Ask Tutor → `AskTutorPanel` mounts → its Cancel
  button → `SlideTransitionPauseModal` re-mounts, `status`/`pauseReason` back to
  `PAUSED`/`'slide-transition'` — 60/60 passing.
- Verification: `tsc --noEmit` clean, targeted `eslint` clean on all 5 touched files, full suite
  green — 95 files / 1269 tests, zero regressions (baseline was 95 files / 1254 tests before this
  story; net +15 new tests).

### File List

- `apps/web/src/stores/player.machine.ts`
- `apps/web/src/components/player/AskTutorPanel.tsx`
- `apps/web/src/__tests__/stores/player.machine.test.ts`
- `apps/web/src/__tests__/components/player/AskTutorPanel.test.tsx`
- `apps/web/src/__tests__/components/player/Player.test.tsx`

## References

- [Source: apps/web/src/stores/player.machine.ts:247-259] — `pauseForIntervention()`, the
  unconditional overwrite this story fixes
- [Source: apps/web/src/components/player/AskTutorPanel.tsx] — "Resume without asking" button
- [Source: docs/stories/2-65-slide-transition-pause-modal.md] — the modal this bug is most visibly
  reachable from
- User feedback, 2026-09-18: "there is not way to go back in popup modal's ask tutor. once clicked
  ask tutor, no option to abort that or cancelled."
