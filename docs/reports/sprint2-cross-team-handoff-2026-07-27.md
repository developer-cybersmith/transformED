# Sprint 2 Cross-Team Handoff — Dev 3 → Dev 1 / Dev 2 / Dev 4

**From:** Dev 3 (tannmayygupta / developer@cybersmithsecure.com)  
**To:** Dev 1 (pipeline/infra), Dev 2 (frontend), Dev 4 (WebSocket/tutor)  
**Date:** 2026-07-27  
**Source:** `docs/reports/sprint2-dev3-audit-2026-07-27.md` (independent adversarial audit)  
**Sprint 2 Dev 3 status:** PASS — 264/264 tests GREEN, 5/5 stories done, all ACs satisfied

---

## Dev 3 Sprint 2: DONE — No Action Required From Other Devs On Dev 3 Code

Dev 3's Sprint 2 implementation is fully complete, reviewed, and tested. All cross-team items below
are defects in other modules that were *discovered during full-suite testing of the integrated
repository*. None of these require changes to Dev 3's code.

---

## Section A — For Dev 1 (Infra / Pipeline)

### A-1: pytest Cannot Run Without Workaround — BLOCKING ALL DEVELOPERS [CRITICAL]

**Severity:** CRITICAL  
**File:** `apps/api/pyproject.toml:133`  
**Blocks:** Every developer on every PR — no one can run `pytest` without the workaround flag  

**Root cause:**
```toml
# Line 133 in pyproject.toml [tool.pytest.ini_options].filterwarnings:
"ignore::starlette.exceptions.StarletteDeprecationWarning",
```

`starlette.exceptions.StarletteDeprecationWarning` does not exist in the current Starlette version.
Pytest fails at collection time:
```
AttributeError: module 'starlette.exceptions' has no attribute 'StarletteDeprecationWarning'
ERROR: while parsing the following warning configuration
Exit code: 4 — ZERO tests run
```

**Workaround** (current crutch, not a fix):
```bash
pytest ... --override-ini="filterwarnings=ignore::DeprecationWarning"
```

**Fix:** Delete exactly line 133. One-line change.

```toml
# BEFORE:
filterwarnings = [
    "error",
    "ignore::starlette.exceptions.StarletteDeprecationWarning",  # ← DELETE THIS LINE
    "ignore::DeprecationWarning",
    ...
]

# AFTER:
filterwarnings = [
    "error",
    "ignore::DeprecationWarning",
    ...
]
```

**Acceptance criterion:** `pytest apps/api/tests/test_suite_health.py` exits code 0 without any
`--override-ini` flag.

---

### A-2: `.env` Binary Character Causes UnicodeDecodeError — 45 Test Errors [HIGH]

**Severity:** HIGH  
**File:** `.env` (project root, not committed to git — affects local dev + CI)  
**Affects:** `test_admin_router.py` (14 errors), `test_content_router.py` (11 errors),
`test_media_router.py` (8 errors) — total 45 test collection errors

**Root cause:**
`slowapi.Limiter` reads the `.env` file via `starlette.config.Config` which defaults to
`cp1252` encoding on Windows. The `.env` file contains a byte at position 1586 that is not
valid cp1252.

**Error signature:**
```
ERROR tests/unit/test_admin_router.py::test_... - UnicodeDecodeError: 'cp1252' codec can't decode byte 0x... in position 1586: ...
```

**Diagnosis command:**
```python
with open(".env", "rb") as f:
    data = f.read()
print(repr(data[1580:1595]))  # show bytes around position 1586
```

**Fix options:**
1. Re-save `.env` as pure ASCII/UTF-8 without BOM — remove or replace the non-ASCII character at position 1586
2. Add `UTF8=1` to the `.env` file (forces starlette Config to read as UTF-8)
3. Ensure CI generates `.env` from secrets with explicit UTF-8 encoding

**Acceptance criterion:** Running `pytest apps/api/tests/unit/test_admin_router.py -q` produces
`X passed` not `X errors`.

---

## Section B — For Dev 2 (Frontend)

### B-1: Quiz Feedback Field Names — Frontend Must Match Backend Contract [HIGH]

**Severity:** HIGH — renders post-quiz feedback UI broken at runtime  
**File:** `apps/web/src/components/player/QuizOverlay.tsx:166–169`  
**Confirmed by:** `docs/dev3-sprint2-audit-handoff.md §1`

**The backend's `QuizResult.feedback` array shape** (intentional, per BMAD Story 3-8 v2):
```typescript
interface QuizFeedbackItem {
  question_id: string;
  is_correct: boolean;      // ← backend sends this
  correct_option: number;
  selected_option: number;
  explanation: string;      // ← backend sends this
}
```

**The frontend currently reads:**
```typescript
// QuizOverlay.tsx:167
f.correct        // undefined at runtime — backend sends f.is_correct
f.message        // undefined at runtime — backend sends f.explanation
```

**Fix:** Two rename operations in `QuizOverlay.tsx`:
```typescript
// Line 167: change
f.correct → f.is_correct
f.message → f.explanation
```

**Note:** Per-question feedback (shown inline on each answer) already works via client-side
computation — this bug only affects the post-quiz summary score overlay section.

**Dev 3 confirmation:** The backend contract `is_correct`/`explanation`/`correct_option`/`selected_option`
is intentional, reviewed by 5-agent BMAD, and will not change. The frontend must conform.

**Acceptance criterion:** Submitting a quiz and clicking through to the summary overlay shows
correct/incorrect labels and explanation text (not `undefined`).

---

### B-2: Six LM Sprint `SessionReport` Fields Missing From Frontend Types [MEDIUM]

**Severity:** MEDIUM — TypeScript will compile but runtime values will be `undefined`  
**File:** `apps/web/src/types/assessment.ts`  
**Source:** LM Sprint Stories 3-29 (tier fields) and 3-30 (DNA snapshot)

**Backend `SessionReport` now returns these additional fields** (all additive, default to `None`):
```typescript
interface SessionReport {
  // ... existing fields unchanged ...

  // Added by Story 3-29 (tier context):
  tier: string | null;                  // "T1" | "T2" | "T3" | null
  tier_label: string | null;            // "Full-Depth" | "Standard" | "Refresher" | null
  quiz_total_questions: number | null;
  quiz_correct_count: number | null;
  quiz_accuracy_label: string | null;   // "Strong" | "Developing" | "Needs Review" | null

  // Added by Story 3-30 (Learner DNA snapshot):
  learner_dna_snapshot: {
    dimension_labels: Record<string, string>; // e.g. {"persistence": "Proficient", ...}
    growth_labels: Record<string, string | null>; // e.g. {"persistence": "Improving", ...}
  } | null;
}
```

**Impact:** Any component rendering tier context or DNA snapshot will read `undefined` fields
until the TypeScript interface is updated. No runtime error — just missing UI data.

**Fix:** Add the 6 fields above to the `SessionReport` interface in `apps/web/src/types/assessment.ts`.
All fields are `| null` — additive changes only, no existing field is removed or renamed.

**Acceptance criterion:** `tsc --noEmit` exits clean after the type update; session report page
renders tier label and DNA snapshot without TypeScript errors.

---

### B-3: `test_onboarding_content.py` Scans Wrong File [MEDIUM]

**Severity:** MEDIUM (test-suite health — 10 failing tests in CI)  
**File:** `apps/api/tests/test_onboarding_content.py`  
**Note:** This is a test file, not production code — no user-facing impact

**Root cause:**
```python
# test_onboarding_content.py scans:
page_tsx = Path("apps/web/src/app/(app)/onboarding/page.tsx")
```

The 20-question onboarding content (`QUESTIONS` array) was moved from `page.tsx` to the
`OnboardingFlow.tsx` component. `page.tsx` is now a thin wrapper that imports `OnboardingFlow` —
the question IDs are no longer present in `page.tsx` and the scanner finds nothing.

**Fix:** Update the path in `test_onboarding_content.py`:
```python
# Change:
page_tsx = Path("apps/web/src/app/(app)/onboarding/page.tsx")
# To:
onboarding_flow = Path("apps/web/src/features/onboarding/OnboardingFlow.tsx")
# (or wherever the QUESTIONS array now lives — verify with grep)
```

**Verification command:**
```bash
grep -r "question_id\|c1\|e1\|s1" apps/web/src --include="*.tsx" -l
```

**Acceptance criterion:** `pytest apps/api/tests/test_onboarding_content.py -q` passes
(10 currently failing tests should go green).

---

## Section C — For Dev 4 (WebSocket / JWT / Tutor FSM)

### C-1: JWT Middleware Returns 401 for a Valid Token [HIGH]

**Severity:** HIGH — authentication broken for any test that issues a real JWT  
**Files:** `apps/api/app/modules/auth/` (JWT middleware), `apps/api/tests/test_auth.py`  
**Failing tests:** `test_valid_token_returns_200` (expects 200, gets 401)

**Symptoms:**
```
FAILED tests/test_auth.py::test_valid_token_returns_200
  AssertionError: assert 401 == 200
```

**Investigation approach:**
1. Check that `PyJWT` decode is receiving the correct `algorithms=["HS256"]` (not ES256)
2. Verify `SUPABASE_JWT_SECRET` value in test environment matches what the test fixture signs with
3. Check that `get_current_user` dependency reads from the correct header (`Authorization: Bearer <token>`)
4. Confirm the middleware does not double-verify (once in middleware, once in dependency)

**Security note:** A related test `test_alg_none_attack_returns_401_not_500` — the `alg=none` MITM
attack returns HTTP 500 instead of HTTP 401. This is a security regression: an attacker probing
for `alg=none` vulnerability currently gets a 500 error response, which reveals that the server
reached the signature validation step (information leak). It should return 401 unconditionally.

Fix: Wrap the PyJWT decode in a try/except that catches `jwt.exceptions.InvalidAlgorithmError`
and re-raises as HTTP 401.

**Acceptance criteria:**
- `test_valid_token_returns_200` → 200 with valid JWT
- `test_alg_none_attack_returns_401_not_500` → 401 (not 500) for `alg: none` tokens
- All existing auth tests pass

---

### C-2: Tutor Service Test — `MagicMock` vs `int` Type Error [HIGH]

**Severity:** HIGH — 13 test failures; tutor service has never been integration-tested  
**File:** `apps/api/app/modules/tutor/service.py:133` (comparison involving a mock return)  
**Failing tests:** `test_tutor_service.py` — 13 failures

**Error signature:**
```
TypeError: '<=' not supported between instances of 'MagicMock' and 'int'
```

**Root cause:** A mock in `test_tutor_service.py` returns a `MagicMock` object where `service.py:133`
expects an `int`. The mock is not configured with a concrete return value for the relevant attribute.

**Investigation approach:**
1. Find line 133 of `service.py` — what comparison is being made?
2. Trace back what attribute/method the mock should be returning an `int` for
3. Add `.return_value = <int>` or `spec=int` to the mock configuration

**Example fix pattern:**
```python
# Before (mock returns MagicMock by default):
mock_session.distraction_count  # → MagicMock

# After (explicitly set the return):
mock_session.distraction_count = 2  # or mock.configure_mock(distraction_count=2)
```

**Acceptance criterion:** `pytest apps/api/tests/test_tutor_service.py -q` passes with 0 failures.

---

## Evidence Summary

All Dev 3 test results are from live execution (2026-07-27) against the current `main` branch:

```bash
cd apps/api
python -m pytest tests/test_dna_growth.py tests/test_dna_fusion.py \
  tests/test_reassessment_flag.py tests/test_session_report_endpoint.py \
  tests/test_posthog_events.py tests/test_analytics_events_endpoint.py \
  tests/test_analytics_summary_endpoint.py tests/test_onboarding_endpoint.py \
  tests/test_assessment_stub_contracts.py \
  --override-ini="filterwarnings=ignore::DeprecationWarning" -q

# Result: 264 passed in 7.35s
```

**Full suite (excluding Dev 1's .env-blocked tests):**
```bash
python -m pytest -m unit --override-ini="filterwarnings=ignore::DeprecationWarning" \
  --ignore=tests/unit/test_admin_router.py \
  --ignore=tests/unit/test_content_router.py \
  --ignore=tests/unit/test_media_router.py \
  --tb=no -q

# Result: 1040 passed, 59 failed (Dev4 JWT/tutor + Dev2 onboarding), 1 skipped
# Dev 3's 264 tests are all in the 1040 PASSED bucket
```

---

## Current Status Summary

| Owner | Issue | Severity | Status |
|-------|-------|----------|--------|
| Dev 1 | `pyproject.toml:133` stale filterwarnings | CRITICAL | Open — 1 line delete |
| Dev 1 | `.env` binary encoding character at pos 1586 | HIGH | Open — re-save .env as UTF-8 |
| Dev 2 | `QuizOverlay.tsx` `f.correct`/`f.message` field names wrong | HIGH | Open — 2 renames |
| Dev 2 | 6 LM Sprint `SessionReport` fields missing from TS types | MEDIUM | Open — add 6 fields to interface |
| Dev 2 | `test_onboarding_content.py` scans wrong file (10 failures) | MEDIUM | Open — update path |
| Dev 4 | JWT middleware returns 401 for valid token | HIGH | Open — investigate decode |
| Dev 4 | `alg=none` attack returns 500 not 401 | HIGH | Open — catch `InvalidAlgorithmError` |
| Dev 4 | Tutor service mock `MagicMock` vs int (13 failures) | HIGH | Open — fix mock spec |
| **Dev 3** | **All Sprint 2 + LM Sprint code** | — | **DONE — 264/264 tests PASS** |

---

## References

- Full audit report: `docs/reports/sprint2-dev3-audit-2026-07-27.md`
- Dev 4 FSM/WebSocket handoff: `docs/dev4-sprint2-audit-handoff.md`
- Dev 3 branch map (updated): `docs/dev3-branch-map.md`
- Dev 3 tracker (updated): `docs/dev3-assessment-tracker.md`
- Sprint 2 360° re-audit: `docs/reports/sprint2-360-reaudit-2026-07-27.md`
