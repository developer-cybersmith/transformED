---
status: ready-for-dev
baseline_commit: 48b0068
---

# Story 3-21 — Analytics Session Summary (GET /api/analytics/session/{id}/summary)

**Epic:** 3 — Assessment, CES & Analytics
**Sprint:** 2 (Week 4–5)
**Story number:** 3-21
**Dev:** Dev 3 (tannmayygupta)
**Priority:** High

---

## User Story

As a **student or tutor dashboard viewing post-session analytics**, I want **a single endpoint that returns aggregated session metrics (engagement score, attention, distraction events, blink activity, page views, duration, and total event count)**, so that **session quality can be understood at a glance without joining multiple tables on the client side**.

---

## Background & Context

The analytics router (`apps/api/app/modules/analytics/router.py`) has a `GET /session/{session_id}/summary` endpoint scaffolded in Sprint 0 as a `501 Not Implemented` stub. The `SessionSummary` Pydantic model was also scaffolded but contains a field mismatch: `avg_head_pose: dict[str, float]` with a comment `{pitch, yaw, roll}` — however, the `attention_events` table only stores a single composite `head_pose_score numeric(5,2)`, not separate pitch/yaw/roll values. This field must be corrected before implementation.

This story replaces the 501 stub with a live read-only aggregation that pulls from three tables:
- `sessions` — session metadata, ownership, `ces_final`, timestamps
- `session_events` — behavioral event log (written by Story 3-20)
- `attention_events` — per-window attention signals (written by Dev 4's WebSocket handler)

**Key constraints:**
- Read-only endpoint — no writes, no LLM calls, no migrations needed
- `attention_events` access is gated by RLS (`attention_consent = true`). If a user hasn't consented, RLS silently returns 0 rows → all attention metrics default to 0.0. The service does NOT need to check consent explicitly.
- `blink_rate` in `attention_events` is a per-5s-window rate, not a raw count. `total_blinks` is computed as `int(round(sum(blink_rate)))` — a reasonable approximation of cumulative blink activity. This is documented as MVP-level accuracy.
- `distraction_events` definition: COUNT WHERE `event_type IN ('tab_switch', 'intervention_acknowledged')`
- `page_views` definition: COUNT WHERE `event_type = 'segment_complete'` (each completed segment ≈ a page view)

---

## Acceptance Criteria

### AC 1 — HTTP 200 with all SessionSummary fields
`GET /api/analytics/session/{session_id}/summary` with a valid Bearer token and an existing session owned by the user returns HTTP 200 with a JSON body containing ALL fields: `session_id`, `user_id`, `lesson_id`, `ces_score`, `avg_attention`, `distraction_events`, `total_blinks`, `avg_head_pose_score`, `page_views`, `duration_seconds`, `events_count`.

### AC 2 — SEC-006: Non-existent session returns 404
A `session_id` that does not exist in the `sessions` table returns HTTP 404 with detail `"Session not found."`.

### AC 3 — SEC-006: Wrong-user session returns identical 404
A `session_id` that exists but belongs to a different authenticated user returns HTTP 404 with detail `"Session not found."` — the SAME status code and SAME detail string as AC 2. This prevents session ID enumeration.

### AC 4 — `ces_score` from `sessions.ces_final`
`ces_score = float(sessions.ces_final)`. If `ces_final` is `NULL`, `ces_score = 0.0`.

### AC 5 — `events_count` from `session_events`
`events_count` = total number of rows in `session_events` where `session_id = ?`. Returns `0` if the session has no events.

### AC 6 — `distraction_events` from `session_events`
`distraction_events` = COUNT of rows in `session_events` where `event_type IN ('tab_switch', 'intervention_acknowledged')`. Returns `0` if none match.

### AC 7 — `page_views` from `session_events`
`page_views` = COUNT of rows in `session_events` where `event_type = 'segment_complete'`. Returns `0` if none match.

### AC 8 — Single query for all `session_events` metrics
All three `session_events` metrics (`events_count`, `distraction_events`, `page_views`) are computed from a **single** Supabase query that fetches `event_type` column only and aggregates in Python. There must NOT be 3 separate count queries.

### AC 9 — `duration_seconds` from session timestamps
`duration_seconds = (sessions.ended_at - sessions.started_at).total_seconds()`, rounded to 2 decimal places. If `ended_at` is `NULL`, `duration_seconds = 0.0`.

### AC 10 — `avg_attention` from `attention_events.gaze_score`
`avg_attention` = mean of non-null `gaze_score` values from `attention_events` for the session. Returns `0.0` if the session has no `attention_events` rows (including the DPDP case where RLS returns 0 rows for users without consent). Result rounded to 4 decimal places.

### AC 11 — `avg_head_pose_score` from `attention_events.head_pose_score`
`avg_head_pose_score` = mean of non-null `head_pose_score` values from `attention_events`. Returns `0.0` if no rows. Result rounded to 4 decimal places.

### AC 12 — `total_blinks` from `attention_events.blink_rate`
`total_blinks = int(round(sum(non-null blink_rate values)))`. Returns `0` if no rows. This is an MVP-level approximation: `blink_rate` is a per-5s-window rate, so the sum represents cumulative blink activity across all attention windows.

### AC 13 — Zero defaults when no `attention_events`
If the session has no `attention_events` rows (empty table, DPDP-blocked, or session in progress): `avg_attention = 0.0`, `avg_head_pose_score = 0.0`, `total_blinks = 0`.

### AC 14 — `SessionSummary` model: `avg_head_pose_score: float` (not dict)
The `avg_head_pose: dict[str, float]` field in the scaffolded `SessionSummary` is corrected to `avg_head_pose_score: float`. The DB schema stores a single `head_pose_score numeric(5,2)` column — not separate pitch/yaw/roll values. Since the endpoint was 501, no backward-compatibility concern exists.

### AC 15 — All DB calls wrapped in `asyncio.to_thread`
All three supabase-py v2 synchronous calls (`sessions`, `session_events`, `attention_events`) must be wrapped in `asyncio.to_thread`. Direct synchronous calls in an async function are prohibited.

### AC 16 — Unauthenticated requests rejected
A request without a Bearer token returns HTTP 401 or 403 (handled by the `CurrentUser` dependency). No business logic executes.

### AC 17 — No LLM calls
Zero LLM calls in the analytics summary flow. This is a pure DB read aggregation.

### AC 18 — Analytics summary stub contract test added
A new test `test_analytics_summary_endpoint_is_live_not_501` is added to `apps/api/tests/test_assessment_stub_contracts.py`, verifying `GET /api/analytics/session/{id}/summary` does NOT return 501. Pattern mirrors `test_analytics_events_endpoint_is_live_not_501`.

---

## Tasks / Subtasks

- [x] Task 0: Branch created (`dev3-sprint2-task4` from `48b0068`)
- [ ] Task 1: Story file created and committed before any code (BMAD gate)

- [ ] Task 2: Fix `SessionSummary` Pydantic model in `router.py` (AC 14)
  - [ ] 2.1 Rename `avg_head_pose: dict[str, float]` → `avg_head_pose_score: float`
  - [ ] 2.2 Verify no other file imports or references `avg_head_pose`

- [ ] Task 3: Add stub contract test (AC 18)
  - [ ] 3.1 Add `test_analytics_summary_endpoint_is_live_not_501` to `test_assessment_stub_contracts.py`
  - [ ] 3.2 Create `_analytics_summary_app` TestClient in test file (with auth override)
  - [ ] 3.3 Run: `pytest tests/test_assessment_stub_contracts.py -v` — confirm new test FAILS (still 501)

- [ ] Task 4: Write failing tests (RED phase) — new file `apps/api/tests/test_analytics_summary_endpoint.py`
  - [ ] 4.1 Mock factory `_build_summary_supabase(*, session_data, events_data, attn_data)` — call-order capture
  - [ ] 4.2 Autouse `_mock_to_thread` fixture (patches `app.modules.analytics.service.asyncio.to_thread`)
  - [ ] 4.3 `test_200_returns_all_summary_fields` — AC 1
  - [ ] 4.4 `test_nonexistent_session_returns_404` — AC 2
  - [ ] 4.5 `test_wrong_user_returns_404` — AC 3
  - [ ] 4.6 `test_404_detail_identical_for_missing_and_wrong_user` — AC 2+3 (SEC-006 identity check)
  - [ ] 4.7 `test_ces_score_from_sessions_ces_final` — AC 4
  - [ ] 4.8 `test_ces_score_null_returns_zero` — AC 4
  - [ ] 4.9 `test_events_count_from_session_events` — AC 5
  - [ ] 4.10 `test_events_count_zero_when_no_events` — AC 5+13
  - [ ] 4.11 `test_distraction_events_counts_tab_switch_and_intervention` — AC 6
  - [ ] 4.12 `test_distraction_events_zero_when_no_matching_types` — AC 6
  - [ ] 4.13 `test_page_views_counts_segment_complete` — AC 7
  - [ ] 4.14 `test_single_query_for_all_session_events_metrics` — AC 8
  - [ ] 4.15 `test_duration_seconds_from_timestamps` — AC 9
  - [ ] 4.16 `test_duration_seconds_zero_when_ended_at_null` — AC 9
  - [ ] 4.17 `test_avg_attention_from_gaze_score` — AC 10
  - [ ] 4.18 `test_avg_head_pose_score_from_attention_events` — AC 11
  - [ ] 4.19 `test_total_blinks_from_blink_rate` — AC 12
  - [ ] 4.20 `test_zero_attention_defaults_when_no_attention_events` — AC 13
  - [ ] 4.21 `test_asyncio_to_thread_used_for_all_db_calls` — AC 15
  - [ ] 4.22 `test_unauthenticated_request_rejected` — AC 16
  - [ ] 4.23 `test_no_llm_calls_in_summary_flow` — AC 17
  - [ ] 4.24 `test_null_gaze_scores_excluded_from_avg_attention` — AC 10 (null exclusion)
  - [ ] 4.25 `test_null_blink_rates_excluded_from_total_blinks` — AC 12 (null exclusion)
  - [ ] 4.26 `test_http_200_smoke_test` — HTTP-layer integration (patches service + db)

- [ ] Task 5: Create `get_session_summary()` in `apps/api/app/modules/analytics/service.py` (GREEN)
  - [ ] 5.1 Function signature: `async def get_session_summary(*, session_id: str, user_id: str, supabase: Any) -> Any`
  - [ ] 5.2 Step 1 — Session ownership: `maybe_single()` on `sessions`, 404 for not-found, 404 for wrong-user (SEC-006)
  - [ ] 5.3 Step 2 — session_events single query: `.select("event_type").eq().execute()` → Python aggregation
  - [ ] 5.4 Step 3 — attention_events query: `.select("gaze_score, head_pose_score, blink_rate").eq().execute()`
  - [ ] 5.5 Compute `ces_score`, `duration_seconds`, `events_count`, `distraction_events`, `page_views`
  - [ ] 5.6 Compute `avg_attention`, `avg_head_pose_score`, `total_blinks` with null-row exclusion
  - [ ] 5.7 Return `SessionSummary(...)` (lazy import from router)
  - [ ] 5.8 logger.info on success

- [ ] Task 6: Update `router.py` to call service (GREEN)
  - [ ] 6.1 Fix `SessionSummary`: rename `avg_head_pose: dict[str, float]` → `avg_head_pose_score: float`
  - [ ] 6.2 Replace 501 stub with lazy imports + `await _get_session_summary(...)`

- [ ] Task 7: Run full test suite (verify GREEN + no regressions)
  - [ ] 7.1 `pytest tests/test_analytics_summary_endpoint.py -v` — 26/26 PASS
  - [ ] 7.2 `pytest tests/test_assessment_stub_contracts.py -v` — all PASS (new AC 18 test passes)
  - [ ] 7.3 `pytest -m unit --ignore=tests/test_tutor_*.py -v` — 0 regressions

- [ ] Task 8: Tracker update
  - [ ] 8.1 Mark Sprint 2 Task 4 done in `docs/dev3-assessment-tracker.md`
  - [ ] 8.2 Update Quick Status Dashboard

---

## Technical Notes

### Exact DB columns used

```
sessions:        session_id, user_id, lesson_id, ces_final, started_at, ended_at
session_events:  event_type                            (single query, aggregated in Python)
attention_events: gaze_score, head_pose_score, blink_rate  (single query, aggregated in Python)
```

### DB query order and call indexes (MUST match mock factory)

| Index | Table | Operation | Result shape |
|-------|-------|-----------|-------------|
| 1 | sessions | `.maybe_single().execute()` | `data = dict or None` |
| 2 | session_events | `.select("event_type").eq().execute()` | `data = list[{"event_type": str}]` |
| 3 | attention_events | `.select("gaze_score, head_pose_score, blink_rate").eq().execute()` | `data = list[{"gaze_score": float|None, ...}]` |

### Session events query — single query, Python aggregation

```python
events_resp = await asyncio.to_thread(
    lambda: supabase.table("session_events")
    .select("event_type")
    .eq("session_id", session_id)
    .execute()
)
events_rows: list[dict] = events_resp.data or []
events_count: int = len(events_rows)
distraction_events: int = sum(
    1 for r in events_rows
    if r.get("event_type") in {"tab_switch", "intervention_acknowledged"}
)
page_views: int = sum(
    1 for r in events_rows if r.get("event_type") == "segment_complete"
)
```

### Attention events query — averages with null exclusion

```python
attn_resp = await asyncio.to_thread(
    lambda: supabase.table("attention_events")
    .select("gaze_score, head_pose_score, blink_rate")
    .eq("session_id", session_id)
    .execute()
)
attn_rows: list[dict] = attn_resp.data or []

gaze_vals = [float(r["gaze_score"]) for r in attn_rows if r.get("gaze_score") is not None]
head_vals  = [float(r["head_pose_score"]) for r in attn_rows if r.get("head_pose_score") is not None]
blink_vals = [float(r["blink_rate"]) for r in attn_rows if r.get("blink_rate") is not None]

avg_attention: float     = round(sum(gaze_vals) / len(gaze_vals), 4) if gaze_vals else 0.0
avg_head_pose_score: float = round(sum(head_vals) / len(head_vals), 4) if head_vals else 0.0
total_blinks: int        = int(round(sum(blink_vals))) if blink_vals else 0
```

### Duration computation (seconds, not minutes — unlike session report)

```python
from datetime import datetime

raw_started = session_row.get("started_at")
raw_ended   = session_row.get("ended_at")

started_at = datetime.fromisoformat(raw_started.replace("Z", "+00:00")) if isinstance(raw_started, str) else raw_started
ended_at   = datetime.fromisoformat(raw_ended.replace("Z", "+00:00"))   if isinstance(raw_ended, str)   else raw_ended

duration_seconds: float = (
    round((ended_at - started_at).total_seconds(), 2)
    if ended_at is not None and started_at is not None
    else 0.0
)
```

### SEC-006 session ownership (404 for both paths, identical detail)

```python
session_resp = await asyncio.to_thread(
    lambda: supabase.table("sessions")
    .select("session_id, user_id, lesson_id, ces_final, started_at, ended_at")
    .eq("session_id", session_id)
    .maybe_single()
    .execute()
)
if session_resp.data is None:
    raise HTTPException(status_code=404, detail="Session not found.")
if str(session_resp.data["user_id"]) != str(user_id):
    raise HTTPException(status_code=404, detail="Session not found.")
```

**IMPORTANT:** Both paths use HTTP 404 (NOT 403) and IDENTICAL detail strings.
This is SEC-006 — prevents session enumeration oracle (same as `get_session_report`).

### Lazy import pattern (prevents circular imports)

```python
@router.get("/session/{session_id}/summary", response_model=SessionSummary)
async def get_session_summary(session_id: str, current_user: CurrentUser) -> SessionSummary:
    from app.core.db import get_supabase
    from app.modules.analytics.service import get_session_summary as _get_session_summary
    return await _get_session_summary(
        session_id=session_id,
        user_id=current_user["sub"],
        supabase=get_supabase(),
    )
```

### Mock factory pattern (call-order capture — identical to test_session_report_endpoint.py)

```python
def _build_summary_supabase(
    *,
    session_data=_SESSION_ROW,
    events_data=None,
    attn_data=None,
) -> MagicMock:
    mock = MagicMock()
    call_count = [0]
    captured: dict[int, MagicMock] = {}

    def _table(name):
        call_count[0] += 1
        n = call_count[0]
        m = MagicMock()
        captured[n] = m
        if n == 1:
            # sessions — maybe_single
            m.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = session_data
        elif n == 2:
            # session_events — list of event_type dicts
            m.select.return_value.eq.return_value.execute.return_value.data = events_data or []
        elif n == 3:
            # attention_events — list of score dicts
            m.select.return_value.eq.return_value.execute.return_value.data = attn_data or []
        return m

    mock.table.side_effect = _table
    mock._captured_mocks = captured
    return mock
```

### asyncio.to_thread shim (must target analytics service, not assessment service)

```python
@pytest.fixture(autouse=True)
def _mock_to_thread(monkeypatch):
    async def _shim(func, *args, **kwargs):
        return func(*args, **kwargs)
    monkeypatch.setattr("app.modules.analytics.service.asyncio.to_thread", _shim)
```

**Critical:** Target `app.modules.analytics.service.asyncio.to_thread` NOT
`app.modules.assessment.service.asyncio.to_thread`. Wrong target = shim doesn't reach
the code under test.

### DPDP / attention_consent note

`attention_events` RLS policy requires `u.attention_consent = true`. If a user hasn't
consented, RLS returns 0 rows → `attn_rows = []` → all three attention metrics default
to 0. The service layer does NOT need to check consent explicitly — RLS handles it.

### `SessionSummary.avg_head_pose` stub mismatch — why and what changed

The Sprint 0 scaffold wrote `avg_head_pose: dict[str, float]` with comment `{pitch, yaw, roll}`.
The actual DB schema stores a single composite `head_pose_score numeric(5,2)`.
Since the endpoint was 501, no client integration has been built against it.
Correct field: `avg_head_pose_score: float`.

### Key difference from `get_session_report` (assessment service)

| Aspect | Session Report (3-19) | Session Summary (3-21) |
|--------|----------------------|----------------------|
| Module | `assessment/service.py` | `analytics/service.py` |
| Tables | sessions + quiz_attempts + teachback_attempts + session_events | sessions + session_events + attention_events |
| Unit | minutes | seconds |
| LLM | never | never |
| SEC-006 | 404 + "Session not found." | 404 + "Session not found." |
| asyncio shim target | `assessment.service.asyncio.to_thread` | `analytics.service.asyncio.to_thread` |

### Files to modify/create

| File | Action |
|------|--------|
| `apps/api/app/modules/analytics/router.py` | UPDATE: fix SessionSummary model field, replace 501 stub |
| `apps/api/app/modules/analytics/service.py` | UPDATE: add `get_session_summary()` |
| `apps/api/tests/test_analytics_summary_endpoint.py` | CREATE: 26 unit tests |
| `apps/api/tests/test_assessment_stub_contracts.py` | UPDATE: add AC 18 contract test |
| `docs/dev3-assessment-tracker.md` | UPDATE: mark Task 4 done |

No new migrations. No changes to `packages/shared/`. No changes to `supabase/migrations/`.

---

## Dev Agent Record

### Debug Log
_To be filled during implementation_

### Completion Notes
_To be filled on completion_

### File List
_To be filled on completion_

### Change Log
- 2026-07-03: Story created (story-first BMAD gate)

---

## Senior Developer Review (AI)

_To be filled after code review_
