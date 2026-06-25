# HIE AI â€” Claude Code Project Guide

**PRD version:** 1.0 Final (10 June 2026) â€” this is the single source of truth.
**Goal:** First paying student completes a full session by end of Week 10.

---

## Locked Technology Stack

| Layer | Choice | Hard constraint |
|-------|--------|-----------------|
| Backend | **FastAPI** (Python 3.12) | Modular monolith |
| Job queue | **ARQ** | Celery is BANNED |
| Frontend | **Next.js 14 + TypeScript + Tailwind** | App Router |
| DB | **Supabase Postgres + pgvector + JSONB** | |
| Storage | **Supabase Storage** | S3-compatible + CDN |
| Auth | **Supabase Auth + PyJWT local verify** | No remote auth call per request |
| Cache/Queue/PubSub | **Railway Redis** | |
| AI orchestration | **LangGraph** (pin exact version â€” never auto-upgrade) | |
| LangGraph checkpointing | **Custom lesson_jobs table + MemorySaver** | PostgresSaver BANNED |
| Primary LLM | **OpenAI GPT-4o + GPT-4o-mini** | Per-task allocation below |
| Alt LLM | **Claude Sonnet** (Phase 2 tutor Q&A only) | |
| TTS | **ElevenLabs â†’ Azure TTS â†’ Browser Speech** | Fallback chain |
| Avatar | **HeyGen cached intro/outro (~$0/lesson)** | No live HeyGen per lesson |
| Image | **DALL-E 3 â†’ stock library â†’ text-only** | Fallback chain |
| Embeddings | **text-embedding-3-small** (at ingestion, never at query time) | |
| OCR | **Tesseract** (in-container) | Azure Doc Intelligence removed |
| PDF | **PyMuPDF + pdfplumber** | |
| Attention | **MediaPipe Face Landmarker WASM** | WebGazer REJECTED |
| Lesson player | **Custom React audio-timeline state machine** | Reveal.js REJECTED |
| Realtime | **Native FastAPI WebSockets** | |
| Observability | **Langfuse + Sentry + OTel + PostHog** | Wire before feature work |
| Deploy | **Railway + GitHub Actions** | railway.toml |

## Per-Task Model Allocation

| Task | Model |
|------|-------|
| Lesson planning, slide generation | GPT-4o |
| Quiz, scoring, complexity, narration, jargon, interventions, Learner DNA | GPT-4o-mini |
| Tutor Q&A (Phase 2) | GPT-4o or Claude Sonnet |

## Repo Structure

```
hie/
â”œâ”€â”€ apps/
â”‚   â”œâ”€â”€ api/                    # FastAPI modular monolith
â”‚   â”‚   â””â”€â”€ app/
â”‚   â”‚       â”œâ”€â”€ main.py         # App factory
â”‚   â”‚       â”œâ”€â”€ config.py       # pydantic-settings (all env vars)
â”‚   â”‚       â”œâ”€â”€ dependencies.py # JWT verify, redis, settings deps
â”‚   â”‚       â”œâ”€â”€ modules/        # auth | content | media | assessment | analytics | tutor | admin
â”‚   â”‚       â”‚   â””â”€â”€ content/
â”‚   â”‚       â”‚       â””â”€â”€ pipeline/
â”‚   â”‚       â”‚           â””â”€â”€ nodes/  # 11 LangGraph nodes
â”‚   â”‚       â”œâ”€â”€ providers/      # LLM | TTS | Image | Avatar (abstract interfaces)
â”‚   â”‚       â”œâ”€â”€ core/           # db | redis | retry | circuit_breaker | cost_tracker | websocket
â”‚   â”‚       â””â”€â”€ workers/        # ARQ entry + content_pipeline job
â”‚   â””â”€â”€ web/                    # Next.js 14 App Router
â”‚       â””â”€â”€ src/
â”‚           â”œâ”€â”€ app/            # Routes: (auth)/ | (app)/dashboard | /lesson/[id] | /upload
â”‚           â”œâ”€â”€ features/       # player | attention | quiz | teachback | tutor | onboarding
â”‚           â”œâ”€â”€ lib/            # supabase | websocket | api clients
â”‚           â””â”€â”€ components/ui/
â”œâ”€â”€ packages/
â”‚   â””â”€â”€ shared/                 # FROZEN Week 1 â€” unblocks all 4 devs
â”‚       â”œâ”€â”€ types/lesson.ts     # LessonPackage TS types
â”‚       â”œâ”€â”€ types/ws.ts         # WebSocket discriminated union
â”‚       â””â”€â”€ lesson_package.schema.json
â”œâ”€â”€ supabase/
â”‚   â””â”€â”€ migrations/             # Never modify applied migrations
â””â”€â”€ .github/workflows/          # CI (lint+test) + deploy to Railway
```

## Core Architectural Principles (from PRD Â§5)

1. **Lesson generation â‰  RAG** â€” source chapter is known; no retrieval needed for generation
2. **Process once, reuse everywhere** â€” embeddings generated at ingestion, never at query time
3. **Modular monolith** â€” one FastAPI deploy; module names match future microservice names
4. **One discipline rule** â€” modules communicate only through service layer, never via direct DB access into another module's tables. Violating PRs are rejected.
5. **Provider abstraction everywhere** â€” no direct provider client calls in business logic
6. **Hierarchical document processing** â€” process Chapter â†’ Section â†’ Topic. Never full-book single call.
7. **Observability from commit one** â€” Langfuse + Sentry + OTel + PostHog wired before feature work

## Content Generation Pipeline (11 nodes, Â§9)

```
extract â†’ structure â†’ chunk â†’ embed  (ingestion)
â†’ lesson_planner â†’ slide_generator â†’ summarise_segment â†’ quiz_generator
â†’ segment_complexity â†’ jargon_extractor â†’ intervention_messages
â†’ narration_generator â†’ tts_node â†’ image_generator â†’ package_builder
```

Checkpoint pattern: after each node, write `last_node` + `node_outputs` to `lesson_jobs`. On ARQ retry: read `last_node`, skip completed nodes. Never re-run completed LLM calls.

## Tutor State Machine (7 states, Â§10)

States: IDLE â†’ TEACHING â†’ INTERVENING / CHECKING_IN â†’ QUIZZING â†’ TEACH_BACK â†’ SESSION_END

Guard rules (MUST be enforced):
- CES monitoring ONLY active in TEACHING state
- 2-minute cooldown after any intervention (Redis TTL key)
- Max 3 distraction interventions per session
- Fatigue fires ONCE per session (Redis flag)
- NEVER interrupt mid-TEACH_BACK

Intervention messages are PRE-GENERATED at lesson build time (node 7). No GPT call at intervention time.

## CES Formula (Â§11 â€” weights are env vars, tunable post-calibration)

```
CES = quiz_accuracyÃ—0.35 + teachback_scoreÃ—0.25 + behavioralÃ—0.20 + head_poseÃ—0.12 + blinkÃ—0.08
```
Trigger: CES < 50 for 2 consecutive 5s windows â†’ intervention.

## Failure Modes (Â§14)

- Exponential backoff: `wait = (2^attempt) + random(0,1)` â€” 3 attempts critical, 2 optional
- Retry on: 429, 500, 502, 503, 504. Never retry: 400, 401
- Circuit breaker: 5 failures/2min â†’ open; 10min â†’ half-open probe (state in Redis)
- Cost ceiling: $3.00/lesson â€” downshift to cheapest providers on breach, complete lesson, flag in admin
- TTS fallback chain: ElevenLabs â†’ Azure TTS â†’ Browser Speech â€” NEVER hard-fails

## Interface Contracts (frozen Week 1, Â§16)

Four contracts are frozen â€” changes require PR reviewed by all 4 developers:
1. `packages/shared/lesson_package.schema.json` + `packages/shared/types/lesson.ts`
2. `packages/shared/types/ws.ts` â€” WebSocket discriminated union
3. Assessment API (OpenAPI auto-generated from FastAPI)
4. `supabase/migrations/` â€” never modify applied migrations

## Security (Â§18)

- JWT verified locally (PyJWT + SUPABASE_JWT_SECRET) â€” never remote call per request
- RLS on ALL Supabase tables â€” users read only their own data
- Raw webcam video NEVER leaves browser â€” only 5 derived numbers sent
- Attention capture requires explicit consent (modal + users.attention_consent flag)
- DPDP Act 2023 compliance â€” Learner DNA disclaimer required, no clinical claims
- Kimi/Qwen deferred â€” China-hosted data residency risk

## Sprint Tracker Rule

After completing any Dev 2 frontend task — regardless of size — update `docs/dev2-sprint-tracker.md` before the conversation ends:

1. Change the task's status badge from `🔲 NOT STARTED` to `✅ DONE`
2. Update the Quick Status Dashboard table: increment the **Done** count, decrement **Not Started** for that sprint row
3. Update the sprint card's progress bar width percentage (`style=”width:X%”`) in the HTML artifact if re-published
4. If a task is partially done (files created but acceptance criteria not fully met), mark `🔵 IN PROGRESS` and note what remains inline

This rule applies to all work done in this repository on behalf of Developer 2. Do not wait to be asked — the update is part of the definition of done.

## Development Rules

- No Celery â€” ARQ only
- No PostgresSaver â€” custom lesson_jobs + MemorySaver
- No direct provider calls in business logic â€” go through providers/
- Pin LangGraph version â€” never auto-upgrade
- No raw IQ/EQ/SQ claims â€” branded as "Learner DNA"
- No clinical scores shown to students â€” descriptive profile only
- Never gate lesson progress on teach-back score in MVP
- No teach-back timer â€” creates test anxiety
- No STT in MVP â€” typed teach-back only
- Embeddings at ingestion only â€” never at query time

## Build Roadmap (10 weeks, Â§22)

- **Week 1 (Sprint 0):** Infra setup + shared contracts frozen (THIS SPRINT)
- **Weeks 2â€“3 (Sprint 1):** Core pipeline + player skeleton
- **Weeks 4â€“5 (Sprint 2):** Full 11-node pipeline + integration â†’ investor demo ready
- **Weeks 6â€“7 (Sprint 3):** MediaPipe + CES + full tutor state machine
- **Weeks 8â€“9 (Sprint 4):** Load test + calibration + Stripe + hardening
- **Week 10:** Launch â€” first paying student

## Team Ownership (Â§21)

| Dev | Owns |
|-----|------|
| Dev 1 | Infra, content pipeline, all 11 nodes, embeddings, provider abstraction, Langfuse |
| Dev 2 | Next.js, custom player, MediaPipe, quiz/teachback UI, dashboard, WebSocket client |
| Dev 3 | Quiz API, teachback scorer, CES formula, Learner DNA, session reports, analytics |
| Dev 4 | WebSocket handlers, JWT middleware, 7-state tutor, Redis buffer, interventions |

Anti-deadlock: after Week 1 schema freeze, each dev mocks the other's interface.

