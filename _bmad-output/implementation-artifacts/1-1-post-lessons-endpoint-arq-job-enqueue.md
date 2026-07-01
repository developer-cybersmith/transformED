---
baseline_commit: ea5f9380923d21ad153ad26c5c8f5b94009a0f76
---

# Story 1.1: POST /lessons Endpoint + ARQ Job Enqueue

Status: done

## Story

As a student uploading a chapter PDF,
I want the upload to return immediately with a `lesson_id` and `job_id`,
so that I don't wait for the full pipeline before I can poll for status.

## Acceptance Criteria

1. `POST /api/content/lessons` accepts a multipart PDF; rejects non-PDFs (MIME type check + magic bytes `%PDF`)
2. Rejects files over 50 MB before reading the full body
3. Creates rows in order: `books` → `lessons` (`status='generating'`) → `lesson_jobs` (`status='pending'`)
4. Stores PDF bytes to Supabase Storage bucket `source-pdfs`; writes signed storage path to `lessons.source_file_path`
5. Enqueues ARQ job `content_pipeline_job(lesson_id)` via `app.state.arq_redis` (ArqRedis pool, not the app's redis-py pool)
6. Returns `202 {"lesson_id": "...", "job_id": "..."}` immediately
7. Rate limit: **"5/minute" per JWT sub** (not per IP) — returns 429 with `Retry-After` header on breach
8. `GET /api/content/lessons/{lesson_id}` returns current status + error from `lessons` + `lesson_jobs` tables
9. `GET /api/content/lessons` returns paginated list of lessons for the current user

## Tasks / Subtasks

- [x] **Task 1: Wire ARQ pool into FastAPI lifespan** (AC: 5) — ✓ 2026-06-28
  - [x] In `apps/api/app/main.py` lifespan startup: `app.state.arq_redis = await create_pool(RedisSettings.from_url(settings.redis_url))`
  - [x] In lifespan shutdown: `await app.state.arq_redis.close()` (before `close_redis()`)
  - [x] Import `from arq import create_pool` and `from arq.connections import RedisSettings`

- [x] **Task 2: Add ARQ dependency** (AC: 5) — ✓ 2026-06-28
  - [x] In `apps/api/app/dependencies.py`: add `get_arq_redis(request: Request) -> ArqRedis` that returns `request.app.state.arq_redis`
  - [x] Add `ArqRedis = Annotated[ArqRedisType, Depends(get_arq_redis)]` alias
  - [x] Export from `__all__`

- [x] **Task 3: Add per-user rate limiter** (AC: 7) — ✓ 2026-06-28
  - [x] Created `apps/api/app/core/rate_limit.py` with `_get_user_key` (JWT sub → IP fallback) and `limiter`
  - [x] `main.py` imports `limiter` from `core/rate_limit` (avoids circular import)
  - [x] Applied `@limiter.limit("5/minute", key_func=_get_user_key)` to `upload_lesson`

- [x] **Task 4: Fix response models** (AC: 6, 8) — ✓ 2026-06-28
  - [x] `LessonUploadResponse`: added `job_id: str`; status default is `"queued"`
  - [x] `LessonStatusResponse`: removed `progress_pct` field; status values documented

- [x] **Task 5: Implement `upload_lesson`** (AC: 1–6) — ✓ 2026-06-28
  - [x] Size check (file.size fast path + post-read enforcement)
  - [x] Magic bytes check (`!= b"%PDF"` → 422)
  - [x] MIME type check
  - [x] DB insert order: books → lessons → storage → source_file_path update → lesson_jobs
  - [x] ARQ enqueue via `arq_redis.enqueue_job("content_pipeline_job", lesson_id)`
  - [x] Returns 202 with lesson_id + job_id

- [x] **Task 6: Implement `get_lesson`** (AC: 8) — ✓ 2026-06-28
  - [x] 404 on missing or wrong-user lesson
  - [x] Status mapping: generating→running, ready→ready, failed→failed
  - [x] Error fetched from lesson_jobs on failed status

- [x] **Task 7: Implement `list_lessons`** (AC: 9) — ✓ 2026-06-28
  - [x] Paginated by limit + offset, newest first

- [x] **Task 8: Tests** — ✓ 2026-06-28
  - [x] `apps/api/tests/unit/test_content_router.py` — 13 tests: 202 shape, DB insert order, 413, 422 magic bytes, 422 content-type, GET 200/404 wrong user/404 not found, LIST 200, status map, key func IP fallback, key func JWT sub
  - [x] `tests/conftest.py` — session-scoped env stubs for all required Settings fields

### Review Findings

**Decision-needed (resolve before patching):**

- [x] [Review][Decision] Status gap: upload response returns `"queued"` but DB `lessons.status` is immediately set to `"generating"` — **resolved: intentional design.** `"queued"` in upload response is the immediate acknowledgment; by the time the DB row exists the job is already dispatched. No change needed.
- [x] [Review][Decision] ARQ `job is None` handling — **resolved: return 409 Conflict.** `job is None` means ARQ deduplicated the key (not a failure). Moved to patch: `raise HTTPException(status_code=409)` instead of `RuntimeError`.

**Patch items:**

- [x] [Review][Patch] `_build_arq_redis_settings` ignores `rediss://` TLS scheme — Railway Redis uses TLS, this connects plaintext or fails [main.py:36-47]
- [x] [Review][Patch] Unsanitized filename in storage path — `../` or URL-special chars in filename create path traversal risk [router.py:140]
- [x] [Review][Patch] Rate limiter uses in-memory backend — `Limiter(key_func=...)` with no `storage_uri` means 5/min limit is per-process, not enforced globally across workers [core/rate_limit.py:44]
- [x] [Review][Patch] ARQ `job is None` → raise 409 Conflict instead of RuntimeError (duplicate job key is not a failure) [router.py:160-161]
- [x] [Review][Patch] Orphaned `books` row on failure — error cleanup updates `lesson_jobs`/`lessons` but never deletes the `books` row inserted at step 1 [router.py:164-177]
- [x] [Review][Patch] Orphaned PDF in storage on failure after step 3 — no `storage.remove()` call in cleanup path [router.py:164-177]
- [x] [Review][Patch] books/lessons insert returns empty data → uncaught `IndexError` — no guard on `resp.data[0]` [router.py:129, router.py:137]
- [x] [Review][Patch] `completed_at` hardcoded as `None` in `_row_to_status_response` — `lessons.completed_at` column is fetched with `select("*")` but never mapped [router.py:68]
- [x] [Review][Patch] `get_arq_redis` no guard — bare `AttributeError` if ARQ pool not in `app.state` (startup failure) [dependencies.py:85-91]
- [x] [Review][Patch] `list_lessons` unbounded `limit`/`offset` — no upper bound; `limit=1000000` triggers full table scan [router.py:220-221]
- [x] [Review][Patch] `file.size` fast-path skipped when client omits Content-Length — full 50 MB body read before size check triggers [router.py:100]
- [x] [Review][Patch] conftest missing `REDIS_URL` stub — Settings validation fails at collection time if `redis_url` is required [tests/conftest.py]
- [x] [Review][Patch] `lesson_id` path param not UUID-validated — non-UUID strings cause Postgres syntax error → 500 [router.py:187]
- [x] [Review][Patch] No test for rate-limit 429 + `Retry-After` header (AC 7 untested) [tests/unit/test_content_router.py]
- [x] [Review][Patch] `RateLimitExceeded` imported in router.py but never referenced there — unused import [router.py:14]

**Deferred (pre-existing / future sprint):**

- [x] [Review][Defer] Synchronous Supabase `.execute()` calls in async handlers block event loop [router.py everywhere] — deferred, pre-existing architecture (whole codebase); revisit in Sprint 4 load test per dev notes
- [x] [Review][Defer] `cost_limit_exceeded` DB status not in `_STATUS_MAP` — maps to `"queued"` as fallback [router.py:47-51] — deferred, Sprint 2 cost-ceiling node concern; `cost_limit_exceeded` not a `lessons.status` CHECK value yet

## Dev Notes

### Files to Modify (UPDATE — read before touching)

| File | Current State | This Story Changes |
|------|-------------|-------------------|
| `apps/api/app/main.py` | Has `lifespan` with Redis + Langfuse init | Add ARQ pool `create_pool()` in startup; `arq_redis.close()` in shutdown |
| `apps/api/app/dependencies.py` | Has `get_current_user`, `CurrentUser` | Add `get_arq_redis()` dep, `ArqRedis` alias |
| `apps/api/app/modules/content/router.py` | All 3 endpoints raise `HTTP_501_NOT_IMPLEMENTED` | Implement all 3; fix response models; add rate limiter |

### File to Create (NEW)

| File | Purpose |
|------|---------|
| `apps/api/tests/unit/test_content_router.py` | Unit tests for the 3 content endpoints |

### Critical: Two Redis Pools Co-Exist

The app uses **two separate Redis clients** — they must NOT be merged:

| Client | Module | Type | Purpose |
|--------|--------|------|---------|
| `get_redis()` | `core/redis.py` | `redis.asyncio.Redis` | App-level pub/sub, circuit breaker, cost tracker |
| `app.state.arq_redis` | `main.py` lifespan | `arq.connections.ArqRedis` | ARQ job enqueue only |

`get_redis()` returns `redis.asyncio.Redis` which has **no `enqueue_job()` method**. Calling `enqueue_job()` on it will raise `AttributeError`. Always use `app.state.arq_redis` for job enqueueing.

ARQ pool creation:
```python
from arq import create_pool
from arq.connections import RedisSettings

# In lifespan startup:
app.state.arq_redis = await create_pool(
    RedisSettings.from_url(settings.redis_url)
)

# In lifespan shutdown (before close_redis()):
await app.state.arq_redis.close()
```

### Critical: PDF Security — Magic Bytes + MIME

```python
# DO NOT pass pdf_bytes to fitz/PyMuPDF in the main process — security risk
# Storage upload is fine; extraction happens in isolated subprocess in extract_node

# Validation pattern:
MAX_PDF_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB

if file.size and file.size > MAX_PDF_SIZE_BYTES:
    raise HTTPException(status_code=413, detail="File exceeds 50 MB limit")

first_bytes = await file.read(4)
await file.seek(0)
if first_bytes != b"%PDF":
    raise HTTPException(status_code=422, detail="File is not a valid PDF")

if file.content_type not in ("application/pdf", "application/octet-stream"):
    raise HTTPException(status_code=422, detail="Invalid content type")
```

### Critical: DB Row Creation Order

`lesson_jobs.lesson_id` FK → `lessons.lesson_id`. `lessons.book_id` FK → `books.book_id`.
**Must insert in order: `books` → `lessons` → `lesson_jobs`**. Violations cause FK constraint errors.

```python
# 1. books
books_resp = supabase.table("books").insert({
    "user_id": user_id,
    "filename": file.filename or "upload.pdf",
}).execute()
book_id = books_resp.data[0]["book_id"]

# 2. lessons
lessons_resp = supabase.table("lessons").insert({
    "user_id": user_id,
    "book_id": book_id,
    "status": "generating",
}).execute()
lesson_id = lessons_resp.data[0]["lesson_id"]

# 3. Storage upload
storage_path = f"{user_id}/{book_id}/{file.filename or 'upload.pdf'}"
supabase.storage.from_("source-pdfs").upload(
    path=storage_path,
    file=pdf_bytes,
    file_options={"content-type": "application/pdf"},
)

# 4. Update source_file_path on lessons
supabase.table("lessons").update(
    {"source_file_path": storage_path}
).eq("lesson_id", lesson_id).execute()

# 5. lesson_jobs
jobs_resp = supabase.table("lesson_jobs").insert({
    "lesson_id": lesson_id,
    "status": "pending",
}).execute()

# 6. Enqueue ARQ job
job = await arq_redis.enqueue_job("content_pipeline_job", lesson_id)
```

### Critical: Per-User Rate Limiting (NOT per-IP)

The existing `limiter` in `main.py` uses `get_remote_address` (IP). The `/lessons` upload must be per-user (JWT sub). slowapi supports per-route key_func override:

```python
# In router.py — import the app-level limiter instance
from app.main import limiter  # circular import risk — see pattern below

# BETTER: define key func here, use it in decorator
from slowapi.util import get_remote_address

def _get_user_key(request: Request) -> str:
    """Rate limit key: JWT sub if present, else IP fallback."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            from app.config import get_settings
            import jwt as pyjwt
            payload = pyjwt.decode(
                auth[7:],
                get_settings().supabase_jwt_secret,
                algorithms=["HS256"],
                options={"verify_exp": False},  # expiry already checked by get_current_user dep
            )
            return f"user:{payload['sub']}"
        except Exception:
            pass
    return get_remote_address(request)

# Then in the route, import limiter from main and apply:
# @limiter.limit("5/minute", key_func=_get_user_key)
# The route also needs `request: Request` as first param for slowapi
```

To avoid circular imports: do NOT `from app.main import limiter`. Instead, access it via `request.app.state.limiter` inside the key function, or move `limiter` to `app/core/rate_limit.py` and import from there in both `main.py` and `router.py`.

**Recommended structure:**
```
apps/api/app/core/rate_limit.py  ← defines limiter + _get_user_key
main.py  ← imports limiter from core/rate_limit
router.py  ← imports limiter + _get_user_key from core/rate_limit
```

### Supabase Client Note

`get_supabase()` is synchronous (returns a cached `supabase-py` v2 client). Call it without `await`. supabase-py v2 `.execute()` calls are synchronous by default. Run them directly in the async handler — they are fast (< 50 ms) and don't block the event loop significantly for this use case. If blocking becomes an issue in load testing (S4-1), wrap in `asyncio.to_thread()`.

### ARQ Job Name

The ARQ job function is registered as `content_pipeline_job` (the function name). ARQ uses the function's `__name__` attribute as the job identifier. Enqueue with the string `"content_pipeline_job"` — not the module path.

```python
job = await arq_redis.enqueue_job("content_pipeline_job", lesson_id)
job_id: str = job.job_id  # UUID string
```

### `LessonStatusResponse` Status Mapping

DB values → API values:
| `lessons.status` | API `status` |
|-----------------|-------------|
| `generating` | `"running"` |
| `ready` | `"ready"` |
| `failed` | `"failed"` |
| (no row yet / pending) | `"queued"` |

Remove `progress_pct` from `LessonStatusResponse` — column was dropped in the gap-fix commit (195c2da). Return it as `None` always if you must keep backward compat, or remove the field entirely since no client reads it yet.

### Supabase Storage Bucket

The bucket name for source PDFs is `source-pdfs` (referenced in router.py comment). Ensure this bucket exists in Supabase with an appropriate RLS policy — service-role key bypasses RLS so the upload will work regardless, but the bucket must exist.

### `file.size` Caveat

`UploadFile.size` is only populated by FastAPI ≥ 0.103.0 when the client sends `Content-Length`. For earlier versions or clients that omit `Content-Length`, `file.size` may be `None`. Safe pattern: check `file.size` if available, then enforce after reading:

```python
if file.size and file.size > MAX_PDF_SIZE_BYTES:
    raise HTTPException(status_code=413, detail="File too large")
pdf_bytes = await file.read()
if len(pdf_bytes) > MAX_PDF_SIZE_BYTES:
    raise HTTPException(status_code=413, detail="File too large")
```

### What `current_user` Contains

`get_current_user` returns the decoded JWT payload dict. Key fields:
- `current_user["sub"]` — user UUID (use as `user_id`)
- `current_user["email"]` — user email (optional, for logging)
- `current_user["role"]` — Supabase role

### Deferred Work (do NOT implement in this story)

- ARQ `_retry_after` header on 429 response — slowapi handles this automatically
- Async Supabase calls — sync is fine for Sprint 1; revisit in Sprint 4 load test (S4-1)
- `GET /api/content/lessons` cursor-based pagination — offset/limit is fine for Sprint 1

### Project Structure Notes

All new files align with the module pattern established in Sprint 0:
- Router logic stays in `apps/api/app/modules/content/router.py`
- Rate limiter moved to `apps/api/app/core/rate_limit.py` (new file, avoids circular import)
- Tests in `apps/api/tests/unit/test_content_router.py` (new file, follows existing test structure)
- No new DB migrations required — `books`, `lessons`, `lesson_jobs` schema from migrations 20260611 and 20260625 covers all writes

### References

- DB schema: `supabase/migrations/20260611000000_initial_schema.sql` — books, lessons, lesson_jobs tables
- DB schema: `supabase/migrations/20260625000000_chunks_inline_embedding.sql` — lessons.book_id FK
- CLAUDE.md: `API Endpoints` section — `POST /api/content/lessons` contract (frozen: 4-dev PR to change)
- CLAUDE.md: Security §18 — PDF must be parsed in isolated subprocess (extraction happens in `extract_node`, NOT here)
- ARQ docs: `arq.connections.ArqRedis.enqueue_job()` — returns `Job` with `.job_id`
- slowapi docs: per-route `key_func` override on `@limiter.limit()`
- Dev1 tracker: S1-9 + S1-10 spec (this story implements both)

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

- Starlette `HTTP_413_REQUEST_ENTITY_TOO_LARGE` / `HTTP_422_UNPROCESSABLE_ENTITY` deprecated in installed version — replaced with integer literals 413/422
- `MagicMock.table()` always returns same child mock regardless of arg — fixed with `side_effect` dispatch by table name
- `main.py` had UTF-8 BOM + mojibake em dash in description string — fixed at byte level
- `get_settings` in `_get_user_key` is a local import inside the function — patch via `app.config.get_settings`, not `app.core.rate_limit.get_settings`
- `arq.connections.RedisSettings.from_url()` may not exist in arq 0.26 — used URL-parse helper pattern (same as workers/main.py)

### Completion Notes List

- Used `core/rate_limit.py` (new file) for the shared limiter to avoid circular import between `main.py` and `router.py`
- HTTP status codes use integer literals instead of deprecated `fastapi.status.HTTP_4xx_*` constants (Starlette deprecation)
- `get_arq_redis` dependency returns `request.app.state.arq_redis` (ArqRedis pool); `get_redis()` returns `redis.asyncio.Redis` — these must NOT be confused
- `maybe_single()` used for `GET /lessons/{id}` to get `None` instead of exception on missing row
- All 9 ACs satisfied, 13 unit tests pass, 0 regressions

### File List

- `apps/api/app/core/rate_limit.py` (NEW) — per-user limiter + `_get_user_key`
- `apps/api/app/main.py` (MODIFIED) — ARQ pool in lifespan, import limiter from core/rate_limit
- `apps/api/app/dependencies.py` (MODIFIED) — `get_arq_redis()`, `ArqRedis` alias
- `apps/api/app/modules/content/router.py` (MODIFIED) — full implementation of all 3 endpoints
- `apps/api/tests/conftest.py` (NEW) — session-scoped env stubs for all required Settings
- `apps/api/tests/unit/__init__.py` (NEW) — package marker
- `apps/api/tests/unit/test_content_router.py` (NEW) — 13 unit tests
