# Epic 2: Lesson Player + Frontend

| Field | Value |
|---|---|
| Epic ID | E-02 |
| Status | Planned |
| Owner | Dev 2 |
| Target Sprints | Sprint 1–2 (Weeks 2–5) |
| Priority | P0 — student-facing core experience |

---

## Problem Statement

The lesson package produced by Epic 1 is inert JSON and audio files until the player brings it to life. Students need a synchronized, distraction-free learning experience where audio, slides, avatar, quizzes, and jargon tooltips all fire at precisely the right moment. No off-the-shelf player (Reveal.js, video.js) fits this model — a custom state-machine-driven player is required.

---

## Goal / Success Metric

> **A student can open any generated lesson and experience fully synchronized audio, slides, quiz prompts, and jargon overlays — with no buffering stalls, no sync drift, and zero developer intervention.**

Secondary metrics:
- Slide sync latency < 100ms from audio timestamp
- Player state survives page refresh (session continuity via Redis/localStorage)
- MediaPipe attention detection initializes within 3 seconds of lesson start

---

## User Stories

- As a **student**, I see slides change in sync with the narration audio, so I always know what the instructor is talking about.
- As a **student**, I can hover over highlighted jargon terms to see definitions without interrupting playback.
- As a **student**, a quiz modal appears automatically at the end of each lesson segment.
- As a **student**, I can track my upload's processing progress in real time so I'm not left staring at a spinner.
- As a **student**, the HeyGen AI avatar intro plays before the lesson and outro plays after it.
- As a **developer**, the player loads no server-side rendered state (SSR disabled) to avoid hydration mismatches with WASM.

---

## Component Specification

| Component | File | Responsibility |
|---|---|---|
| `PlayerLoader` | `components/player/PlayerLoader.tsx` | Dynamic import with `ssr: false`; loads lesson package via SWR |
| `Player` | `components/player/Player.tsx` | Root layout: positions all sub-components, owns AudioTimeline ref |
| `player.machine` | `stores/player.machine.ts` | Zustand store + state machine: IDLE → PLAYING → PAUSED → QUIZ → TEACH_BACK → ENDED |
| `SlideRenderer` | `components/player/SlideRenderer.tsx` | Renders current slide JSON; accepts `slideIndex` from store |
| `AudioTimeline` | `components/player/AudioTimeline.tsx` | `<audio>` element wrapper; fires `onTimeUpdate` → binary search → slide sync |
| `AvatarOverlay` | `components/player/AvatarOverlay.tsx` | HeyGen video for intro/outro; static mid-lesson avatar image |
| `JargonHover` | `components/player/JargonHover.tsx` | Wraps narration text; detects jargon spans, renders Radix tooltip |
| `QuizModal` | `components/player/QuizModal.tsx` | MCQ modal; fires at segment boundaries; submits to `/api/assessment/quiz` |
| `TeachBackModal` | `components/player/TeachBackModal.tsx` | Free-text teach-back; no timer; submits to `/api/assessment/teachback` |
| `TutorInterventionCard` | `components/player/TutorInterventionCard.tsx` | Slides in from right; receives intervention messages via WebSocket |
| `AttentionMonitor` | `components/player/AttentionMonitor.tsx` | MediaPipe FaceMesh WASM; streams head pose + blink signals to WebSocket. **DPDP gate:** checks `user_consents` for `consent_type='attention_capture'` before initializing — shows consent modal if absent. |

---

## Slide Sync: Binary Search Algorithm

`narration.timestamps` is a sorted array of `{ slideIndex, startMs }` pairs produced by the TTS node.

On every `timeUpdate` event from `<audio>`:
1. Current position `t` in milliseconds
2. Binary search `narration.timestamps` for largest `startMs <= t`
3. If resulting `slideIndex !== store.currentSlide` → dispatch `SET_SLIDE(slideIndex)`

This avoids O(n) linear scan on every audio frame. The array is pre-sorted at build time.

**Rejected alternative:** Reveal.js — requires DOM ownership, incompatible with React state machine, no programmatic slide control without hacks.

---

## Route Map

| Route | File | Notes |
|---|---|---|
| `/` | `app/page.tsx` | Landing page (Epic 5) |
| `/onboarding` | `app/onboarding/page.tsx` | Learner DNA 20-question flow (Epic 3 data) |
| `/dashboard` | `app/dashboard/page.tsx` | Lesson library, upload CTA |
| `/upload` | `app/upload/page.tsx` | PDF upload form + real-time generation progress screen |
| `/lesson/[id]` | `app/lesson/[id]/page.tsx` | `PlayerLoader` → `Player` |

---

## Technical Scope

| Layer | Files / Modules |
|---|---|
| Player components | `components/player/` (all files above) |
| State store | `stores/player.machine.ts` |
| Attention monitor | `components/player/AttentionMonitor.tsx` (MediaPipe WASM) |
| WebSocket client | `lib/ws/lessonSocket.ts` — connects to `/ws/{session_id}` |
| API client | `lib/api/assessment.ts` — typed wrappers for quiz + teachback endpoints |
| Lesson data fetching | `lib/api/lesson.ts` — SWR hook for `lesson_package.json` |
| Upload progress | `app/upload/page.tsx` + `lib/ws/uploadSocket.ts` |
| Routes | `app/` (Next.js 14 App Router) |
| Shared types | `types/lesson.ts` — `LessonPackage`, `Slide`, `NarrationTimestamp` |

**State management:** Zustand (custom state machine pattern — not XState, not useReducer).

**Attention library:** MediaPipe FaceMesh via `@mediapipe/face_mesh` WASM bundle. WebGazer is explicitly rejected (too heavy, unreliable in classroom lighting).

**SSR:** Player components use `dynamic(() => import(...), { ssr: false })` — required for MediaPipe WASM and Web Audio API compatibility.

---

## Upload Progress Screen

While the pipeline runs (Epic 1), the `/upload` page shows a live progress screen:

- WebSocket connection to `/ws/{session_id}` receives `{ node, status, progress_pct }` messages
- Node names displayed as human-readable steps ("Extracting text...", "Generating slides...")
- On `package_builder` completion → auto-redirect to `/lesson/{id}`
- On pipeline failure → error card with retry CTA

---

## Out of Scope (Phase 2)

- Reveal.js or any third-party slide framework
- WebGazer eye tracking
- Mobile-optimized player layout (Phase 1 targets desktop Chrome)
- Offline / PWA mode
- Collaborative viewing (multi-student session)
- Closed captions / transcript panel

---

## Dependencies

| Dependency | Status |
|---|---|
| `lesson_package.json` schema finalized (Epic 1 Sprint 0) | Done |
| Epic 1 pipeline producing real packages | Required for integration testing |
| Epic 4 WebSocket server `/ws/{session_id}` | Required for progress screen + tutor cards |
| Epic 3 assessment API endpoints | Required for quiz + teachback submission |
| HeyGen API key + avatar video URLs | Must be provisioned before Sprint 2 |
| MediaPipe WASM bundle size approved (< 3MB gzip) | Verify before Sprint 1 |
| `user_consents` audit table with `consent_type='attention_capture'` | Sprint 2 prerequisite — DPDP Act 2023 compliance gate for AttentionMonitor |

---

## Definition of Done

- [ ] Player renders a lesson package with correct slide sync (manually verified, < 100ms drift)
- [ ] Binary search slide sync implemented and unit-tested with a 30-entry timestamp fixture
- [ ] QuizModal fires at each segment boundary and submits successfully to assessment API
- [ ] TeachBackModal opens after quiz with no timer present
- [ ] JargonHover tooltip appears on all jargon terms without interrupting audio
- [ ] TutorInterventionCard renders on receipt of WebSocket intervention message
- [ ] AvatarOverlay plays HeyGen intro/outro and shows static image during lesson body
- [ ] AttentionMonitor initializes MediaPipe within 3s; signals reach WebSocket
- [ ] AttentionMonitor does NOT initialize without `user_consents` row with `consent_type='attention_capture'` — verified by removing consent row and confirming WASM does not load
- [ ] Upload progress screen shows all pipeline node steps live
- [ ] `PlayerLoader` has `ssr: false` — no hydration errors in browser console
- [ ] All routes render without 404 on fresh deploy
- [ ] Lighthouse performance score > 70 on `/lesson/[id]`

---

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| MediaPipe WASM load time degrades LCP | Medium | Medium | Lazy-load behind `ssr: false`; preload in `<head>` |
| Audio–slide sync drift accumulates over long lessons | Medium | High | Reset binary search reference on seek; test with 45-min lesson |
| HeyGen API latency blocks lesson start | Low | High | Cache HeyGen video URL at build time; player renders immediately |
| WebSocket drops mid-lesson lose tutor signals | Medium | Medium | Reconnect logic with exponential backoff in `lessonSocket.ts` |
| QuizModal fires twice if segment boundary hit during seek | Low | Medium | Guard with `quizFiredForSegment` Set in player store |
