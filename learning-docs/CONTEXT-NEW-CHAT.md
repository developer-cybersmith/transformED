# TransformED AI — New Chat Context Document

**Generated:** 2026-07-08
**Purpose:** Paste this document at the start of a fresh Claude chat to resume development with zero context loss.
**Branch at time of writing:** `sprint1/s1-9-post-lessons-endpoint`

---

## 1. HOW TO USE THIS DOCUMENT

Read this entire document before doing anything else. Every constraint documented here is non-negotiable and actively enforced. Nothing in this document is a suggestion — it reflects architectural decisions, security requirements, legal constraints (AGPL bans), and production bugs that have already been fixed. Reintroducing a fixed bug or violating a hard rule will result in PR rejection.

For the full rule set, always cross-reference `/mnt/e/transformED-corp/CLAUDE.md` — it is the canonical source of truth and is checked into the repo. This document is a dense operational summary to get you running immediately; CLAUDE.md has the authoritative details.

When in doubt about any constraint: stop, re-read CLAUDE.md, and ask for clarification rather than making an assumption.

---

## 2. PROJECT MISSION & GOAL

**TransformED AI** is an AI-powered adaptive learning platform. A student uploads a chapter PDF; the system generates a complete lesson with slides, narration audio, quiz questions, jargon glossary, and intervention messages. During the lesson, a 7-state tutor monitors engagement via a Cognitive Engagement Score (CES) and intervenes when the student is distracted or fatigued.

**Week 10 goal:** First paying student completes a full session by end of Week 10 (approx 2026-08-20).

**Current status (2026-07-08):**
- Sprint 0: Complete (12/12 tasks)
- Sprint 1: Complete (10/10 tasks) — the entire Phase A book-ingestion pipeline is built and tested
- Sprint 2: Not started — Phase B (content generation, 11 remaining nodes) + WebSocket push + cost ceiling
- Next immediate action: Begin Sprint 2, Story 2.1 (Phase 1 economy nodes — all 6 parallel)

**What Sprint 1 delivered:** A student can POST a PDF to `/api/content/lessons`, and the system will extract text, detect structure, chunk it, and embed all chunks into pgvector. The pipeline is idempotent (safe to retry via ARQ), checkpointed (resumes from last completed node), and fully tested (87 unit tests passing).

**What is NOT done yet:** Lesson planning, slide generation, quiz generation, narration scripts, TTS audio, image generation, final LessonPackage assembly, and WebSocket `lesson_ready` push. These are all Sprint 2.

---

## 3. LOCKED TECHNOLOGY STACK

Every choice below is locked. Changing any of these requires a PRD amendment reviewed by all 4 developers. Do not propose alternatives unless the stated item has been explicitly retired.

| Layer | Locked Choice | Hard Constraint / Why |
|-------|--------------|----------------------|
| Backend | FastAPI (Python 3.12) | Modular monolith; no microservice split until post-launch |
| Job queue | ARQ | Celery is BANNED — explicitly rejected in PRD §24 |
| Frontend | Next.js 14 + TypeScript + Tailwind | App Router only |
| Database | Supabase Postgres + pgvector + JSONB | |
| Storage | Supabase Storage | S3-compatible + CDN |
| Auth | Supabase Auth + PyJWT local verify | No remote auth call per request — latency and reliability |
| Cache / Queue / PubSub | Railway Redis | |
| AI orchestration | LangGraph (pinned: `==1.2.6`) | Pin exact version — NEVER auto-upgrade |
| LangGraph checkpointing | Custom `lesson_jobs` table + MemorySaver | PostgresSaver is BANNED |
| Primary LLM | OpenAI GPT-4o + GPT-4o-mini | Defaults — never hardcode model strings; use `settings.llm_*` |
| Alt LLM | Claude Sonnet | Phase 2 tutor Q&A only (evaluation candidate) |
| TTS | Sarvam AI Bulbul v2 → Azure TTS → Browser Speech | Fallback chain. ElevenLabs REMOVED (still in config as optional `None`). |
| Avatar | HeyGen cached intro/outro | No live HeyGen per lesson (~$0/lesson via caching) |
| Image generation | GPT Image 1 Mini → Imagen 4 Fast → text-only | DALL-E 3 is DEAD (shut down May 2026). Never use it. |
| Embeddings | `text-embedding-3-small` | Chunk content: embed at ingestion only, NEVER regenerate stored embeddings. Phase 2 RAG tutor may embed student questions at query time. |
| OCR | Tesseract (in-container) | Azure Doc Intelligence removed |
| PDF text extraction | pypdfium2 + pdftext | PyMuPDF / fitz is BANNED — AGPL-3.0 would open-source entire SaaS |
| PDF table detection | pdfplumber (trigger only) + docling (table markdown) | pdfplumber retained ONLY to detect table pages; no text extraction via pdfplumber |
| PDF image render | pypdfium2 at 300 DPI minimum | `page.render(scale=300/72)` — 150 DPI is not acceptable |
| Attention | MediaPipe Face Landmarker WASM | WebGazer REJECTED |
| Lesson player | Custom React audio-timeline state machine | Reveal.js REJECTED |
| Realtime | Native FastAPI WebSockets | |
| Observability | Langfuse + Sentry + OTel + PostHog | Wire before feature work — not optional |
| Deploy | Railway + GitHub Actions | `railway.toml` |

### Per-Task Model Allocation

All model IDs are driven by env vars. **Never hardcode model strings in business logic.** Swapping models is an env var change only.

| Task | Env Var | Default | Notes |
|------|---------|---------|-------|
| Lesson planning | `LLM_LESSON_PLANNER` | `gpt-4o` | Premium node |
| Slide generation | `LLM_SLIDE_GENERATOR` | `gpt-4o` | Premium node |
| Quiz, jargon, complexity, narration, interventions, Learner DNA | `LLM_MINI` | `gpt-4o-mini` | Economy nodes |
| Tutor Q&A (Phase 2) | `LLM_TUTOR` | `gpt-4o` | Claude 3.5 Sonnet eval candidate |
| Embeddings | N/A | `text-embedding-3-small` | Fixed — not configurable |

**Batch API rule:** Never use OpenAI or Google Batch API. 24-hour completion window is incompatible with real-time generation. All LLM calls use the synchronous API.

---

## 4. NON-NEGOTIABLE HARD RULES

These are REJECT-on-sight rules for PRs. Violation = immediate PR rejection, no exceptions.

1. **No Celery.** ARQ only. Celery is banned per PRD §24.
2. **No PostgresSaver.** Use custom `lesson_jobs` table + MemorySaver for LangGraph checkpointing.
3. **No direct provider calls in business logic.** All LLM, TTS, image, and embedding calls must go through the provider abstraction in `providers/`. No direct `openai.Client()` or similar in pipeline nodes or routers.
4. **Never import fitz / pymupdf / pymupdf4llm / borb.** All AGPL-3.0. Using any of them in any file contaminates the entire codebase with AGPL requirements. PDF extraction uses pypdfium2 + pdftext instead.
5. **Pin LangGraph version — never auto-upgrade.** Pinned to `==1.2.6`. A minor-version bump can break graph serialization and destroy in-flight checkpoint data.
6. **PDF image extraction must render at 300 DPI minimum.** Use `page.render(scale=300/72)` in pypdfium2. 150 DPI is not acceptable for OCR accuracy.
7. **PDF parsing must run in an isolated subprocess.** Never call pypdfium2, pdfplumber, or docling directly in the main FastAPI process or ARQ worker process. A malicious PDF can exploit parser bugs and crash the host process.
8. **Chunk embeddings at ingestion only — never regenerate stored chunk embeddings.** Once written to the `chunks.embedding` column, that vector is permanent. The Phase 2 RAG tutor MAY embed student questions at query time — this is intentional and required.
9. **Never hardcode model strings.** Always use `settings.llm_lesson_planner`, `settings.llm_mini`, etc. from `config.py`. Model switching is an env var change only.
10. **Never use OpenAI or Google Batch API.** 24-hour completion window breaks real-time generation.
11. **JWT is verified locally (PyJWT + SUPABASE_JWT_SECRET).** Never make a remote auth call per request.
12. **Raw webcam video never leaves the browser.** Only 5 derived numbers sent to the backend.
13. **DPDP Act 2023 compliance.** No raw IQ/EQ/SQ claims — branded as "Learner DNA". No clinical scores shown to students — descriptive profile only.
14. **Never gate lesson progress on teach-back score in MVP.** Never add a teach-back timer (creates test anxiety). No STT in MVP — typed teach-back only.
15. **Intervention messages are PRE-GENERATED at lesson build time.** Zero GPT calls at intervention time at runtime.
16. **Cost ceiling: $3.00/lesson.** On breach: downshift to cheapest providers, complete the lesson, flag in admin. Never abort mid-lesson over cost.
17. **DALL-E 3 is banned.** Shut down May 2026. Current image stack: GPT Image 1 Mini → Imagen 4 Fast → text-only (image_url = None).
18. **Applied migrations are immutable.** Never modify `supabase/migrations/*.sql` files that have been applied. Schema changes require a new migration file.
19. **BMAD story-first gate:** Story file must be committed before any implementation code. Never share a commit between a story file and implementation.
20. **5-agent code review required** before any PR merge. See Section 15 for agent layers.

---

## 5. TEAM OWNERSHIP

| Dev | GitHub user | Owns |
|-----|-------------|------|
| Dev 1 | developer1-cybersmith | Infra, content pipeline (all 15 nodes), embeddings, provider abstraction, Langfuse |
| Dev 2 | (Dev 2) | Next.js, custom player, MediaPipe, quiz/teachback UI, dashboard, WebSocket client |
| Dev 3 | (Dev 3) | Quiz API, teachback scorer, CES formula, Learner DNA, session reports, analytics |
| Dev 4 | (Dev 4) | WebSocket handlers, JWT middleware, 7-state tutor, Redis buffer, interventions |

**Anti-deadlock rule:** After Week 1 schema freeze, each dev mocks the other's interface. Never block on another dev's implementation.

**One-discipline rule:** Modules communicate only through the service layer, never via direct DB access into another module's tables. Violating PRs are rejected.

**Dev 1 writes to these DB tables:** `books`, `chapters`, `chunks` (with inline embeddings), `lessons`, `lesson_jobs`

**Dev 1 writes to these Redis keys:**
- `circuit_breaker:{provider}:failures`
- `circuit_breaker:{provider}:state`
- `circuit_breaker:{provider}:opened_at`
- `lesson:{lesson_id}:cost_usd` (via cost_tracker)
- `job:{job_id}:status`
- `job:{job_id}:node_outputs`
- `embeddings:search:{hash}` (cached ANN search results, TTL 300s)

---

## 6. DATABASE SCHEMA

Two migrations are applied and FROZEN. Never modify them. New schema changes require a new `.sql` file in `supabase/migrations/`.

### Applied Migrations (IMMUTABLE)
- `20260611000000_initial_schema.sql` — initial schema
- `20260625000000_chunks_inline_embedding.sql` — books table, inline embedding in chunks, lessons.book_id

### Table: `public.books` (added in 20260625)

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `book_id` | uuid | PK, gen_random_uuid() | Stable PDF identifier |
| `user_id` | uuid | FK → users.id ON DELETE CASCADE, NOT NULL | Owner |
| `filename` | text | NOT NULL | Original upload filename |
| `page_count` | integer | nullable | Written by extract_node |
| `status` | text | NOT NULL DEFAULT 'processing', CHECK IN ('processing','ready','failed') | Book ingestion state |
| `created_at` | timestamptz | NOT NULL DEFAULT now() | |
| `updated_at` | timestamptz | NOT NULL DEFAULT now(), auto-trigger | |

### Table: `public.lessons`

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `lesson_id` | uuid | PK, gen_random_uuid() | Returned to frontend on upload |
| `user_id` | uuid | FK → users.id ON DELETE CASCADE, NOT NULL | RLS gates on this |
| `book_id` | uuid | nullable FK → books.book_id ON DELETE SET NULL | SET NULL: lesson survives book deletion |
| `title` | text | nullable | Set by lesson_planner node |
| `status` | text | NOT NULL DEFAULT 'generating', CHECK IN ('generating','ready','failed') | Frontend polls this |
| `content` | jsonb | nullable | Full LessonPackage JSONB written by package_builder |
| `source_file_path` | text | nullable | Supabase Storage path to source PDF |
| `created_at` | timestamptz | NOT NULL DEFAULT now() | |
| `updated_at` | timestamptz | NOT NULL DEFAULT now(), auto-trigger | |

### Table: `public.lesson_jobs`

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `job_id` | uuid | PK, gen_random_uuid() | ARQ job identifier |
| `lesson_id` | uuid | FK → lessons.lesson_id ON DELETE CASCADE, NOT NULL | |
| `status` | text | NOT NULL DEFAULT 'pending', CHECK IN ('pending','running','completed','failed') | |
| `last_node` | text | nullable | Last successfully completed node — used for checkpoint resume |
| `node_outputs` | jsonb | nullable | Accumulated node outputs keyed by node name |
| `error` | text | nullable | Populated on status='failed' |
| `attempt` | integer | NOT NULL DEFAULT 0 | ARQ retry count (max 3 per PRD §14) |
| `cost_usd` | numeric(10,4) | NOT NULL DEFAULT 0 | Accumulated AI cost for this run |
| `started_at` | timestamptz | nullable | When ARQ worker picked up the job |
| `completed_at` | timestamptz | nullable | When package_builder finished |
| `created_at` | timestamptz | NOT NULL DEFAULT now() | |

### Table: `public.chapters`

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `chapter_id` | uuid | PK, gen_random_uuid() | |
| `book_id` | uuid | FK → books.book_id ON DELETE CASCADE, NOT NULL | FK retrofitted in 20260625 |
| `lesson_id` | uuid | FK → lessons.lesson_id ON DELETE CASCADE, NOT NULL | |
| `title` | text | NOT NULL | From structure detection |
| `page_start` | integer | NOT NULL | 1-indexed |
| `page_end` | integer | NOT NULL | Inclusive |
| `chapter_index` | integer | NOT NULL | 0-indexed position in book |
| `created_at` | timestamptz | NOT NULL DEFAULT now() | |

### Table: `public.chunks` (embeddings table DROPPED — inline since 20260625)

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `chunk_id` | uuid | PK, gen_random_uuid() | |
| `chapter_id` | uuid | FK → chapters.chapter_id ON DELETE CASCADE, NOT NULL | |
| `book_id` | uuid | FK → books.book_id ON DELETE CASCADE, nullable | Shortcut FK backfilled from chapters |
| `section` | text | nullable | Section heading within chapter |
| `page_start` | integer | nullable | |
| `page_end` | integer | nullable | |
| `content` | text | NOT NULL | Raw text — always stored (re-extraction = 200-300ms; source PDF may be deleted) |
| `chunk_index` | integer | NOT NULL | 0-indexed within chapter |
| `token_count` | integer | nullable | Written by embed_node |
| `embedding` | vector(1536) | nullable | text-embedding-3-small inline vector; HNSW index (vector_cosine_ops) |
| `embedding_metadata` | jsonb | NOT NULL DEFAULT '{}' | {model, dimensions, ingested_at} |
| `created_at` | timestamptz | NOT NULL DEFAULT now() | |

**HNSW index** on `chunks.embedding` using `vector_cosine_ops` for approximate nearest-neighbour cosine search.

**NOTE:** The `embeddings` table from the initial migration has been DROPPED. Do not reference it.

### Other Tables (Dev 3, Dev 4 ownership — Dev 1 does not write to these)

- `public.users` — auth.users mirror, attention_consent flag
- `public.sessions` — user lesson sessions with CES final score
- `public.quiz_attempts` — per-question quiz responses
- `public.teachback_attempts` — typed teach-back responses with scores
- `public.learner_dna` — cognitive/emotional/self-direction profile (unique per user)
- `public.onboarding_responses` — initial assessment answers
- `public.session_events` — event log per session
- `public.attention_events` — MediaPipe-derived attention signals (gated by attention_consent)

**RLS is enabled on all tables.** Users read only their own data. Service role key bypasses RLS for pipeline operations.

**DPDP consent gap (Sprint 2 priority):** `users.attention_consent` boolean is insufficient for DPDP Act 2023. A `user_consents` audit table (user_id, consent_type, policy_version, consented_at) is required before any attention data is collected.

---

## 7. THE 15-NODE PIPELINE ARCHITECTURE

### Phase A — Book Ingestion (once per book, ~2–5 min)
```
upload → extract_node → structure_node → chunk_node → embed_node
```

### Phase B — Chapter Generation, Phase 1 (parallel via Send() fan-out)
All 6 must finish before Phase 2 starts. Uses `settings.llm_mini`.
```
summarise_segment_node   × N   (parallel)
quiz_generator_node      × N   (parallel)
segment_complexity_node  × N   (parallel)
jargon_extractor_node    × N   (parallel)
intervention_messages_node × N (parallel)
narration_generator_node × N   (parallel)
```

### Phase B — Chapter Generation, Phase 2 (sequential, after ALL Phase 1 complete)
**CRITICAL:** `lesson_planner` receives segment summaries from Phase 1, NOT raw chapter text. Violating this causes a silent 5× cost overrun.
```
lesson_planner_node    ← input: segment_summaries (NOT raw text)
slide_generator_node   ← input: lesson_plan from lesson_planner
```

### Phase C — Media
```
tts_node               ← narration scripts → .mp3 per segment
image_generator_node   ← slide content → images
package_builder_node   ← assembles final JSONB lesson package
```

### Checkpoint Pattern
After each node: write `last_node` + `node_outputs` to `lesson_jobs`. On ARQ retry: read `last_node`, skip completed nodes. Never re-run completed LLM calls.

### Node Implementation Status

| Node | Graph Position | File | Status | Notes |
|------|---------------|------|--------|-------|
| extract_node | Phase A, Node 1 | graph.py:109 | FULL | subprocess PDF extraction |
| structure_node | Phase A, Node 2 | graph.py:281 | FULL | rule-based + LLM validation |
| chunk_node | Phase A, Node 3 | graph.py:357 | FULL | tiktoken cl100k_base, 512 tokens |
| embed_node | Phase A, Node 4 | graph.py:469 | FULL | OpenAI text-embedding-3-small |
| lesson_planner_node | Phase B2, Node 5 | graph.py:599 | STUB | TODO: LLM call commented out |
| slide_generator_node | Phase B2, Node 6 | graph.py:622 | STUB | TODO: LLM call commented out |
| summarise_segment_node | Phase B1, Node 7 | graph.py:636 | STUB | TODO: parallel LLM calls |
| quiz_generator_node | Phase B1, Node 8 | graph.py:647 | STUB | TODO: LLM structured output |
| segment_complexity_node | Phase B1, Node 9 | graph.py:658 | STUB | TODO: textstat + LLM |
| jargon_extractor_node | Phase B1, Node 10 | graph.py:669 | STUB | TODO: LLM structured output |
| intervention_messages_node | Phase B1, Node 11 | graph.py:680 | STUB | TODO: 3×3 message generation |
| narration_generator_node | Phase B1, Node 12 | graph.py:691 | STUB | TODO: per-slide scripts |
| tts_node | Phase C, Node 13 | graph.py:702 | STUB | ALSO: stale ElevenLabs ref — use Sarvam/Azure |
| image_generator_node | Phase C, Node 14 | graph.py:714 | STUB | ALSO: stale DALL-E 3 ref — use GPT Image 1 Mini |
| package_builder_node | Phase C, Node 15 | graph.py:726 | PARTIAL | assembly logic present; all inputs empty because upstream stubs |

**Stale provider references to fix in Sprint 2:**
- `tts_node` references ElevenLabs (REMOVED). Must use SarvamTTSProvider → AzureTTSProvider → Browser Speech.
- `image_generator_node` references DalleImageProvider / DALL-E 3 (SHUT DOWN May 2026). Must use GPTImage1MiniProvider → Imagen4FastProvider → text-only.

### Helper Functions in graph.py

- `_update_job_progress` (lines 866-883): Writes `last_node` + `status='running'` to `lesson_jobs`. Failures are swallowed (never abort the pipeline). Full implementation.
- `_build_pipeline_graph` (lines 753-799): Constructs and compiles the LinearStateGraph with MemorySaver. All 15 nodes registered and wired with linear edges.
- `get_pipeline_graph` / `run_pipeline`: Module-level lazy graph cache and public entry point.

---

## 8. SPRINT 1 COMPLETE STATE

### Story 1.1 — POST /lessons Endpoint + ARQ Job Enqueue

**File:** `apps/api/app/modules/content/router.py`

**What was built:**
- `POST /api/content/lessons` — validates PDF (magic bytes `%PDF`, 50MB limit, MIME check), streams body, inserts `books` → `lessons` → storage → `lesson_jobs` in FK order, enqueues ARQ job with `_job_id=pipeline:{lesson_id}` for deduplication, returns 202 immediately
- `GET /api/content/lessons/{id}` — ownership-checked status poll
- `GET /api/content/lessons` — paginated list
- Rate limited: 5/minute per user (slowapi)
- Full rollback (hard-delete in FK-reverse order) on any failure before enqueue
- Returns 409 if ARQ deduplication returns None (duplicate job key)

**Key design decisions:**
- Insert order: books → lessons → lesson_jobs (FK dependency order). Rollback in reverse.
- ARQ `_job_id` uses `pipeline:{lesson_id}` as deduplication key to prevent duplicate jobs.
- Storage path: `source-pdfs/{user_id}/{lesson_id}/{filename}` — user-scoped for RLS.
- 202 (Accepted) not 201 (Created) — the resource isn't done being created yet.

### Story 1.2 — PDF Extraction Node

**File:** `apps/api/app/modules/content/pipeline/nodes/extract_subprocess.py`

**What was built:**
- Runs in isolated subprocess — a malicious PDF crash cannot kill the ARQ worker
- Stack: pypdfium2 (text extraction, 97% accuracy) → pdfplumber (table detection only, triggers docling) → pdftext (font/layout metadata, `font_blocks` in JSON output) → docling (table markdown when tables detected) → pytesseract (OCR fallback when text yield < `OCR_TEXT_YIELD_THRESHOLD` chars/page)
- Images extracted at 300 DPI and uploaded to Supabase Storage
- `books.page_count` written after extraction
- Idempotent: skips if `lesson_jobs.node_outputs["extract"]` exists
- Checkpoint written on success: `last_node='extract'`, `node_outputs["extract"]` cached
- Subprocess timeout: 600 seconds

**Why NOT PyMuPDF/fitz:** AGPL-3.0 would require open-sourcing the entire SaaS. This is a hard legal constraint, not a performance choice.

**Bugs fixed in this node (NEVER reintroduce):**
1. Line 247 — `raw_text = "\n\n".join(ocr_parts)` unconditionally overwrote good pypdfium2 text with empty strings when pytesseract is not installed. Fix: `if ocr_text.strip(): raw_text = ocr_text`
2. `get_text_range()` deprecated → replaced with `get_text_bounded()`

### Story 1.3 — Structure Detection Node

**File:** `apps/api/app/modules/content/pipeline/nodes/structure_detection.py`

**What was built:**
- Strategy 1: Font-size clustering using pdftext spans — spans 25%+ larger + bold than median = heading; relative size determines chapter/section/topic level
- Strategy 2: Regex patterns for `Chapter X:`, `1.2 ...`, `1.2.3 ...` numbering schemes
- Both strategies merged and deduplicated by heading text
- LLM validation pass with GPT-4o-mini (`settings.llm_mini`) to clean false positives via `complete_structured()` → `DocumentStructure` Pydantic model
- Falls back to rule-based output on LLM failure
- `@with_retry(max_attempts=3)` on LLM call; Langfuse span records token count

### Story 1.4 — Semantic Chunking Node

**File:** `apps/api/app/modules/content/pipeline/nodes/chunking.py` + `chunk_node` in `graph.py`

**What was built:**
- Tokenizer: `cl100k_base` (MUST match text-embedding-3-small and GPT-4o tokenization)
- Target: 512 tokens, overlap: 64 tokens
- Algorithm: greedy paragraph→sentence packing; overlap = token-level tail decode (`encoding.decode(all_tokens[-64:])`)
- Never breaks mid-sentence; oversized single segments emitted as-is (never truncated)
- Zero-token chunks excluded from DB writes
- One `chapters` row created per detected chapter; bulk-upsert chunk rows to Supabase
- Chunks stored with `chapter_id`, `book_id`, `chunk_index`, `section`, `page_start`, `page_end`, `content`, `token_count`
- Checkpoint: chapter_id + chunk list written to `lesson_jobs.node_outputs["chunk"]`

### Story 1.5 — Embeddings + pgvector Storage Node

**File:** `providers/embeddings/openai.py` + `embed_node` in `graph.py`

**What was built:**
- Idempotency check: `"embed" in node_outputs` → skip entirely (NEVER re-embed stored content)
- Query: `chunks WHERE chapter_id=? AND embedding IS NULL ORDER BY chunk_index`
- Empty/whitespace content filtered before API call (prevents HTTP 400)
- `BATCH_SIZE=2048` (OpenAI limit per call)
- Length guard: `if len(embeddings) != len(texts): raise RuntimeError(...)` — `zip()` silently truncates
- Writes `embedding` (vector(1536)) + `embedding_metadata {model, dimensions, ingested_at}` to each chunk row
- Sets `books.status='ready'` after all chunks embedded
- Checkpoint written to `lesson_jobs` AFTER all chunks embedded (critical — see P1 bug below)
- `@with_retry(max_attempts=3)` on `embed_texts` in provider
- Circuit breaker check before every API call (Redis-backed)
- Langfuse generation span per batch: records model, batch_size, tokens, latency
- Cost tracked via `cost_tracker.accumulate_cost()`

---

## 9. BUGS FIXED — NEVER REINTRODUCE

These bugs were found in the 5-agent adversarial code review and the extract_subprocess.py review. Each fix is in the codebase. Reintroducing any of these will be caught in the next code review.

### P1 — CRITICAL: Checkpoint Silently Swallowed (embed_node)

**Bug:** `except Exception` block around the checkpoint DB write was swallowing failures. Node returned `embeddings_stored=True` even when the checkpoint was not saved to `lesson_jobs`.
**Impact:** ARQ retry would re-embed ALL chunks (100% double cost per retry). Silent data corruption.
**Fix:** Removed the `try/except` entirely — let the exception propagate and abort the node, so ARQ retries from the correct checkpoint.
**File:** `embed_node` in `apps/api/app/modules/content/pipeline/graph.py`

### P2 — Hardcoded Dimensions (embed_node)

**Bug:** `"dimensions": 1536` hardcoded in embedding_metadata dict.
**Impact:** Changing the embedding model (e.g., to 3072-dim) would silently write wrong dimension metadata.
**Fix:** Added `embedding_dimensions: int = Field(default=1536)` to `Settings` in `config.py`. Now uses `settings.embedding_dimensions`.

### P3 — Langfuse generation.end() Never Called on Exception Path (embed_node)

**Bug:** On any exception in the embedding loop, `generation.end()` was never called. Langfuse trace would be left open/incomplete.
**Impact:** Incomplete traces in Langfuse; production observability gap.
**Fix:** `generation.end(level="ERROR", status_message=str(exc))` called in `finally` block before re-raising.

### P4 — sys.modules Stub at Module Scope in Test File

**Bug:** `sys.modules["openai"] = stub` written at module scope in the test file. It bleeds into the entire pytest session, breaking other tests that import real openai.
**Impact:** Flaky test suite; test ordering matters; breaks in CI if test order changes.
**Fix:** Moved to a session-scoped autouse fixture in `tests/conftest.py`. Properly isolated.

### P5 — zip() Silently Truncates on Mismatched Lengths (embed_node)

**Bug:** `zip(batch, embeddings)` — if OpenAI returns fewer vectors than texts (API bug or rate limit truncation), `zip()` silently truncates the longer list. Some chunks get no embedding written; no error raised.
**Impact:** Silent data loss — chunks appear in DB with `embedding IS NULL` after supposed success.
**Fix:** Length guard: `if len(embeddings) != len(texts): raise RuntimeError(f"Expected {len(texts)} vectors, got {len(embeddings)}")`

### P6 — Empty/Whitespace Chunk Content Not Filtered Before API Call (embed_node)

**Bug:** Chunks with empty or whitespace-only `content` passed directly to `openai.embeddings.create()`.
**Impact:** OpenAI returns HTTP 400 on empty strings. Entire batch fails, losing all embeddings.
**Fix:** `if c.get("content", "").strip()` filter applied before batching. Empty chunks excluded.

### P7 — @with_retry Not Exercised in Tests (test coverage)

**Bug:** No test verified that `@with_retry` actually retried on a 429 response from OpenAI.
**Impact:** The retry decorator could be silently broken (e.g., wrong exception type caught) and tests would still pass.
**Fix:** Added `test_embed_node_provider_retry_on_429` — mocks a 429 from OpenAI, verifies embed_texts is called 3 times (max_attempts=3).

### P8 — ORDER BY chunk_index Not Asserted in Tests (test coverage)

**Bug:** The Supabase query chain `.order("chunk_index")` was not asserted in unit tests.
**Impact:** If `ORDER BY` was accidentally removed, chunks would be embedded in arbitrary DB order. Embedding order matters for chunk_index alignment.
**Fix:** `.order.assert_called_with("chunk_index")` added to relevant test.

### P9 — IS NULL Filter Args Not Asserted in Tests (test coverage)

**Bug:** The Supabase query `.is_("embedding", "null")` filter was not asserted.
**Impact:** If the idempotency filter was removed, ALL chunks (including already-embedded ones) would be re-embedded on every run.
**Fix:** `.is_.assert_called_with("embedding", "null")` added to relevant test.

### P10 — Multi-Batch Boundary (2049 Chunks) Not Tested (test coverage)

**Bug:** No test verified the 2048-chunk batch boundary. With exactly 2049 chunks, the code should make 2 API calls (2048 + 1). Off-by-one in the batching loop would mean the last chunk is never embedded.
**Fix:** Added `test_embed_node_batch_split_2049_chunks` with exactly 2049 chunks, asserts 2 API calls.

### P11 — settings.embedding_model Not Proven to Flow Dynamically (test coverage)

**Bug:** No test verified that the embedding model string from `settings.embedding_model` was actually passed to the OpenAI API call and stored in `embedding_metadata`.
**Impact:** If model was hardcoded anywhere (e.g., `"text-embedding-3-small"` literal), an env var swap for model evaluation would silently have no effect.
**Fix:** Test sets `settings.embedding_model = "test-model-xyz"` and asserts `metadata["model"] == "test-model-xyz"`.

### P12 — OpenAIEmbeddingsProvider Constructor Not Asserted (test coverage)

**Bug:** No test verified that `OpenAIEmbeddingsProvider` was constructed with `lesson_id=lesson_id`.
**Impact:** If `lesson_id` was accidentally dropped from the constructor call, Langfuse traces would have no `lesson_id` context.
**Fix:** `mock_cls.assert_called_once_with(lesson_id=FAKE_LESSON_ID)` added.

### Bug E1 — OCR Overwrote Good pypdfium2 Text (extract_subprocess.py)

**Bug:** Line 247: `raw_text = "\n\n".join(ocr_parts)` ran unconditionally. When pytesseract is not installed, `ocr_parts` is empty, setting `raw_text = ""` and discarding all pypdfium2-extracted text.
**Impact:** Every PDF processed without Tesseract installed would have empty text extraction. Silent failure.
**Fix:** `if ocr_text.strip(): raw_text = ocr_text` — only overwrites if OCR actually produced text.
**File:** `apps/api/app/modules/content/pipeline/nodes/extract_subprocess.py`, line 247

### Bug E2 — Deprecated pypdfium2 API (extract_subprocess.py)

**Bug:** `page.get_text_range()` was called but is deprecated in the installed pypdfium2 version.
**Impact:** Runtime DeprecationWarning or hard crash on newer pypdfium2 versions.
**Fix:** Replaced with `page.get_text_bounded()`.

---

## 10. PROVIDER ABSTRACTION PATTERN

**Rule:** No direct provider SDK calls in business logic. All LLM, TTS, image, embedding, and avatar calls must go through the abstract interfaces in `providers/base.py`.

### Abstract Base Classes (providers/base.py)

```python
class LLMProvider(ABC):
    async def complete(self, messages, model, **kwargs) -> str: ...
    async def complete_structured(self, messages, model, response_model, **kwargs) -> BaseModel: ...

class TTSProvider(ABC):
    async def synthesize(self, text, voice_id, **kwargs) -> bytes: ...

class ImageProvider(ABC):
    async def generate(self, prompt, **kwargs) -> bytes: ...

class EmbeddingsProvider(ABC):
    async def embed_texts(self, texts) -> tuple[list[list[float]], int]: ...
    # Returns: (embeddings, total_tokens)

class AvatarProvider(ABC):
    async def get_clip(self, script, **kwargs) -> str: ...
    # Returns: URL to cached video clip
```

### Implementations

| Abstract | Concrete | File | Status |
|----------|----------|------|--------|
| LLMProvider | OpenAILLMProvider | providers/llm/openai.py | Full |
| EmbeddingsProvider | OpenAIEmbeddingsProvider | providers/embeddings/openai.py | Full |
| TTSProvider | SarvamTTSProvider | providers/tts/ | Sprint 2 |
| TTSProvider | AzureTTSProvider | providers/tts/ | Sprint 2 |
| ImageProvider | GPTImage1MiniProvider | providers/image/ | Sprint 2 |
| ImageProvider | Imagen4FastProvider | providers/image/ | Sprint 2 |
| AvatarProvider | HeyGenAvatarProvider | providers/avatar/ | Sprint 2 |

### Construction Pattern

Pipeline nodes create providers with `lesson_id` for Langfuse trace context:

```python
provider = OpenAIEmbeddingsProvider(lesson_id=lesson_id)
embeddings, tokens = await provider.embed_texts(texts)
```

The provider internally:
1. Checks `is_circuit_open(provider_key)` — raises if open
2. Creates a Langfuse trace/generation span
3. Makes the API call with `@with_retry(max_attempts=3)`
4. Records failure/success to circuit breaker
5. Calls `generation.end()` in `finally` (including on exception)

### Langfuse Singleton

`app/core/langfuse.py` exports `get_langfuse()` — returns a module-level singleton. All providers call `get_langfuse()` rather than constructing their own `Langfuse()` instances. The FastAPI lifespan `finally` block and ARQ worker shutdown hook both call `get_langfuse().flush()` to ensure no traces are lost on deploy/restart.

---

## 11. CRITICAL ARCHITECTURAL DECISIONS

### Decision 1: ARQ over Celery

**Chosen:** ARQ (async Redis queue)
**Rejected:** Celery
**Why:** Celery is banned per PRD §24. ARQ is async-native (works with FastAPI's async event loop), lighter-weight, and sufficient for our job volume. The ban is non-negotiable.

### Decision 2: pypdfium2 over PyMuPDF/fitz

**Chosen:** pypdfium2 (Apache 2.0) for text extraction, pdftext (Apache 2.0) for font metadata
**Rejected:** PyMuPDF / fitz / pymupdf4llm / borb (all AGPL-3.0)
**Why:** AGPL-3.0 is a copyleft license that requires open-sourcing all software that uses it as a library. A commercial SaaS cannot use AGPL components. Using fitz anywhere in the codebase — even in a test — is a legal violation.

### Decision 3: PDF Parsing in Isolated Subprocess

**Chosen:** All PDF parser calls run in a subprocess spawned by the ARQ worker
**Rejected:** Direct calls in the ARQ worker process
**Why:** User-uploaded PDFs are untrusted. PDF parsers (pypdfium2, pdfplumber, docling) have known CVEs. A malicious PDF crafted to exploit a parser bug can crash or gain code execution in the host process. Subprocess isolation means the crash is contained and the ARQ worker survives.

### Decision 4: Custom lesson_jobs + MemorySaver over PostgresSaver

**Chosen:** Custom `lesson_jobs` table with `last_node` and `node_outputs` JSONB + LangGraph MemorySaver
**Rejected:** LangGraph's built-in PostgresSaver
**Why:** PostgresSaver is banned per PRD (explicit architectural decision). The custom table gives us full visibility and control over checkpoint state, cost tracking, retry count, and error messages in a single queryable row per job.

### Decision 5: Provider ABC Pattern

**Chosen:** Abstract base classes in `providers/base.py`; concrete implementations injected into nodes
**Rejected:** Direct SDK calls in pipeline nodes
**Why:** Provider independence — we need to swap Sarvam → Azure TTS, GPT Image 1 Mini → Imagen 4 Fast without touching node logic. Circuit breaker and retry are implemented once in the provider, not duplicated in every node.

### Decision 6: Embed Once, Never Regenerate

**Chosen:** Generate embeddings once at ingestion; write to `chunks.embedding`; never re-compute
**Rejected:** Re-embedding on each search query; dynamic embedding regeneration
**Why:** text-embedding-3-small at $0.00002/1K tokens is cheap but adds up over thousands of chunks. Re-embedding 500 chunks per search query would be $0.01 per query, and the vector would be identical to what's already stored. The Phase 2 RAG tutor embeds the student's question at query time — this is intentional and permitted. Only stored chunk embeddings are immutable.

### Decision 7: JWT Local Verification

**Chosen:** PyJWT + `SUPABASE_JWT_SECRET` — local verification in `dependencies.py`
**Rejected:** Remote auth call to Supabase per request
**Why:** A remote auth call on every API request adds 50-200ms latency and creates a Supabase availability dependency on every endpoint. JWT verification is CPU-bound (microseconds). The `SUPABASE_JWT_SECRET` is a shared secret — local verification is cryptographically equivalent to remote.

### Decision 8: 64-Token Overlap Between Chunks

**Chosen:** 64-token overlap in the chunking node
**Rejected:** No overlap (sharp boundaries), larger overlap (>128 tokens)
**Why:** 64 tokens (~48 words) preserves enough sentence context across chunk boundaries for embedding coherence without significantly increasing total token count or redundancy. This matches the industry standard for RAG systems using text-embedding-3-small.

### Decision 9: Hybrid Structure Detection (Rule-based + LLM)

**Chosen:** Font-size clustering + regex patterns first; LLM validation second pass
**Rejected:** Pure LLM detection; pure rule-based detection
**Why:** Pure LLM detection is expensive ($0.002-0.01 per document pass) and slow. Pure rule-based fails on PDFs with non-standard formatting (scanned textbooks, etc.). Hybrid approach: rules handle 80% of cases cheaply, LLM fixes the 20% that rules get wrong. The LLM validates/corrects, not generates from scratch.

### Decision 10: 300 DPI Minimum for OCR and Image Extraction

**Chosen:** `page.render(scale=300/72)` — 300 DPI
**Rejected:** 150 DPI (original implementation)
**Why:** 150 DPI produces 72KB images; 300 DPI produces 288KB images. For OCR, sub-200 DPI reduces character recognition accuracy by ~15-30% on typical textbook fonts. 300 DPI is the industry standard for document OCR. The performance cost (~2× render time) is acceptable in a background pipeline.

### Decision 11: Never Hardcode Model Names

**Chosen:** All model IDs via `settings.llm_lesson_planner`, `settings.llm_mini`, etc.
**Rejected:** String literals like `"gpt-4o"` in pipeline node code
**Why:** The Sprint 1 model evaluation sprint requires swapping models without code changes. An env var change should be sufficient. Hardcoded strings also make it impossible to audit which model is used where.

---

## 12. ENVIRONMENT SETUP — CURRENT STATE

### Services Required

| Service | How to Start | Port |
|---------|-------------|------|
| Redis | `docker start redis-dev` (if stopped) or `docker run -d --name redis-dev -p 6379:6379 redis:7-alpine` | 6379 |
| FastAPI server | `uvicorn app.main:app --host 0.0.0.0 --port 8000 --env-file .env` | 8000 |
| ARQ worker | `arq app.workers.main.WorkerSettings` | N/A |

Both FastAPI and ARQ run from `apps/api/` with `.venv` activated.

### Python Packages Status

**Working directory for all commands:** `apps/api/`

**Installed in `.venv`:**
- pypdfium2, pdftext, pdfplumber, arq, fastapi, supabase, langfuse, langgraph, openai, anthropic, pydantic, pydantic-settings, PyJWT, redis, slowapi, sentry-sdk, httpx, pillow

**MISSING (install before running full pipeline):**
```bash
cd /mnt/e/transformED-corp/apps/api
source .venv/bin/activate
uv add tiktoken docling pytesseract
sudo apt install tesseract-ocr  # or: apt-get install -y tesseract-ocr
```

### .env Field Status

File: `apps/api/.env`

| Variable | Status | Notes |
|----------|--------|-------|
| `SUPABASE_URL` | ✅ Real value | `https://REDACTEDPROJECTREF.supabase.co` |
| `SUPABASE_ANON_KEY` | ✅ Real value | See below |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅ Real value | Server-side only — never expose to client |
| `SUPABASE_JWT_SECRET` | ✅ Real value | Used for local JWT verification |
| `OPENAI_API_KEY` | ✅ Real value | Starts with `sk-proj-...` |
| `REDIS_URL` | ✅ `redis://localhost:6379` | Local Docker |
| `LANGFUSE_PUBLIC_KEY` | ❌ FILL_IN placeholder | Server starts but traces are no-ops |
| `LANGFUSE_SECRET_KEY` | ❌ FILL_IN placeholder | Server starts but traces are no-ops |
| `SARVAM_API_KEY` | ❌ FILL_IN | Sprint 2 — not blocking Sprint 1 |
| `HEYGEN_API_KEY` | ❌ FILL_IN | Sprint 2 — not blocking Sprint 1 |
| `AZURE_TTS_KEY` | ❌ FILL_IN | Sprint 2 TTS fallback |

### Supabase Project

- **URL:** `https://REDACTEDPROJECTREF.supabase.co`
- **Anon key:** `REDACTED_SUPABASE_ANON_KEY`

### Pending Manual Setup Steps (before full E2E test)

1. Install missing packages: `uv add tiktoken docling pytesseract && sudo apt install tesseract-ocr`
2. Create a test user in Supabase dashboard (Authentication > Users > Invite user)
3. Get a JWT (see commands in Section 17)
4. Create `source-pdfs` storage bucket in Supabase (Storage > Create bucket, name: `source-pdfs`)
5. Upload a test PDF via `POST /api/content/lessons` with JWT header
6. Watch pipeline run through nodes 1-4 (extract → structure → chunk → embed)

---

## 13. TEST SUITE STATE

### Current Results

```
87 passed, 0 failed
(from: cd apps/api && source .venv/bin/activate && python3 -m pytest tests/unit/ -q)
```

### Known Collection Errors (NOT Dev 1's problem)

Two test files fail to collect (import errors), but they do not affect Dev 1's test suite:
- `tests/test_quiz_endpoint.py` — Dev 3's file, imports `openai` at module scope without a stub
- `tests/test_teachback_endpoint.py` — Dev 3's file, same issue

These are **not** counted in the 87 passing tests. They appear as collection errors (not test failures). Dev 3 needs to fix them with a session-scoped conftest stub (same fix as P4 above).

Run only Dev 1's tests to avoid collection errors:
```bash
cd /mnt/e/transformED-corp/apps/api
source .venv/bin/activate
python3 -m pytest tests/unit/ -q
```

### Test File Locations

```
apps/api/tests/
├── conftest.py                     # session-scoped openai stub (P4 fix)
├── unit/
│   ├── test_content_router.py      # POST /lessons, GET /lessons/{id}, rollback
│   ├── test_extract_node.py        # subprocess extraction, idempotency
│   ├── test_structure_detection.py # font clustering, regex, LLM validation
│   ├── test_chunking.py            # token chunking, overlap, boundary
│   ├── test_embed_node.py          # embeddings, batch, retry, circuit breaker
│   ├── test_lesson_schema.py       # Pydantic ↔ JSON schema round-trip (22 tests)
│   ├── test_langfuse_core.py       # singleton + flush contract (4 tests)
│   ├── test_retry.py               # with_retry() decorator
│   └── test_circuit_breaker.py     # circuit breaker state machine
└── evals/                          # Sprint 2 (not yet created)
```

---

## 14. SPRINT 2 — WHAT'S NEXT

Sprint 2 covers Weeks 4–5 (due ~2026-07-16). All 8 stories are from Epic 2: Content Generation Pipeline.

### Story 2.1: Phase 1 Economy Nodes — All 6 Parallel

Build all 6 economy nodes simultaneously via LangGraph `Send()` fan-out. All use `settings.llm_mini`.

**Nodes to implement (all stubs in graph.py):**
1. `summarise_segment_node` — ≤100 words per segment summary
2. `quiz_generator_node` — 4 options per question, `correct_index` in range, validates as QuizSet
3. `segment_complexity_node` — `textstat.flesch_reading_ease()` + LLM grade-level estimation
4. `jargon_extractor_node` — domain terms + definitions, no empty entries
5. `intervention_messages_node` — exactly 3 messages each for distraction/confusion/fatigue; ZERO LLM calls at runtime
6. `narration_generator_node` — per-slide narration scripts in speaker-voice style

**Critical constraints:**
- `Annotated[list, operator.add]` reducers must be used to prevent `INVALID_CONCURRENT_GRAPH_UPDATE`
- `phase1_barrier` confirmed: all 6 outputs non-empty before lesson_planner starts
- All outputs validate against Pydantic schemas in `app.schemas`
- All nodes: `@with_retry(max_attempts=3)`, Langfuse spans, cost tracked

### Story 2.2: lesson_planner Node

**Input:** `segment_summaries` from Phase 1 — NOT raw chapter text.

This is the most critical constraint in the entire pipeline. Using raw chapter text instead of summaries causes a silent 5× cost overrun (5× more tokens at GPT-4o rates = $15/lesson instead of $3). This constraint must be enforced and tested.

**Model:** `settings.llm_lesson_planner` (default `gpt-4o`)
**Output validates:** LessonMetadata (title, objectives[], segments[], total_duration_min)

### Story 2.3: slide_generator Node

**Input:** lesson_plan from lesson_planner
**Model:** `settings.llm_slide_generator` (default `gpt-4o`)
**Output:** At least 1 slide per segment; each slide: `slide_id`, `title`, `bullets`, `image_url` (nullable)
**Validates against:** `app.schemas.Slide`

### Story 2.4: TTS Node — Sarvam Bulbul v2 + Azure + Browser Fallback

**Provider chain:** SarvamTTSProvider → AzureTTSProvider → Browser Speech

**Important Sarvam-specific behavior:**
- 403 (not 401) = auth failure
- 429 body inspection: `rate_limit_exceeded_error` = retryable; `insufficient_quota_error` = NOT retryable (do not retry on quota exhaustion)
- `is_circuit_open("sarvam")` checked before every call

**Constraint:** Pipeline NEVER fails over TTS — Browser Speech is always available as final fallback. `audio_provider` set to `"sarvam"`, `"azure"`, or `"browser"` in output so the frontend knows what it got.

**Note:** Fix the stale ElevenLabs reference in `tts_node` stub before implementing.

### Story 2.5: image_generator Node — GPT Image 1 Mini + Imagen 4 Fast + Text-Only

**Provider chain:** GPTImage1MiniProvider → Imagen4FastProvider → text-only (image_url = None)

**Constraints:**
- DALL-E 3 is BANNED (shut down May 2026)
- Falls back to `image_url = None` if cost ceiling is near — never fails pipeline over images
- NOTE: `gpt-image-1-mini` deprecates 2026-12-01 — env var swap to `gpt-image-2` planned for Sprint 3

**Note:** Fix the stale DalleImageProvider / DALL-E 3 reference in `image_generator_node` stub before implementing.

### Story 2.6: package_builder Node + lesson_ready WebSocket Push

**Assembly:**
1. Validate assembled dict: `LessonPackage.model_validate(assembled)` — raises immediately on schema violation
2. Write: `lessons.content = package.model_dump(mode="json")`, `lessons.status = 'ready'`
3. Write: `lesson_jobs.status = 'completed'`, `completed_at = now()`
4. Emit `lesson_ready` WebSocket push matching `packages/shared/types/ws.ts` discriminated union

**Coordinate with Dev 4** before implementing the WebSocket push — shape must exactly match `ws.ts`.

Round-trip test: `LessonPackage.model_validate(row["content"])` must pass after writing.

### Story 2.7: Cost Ceiling Enforcement — All Nodes

Wire `cost_tracker.accumulate_cost(lesson_id, cost_usd)` after every provider call. Wire `check_ceiling()` before starting expensive nodes. On breach: downshift providers, complete lesson, set `lesson_jobs.error = "cost_ceiling_exceeded"`.

`cost_tracker.py` already exists and is implemented — it just isn't wired into any node yet.

### Story 2.8: Eval Harness — 5 Representative PDFs

Create `apps/api/tests/evals/` with 5 test PDFs:
- Short (≤10 pages)
- Long (≥100 pages)
- Dense text
- Table-heavy
- Image-heavy

All 5 must produce valid LessonPackage without pipeline crash. Automated scoring: slide quality + quiz relevance recorded in Langfuse.

---

## 15. BMAD PROCESS RULES

### Story-First Gate (NON-NEGOTIABLE)

Before writing ANY code for a new story:

1. Create story file at `docs/stories/{N}-{M}-{story-slug}.md` with all ACs fully defined
2. Commit ONLY the story file: `git commit -m "docs(story-first): Story N-M — {title}"`
3. Push the story-only commit to remote: `git push origin <branch-name>`
4. Verify the story commit is the chronologically FIRST commit on the branch
5. Only THEN begin the RED phase (write failing tests)

**NEVER** write implementation code in the same commit as the story file.
**NEVER** merge a PR where story and implementation share a commit.

### 5-Agent Code Review Gate (Required Before Every PR Merge)

Run `/bmad-code-review` on every PR. The 5 required agent layers are:

| Layer | Agent | What it checks |
|-------|-------|---------------|
| 1 | Story Quality | All ACs testable, story complete before code |
| 2 | Blind Hunter (Security) | IDOR, injection, enumeration, DoS vectors |
| 3 | Test Coverage | Every AC has a test, edge cases covered, no false confidence |
| 4 | AC Completeness | Every AC maps to at least one explicit test assertion |
| 5 | Process Integrity | No LLM calls in wrong modules, no hardcoded models, no rule violations |

**REJECT** any PR whose Senior Developer Review section lists fewer than 5 agent layers. The Story Quality agent is the most critical.

### Sprint Tracker Auto-Update Rule

Whenever any task is marked complete in `docs/dev1-tracker.md`:
1. Change `- [ ]` to `- [x]`
2. Append ` — ✓ YYYY-MM-DD` to the task title line
3. Update the Quick Status Dashboard table (increment Done, decrement Not Started)
4. Update **Last updated** in the header to today's date

Do this immediately, in the same response. Never mark a task complete without also updating the dashboard.

### Branch Naming Convention

**Pattern:** `sprint{N}/s{N}-{M}-{slug}`

| Sprint | Task | Example Branch |
|--------|------|---------------|
| Sprint 1 | S1-2 "PyMuPDF extraction" | `sprint1/s1-2-pymupdf-extract` |
| Sprint 2 | S2-1 "Phase 1 economy nodes" | `sprint2/s2-1-phase1-economy-nodes` |
| Sprint 2 | S2-7 "lesson_planner node" | `sprint2/s2-7-lesson-planner` |

**Steps (execute in order, no exceptions):**
1. If there are uncommitted changes from a previous task, commit them to the current branch first
2. `git checkout main && git checkout -b <branch-name>`
3. Announce the branch name in the first line of response
4. Then begin implementation

**One task, one branch.** Every task gets its own branch based off `main`. Never stack a new task on top of the previous task's branch.

---

## 16. KEY FILE MAP

### Core Infrastructure (Dev 1 owns)

| Purpose | File Path |
|---------|-----------|
| FastAPI app factory + lifespan + router mounts | `apps/api/app/main.py` |
| All env vars via pydantic-settings | `apps/api/app/config.py` |
| JWT verify, Redis, Settings as FastAPI deps | `apps/api/app/dependencies.py` |
| Supabase async client singleton | `apps/api/app/core/db.py` |
| Redis pool lifecycle | `apps/api/app/core/redis.py` |
| Exponential backoff retry decorator | `apps/api/app/core/retry.py` |
| Redis-backed circuit breaker | `apps/api/app/core/circuit_breaker.py` |
| Per-lesson cost accumulation + ceiling | `apps/api/app/core/cost_tracker.py` |
| Langfuse singleton | `apps/api/app/core/langfuse.py` |
| WebSocket connection manager | `apps/api/app/core/websocket.py` |

### Provider Abstraction

| Purpose | File Path |
|---------|-----------|
| Abstract provider ABCs | `apps/api/app/providers/base.py` |
| OpenAI LLM provider | `apps/api/app/providers/llm/openai.py` |
| OpenAI embeddings provider | `apps/api/app/providers/embeddings/openai.py` |
| TTS provider directory | `apps/api/app/providers/tts/` |
| Image provider directory | `apps/api/app/providers/image/` |
| Avatar provider directory | `apps/api/app/providers/avatar/` |

### Content Pipeline

| Purpose | File Path |
|---------|-----------|
| LangGraph pipeline graph (all 15 nodes) | `apps/api/app/modules/content/pipeline/graph.py` |
| PDF extraction subprocess | `apps/api/app/modules/content/pipeline/nodes/extract_subprocess.py` |
| Structure detection helpers | `apps/api/app/modules/content/pipeline/nodes/structure_detection.py` |
| Chunking helpers | `apps/api/app/modules/content/pipeline/nodes/chunking.py` |
| Node package init (empty) | `apps/api/app/modules/content/pipeline/nodes/__init__.py` |
| Content module router | `apps/api/app/modules/content/router.py` |

### Workers

| Purpose | File Path |
|---------|-----------|
| ARQ WorkerSettings entry point | `apps/api/app/workers/main.py` |
| Content pipeline ARQ job | `apps/api/app/workers/jobs/content_pipeline.py` |

### Schemas

| Purpose | File Path |
|---------|-----------|
| Pydantic lesson schemas | `apps/api/app/schemas/lesson.py` |
| Schemas package init | `apps/api/app/schemas/__init__.py` |

### Tests

| Purpose | File Path |
|---------|-----------|
| pytest conftest (openai stub fixture) | `apps/api/tests/conftest.py` |
| Content router tests | `apps/api/tests/unit/test_content_router.py` |
| Extract node tests | `apps/api/tests/unit/test_extract_node.py` |
| Structure detection tests | `apps/api/tests/unit/test_structure_detection.py` |
| Chunking tests | `apps/api/tests/unit/test_chunking.py` |
| Embed node tests | `apps/api/tests/unit/test_embed_node.py` |
| Lesson schema round-trip tests | `apps/api/tests/unit/test_lesson_schema.py` |
| Langfuse singleton tests | `apps/api/tests/unit/test_langfuse_core.py` |
| Retry decorator tests | `apps/api/tests/unit/test_retry.py` |
| Circuit breaker tests | `apps/api/tests/unit/test_circuit_breaker.py` |

### Documentation & Tracking

| Purpose | File Path |
|---------|-----------|
| Dev 1 sprint task tracker | `docs/dev1-tracker.md` |
| Dev 1 epic + story specs | `docs/epics.md` |
| Sprint status YAML | `_bmad-output/implementation-artifacts/sprint-status.yaml` |
| This context document | `learning-docs/CONTEXT-NEW-CHAT.md` |

### Shared Contracts (FROZEN — 4-dev PR to change)

| Purpose | File Path |
|---------|-----------|
| Lesson package JSON schema | `packages/shared/lesson_package.schema.json` |
| Lesson TypeScript types | `packages/shared/types/lesson.ts` |
| WebSocket discriminated union types | `packages/shared/types/ws.ts` |

### Database

| Purpose | File Path |
|---------|-----------|
| Initial schema migration (APPLIED, FROZEN) | `supabase/migrations/20260611000000_initial_schema.sql` |
| Inline embedding + books table migration (APPLIED, FROZEN) | `supabase/migrations/20260625000000_chunks_inline_embedding.sql` |

### CI/CD

| Purpose | File Path |
|---------|-----------|
| GitHub Actions CI (lint + test) | `.github/workflows/ci.yml` |
| GitHub Actions deploy (Railway) | `.github/workflows/deploy.yml` |
| Railway service config | `railway.toml` |
| Python project config | `apps/api/pyproject.toml` |

---

## 17. CURRENT ENVIRONMENT COMMANDS

All commands assume working directory is `/mnt/e/transformED-corp/apps/api` unless noted.

### Start Redis (Docker)
```bash
docker start redis-dev
# Or, if container doesn't exist yet:
docker run -d --name redis-dev -p 6379:6379 redis:7-alpine
```

### Activate Virtual Environment
```bash
cd /mnt/e/transformED-corp/apps/api
source .venv/bin/activate
```

### Start FastAPI Server (Terminal 1)
```bash
cd /mnt/e/transformED-corp/apps/api
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --env-file .env
# With debug logging:
uvicorn app.main:app --host 0.0.0.0 --port 8000 --env-file .env --log-level debug
```

API docs: http://localhost:8000/docs

### Start ARQ Worker (Terminal 2)
```bash
cd /mnt/e/transformED-corp/apps/api
source .venv/bin/activate
arq app.workers.main.WorkerSettings
```

### Run Tests
```bash
cd /mnt/e/transformED-corp/apps/api
source .venv/bin/activate
python3 -m pytest tests/unit/ -q
# Verbose with coverage:
python3 -m pytest tests/unit/ -v --tb=short
```

### Install Missing Packages
```bash
cd /mnt/e/transformED-corp/apps/api
source .venv/bin/activate
uv add tiktoken docling pytesseract
sudo apt install tesseract-ocr
```

### Get a Test JWT from Supabase
```bash
# Replace with real test user email/password
curl -X POST \
  'https://REDACTEDPROJECTREF.supabase.co/auth/v1/token?grant_type=password' \
  -H 'apikey: REDACTED_SUPABASE_ANON_KEY' \
  -H 'Content-Type: application/json' \
  -d '{"email": "test@example.com", "password": "your-test-password"}'
# The response contains "access_token" — use it as the Bearer token
```

### Upload a Test PDF
```bash
# Replace <JWT> with the access_token from above
curl -X POST http://localhost:8000/api/content/lessons \
  -H 'Authorization: Bearer <JWT>' \
  -F 'file=@/path/to/test.pdf'
# Returns: {"lesson_id": "...", "job_id": "..."}
```

### Poll Lesson Status
```bash
curl -X GET http://localhost:8000/api/content/lessons/<lesson_id> \
  -H 'Authorization: Bearer <JWT>'
# Returns: {"status": "generating"} or {"status": "ready", "content": {...}}
```

### Check Pipeline Progress (Supabase dashboard or direct query)
```bash
# Via Supabase table editor: select * from lesson_jobs where lesson_id = '<lesson_id>'
# Fields to watch: status, last_node, node_outputs, attempt, error
```

### View Logs (ARQ worker output shows node-by-node progress)
```
INFO: Starting content_pipeline_job for lesson <lesson_id>
INFO: extract_node complete — 45 pages extracted
INFO: structure_node complete — 8 chapters detected
INFO: chunk_node complete — 312 chunks created
INFO: embed_node complete — 312 chunks embedded
```

### Git Status / Branch
```bash
cd /mnt/e/transformED-corp
git status
git branch
# Current: sprint1/s1-9-post-lessons-endpoint
# For Sprint 2, start from main:
git checkout main
git pull origin main
git checkout -b sprint2/s2-1-phase1-economy-nodes
```

---

*End of context document. If anything here conflicts with CLAUDE.md, CLAUDE.md wins.*
