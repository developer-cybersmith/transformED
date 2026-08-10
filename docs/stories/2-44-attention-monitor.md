---
baseline_commit: 3601649
---

# Story 2.44: AttentionMonitor Component (MediaPipe) (S3-02)

Status: review

## Story

As a student in an active lesson who has consented to attention tracking,
I want the platform to locally observe my engagement (gaze/head pose, blink rate, on-screen behavior) and report only five small numbers to the tutor — never my video,
so that the tutor state machine can detect distraction/confusion/fatigue and intervene, without my camera feed ever leaving my browser.

**Source:** `docs/dev2-sprint-tracker.md` §S3-02, unblocked 2026-08-06 (dependencies: S3-01 consent gate — done; D29 DPDP consent table — closed via Story 3-32). Branch `sprint3/s3-02-attention-monitor`, cut from `sprint3-master` at `3601649` (not `main`) — this story's hard dependency, `useAttentionConsent.ts` / `AttentionConsentModal.tsx` (Story 2-42), exists only on `sprint3-master` and has not yet been merged to `main`.

**Real dependencies verified directly against source, not taken on faith from the tracker:**

- `apps/web/src/hooks/useAttentionConsent.ts` — the security-relevant consent read. `consentStatus: 'accepted' | 'declined' | 'unknown'` is derived from a **fresh Supabase read on every mount**, keyed on `userId`. `showModal` is explicitly documented as **never** the gate for whether monitoring may start — only `consentStatus === 'accepted'` is. This story calls `useAttentionConsent()` as its **own hook instance** inside `useAttentionMonitor`, so it gets its own fresh mount-time read rather than trusting a value computed by a distant ancestor's render — this satisfies the "fresh read of its own" constraint in that hook's docstring without duplicating the Supabase query.
- `apps/web/src/hooks/useLessonSocket.ts` — already called exactly once, in `Player.tsx:94`, with its return value discarded. It returns `{ status, sendAttentionSignal }` where `sendAttentionSignal` is a stable (`useCallback`, empty deps) function bound to the live socket via a ref. **`useLessonSocket` must never be called a second time** (it opens a real WebSocket connection) — so `AttentionMonitor`, to stay a self-contained/zero-props component matching its Sprint 3 siblings (`TutorInterventionCard`, `CESIndicator`, `AttentionConsentModal`), needs `sendAttentionSignal` exposed through the Zustand player store, mirroring the **existing** `wsSendControl` / `setWsSendControl` pattern (`player.machine.ts:75,116`, registered/cleaned-up inside `useLessonSocket.ts:116,132-134`) — not a new pattern, the same one already solving this exact problem for `LocalControlOut`.
- `apps/web/src/stores/player.machine.ts` — `tutorState: TutorState` (`'IDLE'|'TEACHING'|'INTERVENING'|'CHECKING_IN'|'QUIZZING'|'TEACH_BACK'|'SESSION_END'`) already exists and is kept live: `play()` sets it to `'TEACHING'` optimistically (`player.machine.ts:289`), and real `state_change` WS messages update it afterward via `setTutorState`. CLAUDE.md's tutor guard rule — **"CES monitoring ONLY active in TEACHING state"** — is written in terms of this exact field, not `PlayerStatus`. This story gates on `tutorState === 'TEACHING'`, not `status === 'PLAYING'`, because `tutorState` is the field the rule actually names and the one that reflects the real backend FSM, not just local playback state.
- `packages/shared/types/ws.ts` (frozen) — `AttentionSignalMessage.payload` has exactly 5 fields: `session_id, quiz_accuracy, teachback_score, behavioral_score, head_pose_score, blink_rate`. There is **no `gaze_score` or `expression_label` field on the wire** — the tracker's local-aggregation sketch names 5 locally-computed signals, but only 3 of them (`behavioral_score`, `head_pose_score`, `blink_rate`) are transmittable under the frozen contract. `gaze_score` and `expression_label` are computed locally and folded into `behavioral_score` (see Dev Notes) rather than sent independently — the frozen contract cannot be changed by this story.
- **Package name correction:** the tracker says "Library: `@mediapipe/face_landmarker`" — no such npm package exists. The correct, current package is **`@mediapipe/tasks-vision`**, which exports the `FaceLandmarker` class used via `FaceLandmarker.createFromOptions(...)`. Do not attempt to install the tracker's literal string.

## Acceptance Criteria

1. **AC-1** — `useAttentionMonitor` initializes MediaPipe's `FaceLandmarker` (from `@mediapipe/tasks-vision`) within 3 seconds of `tutorState` becoming `'TEACHING'` — not "lesson start" generically, since `'TEACHING'` is the concrete, code-defined moment that phrase maps to in this codebase.
2. **AC-2** — Camera permission (`getUserMedia`) is requested **only when** `useAttentionConsent().consentStatus === 'accepted'` (never on `showModal`, never on the localStorage dismissal key alone) — matching S3-01's CRITICAL SECURITY CONSTRAINT verbatim.
3. **AC-3** — While `tutorState === 'TEACHING'`, exactly one `AttentionSignalMessage` is sent via the store's `wsSendAttentionSignal` every 5 seconds, with `quiz_accuracy: null` and `teachback_score: null` (filled elsewhere, by `QuizOverlay`/`TeachBackModal` — out of scope here) and computed `behavioral_score`, `head_pose_score`, `blink_rate`.
4. **AC-4** — Monitoring (frame capture + signal sending) **pauses** whenever `tutorState !== 'TEACHING'` (covers `QUIZZING`/`CHECKING_IN`/`INTERVENING`/`TEACH_BACK`/`SESSION_END`/`IDLE`) and **resumes** automatically when it returns to `'TEACHING'` — without tearing down the camera stream or re-initializing the model on every pause (see Dev Notes: teardown is reserved for AC-7).
5. **AC-5** — No raw video frame, canvas image data, or any video/image buffer ever appears in a network request payload. Enforced two ways: (a) a source-level guard test (same style as `AttentionConsentModal.test.tsx`'s AC-4 guard) scanning `useAttentionMonitor.ts`/`AttentionMonitor.tsx` for any `fetch`/`XMLHttpRequest`/`axios`/WebSocket `.send()` call whose argument isn't the typed `AttentionSignalMessage` shape; (b) a runtime test asserting every call to `wsSendAttentionSignal` receives an object with exactly the 6 documented payload keys (`session_id, quiz_accuracy, teachback_score, behavioral_score, head_pose_score, blink_rate`) and no others.
6. **AC-6** — If the MediaPipe WASM bundle fails to load or initialize (network failure, unsupported browser, `createFromOptions` rejects), the hook catches the failure, logs it via `console.error`, sends no signals, and the lesson continues playing uninterrupted — never blocks, crashes, or shows an error overlay in `Player`.
7. **AC-7** — Camera stream tracks are stopped (`MediaStreamTrack.stop()`) and `faceLandmarker.close()` is called when **either** the component unmounts **or** `tutorState` reaches `'SESSION_END'` — whichever happens first. No lingering camera-in-use browser indicator after either event.
8. **AC-8** — `useAttentionMonitor` never initializes (no `getUserMedia` call, no `FaceLandmarker` load) if `consentStatus` is `'declined'` or still `'unknown'`/`isLoading` — consent must resolve to `'accepted'` first.

## Scale & Load

Answering `docs/SCALE-CONTRACT.md`'s six questions, per the BMAD Pre-Implementation Checklist:

1. **Unit of work and range:** one `FaceLandmarker` instance + one open camera stream + one `requestAnimationFrame` detection loop per active lesson session (one per browser tab). Frame processing is local-only (~30fps, never network-bound); network unit of work is exactly one `AttentionSignalMessage` per 5-second window while `tutorState === 'TEACHING'`. Range: bounded by lesson/segment duration — the tracker's own lessons run an estimated 5–15 min per segment; a full multi-segment chapter session could run 30–90+ min of open tab time.
2. **Fixed budgets vs. variable input:** the 5-second aggregation window is fixed and does not vary with session length, so message *rate* is bounded — but total message *count* over a session is directly proportional to how long the tab stays open in `'TEACHING'`, with no explicit upper bound today. This story does not add a hard cap (matching CESIndicator/TutorInterventionCard, which also run for a session's full duration) — AC-7's teardown on `SESSION_END`/unmount is the only stop condition. **Explicit degradation, not silent:** if `wsSendAttentionSignal` is `null` (socket not yet connected, or disconnected), a signal is simply dropped for that window (logged once, not per-window, to avoid console spam) rather than queued — an attention signal is a live snapshot, not a durable record; a queued, late-delivered stale signal would misrepresent the student's *current* state to the tutor FSM.
3. **Scope of every limit:** per-session, per-browser-tab. No shared or cross-tab state; two tabs open on the same `session_id` would each run an independent `FaceLandmarker`/camera and each send their own signals over their own socket connection — a possible double-signal scenario for the backend to reconcile, but that reconciliation is backend/Dev 4 scope, not this component's (flagged as a defer item below).
4. **Unbounded reads/writes:** none. This story has no Supabase reads of its own beyond `useAttentionConsent`'s existing single-row read (already scoped/bounded in Story 2-42); all writes are fire-and-forget WebSocket sends, not HTTP requests, so there is no unbounded query to bound.
5. **Inherited caps re-derived:** none inherited — `useLessonSocket`'s reconnect/backoff behavior is reused as-is (already reviewed under Sprint 1); this story only adds a second stable send-function pointer into the store, not new socket logic.
6. **Concurrent requests safe?** N/A with reason — there is no check-then-act sequence here (no read-then-write race): the store's `wsSendAttentionSignal` pointer is set once per `useLessonSocket` mount and read fresh on each 5-second tick; there is no shared mutable resource two code paths could race on within one tab. Cross-tab double-signaling (point 3 above) is a real but out-of-scope concurrency question for the backend's ingestion path, not this frontend component.

## Tasks / Subtasks

- [x] Task 1 (AC: 3): Expose `sendAttentionSignal` through the player store — add `wsSendAttentionSignal: ((msg: AttentionSignalMessage) => void) | null` + `setWsSendAttentionSignal` to `player.machine.ts`, mirroring `wsSendControl`/`setWsSendControl` exactly; register/clean it up inside `useLessonSocket.ts` the same way `sendControl` already is (same identity-check-before-null pattern at cleanup).
  - [x] 1.1 RED: test that `useLessonSocket` registers `wsSendAttentionSignal` on connect and clears it (only if still its own instance) on cleanup.
  - [x] 1.2 GREEN: implement.
- [x] Task 2 (AC: 1, 2, 6, 8): `useAttentionMonitor` hook — consent gate, MediaPipe init (mocked in tests), camera stream acquisition, WASM-failure fallback.
  - [x] 2.1 RED: tests for consent-gated init (no init while `unknown`/`declined`/`isLoading`; init proceeds once `accepted`), and WASM-load-failure degrades silently with a logged error and no thrown/unhandled rejection.
  - [x] 2.2 GREEN: implement, mocking `@mediapipe/tasks-vision`'s `FaceLandmarker.createFromOptions`/`detectForVideo` and `navigator.mediaDevices.getUserMedia` at the module level (real WASM/camera cannot run under jsdom/vitest).
- [x] Task 3 (AC: 3, 4, 5): Detection loop, 5-second aggregation, signal computation (`head_pose_score` from `facialTransformationMatrixes` yaw/pitch deviation; `blink_rate` from rising-edge `eyeBlinkLeft`/`eyeBlinkRight` blendshape crossings, extrapolated to per-minute; `behavioral_score` folding gaze/expression blendshapes + DOM interaction rate — see Dev Notes for the exact first-pass formulas), gated on `tutorState === 'TEACHING'`.
  - [x] 3.1 RED: tests with mocked per-frame landmark/blendshape fixtures asserting the exact aggregated payload sent after a simulated 5-second window, that no signal fires outside `'TEACHING'`, and that the payload never contains extra keys (AC-5b). Split into a separately-tested pure module (`lib/attention/signalMath.ts`, 18 tests) plus hook-level integration tests (12 tests) — see Dev Agent Record.
  - [x] 3.2 GREEN: implement.
- [x] Task 4 (AC: 7): Cleanup — stop all `MediaStreamTrack`s and call `faceLandmarker.close()` on unmount and on `tutorState === 'SESSION_END'`.
  - [x] 4.1 RED: tests for both teardown triggers, asserting `track.stop()` and `.close()` are each called exactly once (not on every pause per AC-4). Verified non-vacuous via a deliberate mutation check (disabled the SESSION_END branch, confirmed the test fails, reverted).
  - [x] 4.2 GREEN: implement.
- [x] Task 5 (AC: 5a): `AttentionMonitor.tsx` — thin, self-contained (zero props, matching `CESIndicator`/`TutorInterventionCard`) component invoking the hook; renders `null` (no `<video>` element in the component itself — the hook owns an off-DOM `<video>` element internally, never inserted into the document, since no visual camera preview exists anywhere in scope).
  - [x] 5.1 RED: source-level guard test (same style as `AttentionConsentModal.test.tsx`'s AC-4 test) failing on any `fetch(`, raw `XMLHttpRequest`/axios, or `toDataURL`/`captureStream`/`ImageData(` call in the two new files.
  - [x] 5.2 GREEN: implement; added `@mediapipe/tasks-vision@^1.0.1` to `apps/web/package.json` (already-approved per CLAUDE.md's locked stack, not a new ad-hoc dependency).
- [x] Task 6 (AC: 1–8): Wire `<AttentionMonitor />` into `Player.tsx`, rendered unconditionally and self-contained (same tier as `AttentionConsentModal`/`CESIndicator`) — all gating (consent, tutorState) lives inside the hook, not in `Player.tsx`'s JSX.
  - [x] 6.1 RED: integration test on `Player.test.tsx` confirming `AttentionMonitor` mounts; "no duplicate socket connection" verified as a source-level fact (`useAttentionMonitor.ts` never references `useLessonSocket`) rather than a call-count assertion, since a hook invoked once per React render can't distinguish "one mount, several renders" from "two mounts" without a brittle exact count.
  - [x] 6.2 GREEN: implement.
- [x] Task 7: Full `apps/web` suite green (891/891); `tsc --noEmit` clean; `eslint` clean on every touched file (3 pre-existing, unrelated warnings in `useLessonSocket.ts` confirmed via `git stash` to predate this story).

## Dev Notes

### What NOT to do

- Do NOT call `useLessonSocket()` a second time inside `AttentionMonitor`/`useAttentionMonitor` to get `sendAttentionSignal` — it opens a real second WebSocket connection to the same session. Read `wsSendAttentionSignal` from the player store instead (Task 1).
- Do NOT gate monitoring on `PlayerStatus` (`status === 'PLAYING'`) — CLAUDE.md's guard rule is written in terms of the tutor FSM's `'TEACHING'` state (`tutorState`), which is a different field with different transitions (e.g. `CHECKING_IN`/`INTERVENING` can occur while `status` is still effectively mid-playback).
- Do NOT trust `useAttentionConsent().showModal` as the security gate — that hook's own docstring explicitly forbids this. Use `consentStatus === 'accepted'` only.
- Do NOT tear down the camera/model on every `tutorState` transition away from `'TEACHING'` (e.g. entering `QUIZZING`) — only pause capture/sending (AC-4). Full teardown is reserved for unmount/`SESSION_END` (AC-7); re-initializing MediaPipe on every quiz would risk missing the 3-second re-init budget repeatedly within one session and is wasted work for a state that recurs many times per lesson.
- Do NOT invent a new "raw camera bytes to server" code path under any circumstance, including for debugging/telemetry — this is the one hard security line in this story (AC-5) and CLAUDE.md §18.

### Signal computation (first-pass heuristics — explicit, not hidden)

The tracker names 5 locally-aggregated signals but the frozen wire contract only transmits 3. These formulas are a deliberate, testable first pass — not calibrated against real usage data (no such data exists yet, same honest position CLAUDE.md already takes on the server-side CES weights: "tunable post-calibration"):

- **`head_pose_score`** (0–1): from `FaceLandmarker`'s `facialTransformationMatrixes[0]` (requires `outputFacialTransformationMatrixes: true`), extract yaw/pitch. Score = `1` at dead-center, linearly decreasing to `0` at ±30° yaw or ±20° pitch (clamped). Averaged across the frames in the 5-second window.
- **`blink_rate`** (blinks/minute): from blendshapes `eyeBlinkLeft`/`eyeBlinkRight` (requires `outputFaceBlendshapes: true`). A blink is a **rising-edge** crossing of both scores above `0.5` (not a sustained-frame count, which would overcount a single slow blink as many blinks). Count discrete blinks in the 5-second window, multiply by 12 to extrapolate to per-minute.
- **`behavioral_score`** (0–1): local-only aggregate folding in the two signals the frozen contract has no field for (`gaze_score`, from `eyeLookIn/Out/Up/Down` blendshapes; `expression_label`, classified from `browDownLeft/Right`/`eyeWideLeft/Right`/`browInnerUp` into `'neutral'|'confused'|'surprised'`) plus a normalized DOM interaction rate (click/scroll/mousemove events in the window, capped and normalized against a fixed baseline rate). Weighted average, equal thirds, pending real calibration data.

### Testing standards

Real WASM and real camera access cannot run under vitest/jsdom. Mock `@mediapipe/tasks-vision` (`FaceLandmarker.createFromOptions`, `detectForVideo`) and `navigator.mediaDevices.getUserMedia` at the module level for every test — there is no real-boundary test possible here, unlike the MSW convention used for HTTP services. Use fake timers to simulate 5-second window boundaries deterministically rather than real `setTimeout`/`requestAnimationFrame` delays.

### References

- [Source: `docs/dev2-sprint-tracker.md` lines 1546–1583 — S3-02 spec, ACs, wire payload sketch]
- [Source: `packages/shared/types/ws.ts` — frozen `AttentionSignalMessage`/`ServerMessage` contract]
- [Source: `apps/web/src/hooks/useAttentionConsent.ts` — consent read this story must reuse via its own hook instance]
- [Source: `apps/web/src/hooks/useLessonSocket.ts` — existing `sendAttentionSignal`/`wsSendControl` registration pattern to mirror]
- [Source: `apps/web/src/stores/player.machine.ts` — `tutorState` field and transitions]
- [Source: `apps/web/src/components/player/Player.tsx` — render tree/integration point, self-contained sibling components]
- [Source: `apps/web/src/__tests__/components/player/AttentionConsentModal.test.tsx` — source-level guard test style to copy for AC-5a]

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-08-10 | Story created per S3-02 in `docs/dev2-sprint-tracker.md`. Branch `sprint3/s3-02-attention-monitor` off `sprint3-master` at `3601649` (not `main` — hard dependency on Story 2-42's consent hook, which only exists on `sprint3-master`). Verified real contracts directly: `ws.ts`'s frozen `AttentionSignalMessage` shape, `useAttentionConsent.ts`'s consent-gate semantics, `useLessonSocket.ts`'s single-call-site constraint, and `player.machine.ts`'s `tutorState` field — corrected the tracker's ambiguous "lesson start"/`@mediapipe/face_landmarker` package name against real code before writing ACs. | Dev 2 |
| 2026-08-10 | Implemented all 7 tasks, TDD (RED confirmed before each GREEN, including a deliberate mutation check on the highest-risk SESSION_END teardown test). Split signal computation into a separately unit-tested pure module (`lib/attention/signalMath.ts`, not in the original file list — added because MediaPipe/camera can't be tested at all, so isolating the math into pure functions was the only way to get real, non-mocked test coverage on the formulas themselves). `useLessonSocket.ts`'s `sendAttentionSignal` useCallback was relocated above the effect that registers it into the store — referencing a later-declared `const` compiled fine at runtime but was rejected by the React Compiler ESLint plugin ("accessed before it is declared" / lost memoization), caught by running `eslint` before considering the task done. Removed a redundant leftover `cancelled` flag in `useAttentionMonitor.ts` (superseded by the `tornDown`/`teardown()` design) that `eslint` flagged as unused. Full `apps/web` suite: 75 files / 891 tests passing. `tsc --noEmit` clean. `eslint` clean (3 pre-existing warnings in `useLessonSocket.ts`, confirmed via `git stash` to predate this branch). Status → review. | Dev 2 |

## Dev Agent Record

### Context Reference

- `docs/dev2-sprint-tracker.md` §S3-02
- `docs/decisions/` — none directly applicable to this story

### Agent Model Used

Claude (Sonnet 5)

### Debug Log

- React Compiler ESLint errors on first `eslint` run: `sendAttentionSignal` (a `useCallback` declared after the `useEffect` that referenced it) — "accessed before it is declared" and "Could not preserve existing memoization." Valid at runtime (effects execute after the full render body, including later `const` declarations), but rejected by the compiler's static ordering requirement. Fixed by moving the `useCallback` above the effect.
- `eslint` also flagged a redundant `cancelled` flag in `useAttentionMonitor.ts` left over from an early draft, fully superseded by the `tornDown`/`teardown()` idempotent-teardown design — removed.
- Mutation-tested the SESSION_END teardown test (temporarily short-circuited the teardown branch with `if (false && ...)`, confirmed the test failed, reverted) to verify it wasn't vacuously passing given the heavy mocking MediaPipe/camera testing requires.

### Completion Notes

All 8 ACs implemented and covered by tests (34 new tests across 4 new test files + 5 new tests added to existing `useLessonSocket.test.ts`/`Player.test.tsx`). Key design decisions, all recorded in Dev Notes before implementation began:
- `useAttentionMonitor` calls `useAttentionConsent()` as its own hook instance (gets its own fresh mount-time Supabase read) rather than trusting a value from a distant ancestor's render.
- Gated on `tutorState === 'TEACHING'` (the tutor FSM field CLAUDE.md's guard rule actually names), not `PlayerStatus`.
- `sendAttentionSignal` exposed via a new `wsSendAttentionSignal` store field, mirroring the existing `wsSendControl` pattern exactly, rather than calling `useLessonSocket` a second time.
- Pausing (AC-4) vs. full teardown (AC-7) are distinct: an idempotent `teardown()` closure is called from either the effect's cleanup (unmount) or from inside `detectFrame()` when it observes `tutorState === 'SESSION_END'`; every other non-TEACHING state only skips sampling for that window, leaving the camera/model warm.
- Signal formulas (`head_pose_score`, `blink_rate`, `behavioral_score`) are explicitly documented first-pass heuristics, unit-tested in isolation via `lib/attention/signalMath.ts` — calibration against real usage data is future work, same honest position CLAUDE.md already takes on the server-side CES weights.

### File List

**New:**
- `apps/web/src/hooks/useAttentionMonitor.ts`
- `apps/web/src/components/player/AttentionMonitor.tsx`
- `apps/web/src/lib/attention/signalMath.ts` (not in the original story file list — added during implementation; see Change Log)
- `apps/web/src/__tests__/hooks/useAttentionMonitor.test.ts`
- `apps/web/src/__tests__/components/player/AttentionMonitor.test.tsx`
- `apps/web/src/__tests__/lib/attention/signalMath.test.ts`

**Modified:**
- `apps/web/src/stores/player.machine.ts` (`wsSendAttentionSignal` field + `setWsSendAttentionSignal` action)
- `apps/web/src/hooks/useLessonSocket.ts` (registers/cleans up `wsSendAttentionSignal`; relocated `sendAttentionSignal` useCallback above the effect)
- `apps/web/src/components/player/Player.tsx` (renders `<AttentionMonitor />`)
- `apps/web/src/__tests__/hooks/useLessonSocket.test.ts` (3 new tests for `wsSendAttentionSignal`)
- `apps/web/src/__tests__/components/player/Player.test.tsx` (mocks `useAttentionMonitor`; 1 new integration test)
- `apps/web/package.json` / `pnpm-lock.yaml` (`@mediapipe/tasks-vision@^1.0.1` added)
