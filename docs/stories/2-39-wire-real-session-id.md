---
baseline_commit: c3cd81e
---

# Story 2.39: Wire the real server-minted session_id (D18 AC-6 / D35)

Status: ready-for-dev

## Story

As a student completing a lesson,
I want the quiz and teach-back submissions I make to be attributed to a real, backend-created session,
so that they stop 404ing and my session actually shows up in my session report and Learner DNA history.

**Source:** `docs/DEFECT-REGISTER.md` **D18** / **D35**. Dev 1 shipped the backend half — `POST /api/assessment/sessions` (PR #119, Story 2-35, pending Dev 3 review) — and flagged in that PR's own description: *"This does NOT close D18 on its own. AC-6 is Dev 2's and cannot be done here."* D35 (found 2026-07-30 during a frontend wiring audit) names the exact gap: `player.machine.ts:146` still invents `sessionId: crypto.randomUUID()` and nothing ever replaces it with the server's id.

## Acceptance Criteria

1. **AC-1** — `player.machine.ts`'s `loadLesson()` no longer calls `crypto.randomUUID()`. `sessionId` resets to `''` (empty — "no session yet") on every lesson load, matching the store's own existing initial-state convention.
2. **AC-2** — A new `createSession({lesson_id})` function in `lib/assessment.ts` calls `POST /api/assessment/sessions` and returns `{session_id, lesson_id, started_at}`, matching `apps/api/app/modules/assessment/schemas.py::SessionCreated` exactly (verified directly against PR #119's diff, not guessed).
3. **AC-3** — `Player.tsx` calls `createSession()` exactly once per lesson mount — in the same effect, under the same `loadedLessonIdRef` guard, that already calls `loadLesson()` once per `lesson_id`. On success, `setSessionId(session_id)` (an existing, previously-unused store action) is called. **Never call it per-segment** — every call mints a new attempt row server-side, which is intentional (re-learning must produce a new session for CES history per PR #119), but calling it more than once per mount would mint extra, orphaned session rows.
4. **AC-4** — On failure, the error is logged (`console.error`) but does not crash the player or block playback. `sessionId` simply stays `''`; the existing `catch` blocks in `QuizOverlay.tsx`/`TeachBackModal.tsx` already degrade gracefully when a submission fails, unchanged by this story.
5. **AC-5** — No change to `QuizOverlay.tsx`, `TeachBackModal.tsx`, or `submitQuiz`/`submitTeachBack` — they already read `sessionId` from the store and pass it through; once the store holds a real id, submissions work with zero changes on that side.
6. **AC-6** — Tests: `createSession()`'s request/response shape, the once-per-lesson-mount call (not per-segment, not on an unrelated re-render), `setSessionId` being called with the resolved id, and the failure path (logged, non-fatal, `sessionId` stays `''`). Full `apps/web` suite green, `tsc --noEmit` clean, `eslint` clean.

## Tasks / Subtasks

- [ ] Task 1 (AC: 1): Remove `crypto.randomUUID()` from `loadLesson()`; `sessionId` resets to `''`.
  - [ ] 1.1 RED: failing test asserting `sessionId === ''` immediately after `loadLesson()`, before any session-creation call resolves.
  - [ ] 1.2 GREEN: implement.
- [ ] Task 2 (AC: 2): Add `createSession()` to `lib/assessment.ts`, typed against the real `SessionCreated` schema.
  - [ ] 2.1 RED, 2.2 GREEN.
- [ ] Task 3 (AC: 3, 4): Wire `createSession()` into `Player.tsx`'s existing mount effect; call `setSessionId()` on success, log-and-swallow on failure.
  - [ ] 3.1 RED: tests for once-per-mount, not-per-segment, not-on-unrelated-rerender, and the failure path.
  - [ ] 3.2 GREEN: implement.
- [ ] Task 4 (AC: 6): Full `apps/web` suite green; `tsc --noEmit` clean; `eslint` clean on every touched file.

## Dev Notes

### What NOT to do

- Do NOT send `session_id` or `started_at` in the request body — the backend schema deliberately ignores both (DB-generated); sending them changes nothing but signals a misunderstanding of the contract if added.
- Do NOT call `createSession()` per segment or per quiz/teach-back attempt — once per lesson mount only, matching the existing `loadedLessonIdRef` guard `loadLesson()` already uses.
- Do NOT touch `QuizOverlay.tsx`, `TeachBackModal.tsx`, `submitQuiz`, or `submitTeachBack` — they already consume `sessionId` from the store correctly; this story only fixes what populates that field.
- Do NOT block rendering or playback on the session-creation call resolving — it must be fire-and-forget from the player's perspective (log on failure, don't throw, don't show a blocking spinner).

### Testing standards

`apps/web/src/__tests__/components/player/Player.test.tsx` already mocks `@/lib/api`'s `post` (added in the S2-34-adjacent analytics-gap fix) — extend that mock to branch on the request path so `/assessment/sessions` and `/analytics/events` can be asserted on independently, rather than asserting "the mock was never called" (which would now always be false once this story lands, since every mount fires a session-creation call).

### References

- [Source: docs/DEFECT-REGISTER.md D18, D35]
- [Source: PR #119, developer-cybersmith/transformED — `apps/api/app/modules/assessment/router.py`/`schemas.py`, the exact request/response contract this story consumes]
- [Source: apps/web/src/stores/player.machine.ts — `loadLesson()`, `setSessionId` (already exists, previously uncalled)]
- [Source: apps/web/src/components/player/Player.tsx — the existing `loadedLessonIdRef`-guarded mount effect this story extends]

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-30 | Story created to close D18/D35 from the frontend side, following Dev 1's PR #119 (backend session-minting endpoint, pending Dev 3 review). Branch `sprint2/s2-39-wire-real-session-id` off `main`. | Dev 2 |
