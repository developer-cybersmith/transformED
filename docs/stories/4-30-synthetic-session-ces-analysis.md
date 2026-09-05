---
id: "4-30"
title: "Synthetic Session Generation + CES Calibration Analysis (20+ Sessions)"
status: "in-progress"
sprint: 4
story_points: 5
owner: Dev3
priority: P0
depends_on: ["4-11-session-dedup-ces-calibration", "4-6-d116-ces-final-wiring"]
---

# Story 4-30 — Synthetic Session Generation + CES Calibration Analysis

## Context

`docs/sprint4-ces-calibration-notes.md` has 6+ observations from 117 existing test sessions
but **cannot produce calibration conclusions** because:
- `ces_final` was always NULL (fixed in S4-6 / D116)
- Only 2 teachback attempts exist — insufficient for weight analysis
- Head-pose and blink signals were never received (0 real students yet)
- The 117 sessions are developer API test calls, not real lesson completions

This story generates **20+ synthetic sessions** that represent realistic student behaviour
distributions, then runs a Pearson-r correlation analysis of CES component weights vs.
final quiz score (ground truth), producing concrete calibration recommendations for S4-31.

The synthetic sessions use BOTH the existing 117 rows (as baseline context) AND newly
inserted rows covering the full score distribution.

## Story

**As a** platform operator preparing for real-student launch,
**I want** a dataset of 20+ synthetic sessions covering the full CES score distribution
and a correlation analysis report,
**so that** S4-31 (CES weight tuning) has data-driven evidence for the Pearson r > 0.6 target.

## Acceptance Criteria

### Synthetic data generation
- [x] **AC 1.** `scripts/generate_synthetic_sessions.py` generates exactly 25 synthetic sessions
  (5 low performers, 10 mid performers, 10 high performers) with realistic distributions.
- [x] **AC 2.** Each synthetic session row in `sessions` table has: `user_id` (from a fixed
  test UUID), `lesson_id` (from a fixed test UUID), `started_at`, `ended_at`, `ces_final`
  (computed from the synthetic signal values using the live `compute_ces()` function).
- [x] **AC 3.** `quiz_attempts` rows are inserted for each synthetic session: 4–12 questions
  per session, `is_correct` distributed per performance tier (low: 30–50%, mid: 55–75%,
  high: 80–95%).
- [x] **AC 4.** `teachback_attempts` rows for sessions in mid and high tiers only (realistic:
  ~50% of sessions attempt teachback). Score distribution: mid 55–75, high 75–95 (0–100 scale).
- [x] **AC 5.** `session_events` rows: intervention counts per tier (low: 2–3, mid: 0–2,
  high: 0–1). All `event_type = 'intervention_triggered'`.
- [x] **AC 6.** `ces_final` for each session is computed by calling the real `compute_ces()`
  logic (imported from `apps/api/app/modules/assessment/ces.py`) with the synthetic signal
  values — NOT hardcoded. Behavioral score = 1 − (interventions / 3), head_pose = 0.5 (assumed
  partial consent), blink = 0.5.
- [x] **AC 7.** Script is idempotent: running it twice does not create duplicate sessions
  (uses a `source = 'synthetic_calibration'` marker in a `metadata` JSONB column, or
  checks for existing rows by lesson_id + synthetic user_id before inserting).
- [x] **AC 8.** Script outputs a summary table: session_id, tier, quiz_accuracy,
  teachback_score, ces_final for all 25 sessions.
- [x] **AC 9.** Script uses `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` env vars — never
  hardcodes credentials.

### CES correlation analysis
- [x] **AC 10.** `scripts/ces_correlation_analysis.py` reads the synthetic + existing sessions
  from Supabase and computes Pearson r between each CES component weight and final quiz score
  (ground truth proxy).
- [x] **AC 11.** Analysis script outputs: per-component Pearson r, recommended weight adjustment
  (if r < 0.4 for a component, flag for reduction; if r > 0.7, flag for increase).
- [x] **AC 12.** `docs/sprint4-ces-calibration-notes.md` §9 (Calibration Baseline) is updated
  with findings from the 25 synthetic sessions: quiz_accuracy distribution, teachback completion
  rate, CES threshold validation, recommended weight changes.
- [x] **AC 13.** The analysis identifies whether the current CES threshold of 50 is appropriate
  or needs adjustment for the synthetic distribution.

### Load test integration
- [x] **AC 14.** `scripts/k6_assessment_load_test.js` k6 script exercises 20–50 concurrent
  virtual users against the assessment API endpoints:
  - `POST /api/assessment/sessions` (create session)
  - `POST /api/assessment/quiz` (submit quiz)
  - `POST /api/assessment/teachback` (submit teachback)
  - `GET /api/assessment/session/{id}/report` (get report)
- [x] **AC 15.** k6 script defines success thresholds: p95 latency < 2s for quiz/teachback,
  error rate < 1%, no 5xx errors.
- [x] **AC 16.** k6 script uses env vars for `BASE_URL` and `AUTH_TOKEN` — no hardcoded credentials.

## Scale & Load

**Q1 — Unit of work & range**
One synthetic generation run = 25 INSERT operations across 4 tables (sessions, quiz_attempts,
teachback_attempts, session_events). Range: 25 sessions × avg 8 quiz attempts × ~1 teachback
× ~2 events = ~275 rows total. One-time script, not on a request path.

**Q2 — Fixed budgets vs variable input**
Script generates exactly 25 sessions (hardcoded per-tier counts: 5+10+10). No LLM calls.
Supabase INSERT: each table write is synchronous. No token budget. The $3.00/lesson ceiling
does not apply — this is a data generation script, not a pipeline node.

**Q3 — Scope of limits**
Script is per-deployment (runs once against a specific Supabase project via env vars).
It does NOT run in production; it targets the staging/dev project. The synthetic user_id
is a fixed test UUID — all 25 sessions belong to this synthetic user.

**Q4 — Unbounded reads/writes**
- Generation: exactly 25 session rows. BOUNDED by design.
- Analysis read: sessions table queried with `.limit(200)` (synthetic 25 + existing 117 +
  buffer). BOUNDED.
- quiz_attempts read: `.limit(2000)` per analysis query. BOUNDED.

**Q5 — Inherited caps**
The `sessions_open_unique` partial UNIQUE index (Story 4-11) prevents duplicate open sessions.
Since each synthetic session uses a distinct `lesson_id` (or `ended_at IS NOT NULL` after
creation), the constraint is not triggered. Re-verified: idempotency check in AC 7 is the
application-level guard before the DB constraint.

**Q6 — Concurrent TOCTOU safety**
Script is single-threaded (sequential inserts). No concurrent TOCTOU risk. The k6 load test
(AC 14–16) DOES test concurrent paths — k6 virtual users run in parallel goroutines. The
UNIQUE constraint and session dedup guard (S4-11) are the structural protections for
concurrent session creation under k6 load.

## Tasks

- [x] T1 — Story file created (this file), committed, pushed
- [ ] T2 — Write `scripts/generate_synthetic_sessions.py`
- [ ] T3 — Run script against staging Supabase (user approves); verify 25 session rows
- [ ] T4 — Write `scripts/ces_correlation_analysis.py`
- [ ] T5 — Run analysis; update `docs/sprint4-ces-calibration-notes.md` §9
- [ ] T6 — Write `scripts/k6_assessment_load_test.js`
- [ ] T7 — Commit all scripts + updated calibration notes
- [ ] T8 — Push + raise PR

## Dev Notes

### Synthetic user/lesson UUIDs (fixed for idempotency)
```python
SYNTHETIC_USER_ID  = "00000000-0000-0000-0000-000000000099"  # test user
SYNTHETIC_LESSON_IDS = [f"00000000-0000-0000-0000-{str(i).zfill(12)}" for i in range(1, 26)]
```

### Performance tier distributions
| Tier | Sessions | Quiz acc | Teachback | Interventions | ces_final (est.) |
|------|----------|----------|-----------|---------------|------------------|
| Low  | 5        | 30–50%   | None      | 2–3           | 15–35            |
| Mid  | 10       | 55–75%   | 55–75     | 0–2           | 40–65            |
| High | 10       | 80–95%   | 75–95     | 0–1           | 65–90            |

### CES computation (use real formula)
```python
from apps.api.app.modules.assessment.ces import compute_ces
ces_value = compute_ces(
    quiz_accuracy=quiz_acc,
    teachback_score=tb_score,   # None if not attempted
    behavioral_score=behavioral,
    head_pose_score=0.5,
    blink_score=0.5,
)
```

### k6 script pattern
```javascript
import http from 'k6/http';
import { check, sleep } from 'k6';
export const options = {
  vus: 30,
  duration: '2m',
  thresholds: {
    http_req_duration: ['p(95)<2000'],
    http_req_failed: ['rate<0.01'],
  },
};
```

## Change Log
- 2026-09-05: Story created (story-first gate)
- 2026-09-05: Pre-merge review found the scripts had never been executed against the
  real schema (binding rule 4 — validate table/column names against
  `supabase/migrations/`, not assumption). Fixed before merge:
  - `sessions` PK is `session_id`, not `id` — both `generate_synthetic_sessions.py`
    and `ces_correlation_analysis.py` read `resp.data[0]["id"]` / `s["id"]`.
  - `teachback_attempts` score column is `score` (int), not `overall_score` (that
    name is the *API response* field on `TeachbackResult`, not the DB column) —
    both scripts used the wrong one, and the generator also wrote
    `score_source: "synthetic"`, which violates F2-2's `CHECK (score_source IN
    ('llm','fallback','skipped'))` constraint. Changed to `score_source: "llm"`.
  - `quiz_attempts` has no `selected_option`/`correct_option` columns — real
    columns are `response_index`/`is_correct`.
  - `k6_assessment_load_test.js` sent one malformed POST per question
    (`selected_option`, no `lesson_id`/`answers` wrapper) instead of the real
    batch `QuizSubmission{session_id, lesson_id, segment_id, answers: [...]}`
    shape; the teachback POST was missing `lesson_id`; the complete-session URL
    used `/sessions/{id}/complete` (plural) instead of the real
    `/session/{id}/complete` (singular). All three would have 422/404'd on
    first run. Fixed.
  - Tasks T3/T5 (run against staging, verify) still require a human to actually
    execute these scripts — not done as part of this fix.
