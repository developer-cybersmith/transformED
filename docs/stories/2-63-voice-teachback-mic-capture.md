---
title: "Story 2-63 — Voice Teach-Back: Mic Capture UI (BR-6)"
status: done
owners: [Dev 2]
sprint: bug-resolution
---

# Story 2-63 — Voice Teach-Back: Mic Capture UI (BR-6)

## Problem Statement

Teach-back is currently typed-only (`TeachBackModal.tsx`). BR-6 (`docs/dev2-sprint-tracker.md`) asks
for mic capture UI, recording + upload, and a toggle between typed/voice input.

This was blocked on an STT node whose ownership was inconsistently attributed across all 4 devs'
own trackers. Confirmed 2026-09-11: **Dev 3 already built and merged it** — Story F2-4
(`docs/stories/f2-4-voice-teachback-stt.md`, PR #197, merged to `main` 2026-09-04). The real backend:

- `POST /assessment/teachback/{session_id}/{segment_id}/audio` — multipart `UploadFile` named
  `audio`, accepts WAV/MP3/MP4/WEBM, JWT-authenticated.
- Transcribes via `WhisperProvider`, feeds the transcript into the existing `grade_teachback()`
  scorer — same `TeachbackResult` response shape as the typed endpoint, no schema change.
- On transcription failure: HTTP 200 with `score_source="fallback"` (never a 500, never blocks the
  student).
- File size capped at `settings.stt_max_file_mb` (25 MB default) — explicit HTTP 413 past that, not
  silent truncation.
- Raw audio never persisted (DPDP data-minimisation).

This story is BR-6's remaining half: the frontend recording UI that calls this real, already-shipped
endpoint.

## Acceptance Criteria

- **AC1** — `TeachBackModal` gains a Type/Record toggle (two tab-style buttons), defaulting to
  **Type** — every existing typed-mode test (auto-focus, submit-disabled-until-text, Skip, submit
  payload shape, result view, no-timer, failure handling, empty-sessionId guard, focus-ring a11y)
  passes unmodified, because the default render path is byte-for-byte the same as before this story.
- **AC2** — The Record tab is **not rendered at all** when the browser lacks `MediaRecorder` or
  `navigator.mediaDevices.getUserMedia` (feature-detected via a new exported
  `isVoiceRecordingSupported()`) — explicit degradation to typed-only, not a broken/dead button.
- **AC3** — New `VoiceTeachBackRecorder` component implements a state machine: `idle` (Start
  Recording button) → `requesting` (mic permission prompt in flight) → `recording` (Stop button,
  non-numeric pulsing indicator — see AC4) → `recorded` (audio preview via `<audio controls>`,
  Re-record and Submit Recording buttons). Mic permission denial or absence lands on a
  `permission-denied` state with an inline message; it never dead-ends the student — the Type tab
  stays available throughout.
- **AC4 — No timer, of any kind, anywhere in this UI.** CLAUDE.md: *"No teach-back timer — creates
  test anxiety."* The existing test `TeachBackModal — has no timer element of any kind` (regex
  `/\d+:\d{2}/` against the whole container) already guards the default Type view; this story's new
  Record view must independently satisfy the same constraint — no live elapsed-time countdown or
  clock, in any status.
- **AC5 — A generous, non-live recording ceiling, explicit not silent.** Recording auto-stops at a
  fixed `MAX_RECORDING_MS` (5 minutes) — chosen with headroom under Whisper's 25 MB/~100 min API
  limit at typical browser bitrates, and far beyond any real teach-back explanation. This is an
  explicit, surfaced degradation per `docs/SCALE-CONTRACT.md` §2 (a one-time notice shown after
  auto-stop, in the `recorded` state — "Recording stopped automatically after 5 minutes" — never a
  live countdown, which would violate AC4), not silent truncation.
- **AC6** — Recording uses `MediaRecorder.isTypeSupported()` to prefer `audio/webm;codecs=opus` →
  `audio/webm` → `audio/mp4`, falling back to the browser's own default if none match or the check
  itself throws — matches this codebase's existing fallback-chain idiom (TTS provider chain), never
  a hard failure on mimeType selection.
- **AC7** — New `submitTeachBackAudio()` (`lib/assessment.ts`) posts the recorded `Blob` as
  multipart `FormData` (field name `audio`) to the real endpoint above, with no explicit
  `Content-Type` header (matches `uploadService.uploadLesson`'s established pattern — axios must
  generate its own multipart boundary). Returns the same `TeachBackResult` shape the typed path
  already uses; `TeachBackModal`'s existing result view is reused unmodified for both submission
  paths.
- **AC8** — `TeachBackResult` (`lib/assessment.ts`) gains `score_source: 'llm' | 'fallback' |
  'skipped'`, matching the real backend `TeachbackResult.score_source` field (already present
  server-side since Story F2-2/F2-4) — accurate typing, no new UI branch built on it (out of scope;
  the existing feedback text already covers the fallback case server-side).
- **AC9** — The mic stream is always released (`track.stop()`) as soon as it's no longer needed —
  on recording stop, re-record, submission, or component unmount — never left running with the
  browser's mic-in-use indicator lit after recording ends.
- **AC10** — A successful voice submission fires the same `teachback_submitted` PostHog event the
  typed path already fires, with an added `source: 'voice'` property — **the existing typed-path
  capture call is not modified** (still exactly `{lesson_id, segment_id}`, no `source` field), so
  the existing exact-match test on that call stays green unmodified. This is a deliberate asymmetry,
  not an oversight: adding `source` to the typed call would require touching an already-passing,
  exact-match test that AC1 requires to stay untouched.
- **AC11** — New tests for `VoiceTeachBackRecorder` (permission grant → record → stop → preview →
  submit; permission denial → inline message, Type tab still reachable; unsupported browser → tab
  hidden; stream released on stop/unmount; MIME type preference order) and for the toggle + voice
  submission wiring in `TeachBackModal` (toggle switches views; voice submission calls
  `submitTeachBackAudio` with the right ids; result view reused; `teachback_submitted` fires with
  `source: 'voice'`).
- **AC12** — `tsc --noEmit` and targeted `eslint` clean; full frontend suite green, zero regressions.

## Scale & Load

1. **Unit of work and range.** One recorded `Blob` per submission. Min: a few KB (a very short
   clip). Typical: 30s–2min voice explanation at browser-default Opus bitrate (~24–32 kbps) ≈
   100KB–1MB. Max: bounded by AC5's 5-minute auto-stop, which at a generous upper-bound bitrate
   (128 kbps) is ≈ 4.8MB — comfortably under the backend's own 25MB/`stt_max_file_mb` cap (Story
   F2-4 AC2), so the client-side cap can never itself trigger the backend's 413.
2. **Fixed budgets vs. variable input.** `MAX_RECORDING_MS` (5 min) is the one fixed budget here,
   against a variable "how long the student talks" input. Behavior past it: explicit auto-stop +
   a surfaced one-time notice (AC5) — never a silent cutoff, never a live countdown (AC4).
3. **Scope of limits.** `MAX_RECORDING_MS` is a client-side, per-recording-session constant — no
   per-user or per-deployment state involved.
4. **Unbounded reads/writes.** None — no DB/network call from this component beyond the single
   `submitTeachBackAudio()` POST per submission, already scale-audited on the backend side (Story
   F2-4's own Scale & Load section).
5. **Inherited caps re-derived.** `MAX_RECORDING_MS` is newly derived here specifically against
   Story F2-4's already-stated 25MB backend cap and Whisper's real API limit — not inherited from
   an unrelated earlier design.
6. **Check-then-act under concurrency.** N/A — one recording session belongs to one student's one
   browser tab; no shared mutable state, no concurrent-request race.

## Dev Notes

- Reuses `FOCUS_RING` (`lib/a11y/focusRing.ts`) for every new interactive element, matching
  `TeachBackModal`'s own existing a11y convention (Story 2-55).
- Reuses `uploadService.uploadLesson`'s established multipart-upload idiom (`services/upload.service.ts`)
  — no explicit `Content-Type` header on a `FormData` body.
- Mic-permission test pattern mirrors `useAttentionMonitor.test.ts`'s existing
  `Object.defineProperty(navigator, 'mediaDevices', ...)` convention — the established way this
  codebase mocks `getUserMedia` under jsdom, since real camera/mic access cannot run under vitest
  (# MOCK-CONTRACT, same class of boundary as that hook's own tests).
- Does **not** touch `apps/api` at all — the backend is Story F2-4's, already merged. This story is
  frontend-only (`apps/web`).
- Does **not** build any UI differentiated on `score_source` — AC8 adds accurate typing only; the
  existing `feedback` text already covers the fallback case server-side, and inventing a new UI
  branch for it here would be scope creep beyond what BR-6 asks for.

## Dev Agent Record

### Completion Notes

- **AC1-DONE.** `TeachBackModal` gains an `inputMode` state defaulting to `'typed'`; every
  pre-existing test (13) passes unmodified — the default render path is byte-for-byte the same as
  before this story.
- **AC2-DONE.** New `isVoiceRecordingSupported()` (exported from `VoiceTeachBackRecorder.tsx`)
  feature-detects `MediaRecorder` + `navigator.mediaDevices.getUserMedia`; the Type/Record toggle is
  only rendered when it returns `true`. jsdom's default test environment has neither, so all
  pre-existing tests see no toggle at all with zero mocking required.
- **AC3-DONE.** `VoiceTeachBackRecorder` implements the full state machine (`idle` → `requesting` →
  `recording` → `recorded`, plus `permission-denied`) exactly as specified. Permission denial shows
  an inline message and keeps "Start Recording" available to retry — never a dead end.
- **AC4-DONE.** No timer/countdown anywhere in either the recording or recorded states — a
  non-numeric pulsing dot signals "recording is live." Verified by a dedicated regex test
  (`/\d+:\d{2}/`) mirroring the existing typed-view guard test exactly.
- **AC5-DONE.** `MAX_RECORDING_MS = 5 * 60 * 1000` auto-stops recording; a one-time notice
  ("stopped automatically after 5 minutes") appears in the `recorded` state — never a live
  countdown. Verified with `vi.useFakeTimers()`.
- **AC6-DONE.** `pickSupportedMimeType()` tries `audio/webm;codecs=opus` → `audio/webm` →
  `audio/mp4` via `MediaRecorder.isTypeSupported()`, falling through to the browser default
  (`undefined` options) if none match or the check throws.
- **AC7-DONE.** `submitTeachBackAudio()` posts the recorded `Blob` as multipart `FormData` (field
  `audio`) to `POST /assessment/teachback/{session_id}/{segment_id}/audio` — no explicit
  `Content-Type` header, matching `uploadService.uploadLesson`'s established pattern. Returns the
  same `TeachBackResult`; the existing result view is reused with zero changes.
- **AC8-DONE.** `TeachBackResult.score_source: 'llm' | 'fallback' | 'skipped'` added, matching the
  real backend field exactly. No new UI branch built on it, per the story's own stated scope.
- **AC9-DONE.** `releaseStream()` called on recording stop, re-record, and component unmount
  (cleanup effect) — verified by a dedicated test asserting the mock track's `stop()` is called.
- **AC10-DONE.** Voice submission fires `teachback_submitted` with an added `source: 'voice'` via
  its own separate `posthog.capture()` call in `handleAudioSubmit` — the typed path's existing
  capture call in `handleSubmit` is untouched, so its pre-existing exact-match test
  (`{lesson_id, segment_id}`, no `source` field) passes unmodified.
- **AC11-DONE.** 15 new tests in `VoiceTeachBackRecorder.test.tsx` (state machine, mic release,
  mime-type preference, permission denial, auto-stop, no-timer guard) + 7 new tests in
  `TeachBackModal.test.tsx` (toggle rendering/switching, voice submission wiring, shared result
  view, `source: 'voice'` capture, graceful failure handling).
- **AC12-DONE.** `tsc --noEmit` clean, targeted `eslint` clean (one pre-existing unused-directive
  warning found and removed during implementation, not shipped). Full frontend suite: 94 files /
  1231 tests (was 93/1209 pre-story), zero regressions.
- **Test-infra note, not an AC**: two testing-library/jsdom gotchas were hit and fixed during RED
  phase — (1) stubbing the whole `URL` global via `vi.stubGlobal` raced against
  `@testing-library/react`'s own cleanup-on-unmount timing (jsdom has no real
  `createObjectURL`/`revokeObjectURL` to fall back to); fixed by assigning directly onto the real
  `URL` constructor instead of replacing it wholesale. (2) `userEvent` under `vi.useFakeTimers()`
  deadlocked even with `delay: null`; fixed by using `fireEvent.click` + explicit microtask flushes
  for the one test that needed both a click and fake-timer advancement in the same test.

### File List

- `apps/web/src/components/player/VoiceTeachBackRecorder.tsx` (new)
- `apps/web/src/__tests__/components/player/VoiceTeachBackRecorder.test.tsx` (new)
- `apps/web/src/lib/assessment.ts`
- `apps/web/src/components/player/TeachBackModal.tsx`
- `apps/web/src/__tests__/components/player/TeachBackModal.test.tsx`

## References

- [Source: docs/dev2-sprint-tracker.md — BR-6] — the task itself, its now-resolved dependency
- [Source: docs/stories/f2-4-voice-teachback-stt.md] — the real backend this story consumes
- [Source: apps/api/app/modules/assessment/router.py — submit_audio_teachback] — the real endpoint
  contract (path, field name, accepted formats, response model)
- [Source: apps/web/src/hooks/useAttentionMonitor.ts + its test file] — existing
  `getUserMedia`/media-stream lifecycle and test-mocking precedent this story follows
