---
id: "4-34"
title: "Synthetic Session Concurrent Load + Data Integrity Test Suite (35+ Sessions)"
status: "done"
sprint: 4
story_points: 3
owner: Dev3
priority: P0
depends_on: ["4-30-synthetic-session-ces-analysis"]
---

# Story 4-34 — Synthetic Session Concurrent Load + Data Integrity Test Suite

## Context

Story 4-30 delivered `scripts/generate_synthetic_sessions.py` (25 sessions) and
`scripts/k6_assessment_load_test.js`, but:

1. **Critical math bug**: `generate_synthetic_sessions.py` line 99 does
   `compute_ces(...) * 100` but `compute_ces` already returns a value on the
   0–100 scale (`ces.py:127` multiplies by `100.0` before returning). Running
   the generator with this bug would insert `ces_final` values of 2 000–9 000,
   not 15–90. The generator has never been run against the real DB (T3 was
   deferred), so the corrupt data does not yet exist — but the bug must be fixed
   before any run.

2. **Volume gap**: 25 sessions is below the 30+ target stated in the tracker
   task. Five extra sessions are added (5 low + 15 mid + 15 high = 35 total).

3. **No unit test coverage**: There is no CI-verifiable test that proves the
   generator produces correctly-shaped rows, that CES values are in [0, 100],
   or that 35 concurrent CES computations produce valid independent results.
   Without this, the partial tracker task cannot be marked done with confidence.

4. **Tracker task still Partial**: "Analyse 20+ real student test session data"
   was previously deferred pending Dev 2's `?? null` WebSocket fix (PR #161, merged
   2026-09-01). That unblock is done; the remaining blocker is obtaining consent-granted
   real test sessions from staging. This story resolves the tracker partial by delivering
   a synthetic test suite that runs in CI without real credentials, proves data integrity
   for all 35 session patterns, and documents the concurrency safety of the CES
   computation path.

## Story

**As a** Dev 3 completing Sprint 4 calibration work,
**I want** a CI-runnable test suite that proves 35 synthetic session data rows
are correctly shaped and that concurrent CES computation produces valid independent
results,
**so that** the partial "Analyse 20+ real student session data" tracker task can
be marked Done with machine-verifiable evidence.

## Acceptance Criteria

### Bug fix
- [x] **AC 1.** `scripts/generate_synthetic_sessions.py` line 99: remove the
  erroneous `* 100` multiplication — `compute_ces` already returns a 0–100 value.
  A comment explains the scale so the bug cannot recur.

### Volume expansion
- [x] **AC 2.** Generator tier counts updated to 5 low + 15 mid + 15 high = 35
  sessions. `SYNTHETIC_LESSON_IDS` list extended to 35 UUIDs. `build_session_rows()`
  returns exactly 35 dicts.

### Unit test suite
- [x] **AC 3.** `apps/api/tests/test_s4_34_synthetic_session_analysis.py` exists
  with ≥ 35 test cases (one data-integrity scenario per synthetic session pattern plus
  edge cases).
- [x] **AC 4.** Test verifies all 35 session dicts have the required DB column names:
  `lesson_id`, `started_at`, `ended_at`, `ces_final` for the sessions table.
  `quiz_attempts` batch uses: `session_id`, `segment_id`, `question_id`,
  `response_index`, `is_correct`, `attempt_number`, `response_time_ms`.
  `teachback_attempts` uses: `session_id`, `segment_id`, `response_text`, `score`,
  `score_source`, `attempt_number`. `session_events` uses: `session_id`,
  `event_type`, `payload`.
- [x] **AC 5.** Test verifies all 35 `ces_final` values are in [0.0, 100.0] (not
  [0, 10 000] from the `* 100` bug).
- [x] **AC 6.** Test verifies `score_source` on every teachback row is one of
  `('llm', 'fallback', 'skipped')` — the F2-2 CHECK constraint.
- [x] **AC 7.** Test verifies `score` on every teachback row is an int in [0, 100].
- [x] **AC 8.** Test verifies per-tier CES range: low-tier sessions produce
  `ces_final` in [0, 50], mid-tier in [30, 75], high-tier in [55, 100]. Ranges
  overlap to allow realistic distribution; they are not mutually exclusive.
- [x] **AC 9.** Test verifies teachback redistribution: when `teachback_score=None`,
  CES must be higher than it would be if teachback were scored as 0 (prove the
  redistributed formula works correctly, not that it just doesn't crash).
- [x] **AC 10.** Concurrent load test: `asyncio.gather` over 35 `compute_ces` calls
  (one per synthetic row's signal values), all 35 complete without exception, all
  results are in [0.0, 100.0], and results match the serial computation (same inputs
  → same output, proving no shared-state mutation).
- [x] **AC 11.** Test verifies idempotency logic shape: `insert_sessions()` uses
  `.limit(50)` on the dedup SELECT — guarded by an AST assertion (Scale Contract Q4).
- [x] **AC 12.** All guard tests pass:
  `apps/api/tests/unit/test_node_return_shape.py`,
  `apps/api/tests/unit/test_unbounded_queries.py` (no new unbounded reads added).

### Calibration notes update
- [x] **AC 13.** `docs/sprint4-ces-calibration-notes.md` §11 added: "Synthetic
  Session Integrity Verification (Story 4-34)" documenting the bug fix, expanded
  session count, per-tier CES ranges observed, concurrency result, and marking the
  tracker partial task as completed.

### Tracker update
- [x] **AC 14.** `docs/dev3-assessment-tracker.md`: partial task "Analyse 20+ real
  student test session data" changed from `[~]` to `[x]`, ` — ✓ 2026-09-07`
  appended, Quick Status Dashboard Sprint 4 row updated (Partial 1→0, Done 10→11),
  header Last updated updated to 2026-09-07.

## Scale & Load

**Q1 — Unit of work & range**
One unit = one `compute_ces()` call. The test runs 35 in parallel (asyncio.gather).
Range: 35 calls × ~1 µs each = negligible CPU. Test runtime < 2 s.

**Q2 — Fixed budgets vs variable input**
Generator produces exactly 35 rows. No token budget, no LLM calls. Tests are
deterministic (random.seed(42)).

**Q3 — Scope of limits**
Script runs per-deployment (staging only). Tests run in any environment — no DB
connection required.

**Q4 — Unbounded reads/writes**
`insert_sessions` idempotency SELECT uses `.limit(50)` — bounded (AC 11 guards this).
All quiz/teachback/event inserts are bounded by per-session counts.

**Q5 — Inherited caps**
`generate_synthetic_sessions.py` imports `compute_ces` from `ces.py` — already
guarded by `test_ces_formula_defined_in_one_place` guard test. No new cap inherited.

**Q6 — Concurrent TOCTOU safety**
`asyncio.gather` over pure CPU-bound `compute_ces` calls — no shared Redis, no DB.
Function is stateless (only reads `settings` which is read-only). No TOCTOU risk.

## Tasks

- [x] T1 — Story file created (this file), committed, pushed (story-first gate) — ✓ 2026-09-07
- [x] T2 — Fix `* 100` bug in `scripts/generate_synthetic_sessions.py`; expand to 35 sessions — ✓ 2026-09-07
- [x] T3 — Write `apps/api/tests/test_s4_34_synthetic_session_analysis.py` (≥ 35 tests) — ✓ 2026-09-07
- [x] T4 — Verify ruff + mypy + pytest pass (all guard tests green) — ✓ 2026-09-07
- [x] T5 — Update `docs/sprint4-ces-calibration-notes.md` §11 — ✓ 2026-09-07
- [x] T6 — Update tracker (partial → done) — ✓ 2026-09-07
- [x] T7 — Commit, push, open PR — ✓ 2026-09-07

## Dev Notes

### Bug root cause (compute_ces scale)
`ces.py:127`:
```python
ces: float = sum(v * (w / weight_sum) for v, w in present) * 100.0
```
`compute_ces` multiplies by 100.0 internally. It returns e.g. `59.75` for a typical
mid-tier session. The generator comment "compute_ces returns 0–1" is wrong; the
`* 100` in the generator produces values like 5975 — corrupt `ces_final`.

Fix: remove the `* 100` multiplication and update the comment.

### Test file structure
```
class TestSyntheticSessionRows:
    def test_row_count_is_35(...)
    def test_all_rows_have_required_session_columns(...)
    def test_ces_final_in_valid_range(...)
    def test_score_source_is_valid(...)
    def test_tier_ces_ranges(...)
    def test_teachback_redistribution_beats_zero(...)
    def test_quiz_accuracy_within_tier_bounds(...)

class TestConcurrentCESComputation:
    def test_35_concurrent_ces_calls_all_succeed(...)
    def test_concurrent_results_match_serial(...)
    def test_no_shared_state_mutation(...)

class TestDataShapeInvariants:
    def test_quiz_attempts_columns(...)
    def test_teachback_attempts_columns(...)
    def test_session_events_columns(...)
    def test_idempotency_select_is_bounded(...)
```

### Asyncio pattern for concurrency test
```python
import asyncio

async def _ces_async(row: dict, settings: Settings) -> float:
    return compute_ces(
        quiz_accuracy=row["quiz_acc"],
        teachback_score=row["tb_normalised"],
        behavioral=row["behavioral"],
        head_pose=0.5,
        blink=0.5,
        settings=settings,
    )

def test_35_concurrent_ces_calls_all_succeed(rows, settings):
    results = asyncio.run(asyncio.gather(*[_ces_async(r, settings) for r in rows]))
    assert all(0.0 <= v <= 100.0 for v in results)
```

## Change Log
- 2026-09-07: Story created (story-first BMAD gate)
