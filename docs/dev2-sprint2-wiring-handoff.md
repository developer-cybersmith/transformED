# Dev 2 Handoff: Sprint 2 Wiring Gaps (from the 360° Audit)

**From:** Dev 1 (developer1-cybersmith)
**To:** Dev 2 (Next.js / player / dashboard owner)
**Date:** 2026-07-27
**Source:** `docs/reports/sprint2-360-audit-2026-07-27.md` + `docs/reports/sprint2-360-reaudit-2026-07-27.md` (re-verified against current `main` post-Story-2-25)
**Severity:** P0 — nothing else in Sprint 3 matters if these aren't fixed. A student who uploads a PDF today still sees a canned mock lesson regardless of what they submitted.

---

## TL;DR

Every backend endpoint your side needs is real, tested, and ready. None of them are wired. Specifically:

1. **Lesson player** (`/lesson/[id]`) still calls `apps/web/src/mocks/api/lesson.ts` instead of the real `GET /api/content/lessons/{id}`. **This is the single highest-priority item in the whole audit.**
2. **Dashboard/library** still call mocks instead of the real, paginated `GET /api/content/lessons`.
3. **The tutor WebSocket is never opened** — `useLessonSocket` exists, is unit-tested, and is correct, but has zero call sites in any production component. This blocks Dev4's entire CES/attention subsystem from ever being validated live.
4. Quiz feedback rendering is broken (cross-owner with Dev3 — see §4).
5. `reassessment_due` is fetched and then thrown away before it can be shown to anyone.
6. `/api/media/signed-url` has no caller (low priority — likely resolves itself once #1 is fixed).

None of this requires backend changes from Dev1. Everything below is either already-shipped and ready, or a coordination item with Dev3/Dev4.

---

## 1. Lesson Player — Wire to Real Content (P0)

**Current state:** `apps/web/src/hooks/useLesson.ts` → `apps/web/src/services/lesson.service.ts` → `apps/web/src/mocks/api/lesson.ts::getLessonPackageById` returns a hardcoded fixture. Stale `[DEV1-SPRINT2-PENDING]` comments are still in all three files — they're outdated; the backend side they're waiting on shipped in Story 1-6 (merged to `main` weeks ago) and is unaffected by anything in Story 2-25.

**What's actually ready:** `GET /api/content/lessons/{lesson_id}` (`apps/api/app/modules/content/router.py::get_lesson`) — real, UUID-validated, ownership-checked, and returns the full `LessonPackage` with every `audio_url`/`image_url` already resolved to a working signed URL when `status == "ready"`.

**A prior handoff doc already covers this exact wiring in full detail, including the shape mismatch you'll hit (`response.data.content`, not `response.data`) and the `!lesson → error` bug that will misfire on a still-generating lesson:**

👉 **See `docs/dev2-lesson-content-wiring-handoff.md`** — written when Story 1-6 shipped, still 100% accurate. Nothing about the endpoint has changed since. This handoff doc's §3 and §5 are your literal action items.

If that handoff was missed/deprioritized when it landed, this is the moment to pick it back up — it's the actual root cause of the mock-backed player.

---

## 2. Dashboard & Library — Wire to Real List Endpoint (HIGH)

**Current state:** `apps/web/src/services/dashboard.service.ts` and `library.service.ts` both import exclusively from `../mocks/api` — zero references to `fetch`/`axios`/the real content API in either file.

**What's ready:** `GET /api/content/lessons` (paginated, user-scoped, newest-first) — `list_jobs`/`list_lessons` in `content/router.py`. Query params: `limit` (default 20, max 200), `offset`.

**Action:** Point both services at the real endpoint, mapping `LessonStatusResponse[]` into whatever card shape the dashboard/library UI expects. No backend change needed — this is a pure frontend swap, same pattern as §1.

---

## 3. Tutor WebSocket — Mount `useLessonSocket` (CRITICAL, blocks Sprint 3)

**Current state:** `apps/web/src/hooks/useLessonSocket.ts` is fully built and unit-tested (`apps/web/src/__tests__/hooks/useLessonSocket.test.ts`), but has **zero production call sites** — grep confirms it's referenced only by its own definition and its own test. `Player.tsx`/`PlayerLoader.tsx` drive all UI state from local Zustand state only; the backend's `/ws/{session_id}` endpoint is fully functional and dispatching real events but receives no live traffic.

**Why this blocks Sprint 3:** Sprint 3's CES/MediaPipe/attention work (Dev4's domain) cannot be validated against a live client until something actually opens the socket and sends `attention_signal` frames. Right now the entire subsystem is dead code in production.

**Action:**
1. Mount `useLessonSocket(sessionId)` inside `Player.tsx` (or a wrapping provider around it).
2. Wire `sendAttentionSignal` into wherever the MediaPipe capture loop lands (Sprint 3 work, but the hook needs to exist and be mounted *before* that work starts, not after).
3. Coordinate with Dev4 on `session_id` — see §5, it's currently a client-generated UUID with no backend round-trip.

**Note:** the WS message handlers you already wrote (e.g. the `lesson_ready` no-op documented in `docs/dev2-lesson-content-wiring-handoff.md` §2) are correct. This isn't about fixing your WS client code — it's about actually invoking the hook that owns it.

---

## 4. Quiz Feedback Rendering Broken (CRITICAL — coordinate with Dev3)

**Current state:** Backend (`apps/api/app/modules/assessment/service.py`) builds quiz feedback objects with keys `question_id, question, is_correct, correct_index, correct_option, selected_option, explanation`. Your `QuizFeedbackItem` type and its only consumer, `QuizOverlay.tsx`, read `f.correct` and `f.message` — **neither key exists on the wire**. Both are always `undefined` at runtime. **Every quiz currently renders every answer as incorrect with a blank explanation, in every environment, right now.**

`QuizResult.feedback` is typed `list[dict[str, Any]]` on the backend, so Pydantic never caught this drift — it's a pure naming mismatch, not a type error either side would see in isolation.

**Action:** Update `QuizFeedbackItem` and `QuizOverlay.tsx` to read `is_correct`/`explanation`/`correct_option`/`selected_option` instead of `correct`/`message`. This needs a quick sync with Dev3 first — confirm whether the backend keys are the intended final shape (they look deliberate, not accidental) before you rename on your side, since this is technically a cross-team wire contract even though it was never formally frozen.

---

## 5. `reassessment_due` Discarded Before It Reaches the UI (HIGH)

**Current state:** `GET /api/assessment/user/dna` correctly computes and returns `reassessment_due` (flips true every 10th session, backend logic is solid). `apps/web/src/components/onboarding/OnboardingFlow.tsx`'s mount-time probe calls `getLearnerDna()` purely to check onboarding-completion status, **discards the resolved object entirely**, and redirects to `/dashboard`. No component anywhere in the codebase reads `reassessment_due` — it only appears in types and test fixtures.

**Action:**
1. Fix the discard-then-redirect callback in `OnboardingFlow.tsx` to actually capture the fetched DNA object instead of throwing it away.
2. Add a banner/prompt somewhere reachable (dashboard is the obvious spot) that reads `dna.reassessment_due` and surfaces a re-assessment CTA when true.

No backend change needed — this is purely surfacing data that's already correctly computed.

---

## 6. Session-Identity Coordination (MEDIUM — with Dev4)

**Current state:** `usePlayerStore.loadLesson()` generates `sessionId` via `crypto.randomUUID()` entirely client-side, with no round-trip to any backend session-creation call. The backend WS endpoint accepts whatever `session_id` shows up in the URL, with no validation against a server-issued/registered record.

**Why it matters:** no collision/replay protection, and no durable link between a WS session and Dev3's session-report data. Currently moot in practice since the socket is never opened at all (§3) — but worth deciding on purpose before mounting the socket, not after.

**Action:** Sync with Dev4 on whether the backend should mint `session_id` (returned from a "start session" REST call before the WS connects) or the client UUID gets registered/validated via REST before the handshake. Either is fine — just needs one decision, not two independent implementations.

---

## 7. Low Priority — `/api/media/signed-url` Has No Caller

**Current state:** Zero references to `signed-url`/`signedUrl` anywhere in `apps/web/src`. Not urgent — once §1 is wired, the player will consume `audio_url`/`image_url` as pre-signed values embedded directly in the lesson content response (per `docs/dev2-lesson-content-wiring-handoff.md`), and this endpoint may simply stay unused unless you build an expiry-refresh path (`<audio onError>` re-signing a specific expired segment — a nice-to-have, not blocking).

---

## Files Involved

| File | Action Needed |
|------|----------------|
| `apps/web/src/services/lesson.service.ts` | Point `getLessonPackage` at the real endpoint — see `docs/dev2-lesson-content-wiring-handoff.md` §3a |
| `apps/web/src/hooks/useLesson.ts` | Read `.content`, surface `status`/`error` — see handoff §3b |
| `apps/web/src/components/player/PlayerLoader.tsx` | Handle the still-generating / failed states — see handoff §3b |
| `apps/web/src/services/dashboard.service.ts` | Wire to real `GET /api/content/lessons` |
| `apps/web/src/services/library.service.ts` | Wire to real `GET /api/content/lessons` |
| `apps/web/src/components/player/Player.tsx` (or `PlayerLoader.tsx`) | Mount `useLessonSocket(sessionId)` |
| `apps/web/src/types/assessment.ts` (or wherever `QuizFeedbackItem` lives) | Rename fields to match backend (`is_correct`/`explanation`/...) — coordinate with Dev3 |
| `apps/web/src/components/quiz/QuizOverlay.tsx` | Update field reads to match |
| `apps/web/src/components/onboarding/OnboardingFlow.tsx` | Stop discarding the DNA fetch; capture it |
| Dashboard (wherever a persistent banner can live) | Surface `reassessment_due` |
| `apps/web/src/store/usePlayerStore.ts` (or wherever `loadLesson` lives) | Coordinate `session_id` sourcing with Dev4 |

---

## Reference

- `docs/reports/sprint2-360-audit-2026-07-27.md` — original full audit
- `docs/reports/sprint2-360-reaudit-2026-07-27.md` — re-verification post Story 2-25, confirms all of the above is unchanged/still accurate
- `docs/dev2-lesson-content-wiring-handoff.md` — detailed, still-accurate walkthrough for §1
- `docs/stories/2-25-sprint2-audit-gapfix-dev1-items.md` — Dev1's own fixes (admin, media allowlist, contracts) from this same audit round — not your action items, included for context
