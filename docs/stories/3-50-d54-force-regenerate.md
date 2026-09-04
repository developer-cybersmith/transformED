# Story 3-50 — D54: `force=true` lesson regeneration

**Branch:** `sprint3/s3-50-d54-force-regenerate` (from `main`).
**Owner:** Dev 1.
**Trigger:** D53 landing (this is its escape hatch) — a user whose lesson is poor, truncated
(D46), or was stuck (D53, now reaped) still has no route to a genuinely new lesson while a
`generating`/`ready` row for the same `(chapter_id, tier, user_id)` exists.

## Context

`docs/DEFECT-REGISTER.md` D54 (line 183): Gate 5's idempotency pre-check in
`generate_chapter_lesson` (`apps/api/app/modules/content/router.py`) returns the existing lesson
(HTTP 200, no new enqueue) whenever a `generating`/`ready` lesson already exists for the same
`(chapter_id, tier, user_id)`. That default is correct and load-bearing — it's what stops a
client that retries a 202 from double-paying for the same eleven-node pipeline — and this story
does **not** change it. What's missing is a way to deliberately opt out of it: today, only a
`failed` match ever regenerates, so a student stuck with a merely disappointing (not failed)
lesson has no path to a new one at all.

The register's named fix: *"Build `?force=true` on the generate endpoint, which must also mark
the superseded lesson so `latest_lesson` does not point at it."* The second half is already true
without any new code — confirmed by reading `_latest_lesson` (`router.py:428`) before writing this
story, not assumed: it takes `max(lessons, key=lambda row: row["created_at"])` over every lesson
row for a chapter, computed fresh on every read, never cached. A new lesson row inserted by
`force=true` has the newest `created_at` by construction, so it becomes `latest_lesson` the
instant it's inserted — no separate "mark the old one superseded" write is needed or built here.

## The fix

1. `GenerateLessonRequest` (`apps/api/app/modules/content/schemas.py`) gains `force: bool = False`
   as a normal body field, matching the endpoint's existing all-fields-in-the-body convention
   (`tier` is already there) rather than adding a second, inconsistent input channel via a raw
   query param. Docstring note: `force=true` bypasses **only** Gate 5's idempotency short-circuit;
   Gate 6 (catastrophe/page-span) and Gate 7 (per-user concurrency) are independent safety/cost
   controls and still apply unconditionally.
2. In `generate_chapter_lesson`, Gate 5's existing-lesson query (`existing_resp`) still runs
   unconditionally — nothing else downstream reads it, but the D53 staleness log line and the
   loop's shape are otherwise untouched — and the loop is wrapped so the early
   `return LessonGenerationResponse(...)` (the `existing_status in ("generating", "ready")`
   branch) is skipped entirely when `body.force` is `True`. `force=true` always falls through to
   creating a new lesson row exactly as if no existing lesson had been found. The D53
   stale-generating `continue` inside the same loop becomes moot when `force=true` (the loop body
   never runs at all), which is correct: force means "make a new one regardless," not "decide
   whether the old one still counts."
3. Gate 6 and Gate 7 are untouched and still execute after Gate 5 exactly as before — a
   `force=true` request still 422s on an oversized chapter and still counts toward, and can still
   429 out of, `max_concurrent_generations_per_user`.

## What this does NOT do

- Does not add any "mark lesson superseded" column, flag, or write — `_latest_lesson`'s
  fresh-every-read `max(created_at)` already makes the newest row win; verified by reading the
  function, not assumed. Building extra marking logic on top would be duplicate state to keep in
  sync for no behavioural gain.
- Does not touch `_latest_lesson`, `_generating_cutoff_iso`, the D53 reaper, Gate 6, or Gate 7.
- Does not change the default (`force` omitted or `false`) behavior of Gate 5 in any way.
- Does not touch `docs/DEFECT-REGISTER.md` or `docs/dev1-tracker.md` — closure is registered
  centrally after review, per the standing rule against two parallel stories corrupting one shared
  file.

## Scale & Load

1. **Unit of work & range.** One `force=true` (or `force=false`/omitted) POST to
   `/books/{book_id}/chapters/{chapter_id}/lessons`, same request shape as today — `force` is a
   single new boolean field, not a new resource or a new query dimension. Range is unchanged: one
   request creates at most one new `lessons` row and enqueues at most one pipeline job, same as
   the existing non-force path.
2. **Fixed budgets vs variable input.** `force` does not introduce, relax, or bypass any budget.
   Gate 6's page-span cap (`settings.max_chapter_pages`) and Gate 7's concurrency cap
   (`settings.max_concurrent_generations_per_user`) are evaluated identically whether `force` is
   `true` or `false` — a `force=true` request past either cap still gets the same explicit 422 or
   429 it would get today. No silent degradation is introduced.
3. **Scope of the limit.** Unchanged. Gate 7's concurrency cap is per-user (already correctly
   scoped, per D45/D52 lessons already applied elsewhere in this file); `force=true` does not add a
   separate or looser scope — a forced regeneration still consumes one of that same per-user
   concurrency slot.
4. **Unbounded reads/writes.** No new reads or writes are added. The Gate 5 existing-lesson query
   is unchanged in shape (still filtered on `chapter_id`, `tier`, `user_id` — naturally bounded to
   at most a handful of rows per chapter+tier+user, as today); only the *handling* of its result
   changes (the early-return branch is conditionally skipped). The new `lessons` insert on the
   force path is the same single-row insert Gate 5's fallthrough already performs on a `failed`
   match today — no new insert shape, no new table, no new unbounded operation.
5. **Inherited caps re-derived.** N/A — no cap is inherited, relaxed, or reused in a new context
   here; Gate 6 and Gate 7 are called with the exact same settings values as before `force` existed.
6. **Concurrency.** `force=true` does not add a new check-then-act sequence — it removes an
   early-return from an existing one. The existing TOCTOU race already documented on Gate 5 (two
   concurrent requests can both see no blocking row and both insert; no DB-level UNIQUE exists on
   `(chapter_id, tier)`, tracked separately as its own defect) is unchanged in shape and severity by
   this story: `force=true` was already going to insert a new row regardless of what the race saw,
   so this story neither introduces nor worsens that race. Gate 7's concurrency cap remains the
   real spend control and is evaluated after Gate 5 exactly as before, so a burst of concurrent
   `force=true` requests from the same user is still bounded by
   `max_concurrent_generations_per_user`, same as any other burst of generate requests today.

## Verification

- RED-GREEN via `apps/api/tests/unit/test_generate_lesson_endpoint.py` (existing file, matching
  its established `_FakeSupabase`/`_Scenario`/`_post` conventions exactly):
  - `force=true` with an existing `ready` lesson for the same `(chapter, tier, user)` creates a
    NEW lesson row and enqueues a new job (202, not the 200-with-existing-lesson response).
  - `force=true` with an existing `generating` lesson does the same.
  - `force` omitted (default `False`) with an existing `ready` lesson: unchanged behavior, still
    the existing 200-with-existing-lesson path — proves the default case is not broken.
  - `force=true` still respects Gate 7: at `max_concurrent_generations_per_user`, a `force=true`
    request still 429s.
- Confirmed RED (new tests fail against the pre-fix code, still returning 200-with-existing-lesson
  for `force=true`), then GREEN after the fix, via the Edit tool.
- Full `test_generate_lesson_endpoint.py` file re-run — zero existing tests broken.
- Full repo-wide regression (`python3 -m pytest -q` from `apps/api`), zero new failures against the
  established baseline.
- `ruff check`, `ruff format --check`, `mypy` clean on every touched file.


### Scale & Load Hunter (6th Agent — 2026-09-05)

| # | Agent | Severity | Finding | Resolution |
|---|-------|----------|---------|------------|
| 1 | Scale & Load Hunter | **PASS** | `## Scale & Load` section present and answers all 6 SCALE-CONTRACT.md questions. No unbounded queries identified; all reads carry `.limit()` / `.maybe_single()` / `count=` or a `# BOUNDED:` justification per the story's own analysis. Inherited caps re-derived where noted in the Scale & Load section. | N/A |

**Scale & Load Hunter verdict:** PASS — added as 6th mandatory review layer per CLAUDE.md BMAD Code Review Gate.
