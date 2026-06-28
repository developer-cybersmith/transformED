---
baseline_commit: 544331c788fa102e0d602d6374116fbf025f55c6
---

# Story 3.1: Assessment Module Stub — Five Endpoints, All PRD Model Violations Fixed

Status: done

---

## Story

As Dev 3 (tannmayygupta),
I want the five assessment API endpoints scaffolded as FastAPI stubs with all Pydantic models correctly typed and PRD-compliant,
so that Dev 2 (frontend) has stable OpenAPI contracts to code against during Sprint 0.

---

## Acceptance Criteria

1. `POST /api/assessment/quiz` endpoint exists and returns HTTP 501 NOT_IMPLEMENTED for any valid request body.
2. `POST /api/assessment/teachback` endpoint exists and returns HTTP 501 NOT_IMPLEMENTED for any valid request body.
3. `GET /api/assessment/session/{session_id}/report` endpoint exists and returns HTTP 501 NOT_IMPLEMENTED.
4. `GET /api/assessment/user/dna` endpoint exists and returns HTTP 501 NOT_IMPLEMENTED.
5. `POST /api/assessment/onboarding/submit` endpoint exists and returns HTTP 501 NOT_IMPLEMENTED.
6. `TeachbackSubmission` Pydantic model has field `response_text: str` — typed teach-back is always text, no STT allowed.
7. `TeachbackSubmission` does NOT have a `transcript` field — field name `transcript` implies STT which is banned.
8. `TeachbackSubmission` does NOT have a `duration_seconds` field — adding a timer creates test anxiety (banned per CLAUDE.md).
9. `QuizSubmission` has `segment_id: str` field — quiz grading is per-segment.
10. `QuizAnswer` is a fully typed Pydantic model with `question_id: str`, `response_index: int`, `response_time_ms: int` fields.
11. `LearnerDNA` response model has `badge_labels: list[str]` and `profile_text: str | None` fields.
12. `LearnerDNA` response model does NOT expose any raw numeric dimension score fields (no `iq_*`, `eq_*`, `sq_*`, `raw_score`, `dimension_score` fields).
13. `OnboardingDiagnosticSubmission` has `responses: list[OnboardingAnswer]` — NOT `subject` or `grade_level` top-level fields.
14. No IQ/EQ/SQ language appears anywhere in model names, field names, or inline code comments.
15. The assessment router is registered in `apps/api/app/main.py` under prefix `/api/assessment`.
16. All five CES weight fields exist in `apps/api/app/config.py`: `ces_weight_quiz=0.35`, `ces_weight_teachback=0.25`, `ces_weight_behavioral=0.20`, `ces_weight_head_pose=0.12`, `ces_weight_blink=0.08`.
17. Endpoint summaries do not use the word "transcript" (which implies STT — banned in MVP).

---

## Tasks / Subtasks

- [x] Task 1: Scaffold assessment router with all 5 stubs (AC: #1–#5, #15) — ✓ 2026-06-17
  - [x] 1.1 Create `apps/api/app/modules/assessment/router.py`
  - [x] 1.2 Register router in `apps/api/app/main.py` under prefix `/api/assessment`
  - [x] 1.3 Verify all 5 routes raise `HTTPException(status_code=501)`

- [x] Task 2: Define PRD-compliant Pydantic request/response models (AC: #6–#14, #17) — ✓ 2026-06-17
  - [x] 2.1 `QuizAnswer` — `question_id: str`, `response_index: int`, `response_time_ms: int`
  - [x] 2.2 `QuizSubmission` — `session_id`, `lesson_id`, `segment_id`, `answers: list[QuizAnswer]`
  - [x] 2.3 `TeachbackSubmission` — `session_id`, `lesson_id`, `segment_id`, `response_text: str` (no `transcript`, no `duration_seconds`)
  - [x] 2.4 `LearnerDNA` — `badge_labels: list[str]`, `profile_text: str | None`, no raw dimension scores
  - [x] 2.5 `OnboardingDiagnosticSubmission` — `responses: list[OnboardingAnswer]`
  - [x] 2.6 Scan for any IQ/EQ/SQ language — none found

- [x] Task 3: Confirm CES weights in config.py (AC: #16) — ✓ 2026-06-17
  - [x] 3.1 Verify `ces_weight_quiz=0.35`, `ces_weight_teachback=0.25`, `ces_weight_behavioral=0.20`, `ces_weight_head_pose=0.12`, `ces_weight_blink=0.08`
  - [x] 3.2 Confirm `ces_threshold=50.0` is present

- [x] Task 4: Retroactive BMAD documentation + unit tests (AC: all) — ✓ 2026-06-26
  - [x] 4.1 Fix "transcript" wording in endpoint summary (was "Submit a teach-back transcript for LLM evaluation" — changed to "typed teach-back response")
  - [x] 4.2 Write `apps/api/tests/test_assessment_stub_contracts.py` with 10 `@pytest.mark.unit` tests
  - [x] 4.3 Fix UTF-8 BOM in `apps/api/pyproject.toml` (was causing pytest exit code 4)
  - [x] 4.4 Fix smart/curly quotes in `apps/api/pyproject.toml` (was causing TOML parse error at line 17)
  - [x] 4.5 Run `pytest tests/test_assessment_stub_contracts.py -v -m unit` — 10 passed, 0 failed

---

## Dev Notes

### Router Design

The assessment router (`apps/api/app/modules/assessment/router.py`) is a pure Sprint 0 stub. All five endpoints accept well-typed request bodies and have well-typed response models, but each raises `HTTPException(status_code=501)` immediately. This approach:

- Generates a complete, correct OpenAPI schema at `/docs` for Dev 2 (frontend) to code against
- Validates incoming request shapes against the Pydantic models (400 errors on malformed requests before hitting the stub)
- Has zero business logic to misimplement in Sprint 0

### PRD Rules Implemented

| Rule | Implementation |
|---|---|
| No STT — typed teach-back only | `response_text: str` field; no `transcript` field; endpoint summary says "typed" not "transcript" |
| No teach-back timer | No `duration_seconds` field on `TeachbackSubmission` |
| No IQ/EQ/SQ language | Scanned all model names, field names, comments — clean |
| No raw dimension scores exposed | `LearnerDNA` has only `badge_labels` and `profile_text` for student-facing data |
| `OnboardingDiagnosticSubmission` shape | `responses: list[OnboardingAnswer]` — per-answer model, not flat subject/grade_level fields |

### Model Hierarchy

```
QuizSubmission
  └── answers: list[QuizAnswer]
        ├── question_id: str
        ├── response_index: int
        └── response_time_ms: int (default 0)

TeachbackSubmission
  ├── session_id: str
  ├── lesson_id: str
  ├── segment_id: str
  └── response_text: str  ← typed text only, no STT

LearnerDNA (response)
  ├── user_id: str
  ├── badge_labels: list[str]  ← plain English labels
  ├── profile_text: str | None ← DPDP disclaimer appended at generation time
  ├── session_count: int
  ├── reassessment_due: bool
  └── last_updated: str | None

OnboardingDiagnosticSubmission
  └── responses: list[OnboardingAnswer]
        ├── question_id: str
        ├── dimension: str
        ├── selected_index: int
        └── selected_text: str
```

### CES Weights in Config

All five CES weight fields confirmed in `apps/api/app/config.py`:
- `ces_weight_quiz: float = 0.35`
- `ces_weight_teachback: float = 0.25`
- `ces_weight_behavioral: float = 0.20`
- `ces_weight_head_pose: float = 0.12`
- `ces_weight_blink: float = 0.08`
- `ces_threshold: float = 50.0`

These are env-var driven (pydantic-settings), tunable post-calibration without code changes.

### Router Registration

`apps/api/app/main.py` line 99:
```python
app.include_router(assessment_router, prefix="/api/assessment")
```

All five routes are reachable under `/api/assessment/...`.

---

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6 (retroactive documentation 2026-06-26; original implementation 2026-06-17)

### Debug Log References

- **Issue 1: Endpoint summary used "transcript"** — `submit_teachback` had summary "Submit a teach-back transcript for LLM evaluation". Fixed to "Submit a typed teach-back response for LLM evaluation". The word "transcript" implies STT which is banned per CLAUDE.md.
- **Issue 2: pyproject.toml had UTF-8 BOM** — File started with `EF BB BF` byte-order mark. This caused pytest exit code 4 with "Invalid statement (at line 1, column 1)". Fixed by rewriting file without BOM using `UTF8Encoding(false)`.
- **Issue 3: pyproject.toml had smart/curly quotes** — Unicode curly quotes (`“`, `”`) appeared around dependency strings (e.g., `"supabase>=2.4.0"` used smart quotes). This caused TOML parse error "Invalid value (at line 17, column 5)". Fixed by replacing all curly quotes with straight ASCII double quotes.
- **Issue 4: Endpoint tests got 403 instead of 501** — The `CurrentUser` dependency requires a valid JWT Bearer token. TestClient with no auth header triggers 403 before reaching the route handler. Fixed by overriding `get_current_user` dependency in the test app with `_fake_user()`.

### Completion Notes List

- All 5 endpoints confirmed present: `/quiz`, `/teachback`, `/session/{id}/report`, `/user/dna`, `/onboarding/submit`
- All 5 endpoints return HTTP 501 (verified by TestClient with mocked auth)
- `TeachbackSubmission.response_text` present; `transcript` and `duration_seconds` absent
- `QuizSubmission.segment_id` present
- `QuizAnswer` fully typed with 3 required fields
- `LearnerDNA` has `badge_labels` and `profile_text`; no raw score fields
- `OnboardingDiagnosticSubmission.responses` is `list[OnboardingAnswer]`
- No IQ/EQ/SQ language in any model names, field names, or comments
- Assessment router registered in `main.py` at `prefix="/api/assessment"`
- All 5 CES weight fields present in `config.py` at correct PRD values
- `pytest tests/test_assessment_stub_contracts.py -v -m unit` — **10 passed, 0 failed**
- Fixed pyproject.toml BOM issue (affected all pytest runs in this project)
- Fixed pyproject.toml smart quote encoding issue

### File List

- `apps/api/app/modules/assessment/router.py` — CREATED (Sprint 0, original implementation 2026-06-17); MODIFIED (2026-06-26: fixed "transcript" in endpoint summary)
- `apps/api/tests/test_assessment_stub_contracts.py` — CREATED (retroactive 2026-06-26)
- `apps/api/pyproject.toml` — MODIFIED (2026-06-26: removed UTF-8 BOM, replaced smart quotes with ASCII quotes)

### Change Log

| Date | Change | Reason |
|---|---|---|
| 2026-06-17 | Created assessment router with 5 stub endpoints | Sprint 0 contract requirement |
| 2026-06-26 | Fixed "transcript" in teachback endpoint summary | STT language ban per CLAUDE.md |
| 2026-06-26 | Fixed pyproject.toml BOM + smart quotes | pytest could not parse TOML file |
| 2026-06-26 | Created test_assessment_stub_contracts.py | Retroactive BMAD story lifecycle |

---

## Senior Developer Review (AI)

**Reviewer:** claude-sonnet-4-6 · **Date:** 2026-06-26 · **Outcome:** Approved

### Action Items

| Severity | Finding | Resolution |
|---|---|---|
| FIXED | Endpoint summary `submit_teachback` used "transcript" implying STT | Changed to "typed teach-back response" |
| INFO | `pyproject.toml` had UTF-8 BOM and smart/curly quotes causing pytest failures | Fixed — BOM removed, straight ASCII quotes substituted |
| PASS | All Pydantic model field contracts are PRD-compliant | No action required |
| PASS | No IQ/EQ/SQ language in any model or comment | No action required |
| PASS | `LearnerDNA` exposes only descriptive fields, no numeric dimension scores | No action required |
| PASS | Assessment router registered in `main.py` under correct prefix | No action required |
| PASS | All 5 CES weights present in `config.py` at correct PRD values | No action required |
| PASS | All 5 endpoints return 501 (confirmed by 10 unit tests, all green) | No action required |
