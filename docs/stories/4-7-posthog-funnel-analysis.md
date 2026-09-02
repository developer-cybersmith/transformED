---
status: in-progress
---

# Story 4-7 — PostHog Funnel Analysis: Where Do Students Drop Off?

**Sprint:** 4 · **Owner:** Dev 3  
**Branch:** `sprint4/s4-7-posthog-funnel-analysis`

## User Story

As the product team, I want to know at which funnel step the largest share of sessions drop off, with supporting data and two concrete hypotheses, so we can prioritise the highest-impact fix before Week 10 launch.

## Background

PostHog received **zero events** across all 117 sessions — `POSTHOG_API_KEY` was never set in the Railway production environment, so every `posthog_client.capture_event()` call silently skipped. The funnel is therefore reconstructed from relational tables: `sessions`, `quiz_attempts`, `teachback_attempts`. These tables are the authoritative source and produce equivalent funnel data.

**Funnel steps defined:**
1. **session_start** — a `sessions` row exists (`started_at IS NOT NULL`)
2. **quiz_submitted** — ≥1 row in `quiz_attempts` for that session
3. **teachback_submitted** — ≥1 row in `teachback_attempts` for that session
4. **session_end** — `sessions.ended_at IS NOT NULL`

## Acceptance Criteria

- **AC1:** Funnel step definitions documented with data source (relational tables) and reason PostHog was unavailable
- **AC2:** Drop-off count and percentage calculated at each of the 4 funnel transitions (start→quiz, quiz→teachback, teachback→end)
- **AC3:** The step with the highest drop-off rate identified and named
- **AC4:** Top 2 drop-off hypotheses documented with supporting evidence from the data
- **AC5:** Any secondary defects revealed by the analysis registered in `docs/DEFECT-REGISTER.md`
- **AC6:** Findings written to `docs/sprint4-funnel-analysis.md` with: data source, date range, sample size, caveats, funnel table, hypotheses
- **AC7:** `docs/dev3-assessment-tracker.md` updated — task marked done

## Scale & Load

1. **Unit of work:** One read-only SQL query over `sessions`, `quiz_attempts`, `teachback_attempts`. Row counts: 117 sessions, 55 quiz_attempts, ~2 teachback_attempts. Bounded at current data volume; trivially small.
2. **Fixed budgets while input varies:** Query is bounded by `LIMIT` clauses where used. Analysis document is static. No computation budget risk.
3. **Scope of each limit:** Per-project (entire Supabase instance). Read-only.
4. **Unbounded reads/writes:** The aggregate queries run over all rows — at 117 sessions this is negligible. For production scale (thousands of sessions) these should be indexed or paginated. `quiz_attempts.session_id` and `teachback_attempts.session_id` should be indexed. This is noted as a future concern, not a current blocker.
5. **Inherited caps re-derived:** N/A — no inherited limits apply to a one-time read-only analysis.
6. **Concurrent check-then-act:** N/A — read-only analysis with no writes.

## Tasks

- [x] T1: Create story file (this file), commit alone, push
- [ ] T2: Write `docs/sprint4-funnel-analysis.md` with full analysis
- [ ] T3: Register PostHog silent-drop defect in `docs/DEFECT-REGISTER.md`
- [ ] T4: Update `docs/dev3-assessment-tracker.md` — mark task done, update dashboard
- [ ] T5: Commit implementation, push, merge into `master-sprint4-dev3`

## Change Log

| Date | Author | Change |
|---|---|---|
| 2026-08-31 | Dev 3 | Story file created |
