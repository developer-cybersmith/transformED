# Sprint 1 — Big Picture Overview

> **Who this is for**: You're a CS student who wants to confidently explain this project in a job interview. This document gives you the 30,000-foot view. Detailed docs for each story are in the files that follow.

---

## 🎓 What is TransformED AI?

TransformED AI is an EdTech startup building a personalized AI tutoring platform. The idea is simple: a student uploads a textbook chapter (as a PDF), and the system automatically builds a complete interactive lesson — structured slides, quiz questions, narration scripts, and semantic search capability for an AI tutor.

The goal stated in the project: **first paying student completes a full session by end of Week 10.**

---

## 🏃 What is Sprint 1?

Sprint 1 built the **content ingestion pipeline** — the foundation that everything else sits on. Think of it as the "digestion" step: take a raw textbook PDF and turn it into clean, structured, searchable data that AI nodes can work with in Sprint 2.

Five stories were completed:

| Story | Name | What it does |
|-------|------|-------------|
| 1.1 | API + Job Queue | The "front door" — accept a PDF upload, store it, kick off background processing |
| 1.2 | PDF Extraction | Read the PDF using 5 libraries, handle scanned pages, extract images |
| 1.3 | Structure Detection | Find chapters, sections, sub-sections within the raw text |
| 1.4 | Semantic Chunking | Split sections into token-sized pieces with context overlap |
| 1.5 | Embeddings + pgvector | Turn chunks into 1536-dimensional vectors and store them in Supabase |

---

## 🗺️ The Flow (End to End)

```
Student uploads PDF
        │
        ▼
POST /lessons (FastAPI)
  - Validate file (size, magic bytes, MIME type)
  - INSERT: books → lessons → lesson_jobs
  - Upload PDF to Supabase Storage
  - Enqueue ARQ background job
  - Return 202 Accepted + lesson_id (in ~200ms)
        │
        ▼
ARQ Worker (background job)
  - Mark status → "running"
  - Call run_pipeline(lesson_id, ...)
        │
        ▼
LangGraph Pipeline (15 nodes)
  ┌─────────────────────────────────────┐
  │ Node 1: extract_node                │ ← PDF → raw text + images + font metadata
  │ Node 2: structure_node              │ ← raw text → sections (chapter/section/topic)
  │ Node 3: chunk_node                  │ ← sections → 512-token chunks with 64-token overlap
  │ Node 4: embed_node                  │ ← chunks → 1536-dim vectors stored in pgvector
  │ Nodes 5-15: TODO stubs (Sprint 2)   │ ← lesson plan, slides, quiz, TTS, images, package
  └─────────────────────────────────────┘
        │
        ▼
lesson_jobs.status → "ready"
chunks table: filled with text + embeddings
books.status → "ready"
Redis pub/sub: publish "lesson_ready" event
```

---

## ⭐ STAR Method: The Full Sprint

Use this when an interviewer says *"Tell me about a project you worked on."*

**Situation**

We were building an AI tutoring platform from scratch. The foundational problem: how do you take an unstructured textbook PDF and make it usable by AI models? Textbooks are notoriously messy — they mix scanned pages, complex tables, and inconsistent formatting. Before any lesson could be generated, the content had to be extracted, understood, and converted into a format that language models can efficiently search.

**Task**

Build a production-grade 4-node content ingestion pipeline (PDF extraction → structure detection → semantic chunking → vector embedding storage) with these constraints:
- **Idempotent**: safe to retry if the ARQ worker crashes mid-job
- **Cost-aware**: $3.00/lesson ceiling enforced
- **Provider-swappable**: AI providers replaceable via environment variable
- **Legally compliant**: avoid AGPL-licensed libraries (would force open-sourcing the product)

**Action**

- Built an async POST /lessons endpoint with 3-layer file validation, Supabase Storage upload, ARQ job enqueue with deduplication, and full rollback on failure
- Chose pypdfium2 (Apache 2.0) over PyMuPDF — AGPL licensing on PyMuPDF would have required open-sourcing the entire SaaS product
- Ran PDF parsing in an isolated subprocess so malformed PDFs cannot crash the ARQ worker
- Implemented hybrid structure detection: font-size clustering + regex patterns + GPT-4o-mini cleanup
- Built semantic chunker with 512-token target, 64-token overlap, using the exact cl100k_base tokenizer the embedding model uses
- Created a provider abstraction layer (Abstract Base Classes) so embed_node only knows about the EmbeddingsProvider interface — never imports OpenAI directly
- Stored 1536-dimensional vectors in Supabase pgvector with IS NULL idempotency (only embed chunks without vectors)
- Applied a 5-agent adversarial code review on every story — caught 12 production bugs including one that would have doubled embedding costs on every ARQ retry

**Result**

A complete, production-ready ingestion pipeline. Each node is checkpoint-idempotent: if the worker crashes, it resumes from the last completed node. 87 unit tests passing. The provider abstraction means swapping OpenAI for any other embedding service is a one-line env var change.

---

## 🔢 Key Numbers to Remember

| Number | What it means |
|--------|--------------|
| **50 MB** | Max PDF upload size |
| **5/min** | Rate limit on POST /lessons per user |
| **512 tokens** | Target chunk size |
| **64 tokens** | Overlap between consecutive chunks |
| **1536 dims** | Vector size (text-embedding-3-small) |
| **2048** | Max texts per OpenAI embedding batch |
| **$3.00** | Cost ceiling per lesson |
| **300 DPI** | Minimum render resolution for images and OCR |
| **87** | Unit tests passing at end of Sprint 1 |
| **15** | Total pipeline nodes (4 built, 11 stubs for Sprint 2) |

---

## 🛠️ Technologies Used (and why)

| Technology | What it does | Why this one? |
|-----------|-------------|---------------|
| **FastAPI** | HTTP API framework | Async-native, fast, automatic OpenAPI docs |
| **ARQ** | Background job queue | Pure asyncio — no thread pool hacks needed |
| **LangGraph** | Pipeline graph orchestration | Checkpoint/resume built-in; clear node boundaries |
| **pypdfium2** | PDF text extraction | Apache 2.0 (commercial-safe) — PyMuPDF is AGPL-3.0 (banned) |
| **pdftext** | Font metadata extraction | Reads font size/bold per span — needed for heading detection |
| **pdfplumber** | Table detection | Lightweight; only used to trigger the docling path |
| **docling** | Table-aware PDF → markdown | Preserves table structure that pypdfium2 flattens |
| **pytesseract** | OCR for scanned PDFs | Tesseract (Google) wrapped in Python; 300 DPI render = ~95% accuracy |
| **tiktoken** | Token counting | Must match the embedding model's tokenizer (cl100k_base) |
| **OpenAI text-embedding-3-small** | Generate vectors | $0.00002/1K tokens; 1536 dims; right balance of cost and quality |
| **Supabase pgvector** | Store and search vectors | No separate vector DB needed; RLS applies to vector searches too |
| **Redis** | Job queue + pub/sub | ARQ uses Redis; also pub/sub channel for lesson_ready events |
| **PyJWT** | JWT verification | Local verify in microseconds — no remote auth call per request |

---

## 📁 What to Read Next

Each story has its own detailed document:

- `01-api-and-queue.md` — Story 1.1: The HTTP endpoint and ARQ job queue
- `02-pdf-extraction.md` — Story 1.2: PDF parsing, licensing, subprocess isolation
- `03-structure-and-chunking.md` — Stories 1.3 + 1.4: Heading detection and chunking
- `04-embeddings-and-providers.md` — Story 1.5: Vectors, pgvector, provider pattern
- `05-key-decisions-why.md` — All the "why not X?" answers interviewers love
- `06-interview-cheatsheet.md` — Quick-reference card for the day before an interview
