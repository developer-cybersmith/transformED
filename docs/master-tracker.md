# HIE — Master Project Tracker
**Last updated:** 2026-09-01 (Sprint 4 close-out sync + **Bug Resolution Sprint (Feature Sprint 2) added**. Sprint 4: S4-02/03/04 all merged to `main` (not just `sprint4-master`); a cross-team `attention_signal` null-vs-0.0 fix merged; Dev 3's onboarding audit (S4-5), session dedup (S4-11), D116 `ces_final` wiring, D137 reassessment-overwrite fix, and the new Learner DNA → CES threshold personalization (S4-13) all merged — the last two found and fixed via cross-team review this session (D137: reassessment was discarding real behavioral fusion data on every retake; S4-13: a dimension-name sign inversion that would have raised intervention frequency for students actually doing well, plus two CI guard-test regressions hidden in an "advisory, not gating" bucket that doesn't fail the build — both independently re-verified against real CI logs, not the green checkmark). Dev 1's Razorpay backend (PR #157), rate limiting (PR #159), and RLS audit (PR #160) remain open/unmerged — #157 has a failing CI check despite an existing approval, #159/#160 have real merge conflicts. **New: Bug Resolution Sprint** — a second feature sprint started immediately after Sprint 4 on per-dev integration branches; full task list added below per-dev, Dev 4 already has 2 items done (caption-cue WS delivery, CES-timing-vs-human-narration verification) and 1 in progress (backend CAPTCHA verification).) — previously 2026-08-27 (Dev 2 Sprint 4 sync: S4-10 loading/error/empty-states and S4-12 email notifications checked off DONE (both merged into `sprint4-master`, 8-agent reviews passed); S4-02 Razorpay marked PARTIAL, not DONE — the frontend checkout unit is built/reviewed/merged but not yet wired into a page, and partly blocked on the backend's `GET /api/payments/access` not existing yet; added a new PostHog event-instrumentation line (S4-03, DONE) feeding into the existing Dev 3 "PostHog funnel analysis" line below — instrumentation is wired but not yet producing real data since the production PostHog key hasn't been added to Vercel yet.) — previously 2026-08-24 (Cross-team reconciliation against each dev's own online tracker. Dev 1 Sprint 3: all 5 lines flipped to done, unverified by Dev 2 — see note below that section (also flags stale ElevenLabs/DALL-E provider labels on the Sprint 2 tts_node/image_generator lines in Dev 1's online tracker itself, contradicting CLAUDE.md's locked stack and this doc's own already-verified entries). Dev 3 Sprint 3: Growth tracking and Session report Learner DNA section flipped to done — corroborated via Dev 2 tracker §11 S2-10's consumption of Dev 3's Story 3-30; Re-assessment prompt logic still IN PROGRESS. Payment gateway switched Stripe → Razorpay across all trackers/specs (see `docs/decisions/ADR-002-payment-gateway-razorpay.md`); Dev 2's own S4-10 (loading/error/empty states) shipped, 8-agent review passed.) — previously 2026-08-10 (Cross-team reconciliation against each dev's own online tracker. Dev 2: S3-02 AttentionMonitor shipped + S3-07 Notifications UI found already done but never checked off — Sprint 3 now 5/8 for Dev 2. Dev 1/3/4 Sprint 0-2 sections updated from their online tracker (several items marked "per their own tracker, unverified by Dev 2" where this doc previously had stronger caveats, e.g. Dev 4's Sprint 2 "pending integration test" notes and Dev 3's Sprint 2 7-item jump from all-not-started to all-done). Dev 3 and Dev 4's Sprint 3 backend claims (CES formula, DNA fusion, attention ingestion, intervention triggers, cooldowns, caps) were independently verified against real code on `origin/main` with file:line citations — all 10 + 2 confirmed, and 2 of Dev 4's own "Not Started" lines turned out to already be done in the actual repo.) — previously 2026-08-06 (Dev 2's Sprint 3 checklist below brought current — Consent flow UI, Tutor intervention card, and CES indicator all shipped (S3-01/S3-03/S3-04). D18, D29, D30 all closed. See Dev 2 tracker §12 for full detail.) — previously 2026-07-29 (Both systemic Dev 1 pipeline bugs reported 2026-07-27 are now fixed and verified end-to-end — backend fixes PR #100/#101, frontend fix (Story 2-33) closing the visible TTS-fallback symptom. Dev 2's Sprint 2 checklist below also brought current — S2-11 through S2-15, S2-26, S2-33 all shipped. See status notes below.)

> Source of truth for cross-team task ownership. Use this to know who to escalate to when blocked.

---

**Status note — 2026-07-29 (Sprint 2 completion audit):** Full cross-team verification run at the user's request — every frontend page and every backend endpoint accessible to it read in full, cross-referenced against each other and against all 4 devs' Sprint 2/Learner Mode tracker claims. Full writeup: `docs/sprint2-completion-audit-2026-07-29.md`. **Sprint 2 is not yet end-to-end functional for a real student.** Upload → generate → play-lesson is genuinely solid (Dev 1 + Dev 2, nothing mocked). The assessment path (quiz, teach-back, session report) is correctly implemented on both ends but structurally broken in practice: **D18** — no code anywhere creates a `sessions` row, confirmed independently via direct grep (zero `.insert()` calls against `sessions` in `apps/api`), re-confirmed against `main` a day later — still open, needs a joint Dev 2 + Dev 3 + Dev 4 decision. Two new defects registered: **D29** (DPDP `user_consents` table has a migration but no writer — Dev 3, a CLAUDE.md §18 Sprint 2 priority) and **D30** (3 tests failing on `main` in `test_tutor_service.py`, reproduced live twice — Dev 4). Resolved during this audit: Dev 2 signed off on `docs/ws-message-contract.md` (caught and corrected one staleness in the doc — a dropped `attention_ack.ces` field — before signing off). See `docs/DEFECT-REGISTER.md` for full defect details.

**Status note — 2026-07-29:** Both bugs from the 2026-07-27 audit are now resolved. Bug 1 (Phase 1 quiz/segment-data duplication): fixed at the root (PR #100, Story 2-28) by removing the `**state` spread that was re-accumulating `operator.add` reducer fields on every node return — root cause was graph shape (`2⁴ = 16×` in one clean run), not ARQ retries as first suspected. Bug 2 (TTS-fallback losing the narration script): backend half fixed (PR #101, Story 2-31 — `_fallback_narration()` now recovers the real script), frontend half fixed (Story 2-33 — a virtual playback clock actually closes the "quiz fires at 0:00" symptom, since the backend fix alone didn't change what a student saw). See the Sprint 2 Dev 1 section below for the full per-node status and Dev 2 tracker §11 S2-33 for the frontend fix's own review findings.

**Status note — 2026-07-27 (superseded by the above for bug status, per-node checklist below still current):** Full code-level audit of Dev 1's Sprint 2 pipeline (all 11 nodes + cost ceiling + `lesson_ready` push + eval harness), run against actual `main`/`sprint2-master` code rather than this tracker's own (badly stale) checklist. Summary: everything is implemented; most of it is genuinely correct; two real, systemic bugs found — see `docs/dev1-sprint2-bug-status-correction.md` for the full write-up handed to Dev 1 (now fixed, per the note above).

**Status note — 2026-07-13 (superseded by the above):** Backend content-ingestion pipeline (Sprint 1) merged to `main` 2026-07-13 (PR #72). Sprint 2 backend — lesson generation (11 nodes: `lesson_planner`, `slide_generator`, `summarise_segment`, `quiz_generator`, `segment_complexity`, `jargon_extractor`, `intervention_messages`, `narration_generator`, `tts_node`, `image_generator`, `package_builder`) — is Dev 1's next work, starting now. **Frontend/assessment/tutor should continue building against existing mocks/fixtures** (`apps/web/src/mocks/data/lessonPackage.ts`, test fixtures) until `package_builder` (Story S2-11) lands — please do not build a parallel real-content path or workaround; ping Dev 1 first if a mock is blocking real progress.

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
- [x] Payment gateway integration for subscription — ✓ per Dev 3's own tracker (2026-08-10), architecture + integration both complete. Not independently re-verified against code by Dev 2. *(added sprint 0)*
- [x] 20-question onboarding content written + reviewed — drives Learner DNA scoring
- [x] GPT-4o-mini provider wired for scoring
- [x] Teach-back scoring prompt v1 written + tested in isolation
- [x] OpenAPI spec published for all 5 assessment endpoints — ✓ per Dev 3's own tracker (2026-08-10). Not independently re-verified against code by Dev 2.

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
- [x] PyMuPDF text + image + layout extraction node — ✓ 2026-07-13, merged to `main` (PR #72). Note: implemented per CLAUDE.md as pypdfium2 + pdftext (PyMuPDF/fitz is AGPL-3.0 banned) — task title predates that decision, kept for tracker continuity.
- [x] pdfplumber table extraction node — ✓ 2026-07-13, merged to `main` (PR #72); pdfplumber triggers docling for table-markdown extraction
- [x] Tesseract OCR fallback node — ✓ 2026-07-13, merged to `main` (PR #72)
- [x] Structure detection: rule-based (font/TOC/numbering) — ✓ 2026-07-13, merged to `main` (PR #72)
- [x] Structure detection: GPT-4o-mini LLM validation — ✓ 2026-07-13, merged to `main` (PR #72)
- [x] Semantic chunking (chapter → section → topic) — ✓ 2026-07-13, merged to `main` (PR #72)
- [x] text-embedding-3-small + pgvector storage — ✓ 2026-07-13, merged to `main` (PR #72)
- [x] lesson_jobs table + ARQ job enqueue — ✓ confirmed live (pipeline submit working)
- [ ] with_retry() decorator (exponential backoff + jitter)
- [x] POST /api/content/lessons — route registered, auth wired, 14/14 tests pass. Body: returns `{lesson_id, status:"queued"}`. Supabase storage + ARQ enqueue are TODO stubs (HTTP 501 until implemented). Dev 2 must keep using mock until Supabase integration lands.
- [x] GET /api/content/lessons — route registered, auth wired. Returns `list[{lesson_id, status, title, progress_pct, error, created_at, completed_at}]`. Supabase query TODO stub.
- [x] GET /api/content/lessons/{lesson_id} — route registered, auth wired. Returns status metadata only — **NOT the full lesson package JSONB**. Supabase query TODO stub. **Dev 2 cannot load lesson content via REST yet.**

### Dev 2 — Lesson Player + Frontend
- [x] Custom React audio-timeline state machine — ✓ done
- [x] Slide renderer from lesson package JSONB — ✓ done
- [x] Audio playback + timestamp-driven slide advance — ✓ done
- [x] Avatar intro/outro video component (HeyGen cached) — ✓ 2026-07-29, unblocked and shipped as Story 1-5 (PR #109). Cross-team sign-off confirmed on `docs/proposals/avatar-fields-schema-change.md`; added 3 optional `avatar_intro_url`/`avatar_static_url`/`avatar_outro_url` fields to the frozen `LessonPackage` contract (NOT required, to avoid repeating the `tier`/Story 2-25 regression) plus `AvatarOverlay.tsx`. Not yet visibly active for real students — `package_builder_node` doesn't populate these fields yet (Dev 1 follow-up). See Dev 2 tracker §10 S1-05.
- [x] Jargon hover tooltip component — ✓ done
- [x] Lesson load from real API — ✓ 2026-07-23. Unblocked by Dev 1's Story 1-6 (`GET /api/content/lessons/{id}` now returns real `content` with signed media URLs). Wired frontend-side as Story 1-7: `lesson.service.ts`/`useLesson.ts` swapped off mocks onto the real endpoint, `PlayerLoader.tsx` now distinguishes running/queued/failed/ready instead of collapsing to a permanent error, `AudioTimeline.tsx` degrades gracefully on an empty `audio_url`.
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
- [x] quiz_attempts + teachback_attempts DB writes working — ✓ per Dev 3's own tracker (2026-08-10), resolving this section's prior "status unknown." Not independently re-verified against code by Dev 2.

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

> **Corrected 2026-07-27, bugs fixed 2026-07-28/29** — every line below was still shown as `[ ]` not-started since 2026-07-13; all 11 nodes are actually built (stories `2-1`, `2-1b`, `2-6` through `2-25` in `docs/stories/`). Re-verified against real code, not just story status. Two systemic bugs found 2026-07-27, reported to Dev 1 (`docs/dev1-sprint2-bug-status-correction.md`), and **both are now fixed and verified in the merged code** — see below.

- [x] lesson_planner node — GPT-4o — ✓ working, no bugs found. Idempotent (whole-node Supabase checkpoint on a plain `lesson_plan` dict field, no accumulation risk). Extensive validation: segment count/id/duplicate/blank checks, batch-and-reassemble for large chapters, cost-ceiling-aware downshift that fails closed on a Redis outage.
- [x] slide_generator node — GPT-4o — ✓ working, no bugs found. Same idempotent design as `lesson_planner_node` (`slides` is a plain list, not an `operator.add` reducer field).
- [x] summarise_segment node — GPT-4o-mini — ✓ working. Shared the systemic Phase 1 duplication bug — **fixed** (see below).
- [x] segment_complexity node — GPT-4o-mini — ✓ working. Same systemic bug, **fixed**.
- [x] quiz_generator node — GPT-4o-mini — ✓ working. Same systemic bug — this is the one live-tested as "32 quiz questions from 2 unique items, repeated 16x." **Fixed**, PR #100 (Story 2-28), verified live.
- [x] jargon_extractor node — GPT-4o-mini — ✓ working. Same systemic bug, **fixed**.
- [x] intervention_messages node — GPT-4o-mini (3 variations × 3 types) — ✓ working. Same systemic bug, **fixed**.
- [x] narration_generator node — GPT-4o-mini — ✓ working. Same systemic bug, **fixed** — this was behind the TTS-fallback script-loss bug below, also fixed.
- [x] tts_node — Sarvam Bulbul v2 → Azure TTS → Browser fallback chain — ✓ working. No bug in this node itself; the "wasted cost on duplicate scripts" downstream symptom is resolved now that the Phase 1 duplication bug is fixed.
- [x] image_generator node — GPT Image 1 Mini → Imagen 4 Fast → text-only — 🔵 implemented, not fully verified (fallback chain + hardened URI decoding look solid on the portion reviewed; not exhaustively read)
- [x] package_builder node → JSONB write to Supabase — ✓ working. Both real bugs found 2026-07-27 are fixed: (1) `_fallback_narration()` now recovers the real script from `state["narration_scripts"]` instead of blanking it (PR #101, Story 2-31). (2) The Phase 1 duplication root cause (below) is fixed at the source, so `_group_by_segment_id()` no longer receives duplicate entries to begin with.
- [x] WebSocket lesson_ready push working — ✓ confirmed implemented in `apps/api/app/workers/jobs/content_pipeline.py`, matches the frozen `ws.ts` contract.
- [x] Cost ceiling implementation (MAX_LESSON_COST_USD env var) — ✓ working. `settings.max_lesson_cost_usd` wired via `check_ceiling()`/`accumulate_cost()` across `lesson_planner_node`, `slide_generator_node`, `tts_node`, `image_generator_node`, and the Phase 1 fan-out router; fails safe (downshifts) rather than fails open.
- [x] Eval harness running against 5 PDFs — 🔵 harness itself implemented and unit-tested (Story 2-14); the actual live 5-PDF run is deliberately gated behind a `@pytest.mark.live_eval` marker and has not been executed yet — an explicit scope decision in the story, not a gap.

**Systemic bug (Phase 1 economy nodes) — FIXED, PR #100 (Story 2-28), 2026-07-28.** Root cause was not what either dev first suspected — ARQ's `max_tries=3` means 16 retries was never possible. The real cause: every downstream node's `return {**state, ...}` re-spread already-accumulated `operator.add` reducer fields back into the return value, and LangGraph's merge-as-append semantics for reducer channels turned that into `2⁴ = 16×` duplication in a single clean run, no retry involved. Fixed by dropping the `**state` spread from every node's return — verified directly in the merged diff. Also added: per-attempt `thread_id` nonces + `MemorySaver` eviction (a separate memory-hygiene fix, not the duplication fix itself) and duplication canary logging/tests.

**TTS-fallback script loss — backend half FIXED, PR #101 (Story 2-31), 2026-07-28; frontend half FIXED, Story 2-33, 2026-07-29.** `_fallback_narration()` now recovers the real script before falling back to blank (backend). But the backend fix alone didn't change what a student saw — `AudioTimeline.tsx`'s `!hasAudio` branch still called `handleEnded()` immediately regardless of script presence, so "quiz fires at 0:00" persisted until Dev 2 built a virtual playback clock (`processTimeUpdate`-driven synthetic timer) to actually close the visible symptom. See Dev 2 tracker §11 S2-33 for full detail, including 2 High-severity bugs the 3-agent review caught before that merged.

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
- [x] **Learner Mode — mode selection screen** (added 2026-07-14) — ✓ 2026-07-14, 3 cards after upload: T1 Deep / T2 Balanced / T3 Refresher. See Dev 2 tracker §11 S2-07.
- [x] **Learner Mode — tier disclaimers** (added 2026-07-14) — ✓ 2026-07-14, inline warnings: T2 time-deficit, T3 refresher-only, T1 none. See Dev 2 tracker §11 S2-08.
- [x] **Learner Mode — wire selected tier into lesson creation** (added 2026-07-14) — ✓ 2026-07-21, chosen tier passed into the lesson-creation request and shown on the generating screen; code review complete on `feature-learner-mode`. See Dev 2 tracker §11 S2-09.
- [ ] **Learner Mode — tier badge on player + session report** (added 2026-07-14) — e.g. `Deep · 45 min`, shown in the player chrome and on the session report. Re-scoped 2026-07-21: splits into an unblocked player half + a Dev-3-blocked session-report half (needs a new `tier` field on `SessionReport`) — decision pending. See Dev 2 tracker §11 S2-10.
- [x] **Quiz feedback field-name fix** (S2-11, added 2026-07-23) — ✓ `correct`/`message` → `is_correct`/`explanation`, matching the real backend contract. See Dev 2 tracker §11 S2-11.
- [x] **Re-assessment prompt after 10 sessions** (S2-12, added 2026-07-23) — ✓ frontend counterpart to Dev 3's Story 3-31. See Dev 2 tracker §11 S2-12.
- [x] **Assessment library test gaps + RubricScores type drift** (S2-13, added 2026-07-27) — ✓ found during first live end-to-end test session. See Dev 2 tracker §11 S2-13.
- [x] **Wire dashboard/library to real GET /lessons** (S2-14, added 2026-07-27) — ✓ both were still calling mocks despite the real endpoint being ready. See Dev 2 tracker §11 S2-14.
- [x] **Fix dashboard/library 401** (S2-15, added 2026-07-27) — ✓ Server Components can't use the browser-only auth interceptor; converted to Client Components. See Dev 2 tracker §11 S2-15.
- [x] **Audio buffering + playback-error retry states** (S2-26, added 2026-07-29) — ✓ merged to `main` via PR #95. See Dev 2 tracker §11 S2-26.
- [x] **Virtual playback clock + retry re-fetch on media error** (S2-33, added 2026-07-29) — ✓ merged to `main` via PR #106 — this is the frontend half that closes the TTS-fallback bug above. See Dev 2 tracker §11 S2-33.

### Dev 3 — Assessment + Analytics + Learner DNA

> **2026-08-10:** all 7 lines below flip from not-started to done per Dev 3's own online tracker in one update — a large, one-shot jump this section had no prior visibility into. **None of the 7 have been independently re-verified against code by Dev 2** (unlike the Sprint 2 Dev 1 pipeline audit above, which read every node directly before checking anything off). Flagging rather than silently absorbing, given this exact domain (assessment/session reporting) is where D18 was found — a case where Dev 3's own "live and implemented" claim for session creation was contradicted by a direct grep finding zero `.insert()` calls against `sessions` anywhere in `apps/api`.

- [x] Onboarding assessment scoring logic complete — per Dev 3's own tracker, unverified by Dev 2
- [x] learner_dna table initial writes (9 sub-dimensions) — per Dev 3's own tracker, unverified by Dev 2
- [x] Session report generation API live — per Dev 3's own tracker, unverified by Dev 2
- [x] Jargon hover usage event tracking — per Dev 3's own tracker, unverified by Dev 2
- [x] Session events instrumentation (tab_switch, retry_after_fail, etc.) — per Dev 3's own tracker, unverified by Dev 2
- [x] Basic analytics module (per-session aggregations) — per Dev 3's own tracker, unverified by Dev 2
- [x] PostHog events for all assessment actions — per Dev 3's own tracker, unverified by Dev 2

### Dev 4 — Tutor Agent + Attention + Realtime

> **2026-08-10:** Dev 4's own online tracker now shows all 5 lines below as "Done," upgraded from this section's prior "code merged, pending integration/live-network test" caveats. Retaining those caveats alongside the new claim rather than deleting them — a spreadsheet checkbox doesn't itself confirm the live-Redis/live-network integration test happened; unverified by Dev 2.

- [x] Full 7-state LangGraph StateGraph with real logic — per Dev 4's own tracker (2026-08-10); previously "code merged + unit tested (mock Redis), pending integration test against live Redis" — that live-Redis test has not been independently re-confirmed by Dev 2
- [x] All 14 transitions wired and tested — per Dev 4's own tracker (2026-08-10); previously "code merged + 884-line unit test suite, pending integration test" — not independently re-confirmed by Dev 2
- [x] CHECKING IN → QUIZZING → TEACH-BACK → TEACHING flow — per Dev 4's own tracker (2026-08-10); previously "code merged, pending integration test" — not independently re-confirmed by Dev 2
- [x] Session state restore on reconnect tested — per Dev 4's own tracker (2026-08-10); previously "code merged, pending live-network test" — not independently re-confirmed by Dev 2
- [x] Intervention message selection from lesson package — per Dev 4's own tracker (2026-08-10); previously "code merged, pending integration test" — not independently re-confirmed by Dev 2
- [x] WebSocket message types finalized and published — ✓ docs/ws-message-contract.md published. **Needs Dev 2 sign-off.**

---

## Sprint 3 — Weeks 6–7 (MediaPipe + CES + Full Tutor FSM)

> **Prerequisite:** Migrate FastAPI/ARQ from Railway to India-region provider before real students join (Fly.io Mumbai, Render Singapore, or AWS ap-south-1). Dev 1 owns this migration.

### Dev 1 — Infrastructure + Content Pipeline

> **2026-08-24:** all 5 lines below flip from not-started/in-progress to done per Dev 1's own online tracker — a jump from the 2026-08-10 snapshot ("circuit breaker IN PROGRESS", rest not started). **None of the 5 independently re-verified against code by Dev 2** — same unverified-caveat pattern as the Sprint 2/3 Dev 3/Dev 4 entries below. Also note: that same online tracker labels `tts_node`/`image_generator` (Sprint 2, above) as "ElevenLabs + Azure TTS + Browser" and "DALL-E + stock library fallback" — both **stale provider names** contradicting CLAUDE.md's locked stack (ElevenLabs REMOVED; DALL-E 3 DEAD) and this doc's own already-verified Sprint 2 entries (Sarvam Bulbul v2; GPT Image 1 Mini → Imagen 4 Fast). Not a code problem — Dev 1's actual implementation was already confirmed against the real providers above — just a stale label in whatever tool Dev 1's online tracker renders from.

- [x] Eval harness expanded to 20 PDFs — per Dev 1's own tracker (2026-08-24), unverified by Dev 2
- [x] Prompt iteration from eval results (slides + quiz quality) — per Dev 1's own tracker (2026-08-24), unverified by Dev 2
- [x] Circuit breaker implementation (Redis state, 5 failures/2min) — per Dev 1's own tracker (2026-08-24), unverified by Dev 2; previously 🔵 IN PROGRESS (2026-08-10)
- [x] Admin panel: job status, cost tracking, failed jobs — per Dev 1's own tracker (2026-08-24), unverified by Dev 2
- [x] Pipeline cost attribution in Langfuse — per Dev 1's own tracker (2026-08-24), unverified by Dev 2

### Dev 2 — Lesson Player + Frontend
- [x] **MediaPipe Face Landmarker WASM integration** — ✓ 2026-08-10, `AttentionMonitor.tsx` + `useAttentionMonitor.ts`. Story 2-44, 8-layer adversarial review (1 decision resolved: added a CPU delegate fallback; 21 patch findings applied, incl. a real head-pose axis-extraction bug and an AC-1 gating gap, both confirmed via mutation-tested regression tests). Merged into `sprint3-master`. Not yet verified against a real browser/camera end-to-end — blocked on an OpenAI account credit issue preventing a fresh lesson from being generated to test against. See Dev 2 tracker §12 S3-02.
- [x] 5-signal aggregation every 5 seconds (client-side) — part of S3-02 above
- [x] WebSocket attention payload sending (~200 bytes/5s) — part of S3-02 above
- [x] **Consent flow UI (camera permission + privacy notice)** — ✓ 2026-08-06, `AttentionConsentModal.tsx` + `useAttentionConsent.ts`. Writes via Dev 3's real `POST /api/assessment/consent` (Story 3-32), not the originally-assumed `PATCH /api/users/consent`. See Dev 2 tracker §12 S3-01.
- [x] **Tutor intervention card component (Type A/B/C)** — ✓ 2026-08-03, `TutorInterventionCard.tsx`. See Dev 2 tracker §12 S3-03.
- [x] **CES indicator in player (subtle, non-intrusive UI)** — ✓ 2026-08-03, `CESIndicator.tsx`. See Dev 2 tracker §12 S3-04.
- [x] **Notifications UI wired to real backend** — ✓ 2026-08-06/07, `useNotificationPreferences.ts` + `settings.service.ts` + `NotificationsTab.tsx`. Wired to Dev 4's real `PATCH /api/auth/notifications` (Story 4-23) — this line item didn't previously exist in this tracker; added now that it's found done. Storage only, no email-sending pipeline yet (Sprint 4 scope). See Dev 2 tracker §12 S3-07, `docs/DEFECT-REGISTER.md` D60.
- [ ] Session report: attention timeline chart — unblocked 2026-08-10 now that S3-02 shipped. See Dev 2 tracker §12 S3-05.
- [ ] Mobile responsive audit

### Dev 3 — Assessment + Analytics + Learner DNA

> **2026-08-10:** the 4 lines below were independently verified against real code on `origin/main` (not just Dev 3's own tracker claim) after the user flagged suspicion that Sprint 3 backend claims might not be on `main` yet. All 4 confirmed with file:line citations — this is a higher confidence level than the "per their own tracker, unverified" items elsewhere in this doc.

- [x] CES v1 formula implementation (5 weights as env vars) — ✓ CONFIRMED, `apps/api/app/modules/assessment/ces.py:19-87`, exact match to CLAUDE.md §11 including the teachback-`None` redistribution. Weights are real `pydantic-settings` fields in `app/config.py:251-255` (`ces_weight_quiz=0.35`, `ces_weight_teachback=0.25`, `ces_weight_behavioral=0.20`, `ces_weight_head_pose=0.12`, `ces_weight_blink=0.08`), env-var overridable.
- [x] Per-learner baseline computation — ✓ CONFIRMED, `apps/api/app/modules/assessment/ces_baseline.py:50+`, `compute_and_store_ces_baseline()` reads last-N session `ces_final` rows, rolling average, cached at `user:{id}:ces_baseline`.
- [x] Learner DNA fusion formula live — ✓ CONFIRMED, `apps/api/app/modules/assessment/dna_fusion.py:1-50`, real EMA blend (`new = retain*old + (1-retain)*signal`) across all 9 documented dimensions.
- [x] GPT-4o-mini profile text generation — ✓ CONFIRMED, `apps/api/app/modules/assessment/dna_profile.py:4-94`, `generate_dna_profile_text` calls `settings.llm_mini` (no hardcoded model string, per CLAUDE.md's rule).
- [x] Growth tracking (delta per dimension per session) — per Dev 3's own tracker (2026-08-24), unverified by Dev 2 directly, but corroborated: Dev 2 tracker §11 S2-10 (2026-07-23) already consumed "growth indicators" per dimension from Dev 3's Story 3-30 (`learner_dna_snapshot`) — this line should likely have already been checked off weeks earlier.
- [x] Session report: Learner DNA section — per Dev 3's own tracker (2026-08-24), unverified by Dev 2 directly, but corroborated the same way: Dev 2's `SessionReport.tsx` has rendered a "Learner DNA snapshot section (9 dimension labels + growth indicators)" since Story 2-10 (2026-07-23), sourced from Dev 3's Story 3-30 — same stale-checkbox pattern as above.
- [ ] Re-assessment prompt after 10 sessions logic — 🔵 IN PROGRESS per Dev 3's own tracker (2026-08-24). Note: the frontend counterpart (banner + onboarding-flow bypass) already shipped via Dev 2 tracker §11 S2-12 (2026-07-23), built against Dev 3's Story 3-31 (`reassessment_due` field) — unclear whether "logic" here means something beyond Story 3-31, or whether this line is itself stale. Flagging for Dev 3 to clarify rather than guessing.

### Dev 4 — Tutor Agent + Attention + Realtime

> **2026-08-10:** all 8 lines below independently verified against real code on `origin/main` (not just Dev 4's own tracker claim), after the user flagged suspicion that Sprint 3 backend claims might not be on `main` yet. All 8 confirmed with file:line citations. **Notably, the last 2 lines were marked "Not Started" in Dev 4's own pasted online tracker — the actual repo is ahead of what that tracker shows, the opposite direction from the usual staleness pattern in this doc.**

- [x] Attention signal ingestion from WebSocket live — ✓ CONFIRMED, `apps/api/app/core/websocket.py:162-163` routes `attention_signal` → `_handle_attention_signal` → `app/modules/tutor/service.py::process_attention_signal` — not accepted-and-dropped.
- [x] Redis CES buffer (LPUSH/LTRIM/LRANGE) computing every 5s — ✓ CONFIRMED, `service.py:306-312`, real `lpush`/`ltrim`/`lrange` on `session:{id}:ces_history`.
- [x] CES computation in-process (~3–5ms total) — ✓ CONFIRMED, `service.py:296`, `compute_ces(normalized)` called in-process, no external round-trip.
- [x] Intervention trigger: 2 consecutive windows below threshold — ✓ CONFIRMED, `service.py:321-332` — genuinely checks the last 2 buffered values (`recent = history_raw[:2]`, `all(v < settings.ces_threshold for v in recent)`), not just 1.
- [x] 2-minute cooldown enforcement (Redis TTL key) — ✓ CONFIRMED, `state_machine/graph.py:187-189`, `redis.set(cooldown_key, "1", ex=settings.intervention_cooldown_seconds)`.
- [x] Max 3 distraction interventions per session cap — ✓ CONFIRMED, `graph.py:106-126`, `_can_intervene_distraction()` checks a real Redis counter against `settings.max_distraction_per_session`.
- [x] Fatigue intervention: once per session flag — ✓ CONFIRMED (contradicts the online tracker's own "Not Started"), `graph.py:129-134`, `tutor_fatigue_fired` Redis key.
- [x] Type A/B/C intervention routing to correct message — ✓ CONFIRMED (contradicts the online tracker's own "Not Started"), `graph.py:61-65,170-195`, real `distraction | confusion | fatigue` message-selection routing.

---

## Sprint 4 — Weeks 8–9 (Load Test + Calibration + Razorpay + Hardening)

### Dev 1 — Infrastructure + Content Pipeline
- [ ] Load test: 50 concurrent lesson generations
- [ ] All pipeline reliability fixes from test sessions
- [ ] Razorpay Checkout integration (Standard Checkout via Orders API, no custom card UI) — 🔵 PARTIAL: backend built on PR #157 (`create-order`/webhook/`lesson_access`, 6-layer review done, 25 tests green per PR description) but **not merged** — its own CI `API — lint, type-check, test` check is currently FAILING despite an existing approval; do not treat as done until that's green and re-verified. PR itself also names 4 open gaps: no `GET /api/payments/access` endpoint (blocks Dev 2), all lessons still `price_paise = 0` (Razorpay would reject a real charge), beta-allowlist-only access, no rate limiting on payment routes.
- [ ] Rate limiting (slowapi middleware) — PR #159 open, real merge conflict against `main`, not yet resolved by owner
- [ ] RLS security audit on all Supabase tables — PR #160 open, real merge conflict against `main`, not yet resolved by owner
- [ ] Railway backups confirmed + disaster recovery tested
- [ ] On-call runbook written (5 most likely failure scenarios)

### Dev 2 — Lesson Player + Frontend
- [ ] All UI bugs from real student test sessions fixed
- [x] Loading + error + empty states for all flows — ✅ 2026-08-26 (Story 2-50/S4-10, 8-agent review passed, merged into `sprint4-master`)
- [x] Email notifications (lesson ready, session report) — ✅ 2026-08-26 (Story 2-52/S4-12, 8-agent review passed, merged into `sprint4-master`; crosses into `apps/api` under an explicit user-approved exception)
- [ ] Landing page + marketing copy
- [ ] Pricing page
- [ ] Razorpay Checkout integrated into onboarding flow — 🔵 PARTIAL 2026-08-27 (Story 2-53/S4-02): frontend checkout unit (`RazorpayCheckoutButton`/`useRazorpayCheckout`/`payment.service.ts`) built, tested, 8-agent review passed, merged into `main`. Still blocked on backend: PR #157 (`GET /api/payments/access` + real `price_paise` values) is open but not merged (failing CI, see Dev 1's row above) — `checkAccess()` remains a hardcoded mock (D136).
- [x] Accessibility audit (WCAG AA minimum) — ✅ 2026-08-29 (Story 2-55/S4-04, 8-agent review passed, merged into `main`): focus states, contrast, `aria-live` announcements, and keyboard navigation fixed across the quiz/tutor-intervention/teach-back/onboarding UI; alt text confirmed already compliant
- [x] PostHog event instrumentation (feeds the Dev 3 funnel-analysis line below) — ✅ 2026-08-27 (Story 2-54/S4-03, 8-agent review passed, merged into `main`; same-day fast-follow wired `posthog.identify()`/`reset()` so events tie to real accounts) — **still not producing real data**: `NEXT_PUBLIC_POSTHOG_KEY`/`HOST` still not in Vercel's production env (D118, Dev 1 owns, per Dev 3's calibration doc — `POSTHOG_API_KEY` was also never set in Railway, so historical backend events are zero too); Dev 3's funnel analysis (Story 4-7) had to be reconstructed from Supabase tables instead
- [x] Cross-team fix: `attention_signal` sent `0.0` instead of `null` for a genuinely empty MediaPipe measurement window — ✅ 2026-08-29 (merged into `main`), found via Dev 3's CES calibration thread; a real (worst-case) score was being sent instead of the "no data, redistribute weight" signal the backend's `compute_ces` needs

### Dev 3 — Assessment + Analytics + Learner DNA
- [ ] Analyse 20+ real student test session data — still blocked pending a fresh run with all prerequisites now closed (see below); no run has happened yet as of this update
- [ ] CES weight tuning against post-session ground truth quiz scores — blocked on the above
- [ ] Update tuned weights in Railway env vars
- [ ] Learner DNA profile quality review (human review 10 profiles)
- [x] Onboarding question quality audit — ✅ 2026-08-31/09-01 (Story 4-5, merged via PR #166): 7 questions reworded. **Found and fixed mid-review:** the reword silently corrupted Learner DNA scoring on 7 of those questions, because `_compute_dimension_scores` scores by raw array *index* (`selected_index/3*100`), not option content — a reorder-for-clarity pass had scrambled the intended low→high gradient. Fixed with option order restored/corrected + a new CI guard test (`test_onboarding_question_ordering.py`) that fails on any future silent reorder.
- [x] PostHog funnel analysis: where do students drop off? — ✅ (Story 4-7, `docs/sprint4-funnel-analysis.md`) — reconstructed from Supabase tables since PostHog itself never received real events (D118)
- [x] Session dedup guard + CES architecture confirmation — ✅ 2026-08-31 (Story 4-11 / PR #164, ad-hoc, not originally on this checklist): fixed React-StrictMode duplicate session creation (app-level pre-check + DB partial UNIQUE index `sessions_open_unique`); confirmed CES is correctly WS-only with no missing REST endpoint
- [x] D116 — `ces_final` always NULL fix — ✅ 2026-08-31 (Story 4-6, ad-hoc): `complete_session` REST endpoint now dispatches `lesson_complete` over the tutor FSM so `_finalize_session` actually fires from any state, not just after a WS event that was never being sent
- [x] D137 — reassessment was overwriting (not blending) Learner DNA — ✅ 2026-09-01 (Story 4-12 / PR #167, ad-hoc): found in a cross-team review discussion (reassessment fully discarded 10 sessions of real behavioral EMA fusion data on every retake); fixed to blend the fresh self-report into the existing profile via the same `_apply_ema()` session-fusion already uses, and stopped resetting `session_count`
- [x] Learner DNA → CES threshold personalization — ✅ 2026-09-01 (Story 4-13 / PR #168, ad-hoc): closes the "Learner DNA is purely decorative" gap — `compute_personalized_threshold()` now adjusts each student's CES intervention threshold using `frustration_tolerance`/`persistence`/`goal_orientation`, seeded into Redis at session creation, read by `process_attention_signal` in the hot path (O(1), no extra DB query). **Found and fixed mid-review:** the `frustration_tolerance` term's sign was inverted relative to how that field is actually computed in `dna_fusion.py` (would have raised the intervention threshold — more interventions — for students who were behaviorally handling frustration *well*); also found and fixed two masked CI regressions (this PR's own changes broke `ces.py`'s pre-existing `__all__`-shape and no-hardcoded-literal guard tests, hidden inside CI's "advisory, not gating" bucket that doesn't fail the build). Both rounds fixed and independently re-verified against the real CI logs, not just the green checkmark.

### Dev 4 — Tutor Agent + Attention + Realtime
- [ ] Intervention threshold tuning — 🔵 PARTIAL: methodology written, pending ≥20 real sessions of data
- [ ] Review which interventions students responded to vs ignored — 🔵 PARTIAL: blocked on instrumentation + real data
- [ ] Cooldown period tuning from real session data — 🔵 PARTIAL: methodology written, pending session data
- [ ] WebSocket stability testing under 50 concurrent users — 🔵 PARTIAL: harness built + locally validated, production run pending staging
- [ ] Session reconnect testing under poor network conditions — 🔵 PARTIAL: all-7-states Redis restore proven, live network-fault sim pending
- [ ] Intervention message copy review (tone + warmth) — 🔵 PARTIAL: checklist ready, pending 5 real lesson packages

---

## Bug Resolution Sprint (Feature Sprint 2)

Started immediately after Sprint 4, on its own integration branches (e.g. Dev 4's `dev4/master-bug-resolution`) rather than waiting for a full Sprint 4 close-out. Task list as reported by each dev; statuses below are each dev's own self-report, not independently re-verified except where noted.

### Dev 1 — Infrastructure + Content Pipeline
- [ ] Line-level caption timestamps: extend `narration_generator` + `tts_node` to emit start/end time per caption line — High
- [ ] Evaluate + integrate Nano Banana (Gemini 2.5 Flash Image) in `image_generator` fallback chain for slides/diagrams — Medium
- [ ] Inject Learner DNA + behavior signals into `lesson_planner` / `slide_generator` / `narration_generator` system prompts — Medium
- [ ] Human narration pipeline: new node to accept human-recorded audio per segment, store in Supabase, sync duration to slide timing — High
- [ ] Redesign `lesson_planner`/`slide_generator` prompts: plain-language explanations + easy-to-understand diagram prompts — Medium

### Dev 2 — Lesson Player + Frontend
- [ ] CAPTCHA widget on login + signup screens (reCAPTCHA v3 invisible badge) — High
- [ ] Update mode-selection cards to show explicit "15 min / 30 min / 45 min" labels — Low
- [ ] Caption/subtitle display — one dialogue line at a time, synced to narration timestamps — High
- [ ] Highlight/underline the active narration text on slide (karaoke-style sync) using caption timestamps — High — **depends on Dev 1's caption timestamp output**
- [ ] Slide transition: add configurable pause (default 2s) between slides + manual "Next" button for navigation — Medium
- [ ] Voice teach-back: mic capture UI, recording + upload, toggle between typed/voice input — Medium — **depends on an STT node** (as reported to Dev 2; note this reads "Dev 1's STT node" in the source list while Dev 3's own list below describes building the STT node itself and Dev 4's list says "depends on Dev 3's STT node" — flagging this inconsistency rather than silently resolving it; confirm the real owner before starting this task)

### Dev 3 — Assessment + Analytics + Learner DNA
- [ ] Expose Learner DNA + behavior-signal summary via internal API for prompt injection — Medium
- [ ] Teach-back scorer: accept source flag (typed vs voice-transcribed) — no rubric change, just input path — Low
- [ ] Verify Learner Mode tiers already map to 15/30/45 min (T3=15, T2=30, T1=45); relabel internally if needed — Low
- [ ] Voice teach-back: Whisper/OpenAI STT node to transcribe audio submissions, feed transcript into existing scorer — Medium

### Dev 4 — Tutor Agent + Attention + Realtime
- [x] WebSocket: support progressive caption-cue delivery for live narration playback — Medium — **Done** (Story BR-1, PR #162)
- [x] Verify tutor intervention/CES timing still functions correctly with variable-length human-recorded narration — Medium — **Done** (Story BR-2, PR #163)
- [ ] Voice teach-back: real-time mic capture integration in live session flow — Low — depends on Dev 3's STT node
- [ ] Backend CAPTCHA verification (reCAPTCHA v3) on login + signup — reject low trust score before issuing session — High — **In Progress**

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
