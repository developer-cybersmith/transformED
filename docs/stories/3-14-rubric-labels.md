---
Status: ready-for-dev
baseline_commit: ""
---

# Story 3-14: TeachbackResult rubric_labels (Frozen Contract Change)

**Epic:** Sprint 1 Assessment API — Remediation
**Branch:** `sprint1/s1-14-rubric-labels`
**Audit source:** F-002 (raw numeric scores returned to students violates CLAUDE.md rule)
**FROZEN CONTRACT CHANGE** — requires 4-dev PR review before merge

## User Story

As a student reviewing my teach-back feedback,
I want to see descriptive labels ("Strong", "Developing", "Needs Work") instead of raw numeric scores per rubric dimension,
so that feedback is motivating and does not expose internal evaluation metrics.

## Acceptance Criteria

### AC 1 — TeachbackResult schema change (frozen contract — 4-dev PR required)
- `TeachbackResult` in `schemas.py` changes:
  - OLD: `rubric_scores: dict[str, float]`
  - NEW: `rubric_labels: dict[str, str]`
- Comment on old field is removed; new comment: `# descriptive labels — never return raw numerics to students`

### AC 2 — Label thresholds applied in grade_teachback()
- Three rubric dimensions converted before building the result: accuracy, completeness, clarity
- Threshold logic:
  - score >= 80 → "Strong"
  - 60 <= score < 80 → "Developing"
  - score < 60 → "Needs Work"
- Source scores come from `result.accuracy_score`, `result.completeness_score`, `result.clarity_score`
  (from `TeachbackScoreResult` in `prompts.py`)

### AC 3 — grade_teachback() builds rubric_labels dict
```python
def _label(score: float) -> str:
    if score >= 80:
        return "Strong"
    elif score >= 60:
        return "Developing"
    return "Needs Work"

rubric_labels = {
    "accuracy": _label(result.accuracy_score),
    "completeness": _label(result.completeness_score),
    "clarity": _label(result.clarity_score),
}
```
- `_label()` is a module-level private helper in `service.py` (not a method, not a lambda inline)

### AC 4 — No raw numeric scores in TeachbackResult response body
- The JSON response from `POST /api/assessment/teachback` must not contain `rubric_scores` key
- Dev 2 (Next.js) must be notified before merge (see 4-dev PR gate)

### AC 5 — Tests updated for rubric_labels
- All existing tests that assert on `TeachbackResult.rubric_scores` are updated to assert on `rubric_labels`
- New parametrized test: `test_rubric_label_thresholds` — verify all 3 threshold boundaries:
  - accuracy_score=79, completeness_score=80, clarity_score=59 → {"accuracy": "Developing", "completeness": "Strong", "clarity": "Needs Work"}
  - accuracy_score=80, completeness_score=60, clarity_score=0 → {"accuracy": "Strong", "completeness": "Developing", "clarity": "Needs Work"}
- Edge case: score exactly at boundary 80 → "Strong", exactly at 60 → "Developing"

### AC 6 — 4-dev PR review gate satisfied
- PR description explicitly calls out: "FROZEN CONTRACT CHANGE — TeachbackResult.rubric_scores → rubric_labels"
- PR must be approved by at least 1 reviewer from Dev 1, Dev 2, and Dev 4 before merge
- Dev 2 must confirm frontend is updated to use `rubric_labels` before merge

### AC 7 — OpenAPI schema reflects new field name
- After implementation, `GET /openapi.json` (or FastAPI auto-docs) shows `rubric_labels: object` in TeachbackResult
- No `rubric_scores` key present in schema

## Tasks

- [ ] Task 1: Write test_rubric_label_thresholds (RED — fails because field doesn't exist yet)
- [ ] Task 2: Update existing tests from rubric_scores to rubric_labels (RED → GREEN alignment)
- [ ] Task 3: Change `TeachbackResult.rubric_scores: dict[str, float]` → `rubric_labels: dict[str, str]` in schemas.py
- [ ] Task 4: Add `_label()` helper function in service.py
- [ ] Task 5: Update `grade_teachback()` to build `rubric_labels` dict using `_label()`
- [ ] Task 6: Run `pytest -m unit -v` — all tests green
- [ ] Task 7: Commit and open PR with "FROZEN CONTRACT CHANGE" in title
- [ ] Task 8: Tag Dev 1, Dev 2, Dev 4 for review in PR description

## Dev Notes

### This is a frozen contract shape change
Per CLAUDE.md: "All 5 assessment endpoint signatures are frozen contracts — shape changes require 4-dev PR review."
- Do NOT merge without reviews from Dev 1, Dev 2, Dev 4
- Dev 2 owns the frontend — they must update quiz/teachback UI to use `rubric_labels`
- Coordinate timing: frontend and backend must deploy together or frontend must handle both shapes

### Files to modify
| File | Change |
|------|--------|
| `apps/api/app/modules/assessment/schemas.py` | rubric_scores → rubric_labels field |
| `apps/api/app/modules/assessment/service.py` | _label() helper + build rubric_labels dict |
| `apps/api/tests/test_teachback_endpoint.py` | Update assertions + add threshold test |

### Do NOT modify
- `packages/shared/types/lesson.ts` — read-only for Dev 3
- `packages/shared/types/ws.ts` — read-only for Dev 3

### Current TeachbackScoreResult fields in prompts.py (source data)
The LLM scorer returns:
- `result.score`: overall 0–100 score
- `result.accuracy_score`: 0–100 accuracy dimension
- `result.completeness_score`: 0–100 completeness dimension
- `result.clarity_score`: 0–100 clarity dimension
- `result.praise`, `result.correction`, `result.concepts_hit`, `result.concepts_missed`

### DPDP Act 2023 rule
rubric_labels values ("Strong", "Developing", "Needs Work") are descriptive.
Do NOT use "score" language or percentages in label values. These labels comply with CLAUDE.md:
"Never return raw numeric dimension scores to students — descriptive text only."

### BMAD development sequence
1. **RED**: Write failing test (rubric_labels field doesn't exist → AttributeError or KeyError)
2. **GREEN**: Change schema + add _label() + update grade_teachback()
3. **REFACTOR**: Ensure _label() is clean, boundary conditions correct
4. **TEST**: Full suite passes
5. **COORDINATE**: Sync with Dev 2 before opening PR
6. **PR**: Mark as "FROZEN CONTRACT CHANGE", request 3 reviews (Dev 1, Dev 2, Dev 4)
7. **MERGE**: Only after all 3 approvals

---

## Dev Agent Record

### Completion Notes
_(fill after implementation)_

### File List
_(fill after implementation)_

### Change Log
- 2026-06-30: Story created (story-first gate commit)
