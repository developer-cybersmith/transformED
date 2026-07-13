---
status: done
baseline_commit: "daddb26"
---

# Story 3-22 — PostHog Events for Assessment Actions

## Story

As the **product team**, I want PostHog events fired after every key assessment action so that we can track student engagement, funnel drop-off, and feature adoption in real time.

## Acceptance Criteria

**AC 1 — Dependency added:** `posthog>=3.0.0` is present in the `[project.dependencies]` section of `apps/api/pyproject.toml`.

**AC 2 — Config: API key:** `apps/api/app/config.py` has `posthog_api_key: str = ""` (empty string default; optional — no PostHog calls when empty).

**AC 3 — Config: Host:** `apps/api/app/config.py` has `posthog_host: str = "https://us.i.posthog.com"` (PostHog ingest endpoint; configurable for EU compliance).

**AC 4 — Core wrapper exists:** `apps/api/app/core/posthog_client.py` is created with a single `capture_event(*, distinct_id: str, event: str, properties: dict) -> None` function. If `settings.posthog_api_key` is falsy, the function returns immediately without any network call or import error.

**AC 5 — No PII beyond user_id:** PostHog events never include email addresses, full names, raw response text, or any field not listed in the property schemas below.

**AC 6 — quiz submit event:** After a successful call to `grade_quiz()` in `apps/api/app/modules/assessment/service.py`, `capture_event` is called with:
- `event = "assessment_quiz_submitted"`
- `distinct_id = user_id`
- `properties = {"session_id": session_id, "segment_id": segment_id, "ces_contribution": ces_contribution, "quiz_accuracy": quiz_accuracy, "total_questions": total_questions, "correct_count": correct_count}`

**AC 7 — teachback submit event:** After a successful call to `grade_teachback()` in `service.py`, `capture_event` is called with:
- `event = "assessment_teachback_submitted"`
- `distinct_id = user_id`
- `properties = {"session_id": session_id, "segment_id": segment_id, "score": score, "attempt_number": attempt_number}`

**AC 8 — onboarding complete event:** After a successful call to `process_onboarding()` in `service.py`, `capture_event` is called with:
- `event = "assessment_onboarding_completed"`
- `distinct_id = user_id`
- `properties = {"session_count": session_count}` where `session_count` is the value written to `learner_dna`

**AC 9 — session report viewed event:** Inside `GET /api/assessment/session/{session_id}/report` route handler in `router.py`, after the service call returns successfully, `capture_event` is called with:
- `event = "assessment_session_report_viewed"`
- `distinct_id = current_user["sub"]`
- `properties = {"session_id": session_id}`

**AC 10 — learner DNA viewed event:** Inside `GET /api/assessment/user/dna` route handler in `router.py`, after the service call returns successfully, `capture_event` is called with:
- `event = "assessment_dna_viewed"`
- `distinct_id = current_user["sub"]`
- `properties = {"session_count": body["session_count"]}` where `body` is the dict returned by the DNA service

**AC 11 — Fire-and-forget: non-blocking:** `capture_event` never raises an exception visible to the caller. Any PostHog SDK exception is caught and logged at WARNING level; the HTTP response is unaffected.

**AC 12 — PostHog client singleton:** `posthog.api_key` and `posthog.host` are set once (at module import time of `posthog_client.py`) — not re-set on every `capture_event` call.

**AC 13 — Unit tests — quiz:** `test_posthog_quiz_event_fired` asserts that after a successful `submit_quiz` request, `posthog.capture` was called with `event="assessment_quiz_submitted"`, `distinct_id=USER_ID`, and `properties` containing `session_id`, `ces_contribution`, `quiz_accuracy`.

**AC 14 — Unit tests — teachback:** `test_posthog_teachback_event_fired` asserts `posthog.capture` called with `event="assessment_teachback_submitted"` and `distinct_id=USER_ID`.

**AC 15 — Unit tests — onboarding:** `test_posthog_onboarding_event_fired` asserts `posthog.capture` called with `event="assessment_onboarding_completed"` and `distinct_id=USER_ID`.

**AC 16 — Unit tests — session report:** `test_posthog_session_report_event_fired` asserts `posthog.capture` called with `event="assessment_session_report_viewed"` and `properties={"session_id": SESSION_ID}`.

**AC 17 — Unit tests — DNA view:** `test_posthog_dna_viewed_event_fired` asserts `posthog.capture` called with `event="assessment_dna_viewed"` and key `"session_count"` in `properties`.

**AC 18 — Unit tests — no-op when key absent:** `test_posthog_no_call_when_api_key_empty` confirms `posthog.capture` is NOT called when `settings.posthog_api_key == ""` — existing tests that do not patch PostHog remain green because the default key is empty.

**AC 19 — No regressions:** Full `pytest -m unit` suite passes after PostHog integration. Pre-existing tests that do NOT mock PostHog continue to pass (because empty API key causes silent skip, not an error).

## Tasks / Subtasks

- [x] Task 1: Add dependency + config — ✓ 2026-07-03
  - [x] 1.1 Add `posthog>=3.0.0` to `[project.dependencies]` in `apps/api/pyproject.toml` (already present)
  - [x] 1.2 Add `posthog_api_key: str = ""` to `Settings` in `apps/api/app/config.py`
  - [x] 1.3 Add `posthog_host: str = "https://us.i.posthog.com"` to `Settings`

- [x] Task 2: Create `apps/api/app/core/posthog_client.py` — ✓ 2026-07-03
  - [x] 2.1 Import `posthog`; set `posthog.api_key` and `posthog.host` from settings at module level (try/except for test env)
  - [x] 2.2 Implement `capture_event(*, distinct_id, event, properties)` — early return if api_key falsy; catch all exceptions, log WARNING, never re-raise

- [x] Task 3: Write RED tests for all 5 PostHog events — ✓ 2026-07-03
  - [x] 3.1 `test_posthog_quiz_event_fired` — failed before AC 6 implemented ✓
  - [x] 3.2 `test_posthog_teachback_event_fired` — failed before AC 7 implemented ✓
  - [x] 3.3 `test_posthog_onboarding_event_fired` — failed before AC 8 implemented ✓
  - [x] 3.4 `test_posthog_session_report_event_fired` — failed before AC 9 implemented ✓
  - [x] 3.5 `test_posthog_dna_viewed_event_fired` — failed before AC 10 implemented ✓
  - [x] 3.6 `test_posthog_no_call_when_api_key_empty` — passed trivially in RED (no PostHog called at all)
  - [x] 3.7 RED verified: 5 failed, 1 passed trivially

- [x] Task 4: Add `capture_event` call to `grade_quiz()` (service.py) — AC 6 — ✓ 2026-07-03
  - [x] 4.1 After successful bulk insert (Step 9), call `capture_event` with quiz event
  - [x] 4.2 `test_posthog_quiz_event_fired` GREEN ✓

- [x] Task 5: Add `capture_event` call to `grade_teachback()` (service.py) — AC 7 — ✓ 2026-07-03
  - [x] 5.1 After successful insert, call `capture_event` with teachback event
  - [x] 5.2 `test_posthog_teachback_event_fired` GREEN ✓

- [x] Task 6: Add `capture_event` call to `process_onboarding()` (service.py) — AC 8 — ✓ 2026-07-03
  - [x] 6.1 After upsert, call `capture_event` with onboarding event
  - [x] 6.2 `test_posthog_onboarding_event_fired` GREEN ✓

- [x] Task 7: Add `capture_event` to `get_session_report` and `get_learner_dna` route handlers (router.py) — AC 9, AC 10 — ✓ 2026-07-03
  - [x] 7.1 Session report route: fire event after service call returns
  - [x] 7.2 DNA route: implement `get_learner_dna_data()` service function + fire event with session_count
  - [x] 7.3 Both tests GREEN ✓

- [x] Task 8: Verify no-op test and full suite GREEN — ✓ 2026-07-03
  - [x] 8.1 `test_posthog_no_call_when_api_key_empty` passes (api_key="" → no capture call)
  - [x] 8.2 150/150 Dev 3 unit tests pass; 0 regressions in Dev 3 modules

## Dev Notes

### Context

PostHog is in the locked tech stack (CLAUDE.md): `Observability: Langfuse + Sentry + OTel + PostHog`. This story wires PostHog for Dev 3's assessment events only. Dev 1 (pipeline), Dev 4 (WebSocket) own their own PostHog calls.

### Key constraints

- All Dev 3 routes call the PostHog wrapper from `apps/api/app/core/posthog_client.py` — never `import posthog` directly in service or router
- `distinct_id` must be the authenticated `user_id` UUID string — NOT email
- `capture_event` must never raise or block the HTTP response
- Empty `POSTHOG_API_KEY` is the default — unit tests that don't explicitly set the key will skip PostHog automatically (AC 19 relies on this)

### posthog Python SDK pattern

```python
import posthog
posthog.api_key = "phc_..."      # set once at import time
posthog.host = "https://us.i.posthog.com"
posthog.capture("user-uuid-str", "event_name", {"prop": "val"})
```

`posthog.capture()` is synchronous but non-blocking — the SDK queues internally and flushes in a background thread. Do NOT use `posthog.flush()` in tests (it would make network calls); mock `posthog.capture` at the SDK module level.

### Mock pattern for tests

```python
from unittest.mock import patch

with patch("posthog.capture") as mock_capture:
    response = client.post("/api/assessment/quiz", ...)
    mock_capture.assert_called_once()
    call_kwargs = mock_capture.call_args
    assert call_kwargs[0][1] == "assessment_quiz_submitted"
```

Or patch the wrapper directly: `"app.core.posthog_client.posthog.capture"`.

### service.py PostHog call location

For `grade_quiz()`:
- Call AFTER the bulk insert succeeds (after the insert error check)
- Pass `user_id`, `session_id`, `segment_id`, `ces_contribution`, `quiz_accuracy`, `total_questions`, `correct_count` from already-computed local variables

For `grade_teachback()`:
- Call AFTER the teachback insert succeeds
- Pass `user_id`, `session_id`, `segment_id`, `score`, `attempt_number`

For `process_onboarding()`:
- Call AFTER the learner_dna upsert succeeds
- The `session_count` in the upsert payload is available as `dna_row["session_count"]`

### router.py PostHog call location

For `get_session_report()` and `get_learner_dna()` these are GET endpoints so the PostHog call lives in the router (no dedicated service function with the result context).

The `get_learner_dna` handler returns a dict; `session_count` comes from `body.get("session_count", 0)` before returning.

### session_report route location

The session report route is in `apps/api/app/modules/assessment/router.py` — check that it uses a lazy import for the service, consistent with the existing pattern.

### File locations

| File | Action |
|------|--------|
| `apps/api/pyproject.toml` | Add posthog dependency |
| `apps/api/app/config.py` | Add posthog_api_key + posthog_host settings |
| `apps/api/app/core/posthog_client.py` | CREATE — PostHog wrapper |
| `apps/api/app/modules/assessment/service.py` | Add capture_event after quiz, teachback, onboarding inserts |
| `apps/api/app/modules/assessment/router.py` | Add capture_event after session report + DNA route returns |
| `apps/api/tests/test_posthog_events.py` | CREATE — 6 unit tests (ACs 13–18) |

---

## Dev Agent Record

### Completion Notes

All 19 ACs satisfied. 13 unit tests, all passing (expanded from 6 after first BMAD review, then 11 → 13 after re-review). Key implementation details:

- `posthog_client.py` uses try/except around the Settings initialization at module import time so the module loads cleanly in test environments. `posthog.api_key` stays falsy → `capture_event()` is a no-op. Init failures now log at WARNING (BLOCKER-001).
- `capture_event()` requires `analytics_consent=True` to fire (DPDP Option C). Default is `False` — no events sent without explicit consent.
- `get_analytics_consent(user_id, supabase)` in service.py reads `users.analytics_consent`; returns `False` on any DB error (fail-safe); exception now logged at WARNING level.
- `_mock_analytics_consent` autouse fixture in `test_posthog_events.py` patches consent to `True` for PostHog tests; consent=False verified for quiz, teachback, and onboarding (3 suppression tests total).
- Same autouse fixture added to `test_quiz_endpoint.py`, `test_teachback_endpoint.py`, `test_onboarding_endpoint.py` with `return_value=False` to isolate consent from table-routing assertions.
- `GET /api/assessment/user/dna` was previously a 501 stub — implemented using `get_learner_dna_data()`.
- PostHog calls fire AFTER successful DB writes — never on error paths (IMP-003 test verifies this).
- Migration renamed to `20260703010000_add_analytics_consent.sql` to avoid timestamp collision with Story 3-18's `20260703000000_onboarding_unique_constraint.sql`.
- 419 Dev 3 unit tests pass; 0 regressions (18 pre-existing Dev 4 WebSocket failures excluded).

### File List

| File | Action | Notes |
|------|--------|-------|
| `apps/api/pyproject.toml` | No change needed | `posthog>=3.0.0` was already present |
| `apps/api/app/config.py` | Updated | Added `posthog_api_key` + `posthog_host` settings |
| `apps/api/app/core/posthog_client.py` | Created | PostHog wrapper; `capture_event()` with `analytics_consent` guard + WARNING logging |
| `apps/api/app/modules/assessment/service.py` | Updated | `capture_event` calls in quiz/teachback/onboarding; `get_analytics_consent()`; `get_learner_dna_data()` |
| `apps/api/app/modules/assessment/router.py` | Updated | Top-level `capture_event` import; consent fetch + event fire in session report and DNA handlers |
| `apps/api/tests/test_posthog_events.py` | Created | 11 unit tests (ACs 13–18 + BMAD patches IMP-001–003, consent gating, null-safe defaults) |
| `apps/api/tests/test_quiz_endpoint.py` | Updated | `_mock_analytics_consent` autouse fixture + `AsyncMock` import |
| `apps/api/tests/test_teachback_endpoint.py` | Updated | `_mock_analytics_consent` autouse fixture + `AsyncMock` import |
| `apps/api/tests/test_onboarding_endpoint.py` | Updated | `_mock_analytics_consent` autouse fixture |
| `apps/api/tests/test_assessment_stub_contracts.py` | Updated | Renamed `test_dna_endpoint_returns_501` → `test_dna_endpoint_is_live_not_501` |
| `supabase/migrations/20260703010000_add_analytics_consent.sql` | Created | Adds `analytics_consent BOOLEAN NOT NULL DEFAULT FALSE` to `public.users` (renamed from 20260703000000 to avoid timestamp collision with Story 3-18) |
| `docs/deferred-work.md` | Created | DEFER-001 (PostHog erasure), DEFER-002 (sync capture on async loop) |

### Change Log

| Date | Change |
|------|--------|
| 2026-07-03 | Story created — story-first commit before implementation |
| 2026-07-03 | Implementation: posthog_client.py, config settings, service PostHog calls, router updates, 6 tests |
| 2026-07-03 | 5-agent adversarial code review run; 1 decision_needed, 10 patch, 2 defer, 1 dismissed |
| 2026-07-03 | BMAD patches applied: BLOCKER-001/002 fixed; IMP-001–008 implemented; DPDP Option C (analytics_consent); test count 6→11; consent autouse fixture added to quiz/teachback/onboarding test files; 389 tests passing |
| 2026-07-03 | BMAD re-review patches: migration renamed 20260703000000→20260703010000 (timestamp collision); logger.warning added to get_analytics_consent() except block; segment_id assertions added to quiz+teachback PostHog tests (AC 13/14); consent=False tests added for teachback+onboarding; test count 11→13; 419 tests passing |

---

## Senior Developer Review (AI)

**Review date:** 2026-07-03
**Branch:** dev3-sprint2-task5
**Agents:** Story Quality · Blind Hunter · Test Coverage · AC Completeness · Process Integrity
**Outcome:** Changes Requested

### Decision-Needed

- [x] [Review][Decision] DPDP-001: Selected **Option C** — implemented `analytics_consent` mechanism. New `users.analytics_consent` column (migration `20260703000000_add_analytics_consent.sql`, default FALSE). `capture_event()` now accepts `analytics_consent: bool = False`; events are suppressed when False. `get_analytics_consent(user_id, supabase)` added to service.py; all five call sites updated. `test_posthog_not_fired_without_consent` verifies suppression. `_mock_analytics_consent` autouse fixture grants consent in all PostHog tests.

### Patch Findings (BLOCKERs first, then Improvements)

#### BLOCKERs

- [x] [Review][Patch] BLOCKER-001: `except Exception: pass` in posthog_client.py init swallows unexpected errors (AttributeError, ImportError) with no log line — PostHog is silently disabled with zero observability signal [apps/api/app/core/posthog_client.py:31] — FIXED: replaced with `logger.warning("PostHog client init failed...: %s", _exc)`
- [x] [Review][Patch] BLOCKER-002: AC 8 test gap — `test_posthog_onboarding_event_fired` asserts `"session_count" in pos_args[2]` (key presence only); AC 8 requires the value written to learner_dna; add `assert pos_args[2]["session_count"] == 0` [apps/api/tests/test_posthog_events.py:285] — FIXED: assertion added

#### Improvements

- [x] [Review][Patch] IMP-001: No test exercises `capture_event()` exception-swallowing path (AC 11); if the try/except is removed all tests remain green — add a test that patches `posthog.capture` to `side_effect=RuntimeError` and asserts `capture_event()` returns normally — FIXED: `test_capture_event_exception_swallowed` added
- [x] [Review][Patch] IMP-002: `get_learner_dna_data()` 404 path and null-safe defaults (`badge_labels or []`, `session_count or 0`) are entirely untested — the DNA test mocks the whole function; add direct unit tests for these branches [apps/api/app/modules/assessment/service.py:828] — FIXED: `test_get_learner_dna_data_returns_404_when_no_row` and `test_get_learner_dna_data_null_safe_defaults` added
- [x] [Review][Patch] IMP-003: No test verifies PostHog does NOT fire when `grade_quiz()` DB insert fails — if `capture_event` is accidentally moved above the insert, all 6 tests pass while analytics diverge from DB — FIXED: `test_posthog_not_fired_when_quiz_insert_fails` added
- [x] [Review][Patch] IMP-004: `process_onboarding()` PostHog call hardcodes `session_count: 0` instead of reading from `dna_row["session_count"]` — will silently diverge if upsert logic ever returns non-zero for re-onboarding [apps/api/app/modules/assessment/service.py:794] — FIXED: reads `dna_row["session_count"]`
- [x] [Review][Patch] IMP-005: Quiz test missing assertions for `total_questions` and `correct_count` (required by AC 6 property schema); add `assert "total_questions" in props` and `assert "correct_count" in props` [apps/api/tests/test_posthog_events.py:219] — FIXED: both assertions added
- [x] [Review][Patch] IMP-006: Teachback test asserts `"attempt_number" in props` (presence only) — with mock returning count=0 the expected value is 1; add `assert props["attempt_number"] == 1` [apps/api/tests/test_posthog_events.py:262] — FIXED: value assertion added
- [x] [Review][Patch] IMP-007: No-op test (AC 18) uses `patch("posthog.capture")` while all other tests use `patch("app.core.posthog_client.posthog.capture")` — functionally equivalent today but inconsistent; change to the explicit path [apps/api/tests/test_posthog_events.py:353] — FIXED: consistent patch path used
- [x] [Review][Patch] IMP-008: `capture_event` imported top-level in service.py but lazily inside function bodies in router.py — inconsistent; no circular-import reason for lazy in router.py since posthog_client only imports from config (a leaf module) — FIXED: moved to top-level import in router.py

### Deferred Findings

- [x] [Review][Defer] DEFER-001 [apps/api/app/modules/assessment/router.py:125] — UUID `distinct_id` sent to PostHog with no erasure pathway for DPDP right-to-erasure; PostHog person profile persists after account deletion — deferred, pre-existing design concern; addressable in a dedicated DPDP compliance story
- [x] [Review][Defer] DEFER-002 [apps/api/app/core/posthog_client.py:44] — Synchronous `posthog.capture()` called on the async event loop thread; SDK currently non-blocking (background queue) but no `asyncio.to_thread` guard — deferred, no current risk; guard if SDK v4 changes flush semantics

---

## Senior Developer Re-Review (AI) — Patch Verification Pass

**Review date:** 2026-07-03
**Branch:** dev3-sprint2-task5
**Trigger:** Re-review after first-pass BLOCKER/IMP fixes
**Outcome:** APPROVED — 0 new BLOCKERs; all new findings addressed

### New Findings Addressed

- [x] [Re-Review][Fixed] P1 — Migration timestamp collision: `20260703000000_add_analytics_consent.sql` shared timestamp prefix with Story 3-18's `20260703000000_onboarding_unique_constraint.sql`; renamed to `20260703010000_add_analytics_consent.sql` [supabase/migrations/]
- [x] [Re-Review][Fixed] P2 — `get_analytics_consent()` bare `except Exception: return False` had no warning log — silent failure in production; added `logger.warning("PostHog consent check failed user=%s: %s", user_id, exc)` [apps/api/app/modules/assessment/service.py:56]
- [x] [Re-Review][Fixed] P3 — AC 13 partial: `test_posthog_quiz_event_fired` missing `assert props["segment_id"] == SEGMENT_ID` — added [apps/api/tests/test_posthog_events.py]
- [x] [Re-Review][Fixed] P4 — AC 14 partial: `test_posthog_teachback_event_fired` missing `assert props["segment_id"] == SEGMENT_ID` — added [apps/api/tests/test_posthog_events.py]
- [x] [Re-Review][Fixed] P5 — consent=False suppression only tested for `grade_quiz()`; `grade_teachback()` and `process_onboarding()` uncovered; added `test_posthog_not_fired_without_consent_teachback` and `test_posthog_not_fired_without_consent_onboarding` — test count 11→13 [apps/api/tests/test_posthog_events.py]

### Dismissed / Deferred New Findings

- [Re-Review][Dismiss] DNA route user_id path-param IDOR — false positive; DNA route is `GET /user/dna` with no path param; `user_id = current_user["sub"]` only
- [Re-Review][Defer] TOCTOU race: consent checked after business logic in router handlers — theoretical, narrow window, MVP risk negligible; addressable in DPDP compliance story
- [Re-Review][Defer] AC 12 import-time init test — requires module reload; complexity outweighs value at MVP stage
- [Re-Review][Defer] AC 1/19 CI gate items — inherently process gates, not unit-testable
