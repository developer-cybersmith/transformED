# Handoff: Dev 2 → Dev 3 — Teach-Back Summary Detail (Story 2-48 / S3-06)

**Date:** 2026-08-18
**From:** Dev 2 (frontend, lesson player, WebSocket client)
**To:** Dev 3 (Quiz API, teachback scorer, CES formula, Learner DNA, session reports, analytics)
**Story:** `docs/stories/2-48-teachback-summary-detail.md`
**Why a handoff instead of a direct PR:** earlier Sprint 3 stories (2-46) had Dev 2 extend this
same module directly with a cross-team review-flag comment. That precedent is no longer being
used — this is a clean request instead, per current team-boundary instruction (Dev 2 stays in
`apps/web`; backend changes go through Dev 3).

## What's needed

`GET /api/assessment/session/{session_id}/report` (`apps/api/app/modules/assessment/router.py`,
`SessionReport` model) needs one new, additive, nullable field: `teachback_details`.

The data already exists — `score_and_persist_teachback` (`service.py:671-685`) already writes
`feedback_praise`, `feedback_correction`, `concepts_hit`, `concepts_missed`, `segment_id`, and
`attempt_number` to `teachback_attempts` on every submission. `get_session_report`'s existing
Step 3 query (`service.py:916-923`) already reads this table but only selects `score`, collapsing
it into the session-wide `teachback_score` average. Nothing new needs to be persisted — this is
purely exposing columns that are already written.

## Exact spec (from Story 2-48, ACs 1-4)

1. **New Pydantic model** `TeachbackDetail` (put alongside `SessionReport` in `router.py`, same
   pattern as the existing model):
   ```python
   class TeachbackDetail(BaseModel):
       segment_id: str
       score: int
       feedback_praise: str | None
       feedback_correction: str | None
       concepts_hit: list[str]
       concepts_missed: list[str]
       attempt_number: int
   ```
   Field names/types match `teachback_attempts` verbatim
   (`supabase/migrations/20260611000000_initial_schema.sql:205-217`).

2. **`SessionReport` gains:** `teachback_details: list[TeachbackDetail] | None`.
   `None` (not `[]`) when the student did no teach-back this session — same convention as the
   existing `teachback_score: None` / `ces_timeline: None` fields.

3. **`get_session_report` Step 3** (`service.py:916-923`) — extend the *existing* query, do not
   add a second one:
   ```python
   tb_resp = await asyncio.to_thread(
       lambda: (
           supabase.table("teachback_attempts")
           .select(
               "segment_id, score, feedback_praise, feedback_correction, "
               "concepts_hit, concepts_missed, attempt_number"
           )
           .eq("session_id", session_id)
           .order("created_at")
           .limit(50)
           .execute()
       )
   )
   ```
   `.order("created_at")` is new — needed so `teachback_details` comes back in the
   chronological order segments were taught (the frontend labels entries "Segment 1", "Segment 2"
   by array position, never the raw `segment_id`). The existing `.limit(50)` safety ceiling and its
   BOUNDED comment (max 1 attempt per segment, no retry) are unchanged.

4. **No change** to `teachback_score`, `formula_applied`, `signal_coverage`, or the CES formula —
   this is additive only. A partially-null row (`feedback_praise`/`feedback_correction` both
   `None`, empty concept arrays — a real shape per the migration's nullable columns/`DEFAULT '{}'`)
   should pass through unchanged, no synthetic fallback text needed server-side.

## Frontend contract (already being implemented against this spec)

`apps/web/src/types/assessment.ts`'s `SessionReport` will get a matching `TeachbackDetail`
interface and `teachback_details: TeachbackDetail[] | null` field — TypeScript mirrors the Python
model field-for-field. Please flag if the shipped backend model ends up differing from the spec
above so the frontend type doesn't silently drift out of sync.

## Test note

`test_session_report_endpoint.py`'s `_build_report_supabase` mock builder will need its
`teachback_attempts` mock (call position 4) updated for the new `.select()`/`.order()` columns.
Story 2-46 hit exactly this kind of mock-shape mismatch when it added a new query; this change
only alters an *existing* call's arguments, so call-position indices should be unaffected — but
verify empirically rather than assuming.

## Reference

Full AC text, Scale & Load answers, and Dev Notes: `docs/stories/2-48-teachback-summary-detail.md`
(Task 1, AC-1 through AC-4).
