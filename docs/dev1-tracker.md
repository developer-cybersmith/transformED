# Dev 1 Sprint Tracker — TransformED AI

**Owner:** Dev 1 (developer1-cybersmith) — developer.team2@cybersmithsecure.com
**Domain:** Infra · Content Pipeline (11 nodes) · Provider Abstraction · Embeddings · Langfuse
**PRD:** 1.0 Final (10 June 2026) + Decisions Update (25 June 2026) — `CLAUDE.md` is source of truth
**Last updated:** 2026-07-13
**Sprint 0 status:** 12/12 COMPLETE ✅
**Sprint 1 status:** 10/10 COMPLETE ✅ — merged to `main` 2026-07-13 (PR #72). Includes Tier-1/Tier-2 hardening plus Story 2-0b (page-scoped docling + extraction performance). Sprint 2 (11 lesson-generation nodes) starts next — see Sprint 2 section below. Frontend/assessment/tutor teams should keep building against `apps/web/src/mocks/data/lessonPackage.ts` and test fixtures until `package_builder` (S2-11) lands; do not build a parallel real-content path.

---

## Quick Status Dashboard

> Update this table each time a task is checked off below.

| Sprint | Period | Tasks | Done | Partial | Not Started |
|--------|--------|------:|-----:|--------:|------------:|
| Sprint 0 | Week 1 (Jun 12–18) | 12 | 12 | 0 | 0 |
| Sprint 1 | Weeks 2–3 (Jun 19 – Jul 2) | 10 | 10 | 0 | 0 |
| Sprint 2 | Weeks 4–5 (Jul 3–16) | 20 | 2 | 1 | 17 |
| Sprint 3 | Weeks 6–7 (Jul 17–30) | 5 | 1 | 0 | 4 |
| Sprint 4 | Weeks 8–9 (Jul 31 – Aug 13) | 7 | 0 | 1 | 6 |
| Week 10 | Aug 14–20 | 4 | 0 | 0 | 4 |
| **Totals** | | **58** | **25** | **2** | **31** |

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
| `apps/api/app/modules/content/pipeline/graph.py` | LangGraph graph wired (node functions not yet created) |
| `apps/api/app/modules/content/pipeline/nodes/__init__.py` | Node package (individual node files not yet created) |
| `apps/api/app/schemas/__init__.py` | **EMPTY — awaiting `lesson.py` (S0-12)** |
| `apps/api/app/workers/main.py` | ARQ `WorkerSettings` entry point |
| `apps/api/app/workers/jobs/content_pipeline.py` | ARQ content pipeline job skeleton |
| `.github/workflows/ci.yml` | CI: lint + test on every PR |
| `.github/workflows/deploy.yml` | Deploy: Railway on merge to main |
| `railway.toml` | Railway service config |
| `supabase/migrations/20260611000000_initial_schema.sql` | Initial DB schema — **APPLIED, NEVER MODIFY** |
| `supabase/migrations/20260625000000_chunks_inline_embedding.sql` | Inline embeddings + books table — **APPLIED, NEVER MODIFY** |

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
| `apps/api/app/modules/content/pipeline/nodes/lesson_planner.py` | Lesson planning — GPT-4o *(S2-7)* |
| `apps/api/app/modules/content/pipeline/nodes/slide_generator.py` | Slide generation — GPT-4o *(S2-8)* |
| `apps/api/app/modules/content/pipeline/nodes/tts_node.py` | TTS: Sarvam → Azure → Browser *(S2-9)* |
| `apps/api/app/modules/content/pipeline/nodes/image_generator.py` | Images: GPT Image 1 Mini → Imagen 4 Fast → text-only *(S2-10)* |
| `apps/api/app/modules/content/pipeline/nodes/package_builder.py` | Assemble + write JSONB LessonPackage *(S2-11)* |
| `supabase/migrations/{new-timestamp}_add_lesson_tier.sql` | `lessons.tier` column, enum-constrained *(S2-LM2)* |
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
| `tier` | `text` | **PENDING — S2-LM2, not yet migrated.** Planned: NOT NULL DEFAULT `'T2'`, CHECK IN (`'T1'`,`'T2'`,`'T3'`) | Learner Mode content-depth tier; drives slide count + content depth in `lesson_planner`/`slide_generator` (S2-LM4/S2-LM5) |
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

- [ ] **S2-1 `summarise_segment` node** ⚠️ PARTIAL — 2026-07-13
  - `apps/api/app/modules/content/pipeline/graph.py::summarise_segment_node` (NOT a separate `nodes/summarise_segment.py` file — see Story 2-1's Tracker Cross-Reference Notes on why this file-per-node table entry is stale)
  - Model: `settings.llm_mini` (`LLM_MINI`)
  - Phase 1 — dispatched via `Send()`, once per section (graph-level fan-out, see AC-0 below)
  - ✓ Produces a 2–3 sentence, ≤100-word summary per section, calling `OpenAILLMProvider.complete_structured()` — real implementation, tested (`test_phase1_economy_nodes.py`, AC-1)
  - ✗ `lesson_planner` (S2-7) does not yet actually consume these summaries for real generation — it's still a stub that only reads `len(segment_summaries)` to prove the wiring works. The 5×-token-savings half of this AC is not yet realized (blocked on S2-7, not yet started)
  - **AC:** Summary ≤100 words ✓; `lesson_planner` (S2-7) consumes summaries not raw text — 5× token savings enforced ✗ (pending S2-7)

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
  - Applied to `summarise_segment_node`/`segment_complexity_node` (S2-1/S2-2, the only 2 of 6 economy nodes implemented so far) — S2-3 through S2-6 must adopt the same pattern when built
  - **AC:** simulated retry after partial completion makes 0 duplicate LLM calls for already-completed sections ✓ — tested (`test_phase1_checkpoint_idempotency.py`, 9 tests incl. a real `asyncio.gather` concurrency test) ✅

- [ ] **S2-3 `quiz_generator` node**
  - `apps/api/app/modules/content/pipeline/nodes/quiz_generator.py`
  - Model: `settings.llm_mini` (`LLM_MINI`)
  - Phase 1 — parallel
  - Output: list of `QuizQuestion`; each must have exactly 4 options, `correct_index` in range, difficulty set
  - **AC:** Output validates against `app.schemas.QuizQuestion`; `min_length=4` on options enforced; matches quiz schema in `lesson_package.schema.json`

- [ ] **S2-4 `jargon_extractor` node**
  - `apps/api/app/modules/content/pipeline/nodes/jargon_extractor.py`
  - Model: `settings.llm_mini` (`LLM_MINI`)
  - Phase 1 — parallel
  - Output: list of `JargonEntry` with `term` + `definition`
  - **AC:** Output validates against `app.schemas.JargonEntry`; no empty terms or definitions

- [ ] **S2-5 `intervention_messages` node**
  - `apps/api/app/modules/content/pipeline/nodes/intervention_messages.py`
  - Model: `settings.llm_mini` (`LLM_MINI`)
  - Phase 1 — parallel
  - Output: `SegmentInterventions` — exactly 3 messages each for `distraction`, `confusion`, `fatigue`
  - **CRITICAL:** Pre-generated at pipeline time. Zero GPT calls at intervention runtime (PRD §10).
  - **AC:** 3×3 messages generated; validates against `app.schemas.SegmentInterventions`; runtime callers read from `LessonPackage.segments[n].interventions` — no LLM calls possible at runtime

- [ ] **S2-6 `narration_generator` node**
  - `apps/api/app/modules/content/pipeline/nodes/narration_generator.py`
  - Model: `settings.llm_mini` (`LLM_MINI`)
  - Phase 1 — parallel
  - Output: narration script string; conversational tone; respects `complexity.narration_style`
  - **AC:** Script readable at ≤15 words/sec; tone matches `narration_style` from `SegmentComplexity`

---

### Learner Mode (tier-aware lessons) — inserted between Phase 1 and Phase 2

> Tier values: **T1** (full depth, 20–25 slides), **T2** (standard, 12–15 slides), **T3** (critical-topics-only / refresher, 6–8 slides). Default `T2` for any lesson that doesn't specify a tier (keeps existing frontend mocks/tests, which assume no tier, working unmodified).

- [ ] **S2-LM1 Add `tier` field to the lesson package contract + Pydantic**
  - `packages/shared/lesson_package.schema.json`, `packages/shared/types/lesson.ts`, `apps/api/app/schemas/lesson.py` (`LessonMetadata.tier`)
  - **FROZEN CONTRACT CHANGE — requires the 4-developer PR review per `CLAUDE.md` §16 / Interface Contracts before merge. Do not implement S2-LM3/S2-LM4/S2-LM5 against a local draft of this field — get the shape agreed first.**
  - `tier: Literal["T1", "T2", "T3"]` added to `LessonMetadata`; JSON schema and TS type updated in the same PR (never let them drift).
  - **AC:** All three artifacts (JSON schema, TS type, Pydantic model) agree byte-for-byte on the enum values; existing `LessonPackage` test fixtures updated (either given an explicit tier or the model defaults `T2`) so no existing round-trip test breaks; 4-dev sign-off recorded in the PR description.

- [ ] **S2-LM2 Add `tier` column to `lessons` table**
  - New file under `supabase/migrations/` — assign a real, correctly-ordered timestamp prefix at creation time; do not reuse or backdate an existing migration's timestamp, and never modify an already-applied migration (`20260611000000_initial_schema.sql`, `20260625000000_chunks_inline_embedding.sql`, etc. stay untouched).
  - `tier text NOT NULL DEFAULT 'T2' CHECK (tier IN ('T1','T2','T3'))` on `public.lessons`.
  - Independent of S2-LM1 — can be built in parallel, not sequentially after it.
  - **AC:** Migration applies cleanly against the current schema; CHECK constraint rejects any value outside `T1/T2/T3`; existing rows (pre-migration) backfill to the `T2` default without a manual data migration step.

- [ ] **S2-LM3 Accept & validate `tier` param in `POST /lessons`; thread into the ARQ job**
  - `apps/api/app/modules/content/router.py`, `apps/api/app/workers/jobs/content_pipeline.py`, `PipelineState` in `apps/api/app/modules/content/pipeline/graph.py` (add a `tier: str` field alongside the existing input keys)
  - **Depends on S2-LM1 (enum values) and S2-LM2 (column to persist to).**
  - Optional multipart field `tier`, defaulting to `"T2"` when omitted (existing Sprint 1 upload flow and frontend mocks must keep working unchanged); invalid value → `422`, not a silent fallback.
  - Written to `lessons.tier` at creation time; passed through the ARQ job payload into `PipelineState["tier"]` so S2-7/S2-8 can read it without a second DB round-trip.
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

- [ ] **S2-7 `lesson_planner` node**
  - `apps/api/app/modules/content/pipeline/nodes/lesson_planner.py`
  - Model: `settings.llm_lesson_planner` (`LLM_LESSON_PLANNER`) — highest cost node
  - **Phase 2 Premium — starts ONLY after ALL Phase 1 nodes complete for ALL segments**
  - Input: segment summaries from S2-1 — **NOT raw chapter text** (5× token savings; violating this is a silent cost overrun)
  - Use `complete_structured()` with Pydantic response model to guarantee schema
  - **AC:** Input confirmed as summaries; output passes `LessonMetadata` validation; Langfuse span records token count and `token_cost_usd`

- [ ] **S2-8 `slide_generator` node**
  - `apps/api/app/modules/content/pipeline/nodes/slide_generator.py`
  - Model: `settings.llm_slide_generator` (`LLM_SLIDE_GENERATOR`)
  - Phase 2 — sequential after S2-7
  - Input: lesson outline from `lesson_planner`; output: list of `Slide` per segment
  - Each `Slide`: `slide_id`, `title`, `bullets`, `image_url` (nullable), `fallback_image_url` (nullable)
  - **AC:** Output validates against `app.schemas.Slide`; at least 1 slide per segment; `image_url` nullable (images filled by S2-10)

- [ ] **S2-9 `tts_node` — Sarvam AI Bulbul v2 + Azure TTS + Browser fallback**
  - `apps/api/app/modules/content/pipeline/nodes/tts_node.py`
  - Phase 3 Media node
  - **Fallback chain: Sarvam AI Bulbul v2 → Azure TTS → Browser Speech** (ElevenLabs REMOVED 2026-06-25)
  - Each segment's narration script → `.mp3` stored to Supabase Storage
  - Wire `is_circuit_open("sarvam")` before each call; fallback never hard-fails — Browser Speech is always available
  - Include TTS cost in `cost_tracker.accumulate_cost()`
  - **AC:** Audio file produced per segment; URL in `Narration.audio_url`; `audio_provider` set to `"sarvam"`, `"azure"`, or `"browser"`; pipeline never fails over TTS

- [ ] **S2-10 `image_generator` node — GPT Image 1 Mini + Imagen 4 Fast + text-only fallback**
  - `apps/api/app/modules/content/pipeline/nodes/image_generator.py`
  - Phase 3 Media node
  - **DALL-E 3 REMOVED — shut down May 2026. Stack: GPT Image 1 Mini → Imagen 4 Fast → text-only**
  - Fall back to `image_url = None` (text-only) if cost ceiling is near — never fail the pipeline over images
  - Include image cost in `cost_tracker.accumulate_cost()`
  - **AC:** Image URL or `None` set on each slide; pipeline completes if all image providers fail; cost tracked

- [ ] **S2-11 `package_builder` node → JSONB write**
  - `apps/api/app/modules/content/pipeline/nodes/package_builder.py`
  - Phase 3 final node — assembles all prior node outputs
  - 1. Build `LessonPackage` from accumulated `state` outputs
  - 2. `LessonPackage.model_validate(assembled)` — raises immediately if schema violated
  - 3. `lessons.content = package.model_dump(mode="json")`; `lessons.status = 'ready'`
  - 4. `lesson_jobs.status = 'completed'`; `completed_at = now()`
  - 5. Emit `lesson_ready` WebSocket push matching `packages/shared/types/ws.ts` (coordinate with Dev 4 before implementing)
  - **AC:** `lessons.content` valid JSONB; `LessonPackage.model_validate(row["content"])` round-trip passes; `lesson_ready` push delivered; `lessons.status = 'ready'`

- [ ] **S2-12 WebSocket `lesson_ready` push — coordinate with Dev 4**
  - Shape must match `packages/shared/types/ws.ts` discriminated union exactly
  - Triggered by `package_builder` (S2-11) on success
  - **AC:** Frontend receives `lesson_ready`; message passes TS discriminated-union type check; no shape mismatch with Dev 4 handler

- [ ] **S2-13 Cost ceiling enforcement wired into all nodes**
  - `apps/api/app/core/cost_tracker.py` — wire into every LLM, TTS, image call
  - `MAX_LESSON_COST_USD = settings.max_lesson_cost_usd` (default `$3.00`)
  - On breach: downshift to cheapest providers; complete lesson; set `lesson_jobs.error = "cost_ceiling_exceeded"`
  - **AC:** A test run exceeding $3.00 mid-pipeline completes without crashing; admin panel shows the flag; cost tracked in `lesson_jobs.cost_usd`

- [ ] **S2-14 Eval harness — 5 PDFs**
  - `apps/api/tests/evals/`
  - 5 representative PDFs: short (≤10 pages), long (≥100 pages), dense text, table-heavy, image-heavy
  - Automated scoring: slide quality + quiz relevance; output recorded in Langfuse
  - **AC:** All 5 PDFs produce a valid `LessonPackage`; no pipeline crash; per-lesson scores visible in Langfuse

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
