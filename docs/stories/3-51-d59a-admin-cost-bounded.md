# Story 3-51 — D59(a): bound the admin cost-report query

**Branch:** `sprint3/s3-51-d59a-admin-cost-bounded` (from `main`).
**Owner:** Dev 1.
**Trigger:** Sprint 3's own S3-4 ("Admin panel: job status, cost tracking") making the admin
panel real, per D59's own owner/trigger note in `docs/DEFECT-REGISTER.md`.

## Context

`apps/api/app/modules/admin/router.py:192` (`get_cost_report`) runs:

```python
resp = (
    supabase.table("lesson_jobs")
    .select("cost_usd, lesson_id, lessons!inner(user_id, created_at)")
    .gte("lessons.created_at", start.isoformat())
    .execute()
)
```

No `.limit()`. This materialises **every** `lesson_jobs` row (joined to `lessons`) for the
requested period, then groups by user in Python — PostgREST has no server-side GROUP BY, so the
grouping step itself is not the bug, the unbounded fetch feeding it is. Fine at today's real
scale (~23 lessons total); wrong once the admin panel is used against real production volume —
a `this_month` report on a live deployment materialises every job row for the whole month in one
request, with no ceiling.

This is registered as **D59(a)** in `docs/DEFECT-REGISTER.md` (D59 covers two unbounded reads;
part (b), `analytics/service.py:54`, is Dev 3's and is explicitly out of scope for this story).
The query is currently allow-listed in `apps/api/tests/unit/test_unbounded_queries.py`'s
`_KNOWN_UNBOUNDED["admin/router.py"]` — the guard's own docstring says the list "may only
shrink" and landing a real fix without removing the entry is exactly the "matches existing
accepted pattern" ratchet CLAUDE.md's binding rule 6 names, so this story treats removing that
entry as part of the fix, not a separate cleanup.

## The fix

1. Add a new module-level constant in `admin/router.py`:
   ```python
   _COST_REPORT_ROW_LIMIT = 10_000
   ```
   sized generously above any realistic near-term admin report volume (current real scale is
   two orders of magnitude below this).
2. Add `.limit(_COST_REPORT_ROW_LIMIT)` to the query, after `.gte(...)` and before `.execute()`.
3. **Explicit surfaced degradation, not silent truncation** (CLAUDE.md's binding "silent
   truncation is never acceptable" rule — and doubly important for a COST report specifically:
   silently dropping rows would UNDER-report real spend, exactly the failure class this project
   has spent this session fixing in other forms). After the query executes:
   ```python
   truncated = len(matching) == _COST_REPORT_ROW_LIMIT
   ```
   This is a real signal the true row count may exceed what was fetched (PostgREST returned
   exactly the limit, i.e. there could be more), not a guess. Add a new field to `CostReport`:
   ```python
   truncated: bool = False
   # True means more lesson_jobs rows exist for this period than were fetched
   # (hit _COST_REPORT_ROW_LIMIT) — the report below may be missing rows and
   # under-reporting real spend. Narrow the period or raise the limit.
   ```
4. Remove the `"admin/router.py": {"lesson_jobs.select('cost_usd, lesson_id,
   lessons!inner(user_id, created_at)')"}` entry from `_KNOWN_UNBOUNDED` in
   `apps/api/tests/unit/test_unbounded_queries.py`. Leave the `"analytics/service.py"` entry
   untouched (D59(b), Dev 3, out of scope here).

## What this does NOT do

- Does not touch `analytics/service.py` or D59(b) in any way.
- Does not touch `docs/DEFECT-REGISTER.md` or `docs/dev1-tracker.md` — a coordinator registers
  the closure centrally after this branch is reviewed.
- Does not change the period-filter logic (`_period_start`, the `lessons!inner(...)` server-side
  filter) — that part of the query is already correctly bounded to the requested period; the
  missing piece was solely the row-count ceiling on top of it.
- Does not add pagination/offset to the admin `/costs` endpoint — out of scope; `truncated` is
  the surfaced signal an operator uses to narrow the period, not a paging mechanism.

## Scale & Load

1. **What is ONE unit of work, and what is its range?** One admin cost-report request for one
   period (`today` / `this_week` / `this_month`). Range: 0 rows (no jobs yet) up to every
   `lesson_jobs` row created in the period, unbounded by anything upstream — the only thing that
   bounds it is this fix. Today's real measured volume is ~23 lessons total (all-time); a
   `this_month` report at that scale returns a handful of rows.
2. **Which budgets are FIXED while the input VARIES — and what happens past them?** Fixed:
   `_COST_REPORT_ROW_LIMIT = 10_000` rows per request. Past it: the query still returns (capped
   at 10,000 rows via `.limit()`), but `CostReport.truncated` is set `True` — an explicit,
   surfaced degradation the admin caller sees in the response body, not a silent drop. This is
   the re-derivation D59's register entry asks for: previously there was no budget at all (fully
   unbounded), so there was nothing to re-derive; this story is what introduces the first bound
   and states it explicitly rather than letting a future dev inherit an unstated one.
3. **What is the SCOPE of every limit?** Per-request. `_COST_REPORT_ROW_LIMIT` applies to a
   single `GET /api/admin/costs` call; it is not a per-user or per-deployment budget — every
   admin request gets its own fresh 10,000-row ceiling.
4. **Which reads and writes are UNBOUNDED?** None, after this fix, within `get_cost_report`. The
   `.limit()` bounds the previously-unbounded `lesson_jobs` join-select; `test_unbounded_queries.py`
   is the enforcing guard (see below).
5. **Which caps were INHERITED from an earlier design, and have they been re-derived?** None
   inherited — there was no cap before this story (that is the defect). `10_000` is a fresh
   number sized against real current volume (~23 lessons, ~2 orders of magnitude below the cap)
   with headroom for the admin panel becoming real usage this sprint, not carried over from a
   different unit of work.
6. **Is every check-then-act sequence safe under CONCURRENT requests?** N/A — this endpoint is
   read-only (a GET aggregating existing rows into a response); there is no check-then-act
   write sequence here to race. Concurrent admin requests each get their own independent
   `.limit()`-bounded read.

## Tests (added to `apps/api/tests/unit/test_admin_router.py`)

- Query chain includes `.limit(_COST_REPORT_ROW_LIMIT)` — asserted directly on the mock.
- Fewer rows than the limit → `truncated=False`.
- Exactly `_COST_REPORT_ROW_LIMIT` rows returned → `truncated=True`.

## Guard

`apps/api/tests/unit/test_unbounded_queries.py` — the `admin/router.py` allow-list entry is
removed as part of this fix (not left in place), so the repo-wide source-scan guard now actively
enforces that this query stays bounded, per CLAUDE.md binding rule 7 ("a fix without a guard is
FIXED-UNGUARDED, not fixed").


### Scale & Load Hunter (6th Agent — 2026-09-05)

| # | Agent | Severity | Finding | Resolution |
|---|-------|----------|---------|------------|
| 1 | Scale & Load Hunter | **PASS** | `## Scale & Load` section present and answers all 6 SCALE-CONTRACT.md questions. No unbounded queries identified; all reads carry `.limit()` / `.maybe_single()` / `count=` or a `# BOUNDED:` justification per the story's own analysis. Inherited caps re-derived where noted in the Scale & Load section. | N/A |

**Scale & Load Hunter verdict:** PASS — added as 6th mandatory review layer per CLAUDE.md BMAD Code Review Gate.
