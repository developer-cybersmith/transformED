# TransformED AI — Claude Code Project Guide

**PRD version:** 1.0 Final (10 June 2026) + Decisions Update (25 June 2026).
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
| Primary LLM | **OpenAI GPT-4o + GPT-4o-mini** (defaults — see model table) | Per-task allocation below |
| Alt LLM | **Claude Sonnet** (Phase 2 tutor Q&A, evaluation candidate) | |
| TTS | **Sarvam AI Bulbul v2 → Azure TTS → Browser Speech** | Fallback chain. ElevenLabs REMOVED. |
| Avatar | **HeyGen cached intro/outro (~$0/lesson)** | No live HeyGen per lesson |
| Image | **GPT Image 1 Mini → Imagen 4 Fast → text-only** | DALL-E 3 DEAD (shut down May 2026). |
| Embeddings | **text-embedding-3-small** | Chunk content: embed at ingestion only, never regenerate. Phase 2 RAG tutor embeds student questions at query time — this is permitted. |
| OCR | **Tesseract** (in-container) | Azure Doc Intelligence removed |
| PDF | **PyMuPDF + pdfplumber** | |
| Attention | **MediaPipe Face Landmarker WASM** | WebGazer REJECTED |
| Lesson player | **Custom React audio-timeline state machine** | Reveal.js REJECTED |
| Realtime | **Native FastAPI WebSockets** | |
| Observability | **Langfuse + Sentry + OTel + PostHog** | Wire before feature work |
| Deploy | **Railway + GitHub Actions** | railway.toml |

## Per-Task Model Allocation

> **Model evaluation sprint: Sprint 1, Week 1.** Defaults below are conservative and confirmed working. Final model IDs locked before Sprint 2. **Never hardcode model strings** — always use `settings.llm_*` aliases from `config.py`. Swapping models is an env var change only.

| Task | Default (env var) | Evaluation candidates |
|------|-------------------|-----------------------|
| Lesson planning | `gpt-4o` (`LLM_LESSON_PLANNER`) | GPT-4o, Claude 3.5 Sonnet, o1-mini |
| Slide generation | `gpt-4o` (`LLM_SLIDE_GENERATOR`) | Same as above |
| Quiz, scoring, complexity, narration, jargon, interventions, Learner DNA | `gpt-4o-mini` (`LLM_MINI`) | GPT-4o-mini, Gemini 2.0 Flash |
| Tutor Q&A (Phase 2) | `gpt-4o` (`LLM_TUTOR`) | GPT-4o, Claude 3.5 Sonnet |

**Batch API rule:** Never use OpenAI or Google Batch API for pipeline nodes. Batch API has a 24-hour completion window — incompatible with real-time generation. All pipeline LLM calls use the synchronous (real-time) API endpoint.

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
2. **Process once, reuse everywhere** — chunk embeddings generated at ingestion, never regenerated for stored content. Phase 2 RAG tutor embeds the student's question at query time — this is intentional and required.
3. **Modular monolith** — one FastAPI deploy; module names match future microservice names
4. **One discipline rule** — modules communicate only through service layer, never via direct DB access into another module's tables. Violating PRs are rejected.
5. **Provider abstraction everywhere** — no direct provider client calls in business logic
6. **Hierarchical document processing** — process Chapter → Section → Topic. Never full-book single call.
7. **Observability from commit one** — Langfuse + Sentry + OTel + PostHog wired before feature work

## Content Generation Pipeline (§9)

**Phase A — Book Ingestion** (once per book, ~2–5 min):
```
upload → store_pdf → extract_text → structure_detect → chunk → embed
```

**Phase B — Chapter Generation** (per chapter, student-triggered, ~5–15 min):

*Phase 1 — Economy nodes (all run in parallel, `settings.llm_mini`):*
```
summarise_segment × N   ← ALL must finish before Phase 2 starts
quiz_generator    × N
segment_complexity× N
jargon_extractor  × N
intervention_msgs × N
narration_script  × N
```

*Phase 2 — Premium nodes (sequential, start only after ALL Phase 1 segments complete):*
```
lesson_planner   ← input: segment summaries from Phase 1, NOT raw chapter text (5× token savings)
slide_generator  ← input: lesson outline from lesson_planner
```

*Phase 3 — Media nodes:*
```
tts_node         ← narration scripts → .mp3 per segment
image_generator  ← slide content → images
package_builder  ← assembles final JSONB lesson package
```

Checkpoint pattern: after each node, write `last_node` + `node_outputs` to `lesson_jobs`. On ARQ retry: read `last_node`, skip completed nodes. Never re-run completed LLM calls.

**Critical constraint:** `lesson_planner` receives segment summaries, not raw chapter text. Phase 1 must fully complete before Phase 2 starts. Violating this silently causes a 5× cost overrun.

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

When `teachback_score` is `None` (teach-back skipped — never gated, always allow Skip):
```
CES = quiz_accuracy×0.467 + behavioral×0.267 + head_pose×0.160 + blink×0.107
```
(Redistribute 0.25 weight proportionally across remaining 4 signals: each new weight = original ÷ 0.75)

## Failure Modes (§14)

- Exponential backoff: `wait = (2^attempt) + random(0,1)` — 3 attempts critical, 2 optional
- Retry on: 429, 500, 502, 503, 504. Never retry: 400, 401
- Circuit breaker: 5 failures/2min → open; 10min → half-open probe (state in Redis)
- Cost ceiling: $3.00/lesson — downshift to cheapest providers on breach, complete lesson, flag in admin
- TTS fallback chain: Sarvam Bulbul v2 → Azure TTS → Browser Speech — NEVER hard-fails

## Interface Contracts (frozen Week 1, §16)

Four contracts are frozen — changes require PR reviewed by all 4 developers:
1. `packages/shared/lesson_package.schema.json` + `packages/shared/types/lesson.ts`
2. `packages/shared/types/ws.ts` — WebSocket discriminated union
3. Assessment API (OpenAPI auto-generated from FastAPI)
4. `supabase/migrations/` — never modify applied migrations

Applied and frozen migrations (do not alter):
- `20260611000000_initial_schema.sql` — initial schema
- `20260625000000_chunks_inline_embedding.sql` — books table, inline embedding in chunks, lessons.book_id (applied 2026-06-25)

## Security (§18)

- JWT verified locally (PyJWT + SUPABASE_JWT_SECRET) — never remote call per request
- RLS on ALL Supabase tables — users read only their own data
- Raw webcam video NEVER leaves browser — only 5 derived numbers sent
- Attention capture requires explicit consent (modal + users.attention_consent flag)
- DPDP Act 2023 compliance — Learner DNA disclaimer required, no clinical claims
- **DPDP consent gap:** `users.attention_consent` boolean is insufficient — a `user_consents` audit table (columns: user_id, consent_type, policy_version, consented_at) is required before any attention data is collected. Sprint 2 priority.
- PDF security: parse user-uploaded PDFs in an isolated subprocess — calling `fitz.open()` directly in the main FastAPI process is a security risk with untrusted files
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
- Chunk embeddings at ingestion only — never regenerate stored chunk embeddings. Phase 2 RAG tutor query-embedding IS allowed (embed the student question at query time).
- API deployed on Railway (no India region) — must migrate FastAPI/ARQ to India-region provider before Sprint 3 real-student launch (Fly.io Mumbai, Render Singapore, or AWS ap-south-1)

## BMAD Pre-Implementation Checklist (Story-First Gate)

Before writing ANY code for a new story, complete ALL of the following in order — no exceptions:

1. **Create the story file** at `docs/stories/{N}-{M}-{story-slug}.md` with all ACs fully defined
2. **Commit ONLY the story file**: `git commit -m "docs(story-first): Story N-M — {title}"`
3. **Push the story-only commit** to remote: `git push origin <branch-name>`
4. **Verify** the story commit is the chronologically first commit on the branch
5. **Only then** begin the RED phase (write failing tests)

**NEVER** write implementation code in the same commit as the story file.
**NEVER** merge a PR where story and implementation share a commit.

## BMAD Code Review Gate (5-Agent Requirement)

Every PR requires a 5-agent adversarial code review via `/bmad-code-review` before merge.

The 5 required agent layers are:
1. **Story Quality** — all ACs testable, story complete before code
2. **Blind Hunter (Security)** — IDOR, injection, enumeration, DoS vectors
3. **Test Coverage** — every AC has a test, edge cases covered, no false confidence
4. **AC Completeness** — every AC maps to at least one explicit test assertion
5. **Process Integrity** — no LLM calls in wrong modules, no hardcoded models, no rule violations

**REJECT** any PR whose Senior Developer Review section lists fewer than 5 agent layers.
The Story Quality agent is the most critical — it catches missing ACs before they reach main.

## Build Roadmap (10 weeks, §22)

- **Week 1 (Sprint 0):** Infra setup + shared contracts frozen (THIS SPRINT)
- **Weeks 2–3 (Sprint 1):** Core pipeline + player skeleton
- **Weeks 4–5 (Sprint 2):** Full 11-node pipeline + integration → investor demo ready
- **Weeks 6–7 (Sprint 3):** MediaPipe + CES + full tutor state machine — **prerequisite:** migrate FastAPI/ARQ from Railway to India-region provider before real students join
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

## Sprint Tracker Auto-Update Rule

The Dev 4 tracker is `docs/dev4-tracker.md`. It uses three-state labels — `[Not Started]` / `[Partial]` / `[Completed]` — one per task, each tagged with a `<!-- CHECK:tag -->` marker, and is auto-maintained by `scripts/check_dev4_progress.py` (flips `[Not Started]`↔`[Completed]` by code presence; never downgrades a human-set `[Partial]`).

Whenever you finish implementing a task, or the user confirms one is done — either way, in the same response — you MUST:

1. Set the task's label to `[Completed]` and append ` ✅ YYYY-MM-DD (short note)` to the task title line. Use `[Partial]` (with a `⚠️ PARTIAL — <reason>` note) when the code exists but is untested, unmerged, or blocked on an external dependency.
2. Update the **Quick Status Dashboard** table at the top of the file (adjust Completed / Partial / Not Started on the correct sprint row, and update the **Total** row so the columns still sum to 39).
3. Update **Last updated** and **Overall status** in the header to today's date and the new counts.
4. Prefer running `python scripts/check_dev4_progress.py` to auto-apply label changes and print the authoritative per-sprint counts — then reconcile the dashboard/header to match its output. The script updates labels only, not the dashboard table.

Do this without being asked. Never mark a task complete without also updating the dashboard. Never update the dashboard without also updating the header date. Keep the dashboard totals consistent with the script's reported counts.

## Sprint Task Branch Rule

**Apply automatically — do not wait to be asked.**

When you begin implementing any sprint task from `docs/dev4-tracker.md`, the very first action before any file edit must be to create a dedicated git branch.

### Branch naming

| Pattern | Example |
|---------|---------|
| `sprint{N}/s{N}-{M}-{slug}` | `sprint1/s1-2-pymupdf-extract` |
| `week10/w10-{M}-{slug}` | `week10/w10-1-prod-deploy` |

- `N` = sprint number (0–4)
- `M` = task number within the sprint
- `slug` = 2–4 word lowercase hyphenated summary of the task title (not the full title — just enough to identify it at a glance)

Examples:
- S1-2 "PyMuPDF text + image + layout extraction node" → `sprint1/s1-2-pymupdf-extract`
- S1-7 "Semantic chunking" → `sprint1/s1-7-semantic-chunking`
- S2-7 "`lesson_planner` node" → `sprint2/s2-7-lesson-planner`
- S0-9 "Langfuse wired globally" → `sprint0/s0-9-langfuse-global`

### Steps (execute in this order, no exceptions)

1. If there are uncommitted changes from a previous task, commit them to the current branch first.
2. Run: `git checkout main && git checkout -b <branch-name>`
   - If the branch already exists (resumed session): `git checkout <branch-name>` instead.
3. Announce the branch in the first line of your response — e.g., `Branch: sprint1/s1-2-pymupdf-extract created.`
4. Then begin implementation.

### One task, one branch

Every task gets its own branch based on `main`. Never stack a new task on top of the previous task's branch. When a task is marked complete and the next task begins, the next branch is created fresh from `main` at the start of implementation — again, without being asked.
