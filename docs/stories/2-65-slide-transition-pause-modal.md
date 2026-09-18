---
title: "Story 2-65 — Slide-Transition Pause: Popup Modal (BR-10)"
status: done
owners: [Dev 2]
sprint: bug-resolution
---

# Story 2-65 — Slide-Transition Pause: Popup Modal (BR-10)

## Problem Statement

Direct user feedback: the slide-transition pause (Story 2-57/BR-5, extended in its 2026-09-07
follow-up) currently surfaces only as a small, non-blocking pill in the bottom-right corner
(`data-testid="slide-transition-pause-pill"`, `Player.tsx`) — "the toast at bottom." The user wants
a real popup modal (centered, matching this codebase's existing `TeachBackModal`/`AskTutorPanel`/
`QuizOverlay` overlay pattern) that appears when the slide changes, containing: the **Next**
button, the **"Skip pause for this segment"** checkbox, and **Ask Tutor**.

## Design

**Replaces** the pill entirely with a new `SlideTransitionPauseModal.tsx`, mounted under the exact
same condition the pill used (`status === 'PAUSED' && pauseReason === 'slide-transition'`), inside
the same "slide area" `relative flex-1 min-h-0` container in `Player.tsx` — same `absolute inset-0`
scoping `QuizOverlay`/`TeachBackModal`/`AskTutorPanel` already use, so it overlays only the slide
area, not the transport bar (`PlayerControls`) below it.

**Consolidation decision, made explicit rather than silently guessed:**
- The **"Skip pause for this segment" checkbox** MOVES from `PlayerControls`'s persistent row into
  the modal, exclusively. It was already only meaningful in-context, at the moment of an actual
  pause — showing it at all times (as before) meant asking about a thing that hadn't happened yet.
  Leaving a duplicate copy in both places would show two checkboxes bound to the same store field
  simultaneously whenever the modal is open, which reads as a bug, not a feature.
- **Ask Tutor stays available in `PlayerControls`'s persistent row, unchanged**, AND is offered
  again inside the new modal as a convenience action. Story 2-57's own AC11 explicitly designed
  Ask Tutor to be available "while `PLAYING`, or while already `PAUSED` for any OTHER reason" —
  general-purpose, not tied to a slide transition. Removing it from the persistent controls would
  silently narrow an already-shipped, deliberately-scoped feature the user did not ask to remove.
  Both call the identical `pauseForIntervention()` action, so there is no divergent behavior to
  keep in sync — clicking either one is indistinguishable in outcome.
- **The Next-button icon-swap in `PlayerControls`'s transport button is unchanged.** It's a second,
  redundant way to do exactly what the modal's own Next button does (`play()`) — harmless overlap,
  not a conflict, and removing it wasn't requested.
- **No live countdown/timer of any kind in the modal** — matches this codebase's established
  pattern (`CaptionOverlay`, `VoiceTeachBackRecorder`) of never showing a numeric countdown to the
  student, even outside the teach-back-specific CLAUDE.md rule this pattern originates from. The
  existing 5-second (`DEFAULT_SLIDE_TRANSITION_PAUSE_MS`) auto-resume timer is unchanged and still
  unmounts the modal automatically when it fires (the same `status`/`pauseReason` condition that
  mounts it), exactly as the pill did.

## Acceptance Criteria

- **AC1** — New `SlideTransitionPauseModal.tsx`: centered overlay card (`absolute inset-0 z-20`,
  matching `AskTutorPanel`/`TeachBackModal`'s exact visual pattern — white card, rounded-2xl,
  backdrop-blur), `data-testid="slide-transition-pause-modal"`.
- **AC2** — Contains a "Next" button that calls `play()` — identical outcome to the auto-resume
  timer firing or `PlayerControls`'s existing Next-icon-swap button.
- **AC3** — Contains the "Skip pause for this segment" checkbox, bound to
  `skipTransitionPauseForSegment`/`setSkipTransitionPauseForSegment` (unchanged store fields from
  Story 2-57) — same behavior as before, just relocated.
- **AC4** — Contains an "Ask Tutor" button that calls `pauseForIntervention()` — clicking it
  transitions `pauseReason` to `'intervention'`, which (via the existing, unchanged mount
  condition) unmounts this modal and mounts `AskTutorPanel` in its place.
- **AC5** — `PlayerControls.tsx`'s "Skip pause for this segment" checkbox is removed (moved to
  AC3); its "Ask Tutor" button is unchanged and remains enabled under exactly the same
  `canAskTutor` conditions as before this story.
- **AC6** — `Player.tsx`'s pill (`slide-transition-pause-pill`) is removed entirely, replaced by
  `<SlideTransitionPauseModal />` under the identical mount condition.
- **AC7** — No numeric countdown, timer text, or `role="timer"` element anywhere in the new modal.
- **AC8** — Every pre-existing test asserting the pill's presence/absence is updated to assert the
  modal instead (named explicitly, not silently changed) — the underlying mount-condition logic
  being tested (shows only for `'slide-transition'`, not `'manual'`/`'intervention'`/`PLAYING`) is
  unchanged, only the testid/component under test changes.
- **AC9** — The `PlayerControls` test asserting the skip-pause checkbox there is removed/relocated
  to the new modal's own test file (named explicitly); the Ask-Tutor-in-`PlayerControls` tests are
  otherwise untouched.
- **AC10** — `tsc --noEmit` and targeted `eslint` clean; full frontend suite green, zero
  regressions.

## Scale & Load

N/A for all six questions — pure client-side UI relocation/redesign (one existing pill's content
moved into a new centered overlay, one checkbox relocated from one existing component to another).
No new network call, no new query, no new variable-sized input, no concurrency-sensitive sequence.
The existing 5000ms auto-resume timer (Story 2-57's own already-answered Q2) is unchanged.

## Dev Notes

- Reuses the exact `absolute inset-0 z-20 ... bg-white/80 backdrop-blur-sm` / white rounded-2xl
  card markup already established by `TeachBackModal.tsx` and `AskTutorPanel.tsx` — no new visual
  pattern invented.
- `pauseForIntervention()`, `play()`, `skipTransitionPauseForSegment`, and
  `setSkipTransitionPauseForSegment` are all pre-existing `player.machine.ts` actions/state from
  Story 2-57 — this story wires existing state into new/relocated UI, it does not add new store
  fields.
- `PlayerControls.tsx`'s "Ask Tutor + skip-pause" row (`flex items-center justify-between`)
  collapses to just the Ask Tutor button once the checkbox is removed — reflowed to
  `justify-end` rather than left with an empty flex gap.

## Dev Agent Record

### Completion Notes

- **AC1-DONE.** `SlideTransitionPauseModal.tsx` reuses `AskTutorPanel`/`TeachBackModal`'s exact
  overlay-card markup (`absolute inset-0 z-20`, white rounded-2xl card, backdrop-blur).
- **AC2-DONE.** "Next" button calls `play()` directly.
- **AC3-DONE.** Skip-pause checkbox bound to the pre-existing `skipTransitionPauseForSegment`/
  `setSkipTransitionPauseForSegment` store fields — no new store state.
- **AC4-DONE.** "Ask Tutor" button calls `pauseForIntervention()`; confirmed via a `Player.test.tsx`
  integration test that clicking it inside the modal actually unmounts the modal and mounts the
  real `AskTutorPanel`.
- **AC5-DONE.** Checkbox removed from `PlayerControls.tsx`; its Ask Tutor button and every one of
  its existing `canAskTutor`-gated tests are untouched.
- **AC6-DONE.** Pill removed entirely from `Player.tsx`; a dedicated assertion confirms
  `slide-transition-pause-pill` no longer exists anywhere, not just that the modal is additionally
  present.
- **AC7-DONE.** No timer/countdown text anywhere in the new modal — dedicated regex test.
- **AC8-DONE.** All 4 pill-presence tests in `Player.test.tsx` rewritten to assert the modal
  instead (same underlying mount-condition logic, different testid) — plus one new test covering
  the Ask-Tutor hand-off between the modal and `AskTutorPanel` that didn't exist for the pill
  (the pill was purely informational and had no interactive elements of its own to test a
  transition from).
- **AC9-DONE.** `PlayerControls.test.tsx`'s checkbox test removed with a pointer to its new home;
  all 4 Ask-Tutor-button tests there pass completely unmodified.
- **AC10-DONE.** `tsc --noEmit` clean, targeted `eslint` clean. Full frontend suite: 95 files /
  1254 tests, zero regressions.
- **Real interaction bug found and fixed while writing tests**: `screen.getByRole('button', {name:
  'Ask Tutor'})` throws "multiple elements found" during a slide-transition pause, because
  `PlayerControls`'s persistent Ask Tutor button and the new modal's own Ask Tutor button are BOTH
  rendered and enabled simultaneously (by design — see the Design section's consolidation
  decision) with the identical accessible name. Not a product bug (both buttons doing the same
  thing is intentional), but a real test-authoring trap this story's own new test had to route
  around with `within(modal)` rather than paper over.

### File List

- `apps/web/src/components/player/SlideTransitionPauseModal.tsx` (new)
- `apps/web/src/__tests__/components/player/SlideTransitionPauseModal.test.tsx` (new)
- `apps/web/src/components/player/Player.tsx`
- `apps/web/src/components/player/PlayerControls.tsx`
- `apps/web/src/__tests__/components/player/Player.test.tsx`
- `apps/web/src/__tests__/components/player/PlayerControls.test.tsx`

## References

- [Source: docs/stories/2-57-slide-transition-pause.md] — original pause mechanism, the pill this
  story replaces, and the `PlayerControls` checkbox/Ask-Tutor design this story relocates/reuses
- [Source: apps/web/src/components/player/AskTutorPanel.tsx] — the exact overlay-card visual
  pattern this story's new modal reuses
- [Source: apps/web/src/components/player/Player.tsx] — pill mount site being replaced
- User feedback, 2026-09-18: "we dont have that in slide pause screen yet. what i want is a popup
  modal that shows up when slides changes. not just a toast at bottom that we have now. in that
  modal, add that next button, skip pause checkbox and ask tutor."
