# HIE — Dev 1 Epics (Content Pipeline + Infra)

**Owner:** Dev 1 (developer1-cybersmith)
**Domain:** Infra · Content Pipeline (15 nodes) · Provider Abstraction · Embeddings · Langfuse
**Source:** PRD 1.0 Final (10 Jun 2026) + Decisions Update (25 Jun 2026) + CLAUDE.md

---

## Epic 1: Content Ingestion Pipeline

**Goal:** PDF upload → extract → structure → chunk → embed → stored in pgvector. First end-to-end book ingestion.

**Acceptance Criteria:**
- Student can upload a PDF via `POST /api/content/lessons`; lesson_id returned immediately
- All chunks stored in Supabase pgvector with `embedding vector(512)` (dimensions set permanently at first run)
- Ingestion pipeline idempotent — ARQ retry skips completed nodes via `lesson_jobs.last_node`
- `books.page_count` written; `lessons.status = 'generating'`

### Story 1.1: POST /lessons Endpoint + ARQ Job Enqueue

**As a** student uploading a chapter PDF,
**I want** the upload to return a lesson_id immediately and start processing in the background,
**so that** I don't wait for the full pipeline before getting a response.

**Acceptance Criteria:**
- `POST /api/content/lessons` accepts multipart PDF; validates MIME type + magic bytes
- Creates `books` row, `lessons` row (`status='generating'`), `lesson_jobs` row (`status='pending'`)
- Stores PDF to Supabase Storage; writes `lessons.source_file_path`
- Enqueues ARQ job `content_pipeline_job(lesson_id)`
- Returns `201 {"lesson_id": "...", "job_id": "..."}` immediately
- `slowapi` rate limit: `"5/minute"` per user JWT sub
- ARQ worker: `lesson_jobs.status = 'running'` on pickup; `'completed'` on success; `'failed'` on error

### Story 1.2: PDF Extraction Node — pypdfium2 + pdftext + Docling + Tesseract OCR

**As a** content pipeline,
**I want** to extract all text, font metadata, tables, and images from a PDF in an isolated subprocess,
**so that** malicious PDFs cannot exploit the main FastAPI process and downstream nodes receive high-accuracy structured data.

**Acceptance Criteria:**
- Uses **pypdfium2** (Apache 2.0) for text extraction (97% accuracy, 100× faster than pdfplumber) — NOT PyMuPDF/fitz (AGPL-3.0 banned) and NOT pdfplumber for text (75% accuracy, too slow)
- **pdfplumber** (MIT) retained ONLY for table detection (`page.extract_tables()` to trigger docling) — zero text extraction via pdfplumber
- **pdftext** (Apache 2.0) extracts structured font/layout metadata (blocks → lines → spans with fontname, size, bold flag); output included in subprocess JSON as `font_blocks` list; consumed by Story 1.3 structure detection node
- Docling (Apache 2.0) converts whole document to structured markdown when pdfplumber detects ≥ 1 table page
- Tesseract OCR fallback when text yield < `OCR_TEXT_YIELD_THRESHOLD` chars/page (env var, default 50); page rendering via pypdfium2 at **300 DPI**
- Embedded images extracted at **300 DPI** using pypdfium2 page rendering and stored to Supabase Storage (lesson-images bucket)
- PDF parsed in isolated subprocess (security requirement — never call PDF parsers in the main ARQ worker process)
- `books.page_count` written to DB after extraction
- Node is idempotent — skips if `lesson_jobs.node_outputs["extract"]` already exists
- Checkpoint written on success: `lesson_jobs.last_node = 'extract'`, `node_outputs["extract"]` cached

### Story 1.3: Structure Detection Node — Rule-Based + LLM Validation

**As a** content pipeline,
**I want** to detect chapter and section boundaries in the extracted text,
**so that** chunking respects the document's logical hierarchy.

**Acceptance Criteria:**
- Rule-based first pass: font sizes, TOC entries, numbering patterns (regex)
- Hierarchy: Chapter → Section → Topic (never full-book single structure per PRD §5 principle 6)
- LLM validation second pass: `settings.llm_mini` validates boundaries and corrects misdetections
- `complete_structured()` used for LLM call — output validates as `DocumentStructure` Pydantic model
- `@with_retry(max_attempts=3)` on LLM call; Langfuse span records token count
- Node idempotent; checkpoint written on success

### Story 1.4: Semantic Chunking Node

**As a** content pipeline,
**I want** to split each document section into token-bounded chunks,
**so that** no chunk exceeds the LLM context budget and each chunk maps to a meaningful topic.

**Acceptance Criteria:**
- Consumes corrected `DocumentStructure` from structure detection
- Target ≤ 800 tokens per chunk; 64-token overlap
- Hierarchy preserved: each chunk carries `chapter_id`, `section`, `page_start`, `page_end`
- All chunks written to `chunks` table with correct FKs: `chapter_id`, `book_id`, `chunk_index`
- Never creates a full-book single chunk (PRD §5 principle 6)
- A 20-page chapter produces ≥ 3 chunks
- Node idempotent; checkpoint written on success

### Story 1.5: Embeddings + pgvector Storage Node

**As a** content pipeline,
**I want** to generate vector embeddings for all chunks and store them in pgvector,
**so that** the Phase 2 RAG tutor can perform approximate nearest-neighbour search.

**Acceptance Criteria:**
- Model: `text-embedding-3-small` (fixed — not configurable)
- **CRITICAL:** `dimensions=512` in every API call — irreversible after first ingestion (migration 20260628000001 applied)
- Batch all chunks (max 2048 per API call)
- Writes `embedding`, `token_count`, `embedding_metadata` (model, version, timestamp) to `chunks`
- HNSW index on `chunks.embedding` (`vector_cosine_ops`) used in search queries
- Embeddings computed ONCE at ingestion — never regenerated for stored content
- `@with_retry(max_attempts=3)`; cost tracked via `cost_tracker.accumulate_cost()`
- Node idempotent; checkpoint written on success; second run skips entirely

### Epic 1 Retrospective

Review: ingestion pipeline reliability, OCR accuracy on test PDFs, chunking quality, embedding search recall.

---

## Epic 2: Content Generation Pipeline

**Goal:** Ingested chunks → full `LessonPackage` JSONB with slides, quiz, audio, images. Investor demo ready.

**Acceptance Criteria:**
- All 6 Phase 1 economy nodes run in parallel via Send() fan-out
- Phase 2 (lesson_planner + slide_generator) starts ONLY after all Phase 1 complete
- `lessons.content` contains valid `LessonPackage` JSONB after pipeline
- `lesson_ready` WebSocket push delivered matching `packages/shared/types/ws.ts`
- Cost ceiling $3.00/lesson enforced; never aborts — downshifts to cheapest provider

### Story 2.1: Phase 1 Economy Nodes — All 6 Parallel

**As a** content pipeline,
**I want** to run all 6 economy nodes simultaneously via Send() fan-out,
**so that** segment processing takes the time of the slowest node, not the sum.

**Acceptance Criteria:**
- All 6 nodes implemented: `summarise_segment`, `quiz_generator`, `segment_complexity`, `jargon_extractor`, `intervention_messages`, `narration_generator`
- All use `settings.llm_mini` (`LLM_MINI` env var)
- `Annotated[list, operator.add]` reducers prevent INVALID_CONCURRENT_GRAPH_UPDATE (already in graph.py)
- `phase1_barrier` confirmed: all 6 outputs non-empty before lesson_planner starts
- `summarise_segment` output ≤ 100 words per segment
- `quiz_generator` output: exactly 4 options per question, `correct_index` in range
- `intervention_messages`: exactly 3 messages each for distraction, confusion, fatigue — zero LLM calls at runtime
- `jargon_extractor`: no empty terms or definitions
- All outputs validate against Pydantic schemas in `app.schemas`
- All nodes: `@with_retry(max_attempts=3)`; Langfuse spans; cost tracked

### Story 2.2: lesson_planner Node

**As a** content pipeline,
**I want** to generate a structured lesson plan from Phase 1 segment summaries,
**so that** the lesson structure is coherent and costs 5× less than using raw chapter text.

**Acceptance Criteria:**
- Input: `segment_summaries` from Phase 1 — NOT raw chapter text (violating this is a silent 5× cost overrun)
- Model: `settings.llm_lesson_planner` (`LLM_LESSON_PLANNER` env var, default `gpt-4o`)
- `complete_structured()` with `LessonMetadata` Pydantic model
- Output validates: title, objectives[], segments[], total_duration_min
- Langfuse span records token count and `token_cost_usd`
- `@with_retry(max_attempts=3)`; checkpoint written on success

### Story 2.3: slide_generator Node

**As a** content pipeline,
**I want** to generate a slide deck from the lesson plan,
**so that** each segment has structured slides for the custom React player.

**Acceptance Criteria:**
- Input: lesson_plan from lesson_planner
- Model: `settings.llm_slide_generator` (`LLM_SLIDE_GENERATOR` env var, default `gpt-4o`)
- At least 1 slide per segment; each slide: `slide_id`, `title`, `bullets`, `image_url` (nullable)
- Output validates against `app.schemas.Slide`
- `@with_retry(max_attempts=3)`; checkpoint written on success

### Story 2.4: TTS Node — Sarvam Bulbul v2 + Azure + Browser Fallback

**As a** content pipeline,
**I want** to synthesise narration scripts to `.mp3` audio per segment,
**so that** the lesson player has pre-generated audio for every slide.

**Acceptance Criteria:**
- Fallback chain: SarvamTTSProvider (Bulbul v2) → AzureTTSProvider → Browser Speech
- Sarvam: 403 (not 401) = auth failure; inspect 429 body — `rate_limit_exceeded_error` retryable, `insufficient_quota_error` NOT retryable
- `is_circuit_open("sarvam")` checked before each call
- Audio per segment stored to Supabase Storage (lesson-audio bucket); URL in `Narration.audio_url`
- `audio_provider` set to `"sarvam"`, `"azure"`, or `"browser"` in output
- Pipeline NEVER fails over TTS — Browser Speech is always available
- TTS cost tracked via `cost_tracker.accumulate_cost()`

### Story 2.5: image_generator Node — GPT Image 1 Mini + Imagen 4 Fast + Text-Only

**As a** content pipeline,
**I want** to generate illustrative images for slides,
**so that** visual learners have a supporting image for complex concepts.

**Acceptance Criteria:**
- Provider chain: GPTImage1MiniProvider → Imagen4FastProvider → text-only (image_url = None)
- DALL-E 3 is BANNED (shut down May 2026)
- Falls back to `image_url = None` (text-only) if cost ceiling is near — never fails pipeline over images
- Image cost tracked via `cost_tracker.accumulate_cost()`
- NOTE: gpt-image-1-mini deprecates 2026-12-01 — env var swap to gpt-image-2 in Sprint 3

### Story 2.6: package_builder Node + lesson_ready WebSocket Push

**As a** student,
**I want** to be notified when my lesson is ready to play,
**so that** I can start learning immediately.

**Acceptance Criteria:**
- Assembles all node outputs into `LessonPackage`
- `LessonPackage.model_validate(assembled)` — raises immediately if schema violated
- `lessons.content = package.model_dump(mode="json")`; `lessons.status = 'ready'`
- `lesson_jobs.status = 'completed'`; `completed_at = now()`
- Emits `lesson_ready` WebSocket push matching `packages/shared/types/ws.ts` discriminated union
- Round-trip: `LessonPackage.model_validate(row["content"])` passes after write
- Coordinate shape with Dev 4 before implementing

### Story 2.7: Cost Ceiling Enforcement — All Nodes

**As a** product,
**I want** every LLM/TTS/image call to track cost and downshift providers on ceiling breach,
**so that** no lesson costs more than $3.00 regardless of input complexity.

**Acceptance Criteria:**
- `cost_tracker.accumulate_cost(lesson_id, cost_usd)` called after every provider call
- `check_ceiling()` checked before starting expensive nodes
- On breach: downshift to cheapest providers; complete lesson; set `lesson_jobs.error = "cost_ceiling_exceeded"`
- Test run exceeding $3.00 mid-pipeline completes without crashing
- Cost visible in `lesson_jobs.cost_usd` and Langfuse span metadata

### Story 2.8: Eval Harness — 5 Representative PDFs

**As a** developer,
**I want** automated quality scoring across 5 diverse PDFs,
**so that** I can validate the full pipeline produces quality output before Sprint 3.

**Acceptance Criteria:**
- 5 PDFs: short (≤10 pages), long (≥100 pages), dense text, table-heavy, image-heavy
- All 5 produce a valid `LessonPackage` without pipeline crash
- Automated scoring: slide quality + quiz relevance recorded in Langfuse
- Eval harness in `apps/api/tests/evals/`

### Epic 2 Retrospective

Review: Phase 1 parallelism latency, lesson quality scores from eval harness, cost per lesson, TTS audio quality.

---

## Epic 3: Observability, Eval Scale & Admin

**Goal:** Production-grade observability. Admin panel. 20-PDF eval. Prompt iteration from data.

**Acceptance Criteria:**
- All pipeline nodes have Langfuse cost attribution
- Admin panel live: job status, retry, cost aggregation
- 20 PDFs pass eval harness

### Story 3.1: Expanded Eval Harness — 20 PDFs + Prompt Iteration

**As a** developer,
**I want** quality data across 20 diverse PDFs and data-driven prompt improvements,
**so that** pipeline quality is validated at scale before real students.

**Acceptance Criteria:**
- 20 PDFs covering all failure modes
- At least one node prompt improved based on Langfuse scores (≥5% improvement threshold)
- Before/after scores committed; no blind prompt edits

### Story 3.2: Admin Panel — Jobs, Costs, Retry

**As an** admin,
**I want** visibility into all pipeline jobs and the ability to retry failed ones,
**so that** I can resolve issues without touching the database.

**Acceptance Criteria:**
- `GET /api/admin/jobs` — all jobs with status + cost
- `POST /api/admin/jobs/{job_id}/retry` — re-enqueues failed job
- `GET /api/admin/costs` — cost aggregation per lesson and per user

### Story 3.3: Pipeline Cost Attribution in Langfuse

**As a** developer,
**I want** every pipeline node's cost visible in Langfuse,
**so that** I can identify the most expensive nodes and optimise them.

**Acceptance Criteria:**
- Every Langfuse span includes `token_cost_usd` in metadata
- No node missing cost attribution
- Dashboard shows per-node cost breakdown per lesson

### Epic 3 Retrospective

Review: prompt quality improvements, admin panel usability, eval coverage gaps.

---

## Epic 4: Launch Readiness

**Goal:** Load-tested, rate-limited, Stripe-ready, disaster-recovery-documented, first paying student.

### Story 4.1: Load Test — 50 Concurrent Lesson Generations

**As a** developer,
**I want** to validate the pipeline under 50 concurrent jobs,
**so that** I know the system won't degrade on launch day.

**Acceptance Criteria:**
- 50 concurrent jobs complete without crash
- P99 enqueue latency < 500ms
- Pipeline completion within SLA (≤15 min per lesson)
- No Redis drops; cost ceiling respected under load

### Story 4.2: Rate Limiting + Stripe Checkout

**As a** product,
**I want** upload rate limiting and a payment flow,
**so that** we can charge for lessons and prevent abuse.

**Acceptance Criteria:**
- `"5/minute"` per-user limit on `POST /api/content/lessons` returns `429` with `Retry-After`
- Stripe Hosted Checkout page; webhook updates user access tier in DB

### Story 4.3: RLS Security Audit

**As a** security reviewer,
**I want** all Supabase tables audited for RLS correctness,
**so that** no user can read another user's lessons or attention data.

**Acceptance Criteria:**
- All tables audited; `attention_consent` gate verified
- No table accessible without authenticated JWT
- Audit report committed to `docs/`

### Story 4.4: Backups, Disaster Recovery + Runbook

**As an** operator,
**I want** a tested recovery procedure and a written runbook,
**so that** any on-call engineer can resolve the 5 most common failure scenarios.

**Acceptance Criteria:**
- Restore from backup tested; completes in < 30 min
- Runbook: 5 scenarios, ≤5 steps each, tested by a teammate
- On-call rotation established

### Story 4.5: Production Launch — First Paying Student

**As a** business,
**I want** the first paying student to complete a full session without manual intervention,
**so that** we validate the end-to-end product with a real user.

**Acceptance Criteria:**
- Full lesson pipeline runs in production with a real PDF
- Lesson plays in browser for a real user who paid via Stripe
- All three monitoring dashboards populated (Langfuse, Sentry, Railway)
- CES data flows to Dev 3's analytics pipeline

### Epic 4 Retrospective

Review: launch readiness gaps, on-call handoff, first paying student feedback.
