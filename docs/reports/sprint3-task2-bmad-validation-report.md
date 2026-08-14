# BMAD Post-Implementation Audit — Validation Report
## Sprint 3 Task 2: CES Baseline Computation (Story 3-24)

**Report date:** 2026-08-04
**Branch:** `sprint3-task2-dev3`
**Story:** `docs/stories/3-24-ces-baseline-computation.md`
**Implementation file:** `apps/api/app/modules/assessment/ces_baseline.py`
**Test file:** `apps/api/tests/test_ces_baseline.py`
**Reporter:** Dev 3 adversarial audit

---

## Executive Summary

Sprint 3 Task 2 implements `compute_and_store_ces_baseline()` — an async function that reads a
user's last N completed sessions' CES finals from Supabase, computes a rolling average, and caches
the result in Redis under `user:{user_id}:ces_baseline`.

The initial implementation (committed 2026-07-03) passed all 19 ACs with 25 tests and a full
5-agent adversarial review. This post-implementation audit identified 3 non-blocking gaps in test
coverage and documentation quality. All 3 were verified against the actual codebase, fixed, and
re-validated. **No production logic was changed.** The implementation was already correct.

**Final verdict: PRODUCTION-READY — 100% implemented, 27/27 tests pass, 0 regressions.**

---

## Issues Found (Pre-Remediation)

### Issue 1 — AC 3: Async nature not explicitly asserted (MEDIUM)

| Field | Detail |
|-------|--------|
| **AC** | AC 3: all parameters keyword-only; function is async |
| **File** | `apps/api/tests/test_ces_baseline.py` |
| **Test** | `test_positional_args_raise_type_error` |
| **Gap** | Test verified keyword-only constraint via `TypeError` on positional call but never asserted `inspect.iscoroutinefunction(func) == True`. An accidental revert of `async def` to `def` would pass all 25 tests silently. Dev 4 awaits this function in the WebSocket handler — a sync function would deadlock the event loop. |
| **Risk** | Silent regression: sync function would deadlock Dev 4's WebSocket handler |

**Before:**
```python
async def test_positional_args_raise_type_error():
    """AC 3: All parameters are keyword-only."""
    with pytest.raises(TypeError):
        await func("user-1", MagicMock(), AsyncMock(), _settings())
```

**After:**
```python
async def test_positional_args_raise_type_error():
    """AC 3: All parameters are keyword-only and the function is async (awaitable).
    Explicitly asserts iscoroutinefunction so a future accidental `def` → `async def`
    revert is caught immediately rather than via an obscure downstream failure.
    Dev 4 awaits this function in the WebSocket handler — sync would deadlock.
    """
    import inspect
    func = _import_func()
    assert inspect.iscoroutinefunction(func), (
        "compute_and_store_ces_baseline must be async — Dev 4 awaits it in the WebSocket handler"
    )
    with pytest.raises(TypeError):
        await func("user-1", MagicMock(), AsyncMock(), _settings())
```

---

### Issue 2 — ACs 11/12: Settings field constraints never explicitly tested (MEDIUM)

| Field | Detail |
|-------|--------|
| **ACs** | AC 11: `ces_baseline_window = Field(default=5, ge=1, le=50)`; AC 12: `ces_baseline_ttl_seconds = Field(default=86400, ge=60)` |
| **File** | `apps/api/tests/test_ces_baseline.py` |
| **Gap** | The `_settings()` factory in tests only exercised the happy path (valid values). No test ever passed `window=0`, `window=51`, or `ttl=59` to confirm `pydantic.ValidationError` is raised. The constraints in `config.py` existed and were correct, but they lacked any test that would catch a regression (e.g., `ge=1` being changed to `ge=0`). |
| **Risk** | A silent relaxation of the Field constraints would not be caught by the test suite |

**New test added — AC 11:**
```python
@pytest.mark.unit
def test_config_ces_baseline_window_default_and_constraints():
    """AC 11: Settings.ces_baseline_window = Field(default=5, ge=1, le=50)."""
    import pydantic
    s = _settings()
    assert s.ces_baseline_window == 5, "default window must be 5"
    assert _settings(window=1).ces_baseline_window == 1, "lower bound 1 must be accepted"
    assert _settings(window=50).ces_baseline_window == 50, "upper bound 50 must be accepted"
    with pytest.raises(pydantic.ValidationError):
        _settings(window=0)  # violates ge=1
    with pytest.raises(pydantic.ValidationError):
        _settings(window=51)  # violates le=50
```

**New test added — AC 12:**
```python
@pytest.mark.unit
def test_config_ces_baseline_ttl_default_and_constraints():
    """AC 12: Settings.ces_baseline_ttl_seconds = Field(default=86400, ge=60)."""
    import pydantic
    s = _settings()
    assert s.ces_baseline_ttl_seconds == 86400, "default TTL must be 86400 (24 h)"
    assert _settings(ttl=60).ces_baseline_ttl_seconds == 60, "lower bound 60 s must be accepted"
    assert _settings(ttl=3600).ces_baseline_ttl_seconds == 3600, "arbitrary valid TTL accepted"
    with pytest.raises(pydantic.ValidationError):
        _settings(ttl=59)  # violates ge=60
```

---

### Issue 3 — Coverage header: AC 19 label wrong, AC 11/12 entries missing (LOW)

| Field | Detail |
|-------|--------|
| **File** | `apps/api/tests/test_ces_baseline.py` (header comment block) |
| **Gap 3a** | AC 19 entry read: "Redis.set NOT called when baseline is None" — this describes AC 8 behavior (`test_async_no_redis_write_when_no_sessions`). AC 19 is "≥15 `@pytest.mark.unit` tests all pass; 0 regressions in full suite." |
| **Gap 3b** | AC 11 and AC 12 had no header entries despite being tested via `_settings()` |
| **Risk** | Misleading coverage map: a reviewer tracing AC 19 finds the wrong test |

**Before:**
```
# AC 3: keyword-only parameters
# ...
# AC 19: Redis.set NOT called when baseline is None
```

**After:**
```
# AC 3: keyword-only async signature; iscoroutinefunction asserted explicitly
# ...
# AC 11: ces_baseline_window = Field(default=5, ge=1, le=50) in Settings
# AC 12: ces_baseline_ttl_seconds = Field(default=86400, ge=60) in Settings
# ...
# AC 19: ≥15 @pytest.mark.unit tests all pass; 0 regressions in full suite
```

---

## Before / After Comparison

| Metric | Before (2026-07-03) | After (2026-08-04) |
|--------|---------------------|--------------------|
| Test count | 25 | **27** |
| AC 3 async assertion | No (keyword-only only) | **Yes — `iscoroutinefunction` asserted** |
| AC 11 dedicated test | No | **Yes** |
| AC 12 dedicated test | No | **Yes** |
| AC 19 coverage label | Wrong (described AC 8) | **Correct** |
| AC 11/12 header entries | Missing | **Present** |
| Ruff lint errors | 0 | 0 |
| Production logic changes | — | None |

---

## AC-by-AC Compliance Table

| AC | Description | Test(s) | Status |
|----|-------------|---------|--------|
| AC 1 | `compute_and_store_ces_baseline` exported in `__all__` | `test_dunder_all_exports_only_compute_and_store` | ✅ |
| AC 2 | Redis key pattern `user:{user_id}:ces_baseline` | `test_redis_key_format` | ✅ |
| AC 3 | Keyword-only params; function is async | `test_positional_args_raise_type_error` (strengthened) | ✅ |
| AC 4 | Single session baseline = that session's CES | `test_compute_baseline_single_score`, `test_async_single_session_baseline` | ✅ |
| AC 5 | Fewer sessions than window = average of available | `test_compute_baseline_fewer_than_window` | ✅ |
| AC 6 | Exactly window sessions = average of all | `test_compute_baseline_exactly_window`, `test_async_rolling_window_uses_most_recent` | ✅ |
| AC 7 | NULL `ces_final` or NULL `ended_at` rows skipped | `test_async_skips_null_ces_final_rows`, `test_async_skips_null_ended_at_rows` | ✅ |
| AC 8 | No completed sessions → return `None`, no Redis write | `test_compute_baseline_empty_returns_none`, `test_async_returns_none_when_no_sessions`, `test_async_no_redis_write_when_no_sessions`, `test_async_all_rows_ended_at_none_returns_none` | ✅ |
| AC 9 | Redis write uses correct key | `test_async_writes_correct_redis_key` | ✅ |
| AC 10 | Redis TTL set from `settings.ces_baseline_ttl_seconds` | `test_async_sets_correct_ttl` | ✅ |
| AC 11 | `ces_baseline_window = Field(default=5, ge=1, le=50)` | `test_config_ces_baseline_window_default_and_constraints` (new) | ✅ |
| AC 12 | `ces_baseline_ttl_seconds = Field(default=86400, ge=60)` | `test_config_ces_baseline_ttl_default_and_constraints` (new) | ✅ |
| AC 13 | Redis failure non-fatal (logged at WARNING, not raised) | `test_async_redis_failure_does_not_raise` | ✅ |
| AC 14 | DB failure raises `HTTPException 503` | `test_async_db_failure_raises_503` | ✅ |
| AC 15 | No hardcoded window literal in `ces_baseline.py` (AST) | `test_no_hardcoded_window_literal` | ✅ |
| AC 16 | No forbidden imports (`fitz`, etc.) in `ces_baseline.py` (AST) | `test_no_forbidden_imports` | ✅ |
| AC 17 | Supabase query bounded: `fetch_limit = window × _OVERFETCH_FACTOR` | `test_async_fetch_limit_is_bounded` | ✅ |
| AC 18 | Baseline rounded to 4 decimal places | `test_compute_baseline_rounded_to_4dp` | ✅ |
| AC 19 | ≥15 `@pytest.mark.unit` tests; 0 regressions | 27 tests (15 minimum exceeded); 0 regressions confirmed | ✅ |

**19/19 ACs satisfied.**

---

## Validation Pipeline Results

### Ruff lint
```
ruff check apps/api/app/modules/assessment/ces_baseline.py apps/api/tests/test_ces_baseline.py
All checks passed.
```

### Ruff format
```
ruff format apps/api/app/modules/assessment/ces_baseline.py apps/api/tests/test_ces_baseline.py
1 file reformatted, 1 file left unchanged.
```
(Format auto-applied cleanly; no manual intervention required.)

### Unit tests
```
pytest -m unit apps/api/tests/test_ces_baseline.py -v
...
tests/test_ces_baseline.py::test_dunder_all_exports_only_compute_and_store PASSED
tests/test_ces_baseline.py::test_positional_args_raise_type_error PASSED
tests/test_ces_baseline.py::test_redis_key_format PASSED
tests/test_ces_baseline.py::test_compute_baseline_single_score PASSED
tests/test_ces_baseline.py::test_compute_baseline_fewer_than_window PASSED
tests/test_ces_baseline.py::test_compute_baseline_exactly_window PASSED
tests/test_ces_baseline.py::test_compute_baseline_empty_returns_none PASSED
tests/test_ces_baseline.py::test_compute_baseline_rounded_to_4dp PASSED
tests/test_ces_baseline.py::test_async_returns_none_when_no_sessions PASSED
tests/test_ces_baseline.py::test_async_single_session_baseline PASSED
tests/test_ces_baseline.py::test_async_rolling_window_uses_most_recent PASSED
tests/test_ces_baseline.py::test_async_skips_null_ces_final_rows PASSED
tests/test_ces_baseline.py::test_async_writes_correct_redis_key PASSED
tests/test_ces_baseline.py::test_async_sets_correct_ttl PASSED
tests/test_ces_baseline.py::test_async_redis_failure_does_not_raise PASSED
tests/test_ces_baseline.py::test_async_db_failure_raises_503 PASSED
tests/test_ces_baseline.py::test_no_hardcoded_window_literal PASSED
tests/test_ces_baseline.py::test_no_forbidden_imports PASSED
tests/test_ces_baseline.py::test_async_no_redis_write_when_no_sessions PASSED
tests/test_ces_baseline.py::test_async_redis_value_is_string PASSED
tests/test_ces_baseline.py::test_async_fetch_limit_is_bounded PASSED
tests/test_ces_baseline.py::test_async_resp_data_none PASSED
tests/test_ces_baseline.py::test_async_all_rows_ended_at_none_returns_none PASSED
tests/test_ces_baseline.py::test_async_skips_null_ended_at_rows PASSED
tests/test_ces_baseline.py::test_compute_baseline_all_zeros PASSED
tests/test_ces_baseline.py::test_config_ces_baseline_window_default_and_constraints PASSED
tests/test_ces_baseline.py::test_config_ces_baseline_ttl_default_and_constraints PASSED

27 passed in 2.94s
```

### Regression check
Full suite: **0 regressions** (27/27 task tests + existing suite unaffected).

---

## BMAD Process Gate

| Gate | Requirement | Status |
|------|-------------|--------|
| Story-first gate | Story commit (41fb90f) predates implementation commit | ✅ PASS |
| Story ACs | All 19 ACs defined, testable, and satisfied | ✅ PASS |
| RED → GREEN → REFACTOR | Tests written first; GREEN; AST tests as refactor guard | ✅ PASS |
| Test count (AC 19) | ≥15 `@pytest.mark.unit` — actual: **27** | ✅ PASS |
| No hardcoded literals (AC 15) | AST scan confirms `settings.ces_baseline_window` only | ✅ PASS |
| No forbidden imports (AC 16) | AST scan confirms `fitz`/`pymupdf` absent | ✅ PASS |
| No production logic in wrong module | `ces_baseline.py` in `assessment/` — correct | ✅ PASS |
| LLM provider rule | No LLM calls in this function | ✅ PASS (N/A) |
| Ruff clean | 0 lint errors, format applied | ✅ PASS |
| No `return {**state}` spread | Not a LangGraph node — N/A | ✅ PASS (N/A) |
| 5-agent adversarial review | Completed 2026-07-03; all BLOCKERs resolved | ✅ PASS |

---

## Implementation Percentage

**100%** — All 19 ACs implemented and verified. 27/27 tests pass. No pending items.

---

## Production-Readiness Verdict

**PRODUCTION-READY.**

`compute_and_store_ces_baseline()` is a correctly implemented, fully tested async function with:
- Rolling average over configurable window (env-var driven, no hardcoded values)
- Bounded Supabase query (overfetch factor prevents N+1 on NULL rows)
- Redis cache write with TTL — non-fatal on failure
- Supabase failure raises 503 (fatal, propagates to caller)
- `math.isfinite()` guard for corrupt data robustness
- Security note: `user_id` must come from JWT subject (caller responsibility)
- Dev 4 integration: async-safe, keyword-only, documented in `ces_baseline.py` module docstring

No blocking issues. Merge to `master-sprint3-dev3` is approved.

---

## Commit Message

```
test(assessment): post-impl audit — strengthen CES baseline tests (Story 3-24)

- AC 3: add inspect.iscoroutinefunction assertion to test_positional_args_raise_type_error
  Dev 4 awaits this function in the WebSocket handler; sync would deadlock.
- AC 11: add test_config_ces_baseline_window_default_and_constraints
  Exercises ge=1, le=50 bounds; confirms pydantic.ValidationError on window=0 / window=51
- AC 12: add test_config_ces_baseline_ttl_default_and_constraints
  Exercises ge=60 bound; confirms pydantic.ValidationError on ttl=59
- Fix coverage header: correct AC 19 label, add AC 11/12 entries
- Story 3-24 completion notes, file list, and change log updated (25→27 tests)

No production logic changed. 27/27 tests pass, 0 regressions.
```

---

## PR Description

**Title:** `test(assessment): Story 3-24 post-impl audit — AC 3/11/12 test coverage hardening`

**Base:** `master-sprint3-dev3`
**Head:** `sprint3-task2-dev3`

### What
BMAD post-implementation audit remediation for Sprint 3 Task 2 (`ces_baseline.py`).
No production code changed. Three test gaps closed; documentation corrected.

### Changes

| File | Change |
|------|--------|
| `apps/api/tests/test_ces_baseline.py` | +2 new tests (AC 11, AC 12); AC 3 test strengthened; coverage header fixed |
| `docs/stories/3-24-ces-baseline-computation.md` | Task list + completion notes + file list + change log updated; post-impl audit section added |
| `docs/reports/sprint3-task2-bmad-validation-report.md` | New — full validation report |

### Why each gap matters

**AC 3 — `iscoroutinefunction` assertion:**
Dev 4 `await`s `compute_and_store_ces_baseline()` in the WebSocket handler. Without this assertion,
a future accidental `async def` → `def` revert passes all tests silently and causes an event loop
deadlock in production. The assertion is now the machine guard.

**ACs 11/12 — Settings field constraints:**
`ces_baseline_window` has `ge=1, le=50`; `ces_baseline_ttl_seconds` has `ge=60`. These constraints
were correct in `config.py` but had zero tests. A silent relaxation (e.g., `ge=1` → `ge=0`) would
not be caught. Both tests now exercise the invalid-input path via `pydantic.ValidationError`.

### Test results
```
27 passed in 2.94s   (0 regressions)
```

### Checklist
- [x] All 19 ACs satisfied
- [x] 27/27 tests pass
- [x] Ruff lint clean
- [x] Ruff format applied
- [x] No production logic changed
- [x] Story file updated (task list, completion notes, file list, change log, audit section)
- [x] Validation report created
- [x] BMAD process gates satisfied
