# Story: `book_ingest_job` must mark `books.status = 'failed'` when ARQ cancels it on timeout

**Discovered:** 2026-09-24, live production smoke-test of book ingestion (real upload of
"The Hitchhiker's Guide to Python", 501 pages, via `hieiq.ai/upload`). Registered as **D181**
in `docs/DEFECT-REGISTER.md`.

## Problem

`book_ingest_job` (`apps/api/app/workers/jobs/book_ingest.py`) wraps its whole body in:

```python
except Exception as exc:
    logger.exception("book_ingest_job FAILED book_id=%s", book_id)
    try:
        supabase.table("books").update({"status": "failed"}).eq("book_id", book_id).execute()
    except Exception:
        logger.exception("book_ingest_job could not mark book %s failed", book_id)
    raise BookIngestError(str(exc)) from exc
```

`except Exception` does **not** catch `asyncio.CancelledError` — it has inherited from
`BaseException`, not `Exception`, since Python 3.8. When ARQ's own outer `job_timeout`
(`arq_job_timeout_s`, default 1800s) fires and cancels the job's task, the cancellation lands
as `asyncio.CancelledError` inside `_extract_text_only`'s `await proc.communicate()` /
`await proc.wait()`. That `CancelledError` propagates straight past this `except Exception`
block untouched. The `books.status = 'failed'` write never runs. `books.status` is left at
`'processing'` **permanently** — there is no other code path that ever revisits it — with no
error surfaced to the uploader, the admin, or any log a human is likely to read.

**Confirmed live** against book_id `22dce7c5-55c5-4086-b885-9f45f052871b`
(`hie-api` Fly app, machine `873d97a0404d78`, `sin` region):

- `13:02:25` — `book_ingest_job` starts.
- `13:32:25` (exactly `1800.03s` later — ARQ's `arq_job_timeout_s`, not the code's own
  900s `_EXTRACT_TIMEOUT_S`) — ARQ logs `book_ingest_job failed, TimeoutError`, traceback
  shows `asyncio.CancelledError` raised inside `proc.communicate()`/`proc.wait()`.
- `14:2x` — direct `/proc` inspection on the worker machine (via `fly-machine-exec`, no `ps`
  binary in this slim image, so read `/proc/[pid]/cmdline` directly) shows **no extraction
  subprocess running at all** — it is long dead.
- Fresh DB query at the same time: `books.status = 'processing'`, `updated_at` unchanged
  since the original `13:02:23.703543+00` insert — **1h22m** stuck with zero record of the
  failure ARQ itself already logged.

This is a distinct root cause from **D180** (ARQ's job-level `max_tries` retry never fires for
exceptions this codebase raises) — D180 is about the job not being *retried*; this story is
about the job's own *failure bookkeeping* silently not running on cancellation, regardless of
whether a retry follows. Both are real; only this one is in scope here, per Defect Register
binding rule 6 ("wrong at site 19 means wrong at site 1 — open a register entry instead" of
folding into an existing one with a different root cause).

## Acceptance Criteria

1. **AC1**: `book_ingest_job` catches `asyncio.CancelledError` in addition to `Exception` and,
   on that path too, writes `books.status = 'failed'` (with a reason distinguishable in logs
   from an ordinary exception failure) **before re-raising `CancelledError`** — a cancelled
   task must not be swallowed or converted into a different exception type, since that breaks
   asyncio's own cancellation propagation contract (the task must still end up cancelled from
   the caller's point of view).
2. **AC2**: The `finally`-block cleanup in `_extract_text_only` (`proc.kill()` /
   `await proc.wait()` to reap the child) must not itself raise `CancelledError` and mask the
   original cancellation — verified by a test that cancels the task mid-`communicate()` and
   asserts the process is reaped without a second, confusing exception replacing the first.
3. **AC3**: Regression test `test_book_ingest_job_cancelled_marks_books_failed` — cancels the
   job's task while it is inside `_extract_text_only`, asserts
   `supabase.table("books").update` was called with `{"status": "failed"}` for this
   `book_id`, and asserts the awaited call still raises `asyncio.CancelledError` (not
   `BookIngestError` or any other type) to its caller.
4. **AC4**: `docs/DEFECT-REGISTER.md` gets a new `D181` entry (status `FIXED-GUARDED` once
   AC3's test lands in CI) describing this exact failure mode, cross-linking **D180**.
5. **AC5**: `tests/unit/test_book_ingest_job.py` and any other existing guard tests that
   reference `book_ingest.py` still pass (BMAD guard-test discipline — Development Rules,
   "Guard-test check before touching any module").

## Scale & Load

1. **Unit of work & range**: one `book_ingest_job` invocation per uploaded book. This fix
   changes only the failure-bookkeeping path; it does not change per-book cost or duration.
2. **Fixed budgets vs. variable input**: `_EXTRACT_TIMEOUT_S = 900` (inner) and
   `arq_job_timeout_s = 1800` (outer) are both still fixed. This story does **not** re-derive
   either — that a 501-page book's extraction subprocess ran past 900s (and even past 1800s)
   in production while completing in under 60s locally with the correctly pinned dependency is
   a **separate, still-open question** (why production extraction is ~30x slower than local)
   and is explicitly out of scope for this story, which only fixes what happens *after* the
   timeout fires. Filed as a follow-up, not silently dropped.
3. **Scope of the fix**: per-job. No new shared state, no new limiter, no cross-request
   concern.
4. **Unbounded reads/writes**: none introduced. The `books.status` update is a single-row
   `.eq("book_id", book_id)` write, matching the existing pattern used for the `Exception`
   branch it parallels.
5. **Inherited caps re-derived?**: N/A — no cap changes here, only the exception type caught.
6. **Concurrent-request safety**: the `books.status = 'failed'` write on the cancellation path
   uses the same single-row `.eq(...)` update as the existing exception path; no new
   check-then-act sequence is introduced. A book row is only ever ingested by one
   `book_ingest_job` at a time (idempotency section of the job's own docstring), so no new
   concurrency hazard is created by adding a second write path that reaches the same update.

## Out of scope

- Why the extraction subprocess itself took >30 minutes in production for a book that
  extracts in <60s locally (resource contention on the shared `sin`-region Fly worker vs. a
  genuine hang — not yet distinguished). Tracked separately; not blocked on this story.
- D180 (ARQ's `max_tries` retry not actually firing for any exception this codebase raises).
- Manually unsticking the specific stuck book row (`22dce7c5-55c5-4086-b885-9f45f052871b`) —
  done directly via SQL as an operational action once this fix is verified, not part of the
  code change itself.
