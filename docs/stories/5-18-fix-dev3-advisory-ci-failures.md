# Story 5-18 — Fix Dev 3 Advisory CI Failures: Align Tests With Current Code State

**Sprint:** 5  
**Owner:** Dev 3  
**Branch:** sprint5/dev3-sprint5-batch (PR #267)  
**Created:** 2026-09-28  
**Status:** Review Complete — Approved for Merge

---

## Context

The advisory CI bucket (`tests/` with `continue-on-error: true`) has 37 pre-existing failures
owned by Dev 3. These are NOT regressions — they are drift between test fixtures/expectations
and production code changes that accumulated without being caught because advisory failures
don't block merge.

Root causes fall into six clusters:

| Cluster | Count | Root cause |
|---------|-------|------------|
| `test_teachback_endpoint.py` | 22 | `_build_supabase_tb` side_effect list order doesn't match `grade_teachback`'s call order after the R2 fix moved the count query before the lesson load |
| `test_intervention_event_persistence.py` | 2 | AC7 tests import `_get_distraction_count` which was intentionally removed by S3-53/D63 |
| `test_tutor_service.py` | 3 | `_settings_mock` hardcodes PRD §11 CES weights (0.35/0.20/0.12/0.08) but config.py was recalibrated (0.40/0.15/0.13/0.07); `_EXPECTED_CES` is computed at module load with calibrated weights, creating a mismatch |
| `test_env_example_consistency.py` | 1 | `.env.example` has old PRD §11 CES weights; config.py defaults now differ |
| `test_s3_42_ces_breakdown_accuracy.py` | 1 | Hardcoded absolute Windows path `D:/intern/…/router.py`; fails on Linux CI |
| `test_s2_48_teachback_detail.py` | 1 | Source-scan asserts `.limit(50)` but `get_session_report` was deliberately widened to `.limit(200)` after F2-2 added skip/fallback rows |

**Total: 30 failures addressed in this story.** The remaining 8 advisory failures belong to Dev 4
(`test_tutor_graph.py` 3 — fatigue guard broken; `test_lesson_ready_pubsub.py` 3 — real-Supabase
called, Dev 4 owns pubsub per CLAUDE.md §21) and Dev 1 (`test_llm_provider_smoke.py` 2 — no API
key on CI runner, Dev 1 owns LLM provider infra).

---

## Acceptance Criteria

### AC1 — Fix `_build_supabase_tb` mock order (22 failures)
The `grade_teachback` service call order after the R2 fix is:
1. `sessions` (ownership check)
2. `teachback_attempts` COUNT (moved before lesson load)
3. `lessons` (only for non-skip path)
4. `teachback_attempts` INSERT

`_build_supabase_tb` must return `[session_mock, count_mock, lesson_mock, insert_mock]` for the
non-skip path. Add `is_skip: bool = False` parameter; for skip path return
`[session_mock, count_mock, insert_mock]`.

After fix: all 22 functional teachback endpoint tests pass.

### AC2 — Remove orphaned AC7 `_get_distraction_count` tests (2 failures)
`_get_distraction_count` was removed by S3-53/D63 as dead code. A guard in
`test_s3_53_ces_production_closure.py` actively asserts it does not exist.

Delete these two test functions from `test_intervention_event_persistence.py`:
- `test_redis_miss_triggers_db_count_reconstruction`
- `test_redis_hit_skips_db_reconstruction`

After fix: no ImportError from `_get_distraction_count`.

### AC3 — Update `_settings_mock` CES weights (3 failures)
`_settings_mock` in `test_tutor_service.py` must use the calibrated config.py defaults:
- `ces_weight_quiz = 0.40`
- `ces_weight_teachback = 0.25`
- `ces_weight_behavioral = 0.15`
- `ces_weight_head_pose = 0.13`
- `ces_weight_blink = 0.07`

`_EXPECTED_CES` is computed at module load from real Settings (which uses calibrated defaults).
After the mock update, mock-computed CES == module-load CES. All three assertion-on-value tests
pass.

No hardcoded weight values anywhere else in `test_tutor_service.py`.

### AC4 — Update `.env.example` CES weights (1 failure)
`.env.example` must match config.py defaults. Update:
```
CES_WEIGHT_QUIZ=0.40
CES_WEIGHT_TEACHBACK=0.25
CES_WEIGHT_BEHAVIORAL=0.15
CES_WEIGHT_HEAD_POSE=0.13
CES_WEIGHT_BLINK=0.07
```

`test_env_example_consistency.py` uses this file to verify env-var examples match Settings defaults.

### AC5 — Fix hardcoded Windows path (1 failure)
`test_s3_42_ces_breakdown_accuracy.py` line ~364 reads the router source with a hardcoded
absolute path:
```python
pathlib.Path("D:/intern/transformED/transformED/apps/api/app/modules/assessment/router.py")
```

Replace with:
```python
pathlib.Path(__file__).resolve().parents[1] / "app" / "modules" / "assessment" / "router.py"
```

After fix: test runs on Linux CI without FileNotFoundError.

### AC6 — Fix source-scan limit assertion (1 failure)
`test_s2_48_teachback_detail.py` asserts `.limit(50)` is in `get_session_report` source.
The service was deliberately widened to `.limit(200)` after F2-2 added skip/fallback rows
(worst case ~45 rows per session, 200 provides a safe ceiling).

Update the assertion and mock comment to `.limit(200)`. No service code change.

### AC7 — CES lifecycle carries forward with no hardcoded values
`ces.py` reads weights from `settings.ces_weight_*` dynamically at call time. No weight value
is hardcoded in any module under `app/`. Any test that supplies weights must either use a real
`Settings` object (for formula-behavior tests) or a MagicMock with current defaults (for
integration-style unit tests).

### AC8 — Guard tests pass
All existing guard tests for Dev 3 modules still pass after this story:
- `tests/unit/test_ces_formula_guard.py` (if exists)
- `test_s3_53_ces_production_closure.py::test_get_distraction_count_removed`
- `tests/unit/test_node_return_shape.py`
- `tests/unit/test_unbounded_queries.py`

### AC9 — ruff format + check clean
All modified Python files pass `ruff format --check` and `ruff check` with zero errors.

### AC10 — CLAUDE.md CES formula synced to calibrated defaults
`CLAUDE.md` §11 CES formula updated from PRD placeholder weights (0.35/0.20/0.12/0.08) to
post-calibration defaults (0.40/0.15/0.13/0.07). Redistributed without-teachback formula
recalculated (0.533/0.200/0.173/0.093). Note added explaining the PRD values were pre-calibration
placeholders; `config.py` and `.env.example` are now the single source of truth.

---

## Scale & Load

1. **One unit of work:** One advisory test run (advisory bucket is not gating — no scale concern).
2. **Fixed budgets vs variable input:** N/A — this story only changes test fixtures and `.env.example`.
3. **Scope of every limit:** `.limit(200)` in `get_session_report` is per-session, per-call.
   Worst case: 15 segments × 3 row types (llm + fallback + skip) = 45 rows. 200 is the safety
   ceiling; a session cannot naturally produce more rows than this.
4. **Unbounded reads/writes:** None introduced.
5. **Inherited caps re-derived:** `.limit(50)` inherited from the original Story 2-48 AC before
   F2-2 added skip/fallback rows. Re-derived here: 45 rows worst case → `.limit(200)`.
6. **Check-then-act concurrency:** N/A — test-only changes.

---

## Implementation Notes

- All changes push to `sprint5/dev3-sprint5-batch` (PR #267).
- No production code changes except the `test_s2_48_teachback_detail.py` source-scan fix
  (which only updates a test assertion, not service code).
- `_get_distraction_count` removal was done by S3-53; this story only removes the orphaned tests.
