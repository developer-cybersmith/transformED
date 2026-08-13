---
id: demo-t28
title: "T28 (Cross-team) — Learner DNA display contract tests for Dev 2"
status: ready-for-dev
branch: dev3-demo-t28-crossteam
target_branch: master-demo-dev3
owner: Dev3
---

# T28 — Learner DNA Display Review (Cross-Team)

**As** Dev 2 building the Learner DNA profile card in the Next.js frontend,
**I need** a machine-executable HTTP contract test suite verifying every field Dev 3's API
returns to me,
**so that** I can trust the `/api/assessment/user/dna` and `/api/assessment/onboarding/submit`
responses will never silently include raw numeric scores, stale brand names, or a missing DPDP
disclaimer — the three presentation bugs that would make the student-facing screens
non-compliant with CLAUDE.md Learner DNA display rules and DPDP Act 2023.

---

## Background & Cross-Team Context

Dev 2 renders two DNA-display surfaces:
1. **Onboarding profile card** — shown immediately after `POST /onboarding/submit` returns
   `OnboardingResult.profile_text + badge_labels`.
2. **Returning-student DNA card** — shown when `GET /user/dna` returns
   `LearnerDNA.profile_text + badge_labels`.

Three compliance rules (CLAUDE.md §Dev Rules) bind both surfaces:
- **No raw numeric scores** — `OnboardingResult` and `LearnerDNA` must never expose dimension
  values (e.g. `cognitive_score`, `pattern_recognition`) to the client; descriptive text only.
- **HIE brand** — every student-facing string must say "HIE" (never "TransformED", the old
  brand). D72 was confirmed live (2026-08-13) and fixed in Story 3-54 (`6bad7a8`). This test
  suite is the CI guard that keeps it fixed.
- **DPDP disclaimer** — every `profile_text` returned to the client must end with the
  statutory disclaimer: _"This assessment reflects your personal learning preferences…
  Pursuant to DPDP Act 2023."_

Badge labels also bind a rule: plain English only — never IQ, EQ, SQ, or any clinical label.

**D72 status:** Fixed in `main` (`6bad7a8`) before this story was written. The tests in this
story form the CI guard against regression.

---

## Acceptance Criteria

### AC1 — `LearnerDNA` HTTP response has no raw numeric fields
`GET /api/assessment/user/dna` response JSON must not contain any of:
`cognitive_score`, `emotional_score`, `self_direction_score`, `pattern_recognition`,
`logical_deduction`, `processing_speed`, `frustration_tolerance`, `persistence`,
`help_seeking`, `goal_orientation`, `curiosity_index`, `study_independence`.

Verified by a test that mocks the DB row to return all nine dimension columns and asserts they
are absent from the HTTP response body.

### AC2 — `OnboardingResult` HTTP response has no raw numeric fields
`POST /api/assessment/onboarding/submit` response JSON must not contain any numeric dimension
field listed in AC1. Verified by a test that mocks the full onboarding pipeline and asserts the
201 response body.

### AC3 — `DPDP_DISCLAIMER` constant uses "HIE Learner DNA" (source-level guard)
`prompts.DPDP_DISCLAIMER` must contain the substring "HIE Learner DNA" and must not contain
the substring "TransformED". Must also contain "DPDP Act 2023".

### AC4 — `ONBOARDING_PROFILE_SYSTEM_PROMPT` uses "HIE" (source-level guard)
`prompts.ONBOARDING_PROFILE_SYSTEM_PROMPT` must contain "HIE" and must not contain
"TransformED".

### AC5 — `badge_labels` never contain IQ / EQ / SQ language
The `badge_labels` field in both response schemas must never contain any of the banned labels:
"IQ", "EQ", "SQ", "intelligence quotient", "emotional quotient". Verified by testing with a
realistic full badge set (all nine dimensions above threshold) and asserting no banned term
appears in any label string.

### AC6 — `profile_text` in `OnboardingResult` ends with the DPDP disclaimer
The `POST /api/assessment/onboarding/submit` response must have `profile_text` that ends with
`prompts.DPDP_DISCLAIMER`. The disclaimer must not be truncated.

### AC7 — `profile_text` in `LearnerDNA` ends with the DPDP disclaimer (when present)
`GET /api/assessment/user/dna` response must have `profile_text` (when non-null) ending with
`prompts.DPDP_DISCLAIMER`. Verified by seeding a DB mock row with a profile text that ends
with the disclaimer and asserting the HTTP response reflects it.

### AC8 — `GET /user/dna` returns 200 for an authenticated user with a DNA row
Smoke test: authenticated `GET /api/assessment/user/dna` returns 200 when the DB has a row for
the user.

### AC9 — `GET /user/dna` returns 404 for an authenticated user with no DNA row
Edge case: authenticated `GET /api/assessment/user/dna` returns 404 when `.maybe_single()`
returns `data=None`.

### AC10 — `LearnerDNA` response shape matches Dev 2's expected JSON schema
All fields Dev 2 renders must be present: `user_id`, `badge_labels`, `profile_text`,
`session_count`, `reassessment_due`, `last_updated`. Response must be JSON-parseable and
schema-valid against `LearnerDNA` Pydantic model.

---

## Scale & Load

1. **One unit of work:** One HTTP GET or POST request against a single authenticated user's DNA
   row. Range: always 1 DB row (`.maybe_single()`) per request. The service returns a single
   dict; no list reads are involved.

2. **Fixed budgets vs variable input:** `profile_text` is stored text from the DB (generated
   at onboarding/session time, not regenerated on read). No LLM calls at read time. The only
   variable input is the `user_id` in the JWT — one row per user, naturally bounded.

3. **Scope of limits:** Per-user. One row in `learner_dna` per user_id (unique constraint on
   `user_id`). No pagination, no fan-out.

4. **Unbounded reads/writes:** None. `.maybe_single()` returns at most one row; Pydantic
   validation rejects any extra fields.

5. **Inherited caps re-derived:** N/A — this story writes contract tests only, does not change
   any query or budget. The existing service code was reviewed in Story 3-26 and 3-54.

6. **Check-then-act concurrency:** N/A for read-only GET. POST `/onboarding/submit` already
   uses the Redis `onboarding_done` idempotency lock (Story 3-54); concurrent POST is not a
   concern for this story's HTTP contract test scope.

---

## Tasks / Subtasks

- [ ] **T1 — Write test file** `apps/api/tests/test_t28_dna_display_contract_dev2.py`
  - [ ] T1a — AC3/AC4 source-level guards: `DPDP_DISCLAIMER` contains "HIE Learner DNA", no "TransformED"; `ONBOARDING_PROFILE_SYSTEM_PROMPT` contains "HIE", no "TransformED"; both contain "DPDP Act 2023" / "HIE"
  - [ ] T1b — AC1: `GET /user/dna` response body has no raw numeric dimension keys; mock DB row explicitly containing all nine dimension columns + sub-dimensions
  - [ ] T1c — AC8/AC9/AC10: `GET /user/dna` 200 smoke + 404 for missing row + shape validation (all required fields present)
  - [ ] T1d — AC7: `GET /user/dna` `profile_text` ends with `DPDP_DISCLAIMER`
  - [ ] T1e — AC5: `badge_labels` no IQ/EQ/SQ terms (GET /user/dna path)
  - [ ] T1f — AC2: `POST /onboarding/submit` response body has no raw numeric dimension keys
  - [ ] T1g — AC6: `POST /onboarding/submit` `profile_text` ends with `DPDP_DISCLAIMER`
  - [ ] T1h — AC5: `badge_labels` no IQ/EQ/SQ terms (onboarding path)
- [ ] **T2 — Run full test suite and confirm all tests GREEN**
- [ ] **T3 — Commit + push branch; confirm story-first gate satisfied**

---

## Dev Notes

### Endpoint signatures (confirmed from `router.py`)
- `GET /api/assessment/user/dna` — `response_model=LearnerDNA`, JWT required
- `POST /api/assessment/onboarding/submit` — `response_model=OnboardingResult`, status 201, ApprovedUser (notification_preferences guard)

### Response schemas (from `schemas.py`)
```python
class LearnerDNA(BaseModel):
    user_id: str
    badge_labels: list[str]
    profile_text: str | None
    session_count: int
    reassessment_due: bool = False
    last_updated: str | None

class OnboardingResult(BaseModel):
    badge_labels: list[str]
    profile_text: str
    session_count: int
```

### Nine dimension columns in `learner_dna` table (must NOT appear in API response)
`pattern_recognition`, `logical_deduction`, `processing_speed`, `frustration_tolerance`,
`persistence`, `help_seeking`, `goal_orientation`, `curiosity_index`, `study_independence`.
These are stored in the DB but `get_learner_dna_data()` selects only:
`"user_id, badge_labels, profile_text, session_count, last_updated"` — so they are already
excluded at the query layer. AC1 tests that FastAPI/Pydantic also blocks any accidental
addition via `response_model=LearnerDNA` (it does — extra fields are stripped by `model`).

### DPDP_DISCLAIMER (from `prompts.py`)
```python
DPDP_DISCLAIMER = (
    "This assessment reflects your personal learning preferences, not your intelligence "
    "or capability. HIE Learner DNA is not a clinical assessment and does not "
    "diagnose any learning or psychological condition. — Pursuant to DPDP Act 2023."
)
```
All `profile_text` values returned to the client must end with this exact string (appended by
`generate_onboarding_profile()` and `generate_dna_profile_text()` in `prompts.py`).

### Mock pattern (follow T26's established pattern)
- Use `starlette.testclient.TestClient` (sync `def test_*`)
- JWT: `"app.modules.assessment.router.get_current_user"` → returns `{"sub": "<user_id>"}` (CurrentUser)
- ApprovedUser guard: `"app.modules.assessment.router.get_approved_user"` → returns same dict + `"email": "test@example.com"`
- DB: `"app.core.db.get_supabase"` → MagicMock
- For `get_learner_dna_data` (service layer): mock `"app.modules.assessment.service.get_learner_dna_data"` returning a dict
- For onboarding: mock `"app.modules.assessment.service.process_onboarding"` returning an `OnboardingResult`
- Redis: `"app.core.redis.get_redis"` → MagicMock or raises Exception (test both paths)

### Notification preference guard (onboarding endpoint)
`POST /onboarding/submit` uses `ApprovedUser` which checks notification preferences via
`get_approved_user`. Follow the T26 pattern: define `_approved_client` with a mocked
`get_approved_user` dependency override.

### Lazy import mock paths (critical — from T26 lessons learned)
Handlers use `from app.modules.assessment.service import ...` inside the handler body.
Patch at the **service module** path, not the router path:
- `"app.modules.assessment.service.get_learner_dna_data"` (not `router.get_learner_dna_data`)
- `"app.modules.assessment.service.process_onboarding"` (not `router.process_onboarding`)
Also patch `"app.modules.assessment.service.get_analytics_consent"` for GET /user/dna.

### Key test invariants
- AC1/AC2: iterate over `_RAW_DIMENSION_KEYS` list and assert `key not in resp.json()` for
  each — this is NOT vacuously true because we explicitly include all nine keys in the mocked
  service return dict, then assert FastAPI strips them.
- AC3/AC4: import directly from prompts module — `from app.modules.assessment.prompts import
  DPDP_DISCLAIMER, ONBOARDING_PROFILE_SYSTEM_PROMPT`; no HTTP call needed.
- AC5: Define `_BANNED_BADGE_TERMS = {"IQ", "EQ", "SQ", "intelligence quotient", "emotional quotient"}`
  and check each badge label's lowercased form.
- AC6/AC7: `assert resp.json()["profile_text"].endswith(DPDP_DISCLAIMER)`

---

## Dev Agent Record

### Debug Log
*(empty)*

### Completion Notes
*(empty)*

### File List
*(to be filled during implementation)*

### Change Log
*(to be filled during implementation)*

---

## Senior Developer Review (AI)
*(to be filled after /bmad-code-review)*
