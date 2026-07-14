# HIE — Master Project Tracker
**Last updated:** 2026-07-06 (Dev 2 Sprint 2 is now fully complete, 5/5 tasks: S2-04 Session Report Page (PR #63) and S2-05 Player State Persistence (PR #66) both merged to `main` via full BMAD story workflows with 5-agent review gates — checklist lines below updated to match. Earlier, 2026-07-04: app-wide `apps/web` audit run, 9 issues patched across 8 rounds incl. an `/auth/callback` regression that broke all OAuth/email sign-in, then a `/bmad-code-review` gate on that fix branch itself — merged to `main` as PR #61 (`a75535d`), 201/201 tests. Separately, Story 2-3 Onboarding Assessment Flow — previously checked off below as done — was discovered to have never actually been merged to `main` (implementation commit sat unpushed on its branch); rebased onto current `main`, merged clean, no conflicts — PR #62 (`5c40db1`), 239/239 tests.)

> Source of truth for cross-team task ownership. Use this to know who to escalate to when blocked.

---

## Escalation Quick Reference

| Blocked on | Owner | Their domain |
|---|---|---|
| PDF extraction, pipeline nodes, Supabase schema, Railway infra | **Dev 1** | Infrastructure + Content Pipeline |
| Next.js frontend, lesson player, upload UI, WebSocket client | **Dev 2** | Lesson Player + Frontend |
| Quiz API, teach-back API, CES formula, Learner DNA, session reports | **Dev 3** | Assessment + Analytics + Learner DNA |
| WebSocket server, JWT middleware, tutor FSM, Redis buffers, interventions | **Dev 4** | Tutor Agent + Attention + Realtime |

---

## Sprint 0 — Week 1 (Foundation)

### Dev 1 — Infrastructure + Content Pipeline
- [ ] Railway project setup + env vars — ⚠️ NOT DEPLOYED YET
- [x] Supabase project + all DB migrations
- [ ] Railway Redis service config — ⚠️ NOT DEPLOYED YET
- [x] GitHub Actions CI/CD pipeline
- [x] Monorepo scaffold (apps/web, apps/api, packages/shared)
- [x] FastAPI app factory + router mounts
- [x] ARQ worker entry point + task registry
- [x] Langfuse + Sentry wired from day one
- [x] Shared Pydantic schemas published in packages/shared/ — to be pushed to main by 2026-06-25
- [ ] Lesson package JSON contract frozen **(BLOCKS ALL DEVS)** — 🔵 IN PROGRESS

### Dev 2 — Lesson Player + Frontend
- [ ] Next.js 14 init + Tailwind CSS
- [ ] Supabase JS client (auth + storage) wired
- [ ] Auth flow (sign up, sign in, JWT session)
- [ ] Dashboard shell + routing structure
- [ ] Shared TS types from lesson package contract
- [ ] Mock API response fixtures for all endpoints
- [ ] Mock WebSocket client for local development

### Dev 3 — Assessment + Analytics + Learner DNA
- [x] Assessment module stub in FastAPI
- [x] DB tables: quiz_attempts, teachback_attempts, learner_dna
- [x] DB tables: onboarding_responses, session_events — subscription table schema also added
- [x] Foreign key between tables and subscription table *(added sprint 0)*
- [ ] Payment gateway integration for subscription — 🔵 IN PROGRESS (architecture done, integration in progress) *(added sprint 0)*
- [x] 20-question onboarding content written + reviewed — drives Learner DNA scoring
- [x] GPT-4o-mini provider wired for scoring
- [x] Teach-back scoring prompt v1 written + tested in isolation
- [ ] OpenAPI spec published for all 5 assessment endpoints — 🔵 IN PROGRESS (Google SSO client secret added to Supabase; SSO integration in progress)

### Dev 4 — Tutor Agent + Attention + Realtime
- [x] FastAPI WebSocket handler scaffold
- [x] Local JWT middleware (PyJWT + SUPABASE_JWT_SECRET)
- [x] Redis LPUSH/LTRIM/LRANGE pattern operational — completed EOD 2026-06-26
- [x] LangGraph StateGraph scaffold (7 state nodes stubbed)
- [x] Tutor module stub in FastAPI
- [x] Mock WebSocket client for local testing (Python script)
- [x] Sentry wired to FastAPI error handler

---

## Sprint 1 — Weeks 2–3 (Core Pipeline + Player Skeleton)

### Dev 1 — Infrastructure + Content Pipeline
- [ ] PyMuPDF text + image + layout extraction node — 🔵 IN PROGRESS (code ready; PDF segmentation testing in progress; image extraction testing pending)
- [ ] pdfplumber table extraction node
- [ ] Tesseract OCR fallback node
- [ ] Structure detection: rule-based (font/TOC/numbering)
- [ ] Structure detection: GPT-4o-mini LLM validation
- [ ] Semantic chunking (chapter → section → topic)
- [ ] text-embedding-3-small + pgvector storage
- [x] lesson_jobs table + ARQ job enqueue — ✓ confirmed live (pipeline submit working)
- [ ] with_retry() decorator (exponential backoff + jitter)
- [x] POST /api/content/lessons — route registered, auth wired, 14/14 tests pass. Body: returns `{lesson_id, status:"queued"}`. Supabase storage + ARQ enqueue are TODO stubs (HTTP 501 until implemented). Dev 2 must keep using mock until Supabase integration lands.
- [x] GET /api/content/lessons — route registered, auth wired. Returns `list[{lesson_id, status, title, progress_pct, error, created_at, completed_at}]`. Supabase query TODO stub.
- [x] GET /api/content/lessons/{lesson_id} — route registered, auth wired. Returns status metadata only — **NOT the full lesson package JSONB**. Supabase query TODO stub. **Dev 2 cannot load lesson content via REST yet.**

### Dev 2 — Lesson Player + Frontend
- [x] Custom React audio-timeline state machine — ✓ done
- [x] Slide renderer from lesson package JSONB — ✓ done
- [x] Audio playback + timestamp-driven slide advance — ✓ done
- [ ] Avatar intro/outro video component (HeyGen cached) — ⛔ BLOCKED: avatar_intro/outro/static_url not in frozen schema; needs all-4-dev sign-off + Sprint 2 avatar node. Deferred to Sprint 2.
- [x] Jargon hover tooltip component — ✓ done
- [ ] Lesson load from real API — ⛔ BLOCKED: GET /api/content/lessons/{id} returns status only (no JSONB). Full package endpoint not built yet. Continue using mock.
- [x] PDF upload UI + generation progress indicator — ✓ done
- [x] Frontend security/bug audit (S1-13) — ✓ 2026-07-02, scoped to apps/web only. Fixed a real auth-guard gap in `middleware.ts` (`/library`, `/upload`, `/onboarding`, `/lesson/[id]` were all completely unauthenticated — allow-list only matched `/dashboard`/`/settings`; now a deny-list, fails safe for future routes) and a resource-leak in `UploadFlow.tsx` (generation socket singleton never disconnected on unmount/completion). See `docs/dev2-sprint-tracker.md` S1-13 for full findings including deferred items (Next.js 16/React 19 vs. locked Next 14 — governance decision, not fixed here).
- [x] Fix 5 pre-existing stale test failures (S1-14) — ✓ 2026-07-02, all confirmed stale (implementation was already correct, tests never updated after commit 5c2b5c5). Suite now 132/132 passing. Merged to `main` alongside S1-07/S1-13 (`a4ca1d3`).
- [x] Build WebSocket client (/ws/{session_id}) (S1-07) — ✓ 2026-07-02, built via BMAD story cycle (Winston-reviewed typing pattern for the frozen `ws.ts` contract vs. live flat-frame backend behavior). `wireTypes.ts` + `lessonSocket.ts` + `useLessonSocket.ts` hook; normalizes non-conforming frames (flat errors, pong, control messages) at the `onmessage` boundary only, rest of app sees frozen `ServerMessage` types. Also fixed a tutor-FSM reconnect fallthrough bug found during review (AC11). Merged to `main` (`a4ca1d3`).
- [x] Sign off on WS message contract — ✓ 2026-07-02, resolved as part of S1-07 implementation (see Dev Notes in `_bmad-output/implementation-artifacts/1-07-websocket-client.md` for the reconciliation approach agreed without modifying the frozen contract).
- [x] Brand recolor — Navy/Gold/Grey palette (S1-15) — ✓ 2026-07-02, full frontend rebrand from generic blue to the HIE logo palette (Navy `#07172C`, Gold `#C6A45C`, Grey `#797B7D`/`#6B6D6F`, Off-white `#F9F9F9`), via BMAD story + UX design review (gold-fill+navy-text pattern for buttons/badges/active-states, since gold fails WCAG contrast as text/icon color on the light canvas). 19 files fixed across hex-literal and Tailwind-utility-class sweeps; sidebar gold-fill active-nav indicator added; 4 additional contrast bugs found via repo-wide re-grep during implementation (not just the pre-listed files) and fixed. Manually verified via Playwright screenshots. 132/132 tests passing, `tsc` clean. See `docs/dev2-sprint-tracker.md` S1-15 for full detail.
- [x] Hero redesign + sitewide brand-consistency pass (S1-18) — ✓ 2026-07-03, replaced the generic text-left/screenshot-right hero with a live "Interruption" demo that enacts HIE's actual attention-drift/active-recall mechanic on real text (moving caret, focus-blur, pausable on hover, 3 rotating passages), copy pressure-tested via an independent adversarial critic before committing. Added Fraunces serif typography sitewide (landing, auth, dashboard, settings, library, upload, lesson player) for one consistent headline voice. Rebuilt Navbar as a floating glass pill, redesigned FAQ/FinalCTA (FinalCTA now bookends the hero's own closing line). Restyled the lesson player off a disconnected generic dark palette onto the real navy/gold brand tokens, establishing navy=structural-UI / gold=reward-highlight / emerald-red=semantic-correctness; caught and fixed a real invisible-progress-bar bug in the process. Verified to fit one full laptop viewport (1440×900 and 1366×768) via Playwright. 132/132 tests passing, `tsc` clean throughout. See `docs/dev2-sprint-tracker.md` S1-18 for full detail. Merged to `main` (`3d41df5`).
- [ ] Wire upload to POST /api/content/lessons — ⬜ ready to wire (URL + auth wired; Supabase stub on backend, will get 501 until Dev 1 implements storage)
- [ ] Wire library/dashboard to GET /api/content/lessons — ⬜ ready to wire (URL + auth wired; will return empty/501 until Dev 1 implements Supabase query)
- [ ] GET /api/sessions/latest for continue-learning card — ⛔ BLOCKED: endpoint doesn't exist, Dev 4 owns (session state in Redis). Escalate.
- [ ] Wire QuizOverlay to POST /api/assessment/quiz — ⬜ READY: endpoint live (Dev 3). Send {session_id, lesson_id, segment_id, answers:[{question_id, response_index, response_time_ms}]}. Receive {score, correct_count, total_count, ces_contribution, feedback}.
- [ ] Wire TeachBackModal to POST /api/assessment/teachback — ⬜ READY: endpoint live (Dev 3). Send {session_id, lesson_id, segment_id, response_text}. Receive {rubric_scores, overall_score, ces_contribution, feedback}.

### Dev 3 — Assessment + Analytics + Learner DNA
- [x] POST /api/assessment/quiz — ✓ LIVE. Accepts {session_id, lesson_id, segment_id, answers:[{question_id, response_index, response_time_ms}]}. Returns {session_id, score, correct_count, total_count, ces_contribution, feedback}.
- [x] MCQ scoring + response time capture — ✓ done (in grade_quiz service)
- [x] POST /api/assessment/teachback — ✓ LIVE. Accepts {session_id, lesson_id, segment_id, response_text}. Returns {session_id, rubric_scores:{accuracy,completeness,clarity}, overall_score, ces_contribution, feedback}.
- [x] GPT-4o-mini rubric scoring (accuracy/completeness/clarity) — ✓ done
- [x] Praise + correction feedback response format — ✓ done (praise only if ≥90, praise+correction if <90)
- [ ] quiz_attempts + teachback_attempts DB writes working — status unknown

### Dev 4 — Tutor Agent + Attention + Realtime
- [x] JWT middleware live and tested on all routes — merge conflicts resolved
- [x] WebSocket connection + message type routing — ✓ live at /ws/{session_id}
- [x] Lesson progress push (ARQ pub/sub → WebSocket) — ✓ lesson_ready push via Redis pub/sub live
- [x] Redis signal buffer operational — ✓ done
- [x] IDLE → TEACHING state transition live — ✓ done
- [x] Session state init on lesson start — ✓ done
- [x] Session state Redis persistence (24h TTL) — ✓ done
- [x] Full 7-state LangGraph StateGraph with real logic — ✓ done (merged Sprint 2 work)
- [x] All 14 transitions wired and tested — ✓ done (884-line test suite)
- [x] QUIZZING → TEACH_BACK → TEACHING flow — ✓ done
- [x] Session state restore on reconnect tested — ✓ done
- [x] Intervention message selection from lesson package — ✓ done
- [x] WebSocket message types finalized — ✓ docs/ws-message-contract.md published. **Needs Dev 2 sign-off.**

---

## Sprint 2 — Weeks 4–5 (Full Pipeline + Integration → Investor Demo)

### Dev 1 — Infrastructure + Content Pipeline
- [ ] lesson_planner node — GPT-4o
- [ ] slide_generator node — GPT-4o
- [ ] summarise_segment node — GPT-4o-mini
- [ ] segment_complexity node — GPT-4o-mini
- [ ] quiz_generator node — GPT-4o-mini
- [ ] jargon_extractor node — GPT-4o-mini
- [ ] intervention_messages node — GPT-4o-mini (3 variations × 3 types)
- [ ] narration_generator node — GPT-4o-mini
- [ ] tts_node — Sarvam Bulbul v2 → Azure TTS → Browser fallback chain
- [ ] image_generator node — GPT Image 1 Mini → Imagen 4 Fast → text-only
- [ ] package_builder node → JSONB write to Supabase
- [ ] WebSocket lesson_ready push working
- [ ] Cost ceiling implementation (MAX_LESSON_COST_USD env var)
- [ ] Eval harness running against 5 PDFs

### Dev 2 — Lesson Player + Frontend
- [x] Quiz popup integration (Dev 3 API) — ✓ 2026-07-01, wired to `POST /api/assessment/quiz` in `QuizOverlay.tsx`
- [x] Teach-back modal integration (Dev 3 API) — ✓ 2026-07-01, wired to `POST /api/assessment/teachback` in `TeachBackModal.tsx`
- [ ] Segment-end detection → CHECKING IN state — 🔴 PARTIALLY BLOCKED, escalated to Dev 4 2026-07-06. **Corrected 2026-07-06** (previous 2026-07-02 note overstated readiness — "Dev 4's FSM state is live in the player store" was not actually true): `sendControl({type:'segment_complete'})` and `useLessonSocket` (S1-07) are built and unit-tested in isolation, but `useLessonSocket` is **not mounted anywhere in the live player** (`Player.tsx`/`PlayerLoader.tsx`) — the lesson WebSocket never actually connects during a real session today, so `setTutorState()` is never called in production regardless of what the server sends. `tutorState` in `player.machine.ts` also has zero readers anywhere in the UI — no CHECKING_IN screen exists. Quiz triggering today is entirely client-local (`AudioTimeline.tsx` calls `store.enterQuiz()` directly on segment boundary), with no round-trip to the backend tutor FSM at all.
  - **Send side — NOT blocked, can proceed any time:** mount the socket live in the player, call `sendControl({type:'segment_complete'})` on segment end.
  - **Receive side — genuinely blocked, escalated to Dev 4 2026-07-06** (see Cross-Team Dependency Map above): traced the actual code path (`websocket.py:_handle_tutor_event` → `service.py:advance_tutor_state` → `graph.py:dispatch_event`) and confirmed none of them ever call `manager.send()` — the FSM transitions internally but nothing broadcasts it. The *only* live `state_change` emitter is the reconnect-sync path, and it always sends `from_state == to_state` (a sync, not a transition), exactly as `docs/ws-message-contract.md` already documents. This is **not** "pending integration test" as the 2026-07-02 note assumed — the broadcast call doesn't exist in the code at all. Asked Dev 4 to add a `manager.send(state_change)` call inside `dispatch_event()` whenever `from_state != to_state`. Holding S2-06's CHECKING_IN UI work until that lands; the send-side half may still proceed independently. See Dev 2 tracker §11 S2-06 for the full write-up and the exact message sent.
- [x] Feedback display (praise + correction sentences) — ✓ 2026-07-02, `result.feedback` rendered in both `QuizOverlay.tsx` and `TeachBackModal.tsx`. **Corrected 2026-07-04:** `TeachBackModal.tsx`'s feedback display was also rendering a numeric `overall_score` and a full rubric breakdown alongside the encouraging message — a real hard-constraint violation ("never show a rubric score"), caught during a tracker-vs-codebase audit with zero prior test coverage on either component. Fixed: score/rubric stripped, 18 new tests added across both. See Dev 2 tracker §11 S2-01/S2-02.
- [x] Session report page v1 (quiz + teach-back scores) — ✓ merged to `main` 2026-07-04 (PR #63). Implemented as Story 2-4 via BMAD workflow, 5-agent review passed. `src/app/reports/[sessionId]/page.tsx` — quiz accuracy %, CES and teach-back shown as qualitative labels only (never raw scores, per CLAUDE.md), "Study Again" link. Found and fixed a real pre-existing bug along the way: `types/assessment.ts`'s `ces_breakdown` used wrong key names that never matched the real backend contract. See Dev 2 tracker §11 S2-04.
- [x] Onboarding assessment UI (20 questions flow) — ✓ merged to `main` 2026-07-04 (PR #62, `5c40db1`). Implemented as Story 2-3 via BMAD workflow, 5-agent review passed (14 patches), `OnboardingFlow.tsx`/`QuestionCard.tsx`/`questions.ts`. **Process gap caught and fixed same day:** this was implemented and reviewed on 2026-07-04 but the commit sat unpushed on `sprint2/s2-3-onboarding-flow` and was never merged — `main` genuinely had none of this code even though this line had already been checked off prematurely. Caught during a status audit, branch was rebased onto current `main` (auto-merged cleanly against the intervening audit-fixes and Dev 3 CES/DNA-fusion work) and merged for real. Lesson: don't mark a task done in this tracker until `git merge-base --is-ancestor <branch> main` confirms it, not just "story + review complete."
- [x] Learner DNA profile display component — ✓ shipped as part of the same S2-03 merge above — `DNAResultCard.tsx` renders `badge_labels` + `profile_text` (no raw scores). Was listed as a separate not-started line item here but is functionally the same deliverable as the onboarding UI's result screen; folding it in rather than double-tracking.
- [x] Player state persistence / session restore — ✓ merged to `main` 2026-07-06 (PR #66). Implemented as Story 2-5 via BMAD workflow, 5-agent review passed (7 patches applied). `player.machine.ts` `saveProgress`/`restoreProgress`, keyed by `hie:session:{lesson_id}` in localStorage; resumes segment/audio-position/quiz-fired state within ±3s on refresh. This line item wasn't in the master tracker's original Sprint 2 sketch — added here since it's the 5th and last Dev 2 Sprint 2 task per the Dev 2 tracker's own §11 breakdown. **4 new Learner Mode tasks added below 2026-07-14 — see Dev 2 tracker §11 S2-07–S2-10 for full detail.**
- [ ] **Learner Mode — mode selection screen** (new feature, added 2026-07-14) — 3 cards after upload: T1 Deep / T2 Balanced / T3 Refresher. No story/spec exists yet. See Dev 2 tracker §11 S2-07.
- [ ] **Learner Mode — tier disclaimers** (added 2026-07-14) — inline warnings: T2 time-deficit, T3 refresher-only, T1 none. See Dev 2 tracker §11 S2-08.
- [ ] **Learner Mode — wire selected tier into lesson creation** (added 2026-07-14) — pass chosen tier into the lesson-creation request (field/contract not yet defined — needs Dev 1 sign-off), show chosen tier on the generating screen. See Dev 2 tracker §11 S2-09.
- [ ] **Learner Mode — tier badge on player + session report** (added 2026-07-14) — e.g. `Deep · 45 min`, shown in the player chrome and on the session report. See Dev 2 tracker §11 S2-10.

### Dev 3 — Assessment + Analytics + Learner DNA
- [ ] Onboarding assessment scoring logic complete
- [ ] learner_dna table initial writes (9 sub-dimensions)
- [ ] Session report generation API live
- [ ] Jargon hover usage event tracking
- [ ] Session events instrumentation (tab_switch, retry_after_fail, etc.)
- [ ] Basic analytics module (per-session aggregations)
- [ ] PostHog events for all assessment actions

### Dev 4 — Tutor Agent + Attention + Realtime
- [ ] Full 7-state LangGraph StateGraph with real logic — 🔵 code merged + unit tested (mock Redis); pending integration test against live Redis
- [ ] All 14 transitions wired and tested — 🔵 code merged + 884-line unit test suite; pending integration test
- [ ] CHECKING IN → QUIZZING → TEACH-BACK → TEACHING flow — 🔵 code merged; pending integration test
- [ ] Session state restore on reconnect tested — 🔵 code merged; pending live-network test
- [ ] Intervention message selection from lesson package — 🔵 code merged; pending integration test
- [x] WebSocket message types finalized and published — ✓ docs/ws-message-contract.md published. **Needs Dev 2 sign-off.**

---

## Sprint 3 — Weeks 6–7 (MediaPipe + CES + Full Tutor FSM)

> **Prerequisite:** Migrate FastAPI/ARQ from Railway to India-region provider before real students join (Fly.io Mumbai, Render Singapore, or AWS ap-south-1). Dev 1 owns this migration.

### Dev 1 — Infrastructure + Content Pipeline
- [ ] Eval harness expanded to 20 PDFs
- [ ] Prompt iteration from eval results (slides + quiz quality)
- [ ] Circuit breaker implementation (Redis state, 5 failures/2min)
- [ ] Admin panel: job status, cost tracking, failed jobs
- [ ] Pipeline cost attribution in Langfuse

### Dev 2 — Lesson Player + Frontend
- [ ] MediaPipe Face Landmarker WASM integration
- [ ] 5-signal aggregation every 5 seconds (client-side)
- [ ] WebSocket attention payload sending (~200 bytes/5s)
- [ ] Consent flow UI (camera permission + privacy notice)
- [ ] Tutor intervention card component (Type A/B/C)
- [ ] CES indicator in player (subtle, non-intrusive UI)
- [ ] Session report: attention timeline chart
- [ ] Mobile responsive audit

### Dev 3 — Assessment + Analytics + Learner DNA
- [ ] CES v1 formula implementation (5 weights as env vars)
- [ ] Per-learner baseline computation
- [ ] Learner DNA fusion formula live
- [ ] GPT-4o-mini profile text generation
- [ ] Growth tracking (delta per dimension per session)
- [ ] Session report: Learner DNA section
- [ ] Re-assessment prompt after 10 sessions logic

### Dev 4 — Tutor Agent + Attention + Realtime
- [ ] Attention signal ingestion from WebSocket live — 🔵 code merged; pending integration test against live Redis
- [ ] Redis CES buffer (LPUSH/LTRIM/LRANGE) computing every 5s — 🔵 code merged; pending integration test
- [ ] CES computation in-process (~3–5ms total) — 🔵 code merged; pending integration test
- [ ] Intervention trigger: 2 consecutive windows below threshold — 🔵 code merged; pending integration test
- [ ] 2-minute cooldown enforcement (Redis TTL key) — 🔵 code merged; pending integration test
- [ ] Max 3 distraction interventions per session cap — 🔵 code merged; pending integration test
- [ ] Fatigue intervention: once per session flag — 🔵 code merged; pending integration test
- [ ] Type A/B/C intervention routing to correct message — 🔵 code merged; pending integration test

---

## Sprint 4 — Weeks 8–9 (Load Test + Calibration + Stripe + Hardening)

### Dev 1 — Infrastructure + Content Pipeline
- [ ] Load test: 50 concurrent lesson generations
- [ ] All pipeline reliability fixes from test sessions
- [ ] Stripe Checkout integration (hosted page, not custom UI)
- [ ] Rate limiting (slowapi middleware)
- [ ] RLS security audit on all Supabase tables
- [ ] Railway backups confirmed + disaster recovery tested
- [ ] On-call runbook written (5 most likely failure scenarios)

### Dev 2 — Lesson Player + Frontend
- [ ] All UI bugs from real student test sessions fixed
- [ ] Loading + error + empty states for all flows
- [ ] Email notifications (lesson ready, session report)
- [ ] Landing page + marketing copy
- [ ] Pricing page
- [ ] Stripe Checkout redirect integrated into onboarding flow
- [ ] Accessibility audit (WCAG AA minimum)

### Dev 3 — Assessment + Analytics + Learner DNA
- [ ] Analyse 20+ real student test session data
- [ ] CES weight tuning against post-session ground truth quiz scores
- [ ] Update tuned weights in Railway env vars
- [ ] Learner DNA profile quality review (human review 10 profiles)
- [ ] Onboarding question quality audit
- [ ] PostHog funnel analysis: where do students drop off?

### Dev 4 — Tutor Agent + Attention + Realtime
- [ ] Intervention threshold tuning — 🔵 PARTIAL: methodology written, pending ≥20 real sessions of data
- [ ] Review which interventions students responded to vs ignored — 🔵 PARTIAL: blocked on instrumentation + real data
- [ ] Cooldown period tuning from real session data — 🔵 PARTIAL: methodology written, pending session data
- [ ] WebSocket stability testing under 50 concurrent users — 🔵 PARTIAL: harness built + locally validated, production run pending staging
- [ ] Session reconnect testing under poor network conditions — 🔵 PARTIAL: all-7-states Redis restore proven, live network-fault sim pending
- [ ] Intervention message copy review (tone + warmth) — 🔵 PARTIAL: checklist ready, pending 5 real lesson packages

---

## Week 10 — Launch

### Dev 1 — Infrastructure + Content Pipeline
- [ ] Production deployment verified end-to-end
- [ ] Monitoring dashboards live (Langfuse + Sentry + Railway)
- [ ] On-call rotation established
- [ ] First paying user pipeline job monitored live

### Dev 2 — Lesson Player + Frontend
- [ ] Final UX pass — first user onboarding flow verified
- [ ] All critical paths smoke-tested in production

### Dev 3 — Assessment + Analytics + Learner DNA
- [ ] First session report reviewed for quality
- [ ] First Learner DNA profile verified for accuracy

### Dev 4 — Tutor Agent + Attention + Realtime
- [ ] WebSocket stability confirmed at launch load
- [ ] Tutor interventions verified firing correctly in production

---

## Cross-Team Dependency Map

```
When Dev 2 is blocked on...                          → Escalate to...
────────────────────────────────────────────────────────────────────────────────────
POST /api/content/lessons (upload)                   → Dev 1 ⚠️ route live, Supabase impl TODO (501)
GET /api/content/lessons (library list)              → Dev 1 ⚠️ route live, Supabase impl TODO (501)
GET /api/content/lessons/{id} (status only)          → Dev 1 ⚠️ route live, Supabase impl TODO (501)
Full lesson package JSONB via REST                   → Dev 1 ❌ not built — GET /{id} returns status only, no content field. Discuss whether to add content field to existing model or build new endpoint.
Supabase Storage signed URLs                         → Dev 1
avatar_intro/outro/static_url in lesson package      → All 4 devs (schema change) — Sprint 2
POST /api/assessment/quiz                            → Dev 3 ✅ live and implemented
POST /api/assessment/teachback                       → Dev 3 ✅ live and implemented
GET /api/assessment/session/{id}/report              → Dev 3 ⬜ Sprint 2 stub
POST /api/assessment/onboarding/submit               → Dev 3 ✅ live and implemented — confirmed by Dev 2's S2-03 integration (2026-07-04), returns `{badge_labels, profile_text, session_count}`, not the `{dna_label, profile_narrative}` shape earlier docs assumed
GET /api/sessions/latest (continue-learning card)    → Dev 4 ❌ not built, needs new endpoint
WebSocket /ws/{session_id}                           → Dev 4 ✅ live
WS message contract sign-off                         → Dev 2 ACTION: review docs/ws-message-contract.md
tutor_intervene / attention_ack msgs                 → Dev 4 ✅ live
state_change on a REAL transition (from != to)       → Dev 4 ❌ ESCALATED 2026-07-06 — only the reconnect-sync path
                                                        (websocket.py ConnectionManager.connect) ever sends state_change,
                                                        and always from==to. advance_tutor_state()/dispatch_event() mutate
                                                        the FSM but never call manager.send(). Blocks S2-06's CHECKING_IN
                                                        UI (send side unblocked — sendControl({segment_complete}) works
                                                        today; only the receive side needs this). See Dev 2 tracker §11
                                                        S2-06 for the full message sent to Dev 4.
JWT middleware / auth errors                         → Dev 4 ✅ live
```
