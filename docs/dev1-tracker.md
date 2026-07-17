# Dev 1 Sprint Tracker — TransformED AI

**Owner:** Dev 1 (developer1-cybersmith) — developer.team2@cybersmithsecure.com
**Domain:** Infra · Content Pipeline (11 nodes) · Provider Abstraction · Embeddings · Langfuse
**PRD:** 1.0 Final (10 June 2026) + Decisions Update (25 June 2026) — `CLAUDE.md` is source of truth
**Last updated:** 2026-07-17
**Sprint 0 status:** 12/12 COMPLETE ✅
**Sprint 1 status:** 10/10 COMPLETE ✅ — merged to `main` 2026-07-13 (PR #72). Includes Tier-1/Tier-2 hardening plus Story 2-0b (page-scoped docling + extraction performance). Sprint 2 (11 lesson-generation nodes) — see Sprint 2 section below. `package_builder` (S2-11) and the `lesson_ready` WebSocket push (S2-12) have both landed (2026-07-16) — the pipeline produces real, schema-validated `LessonPackage` JSONB and correctly notifies clients over WebSocket. Frontend/assessment/tutor teams can start migrating off `apps/web/src/mocks/data/lessonPackage.ts` for integration testing.

---

## Quick Status Dashboard

> Update this table each time a task is checked off below.

| Sprint | Period | Tasks | Done | Partial | Not Started |
|--------|--------|------:|-----:|--------:|------------:|
| Sprint 0 | Week 1 (Jun 12–18) | 12 | 12 | 0 | 0 |
| Sprint 1 | Weeks 2–3 (Jun 19 – Jul 2) | 10 | 10 | 0 | 0 |
| Sprint 2 | Weeks 4–5 (Jul 3–16) | 21 | 17 | 1 | 3 |
| Sprint 3 | Weeks 6–7 (Jul 17–30) | 5 | 1 | 0 | 4 |
| Sprint 4 | Weeks 8–9 (Jul 31 – Aug 13) | 7 | 0 | 1 | 6 |
| Week 10 | Aug 14–20 | 4 | 0 | 0 | 4 |
| **Totals** | | **59** | **40** | **2** | **17** |

---

## Primary Files (Dev 1 Owns)

### Files That Exist

| File | Purpose |
|------|---------|
| `apps/api/app/main.py` | FastAPI app factory, lifespan hooks, all router mounts |
| `apps/api/app/config.py` | All env vars via pydantic-settings — `get_settings()` is the only entry point |
| `apps/api/app/dependencies.py` | JWT verify, Redis, Settings as FastAPI deps |
| `apps/api/app/core/db.py` | Supabase async client lifecycle |
| `apps/api/app/core/redis.py` | `init_redis()` / `get_redis()` / `close_redis()` |
| `apps/api/app/core/retry.py` | `with_retry()` — exponential backoff + jitter ✅ done |
| `apps/api/app/core/circuit_breaker.py` | 5-failure/2-min breaker, Redis state ✅ done |
| `apps/api/app/core/cost_tracker.py` | Per-lesson cost accumulation + ceiling enforcement |
| `apps/api/app/core/websocket.py` | WebSocket connection manager |
| `apps/api/app/providers/base.py` | Abstract `LLMProvider` / `TTSProvider` / `ImageProvider` interfaces |
| `apps/api/app/providers/llm/openai.py` | OpenAI provider — GPT-4o / GPT-4o-mini |
| `apps/api/app/providers/tts/` | TTS provider directory |
| `apps/api/app/providers/image/` | Image provider directory |
| `apps/api/app/providers/avatar/` | HeyGen avatar provider directory |
| `apps/api/app/modules/content/router.py` | Content module router |
| `apps/api/app/modules/content/pipeline/graph.py` | LangGraph graph + all node functions inline (not one file per node, despite the "Files to Create" rows below — see Story 2-1's Tracker Cross-Reference Notes). Real: extract/structure/chunk/embed (Sprint 1), all 6 Phase 1 economy nodes (S2-1–S2-6), `lesson_planner_node` (S2-7), `slide_generator_node` (S2-8), `tts_node` (S2-9), `image_generator_node` (S2-10), `package_builder_node` (S2-11) — all 15 nodes in the pipeline have a real implementation. The `lesson_ready` WebSocket push (S2-12) — a separate file, `apps/api/app/workers/jobs/content_pipeline.py` + `apps/api/app/core/pubsub.py`, not this file — has also landed. |
| `apps/api/app/providers/tts/sarvam.py` | `SarvamTTSProvider` — primary TTS ✅ S2-9 |
| `apps/api/app/providers/tts/azure.py` | `AzureTTSProvider` — fallback TTS ✅ S2-9 |
| `apps/api/app/modules/content/pipeline/nodes/__init__.py` | Node package (individual node files not yet created) |
| `apps/api/app/schemas/__init__.py` | **EMPTY — awaiting `lesson.py` (S0-12)** |
| `apps/api/app/workers/main.py` | ARQ `WorkerSettings` entry point |
| `apps/api/app/workers/jobs/content_pipeline.py` | ARQ content pipeline job skeleton |
| `.github/workflows/ci.yml` | CI: lint + test on every PR |
| `.github/workflows/deploy.yml` | Deploy: Railway on merge to main |
| `railway.toml` | Railway service config |
| `supabase/migrations/20260611000000_initial_schema.sql` | Initial DB schema — **APPLIED, NEVER MODIFY** |
| `supabase/migrations/20260625000000_chunks_inline_embedding.sql` | Inline embeddings + books table — **APPLIED, NEVER MODIFY** |
| `supabase/migrations/20260714020000_add_lesson_tier.sql` | `lessons.tier` column, enum-constrained ✅ S2-LM2 |

### Files to Create

| File | Purpose |
|------|---------|
| `apps/api/app/core/langfuse.py` | Global `Langfuse` singleton — `get_langfuse()` used by all providers ✅ S0-9 |
| `apps/api/app/schemas/lesson.py` | Pydantic v2 models mirroring `lesson_package.schema.json` ✅ S0-12 |
| `apps/api/app/modules/content/pipeline/nodes/extract_text.py` | PyMuPDF extraction node *(S1-2)* |
| `apps/api/app/modules/content/pipeline/nodes/extract_tables.py` | pdfplumber table extraction *(S1-3)* |
| `apps/api/app/modules/content/pipeline/nodes/ocr_fallback.py` | Tesseract OCR fallback *(S1-4)* |
| `apps/api/app/modules/content/pipeline/nodes/structure_detect.py` | Rule-based + GPT-4o-mini structure detection *(S1-5, S1-6)* |
| `apps/api/app/modules/content/pipeline/nodes/chunk.py` | Semantic chunking *(S1-7)* |
| `apps/api/app/modules/content/pipeline/nodes/embed.py` | Embedding generation + pgvector storage *(S1-8)* |
| `apps/api/app/modules/content/pipeline/nodes/summarise_segment.py` | Segment summaries — GPT-4o-mini *(S2-1)* |
| `apps/api/app/modules/content/pipeline/nodes/segment_complexity.py` | Complexity scoring — GPT-4o-mini *(S2-2)* |
| `apps/api/app/modules/content/pipeline/nodes/quiz_generator.py` | Quiz generation — GPT-4o-mini *(S2-3)* |
| `apps/api/app/modules/content/pipeline/nodes/jargon_extractor.py` | Jargon extraction — GPT-4o-mini *(S2-4)* |
| `apps/api/app/modules/content/pipeline/nodes/intervention_messages.py` | Pre-generate 3×3 interventions — GPT-4o-mini *(S2-5)* |
| `apps/api/app/modules/content/pipeline/nodes/narration_generator.py` | Narration scripts — GPT-4o-mini *(S2-6)* |
| `apps/api/app/modules/content/pipeline/nodes/image_generator.py` | Images: GPT Image 1 Mini → Imagen 4 Fast → text-only *(S2-10)* |
| `apps/api/app/modules/content/pipeline/nodes/package_builder.py` | Assemble + write JSONB LessonPackage *(S2-11)* |
| `apps/api/app/modules/admin/router.py` | Admin: job status, costs, retry trigger *(S3-4)* |
| `apps/api/tests/unit/test_lesson_schema.py` | Pydantic ↔ JSON schema round-trip tests (22 tests) ✅ S0-12 |
| `apps/api/tests/unit/test_langfuse_core.py` | Singleton + flush contract tests (4 tests) ✅ S0-9 |
| `apps/api/tests/evals/` | Eval harness against real PDFs *(S2-14)* |

### Read-Only Dependencies (Do Not Modify)

| File | Owned By | Why Dev 1 Reads It |
|------|----------|--------------------|
| `packages/shared/lesson_package.schema.json` | Frozen (all devs) | Authoritative schema — Pydantic models must mirror it exactly |
| `packages/shared/types/lesson.ts` | Dev 2 | Cross-reference TS types when writing Pydantic models |
| `packages/shared/types/ws.ts` | Dev 4 | `lesson_ready` push from `package_builder` must match this discriminated union |
| `apps/api/app/modules/assessment/router.py` | Dev 3 | Coordinate `lesson_jobs` state enum — Dev 3 reads job state in Sprint 2 |

---

## Interface Contracts (Frozen)

Changes require a **4-developer PR review** (PRD §16):

1. `packages/shared/lesson_package.schema.json` — JSON schema; authoritative. Both Pydantic models and TS types must stay in sync.
2. `packages/shared/types/lesson.ts` — TS mirror of the JSON schema.
3. `packages/shared/types/ws.ts` — WebSocket discriminated union; `lesson_ready` message shape.
4. `supabase/migrations/` — Applied migrations are immutable. Schema changes require a new `.sql` file.
5. **Assessment OpenAPI** — Auto-generated from FastAPI routes; breaking route changes require cross-dev review.

---

## Dependency Map

```
Dev 2 (Frontend / Player)
  ──► POST /api/content/lessons       [uploads PDF, triggers pipeline]
  ◄── GET  /api/content/lessons/{id}  [polls status; reads content JSONB when ready]
  ◄── WS   lesson_ready push          [via Dev 4 WebSocket layer — Dev 1 triggers it]

Dev 3 (Assessment / CES / Analytics)
  ──► lesson_jobs.status              [reads pipeline state to time CES scoring start]
  ◄── lessons.content JSONB           [reads LessonPackage after pipeline completes]

Dev 4 (WebSocket / Tutor State Machine)
  ──► packages/shared/types/ws.ts     [defines lesson_ready message shape Dev 1 must emit]
  ◄── package_builder emits lesson_ready  [Dev 1 fires the push on pipeline completion]
  ──► Redis session:{session_id}:*    [Dev 4 writes; Dev 1 reads for cost/state context]

DB tables Dev 1 WRITES:
  books, chapters, chunks (with inline embeddings), lessons, lesson_jobs

Redis keys Dev 1 WRITES:
  circuit_breaker:{provider}:failures
  circuit_breaker:{provider}:state
  circuit_breaker:{provider}:opened_at
  lesson:{lesson_id}:cost_usd
  job:{job_id}:status
  job:{job_id}:node_outputs
  embeddings:search:{hash}            [cached ANN search results, TTL 300s]
```

---

## Technical Reference

### LLM / AI Model Allocation

> All model IDs are env-var driven via `config.py`. **Never hardcode model strings in business logic.**
> **Batch API rule:** Never use OpenAI or Google Batch API — 24-hour window breaks real-time generation.

| Task | Env Var | Default | Eval Candidates |
|------|---------|---------|-----------------|
| Lesson planning | `LLM_LESSON_PLANNER` | `gpt-4o` | GPT-4o, claude-3-5-sonnet-20241022, o1-mini |
| Slide generation | `LLM_SLIDE_GENERATOR` | `gpt-4o` | Same as above |
| Quiz, jargon, complexity, narration, interventions | `LLM_MINI` | `gpt-4o-mini` | GPT-4o-mini, gemini-2.0-flash |
| Tutor Q&A (Phase 2) | `LLM_TUTOR` | `gpt-4o` | GPT-4o, claude-3-5-sonnet-20241022 |
| Embeddings | fixed | `text-embedding-3-small` | Not evaluated — cost/perf optimal |

**Decision (2026-07-17): direct provider SDKs, NOT an LLM router/aggregator (OpenRouter or similar).** Considered and rejected after S2-15's provider factory landed. Rationale:
- `providers/llm/factory.py` (S2-15) already gives model-agnostic dispatch by model-string prefix — adding Claude (`AnthropicLLMProvider`) or Gemini (`GeminiLLMProvider`) as an eval candidate is one new provider file + one registry entry, zero call-site changes. This was the actual problem an aggregator would have solved, and it's already solved.
- `core/circuit_breaker.py` and `core/cost_tracker.py` both key/price per literal provider (`"openai"`/`"sarvam"`/`"azure_tts"` breaker keys; fixed per-provider cost tables). Routing multiple model families through one OpenRouter key would blur or require rebuilding both — a real regression, not a simplification.
- An aggregator adds an unresearched third-party dependency (rate limits, uptime, added latency) into the pipeline's critical path, with no verified reliability data, right as the project approaches Sprint 3's real-student launch.
- The multi-provider decision (cheap models for economy nodes, premium for planning) was made for cost/quality reasons, not because direct SDK integration was too costly — and S2-15 confirmed direct integration is cheap per new provider.
- **Action:** when GPT-4o-mini/Claude 3.5 Sonnet/Gemini 2.0 Flash evaluations (Sprint 1 Week 1 eval sprint, still not formally run) pick a non-OpenAI model for any slot in the table above, add that provider directly to `providers/llm/factory.py` — do not introduce an aggregator layer.

### API Endpoints (Frozen — 4-Dev PR to Change)

| Method | Path | Sprint | DB Write | Notes |
|--------|------|--------|----------|-------|
| `POST` | `/api/content/lessons` | S1 | `books`, `lessons`, `lesson_jobs` | Accepts PDF upload; enqueues ARQ job; returns `lesson_id + job_id` immediately |
| `GET` | `/api/content/lessons/{lesson_id}` | S1 | — | Returns `LessonRecord` (status + content when ready) |
| `GET` | `/api/admin/jobs` | S3 | — | Job list with status + cost per lesson |
| `POST` | `/api/admin/jobs/{job_id}/retry` | S3 | `lesson_jobs` | Re-enqueues a failed job |
| `GET` | `/api/admin/costs` | S3 | — | Cost aggregation per lesson and per user |

### DB Tables Owned by Dev 1

**`public.books`** *(added migration 20260625)*

| Column | Type | Constraints | Meaning |
|--------|------|-------------|---------|
| `book_id` | `uuid` | PK, `gen_random_uuid()` | Stable identifier for the uploaded PDF |
| `user_id` | `uuid` | FK → `users.id` ON DELETE CASCADE, NOT NULL | Owner |
| `filename` | `text` | NOT NULL | Original uploaded filename |
| `page_count` | `integer` | nullable | Populated after PyMuPDF extraction (S1-2) |
| `status` | `text` | NOT NULL, DEFAULT `'processing'`, CHECK IN (`'processing'`, `'ready'`, `'failed'`) | Book ingestion state |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() | Row creation time |
| `updated_at` | `timestamptz` | NOT NULL DEFAULT now(), auto-trigger | Auto-updated on any change |

**`public.lessons`**

| Column | Type | Constraints | Meaning |
|--------|------|-------------|---------|
| `lesson_id` | `uuid` | PK, `gen_random_uuid()` | Stable lesson identifier returned to frontend |
| `user_id` | `uuid` | FK → `users.id` ON DELETE CASCADE, NOT NULL | Owner — RLS gates on this |
| `book_id` | `uuid` | nullable FK → `books.book_id` ON DELETE SET NULL | Source book; SET NULL so lesson survives book deletion |
| `title` | `text` | nullable | Set by `lesson_planner` node when it completes |
| `status` | `text` | NOT NULL, DEFAULT `'generating'`, CHECK IN (`'generating'`, `'ready'`, `'failed'`) | Pipeline state visible to frontend via polling |
| `content` | `jsonb` | nullable | Full `LessonPackage` JSONB written by `package_builder`; `NULL` until pipeline completes |
| `source_file_path` | `text` | nullable | Supabase Storage path to the source PDF |
| `tier` | `text` | NOT NULL DEFAULT `'T2'`, CHECK IN (`'T1'`,`'T2'`,`'T3'`) ✅ migrated S2-LM2 (2026-07-14) | Learner Mode content-depth tier. Column exists and is writable, but **nothing writes a non-default value yet** — `POST /lessons`'s `tier` param (S2-LM3) was implemented then reverted pending S2-LM1's 4-dev sign-off; drives slide count + content depth in `lesson_planner`/`slide_generator` (S2-LM4/S2-LM5, not started) |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() | Row creation time |
| `updated_at` | `timestamptz` | NOT NULL DEFAULT now(), auto-trigger | Auto-updated on any write |

**`public.lesson_jobs`**

| Column | Type | Constraints | Meaning |
|--------|------|-------------|---------|
| `job_id` | `uuid` | PK, `gen_random_uuid()` | ARQ job identifier |
| `lesson_id` | `uuid` | FK → `lessons.lesson_id` ON DELETE CASCADE, NOT NULL | Owning lesson |
| `status` | `text` | NOT NULL, DEFAULT `'pending'`, CHECK IN (`'pending'`, `'running'`, `'completed'`, `'failed'`) | ARQ job lifecycle state |
| `last_node` | `text` | nullable | Name of the last successfully completed pipeline node — used for checkpoint resume on retry |
| `node_outputs` | `jsonb` | nullable | Accumulated node outputs keyed by node name — read on ARQ retry to skip completed nodes |
| `error` | `text` | nullable | Error message populated on `status='failed'` |
| `attempt` | `integer` | NOT NULL DEFAULT 0 | ARQ retry count (max 3 per PRD §14) |
| `cost_usd` | `numeric(10,4)` | NOT NULL DEFAULT 0 | Accumulated LLM + TTS + image cost for this pipeline run |
| `started_at` | `timestamptz` | nullable | When ARQ worker picked up the job |
| `completed_at` | `timestamptz` | nullable | When `package_builder` finished successfully |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() | Row creation time |

**`public.chapters`**

| Column | Type | Constraints | Meaning |
|--------|------|-------------|---------|
| `chapter_id` | `uuid` | PK, `gen_random_uuid()` | Chapter unit identifier |
| `book_id` | `uuid` | FK → `books.book_id` ON DELETE CASCADE, NOT NULL | Parent book (FK retrofitted in migration 20260625) |
| `lesson_id` | `uuid` | FK → `lessons.lesson_id` ON DELETE CASCADE, NOT NULL | Associated lesson |
| `title` | `text` | NOT NULL | Chapter title from structure detection |
| `page_start` | `integer` | NOT NULL | First page (1-indexed) |
| `page_end` | `integer` | NOT NULL | Last page (inclusive) |
| `chapter_index` | `integer` | NOT NULL | 0-indexed position within the book |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() | Row creation time |

**`public.chunks`** *(embedding inlined as of migration 20260625 — `embeddings` table dropped)*

| Column | Type | Constraints | Meaning |
|--------|------|-------------|---------|
| `chunk_id` | `uuid` | PK, `gen_random_uuid()` | Text chunk identifier |
| `chapter_id` | `uuid` | FK → `chapters.chapter_id` ON DELETE CASCADE, NOT NULL | Parent chapter |
| `book_id` | `uuid` | FK → `books.book_id` ON DELETE CASCADE, nullable | Shortcut FK for book-level queries (backfilled from chapters) |
| `section` | `text` | nullable | Section heading within the chapter, if detected |
| `page_start` | `integer` | nullable | Page range start for this chunk |
| `page_end` | `integer` | nullable | Page range end for this chunk |
| `content` | `text` | NOT NULL | Raw text — always stored alongside vector (re-extraction costs 200–300ms; source PDF may be deleted) |
| `chunk_index` | `integer` | NOT NULL | 0-indexed position within the chapter |
| `token_count` | `integer` | nullable | Token count populated by `embed` node |
| `embedding` | `vector(1536)` | nullable | `text-embedding-3-small` inline vector; HNSW index via `vector_cosine_ops` |
| `embedding_metadata` | `jsonb` | NOT NULL DEFAULT `'{}'` | Model name, version, ingestion timestamp |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() | Row creation time |

> **HNSW index** on `chunks.embedding` (`vector_cosine_ops`) for approximate nearest-neighbour cosine search.

### Redis Keys (Dev 1 Owns)

| Key Pattern | Type | What It Stores | TTL |
|-------------|------|----------------|-----|
| `circuit_breaker:{provider}:failures` | string (int) | Failure count in the current 2-minute window | 120 s rolling |
| `circuit_breaker:{provider}:state` | string | `CLOSED` / `OPEN` / `HALF_OPEN` | None — managed by logic |
| `circuit_breaker:{provider}:opened_at` | string (epoch float) | Timestamp when breaker tripped OPEN | 600 s (OPEN → HALF_OPEN after 10 min) |
| `lesson:{lesson_id}:cost_usd` | string (float) | Accumulated cost for this pipeline run | None — cleared on job completion |
| `job:{job_id}:status` | string | `pending / running / completed / failed` | None |
| `job:{job_id}:node_outputs` | hash | `node_name → JSON output` | None |
| `embeddings:search:{hash}` | string | Cached ANN vector search result (JSON) | 300 s |

### Cost Ceiling (PRD §12)

| Env Var | Default | Meaning |
|---------|---------|---------|
| `MAX_LESSON_COST_USD` | `3.00` | Hard ceiling per lesson pipeline run |
| `MAX_DAILY_SPEND_PER_USER_USD` | `10.00` | Daily per-user AI spend cap |

On breach: downshift to cheapest providers, complete the lesson, flag in admin — **never abort mid-lesson**.

---

## Cross-Cutting Bugs Found

| # | File | Bug | Impact | Fix |
|---|------|-----|--------|-----|
| B1 | `apps/api/app/providers/llm/openai.py:44–47` | `Langfuse()` instantiated inside `__init__()` — each `OpenAILLMProvider` creates an independent Langfuse client with its own buffer. No global `langfuse.flush()` on process shutdown means buffered traces are silently lost on every deploy or restart. | HIGH — production traces dropped on every Railway deploy | Create a global `Langfuse` singleton (e.g. `app/core/langfuse.py`); inject it into providers rather than constructing inside `__init__`; call `langfuse.flush()` in FastAPI lifespan `finally` block |
| B2 | `apps/api/app/schemas/__init__.py` (empty file) | `lesson.py` not created — `from app.schemas import LessonPackage` raises `ImportError` at module load. All 11 pipeline nodes that reference `app.schemas` fail at import time. | CRITICAL — blocks all Sprint 1 and Sprint 2 node work | Create `schemas/lesson.py` — full spec + ready-to-paste code in `docs/dev1-pydantic-schemas-task.md` |

---

## Known Stub Discrepancies to Fix

| Location | Current Stub Issue | Correct Behaviour | PRD Rule |
|----------|--------------------|-------------------|----------|
| `apps/api/app/config.py:54` | `elevenlabs_api_key` field present (marked deprecated) | Keep as `str \| None = None` to avoid breaking existing `.env` files; add a validator that warns if set; remove in Sprint 2 cleanup | CLAUDE.md 2026-06-25: ElevenLabs REMOVED, replaced by Sarvam AI Bulbul v2 |
| `apps/api/app/workers/jobs/content_pipeline.py` | Skeleton only — no actual graph execution | Must call `graph.arun()`, write `lesson_jobs.status = 'running'` on pickup, `'completed'/'failed'` on exit, emit `lesson_ready` WebSocket push | PRD §9: checkpoint pattern mandatory for all nodes |
| `apps/api/app/core/cost_tracker.py` | Exists but not wired into any node yet | Must be called inside every LLM, TTS, and image node via `accumulate_cost()` + `check_ceiling()` | PRD §12: $3.00/lesson ceiling enforced at every provider call |
| `apps/api/app/modules/content/pipeline/nodes/__init__.py` | Empty file | Remains empty; node files are imported individually — confirm `graph.py` import paths match the `nodes/` filenames as they are created | Structural note — not a logic bug |

---

## Sprint 0 — Week 1 (Due: ~2026-06-18)

> **Goal:** Ship the infra skeleton — every dev can run locally, CI is green, contracts are frozen.

- [x] **S0-1 Railway project setup + env vars** — ✓ 2026-06-12
  - `railway.toml`, `apps/api/app/config.py`
  - All vars use `Field(...)` — no defaults that mask missing secrets
  - **AC:** `railway.toml` present; all env vars in `Settings` with pydantic-settings; `get_settings()` is the only instantiation point ✅

- [x] **S0-2 Supabase project + all DB migrations** — ✓ 2026-06-12
  - `supabase/migrations/20260611000000_initial_schema.sql`
  - `supabase/migrations/20260625000000_chunks_inline_embedding.sql`
  - **AC:** Both migrations applied; `supabase/config.toml` present; never modify applied migrations (PRD §16) ✅

- [x] **S0-3 Railway Redis service config** — ✓ 2026-06-12
  - `apps/api/app/core/redis.py`
  - **AC:** `init_redis()` / `get_redis()` / `close_redis()` usable by all modules; called in API lifespan and ARQ worker startup ✅

- [x] **S0-4 GitHub Actions CI/CD pipeline** — ✓ 2026-06-12
  - `.github/workflows/ci.yml`, `.github/workflows/deploy.yml`
  - **AC:** CI runs lint + test on every PR; deploy triggers on merge to main ✅

- [x] **S0-5 Monorepo scaffold** — ✓ 2026-06-12
  - `apps/web/`, `apps/api/`, `packages/shared/`, `pnpm-workspace.yaml`, root `package.json`
  - **AC:** All workspace packages resolvable via `pnpm`; root `package.json` present ✅

- [x] **S0-6 FastAPI app factory + router mounts** — ✓ 2026-06-12
  - `apps/api/app/main.py`
  - **AC:** All 7 module routers mounted; WebSocket router mounted; `/health` returns `{"status": "ok"}` ✅

- [x] **S0-7 ARQ worker entry point + task registry** — ✓ 2026-06-12
  - `apps/api/app/workers/main.py`, `apps/api/app/workers/jobs/content_pipeline.py`
  - **AC:** `WorkerSettings` with `functions`, `redis_settings`, lifecycle hooks; `max_jobs=5`, `job_timeout=600`, `max_tries=3` per PRD §14 ✅

- [x] **S0-8 Sentry wired from day one** — ✓ 2026-06-12
  - `apps/api/app/main.py:52–58`
  - **AC:** `sentry_sdk.init()` called in lifespan startup when `SENTRY_DSN` present; no-ops gracefully when absent ✅

- [x] **S0-9 Langfuse wired globally** — ✓ 2026-06-26
  - `apps/api/app/core/langfuse.py` *(created — module-level singleton + `get_langfuse()`)*
  - `apps/api/app/providers/llm/openai.py` *(updated — `__init__` now calls `get_langfuse()` not `Langfuse()`)*
  - `apps/api/app/main.py` *(updated — startup log `Langfuse host: …`; shutdown calls `get_langfuse().flush()`)*
  - `apps/api/tests/unit/test_langfuse_core.py` *(created — 4 unit tests: singleton identity, constructor args, flush contract)*
  - **AC:** Single `Langfuse` instance per process ✅; `flush()` called on graceful shutdown ✅; no dropped traces on Railway deploy ✅; startup log present ✅

  **Review Findings (2026-06-26):**
  - [x] [Review][Patch] **P1-HIGH** Thread-safety: `get_langfuse()` has no lock — two concurrent callers can each construct a `Langfuse` instance; second overwrites first without flushing it [`core/langfuse.py:24-30`] — ✓ 2026-06-26
  - [x] [Review][Patch] **P2-HIGH** ARQ worker process (separate OS process) never calls `get_langfuse()` at startup or `flush()` at shutdown — all pipeline node traces dropped on worker exit [`workers/main.py`] — ✓ 2026-06-26
  - [x] [Review][Patch] **P3-HIGH** `flush()` is unreachable if `close_redis()` raises — lifespan shutdown block lacks `try/finally`; flush must survive preceding failures [`main.py:68-72`] — ✓ 2026-06-26
  - [x] [Review][Patch] **P4-MED** `flush()` itself has no `try/except` — an exception from the Langfuse SDK propagates out of the lifespan generator, masking the real shutdown cause [`main.py:72`] — ✓ 2026-06-26
  - [x] [Review][Patch] **P5-MED** `Langfuse.__init__` failure leaves `_langfuse = None` — every subsequent `get_langfuse()` call retries construction and raises, taking down pipeline nodes [`core/langfuse.py:25-30`] — ✓ 2026-06-26
  - [x] [Review][Patch] **P6-LOW** `flush()` is synchronous/blocking with a 60-second default timeout (Langfuse 4.x) — blocks the event loop thread on shutdown; Railway may SIGKILL before it completes [`main.py:72`] — ✓ 2026-06-26
  - [x] [Review][Patch] **P7-LOW** `reset_singleton` fixture annotated `-> None` but is a generator — correct type is `Generator[None, None, None]` [`tests/unit/test_langfuse_core.py:29`] — ✓ 2026-06-26
  - [x] [Review][Defer] `OpenAILLMProvider` captures singleton by reference at construction — stale reference in tests if singleton is reset mid-test [`providers/llm/openai.py:44`] — deferred, test isolation edge case only
  - [x] [Review][Defer] `generation.end()` not called on exception path in `openai.py` — spans left open on every LLM error [`providers/llm/openai.py:63`] — deferred, pre-existing before S0-9
  - [x] [Review][Defer] No `atexit` hook for crash-safe flush — traces lost on abnormal process exit — deferred, separate enhancement
  - [x] [Review][Defer] Test suite has no lifespan integration test covering `flush()` call path — deferred, requires full FastAPI test harness
  - [x] [Review][Defer] No concurrency test for singleton race — deferred, fix the lock (P1) first

- [x] **S0-10 Shared TS types + JSON schema published** — ✓ 2026-06-12
  - `packages/shared/types/lesson.ts`, `packages/shared/types/ws.ts`, `packages/shared/lesson_package.schema.json`
  - **AC:** TS types + JSON schema committed; importable as `@transformED/shared` ✅

- [x] **S0-11 Lesson package JSON contract frozen** — ✓ 2026-06-12
  - `packages/shared/lesson_package.schema.json`
  - **AC:** Schema committed; all 4 devs unblocked for mocking; **FROZEN — 4-dev PR required to change** ✅

- [x] **S0-12 Pydantic lesson schemas** — ✓ 2026-06-26
  - `apps/api/app/schemas/lesson.py` *(to create)*
  - `apps/api/app/schemas/__init__.py` *(update — currently empty)*
  - `apps/api/tests/unit/test_lesson_schema.py` *(to create)*
  - Full implementation spec + ready-to-paste code: `docs/dev1-pydantic-schemas-task.md`
  - Implementation:
    1. Create `schemas/lesson.py` — 17 Pydantic v2 models (`LessonPackage`, `Segment`, `Slide`, etc.) mirroring JSON schema
    2. Update `schemas/__init__.py` to re-export all 17 models
    3. Create `tests/unit/test_lesson_schema.py` — round-trip JSON schema validation test
    4. Run `mypy app` → clean; `ruff check .` → clean
  - **AC:** `from app.schemas import LessonPackage` works; unit test passes against `lesson_package.schema.json`; `mypy` and `ruff` both clean

---

## Sprint 1 — Weeks 2–3 (Due: ~2026-07-02)

> **Goal:** Book ingestion pipeline end-to-end — PDF upload → extracted text → chunked → embedded → stored in DB.

### Checkpoint Pattern (mandatory for every node below)

Every node must:
1. **On entry:** read `last_node` from `lesson_jobs` — if `last_node >= this_node_name`, return cached output from `node_outputs` and skip
2. **On success:** write `last_node = node_name` + `node_outputs[node_name] = output` to `lesson_jobs`
3. Wrap every LLM/provider call: `@with_retry(max_attempts=3)` for critical nodes, `max_attempts=2` for optional
4. Call `await cost_tracker.accumulate_cost(lesson_id, cost)` after every LLM call
5. Emit a Langfuse span with `lesson_id`, `node_name`, and token counts via `get_langfuse()`

- [x] **S1-1 `with_retry()` decorator** — ✓ 2026-06-12 (built ahead of schedule)
  - `apps/api/app/core/retry.py`
  - `wait = (2^attempt) + random.random()`; retries 429/5xx; never retries 400/401/403/404/422
  - **AC:** Applied to all LLM/provider calls in Sprint 1+ nodes; backoff formula matches PRD §14 ✅

- [x] **S1-2 PyMuPDF text + image + layout extraction node** — ✓ 2026-07-07
  - `apps/api/app/modules/content/pipeline/nodes/extract_text.py`
  - 1. Accept `state["pdf_path"]` (Supabase Storage signed URL)
  - 2. Open with `fitz.open()`; iterate pages; extract text blocks with bounding boxes
  - 3. Extract embedded images; store to Supabase Storage; record paths in state
  - 4. Write `books.page_count` once known
  - 5. Return `{"raw_pages": [...], "page_count": N}` → checkpoint write on success
  - **AC:** All text, images, and layout blocks extracted from a test PDF; `books.page_count` written; node is idempotent (second run skips if `last_node >= extract_text`)

- [x] **S1-3 pdfplumber table extraction node** — ✓ 2026-07-07
  - `apps/api/app/modules/content/pipeline/nodes/extract_tables.py`
  - 1. Run `pdfplumber.open()` against same PDF as S1-2
  - 2. Detect tables per page; serialize to list-of-dicts (JSON-serializable)
  - 3. Merge table data into `raw_pages` from S1-2
  - **AC:** Tables extracted from a known table-heavy PDF; serializable to JSON; merged correctly into extraction output

- [x] **S1-4 Tesseract OCR fallback node** — ✓ 2026-07-07
  - `apps/api/app/modules/content/pipeline/nodes/ocr_fallback.py`
  - 1. Check text yield from S1-2: if `chars_per_page < OCR_TEXT_YIELD_THRESHOLD` (env var, default 50), invoke OCR
  - 2. Run `pytesseract.image_to_string()` in-container
  - 3. Replace low-yield pages with OCR text; merge back into state
  - **AC:** Scanned PDF with <50 chars/page triggers OCR; text-based PDF skips entirely; env var controls threshold

- [x] **S1-5 Structure detection — rule-based** — ✓ 2026-07-07
  - `apps/api/app/modules/content/pipeline/nodes/structure_detect.py`
  - 1. Analyse font sizes, TOC entries, numbering patterns (regex) across pages
  - 2. Produce `DocumentStructure` with `chapters[]`, each with `sections[]`
  - Hierarchy: **Chapter → Section → Topic** — never full-book single structure (PRD §5 principle 6)
  - **AC:** Chapter boundaries correctly identified in 3 test PDFs of varying layout styles

- [x] **S1-6 Structure detection — GPT-4o-mini LLM validation** — ✓ 2026-07-07
  - `apps/api/app/modules/content/pipeline/nodes/structure_detect.py` (second pass in same file)
  - Model: `settings.llm_mini` (env var `LLM_MINI`)
  - 1. Feed rule-based `DocumentStructure` + first/last lines of each detected chapter to LLM
  - 2. LLM validates boundaries and corrects misdetections using `complete_structured()`
  - 3. Write corrected structure to `lesson_jobs.node_outputs["structure_detect"]`
  - **AC:** LLM corrects at least one misdetection in a known-hard test PDF; output validates as `DocumentStructure`; `@with_retry(max_attempts=3)` applied; Langfuse span records token count

- [x] **S1-7 Semantic chunking (chapter → section → topic)** — ✓ 2026-07-07
  - `apps/api/app/modules/content/pipeline/nodes/chunk.py`
  - 1. Consume corrected `DocumentStructure` from S1-6
  - 2. Split each section into topic-level chunks; target ≤800 tokens each
  - 3. Write `chunks` rows: `chapter_id`, `book_id`, `section`, `page_start`, `page_end`, `content`, `chunk_index`
  - Never create a full-book single chunk (PRD §5 principle 6)
  - **AC:** A 20-page chapter produces ≥3 chunks; no chunk exceeds 800 tokens; all chunks written to DB with correct FKs

- [x] **S1-8 text-embedding-3-small + pgvector storage** — ✓ 2026-07-07
  - `apps/api/app/modules/content/pipeline/nodes/embed.py`
  - Model: `text-embedding-3-small` (fixed — not configurable)
  - 1. Batch all chunks (max 2048 per API call)
  - 2. Call OpenAI embeddings API; receive 1536-dim vectors
  - 3. Write `embedding`, `token_count`, `embedding_metadata` to `chunks` inline
  - **Embeddings computed ONCE at ingestion — never regenerated for stored content (PRD rule)**
  - **AC:** All chunks have `embedding IS NOT NULL` after node; HNSW index on `chunks.embedding` used in search query; re-run skips checkpoint

- [x] **S1-9 `lesson_jobs` table + ARQ job enqueue** — ✓ 2026-07-07
  - `apps/api/app/workers/jobs/content_pipeline.py`, `apps/api/app/modules/content/router.py`
  - 1. `POST /api/content/lessons` creates `books` row, `lessons` row (`status='generating'`), `lesson_jobs` row (`status='pending'`)
  - 2. Enqueues ARQ job with `lesson_id` + `job_id`
  - 3. ARQ pickup: `lesson_jobs.status = 'running'`, `started_at = now()`
  - 4. ARQ success: `status = 'completed'`, `completed_at = now()`
  - 5. ARQ failure: `status = 'failed'`, `error = str(exc)`
  - **AC:** `lesson_jobs` row transitions correctly through all 4 states; ARQ `max_tries=3` matches PRD §14

- [x] **S1-10 `POST /lessons` endpoint live** — ✓ 2026-07-07
  - `apps/api/app/modules/content/router.py`
  - 1. Accept multipart PDF; validate file type (MIME + magic bytes)
  - 2. Store PDF to Supabase Storage; set `lessons.source_file_path`
  - 3. Enqueue ARQ job (S1-9)
  - 4. Return `201` with `{"lesson_id": "...", "job_id": "..."}` immediately — do not wait for pipeline
  - Apply `slowapi` rate limit: `"5/minute"` per user — **do not defer to Sprint 4**
  - **AC:** Integration test — upload valid PDF → `201` with UUIDs → ARQ job enqueued → `lesson_jobs` row visible in DB

---

## Sprint 2 — Weeks 4–5 (Due: ~2026-07-16)

> **Goal:** All 11 generation nodes producing a valid `LessonPackage` JSONB from an ingested chapter.
> **Added 2026-07-13 — Learner Mode (tier-aware lessons) is now in scope for Sprint 2**, inserted between Phase 1 and Phase 2 below (S2-LM1 through S2-LM5). This was previously undocumented anywhere in this tracker or `CLAUDE.md` — see `docs/stories/2-1-phase1-economy-nodes.md` context for how the gap was found. Positioned here (not as a separate future "feature sprint") because S2-LM4/S2-LM5 directly amend S2-7/S2-8's acceptance criteria — a Learner Mode "feature sprint" bolted on *after* Sprint 2 would mean re-opening `lesson_planner`/`slide_generator` a second time.

> **Cost ceiling rule:** Every node that calls a provider must call `cost_tracker.accumulate_cost()` immediately after. On `check_ceiling()` returning `True`, downshift to cheapest available provider, complete the lesson, flag in admin — never abort.
> **Circuit breaker:** Call `is_circuit_open(provider_key)` before every external provider call. Wire in Sprint 2 — don't wait for Sprint 3.

**Phase 1 Economy nodes** (S2-1 through S2-6) run in parallel per segment. **All must complete before Phase 2 starts.**
**Learner Mode infra** (S2-LM1 through S2-LM3) — contract, migration, endpoint. Independent of Phase 1; must complete before Phase 2 starts (S2-7 needs `tier` to read).
**Phase 2 Premium nodes** (S2-7, S2-8) sequential — consume Phase 1 outputs **and** `state["tier"]` from S2-LM3.
**Learner Mode tier logic** (S2-LM4, S2-LM5) — lands together with S2-7/S2-8, not as a later rework pass.
**Phase 3 Media nodes** (S2-9, S2-10, S2-11) sequential after Phase 2.

- [x] **S2-1 `summarise_segment` node** — ✓ 2026-07-15 (upgraded from PARTIAL now that S2-7 is real)
  - `apps/api/app/modules/content/pipeline/graph.py::summarise_segment_node` (NOT a separate `nodes/summarise_segment.py` file — see Story 2-1's Tracker Cross-Reference Notes on why this file-per-node table entry is stale)
  - Model: `settings.llm_mini` (`LLM_MINI`)
  - Phase 1 — dispatched via `Send()`, once per section (graph-level fan-out, see AC-0 below)
  - ✓ Produces a 2–3 sentence, ≤100-word summary per section, calling `OpenAILLMProvider.complete_structured()` — real implementation, tested (`test_phase1_economy_nodes.py`, AC-1)
  - ✓ `lesson_planner` (S2-7, Story 2-6, done 2026-07-14/15) now really consumes these summaries — never raw chapter text — enforced structurally and by a dedicated regression test (`test_prompt_never_includes_raw_chapter_text_or_sections`). The 5×-token-savings constraint is now actually realized, not just wired.
  - **AC:** Summary ≤100 words ✓; `lesson_planner` (S2-7) consumes summaries not raw text — 5× token savings enforced ✓ — tested ✅
  - **Still ⚠️ PARTIAL for the reason above** (blocked on S2-7, unrelated to code quality) — separately, the second-pass `/bmad-code-review` findings against all 6 economy nodes (AC-3..AC-7 combined diff) were fully closed 2026-07-14: 6 patches applied (checkpoint re-validation extended to all 6 nodes, quiz duplicate/blank-option guards on both read and write paths, jargon/intervention checkpoint value-quality re-validation, `narration_style` strip-before-truthiness fix) and 1 decision resolved (`narration_style` moved from the system-role to the user-role prompt — untrusted LLM-derived value, now at the same trust level as the section body). 267/267 unit tests pass. See `docs/stories/2-1-phase1-economy-nodes.md`'s "Review Findings (2026-07-14, second pass...)" section for the full findings.

- [x] **S2-2 `segment_complexity` node** — ✓ 2026-07-13
  - `apps/api/app/modules/content/pipeline/graph.py::segment_complexity_node` (NOT a separate `nodes/segment_complexity.py` file — see note above)
  - Model: `settings.llm_mini` (`LLM_MINI`)
  - Phase 1 — dispatched via `Send()`, once per section
  - Output: `SegmentComplexity` Pydantic model; `intervention_sensitivity` clamped into [0.0, 1.0] with a warning log if the LLM returned an out-of-range value (never silently trusted)
  - **AC:** Output validates against `app.schemas.SegmentComplexity` ✓; field ranges enforced ✓ — tested (`test_phase1_economy_nodes.py`, AC-2) ✅

- [x] **S2-1b Phase 1 economy node checkpoint/idempotency** — ✓ 2026-07-13 (deferred from Story 2-1's code review; itself reviewed and patched same day)
  - `docs/stories/2-1b-phase1-checkpoint-idempotency.md`
  - Per-section checkpoint via `merge_lesson_job_node_output()` (Postgres function, `supabase/migrations/20260713020000_lesson_job_node_output_merge_fn.sql`) — atomic server-side JSONB merge, not the client-side read-modify-write Phase A nodes use (unsafe under Story 2-1's concurrent `Send()` dispatch). **Review caught and fixed a critical finding here:** the function had no access control — Supabase auto-exposes every Postgres function as a public RPC endpoint, so any caller could have overwritten another user's `lesson_jobs` row (cross-tenant IDOR, RLS bypass). Fixed: revoked `anon`/`authenticated`/`public` execute, granted only `service_role`; also hardened `search_path` and made a missing-row write raise instead of silently no-op'ing.
  - Phase 1 progress visibility via a Redis **set** (`job:{lesson_id}:phase1_completed_keys`, SADD/SCARD) — not a plain INCR counter, which review found would double-count a section re-visited on ARQ retry; SADD is idempotent per checkpoint key
  - Applied to `summarise_segment_node`/`segment_complexity_node` at the time this task shipped (2026-07-13, only 2 of 6 economy nodes existed then); S2-3 through S2-6 have since adopted the same checkpoint pattern (all 6 nodes checkpointed as of 2026-07-14, including the second-pass fix that re-validates cached value quality — not just key presence — on every one of the 6 checkpoint reads, see S2-1's story file)
  - **AC:** simulated retry after partial completion makes 0 duplicate LLM calls for already-completed sections ✓ — tested (`test_phase1_checkpoint_idempotency.py`, 9 tests incl. a real `asyncio.gather` concurrency test) ✅

- [x] **S2-3 `quiz_generator` node** — ✓ 2026-07-14
  - `apps/api/app/modules/content/pipeline/graph.py::quiz_generator_node` (NOT a separate `nodes/quiz_generator.py` file — see Story 2-1's Tracker Cross-Reference Notes)
  - Model: `settings.llm_mini` (`LLM_MINI`)
  - Phase 1 — dispatched via `Send()`, once per section; per-section checkpoint (Story 2-1b pattern)
  - Output: `QuizQuestion`-shaped dict; exactly-4-options guard (frozen schema only enforces a minimum), out-of-range `correct_index` and blank question/explanation rejected (degrade section, not fabricated)
  - **AC:** Output validates against `app.schemas.QuizQuestion` (segment_id stripped first) ✓; `min_length=4` enforced by the node itself, not just the schema ✓ — tested (`test_phase1_economy_nodes.py`, AC-3; 5-agent review 2026-07-14 added the missing `QuizQuestion.model_validate` assertion) ✅

- [x] **S2-4 `jargon_extractor` node** — ✓ 2026-07-14
  - `apps/api/app/modules/content/pipeline/graph.py::jargon_extractor_node`
  - Model: `settings.llm_mini` (`LLM_MINI`)
  - Phase 1 — dispatched via `Send()`, once per section; per-section checkpoint
  - Output: list of `JargonEntry`; empty term/definition entries filtered before reaching `state["glossary"]`
  - **AC:** Output validates against `app.schemas.JargonEntry` ✓; no empty terms or definitions ✓ — tested (`test_phase1_economy_nodes.py`, AC-4) ✅

- [x] **S2-5 `intervention_messages` node** — ✓ 2026-07-14
  - `apps/api/app/modules/content/pipeline/graph.py::intervention_messages_node`
  - Model: `settings.llm_mini` (`LLM_MINI`)
  - Phase 1 — dispatched via `Send()`, once per section; per-section checkpoint
  - Output: `SegmentInterventions` — exactly 3 messages each for `distraction`, `confusion`, `fatigue`, forced via truncate/pad guard (padding-by-duplication on <3 is a documented decision, see Story 2-1 AC-5 note — not a retry loop)
  - **CRITICAL:** Pre-generated at pipeline time. Zero GPT calls at intervention runtime (PRD §10) — verified no such call exists in `modules/tutor/`.
  - **AC:** 3×3 messages generated; validates against `app.schemas.SegmentInterventions` ✓; shape-pinning test added for future `package_builder_node` (S2-11) integration — tested (`test_phase1_economy_nodes.py`, AC-5) ✅

- [x] **S2-6 `narration_generator` node** — ✓ 2026-07-14
  - `apps/api/app/modules/content/pipeline/graph.py::narration_generator_node`
  - Model: `settings.llm_mini` (`LLM_MINI`)
  - Phase 1 — dispatched via `Send()`, once per section; per-section checkpoint
  - Output: narration script + `narration_style`; pacing guard rejects a script implying >15 words/sec against a target duration (explicit `target_duration_sec` or a page-count-based estimate, ~90s/page)
  - **AC-6 note:** `narration_style` is sourced from `segment_complexity_node`'s checkpoint for the same section when it's already written (opportunistic cross-node read — the common case, since `Send()`-dispatched sibling calls don't resolve in lockstep); falls back to the LLM self-reporting a style only when complexity genuinely isn't available yet. This is a best-effort resolution of a real AC-0/AC-6 architectural conflict (Send() fan-out has no cross-node ordering guarantee) — see Story 2-1's AC-6 note for the full rationale; a guaranteed-every-run fix needs an AC-0 redesign, not done here.
  - **AC:** Script readable at ≤15 words/sec ✓ (guard now fires in both the explicit- and estimated-duration cases — 5-agent review 2026-07-14 found the original no-target-duration branch was a mathematical no-op); tone matches `narration_style` from `SegmentComplexity` when available ✓ — tested (`test_phase1_economy_nodes.py`, AC-6) ✅

---

### Learner Mode (tier-aware lessons) — inserted between Phase 1 and Phase 2

> Tier values: **T1** (full depth, 20–25 slides), **T2** (standard, 12–15 slides), **T3** (critical-topics-only / refresher, 6–8 slides). Default `T2` for any lesson that doesn't specify a tier (keeps existing frontend mocks/tests, which assume no tier, working unmodified).

- [ ] **S2-LM1 Add `tier` field to the lesson package contract + Pydantic** ⚠️ PARTIAL — 2026-07-14
  - `packages/shared/lesson_package.schema.json`, `packages/shared/types/lesson.ts`, `apps/api/app/schemas/lesson.py` (`LessonMetadata.tier`)
  - **FROZEN CONTRACT CHANGE — requires the 4-developer PR review per `CLAUDE.md` §16 / Interface Contracts before merge. Do not implement S2-LM3/S2-LM4/S2-LM5 against a local draft of this field — get the shape agreed first.**
  - ✓ `tier: Literal["T1", "T2", "T3"]` added to `LessonMetadata`; JSON schema and TS type updated in the same commit, byte-for-byte agreeing enum values (Story 2-2, `docs/stories/2-2-learner-mode-infra.md`)
  - ✓ Existing `LessonPackage`/frontend fixtures unaffected — Pydantic default (`"T2"`) meant zero backend fixtures needed updating; two frontend fixtures (`apps/web/src/mocks/data/lessonPackage.ts`, `apps/web/src/__tests__/stores/player.machine.test.ts`) needed `tier: 'T2'` added (caught by code review, fixed same day)
  - ✗ **4-dev sign-off NOT yet recorded** — this is the blocking gap. S2-LM3 was implemented then **reverted** 2026-07-14 specifically because it got ahead of this sign-off (see Story 2-2's Change Log) — do not re-attempt S2-LM3/LM4/LM5 until this AC is actually satisfied.
  - **AC:** JSON schema/TS/Pydantic agree byte-for-byte ✓; existing fixtures unaffected ✓; 4-dev sign-off recorded ✗ (blocking)

- [x] **S2-LM2 Add `tier` column to `lessons` table** — ✓ 2026-07-14
  - `supabase/migrations/20260714020000_add_lesson_tier.sql` — timestamped after the true latest applied migration at the time (`20260713020000_lesson_job_node_output_merge_fn.sql`, Story 2-1b — corrects this task's own stale `20260710000000` reference)
  - `tier text NOT NULL DEFAULT 'T2' CHECK (tier IN ('T1','T2','T3'))` on `public.lessons` — verified via static SQL-text test (`test_learner_mode_tier.py`, no live Postgres in this suite)
  - Independent of S2-LM1 — built in parallel, not reverted alongside S2-LM3/LM4
  - **AC:** Migration applies cleanly (additive, no existing migration touched) ✓; CHECK constraint rejects any value outside `T1/T2/T3` ✓; existing rows backfill to `T2` via `DEFAULT`, no manual step ✓ — tested ✅

- [ ] **S2-LM3 Accept & validate `tier` param in `POST /lessons`; thread into the ARQ job** — implemented 2026-07-14, then **REVERTED same day** pending S2-LM1's 4-dev sign-off
  - `apps/api/app/modules/content/router.py`, `apps/api/app/workers/jobs/content_pipeline.py`, `PipelineState` in `apps/api/app/modules/content/pipeline/graph.py` (add a `tier: str` field alongside the existing input keys)
  - **Depends on S2-LM1 (enum values) and S2-LM2 (column to persist to).**
  - Note (corrected by Story 2-2's Dev Notes): tier reaches the pipeline via the SAME `lessons`-table re-fetch `content_pipeline_job` already uses for `user_id`/`book_id`/`source_pdf_path` — not a new ARQ job-payload argument. This tracker's "thread into the ARQ job" wording is imprecise; update if this task is picked up again.
  - Optional multipart field `tier`, defaulting to `"T2"` when omitted; invalid value → `422`, not a silent fallback — this behavior was implemented and passed a full 3-layer adversarial code review with no unresolved functional findings, but was reverted anyway per the explicit decision to honor S2-LM1's sign-off gate rather than accept the sequencing violation.
  - **Re-pickup condition:** do not restart this task until S2-LM1's 4-dev sign-off is recorded.
  - **AC:** not yet met — reverted, not abandoned.
  - **AC:** Omitting `tier` behaves exactly as before this story (defaults `T2`); an invalid tier string returns `422`; `PipelineState["tier"]` is populated by the time `lesson_planner` runs.

- [ ] **S2-LM4 Tier-aware slide count in `lesson_planner` + `slide_generator`**
  - Amends **S2-7** and **S2-8** directly — build this together with those two nodes' base implementation, not as a follow-up rework pass.
  - Slide/segment budget by tier: **T1: 20–25**, **T2: 12–15**, **T3: 6–8**.
  - `lesson_planner` reads `state["tier"]` and targets the corresponding slide-count range when producing `LessonMetadata`/segment structure; `slide_generator` respects the resulting per-segment slide budget it's handed — it does not re-derive tier logic independently.
  - **AC:** For a fixed test chapter, three separate pipeline runs (T1/T2/T3) each produce a total slide count inside that tier's range; `slide_generator` never exceeds the budget `lesson_planner` set for a segment.

- [ ] **S2-LM5 Tier-aware content-depth prompt variants (T3 = critical topics only / refresher)** ⚠️ scope needs team confirmation
  - Amends **S2-7** (`lesson_planner`)'s prompt — and *possibly* the Phase 1 economy nodes (`quiz_generator`, `narration_generator`) if "content depth" is meant to vary per-segment rather than only at the outline level. **This ambiguity is not resolved by the source task list — confirm with the team before implementing:** does T3 only change what `lesson_planner` selects as "critical topics," or does it also mean shallower quizzes/narration per segment?
  - Default interpretation until confirmed: only `lesson_planner`'s outline-generation prompt gets a tier-conditioned variant (T3 prompt explicitly asks for critical-topics-only / refresher framing); Phase 1 economy nodes are unaffected by tier.
  - **AC (pending confirmation):** T3 lesson plans visibly omit non-critical sub-topics a T1/T2 plan for the same chapter would include; a reviewer can distinguish a T3 outline from a T1 outline for the same source chapter without reading tier metadata.

---

- [x] **S2-7 `lesson_planner` node** — ✓ 2026-07-17 (upgraded from PARTIAL now that S2-11 really validates it)
  - `apps/api/app/modules/content/pipeline/graph.py::lesson_planner_node` (NOT a separate `nodes/lesson_planner.py` file — see Story 2-1's Tracker Cross-Reference Notes on why this file-per-node table entry is stale; the placeholder row above is removed)
  - Model: `settings.llm_lesson_planner` (`LLM_LESSON_PLANNER`) — highest cost node so far
  - **Phase 2 Premium — starts ONLY after ALL Phase 1 nodes complete for ALL segments** — already true via the existing graph wiring (Story 2-1 AC-0), unchanged by this task
  - ✓ Input is `state["segment_summaries"]` ONLY — never raw chapter text/sections; enforced structurally and by a dedicated regression test (`test_prompt_never_includes_raw_chapter_text_or_sections`) that plants raw text in state alongside summaries and asserts it never reaches the prompt
  - ✓ `complete_structured()` used with an internal Pydantic response model (`_LessonPlanLLM`/`_LessonPlanSegmentLLM`); degrade-not-fabricate guards (segment count/ID match, no duplicates, non-blank title/subject/objectives, valid `duration_min`, `complexity_level` clamped to low/medium/high) all reviewed via a real 3-layer `/bmad-code-review` and patched
  - ✓ Idempotency checkpoint added (Phase-A read-then-write style, not Story 2-1b's atomic RPC — correct choice for this single-sequential-dispatch node)
  - ✓ **Output now DOES pass `LessonMetadata.model_validate()`** — resolved transitively by S2-11 (`package_builder_node`, done 2026-07-16), which projects `lesson_plan`'s `title`/`subject`/`total_segments`/`total_duration_min`/`complexity_level` into `LessonPackage.metadata` and calls `LessonPackage.model_validate(assembled)` uncaught (AC-9). `LessonMetadata.tier` defaults `"T2"` so the metadata dict — built with no `tier` key, since S2-LM1/LM3 are still reverted — validates cleanly. Confirmed via `test_package_builder_node.py::test_model_validate_failure_propagates_uncaught` and the full round-trip assertion at line 174 (`LessonPackage.model_validate(result["lesson_package"])`); full suite re-run 2026-07-17: 381 passed, 1 skipped.
  - ✗ **Langfuse span does not record an explicit `token_cost_usd` field** — `complete_structured()`'s existing tracing records `usage_details` (input/output token counts) on the generation span, and cost IS accumulated via `cost_tracker.accumulate_cost()`/`check_ceiling()`, but the two aren't joined into one named `token_cost_usd` field on the span itself. This is a pre-existing gap shared by every node using `complete_structured()`, not something specific to `lesson_planner` — **tracked as Sprint 3's S3-5 (Pipeline cost attribution in Langfuse)**, not reopened here.
  - Tier-aware slide-count targets (Epic 1's node-11 spec) are explicitly NOT part of this task — `state` has no `tier` key post-revert (Story 2-2); deferred to S2-LM4 once S2-LM1's 4-dev sign-off unblocks tier plumbing again.
  - **AC:** Input confirmed as summaries ✓ (tested); output passes `LessonMetadata` validation ✓ (resolved by S2-11, tested); Langfuse span records `token_cost_usd` ✗ (pre-existing provider-wide gap, deferred to S3-5) — see `docs/stories/2-6-lesson-planner-node.md` for the full story, including a 3-layer adversarial code review (7 patches applied, 4 pre-existing risks deferred, 297/297 tests passing)

- [x] **S2-8 `slide_generator` node** — ✓ 2026-07-15
  - `apps/api/app/modules/content/pipeline/graph.py::slide_generator_node` (NOT a separate `nodes/slide_generator.py` file — see Story 2-1's Tracker Cross-Reference Notes on why this file-per-node table entry is stale)
  - Model: `settings.llm_slide_generator` (`LLM_SLIDE_GENERATOR`) — ONE structured-output call for the whole lesson plan (not one call per segment), same cost-conscious design `lesson_planner_node` (S2-7) uses
  - Phase 2 — sequential after S2-7, consumes `state["lesson_plan"]["segments"]` only (never raw summaries/sections/chapter text — enforced structurally and by test)
  - Output: nested `{segment_id, data}` list (mirrors `quiz_generator_node`'s established pattern, Story 2-1) — `data` is `Slide.model_validate()`-checked inside this node itself, not deferred to `package_builder`
  - Degrade-not-fabricate guards (segment count/ID match, no duplicates, 1-8 slides/segment, non-blank titles, non-blank bullets — including per-bullet blank checks and malformed-entry guards added in the 2026-07-15 code review round) all reviewed via a real 3-layer `/bmad-code-review` (orchestrated via multi-agent Workflow) and patched
  - Idempotency checkpoint (Phase-A style, same as `lesson_planner_node`)
  - Tier-aware slide-count targets (Epic 1's node-12 spec) explicitly NOT part of this task — fixed 1-8 slides/segment band, same reasoning as S2-7; deferred to S2-LM4 once S2-LM1's 4-dev sign-off unblocks tier plumbing again
  - **AC:** Output validates against `app.schemas.Slide` ✓ (tested); at least 1 (and at most 8) slide per segment ✓ (tested); `image_url`/`fallback_image_url` both nullable, always `None` at this node (images filled by S2-10) ✓ — see `docs/stories/2-7-slide-generator-node.md` for the full story, including the 3-layer adversarial code review (5 patches applied, 3 pre-existing risks deferred, 314/314 tests passing) ✅

- [x] **S2-9 `tts_node` — Sarvam AI Bulbul v2 + Azure TTS + Browser fallback** — ✓ 2026-07-15
  - `apps/api/app/modules/content/pipeline/graph.py::tts_node` (NOT a separate `nodes/tts_node.py` file — see Story 2-1's Tracker Cross-Reference Notes) + new `apps/api/app/providers/tts/sarvam.py`/`azure.py`
  - Phase 3 Media node — **banned `providers/tts/elevenlabs.py` deleted as part of this story** (ElevenLabs REMOVED 2026-06-25; the dead file had lingered in the repo until now)
  - Fallback chain: Sarvam AI Bulbul v2 → Azure TTS → Browser Speech, real HTTP calls via `httpx.AsyncClient`, each with its own circuit-breaker key (`"sarvam"`/`"azure_tts"`) and `@with_retry(max_attempts=3)`. Sarvam's 429 response body is inspected: `insufficient_quota_error` is non-retryable, anything else (e.g. `rate_limit_exceeded_error`) is retried normally.
  - Each segment's narration script → `.mp3` uploaded to the private `lesson-audio` Supabase Storage bucket (`upsert: true`, added during code review) at `{lesson_id}/{segment_id}.mp3`; `Narration.audio_url` set to that storage path (never a public URL)
  - `is_circuit_open()` wired before every provider call; fallback genuinely never hard-fails — a 3-layer adversarial `/bmad-code-review` caught that the ORIGINAL implementation's "never hard-fails" claim only covered the synthesis call itself, not the surrounding per-segment loop (storage upload, malformed-entry indexing) — fixed with a per-segment `try/except` that degrades just that one segment to browser fallback on any failure, never crashing the whole node
  - TTS cost included in `cost_tracker.accumulate_cost()` via a documented flat per-character estimate (neither vendor's exact billing API is verifiable from this environment — flagged for a future story to replace with real invoiced numbers)
  - Word-to-slide audio timestamps explicitly NOT implemented — `Narration.timestamps` ships `[]` for every segment; the tracker's own AC below doesn't require them, and no established slide-mapping heuristic exists yet (deferred to a follow-up story)
  - **AC:** Audio file produced per segment ✓; URL in `Narration.audio_url` ✓; `audio_provider` set to `"sarvam"`/`"azure"`/`"browser"` ✓; pipeline never fails over TTS ✓ (tested, including the code-review round's per-segment degrade fix) — see `docs/stories/2-8-tts-node.md` for the full story, including the adversarial review (7 patches applied, 1 pre-existing risk deferred, 333/333 tests passing) ✅

- [x] **S2-10 `image_generator` node — GPT Image 1 Mini + Imagen 4 Fast + text-only fallback** — ✓ 2026-07-15
  - `apps/api/app/modules/content/pipeline/nodes/image_generator.py` (real implementation inline in `graph.py`, per repo convention)
  - Phase 3 Media node
  - **DALL-E 3 REMOVED — shut down May 2026. Stack: GPT Image 1 Mini → Imagen 4 Fast → text-only** — `apps/api/app/providers/image/dalle.py` deleted, real `OpenAIImageProvider`/`ImagenProvider` added
  - Fall back to `image_url = None` (text-only) if cost ceiling is near — never fail the pipeline over images — proactive per-slide `check_ceiling()` pre-check implemented
  - Image cost included in `cost_tracker.accumulate_cost()` — called from `image_generator_node` itself, only after a successful Storage upload (moved out of the providers during code review — see below)
  - **AC:** Image URL or `None` set on each slide ✓ (tested); pipeline completes if all image providers fail ✓ (tested, per-slide try/except); cost tracked ✓ (tested, only after successful upload) — see `docs/stories/2-9-image-generator-node.md` for the full story, including the 3-layer adversarial code review (9 patches applied — 1 CRITICAL API-key-leak, 2 HIGH cost-accumulation race, plus a newly-discovered `app/core/retry.py` bug fixed in the same round — 356 tests, 355 passing + 1 pre-existing unrelated skip) ✅

- [x] **S2-11 `package_builder` node → JSONB write** — ✓ 2026-07-16
  - `apps/api/app/modules/content/pipeline/graph.py::package_builder_node` (real implementation inline, per repo convention)
  - Phase 3 final node — assembles all prior node outputs
  - ✓ 1. `LessonPackage` built from accumulated `state` outputs — per-segment correlation across all 6 upstream node outputs by `segment_id` (`slide_images` by `slide_id` separately, its own deliberately flat shape); a segment missing required data is skipped with a warning, not a crash; `RuntimeError` if every segment gets skipped.
  - ✓ 2. `LessonPackage.model_validate(assembled)` called uncaught — raises immediately if schema violated (tested).
  - ✓ 3. `lessons.content = package.model_dump(mode="json")`; `lessons.status = 'ready'`; `lessons.title` also populated (first node in the pipeline to write to `lessons` at all).
  - ✓ 4. `lesson_jobs.status = 'completed'`; `completed_at` set (ISO-8601 UTC) — the pre-existing `_update_job_progress()` helper could never do this (only ever sets `status="running"`); the stub's previous final call was a latent bug (would have reset status back to "running") and has been removed.
  - 5. **WebSocket `lesson_ready` push is S2-12's own scope, not S2-11's** (see S2-12's tracker entry below — "coordinate with Dev 4 before implementing"). This story's scope note treats S2-11 and S2-12 as distinct, not-overlapping work, so S2-11 is complete without it.
  - **Frozen-contract change, flagged for 4-dev sign-off (PRD §16), mirroring S2-LM1's precedent:** `Slide.image_url`/`fallback_image_url` relaxed from `AnyHttpUrl` to `str` in `app/schemas/lesson.py` + `packages/shared/lesson_package.schema.json` — both fields now store the bare Supabase Storage path, not a signed URL (baking a signed URL into stored JSONB would silently expire before a lesson is necessarily viewed; resolving paths to fresh signed URLs at lesson-view time is a separate, not-yet-built component's job).
  - **`teachback_prompt` is a PROVISIONAL placeholder** (deterministic template, no LLM call) — no node in the 15-node pipeline generates a real teach-back prompt; this is pending confirmation from whoever owns the teach-back feature (Dev 3 — Quiz API, teachback scorer, CES formula, Learner DNA per team ownership).
  - **AC:** `lessons.content` valid JSONB ✓ (tested); `LessonPackage.model_validate(row["content"])` round-trip passes ✓ (tested); `lessons.status = 'ready'` ✓ (tested); `lesson_ready` WebSocket push — out of scope for S2-11, see S2-12 below — see `docs/stories/2-11-package-builder-node.md` for the full story, including the 3-layer adversarial code review (5 patches applied — defensive `.get()` lookups replacing crash-prone direct subscripting, duplicate/orphaned-segment_id warning logging, 6 new coverage tests — plus 2 findings correctly deferred with documented rationale, 381/382 tests passing) ✅

- [x] **S2-12 WebSocket `lesson_ready` push — coordinate with Dev 4** — ✓ 2026-07-16
  - **Discovery: this infrastructure already existed, built by Dev 4** (`4534078 fix(arq): lesson_ready via Redis pub/sub`) — `apps/api/app/core/pubsub.py` (Redis pub/sub subscriber → `ConnectionManager.send()`) already wired into `app/main.py`'s lifespan, and `apps/api/app/workers/jobs/content_pipeline.py::content_pipeline_job` already published to `lesson_ready:{session_id}`. S2-12 turned out to be a reconciliation/bug-fix story against Story 2-11's landing, not new infrastructure.
  - ✓ **Real bug fixed:** `package_summary`'s `slides_count`/`quiz_count`/`audio_count` had silently reported `0`/`0`/`0` for every successful lesson since S2-11 landed — the code read top-level `slides`/`quiz_questions`/`audio_assets` keys that only existed on the old flat stub shape (S2-11's real `LessonPackage` nests all three inside each segment). Fixed to aggregate from `segments[].slides`/`.quiz`, with `audio_count = len(segments)`.
  - ✓ **Frozen-contract deviation fixed:** the published payload had an extra `session_id` key not present in `ws.ts`'s `LessonReadyMessage` type (`{lesson_id, lesson}` only). Removed — confirmed the subscriber only ever extracted `session_id` from the channel name, never the payload, so this was pure redundancy, never load-bearing.
  - `session_id` fallback (`lesson_row.get("session_id") or lesson_id`) is UNCHANGED and confirmed correct — no `sessions`-table column exists on `lessons` yet, so this remains the only path in practice; building real session-tracking stays out of scope pending genuine Dev 4 coordination.
  - Shape must match `packages/shared/types/ws.ts` discriminated union exactly — ✓ confirmed (payload is now byte-for-byte `LessonReadyMessage`'s type).
  - Triggered by `package_builder` (S2-11) on success — ✓ (pre-existing wiring, confirmed still correct).
  - **AC:** Frontend receives `lesson_ready` ✓ (pre-existing, Dev 4's wiring); message passes TS discriminated-union type check ✓ (payload now matches exactly, extra key removed); no shape mismatch with Dev 4 handler ✓ — see `docs/stories/2-12-lesson-ready-websocket-push.md` for the full story, including the 3-layer adversarial code review (4 patches applied — defensive guard against a crash-after-publish failure mode, 2 new coverage tests, 1 documentation correction — plus 2 findings correctly dismissed as verified-honest/not-a-defect, 942 tests passing) ✅

- [x] **S2-13 Cost ceiling enforcement wired into all nodes** — ✓ 2026-07-17
  - `apps/api/app/core/cost_tracker.py` — wire into every LLM, TTS, image call
  - `MAX_LESSON_COST_USD = settings.max_lesson_cost_usd` (default `$3.00`)
  - ✓ `lesson_planner_node`/`slide_generator_node` (S2-7/S2-8) now check `check_ceiling()` before dispatch — on breach, downshift from the premium model (`llm_lesson_planner`/`llm_slide_generator`) to `llm_mini` rather than aborting. `tts_node` (S2-9) checks per segment — on breach, skips Sarvam/Azure entirely and degrades straight to the free browser fallback. `image_generator_node` (S2-10) already had this (Story 2-9 AC-3) — verified unchanged. New `_record_cost_downshift()` helper writes a durable `{node, from, to, at}` trail into `lesson_jobs.node_outputs["_cost_downshifts"]` for the future S3-4 admin panel to read.
  - ✓ Story 2-1 AC-7's Phase 1 pre-dispatch gate (`_fan_out_phase1_economy_nodes`) is **explicitly and deliberately left unchanged** — `llm_mini` is already the cheapest configured LLM tier, so there is nothing to downshift Phase 1 economy nodes *to*; terminate-and-flag remains the accepted behavior there (documented as a known, accepted gap against CLAUDE.md §14's literal "never abort" wording, not something silently left inconsistent — see Story 2-13's Dev Notes).
  - Code review (3-layer adversarial, Blind Hunter + Edge Case Hunter + Acceptance Auditor) caught and fixed 2 real HIGH-severity bugs before merge: `_record_cost_downshift`'s own DB write was silently clobbered by each node's own subsequent final checkpoint write (defeating the downshift-recording AC on the very request meant to demonstrate it) — fixed by converting it to a pure in-memory merge; and `check_ceiling()` in the two new LLM-node call sites had no fail-open guard (a transient Redis error would have crashed the node) — fixed to match the existing fail-open pattern used everywhere else in the file.
  - No admin panel exists yet (S3-4, Sprint 3, not started) — "flag in admin" is satisfied today via the durable `_cost_downshifts` JSONB trail, not a literal UI.
  - **AC:** A test run over the cost ceiling completes each of the 4 premium/media nodes without crashing ✓ (tested); cost tracked in `lesson_jobs.cost_usd` (unchanged, already done) ✓; downshift recorded for future admin visibility ✓ (tested, survives the node's own final checkpoint write) — see `docs/stories/2-13-cost-ceiling-enforcement.md` for the full story, including the 3-layer adversarial code review (2 HIGH patches applied, 3 LOW patches applied, 5 findings correctly dismissed with rationale). 947/995 tests passing, 48 pre-existing unrelated failures (unchanged baseline), 2 skipped — 0 regressions.

- [x] **S2-14 Eval harness — 5 PDFs** — ✓ 2026-07-17
  - `apps/api/tests/evals/scoring.py` (rule-based slide-quality/quiz-relevance heuristics), `apps/api/tests/evals/runner.py` (drives one PDF through the real `run_pipeline()`, validates + scores + records to Langfuse + cleans up), `apps/api/tests/evals/test_live_run.py` (the actual live entry point), `apps/api/tests/fixtures/generate_eval_pdfs.py` (synthetic PDF generator, `fpdf2` new dev-only dependency)
  - **No real representative textbook PDFs were available in this session** — 5 synthetic PDFs generated deterministically instead (short=3pp, long=120pp, dense_text=15pp, table_heavy=8pp/3 tables-per-page, image_heavy=10pp/4 synthetic images-per-page). PDFs themselves are NOT committed — a pre-existing Sprint 0 `.gitignore` rule (`tests/fixtures/eval_pdfs/*.pdf`) already excluded them, discovered (not created) during this story; only the generator is committed, and it's re-runnable to regenerate them locally.
  - Scoring is explicitly rule-based/heuristic (documented honestly as such), not LLM/semantic — spends zero additional LLM budget scoring an already-completed lesson, consistent with the project's cost discipline.
  - **The actual live 5-PDF pipeline run was explicitly NOT executed** — a deliberate scope decision made with the user before implementation (real OpenAI/Sarvam/Azure/Supabase cost + up to ~15 min/lesson × 5). The harness is fully built and unit-tested (16 offline tests, zero live calls); gated behind a new `live_eval` pytest marker + `--run-live-eval` flag (scoped to `tests/evals/conftest.py`, not a global `pyproject.toml` addopts change — a code-review finding caught and reverted an initial version that did touch global config without team sign-off). **Trigger it when ready:** `pytest apps/api/tests/evals/test_live_run.py -v --run-live-eval` (requires live credentials already in `.env`).
  - Code review (3-layer adversarial) caught and fixed 5 real issues before merge, most notably: a slide-count band violation that was logged but never actually lowered the score; two places where `run_eval()`'s own "never raises" contract was violated by unguarded checks outside its try block; `run_all_evals()` having no per-PDF exception isolation around `run_eval()` itself (would have discarded all results on any future bug); and — most operationally important — no cleanup of the `books`/`lessons`/`lesson_jobs` rows or Storage object each eval run created, meaning every run (pass or fail) would have permanently accumulated orphaned test data in Supabase.
  - **AC:** All 5 synthetic PDFs produce a valid `LessonPackage` when run live (not yet verified — deferred to the user's live trigger, see above); no pipeline crash — per-PDF failure isolation is unit-tested ✓; per-lesson scores recorded to Langfuse via `start_observation()`/`score_trace()`/`.end()` (verified against the installed v4 SDK, not guessed) ✓ — see `docs/stories/2-14-eval-harness-5-pdfs.md` for the full story, including the 3-layer adversarial code review (8 patches applied — 5 HIGH, 3 LOW — plus 4 findings correctly dismissed with documented rationale). 963/1014 tests passing, 48 pre-existing unrelated failures (unchanged baseline), 3 skipped — 0 regressions.

- [x] **S2-15 LLM provider factory — model-agnostic dispatch (MANDATORY refactor)** — ✓ 2026-07-16
  - `apps/api/app/providers/llm/factory.py` (new) — `get_llm_provider(model, lesson_id=None) -> LLMProvider`
  - **Why:** all 9 economy/premium node call sites in `graph.py` hardcoded `from app.providers.llm.openai import OpenAILLMProvider` directly — `settings.llm_mini`/`settings.llm_lesson_planner`/etc. were env-var-driven for the MODEL STRING, but the PROVIDER CLASS was not selectable at all. CLAUDE.md's "swapping models is an env var change only" claim was only true within OpenAI's own model lineup — pointing `LLM_MINI` at a non-OpenAI model (Gemini, Claude) would have broken at request time. This refactor makes provider selection itself config-driven, in-process (no new service/deploy) — a future new provider (Gemini, Claude, etc.) now requires writing one file + one registry entry, zero node call-site changes.
  - ✓ Factory dispatches by model-name prefix (`"gpt-"`/`"o1-"`, both routed to `OpenAILLMProvider`); lazy per-branch import deliberately preserved (mirrors every node's pre-existing pattern) — this is what made the migration a genuinely zero-test-file-touched refactor: **0 of the ~98 informally-estimated test references actually needed a patch-target change**, confirmed by running the full suite immediately after migration, before touching any test file.
  - ✓ All 9 `graph.py` call sites migrated (`structure_node`, `lesson_planner_node`, `slide_generator_node`, `summarise_segment_node`, `quiz_generator_node`, `segment_complexity_node`, `jargon_extractor_node`, `intervention_messages_node`, `narration_generator_node`) — confirmed via grep, zero `OpenAILLMProvider` references remain in `graph.py`.
  - Does NOT include writing a second provider (Gemini/Claude) — stays deferred until actually needed for an eval. Also does NOT cover 3 additional hardcoded call sites discovered in the `assessment/` module (`dna_profile.py`, `service.py` — Dev 3's owned territory, out of this story's scope) — flagged as a deferred review finding for whoever owns that module next.
  - **AC:** `get_llm_provider()` returns a correctly-typed `LLMProvider` for every currently-supported model string ✓ (tested, including the `o1-mini` edge case found in review); all 9 `graph.py` call sites migrated ✓ (verified via grep); unknown/unregistered/non-string model raises a clear `ValueError` ✓ (tested); zero behavior change ✓ (364/365 tests passing, only patch-round additions, no existing test logic changed) — see `docs/stories/2-15-llm-provider-factory.md` for the full story, including the 3-layer adversarial code review (4 patches applied — 2 HIGH, 2 MEDIUM/LOW — 1 HIGH finding deferred as cross-module scope, 1 LOW dismissed as unrelated pre-existing clutter) ✅

---

## Sprint 3 — Weeks 6–7 (Due: ~2026-07-30)

> **Goal:** Production quality — eval harness at scale, full observability, admin panel live.

- [ ] **S3-1 Eval harness expanded to 20 PDFs**
  - `apps/api/tests/evals/`
  - Cover all failure modes: dense text, table-heavy, image-heavy, short (≤10 pages), long (≥100 pages)
  - **AC:** All 20 PDFs produce valid `LessonPackage`; no pipeline crash; scores tracked in Langfuse

- [ ] **S3-2 Prompt iteration from eval results**
  - `apps/api/app/modules/content/pipeline/nodes/` — prompt strings only
  - Data-driven only: track before/after Langfuse scores; change only prompts that show ≥5% regression or improvement
  - **AC:** At least one node prompt improved; before/after scores committed to Langfuse; no blind prompt edits

- [x] **S3-3 Circuit breaker implementation** — ✓ 2026-06-12 (built ahead of schedule)
  - `apps/api/app/core/circuit_breaker.py`
  - 5 failures / 2 min → OPEN; 10 min → HALF_OPEN probe; state in Redis
  - **Wire into ALL Sprint 2 provider calls immediately — do not wait until Sprint 3**
  - **AC:** `is_circuit_open()` / `record_failure()` / `record_success()` callable by all providers; state persists across restarts via Redis ✅

- [ ] **S3-4 Admin panel: job status, cost tracking, failed jobs**
  - `apps/api/app/modules/admin/router.py` *(to create)*
  - Endpoints: `GET /api/admin/jobs`, `POST /api/admin/jobs/{job_id}/retry`, `GET /api/admin/costs`
  - **AC:** All jobs listable with status + cost; failed jobs retryable via single API call; cost per lesson and per user visible

- [ ] **S3-5 Pipeline cost attribution in Langfuse**
  - All pipeline nodes — each Langfuse span must include `token_cost_usd` in metadata
  - **AC:** Langfuse dashboard shows cost breakdown per node per lesson; no node missing cost attribution

---

## Sprint 4 — Weeks 8–9 (Due: ~2026-08-13)

> **Goal:** Load-tested, rate-limited, RLS-audited, Stripe-ready, runbook written.

- [ ] **S4-1 Load test: 50 concurrent lesson generations**
  - Use `locust` or `k6`
  - Assert: P99 enqueue latency <500ms; pipeline completion within SLA (≤15 min per lesson)
  - **AC:** 50 concurrent jobs complete without crash; no Redis drops; cost ceiling respected under load; results documented

- [ ] **S4-2 Pipeline reliability fixes from test sessions**
  - Prioritize: retry exhaustion, cost ceiling mid-flight, Redis connection drops, node timeout under load
  - **AC:** All failure modes from S4-1 resolved; no silent failures in production

- [ ] **S4-3 Stripe Checkout integration**
  - Hosted Stripe Checkout page only — no custom payment UI in MVP
  - **AC:** User completes a purchase; Stripe webhook updates user access tier in DB

- [ ] **S4-4 Rate limiting — per-route limits** ⚠️ PARTIAL
  - `apps/api/app/main.py` — `slowapi` middleware mounted ✓
  - Per-route limits not yet configured on pipeline endpoints ✗
  - Apply `"5/minute"` per-user limit on `POST /api/content/lessons`
  - **AC:** Exceeding 5 uploads/minute returns `429` with `Retry-After` header; limit is per-user (JWT sub), not global IP

- [ ] **S4-5 RLS security audit on all Supabase tables**
  - All tables have RLS enabled (verified in migrations)
  - Verify policies: users can only read/write their own rows; `attention_events` gates on `users.attention_consent = true`
  - Verify no table is readable without an authenticated JWT
  - **AC:** Audit report committed to `docs/`; no table accessible without RLS; `attention_consent` gate verified

- [ ] **S4-6 Railway backups + disaster recovery tested**
  - Test restore from latest backup; validate data integrity post-restore
  - **AC:** Recovery procedure documented; restore completes in <30 min; data integrity confirmed

- [ ] **S4-7 On-call runbook written**
  - `docs/` — 5 most likely failure scenarios with step-by-step resolution
  - Scenarios: ARQ job stuck, cost ceiling breach mid-pipeline, Redis unreachable, Supabase down, pipeline node 500-loop
  - **AC:** Runbook committed; each scenario has ≤5 resolution steps; tested by a teammate who didn't write it

---

## Week 10 — Launch (Due: ~2026-08-20)

> **Goal:** First paying student completes a full session without manual intervention.

- [ ] **W10-1 Production deployment verified end-to-end**
  - **AC:** Full lesson pipeline runs in production with a real PDF; lesson plays in browser for a real user

- [ ] **W10-2 Monitoring dashboards live**
  - Langfuse (pipeline costs + traces), Sentry (errors), Railway (infra + Redis)
  - **AC:** All three dashboards populated; alerts configured for pipeline failures and cost ceiling breaches

- [ ] **W10-3 On-call rotation established**
  - **AC:** All 4 devs on rotation schedule; runbook link shared with all

- [ ] **W10-4 First paying user pipeline job monitored live**
  - **AC:** Real user, real PDF, real payment — pipeline completes without manual intervention; CES data flows to Dev 3

---

## Ahead-of-Schedule Wins

| Item | Built | Intended Sprint | Action Now |
|------|-------|----------------|------------|
| `core/retry.py` — `with_retry()` | Sprint 0 | Sprint 1 (S1-1) | Apply to all Sprint 1 nodes immediately ✅ |
| `core/circuit_breaker.py` | Sprint 0 | Sprint 3 (S3-3) | Wire into ALL Sprint 2 provider calls — do not wait |
| `core/cost_tracker.py` | Sprint 0 | Sprint 2 (S2-13) | Wire into each LLM/TTS/image node as Sprint 2 nodes are built |
| `slowapi` middleware | Sprint 0 | Sprint 4 (S4-4) | Add per-route limit to `POST /api/content/lessons` in Sprint 1 (S1-10) |

---

## Frozen Contracts (PRD §16)

| Contract | File | Status |
|----------|------|--------|
| Lesson package schema | `packages/shared/lesson_package.schema.json` | ✅ Frozen — 4-dev PR to change |
| TypeScript lesson types | `packages/shared/types/lesson.ts` | ✅ Frozen |
| WebSocket discriminated union | `packages/shared/types/ws.ts` | ✅ Frozen |
| Assessment API (OpenAPI) | Auto-generated from FastAPI routes | ✅ Frozen |
| DB migrations | `supabase/migrations/` | ✅ Never modify applied |

---

## Security Checklist (PRD §18)

| Item | Status | Notes |
|------|--------|-------|
| JWT verified locally (PyJWT + `SUPABASE_JWT_SECRET`) | ✅ | `dependencies.py` — no remote call per request |
| RLS enabled on all Supabase tables | ✅ | Enabled in both migrations; full audit due Sprint 4 (S4-5) |
| Env vars never committed | ✅ | `.gitignore` covers all `.env*` patterns |
| `attention_events` RLS gates on `attention_consent = true` | ✅ | Enforced in migration 20260611 policy |
| Raw webcam video never leaves browser | N/A | Dev 2 owns — verify in integration review |
| No clinical score fields in API responses | ⬜ | Ensure no `iq_score`, `eq_score` fields in any `LessonPackage` or API response; DPDP Act 2023 |

---

## Module Ownership Reference

| Module | Dev 1 Touches? | Notes |
|--------|---------------|-------|
| `core/` | ✅ Owner | retry, circuit_breaker, cost_tracker, redis, db, langfuse |
| `providers/` | ✅ Owner | llm, tts, image, avatar — abstract interfaces + implementations |
| `modules/content/` | ✅ Owner | pipeline nodes, router |
| `workers/` | ✅ Owner | ARQ entry, job registry |
| `modules/tutor/` | Dev 4 | Do not modify — review only |
| `modules/assessment/` | Dev 3 | Do not modify |
| `apps/web/` | Dev 2 | Do not modify |
| `supabase/migrations/` | Dev 1 authors | All 4 devs must review migration PRs |

---

## Update Protocol

1. Change `- [ ]` → `- [x]`
2. Append ` — ✓ YYYY-MM-DD` to the task title line
3. Update the **Quick Status Dashboard** table at the top (increment Done, decrement Not Started or Partial)
4. Update **Last updated** in the header block

**Example — task just completed:**
```markdown
- [x] **S1-2 PyMuPDF text + image + layout extraction node** — ✓ 2026-06-28
```

**Example — task partially done:**
```markdown
- [ ] **S0-9 Langfuse wired globally** ⚠️ PARTIAL
  - ✓ Traces emitted per-call
  - ✗ No global flush on shutdown
```

Do not delete task details after completion — they serve as a specification record.
