---
baseline_commit: dc6e78ff9d13b6f8e6a736cb136b1a0a03c6a563
---

# Story 2.54: PostHog Full Instrumentation (S4-03)

Status: ready-for-dev

## Story

As the product team,
I want the 8 significant student-behavior events fired to PostHog,
so that we can see the real signup → onboarding → upload → lesson → completion funnel before real students arrive in Week 10, instead of only finding out where students drop off after the fact.

**Source:** `docs/dev2-sprint-tracker.md` S4-03 ("PostHog Full Instrumentation", P1). CLAUDE.md's observability stack already names PostHog as mandatory ("Langfuse + Sentry + OTel + PostHog — Wire before feature work"), but confirmed by a repo-wide case-insensitive search that it has never been wired into `apps/web`: no `posthog-js` dependency, no provider, no `posthog.capture(...)` call, no `NEXT_PUBLIC_POSTHOG_*` env var, anywhere. This story is genuinely greenfield, not a gap-fill.

## Current State, Confirmed By Reading Every File This Story Touches

**Fully greenfield.** Zero PostHog references anywhere in `apps/web`.

**A pre-existing, separate analytics system already exists and must not be confused with this story's scope:** `apps/web/src/lib/analytics.ts`'s `trackEvent()` posts to `POST /api/analytics/events` against a closed `AnalyticsEventType` union (`tab_switch`, `retry_after_fail`, `jargon_hover`, `quiz_skip`, `teachback_skip`, `intervention_acknowledged`, `segment_complete`, `session_start`, `session_end`) that must match `apps/api/app/modules/analytics/service.py::KNOWN_EVENT_TYPES` exactly — this is **Dev 3's backend-owned CES/behavioral-scoring pipeline**, persisted to `session_events` and consumed by Learner DNA. None of this story's 8 PostHog event names overlap with that enum. **Do not add these events to that enum or call `trackEvent()` for them** — that would silently corrupt a contract Dev 3 owns. The two systems are additive and separate: this story adds new, independent `posthog.capture(...)` calls at some of the same UI moments `trackEvent()` already instruments for a different purpose.

**Next.js version confirmed:** `next@16.2.9` (`apps/web/package.json`) — supports `instrumentation-client.ts` (stable since 15.3), PostHog's own currently-recommended App Router integration. This sits beside `app/` inside `src/` (same convention as `apps/web/src/proxy.ts` living outside `app/`), runs once in the browser before hydration, and needs no provider component or `layout.tsx` change — simpler than the older `PostHogProvider`-wrapping pattern.

**Exact trigger points, confirmed by reading the real code (not the tracker's paraphrase):**

1. **`onboarding_completed`** — `apps/web/src/components/onboarding/OnboardingFlow.tsx`, the main submit-success path: `const data = await onboardingService.submitOnboarding(responses); ... setResult(data); setPhase("result");` (~line 174-177). **Not** the separate 409-recovery fallback path (~line 185-190) that re-fetches an already-completed profile — that's recovering from a duplicate submit, not a new completion, and firing there would double-count.
2. **`upload_started`** — `apps/web/src/components/dashboard/upload/UploadFlow.tsx`, `handleFile()` (~line 65-77), the success path after the 50MB size check passes (`setFile(selectedFile); setUploadState('processing');`). **Not** the oversized-file early return.
3. **`upload_completed`** — same file, the book-status poll reaching `status.status === 'ready'` (~line 131-133, `setUploadState('completed')`). **Correction to the tracker's own wording**: the tracker says "lesson_ready message received," but no WebSocket message named `lesson_ready` exists anywhere in `apps/web/src/lib/ws/wireTypes.ts` — confirmed by direct search. The book-status poll reaching `ready` is the real, closest equivalent (the book finished processing), not a lesson-level or WebSocket event. Named `upload_completed` per the tracker regardless, since that's the public event name already implied by the table.
4. **`lesson_started`** — `apps/web/src/stores/player.machine.ts`'s `play()` action (~line 193-198) sets `status: 'PLAYING'`, but this is re-entered on every resume from `PAUSED` and after `exitTeachBack()` (~line 297) — not just once per lesson. A naive effect watching `status === 'PLAYING'` would fire on every resume. Guarded with a mount-scoped ref in the consuming `Player.tsx`, firing only the first time `PLAYING` is observed per mount — since `PlayerLoader` is keyed by lesson id (S4-11's own fix), the whole player subtree remounts fresh per lesson visit, so a mount-scoped ref is the correct, already-available reset boundary.
5. **`lesson_completed`** — `apps/web/src/stores/player.machine.ts`'s `endLesson()` (~line 304-319) is the only call site setting `status: 'ENDED'` (from `advanceSegment()` when the last segment finishes). `Player.tsx` already has an exact precedent to mirror at ~line 214-219 (`useEffect(() => { if (status !== 'ENDED' || !sessionId) return; ...}, [status, sessionId])` for `completeSession`) — status never leaves `ENDED` once set, so no extra guard is needed; add the capture call alongside the existing one.
6. **`quiz_answered`** — `apps/web/src/components/player/QuizOverlay.tsx`'s `handleSubmit()` (~line 45-79). **Decision, stated explicitly rather than silently picked**: this function runs once *per question* in a multi-question quiz, not once for the whole quiz. Firing per-question (right after `setSubmitted(true)`, ~line 54) gives within-quiz drop-off visibility (how many questions answered vs. how many quizzes started), which is more useful for a funnel than a single per-quiz completion event — and `lesson_completed` already exists for the lesson-level terminal signal. If this reading is wrong, it's a one-line move (to the `isLast` success block, ~line 72) — flagged here so it's a reviewable decision, not an assumption.
7. **`teachback_submitted`** — `apps/web/src/components/player/TeachBackModal.tsx`'s `handleSubmit()` (~line 28-55), inside the success path after `setResult(teachBackResult)` (~line 48). The empty-text Skip path (~line 35-38, calls `exitTeachBack()` directly, never reaches `submitTeachBack`) must **not** fire this — that's a skip, not a submission.
8. **`intervention_received`** — `apps/web/src/components/player/TutorInterventionCard.tsx`'s existing `useEffect` (~line 60-75, deps `[visible, activeIntervention, setActiveIntervention]`). **Real double-fire risk found during research**: `visible` (~line 33) is `activeIntervention !== null && status !== 'TEACH_BACK'`. If a card is showing when `TEACH_BACK` starts, `visible` flips false without `activeIntervention` being cleared; when teach-back ends back to `PLAYING`, `visible` flips true again for the *same* intervention payload, and a naive capture on this effect would fire twice for one intervention. Guarded with a ref keyed on the intervention's identity (`JSON.stringify(activeIntervention)`, matching the existing `renderKey` derivation at ~line 54) so a given payload only ever fires once, independent of visibility toggling.

## Acceptance Criteria

1. **AC-1 (setup)** — `apps/web/src/instrumentation-client.ts` initializes `posthog-js` using `NEXT_PUBLIC_POSTHOG_KEY`/`NEXT_PUBLIC_POSTHOG_HOST` from env (never hardcoded). If the key is unset (local dev/CI without one configured), initialization is skipped — no crash, no events silently sent to a misconfigured/absent project.
2. **AC-2 (8 events fire exactly where specified above)** — each of the 8 events fires at its documented trigger point, with the documented exclusions (409-recovery, oversized-file, skip-path) correctly NOT firing.
3. **AC-3 (no double-fire)** — `lesson_started` and `intervention_received` each carry the specific guard described above (mount-scoped ref; identity-keyed ref) and are proven not to double-fire under their documented replay conditions (resume-from-pause; TEACH_BACK-then-back-to-PLAYING for the same intervention).
4. **AC-4 (no collision with Dev 3's `trackEvent`/`AnalyticsEventType`)** — none of the 8 events are added to `apps/web/src/lib/analytics.ts`'s `AnalyticsEventType` union or sent via `trackEvent()`; a guard test greps for any of the 8 event name strings inside `analytics.ts` and fails if found.
5. **AC-5 (properties are useful, not empty)** — each `posthog.capture()` call carries the IDs needed to build a real funnel (e.g. `lesson_id`, `book_id`, `session_id`, `question_id`/`quiz_index`, `intervention_type` — whatever is actually in scope at that call site), never a bare event name with no properties.
6. **AC-6 (tests)** — a unit test per event proving it fires under the success condition and does NOT fire under the documented exclusion/edge case (409-recovery, oversized file, skip path, resume-from-pause, TEACH_BACK-replay). `posthog-js` is mocked in tests — no real network calls, no real project pollution from CI runs.

## Scale & Load

Answering the six questions (`docs/SCALE-CONTRACT.md`):

1. **Unit of work and range:** one `posthog.capture()` call per qualifying user action; volume scales linearly with DAU × actions/session. No large-input concern — this is client-side event emission, not a query or a generation job.
2. **Fixed budgets vs. variable input:** N/A for code-level budgets — `posthog-js` batches/queues capture calls internally and manages its own flush timing; this story adds no new timeout, retry count, or size cap of its own.
3. **Scope of every limit:** the one real limit is PostHog's own account-level event quota (free tier: 1M events/month) — an externally-imposed, dashboard-visible limit, not something this code enforces or could silently exceed without PostHog's own dashboard showing it.
4. **Unbounded reads/writes:** none introduced — no DB reads/writes; this is entirely client-to-PostHog SDK calls.
5. **Inherited caps re-derived:** N/A — no cap carried over from an earlier design.
6. **Concurrent check-then-act safety:** the two double-fire guards (AC-3) are the real concurrency-adjacent concern. React's StrictMode double-invokes effects in dev, but a `useRef` value persists across that same-commit double-invoke (it isn't reset between the two calls), so both guards hold under StrictMode as well as under their real-world replay conditions (resume-from-pause, TEACH_BACK-round-trip) — this is asserted by AC-3's tests, not just claimed.

## Tasks / Subtasks

- [x] Task 1 (AC: 1): `apps/web/src/instrumentation-client.ts` — init with env-sourced key/host, skip-if-unset guard.
- [x] Task 2 (AC: 2, 5, 6): `onboarding_completed`, `upload_started`, `upload_completed` — wired + tested.
- [x] Task 3 (AC: 2, 3, 5, 6): `lesson_started` (mount-scoped ref guard), `lesson_completed` — wired + tested.
- [x] Task 4 (AC: 2, 5, 6): `quiz_answered`, `teachback_submitted` — wired + tested.
- [x] Task 5 (AC: 2, 3, 5, 6): `intervention_received` (identity-keyed ref guard) — wired + tested.
- [x] Task 6 (AC: 4): guard test (`no-posthog-events-in-analytics-ts.test.ts`) — none of the 8 event names appear in `analytics.ts`. Full `apps/web` suite (87 files, 1038 tests), lint (0 errors), typecheck, and a production build all green.

## Dev Notes

### What NOT to do

- Do NOT add any of the 8 event names to `AnalyticsEventType` in `apps/web/src/lib/analytics.ts`, or call `trackEvent()` for them — that union is Dev 3's contract with the backend's `KNOWN_EVENT_TYPES`, a completely separate system from PostHog.
- Do NOT hardcode the PostHog key or host anywhere — `NEXT_PUBLIC_POSTHOG_KEY`/`NEXT_PUBLIC_POSTHOG_HOST` only.
- Do NOT fire `lesson_started` on every `PLAYING` transition (resume-from-pause, post-teach-back) — mount-scoped guard required.
- Do NOT fire `intervention_received` twice for the same intervention payload across a TEACH_BACK visibility round-trip — identity-keyed guard required.
- Do NOT fire `quiz_answered`/`teachback_submitted` on a skip path — only on a real submission.
- Do NOT wrap this in a `PostHogProvider` React component — `instrumentation-client.ts` is the current, simpler, officially-recommended App Router integration for this Next.js version; no `layout.tsx` change needed.

### Testing standards

Vitest + Testing Library, matching this repo's existing `apps/web/src/__tests__/` conventions. `posthog-js` is mocked (`vi.mock('posthog-js', ...)`) in every test touching a capture call — no real network calls, no real PostHog project pollution from CI.

### References

- [Source: docs/dev2-sprint-tracker.md, S4-03] — origin of this task.
- [Source: apps/web/src/lib/analytics.ts, apps/api/app/modules/analytics/service.py] — the separate, pre-existing system this story must not collide with.
- [Source: apps/web/src/stores/player.machine.ts, apps/web/src/components/player/Player.tsx] — `lesson_started`/`lesson_completed` trigger points and the existing ENDED-effect precedent to mirror.
- [Source: apps/web/src/components/player/TutorInterventionCard.tsx] — the TEACH_BACK visibility-toggle double-fire risk for `intervention_received`.

## Dev Agent Record

### Implementation Plan

- **Setup**: `apps/web/src/instrumentation-client.ts`, Next.js's officially-recommended App Router integration for client-side instrumentation (stable since 15.3, confirmed against `next@16.2.9` in `package.json`) — no `PostHogProvider` component or `layout.tsx` change needed, simpler than the older provider-wrapping pattern. Skips `posthog.init(...)` entirely if `NEXT_PUBLIC_POSTHOG_KEY` is unset.
- **Grounding before wiring**: a dedicated research pass read the real trigger-point code for all 8 events rather than trusting the tracker's one-line paraphrases — this caught two real double-fire risks before they shipped (see below) and one stale tracker claim (no WS message named `lesson_ready` exists anywhere).
- **`lesson_started` guard**: a mount-scoped `useRef` in `Player.tsx`, not a bare status-transition effect — `PLAYING` is re-entered on every resume-from-pause and after `exitTeachBack()`. Since `PlayerLoader` is already keyed on `lesson_id` (S4-11), `Player` remounts fresh per lesson visit, making a mount-scoped ref the correct, already-available reset boundary.
- **`intervention_received` guard**: a `useRef` keyed on `JSON.stringify(activeIntervention)` (the same derivation `TutorInterventionCard.tsx` already uses for its remount key) — `visible` toggles false→true again for the SAME payload across a TEACH_BACK round-trip (the card hides, but `activeIntervention` itself isn't cleared), so a bare `visible`-watching effect would have double-fired.
- **`quiz_answered` fires per-question, not per-quiz** — a deliberate, documented choice (see the story's AC-6 clause) since `handleSubmit()` runs once per question in a multi-question quiz; `lesson_completed` already covers the lesson-level terminal signal.
- **No collision with Dev 3's system**: `apps/web/src/lib/analytics.ts`'s `trackEvent()`/`AnalyticsEventType` is a separate, backend-owned CES contract — confirmed by reading it directly, and guarded going forward by a dedicated test scanning for all 8 event name strings inside that file.

### Completion Notes

- All 6 tasks complete. Full `apps/web` suite: **87 files, 1038 tests passed** (1027 + 11 new: 8 from the new AC-4 guard test, 1 new `Player.test.tsx` `lesson_completed` test, 1 new `lesson_started` no-double-fire test, 1 new `TutorInterventionCard` no-double-fire test — the remaining events were tested via new assertions added to existing tests, not new test cases). `pnpm lint`: 0 errors, same 33 pre-existing warnings. `pnpm type-check`: clean. `pnpm build`: succeeds, `instrumentation-client.ts` compiles and is picked up correctly (confirmed via the build's own "Environments: .env.local" line).
- One transient full-suite failure (15 tests/6 errors, all `Object.onTimeoutError`/`Timeout._onTimeout` traces, 288s duration) on a first `pnpm test` run — re-ran immediately and got a clean 87/87, 1038/1038 pass at 120s duration. Diagnosed as resource-contention flakiness under the full parallel suite's load, not a real regression: every individually-run test file (all 7 touched by this story) passed cleanly on its own before the full-suite run was ever attempted, and the failure signature (bare timeout errors, no assertion failures) doesn't implicate any of this story's code.
- The user provided a real PostHog project API key and EU-cloud host directly in conversation (not via a formal account-request process — PostHog's free tier is self-serve, no business KYC/approval chain needed, unlike Razorpay). Set in `apps/web/.env.local` as `NEXT_PUBLIC_POSTHOG_KEY`/`NEXT_PUBLIC_POSTHOG_HOST`. **Not yet added to Vercel's production environment variables** — local dev only for now; production wiring is a follow-up when this is ready to ship live (same pattern as the beta-allowlist and Redis work earlier this sprint).

### File List

- `apps/web/src/instrumentation-client.ts` (NEW)
- `apps/web/.env.local` (MODIFIED — `NEXT_PUBLIC_POSTHOG_KEY`, `NEXT_PUBLIC_POSTHOG_HOST`; gitignored, not committed)
- `apps/web/package.json`, `apps/web/pnpm-lock.yaml` (MODIFIED — `posthog-js` dependency)
- `apps/web/src/components/onboarding/OnboardingFlow.tsx` (MODIFIED — `onboarding_completed`)
- `apps/web/src/components/dashboard/upload/UploadFlow.tsx` (MODIFIED — `upload_started`, `upload_completed`)
- `apps/web/src/components/player/Player.tsx` (MODIFIED — `lesson_started`, `lesson_completed`)
- `apps/web/src/components/player/QuizOverlay.tsx` (MODIFIED — `quiz_answered`)
- `apps/web/src/components/player/TeachBackModal.tsx` (MODIFIED — `teachback_submitted`)
- `apps/web/src/components/player/TutorInterventionCard.tsx` (MODIFIED — `intervention_received`)
- `apps/web/src/__tests__/components/onboarding/OnboardingFlow.test.tsx` (MODIFIED — posthog mock + 2 assertions)
- `apps/web/src/__tests__/components/dashboard/upload/UploadFlow.test.tsx` (MODIFIED — posthog mock + 3 assertions)
- `apps/web/src/__tests__/components/player/Player.test.tsx` (MODIFIED — posthog mock + 2 new tests)
- `apps/web/src/__tests__/components/player/QuizOverlay.test.tsx` (MODIFIED — posthog mock + 1 assertion)
- `apps/web/src/__tests__/components/player/TeachBackModal.test.tsx` (MODIFIED — posthog mock + 2 assertions)
- `apps/web/src/__tests__/components/player/TutorInterventionCard.test.tsx` (MODIFIED — posthog mock + 1 new test)
- `apps/web/src/__tests__/guards/no-posthog-events-in-analytics-ts.test.ts` (NEW — 8 tests)

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-08-27 | Story created after confirming PostHog is fully greenfield in `apps/web` (repo-wide search: no dependency, no provider, no capture calls, no env vars) and reading the real trigger-point code for all 8 events (not the tracker's paraphrase) — found and corrected the tracker's stale "lesson_ready message received" wording (no such WS message exists), found a real double-fire risk on `lesson_started` (PLAYING re-entered on resume) and `intervention_received` (TEACH_BACK visibility round-trip replays the same payload), and confirmed a pre-existing, separate Dev-3-owned `trackEvent`/`AnalyticsEventType` system this story must not collide with. User provided a real PostHog EU-cloud project key or account creation. Branch `sprint4/s4-03-posthog-instrumentation` off `sprint4-master`. | Dev 2 |
