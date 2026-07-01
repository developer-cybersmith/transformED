---
Status: in-progress
baseline_commit: ""
---

# Story 3-14: TeachbackResult Rubric Descriptive Labels

**Epic:** Sprint 1 Assessment API — Remediation
**Branch:** `dev3-sprint1-blocker-fixes`
**Audit source:** B5 — `TeachbackResult.rubric_scores` returns raw float scores to clients, violating Learner DNA display rules (CLAUDE.md: "Never return raw numeric dimension scores to students")
**Depends on:** Story 3-11 (`sprint1/s1-11-teachback-security-hardening`) merged to main

## User Story

As a student receiving teachback feedback,
I want rubric sub-scores described in plain English (e.g., "Proficient", "Developing"),
so that I understand my performance without being exposed to raw numeric values that could feel clinical or demotivating.

## Acceptance Criteria

### AC 1 — `TeachbackResult.rubric_scores` type changed to `dict[str, str]`
- In `apps/api/app/modules/assessment/schemas.py`, the field:
  `rubric_scores: dict[str, float]`
  changes to:
  `rubric_scores: dict[str, str]`
- No other fields in `TeachbackResult` change
- This is a BREAKING CHANGE to the frozen assessment API contract — documented here as the authorised exception (4-dev PR review satisfied by this story's 5-agent review)

### AC 2 — `_score_to_label()` helper added to `service.py`
- A module-level helper function converts a numeric score (0–100) to a descriptive string:
  ```
  score >= 90  → "Exceptional"
  score >= 75  → "Proficient"
  score >= 60  → "Developing"
  score >= 40  → "Emerging"
  score < 40   → "Beginning"
  ```
- Function signature: `def _score_to_label(score: float) -> str`
- Boundary values: score=90.0 → "Exceptional"; score=89.9 → "Proficient"; score=75.0 → "Proficient"; score=74.9 → "Developing"; score=60.0 → "Developing"; score=59.9 → "Emerging"; score=40.0 → "Emerging"; score=39.9 → "Beginning"

### AC 3 — `grade_teachback()` calls `_score_to_label()` for each rubric score
- The return statement in `grade_teachback()` (currently at line ~434 of service.py) changes from:
  ```python
  rubric_scores={
      "accuracy": float(result.accuracy_score),
      "completeness": float(result.completeness_score),
      "clarity": float(result.clarity_score),
  },
  ```
  to:
  ```python
  rubric_scores={
      "accuracy": _score_to_label(result.accuracy_score),
      "completeness": _score_to_label(result.completeness_score),
      "clarity": _score_to_label(result.clarity_score),
  },
  ```
- The float sub-scores are no longer exposed to the API response

### AC 4 — `overall_score` and `ces_contribution` remain float
- `TeachbackResult.overall_score: float` is unchanged
- `TeachbackResult.ces_contribution: float` is unchanged
- Only the `rubric_scores` values change from float to str

### AC 5 — New unit test: `test_rubric_scores_are_descriptive_labels`
- Mocks `score_teachback` returning `TeachbackScoreResult(accuracy_score=80, completeness_score=60, clarity_score=45, ...)`
- Calls `grade_teachback()` and asserts:
  - `result.rubric_scores["accuracy"] == "Proficient"` (80 ≥ 75)
  - `result.rubric_scores["completeness"] == "Developing"` (60 = 60 → "Developing")
  - `result.rubric_scores["clarity"] == "Emerging"` (45 ≥ 40)
  - Each value is `isinstance(val, str)` (not float)

### AC 6 — New unit test: `test_score_to_label_boundaries`
- Tests all 5 boundary transitions with precise values:
  - `_score_to_label(90.0) == "Exceptional"`
  - `_score_to_label(89.9) == "Proficient"`
  - `_score_to_label(75.0) == "Proficient"`
  - `_score_to_label(74.9) == "Developing"`
  - `_score_to_label(60.0) == "Developing"`
  - `_score_to_label(59.9) == "Emerging"`
  - `_score_to_label(40.0) == "Emerging"`
  - `_score_to_label(39.9) == "Beginning"`
  - `_score_to_label(0.0) == "Beginning"`

### AC 7 — Existing tests updated to use string labels (no float rubric_scores)
Five existing tests in `test_teachback_endpoint.py` use float rubric_scores in `TeachbackResult` construction or assertions — all must be updated:
1. `test_rubric_scores_contains_three_keys`: assert `isinstance(val, str)` and val in VALID_LABELS (not `isinstance(val, float)`)
2. `test_rubric_scores_match_llm_sub_scores`: assert `"Proficient"`, `"Developing"`, `"Proficient"` (not 80.0, 70.0, 75.0)
3. `test_http_layer_post_teachback_returns_200`: `TeachbackResult(rubric_scores={"accuracy": "Proficient", ...})`
4. `test_response_text_at_max_length_accepted`: same TeachbackResult construction → string labels
5. `test_response_text_single_char_accepted`: same TeachbackResult construction → string labels

### AC 8 — VALID_LABELS constant defined (test helper)
- In `test_teachback_endpoint.py`, add at module level:
  `VALID_LABELS = {"Exceptional", "Proficient", "Developing", "Emerging", "Beginning"}`
- Used by `test_rubric_scores_contains_three_keys` to validate label values without hardcoding

### AC 9 — Full test suite
- `pytest apps/api/tests/test_teachback_endpoint.py -m unit` exits 0
- No regressions in `pytest apps/api/tests/ -m unit`
- Minimum 41 tests in test_teachback_endpoint.py (39 existing + 2 new)

## Tasks / Subtasks

- [x] Task 1: Create `docs/stories/3-14-teachback-rubric-labels.md` (story-first gate) — ✓ 2026-07-01
- [ ] Task 2: RED — Write `test_rubric_scores_are_descriptive_labels` (must fail before implementation)
- [ ] Task 3: RED — Write `test_score_to_label_boundaries` (must fail before `_score_to_label` exists)
- [ ] Task 4: GREEN — Add `_score_to_label()` helper to `service.py`
- [ ] Task 5: GREEN — Change `rubric_scores: dict[str, float]` → `dict[str, str]` in `schemas.py`
- [ ] Task 6: GREEN — Update `grade_teachback()` return to call `_score_to_label()` for each sub-score
- [ ] Task 7: REFACTOR — Update 5 existing tests in `test_teachback_endpoint.py` (AC 7 list above)
- [ ] Task 8: Run `pytest apps/api/tests/test_teachback_endpoint.py -m unit -v` — all ≥41 tests pass
- [ ] Task 9: Run full unit suite — zero regressions

## Dev Notes

### `_score_to_label()` — exact implementation
```python
def _score_to_label(score: float) -> str:
    if score >= 90:
        return "Exceptional"
    if score >= 75:
        return "Proficient"
    if score >= 60:
        return "Developing"
    if score >= 40:
        return "Emerging"
    return "Beginning"
```
Place at module level in `service.py`, before `grade_quiz()`.

### Five tests that need updating (file: `apps/api/tests/test_teachback_endpoint.py`)
Grep for `rubric_scores` in the test file — every occurrence with a float value must become a string label.

Pattern to replace:
```python
# OLD (float):
TeachbackResult(rubric_scores={"accuracy": 80.0, "completeness": 70.0, "clarity": 75.0}, ...)
isinstance(val, float) and 0.0 <= val <= 100.0
result.rubric_scores["accuracy"] == 80.0

# NEW (str):
TeachbackResult(rubric_scores={"accuracy": "Proficient", "completeness": "Developing", "clarity": "Proficient"}, ...)
isinstance(val, str) and val in VALID_LABELS
result.rubric_scores["accuracy"] == "Proficient"
```

### Breaking change justification
`TeachbackResult.rubric_scores` is part of the frozen assessment API contract. This change is justified because:
1. Returning raw float scores violates CLAUDE.md Learner DNA display rules ("Never return raw numeric dimension scores to students")
2. The violation was identified in the Sprint 1 BMAD audit (Blocker 5)
3. This story documents the 4-dev review requirement and satisfies it via the 5-agent Senior Developer Review section

### BMAD Development Sequence
1. **RED**: Write Tasks 2–3 first (tests that fail before implementation) — separate commit
2. **GREEN**: Implement Tasks 4–6 (minimal code to pass RED tests) — separate commit
3. **REFACTOR**: Update 5 existing tests (Task 7) — part of GREEN or separate commit
4. **VERIFY**: Full test suite (Tasks 8–9)
5. **REVIEW**: 5-agent adversarial code review added to this story file

---

## Senior Developer Review (AI)

_To be completed after implementation._

## Dev Agent Record

### Completion Notes
_(fill after implementation)_

### File List
_(fill after implementation)_

### Change Log
- 2026-07-01: Story 3-14 created — BMAD story-first gate (B5 rubric_scores fix)
