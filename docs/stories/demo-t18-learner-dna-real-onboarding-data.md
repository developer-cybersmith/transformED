# Demo T18 — Learner DNA profile generation with real onboarding data

**Status:** in-progress
**Sprint:** Demo Sprint
**Owner:** Dev 3
**Branch:** `dev3-demo-t18-phaseL5`
**Depends on:** T15 (real schema fixture pattern), T16 (UUID chain pattern established)

---

## Problem Statement

Prior onboarding tests use minimal `OnboardingAnswer` fixtures: sometimes just 1–3
responses, generic question_ids ("q1", "q2"), and dimension values that don't match
the live 20-question form ("cognitive", "emotional", "self_direction"). These tests
pass but never exercise the real mapping path:

  real question_ids (c1–c8, e1–e5, s1–s7)
    → `QUESTION_SUBDIMENSION_MAP`
      → 9 sub-dimension scores
        → `BADGE_THRESHOLDS` badge labels
          → `generate_onboarding_profile(badge_labels, provider)`
            → profile_text with DPDP_DISCLAIMER appended

T18 validates this full chain with the exact question_ids, dimension tags, and scoring
formula that the live onboarding form produces. It also guards the D72 fix (HIE
rebrand) against regression at every point where "TransformED" could resurface.

---

## User Story

As a student completing onboarding, when I submit my 20 answers, the system correctly
maps my responses to sub-dimension scores, awards earned badges, generates a profile
that uses the HIE brand name, and returns only my badge labels and profile text — never
raw numeric scores.

---

## Acceptance Criteria

**AC1 — `_compute_dimension_scores()` maps real question_ids to correct sub-dimensions:**
Given 20 `OnboardingAnswer` objects using real question_ids (c1–c8, e1–e5, s1–s7) and
`selected_index=3`, `_compute_dimension_scores()` returns a dict with all 9
sub-dimension keys. Spot checks:
- `pattern_recognition` = 100.0 (questions c1, c5, c8 all at index 3 → (3/3)×100=100.0, mean=100.0)
- `logical_deduction` = 100.0 (questions c2, c3, c7 → same formula)
- `persistence` = 100.0 (question e2 alone → 100.0)

**AC2 — `_compute_badge_labels()` returns plain-English labels with no IQ/EQ/SQ language:**
Given all 9 dimensions at 100.0 (above BADGE_THRESHOLD=70.0), `_compute_badge_labels()`
returns a list containing "Pattern Thinker" and no label containing "IQ", "EQ", or "SQ".

**AC3 — `process_onboarding()` upsert row contains all 9 dimension scores + profile_text:**
`process_onboarding()` with 20 real responses writes a `learner_dna` upsert row that
contains all 9 sub-dimension keys (pattern_recognition, logical_deduction,
processing_speed, frustration_tolerance, persistence, help_seeking, goal_orientation,
curiosity_index, study_independence) and `profile_text` ending with the DPDP disclaimer.
Test: spy on `supabase.table("learner_dna").upsert()` to capture the row; assert all 9
keys present and `dna_row["profile_text"].endswith(DPDP_DISCLAIMER)`.

**AC4 — `DPDP_DISCLAIMER` uses "HIE", not "TransformED" (D72 regression guard):**
`DPDP_DISCLAIMER` in `prompts.py` contains the substring "HIE" and does not contain
the substring "TransformED". No mocking required — direct import and string assertion.

**AC5 — `generate_onboarding_profile()` receives non-empty badge_labels when scores are high:**
When all 9 dimension scores are >= BADGE_THRESHOLD (70.0), `generate_onboarding_profile`
is called with a non-empty `badge_labels` list (at least 1 element). This prevents the
"no badges" fallback prompt path from silently masking a scoring error.
Test: spy on `generate_onboarding_profile`; assert `len(captured["badge_labels"]) >= 1`.

**AC6 — `OnboardingResult` exposes no raw dimension scores to the caller:**
The `OnboardingResult` returned by `process_onboarding()` has exactly three fields:
`badge_labels`, `profile_text`, `session_count`. No raw numeric dimension scores
(e.g., `pattern_recognition`, `logical_deduction`) appear on the result object.
Test: assert `not hasattr(result, "pattern_recognition")`.

**AC7 — `_compute_dimension_scores()` returns 0.0 for a dimension with no matching responses:**
`persistence` maps exclusively to question `e2`. If `e2` is removed from the 20-response
set, the returned scores dict has `persistence == 0.0` (mean of empty list → 0.0 default).
Test: 19-answer fixture (e2 removed) → `scores["persistence"] == 0.0`.

**AC8 — `_compute_badge_labels()` returns [] when all dimension scores are below threshold:**
Given all 20 responses with `selected_index=0` → all scores 0.0 → no scores meet the
70.0 threshold → `badge_labels == []`.

**AC9 — `ONBOARDING_PROFILE_SYSTEM_PROMPT` uses "HIE", not "TransformED" (D72 regression guard):**
`ONBOARDING_PROFILE_SYSTEM_PROMPT` in `prompts.py` contains "HIE" and does not contain
"TransformED". Direct import assertion — no mocking required.

---

## Scale & Load

**Q1 — ONE unit of work and its range:**
One unit = one `process_onboarding()` call = 20 `onboarding_responses` rows + 1 LLM call
+ 1 `learner_dna` upsert. All tests are @pytest.mark.unit with mocked DB and LLM —
no new real I/O introduced. Range is deterministic.

**Q2 — Fixed budgets while input varies:**
`OnboardingDiagnosticSubmission` enforces `min_length=20, max_length=20` at the Pydantic
layer — the 20-response limit is fixed. The `_compute_dimension_scores` bucket covers
exactly 9 dimensions. No silent truncation: questions not in `QUESTION_SUBDIMENSION_MAP`
are silently skipped (no error), which is existing documented behaviour, not new.

**Q3 — Scope of every limit:**
- 20-question bound: per-user, per-submission (Pydantic schema enforces it)
- 9-dimension output: fixed set from `ALL_NINE_DIMENSIONS` constant
- These tests add no new limits.

**Q4 — Unbounded reads/writes:**
None introduced. This is a tests-only diff.

**Q5 — Inherited caps re-derived:**
No caps inherited by this story. The 20-question limit was established in Story 3-18.

**Q6 — Check-then-act concurrency:**
No new check-then-act sequences. The Redis idempotency guard on onboarding is already
tested in `test_onboarding_endpoint.py` and `test_onboarding_llm_failure.py`.

---

## Technical Requirements

- File: `apps/api/tests/test_learner_dna_real_onboarding.py` (new)
- 9 tests: AC1 through AC9
- Helper: `_build_real_onboarding_responses(selected_index: int = 3) -> list[OnboardingAnswer]`
  — 20 `OnboardingAnswer` objects with real question_ids (c1–c8, e1–e5, s1–s7)
- Tests for AC1, AC2, AC7, AC8: call `_compute_dimension_scores` and `_compute_badge_labels` directly
  (imported from `app.modules.assessment.service`); no DB or LLM mocking needed
- Tests for AC4, AC9: import `DPDP_DISCLAIMER` and `ONBOARDING_PROFILE_SYSTEM_PROMPT`
  from `app.modules.assessment.prompts`; no mocking needed
- Tests for AC3, AC5, AC6: call `process_onboarding()` with mocked supabase + mocked
  `generate_onboarding_profile`

### Real onboarding response fixture:
```python
def _build_real_onboarding_responses(selected_index: int = 3) -> list[OnboardingAnswer]:
    questions = [
        # Cognitive — 8
        ("c1", "cognitive"), ("c2", "cognitive"), ("c3", "cognitive"), ("c4", "cognitive"),
        ("c5", "cognitive"), ("c6", "cognitive"), ("c7", "cognitive"), ("c8", "cognitive"),
        # Emotional — 5
        ("e1", "emotional"), ("e2", "emotional"), ("e3", "emotional"),
        ("e4", "emotional"), ("e5", "emotional"),
        # Self-direction — 7
        ("s1", "self_direction"), ("s2", "self_direction"), ("s3", "self_direction"),
        ("s4", "self_direction"), ("s5", "self_direction"), ("s6", "self_direction"),
        ("s7", "self_direction"),
    ]
    return [
        OnboardingAnswer(question_id=qid, dimension=dim, selected_index=selected_index,
                         selected_text="Option C", response_time_ms=1500)
        for qid, dim in questions
    ]
```

### Supabase mock for process_onboarding (AC3, AC5, AC6):
```
2-call order: onboarding_responses(insert) → learner_dna(upsert)
insert: .insert().execute().error = None
upsert: capture the row via side_effect spy; .execute().error = None
```

### generate_onboarding_profile spy (AC5):
```python
captured = {}
async def _spy_generate(*, badge_labels, provider):
    captured["badge_labels"] = badge_labels
    return f"Profile text.\n\n{DPDP_DISCLAIMER}"
monkeypatch.setattr("app.modules.assessment.service.generate_onboarding_profile", _spy_generate)
```

### Expected score for selected_index=3 (all questions):
- normalized = (3/3) × 100 = 100.0 for every response
- All 9 dimensions → 100.0 (mean of all 100.0)
- All 9 badges awarded (100.0 >= 70.0 threshold)

### Expected score for selected_index=0 (all questions):
- normalized = (0/3) × 100 = 0.0 for every response
- All 9 dimensions → 0.0
- No badges awarded (0.0 < 70.0 threshold)

---

## Dependencies

- `app.modules.assessment.service._compute_dimension_scores` (private, importable in tests)
- `app.modules.assessment.service._compute_badge_labels` (private, importable in tests)
- `app.modules.assessment.service.process_onboarding` (public)
- `app.modules.assessment.prompts.DPDP_DISCLAIMER`
- `app.modules.assessment.prompts.ONBOARDING_PROFILE_SYSTEM_PROMPT`
- `app.modules.assessment.schemas.OnboardingAnswer`, `OnboardingResult`
- `app.modules.assessment.onboarding_questions.QUESTION_SUBDIMENSION_MAP`, `ALL_NINE_DIMENSIONS`,
  `BADGE_THRESHOLD`, `BADGE_THRESHOLDS`
- No new migrations, no service.py changes — tests-only diff

---

## Tasks / Subtasks

- [ ] **T1 — RED: write 9 failing tests (one per AC)**
- [ ] **T2 — GREEN: confirm all 9 tests pass (no implementation changes needed)**
- [ ] **T3 — VERIFY: run full assessment test suite, confirm no regressions**
- [ ] **T4 — UPDATE dev3-assessment-tracker.md**

---

## Dev Notes

### Why test private functions directly?
`_compute_dimension_scores` and `_compute_badge_labels` are tested in isolation (AC1,
AC2, AC7, AC8) because they are the mapping kernel — if the mapping is wrong, the LLM
receives the wrong badge_labels and the profile text is silently meaningless. A service-
level test that only checks the final `OnboardingResult` would not catch a mapping bug
that affects which badges are awarded.

### process_onboarding() call order (3 DB calls):
1. `onboarding_responses.insert(rows).execute()` → mock `error = None`
2. LLM: `generate_onboarding_profile(badge_labels, provider)` → mocked via monkeypatch
3. `learner_dna.upsert(dna_row, on_conflict="user_id").execute()` → spy to capture row

Plus `get_analytics_consent(user_id, supabase)` → autouse mock returns False.

### DPDP_DISCLAIMER structure (post-D72):
```
"This assessment reflects your personal learning preferences, not your intelligence
or capability. HIE Learner DNA is not a clinical assessment and does not diagnose
any learning or psychological condition. — Pursuant to DPDP Act 2023."
```

### Scoring formula verification (AC1):
- `c1 → pattern_recognition`: (3/3)×100 = 100.0
- `c5 → pattern_recognition`: (3/3)×100 = 100.0
- `c8 → pattern_recognition`: (3/3)×100 = 100.0
- Mean = 100.0 → `scores["pattern_recognition"] == 100.0`
- `e2 → persistence` (only question): mean of [100.0] = 100.0

---

## Dev Agent Record

### Completion Notes
*To be filled on completion.*

### Debug Log
*Empty.*

---

## Change Log

| Date | Change |
|---|---|
| 2026-08-13 | Story created (story-first gate) |
