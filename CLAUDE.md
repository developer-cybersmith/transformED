# TransformED AI — Claude Code Project Guide

**PRD version:** 1.0 Final (10 June 2026) — this is the single source of truth.
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
| AI orchestration | **LangGraph** (pin exact version — never auto-upgrade) | |
| LangGraph checkpointing | **Custom lesson_jobs table + MemorySaver** | PostgresSaver BANNED |
| Primary LLM | **OpenAI GPT-4o + GPT-4o-mini** | Per-task allocation below |
| Alt LLM | **Claude Sonnet** (Phase 2 tutor Q&A only) | |
| TTS | **ElevenLabs → Azure TTS → Browser Speech** | Fallback chain |
| Avatar | **HeyGen cached intro/outro (~$0/lesson)** | No live HeyGen per lesson |
| Image | **DALL-E 3 → stock library → text-only** | Fallback chain |
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
transformED-corp/
├── apps/
│   ├── api/                    # FastAPI modular monolith
│   │   └── app/
│   │       ├── main.py         # App factory
│   │       ├── config.py       # pydantic-settings (all env vars)
│   │       ├── dependencies.py # JWT verify, redis, settings deps
│   │       ├── modules/        # auth | content | media | assessment | analytics | tutor | admin
│   │       │   └── content/
│   │       │       └── pipeline/
│   │       │           └── nodes/  # 11 LangGraph nodes
│   │       ├── providers/      # LLM | TTS | Image | Avatar (abstract interfaces)
│   │       ├── core/           # db | redis | retry | circuit_breaker | cost_tracker | websocket
│   │       └── workers/        # ARQ entry + content_pipeline job
│   └── web/                    # Next.js 14 App Router
│       └── src/
│           ├── app/            # Routes: (auth)/ | (app)/dashboard | /lesson/[id] | /upload
│           ├── features/       # player | attention | quiz | teachback | tutor | onboarding
│           ├── lib/            # supabase | websocket | api clients
│           └── components/ui/
├── packages/
│   └── shared/                 # FROZEN Week 1 — unblocks all 4 devs
│       ├── types/lesson.ts     # LessonPackage TS types
│       ├── types/ws.ts         # WebSocket discriminated union
│       └── lesson_package.schema.json
├── supabase/
│   └── migrations/             # Never modify applied migrations
└── .github/workflows/          # CI (lint+test) + deploy to Railway
```

## Core Architectural Principles (from PRD §5)

1. **Lesson generation ≠ RAG** — source chapter is known; no retrieval needed for generation
2. **Process once, reuse everywhere** — embeddings generated at ingestion, never at query time
3. **Modular monolith** — one FastAPI deploy; module names match future microservice names
4. **One discipline rule** — modules communicate only through service layer, never via direct DB access into another module's tables. Violating PRs are rejected.
5. **Provider abstraction everywhere** — no direct provider client calls in business logic
6. **Hierarchical document processing** — process Chapter → Section → Topic. Never full-book single call.
7. **Observability from commit one** — Langfuse + Sentry + OTel + PostHog wired before feature work

## Content Generation Pipeline (11 nodes, §9)

```
extract → structure → chunk → embed  (ingestion)
→ lesson_planner → slide_generator → summarise_segment → quiz_generator
→ segment_complexity → jargon_extractor → intervention_messages
→ narration_generator → tts_node → image_generator → package_builder
```

Checkpoint pattern: after each node, write `last_node` + `node_outputs` to `lesson_jobs`. On ARQ retry: read `last_node`, skip completed nodes. Never re-run completed LLM calls.

## Tutor State Machine (7 states, §10)

States: IDLE → TEACHING → INTERVENING / CHECKING_IN → QUIZZING → TEACH_BACK → SESSION_END

Guard rules (MUST be enforced):
- CES monitoring ONLY active in TEACHING state
- 2-minute cooldown after any intervention (Redis TTL key)
- Max 3 distraction interventions per session
- Fatigue fires ONCE per session (Redis flag)
- NEVER interrupt mid-TEACH_BACK

Intervention messages are PRE-GENERATED at lesson build time (node 7). No GPT call at intervention time.

## CES Formula (§11 — weights are env vars, tunable post-calibration)

```
CES = quiz_accuracy×0.35 + teachback_score×0.25 + behavioral×0.20 + head_pose×0.12 + blink×0.08
```
Trigger: CES < 50 for 2 consecutive 5s windows → intervention.

## Failure Modes (§14)

- Exponential backoff: `wait = (2^attempt) + random(0,1)` — 3 attempts critical, 2 optional
- Retry on: 429, 500, 502, 503, 504. Never retry: 400, 401
- Circuit breaker: 5 failures/2min → open; 10min → half-open probe (state in Redis)
- Cost ceiling: $3.00/lesson — downshift to cheapest providers on breach, complete lesson, flag in admin
- TTS fallback chain: ElevenLabs → Azure TTS → Browser Speech — NEVER hard-fails

## Interface Contracts (frozen Week 1, §16)

Four contracts are frozen — changes require PR reviewed by all 4 developers:
1. `packages/shared/lesson_package.schema.json` + `packages/shared/types/lesson.ts`
2. `packages/shared/types/ws.ts` — WebSocket discriminated union
3. Assessment API (OpenAPI auto-generated from FastAPI)
4. `supabase/migrations/` — never modify applied migrations

## Security (§18)

- JWT verified locally (PyJWT + SUPABASE_JWT_SECRET) — never remote call per request
- RLS on ALL Supabase tables — users read only their own data
- Raw webcam video NEVER leaves browser — only 5 derived numbers sent
- Attention capture requires explicit consent (modal + users.attention_consent flag)
- DPDP Act 2023 compliance — Learner DNA disclaimer required, no clinical claims
- Kimi/Qwen deferred — China-hosted data residency risk

## Development Rules

- No Celery — ARQ only
- No PostgresSaver — custom lesson_jobs + MemorySaver
- No direct provider calls in business logic — go through providers/
- Pin LangGraph version — never auto-upgrade
- No raw IQ/EQ/SQ claims — branded as "Learner DNA"
- No clinical scores shown to students — descriptive profile only
- Never gate lesson progress on teach-back score in MVP
- No teach-back timer — creates test anxiety
- No STT in MVP — typed teach-back only
- Embeddings at ingestion only — never at query time

## Build Roadmap (10 weeks, §22)

- **Week 1 (Sprint 0):** Infra setup + shared contracts frozen (THIS SPRINT)
- **Weeks 2–3 (Sprint 1):** Core pipeline + player skeleton
- **Weeks 4–5 (Sprint 2):** Full 11-node pipeline + integration → investor demo ready
- **Weeks 6–7 (Sprint 3):** MediaPipe + CES + full tutor state machine
- **Weeks 8–9 (Sprint 4):** Load test + calibration + Stripe + hardening
- **Week 10:** Launch — first paying student

## Team Ownership (§21)

| Dev | Owns |
|-----|------|
| Dev 1 | Infra, content pipeline, all 11 nodes, embeddings, provider abstraction, Langfuse |
| Dev 2 | Next.js, custom player, MediaPipe, quiz/teachback UI, dashboard, WebSocket client |
| Dev 3 | Quiz API, teachback scorer, CES formula, Learner DNA, session reports, analytics |
| Dev 4 | WebSocket handlers, JWT middleware, 7-state tutor, Redis buffer, interventions |

Anti-deadlock: after Week 1 schema freeze, each dev mocks the other's interface.
