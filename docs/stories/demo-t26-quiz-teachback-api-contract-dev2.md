---
status: done
baseline_commit: 5b33523
---

# Story: Demo T26 Phase L8 — Quiz/Teachback API Contract Review with Dev 2

**Story ID:** demo-t26
**Phase:** L8 (HTTP contract validation layer)
**Branch:** `dev3-demo-t26-phaseL8` → PR targets `master-demo-dev3`
**Date:** 2026-08-13
**Owner:** Dev 3 (tannmayygupta)

---

## User Story

**As** Dev 2 (lesson player developer),
**I want** a machine-verifiable specification of every HTTP payload shape, validation rule, and response field for the assessment API,
**So that** I can integrate the lesson player with confidence that the exact JSON I send and receive is tested and contractually guaranteed.

---

## Background

The five assessment endpoints are a frozen 4-dev contract (CLAUDE.md §16). Dev 2's lesson player must:

1. Start a session (`POST /sessions`) **once per lesson attempt** — before any quiz or teach-back submission.
2. Submit quiz answers per segment (`POST /quiz`).
3. Submit typed teach-back responses per segment (`POST /teachback`).
4. Handle the exact response shapes: `QuizResult.feedback: list[dict]` and `TeachbackResult.rubric_scores: dict[str, str]`.

Existing tests cover model-field presence and service-layer behaviour. They do **not** cover HTTP-layer 422 validation or the boundary conditions Dev 2 needs to know about. T26 closes that gap: a dedicated HTTP-level contract test file that acts as the machine-executable Dev 2 integration guide.

---

## Acceptance Criteria

### AC1 — POST /sessions: lesson_id-only contract

**Given** Dev 2 sends `POST /api/assessment/sessions` with `{"lesson_id": "lesson-uuid"}` and a valid JWT,
**Then** the server returns `201 Created` with `{session_id, lesson_id, started_at}`.

**Given** Dev 2 accidentally includes `user_id` in the body `{"lesson_id": "...", "user_id": "attacker-id"}`,
**Then** the server ignores `user_id` silently (Pydantic extra-field ignore), creates the session with the JWT user's ID, and returns HTTP 201 — NOT 422.

**Given** Dev 2 omits `lesson_id` entirely from the body,
**Then** the server returns HTTP 422 (Pydantic validation failure — required field missing).

### AC2 — POST /quiz: answer list bounds and field validation

**Given** Dev 2 sends `answers: []` (empty list),
**Then** the server returns HTTP 422 (`min_length=1` violated).

**Given** Dev 2 sends `answers` with 51 items,
**Then** the server returns HTTP 422 (`max_length=50` violated).

**Given** Dev 2 sends a `QuizAnswer` with `response_index: -1`,
**Then** the server returns HTTP 422 (`ge=0` violated).

**Given** Dev 2 sends a `QuizAnswer` with `response_time_ms: -1`,
**Then** the server returns HTTP 422 (`ge=0` violated).

**Given** Dev 2 sends a `QuizAnswer` that omits `response_time_ms` entirely,
**Then** the server accepts the payload (default=0 applies) — HTTP 200, no 422.

### AC3 — POST /quiz: response shape (QuizResult.feedback is list)

**Given** a valid quiz submission is processed,
**Then** the response body contains `feedback` as a **list** (not a string, not a single dict).
Dev 2 must iterate `feedback`, not access it as `.feedback[0]` or `.feedback.message`.

### AC4 — POST /teachback: response_text bounds and banned field behaviour

**Given** Dev 2 sends `response_text: ""` (empty string),
**Then** the server returns HTTP 422 (`min_length=1` violated).

**Given** Dev 2 sends `response_text` longer than 4000 characters,
**Then** the server returns HTTP 422 (`max_length=4000` violated).

**Given** Dev 2 sends a `transcript` field alongside a valid `response_text`,
**Then** the server accepts the payload without 422 (`transcript` is silently ignored — Pydantic extra-field discard) and `transcript` is NOT passed to the scoring service.

**Given** Dev 2 sends a `duration_seconds` field alongside a valid `response_text`,
**Then** the server accepts the payload without 422 (`duration_seconds` silently ignored) and `duration_seconds` does NOT appear in any response field.

### AC5 — POST /teachback: response shape (TeachbackResult.rubric_scores values are str)

**Given** a valid teach-back submission is processed,
**Then** `rubric_scores` in the response is `dict[str, str]` — the values are descriptive label strings (e.g. `"Excellent"`, `"Needs work"`), NOT floats.
Dev 2 must render `rubric_scores` values as text, never as numbers.

### AC6 — POST /teachback: ApprovedUser gate (403 for non-approved email)

**Given** Dev 2's JWT has an email that is NOT on the approved list,
**Then** `POST /teachback` returns HTTP 403 (the `ApprovedUser` dependency rejects the request before the route handler runs).

> **Dev 2 integration note:** The approved email list is configured via env var `APPROVED_EMAILS`. For the demo, Dev 2's test account email must be on this list. Coordinate with the project lead to confirm the email is registered. Dev 3 does not own this list.

### AC7 — Extra fields silently ignored on all POST endpoints

**Given** Dev 2 sends an extra field (`client_timestamp`, `device_id`, `user_agent`) in any POST body,
**Then** the server returns 200/201 (not 422) — Pydantic ignores unknown fields by default.
Dev 2 does not need to strip client-side metadata from payloads before sending.

### AC8 — POST /sessions security invariant: user_id from body is never trusted

This is a named security assertion (separate test from AC1) with an explicit security comment so it is independently auditable. The test must assert both that the HTTP response is 201 **and** that the session service was called with the JWT user's ID, not the body's `user_id`.

---

## Scale & Load

1. **One unit of work:** One HTTP round-trip to one endpoint (sessions/quiz/teachback). These tests mock the service layer entirely — no DB reads/writes or LLM calls from the test execution itself.

2. **Fixed budgets while input varies:** Pydantic bounds are the budgets being tested: `answers min=1, max=50`; `response_text min=1, max=4000`. Both boundaries are exercised at the extreme values (0, 1, 50, 51; 0, 1, 4000, 4001 chars). Silent truncation is not possible at the Pydantic layer — it raises 422 or passes, never silently clips.

3. **Scope of every limit:** Pydantic validation is per-request, stateless. `min_length` / `max_length` apply identically across all users, instances, and replicas. No per-user or per-deployment scope issues.

4. **Unbounded reads/writes:** None. Tests mock the service layer. No unbounded queries introduced. `test_unbounded_queries.py` CI guard already covers the production router.py and service.py — no new source file paths need to be added for the new test file (test files are not in the guard's REQUEST_PATH_FILENAMES scope by design).

5. **Inherited caps re-derived:** `answers: max_length=50` was set in Sprint 1 when a typical lesson segment had ≤10 MCQ questions. A segment has at most 10 questions (confirmed by LessonPackage schema). Cap is 5× the actual maximum — still valid. `response_text: max_length=4000` sized for a ≤500-word typed response. Both caps remain valid and do not need re-derivation.

6. **Check-then-act concurrency:** Not applicable — these are HTTP validation tests. No check-then-act sequences introduced. Production concurrency is covered by existing service-layer tests.

---

## Technical Requirements

### Test file location
`apps/api/tests/test_t26_api_contract_dev2.py` — **new file**, do not modify existing test files.

### Framework and marks
- pytest + `starlette.testclient.TestClient`
- All tests marked `@pytest.mark.unit` — no external services, no LLM calls, no DB
- `asyncio_mode=auto` is configured in `pyproject.toml` — use `async def` if needed; do NOT call `asyncio.get_event_loop().run_until_complete()` (D95 (was D76) — Python 3.12 incompatible)

### Dependency override pattern
Follow the exact pattern from `tests/test_teachback_endpoint.py`:

```python
from app.dependencies import get_current_user, get_settings

async def _fake_user():
    return {"sub": "user-001", "email": "test@example.com"}

def _fake_settings_approved():
    settings = MagicMock()
    settings.approved_emails = ["test@example.com"]
    return settings

def _fake_settings_not_approved():
    settings = MagicMock()
    settings.approved_emails = []
    return settings
```

Create separate `TestClient` instances for approved vs. non-approved teachback tests — do NOT reuse a single `_app` with different settings across test functions. Each client is module-level.

### Service mock pattern
For tests covering response shapes (AC3, AC5), mock the service functions at the module level to return controlled output:

```python
# For grade_quiz response shape test:
with patch("app.modules.assessment.router.grade_quiz") as mock:
    mock.return_value = QuizResult(
        session_id="sess-001", score=80.0, correct_count=4, total_count=5,
        ces_contribution=28.0,
        feedback=[{"question_id": "q1", "correct": True, "explanation": "Good"}],
    )
    resp = client.post("/api/assessment/quiz", json=_VALID_QUIZ_PAYLOAD)

# For grade_teachback response shape test:
with patch("app.modules.assessment.router.grade_teachback") as mock:
    mock.return_value = TeachbackResult(
        session_id="sess-001",
        rubric_scores={"accuracy": "Excellent", "completeness": "Good", "clarity": "Excellent"},
        overall_score=88.0, ces_contribution=22.0,
        feedback="Great explanation! You correctly identified the key concept.",
    )
    resp = client.post("/api/assessment/teachback", json=_VALID_TEACHBACK_PAYLOAD)
```

### Forbidden patterns
- Do NOT call real service functions — mock them for response-shape tests
- Do NOT add `transcript`, `duration_seconds`, `user_id`, `session_id`, or `started_at` to schema as new fields
- Do NOT modify `router.py` or `schemas.py` — this story adds tests only
- Do NOT use `asyncio.get_event_loop().run_until_complete()` — D95 (was D76)

### Response shape assertions
AC3 (feedback is list):
```python
assert isinstance(response.json()["feedback"], list), (
    "QuizResult.feedback must be list[dict] — Dev 2 must iterate it, "
    "not access as string or single dict"
)
```

AC5 (rubric_scores values are str):
```python
rubric = response.json()["rubric_scores"]
assert isinstance(rubric, dict)
for key, val in rubric.items():
    assert isinstance(val, str), (
        f"rubric_scores['{key}'] must be a string label, not a numeric score — "
        "Dev 2 must render these as text (B5, Story 3-14)"
    )
```

### Security assertion (AC8)
```python
def test_user_id_body_field_never_trusted():
    """Security invariant: user_id from body is silently discarded.
    
    Dev 2 cannot inject a different user_id via the request body —
    the session is always created under the JWT user's sub.
    """
    with patch("app.modules.assessment.router.create_session") as mock:
        mock.return_value = {"session_id": "s1", "lesson_id": "l1", "started_at": None}
        resp = sessions_client.post(
            "/api/assessment/sessions",
            json={"lesson_id": "l1", "user_id": "attacker-id"},
        )
    assert resp.status_code == 201
    _, kwargs = mock.call_args
    assert kwargs.get("user_id") != "attacker-id", (
        "Security: user_id from body must never be passed to create_session"
    )
    assert kwargs.get("user_id") == "user-001"  # JWT sub, not body value
```

---

## Dev Notes

### What this story is and is not
- **IS:** HTTP-level contract validation from Dev 2's perspective — what 422 errors to expect, what response shapes to handle, what fields are silently ignored or banned.
- **IS NOT:** Business logic testing (covered in `test_quiz_endpoint.py`, `test_teachback_endpoint.py`), service-layer testing, or integration testing requiring a real DB.

### ApprovedUser dependency internals
`POST /teachback` uses `ApprovedUser` (not `CurrentUser`). Looking at `app/dependencies.py` line 162: `if not email or email.lower() not in settings.approved_emails: raise 403`. The check uses `settings.approved_emails` from the app's settings object. The override pattern is:
- Override `get_settings` to return a mock with `approved_emails = ["test@example.com"]` for the happy path
- Override `get_settings` to return a mock with `approved_emails = []` for the 403 path

### Pydantic extra-field behaviour
FastAPI's Pydantic v2 uses `extra="ignore"` by default — unknown fields in request bodies are silently discarded before the handler is called. This is why `user_id`, `transcript`, `duration_seconds`, `client_timestamp` in the body body never cause 422 errors and never reach the service layer.

### POST /sessions service signature
`create_session(lesson_id: str, user_id: str, supabase: ...)` — verify the mock call_args to confirm `user_id` is the JWT sub, not the body field.

### Existing coverage (do not duplicate)
| Already covered | Where |
|----------------|-------|
| `transcript` not a model field | `test_assessment_stub_contracts.py` |
| `duration_seconds` not a model field | `test_assessment_stub_contracts.py` |
| `rubric_scores` type is `dict[str, str]` (model-level) | `test_assessment_stub_contracts.py` |
| grade_quiz service correctness | `test_quiz_endpoint.py` |
| grade_teachback service correctness | `test_teachback_endpoint.py` |

T26 does NOT re-test what those files already cover at the model-inspection level. T26's value is the **HTTP-layer behaviour** — what status codes Dev 2 actually receives when they send boundary values or banned fields.

### Gap summary this story fills
| Gap | AC |
|-----|----|
| HTTP 422 for `answers: []` | AC2 |
| HTTP 422 for `answers` with 51 items | AC2 |
| HTTP 422 for `response_index: -1` | AC2 |
| HTTP 422 for `response_time_ms: -1` | AC2 |
| `response_time_ms` optional → 200 when omitted | AC2 |
| `feedback` is `list` at HTTP response level | AC3 |
| HTTP 422 for empty `response_text` | AC4 |
| HTTP 422 for >4000 char `response_text` | AC4 |
| `transcript` silently ignored → no 422 | AC4 |
| `duration_seconds` silently ignored → no 422 | AC4 |
| `rubric_scores` values are `str` at HTTP response level | AC5 |
| `POST /teachback` returns 403 for non-approved email | AC6 |
| Extra fields silently ignored on quiz + teachback | AC7 |
| `user_id` from body never passed to service | AC1 + AC8 |

---

## Tasks / Subtasks

- [x] **T1 — Write failing tests (RED phase)**
  - [x] T1.1 — AC1: sessions endpoint — lesson_id only contract, user_id silently ignored, missing lesson_id → 422
  - [x] T1.2 — AC2: quiz endpoint — empty answers → 422; 51 answers → 422; response_index -1 → 422; response_time_ms -1 → 422; omitted response_time_ms → 200
  - [x] T1.3 — AC3: quiz response — `feedback` is list assertion (mocked service)
  - [x] T1.4 — AC4: teachback endpoint — empty response_text → 422; >4000 chars → 422; transcript silently ignored → 200; duration_seconds silently ignored → 200
  - [x] T1.5 — AC5: teachback response — `rubric_scores` values are str (mocked service)
  - [x] T1.6 — AC6: teachback ApprovedUser gate — non-approved email → 403
  - [x] T1.7 — AC7: extra fields silently ignored on quiz and teachback endpoints
  - [x] T1.8 — AC8: named security test — user_id from body never passed to create_session

- [x] **T2 — GREEN phase**
  No production code changes required. All tests mock the service layer and test only the router + Pydantic validation. If a test fails, diagnose whether the test's assumption about Pydantic behaviour is wrong — do not add new fields or relax validation in production code.

- [x] **T3 — Run full test suite**
  - [x] T3.1 — New tests: 18/18 passed — `pytest tests/test_t26_api_contract_dev2.py -v -m unit -p no:warnings`
  - [x] T3.2 — Assessment scope: 171/171 passed — all existing tests green, no regressions

- [x] **T4 — Update dev3 tracker** — mark Demo Sprint T26 complete with date

---

## File List

**New:**
- `apps/api/tests/test_t26_api_contract_dev2.py`

**Modified (tracker only):**
- `docs/dev3-assessment-tracker.md` — mark T26 complete

---

## Dev Agent Record

### Completion Notes
23 unit tests in `apps/api/tests/test_t26_api_contract_dev2.py` (18 original + 5 added post-review).
No production code changes. All ACs verified at the HTTP layer via TestClient with mocked service layer.
239/239 assessment-scope tests pass. Pre-existing full-suite failures are unrelated (encoding, tinytag).

6-agent BMAD code review passed. Two production schema gaps registered as D97 (was D79) / D98 (was D80) in DEFECT-REGISTER.md
(out of scope for this test-only story; require separate PR touching schemas.py).

### Debug Log
_No issues._

### Senior Developer Review (AI)

**Outcome:** Approved (after fixes applied)
**Review date:** 2026-08-13
**Layers:** Story Quality ✅ | Blind Hunter ✅ | Test Coverage ✅ | AC Completeness ✅ | Process Integrity ✅ | Scale & Load ✅

**Action Items (all resolved):**
- [x] AC4-GAP (High / Blocker): Add kwargs inspection to `_fake_grade_teachback` — `assert "transcript" not in kwargs`
- [x] BH-1 (Med): Change `_denied_settings.approved_emails = []` → `["other_approved@example.com"]`
- [x] TC-1 (Med): Add accepted-side boundary tests — `test_teachback_max_length_response_text_accepted`, `test_quiz_max_answers_accepted`
- [x] TC-2 (Med): Add missing-field tests — `test_quiz_missing_session_id_returns_422`, `test_teachback_missing_session_id_returns_422`
- [x] TC-3 (Med): Add `test_teachback_whitespace_only_response_text_accepted` documenting client-side guard requirement
- [x] SL-D1 (Med / Deferred): Registered as D97 (was D79) — `lesson_id: ""` → 500 instead of 422; fix is schema change, out of scope for T26
- [x] SL-D2 (Med / Deferred): Registered as D98 (was D80) — whitespace response_text triggers real LLM; fix is schema validator, out of scope for T26

### Change Log

| Date | Change |
|------|--------|
| 2026-08-13 | Story created — BMAD story-first gate (demo-t26-phaseL8) |
| 2026-08-13 | Implementation complete — 18 tests, all passed, no regressions |
| 2026-08-13 | 6-agent BMAD review complete — 5 fixes applied, test count 18 → 23; D97 (was D79)/D98 (was D80) registered |
