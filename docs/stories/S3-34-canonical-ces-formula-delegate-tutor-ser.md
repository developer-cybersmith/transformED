# Story S3-34 — Canonical CES Formula: Delegate tutor/service.py compute_ces to assessment/ces.py

**Sprint:** Sprint 3
**Dev:** Dev 3
**Status:** Draft
**Branch:** `sprint3/s3-34-canonical-ces-formula`
**Decisions implemented:** D1, D61, D62
**Depends on:** Story 3-23 (CES v1 formula), Story S3-42 (CES breakdown accuracy)
**Migration:** NO

---

## User Story

As the system processing attention signals for an active student session,
I need a single authoritative CES computation function shared between the tutor signal-processing path and the assessment reporting path,
so that the CES score a student is monitored against in real-time is mathematically identical to the CES score surfaced in their session report — and so any fix or calibration to the formula propagates to both callers without a code change in two places.

---

## Background

Two divergent `compute_ces()` implementations existed before this story:

| Location | Status before fix | Problem |
|---|---|---|
| `assessment/ces.py` | Tested but never called in production | `quiz_accuracy=None` treated as `0.0` with full weight retained (D61); only `teachback_score` handled as truly optional |
| `tutor/service.py` | Production path with no unit tests | Correct generalized redistribution, but duplicated logic (D62); any divergence undetectable until a session report disagreed with the live CES threshold |

The divergence meant tests passed against code that never ran in production, and production code had no tests. D1 (wire the canonical implementation into the tutor path) resolves both: one source of truth, tested, called in both places.

### Defect Register entries closed by this story

| ID | Description |
|----|-------------|
| D1 | `tutor/service.py::compute_ces` is a separate implementation — should import and delegate to `assessment/ces.py::compute_ces` |
| D61 | `assessment/ces.py::compute_ces`: `quiz_accuracy=None` treated as `0.0` (weight retained, not redistributed); breaks symmetry with `teachback_score=None` handling |
| D62 | `tutor/service.py::compute_ces` duplicates canonical CES logic with no unit tests; any fix to `assessment/ces.py` would silently diverge from the production path |

---

## Acceptance Criteria

### AC 1 — Single canonical source enforced
`assessment/ces.py::compute_ces` is the sole implementation in the codebase. No other file defines a function that independently applies the CES weighted sum formula. An AST scan of the repo finds exactly one definition of the weighted sum pattern.

### AC 2 — All five signals are `Optional[float]`
The canonical function signature is:
```python
def compute_ces(
    *,
    quiz_accuracy: float | None,
    teachback_score: float | None,
    behavioral: float | None,
    head_pose: float | None,
    blink: float | None,
    settings: Settings,
) -> float
```
Any `None` signal's weight is redistributed proportionally across the remaining non-`None` signals:
```
effective_weight_i = w_i / sum(w_j for all present j)
```

### AC 3 — `quiz_accuracy=None` redistributes weight (not treated as 0.0)
Given default weights (quiz=0.35, teachback=0.25, behavioral=0.20, head_pose=0.12, blink=0.08) and inputs `quiz_accuracy=None, teachback_score=1.0, behavioral=1.0, head_pose=1.0, blink=1.0`:
- Old (wrong) result: `(0.0×0.35 + 1.0×0.25 + 1.0×0.20 + 1.0×0.12 + 1.0×0.08) × 100 = 65.0`
- New (correct) result: `weight_sum = 0.25+0.20+0.12+0.08 = 0.65`; `CES = (1.0×0.25/0.65 + 1.0×0.20/0.65 + 1.0×0.12/0.65 + 1.0×0.08/0.65) × 100 = 100.0`

The test that previously asserted the wrong value (AC 8 in `test_ces.py`) is updated with `# BREAKING-CHANGE: D61` annotation and now asserts `100.0`.

### AC 4 — All-`None` guard returns `0.0`
When all five signals are `None` (e.g., no data available at session start), `compute_ces` returns `0.0` without raising an exception.

### AC 5 — Value clamping preserved with logging
Each present signal value is clamped to `[0.0, 1.0]`. Values outside this range emit a `logger.warning` before clamping (to surface calibration bugs). Out-of-range values do not raise; they are clamped silently after the warning.

### AC 6 — Non-finite values raise `ValueError`
If any present (non-`None`) signal value is `NaN` or `±inf`, `compute_ces` raises `ValueError` immediately. The error message names the offending signal. This distinguishes corrupt signals (NaN/inf) from absent signals (`None`).

### AC 7 — Output clamped and rounded to 4 decimal places
The return value is `max(0.0, min(100.0, round(ces, 4)))`. The `max(0.0, ...)` guard protects against degenerate configurations with negative weight values.

### AC 8 — `weight_sum` guard is NaN-safe
The guard `if not (weight_sum > 0.0): return 0.0` is used rather than `if weight_sum <= 0.0`, because `NaN <= 0.0` evaluates to `False` in IEEE 754, which would otherwise skip the guard and produce a NaN result.

### AC 9 — No hardcoded weight literals in `ces.py`
An AST scan of `apps/api/app/modules/assessment/ces.py` finds no float literals matching the default weight values (0.35, 0.25, 0.20, 0.12, 0.08) embedded in the computation. All weights are read from `settings.ces_weight_*`.

### AC 10 — `tutor/service.py::compute_ces` delegates to canonical
`tutor/service.py` imports `compute_ces` from `app.modules.assessment.ces` and the local `compute_ces` is a thin wrapper:
```python
from app.modules.assessment.ces import compute_ces as _compute_ces_canonical

def compute_ces(signal: NormalizedSignal) -> float:
    from app.config import get_settings
    return _compute_ces_canonical(
        quiz_accuracy=signal.quiz_accuracy,
        teachback_score=signal.teachback_score,
        behavioral=signal.behavioral_score,
        head_pose=signal.head_pose_score,
        blink=signal.blink_rate,
        settings=get_settings(),
    )
```
No independent weighted-sum computation remains in `tutor/service.py`.

### AC 11 — Delegation produces identical results
For any set of valid inputs, `tutor.service.compute_ces(signal)` and `assessment.ces.compute_ces(...)` produce identical results (within floating-point tolerance, i.e., `abs(a - b) < 1e-9`). This is verified by a parametrized test covering at least 10 representative input combinations including `None` values.

### AC 12 — No forbidden imports in `ces.py`
`assessment/ces.py` does not import: `supabase`, `openai`, `posthog`, `httpx`, `requests`, `asyncio`, `aiohttp`, `redis`. The module is a pure synchronous computation library with no I/O.

### AC 13 — No ruff errors
`ruff check apps/api/app/modules/assessment/ces.py apps/api/app/modules/tutor/service.py apps/api/tests/test_ces.py apps/api/tests/test_ces_canonical_delegation.py` reports 0 errors.

### AC 14 — All pre-existing passing tests still pass
All tests that were passing before this story continue to pass. The two tests in `test_ces.py` that asserted the incorrect D61 behavior are updated (not deleted) to assert the corrected behavior.

---

## Tasks / Subtasks

- [x] **T1** Write RED tests: redistribution for `quiz_accuracy=None`, all-`None` guard, `behavioral`/`head_pose`/`blink` as `Optional[float]`, delegation identity test
- [x] **T2** Update `assessment/ces.py`: generalize all 5 signals to `Optional[float]`, implement generalized proportional redistribution, add NaN guard (ValueError), add out-of-range warning, NaN-safe `weight_sum` guard
- [x] **T3** Update `tutor/service.py::compute_ces` to delegate to canonical function via import from `assessment.ces`
- [x] **T4** Update `test_ces.py`: correct AC8/AC8b tests with `# BREAKING-CHANGE: D61` annotation; add 7 new tests for `behavioral`/`head_pose`/`blink` `None` handling and all-`None` guard
- [x] **T5** Create `test_ces_canonical_delegation.py`: 10 parametrized cases proving identical results between the two call sites
- [x] **T6** Run `ruff check` and `pytest -m unit` — confirm 0 errors and all GREEN
- [x] **T7** 6-agent code review (Story Quality, Blind Hunter, Test Coverage, AC Completeness, Process Integrity, Scale & Load)
- [x] **T8** Update `docs/dev3-assessment-tracker.md` and merge

---

## Scale & Load

### Q1 — Unit of work and range
One CES computation per 5-second attention window per active session.

- **Minimum:** 1 computation per session (first signal window)
- **Typical:** 60–120 computations per session (5–10 minutes of active learning)
- **Maximum measured:** ~720 computations for a 60-minute session
- **Beyond maximum:** No cap needed. Each computation is O(1) stateless arithmetic (5 multiplications, 1 division, 1 clamp). No resources are consumed beyond CPU cycles. There is no fixed budget that the input can exceed.

### Q2 — Fixed budgets vs variable input
No fixed budgets exist in this computation. The function is pure arithmetic: 5 signals, 5 weights, 1 weighted sum. The only fixed element is the 5-slot signal schema — `None` signals drop from the computation cleanly.

Guard behaviors at limits:
- `weight_sum <= 0.0` (all signals `None` or degenerate config): returns `0.0` explicitly — not an error
- Non-finite input: raises `ValueError` immediately with the signal name — explicit error, not silent
- Output > 100.0: clamped to `100.0` — explicit surfaced degradation (logged upstream by the caller)
- Output < 0.0: clamped to `0.0` (degenerate negative-weight config) — explicit guard

Silent truncation is not possible in this function.

### Q3 — Scope of every limit
Per-call. Fully stateless. No shared mutable state, no per-user budget, no per-instance limit, no per-deployment cap. A thousand concurrent calls to `compute_ces` share nothing.

`settings.ces_weight_*` env vars are read-only after startup — they are the same value for every call in every replica.

### Q4 — Unbounded reads and writes
None. The function performs no I/O: no Supabase reads, no Redis reads, no network calls, no file operations. The callers (`tutor/service.py::process_attention_signal`) perform the Redis reads and writes — those are bounded by `_CES_HISTORY_MAX = 10` (LTRIM) and `_CES_WINDOW_TTL = 86_400` (TTL). Those bounds are owned by the calling function, not by `compute_ces` itself.

### Q5 — Inherited caps re-derived
The previous implementation treated `behavioral`, `head_pose`, and `blink` as required non-`None` floats. This was an inherited assumption from CES v1 (Story 3-23), which predated MediaPipe failure handling (Story S3-40).

Re-derived for this story: making all five signals `Optional[float]` is the correct generalization. The redistribution formula `effective_weight_i = w_i / sum(w_j for present j)` is a mathematically consistent extension — when all signals are present it reduces to the original formula exactly. No existing behavior changes for callers that always pass non-`None` values.

The `quiz_accuracy=None → 0.0` behavior in the old `assessment/ces.py` was not a cap — it was a bug (D61). It has been corrected.

### Q6 — Check-then-act under concurrency
No check-then-act sequences exist in `compute_ces`. The function is a pure function with no reads of shared state. Concurrent calls from different sessions, different users, or different replicas are completely independent.

The callers that read Redis before dispatching interventions (`process_attention_signal`) have their own concurrency analysis in Story S3-35 (session finalization) and Story S3-37 (intervention events).

---

## Security

### Auth and ownership
`compute_ces` is a pure internal function — it accepts validated numeric inputs and returns a float. It has no knowledge of user identity, session ownership, or auth tokens. Session ownership validation occurs upstream in the WebSocket handler (Dev 4's scope) and in the assessment service before any signal processing begins.

### Injection risk
No string interpolation, SQL construction, or shell invocation. Inputs are typed `float | None`; the Python type system and `math.isfinite` guard prevent injection. Non-numeric inputs would cause a `TypeError` at `float(v)` in the caller's `_parse_signal`.

### Data exposure
`compute_ces` accepts already-anonymized numeric signals. No PII or raw webcam data enters this function. Raw webcam video never leaves the browser (CLAUDE.md §18).

### Denial of service
The function is O(1) with no loops beyond the fixed 5-element signal list. A malicious payload cannot cause an expensive computation. The `ValueError` on non-finite values prevents degenerate arithmetic from propagating (e.g., a NaN CES being stored as `100.0` in Redis and suppressing all interventions).

---

## Test Requirements

The following tests must exist and pass. All are unit tests (`@pytest.mark.unit` or unmarked in the unit test module).

### `apps/api/tests/test_ces.py` (updated)

| Test name | What it asserts |
|---|---|
| `test_all_signals_present_default_weights` | All 5 signals = 1.0 → CES = 100.0 |
| `test_all_signals_zero` | All 5 signals = 0.0 → CES = 0.0 |
| `test_teachback_none_redistributes_to_four_signals` | `teachback_score=None`, other 4 = 1.0 → CES = 100.0 |
| `test_quiz_accuracy_none_redistributes_weight` | **D61 fix (BREAKING-CHANGE)**: `quiz_accuracy=None`, other 4 = 1.0 → CES = 100.0 (not 65.0) |
| `test_both_none_quiz_teachback_redistributes_to_three` | **D61 fix (BREAKING-CHANGE)**: `quiz_accuracy=None, teachback_score=None`, behavioral/head_pose/blink = 1.0 → CES = 100.0 (not ~53.33) |
| `test_all_none_returns_zero` | All 5 signals = `None` → CES = 0.0 |
| `test_behavioral_none_redistributes` | `behavioral=None`, other 4 = 1.0 → CES = 100.0 |
| `test_head_pose_none_redistributes` | `head_pose=None`, other 4 = 1.0 → CES = 100.0 |
| `test_blink_none_redistributes` | `blink=None`, other 4 = 1.0 → CES = 100.0 |
| `test_clamping_above_one` | Signal value = 1.5 → clamped to 1.0 before weighting |
| `test_clamping_below_zero` | Signal value = -0.5 → clamped to 0.0 before weighting |
| `test_output_capped_at_100` | Result cannot exceed 100.0 |
| `test_output_minimum_is_zero` | Result cannot be negative |
| `test_output_rounded_4dp` | Result is rounded to 4 decimal places |
| `test_no_hardcoded_weight_literals_in_ces_py` | AST scan: no weight float literals in `ces.py` source |
| `test_no_forbidden_imports_in_ces_py` | AST scan: no I/O library imports in `ces.py` |
| `test_nonfinite_nan_raises_value_error` | `quiz_accuracy=float('nan')` → raises `ValueError` |
| `test_nonfinite_inf_raises_value_error` | `behavioral=float('inf')` → raises `ValueError` |
| `test_weight_sum_nan_safe_guard` | Degenerate `weight_sum` guard uses `not (weight_sum > 0.0)` pattern |
| `test_mixed_none_and_zero_signals` | Two signals `None`, two = 0.0, one = 1.0 → correct redistribution |

### `apps/api/tests/test_ces_canonical_delegation.py` (new)

| Test name | What it asserts |
|---|---|
| `test_delegation_all_present[case0]` | All signals present: `tutor.compute_ces` == `assessment.compute_ces` to 1e-9 |
| `test_delegation_teachback_none[case1]` | `teachback_score=None`: identical results |
| `test_delegation_quiz_none[case2]` | `quiz_accuracy=None`: identical results |
| `test_delegation_both_optional_none[case3]` | `quiz_accuracy=None, teachback_score=None`: identical results |
| `test_delegation_all_zero[case4]` | All signals = 0.0: identical results |
| `test_delegation_mixed_values[case5]` | Partial engagement: identical results |
| `test_delegation_behavioral_none[case6]` | `behavioral=None`: identical results |
| `test_delegation_head_pose_none[case7]` | `head_pose=None`: identical results |
| `test_delegation_blink_none[case8]` | `blink=None`: identical results |
| `test_delegation_all_none[case9]` | All `None`: both return `0.0` |

---

## Definition of Done

- [x] Story file committed before any implementation code on this branch
- [x] RED tests written and confirmed failing before implementation
- [x] Implementation makes all tests GREEN
- [x] Ruff: 0 errors in all modified files
- [x] 6-agent adversarial code review passed (Story Quality, Blind Hunter, Test Coverage, AC Completeness, Process Integrity, Scale & Load)
- [x] `docs/dev3-assessment-tracker.md` updated
- [x] PR merged to main

---

## Dev Notes

### Why the canonical function signature uses keyword-only arguments

All five signals plus `settings` are keyword-only (`*`). This prevents silent argument transposition — `compute_ces(0.5, 0.8, 0.7, 0.6, 0.9, settings)` would be a bug waiting to happen if the positional order changed. Keyword-only is enforced by the `*` before the first parameter.

### The redistribution formula

For any subset of present signals `P` (non-`None` values), each effective weight is:
```
effective_weight_i = w_i / sum(w_j for j in P)
```

When all 5 are present: `sum = 1.0`, so `effective_weight_i = w_i` — formula reduces to standard CES.
When only teachback is `None`: `sum = 0.75`, matching CLAUDE.md §11 redistribution exactly.
When quiz and teachback are both `None`: `sum = 0.40`, sharing weight proportionally over behavioral/head_pose/blink.

### What changed in `tutor/service.py`

The function `compute_ces(signal: NormalizedSignal) -> float` now reads:
```python
from app.modules.assessment.ces import compute_ces as _compute_ces_canonical

def compute_ces(signal: NormalizedSignal) -> float:
    from app.config import get_settings
    return _compute_ces_canonical(
        quiz_accuracy=signal.quiz_accuracy,
        teachback_score=signal.teachback_score,
        behavioral=signal.behavioral_score,
        head_pose=signal.head_pose_score,
        blink=signal.blink_rate,
        settings=get_settings(),
    )
```

The previous implementation (generalized redistribution list comprehension) is deleted. The `NormalizedSignal` dataclass and `_parse_signal` boundary mapper are unchanged.

### Files modified by implementation

- `apps/api/app/modules/assessment/ces.py` — canonical implementation; all 5 signals Optional
- `apps/api/app/modules/tutor/service.py` — delegation wrapper replaces local computation
- `apps/api/tests/test_ces.py` — AC8/AC8b updated; 7 new tests added
- `apps/api/tests/test_ces_canonical_delegation.py` — new: 10 parametrized delegation identity tests
