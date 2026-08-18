---
id: "2-48"
title: "Teachback Summary Detail in Session Report"
status: in-progress
owner: dev3
sprint: 3
branch: sprint3/s3-06-teachback-detail
baseline_commit: ""
---

## Story

As a student viewing my session report, I want to see per-attempt teachback feedback so that I can
understand which concepts I demonstrated well and which I missed on each segment.

## Acceptance Criteria

- **AC-1** `GET /api/assessment/session/{id}/report` returns `teachback_details: list[TeachbackDetail] | None`.
- **AC-2** `teachback_details` is `None` (not `[]`) when the session has no teachback attempts.
- **AC-3** Each `TeachbackDetail` has exactly 7 fields: `segment_id`, `score`, `feedback_praise`,
  `feedback_correction`, `concepts_hit`, `concepts_missed`, `attempt_number`.
- **AC-4** Details are ordered by `created_at` ascending (earliest attempt first).
- **AC-5** At most 50 rows returned (existing safety ceiling preserved).
- **AC-6** No new DB migration required — columns already exist in `teachback_attempts`.
- **AC-7** Existing `teachback_score` aggregate is unchanged.
- **AC-8** No LLM call added — pure DB read + model mapping.

## Scale & Load

1. **Unit of work:** one session → one `.select()` on `teachback_attempts`. Range: 0 rows (no
   teach-back) to ~15 rows (one per segment, one attempt each). With retakes bounded by the
   `uq_teachback_attempt` unique constraint at `(session_id, segment_id, attempt_number)`, the
   row count is naturally bounded by `segments × attempt_ceiling`.
2. **Fixed budgets while input varies:** `.limit(50)` is the safety ceiling. A book with more than
   50 segments is explicitly truncated; `teachback_details` will contain only the first 50 rows in
   `created_at` order. Silent truncation is prevented: the `.limit(50)` is visible in the query and
   the caller receives exactly what was fetched.
3. **Scope of limits:** per-session query; no cross-user or cross-session aggregation.
4. **Unbounded reads:** none — `.limit(50)` is applied.
5. **Inherited caps re-derived:** the `.limit(50)` was already present for the `score`-only query;
   it is preserved for the widened select. The widened columns add ~200 bytes per row ×50 rows =
   ~10 KB max payload increase per report — well within Supabase response limits.
6. **Check-then-act under concurrency:** no write path. Pure read — no TOCTOU risk.

## Tasks

- [x] **T1** Create story file and commit story-only — `docs(story-first)` commit
- [x] **T2** Add `TeachbackDetail` Pydantic model to `router.py` (7 fields, matches DB columns)
- [x] **T3** Add `teachback_details: list[TeachbackDetail] | None = None` to `SessionReport`
- [x] **T4** Widen `.select("score")` → full column list + `.order("created_at")` in `service.py`
- [x] **T5** Map `tb_rows` to `TeachbackDetail` objects; pass to `SessionReport`; `None` when 0 rows
- [x] **T6** Update existing test mocks in `test_s3_47` and `test_s3_46` (`.order` chain fix)
- [x] **T7** Write `tests/test_s2_48_teachback_detail.py` covering all 8 ACs

## Dev Notes

- `TeachbackDetail` lives in `router.py` alongside `SessionReport` (lazy-imported in `service.py`
  to avoid circular import — same pattern as `SessionReport`).
- `concepts_hit` / `concepts_missed` are `text[]` in Postgres; Supabase client returns them as
  Python `list[str]`. Use `r.get("concepts_hit") or []` to guard against `None` if the row
  predates the NOT NULL DEFAULT.
- Adding `.order("created_at")` before `.limit(50)` changes the mock chain in existing tests that
  test `get_session_report`. Two files need updating: `test_s3_47_formula_applied_signal_coverage.py`
  and `test_s3_46_ces_breakdown_redistribution.py` — the `n == 4` block.

## Dev Agent Record

### Completion Notes

Implemented 2026-08-18. No migration needed — all columns already exist in `teachback_attempts`
(initial schema `20260611000000_initial_schema.sql` lines 205–217). Frontend contract from Dev 2
handoff matched exactly: 7 fields, `None` for absent sessions, `created_at` ordering.
