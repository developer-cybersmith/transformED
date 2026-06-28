---
baseline_commit: 617faa5a6a7b60db1a6e87b1f0d7dbee9a764fd8
---

# Story 3.3: DB Tables — onboarding_responses and session_events

Status: done

---

## Story

As Dev 3 (tannmayygupta),
I want the `onboarding_responses` and `session_events` tables created in Supabase with correct columns, constraints, RLS, and indexes,
so that onboarding diagnostic data and real-time session events can be stored securely per student, enabling the Learner DNA pipeline and CES computation in later sprints.

---

## Acceptance Criteria

1. Table `onboarding_responses` exists in migration `20260611000000_initial_schema.sql`.
2. `onboarding_responses` has column `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`.
3. `onboarding_responses` has column `user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE`.
4. `onboarding_responses` has column `question_id TEXT NOT NULL`.
5. `onboarding_responses` has column `response_value INTEGER NOT NULL` (stores the selected index).
6. `onboarding_responses` has column `response_time_ms INTEGER` (nullable — optional, used in behavioral analytics).
7. `onboarding_responses` has column `dimension_tag TEXT NOT NULL` with a CHECK constraint restricting values to `'cognitive'`, `'emotional'`, `'self_direction'`.
8. `onboarding_responses` has column `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`.
9. RLS is enabled on `onboarding_responses` and policies allow users to SELECT/INSERT/UPDATE/DELETE only their own rows (`user_id = auth.uid()`).
10. Table `session_events` exists in migration `20260611000000_initial_schema.sql`.
11. `session_events` has column `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`.
12. `session_events` has column `session_id UUID NOT NULL REFERENCES public.sessions(session_id) ON DELETE CASCADE`.
13. `session_events` has column `event_type TEXT NOT NULL`.
14. `session_events` has column `payload JSONB NOT NULL DEFAULT '{}'` — NOT NULL with empty-object default prevents null payload queries.
15. `session_events` has column `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`.
16. RLS is enabled on `session_events` and policies allow users to SELECT/INSERT/UPDATE/DELETE only rows belonging to their own sessions (joined via `sessions.user_id = auth.uid()`).
17. Index exists on `onboarding_responses(user_id)` for query performance.
18. Index exists on `session_events(session_id)` for query performance.
19. Index exists on `session_events(event_type)` for filtering by event type.

---

## Tasks / Subtasks

- [x] Task 1: Design onboarding_responses schema (AC: #1–#9) — ✓ 2026-06-17
  - [x] 1.1 Define column list: id, user_id, question_id, response_value, response_time_ms, dimension_tag, created_at
  - [x] 1.2 Define CHECK constraint on dimension_tag with values cognitive, emotional, self_direction
  - [x] 1.3 Define FK user_id → public.users(id) ON DELETE CASCADE
  - [x] 1.4 Write SQL CREATE TABLE statement in migration file

- [x] Task 2: Design session_events schema (AC: #10–#16) — ✓ 2026-06-17
  - [x] 2.1 Define column list: id, session_id, event_type, payload, created_at
  - [x] 2.2 Define payload as JSONB NOT NULL DEFAULT '{}' — flexible event schema, never null
  - [x] 2.3 Define FK session_id → public.sessions(session_id) ON DELETE CASCADE
  - [x] 2.4 Write SQL CREATE TABLE statement in migration file

- [x] Task 3: RLS setup for both tables (AC: #9, #16) — ✓ 2026-06-17
  - [x] 3.1 ALTER TABLE onboarding_responses ENABLE ROW LEVEL SECURITY
  - [x] 3.2 Create 4 RLS policies for onboarding_responses (SELECT/INSERT/UPDATE/DELETE) scoped to user_id = auth.uid()
  - [x] 3.3 ALTER TABLE session_events ENABLE ROW LEVEL SECURITY
  - [x] 3.4 Create 4 RLS policies for session_events (SELECT/INSERT/UPDATE/DELETE) scoped via sessions.user_id = auth.uid()

- [x] Task 4: Indexes (AC: #17–#19) — ✓ 2026-06-17
  - [x] 4.1 CREATE INDEX ON public.onboarding_responses(user_id)
  - [x] 4.2 CREATE INDEX ON public.session_events(session_id)
  - [x] 4.3 CREATE INDEX ON public.session_events(event_type)

- [x] Task 5: Apply migration to Supabase — ✓ 2026-06-17
  - [x] 5.1 Run supabase db push (or equivalent) to apply 20260611000000_initial_schema.sql
  - [x] 5.2 Confirm migration applied without errors

---

## Dev Notes

### Why dimension_tag Uses a CHECK Constraint

The onboarding questionnaire is scored across exactly 3 domains: `cognitive`, `emotional`, `self_direction`. Using a CHECK constraint instead of a foreign key to a lookup table keeps the schema self-contained and prevents invalid domain tags from being inserted at the DB level without requiring a join. This aligns with Epic 3's Learner DNA fusion formula which weights the three domains independently.

### Why payload Is JSONB NOT NULL DEFAULT '{}'

Session events have heterogeneous structures — a quiz start event has different fields than a teach-back submit or a distraction intervention. JSONB accommodates this without schema migration on every new event type. The `NOT NULL DEFAULT '{}'` combination is deliberate: application code can always safely access `payload` fields without a null check, and `WHERE payload @> '{"key": "value"}'` queries work without additional null guards. A nullable JSONB would require `IS NOT NULL` guards throughout analytics queries.

### Why session_events FK Uses ON DELETE CASCADE

If a session is deleted, all its events become meaningless and should be cleaned up automatically. CASCADE prevents orphaned rows that would silently inflate analytics aggregates.

### RLS Pattern — session_events Joins Through sessions

`session_events` does not have a `user_id` column directly. The RLS policy joins to `public.sessions` to resolve ownership:
```sql
EXISTS (
  SELECT 1 FROM public.sessions s
  WHERE s.session_id = session_events.session_id
    AND s.user_id = auth.uid()
)
```
This is the correct pattern for child tables that are owned transitively through a parent.

### Missing UNIQUE Constraint on onboarding_responses

The migration does NOT include a UNIQUE constraint on `(user_id, question_id)`. This means duplicate answers for the same question are technically allowed at the DB level. Application logic must deduplicate or prevent re-submission. A future migration should add `UNIQUE (user_id, question_id)` to enforce this at the DB level. Severity: **medium** (noted as code review finding).

### Redis Key Patterns (for reference)

The migration documents the relevant Redis key:
- `user:{user_id}:onboarding_done → "1"` once onboarding is complete
- `session:{session_id}:events → list` of serialized session_event payloads (buffered before DB flush)

---

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6 (story retroactively documented 2026-06-26)

### Debug Log References

- Migration was originally written and applied on 2026-06-17 as part of Sprint 0 initial schema.
- BMAD documentation retroactively applied on 2026-06-26.
- Code review identified one medium-severity finding: missing UNIQUE(user_id, question_id) on onboarding_responses.
- All schema tests pass (7/7 unit tests green).

### Completion Notes List

- Migration `20260611000000_initial_schema.sql` contains both tables, confirmed by reading lines 247–269.
- dimension_tag CHECK constraint confirmed: `CHECK (dimension_tag IN ('cognitive', 'emotional', 'self_direction'))` at line 254.
- JSONB payload confirmed with `NOT NULL DEFAULT '{}'` at line 267.
- RLS enabled for both tables at lines 333–334 (ALTER TABLE statements).
- RLS policies for onboarding_responses at lines 726–741 (4 policies).
- RLS policies for session_events at lines 749–787 (4 policies, joins through sessions).
- Index on onboarding_responses(user_id) at line 304.
- Index on session_events(session_id) at line 305.
- Index on session_events(event_type) at line 313.
- FK constraints both use ON DELETE CASCADE.
- Missing: UNIQUE(user_id, question_id) constraint — noted as medium finding, requires future migration.

### File List

- `supabase/migrations/20260611000000_initial_schema.sql` — READ-ONLY (applied, never modified). Contains onboarding_responses (lines 247–256) and session_events (lines 263–269).
- `apps/api/tests/test_migration_analytics_schema.py` — CREATED: 7 unit tests verifying schema contents.

---

## Senior Developer Review

Status: Approved

Review notes:
- Schema design is sound. JSONB payload with NOT NULL DEFAULT '{}' is the correct choice for heterogeneous event data.
- dimension_tag CHECK constraint correctly enforces domain values at DB level.
- RLS policies follow established pattern (join-through for child tables, direct user_id for owned tables).
- Indexes on all FK columns and on event_type are appropriate for anticipated query patterns.
- Code review finding acknowledged: missing UNIQUE(user_id, question_id) on onboarding_responses is a medium-severity gap. Must be addressed in a new migration (not this one — this migration is frozen).
- Schema verification tests provide a regression safety net against future accidental migration edits.
