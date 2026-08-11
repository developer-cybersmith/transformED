# Story 3-34 — Canonical CES Formula

**Sprint:** Sprint 3 (CES v2 hardening)
**Dev:** Dev 3
**Status:** in-progress
**Branch:** `sprint3/s3-34-canonical-ces-formula`
**Depends on:** Story 3-23 (CES v1), Story 3-27 (tutor service)

---

## Background

Two divergent `compute_ces()` implementations exist:

1. `assessment/ces.py` — the tested reference, **dead in production**. Bug: `quiz_accuracy=None` is treated as `0.0` with full weight retained rather than redistributed. Only `teachback_score` is handled as truly optional.
2. `tutor/service.py` — the production path. Correct: uses generalized proportional redistribution for **all** `None` signals via a `(value, weight)` pairs list.

The divergence means:
- `test_ces.py` tests `assessment/ces.py` — which is never called in production.
- The production function (`tutor/service.py::compute_ces`) has no unit tests.
- AC 8 in `test_ces.py` asserts the buggy behavior (`quiz_accuracy=None → 0.0`) as if it were correct.

This story makes `assessment/ces.py::compute_ces` the **single canonical source**, fixes the `quiz_accuracy=None` bug, makes all five signals `Optional[float]` (forward-compatibility for MediaPipe failure in S3-40), and has `tutor/service.py::compute_ces` delegate to it.

### Defect Record

| ID | Description | Status |
|----|-------------|--------|
| D61 | `assessment/ces.py::quiz_accuracy=None` treated as `0.0` (weight not redistributed) | Fixed by this story |
| D62 | `tutor/service.py::compute_ces` duplicates canonical logic with no unit tests | Fixed by this story (delegation) |

---

## Acceptance Criteria

### AC 1 — Single canonical source
`assessment/ces.py::compute_ces` is the authoritative implementation. `tutor/service.py::compute_ces` is a thin wrapper that delegates to it. No other file in the codebase computes a CES score independently.

### AC 2 — All five signals are Optional
The canonical function signature accepts `Optional[float]` for **all five** signals: `quiz_accuracy`, `teachback_score`, `behavioral`, `head_pose`, `blink`. Any `None` signal's weight is redistributed proportionally across the remaining non-`None` signals using the formula:
```
effective_weight_i = w_i / Σ(w_j for present j)
```

### AC 3 — quiz_accuracy=None redistributes (not 0.0)
When `quiz_accuracy=None`, its weight (`settings.ces_weight_quiz`) is redistributed proportionally across the present signals. This is the same behavior already applied to `teachback_score=None`. The old AC 8 behavior (treat as 0.0) is corrected; the test is updated with a `# BREAKING-CHANGE: D61` annotation.

### AC 4 — All-None guard
When all five signals are `None` (no data at all), `compute_ces` returns `0.0` without raising.

### AC 5 — Value clamping preserved
Each present signal value is clamped to `[0.0, 1.0]` before computation. Out-of-range values are clamped silently (existing behavior retained).

### AC 6 — Output rounding preserved
Result is `min(100.0, round(raw * 100, 4))` — 4 decimal places, capped at 100.0.

### AC 7 — No hardcoded weight literals
The AST scan `test_no_hardcoded_weight_literals_in_ces_py` continues to pass. No weight literal appears in `ces.py` source.

### AC 8 — Delegation test
`test_tutor_service_delegates_to_assessment_ces` confirms that for identical inputs, `tutor.service.compute_ces` and `assessment.ces.compute_ces` produce identical results (to within floating-point tolerance).

### AC 9 — No forbidden imports
`assessment/ces.py` must not import: `supabase`, `openai`, `posthog`, `httpx`, `requests`, `asyncio`, `aiohttp`. Existing AST scan continues to pass.

### AC 10 — No ruff errors
`ruff check apps/api/app/modules/assessment/ces.py apps/api/app/modules/tutor/service.py apps/api/tests/test_ces.py` reports 0 errors.

### AC 11 — All existing passing tests still pass
All 33 tests in `test_ces.py` pass under the new implementation (27 from Story 3-34, plus 6 patches from the post-review cycle). The two tests that described the (now-fixed) bug behavior are updated to assert the correct new behavior.

---

## Tasks / Subtasks

- [ ] **T1** Write RED tests: new behavior for quiz_accuracy=None (redistribution), all-None guard, behavioral/head_pose/blink None handling, delegation test
- [ ] **T2** Update `assessment/ces.py`: generalize all 5 signals to Optional, implement generalized redistribution
- [ ] **T3** Update `tutor/service.py::compute_ces` to delegate to canonical function
- [ ] **T4** Update `test_ces.py`: AC8 and AC8b tests corrected with `# BREAKING-CHANGE: D61` annotation
- [ ] **T5** Run `ruff check` and `pytest -m unit` — all pass
- [ ] **T6** 6-agent code review
- [ ] **T7** Merge

### Review Findings

- [x] [Review][Decision] NaN signal input has no explicit guard in canonical ces.py — `v is not None` passes NaN, which CPython's `max(0.0, nan)` silently converts to 0.0 (zero engagement instead of absent signal). Options: (a) add `if v is not None and math.isfinite(v)` to the `present` list-comp, (b) raise `ValueError` on non-finite input, (c) document caller must pre-validate. Service-layer already validates for WebSocket path; direct-API callers are unguarded. **RESOLVED: Option (b) — ValueError. P-A applied 2026-08-11.**
- [x] [Review][Decision] Out-of-range signal clamping is silent — AC5 explicitly accepts this, but CLAUDE.md binding rule "silent truncation is never acceptable" requires either (a) `logger.warning(...)` emitted when `v` is outside [0,1], or (b) a D-nn register entry explicitly accepting clamping as a known, bounded exception with a trigger. **RESOLVED: Option (a) — logger.warning. P-B applied 2026-08-11.**
- [x] [Review][Patch] weight_sum NaN-blindness: `NaN <= 0.0` is False in IEEE 754, so a NaN weight bypasses the guard, propagates through division, and `min(100.0, NaN)` returns 100.0 — spurious maximum engagement [apps/api/app/modules/assessment/ces.py:78] **APPLIED P1 2026-08-11.**
- [x] [Review][Patch] Missing `max(0.0, ...)` output lower-bound guard — old service.py had `max(0.0, min(100.0, ces))` but the canonical has only `min(100.0, ...)` [apps/api/app/modules/assessment/ces.py:83] **APPLIED P2 2026-08-11.**
- [x] [Review][Patch] Add asymmetric redistribution test for quiz_accuracy=None — all current quiz=None tests use all-1.0 for other signals, which cannot catch a weight-swap bug [apps/api/tests/test_ces.py] **APPLIED P3 2026-08-11: `test_quiz_accuracy_none_asymmetric_redistribution`.**
- [x] [Review][Patch] Add combined test for quiz=None + teachback=0.0 — catches accidental `if not v` instead of `if v is None` treatment [apps/api/tests/test_ces.py] **APPLIED P4 2026-08-11: `test_quiz_none_and_quiz_zero_are_different`.**
- [x] [Review][Patch] 4dp rounding not discriminatingly tested — add test with a 1/3 value that distinguishes rounded from unrounded output [apps/api/tests/test_ces.py] **APPLIED P5 2026-08-11: `test_output_rounded_to_4dp`.**
- [x] [Review][Patch] D61 + D62 not entered in docs/DEFECT-REGISTER.md — story references them in its own table but they have no register entries; CLAUDE.md binding rules 5 and 7 require register IDs for all known defects [docs/DEFECT-REGISTER.md] **APPLIED P6 2026-08-11: D61 CLOSED, D62 CLOSED, D63 OPEN/deferred registered.**
- [x] [Review][Patch] Story inaccuracies: AC11 says "20 tests" (actual: 27), Q6 uses "goroutines" (Python, not Go), Status field still "In Progress" [docs/stories/3-34-canonical-ces-formula.md] **APPLIED P7 2026-08-11: AC11 updated to 33 tests, Q6 fixed to "concurrent async tasks", Status to "in-progress".**
- [x] [Review][Patch] Add clamping+redistribution combined test (e.g., behavioral=1.5 + teachback=None) to prove clamping occurs before redistribution [apps/api/tests/test_ces.py] **APPLIED P8 2026-08-11: `test_clamping_with_redistribution_combined`.**
- [x] [Review][Defer] Dead-code paths: behavioral/hp/blink=None redistribution unreachable through production NormalizedSignal wrapper (typed float, not Optional) — S3-40 responsibility, already noted in Dev Notes [apps/api/app/modules/tutor/service.py:107-123] — deferred, pre-existing by design
- [x] [Review][Defer] No AST scan enforcing CES-uniqueness across repo (AC1 enforcement) — D62 documents the defect; a CI guard would be a separate story [new test file needed] — deferred, separate story scope
- [x] [Review][Defer] Degenerate weight config (Scale Q5): settings where behavioral+hp+blink weights all = 0.0 AND academic signals None → weight_sum=0 → CES=0 silently with no error — pre-existing, register as D63 [apps/api/app/modules/assessment/ces.py:77-80] — deferred, pre-existing, needs D63 in register

---

## Scale & Load

**Q1 — Unit of work and range:**
One CES computation per 5-second window per active session. Range: 1 session (development) → thousands of concurrent sessions at scale. Each computation is stateless and O(1). No shared state between calls.

**Q2 — Fixed budgets vs variable input:**
None. The function is purely computational. Weight config comes from env vars (Settings). The only fixed element is 5 signal slots — `None` signals simply drop from the computation. Division guard (`weight_sum <= 0 → 0.0`) handles the degenerate all-None case explicitly.

**Q3 — Scope of every limit:**
Per-call. Fully stateless. No per-user, per-instance, or per-deployment limits.

**Q4 — Unbounded reads/writes:**
None. Pure function; no I/O.

**Q5 — Inherited caps re-derived:**
The previous implementation treated `behavioral`, `head_pose`, `blink` as required (non-None). This was an inherited assumption from CES v1 before MediaPipe failure handling was considered. Re-derived for S3-40 (MediaPipe failure): all five must be Optional to allow head_pose=None and blink=None when the camera fails. Making them Optional now is forward-compatible and removes a hidden constraint.

**Q6 — Check-then-act under concurrency:**
No state mutation. Fully concurrent-safe. Multiple concurrent async tasks calling `compute_ces` simultaneously is safe — no shared mutable state, no I/O, pure computation.

---

## Definition of Done

- [ ] Story file committed before any implementation code
- [ ] RED tests written and confirmed failing before implementation
- [ ] Implementation makes all tests GREEN
- [ ] Ruff: 0 errors in modified files
- [ ] 6-agent adversarial code review passed (Story Quality, Blind Hunter, Test Coverage, AC Completeness, Process Integrity, Scale & Load)
- [ ] `docs/dev3-assessment-tracker.md` updated: task checked + dashboard updated
- [ ] PR merged to main

---

## Dev Notes

### What the canonical implementation must do

1. Build a `(value, weight)` pairs list for all 5 signals.
2. Filter to `present = [(v, w) for (v, w) in pairs if v is not None]`.
3. For each present value, clamp `v = min(1.0, max(0.0, v))`.
4. `weight_sum = sum(w for _, w in present)`.
5. Guard: if `weight_sum <= 0.0`, return `0.0`.
6. `ces = sum(v * (w / weight_sum) for v, w in present) * 100.0`.
7. Return `min(100.0, round(ces, 4))`.

This is already what `tutor/service.py::compute_ces` does — minus the clamping and rounding. The canonical function adds both.

### Wrapper in tutor/service.py

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

### Breaking change in test_ces.py

`test_quiz_accuracy_none_treated_as_zero` (AC 8) and `test_both_none_quiz_accuracy_treated_as_zero_in_redistribution` (AC 8b) both assert the old buggy behavior. These tests must be updated to assert the new correct behavior (redistribution). Add `# BREAKING-CHANGE: D61` comment to the updated test.

New expected value for `quiz_accuracy=None, teachback=1.0, beh=1.0, hp=1.0, blink=1.0`:
- Old (wrong): `(0.0×0.35 + 1.0×0.25 + 1.0×0.20 + 1.0×0.12 + 1.0×0.08) × 100 = 65.0`
- New (correct): all 4 present signals have full weight redistribution.
  `weight_sum = 0.25 + 0.20 + 0.12 + 0.08 = 0.65`
  `CES = (1.0×0.25/0.65 + 1.0×0.20/0.65 + 1.0×0.12/0.65 + 1.0×0.08/0.65) × 100 = 100.0`

New expected value for `quiz_accuracy=None, teachback=None, beh=1.0, hp=1.0, blink=1.0`:
- Old (wrong): `(0.0×0.35/0.75 + 1.0×0.20/0.75 + 1.0×0.12/0.75 + 1.0×0.08/0.75) × 100 ≈ 53.33`
- New (correct): only beh, hp, blink present.
  `weight_sum = 0.20 + 0.12 + 0.08 = 0.40`
  `CES = (1.0×0.20/0.40 + 1.0×0.12/0.40 + 1.0×0.08/0.40) × 100 = 100.0`

### Files modified

- `apps/api/app/modules/assessment/ces.py` — canonical implementation update
- `apps/api/app/modules/tutor/service.py` — delegation wrapper
- `apps/api/tests/test_ces.py` — test corrections + new tests
