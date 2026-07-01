# HIE — Master Project Tracker
**Last updated:** 2026-06-30 (Dev 1 Sprint 1 API status synced from direct reply)

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
- [x] POST /api/content/lessons — ✓ live, 14/14 tests pass (Dev 2 was using wrong path /api/pipeline/submit)
- [x] GET /api/content/lessons — ✓ live, paginated (?limit=20&offset=0), returns status/title/created_at
- [x] GET /api/content/lessons/{lesson_id} — ✓ live, returns status only (not lesson package content)
- [ ] GET /api/content/lessons/{lesson_id}/package — ⬜ NOT BUILT — Dev 1 needs to expose lessons.content JSONB (~30 min). **Blocks Dev 2 real player wiring.**

### Dev 2 — Lesson Player + Frontend
- [x] Custom React audio-timeline state machine — ✓ done
- [x] Slide renderer from lesson package JSONB — ✓ done
- [x] Audio playback + timestamp-driven slide advance — ✓ done
- [ ] Avatar intro/outro video component (HeyGen cached) — ⛔ BLOCKED: avatar_intro/outro/static_url not in frozen schema; needs all-4-dev sign-off + Sprint 2 avatar node. Deferred to Sprint 2.
- [x] Jargon hover tooltip component — ✓ done
- [ ] Lesson load from Supabase Storage signed URLs — 🔵 IN PROGRESS: service layer ready, blocked on GET /api/content/lessons/{id}/package (Dev 1, ~30 min)
- [x] PDF upload UI + generation progress indicator — ✓ done
- [ ] Wire upload to POST /api/content/lessons — ⬜ ready to wire (URL correction only, endpoint is live)
- [ ] Wire library/dashboard to GET /api/content/lessons — ⬜ ready to wire (URL correction only, endpoint is live)
- [ ] GET /api/sessions/latest for continue-learning card — ⛔ BLOCKED: endpoint doesn't exist, Dev 4 owns (session state in Redis). Escalate.

### Dev 3 — Assessment + Analytics + Learner DNA
- [ ] POST /api/assessment/quiz endpoint live — 🔵 IN PROGRESS
- [ ] MCQ scoring + response time capture
- [ ] POST /api/assessment/teachback live
- [ ] GPT-4o-mini rubric scoring (accuracy/completeness/clarity)
- [ ] Praise + correction feedback response format
- [ ] quiz_attempts + teachback_attempts DB writes working

### Dev 4 — Tutor Agent + Attention + Realtime
- [x] JWT middleware live and tested on all routes — merge conflicts resolved
- [ ] WebSocket connection + message type routing — 🔵 IN PROGRESS (target: 2026-06-29 EOD)
- [ ] Lesson progress push (ARQ pub/sub → WebSocket)
- [ ] Redis signal buffer operational
- [ ] IDLE → TEACHING state transition live
- [x] Session state init on lesson start
- [x] Session state Redis persistence (24h TTL)

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
- [ ] Quiz popup integration (Dev 3 API)
- [ ] Teach-back modal integration (Dev 3 API)
- [ ] Segment-end detection → CHECKING IN state
- [ ] Feedback display (praise + correction sentences)
- [ ] Session report page v1 (quiz + teach-back scores)
- [ ] Onboarding assessment UI (20 questions flow)
- [ ] Learner DNA profile display component

### Dev 3 — Assessment + Analytics + Learner DNA
- [ ] Onboarding assessment scoring logic complete
- [ ] learner_dna table initial writes (9 sub-dimensions)
- [ ] Session report generation API live
- [ ] Jargon hover usage event tracking
- [ ] Session events instrumentation (tab_switch, retry_after_fail, etc.)
- [ ] Basic analytics module (per-session aggregations)
- [ ] PostHog events for all assessment actions

### Dev 4 — Tutor Agent + Attention + Realtime
- [ ] Full 7-state LangGraph StateGraph with real logic
- [ ] All 14 transitions wired and tested
- [ ] CHECKING IN → QUIZZING → TEACH-BACK → TEACHING flow
- [ ] Session state restore on reconnect tested
- [ ] Intervention message selection from lesson package
- [ ] WebSocket message types finalized and published

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
- [ ] Attention signal ingestion from WebSocket live
- [ ] Redis CES buffer (LPUSH/LTRIM/LRANGE) computing every 5s
- [ ] CES computation in-process (~3–5ms total)
- [ ] Intervention trigger: 2 consecutive windows below threshold
- [ ] 2-minute cooldown enforcement (Redis TTL key)
- [ ] Max 3 distraction interventions per session cap
- [ ] Fatigue intervention: once per session flag
- [ ] Type A/B/C intervention routing to correct message

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
- [ ] Intervention threshold tuning (is CES < 50 right?)
- [ ] Review which interventions students responded to vs ignored
- [ ] Cooldown period tuning from real session data
- [ ] WebSocket stability testing under 50 concurrent users
- [ ] Session reconnect testing under poor network conditions
- [ ] Intervention message copy review (tone + warmth)

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
POST /api/content/lessons (upload)                   → Dev 1 ✅ live
GET /api/content/lessons (library list)              → Dev 1 ✅ live
GET /api/content/lessons/{id} (status)               → Dev 1 ✅ live
GET /api/content/lessons/{id}/package (full JSONB)   → Dev 1 ⬜ ~30 min to add
Supabase Storage signed URLs                         → Dev 1
avatar_intro/outro/static_url in lesson package      → All 4 devs (schema change) — Sprint 2
POST /api/assessment/quiz                            → Dev 3
POST /api/assessment/teachback                       → Dev 3
GET /api/session/:id/report                          → Dev 3
POST /api/onboarding/dna                             → Dev 3
GET /api/sessions/latest (continue-learning card)    → Dev 4 ❌ not built, needs new endpoint
WebSocket /ws/:session_id                            → Dev 4
tutor_intervene / ces_update / state_change WS msgs  → Dev 4
JWT middleware / auth errors                         → Dev 4
```
