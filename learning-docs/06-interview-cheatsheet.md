# Sprint 1 — Interview Cheat Sheet

> **For the morning of the interview.** Read this, don't read the longer docs. Everything you need in one scannable page.

---

## ⚡ The 30-Second Project Pitch

> "I worked on TransformED AI — an EdTech startup building an AI-powered personalized learning platform. Students upload textbook chapters, and the system automatically generates complete interactive lessons: slides, quiz questions, narration scripts, and an AI tutor backed by vector search. My work in Sprint 1 was the content ingestion pipeline — the foundation layer that takes a raw PDF and turns it into structured, searchable data: text extraction → document structure → semantic chunking → vector embeddings stored in pgvector."

---

## 📋 The 5 Stories (One Liner Each)

| Story | Name | Your One Sentence |
|-------|------|-------------------|
| **1.1** | API + Queue | FastAPI POST /lessons validates a PDF, uploads to Supabase Storage, enqueues an ARQ job, and returns 202 in ~200ms |
| **1.2** | PDF Extraction | 5-library cascade (pypdfium2→pdfplumber→pdftext→docling→pytesseract) runs in an isolated subprocess at 300 DPI |
| **1.3** | Structure Detection | Font-size clustering + regex finds headings, then GPT-4o-mini cleans up edge cases |
| **1.4** | Semantic Chunking | Greedy sentence packing to 512-token chunks with 64-token overlap using cl100k_base tokenizer |
| **1.5** | Embeddings | Provider-abstracted OpenAI calls store 1536-dim vectors in pgvector; IS NULL filter = idempotent & never regenerated |

---

## 🔢 Numbers You Must Know Cold

| Number | What |
|--------|------|
| **50 MB** | Max PDF size |
| **5/min** | Rate limit per user on POST /lessons |
| **~200ms** | Endpoint response time (async, returns immediately) |
| **512 tokens** | Target chunk size |
| **64 tokens** | Overlap between chunks |
| **cl100k_base** | Tokenizer (must match text-embedding-3-small) |
| **1536** | Embedding vector dimensions |
| **2048** | Max texts per OpenAI embedding batch |
| **$0.00002** | text-embedding-3-small cost per 1K tokens |
| **$3.00** | Cost ceiling per lesson (hard limit) |
| **300 DPI** | Minimum render resolution for OCR/images (= scale 300/72 = 4.17×) |
| **87** | Unit tests passing at Sprint 1 end |
| **15** | Total pipeline nodes (4 built + 11 stubs) |
| **3** | Max retries on OpenAI calls (exponential backoff) |
| **5** | Circuit breaker opens after 5 failures in 2 min |
| **12** | Bugs caught by the 5-agent code review on Story 1.5 |

---

## ❓ "Why Didn't You Use...?" Answers

| If they ask about... | Your answer (say exactly this) |
|---------------------|-------------------------------|
| **PyMuPDF / fitz?** | "AGPL-3.0 — using it in a commercial SaaS requires open-sourcing the entire product. We used pypdfium2 (Apache 2.0) instead." |
| **Celery?** | "Our backend is async FastAPI. Celery is synchronous-native and needs workarounds for asyncio. ARQ is pure asyncio — tasks are just async functions." |
| **PostgresSaver (LangGraph)?** | "Creates an opaque schema we can't query. Our custom lesson_jobs table gives us queryable status, progress %, per-node checkpoints, and cost tracking." |
| **Pinecone / Weaviate?** | "pgvector in Supabase keeps everything in one DB. No sync issues, Supabase RLS applies to vector searches too." |
| **Remote JWT verification?** | "50–100ms latency per request. PyJWT + our JWT secret verifies locally in ~0.1ms — 1000× faster, equally secure." |
| **OpenAI Batch API?** | "Batch API has a 24-hour completion window — completely incompatible with real-time lesson generation." |
| **Re-generating embeddings on demand?** | "10,000× cost difference at scale. $5 to embed everything once vs $50/day if regenerated per request." |
| **WebSocket for upload response?** | "Polling is simpler for MVP. Full real-time WebSocket push is Sprint 2." |

---

## ⭐ STAR Bullets (Expand Any of These in Interview)

### Story 1.1 — API + Queue
- **S**: 5–15 min generation can't block a 30s HTTP connection
- **T**: Accept PDF, validate, store, queue job, return in 200ms
- **A**: ARQ (asyncio-native); 3-layer file validation; FK-ordered inserts; dedup key; hard-delete rollback
- **R**: 202 response in ~200ms; one job per lesson; clean retry on failure

### Story 1.2 — PDF Extraction
- **S**: PDFs mix scanned/digital/tables; PyMuPDF (obvious choice) is AGPL-banned
- **T**: Multi-library extraction stack, no AGPL, crash-safe
- **A**: pypdfium2→pdftext→pdfplumber→docling→pytesseract cascade; subprocess isolation; 300 DPI
- **R**: All 3 PDF types handled; malformed PDFs can't kill the worker; fixed silent OCR-overwrite bug

### Story 1.3 — Structure Detection
- **S**: Raw text is one blob; need chapters/sections for lesson generation
- **T**: Detect document hierarchy across wildly different PDF formats
- **A**: Font-size clustering (25%+larger+bold=heading) + regex + GPT-4o-mini cleanup
- **R**: Works on scanned AND digital PDFs; 80% cheaper than pure-LLM detection

### Story 1.4 — Chunking
- **S**: Sections too large for embedding model; need semantically complete pieces
- **T**: 512-token chunks, 64-token overlap, never break mid-sentence
- **A**: tiktoken cl100k_base (exact model tokenizer); greedy sentence packing; token-level overlap
- **R**: Token-accurate, semantically complete, boundary context preserved

### Story 1.5 — Embeddings
- **S**: Need semantic search for Phase 2 RAG tutor; keyword search misses paraphrases
- **T**: Vectorize all chunks once, store in pgvector, provider-swappable
- **A**: EmbeddingsProvider ABC; @with_retry(3); circuit breaker; IS NULL idempotency; batch length guard
- **R**: All chunks vectorized; provider-swappable by env var; safe to retry; 12 bugs caught before merge

---

## 🏗️ Architectural Patterns (Know These by Name)

| Pattern | Where in Sprint 1 | 10-Word Summary |
|---------|-------------------|----------------|
| **Queue-based async** | ARQ + POST /lessons | Accept fast, process slow in background |
| **Idempotent checkpoint** | lesson_jobs.node_outputs | ARQ retry skips already-completed nodes |
| **Provider abstraction (ABC)** | providers/base.py + providers/ | Swap AI providers without touching business logic |
| **Circuit breaker** | Redis-backed, all providers | Stop calling failing service; try again after cooldown |
| **Process isolation** | extract_subprocess.py | Subprocess crash can't kill the parent worker |
| **Embed once, reuse always** | IS NULL filter in embed_node | Content embedded at ingestion, never regenerated |
| **Hybrid heuristics** | Structure detection | Rules for the 90%, LLM for the 10% edge cases |
| **Modular monolith** | FastAPI module structure | One deploy, domain-separated, microservice-ready |

---

## 🔬 The 5-Agent Code Review (Know the Story)

Every PR goes through 5 adversarial AI agents:

| Agent | Looks for |
|-------|----------|
| Story Quality | ACs complete, story written before code |
| Blind Hunter (Security) | IDOR, injection, DoS vectors |
| Test Coverage | Every AC tested, edge cases covered |
| AC Completeness | Every AC maps to a test assertion |
| Process Integrity | No hardcoded models, no rule violations, no wrong modules |

**Story 1.5 found 12 bugs** including:
- **P1 (critical)**: Checkpoint `except Exception` was *swallowing* DB write failures — node returned "success" even when checkpoint wasn't saved → next ARQ retry re-embeds ALL chunks → double cost
- **P5 (serious)**: `zip(batch, embeddings)` silently truncates if OpenAI returns fewer vectors — wrong embeddings stored with no error

---

## 💬 One-Liners to Drop in Any Interview

Say one of these when relevant — they make you sound like you think at the system level:

- *"We used ARQ not Celery because our entire stack is async and Celery's native model is synchronous workers."*
- *"PyMuPDF is banned — AGPL would force us to open-source the entire product."*
- *"All model names come from env vars, never hardcoded — we're doing model evaluation so we swap providers by changing a config value."*
- *"Every pipeline node is checkpoint-idempotent — if the worker crashes, resuming only re-runs incomplete nodes."*
- *"Embeddings are generated once at ingestion and never regenerated — prevents a 10,000× cost explosion at scale."*
- *"The provider abstraction means any AI provider is swappable by implementing one class."*
- *"We run PDF parsing in an isolated subprocess — a malformed PDF can't crash the job queue for all users."*
- *"The 5-agent adversarial code review caught 12 bugs on one story before it reached main, including one that would have doubled embedding costs on every retry."*

---

## 🗂️ File Locations (If Asked)

| Topic | File |
|-------|------|
| POST /lessons endpoint | `apps/api/app/modules/content/router.py` |
| ARQ job worker | `apps/api/app/workers/jobs/content_pipeline.py` |
| LangGraph pipeline | `apps/api/app/modules/content/pipeline/graph.py` |
| PDF extraction subprocess | `apps/api/app/modules/content/pipeline/nodes/extract_subprocess.py` |
| Chunking algorithm | `apps/api/app/modules/content/pipeline/nodes/chunking.py` |
| Structure detection | `apps/api/app/modules/content/pipeline/nodes/structure_detection.py` |
| Provider interfaces (ABCs) | `apps/api/app/providers/base.py` |
| Embeddings provider | `apps/api/app/providers/embeddings/openai.py` |
| Settings (all env vars) | `apps/api/app/config.py` |
