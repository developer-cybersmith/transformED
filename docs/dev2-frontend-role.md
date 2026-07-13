# Developer 2 — Frontend & Lesson Player

## Role Overview

Dev 2 owns the entire student-facing experience — from the first page load to the session report. The lesson player is the most technically complex frontend component in the system: a custom React audio-timeline state machine that synchronises slides, audio, avatar mouth animation, transcript, jargon hovers, quiz popups, and teach-back modal through pause, resume, and seek operations. Dev 2 builds against mock fixtures from Week 1 and integrates with live APIs at the end of each sprint.

---

## Permanent Ownership

- Next.js 14 app — routing, SSR, layout, pages
- Supabase JS client (auth + storage) — browser-side only
- Auth flow — sign up, sign in, session management, JWT
- Custom React audio-timeline lesson player (most complex component)
- Slide renderer from lesson package
- Avatar intro/outro video component (HeyGen cached)
- Jargon hover tooltip system
- Quiz popup UI (consumes Dev 3 API)
- Teach-back modal (textarea + submit + feedback display)
- MediaPipe Face Landmarker WASM integration + attention capture
- WebSocket client — connects to Dev 4 backend
- Tutor intervention card UI (3 types: distraction, confusion, fatigue)
- Onboarding assessment UI — 20 questions
- Learner DNA profile display component
- Session report page
- Dashboard — lesson library, upload, status
- Landing page + pricing page
- PostHog product analytics instrumentation

---

## The Lesson Player — Most Critical Component

**Do not use Reveal.js.** Build a custom React audio-timeline state machine. Reveal.js click model cannot be made to work with timestamp-driven sync, pause/resume/seek, and quiz popups. This was an explicit architecture decision.

The player is driven by an audio timeline. Every event (slide advance, quiz popup, jargon highlight, avatar mouth) is triggered by an audio timestamp, not by user click. The state machine must survive:

- Pause and resume — all elements freeze and resume in sync
- Seek (scrub) — all elements jump to the correct state for that timestamp
- Quiz popup — audio pauses, quiz card appears, resumes after submission
- Teach-back modal — audio pauses, textarea appears, resumes after submission
- Tutor intervention — audio pauses, intervention card appears, resumes on dismiss
- Segment end — audio stops, CHECKING IN state triggers, then QUIZZING, then TEACH-BACK, then next segment

### Player Component Map

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
| `AttentionMonitor` | `components/player/AttentionMonitor.tsx` | MediaPipe FaceMesh WASM; streams head pose + blink signals to WebSocket |

### Slide Sync: Binary Search Algorithm

`narration.timestamps` is a sorted array of `{ slideIndex, startMs }` pairs produced by the TTS node.

On every `timeUpdate` event from `<audio>`:
1. Current position `t` in milliseconds
2. Binary search `narration.timestamps` for largest `startMs <= t`
3. If resulting `slideIndex !== store.currentSlide` → dispatch `SET_SLIDE(slideIndex)`

This avoids O(n) linear scan on every audio frame. The array is pre-sorted at build time.

---

## MediaPipe Attention Capture

MediaPipe Face Landmarker runs entirely in the browser (WASM). Raw video NEVER leaves the device. Every 5 seconds, the client aggregates 150 frames of local signal state into 5 numbers and sends them over the existing WebSocket connection.

| Property | Value |
|---|---|
| Aggregation interval | Every 5 seconds (`setInterval 5000`) |
| Frame rate | MediaPipe runs at 30fps — local only, never sent |
| Payload per send | ~200 bytes — 5 numbers + session_id + timestamp |
| Transport | Existing WebSocket connection — piggybacks on lesson progress socket |

| Signal | Description |
|---|---|
| `gaze_score` | (0–1) averaged gaze-on-screen from 150 frames |
| `head_pose_score` | (0–1) head-facing-screen ratio |
| `blink_rate` | blinks per minute (derived from 150 frames) |
| `expression_label` | dominant expression (neutral/confused/surprised) |
| `behavioral_score` | (0–1) click + scroll + mouse activity events |

### Consent Flow — Required Before Attention Capture

Before enabling MediaPipe, show a consent modal explaining exactly what is captured. Do not start camera access without explicit user consent. The consent state must be stored in Supabase (`users.attention_consent` boolean). If consent is declined, lesson plays normally — attention monitoring is simply disabled for that session.

---

## WebSocket Message Types (Contract with Dev 4)

Dev 2 publishes the TypeScript discriminated union in `packages/shared/types/ws.ts`. Dev 2 mocks all of these from Week 1 using a local mock WebSocket — does not wait for Dev 4.

```typescript
// packages/shared/types/ws.ts
type WSMessage =
  | { type: "lesson_ready"; lesson_id: string }
  | { type: "generation_progress"; node: string; progress: number }
  | { type: "attention_ack"; ces_score: number }
  | { type: "tutor_intervene"; intervention_type: "A" | "B" | "C"; message: string }
  | { type: "ces_update"; score: number; baseline: number }
  | { type: "state_change"; state: TutorState }
```

---

## Sprint Deliverables

### Sprint 0 — Week 1 (Done)
- Next.js 14 init + Tailwind
- Supabase JS client wired
- Auth flow (sign up, sign in, JWT)
- Dashboard shell
- Routing structure
- Shared TS types from lesson package contract
- Mock API fixtures for all endpoints
- Mock WebSocket client for local dev

### Sprint 1 — Weeks 2–3
- Audio-timeline state machine (React)
- Slide renderer from lesson package
- Audio playback + timestamp-driven slide advance
- Avatar intro/outro video component
- Jargon hover tooltip component
- Lesson load from Supabase Storage signed URLs
- PDF upload UI + generation progress indicator

### Sprint 2 — Weeks 4–5
- Quiz popup integration (Dev 3 API)
- Teach-back modal integration
- Segment-end detection → CHECKING IN state
- Feedback display (praise + correction sentences)
- Session report page v1
- Onboarding assessment UI (20 questions)
- Learner DNA profile display component

### Sprint 3 — Weeks 6–7
- MediaPipe Face Landmarker WASM integration
- 5-signal aggregation every 5 seconds
- WebSocket attention payload sending
- Consent flow UI
- Tutor intervention card component (3 types)
- CES indicator in player (subtle, non-intrusive)
- Session report: attention timeline chart
- Mobile responsive audit

### Sprint 4 — Weeks 8–9
- All UI bugs from test sessions fixed
- Loading + error + empty states for all flows
- Email notifications (lesson ready, session report)
- Landing page + pricing page
- Stripe Checkout redirect integration
- Accessibility audit (WCAG AA minimum)

---

## Rules Dev 2 Must Follow

- **Never use Reveal.js.** Custom audio-timeline state machine only.
- Build a sync test harness in Week 2 before adding any features on top of the timeline. If sync breaks it breaks everything.
- Always build against mock fixtures first. Never wait for a backend developer to be done before starting UI work.
- All API calls go through the generated TypeScript client (from Dev 3 OpenAPI spec). No hand-written fetch calls to assessment endpoints.
- Raw video from MediaPipe never leaves the browser. If any code path sends video bytes to the server, it is a critical bug.
- PostHog event fired for every significant user action from day one.
- Player components use `dynamic(() => import(...), { ssr: false })` — required for MediaPipe WASM and Web Audio API compatibility.
- State management: Zustand (custom state machine pattern — not XState, not useReducer).
