---
baseline_commit: c3cd81e
---

# Story 2.39: Wire the real server-minted session_id (D18 AC-6 / D35)

Status: review

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

- [x] Task 1 (AC: 1): Remove `crypto.randomUUID()` from `loadLesson()`; `sessionId` resets to `''`.
  - [x] 1.1 RED: failing test asserting `sessionId === ''` immediately after `loadLesson()`, before any session-creation call resolves.
  - [x] 1.2 GREEN: implement.
- [x] Task 2 (AC: 2): Add `createSession()` to `lib/assessment.ts`, typed against the real `SessionCreated` schema.
  - [x] 2.1 RED, 2.2 GREEN.
- [x] Task 3 (AC: 3, 4): Wire `createSession()` into `Player.tsx`'s existing mount effect; call `setSessionId()` on success, log-and-swallow on failure.
  - [x] 3.1 RED: tests for once-per-mount, not-per-segment, not-on-unrelated-rerender, and the failure path.
  - [x] 3.2 GREEN: implement.
- [x] Task 4 (AC: 6): Full `apps/web` suite green; `tsc --noEmit` clean; `eslint` clean on every touched file.

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
| 2026-07-30 | Implemented all 4 tasks. Full suite 55 files / 575 tests passing, `tsc --noEmit` clean, `eslint` clean. | Dev 2 |

## Dev Agent Record

### Implementation Plan

- Fetched PR #119's actual branch (`git fetch origin pull/119/head`) rather than trusting the PR description's paraphrase, and read the real `SessionCreated`/`SessionCreate` Pydantic schemas and the router's exact path/method directly, since PR #119 is still open (pending Dev 3 review) and its exact contract is what this story's frontend code has to match.
- `loadLesson()`: replaced `sessionId: crypto.randomUUID()` with `sessionId: ''`, matching the store's own existing empty-string convention for "not yet available."
- `lib/assessment.ts`: added `createSession()` + `SessionCreated`/`CreateSessionPayload` types, matching the real backend schema field-for-field.
- `Player.tsx`: extended the existing `loadedLessonIdRef`-guarded mount effect (the same one that already calls `loadLesson()`/`restoreProgress()` once per `lesson_id`) with a `createSession(...).then(setSessionId).catch(console.error)` call — no new ref/guard needed since it piggybacks on the guard already there.
- Hit a real test-suite-wide issue while writing tests: `Player.test.tsx`'s existing 30 tests all call bare `render(<Player .../>)` without awaiting anything, and the new session-creation promise resolving asynchronously (updating `sessionId` via Zustand) after each test's synchronous assertions fired an "update not wrapped in act()" React warning on every single one. Root-caused and fixed properly rather than suppressing: changed the shared `apiPostMock`'s default mock for `/assessment/sessions` to a permanently-pending `Promise` (so tests that don't care about the real session id never trigger the async update at all), and added a small `resolveSessionCreation()` test helper that the 3 tests which specifically need a resolved id (mine, plus 2 pre-existing tests -- the WebSocket-mount test and one tab_switch test, both of which needed a truthy `sessionId`) call explicitly.
- Two pre-existing tests needed small, deliberate updates as a direct, expected consequence of `sessionId` becoming asynchronous: the WebSocket-mount test now awaits resolution before asserting (`toHaveBeenLastCalledWith` instead of `toHaveBeenCalledWith`, since the hook is now legitimately called twice -- once with `null`, once with the resolved id), and one tab_switch test now awaits session resolution first, since `trackEvent` correctly no-ops without a real `sessionId` and the test was previously exploiting the fact that `sessionId` used to be synchronously available.

### Completion Notes

- All 4 tasks complete, all ACs (1-6) satisfied.
- Full `apps/web` test suite: 55 files, 575 tests (567 baseline + 8 new: 2 in `player.machine.test.ts`, 2 in `assessment.test.ts`, 4 in `Player.test.tsx`), all passing, zero act() warnings.
- `tsc --noEmit`: clean. `eslint`: clean on every touched file.
- This closes D18/D35 from Dev 2's side. The backend half (PR #119) is still pending Dev 3's review as of this story's completion -- until that merges, `POST /api/assessment/sessions` doesn't exist on `main` yet, so this frontend code will 404 until PR #119 lands. That is expected and matches this codebase's established anti-deadlock pattern (build against a documented, stable contract before the other side's PR merges).

### File List

- `apps/web/src/stores/player.machine.ts` (MODIFIED -- `loadLesson()` no longer invents a client-side session id; updated stale doc comments on `sessionId`/`setSessionId`)
- `apps/web/src/lib/assessment.ts` (MODIFIED -- added `createSession()`, `CreateSessionPayload`, `SessionCreated`)
- `apps/web/src/components/player/Player.tsx` (MODIFIED -- mount effect now calls `createSession()` once per lesson and `setSessionId()` on success)
- `apps/web/src/__tests__/stores/player.machine.test.ts` (MODIFIED -- `loadLesson` resets `sessionId` to `''`; new `setSessionId` describe block)
- `apps/web/src/__tests__/lib/assessment.test.ts` (MODIFIED -- new `createSession` describe block)
- `apps/web/src/__tests__/components/player/Player.test.tsx` (MODIFIED -- `apiPostMock` now branches by URL with a never-resolving default for `/assessment/sessions`; new `resolveSessionCreation()` helper; new describe block for session-creation wiring; 2 pre-existing tests updated for the new async `sessionId` timing)
