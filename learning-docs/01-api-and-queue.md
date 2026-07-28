# Story 1.1 — "The Front Door"
## POST /lessons Endpoint + ARQ Job Queue

> **Interview value**: This story covers async API design, file validation, queue-based background processing, and database transaction ordering. These patterns come up constantly.

---

## 🧩 What Problem Does This Solve?

Generating a lesson takes **5–15 minutes**. HTTP connections time out after 30 seconds. If we processed the PDF synchronously (inline in the HTTP request), every upload would fail before the lesson was done.

**The solution**: Accept the request instantly, process it in the background.

This is called the **queue-based async pattern** — one of the most important backend engineering patterns you'll use throughout your career.

> **Analogy**: Think of a fast food restaurant. You walk up, order a burger, they hand you a receipt with a number and say "we'll call you when it's ready." You sit down. The kitchen processes your order in the background. You don't stand at the counter for 10 minutes blocking everyone else.

The POST /lessons endpoint is the cashier. ARQ is the kitchen. The `lesson_id` is your receipt number.

---

## 📋 The POST /lessons Endpoint (Step by Step)

The client sends a `multipart/form-data` request with the PDF file. Here's what happens inside, step by step:

### Step 1: Authentication — "Who are you?"
```python
async def upload_lesson(
    current_user: CurrentUser,  # FastAPI dependency injection
    ...
):
    user_id: str = current_user["sub"]
```

The JWT (JSON Web Token) is verified **locally** using PyJWT and the `SUPABASE_JWT_SECRET`. No remote call. This is fast (microseconds) and means we can handle thousands of authenticated requests per second.

> **Interview tip**: "We verify JWTs locally with PyJWT rather than making a remote auth call per request — that would add 50–100ms latency to every API endpoint."

### Step 2: File Validation (Three Layers)
```python
# Layer 1: Size check (fast — before reading the body)
if file.size and file.size > 50_MB:
    raise HTTPException(413, "File exceeds 50 MB limit")

# Layer 2: Magic bytes — first 4 bytes must be %PDF
first_bytes = await file.read(4)
await file.seek(0)
if first_bytes != b"%PDF":
    raise HTTPException(422, "File is not a valid PDF")

# Layer 3: MIME type
if file.content_type not in ("application/pdf", "application/octet-stream"):
    raise HTTPException(422, "Invalid content type")
```

Why three layers?

- **Size check first**: If someone sends a 5 GB file, we reject it before reading the body. Cheaper.
- **Magic bytes**: A user could rename `virus.exe` to `mybook.pdf`. The MIME type check is easy to fake. The first 4 bytes of a real PDF are always `%PDF`. An EXE starts with `MZ`. This catches renamed files.
- **MIME type**: A basic check — easy to fake but filters out obvious mistakes.

### Step 3: Streaming Read with Rolling Size Guard
```python
# Stream the body 1 MB at a time, enforce limit even without Content-Length
chunks: list[bytes] = []
total_bytes = 0
while True:
    chunk = await file.read(1024 * 1024)  # 1 MB at a time
    if not chunk:
        break
    total_bytes += len(chunk)
    if total_bytes > MAX_PDF_SIZE_BYTES:
        raise HTTPException(413, "File exceeds 50 MB limit")
    chunks.append(chunk)
pdf_bytes = b"".join(chunks)
```

Why stream instead of reading all at once? HTTP clients can lie about `Content-Length`. A client could send a 500 MB body but claim it's 5 MB. Streaming lets us enforce the limit in real time, aborting early instead of loading the whole file into memory first.

### Step 4: Database Inserts in the Right Order
```python
# 1. books row (FK parent)
books_resp = supabase.table("books").insert({...}).execute()
book_id = books_resp.data[0]["book_id"]

# 2. lessons row (FK: lessons.book_id → books.book_id)
lessons_resp = supabase.table("lessons").insert({...}).execute()
lesson_id = lessons_resp.data[0]["lesson_id"]

# 3. Supabase Storage upload
supabase.storage.from_("source-pdfs").upload(path=storage_path, file=pdf_bytes)

# 4. Update lessons.source_file_path
supabase.table("lessons").update({"source_file_path": storage_path}).eq(...)

# 5. lesson_jobs row (FK: lesson_jobs.lesson_id → lessons.lesson_id)
supabase.table("lesson_jobs").insert({"lesson_id": lesson_id, "status": "pending"})
```

The order matters because of **Foreign Key constraints**. `lessons.book_id` points to `books.book_id` — so books must exist before lessons can reference it. Similarly, `lesson_jobs.lesson_id` points to `lessons.lesson_id` — so lessons must exist first.

If you insert in the wrong order, the database will reject the insert with a foreign key violation error.

### Step 5: Enqueue the ARQ Job (with Deduplication)
```python
job = await arq_redis.enqueue_job(
    "content_pipeline_job",    # function name to call
    lesson_id,                 # argument
    _job_id=f"pipeline:{lesson_id}"  # deduplication key
)
if job is None:
    # ARQ already has a job with this key — return 409 Conflict
    raise HTTPException(409, "A pipeline job is already queued for this ID")
```

The `_job_id` parameter is the deduplication key. If the user accidentally submits the same PDF twice (double-click on submit), ARQ will deduplicate: the second `enqueue_job` call returns `None` instead of creating a duplicate job. We detect this and return `409 Conflict`.

### Step 6: Return Immediately
```python
return LessonUploadResponse(
    lesson_id=lesson_id,
    job_id=job_id,
    status="queued"
)
# HTTP 202 Accepted — "I got it, I'm working on it"
```

The endpoint returns in **~200ms** regardless of PDF size. The client then polls `GET /lessons/{lesson_id}` every few seconds until status becomes `"ready"`.

---

## ⚙️ The ARQ Worker (What Happens in the Background)

After the endpoint returns, ARQ picks up the job and calls `content_pipeline_job`:

```
lesson_jobs.status: "pending"
         │
         ▼ (ARQ picks up the job)
lesson_jobs.status: "running"
         │
         ▼ (run_pipeline() executes all 15 nodes)
         │
    ┌────┴─────────────────────────────────┐
    │  On success:                          │
    │  lesson_jobs.status → "ready"         │
    │  lesson_jobs.lesson_package → {...}   │
    │  Redis pub/sub → "lesson_ready" event │
    └───────────────────────────────────────┘
         │
    ┌────┴─────────────────────────────────┐
    │  On failure:                          │
    │  lesson_jobs.status → "failed"        │
    │  re-raise exception → ARQ retries     │
    └───────────────────────────────────────┘
```

Key design decision: when the pipeline fails, we **re-raise the exception**. This tells ARQ that the job failed and it should be retried. Because all 15 pipeline nodes write checkpoints to `lesson_jobs.node_outputs`, the retry picks up from the last completed node — it doesn't re-run everything from scratch.

---

## 🔄 The Rollback Story

What if something fails partway through the endpoint (e.g., Supabase Storage upload fails)?

The endpoint does a **hard-delete rollback** in FK-reverse order:
```
1. Delete lesson_jobs (FK child — must go first)
2. Delete lessons
3. Delete from Supabase Storage
4. Delete books (FK parent — must go last)
```

This gives the user a clean slate. They can retry without getting "lesson already exists" errors. We chose hard-delete over soft-marking-as-failed because marking as failed would leave orphaned `books` rows that pile up on subsequent retries.

---

## 💡 Why ARQ Instead of Celery?

This comes up in interviews. Here's the honest answer:

| | ARQ | Celery |
|--|-----|--------|
| **Async support** | Native asyncio | Needs workarounds (gevent, eventlet) |
| **Configuration** | ~50 lines | ~500 lines |
| **Backend** | Redis only | Redis, RabbitMQ, Amazon SQS, more |
| **Maturity** | Newer, smaller community | Old, huge community |
| **Why we chose it** | Our whole stack is async FastAPI — ARQ fits naturally | Forced thread pool = overhead |

The constraint from CLAUDE.md: **"No Celery — ARQ only"**. This is a hard constraint, not a judgment call. The reason: the entire backend is async Python (FastAPI + asyncio), and Celery's native mode is synchronous workers. Using Celery would require either thread pool hacks or complex workarounds to play nicely with async code.

---

## ⭐ STAR Interview Answer

**Situation**

We needed to accept PDF uploads from students and trigger a 5–15 minute AI generation pipeline. Holding an HTTP connection open for 15 minutes is impossible: browsers time out, networks drop, and servers would be stuck waiting with thousands of idle connections.

**Task**

Build an async REST endpoint that accepts a PDF, validates it thoroughly, stores it safely, and hands off to a background job queue — all within a single HTTP round trip of ~200ms.

**Action**

- Implemented POST /lessons with 3-layer file validation: header-based size check, magic bytes (`%PDF`), MIME type — in that order, cheapest check first
- Used streaming reads (1 MB at a time) to enforce the 50 MB limit even on clients that omit `Content-Length`
- Followed strict FK-ordered DB inserts: books → lessons → storage → lesson_jobs
- Used ARQ (not Celery) — pure asyncio, zero thread pool overhead, integrates naturally with our async FastAPI stack
- Added ARQ deduplication key (`pipeline:{lesson_id}`) so double-submitting returns 409 instead of processing the PDF twice
- Implemented FK-reverse hard-delete rollback on failure so users get a clean retry

**Result**

The endpoint returns 202 Accepted in ~200ms regardless of PDF size. The ARQ deduplication key prevents double-processing. Full rollback on failure means users never see orphaned data. The pipeline retries from the last checkpoint on failure, not from scratch.

---

## 📖 Key Terms Glossary

| Term | Plain English |
|------|--------------|
| **202 Accepted** | HTTP status meaning "I received it, working on it, not done yet" |
| **ARQ** | Async Redis Queue — a Python background job library |
| **JWT** | JSON Web Token — a cryptographically signed token proving who you are |
| **Idempotent** | Running the operation twice has the same effect as running it once |
| **Magic bytes** | First bytes of a file that identify its format (`%PDF` = real PDF) |
| **Foreign key** | A DB column that points to a row in another table — must exist before you can reference it |
| **Deduplication key** | A unique ID that prevents the same job from being queued twice |
| **pub/sub** | Publish-subscribe — one publisher sends a message; many subscribers can receive it |
