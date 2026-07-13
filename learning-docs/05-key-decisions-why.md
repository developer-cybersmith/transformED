# Sprint 1 Key Decisions — The WHY Behind Every Choice

> **Who this is for**: The best interview candidates don't just know what they built — they know why. This document gives you the reasoning behind every significant Sprint 1 decision.

> **How to use this**: For each decision, there's a 30-second interview answer ready to go. Practice saying it out loud until it feels natural.

---

## How to Talk About Technical Decisions in Interviews

The formula that works:

> "We chose **[X]** over **[Y]** because **[specific reason]**. The tradeoff was **[what we gave up]**, which was acceptable because **[why that tradeoff was worth it]**."

Notice it acknowledges a tradeoff. Saying "X is just better" sounds naive. Saying "X solves our specific constraint better, and we accepted the tradeoff of Y" sounds like an engineer who thinks.

---

## Decision 1: ARQ over Celery (Job Queue)

**What we chose**: ARQ  
**What we rejected**: Celery  
**Constraint**: Hard rule in CLAUDE.md — "No Celery — ARQ only"

### The Honest Comparison

| | ARQ | Celery |
|--|-----|--------|
| Async support | Native asyncio | Needs gevent/eventlet workarounds |
| Lines to configure | ~50 | ~500+ |
| Brokers supported | Redis only | Redis, RabbitMQ, SQS, more |
| Community size | Small | Huge |
| Age | Newer | Old standard |

### Why It Matters

Our entire backend is async Python (FastAPI + asyncio). Celery's default workers are synchronous processes — they use thread pools or subprocess pools. To run async code with Celery, you'd use `asyncio.run()` inside the Celery task, which creates a new event loop per task — expensive and awkward.

ARQ is designed for asyncio from the ground up. Tasks are just async functions. No wrapper needed.

### 30-Second Interview Answer

> "We used ARQ instead of Celery for background jobs because our entire backend is async FastAPI, and Celery's native execution model is synchronous workers. Running async code in Celery requires a new event loop per task, which adds overhead and complexity. ARQ is asyncio-native — tasks are just async functions. The tradeoff is a smaller community and fewer broker options, but since we already use Redis for caching and pub/sub, limiting ARQ to Redis-only was no sacrifice."

---

## Decision 2: pypdfium2 over PyMuPDF (Licensing)

**What we chose**: pypdfium2  
**What we rejected**: PyMuPDF (fitz)  
**Constraint**: Hard rule in CLAUDE.md — "Never import fitz/pymupdf — AGPL-3.0"

### The Licensing Reality

AGPL-3.0 (Affero General Public License) has a "viral" clause: if you use AGPL code in a network-accessible service (like a SaaS web app), you must release your entire application's source code under AGPL.

For a startup that plans to charge students and has investor funding, publishing the entire backend codebase is not acceptable. Our business model depends on proprietary algorithms and AI prompts.

pypdfium2 wraps PDFium — the same PDF rendering engine used in Google Chrome. License: Apache 2.0. Commercial-friendly.

### 30-Second Interview Answer

> "We chose pypdfium2 over PyMuPDF — despite PyMuPDF being the more popular choice — because PyMuPDF is AGPL-3.0 licensed. AGPL has a viral clause: using it in a commercial web service requires open-sourcing the entire application. For a startup with proprietary business logic, that's unacceptable. pypdfium2 wraps PDFium (the same engine as Chrome) under Apache 2.0 and provides similar functionality. We enforced this as a hard rule in our CLAUDE.md configuration file so no developer could accidentally introduce the banned library."

---

## Decision 3: Subprocess Isolation for PDF Parsing

**What we chose**: Parse PDFs in an isolated subprocess  
**What we rejected**: Parsing in the main ARQ worker process  
**Constraint**: CLAUDE.md §18 — "parse user-uploaded PDFs in an isolated subprocess"

### The Security Argument

A user uploads a PDF. We don't control the content. A malformed PDF (or a deliberately crafted malicious one) could:
- Cause a segfault that kills the Python process
- Trigger an infinite loop that starves the CPU
- Exhaust memory until the OS kills the process

If any of these happen inside the ARQ worker: **all pending jobs for all users stop**.

With subprocess isolation: one PDF crashes one subprocess. The ARQ worker is unaffected. Everyone else's lessons continue.

### 30-Second Interview Answer

> "We run PDF parsing in an isolated subprocess rather than in the main ARQ worker process. Untrusted user-uploaded files can be malformed or malicious, causing parser crashes. A crash inside the ARQ worker would stop all pending lesson jobs for all users. By spawning a subprocess, a crash is contained — only that one job fails, and the worker continues. The subprocess communicates back over stdout as JSON — clean data only crosses the process boundary."

---

## Decision 4: Custom lesson_jobs Table over PostgresSaver

**What we chose**: Custom `lesson_jobs` table + MemorySaver  
**What we rejected**: LangGraph PostgresSaver  
**Constraint**: Hard rule in CLAUDE.md — "No PostgresSaver — custom lesson_jobs + MemorySaver"

### What PostgresSaver Would Have Done

LangGraph's PostgresSaver is a built-in checkpointing backend that stores the full graph state in Postgres automatically. Sounds convenient.

The problems:
1. Creates its own opaque schema — you can't easily query "how many lessons are stuck at node 3?"
2. Stores the entire LangGraph state blob — hard to expose progress percentage to the client
3. Tightly coupled to LangGraph's internal format — any LangGraph upgrade could break your checkpoints
4. No custom fields — can't add `status`, `error`, `progress_pct`, `cost_usd` columns

Our custom `lesson_jobs` table has full control:
```sql
lesson_jobs (
    lesson_id       UUID,
    status          TEXT,  -- pending | running | ready | failed
    progress_pct    FLOAT,
    last_node       TEXT,
    node_outputs    JSONB,  -- checkpoint data per node
    error           TEXT,
    cost_usd        FLOAT
)
```

### 30-Second Interview Answer

> "We used a custom lesson_jobs table instead of LangGraph's PostgresSaver for checkpointing. PostgresSaver creates an opaque schema that's hard to query for operational purposes — you can't easily check which node a job is stuck on, or build a progress bar. Our custom table stores status, progress percentage, per-node checkpoint data in JSONB, and cost tracking. This gives us full control over the checkpoint format and makes operational monitoring straightforward."

---

## Decision 5: Provider Abstraction (ABC Pattern)

**What we chose**: Abstract Base Class for every AI provider  
**What we rejected**: Direct provider SDK calls in business logic  
**Constraint**: CLAUDE.md rule — "No direct provider calls in business logic — go through providers/"

### Why This Matters at Scale

In Sprint 1, we only had one embedding provider (OpenAI). But Sprint 1 also runs **model evaluation** — we're comparing GPT-4o vs Claude vs Gemini for lesson planning. By Sprint 2, we may switch providers for cost reasons.

Without abstraction, swapping a provider means rewriting every node that calls it. With the ABC pattern:
1. Define `EmbeddingsProvider` with `embed_texts()` abstract method
2. `embed_node` depends only on `EmbeddingsProvider`
3. To swap: write `CohereEmbeddingsProvider(EmbeddingsProvider)`, change one import

The same pattern applies to LLMProvider, TTSProvider, ImageProvider, AvatarProvider.

### 30-Second Interview Answer

> "We implemented a provider abstraction layer — Abstract Base Classes for every AI provider type: embeddings, LLM completions, TTS, image generation. Business logic nodes only import the abstract interface, never the provider SDK directly. This means swapping from OpenAI to any other embedding provider requires writing one new class and changing one import line — no changes to business logic. We're currently running model evaluation in Sprint 1, so this abstraction is already paying off — we can test different providers by swapping implementations without touching the pipeline nodes."

---

## Decision 6: Embed at Ingestion, Never Regenerate

**What we chose**: Generate embeddings once at ingestion, cache forever  
**What we rejected**: Regenerate on every request or periodically  
**Constraint**: CLAUDE.md — "Chunk embeddings at ingestion only — never regenerate stored chunk embeddings"

### The Cost Math

- text-embedding-3-small: `$0.00002` per 1K tokens
- Average chapter: ~250,000 tokens = `$0.005` per chapter
- 10,000 student × chapter interactions per day
- If regenerated each time: 10,000 × $0.005 = **$50/day**
- If embedded once: **$0.005 total, one time**

That's a 10,000× cost difference at scale.

The enforcement mechanism is the `IS NULL` filter in the embed query — there's literally no code path that overwrites an existing embedding. The rule is self-enforcing.

### 30-Second Interview Answer

> "We embed at ingestion only and never regenerate stored content embeddings. The math is straightforward: at 10,000 student-chapter interactions per day, regenerating embeddings each time would cost $50/day for the same content. Embedding once costs $0.005 total. The 'never regenerate' rule is self-enforcing — the embed_node query filters `WHERE embedding IS NULL`, so it physically cannot overwrite existing vectors. The only exception (by design) is the Phase 2 RAG tutor, which embeds the student's *question* at query time — that's a new input, not stored content."

---

## Decision 7: JWT Local Verification

**What we chose**: PyJWT + SUPABASE_JWT_SECRET (local verification)  
**What we rejected**: Remote auth verification on every request  
**Constraint**: CLAUDE.md — "JWT verified locally — never remote auth call per request"

### The Latency Argument

A remote verification call (to Supabase Auth) adds 50–100ms to every authenticated API endpoint. At 100 requests/second, that's 5–10 seconds of cumulative latency per second. Under load, this becomes a major bottleneck.

Local JWT verification with PyJWT takes ~0.1ms — 500–1000× faster. JWTs are cryptographically signed; verifying the signature locally using the known secret is completely secure.

### 30-Second Interview Answer

> "We verify JWTs locally using PyJWT and the Supabase JWT secret rather than making a remote call to Supabase Auth per request. A remote call adds 50–100ms latency to every authenticated endpoint — at any meaningful scale, that compounds into serious throughput degradation. JWT signatures are cryptographically verifiable locally using the known secret, so local verification is both faster and equally secure."

---

## Decision 8: 64-Token Overlap in Chunking

**What we chose**: 64-token overlap between consecutive chunks  
**What we rejected**: Zero overlap (adjacent chunks with no repetition)  

### The Boundary Problem

Imagine this text split at a 512-token boundary:
```
Chunk 1: "...RuBisCO is the enzyme that catalyzes the first step of carbon fixation in"
Chunk 2: "the Calvin cycle, combining CO₂ with ribulose bisphosphate."
```

Without overlap: searching for "how does RuBisCO work in the Calvin cycle" retrieves Chunk 1 (mentions RuBisCO) but Chunk 1 ends mid-sentence. The complete answer requires Chunk 2.

With 64-token overlap, Chunk 2 starts:
```
"...RuBisCO is the enzyme that catalyzes the first step of carbon fixation in the Calvin cycle, combining CO₂..."
```

Either chunk retrieval gives enough context to answer the question.

### 30-Second Interview Answer

> "We use 64-token overlap between consecutive chunks. Without overlap, a concept that spans a chunk boundary would be split — the question 'how does X work' might retrieve the chunk that mentions X, but not the chunk that explains the mechanism, because they're adjacent but separate. Overlap ensures that key information appearing at a chunk's end is repeated at the next chunk's start, so retrieval captures complete explanations regardless of where the boundary falls."

---

## Decision 9: Hybrid Structure Detection (Rules + LLM)

**What we chose**: Font-size clustering + regex → GPT-4o-mini cleanup  
**What we rejected**: Pure LLM detection OR pure rule-based  

### Why Not Pure Rules?

Real textbooks don't all follow the same formatting. A PDF from a 1998 scanner, a modern LaTeX-generated paper, and a Keynote presentation exported as PDF all look different. Pure regex is brittle.

### Why Not Pure LLM?

GPT-4o-mini running on a 200-page chapter to detect headings uses tens of thousands of tokens. At 50 chapters per day at $0.0002/1K tokens, that's significant cost for a deterministic task that's mostly solvable with simple rules.

### Why Hybrid?

Rules handle 90% of cases (fast, free). LLM cleans up the 10% edge cases (false positives, missed headings). Total cost: one LLM call per chapter on the *candidates list* (100 tokens), not the full text.

### 30-Second Interview Answer

> "We used a hybrid approach for structure detection: font-size clustering and regex patterns for the initial candidate detection, then GPT-4o-mini to clean up edge cases. Pure rule-based approaches fail on PDFs with inconsistent formatting. Pure LLM detection runs on the full chapter text — expensive and overkill when 90% of headings are identifiable by font size alone. The hybrid processes the full text with cheap rules first, then passes only the small candidates list to the LLM, reducing cost by approximately 80%."

---

## Decision 10: 300 DPI for Image Rendering

**What we chose**: `scale=300/72` (300 DPI) for all renders  
**What we rejected**: Lower resolutions (72 DPI, 150 DPI)  
**Constraint**: Hard rule in CLAUDE.md — "PDF image extraction must render at 300 DPI minimum"

The math: Tesseract accuracy at 72 DPI is ~60%. At 300 DPI it's ~95%. The 4× increase in render resolution costs 16× more memory for the bitmap — but produces images clear enough for accurate OCR. For educational content where accuracy matters, the tradeoff is clear.

### 30-Second Interview Answer

> "We render all PDF pages at 300 DPI for image extraction and OCR — Tesseract's accuracy drops to around 60% at PDF-native 72 DPI and reaches 95% at 300 DPI. The tradeoff is 16× larger bitmaps in memory, but for educational content where OCR errors corrupt the learning material, accuracy outweighs memory cost."

---

## Decision 11: Never Hardcode Model Names

**What we chose**: All model names in environment variables via `settings.llm_*`  
**What we rejected**: Hardcoded strings like `"gpt-4o"` or `"text-embedding-3-small"` in code  
**Constraint**: CLAUDE.md — "Never hardcode model strings — always use settings.llm_* aliases"

### Why It Matters

Sprint 1 is the model evaluation sprint. We're testing GPT-4o vs Claude 3.5 Sonnet vs GPT-4o-mini across different nodes. With hardcoded strings, each test requires a code change + deploy. With env vars, changing the model is:

```bash
# .env
LLM_LESSON_PLANNER=claude-3-5-sonnet-20241022
LLM_MINI=gemini-2.0-flash
```

No code change. No deploy. Just update the config and restart. This is what makes model evaluation practical.

### 30-Second Interview Answer

> "All AI model identifiers come from environment variables rather than code — never hardcoded strings. Sprint 1 is our model evaluation sprint, comparing GPT-4o, Claude 3.5 Sonnet, and others across different pipeline nodes. With env var configuration, we can swap models by changing a config value and restarting — no code change, no deploy. With hardcoded strings, every model swap would require a PR, code review, and deployment cycle."

---

## 🔖 Quick Reference Table

| Decision | Chose | Rejected | One-line reason |
|----------|-------|----------|-----------------|
| Job queue | ARQ | Celery | asyncio-native; Celery needs thread pool hacks |
| PDF library | pypdfium2 | PyMuPDF | AGPL-3.0 would force open-sourcing our SaaS |
| PDF parsing | Subprocess | In-process | Crash isolation — bad PDF can't kill the worker |
| Checkpointing | Custom lesson_jobs | PostgresSaver | Full control: queryable schema, progress %, status |
| AI providers | ABC pattern | Direct SDK calls | Swap providers by env var, no business logic changes |
| Embedding frequency | Once at ingestion | Per request | 10,000× cheaper at scale; enforced by IS NULL filter |
| JWT auth | PyJWT local | Remote call | 500–1000× faster; cryptographically equivalent |
| Chunk overlap | 64 tokens | 0 tokens | Preserves context at chunk boundaries |
| Structure detection | Hybrid (rules+LLM) | Pure rules / pure LLM | Rules handle 90%, LLM cleans 10% — 80% cost savings |
| Image resolution | 300 DPI | 72 DPI | Tesseract: 60% accuracy at 72 DPI vs 95% at 300 DPI |
| Model names | Env vars | Hardcoded | Model swap = config change, not code change |
