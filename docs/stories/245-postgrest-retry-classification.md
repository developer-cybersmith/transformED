# Story 245 — PostgREST/Supabase errors are never retried; classify and wrap the two cost-downstream call sites

**GitHub issue:** #245 — "Supabase/PostgREST errors (e.g. Cloudflare 521) are never retried in the content
pipeline, and ARQ's job-level retry never actually fires either"
**Reporter:** Dev 1 (developer1-cybersmith), confirmed live against 15 real production ingestion attempts
on `real_world_red_team_engineering.pdf` (2026-09-22).
**Status:** Implemented, pending review

## Completion Notes

- **AC1**: `with_retry()` gained a `postgrest.exceptions.APIError` branch (`core/retry.py`), guarded-imported
  like `openai`/`redis`. Classifies on `exc.code`: `int` in `_POSTGREST_RETRYABLE_STATUS_CODES`
  (`_RETRYABLE_STATUS_CODES | {520,521,522,523,524,525,526,527,530}`) → retry; any other `int` → raise
  immediately; `str` → raise immediately (never retried); no code at all → raise immediately (conservative).
- **AC2**: `embed_node`'s chunk-embedding upsert and `chunk_node`'s new-chunk upsert are each now routed
  through a dedicated `@with_retry(max_attempts=3)`-decorated module-level helper
  (`_upsert_embedded_chunk_batch`, `_upsert_new_chunk_rows`) instead of a bare call — same exception shape
  (`RuntimeError(...) from exc`) preserved at both original call sites so existing callers/tests are
  unaffected by the wrapping itself.
- **AC3**: `test_postgrest_api_error_code_is_int_for_non_json_response` added next to the existing
  string-code premise test, proving `APIError(generate_default_error_message(fake_response)).code` is an
  `int` — built directly from the installed package's own fallback constructor, not assumed.
- **AC4**: `test_retry.py` gained 7 new tests mirroring the OpenAI classification suite's structure:
  retryable int codes retry, non-retryable int codes don't, string Postgres codes never retry (parametrized
  over FK/NOT-NULL/`PGRST116`-shaped codes), a bare-APIError-with-no-code conservative case, the
  not-httpx-derived premise, and a subprocess-isolated guarded-import test (postgrest absent → httpx
  classification still works).
- **AC5**: Registered **D180** in `docs/DEFECT-REGISTER.md` for the ARQ-retry-never-fires gap — confirmed
  live by reading the installed `arq` package's `Worker.run_job()` directly (only `arq.worker.Retry`/
  `CancelledError`/`RetryJob` requeue a job; every other exception is a permanent failure after one
  attempt regardless of `max_tries`). Registered, not fixed, per this story's explicit scoping — the real
  fix is job-orchestration work, a separate story.
- **Verification**: `ruff check .`/`ruff format --check .` clean repo-wide; `mypy app` clean except the
  pre-existing, documented, environment-only `tinytag` import gap (unrelated — `tts_node`'s own local
  import, not touched by this story). Full gating suite (`pytest tests/unit tests/integration -m "not
  postgres"`) re-run: 1458 passed, 25 failed — all 25 confirmed pre-existing and unrelated (verified by
  stashing this diff and reproducing the same 25 failures identically: 5 are a separate pre-existing
  `fpdf`/vacuous-fixture gap, 20 all trace to `tts_node`'s own `tinytag` import, none touch `retry.py`,
  `chunk_node`, or `embed_node`). Targeted re-runs of `test_retry.py`, `test_chapter_context_exceptions_
  premise.py`, `test_embed_node.py`, `test_chunk_node.py`, `test_node_return_shape.py`,
  `test_unbounded_queries.py`, `test_book_ingest_job.py`, `test_phase1_economy_nodes.py`,
  `test_pipeline_writes_no_books.py`, `test_pipeline_tier1.py` all green.

## Verified before implementation (not trusted from the issue's prose alone)

- `apps/api/app/core/retry.py` read in full: `with_retry()`'s exception branches are httpx / `_TRANSIENT_ERRORS`
  (httpx transient + Redis + builtin `TimeoutError`) / `CircuitOpenError` / `SanitizedHTTPError` /
  `_OPENAI_API_ERRORS` / catch-all. **No branch anywhere classifies `postgrest.exceptions.APIError`.**
  `_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}` — confirmed missing Cloudflare's 520-527/530.
- `postgrest.exceptions.APIError` read directly from the installed package
  (`site-packages/postgrest/exceptions.py`): `.code` is populated from `error.get("code")`, where `error` is
  either (a) the parsed JSON error body from Postgres/PostgREST — `.code` is a **string** SQLSTATE/PostgREST
  code (e.g. `"23503"`, `"PGRST116"`) — or (b) `generate_default_error_message(r)`'s fallback dict when the
  response body isn't valid JSON (a Cloudflare HTML error page for a 521 is exactly this case) — there,
  `"code": r.status_code`, an **int** (`httpx.Response.status_code`). Both `_async/request_builder.py` and
  `_sync/request_builder.py` raise via this exact fallback in every one of their `except ValidationError`
  handlers. Confirmed live via direct source read, not assumed.
- `apps/api/tests/unit/test_chapter_context_exceptions_premise.py` already has 3 premise tests proving
  `APIError` is `Exception`-derived, carries `.code`, and that `.code` is a **string** in the normal
  (parsed-JSON) case — used by `router.py:1592-1599`'s `exc.code == "23503"` FK-violation check. It has
  **no** test for the int-code (HTTP-status-fallback) branch this story's fix depends on.
- `apps/api/app/modules/content/pipeline/graph.py`: zero `@with_retry` usage anywhere in the file (grep
  confirmed). `embed_node`'s chunk-upsert (~line 1135-1148) and `chunk_node`'s chunk-upsert (~line 923) are
  both bare `try/except Exception as exc: raise RuntimeError(...) from exc` — no retry at either site, both
  sitting downstream of real, already-spent OpenAI embedding cost.
- ARQ's actual retry semantics read directly from the installed `arq` package
  (`site-packages/arq/worker.py`, `Worker.run_job()`, ~line 613-633): a job is only requeued when the raised
  exception is `isinstance(e, Retry)`, or (`retry_jobs=True`) `isinstance(e, (asyncio.CancelledError,
  RetryJob))`. Every other exception (the `else` branch) sets `result = e; finish = True` — the job is
  marked **finished** (permanently failed), never requeued, regardless of `WorkerSettings.max_tries`.
  `grep -rn "arq.worker.Retry" app/` → zero hits anywhere in this codebase, confirmed. `max_tries=3` is
  live-but-inert configuration for every failure mode this codebase currently produces.

## Scope

This story implements exactly the issue's own "Recommended fix" items 1-3, and registers (does not fix)
item 4. It deliberately does **not** touch the other ~28 unwrapped Supabase call sites, does not wire
Supabase into the circuit breaker, and does not address `storage3.exceptions.StorageApiError`
classification (a different exception class entirely) — all named by the issue itself as separately-scoped
follow-ups, not blockers here.

## Acceptance Criteria

- **AC1** — `with_retry()` (`core/retry.py`) gains a `postgrest.exceptions.APIError` exception branch,
  positioned before the catch-all, following the same structure as the existing `_OPENAI_API_ERRORS`
  branch:
  - If `exc.code` is an `int` and is in the retryable set (`_RETRYABLE_STATUS_CODES` **plus** Cloudflare's
    `{520, 521, 522, 523, 524, 525, 526, 527, 530}`) → retry (`last_exc = exc`).
  - If `exc.code` is an `int` and is in `_NON_RETRYABLE_STATUS_CODES`, or any other int not in the
    retryable set → log and re-raise immediately, matching every other branch's "unclassified — not
    retrying" pattern.
  - If `exc.code` is a `str` (a real Postgres/PostgREST error code) → **never** retry, log and re-raise
    immediately. A structured DB error (constraint violation, `PGRST116` "no rows", etc.) is not transient
    and retrying it would be wrong — this is the issue's own explicit caution (§B).
  - The import of `postgrest` must be guarded exactly like the existing `openai`/`redis` guards (`core/`
    must not hard-depend on failing to import this optional-at-runtime dependency); degrade to an empty
    tuple and log a warning, matching the existing pattern for `_OPENAI_API_ERRORS`/`_REDIS_TRANSIENT_ERRORS`.
- **AC2** — `embed_node`'s `chunks` upsert and `chunk_node`'s `chunks` upsert (`content/pipeline/graph.py`)
  are each wrapped so the actual Supabase call goes through `@with_retry(max_attempts=3)` — these are the
  two call sites the issue names as sitting downstream of real, already-spent OpenAI cost. The wrapped
  function's raised-after-exhaustion exception must still surface as the existing `RuntimeError(...)
  from exc` each site already raises, so callers/tests that depend on that shape are unaffected.
- **AC3** — A new premise test, next to the existing `test_postgrest_api_error_code_is_string_type` in
  `test_chapter_context_exceptions_premise.py`, proves `APIError(generate_default_error_message(r)).code`
  is an `int` for a mocked non-JSON response — the int-code branch AC1's fix depends on, previously
  untested (binding rule 3).
- **AC4** — New `with_retry`-focused tests (in `test_retry.py`, mirroring its existing OpenAI/httpx
  classification test style) proving: a retryable int code (e.g. 521) retries and eventually raises after
  exhaustion; a non-retryable int code (e.g. 400) raises immediately without retrying; and a string
  Postgres code (e.g. `"23503"`) raises immediately without retrying, never treated as transient.
- **AC5** — `docs/DEFECT-REGISTER.md` gains a new `D-nn` entry for the ARQ-retry-never-fires gap (issue
  §E) — **registered, not fixed** here, per the issue's own explicit scoping (a distinct root cause: job
  orchestration, not exception classification). Must state the concrete mechanism (only `arq.worker.Retry`/
  `CancelledError`/`RetryJob` requeue a job; everything else — including every exception this codebase
  currently raises — is a permanent failure after one attempt regardless of `max_tries`), and name it as
  the higher-priority of the two gaps this issue reports, since today nothing retries a failed ingestion
  job automatically at any layer.
- **AC6** — Existing guard tests for the touched modules must pass: `tests/unit/test_node_return_shape.py`
  (touches `graph.py`), `tests/unit/test_unbounded_queries.py` (no query-shape change, but `graph.py` is in
  its scanned scope), and `test_retry.py`'s own existing suite (must not regress the httpx/OpenAI/Redis
  classification this change sits alongside).

## Scale & Load (docs/SCALE-CONTRACT.md's six questions)

1. **Unit of work and range**: one retry-decorated call (one chunk-batch upsert, up to `_EMBED_BATCH_SIZE`
   rows per call). Unchanged by this story — `with_retry` adds classification and backoff around an
   existing call, it does not change batch sizing.
2. **Fixed budget meeting variable input**: `max_attempts=3` (fixed) against an arbitrarily-long real
   outage (variable). Past 3 attempts, the original exception is re-raised — an explicit, loud failure
   (the existing `RuntimeError(...) from exc`), never silent. `wait = (2**attempt) + random.random()` full
   jitter, same PRD §14 formula every other retry site uses — bounded to a few seconds across 3 attempts,
   not unbounded.
3. **Scope of every limit**: `max_attempts` is per-call (one `embed_node`/`chunk_node` invocation), not
   per-lesson or per-deployment — unaffected by concurrent lessons or worker replica count.
4. **Unbounded reads/writes**: none introduced. The wrapped calls already had bounded batch sizes before
   this story; `with_retry` does not change what is read or written, only whether a transient failure gets
   a second chance.
5. **Inherited caps re-derived**: `_RETRYABLE_STATUS_CODES`'s Cloudflare extension (520-527, 530) is a new,
   explicit addition, not an inherited assumption — sourced from Cloudflare's own published error-code
   list, cited in the code comment.
6. **Concurrent-request safety**: `with_retry` wraps a single call with no shared mutable state between
   concurrent invocations (each call gets its own `last_exc`/`attempt` closure) — no new check-then-act
   sequence is introduced. `embed_node`/`chunk_node` are not currently subject to the reducer-duplication
   class of bug (CLAUDE.md's `return {**state, ...}` rule) — this story does not touch their return shape.

## Explicitly out of scope (per the issue's own scoping)

- Rewrapping the other ~28 unwrapped Supabase call sites in `graph.py`/`book_ingest.py` (every node's
  `lesson_jobs` checkpoint read/write, `book_ingest.py`'s PDF download, etc.) — real, separately-scoped
  follow-up work.
- Wiring Supabase calls into the circuit breaker (`core/circuit_breaker.py`) — deliberate follow-up, not a
  side effect of this fix.
- `storage3.exceptions.StorageApiError` classification (TTS/image storage-bucket uploads) — a different
  exception class entirely; unaffected by a postgrest-only classification branch.
- Actually fixing the ARQ-retry-never-fires gap (AC5 registers it; the fix itself is job-orchestration
  work, not exception classification, and belongs to a separate story).
