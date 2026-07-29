---
baseline_commit: 5a28343db7be2634cb1a65a2baf8860dc9d2f997
---

# Story 2.34: Browser SpeechSynthesis Fallback for Virtual Playback Clock

Status: done

## Story

As a student on a segment with a recovered narration script but no playable audio (Story 2-31's degrade path),
I want to actually hear the narration spoken aloud instead of sitting through a silent, timed slide advance,
so that the TTS fallback chain's last resort (CLAUDE.md: Sarvam Bulbul v2 → Azure TTS → **Browser Speech**) is genuinely implemented, not just a silent timer with no audio at all.

**Source:** `docs/handoffs/dev2-handoff-2026-07-29.md` §4c (Dev 1, 2026-07-29), explicitly labeled a non-blocking enhancement — "Layer it on the working clock so the clock stays the source of truth for timing and audio can't desync from slides." Requested directly by the user despite the non-blocking label.

Story 2-33 (`docs/stories/2-33-virtual-playback-clock.md`, merged to `main`) built the three-way branch in `AudioTimeline.tsx` and the `setInterval`-based virtual clock that drives `processTimeUpdate` when a segment has a recovered script but no audio. That clock is silent — it advances slides and fires the quiz on schedule, but produces no sound. This story adds the browser's native `SpeechSynthesis` API as supplementary audio in that same branch, with one hard rule carried over from 2-33: **the virtual clock remains the sole timing authority.** Speech is fire-and-forget narration layered on top; it must never drive `processTimeUpdate`, segment advancement, or quiz firing.

## Acceptance Criteria

1. **AC-1** — In `AudioTimeline.tsx`'s existing `!hasAudio && hasScript` branch, when the segment enters `PLAYING` for the first time (mount while already `PLAYING`, or transition into `PLAYING`) and `window.speechSynthesis` exists, speak `segment.narration.script` via a `SpeechSynthesisUtterance`.
2. **AC-2** — If `window.speechSynthesis` is `undefined` (unsupported browser), the feature silently no-ops: the virtual clock ticks exactly as it does today (per Story 2-33), no console warning, no error, no behavior change to timing/slides/quiz.
3. **AC-3** — `SpeechSynthesis` never calls `processTimeUpdate`, `updateAudioPosition`, or any store action that affects segment position/advancement/quiz-firing. It is purely supplementary audio; the `setInterval` clock from Story 2-33 is unmodified and remains the sole timing authority.
4. **AC-4** — When `status` leaves `'PLAYING'` while in virtual-clock mode (`PAUSED`/`QUIZ`/`TEACH_BACK`/`IDLE`/`ENDED`), call `speechSynthesis.pause()` — not `cancel()` — so narration can resume from where it left off rather than restarting from the beginning.
5. **AC-5** — When `status` re-enters `'PLAYING'` for the same segment after a pause (not a segment change), call `speechSynthesis.resume()`. Do not re-call `.speak()` — that would restart the utterance from the beginning.
6. **AC-6** — On segment change (new `segment_id`), or on transitioning out of the `!hasAudio && hasScript` case entirely (`hasAudio` becomes true, or `hasScript` becomes false), call `speechSynthesis.cancel()` to stop any in-progress or paused utterance before the new segment's effect runs — prevents old narration bleeding into a new segment.
7. **AC-7** — On `AudioTimeline` unmount, call `speechSynthesis.cancel()` (effect cleanup).
8. **AC-8** — The speak-effect must not double-speak on unrelated re-renders (e.g., a re-render triggered by an unrelated store field change, or a React strict-mode dev double-invoke). Gate the effect on `[segment?.segment_id, hasAudio, hasScript, status]` and guard against re-speaking the same segment via a ref tracking the last `segment_id` a `.speak()` call was issued for — resuming (AC-5) and re-entering an already-spoken segment on a `PLAYING`-status re-render must not call `.speak()` again.
9. **AC-9** — `utterance.rate` is set from `playbackRate` (store) once, at the moment `.speak()` is called for that segment — not updated continuously mid-utterance (browser TTS engines don't support live rate changes on an in-flight utterance the way `<audio>.playbackRate` does). Document this as a known limitation in Dev Notes rather than attempting a workaround.
10. **AC-10** — Tests cover: browser-unsupported no-op (AC-2), speak-once on entering virtual-clock `PLAYING` (AC-1), `pause()`/`resume()` on status transitions (AC-4/5), `cancel()` on segment change and on unmount (AC-6/7), no double-speak on unrelated re-render (AC-8), rate set from `playbackRate` (AC-9), and confirmation that no test ever observes a call to `processTimeUpdate`/`updateAudioPosition` originating from the speech effect (AC-3). Full `apps/web` suite green, `tsc --noEmit` clean, `eslint` clean on every touched file.

## Tasks / Subtasks

- [x] Task 1 (AC: 1, 2, 3): Add the speech-synthesis effect to `AudioTimeline.tsx`'s virtual-clock branch — support detection, `.speak()` on entering `PLAYING` for a segment, utterance built from `segment.narration.script`.
  - [x] 1.1 RED: failing tests for speak-on-entry and the unsupported-browser no-op.
  - [x] 1.2 GREEN: implement.
- [x] Task 2 (AC: 4, 5): Wire `pause()`/`resume()` to `status` leaving/re-entering `'PLAYING'` for the same segment.
  - [x] 2.1 RED, 2.2 GREEN.
- [x] Task 3 (AC: 6, 7): Wire `cancel()` to segment change, to leaving the `!hasAudio && hasScript` case, and to unmount.
  - [x] 3.1 RED, 3.2 GREEN.
- [x] Task 4 (AC: 8): Add the last-spoken-segment ref guard; verify no double-speak on an unrelated re-render or strict-mode remount.
  - [x] 4.1 RED, 4.2 GREEN.
- [x] Task 5 (AC: 9): Set `utterance.rate` from `playbackRate` at speak-time.
  - [x] 5.1 RED, 5.2 GREEN.
- [x] Task 6 (AC: 10): Full `apps/web` suite green; `tsc --noEmit` clean; `eslint` clean on every touched file.

## Dev Notes

### What NOT to do

- Do NOT let `SpeechSynthesis` drive `processTimeUpdate`, segment advancement, or quiz firing in any way — the Story 2-33 `setInterval` clock is the sole timing authority; this story only adds supplementary audio on top of it. If a reviewer finds any path from a speech event (`onend`, `onboundary`, etc.) into a store timing/advancement action, that's a hard reject.
- Do NOT modify the Story 2-33 virtual-clock `setInterval` effect itself, `processTimeUpdate`, or `handleEnded` — this story only adds a new, independent effect alongside them.
- Do NOT restart narration from the beginning on pause/resume — use `speechSynthesis.pause()`/`resume()`, never `cancel()` followed by a fresh `.speak()`, except on an actual segment change.
- Do NOT call `.speak()` on every render or every virtual-clock tick — gate strictly on segment entry per AC-8's dependency array and ref guard.
- Do NOT touch anything related to speech-to-text or teach-back voice input — this is TTS output only. PRD: "No STT in MVP — typed teach-back only" (unrelated but easy to conflate given "speech" in the name — do not touch `TeachBackModal.tsx`).
- Do NOT implement this for the `hasAudio` branch — real audio already has real sound; this only applies to `!hasAudio && hasScript`.

### Testing standards

jsdom (this project's `vitest.config.ts` test environment) has no native `SpeechSynthesis` implementation. Mock `window.speechSynthesis` (`speak`/`cancel`/`pause`/`resume` as `vi.fn()`) and `window.SpeechSynthesisUtterance` (a `vi.fn()` constructor capturing the `text`/`rate` passed to it) in the test file's `beforeEach`/`afterEach`, restoring the originals afterward — mirrors the existing `window.HTMLMediaElement.prototype.play`/`pause` override pattern already used in `AudioTimeline.component.test.tsx` (lines 7–25) for the real-audio path. For the unsupported-browser test (AC-2), delete `window.speechSynthesis` for that one test and restore it afterward. Use `vi.useFakeTimers()`/`vi.advanceTimersByTime()` for any interaction with the existing virtual clock, matching Story 2-33's established convention.

### References

- [Source: docs/handoffs/dev2-handoff-2026-07-29.md §4c] — the handoff item this story implements.
- [Source: docs/stories/2-33-virtual-playback-clock.md] — the virtual clock this story layers supplementary audio onto; explicitly scoped `SpeechSynthesis` out (see its own "What NOT to do").
- [Source: CLAUDE.md, TTS row] — "Sarvam AI Bulbul v2 → Azure TTS → Browser Speech" fallback chain; this story implements the final tier.
- [Source: apps/web/src/components/player/AudioTimeline.tsx] — current three-way branch (`hasAudio` / `!hasAudio && hasScript` / `!hasAudio && !hasScript`), lines 96–202, the virtual-clock effect (131–188) and duration-setting effect (196–202) this story's new effect sits alongside.

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-29 | Story created from Dev 1's handoff item 4c, explicitly requested despite its non-blocking label. Branch `sprint2/s2-34-speech-synthesis-fallback` off `main`. | Dev 2 |
| 2026-07-29 | Implemented all 6 tasks in a single cohesive effect (plus a dedicated unmount-cancel effect). Full suite 54 files / 555 tests passing, `tsc --noEmit` clean, `eslint` clean. | Dev 2 |
| 2026-07-29 | 3-agent code review (Blind Hunter, Edge Case Hunter, Acceptance Auditor). 3 decision-needed items resolved by user (2 deferred as documented limitations, 1 applied), 7 patch findings applied, 1 pre-existing pattern deferred. Full suite 54 files / 560 tests passing, `tsc --noEmit` clean, `eslint` clean. | Dev 2 |

## Dev Agent Record

### Implementation Plan

- Read the current `AudioTimeline.tsx` (post-S2-33) in full before writing anything, confirming the exact three-way branch, the virtual clock effect, and the duration-setting effect this story's new effect sits alongside — per its own comments, none of that logic needed to change.
- Implemented one cohesive `useEffect` (deps: `[hasAudio, hasScript, segment, status]`) owning the entire SpeechSynthesis lifecycle: early-return when unsupported/not-applicable (AC-2, and the `hasAudio || !hasScript || !segment` case which also `cancel()`s and clears the ref — AC-6's "leaving virtual-clock mode" half); `pause()` when `status !== 'PLAYING'` (AC-4); `resume()` when re-entering `PLAYING` for the *same* segment (tracked via `spokenSegmentIdRef`, AC-5); otherwise `cancel()` (harmless pre-emptive stop, also covers AC-6's "segment change" half) then `speak()` a fresh `SpeechSynthesisUtterance` with `rate` set once from `playbackRate` (AC-9), and updates the ref (AC-1, AC-8's speak-once guard).
- Added a second, `[]`-deps effect solely for AC-7 (cancel on unmount) — kept separate because the main effect's cleanup would otherwise fire on every dependency change (including a `status`-only pause), which must call `pause()`, not `cancel()`.
- Deliberately did NOT touch the S2-33 virtual clock, `processTimeUpdate`, or `handleEnded` — verified AC-3 by asserting `audioPositionMs` stays `0` immediately after mount with no fake timers advanced (the speech effect itself never touches store position/timing actions).
- Followed the same jsdom-mock pattern already established in this file for `window.HTMLMediaElement.prototype.play`/`pause` (S2-26/S2-33): mocked `window.speechSynthesis` and `window.SpeechSynthesisUtterance` per-test via `Object.defineProperty`/direct assignment, restored in `afterEach`.
- One test bug caught and fixed during GREEN, not a production issue: the AC-4 (pause) test initially asserted `cancelMock` was never called across the whole test, but the very first mount legitimately calls a pre-emptive `cancel()` before its first `speak()` (harmless, and also covers AC-6). Fixed by clearing `cancelMock` after the initial render, same as the already-cleared `speakMock`.

### Completion Notes

- All 6 tasks complete, all ACs (1–10) satisfied.
- Full `apps/web` test suite: 54 files, 555 tests (544 baseline + 11 new), all passing.
- `tsc --noEmit`: clean. `eslint`: clean on both touched files.
- Known, documented limitation (AC-9): `utterance.rate` is fixed at speak-time and does not live-update if the student changes `playbackRate` mid-segment — matches the story's explicit scope decision, not a defect.
- **Post-review round:** applied all 7 patch findings — deferred `speak()` behind a `setTimeout(0)` after `cancel()` (Chrome same-tick race), added a swallowing `onerror` handler, extended the support guard to also check `SpeechSynthesisUtterance`, made segment-change `cancel()` unconditional on status (was previously deferred to the next `PLAYING` transition — a real AC-6 gap), changed the effect's dependency array to `segment?.segment_id` per AC-8's literal wording, special-cased `ENDED` to hard-`cancel()` (user's explicit call), and reset `spokenSegmentIdRef` in the unmount-cleanup effect (fixes a React StrictMode dev double-mount edge case). Two decision-needed items (seek resync, long-script truncation) were resolved by the user as documented limitations — no code change, logged in `docs/stories/deferred-work.md`.
- Full `apps/web` test suite after the review round: 54 files, 560 tests (555 + 5 new), all passing. `tsc --noEmit` clean. `eslint` clean (one intentional `react-hooks/exhaustive-deps` suppression, matching existing precedent elsewhere in this codebase, for the deliberate `segment?.segment_id`-only dependency).

### File List

- `apps/web/src/components/player/AudioTimeline.tsx` (MODIFIED — added `spokenSegmentIdRef`, the SpeechSynthesis lifecycle effect, and the unmount-only cancel effect)
- `apps/web/src/__tests__/components/player/AudioTimeline.component.test.tsx` (MODIFIED — new `AudioTimeline — SpeechSynthesis fallback (S2-34)` describe block, 11 tests)

### Review Findings

- [x] [Review][Defer] Seeking within a script-only segment does not resync or restart narration — deferred, documented limitation: user opted to accept the drift rather than restart narration on every seek; no AC covers seek behavior, matches this story's stated scope. [apps/web/src/components/player/AudioTimeline.tsx]
- [x] [Review][Defer] Long narration scripts risk truncation by browser TTS engines (a well-documented ~15s/Chromium behavior) — deferred, documented limitation: user opted to accept as a known limitation rather than implement sentence-chunked queuing now; chunking is a real scope increase beyond this story's stated ACs, logged as a follow-up story candidate. [apps/web/src/components/player/AudioTimeline.tsx]
- [x] [Review][Patch] `ENDED` status should hard-`cancel()` the utterance instead of `pause()` — user's explicit call: the lesson is genuinely over, no reason to ever resume, and canceling frees the speech queue immediately instead of leaving it paused until unmount [apps/web/src/components/player/AudioTimeline.tsx:227-230]
- [x] [Review][Patch] `cancel()` immediately followed by `speak()` in the same tick is a documented Chrome race that can silently drop the new utterance [apps/web/src/components/player/AudioTimeline.tsx:239-245]
- [x] [Review][Patch] Utterance has no `onerror` handler — a TTS engine failure fails completely silently with no observability [apps/web/src/components/player/AudioTimeline.tsx:240-245]
- [x] [Review][Patch] Support guard only checks `window.speechSynthesis`, never `window.SpeechSynthesisUtterance` — throws if only one exists [apps/web/src/components/player/AudioTimeline.tsx:218]
- [x] [Review][Patch] AC-6 violation: `cancel()` is deferred (not fired) when the segment changes while `status !== 'PLAYING'` — only reached on the next `PLAYING` transition, not immediately on segment change as AC-6 requires unconditionally [apps/web/src/components/player/AudioTimeline.tsx:217-247]
- [x] [Review][Patch] AC-8 dependency array uses the whole `segment` object instead of `segment?.segment_id` as the AC literally specifies — functionally equivalent today but fragile against a future store change that recreates `segment` without changing `segment_id` [apps/web/src/components/player/AudioTimeline.tsx:247]
- [x] [Review][Patch] React StrictMode dev double-invoke can silently prevent narration from ever speaking on mount — the unmount-only cleanup effect's `cancel()` fires between the dev double-mount's two passes, but `spokenSegmentIdRef` isn't reset, so the second pass calls a no-op `resume()` on an already-canceled queue instead of a fresh `speak()` [apps/web/src/components/player/AudioTimeline.tsx:250-256]
- [x] [Review][Defer] `utterance.rate` is unclamped [apps/web/src/components/player/AudioTimeline.tsx:279] — deferred, pre-existing: mirrors the identical unclamped pattern already used for real `<audio>.playbackRate` elsewhere in this same file; not a regression unique to this story.
