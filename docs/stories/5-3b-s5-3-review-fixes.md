---
status: ready-for-dev
baseline_commit: ""
---

# Story S5-3b — Chapter Context Form: 10 Dev-2 Review Findings

**Branch:** `sprint5/s5-3-chapter-context-form`
**PR:** #238
**Blocking:** PR #238 cannot merge until all CONFIRMED findings are resolved; PLAUSIBLE findings
should be resolved in the same pass to avoid a second review cycle.

---

## Story

As the engineering team, we need to fix all 10 findings raised by Dev 2's review of PR #238 before
the chapter context form (S5-3) can be merged. The findings cover event-loop blocking, missing UUID
validation, missing rate limiting, a dangling Langfuse span, a redundant DB round-trip, a 204
body violation, and a frontend timeout gap.

---

## Acceptance Criteria

### AC1 — Event-loop blocking removed from context_chapter.py (Finding 1)
- `upsert_chapter_context` wraps every `.execute()` call in `asyncio.to_thread`
- `get_chapter_context_row` wraps every `.execute()` call in `asyncio.to_thread`
- No blocking supabase-py call remains in any `async def` function in `context_chapter.py`

### AC2 — `_resolve_chapter_for_context` rewritten as async; reuses `_fetch_owned_book` (Finding 2)
- `_resolve_chapter_for_context` is `async def`
- Book ownership check delegates to `_fetch_owned_book` (existing helper, D139 pattern)
- All `.execute()` calls inside this function are wrapped in `asyncio.to_thread`
- Call sites in `put_chapter_context` and `get_chapter_context` use `await`

### AC3 — UUID pre-validation in context endpoints (Finding 3)
- `_resolve_chapter_for_context` calls `_validated_book_id(book_id)` before any DB access
- `_resolve_chapter_for_context` calls `_validated_chapter_id(chapter_id)` before any DB access
- A malformed UUID path segment returns 404, never 500 (22P02 never reaches Postgres)

### AC4 — Rate limiting on PUT/GET /context (Finding 4)
- Both endpoints decorated with `@limiter.limit("3/minute;20/hour", key_func=_get_user_key)`
- Both endpoint function signatures include `request: Request` as the first parameter
- The rate limit key is per-user (same `_get_user_key` as `generate_chapter_lesson`)

### AC5 — Langfuse span is opened AND ended in `lesson_planner_node` (Finding 5)
- `start_observation(as_type="span", ...)` return value is captured
- `span.end()` is called in a `safe_trace` call immediately after
- No dangling span remains after `lesson_planner_node` runs

### AC6 — `upsert_chapter_context` returns the written row; no second round-trip (Finding 6)
- `upsert_chapter_context` chains `.select(_CHAPTER_CONTEXT_COLUMNS)` on the upsert call
- Return type is `dict[str, Any]` (the written row, never empty if upsert succeeded)
- `put_chapter_context` in `router.py` uses the returned row directly — no second
  `get_chapter_context_row` call

### AC7 — `_resolve_chapter_for_context` docstring corrected (Finding 7)
- Docstring no longer mentions 403
- Docstring accurately describes: 404 for malformed UUIDs, unknown books, cross-user books,
  unknown chapters

### AC8 — FK race condition handled gracefully (Finding 8)
- `put_chapter_context` catches `postgrest.exceptions.APIError` with code `"23503"` (FK violation)
  and raises `HTTP 404 "Chapter not found"` instead of propagating a raw 500
- A `# PREMISE:` comment (or equivalent guard test reference) identifies the exception class

### AC9 — GET /context returns proper 204 with no body (Finding 9)
- When no context row exists, `get_chapter_context` returns `Response(status_code=204)` directly
- The endpoint never returns `None` with a manually-set `response.status_code = 204`
- An existing test asserts `resp.body == b""` (or equivalent) for the 204 path

### AC10 — `ChapterContextForm.tsx` has a 5 s timeout on the mount-time fetch (Finding 10)
- If `getChapterContext` does not resolve within 5 s, the loading spinner clears
- Student sees the empty form (all fields blank, Skip/Generate Now buttons visible) rather than
  an infinite spinner
- The timeout path is treated as non-fatal (same as a fetch error — form stays empty)

### AC11 — Guard tests pass (`test_node_return_shape`, `test_unbounded_queries`, ruff, mypy)
- `pytest tests/unit/test_node_return_shape.py -v` passes
- `pytest tests/unit/test_unbounded_queries.py -v` passes
- `python -m ruff check apps/api/app/modules/content/context_chapter.py apps/api/app/modules/content/router.py apps/api/app/modules/content/pipeline/graph.py` → 0 errors
- `python -m ruff format --check` same files → already formatted
- `python -m mypy apps/api/app/modules/content/context_chapter.py apps/api/app/modules/content/router.py --ignore-missing-imports` → 0 errors

---

## Tasks / Subtasks

- [ ] **T1** — Fix event-loop blocking in `context_chapter.py` (AC1, AC6)
  - [ ] T1.1 Add `import asyncio` to `context_chapter.py`
  - [ ] T1.2 Wrap `upsert_chapter_context`'s `.execute()` in `asyncio.to_thread`; chain `.select(_CHAPTER_CONTEXT_COLUMNS)` on the upsert; return the written row (`dict[str, Any]`)
  - [ ] T1.3 Wrap `get_chapter_context_row`'s `.execute()` in `asyncio.to_thread`
  - [ ] T1.4 Update `upsert_chapter_context` docstring and return type annotation
  - [ ] T1.5 Update unit tests for new `upsert_chapter_context` return type

- [ ] **T2** — Rewrite `_resolve_chapter_for_context` as async; UUID guards; reuse `_fetch_owned_book` (AC2, AC3, AC7)
  - [ ] T2.1 Change signature to `async def _resolve_chapter_for_context(book_id, chapter_id, user_id, supabase)` returning `tuple[str, str]` (validated IDs)
  - [ ] T2.2 Call `_validated_book_id(book_id)` and `_validated_chapter_id(chapter_id)` first
  - [ ] T2.3 Delegate book ownership to `asyncio.to_thread(_fetch_owned_book, supabase, validated_book_id, user_id, "book_id")`
  - [ ] T2.4 Fetch chapter with `asyncio.to_thread` scoped to `validated_book_id`; 404 if missing
  - [ ] T2.5 Fix docstring (remove 403 mention; describe actual 404 behaviour)
  - [ ] T2.6 Update call sites: add `await` and use returned validated IDs

- [ ] **T3** — Add rate limiting to PUT/GET /context (AC4)
  - [ ] T3.1 Add `request: Request` as first parameter to `put_chapter_context`
  - [ ] T3.2 Add `@limiter.limit("3/minute;20/hour", key_func=_get_user_key)` decorator
  - [ ] T3.3 Add `request: Request` as first parameter to `get_chapter_context`
  - [ ] T3.4 Add `@limiter.limit("3/minute;20/hour", key_func=_get_user_key)` decorator

- [ ] **T4** — Fix dangling Langfuse span in `graph.py` (AC5)
  - [ ] T4.1 Capture return value: `_span = safe_trace(lambda: _lf.start_observation(...))`
  - [ ] T4.2 End the span: `if _span is not None: safe_trace(_span.end)`

- [ ] **T5** — Eliminate redundant DB round-trip in `put_chapter_context` (AC6)
  - [ ] T5.1 Remove the `row = await get_chapter_context_row(chapter_id, user["sub"])` call
  - [ ] T5.2 Use the row returned by `upsert_chapter_context` directly
  - [ ] T5.3 Handle empty-row case: raise 500 if upsert returns empty dict

- [ ] **T6** — Handle FK race condition in `put_chapter_context` (AC8)
  - [ ] T6.1 Import `APIError` from `postgrest.exceptions`
  - [ ] T6.2 Wrap `upsert_chapter_context` call in try/except; catch `APIError` with code `"23503"` → raise 404
  - [ ] T6.3 Add `# PREMISE: APIError(code="23503") is the FK violation from supabase-py's postgrest layer` comment

- [ ] **T7** — Fix 204 response body in GET /context (AC9)
  - [ ] T7.1 Change `response.status_code = 204; return None` to `return Response(status_code=204)`
  - [ ] T7.2 Update endpoint return type annotation accordingly
  - [ ] T7.3 Add `resp.content == b""` assertion to existing 204 test in `test_s5_3_endpoints.py`

- [ ] **T8** — Add 5 s timeout to `ChapterContextForm.tsx` mount fetch (AC10)
  - [ ] T8.1 Wrap `booksService.getChapterContext(...)` with a `Promise.race` against a 5000ms timeout promise
  - [ ] T8.2 On timeout, clear loading (form stays empty); treat as non-fatal

- [ ] **T9** — Verify guard tests and CI checks pass (AC11)
  - [ ] T9.1 Run `pytest tests/unit/test_node_return_shape.py tests/unit/test_unbounded_queries.py -v`
  - [ ] T9.2 Run ruff lint + format check on changed files
  - [ ] T9.3 Run mypy on changed files
  - [ ] T9.4 Verify full unit test suite passes

---

## Dev Notes

### Patterns to follow exactly

**asyncio.to_thread pattern** (from `generate_chapter_lesson`, `router.py:1215-1228`):
```python
book = await asyncio.to_thread(
    _fetch_owned_book, supabase, validated_book_id, user_id, "book_id"
)
chapter_resp = await asyncio.to_thread(
    lambda: (
        supabase.table("chapters")
        .select("chapter_id")
        .eq("chapter_id", validated_chapter_id)
        .eq("book_id", validated_book_id)
        .maybe_single()
        .execute()
    )
)
```

**Upsert+select pattern** (eliminates second round-trip):
```python
resp = await asyncio.to_thread(
    lambda: db.table("chapter_context")
        .upsert({...}, on_conflict="chapter_id,user_id")
        .select(_CHAPTER_CONTEXT_COLUMNS)
        .execute()
)
rows = resp.data or []
return rows[0] if rows else {}
```

**Rate limit decorator** (from `generate_chapter_lesson`, `router.py:1106`):
```python
@router.put(...)
@limiter.limit("3/minute;20/hour", key_func=_get_user_key)
async def put_chapter_context(
    request: Request,  # load-bearing for slowapi — do not remove
    ...
```

**Span lifecycle** (from `traced_node`, `langfuse.py:160-176`):
```python
_span = safe_trace(lambda: _lf.start_observation(
    name="chapter_context_check",
    as_type="span",
    trace_context=_bound_ctx,
    metadata={"has_chapter_context": has_chapter_context},
))
if _span is not None:
    safe_trace(_span.end)
```

**204 with no body** (FastAPI pattern):
```python
from fastapi import Response
...
return Response(status_code=204)  # FastAPI bypasses serialization for Response objects
```

**FK exception** (postgrest-py):
```python
from postgrest.exceptions import APIError
try:
    row = await upsert_chapter_context(...)
except APIError as exc:
    if getattr(exc, "code", None) == "23503":
        raise HTTPException(status_code=404, detail="Chapter not found") from exc
    raise
```

**Frontend timeout** (Promise.race):
```typescript
const timeoutMs = 5000;
const timeoutSignal = new Promise<null>(resolve =>
    setTimeout(() => resolve(null), timeoutMs)
);
const row = await Promise.race([
    booksService.getChapterContext(bookId, chapterId),
    timeoutSignal,
]);
```

### Files to modify
- `apps/api/app/modules/content/context_chapter.py` — T1, T5 (partial)
- `apps/api/app/modules/content/router.py` — T2, T3, T5, T6, T7
- `apps/api/app/modules/content/pipeline/graph.py` — T4
- `apps/web/src/components/dashboard/books/ChapterContextForm.tsx` — T8
- `apps/api/tests/test_s5_3_chapter_context.py` — T1.5
- `apps/api/tests/test_s5_3_endpoints.py` — T7.3

### Guard tests to run before push
```
pytest tests/unit/test_node_return_shape.py tests/unit/test_unbounded_queries.py -v
```

---

## Scale & Load

### Q1 — What is ONE unit of work, and what is its range?
One unit of work is one PUT or GET /context call for a single (book, chapter, user) triple.
- **Min:** a PUT with all fields null (empty form submission) — one upsert row, ~50 bytes
- **Typical:** 5 fields, 2 MCQ values + 2 text fields (~200 chars each) + 1 boolean — one row
- **Largest measured:** two text fields at maxLength=500 (~1 KB total) — unchanged from S5-3
- **Beyond limit:** text fields are capped at 500 chars by the Pydantic schema; no silent truncation

### Q2 — Which budgets are FIXED while the input VARIES?
- **Text fields:** Pydantic `max_length=500` on `specific_doubt` and `goal_and_skip` — schema
  validation raises 422 before DB; explicit error, not silent truncation
- **Rate limit:** 3/minute, 20/hour per user — explicit 429 response
- **asyncio.to_thread thread pool:** bounded by the OS thread pool (default 8–16 threads for
  Python executor) — requests queue rather than fail; no new risk beyond all other DB calls

### Q3 — What is the SCOPE of every limit?
- Rate limit: per-user (keyed by `_get_user_key = JWT sub`) — not per-IP (fixing D52 class)
- `RATE_LIMIT_STORAGE_URL` defaults to `memory://` (D49) — known multi-replica gap, registered
  in existing defect register, not introduced here

### Q4 — Which reads and writes are UNBOUNDED?
- `get_chapter_context_row`: bounded by `.limit(1)` — unchanged, already correctly bounded
- No list reads introduced by this story

### Q5 — Which caps were INHERITED from an earlier design?
- Rate limit "3/minute;20/hour" matches `generate_chapter_lesson` — re-derived as appropriate
  for a low-cost, idempotent form submission (no LLM calls, no ARQ jobs)

### Q6 — Is every check-then-act sequence safe under concurrent requests?
- The upsert uses `on_conflict="chapter_id,user_id"` — idempotent under concurrent writes to
  the same row; two concurrent PUTs both succeed and last-writer-wins at the DB level
- The FK race (AC8): concurrent chapter DELETE between ownership check and upsert → FK 23503 →
  now caught and surfaced as 404 instead of 500; not atomically prevented (no transaction) but
  explicitly surfaced — registered vs. silently accepted (CLAUDE.md binding rule 5)

---

## Dev Agent Record

### Debug Log
_Populated during implementation._

### Completion Notes
_Populated during implementation._

### Implementation Plan
_Populated during implementation._

---

## File List
_Populated during implementation._

---

## Change Log
_Populated during implementation._
