# Developer 2 — Frontend Engineering Tracker
## HIE (Human Intelligence Engine)

---

| Field | Value |
|---|---|
| **Owner** | Developer 2 (Dell) |
| **Domain** | Frontend · Product Experience · Lesson Player · WebSocket Client |
| **PRD Version** | 1.0 Final — 10 June 2026 |
| **Last Updated** | 2026-08-11 (**S3-09 Signed-URL auto-refresh + DEFER-012 (D63) register entry shipped** — Story 2-45, ad-hoc off the Lesson Delivery Tracker's L3 known risk, not a scheduled Sprint 3 item; branch cut from `sprint3-master` since `main` doesn't yet have S3-01–S3-04. `AudioTimeline`/`SlideRenderer` now auto re-sign an expired asset once before falling back to the existing manual Retry/placeholder path. 920 web tests passing. See §12.) — previously 2026-08-06 (**S3-01 Attention Consent Modal shipped** — Story 2-42, 3-agent review passed, all 3 decision-needed + 12 patch findings resolved; switched to the real `POST /api/assessment/consent` endpoint (Story 3-32) after it landed on `main` mid-review, closing **D29**. **S3-04 CES Indicator confirmed shipped** — Story 2-41 (this file had drifted; it was done alongside S3-03 but never updated below). `sprint3-master` synced with `main` (also picked up **D18**/**D30** closures) and pushed. Sprint 3 is now 3/10 done — see §12.) — previously 2026-08-03 (S3-03 TutorInterventionCard shipped — Story 2-40, 3-agent review passed, 9 patches applied. See §12.) — previously 2026-07-29 (D27: `/signin` Suspense-boundary fix shipped — the app's first-ever successful production build. **S2-34** (browser SpeechSynthesis fallback, last tier of the TTS fallback chain) shipped: story-first commit, TDD implementation, 3-agent adversarial code review, 7 patches applied. **PR #114 merged `sprint2-master` into `main`** — S2-11 through S2-15, S2-34, and this file's own tracker updates are now all on `main` alongside the previously-direct-to-`main` S2-26/S2-33. `main` and `sprint2-master` are fully in sync as of this merge. **Cross-team Sprint 2 completion audit run same day — see note below; Dev 2's own scope is done, but the assessment path is blocked cross-team by D18.**) |
| **Active Sprint** | Sprint 3 — Weeks 6–7 (6/9 done — S3-01, S3-02, S3-03, S3-04, S3-07, S3-09; **note:** this row's "Total Tasks" in §1 has read 10 since before an earlier correction, and now 9 S3-numbered items (S3-01–S3-09) exist in this file after S3-09 was added as an ad-hoc item — a pre-existing count discrepancy, not fully resolved by this update, left flagged rather than silently resolved) |
| **Overall Status** | Sprint 0 COMPLETE · Sprint 1 COMPLETE (14/14) · Sprint 2 (Dev 2 scope) COMPLETE (10/10 + 8 additional stories) — **cross-team Sprint 2 is now end-to-end functional; D18/D29/D30 all closed 2026-08-04/05** · Sprint 3 IN PROGRESS (6/9 — S3-01, S3-02, S3-03, S3-04, S3-07, S3-09 done; S3-05/S3-06 unblocked now that S3-02 shipped; S3-08 not started) — **corrected 2026-08-11: S3-09 (signed-URL auto-refresh + DEFER-012/D63) added and shipped same day, ad-hoc off the Lesson Delivery Tracker rather than originally-scheduled Sprint 3 scope** |

---

> **Cross-team note (2026-07-13):** Dev 1's Sprint 1 backend content-ingestion pipeline merged to `main` (PR #72). Dev 1's Sprint 2 backend work (11 lesson-generation nodes, ending in `package_builder`) starts now — real `LessonPackage` JSONB is not available yet. Keep building/testing against `apps/web/src/mocks/data/lessonPackage.ts` and existing fixtures; do not stand up a parallel real-content path. Ping Dev 1 first if a mock is blocking progress. See `docs/master-tracker.md` for the full note.

> **Cross-team note (2026-07-23):** the `apps/web/src/mocks/data/lessonPackage.ts` blocker above is now resolved. A real PDF was uploaded and processed end-to-end through Dev 1's now-fixed content pipeline (segment_id sanitization + over-segmentation bugs both fixed), but the player showed "This lesson could not be loaded" — traced to `lesson.service.ts` still calling the mock, and (once that was found) to `GET /api/content/lessons/{id}` never having actually returned `content` at all (a genuine Sprint 1 gap, not new scope — Dev 1 confirmed and fixed via Story 1-6). Implemented the frontend half as **Story 1-7** (`docs/stories/1-7-wire-player-to-real-lesson-content.md`, branch `sprint1/s1-7-wire-real-lesson-content`): `lesson.service.ts`/`useLesson.ts` now call the real endpoint and surface `status`/`error` alongside the resolved package; `PlayerLoader.tsx` shows a real "still generating" state for `running`/`queued` and the real backend error for `failed`, instead of collapsing every non-ready response into a permanent error page; `AudioTimeline.tsx` degrades gracefully when a segment's `audio_url` is `""` (a real, reachable per-asset signing-failure value now, per Story 1-6's degrade-not-drop design). See `docs/master-tracker.md`'s "Lesson load from real API" line (now checked off).

> **Cross-team note (2026-07-23):** Learner Mode task **S2-10** ("Tier Badge on Player + Session Report") is now done, completing all of Dev 2's Sprint 2 Learner Mode tasks (S2-07–S2-10). It was blocked on Dev 3 adding a `tier` field to `SessionReport` — Dev 3 shipped that and more via **Stories 3-29** (tier/tier_label/quiz counts/quiz_accuracy_label) and **3-30** (learner_dna_snapshot), both merged to `main`. Implemented as **Story 2-10** (`docs/stories/2-10-tier-context-wiring.md`, branch `sprint2/s2-10-tier-context-wiring`): `Player.tsx` shows a persistent tier badge (`Full-Depth`/`Standard`/`Refresher`, from the already-available `lesson.metadata.tier` — needed zero backend work); `SessionReport.tsx` shows `tier_label` and a Learner DNA snapshot section (9 dimension labels + growth indicators, hidden when the user has no DNA profile yet). Also fixed a real bug found while scoping this: the report was displaying `quiz_score` as a raw percentage — replaced with absolute counts (`"3 / 4 correct"`) + the backend's own `quiz_accuracy_label`, matching the "never show a raw score" convention already used for CES/teach-back on this same page. Note: this branch's S2-07–S2-09 sections don't exist on `sprint2-master`'s copy of this file yet (they live on the still-unmerged `feature-learner-mode` branch) — this note stands alone until that branch merges and the full Learner Mode section reconciles.

> **Cross-team note (2026-07-23):** investigated Dev 3's **Story 3-28** (tier-aware quiz question count, 1–5 questions/segment instead of always 1, merged to `main`) to scope the frontend counterpart. Found `QuizOverlay.tsx` already correctly handles a variable question count end-to-end (no code change needed there) — but the investigation surfaced a real, pre-existing, currently-shipping bug unrelated to Story 3-28: the quiz score-summary feedback list used field names (`correct`/`message`) that don't match the real backend contract (`is_correct`/`explanation`, verified directly against `apps/api/app/modules/assessment/service.py::grade_quiz`), so every quiz result's feedback line has been rendering blank/`undefined`. Fixed as **Story 2-11** (`docs/stories/2-11-quiz-feedback-field-fix.md`, branch `sprint2/s2-11-variable-quiz-count`): `lib/assessment.ts`'s `QuizFeedbackItem` and `QuizOverlay.tsx`'s render corrected to the real shape; `types/assessment.ts`'s parallel, unused-at-runtime `QuizResult` type (which had the same wrong shape, backed by its own passing-but-wrong test) now reuses `lib/assessment.ts`'s type instead of re-declaring a third drifting copy.

> **Cross-team note (2026-07-23):** scoped and completed the frontend counterpart to Dev 3's **Story 3-31** (re-assessment prompt after every 10 sessions, adds `reassessment_due` to `GET /api/assessment/user/dna`, merged to `main`). Confirmed feasible end-to-end by reading the real backend directly: `types/assessment.ts`'s `LearnerDNA` already had `reassessment_due: boolean` matching the backend model field-for-field, and the onboarding submit endpoint's re-assessment bypass (clearing the idempotency lock before `SET NX`) needs no special-casing from the frontend at all. But found a real, blocking gap beyond "just add a banner": `OnboardingFlow.tsx`'s mount check unconditionally redirected any already-onboarded user (any 200 response) straight to `/dashboard`, never inspecting `reassessment_due` — meaning a "Take Assessment" CTA would have been a dead end. Fixed as **Story 2-12** (`docs/stories/2-12-reassessment-prompt.md`, branch `sprint2/s2-12-reassessment-prompt`): `OnboardingFlow.tsx`'s mount effect now proceeds into the disclaimer/questions flow when due instead of redirecting; new `ReassessmentPrompt.tsx` is a self-contained dismissible dashboard banner (own `getLearnerDna()` fetch, dismissal persisted to `localStorage` keyed on the specific `session_count` so a session-10 dismissal doesn't suppress the session-20 prompt) mounted on the dashboard page after `HeroSection`.

> **Cross-team note (2026-07-27):** live end-to-end testing (real backend + real Supabase, first time past `package_builder` landing for real) surfaced a batch of real gaps in one session: `apps/web/src/__tests__` had drifted against `OnboardingFlow.tsx`/`questions.ts` after a stale-path scan (fixed as a test-only correction, no product code change); assessment library test gaps and a `RubricScores` type drift were fixed as **Story 2-13** (`docs/stories/2-13-assessment-test-fixes.md`); dashboard/library were confirmed still mock-backed despite `GET /api/content/lessons` being real and ready, wired for real as **Story 2-14** (`docs/stories/2-14-real-dashboard-library.md`, dedup + wider lookup window + mock-pulse isolation added in review); the very first live test of that wiring then hit a 401 (Server Components can't use `api.ts`'s browser-only auth interceptor), fixed same-day as **Story 2-15** (`docs/stories/2-15-fix-dashboard-library-auth.md`) by converting both pages to Client Components with new `useDashboard`/`useLibrary` SWR hooks, matching the established `useLesson`/`useSessionReport` pattern.

> **Cross-team note (2026-07-29):** ran a full Sprint 2 completion audit at the user's request — two independent methods (every frontend page read in full for what it actually calls; every backend endpoint accessible to the frontend read in full for whether it's genuinely implemented and who calls it), then cross-referenced against each other and against all 4 devs' Sprint 2/Learner Mode tracker claims. **Full writeup: `docs/sprint2-completion-audit-2026-07-29.md`.** Headline: the upload→generate→play-lesson path is genuinely solid end-to-end (Dev 1 pipeline + Dev 2 frontend, nothing mocked, nothing stubbed). The assessment path (quiz/teach-back submission, session report) is structurally broken for any real student — not a frontend or backend bug, but the already-registered **D18**: nothing anywhere in `apps/api` ever creates a `sessions` row, so `POST /quiz`, `POST /teachback`, and `GET /session/{id}/report` (all correctly implemented) 404/lookup-miss in practice; still open, re-confirmed against `main` a day later. Two new defects found and registered: **D29** (DPDP `user_consents` table has a migration but zero writers — a CLAUDE.md §18 Sprint 2 priority, unmet) and **D30** (3 tests currently failing on `main` in `test_tutor_service.py`, reproduced live twice). One long-pending item resolved: **signed off on `docs/ws-message-contract.md`** after independently verifying it against `apps/api/app/core/websocket.py` line-for-line — caught and corrected one staleness in the doc itself (a 2026-07-24 PRD §18 fix had dropped `attention_ack`'s raw `ces` field, which the doc still described in its old shape) before signing off. Two small gaps found in my own domain, **both fixed same day**: Dashboard's "Reports" quick action linked to a dead `/reports` route (real route is session-scoped) — removed rather than repointed at a guess. Dev 3's `POST /api/analytics/events` was fully backend-ready but nothing in `apps/web` called it — added `lib/analytics.ts` and wired `jargon_hover`/`tab_switch` tracking. 7 new tests, full suite green (55 files / 567 tests).

> **Cross-team note (2026-07-29):** Dev 1's handoff (`docs/handoffs/dev2-handoff-2026-07-29.md`) flagged that `apps/web` had never produced a successful production build — `useSearchParams()` in `SignInForm.tsx` needs a Suspense boundary Next.js couldn't statically prerender around. Fixed same day (D27): `src/app/(auth)/signin/page.tsx` wraps `<SignInForm />` in `<Suspense>` with a new skeleton fallback (`SignInFormSkeleton.tsx`) matching the form layout. Verified locally with CI's exact env vars — `next build` now completes clean, `/signin` prerenders static. The same handoff's items 4a/4b (virtual playback clock, signed-URL retry re-fetch) turned out to already be shipped via S2-33 before the handoff was written. Item 4c (browser SpeechSynthesis, explicitly non-blocking) was implemented anyway per user request as **S2-34**. All of this, plus Stories 2-11 through 2-15 that had been sitting on `sprint2-master` unmerged, went to `main` together via **PR #114**.

> **Cross-team note (2026-07-27):** live-tested lesson generation end-to-end and found two real, live-reproducible pipeline bugs, reported to Dev 1: (1) quiz questions duplicating exactly 16× regardless of question count (2 unique → 32, 3 unique → 48); (2) a segment whose TTS synthesis failed showed "0:00 total time" and the quiz fired instantly. Root-caused both by reading `apps/api/app/modules/content/pipeline/graph.py` directly (not guessing from symptoms): (1) `PipelineState`'s `operator.add`-annotated reducer fields re-accumulate on any re-invocation; (2) `_fallback_narration()` hardcoded a blank script even though the real text was sitting in `state["narration_scripts"]`. Communicated to Dev 1 directly (not as a formal doc this time — see chat history if needed).

> **Cross-team note (2026-07-28/29):** Dev 1 fixed both bugs for real — verified directly in the merged diffs, not just taken on faith. **Bug 1** — PR #100 (Story 2-28): root cause was not what either of us first thought (ARQ only retries 3×, so 16 retries was never possible) — every downstream node was spreading `**state` into its return, which re-appends an already-accumulated `operator.add` list; `2⁴ = 16×` in a single clean run, no retry involved. Fixed by dropping the `**state` spread from every node's return. **Bug 2** — PR #101 (Story 2-31): `_fallback_narration()` now recovers the real script from `state["narration_scripts"]` before falling back to blank. Dev 1's own handoff (`docs/dev2-narration-playback-handoff.md`) correctly flagged that **the backend fix alone doesn't change what the student sees** — `AudioTimeline.tsx`'s `!hasAudio` branch still called `handleEnded()` immediately regardless of script presence, so the frontend half was still needed. Also separately requested a genuine gap in our own recent work: `retryAudio()` (Story 2-26) remounted the same expired signed URL rather than re-fetching a fresh one.

> **Cross-team note (2026-07-29):** implemented the frontend half of Bug 2, plus the retry re-fetch gap, as **Story 2-33** (`docs/stories/2-33-virtual-playback-clock.md`, merged to `main` via PR #106). `AudioTimeline.tsx` now branches three ways (`hasAudio` / `!hasAudio && hasScript` / neither) — the new `hasScript` case runs a `setInterval`-driven virtual playback clock that drives the exact same `processTimeUpdate` boundary logic a real `<audio>` element would, closing the "quiz fires at 0:00" symptom for real. `Player.tsx`'s Retry button now re-fetches the lesson (fresh signed media URL) before retrying. The 3-agent code review caught two real **High** severity bugs before merge, both fixed with regression tests: (1) a pre-existing `Player.tsx` mount effect keyed on the `lesson` **prop's object identity** rather than `lesson_id` silently reset all playback progress on every retry-triggered refetch — confirmed by all 3 reviewers, one of whom reproduced it directly; fixed with a `lesson_id`-keyed ref guard; (2) the virtual clock had no path to ever reach `ENDED` for a script-only last segment resumed after teach-back — fixed with a narrowly-scoped post-quiz `handleEnded()` call, safe against re-firing the quiz. Both bugs Dev 2 originally reported are now fully closed, frontend + backend.

> **Cross-team note (2026-07-29):** independently audited all of Dev 1's Sprint 2 pipeline deliverables (11 nodes + cost ceiling + WebSocket `lesson_ready` push + eval harness) against the actual current code, since `docs/master-tracker.md`'s Dev 1 Sprint 2 section is dated 2026-07-13 and still shows everything as not-started — badly stale. Confirmed genuinely done and correct: `lesson_planner`, `slide_generator`, `tts_node`, cost ceiling enforcement, the WebSocket push, and the eval harness (its live 5-PDF run is intentionally gated behind a test marker, not a gap). The two bugs above were the only real defects found.

> **Product bug (2026-07-29):** user reported the dashboard's mouse wheel scroll getting stuck (native scrollbar drag still worked) — a recurring issue, seen before on a different page. Root cause: `SmoothScroll.tsx` (Lenis) wraps the whole app and only calls `lenis.resize()` on route change; Lenis never observes DOM mutations on its own, so any page whose content grows after mount (SWR-fetched sections, images, async lists) leaves its cached scroll bounds stale — the wheel gets stuck at the old height while a scrollbar drag (reading the real DOM directly) still works. Fixed generally with a `ResizeObserver` on `document.body` inside `SmoothScroll.tsx`, calling `lenis.resize()` (rAF-debounced) on any body size change — fixes this class of bug for every page, not just the dashboard. Small, ad-hoc fix (no story per user's direction), merged to `main` via PR #108.

> **Tracker correction (2026-07-29):** Sprint 1's **S1-09** (Library Real Data Integration) and **S1-10** (Dashboard Real Data Integration) were still shown `NOT STARTED` in §10 below, but both were actually completed under Sprint 2 story numbers (**2-14**, **2-15**) — same underlying task, tracked twice across two sprint sections. Corrected in §10.

> **Cross-team note (2026-07-29):** **S1-05 (AvatarOverlay) shipped** — `docs/stories/1-5-avatar-overlay.md`, merged to `main` via PR #109. Confirmed cross-team sign-off (user, on behalf of all 4 devs) on `docs/proposals/avatar-fields-schema-change.md`, then independently re-verified the change was genuinely safe before touching the frozen contract: no direct `LessonPackage(...)` Pydantic constructor calls exist anywhere outside `apps/api/app/schemas/lesson.py` itself, and the only 2 full `LessonPackage`-literal sites on the frontend are unaffected by an added optional field. One corrected design decision vs. the proposal's own draft: the 3 new avatar fields are NOT marked `required` in the JSON schema — the draft's version would have repeated the exact `tier`/Story 2-25 regression (a retroactively-added required field breaks raw-schema validation of any pre-existing lesson/fixture that predates it). New `AvatarOverlay.tsx` is fully self-contained (zero changes to `Player.tsx`'s existing status conditionals) and gracefully skips every piece when its URL is absent — currently the only reachable case, since `package_builder_node` doesn't populate these fields yet (Dev 1's separate follow-up). 3-agent review caught and fixed 6 real issues (video watchdog timeout for a hung load, an intro-vs-audio-error z-index conflict, honest test wording after discovering this environment has no `uri` format checker installed, static-thumbnail error handling, and two stale-doc corrections — `GET /media/signed-url` is no longer a 501 stub, and `avatar-clips` was actually *removed* from its bucket allowlist by Story 2-25, both corrected in the proposal doc for whoever picks up the remaining backend wiring).

---

## 1. Quick Status Dashboard

| Sprint | Period | Total Tasks | Done | Partial | Not Started |
|---|---|---|---|---|---|
| Sprint 0 | Week 1 | 8 | **8** | 0 | 0 |
| Sprint 1 | Weeks 2–3 | 14 | **14** | 0 | **0** |
| Sprint 2 | Weeks 4–5 | 10 (+7 additional) | **17** | 0 | **0** |
| Sprint 3 | Weeks 6–7 | 10 (9 accounted for after S3-09 added — see header note) | **6** | 0 | **3** |
| Sprint 4 | Weeks 8–9 | 8 | 0 | 0 | **8** |
| Launch | Week 10 | 5 | 0 | 0 | **5** |
| **Total** | **10 weeks** | **56** | **33** | **0** | **23** |

> **Tracker correction (2026-08-06):** this file had drifted from reality on two points. (1) **S3-04 (CES Indicator)** was shipped alongside S3-03 (Story 2-41, same review pass, both merged to `sprint3-master`) but §12's entry and the dashboard above were never updated — corrected now. (2) **S3-01 (Attention Consent Modal)** shipped today as **Story 2-42**: 3-agent review found 3 decision-needed + 10 patch findings; mid-review, Dev 3's real **Story 3-32** (`POST /api/assessment/consent`) landed on `main` and closed **D29** — the consent write was switched from the tracker's originally-specified `PATCH /api/users/consent` (which never existed) to the real endpoint. `sprint3-master` was then synced with `main` (picking up D18/D29/D30, all now closed) and both S3-01's branch and the sync were merged in — 827/827 web tests, `tsc`/`eslint` clean. **S3-02 (AttentionMonitor) is now unblocked** — its only real dependency (consent gate + D29) is resolved.
>
> **Sprint 0 complete.** Sprint 1: only AvatarOverlay (blocked on schema sign-off) and upload/library/dashboard real-API wiring (blocked on Dev 1's Supabase implementation) remain. Codebase audit (2026-07-02) found S2-01 and S2-02 already implemented in commit `5c2b5c5` (2026-07-01) — QuizModal was shipped under the name **`QuizOverlay.tsx`** instead, plus an unplanned `PlayerControls.tsx` (seek bar, skip ±10s, speed control) shipped alongside. Both `QuizOverlay.tsx` and `TeachBackModal.tsx` had further wiring committed 2026-07-02 (`78b2646`) that adds live scoring feedback display. The same audit found **S1-07 (Real WebSocket Client) was falsely marked done** on 2026-06-29 — it has since been genuinely implemented via a BMAD story (`_bmad-output/implementation-artifacts/1-07-websocket-client.md`), including a real bug (resending `session_start` on reconnect would have forced CHECKING_IN/QUIZZING back to TEACHING) caught by an independent validation pass before implementation. A follow-up frontend security/bug audit (S1-13) found and fixed a real auth-guard gap in `middleware.ts` — `/library`, `/upload`, `/onboarding`, and `/lesson/[id]` were all completely unauthenticated. S1-14 then cleaned up 5 stale pre-existing test failures uncovered along the way. **All of the above (S1-07, S1-13, S1-14) is merged to `main` and pushed (`a4ca1d3`)** — working branches deleted, nothing left in flight.
>
> **UI/UX redesign (S1-15 → S1-18) complete as of 2026-07-03.** Brand recolor, hero rebuild, and a sitewide typography/consistency pass are merged to `main`. Sprint 1 remainder (AvatarOverlay, upload/library/dashboard real-API wiring) and Sprint 2 items resume from here.

> **⚠️ Important:** `src/components/lesson/InteractivePlayer.tsx` is a **320-line functioning mock player** (not a thin stub). It contains inline quiz, teach-back, and intervention UI using `MockLesson` types — not the frozen `LessonPackage` contract. It must be **replaced** by the real player stack (S1-01 through S1-06), not extended. Do not build on top of it. (Confirmed 2026-07-04 audit: it is correctly NOT wired into the live `/lesson/[id]` route — `PlayerLoader → Player` is what actually renders.)

## 0. App-Wide Audit (2026-07-04)

A 5-agent parallel audit of the entire `apps/web` frontend was run after S2-03 shipped. Full findings, severity, and tracker cross-references are in **`docs/app-audit-2026-07-04.md`** — read that file before picking up any new task, since several findings affect in-flight or upcoming work:

- **Critical, patched same day:** `/auth/callback` was missing from `middleware.ts`'s `PUBLIC_PATHS` — a regression from S1-13's allow-list→deny-list rewrite that broke ALL Google OAuth and email-confirmation sign-in. Also patched: an open-redirect risk via the callback's unvalidated `next` param, and banned "IQ/EQ/SQ" terminology that had leaked into the public `Footer.tsx` copy (CLAUDE.md compliance).
- **Confirmed NOT bugs — expected gaps, already tracked:** the tutor WebSocket (`useLessonSocket`) not being consumed by the player is correct — its consumers (`AttentionMonitor` S3-02, `TutorInterventionCard` S3-03, `CESIndicator` S3-04) are still Sprint 3 NOT STARTED. Dashboard/library/upload/settings running on mock data is also expected (S1-09/S1-10 blocked on Dev 1's backend).
- **Also patched same day:** `AuthContext` now implements the `supabase.auth.onAuthStateChange` listener that Section 15's own risk table already prescribed for token-expiry mid-lesson; the `useLesson` SWR hook no longer refetches (and silently resets the player mid-lesson) on browser tab-focus regain; dashboard's dead CTAs (Hero's "Resume Journey"/"Upload PDF", "View Path"/"View All") are now wired; `AudioTimeline`'s segment-replay freeze bug and empty-timestamps crash are fixed with its first-ever component-level tests; all 4 settings tabs (`ProfileTab`/`LearningTab`/`NotificationsTab`/`PrivacyTab`) now fetch/persist through `settingsService` instead of local dummy state, with `LearningTab`'s enum values corrected to match the real `LearningPreferences` type.
- **Still open — see audit doc for full list:** mock `/lesson/[id]` quiz/teachback submissions hitting the real backend with bogus IDs (needs backend session creation), landing-page brand-token cleanup (S4-01), accessibility pass (S4-04), and several dead-code/consistency nits.
- **Also patched (`/bmad-code-review` gate on `sprint2/codebase-audit-fixes`, same day):** `AuthContext`'s stale-`getUser()`-vs-live-`SIGNED_OUT` race and its `useRef(createClient())` re-evaluation anti-pattern; `safeNextPath` backslash open-redirect bypass; optimistic-update rollback on failure for all 3 live settings tabs; graceful thumbnail fallback on image load failure. 88 new tests added across all patches; 201/201 passing.
- **Process gap found and fixed (same day):** a status check found S2-03 (Onboarding Assessment Flow) — marked DONE above — had never actually been merged into `main`; the implementation commit was unpushed and its branch unmerged. Rebased onto current `main`, resolved cleanly (no conflicts despite heavy overlap with the audit-fix rounds above), verified (239/239 tests), and merged as PR #62 (`5c40db1`). See the S2-03 entry in §11 for the full writeup. Cross-referenced and corrected in `docs/master-tracker.md` too, where the corresponding "Onboarding assessment UI" and "Learner DNA profile display component" lines were still unchecked.
- **Full tracker-vs-codebase verification pass (same day):** every task marked DONE in this file was checked against the actual repo — file existence, presence on `main`, and a read-through of the implementation against its own acceptance criteria. Sprint 0 and the core Sprint 1 player stack (state machine, AudioTimeline binary search, SlideRenderer image fallback, JargonHover wiring, WebSocket client, middleware deny-list + DNA gate) all verified genuinely real and correct. Two real problems found in S2-01/S2-02: **`TeachBackModal.tsx` was rendering a numeric score and full rubric breakdown to the student — a direct hard-constraint violation** — and neither `QuizOverlay.tsx` nor `TeachBackModal.tsx` had any test coverage at all despite being P0. Fixed same day: score/rubric display removed (encouraging message only), submit button and textarea `autoFocus` corrected to match the documented ACs, a pre-existing `react-hooks/purity` violation in `QuizOverlay.tsx` (`Date.now()` called during render) fixed via a `useEffect`, and 18 new tests added across both components. See the S2-01/S2-02 entries in §11 for details. 257/257 tests passing, `tsc`/`eslint` clean.

---

## 2. Primary Files

### App Router — Pages & Layouts

```
apps/web/src/
├── app/
│   ├── layout.tsx                          ✓ EXISTS — root layout, font, theme
│   ├── (public)/
│   │   └── page.tsx                        ✓ EXISTS — landing page (sections assembled)
│   ├── (auth)/
│   │   ├── signin/page.tsx                 ✓ EXISTS — sign in page
│   │   └── signup/page.tsx                 ✓ EXISTS — sign up page
│   ├── (dashboard)/
│   │   ├── dashboard/
│   │   │   ├── layout.tsx                  ✓ EXISTS
│   │   │   └── page.tsx                    ✓ EXISTS — mock data wired
│   │   ├── library/
│   │   │   ├── layout.tsx                  ✓ EXISTS
│   │   │   └── page.tsx                    ✓ EXISTS — mock data wired
│   │   ├── upload/
│   │   │   ├── layout.tsx                  ✓ EXISTS
│   │   │   └── page.tsx                    ✓ EXISTS — UploadFlow wired
│   │   └── settings/
│   │       ├── layout.tsx                  ✓ EXISTS
│   │       └── page.tsx                    ✓ EXISTS
│   ├── lesson/
│   │   └── [id]/
│   │       ├── layout.tsx                  ✓ EXISTS
│   │       └── page.tsx                    ✓ EXISTS — stub, needs PlayerLoader
│   ├── onboarding/
│   │   └── page.tsx                        ✓ DONE 2026-07-04 — S2-03
│   ├── reports/
│   │   └── page.tsx                        ✗ NOT CREATED — Sprint 3
│   ├── pricing/
│   │   └── page.tsx                        ✗ NOT CREATED — Sprint 4
│   ├── payment/
│   │   ├── success/page.tsx                ✗ NOT CREATED — Sprint 4
│   │   └── cancel/page.tsx                 ✗ NOT CREATED — Sprint 4
│   └── middleware.ts                       ✓ EXISTS — route protection active
```

### Components

```
apps/web/src/components/
├── auth/
│   ├── SignInForm.tsx                       ✓ EXISTS
│   ├── SignUpForm.tsx                       ✓ EXISTS
│   └── LearnerEvolution.tsx                ✓ EXISTS — auth page visual
├── dashboard/
│   ├── shell/
│   │   ├── Sidebar.tsx                     ✓ EXISTS
│   │   └── TopUtilityBar.tsx               ✓ EXISTS
│   ├── sections/
│   │   ├── HeroSection.tsx                 ✓ EXISTS
│   │   ├── LearningPulse.tsx               ✓ EXISTS
│   │   ├── QuickActions.tsx                ✓ EXISTS
│   │   ├── ContinueLearningCard.tsx        ✓ EXISTS
│   │   └── RecentLessons.tsx               ✓ EXISTS
│   └── upload/
│       └── UploadFlow.tsx                  ✓ EXISTS — aligned to frozen WS contract
├── player/                                 ✗ ENTIRE DIRECTORY — Sprint 1
│   ├── PlayerLoader.tsx                    ✗ Sprint 1 — dynamic SSR:false wrapper
│   ├── Player.tsx                          ✗ Sprint 1 — root layout, owns AudioTimeline
│   ├── SlideRenderer.tsx                   ✗ Sprint 1 — renders Slide JSON
│   ├── AudioTimeline.tsx                   ✗ Sprint 1 — <audio> + timeUpdate handler
│   ├── AvatarOverlay.tsx                   ✗ Sprint 1 — HeyGen intro/outro + static
│   ├── JargonHover.tsx                     ✓ EXISTS — Radix tooltip wrapper (Sprint 1 wire-up)
│   ├── QuizOverlay.tsx                     ✅ DONE — shipped 2026-07-01 (renamed from planned QuizModal), further edits in progress uncommitted
│   ├── TeachBackModal.tsx                  ✅ DONE — shipped 2026-07-01, further edits in progress uncommitted
│   ├── PlayerControls.tsx                  ✅ DONE — not in original plan; seek bar, ±10s skip, speed control
│   ├── TutorInterventionCard.tsx           ✅ DONE 2026-08-03 — S3-03 (Story 2-40)
│   ├── CESIndicator.tsx                    ✅ DONE 2026-08-03 — S3-04 (Story 2-41)
│   ├── AttentionConsentModal.tsx           ✅ DONE 2026-08-06 — S3-01 (Story 2-42)
│   └── AttentionMonitor.tsx                ✗ Sprint 3 — MediaPipe WASM, next up
├── lesson/
│   └── InteractivePlayer.tsx               ✓ EXISTS — STUB, replace with PlayerLoader S1
├── library/
│   └── LibraryView.tsx                     ✓ EXISTS
├── sections/                               ✓ ALL EXIST — landing page sections
│   ├── Hero.tsx
│   ├── Features.tsx
│   ├── HowItWorks.tsx
│   ├── FAQ.tsx
│   ├── Pricing.tsx
│   ├── WhyTransformED.tsx (update to HIE)
│   ├── JourneyToSelfReliance.tsx
│   └── TransformationPromise.tsx
├── settings/
│   ├── SettingsTabs.tsx                    ✓ EXISTS
│   ├── SegmentedControl.tsx                ✓ EXISTS
│   ├── Toggle.tsx                          ✓ EXISTS
│   └── tabs/
│       ├── ProfileTab.tsx                  ✓ EXISTS
│       ├── AccountTab.tsx                  ✓ EXISTS
│       ├── LearningTab.tsx                 ✓ EXISTS
│       ├── PrivacyTab.tsx                  ✓ EXISTS
│       └── NotificationsTab.tsx            ✓ EXISTS
├── onboarding/                             ✗ Sprint 2
│   ├── OnboardingFlow.tsx
│   ├── QuestionCard.tsx
│   └── DNAResultCard.tsx
├── reports/                               ✗ Sprint 3
│   ├── SessionReport.tsx
│   ├── AttentionChart.tsx
│   ├── QuizAccuracyChart.tsx
│   └── MasteryTimeline.tsx
└── ui/                                     ✓ shadcn base components
    ├── button.tsx
    ├── input.tsx
    ├── label.tsx
    └── tooltip.tsx
```

### Contexts, Hooks, Services, Lib

```
apps/web/src/
├── contexts/
│   └── AuthContext.tsx                     ✓ EXISTS
├── hooks/
│   └── use-media-query.ts                  ✓ EXISTS
│   [to create:]
│   ├── usePlayerMachine.ts                 ✗ Sprint 1
│   ├── useLesson.ts                        ✗ Sprint 1
│   ├── useUploadProgress.ts               ✗ Sprint 1
│   ├── useLessonSocket.ts                  ✗ Sprint 1
│   ├── useAttentionMonitor.ts              ✗ Sprint 3
│   └── useCES.ts                          ✗ Sprint 3
├── services/
│   ├── dashboard.service.ts                ✓ EXISTS — mock
│   ├── upload.service.ts                   ✓ EXISTS — mock
│   ├── uploadGeneration.service.ts         ✓ EXISTS — aligned to ws contract
│   ├── lesson.service.ts                   ✓ EXISTS — mock
│   ├── library.service.ts                  ✓ EXISTS — mock
│   ├── reports.service.ts                  ✓ EXISTS — mock
│   ├── settings.service.ts                 ✓ EXISTS — mock
│   └── index.ts                            ✓ EXISTS
│   [to create:]
│   ├── assessment.service.ts               ✗ Sprint 2 — quiz + teachback API
│   └── onboarding.service.ts               ✗ Sprint 2 — DNA onboarding API
├── lib/
│   ├── api.ts                              ✓ EXISTS — axios instance
│   ├── utils.ts                            ✓ EXISTS
│   ├── supabase/
│   │   ├── client.ts                       ✓ EXISTS
│   │   ├── server.ts                       ✓ EXISTS
│   │   └── middleware.ts                   ✓ EXISTS
│   └── websocket/
│       ├── types.ts                        ✓ EXISTS — re-exports frozen ws contract
│       ├── mockEvents.ts                   ✓ EXISTS — WsMessage envelope factories
│       ├── mockSocket.ts                   ✓ EXISTS — GenerationProgressMessage format
│       ├── eventSequence.ts                ✓ EXISTS — 14-stage pipeline simulation
│       └── index.ts                        ✓ EXISTS
│   [to create:]
│   └── ws/
│       └── lessonSocket.ts                 ✗ Sprint 1 — real WS client with reconnect
├── stores/                                 ✗ Sprint 1
│   └── player.machine.ts                  ✗ Sprint 1 — Zustand player state machine
├── mocks/                                  ✓ ALL EXIST
│   ├── utils/delay.ts
│   ├── utils/response.ts
│   ├── data/users.ts
│   ├── data/uploads.ts
│   ├── data/lessons.ts
│   ├── data/reports.ts
│   └── api/ (dashboard, upload, library, reports, lesson, notifications, settings, auth)
└── middleware.ts                           ✓ EXISTS — protected route guard
```

---

## 3. Read-Only Dependencies

Developer 2 **consumes** these. Never modify them.

| Dependency | Location | Owner | Contract Type |
|---|---|---|---|
| `LessonPackage` TS types | `packages/shared/types/lesson.ts` | Dev 2 (published) | **Frozen Week 1** |
| WebSocket discriminated union | `packages/shared/types/ws.ts` | Dev 2 (published) | **Frozen Week 1** |
| JSON Schema | `packages/shared/lesson_package.schema.json` | Dev 2 (published) | **Frozen Week 1** |
| Quiz API (`POST /api/assessment/quiz`) | Dev 3 OpenAPI | Dev 3 | Consume-only |
| Teach-back API (`POST /api/assessment/teachback`) | Dev 3 OpenAPI | Dev 3 | Consume-only |
| Session Report API (`GET /api/session/{id}/report`) | Dev 3 OpenAPI | Dev 3 | Consume-only |
| Onboarding DNA API (`POST /api/onboarding/dna`) | Dev 3 OpenAPI | Dev 3 | Consume-only |
| WebSocket server (`/ws/{session_id}`) | Dev 4 FastAPI | Dev 4 | Consume-only |
| Pipeline submit (`POST /api/pipeline/submit`) | Dev 1 FastAPI | Dev 1 | Consume-only |
| Lesson package storage URLs | Supabase Storage | Dev 1 | Consume-only |
| Supabase DB schema | `supabase/migrations/` | Dev 1 | Never modify applied |

---

## 4. Interface Contracts

The following contracts are **frozen after Week 1**. Changes require a PR reviewed and approved by all 4 developers. Dev 2 is the author of the two frontend contracts.

### Contract 1 — Lesson Package Schema (Dev 2 Authors)
- **File:** `packages/shared/lesson_package.schema.json`
- **TypeScript mirror:** `packages/shared/types/lesson.ts`
- **Key types:** `LessonPackage`, `Segment`, `Slide`, `NarrationTimestamp {slide_id, start_ms, end_ms}`, `Narration`, `QuizQuestion`, `SegmentInterventions {distraction/confusion/fatigue: [string,string,string]}`, `LessonRecord`
- **CRITICAL:** `NarrationTimestamp.slide_id` is a string ID, NOT an array index. Binary search on `start_ms`, then look up slide by matching `slide_id` in `segment.slides`.

### Contract 2 — WebSocket Discriminated Union (Dev 2 Authors)
- **File:** `packages/shared/types/ws.ts`
- **Envelope pattern:** `WsMessage<T, P> = { type: T; payload: P }` — all messages use this shape. NOT flat objects.
- **Server → Client:** `lesson_ready`, `generation_progress`, `attention_ack`, `tutor_intervene`, `ces_update`, `state_change`, `error`
- **Client → Server:** `attention_signal` only

### Contract 3 — Assessment API (Dev 3 Authors)

```
POST /api/assessment/quiz
  Body:   { session_id, segment_id, question_id, selected_option, response_time_ms }
  Return: { correct: bool, explanation: str, segment_accuracy: float }

POST /api/assessment/teachback
  Body:   { session_id, segment_id, response_text }
  Return: { accuracy: float, completeness: float, clarity: float, overall: float }

GET  /api/session/{id}/report
  Return: { session_id, quiz: {...}, teachback: {...}, ces: float, interventions_fired: int, duration_minutes: int }
```

### Contract 4 — Upload / Pipeline API (Dev 1 Authors)

```
POST /api/pipeline/submit
  Body:   multipart/form-data { file: PDF }
  Return: { lesson_id: uuid, session_id: uuid }
  WS:     /ws/{session_id} receives generation_progress messages → lesson_ready on complete

POST /api/onboarding/dna
  Body:   { user_id, responses: [{ question_id, selected_option }] }
  Return: { dna_label: str, profile_narrative: str }
  Note:   Raw domain scores are NEVER returned to frontend.
```

---

## 5. Dependency Map

```
┌─────────────────────────────────────────────────────────────────┐
│                         HIE Platform                            │
│                                                                 │
│  ┌──────────────┐   lesson_package.json (S3/Supabase)          │
│  │    Dev 1     │──────────────────────────────────────────┐   │
│  │  Pipeline    │   /api/pipeline/submit                   │   │
│  │  FastAPI     │──────────────────────────────────────┐   │   │
│  └──────────────┘                                      │   │   │
│         │                                              │   │   │
│         │ ARQ job result                               │   │   │
│         ▼                                              │   │   │
│  ┌──────────────┐   /ws/{session_id}                   │   │   │
│  │    Dev 4     │◄─────────────────────────────────┐   │   │   │
│  │  WebSocket   │   attention_signal (5s cadence)   │   │   │   │
│  │  Tutor FSM   │──────────────────────────────────►│   │   │   │
│  │  Redis CES   │   tutor_intervene, ces_update      │   │   │   │
│  └──────────────┘   state_change                     │   │   │   │
│                                                      │   │   │   │
│  ┌──────────────┐   /api/assessment/quiz             │   │   │   │
│  │    Dev 3     │◄─────────────────────────────────┤ │   │   │   │
│  │  Assessment  │   /api/assessment/teachback        │ │   │   │   │
│  │  Reports     │──────────────────────────────────►│ │   │   │   │
│  │  DNA Scoring │   { correct, segment_accuracy }    │ │   │   │   │
│  └──────────────┘   /api/session/{id}/report         │ │   │   │   │
│                                                      │ │   │   │   │
│  ┌──────────────────────────────────────────────────┘ │   │   │   │
│  │                                                     │   │   │   │
│  │              ┌──────────────────────────────────────┘   │   │   │
│  │              │                                          │   │   │
│  ▼              ▼                                          ▼   │   │
│  ┌──────────────────────────────────────────────────────────┐  │   │
│  │                     Dev 2 (YOU)                          │  │   │
│  │              Next.js 14 App Router                       │◄─┘   │
│  │                                                          │◄─────┘
│  │  AuthContext → Supabase Auth → JWT cookie                │
│  │  PlayerLoader → Player → Zustand machine                │
│  │  AudioTimeline → binary search → SlideRenderer           │
│  │  AttentionMonitor → MediaPipe WASM → WS signal           │
│  │  QuizOverlay / TeachBackModal → Dev 3 assessment API     │
│  │  TutorInterventionCard ← Dev 4 tutor_intervene WS        │
│  │  UploadFlow → pipeline/submit → generation_progress WS   │
│  └──────────────────────────────────────────────────────────┘
│                                                                 │
│  Shared (Dev 2 publishes, all consume):                         │
│  packages/shared/types/lesson.ts                                │
│  packages/shared/types/ws.ts                                    │
│  packages/shared/lesson_package.schema.json                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 6. Architecture Overview

### Authentication

```
Browser → /signin → SignInForm → supabase.auth.signInWithPassword()
                                    → session cookie set by @supabase/ssr
                                    → redirect to /dashboard
Browser → /signup → SignUpForm → supabase.auth.signUp()
                                    → email verification sent
                                    → onboarding gate check

middleware.ts (Vercel Edge):
  - Reads session from cookie via createServerClient
  - /dashboard/* and /lesson/* and /upload/* require valid session
  - /lesson/* and /upload/* additionally require learner_dna.completed_at != NULL (Sprint 2)
  - Redirects to /signin if unauthenticated
  - Redirects to /onboarding if DNA not completed
```

### API Flow

```
Component → Service (services/*.service.ts)
              ├── [mock flag ON]  → mocks/api/*.ts → mock delay → mock data
              └── [mock flag OFF] → lib/api.ts (axios) → Authorization: Bearer JWT
                                      → FastAPI endpoint
                                      → Pydantic response model
                                      → typed TS response
```

Services act as a mock/real toggle boundary. The transition from mock to real in each sprint is a single-line change in the service — the component never changes.

### WebSocket Architecture

```
Sprint 0/1 (mock):
  uploadGenerationService → MockWebSocketClient
    → emits GenerationProgressMessage { type: 'generation_progress', payload: {...} }
    → emits LessonReadyMessage         { type: 'lesson_ready', payload: {...} }

Sprint 1+ (lesson player — real):
  lib/ws/lessonSocket.ts → native WebSocket → /ws/{session_id}
    Client → Server: AttentionSignalMessage every 5s (from AttentionMonitor)
    Server → Client: TutorInterveneMessage (dispatch to player machine)
                     CesUpdateMessage (update CES indicator)
                     StateChangeMessage (sync tutor state display)
```

All WebSocket messages use the frozen `WsMessage<T, P>` envelope. No flat objects.

### Lesson Player State Machine

```
States: IDLE → PLAYING → PAUSED → QUIZ → TEACH_BACK → ENDED

store: stores/player.machine.ts (Zustand)
  state: PlayerState
  currentSegmentIndex: number
  currentSlideId: string           ← slide_id from NarrationTimestamp
  audioPositionMs: number
  quizFiredForSegment: Set<string> ← prevents double-fire on seek
  tutorState: TutorState           ← mirrors Dev 4 FSM state

AudioTimeline.tsx:
  <audio onTimeUpdate={handleTimeUpdate} />

  handleTimeUpdate(e):
    t = e.currentTarget.currentTime * 1000
    // binary search narration.timestamps sorted by start_ms
    idx = binarySearch(timestamps, t)
    targetSlideId = timestamps[idx].slide_id
    if targetSlideId !== store.currentSlideId:
      store.setCurrentSlide(targetSlideId)
```

### Protected Routes

```
middleware.ts checks:
  /dashboard/**   → require session
  /upload/**      → require session + DNA completed (Sprint 2)
  /lesson/**      → require session + DNA completed (Sprint 2)
  /settings/**    → require session
  /reports/**     → require session

Public routes (no auth check):
  /               landing page
  /signin         auth
  /signup         auth
  /pricing        public
  /privacy        public
  /terms          public
```

---

## 7. Primary Pages

### `/` — Landing Page
**Status:** ✓ Sections exist, needs Sprint 4 polish  
**Responsibility:** Full marketing page. Converts visitors to sign-ups. Sections: Hero, TheCrisis, Features, HowItWorks, CognitiveVisualization, ProductPreview, JourneyToSelfReliance, TransformationPromise, WhyHIE, Pricing, FAQ, FinalCTA.  
**Dev 2 owns:** All sections, layout, animation, CTA routing to /signup.

### `/signin` `/signup` — Authentication Pages
**Status:** ✓ COMPLETE  
**Responsibility:** Supabase auth flows. Error handling, loading states, redirect on success.

### `/dashboard` — Student Dashboard
**Status:** ✓ Mock data wired, Sprint 1: real API integration  
**Responsibility:** Shows lesson library, upload CTA, learning streak, continue-learning card, quick actions.

### `/library` — Lesson Library
**Status:** ✓ Stub with LibraryView, Sprint 1: real data + filtering  
**Responsibility:** All user lessons with status, generation progress, thumbnail, duration. Filter by status (generating/ready/failed).

### `/upload` — Upload & Generation
**Status:** ✓ UploadFlow wired to mock WS, Sprint 1: real pipeline API  
**Responsibility:** PDF drop zone → upload → real-time generation progress (14 pipeline stages via WebSocket) → auto-redirect to /lesson/{id} on completion.

### `/lesson/[id]` — Lesson Player
**Status:** ✓ Stub exists, Sprint 1: full player implementation  
**Responsibility:** The core product experience. Loads LessonPackage from Supabase Storage. Renders PlayerLoader → Player. Full state machine: audio sync, slide advance, jargon hovers, segment boundaries, quiz/teachback modals, tutor cards.

### `/onboarding` — Learner DNA Onboarding
**Status:** ✅ DONE 2026-07-04 (S2-03)  
**Responsibility:** 20-question multi-domain assessment (8 cognitive, 5 emotional, 7 self-direction). Progress bar. Legal disclaimer before questions start. Submit to `/api/assessment/onboarding/submit` (corrected from this doc's original `/api/onboarding/dna` — see S2-03 entry). Show completion screen. Required gate before lesson access via middleware.

### `/reports/[sessionId]` — Session Report
**Status:** ✅ DONE 2026-07-04 (S2-04) — v1. Sprint 3 will expand it with an attention timeline chart once MediaPipe data exists.  
**Responsibility:** Single-session report for a completed lesson session: quiz accuracy, teach-back outcome (as a label, never a raw score), CES (as a label), engagement summary, "Study Again" link. Note: the static `/reports` (no session id) — a separate, unbuilt, cross-session "learning progression" page already referenced by Sidebar/QuickActions nav — is NOT this page and remains out of scope/unbuilt.

### `/settings` — User Settings
**Status:** ✓ Tabs exist (Profile, Account, Learning, Privacy, Notifications) — Notifications now wired to real data (S3-07, ✅ done); Profile/Learning/Privacy tabs remain mock-backed, not yet scoped to a story.  
**Responsibility:** Profile management, notification preferences, privacy settings (attention consent toggle), account deletion.

### `/pricing` — Pricing Page
**Status:** Sections exist in landing, Sprint 4: standalone page  
**Responsibility:** Per-lesson credit model explanation, Stripe Checkout CTA, FAQ.

---

## 8. Component Ownership

### Shell & Navigation
| Component | File | Status |
|---|---|---|
| Root layout | `app/layout.tsx` | ✓ |
| Sidebar | `components/dashboard/shell/Sidebar.tsx` | ✓ |
| Top utility bar | `components/dashboard/shell/TopUtilityBar.tsx` | ✓ |
| Navbar (public) | `components/layout/Navbar.tsx` | ✓ |
| Footer (public) | `components/layout/Footer.tsx` | ✓ |
| Smooth scroll | `components/layout/SmoothScroll.tsx` | ✓ |

### Auth Components
| Component | File | Status |
|---|---|---|
| Sign-in form | `components/auth/SignInForm.tsx` | ✓ |
| Sign-up form | `components/auth/SignUpForm.tsx` | ✓ |
| Learner evolution visual | `components/auth/LearnerEvolution.tsx` | ✓ |

### Dashboard Sections
| Component | File | Status |
|---|---|---|
| Hero section | `components/dashboard/sections/HeroSection.tsx` | ✓ |
| Learning pulse | `components/dashboard/sections/LearningPulse.tsx` | ✓ |
| Quick actions | `components/dashboard/sections/QuickActions.tsx` | ✓ |
| Continue learning card | `components/dashboard/sections/ContinueLearningCard.tsx` | ✓ |
| Recent lessons | `components/dashboard/sections/RecentLessons.tsx` | ✓ |

### Upload Flow
| Component | File | Status |
|---|---|---|
| Upload flow | `components/dashboard/upload/UploadFlow.tsx` | ✓ aligned to WS contract |

### Lesson Player (Sprint 1–3)
| Component | File | Status |
|---|---|---|
| PlayerLoader | `components/player/PlayerLoader.tsx` | ✗ Sprint 1 |
| Player root | `components/player/Player.tsx` | ✗ Sprint 1 |
| Slide renderer | `components/player/SlideRenderer.tsx` | ✗ Sprint 1 |
| Audio timeline | `components/player/AudioTimeline.tsx` | ✗ Sprint 1 |
| Avatar overlay | `components/player/AvatarOverlay.tsx` | ✗ Sprint 1 |
| Jargon hover | `components/player/JargonHover.tsx` | ✓ Sprint 1 wire-up |
| Quiz overlay (planned as QuizModal) | `components/player/QuizOverlay.tsx` | ✓ DONE 2026-07-01 |
| Teach-back modal | `components/player/TeachBackModal.tsx` | ✓ DONE 2026-07-01 |
| Player controls (unplanned addition) | `components/player/PlayerControls.tsx` | ✓ DONE 2026-07-01 |
| Tutor intervention card | `components/player/TutorInterventionCard.tsx` | ✅ DONE 2026-08-03 |
| CES indicator | `components/player/CESIndicator.tsx` | ✅ DONE 2026-08-03 |
| Attention consent modal | `components/player/AttentionConsentModal.tsx` | ✅ DONE 2026-08-06 |
| Attention monitor | `components/player/AttentionMonitor.tsx` | ✅ DONE 2026-08-10 |

### Onboarding (Sprint 2)
| Component | File | Status |
|---|---|---|
| Onboarding flow | `components/onboarding/OnboardingFlow.tsx` | ✅ DONE 2026-07-04 |
| Question card | `components/onboarding/QuestionCard.tsx` | ✅ DONE 2026-07-04 |
| DNA result card | `components/onboarding/DNAResultCard.tsx` | ✅ DONE 2026-07-04 |

### Reports (Sprint 3)
| Component | File | Status |
|---|---|---|
| Session report | `components/reports/SessionReport.tsx` | ✗ Sprint 3 |
| Attention chart | `components/reports/AttentionChart.tsx` | ✗ Sprint 3 |
| Quiz accuracy chart | `components/reports/QuizAccuracyChart.tsx` | ✗ Sprint 3 |
| Mastery timeline | `components/reports/MasteryTimeline.tsx` | ✗ Sprint 3 |

---

## 9. Sprint 0 — Foundation
**Period:** Week 1 | **Status:** ✅ COMPLETE

### S0-01 — Next.js 14 + Tailwind v4 Setup
**Status:** ✅ DONE  
**Files:** `apps/web/`, `apps/web/package.json`, `tailwind.config.*`  
**Done:** App Router scaffolded, Tailwind v4 configured, shadcn/ui initialized via `components.json`, TypeScript strict mode, ESLint wired.

### S0-02 — Supabase Client Wiring
**Status:** ✅ DONE  
**Files:** `src/lib/supabase/client.ts`, `src/lib/supabase/server.ts`, `src/lib/supabase/middleware.ts`  
**Done:** Browser client (`createBrowserClient`), server client (`createServerClient`), middleware helper. Both use `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY`.

### S0-03 — Authentication Flow
**Status:** ✅ DONE  
**Files:** `src/app/(auth)/signin/page.tsx`, `src/app/(auth)/signup/page.tsx`, `src/components/auth/SignInForm.tsx`, `src/components/auth/SignUpForm.tsx`, `src/contexts/AuthContext.tsx`  
**Done:** Sign-in, sign-up, session restoration via `AuthContext`, `useAuth` hook, `fetchSession()`, `logout()`.

### S0-04 — Protected Route Middleware
**Status:** ✅ DONE  
**Files:** `src/middleware.ts`  
**Done:** Checks session cookie on `/dashboard/**`, `/settings/**`, `/lesson/**`, `/upload/**`. Redirects unauthenticated to `/signin`. `matcher` configured correctly.

### S0-05 — Dashboard Shell
**Status:** ✅ DONE  
**Files:** `src/components/dashboard/shell/Sidebar.tsx`, `src/app/(dashboard)/*/layout.tsx`  
**Done:** Sidebar navigation, dashboard layout wrapping, TopUtilityBar, route-based active state.

### S0-06 — Mock Layer
**Status:** ✅ DONE  
**Files:** `src/mocks/**` (12 files), `src/services/**` (7 service files)  
**Done:** Mock data for users, uploads, lessons, reports. Mock APIs for all endpoints. Service layer delegates to mocks during development.

### S0-07 — Shared TypeScript Types
**Status:** ✅ DONE  
**Files:** `packages/shared/types/lesson.ts`, `packages/shared/types/ws.ts`, `packages/shared/lesson_package.schema.json`  
**Done:** All 17 lesson package types published. WebSocket discriminated union with `WsMessage<T,P>` envelope. `@hie/shared` workspace package wired to `apps/web`. tsconfig path alias set.

### S0-08 — Mock WebSocket Client
**Status:** ✅ DONE  
**Files:** `src/lib/websocket/types.ts`, `src/lib/websocket/mockEvents.ts`, `src/lib/websocket/mockSocket.ts`, `src/services/uploadGeneration.service.ts`  
**Done:** `MockWebSocketClient` emits `GenerationProgressMessage` and `LessonReadyMessage` using the frozen `WsMessage<T,P>` envelope. `UploadFlow.tsx` handles `generation_progress`, `lesson_ready`, `error` event shapes correctly.

---

## 10. Sprint 1 — Core Player + Upload Integration
**Period:** Weeks 2–3 | **Status:** 🔲 NOT STARTED  
**Delivery gate:** Player renders a lesson from a mock `LessonPackage` fixture with correct audio-slide sync, verified manually. Upload flow talks to real pipeline API.

---

### S1-01 — Zustand Player State Machine
**Priority:** P0 — everything else depends on this  
**Status:** ✅ DONE <!-- completed: 2026-06-26 -->  
**Files to create:** `src/stores/player.machine.ts`

#### Implementation

```typescript
// src/stores/player.machine.ts
import { create } from 'zustand';
import type { LessonPackage, Segment } from '@hie/shared/types/lesson';
import type { TutorState } from '@hie/shared/types/ws';

type PlayerStatus = 'IDLE' | 'PLAYING' | 'PAUSED' | 'QUIZ' | 'TEACH_BACK' | 'ENDED';

interface PlayerStore {
  status: PlayerStatus;
  lesson: LessonPackage | null;
  currentSegmentIndex: number;
  currentSlideId: string | null;
  audioPositionMs: number;
  tutorState: TutorState;
  quizFiredForSegment: Set<string>;

  // Actions
  loadLesson: (pkg: LessonPackage) => void;
  play: () => void;
  pause: () => void;
  seek: (ms: number) => void;
  setCurrentSlide: (slideId: string) => void;
  advanceSegment: () => void;
  enterQuiz: () => void;
  exitQuiz: () => void;
  enterTeachBack: () => void;
  exitTeachBack: () => void;
  endLesson: () => void;
  setTutorState: (s: TutorState) => void;
  updateAudioPosition: (ms: number) => void;
}
```

**Key invariants:**
- `quizFiredForSegment` is a `Set<string>` of `segment_id` values. On seek backward, the set is NOT cleared — quiz re-fires only on forward segment traversal for the first time.
- `status` is the single source of truth. Audio element play/pause must follow `status`, not the other way around.
- `currentSlideId` uses the string `slide_id` from `NarrationTimestamp`, NOT an array index.

**Acceptance criteria:**
- [ ] `status` transitions: IDLE → PLAYING → PAUSED → PLAYING → QUIZ → TEACH_BACK → PLAYING → ENDED
- [ ] `setCurrentSlide` called by AudioTimeline on every timeUpdate; dispatches only when slide actually changes
- [ ] `quizFiredForSegment` prevents double-firing on segment revisit
- [ ] State is Zustand — no XState, no useReducer
- [ ] Unit test: mock 3-segment lesson, verify all state transitions in sequence

---

### S1-02 — PlayerLoader Component
**Priority:** P0  
**Status:** ✅ DONE <!-- completed: 2026-06-26 -->  
**Files to create:** `src/components/player/PlayerLoader.tsx`  
**Files to modify:** `src/app/lesson/[id]/page.tsx`

#### Implementation

```typescript
// src/components/player/PlayerLoader.tsx
import dynamic from 'next/dynamic';

const Player = dynamic(() => import('./Player'), {
  ssr: false,                         // REQUIRED — MediaPipe WASM + Web Audio API
  loading: () => <PlayerSkeleton />,
});

export function PlayerLoader({ lessonId }: { lessonId: string }) {
  const { data: lesson, error } = useSWR(
    `/api/lessons/${lessonId}`,
    () => lessonApi.getLesson(lessonId),
  );
  if (error) return <LessonErrorState />;
  if (!lesson) return <PlayerSkeleton />;
  return <Player lesson={lesson.content} />;
}
```

`app/lesson/[id]/page.tsx` must replace the current `InteractivePlayer` stub with `<PlayerLoader lessonId={id} />`.

**Acceptance criteria:**
- [ ] `ssr: false` confirmed — no `window is not defined` errors in server logs
- [ ] Loading skeleton shown during fetch
- [ ] Error state shown if lesson fetch fails
- [ ] `PlayerLoader` is the only `dynamic()` call — all child player components render normally inside

---

### S1-03 — AudioTimeline + Slide Sync
**Priority:** P0 — core player mechanic  
**Status:** ✅ DONE <!-- completed: 2026-06-26 -->  
**Files to create:** `src/components/player/AudioTimeline.tsx`

#### Binary Search Implementation

```typescript
function binarySearchTimestamps(
  timestamps: NarrationTimestamp[],
  currentMs: number,
): number {
  let lo = 0, hi = timestamps.length - 1, result = 0;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (timestamps[mid].start_ms <= currentMs) {
      result = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return result;
}

function handleTimeUpdate(e: React.SyntheticEvent<HTMLAudioElement>) {
  const ms = e.currentTarget.currentTime * 1000;
  store.updateAudioPosition(ms);

  const segment = lesson.segments[store.currentSegmentIndex];
  const idx = binarySearchTimestamps(segment.narration.timestamps, ms);
  const targetSlideId = segment.narration.timestamps[idx].slide_id;

  if (targetSlideId !== store.currentSlideId) {
    store.setCurrentSlide(targetSlideId);
  }

  // Segment boundary detection
  const segmentEnd = segment.narration.timestamps.at(-1)!.end_ms;
  if (ms >= segmentEnd && !store.quizFiredForSegment.has(segment.segment_id)) {
    store.enterQuiz();
  }
}
```

**Edge cases:**
- Seek backward past a previous segment: binary search re-runs correctly; quizFiredForSegment prevents re-quiz
- Audio `ended` event: call `store.endLesson()` if no more segments
- Seek during QUIZ state: disallow seek until quiz is dismissed

**Acceptance criteria:**
- [ ] Unit test: 30-timestamp fixture, assert correct `slide_id` returned at 20 random positions
- [ ] Sync latency < 100ms from audio position to slide update (manually verified)
- [ ] No linear scan — binary search only
- [ ] Segment boundary triggers `enterQuiz()` exactly once per segment per forward traversal

---

### S1-04 — SlideRenderer Component
**Priority:** P0  
**Status:** ✅ DONE <!-- completed: 2026-06-26 -->  
**Files to create:** `src/components/player/SlideRenderer.tsx`

Receives `Slide` from `LessonPackage` by `slide_id` lookup:

```typescript
interface SlideRendererProps {
  slide: Slide;
  isActive: boolean;
}
```

Renders: `slide.title`, `slide.bullets[]`, `slide.image_url` (with `slide.fallback_image_url` on error), jargon terms highlighted via `JargonHover`. Transition: `opacity` fade between slides (no layout shift).

**Acceptance criteria:**
- [ ] `image_url` loads from Supabase Storage signed URL; fallback shown on 404
- [ ] `slide.bullets` renders as styled list items, not raw text
- [ ] `JargonHover` wraps any term found in `segment.jargon[].term` within bullet text
- [ ] Slide change animates with a 150ms opacity transition — no jump
- [ ] `null` image shows a placeholder, not a broken img tag

---

### S1-05 — AvatarOverlay Component — ✅ 2026-07-29
**Priority:** P1  
**Status:** ✅ DONE — `docs/stories/1-5-avatar-overlay.md`, merged to `main` via PR #109. Unblocked after cross-team sign-off on `docs/proposals/avatar-fields-schema-change.md` (3 new optional `LessonPackage` avatar fields, corrected from the proposal's original "required" draft to avoid repeating the `tier`/Story 2-25 regression). 3-agent review, 6 findings fixed (watchdog timeout, audioError-yield guard, static-image error handling, honest format-checker fix, stale doc corrections, wording precision).
**Files:** `src/components/player/AvatarOverlay.tsx` (new), `src/components/player/Player.tsx`, `packages/shared/types/lesson.ts`, `packages/shared/lesson_package.schema.json`, `apps/api/app/schemas/lesson.py`

```
lesson start → play HeyGen intro video (lesson_package.avatar_intro_url)
lesson body  → show static avatar image (lesson_package.avatar_static_url)
lesson end   → play HeyGen outro video (lesson_package.avatar_outro_url)
```

The HeyGen video URL is **pre-generated at build time** — never call HeyGen API at player load. Player must not block on avatar — if video URL is null, skip intro/outro gracefully.

**Acceptance criteria:**
- [x] Intro video plays automatically before first audio segment
- [x] Static image shown during lesson body (mouth-animation "blink" cue implemented as a CSS pulse on the thumbnail)
- [x] Outro plays after `store.endLesson()` fires
- [x] If `avatar_intro_url` is null: skip silently, start lesson audio immediately
- [x] Video does not cause hydration error (`AvatarOverlay` is a normal import inside `Player.tsx`, covered by `PlayerLoader.tsx`'s existing single `dynamic(..., {ssr:false})` wrapper for the whole tree — no second dynamic import needed)

**Important caveat — not yet visible to real students:** `package_builder_node` doesn't populate the 3 new avatar fields yet (Dev 1's separate follow-up, explicitly out of scope for this story). Every real lesson today still has all 3 fields absent, so `AvatarOverlay` correctly renders nothing — this story's code is real, tested, and working, but the feature has no visible effect until that backend wiring lands. Also flagged during review: `GET /media/signed-url`'s `avatar-clips` bucket entry was removed by Story 2-25 (structurally broken path shape) — whoever picks up the backend follow-up needs to re-enable a corrected bucket entry (or make it public) as a prerequisite, not just resolve the original signed-URL-expiry question.

---

### S1-06 — JargonHover Wire-Up
**Priority:** P1  
**Status:** ✅ DONE <!-- completed: 2026-06-26 -->  
**Files to modify:** `src/components/player/JargonHover.tsx`, `src/components/player/SlideRenderer.tsx`

**Audit finding (2026-06-25):** `JargonHover.tsx` exists and is well-implemented — regex-based term detection, Radix tooltip, case-insensitive matching, longest-key-first ordering to prevent partial matches. Currently accepts a `dictionary?: Record<string, string>` prop and falls back to a hardcoded `MOCK_JARGON_DICTIONARY` of 9 security terms. It is already used inside `InteractivePlayer.tsx` (`<JargonHover text={slide.content} />`).

**What remains:** When `SlideRenderer.tsx` is built (S1-04), pass `segment.jargon` as the dictionary prop. Remove `MOCK_JARGON_DICTIONARY` fallback. Change the prop shape from `dictionary: Record<string,string>` to `jargon: JargonEntry[]` to match the frozen contract type.

```typescript
// In SlideRenderer: pass segment.jargon to JargonHover
<JargonHover jargon={currentSegment.jargon}>
  {slide.bullets[i]}
</JargonHover>
```

The component must find exact term matches (case-insensitive), wrap in `<Tooltip>`, and display the definition. Audio must NOT pause on tooltip hover.

**Acceptance criteria:**
- [ ] Terms in `segment.jargon[].term` are highlighted in bullet text
- [ ] Tooltip shows `jargon[].definition` on hover
- [ ] No audio pause on hover
- [ ] If a term appears in multiple bullets, all instances are highlighted

---

### S1-07 — Real WebSocket Client (Lesson Socket) — ✓ 2026-07-02
**Priority:** P1  
**Status:** ✅ DONE — implemented via BMAD story `_bmad-output/implementation-artifacts/1-07-websocket-client.md` on branch `sprint1/s1-07-websocket-client`. (Previous 2026-06-29 "done" marking was false — see the 2026-07-02 audit note this replaces. `player.machine.ts` is unchanged; `setTutorState` is now called from a live connection for the first time.)  
**Files created:** `src/lib/ws/wireTypes.ts`, `src/lib/ws/lessonSocket.ts`, `src/hooks/useLessonSocket.ts`, `src/__tests__/testUtils/fakeWebSocket.ts`, `src/__tests__/lib/ws/lessonSocket.test.ts`, `src/__tests__/hooks/useLessonSocket.test.ts`

**Deviations from the original sketch above** (that sketch predates the BMAD story and was found to be wrong on two points during implementation):
- **No Bearer token in the handshake.** `apps/api/app/core/websocket.py`'s `websocket_endpoint(websocket, session_id)` takes no auth parameter at all — confirmed by reading the live backend. `connect(sessionId, token)` still accepts `token` and stores it on the instance for forward-compatibility, but nothing sends it today.
- **`session_start` must be sent exactly once per external `.connect()` call, never resent on an internal reconnect.** `graph.py`'s `route_from_checking_in`/`route_from_quizzing` fall through to `TEACHING` for any unrecognized event — resending `session_start` mid check-in or mid-quiz would have silently kicked a student out. Caught by an independent fresh-context validation pass on the story file before implementation; see the story's Change Log for the full list of 8 issues that pass found and fixed.

**Acceptance criteria (see the story file for the full, verified set of 11 — 2 are richer than originally sketched here):**
- [x] Connects to `/ws/{session_id}`; sends `session_start` once to drive IDLE → TEACHING (no Bearer token — see deviations above)
- [x] Dispatches `tutor_intervene` (no-op, Sprint 3), `ces_update` (no-op, not live on any path yet), `attention_ack` (no-op, out of scope until Sprint 3 sends real signals), `lesson_ready` (no-op, fetch via REST per contract), `error` (normalized from the backend's flat `{error}` frame) — all handled in an exhaustive switch, not a `default:` fallthrough
- [x] Dispatches `state_change` to `store.setTutorState()` unconditionally, including the reconnect-sync case (`from_state === to_state`)
- [x] Reconnects with exponential backoff on drop (`2^attempt × 1000ms`, max 5 attempts, then gives up silently — no toast built, not in scope)
- [x] Lesson does NOT freeze or error if WS is unavailable — graceful degradation
- [x] `useLessonSocket` hook cleans up connection on unmount, no leaked sockets across re-renders
- [x] `session_start` sent on first connect only, never on reconnect (new AC, see deviations above)

13+ new tests (10 `lessonSocket.test.ts` + 11 `useLessonSocket.test.ts` after the post-review hardening pass), all passing. `npx tsc --noEmit` clean. **Partially unblocks** the master-tracker Sprint 2 item "Segment-end detection → CHECKING IN state" — only the receive side (server `state_change` → `store.setTutorState()`) is wired. The send side (telling the backend a segment ended via `sendControl({type:'segment_complete'})`) has no caller yet, and the UI reaction to `CHECKING_IN` once entered is also still separate, un-scoped work.

---

### S1-08 — Upload Flow — Real API Integration — ✓ 2026-07-13
**Priority:** P1  
**Status:** ✅ DONE — see `docs/stories/1-8-upload-real-api.md` for the full corrected story  
**Files modified:** `src/services/upload.service.ts`, `src/components/dashboard/upload/UploadFlow.tsx`

**This story's original sketch below was wrong** — written before Dev 1's backend existed, it assumed `POST /api/pipeline/submit` returning `{lesson_id, session_id}` with 14 named pipeline stages streamed over `/ws/{session_id}`. The real backend (merged to `main` at `d38f357`) has none of that: `POST /api/content/lessons` → `{lesson_id, job_id, status}`, and `GET /api/content/lessons/{id}` → flat `queued|running|ready|failed` only. There is no `generation_progress` WS message anywhere in the codebase. Implemented against the real contract instead: multipart upload + 5s status polling, no percentage/stage display (matches `S1-09`'s "not percentage — just Processing..." pattern). The mock WebSocket layer (`uploadGeneration.service.ts`, `lib/websocket/*`) was deleted as dead code. 12 new/updated tests, `tsc` clean.

<details>
<summary>Original (incorrect) sketch — kept for history</summary>

Replace mock in `upload.service.ts` with real call to `POST /api/pipeline/submit`:

```typescript
// upload.service.ts (real)
async submitPipeline(file: File): Promise<{ lesson_id: string; session_id: string }> {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await api.post('/api/pipeline/submit', formData);
  return data;
}
```

After getting `session_id`, connect `uploadGenerationService` real socket to `/ws/{session_id}` instead of mock. On `lesson_ready`, auto-redirect to `/lesson/{lesson_id}`.

**Acceptance criteria:**
- [ ] PDF file uploaded via multipart/form-data
- [ ] `session_id` from response used for WebSocket connection
- [ ] All 14 pipeline stage names displayed as human-readable steps
- [ ] On `lesson_ready`: `router.push('/lesson/{lesson_id}')` fires automatically
- [ ] On `error` event: error card with specific error message + "Try Again" button
- [ ] File size validation (max 50MB) on client before upload attempt

</details>

---

### S1-09 — Library Real Data Integration
**Priority:** P2  
**Status:** ✅ DONE <!-- corrected 2026-07-29: was stale, done via S2-14/S2-15 --> — shipped as **Story 2-14** (real `GET /api/content/lessons` wiring) + **Story 2-15** (fixed the 401 this introduced by moving the fetch client-side). See Dev 2 tracker §11 S2-14/S2-15 for full detail. This Sprint 1 entry was never updated after that work landed under its Sprint 2 story numbers — same underlying task, tracked twice; correcting here rather than double-counting.
**Files to modify:** `src/services/library.service.ts`, `src/components/library/LibraryView.tsx`

Replace mock with real call to `GET /api/lessons` (paginated, user-scoped via JWT). Add status filter tabs: All / Generating / Ready / Failed. Show generation progress for `status: 'generating'` lessons using a polling interval (every 10s) or WebSocket subscription.

**Acceptance criteria:**
- [ ] Library shows real lessons from authenticated user's account
- [ ] Status filter tabs functional
- [ ] Generating lessons show progress badge (not percentage — just "Processing...")
- [ ] Failed lessons show "Retry" button
- [ ] Empty state shown when user has no lessons
- [ ] Pagination works (load more or infinite scroll)

---

### S1-10 — Dashboard Real Data Integration
**Priority:** P2  
**Status:** ✅ DONE <!-- corrected 2026-07-29: was stale, done via S2-14/S2-15 --> — shipped as **Story 2-14** (real `GET /api/content/lessons` wiring, dedup + wider lookup window for the continue-learning card) + **Story 2-15** (fixed the 401). `GET /api/sessions/latest` never materialized as a separate endpoint (Dev 4 owns session state in Redis, not exposed via REST) — S2-14 derives "continue learning" from the same `GET /api/content/lessons` response instead. See Dev 2 tracker §11 S2-14/S2-15.
**Files to modify:** `src/services/dashboard.service.ts`

Replace mock data with real API calls:
- `GET /api/lessons?limit=3&sort=updated_at` for recent lessons
- `GET /api/sessions/latest` for continue-learning card
- Remove hardcoded streak / mastery data until Session Reports API is ready

**Acceptance criteria:**
- [ ] Recent lessons reflect actual user data
- [ ] Continue-learning card shows most recent in-progress lesson (or empty state)
- [ ] Loading skeletons shown during fetch
- [ ] Error state shown on API failure (non-blocking — rest of dashboard still loads)

---

### S1-11 — Player Loading + Error States — ✓ 2026-06-29
**Priority:** P1  
**Status:** ✅ DONE <!-- completed: 2026-06-29 -->  
**Files:** `src/components/player/PlayerLoader.tsx` + all player components

Every async boundary in the player needs a handled state:
- Lesson fetch: skeleton with pulsing slide placeholder
- Audio load: buffering spinner overlaid on slide (non-blocking)
- Audio error (404/network): toast + "Try Again" button
- Lesson package parse error: full-screen error card, report bug CTA

**Acceptance criteria:**
- [ ] Skeleton shown during lesson fetch (< 500ms before content appears with good network)
- [ ] Buffering state shown if audio stalls for > 2s
- [ ] All error states are recoverable — no broken UI requiring refresh
- [ ] `Suspense` boundary wraps PlayerLoader

---

### S1-12 — Player Sync Test Harness — ✓ 2026-06-29
**Priority:** P0 — build BEFORE adding features on top of timeline  
**Status:** ✅ DONE <!-- completed: 2026-06-29 -->  
**Files to create:** `src/__tests__/player/slideSync.test.ts`

```typescript
// slideSync.test.ts
describe('binary search slide sync', () => {
  const timestamps: NarrationTimestamp[] = [
    { slide_id: 'sl_1', start_ms: 0,     end_ms: 5000  },
    { slide_id: 'sl_2', start_ms: 5000,  end_ms: 12000 },
    { slide_id: 'sl_3', start_ms: 12000, end_ms: 20000 },
    // ... 30 entries total
  ];

  it('returns first slide at t=0',         () => { expect(search(timestamps, 0)).toBe('sl_1') });
  it('stays on slide at boundary',         () => { expect(search(timestamps, 4999)).toBe('sl_1') });
  it('advances exactly at start_ms',       () => { expect(search(timestamps, 5000)).toBe('sl_2') });
  it('handles t past end of last slide',   () => { expect(search(timestamps, 99999)).toBe('sl_N') });
  it('handles single-slide lesson',        () => { ... });
});
```

**Acceptance criteria:**
- [ ] All 10+ test cases pass in CI
- [ ] Test uses real `NarrationTimestamp[]` shape (with `slide_id`, `start_ms`, `end_ms`)
- [ ] Tests run in under 100ms total

---

### S1-13 — Frontend Security & Bug Audit — ✓ 2026-07-02
**Priority:** P0 (auth gap) / P2 (rest)
**Status:** ✅ DONE — merged to `main` and pushed (`a4ca1d3`). Ad hoc audit, scoped to `apps/web` only. Working branches (`sprint1/s1-07-websocket-client`, `sprint1/codebase-security-audit`) were local-only, never pushed, and have been deleted now that everything landed on `main`.

Ran a dedicated bug/security sweep of the frontend at the user's request. **Scope note:** explicitly limited to Dev 2's own domain — `apps/api` (backend) is Dev 1/Dev 4 territory and was deliberately left untouched after an initial over-broad pass was corrected mid-session.

**Fixed:**
- **`middleware.ts` (HIGH — real auth-guard gap):** the route-protection check only matched `/dashboard` and `/settings` via `pathname.startsWith()`. Because `/library` and `/upload` live under the `(dashboard)` route group (invisible in the URL) and `/onboarding`/`/lesson/[id]` are separate top-level routes, all four were reachable and fully rendering with **zero session check**. Replaced the allow-list with a deny-list (`PUBLIC_PATHS = {"/", "/signin", "/signup"}`, everything else requires a session) — fails safe for any future route too. Added `__tests__/middleware.test.ts` (15 cases) so this can't silently regress.
- **`UploadFlow.tsx` (LOW — resource leak):** the generation effect's cleanup only called `unsubscribe()`, never `uploadGenerationService.disconnect()`. Since the socket is a module-level singleton, navigating away mid-generation (or completing/erroring) left the mock generation loop running with `isConnected` still `true`. Cleanup now calls `disconnect()` too.

**Checked and dismissed as non-issues:**
- `lucide-react@^1.17.0` flagged elsewhere as a "suspicious version" — verified against `node_modules` it resolves to a real published `1.21.0`. False positive.
- No XSS, no hardcoded secrets, no unsafe token storage found (JWT handling in `lib/api.ts`/`AuthContext.tsx` already correct — uses server-verified `getUser()`, never `localStorage`).
- `player.machine.ts`/`AudioTimeline.tsx` state machine and binary-search logic reviewed — no race conditions or off-by-one errors found.

**Flagged, not fixed (deferred — bigger decisions, not bugs):**
- `InteractivePlayer.tsx` — dead code, explicitly commented "DO NOT IMPORT," confirmed unused except its own test. Left in place; deleting an existing tested file wasn't asked for.
- `PrivacyTab.tsx`'s "Camera-Based Focus Detection" toggle is local-`useState`-only, not wired to any backend or the `user_consents` audit table CLAUDE.md requires. Not an active violation (no attention-capture code exists yet to consent to), but the toggle visually implies a working control that does nothing. Sprint 2/3 scope.
- `apps/web/package.json` has Next 16.2.9 / React 19.2.4 vs. the CLAUDE.md-locked "Next.js 14" stack — a governance/team decision, not something to unilaterally downgrade.

Full `apps/web` suite immediately after these fixes: 132 tests, 127 passing, 5 pre-existing unrelated failures (see S1-14 — fixed same day).

---

### S1-14 — Fix 5 Stale Pre-Existing Test Failures — ✓ 2026-07-02
**Priority:** P2
**Status:** ✅ DONE — merged to `main` and pushed (`a4ca1d3`)

The 5 failures noted in S1-13 (`player.machine.test.ts`, `AudioTimeline.test.ts` ×2, `PlayerLoader.test.tsx`, `SlideRenderer.test.tsx`) were investigated and confirmed to be **stale tests, not regressions** — commit `5c2b5c5` ("full lesson player") intentionally redesigned several behaviors and rewrote the mock lesson fixture, but the tests were never updated to match:

- `AudioTimeline.test.ts` — asserted against the old `sl_0_0: 0–15000ms / sl_0_1: 15000–30000ms` fixture; real fixture is `0–35000ms / 35000–92000ms`. Updated both the slide-sync and segment-end-quiz-trigger tests to the real boundaries.
- `player.machine.test.ts` — `exitTeachBack()` on the last segment intentionally resumes `PLAYING` (not `ENDED`) so remaining audio plays out; `ENDED` only fires later via `AudioTimeline`'s `handleEnded()`. Updated the full-traversal test to expect `PLAYING`, then call `store.endLesson()` directly to still cover the `ENDED` transition.
- `PlayerLoader.test.tsx` — a completed fetch with a null lesson and no explicit error is intentionally treated as `LessonErrorState`, not a skeleton. Updated the assertion accordingly.
- `SlideRenderer.test.tsx` — `SlideImage` intentionally renders nothing (not a placeholder box) when both `image_url` and `fallback_image_url` are null. Updated the test to assert neither element exists.

Full `apps/web` suite: **132/132 passing, zero failures.** `npx tsc --noEmit` clean.

---

### S1-15 — Brand Recolor (Navy / Gold / Grey) — ✓ 2026-07-02
**Priority:** P1
**Status:** ✅ DONE — implemented via BMAD story `_bmad-output/implementation-artifacts/1-15-brand-recolor.md` on branch `sprint1/s1-15-brand-recolor`

Rebranded the entire frontend color system from the generic SaaS blue (`#2F80ED`) to the palette extracted from the actual HIE logo: Deep Navy `#07172C` (primary), Metallic Gold `#C6A45C` (accent), Grey `#797B7D`/`#6B6D6F` darkened (secondary text), Off-white `#F9F9F9` (background). Went through BMAD's full story-creation → validation → UX design review → implementation pipeline before any code changed:

- **Technical validation** (fresh-context adversarial pass): verified WCAG contrast math independently, and caught that the original hardcoded-literal sweep missed an entire category — Tailwind `blue-*`/`sky-*`/`indigo-*` utility classes across 13 additional files, on top of the 6 already found. Expanded before implementation started.
- **UX design review (Sally):** flagged that confining gold to thin borders/glows would read as "a navy site with gold in a few dark corners" rather than a real navy+gold identity. Recommended the **gold-fill + navy-text pattern** (solid gold background with navy content on top — same ~7.6:1 contrast ratio as gold-on-navy, just inverted) as the default for buttons, badges, and active states, plus specific placement: the sidebar's active-nav-item gets a gold-fill icon badge (previously it had nowhere safe to put gold at all, since the sidebar is light, not navy).
- **Implementation:** remapped both `globals.css` token blocks; fixed 19 files across two literal-sweep categories; fixed 2 confirmed contrast violations named ahead of time (`button.tsx` primary gradient, `HeroSection.tsx` stat text) **plus 4 more found only by grepping repo-wide during implementation** — all four were previously-safe light-blue usages that became unsafe gold usages purely because the token's underlying value changed (`signup/page.tsx`'s dark-panel heading gradient and border accent, `TopUtilityBar.tsx`'s avatar-fallback gradient, `Sidebar.tsx`'s "HIE" wordmark gradient). Implemented the required sidebar gold-fill indicator (AC11). Deliberately did **not** force gold into `QuizOverlay`'s correct/incorrect states (already correctly semantic green/red) or invent a streak badge in `ContinueLearningCard` (no natural slot) — both evaluated and explicitly declined per the story's own "don't force it, don't invent new UI" guidance.
- **Manual visual verification:** actually ran the app (`next dev` + Playwright headless screenshots), not just code review — caught a stale Turbopack `.next` cache serving the old blue theme on the first check, cleared it, re-verified. Confirmed the gold-fill button and gold heading gradient render correctly on the sign-up page; landing page nav/hero CTAs correctly remain navy+white (never touched by the gold rules, since they were never gold in the first place).
- One remaining gold+navy gradient combo exists only in `InteractivePlayer.tsx` — confirmed dead code (`DO NOT IMPORT OR EXTEND`, unused except its own test per the S1-13 audit) — left untouched, not in this story's scope.

Full `apps/web` suite: **132/132 passing, zero failures.** `npx tsc --noEmit` clean throughout.

**Code review:** 3-layer adversarial review (Blind Hunter, Edge Case Hunter, Acceptance Auditor) run against commit `6ba908b`. Found and fixed a text-secondary/text-muted grey collapse, an inconsistent gold-vs-navy ambient-glow remap, and 3 real contrast misses (`CognitiveVisualization.tsx` SVG stroke, `SettingsTabs.tsx` active-tab underline, a `Pricing.tsx` confetti label/value mismatch). One candidate finding was reconsidered and dismissed on inspection. 4 pre-existing/out-of-scope items deferred to `_bmad-output/implementation-artifacts/deferred-work.md` (most notable: `/onboarding` page has dead Tailwind classes and is the only route that'll flip to dark mode under OS dark-mode — needs its own follow-up story).

**Post-review manual testing catch:** user spotted the "Phase 01"–"Phase 04" labels in `JourneyToSelfReliance.tsx`'s "Evolution of a Learner" section were invisible (navy `text-primary` on its `bg-slate-900` section) — missed by both the implementation sweep and the code review since it was a `--color-primary` usage, not `--accent-secondary`. Fixed to gold, matching that section's own established dark-surface-accent pattern.

Merged to `main` (`36aff5f`) via direct merge commit (no PR, per established team practice for this branch).

---

### S1-18 — Hero Redesign + Brand Consistency Pass — ✓ 2026-07-03
**Priority:** P1
**Status:** ✅ DONE — implemented directly (no BMAD story this time, fast-iteration UI work), on branch `sprint1/s1-18-hero-redesign`

Follow-up to S1-15: the palette was right but the hero itself was flagged as "just a generic hero with left side text and right side a modal" and several sections still read as templated. Rebuilt in stages, each validated against real feedback before moving on:

- **Hero (`Hero.tsx`) rebuilt from scratch, twice.** First pass replaced the text-left/screenshot-right split with a single left-aligned column (statement → full-width "stage" → CTA) and an animated "Independence Meter" concept — rejected as still structurally identical to the original. Second pass ("The Interruption"): the stage is now a live demo that *enacts* HIE's actual mechanic instead of symbolizing it — real text reads itself with a moving caret, drifts into passive mode (unread tail blurs), gets interrupted inline with an active-recall prompt, answers, and resumes; pausable on hover; rotates through 3 passages per loop; respects `prefers-reduced-motion`.
- **Copy pressure-tested before committing:** new headline "Study smarter. Then study alone." replaced an earlier draft that used "obsolete" — an independent adversarial-critic pass flagged that as weakness-coded and self-defeating for a subscription product ("why am I still paying if it's working?"), so it was reframed as a mastery outcome instead. Also fixed a second instance of the IQ/EQ/SQ compliance bug found in the hero copy (same class of issue as S1-15).
- **Fit-to-viewport constraint:** hero tuned and verified via real Playwright screenshots at both 1440×900 and 1366×768 (a smaller/older laptop resolution), including at the demo's tallest animation frame (prompt card open) — no scroll required at either size.
- **Typography system:** added Fraunces (serif) via `next/font/google` alongside the existing Inter/Outfit, exposed as `--font-serif`/`font-serif`. Applied to every genuine headline moment sitewide — the remaining landing sections (TheCrisis, TransformationPromise, Features, HowItWorks, ProductPreview, JourneyToSelfReliance, Pricing) and their card/phase titles, the Navbar/Footer wordmark, both auth pages' panel and form headlines, all authenticated pages (dashboard, settings incl. all 5 tabs, library incl. every lesson card, upload incl. all 4 flow states), and the lesson player (slide titles, quiz question, teach-back prompt/score, lesson-complete headline) — replacing the generic geometric-sans-everywhere look with one consistent voice.
- **Navbar rebuilt** as a floating glassmorphic pill (backdrop-blur, ambient tint, top-edge sheen) with a matching floating glass mobile menu, replacing the old full-width edge-attached bar.
- **FAQ and FinalCTA redesigned** — the two most templated patterns on the page (centered accordion-on-grey, dark-rounded-CTA-box). FinalCTA's copy now directly bookends the hero's own line ("You know how to study smarter now. / The *alone* part is up to you."). Also fixed hardcoded old-blue-family hex colors (`#f8fafc`/`#e8eef3`) still hiding in `FAQ.tsx` since S1-15's sweep predated the file's redesign.
- **Lesson player restyled** (`components/player/*`) — this was the biggest hidden gap: the actual product experience was still on a completely generic near-black palette (`neutral-950`, `#0a0a0f`, `#0d0d14`, `#13131c`) with zero connection to the navy/gold brand. Rebuilt on the brand's actual navy-dark tokens and established a clear 3-color system: navy for structural UI, gold for reward/highlight signals (jargon tooltips, progress fill, play button, primary submit/continue CTAs, lesson-complete badge), emerald/red untouched for semantic correctness. Caught and fixed a real bug in the process: the seek-bar progress fill was navy and about to sit on a new navy control-bar background, which would have made it invisible — fill is now gold instead.
- `LearnerEvolution.tsx` (signup page) rebuilt: was a flat vertical dot-list using phase names that didn't even match the canonical journey vocabulary used on the landing page — now a live auto-advancing horizontal progress track using the exact canonical phase names (Passive Consumer → Guided Learner → Active Synthesizer → Self-Reliant Scholar).

`npx tsc --noEmit` clean and `npx vitest run` 132/132 passing at every checkpoint. Merged to `main` (`3d41df5`) via direct merge commit, no conflicts with Dev 3's concurrent onboarding/analytics API work.

---

## 11. Sprint 2 — Assessment + Session Flow
**Period:** Weeks 4–5 | **Status:** ✅ 10/10 done — S2-01–S2-06 plus Learner Mode S2-07–S2-10 all complete, see entries below  
**Dependency:** Dev 3 assessment API must be callable (can mock responses if not ready) — confirmed live 2026-07-01

---

### S2-01 — QuizModal Component
**Priority:** P0  
**Status:** ✅ DONE <!-- completed: 2026-07-01 --> — shipped as `QuizOverlay.tsx` (name diverged from plan; also handles a `questions[]` array internally rather than one question per mount, a richer scope than originally planned)  
**Files created:** `src/components/player/QuizOverlay.tsx`, `src/__tests__/components/player/QuizOverlay.test.tsx` (2026-07-04 — was previously shipped with zero test coverage, caught during a tracker-vs-codebase verification pass)

**2026-07-04 fix (found during the same verification pass):** `questionStartMs` read `Date.now()` directly during render — an impure call the `react-hooks/purity` lint rule (correctly) rejects, since it can drift on re-render. Moved to a `useEffect` keyed on `questionIndex`, covering both initial mount and question-advance in one place (removed the redundant manual reset that used to live in `handleNext`). Also corrected the stale "further edits in progress, currently uncommitted" note above — the working tree was already clean; last real change landed inside the S1-18 merge commit.

Triggered by `store.enterQuiz()` when segment boundary is crossed in AudioTimeline. Renders the `QuizQuestion` from `segment.quiz[]` as MCQ.

```typescript
interface QuizModalProps {
  question: QuizQuestion;
  segmentId: string;
  sessionId: string;
  onSubmit: (result: { correct: boolean; explanation: string }) => void;
}
```

**Flow:**
1. Audio pauses (`store.status === 'QUIZ'`)
2. Modal slides up from bottom
3. Student selects option → submit button activates
4. POST `/api/assessment/quiz` with `{ session_id, segment_id, question_id, selected_option, response_time_ms }`
5. Show result: green/red highlight on selected option + explanation text
6. "Continue" button → `store.exitQuiz()` → `store.enterTeachBack()`
7. Audio remains paused until TeachBackModal complete

**HARD CONSTRAINTS (from PRD):**
- NEVER block lesson progress on quiz score — "Continue" must always be available after answering
- No quiz timer UI
- Response time recorded client-side (`Date.now()` delta) but not shown to student

**Acceptance criteria:**
- [x] Quiz fires at end of each segment, exactly once per segment per forward traversal — covered by `player.machine.ts`'s `enterQuiz`/`quizFiredForSegment` tests, not re-tested here
- [x] `quizFiredForSegment` Set prevents double-fire on seek — same as above
- [x] POST to assessment API fires on submit — `QuizOverlay.test.tsx`, confirmed with the exact `{session_id, lesson_id, segment_id, answers[]}` payload
- [x] Correct/incorrect feedback shown with explanation — tested
- [x] "Continue" button always present after submitting, including when the API call rejects — tested
- [ ] Audio confirmed paused during quiz (HTMLAudioElement.paused === true) — covered indirectly by `AudioTimeline`'s own "pauses when status is not PLAYING" test, not re-verified here
- [x] Mock mode: assessment.service uses mock response until Dev 3 API ready — real endpoint (`/assessment/quiz`) is live per Dev 3, `lib/assessment.ts` calls it directly

---

### S2-02 — TeachBackModal Component
**Priority:** P0  
**Status:** ✅ DONE <!-- completed: 2026-07-01 --> — corrected 2026-07-04, see fix note below  
**Files created:** `src/components/player/TeachBackModal.tsx`, `src/__tests__/components/player/TeachBackModal.test.tsx` (2026-07-04 — was previously shipped with zero test coverage)

**🔴 2026-07-04 fix — real hard-constraint violation found during a tracker-vs-codebase verification pass:** the result view was rendering `{overall_score}%` in large text plus a full per-dimension rubric breakdown (`accuracy`/`completeness`/`clarity`, each as a percentage) directly to the student — a straight violation of this task's own "never show a rubric score" constraint and CLAUDE.md's "no clinical scores shown to students." No test existed to catch it. Fixed: result view now shows only `result.feedback` (the encouraging free-text message) plus a generic "Nice work!" heading — `overall_score` and `rubric_scores` are received from the API but never rendered. Two smaller AC misses fixed in the same pass: submit button read "Submit" (spec says "Submit & Continue"), and the textarea had no `autoFocus`. Also corrected the stale "further edits in progress, currently uncommitted" note — working tree was already clean.

Follows QuizModal in the segment boundary flow. Student types a free-text explanation.

```typescript
interface TeachBackModalProps {
  teachbackPrompt: string;  // from segment.teachback_prompt
  segmentId: string;
  sessionId: string;
  onSubmit: () => void;
}
```

**HARD CONSTRAINTS:**
- **NO TIMER.** No countdown, no time remaining, no time elapsed display.
- Never show a rubric score to the student in Phase 1
- Submit button should say "Submit & Continue"
- Feedback display after scoring: show an encouraging message, NOT a score

**Acceptance criteria:**
- [x] No timer present in the component (DOM inspection should show zero timer elements) — tested
- [x] POST to `/api/assessment/teachback` fires on submit — tested with the exact `{session_id, lesson_id, segment_id, response_text}` payload, trimmed
- [x] Feedback shown as encouraging message, not a numeric score — was FAILING until the 2026-07-04 fix above; now tested and enforced (asserts no `\d+%` text and no rubric dimension labels anywhere in the result view)
- [x] "Skip" option present (allowed per PRD — never block progress) — tested
- [ ] Audio paused until `store.exitTeachBack()` fires — covered indirectly by `AudioTimeline`'s own "pauses when status is not PLAYING" test, not re-verified here
- [x] Textarea auto-focuses on modal open — was FAILING until the 2026-07-04 fix; now tested

---

### S2-03 — Onboarding Assessment Flow — ✓ 2026-07-04 (merged to `main` 2026-07-04)
**Priority:** P1  
**Status:** ✅ DONE <!-- completed: 2026-07-04 --> — implemented via BMAD story `docs/stories/2-3-onboarding-assessment-flow.md` on branch `sprint2/s2-3-onboarding-flow`, 5-agent adversarial code review passed (14 patches applied), 170 tests passing.  
**Files:** `src/app/onboarding/page.tsx`, `src/components/onboarding/{OnboardingFlow,QuestionCard,DNAResultCard,questions}.tsx/.ts`, `src/services/onboarding.service.ts`, `src/types/assessment.ts` (added `OnboardingResult`), `src/middleware.ts`, `src/lib/supabase/middleware.ts`

**⚠️ Merge-gap correction (2026-07-04, later same day):** this task was marked DONE above the moment the story/review completed, but the implementation commit (`6066032`) was never pushed and the branch was never merged into `main` — a status audit found `apps/web/src/components/onboarding/` simply didn't exist in a fresh `main` checkout. The branch was rebased onto current `main` (which had since gained the codebase-audit-fixes rounds 1–8 and Dev 3's CES/DNA-fusion work), merged with zero conflicts, verified (239/239 tests, `tsc`/`eslint` clean), and landed as **PR #62 (`5c40db1`)**. "Done" in this tracker from now on should mean confirmed present via `git merge-base --is-ancestor <branch> main`, not just "story + review complete."

20-question Learner DNA assessment. Required gate before first lesson.

```
page.tsx → OnboardingFlow
  → mount check: GET /api/assessment/user/dna (200 → already done, skip to /dashboard; 404 → continue)
  → LegalDisclaimer (shown once, must be acknowledged)
  → QuestionCard × 20 (one at a time, animated transition)
  → POST /api/assessment/onboarding/submit
  → DNAResultCard (shows badge_labels + profile_text)
  → redirect to /dashboard
```

**Deviation from the original sketch above** (discovered during implementation — the real backend contract differs from this doc's original field names): the real, live, tested backend endpoint is `POST /api/assessment/onboarding/submit` (not `/api/onboarding/dna`), returning `{badge_labels: string[], profile_text: string, session_count: number}` — **not** `dna_label`/`profile_narrative`. `profile_text` already includes the DPDP disclaimer sentence server-side. See the story file's Dev Notes for the full contract-discrepancy writeup (the `_bmad-output/planning-artifacts/epic-3-assessment-dna.md` epic doc and `docs/openapi-assessment.json` are both stale on this point).

**HARD CONSTRAINTS (all met):**
- Legal disclaimer shown and acknowledged before question 1 ✓
- Raw domain scores never fetched/stored/rendered ✓
- No IQ, EQ, SQ labels anywhere in the UI ✓
- Only `badge_labels` and `profile_text` are user-facing, and only after submission ✓

**middleware.ts update (Sprint 2):** ✓ done — gates `/lesson/**` and `/upload/**` on the presence of a `learner_dna` row (queried directly via Supabase, RLS-scoped), fails open on DB errors/exceptions. Does NOT gate `/dashboard`, `/onboarding`, `/library`, `/settings`.

**Acceptance criteria:**
- [x] Legal disclaimer shown before questions
- [x] 20 questions rendered, one at a time with animated transition
- [x] Progress bar shows question X / 20
- [x] POST fires with all 20 responses batched
- [x] DNA result card shows `badge_labels` and `profile_text` (not scores)
- [x] After result dismissed, user lands on /dashboard
- [x] Middleware blocks /lesson and /upload until onboarding complete

---

### S2-04 — Session Report Page v1 — ✓ 2026-07-04
**Priority:** P1  
**Status:** ✅ DONE <!-- completed: 2026-07-04 --> — implemented via BMAD story `docs/stories/2-4-session-report-page.md` on branch `sprint2/s2-4-session-report`  
**Files:** `src/types/assessment.ts` (fixed `ces_breakdown` shape — real bug, see below), `src/lib/assessment.ts` (`getSessionReport`), `src/hooks/useSessionReport.ts` (new), `src/lib/utils.ts` (`formatCesLabel`/`formatTeachbackLabel`), `src/components/reports/SessionReport.tsx`, `src/app/reports/[sessionId]/page.tsx`, `src/components/player/Player.tsx` (ENDED screen wiring)

**Route corrected from the original sketch** (resolved with the user before starting, see the story file's Context section for the full writeup): this task's original file target, `src/app/reports/page.tsx`, collides with an unrelated, unbuilt, cross-session "learning progression" analytics page already referenced by `Sidebar.tsx`/`QuickActions.tsx` nav links (backed by `reportsService.getReports()`/`mocks/data/reports.ts` — zero live callers, explicitly out of scope, untouched). This story's single-session report instead lives at **`src/app/reports/[sessionId]/page.tsx`**.

**Real backend contract verified directly against `apps/api` before implementation** (not just trusted from docs): `GET /api/assessment/session/{session_id}/report` is live (`router.py:106-132`), not a stub — the original sketch's "Mock response used until Dev 3 delivers API" was already stale. **A real, pre-existing bug was found and fixed:** `types/assessment.ts`'s `SessionReport.ces_breakdown` used wrong key names (`quiz_accuracy`, nested `teachback_score`) that never matched the real, frozen backend contract's actual keys (`quiz`, `teachback`, `behavioral`, `head_pose`, `blink`) — caught because this type had zero live callers until this story gave it one.

**Hard constraint extended from the TeachBackModal fix earlier this sprint:** `teachback_score` is also never shown as a raw number in this report — mapped to a qualitative label (`formatTeachbackLabel`) for the same reason CES is (CLAUDE.md: no clinical/rubric scores shown to students).

**Known cross-team blocker, does not block this story:** nothing in `apps/api` currently creates a row in the `sessions` table `get_session_report` reads from (confirmed by grep — same gap already flagged in `docs/app-audit-2026-07-04.md` finding #5 re: quiz/teachback submissions). This story was built and tested entirely with mocked `useSessionReport`/`getSessionReport` responses; end-to-end manual QA against a real session isn't possible until that gap is closed by whoever owns session lifecycle (Dev 4).

**Acceptance criteria:**
- [x] Report shows correct quiz accuracy percentage (single session-level number — the real API has no per-segment breakdown; "by segment" descoped, see story Dev Notes)
- [x] CES shown as descriptive label, not raw float — regression-guarded test asserts no digit ever appears
- [x] Teach-back shown as a descriptive label, not raw float — same regression guard
- [x] Report accessible only to the lesson owner (enforced by API via existing JWT interceptor — no extra frontend work needed)
- [x] Empty/error state if report not yet generated/fetch fails, with a link back to `/dashboard`
- [x] `Player.tsx`'s lesson-complete screen links to the new report instead of the old "available in Sprint 2" placeholder

29 new tests (4 type, 4 hook, 10 label-function, 7 component, 2 Player wiring + 2 fixed-in-place). Full suite: 276/276 passing. `tsc`/`eslint` clean.

---

### S2-05 — Player State Persistence (Session Restore) — ✓ 2026-07-06
**Priority:** P2  
**Status:** ✅ DONE <!-- completed: 2026-07-06 --> — implemented via BMAD story `docs/stories/2-5-player-state-persistence.md` on branch `sprint2/s2-5-player-state-persistence` — the last Sprint 2 item, Sprint 2 is now 5/5 done  
**Files:** `src/lib/binarySearch.ts` (new — extracted from `AudioTimeline.tsx` to avoid a circular import), `src/components/player/AudioTimeline.tsx` (re-export only, no behavior change), `src/stores/player.machine.ts` (`saveProgress`, `restoreProgress`), `src/components/player/Player.tsx` (mount-effect wiring)

On page refresh mid-lesson, restores: current segment index, current audio position, `quizFiredForSegment` set. `localStorage` key `hie:session:{lesson_id}`, throttled writes (~2s, via a module-scoped timestamp reset per `loadLesson()` call) plus immediate checkpoint saves on `pause()`/`advanceSegment()`.

**Real bug found and fixed during story-writing, not in the original sketch:** without also resolving `currentSlideId` on restore (via the same `binarySearchTimestamps` `AudioTimeline.tsx` already uses), jumping straight to a restored `currentSegmentIndex` would leave `currentSlideId` pointing at the previous segment's slide — since slide ids are segment-scoped, none of the new segment's slides would match, rendering a **blank slide area** until playback resumed and the next `timeupdate` tick corrected it. Fixed by resolving the correct slide as part of `restoreProgress` itself.

**Real cross-feature interaction found and fixed:** without clearing saved progress in `endLesson()`, a student who finishes a lesson and clicks Story 2-4's "Study Again" link (routes back to `/lesson/{lesson_id}`) would have been silently resumed near the *end* of the lesson instead of restarting — directly undermining that just-shipped feature. `endLesson()` now removes the saved entry.

Dev 4 restores tutor state from Redis on WebSocket reconnect — Dev 2 only needed to restore the player position.

**Acceptance criteria:**
- [x] Refresh on segment 2 restores to within ±3 seconds of last position (satisfied by the ~2s throttle plus checkpoint saves)
- [x] `quizFiredForSegment` persisted so quiz does not re-fire after restore
- [x] If stored session is > 24h old, discard it (use `stored_at` timestamp) — also discards and removes corrupted JSON, wrong-typed fields, and an out-of-bounds `segmentIndex` (e.g. lesson regenerated with fewer segments since the snapshot was saved)

**5-agent adversarial review (2026-07-06) — 7 patches applied, merged as PR #66:** `isStoredProgress` now requires `segmentIndex` to be an integer and `audioPositionMs`/`storedAt` to be finite (closing a `1e400`-style JSON-overflow bypass of the 24h expiry check); every `localStorage` call in `saveProgress`/`restoreProgress`/`endLesson` is now wrapped in try/catch instead of throwing inside `Player.tsx`'s mount effect; `restoreProgress` now guards against a `lessonId` mismatch against the currently-loaded lesson; `enterQuiz()` now saves immediately so a tab closed mid-quiz can't lose the quiz-fired flag; added a dedicated `binarySearch.test.ts`. 4 findings deferred (quiz-fired content-identity validation, no user/account scoping, no multi-tab `storage` event listener, `Player.tsx`'s pre-existing mount-effect re-run behavior — see `_bmad-output/implementation-artifacts/deferred-work.md`), 2 dismissed as noise.

24 new tests total (13 store-level + 2 `Player.tsx` restore-on-mount from initial implementation, plus 8 review-patch tests in `player.machine.test.ts` and 6 in the new `binarySearch.test.ts`). Full suite: 315/315 passing. `tsc`/`eslint` clean.

---

### S2-06 — Segment-End Detection → CHECKING_IN State — ✓ 2026-07-21
**Priority:** P2  
**Status:** ✅ DONE. Dev 4 replied to the escalation below confirming his fix (`dispatch_event` in `graph.py` now broadcasts `state_change` on every real FSM transition) — merged and unit-tested (44/44 passing) on his side, but not yet pushed/merged to `main` at the time. Per user instruction, proceeded to implement and ship this story built and tested against `FakeWebSocket` (same posture S1-07/S2-04 were already shipped against for their own backend dependencies) rather than wait on his push — a live end-to-end check against his real backend is a follow-up once his branch lands, not a design unknown (the wire shape is already frozen in `packages/shared/types/ws.ts`). Implemented via full BMAD story `docs/stories/2-6-segment-checkin.md` (branch `sprint2/s2-6-segment-checkin`, merged into `sprint2-master`): `useLessonSocket` now mounted live in `Player.tsx`; `AudioTimeline.tsx` sends `segment_complete` + an optimistic `setTutorState('CHECKING_IN')` at all 3 segment-boundary call sites, with zero added latency to the (unchanged) client-authoritative quiz trigger; new `CheckingInTransition.tsx` renders an edge-triggered ~500ms "Checking in…" overlay. 5-agent review round applied 3 patches (stuck-visible fix, `wsSendControl` instance-identity guard, `PlayerLoader` remount-per-lesson key) and deferred 2 (documented, out of scope). Full `apps/web` suite 373/373 passing at merge time. **This was the last open item in Dev 2's official Sprint 2 list — Sprint 2 is now 6/6 done.**  
**Files modified:** `src/components/player/Player.tsx`, `src/components/player/AudioTimeline.tsx`, `src/stores/player.machine.ts`, new `src/components/player/CheckingInTransition.tsx`, `src/hooks/useLessonSocket.ts`, plus all their tests

**Files likely touched:** `src/components/player/Player.tsx` or `PlayerLoader.tsx` (mount the socket), `src/components/player/AudioTimeline.tsx` (send on segment boundary), `src/stores/player.machine.ts` (`tutorState` already exists), a new CHECKING_IN UI component (none exists, blocked)

**Investigated 2026-07-06 — found the actual gap is larger than the master tracker's 2026-07-02 note suggested.** That note read as "just wire the send side," implying the receive side was already live. Verified against the actual code:

- `sendControl({type: 'segment_complete'})` — the exact mechanism needed — exists and is tested (`lessonSocket.ts`, `wireTypes.ts`, both from S1-07), but has **zero callers anywhere** in the codebase.
- `useLessonSocket` (the hook that would open the connection and receive `state_change`) is built and unit-tested **in isolation only** — it is **not mounted anywhere in the live player** (`Player.tsx`, `PlayerLoader.tsx`). The lesson WebSocket never actually connects during a real session today, regardless of what the backend sends.
- `tutorState` in `player.machine.ts` is written to via `setTutorState()` but has **zero readers** anywhere in the component tree — no CHECKING_IN screen or any other UI reacts to it. It's a dead field in production.
- Quiz triggering today is entirely **client-local**: `AudioTimeline.tsx` detects the segment boundary directly and calls `store.enterQuiz()` — no round-trip to the backend tutor FSM happens at all.
- `usePlayerStore.sessionId` (client-generated `crypto.randomUUID()` from `loadLesson()`) is already the value `QuizOverlay.tsx`/`TeachBackModal.tsx` send as `session_id` to the assessment API — confirmed this is the correct value to pass to `useLessonSocket(sessionId)` too, no new session concept needed.

**🔴 Escalation raised to Dev 4, 2026-07-06 — corrects an earlier wrong assumption in this same investigation.** My first pass (see the now-superseded note below) assumed the receive side was "not blocked, just pending a live-Redis integration test," based on `docs/master-tracker.md`'s characterization of Dev 4's FSM work. Before writing the story, I traced the actual code path per BMAD's "read every file you're integrating with, don't trust the doc" discipline, and that assumption was wrong:

```
websocket.py: _handle_tutor_event()  →  service.py: advance_tutor_state()  →  graph.py: dispatch_event()
```

None of these three ever call `manager.send()`. Confirmed by reading all three files directly — the FSM's internal state mutates (Redis `tutor_state:{session_id}` gets updated) but the connected client is never told. The **only** live emitter of `state_change` anywhere in the codebase is the reconnect-sync path in `websocket.py`'s `ConnectionManager.connect()`, and it always sends `from_state == to_state` (a sync, not a transition) — exactly as `docs/ws-message-contract.md` (Dev 4's own doc, "pending Dev 2 sign-off") already states: *"Real `from != to` transition frames are not yet pushed over WS by any reviewed path."* This is not a testing gap — the broadcast call doesn't exist in the code.

**Message sent to Dev 4** (verbatim, for the record):

> Subject: Need `state_change` broadcast on real FSM transitions (not just reconnect-sync) — blocking S2-06
>
> Working on segment-end detection → CHECKING_IN state for the player (S2-06). Traced the WS code path: when a client sends a flow event like `segment_complete`, the FSM transitions internally but nothing broadcasts the new state back to the client (`websocket.py:_handle_tutor_event` → `service.py:advance_tutor_state` → `graph.py:dispatch_event` — none call `manager.send()`). The only place `state_change` is ever sent is the reconnect-sync path, and that's always `from_state == to_state`. Matches what `docs/ws-message-contract.md` already documents.
>
> I can wire the frontend to send `segment_complete` on segment end today — no blocker there. But there's no way for the player to learn the backend actually moved TEACHING → CHECKING_IN, since it's never pushed.
>
> **Ask:** add a broadcast inside `dispatch_event()` (or wherever the FSM's state actually mutates) that fires whenever `from_state != to_state`:
> ```python
> await manager.send(session_id, {
>     "type": "state_change",
>     "payload": {"session_id": session_id, "from_state": from_state, "to_state": to_state},
> })
> ```
> This is already a frozen `ws.ts` shape — no contract change needed on your end beyond emitting it on real transitions too.
>
> Before I scope my side, I'd want to know: (1) does this fire for every transition or just ones you've integration-tested so far, (2) rough latency from `segment_complete` received → `state_change` sent, since I need to decide whether the quiz can safely wait on it or stay client-triggered with this as a sync signal only, (3) does the mocked-Redis unit-test path exercise the broadcast too, or is that separate from the live-Redis path.

**Split scope while waiting:**
- **Send side — NOT blocked, can start any time:** mount `useLessonSocket(sessionId)` live in the player, call `sendControl({type: 'segment_complete'})` from `AudioTimeline.tsx`'s existing segment-boundary check. This also has real value independent of CHECKING_IN — it increments `session:{session_id}:segment_index` server-side (`service.py:advance_tutor_state`), which feeds `_segment_intervention_messages`' segment lookup for Sprint 3's intervention system.
- **Receive side — blocked on Dev 4's reply.** Building a CHECKING_IN UI with nothing live to trigger it would be building against a signal that can't arrive yet.

**Holding per user instruction (2026-07-06):** BMAD story creation for S2-06 paused here, pending Dev 4's response. Branch `sprint2/s2-6-segment-checkin` exists but has no commits yet.

<details>
<summary>Superseded 2026-07-06 note (kept for the record — this was the assumption before verifying the actual backend code, corrected within the same investigation)</summary>

~~**Blocked assessment: NOT blocked.** Everything Dev 2 needs on the frontend side already exists and is tested (the WS client, the control-message types, the state-dispatch plumbing). Dev 4's backend tutor FSM logic for this exact transition is code-merged and unit-tested against a mocked Redis (per `docs/dev4-websocket-tutor-tracker.md`), pending only a live-Redis integration test — not a hard blocker, the same posture S2-04 was successfully built against for its own backend dependency. The only open questions are product/architecture decisions, not cross-team waiting.~~ **Corrected above: the backend never broadcasts a real transition at all, regardless of Redis being live or mocked. This is a missing feature, not a pending test.**

</details>

**Recommendation:** given the real architectural decision buried in this "line item" and the fact that nothing here has ever been scoped into acceptance criteria, run this as a full BMAD story (`bmad-create-story` → `bmad-dev-story` → 5-agent review) rather than a quick patch — same rigor as S2-01 through S2-05, once Dev 4 unblocks the receive side (or a decision is made to ship the send-side half alone in the meantime).

</details>

---

### S2-07 — Learner Mode Selection Screen — ✅ 2026-07-14
**Priority:** High  
**Status:** ✅ DONE <!-- completed: 2026-07-14 --> — implemented via BMAD story `docs/stories/2-7-mode-selection-screen.md` on branch `sprint2/s2-7-mode-selection` (branched from `sprint1/s1-8-upload-real-api`, not main — see branch note below), feeds into feature master `feature-learner-mode`. 5-agent adversarial review complete (Blind Hunter, Edge Case Hunter, Acceptance Auditor) — 0 decision-needed, 3 patch, 2 defer, 2 dismissed. All 3 patches applied (see below); the 2 deferred items are tracked in `_bmad-output/implementation-artifacts/deferred-work.md`.  
**Files created:** `src/types/learnerMode.ts`, `src/components/dashboard/upload/ModeSelection.tsx`, `src/__tests__/components/dashboard/upload/ModeSelection.test.tsx`  
**Files modified:** `src/components/dashboard/upload/UploadFlow.tsx` (new `'selecting-mode'` state, `handleTierSelect`/`handleCancelModeSelection`), `src/__tests__/components/dashboard/upload/UploadFlow.test.tsx` (existing tests updated to select a tier before the upload call fires — an intentional, in-scope behavior change, not a regression)

**Branch note:** this task's branch — and the 3 remaining Learner Mode tasks (S2-08, S2-09, S2-10) — are cut from `sprint1/s1-8-upload-real-api` rather than `main`, since that branch carries real unmerged auth/upload backend fixes this feature builds directly on top of (`UploadFlow.tsx`). Task branches stay local; each merges into the dedicated feature master `feature-learner-mode` (not `sprint2-master`), which is what gets pushed and PR'd.

New feature: **Learner Mode** — student picks a tier before generation begins. The mode-selection screen now appears right after a file is dropped/selected and size-validated, **before** the upload POST fires (not after upload completes — confirmed with the user; this lines up with S2-09 needing the tier known before that POST is made). 3 cards:
- **Deep** (full-depth lesson, no time constraint)
- **Balanced** (time-boxed depth)
- **Refresher** (condensed review only)

**Scope boundary (per story):** this task is the selection screen only. Tier disclaimers (S2-08), sending the tier to the backend (S2-09 — no field exists in `POST /api/content/lessons` yet, needs Dev 1 sign-off), and the tier badge on player/report (S2-10) are separate, not-yet-started follow-on tasks. `selectedTier` is captured in `UploadFlow.tsx` component state only (surfaced via a non-visible `data-selected-tier` attribute for S2-10 to pick up later) — not yet persisted or sent anywhere.

**Acceptance criteria:**
- [x] Screen renders after a file is selected/size-validated, before the upload POST fires
- [x] 3 selectable cards, real `<button>`s: Deep / Balanced / Refresher, each with a one-line description
- [x] Clicking a card is both the selection and the confirmation — captures the tier and immediately proceeds to upload (no separate "Continue" button)
- [x] "Choose a different file" returns to the idle drop zone without ever calling the upload API
- [x] Oversized-file rejection path unaffected (still short-circuits to the error state before reaching mode-selection)
- [x] No regression to Story 1-8's upload/polling behavior once a tier is picked — byte-for-byte the same from that point on

15 new/updated tests from initial implementation (4 in `ModeSelection.test.tsx`, 11 in `UploadFlow.test.tsx`) + 5 more from the review-patch pass (2 in `ModeSelection.test.tsx`, 3 in `UploadFlow.test.tsx`) = 20 total. Full `apps/web` suite: 337/337 passing. `tsc --noEmit` clean. `eslint`: 0 errors, 37 warnings (all pre-existing, 0 new).

**Review patches applied:** `handleCancelModeSelection` now clears `file`/`selectedTier`/the file input value (so re-picking the same file after cancelling works); tier cards now have `focus-visible` ring styling matching `Button`'s pattern; `ModeSelection` moves focus to the first card on mount so keyboard users land on the screen without re-tabbing.

**Deferred (tracked in `_bmad-output/implementation-artifacts/deferred-work.md`):** no drag-and-drop guard on the new screen (pre-existing gap, needs a broader fix across all non-idle screens); tier choice has no functional effect on generation yet (by design — S2-09's job — but current copy oversells it).

---

### S2-08 — Tier Disclaimers — ✅ 2026-07-14
**Priority:** Medium  
**Status:** ✅ DONE <!-- completed: 2026-07-14 --> — implemented via BMAD story `docs/stories/2-8-tier-disclaimers.md` on branch `sprint2/s2-8-tier-disclaimers` (branched from `feature-learner-mode`, which already has S2-07 merged in), feeds into feature master `feature-learner-mode`  
**Files modified:** `src/types/learnerMode.ts` (new `disclaimer?: string` field on `LearnerTierOption` + copy for `balanced`/`refresher`), `src/components/dashboard/upload/ModeSelection.tsx` (conditional inline disclaimer block, `AlertTriangle` icon + amber tint), `src/__tests__/components/dashboard/upload/ModeSelection.test.tsx` (4 new tests)

Per-tier inline warning-style disclaimer shown on the mode selection screen:
- **Deep:** no disclaimer
- **Balanced:** time-deficit warning ("Content may be trimmed or condensed to fit your available time.")
- **Refresher:** refresher-only warning ("Assumes you already have prior mastery — not a full first-pass lesson.")

**Acceptance criteria:**
- [x] Deep card shows no disclaimer
- [x] Balanced card shows a time-deficit inline warning
- [x] Refresher card shows a refresher-only inline warning
- [x] Disclaimers styled consistently as an inline warning (icon + tinted background, not a modal/toast) — no reusable `Alert` component existed in the codebase, so this is kept local to `ModeSelection.tsx` per the story's explicit scope
- [x] No regression to S2-07's card click/focus-visible/mount-autofocus behavior; `UploadFlow.tsx` and its tests untouched (confirmed via `git diff --stat`)

11 tests total in `ModeSelection.test.tsx` (6 unmodified from S2-07 + 5 new). Full `apps/web` suite: 342/342 passing. `tsc --noEmit` clean. `eslint` clean, 0 new warnings.

**5-agent adversarial review (2026-07-14) — 2 patches applied, 3 dismissed as noise:** disclaimer text now has a screen-reader-only "Warning:" prefix so assistive tech can distinguish it from the description (button accessible names were a flat concatenation before); the `option.disclaimer &&` render guard is now an explicit `option.disclaimer && option.disclaimer.trim().length > 0 ? (...) : null`, codifying the "must be entirely absent, not empty string" invariant in code rather than only in a comment. Dismissed: a claim that `AlertTriangle` needed explicit `aria-hidden` (verified false by reading `lucide-react`'s installed source — it already sets this automatically), a false "new dependency" concern (`lucide-react` is already used elsewhere in this codebase), and a "brittle exact-count test" critique (the `toHaveLength(2)` test is intentionally behavioral).

---

### S2-09 — Wire Selected Tier into Lesson Creation — ✓ 2026-07-21 (implemented, pending 5-agent code review) — ⚠️ SUPERSEDED 2026-08-04 by Story W3, see amendment below
**Priority:** Medium  
**Status:** ✅ DONE — implementation + tests complete; code review not yet run  
**Files modified:** `apps/web/src/types/learnerMode.ts` (new `LEARNER_TIER_TO_BACKEND` mapping), `apps/web/src/services/upload.service.ts` (`uploadLesson` gains `tier?` param), `apps/web/src/components/dashboard/upload/UploadFlow.tsx` (call site + visible tier label), plus both files' tests

Unblocked 2026-07-21 once Dev 1's Sprint 2 Phase B backend merge (PR #74) landed `tier: Form(...)` on `POST /lessons` (multipart, default `T2`, 422 on invalid — confirmed by reading `apps/api/app/modules/content/router.py`/`apps/api/app/schemas/lesson.py` directly, not assumed). Mapping confirmed by matching backend semantics (`docs/stories/2-lm3-lm4-lm5-tier-aware-generation.md`) to the existing frontend tier descriptions: `deep→T1`, `balanced→T2`, `refresher→T3`. Full story: `docs/stories/2-9-wire-tier-into-lesson-creation.md`. Branch `sprint2/s2-09-wire-tier` off `feature-learner-mode` (task branch kept local, merged into the feature master per standing convention).

**Acceptance criteria:**
- [x] Selected tier included in the lesson-creation request body (`FormData.append('tier', ...)`, mapped T1/T2/T3)
- [x] Chosen tier displayed on the generating/progress screen (`data-testid="selected-tier-label"`)
- [x] No regression to the existing upload flow — tier omitted entirely (not defaulted client-side) when unset, relying on the backend's own `T2` default

**Note:** `GET /lessons/{id}` still doesn't echo `tier` back — this story only wires the send side (upload-time). S2-10 (below) is now unblocked to re-scope, but will still need its own decision on how the player/session report actually gets a tier value (no read-back path exists yet).

> **⚠️ AMENDMENT (2026-08-04) — the AC above is stale; it describes a request that now 422s.**
> Everything above this line is preserved verbatim as the record of what was actually built on
> 2026-07-21. It was correct then. It is not correct now, and it was not made wrong by a defect in
> S2-09 — it was invalidated by a later architecture change.
>
> **What changed.** Book-scale **Phase 6** made `POST /api/content/lessons` ingest a *book*, not a
> lesson. A book has no tier, so that endpoint now rejects the mere presence of a `tier` field with
> a **422** — unconditionally, before any file handling. S2-09's acceptance criterion
> (`FormData.append('tier', ...)`) therefore describes a request that fails 100 % of the time. The
> tier itself did not change meaning: `LEARNER_TIER_TO_BACKEND` (`deep→T1 · balanced→T2 ·
> refresher→T3`) is unchanged and still the only mapping, `lessons.tier` still drives generation via
> Dev 1's S2-LM1–LM5, and S2-10's badge still reads `lesson.metadata.tier`. Phase 6 changed **where
> the student supplies the tier**, not what it does.
>
> **Where it lives now.** Story **W3** (`docs/stories/W3-generate-from-chapter.md`, branch
> `book-scale/track-w`) restores this capability on the chapter card: the tier is chosen per
> *chapter* at generation time and sent as a **JSON** body `{tier}` to
> `POST /api/content/books/{book_id}/chapters/{chapter_id}/lessons`. `ModeSelection.tsx` and
> `types/learnerMode.ts` are reused unchanged — W1 deliberately preserved them when it stripped the
> upload flow's call sites, precisely so this restoration would not need a rebuild. S2-09's one
> assertion worth keeping (*the selected tier reaches the request body, mapped correctly*) is
> re-pointed at the new endpoint and body shape in
> `apps/web/src/__tests__/services/books.generate.service.test.ts` and
> `apps/web/src/__tests__/components/dashboard/books/ChapterGenerateControl.test.tsx`.
>
> **Review debt, recorded rather than quietly inherited.** S2-09's own status line says *"code review
> not yet run"* — its 5-agent adversarial review (CLAUDE.md § BMAD Code Review Gate) was never
> performed. That debt did not disappear when the code path moved: this tier-wiring path still owes
> one, and W3's review does not retroactively discharge S2-09's.
>
> This entry is **amended, not deleted** — same convention the defect register uses: the original
> record of what was built stays, and the correction sits beside it with a date.

---

### S2-10 — Tier Badge on Player + Session Report
**Priority:** Low  
**Status:** 🔲 NOT STARTED — re-investigated 2026-07-21 now that S2-09 has landed. **Splits into two genuinely different states — see below.** <!-- added 2026-07-14 -->  
**Files to modify:** `src/components/player/Player.tsx` (unblocked), `src/components/reports/SessionReport.tsx` (still blocked — cross-team)

Small badge showing the lesson's tier and duration, e.g. `Deep · 45 min`.

**Originally investigated 2026-07-18** (branch `sprint2/s2-10-tier-badge`, no commits, story creation halted): confirmed neither target component had any data path for a tier value. **Decision (user, 2026-07-18): defer S2-10 until S2-09 lands.**

**Re-investigated 2026-07-21, after S2-09:**
- **Player side — genuinely unblocked, no cross-team dependency.** `packages/shared/types/lesson.ts`'s `LessonMetadata` now has a required `tier: LessonTier` field (Dev1's PR #74, self-certified §16-compatible — see `docs/reports/s16-lessonpackage-compat.md`), and `package_builder_node` explicitly bakes the `lessons.tier` column value into it. `Player.tsx` already receives the full `LessonPackage` as a prop — `lesson.metadata.tier` is real, present data today. This half needs no backend work at all.
- **Session report side — still blocked, and it's a different blocker than before.** `apps/web/src/types/assessment.ts`'s `SessionReport` interface (the frozen-ish contract from story 3-19, owned by **Dev 3**'s assessment module) has no `tier` field — confirmed by reading `apps/api/app/modules/assessment/router.py`'s response model directly (also no `tier`). S2-09 never touched this; it only wired the upload-time send (`lessons.tier` column), not anything Dev 3's assessment/session-report endpoint reads. Adding `tier` to `SessionReport` is a small, additive, non-breaking change in spirit — but it's Dev 3's contract to change, per team-ownership rules (CLAUDE.md §"modules communicate only through service layer" / per-dev file ownership) — not something to add unilaterally from the frontend side.

**Decision needed:** ship the player badge now (fully unblocked) and split the session-report badge into its own follow-up pending a small ask to Dev 3, or hold both halves together as one task until Dev 3's field lands. Not yet decided — ask before implementing either half.

**Acceptance criteria (unchanged, split per the above once a path is chosen):**
- [ ] Badge visible in the lesson player (header/chrome area)
- [ ] Same badge shown on the session report (S2-04)
- [ ] Badge format: `{Tier label} · {duration} min`

---

### S2-11 — Fix Quiz Feedback Field-Name Mismatch — ✅ 2026-07-23
**Status:** ✅ DONE — `docs/stories/2-11-quiz-feedback-field-fix.md`, branch `sprint2/s2-11-variable-quiz-count`, merged to `sprint2-master`, and to `main` via PR #114 (2026-07-29)
**Files:** `apps/web/src/lib/assessment.ts`, `apps/web/src/components/player/QuizOverlay.tsx`, `apps/web/src/types/assessment.ts`

Every quiz result's feedback line had been rendering blank/`undefined` in every environment — `QuizFeedbackItem`/`QuizOverlay.tsx` read `correct`/`message`, but the real backend (`apps/api/app/modules/assessment/service.py::grade_quiz`) sends `is_correct`/`explanation`. Found while scoping Dev 3's Story 3-28 (tier-aware quiz count), unrelated to it. Fixed the real shape at both the live call site and the parallel, unused-at-runtime `QuizResult` type in `types/assessment.ts` (which had the same wrong shape, backed by its own passing-but-wrong test) — now reuses `lib/assessment.ts`'s type instead of a third drifting copy. 5-agent review, 1 patch applied.

---

### S2-12 — Re-Assessment Prompt After 10 Sessions — ✅ 2026-07-23
**Status:** ✅ DONE — `docs/stories/2-12-reassessment-prompt.md`, branch `sprint2/s2-12-reassessment-prompt`, merged to `sprint2-master`, and to `main` via PR #114 (2026-07-29)
**Files:** `apps/web/src/components/onboarding/OnboardingFlow.tsx`, `apps/web/src/components/dashboard/sections/ReassessmentPrompt.tsx` (new)

Frontend counterpart to Dev 3's Story 3-31 (`reassessment_due` on `GET /api/assessment/user/dna`). `OnboardingFlow.tsx`'s mount check previously redirected any already-onboarded user straight to `/dashboard`, unconditionally, never checking `reassessment_due` — a "Take Assessment" CTA would have been a dead end. Fixed: mount effect now proceeds into the flow when due. New `ReassessmentPrompt.tsx` is a self-contained dismissible dashboard banner, dismissal persisted to `localStorage` keyed on `session_count` (so dismissing at session 10 doesn't suppress the session-20 prompt). 3-agent review.

---

### S2-13 — Assessment Library Test Gaps + RubricScores Type Drift — ✅ 2026-07-27
**Status:** ✅ DONE — `docs/stories/2-13-assessment-test-fixes.md`, merged to `sprint2-master`, and to `main` via PR #114 (2026-07-29)
**Files:** `apps/web/src/lib/assessment.ts`, its test file, plus a stale-path correction across `OnboardingFlow.tsx`/`questions.ts` tests

Surfaced during the first live end-to-end test session against the real backend + real Supabase. Fixed a real `RubricScores` type drift and closed test coverage gaps in the assessment library that had gone unnoticed under mocks. 3-agent review.

---

### S2-14 — Wire Dashboard and Library to Real GET /lessons Endpoint — ✅ 2026-07-27
**Status:** ✅ DONE — `docs/stories/2-14-real-dashboard-library.md`, merged to `sprint2-master`, and to `main` via PR #114 (2026-07-29)
**Files:** `apps/web/src/services/dashboard.service.ts`, `apps/web/src/services/library.service.ts`, `apps/web/src/components/dashboard/sections/*`, `apps/web/src/components/library/LibraryView.tsx`

Confirmed via `docs/master-tracker.md` that `GET /api/content/lessons` was real, tested, and ready on Dev 1's side — but dashboard/library were still calling mocks. Wired both services to the real, paginated endpoint. Review round added: wider lookup window (`limit: 20`), dedup between `continueLearning` and `recentLessons`, isolated the mock learning-pulse call behind its own try/catch so its failure can't take down the rest of the dashboard, and an `all` field on `LibraryData` for robust "All" tab rendering. Dropped fabricated fields (`chapterTitle`, `durationSeconds`, etc.) per this project's never-fabricate-data convention. 3-agent review.

---

### S2-15 — Fix Dashboard/Library 401 by Moving Real Data Fetching Client-Side — ✅ 2026-07-27
**Status:** ✅ DONE — `docs/stories/2-15-fix-dashboard-library-auth.md`, merged to `sprint2-master`, and to `main` via PR #114 (2026-07-29)
**Files:** `apps/web/src/hooks/useDashboard.ts` (new), `apps/web/src/hooks/useLibrary.ts` (new), `apps/web/src/app/(dashboard)/dashboard/page.tsx`, `apps/web/src/app/(dashboard)/library/page.tsx`

The very first live test of S2-14's wiring hit a 401: both pages were Server Components, but `api.ts`'s auth interceptor only attaches a Bearer token client-side (`typeof window !== 'undefined'`) — a Server Component running in Node.js has no `window`, so every real API call went out with no auth header at all. Fixed by converting both pages to Client Components using two new SWR-based hooks, matching the already-established `useLesson`/`useSessionReport` pattern (real, authenticated data fetching in this codebase is always client-side). Review round added a loading state (was flashing empty-lesson sections) and per-user SWR cache key scoping (`` `dashboard:${user.id}` ``) to prevent cross-user data leakage in a shared browser tab. Merged before review (user was actively blocked live-testing), reviewed immediately after — 2 findings fixed.

---

### S2-26 — Audio Buffering + Playback-Error Retry States — ✅ 2026-07-29
**Status:** ✅ DONE — `docs/stories/2-26-audio-buffer-error-retry.md`, merged to `main` via PR #95
**Files:** `apps/web/src/stores/player.machine.ts`, `apps/web/src/components/player/AudioTimeline.tsx`, `apps/web/src/components/player/Player.tsx`

Re-implemented, against current `main`, the still-valuable half of a 3-week-stale PR (#71) that had diverged too far to merge cleanly (its `PlayerLoader.tsx` approach predated the real backend integration and would have regressed the current, better `status`-based loading/error handling). Adds `isBuffering`/`audioError`/`audioRetryCount` state, `onWaiting`/`onPlaying`/`onCanPlay`/`onError` wiring on the `<audio>` element, a non-blocking buffering indicator, and a playback-error screen with a Retry button. 3-agent review caught and fixed: `retryAudio()` not actually resuming playback (missing effect dependency — clearing the error but never calling `.play()` again on the remounted element), and the error overlay blocking `QUIZ`/`TEACH_BACK`/`ENDED` when a stale error survived into those states. Also fixed in the same PR: an unrelated pre-existing `tsc` break on `main` (Story 2-25's `LessonMetadata.tier` optionality change had broken S2-10's `TIER_LABELS` lookup).

---

### S2-33 — Virtual Playback Clock + Retry Re-Fetch on Media Error — ✅ 2026-07-29
**Status:** ✅ DONE — `docs/stories/2-33-virtual-playback-clock.md`, merged to `main` via PR #106
**Files:** `apps/web/src/components/player/AudioTimeline.tsx`, `apps/web/src/components/player/Player.tsx`, `apps/web/src/components/player/PlayerLoader.tsx`, `apps/web/src/hooks/useLesson.ts`, `apps/web/src/stores/player.machine.ts`

The frontend half needed to actually close the TTS-fallback bug Dev 2 reported to Dev 1 — see the cross-team notes above for the full bug-report/fix history with Dev 1. `AudioTimeline.tsx` now branches three ways (real audio / recovered-script-but-no-audio / neither); the new middle case runs a wall-clock-accurate, `playbackRate`-aware virtual clock driving the same `processTimeUpdate` boundary logic real audio would, closing the "quiz fires at 0:00" symptom for good. `Player.tsx`'s Retry button now re-fetches the lesson (fresh signed media URL) via a new `useLesson` `refetch` + `refreshLessonMedia` store action, instead of remounting the same expired URL. 3-agent review caught 2 real **High** severity bugs pre-merge (see cross-team note above for detail) plus 4 Medium/Low fixes (seek-vs-tick race, in-flight retry-button guard, drift correction, defensive duration reset) — all with regression tests. Full suite 53 files / 521 tests passing throughout.

---

### S2-34 — Browser SpeechSynthesis Fallback for Virtual Playback Clock — ✅ 2026-07-29
**Status:** ✅ DONE — `docs/stories/2-34-speech-synthesis-fallback.md`, branch `sprint2/s2-34-speech-synthesis-fallback`, merged to `sprint2-master` then to `main` via PR #114 (2026-07-29)
**Files:** `apps/web/src/components/player/AudioTimeline.tsx`, `apps/web/src/__tests__/components/player/AudioTimeline.component.test.tsx`

Implements the last tier of CLAUDE.md's TTS fallback chain (Sarvam Bulbul v2 → Azure TTS → **Browser Speech**), requested directly by the user from Dev 1's 2026-07-29 handoff (item 4c) despite its explicit non-blocking label there. Layers the native `SpeechSynthesis` API onto S2-33's virtual clock's `!hasAudio && hasScript` branch — the clock remains the sole timing authority; speech is purely supplementary audio and never drives `processTimeUpdate`/segment advancement. Mirrors `<audio>` play/pause semantics: `pause()`/`resume()` on status transitions, `cancel()` on segment change or leaving virtual-clock mode. 3-agent review (Blind Hunter, Edge Case Hunter, Acceptance Auditor) surfaced 10 findings; user resolved 3 decision-needed items (2 accepted as documented limitations — seek doesn't resync narration, long scripts risk browser TTS truncation — logged in `docs/stories/deferred-work.md`; 1 applied — `ENDED` hard-cancels instead of pausing) and all 7 patch findings were applied: deferred `speak()` behind a `setTimeout(0)` after `cancel()` (same-tick Chrome race), added a swallowing `onerror` handler, guarded on `SpeechSynthesisUtterance` existence, made segment-change `cancel()` unconditional on status (real AC-6 gap), switched the effect's deps to `segment?.segment_id` per the spec's literal wording, and reset the spoken-segment ref in the unmount-cleanup effect (fixes a React StrictMode dev double-mount edge case). Full suite 54 files / 560 tests passing, `tsc --noEmit` clean, `eslint` clean.

---

## 12. Sprint 3 — MediaPipe + CES + Tutor UI
**Period:** Weeks 6–7 | **Status:** 🟡 IN PROGRESS (3/8 done — S3-01, S3-03, S3-04)  
**Dependency:** Dev 4 WebSocket server delivering `tutor_intervene` and `ces_update` messages — this now works for S3-03/S3-04 (both built and shipped against the frozen `ws.ts` contract; live end-to-end delivery depends on Dev 4's tutor FSM, tracked as D30 — **CLOSED 2026-08-04**)

---

### S3-01 — Attention Consent Modal — ✓ DONE 2026-08-06
**Priority:** P0 — must exist before camera access  
**Status:** ✅ DONE 2026-08-06 — Story `2-42-attention-consent-modal.md`, branch `sprint3/s3-01-attention-consent-modal`, 3-agent review passed (3 decision-needed resolved, 12 patch findings applied). Merged into `sprint3-master`.  
**Files:** `src/components/player/AttentionConsentModal.tsx`, `src/hooks/useAttentionConsent.ts`, `src/lib/assessment.ts` (added `recordConsent()`)

Shown once per account (Supabase-consent-status + a localStorage dismissal key gate *visibility only*; the security decision always re-reads Supabase, never the local key — AC-4). Explains: webcam used for attention monitoring, only 5 aggregate numbers sent (never video), student can decline. Suppressed during `QUIZ`/`TEACH_BACK` (same `audioError`-exclusion pattern already in `Player.tsx`) so a slow consent read can never block those screens.

**Corrected from this doc's original spec:** the pseudo-code below assumed a `PATCH /api/users/consent` endpoint that turned out to never exist. What actually shipped, once Dev 3's real **Story 3-32** endpoint landed on `main` mid-review:

```typescript
// On lesson start (status !== 'QUIZ'/'TEACH_BACK'):
if (consentStatus !== 'accepted' && !dismissed) {
  show ConsentModal
  // if accepted: POST /api/assessment/consent { consent_type: 'attention_tracking', policy_version }
  //              → DB trigger syncs users.attention_consent = true → future AttentionMonitor may initialize
  // if declined: no API call (schema has no "declined" value) — local dismissal key only, lesson plays normally
}
```

**CRITICAL SECURITY CONSTRAINT — still holds:** `AttentionMonitor` (S3-02) must never be initialized without a fresh Supabase read confirming `users.attention_consent === true`. This story's hook is exactly that read path; it must never be replaced by a `localStorage` check.

**Acceptance criteria:**
- [x] Consent modal shown exactly once (on first lesson, per-account, via localStorage dismissal key)
- [x] If declined: no camera permission requested, AttentionMonitor never initialized (nothing to gate yet — S3-02 not built; guarded structurally by a source-level test that no camera/MediaPipe API is referenced anywhere in this story's code)
- [x] Consent state persisted server-side — via `public.user_consents` (Story 3-32), not a bare boolean PATCH as originally scoped
- [x] ~~PATCH call fires~~ `POST /api/assessment/consent` fires to record consent on acceptance
- [x] Declining consent does not degrade lesson quality in any way

**Known gaps, deliberately deferred (see story's Review Findings + `docs/deferred-work.md` DEFER-003–005):** decline leaves no server-side audit trail (schema has no "declined" value — accepted as-is); no ARIA modal semantics (shared gap with other modals, not unique to this one); the hook's Supabase mock shape isn't premise-tested against the real client (shared gap with `proxy.ts`'s own tests).

---

### S3-02 — AttentionMonitor Component (MediaPipe) — ✓ DONE 2026-08-10
**Priority:** P0  
**Status:** ✅ DONE 2026-08-10 — Story `2-44-attention-monitor.md`, branch `sprint3/s3-02-attention-monitor` (cut from `sprint3-master`, not `main` — hard dependency on Story 2-42's consent hook). 8-layer adversarial review passed (1 decision resolved, 21 patches applied — most consequential: AC-1's `tutorState` gate was never actually implemented, and a head-pose yaw/pitch axis extraction bug, both confirmed by multiple independent reviewers and fixed). Full `apps/web` suite: 906 tests passing.  
**Files created:** `src/components/player/AttentionMonitor.tsx`, `src/hooks/useAttentionMonitor.ts`, `src/lib/attention/signalMath.ts`

```
MediaPipe Face Landmarker WASM → 30fps local processing (never sent)
  → every 5 seconds: aggregate 150 frames into 5 signals:
      gaze_score: number        (0–1)
      head_pose_score: number   (0–1)
      blink_rate: number        (blinks/minute)
      expression_label: string  ('neutral'|'confused'|'surprised')
      behavioral_score: number  (0–1 from click/scroll/mouse events)
  → send via LessonSocket as AttentionSignalMessage:
      {
        type: 'attention_signal',
        payload: {
          session_id,
          quiz_accuracy: null,      ← filled by QuizModal on submit
          teachback_score: null,    ← filled by TeachBackModal on submit
          behavioral_score,
          head_pose_score,
          blink_rate
        }
      }
```

**Library:** `@mediapipe/face_landmarker` (WASM bundle). Must be loaded via `dynamic(..., { ssr: false })`.  
**CRITICAL:** Raw video frames NEVER leave the browser. Only the 5 aggregated numbers are sent over WebSocket. Any code path that sends video bytes to the server is a critical security bug.

**Acceptance criteria:**
- [ ] MediaPipe initializes within 3 seconds of lesson start
- [ ] Camera permission requested only after consent
- [ ] 5-signal payload sent every 5 seconds via LessonSocket
- [ ] `raw_video` or any video buffer is never in any network request payload
- [ ] If MediaPipe fails to load (WASM bundle error), lesson continues without attention monitoring
- [ ] Component cleanup: camera stream released on unmount (no lingering camera indicator)

---

### S3-03 — TutorInterventionCard Component — ✓ DONE 2026-08-03
**Priority:** P0  
**Status:** ✅ DONE 2026-08-03 — Story `2-40-tutor-intervention-card.md`, branch `sprint3/s3-03-tutor-intervention-card`, 3-agent review passed (9 patches applied). Built against mock WS events per the frozen `ws.ts` contract. **Update 2026-08-06:** all three cross-team blockers on real end-to-end delivery are now closed — D30 (Dev 4's tutor FSM tests) closed 2026-08-03, D18 (session creation) closed 2026-08-04, D29 (DPDP consent) closed 2026-08-05. Nothing known is blocking a live test of this component anymore.  
**Files to create:** `src/components/player/TutorInterventionCard.tsx`

Receives `TutorInterveneMessage` from `LessonSocket`. Slides in from the right side of the player. Three types:

| Type | Trigger | Visual cue |
|---|---|---|
| `distraction` | Head pose low | Warm amber card — gentle re-engagement |
| `confusion` | CES drop | Cool blue card — "Let me re-explain..." |
| `fatigue` | Session > 40min + blink elevated | Soft card — suggest break |

```typescript
// In Player.tsx, subscribe to LessonSocket:
socket.on('tutor_intervene', (msg: TutorInterveneMessage) => {
  showInterventionCard(msg.payload.type, msg.payload.message);
});
```

Audio does NOT pause for interventions — card is non-blocking. User dismisses manually or it auto-dismisses after 30s.

**Acceptance criteria:**
- [x] Card slides in from right with 200ms ease animation
- [x] Dismisses on button click or after 30s timeout
- [x] Audio continues playing during intervention
- [x] Three visual variants (distraction / confusion / fatigue)
- [x] NEVER shows while `store.status === 'TEACH_BACK'` — guard at render level

---

### S3-04 — CES Indicator — ✓ DONE 2026-08-03
**Priority:** P2  
**Status:** ✅ DONE 2026-08-03 — Story `2-41-ces-indicator.md`, branch `sprint3/s3-04-ces-indicator`, 3-agent review passed. Shipped in the same review pass as S3-03; this entry was never updated at the time — corrected 2026-08-06.  
**Files:** `src/components/player/CESIndicator.tsx`

Subtle, non-intrusive. Shows engagement level as a colored dot or subtle progress arc in the player corner. Updates every 5 seconds from `ces_update` WebSocket message.

Shows as qualitative label: `ces < 0.4 → "Low"`, `0.4–0.7 → "Engaged"`, `> 0.7 → "Focused"`. Never shows the raw float to the student.

**Acceptance criteria:**
- [x] Updates on `ces_update` message receipt
- [x] Shows qualitative label, not raw CES float
- [x] Does not distract from lesson content (max 40px dimension)
- [x] Hidden when `store.status !== 'PLAYING'`

---

### S3-05 — Session Report: Attention Timeline Chart
**Priority:** P2  
**Status:** 🔲 NOT STARTED — **unblocked 2026-08-10**, S3-02 shipped and is merged into `sprint3-master`. Real signals only flow once a session actually reaches `TEACHING` with consent granted; live end-to-end signal data hasn't been verified against a real browser/camera yet (blocked separately on the OpenAI account credit issue preventing a fresh lesson from being generated to test against — see chat history 2026-08-10).  
**Files to create:** `src/components/reports/AttentionChart.tsx`

Area chart of CES over session time. X-axis: minutes. Y-axis: 0–1 (but shown as Low/Med/High labels). Marks interventions as vertical lines.

Use a lightweight chart library (recharts or a canvas-based solution) — no D3 from scratch. Must be responsive.

**Acceptance criteria:**
- [ ] Chart renders with data from `/api/session/{id}/report`
- [ ] Intervention timestamps shown as vertical markers
- [ ] Y-axis uses qualitative labels, not raw CES values
- [ ] Responsive (mobile view collapses to a simpler view)

---

### S3-06 — Reports Page
**Priority:** P1  
**Status:** 🔲 NOT STARTED — **unblocked 2026-08-10**, same as S3-05 above.  
**Files:** `src/app/reports/[sessionId]/page.tsx`, `src/components/reports/SessionReport.tsx` (route corrected 2026-07-04 during S2-04 — expand v1 from Sprint 2, not `src/app/reports/page.tsx`)

Add: Attention timeline chart (once MediaPipe/attention data exists), teach-back summary detail. Note: "quiz accuracy by segment" is not buildable as scoped — the real backend's `GET /api/assessment/session/{id}/report` only returns one session-level `quiz_score`, no per-segment breakdown (see S2-04 Dev Notes) — would need a new/extended Dev 3 endpoint first.

---

### S3-07 — Notifications UI — ✓ DONE 2026-08-06/07
**Priority:** P2  
**Status:** ✅ DONE — **correcting a stale entry.** This was genuinely backend-blocked when the note above was written (2026-08-06), but Dev 4 shipped `PATCH /api/auth/notifications` (Story 4-23) the same day, and it was wired up here as Story `2-43-notifications-ui.md`, branch `sprint3/s3-07-notifications-ui`, 4-layer adversarial review passed (9 patches applied), merged into `sprint3-master`. This entry was simply never updated afterward. See `docs/DEFECT-REGISTER.md` D60 for the full four-piece cross-team history (Dev 3/Dev 1/Dev 4/Dev 2).  
**Files:** `src/hooks/useNotificationPreferences.ts` (new), `src/services/settings.service.ts`, `src/components/settings/tabs/NotificationsTab.tsx` (rewritten, 4 toggles incl. new Session Report), removed obsolete mock plumbing.

Wired to the real `PATCH /api/auth/notifications` (not `/api/users/notifications` as originally scoped — corrected against the real endpoint before implementation). Toggles: session report email, lesson ready email, weekly progress email, streak reminders. **Still email preference storage only** — no email-sending pipeline exists yet; that's separately tracked as Sprint 4's "Email notifications (lesson ready, session report)" item.

---

### S3-08 — Mobile Responsive Audit
**Priority:** P2  
**Status:** 🔲 NOT STARTED  

Review all pages at 375px, 768px, 1024px. Player is desktop-first (Chrome target per PRD) — ensure it degrades gracefully on mobile with a "Desktop recommended" banner rather than a broken layout.

---

### S3-09 — Signed-URL auto-refresh + DEFER-012 register entry — ✓ DONE 2026-08-11
**Priority:** P1 (real user-facing gap, not scheduled Sprint 3 scope — surfaced by `docs/LESSON-DELIVERY-TRACKER.md`'s L3 "Known risk" and this dev's own handoff doc, deviation #2)  
**Status:** ✅ DONE 2026-08-11 — Story `2-45-signed-url-refresh-and-defer-012.md`, branch `sprint3/s3-09-signed-url-refresh` (cut from `sprint3-master` — `useAttentionMonitor.ts` doesn't exist on `main`, S3-01–S3-04 never merged there). 8-layer adversarial review (Blind Hunter, Edge Case Hunter, Acceptance Auditor, Scale & Load Hunter, plus Story Quality/Test Coverage/AC Completeness/Process Integrity) found 11 patch findings + 1 deferred; **all 11 applied same day**, including rebuilding the branch to fix a story-first-gate violation and renumbering a colliding defect ID (D63→**D66**; `sprint3-master` already had D63–D65 allocated — the re-check had been performed against the wrong branch). Full `apps/web` suite passing, `tsc --noEmit` clean, `eslint` clean.  
**Files:** `src/lib/media/refreshSignedUrl.ts` (new), `src/components/player/AudioTimeline.tsx`, `src/components/player/SlideRenderer.tsx`, `docs/DEFECT-REGISTER.md` (**D66**, **D67**), `docs/deferred-work.md`.

Closes the "student pauses past the signed-URL expiry window and loses audio/images with only a manual page-level Retry" gap: `AudioTimeline`'s `handleError()` and `SlideRenderer`'s `SlideImage` now each attempt exactly one automatic per-asset re-sign (via the previously-dormant `GET /api/media/signed-url`, parsing `{bucket, path}` back out of the expired Supabase signed URL, with origin validation and an `expires_in` matching the system's 8-hour window — both added in review) before falling through to the existing manual-recovery UI unchanged. Review also caught and fixed two real playback bugs (a stale failed re-sign could flip `audioError` on a segment/lesson already left; a successful re-sign remounted `<audio>` but never resumed playback) and a guard-reset gap on the image side. No `apps/api` changes. Also closed the DEFER-012 binding-rule-5 gap: `useAttentionMonitor.ts`'s floating MediaPipe model tag now has a real register ID (**D66**), owner Dev 2, trigger = the first live browser verification of L6. **D67** (newly-exposed backend rate-limit gap on the signed-url endpoint) is registered and deferred to Dev 1.

---

## 13. Sprint 4 — Polish + Platform
**Period:** Weeks 8–9 | **Status:** 🔲 NOT STARTED

---

### S4-01 — Landing Page + Pricing Polish
**Priority:** P1  
**Status:** 🔲 NOT STARTED  
**Files:** All `src/components/sections/*.tsx`, `src/app/pricing/page.tsx`

Standalone `/pricing` page with Stripe Checkout CTA. Landing page animation pass: entrance animations, scroll-triggered reveals, hero interaction.

### S4-02 — Stripe Checkout Redirect
**Priority:** P0 — required for first paying student  
**Status:** 🔲 NOT STARTED  
**Files to create:** `src/app/payment/success/page.tsx`, `src/app/payment/cancel/page.tsx`

Dev 1 creates `POST /api/payments/create-checkout-session`. Dev 2 builds the CTA button (redirects to Stripe-hosted URL) and the return pages.

**Flow:**
```
"Buy Lesson" button → POST /api/payments/create-checkout-session
                    → redirect to stripe.com hosted checkout
                    → success: redirect to /payment/success?session_id=...
                    → cancel:  redirect to /payment/cancel
```

No Stripe Elements — hosted checkout only. No card data ever touches HIE's frontend.

### S4-03 — PostHog Full Instrumentation
**Priority:** P1  
**Status:** 🔲 NOT STARTED  

Fire PostHog events for every significant action:

| Event | When |
|---|---|
| `lesson_started` | Player enters PLAYING state |
| `lesson_completed` | Player enters ENDED state |
| `quiz_answered` | Quiz submitted |
| `teachback_submitted` | TeachBack submitted |
| `intervention_received` | TutorInterventionCard shown |
| `upload_started` | File dropped in UploadFlow |
| `upload_completed` | lesson_ready message received |
| `onboarding_completed` | DNA result shown |
| `payment_initiated` | Checkout CTA clicked |

### S4-04 — Accessibility Audit (WCAG AA)
**Priority:** P1  

- All interactive elements have visible focus states
- All images have `alt` text
- Color contrast ≥ 4.5:1 for body text, 3:1 for large text
- `aria-live` regions for quiz feedback and tutor intervention cards
- Keyboard navigation through quiz options (arrow keys + Enter)

### S4-05 — Performance: Code Splitting + Lazy Loading
**Priority:** P2  

- MediaPipe WASM bundle: lazy-loaded only when attention consent given
- Chart library: dynamic import in reports page only
- HeyGen video: preload `<link rel="preload">` in lesson page head
- Lighthouse score target: `/lesson/[id]` > 70 performance

---

## 14. Launch Week
**Period:** Week 10 | **Status:** 🔲 NOT STARTED

| Task | Description | Owner |
|---|---|---|
| Frontend smoke tests | Sign up → onboarding → upload → lesson → report end-to-end | Dev 2 |
| Production URL verification | All routes return 200 / correct redirects on Railway deploy | Dev 2 |
| Console error audit | Zero console errors in production build | Dev 2 |
| Cross-browser check | Chrome 120+, Safari 17+, Firefox 120+ | Dev 2 |
| Final QA | Run through full student journey: landing → payment → lesson → report | All devs |

---

## 15. Cross-Cutting Technical Issues

| Issue | Description | Risk | Mitigation |
|---|---|---|---|
| Hydration mismatch | MediaPipe WASM, `Date.now()`, `window` in SSR | HIGH | All player components use `dynamic(..., { ssr: false })` |
| Suspense boundary stacking | Nested `Suspense` with `ssr:false` dynamic imports | MEDIUM | Single `Suspense` wrapper in `PlayerLoader` |
| WebSocket reconnect race | Player store dispatches events from stale WS connection | MEDIUM | `LessonSocket.disconnect()` in cleanup before reconnect |
| Quiz double-fire | `timeUpdate` fires multiple times at segment boundary | MEDIUM | `quizFiredForSegment: Set<string>` guard |
| Auth token expiry mid-lesson | JWT expires during a long session (default 1h Supabase) | MEDIUM | `supabase.auth.onAuthStateChange` listener refreshes token silently |
| MediaPipe memory leak | WASM memory not released on component unmount | MEDIUM | `faceLandmarker.close()` in `AttentionMonitor` cleanup |
| Animation jank | Framer Motion layout animations during slide transitions | LOW | Use `opacity` only (not `layout`) for slide changes |
| Cache invalidation | Library/dashboard shows stale data after upload completes | LOW | Invalidate SWR cache on `lesson_ready` WebSocket message |
| Seek during QUIZ | Student uses browser back/forward or dev tools to seek audio during quiz | LOW | Disable audio seek (remove `<audio controls>`) — custom controls only |
| `Date.now()` in Workflow scripts | Only relevant in workflow scripting — fine in browser code | N/A | Not applicable to frontend components |
| **Voice-prompt bug in InteractivePlayer** | ~~`InteractivePlayer.tsx` ~line 288: "Speak your answer aloud" — implies STT input. PRD §10: "No STT in MVP — typed teach-back only."~~ **FIXED 2026-06-26** — Mic icon + voice copy removed; `<textarea>` + "Submit &amp; Continue" added; `apps/web/src/types/assessment.ts` created with 9 Dev 3 interfaces. | ~~HIGH~~ DONE | Fixed as part of Dev 3 assessment API handoff (S0-07). Real `TeachBackModal` (S2-02) must also use `<textarea>` only. |
| **InteractivePlayer wrong contract types** | `InteractivePlayer.tsx` uses `MockLesson` types, not the frozen `LessonPackage` contract. Risk: Sprint 1 work accidentally built on top of it diverges from the contract. | HIGH | Replace entirely with `PlayerLoader → Player` stack (S1-01 through S1-06). Do not extend `InteractivePlayer.tsx`. |

---

## 16. Technical Reference

### Folder Naming Convention

```
components/         PascalCase filenames — React components only
hooks/              camelCase with "use" prefix — usePlayerMachine.ts
services/           camelCase with ".service" suffix — lesson.service.ts
stores/             camelCase with ".machine" suffix — player.machine.ts
lib/                camelCase utility modules
mocks/              matches real structure (data/, api/, utils/)
```

### API Convention

All API calls flow through `lib/api.ts` (axios instance with base URL and JWT injection). Services call `api.get(...)` / `api.post(...)` — never raw `fetch()` for backend endpoints.

```typescript
// lib/api.ts
const api = axios.create({ baseURL: process.env.NEXT_PUBLIC_API_URL });
api.interceptors.request.use(async (config) => {
  const { data: { session } } = await supabase.auth.getSession();
  if (session) config.headers.Authorization = `Bearer ${session.access_token}`;
  return config;
});
```

### Component Convention

```typescript
// Preferred pattern for player sub-components
export function ComponentName({ prop1, prop2 }: ComponentNameProps) {
  const store = usePlayerStore();  // Zustand selector
  // ...
}

// Dynamic import (SSR:false) — PlayerLoader only
const Player = dynamic(() => import('./Player'), { ssr: false });
```

### State Management

- **Global UI state:** Zustand (`stores/player.machine.ts`)
- **Server state:** SWR for lesson data, React Query optional for paginated lists
- **Auth state:** `AuthContext` (React context — session data only)
- **Form state:** React `useState` — no form library
- **No Redux. No XState. No MobX.**

### Animation Rules

- All transitions: Framer Motion
- Slide changes: `opacity` fade only (150ms) — never `layout` animations inside player
- Modal enter: translate up + fade (200ms ease-out)
- Intervention card: translate from right + fade (200ms ease-out)
- Page transitions: fade (300ms)
- `prefers-reduced-motion`: all animations wrapped in `useReducedMotion()` check

### Design System

HIE uses Tailwind v4 with shadcn/ui for base components. Custom tokens:
- `--accent-primary`: brand blue
- No hardcoded hex values in component files — use `var(--accent-primary)` or Tailwind tokens
- Typography: Tailwind's type scale, no custom font sizes outside config

---

## 17. Acceptance Criteria Template

Every sprint task uses this format before marking complete:

```
Task: [Task ID] — [Task Name]

Files modified:
  - path/to/file.tsx
  - path/to/another.ts

Implementation verified:
  ☐ Component renders without console errors
  ☐ TypeScript compiles with zero errors (npx tsc --noEmit)
  ☐ Mock mode works (mock flag ON shows no API calls)
  ☐ Real mode works (mock flag OFF, API call fires and response handled)
  ☐ Loading state shown during async operations
  ☐ Error state shown on failure
  ☐ Empty state shown when no data
  ☐ Component unmounts cleanly (no memory leaks, no lingering subscriptions)

Player-specific (if applicable):
  ☐ No SSR hydration error in browser console
  ☐ No audio/video bleed after component unmount
  ☐ State machine transitions are correct sequence

Security checks:
  ☐ No raw video bytes in any network request
  ☐ JWT passed in Authorization header, not query param
  ☐ Consent check gates camera access

Tested at:
  ☐ 1280px desktop (primary target)
  ☐ 768px tablet
  ☐ 375px mobile (degraded gracefully)
```

---

## 18. Update Protocol

**When a task is started:**
- Change status from `🔲 NOT STARTED` to `🔵 IN PROGRESS`
- Note blockers inline (e.g., "Blocked: Dev 3 teachback API not ready — using mock")

**When a task is complete:**
- Change status to `✅ DONE`
- Update the Quick Status Dashboard table counts
- Add completion date as a comment: `<!-- completed: 2026-06-28 -->`

**When a task is blocked:**
- Change status to `🔴 BLOCKED`
- Note the blocker, the owner of the blocker, and the expected unblock date

**Sprint changes:**
- Any new task added to a sprint must have a Task ID (e.g., `S1-13`)
- Any descoped task must be moved to the next sprint, not deleted
- Interface contract changes: immediately flag to all 4 devs before merging

**Never:**
- Mark a task complete without running `npx tsc --noEmit` passing
- Implement backend business logic (quiz scoring, CES formula, DNA fusion)
- Send raw video bytes from any browser code path to any server endpoint
- Call `supabase.auth.getUser()` from inside a React component (use `AuthContext`)
