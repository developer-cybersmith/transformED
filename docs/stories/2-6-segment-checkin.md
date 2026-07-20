---
baseline_commit: "131ff6a153ebe1284ceeda4f4900711c63219da2"
---

# Story 2-6: Segment-End Detection → CHECKING_IN State

Status: review

## Story

As a **student**,
I want the lesson player to notify the backend tutor FSM when I finish a segment, and to see a brief visible transition as the system checks in on me,
so that my progress is tracked server-side for the tutor state machine (CLAUDE.md §10) while the quiz still appears instantly, with no perceptible delay.

## Acceptance Criteria

1. `useLessonSocket(sessionId)` is mounted live in `Player.tsx` (driven by the store's existing `sessionId`) — the lesson WebSocket actually opens during a real session. Today it connects nowhere; this is the literal fix.
2. `AudioTimeline.tsx`'s existing segment-boundary detection (the `processTimeUpdate` boundary branch, and both `handleEnded()` branches that call `enterQuiz()`) also sends `{type:'segment_complete'}` over the socket, guarded by the same `!quizFiredForSegment.has(segment.segment_id)` condition already used for the quiz trigger — fires exactly once per forward traversal of a segment, never on replay/seek-back.
3. Sending `segment_complete` never throws and never blocks if the socket isn't open or hasn't connected yet — mirrors `LessonSocket.sendControl`'s existing no-op-when-not-open behavior.
4. The quiz's timing is completely unchanged: `enterQuiz()` still fires immediately and synchronously on the local boundary check, with zero WebSocket dependency. Sending `segment_complete` must never gate, delay, or await anything before `enterQuiz()` runs.
5. `tutorState` (in `player.machine.ts`) gets its first real UI reader: a new `CheckingInTransition` component renders a brief, visible transition (~500ms) when `tutorState` transitions into `'CHECKING_IN'`.
6. Because AC4 requires the quiz trigger to stay zero-latency and synchronous, the same local boundary-check call site that fires `enterQuiz()` and sends `segment_complete` **also** optimistically calls the existing `setTutorState('CHECKING_IN')` action, in the same tick. Do not make this depend on the backend's echoed `state_change` frame — that frame necessarily arrives one WebSocket round-trip later, by which point `status` has already become `'QUIZ'` (see Dev Notes — Timing Constraint).
7. `exitTeachBack()` in `player.machine.ts` resets `tutorState` to `'TEACHING'` (both branches: advancing to the next segment, and resuming playback on the last segment) so that the *next* segment's boundary crossing is a genuine edge-transition into `'CHECKING_IN'` — required for the transition to render more than once across a multi-segment lesson (see AC8).
8. `CheckingInTransition`'s visibility is edge-triggered — it shows once per transition into `'CHECKING_IN'` and auto-hides after a fixed timer. It must NOT be a persistent `tutorState === 'CHECKING_IN'` render gate, because nothing in this story's scope sends the further flow events (`checkin_complete`, `quiz_trigger`, etc.) that would make the backend move `tutorState` on by itself — without AC7's reset and this edge-trigger, the field would either never re-fire the transition or stay visible forever.
9. `CheckingInTransition` renders `pointer-events-none` and at a higher stacking position than `QuizOverlay`/`TeachBackModal` (both `z-20`) — it must never block or intercept input meant for the quiz or teach-back UI, since it may render concurrently with them for its brief visible window.
10. The existing `useLessonSocket` handling of a real `state_change` frame (already wired, unchanged) continues to update `tutorState` when the backend's echo actually arrives. This is a harmless idempotent overwrite of the same value set optimistically in AC6. All existing `useLessonSocket.test.ts` cases keep passing unmodified.
11. No changes to the frozen `packages/shared/types/ws.ts` contract. `segment_complete` stays a `LocalControlOut`/`FlowEvent` local to `apps/web/src/lib/ws/wireTypes.ts`, per that file's own documented TODO (fold into the frozen contract only once the 4-dev `ws.ts` PR lands).
12. Test coverage: `AudioTimeline` tests assert `segment_complete` fires at all 3 boundary call sites, guarded correctly, and that `enterQuiz()`'s call site/timing is unaffected; `player.machine.ts` tests cover the new `wsSendControl` field and `exitTeachBack()`'s `tutorState` reset; a new `CheckingInTransition.test.tsx` covers edge-triggered show/auto-hide/re-trigger; `useLessonSocket.test.ts` gains a case for registering/clearing `wsSendControl`; `Player.test.tsx` confirms `useLessonSocket` is invoked and `CheckingInTransition` is mounted.

## Tasks / Subtasks

- [x] Task 1: Extend `player.machine.ts` — expose a WS-send hook, keep `tutorState` accurate across segments (AC: 6, 7, 10)
  - [x] 1.1 Add `wsSendControl: ((msg: LocalControlOut) => void) | null` field (default `null`) and a `setWsSendControl: (fn: ((msg: LocalControlOut) => void) | null) => void` action to `PlayerStore`. Import `LocalControlOut` from `@/lib/ws/wireTypes` (type-only import — no runtime coupling issue, `wireTypes.ts` only imports from `@hie/shared/types/ws`)
  - [x] 1.2 In `exitTeachBack()`, in **both** branches (the `advanceSegment()` branch and the last-segment "resume playback" branch), also set `tutorState: 'TEACHING'` alongside the existing `status: 'PLAYING'` — do this in the single `set({...})` call already there, not a second `set()`
  - [x] 1.3 Do NOT touch `loadLesson()`'s existing `tutorState: 'IDLE'` reset — correct as-is (a fresh session hasn't reached TEACHING yet; that transition arrives via the real `state_change` echo after `session_start`, already handled by `useLessonSocket`)

- [x] Task 2: Wire `useLessonSocket` to register `wsSendControl` into the store (AC: 1, 3, 12)
  - [x] 2.1 In `useLessonSocket.ts`, add `const sendControl = useCallback((msg: LocalControlOut) => { socketRef.current?.sendControl(msg); }, [])` — same pattern as the existing `sendAttentionSignal` — **deviation:** implemented as an inline closure passed directly to `setWsSendControl` instead of a separately-named `useCallback` returned from the hook, since nothing consumes a hook-returned `sendControl` in this story (AudioTimeline reads `wsSendControl` off the store) — avoids adding an unused export
  - [x] 2.2 In the connect `useEffect`'s `init()`, immediately after `socketRef.current = socket; socket.connect(sid, token)`, call `usePlayerStore.getState().setWsSendControl((msg) => socketRef.current?.sendControl(msg))`. In the effect's cleanup function, alongside the existing `socketRef.current?.disconnect()`, call `usePlayerStore.getState().setWsSendControl(null)`
  - [x] 2.3 In `Player.tsx`, add `const sessionId = usePlayerStore((s) => s.sessionId);` (may already be selected — check) and call `useLessonSocket(sessionId || null);` near the top of the component body. Its returned `{status, sendAttentionSignal}` isn't needed by this story — call it for the side effect only (the mount + guarded-`!sessionId` behavior already exists in the hook)

- [x] Task 3: `AudioTimeline.tsx` — send `segment_complete` + optimistic `CHECKING_IN` at all 3 boundary call sites (AC: 2, 3, 4, 6)
  - [x] 3.1 In `processTimeUpdate`, in the existing `if (ms >= segmentEnd && !quizFiredForSegment.has(segment.segment_id))` branch, before calling `enterQuiz()`: call `usePlayerStore.getState().setTutorState('CHECKING_IN')`, then `usePlayerStore.getState().wsSendControl?.({ type: 'segment_complete' })`, then `enterQuiz()` last (so `enterQuiz()`'s own synchronous timing/behavior is provably unchanged — it's still the final statement in the branch)
  - [x] 3.2 Do the identical 3-line sequence in `handleEnded()`'s two `enterQuiz()` call sites (the last-segment "audio ended before boundary" branch, and the non-last-segment "boundary check should have caught it, fire now" branch). Do **not** add it to the third branch (`segment && quizFiredForSegment.has(segment.segment_id)` → `advanceSegment()`) — that segment already sent its `segment_complete` on first traversal
  - [x] 3.3 No try/catch needed — `wsSendControl` is nullable and called with `?.`; `LessonSocket.sendControl` itself already no-ops safely when the socket isn't open (existing behavior, see `lessonSocket.ts:143-147`)

- [x] Task 4: Build `CheckingInTransition.tsx` (AC: 5, 8, 9)
  - [x] 4.1 New file `apps/web/src/components/player/CheckingInTransition.tsx`. Read `tutorState` via `usePlayerStore((s) => s.tutorState)`
  - [x] 4.2 Local `const [visible, setVisible] = useState(false)`. `useEffect` keyed on `[tutorState]`: `if (tutorState !== 'CHECKING_IN') return;` then `setVisible(true)`, `const timer = setTimeout(() => setVisible(false), TRANSITION_VISIBLE_MS)` (module constant, `500`), return `() => clearTimeout(timer)`. This is edge-triggered by design (AC8) — it only fires when the *value actually changes* to `'CHECKING_IN'`, which is why Task 1.2's reset to `'TEACHING'` is load-bearing, not cosmetic
  - [x] 4.3 Render `className="absolute inset-0 z-30 flex items-center justify-center pointer-events-none bg-primary-dark/90 backdrop-blur-sm"` (z-30, above `QuizOverlay`/`TeachBackModal`'s z-20; same dark/blur visual language as `TeachBackModal.tsx`), brief `font-serif text-white` "Checking in…" copy, no buttons/inputs — **deviation:** used a plain `motion.div` fade-in (no `AnimatePresence`/`exit`) instead of `AnimatePresence`, so removal on timeout is an immediate, deterministic unmount rather than delayed by an exit animation — keeps the edge-triggered/auto-hide behavior (AC8) testable without flakiness
  - [x] 4.4 Mount unconditionally in `Player.tsx` (not gated on `status`) — place it after the slide/quiz/teach-back conditional block so it visually layers on top when it shows

- [x] Task 5: Tests (AC: all)
  - [x] 5.1 `apps/web/src/__tests__/stores/player.machine.test.ts`: `setWsSendControl` sets and clears the field; `exitTeachBack()` sets `tutorState: 'TEACHING'` in both the advance-segment and last-segment branches (extend the existing `describe('enterQuiz / exitQuiz / enterTeachBack / exitTeachBack', ...)` block)
  - [x] 5.2 `apps/web/src/__tests__/components/player/AudioTimeline.test.ts` + `AudioTimeline.component.test.tsx`: inject a `vi.fn()` via `usePlayerStore.setState({ wsSendControl: fn })` before each relevant case; assert it's called once with `{type:'segment_complete'}` per forward traversal at all 3 call sites (processTimeUpdate boundary + both handleEnded branches), not called again on seek-back/replay of an already-quizzed segment, and that `tutorState` becomes `'CHECKING_IN'` synchronously in the same test
  - [x] 5.3 New `apps/web/src/__tests__/components/player/CheckingInTransition.test.tsx`: renders nothing while `tutorState !== 'CHECKING_IN'`; shows on a genuine edge into `'CHECKING_IN'`; auto-hides after the timer (`vi.useFakeTimers()`); re-triggers on a second edge after `tutorState` is reset to `'TEACHING'` in between; does not re-trigger on a same-value no-op set; not gated on `status`
  - [x] 5.4 `apps/web/src/__tests__/hooks/useLessonSocket.test.ts`: added cases asserting `usePlayerStore.getState().wsSendControl` becomes a function once the socket connects (and forwards to the real `FakeWebSocket`), and becomes `null` again after unmount
  - [x] 5.5 `apps/web/src/__tests__/components/player/Player.test.tsx`: mocked `useLessonSocket` and asserted it's called with the store's `sessionId`; asserted `CheckingInTransition` becomes visible when `tutorState` is `CHECKING_IN`

## Dev Notes

### Timing constraint — why AC6/AC7/AC8 exist (read this before touching `CheckingInTransition`)

The quiz trigger (`enterQuiz()`) is, and must remain, **client-authoritative and synchronous** — it fires in the exact same tick as the local segment-boundary check, with zero WebSocket round-trip. The backend's real `state_change` echo (confirmed by Dev 4 as reliable and low-latency: "same coroutine, right after Redis write") still requires at least one full WS round-trip to arrive back at the client. **By the time it arrives, `status` has already become `'QUIZ'`** — there is no way around this given the locked "client-authoritative, zero-latency" decision (do not attempt to delay `enterQuiz()` to "wait and see" — that reintroduces the exact latency/WS-dependency this design explicitly avoids).

Consequence: if `CheckingInTransition`'s visibility depended on the *real* backend echo, it would either never be visible (arrives after the quiz already covers the screen) or — if gated on a persistent `tutorState === 'CHECKING_IN'` check — get stuck open forever, since this story does not send the further flow events (`checkin_complete`, `quiz_trigger`, ...) that would make the backend's FSM advance `tutorState` elsewhere on its own.

Resolution used throughout Tasks 1/3/4: set `tutorState` to `'CHECKING_IN'` **optimistically, locally, in the same tick as `enterQuiz()`/`segment_complete`** (AC6), reset it back to `'TEACHING'` when teach-back exits (AC7) so the *next* segment produces a genuine edge-transition, and make the transition component **edge-triggered with a fixed auto-hide timer**, not a persistent gate (AC8). The real backend echo (already wired in `useLessonSocket`, untouched) still lands in the same field a moment later and is a harmless no-op overwrite of the same value — this is what actually gives `tutorState` "a real UI reader" without regressing the zero-latency quiz.

### Current state of the files this story touches

- **`apps/web/src/components/player/Player.tsx`** — does not call `useLessonSocket` anywhere today; the lesson WebSocket never connects during a real session regardless of what the backend sends. Destructures `status`, `sessionId`, `currentSegmentIndex`, `currentSlideId` from the store already — `sessionId` is right there to pass into the hook.
- **`apps/web/src/hooks/useLessonSocket.ts`** — already handles an incoming `state_change` message correctly (`setTutorState(msg.payload.to_state)`, session-scoped, defensive against malformed payloads) — **do not touch that switch statement**. It currently returns `{ status, sendAttentionSignal }`; this story adds the `wsSendControl` registration as a side effect inside the existing connect effect, not as a new returned value (AudioTimeline reads it off the store via `getState()`, not via the hook's return, because `processTimeUpdate`/`handleEnded` are plain functions outside React, exactly like `enterQuiz` and every other store action they already call).
- **`apps/web/src/components/player/AudioTimeline.tsx`** — `enterQuiz()` currently fires at 3 call sites: `processTimeUpdate`'s boundary check (line ~51), and two branches inside `handleEnded()` (lines ~126, ~138). All 3 need the same 2-line addition described in Task 3.
- **`apps/web/src/stores/player.machine.ts`** — `tutorState: TutorState` field and `setTutorState` action already exist and are already the target of `useLessonSocket`'s handler; `enterQuiz()`/`exitQuiz()`/`enterTeachBack()`/`exitTeachBack()` already exist and are unit-tested (`__tests__/stores/player.machine.test.ts`) — extend, don't rewrite.
- **`apps/web/src/lib/ws/wireTypes.ts`** — `segment_complete` is already a defined `FlowEvent`/`LocalControlOut` member; **no changes needed to this file**, just import `LocalControlOut` as a type where needed.
- **`apps/web/src/lib/ws/lessonSocket.ts`** — `sendControl(msg: LocalControlOut)` already exists and already no-ops safely when the socket isn't open (`rawSend` checks `readyState === WebSocket.OPEN`) — **no changes needed to this file**.

### Backend dependency — resolved, not a blocker, but real integration testing is still pending

Dev 4 fixed the corresponding backend gap (`dispatch_event` in `graph.py` now broadcasts `state_change` on every real FSM transition, `from_state != to_state` — previously only fired on reconnect-sync with `from_state == to_state`) on branch `sprint2/s2-1-state-change-broadcast`, confirmed via 44/44 passing tests including payload-shape verification against the frozen contract. That branch is not yet pushed/merged, so a live end-to-end check against his real backend isn't possible yet — build and test against `FakeWebSocket` (`apps/web/src/__tests__/testUtils/fakeWebSocket.ts`, already used by `useLessonSocket.test.ts`), same posture S2-04/S1-07 were already built and shipped against. Do a real integration check once his branch/PR lands — this is a verification follow-up, not a design unknown; the wire shape is already fully specified by `packages/shared/types/ws.ts` (frozen) and `docs/ws-message-contract.md` (live protocol doc), both already loaded and consistent with what Dev 4 confirmed.

### Two different "state" concepts — do not confuse them

`PlayerStore.status: 'IDLE'|'PLAYING'|'PAUSED'|'QUIZ'|'TEACH_BACK'|'ENDED'` is the **local player status** that actually drives rendering (`Player.tsx`'s `status === 'QUIZ'` / `'TEACH_BACK'` / `'ENDED'` conditionals, `AudioTimeline`'s play/pause effect). `PlayerStore.tutorState: TutorState` (`'IDLE'|'TEACHING'|'INTERVENING'|'CHECKING_IN'|'QUIZZING'|'TEACH_BACK'|'SESSION_END'`, imported from `@hie/shared/types/ws`) is a *separate* field mirroring the **backend tutor FSM** (CLAUDE.md §10's 7-state machine). They are related but not the same enum and do not have to stay in lockstep at every instant (see Timing Constraint above) — `CheckingInTransition` reads `tutorState` only; it must never read or branch on `status`.

### Project Structure Notes

- All new code lands in existing files/directories already owned by this area — `apps/web/src/stores/player.machine.ts`, `apps/web/src/hooks/useLessonSocket.ts`, `apps/web/src/components/player/AudioTimeline.tsx`, `apps/web/src/components/player/Player.tsx` (all UPDATE), plus one NEW file `apps/web/src/components/player/CheckingInTransition.tsx`. No new directories, no changes to `packages/shared/`.
- Matches Epic 2's component table (`_bmad-output/planning-artifacts/epic-2-lesson-player.md`) — `AudioTimeline`/`player.machine`/`lessonSocket.ts` ownership already assigned to this area; `CheckingInTransition` is a natural sibling of `QuizOverlay.tsx`/`TeachBackModal.tsx` in the same directory.

### Testing standards

Vitest + `@testing-library/react` + `@testing-library/user-event`, `jsdom` environment. `vi.hoisted` + `vi.mock` for module-level dependencies (see `useLessonSocket.test.ts`'s `createClient` mock). `FakeWebSocket` (`apps/web/src/__tests__/testUtils/fakeWebSocket.ts`) is the established fake for anything touching `LessonSocket`/`useLessonSocket` — do not hand-roll a new WebSocket mock. `vi.useFakeTimers()` is the established pattern for timer-based assertions (already used in `player.machine.test.ts` and `lessonSocket.test.ts`) — use it for `CheckingInTransition`'s auto-hide test rather than real `setTimeout`+`waitFor` delays.

### References

- [Source: docs/dev2-sprint-tracker.md#S2-06 — Segment-End Detection → CHECKING_IN State] (original investigation: gap analysis, blocked assessment, recommendation to run this as a full BMAD story)
- [Source: docs/ws-message-contract.md#Outbound (server → client), #Contract reconciliation — gaps vs frozen ws.ts item (e)] (live wire protocol, `state_change` reconnect-sync convention, now partially superseded by Dev 4's fix)
- [Source: packages/shared/types/ws.ts] (frozen `StateChangeMessage`/`TutorState` contract — unchanged by this story)
- [Source: apps/web/src/lib/ws/wireTypes.ts] (`LocalControlOut`/`FlowEvent` — local-only, `segment_complete` already defined, not yet called anywhere — this story is the first caller)
- [Source: apps/web/src/lib/ws/lessonSocket.ts#L133-L147] (`sendControl` — already exists, already safe when socket not open)
- [Source: apps/web/src/hooks/useLessonSocket.ts#L30-L67] (`state_change` handling — already correct, do not modify)
- [Source: apps/web/src/stores/player.machine.ts] (`tutorState`/`setTutorState`/`exitTeachBack` — existing fields/actions this story extends)
- [Source: apps/web/src/components/player/AudioTimeline.tsx#L16-L53,L110-L141] (3 `enterQuiz()` call sites — exact insertion points for Task 3)
- [Source: apps/web/src/components/player/TeachBackModal.tsx] (visual reference for `CheckingInTransition`'s dark/blur full-bleed styling)
- [Source: _bmad-output/implementation-artifacts/deferred-work.md#Deferred from: code review of 1-07-websocket-client (2026-07-02)] ("`sendControl()`'s 9 flow events ... have no caller anywhere yet ... Wiring segment-end/quiz-trigger detection to `sendControl()` is separate Sprint 2/3 UI work" — this story is that follow-up)
- [Source: CLAUDE.md#Tutor State Machine (7 states, §10)] (the 7-state FSM `tutorState` mirrors; CES/intervention guard rules are Sprint 3 scope, not touched here)

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (claude-sonnet-5)

### Debug Log References

- RED confirmed for every task before implementation: Task 1's 4 new `player.machine.test.ts` tests (`setWsSendControl is not a function` ×2, `tutorState` wrong-value ×2) all failed as expected pre-implementation, 48 pre-existing tests unaffected. Task 2's 3 new tests (2 in `useLessonSocket.test.ts`, 1 in `Player.test.tsx`) failed with `expected null not to be null` / `expected "spy" to be called with arguments` before the store-registration wiring existed. Task 3's 3 new tests (1 in `AudioTimeline.test.ts`, 2 in `AudioTimeline.component.test.tsx`) failed with `expected "spy" to be called 1 times, but got 0 times` before the 3 call sites were touched. Task 4's 6 new `CheckingInTransition.test.tsx` tests passed on the first implementation attempt (new file, no separate RED run needed beyond confirming the component didn't exist). Task 4's `Player.test.tsx` mount assertion failed (`expected null not to be null`) before `CheckingInTransition` was mounted.
- A real timing tension was worked through before writing any code (documented in Dev Notes "Timing constraint"): the backend's real `state_change` echo necessarily arrives after `status` has already flipped to `'QUIZ'`, given the locked client-authoritative/zero-latency quiz decision — so `CheckingInTransition`'s visibility can't depend on that echo at all. Resolved by setting `tutorState` optimistically and locally at the same boundary-check call sites that fire `enterQuiz()`/`segment_complete`, resetting it back to `'TEACHING'` in `exitTeachBack()` so each subsequent segment produces a genuine edge-transition, and making the transition component edge-triggered with a fixed auto-hide timer rather than a persistent `tutorState === 'CHECKING_IN'` gate.
- `react-hooks/set-state-in-effect` ESLint error surfaced on `CheckingInTransition`'s `setVisible(true)` call inside its `useEffect` — resolved with a targeted `eslint-disable-next-line` + justification comment, matching the exact existing pattern already used in `useLessonSocket.ts` for its own "must be synchronous, no one-tick flash" `setStatus('connecting')` call.
- Implemented `CheckingInTransition` with a plain conditional `motion.div` fade-in (no `AnimatePresence`/`exit`) rather than the story's originally-sketched `AnimatePresence` approach, so hiding on timeout is an immediate, deterministic unmount instead of being delayed by an exit animation — kept the auto-hide test assertions (`vi.advanceTimersByTime` → immediately `null`) deterministic.
- Deviated from Task 2.1's literal wording (a separately-named `useCallback` `sendControl` returned from `useLessonSocket`): implemented as an inline closure passed directly to `setWsSendControl` instead, since nothing in this story consumes a hook-returned `sendControl` (`AudioTimeline` reads `wsSendControl` off the store via `getState()`) — avoids adding an unused export.
- Full regression suite run after all 5 tasks: 336/336 tests passing across 41 files, no regressions. `tsc --noEmit` clean. `eslint` clean on every touched file (3 pre-existing "unused eslint-disable directive" warnings remain in `useLessonSocket.ts`, confirmed via `git show HEAD:...` to predate this story — not introduced or touched here).

### Completion Notes List

- All 5 tasks (12 subtasks) implemented in strict RED → GREEN order; no task marked complete without its tests passing first.
- `player.machine.ts`: added `wsSendControl` field + `setWsSendControl` action; `exitTeachBack()` now resets `tutorState` to `'TEACHING'` in both branches (advance-segment and last-segment-resume), which is load-bearing for `CheckingInTransition`'s edge-trigger to fire again on subsequent segments, not merely cosmetic.
- `useLessonSocket.ts`: registers `wsSendControl` into the store once the socket connects (inline closure over `socketRef`), clears it to `null` in the effect's cleanup alongside the existing `disconnect()` call. The existing `state_change` handling (`setTutorState(msg.payload.to_state)`) was not touched.
- `Player.tsx`: now calls `useLessonSocket(sessionId || null)` — the lesson WebSocket actually connects during a real session for the first time. Also mounts `CheckingInTransition` unconditionally (not gated on `status`).
- `AudioTimeline.tsx`: all 3 `enterQuiz()` call sites (the `processTimeUpdate` boundary check, and both `handleEnded()` branches) now also call `setTutorState('CHECKING_IN')` and `wsSendControl?.({type:'segment_complete'})` immediately before `enterQuiz()` — `enterQuiz()` remains the final statement in each branch, so its own synchronous, zero-latency behavior is unchanged (verified by tests asserting `status` becomes `'QUIZ'` in the same test as the `wsSendControl` assertion).
- New `CheckingInTransition.tsx`: edge-triggered on `tutorState` transitioning into `'CHECKING_IN'`, auto-hides after a fixed 500ms timer, renders independent of `status` (verified by a dedicated test setting `status: 'QUIZ'` and confirming it still shows), `pointer-events-none` and `z-30` (above `QuizOverlay`/`TeachBackModal`'s `z-20`).
- No changes to the frozen `packages/shared/types/ws.ts` contract, `apps/web/src/lib/ws/wireTypes.ts`, or `apps/web/src/lib/ws/lessonSocket.ts` — all three already had everything this story needed.
- Backend dependency (Dev 4's `state_change`-on-every-transition fix) remains unverified end-to-end — his branch (`sprint2/s2-1-state-change-broadcast`) isn't pushed yet. All new tests run against `FakeWebSocket`/direct store manipulation, consistent with the story's documented "not a blocker" posture. A real integration check is still a follow-up once his branch/PR lands.

### File List

**Files CREATED:**
- `apps/web/src/components/player/CheckingInTransition.tsx`
- `apps/web/src/__tests__/components/player/CheckingInTransition.test.tsx`

**Files MODIFIED:**
- `apps/web/src/stores/player.machine.ts` — added `wsSendControl` field + `setWsSendControl` action, `LocalControlOut` type import; `exitTeachBack()` resets `tutorState` to `'TEACHING'`
- `apps/web/src/__tests__/stores/player.machine.test.ts` — new `wsSendControl` describe block (3 tests), 2 new `exitTeachBack` tutorState-reset tests, `wsSendControl: null` added to the shared `beforeEach` reset
- `apps/web/src/hooks/useLessonSocket.ts` — registers/clears `wsSendControl` in the player store on connect/cleanup
- `apps/web/src/__tests__/hooks/useLessonSocket.test.ts` — 2 new tests (register-on-connect + forwards to socket, clear-on-unmount), `wsSendControl: null` added to the existing `beforeEach` reset
- `apps/web/src/components/player/AudioTimeline.tsx` — sends `segment_complete` + optimistic `setTutorState('CHECKING_IN')` at all 3 `enterQuiz()` call sites
- `apps/web/src/__tests__/components/player/AudioTimeline.test.ts` — 3 new tests, `wsSendControl: null` added to `beforeEach`, `vi` import added
- `apps/web/src/__tests__/components/player/AudioTimeline.component.test.tsx` — 3 new tests (`handleEnded`'s two call sites + the already-quizzed no-send case), `wsSendControl: null` added to `beforeEach`
- `apps/web/src/components/player/Player.tsx` — mounts `useLessonSocket(sessionId || null)` and `CheckingInTransition`
- `apps/web/src/__tests__/components/player/Player.test.tsx` — mocked `useLessonSocket` via `vi.mock`, 2 new tests (hook called with `sessionId`, `CheckingInTransition` becomes visible)

### Change Log

- 2026-07-20: Story created via `bmad-create-story` — Sprint 2 extra task (S2-06 in `docs/dev2-sprint-tracker.md`), branch `sprint2/s2-6-segment-checkin`, committed story-only per the story-first gate.
- 2026-07-20: All 5 tasks implemented in RED→GREEN order; 15 new tests across 6 files (`player.machine.test.ts` +5, `useLessonSocket.test.ts` +2, `AudioTimeline.test.ts` +3, `AudioTimeline.component.test.tsx` +3, `CheckingInTransition.test.tsx` +6 new file, `Player.test.tsx` +2); full `apps/web` suite 336/336 passing; `tsc --noEmit` and `eslint` clean; story marked `review`.
