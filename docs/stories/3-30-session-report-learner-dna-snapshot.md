---
story_id: 3-30
title: "Session Report — Learner DNA Snapshot"
status: review
epic: 3
sprint: learner-mode-sprint
branch: learner-mode-sprint-dev3-task3
baseline_commit: "13bd17a"
---

# Story 3-30 — Session Report: Learner DNA Snapshot

## User Story

As a **student**, after completing a lesson I want my session report to show how my Learner DNA
profile dimensions performed and changed during this session — in plain, encouraging language,
without raw numbers — so I can understand my learning patterns and areas for growth.

## Context — Learner Mode Sprint Task 3

This story is the **third task** in the Learner Mode Sprint (`master-learner-mode-sprint-dev3`).

| Task | Story | Status | Branch |
|------|-------|--------|--------|
| Task 1 | 3-28 — Tier-aware quiz question count | ✓ Done | `learner-mode-sprint-dev3-task1` |
| Task 2 | 3-29 — Session Report contextualised by tier | ✓ Done | `learner-mode-sprint-dev3-task2` |
| **Task 3** | **3-30 — Session Report Learner DNA Snapshot** | **← this story** | `learner-mode-sprint-dev3-task3` |

**Branch rule:** This branch is from `main` (not from `master-learner-mode-sprint-dev3`). The tier
fields from Story 3-29 will be added when Task 3 merges into the integration branch. On `main`, the
`SessionReport` model has **10 fields** (no tier fields yet).

---

## Acceptance Criteria

### AC 1 — Backward compatibility: all 10 existing fields unchanged
The 10 existing `SessionReport` fields are returned with identical types and semantics. All 30
existing tests in `test_session_report_endpoint.py` remain GREEN without any modification.

**Verified by:** Running the full pre-existing test suite; zero regressions.

### AC 2 — New field: `learner_dna_snapshot` (additive, optional, default None)
`SessionReport` gains one new field:
```python
learner_dna_snapshot: dict[str, Any] | None = None
```
The field has a Python default of `None` so existing `SessionReport(...)` constructors that omit
it still work. It is always serialised in the JSON response (never omitted from the dict).

### AC 3 — No learner_dna row → `learner_dna_snapshot` is `null`
When the session's user has no `learner_dna` row (not yet onboarded), `learner_dna_snapshot` is
`None` (serialised as JSON `null`).

### AC 4 — `learner_dna_snapshot` structure when DNA row exists
When a `learner_dna` row exists for the user, `learner_dna_snapshot` is a dict with exactly
**2 top-level keys**:
```json
{
  "dimension_labels": { "<dim>": "<label>", ... },
  "growth_labels":    { "<dim>": "<label>|null", ... }
}
```
Both sub-dicts contain all 9 dimensions from `ALL_NINE_DIMENSIONS` in `onboarding_questions.py`.

### AC 5 — `dimension_labels`: descriptive labels, no raw numeric scores
Each value in `dimension_labels` is the string output of the existing `_score_to_label()` helper
applied to the dimension's float value from the `learner_dna` row:

| DB value range | Label |
|---|---|
| ≥ 90.0 | "Exceptional" |
| ≥ 75.0 | "Proficient" |
| ≥ 60.0 | "Developing" |
| ≥ 40.0 | "Emerging" |
| < 40.0 | "Beginning" |

**No raw float values are ever returned.** This satisfies CLAUDE.md Learner DNA display rules.

### AC 6 — `None`/missing dimension value → "Beginning"
If a dimension column is `None` in the DB (edge case: partial row), it is treated as `0.0` and
maps to `"Beginning"`. Use `float(dna_data.get(dim) or 0.0)`.

### AC 7 — `growth_labels`: threshold-based labels for session delta
For each dimension, the delta is taken from the session's `dna_update` events in `session_events`.
Each event's `payload` field contains `{"dimension": str, "delta": float | null, ...}`.

| Delta value | Label |
|---|---|
| `delta > 2.0` | `"Improving"` |
| `delta < -2.0` | `"Needs Attention"` |
| `-2.0 ≤ delta ≤ 2.0` | `"Stable"` |
| `delta` not in event map (key absent) | `None` |

Boundary rule (strict): `delta == 2.0` → `"Stable"` (NOT `"Improving"`).
Boundary rule (strict): `delta == -2.0` → `"Stable"` (NOT `"Needs Attention"`).

### AC 8 — `growth_labels` when no `dna_update` events for session
When no `dna_update` session_events exist for this `session_id` (first session or DNA fusion not
yet run), all 9 `growth_labels` values are `None`.

### AC 9 — `asyncio.to_thread` call count: exactly 6 on the happy path
The updated `get_session_report` makes exactly **6** `asyncio.to_thread` calls in order:

| Call # | Table | Query |
|--------|-------|-------|
| 1 | `sessions` | `select("session_id, user_id, lesson_id, ces_final, started_at, ended_at").eq("session_id", ...).maybe_single()` |
| 2 | `quiz_attempts` | `select("is_correct").eq("session_id", ...)` |
| 3 | `teachback_attempts` | `select("score").eq("session_id", ...)` |
| 4 | `session_events` | `select("id", count="exact").eq("session_id", ...).eq("event_type", "intervention_triggered")` |
| 5 | `learner_dna` | `select(ALL_NINE_DIMENSIONS joined).eq("user_id", row["user_id"]).maybe_single()` |
| 6 | `session_events` | `select("payload").eq("session_id", ...).eq("event_type", "dna_update")` |

Call 6 executes ONLY when call 5 returns a non-None data row (learner_dna exists).
Calls 5 and 6 are NEVER reached when the session fails the ownership check.

### AC 10 — SEC-006 preserved: `learner_dna` never queried on ownership failure
When the session does not exist or belongs to another user, the function raises `HTTP 404` before
call 5. The `learner_dna` table is never queried in that path.

**Verified by test asserting:** `len(supabase._captured_mocks) == 1` when wrong user (only
`sessions` was called).

### AC 11 — DNA queried using `row["user_id"]` (from DB, not JWT)
Call 5 uses `str(row["user_id"])` — the user_id from the verified session row — not `user_id`
from the function parameter (JWT). Consistent with the existing pattern from Story 3-24 AC 17.

### AC 12 — No LLM calls
`get_session_report` makes no LLM calls. `OpenAILLMProvider` is not imported or instantiated
in the function.

### AC 13 — Growth threshold constants at module level in `service.py`
Two module-level float constants immediately after `_quiz_accuracy_label` (or after
`_score_to_label` if Task 2 fields aren't present on this branch):
```python
_DNA_GROWTH_IMPROVING_THRESHOLD: float = 2.0
_DNA_GROWTH_DECLINING_THRESHOLD: float = -2.0
```

### AC 14 — `_delta_to_growth_label` pure function at module level in `service.py`
```python
def _delta_to_growth_label(delta: float | None) -> str | None:
    if delta is None:
        return None
    if delta > _DNA_GROWTH_IMPROVING_THRESHOLD:
        return "Improving"
    if delta < _DNA_GROWTH_DECLINING_THRESHOLD:
        return "Needs Attention"
    return "Stable"
```
Pure function (no side effects), placed immediately after the threshold constants.

### AC 15 — Additive contract noted in PR
The PR description explicitly states: "`learner_dna_snapshot` is additive — optional field with
`default=None`; existing clients are unaffected." 4-dev sign-off is required per CLAUDE.md
frozen-contract rules.

---

## Tasks / Subtasks

### Task 1 — Update `SessionReport` in `router.py`
- [x] **1.1** Confirm `from typing import Any` is present in router.py imports; add if absent — ✓ 2026-07-21
- [x] **1.2** Add `learner_dna_snapshot: dict[str, Any] | None = None` to `SessionReport` — place after `completed_at` — ✓ 2026-07-21
- [x] **1.3** Confirm existing router.py unit tests still pass after model change — ✓ 2026-07-21

### Task 2 — Add module-level helpers to `service.py`
- [x] **2.1** Add `_DNA_GROWTH_IMPROVING_THRESHOLD: float = 2.0` after existing `_score_to_label` function — ✓ 2026-07-21
- [x] **2.2** Add `_DNA_GROWTH_DECLINING_THRESHOLD: float = -2.0` immediately after 2.1 — ✓ 2026-07-21
- [x] **2.3** Add `_delta_to_growth_label(delta: float | None) -> str | None` pure function (see AC 14 for exact body) — ✓ 2026-07-21

### Task 3 — Extend `get_session_report` in `service.py`
- [x] **3.1** After existing Step 7 (ces_score), add Step 8 comment: `# Step 8 — Learner DNA snapshot` — ✓ 2026-07-21
- [x] **3.2** Declare `_dna_snapshot: dict[str, Any] | None = None` before the DB call — ✓ 2026-07-21
- [x] **3.3** Fetch `learner_dna` using `str(row["user_id"])` — select all 9 dims joined with `, `.join(ALL_NINE_DIMENSIONS)` — ✓ 2026-07-21
- [x] **3.4** If `_dna_resp.data` is None/falsy: keep `_dna_snapshot = None`, skip to 3.8 — ✓ 2026-07-21
- [x] **3.5** Build `_dim_labels` dict: all 9 dims → `_score_to_label(float(_dna_resp.data.get(dim) or 0.0))` — ✓ 2026-07-21
- [x] **3.6** Add Step 9: fetch `session_events` where `event_type = "dna_update"` for this session_id — select `"payload"` — ✓ 2026-07-21
- [x] **3.7** Build `_delta_map` from events: `dim → delta` (filter payload where dimension is in ALL_NINE_DIMENSIONS) — ✓ 2026-07-21
- [x] **3.8** Build `_growth_labels`: all 9 dims → `_delta_to_growth_label(_delta_map.get(dim))` — ✓ 2026-07-21
- [x] **3.9** Set `_dna_snapshot = {"dimension_labels": _dim_labels, "growth_labels": _growth_labels}` — ✓ 2026-07-21
- [x] **3.10** Add `learner_dna_snapshot=_dna_snapshot` to the `SessionReport(...)` return statement — ✓ 2026-07-21

### Task 4 — Extend `test_session_report_endpoint.py`
- [x] **4.1** Add `dna_data` and `growth_events` params to `_build_report_supabase` (default both to sentinel/None) — ✓ 2026-07-21
- [x] **4.2** Handle `n=5` (learner_dna `.maybe_single()`) in mock builder — ✓ 2026-07-21
- [x] **4.3** Handle `n=6` (session_events dna_update, 2 `.eq()` filters) — ✓ 2026-07-21
- [x] **4.4** Add `_DNA_ROW` constant with all 9 dims (values 85.0 each) for use in tests — ✓ 2026-07-21
- [x] **4.5** Add `_GROWTH_EVENTS` list with 9 dna_update event dicts (each with delta: 3.0) for tests — ✓ 2026-07-21
- [x] **4.6** Add test: `test_report_dna_snapshot_present_when_dna_exists` — ✓ 2026-07-21
- [x] **4.7** Add test: `test_report_dna_snapshot_none_when_no_dna` — ✓ 2026-07-21
- [x] **4.8** Add test: `test_report_dimension_labels_map_scores_to_labels` — ✓ 2026-07-21
- [x] **4.9** Add test: `test_report_growth_label_improving_when_delta_above_threshold` — ✓ 2026-07-21
- [x] **4.10** Add test: `test_report_growth_label_needs_attention_when_delta_below_threshold` — ✓ 2026-07-21
- [x] **4.11** Add test: `test_report_growth_label_stable_within_range` — ✓ 2026-07-21
- [x] **4.12** Add test: `test_report_growth_label_none_when_no_events` — ✓ 2026-07-21
- [x] **4.13** Add **boundary test**: `test_report_growth_label_stable_at_exact_positive_threshold` — ✓ 2026-07-21
- [x] **4.14** Add **boundary test**: `test_report_growth_label_stable_at_exact_negative_threshold` — ✓ 2026-07-21
- [x] **4.15** Add test: `test_report_sec006_learner_dna_not_queried_for_wrong_user` — ✓ 2026-07-21
- [x] **4.16** Add test: `test_report_asyncio_to_thread_called_6_times_on_happy_path` — ✓ 2026-07-21
- [x] **4.17** Updated `test_get_report_asyncio_to_thread_called_4_times` → `_called_5_times_when_no_dna` (asserts 5 on no-DNA path) — ✓ 2026-07-21

### Task 5 — Update `test_posthog_events.py`
- [x] **5.1** Added `learner_dna_snapshot=None` to `mock_report = SessionReport(...)` — ✓ 2026-07-21

### Task 6 — Run full test suite and verify
- [x] **6.1** `test_session_report_endpoint.py` → 42 passed, 0 failures — ✓ 2026-07-21
- [x] **6.2** Full suite (Dev 3 scope): 127 passed across assessment test files, 0 regressions — ✓ 2026-07-21
- [x] **6.3** Total test count confirmed: 30 (existing) + 12 (new) = 42 tests — ✓ 2026-07-21

---

## Dev Notes

### Files to modify — exactly 4

| File | Change type | What changes |
|------|-------------|--------------|
| `apps/api/app/modules/assessment/router.py` | UPDATE | Add `learner_dna_snapshot` field to `SessionReport` |
| `apps/api/app/modules/assessment/service.py` | UPDATE | Add 2 constants + 1 helper + 2 steps in `get_session_report` |
| `apps/api/tests/test_session_report_endpoint.py` | UPDATE | Extend mock builder, add 12 new tests |
| `apps/api/tests/test_posthog_events.py` | UPDATE | Update `SessionReport(...)` in 1 test |

**DO NOT TOUCH:**
- `supabase/migrations/` — no DB schema changes needed; reads existing tables
- `packages/shared/` — read-only for Dev 3
- Any other test file

---

### `SessionReport` on `main` (10 fields — current state)

```python
class SessionReport(BaseModel):
    session_id: str
    user_id: str
    lesson_id: str
    ces_score: float
    ces_breakdown: dict[str, float]
    interventions_count: int
    quiz_score: float | None
    teachback_score: float | None
    duration_minutes: float
    completed_at: str | None
    # ← ADD HERE:
    # learner_dna_snapshot: dict[str, Any] | None = None
```

The `from typing import Any` import is NOT currently in router.py. Add it.

---

### `_score_to_label` — existing helper in `service.py` (do NOT redefine)

```python
def _score_to_label(score: float) -> str:
    if score >= 90: return "Exceptional"
    if score >= 75: return "Proficient"
    if score >= 60: return "Developing"
    if score >= 40: return "Emerging"
    return "Beginning"
```

Use this directly for `dimension_labels` — do NOT write a new mapping function.

---

### `ALL_NINE_DIMENSIONS` — already imported in `service.py`

```python
from app.modules.assessment.onboarding_questions import (
    ALL_NINE_DIMENSIONS,  # ← already imported
    BADGE_THRESHOLD,
    BADGE_THRESHOLDS,
    QUESTION_SUBDIMENSION_MAP,
)
```

The tuple order: `("pattern_recognition", "logical_deduction", "processing_speed",
"frustration_tolerance", "persistence", "help_seeking",
"goal_orientation", "curiosity_index", "study_independence")`

These are the exact column names in the `learner_dna` table.

---

### DB query for learner_dna (Step 8) — exact form

```python
_dna_resp = await asyncio.to_thread(
    lambda: (
        supabase.table("learner_dna")
        .select(", ".join(ALL_NINE_DIMENSIONS))
        .eq("user_id", str(row["user_id"]))
        .maybe_single()
        .execute()
    )
)
```

Note: `row` is `session_resp.data` — already verified by ownership check. Use `row["user_id"]`,
NOT the function parameter `user_id`. (SEC-006 + AC 11 requirement.)

---

### DB query for dna_update events (Step 9) — exact form

```python
_growth_resp = await asyncio.to_thread(
    lambda: (
        supabase.table("session_events")
        .select("payload")
        .eq("session_id", session_id)
        .eq("event_type", "dna_update")
        .execute()
    )
)
_growth_rows: list[dict[str, Any]] = _growth_resp.data or []
```

Each row's `payload` is a dict `{"dimension": str, "old_value": float|None, "new_value": float, "delta": float|None}`.

Payload is written by `record_dna_growth()` in `dna_growth.py`. The `delta` field is:
- `round(new_value - old_value, 4)` when old_value is not None
- `None` when old_value is None (first-ever session for this user)

---

### Building `_delta_map` from growth rows — safe pattern

```python
_delta_map: dict[str, float | None] = {}
for _evt in _growth_rows:
    _payload = _evt.get("payload")
    if not isinstance(_payload, dict):
        continue
    _dim = _payload.get("dimension")
    if _dim in ALL_NINE_DIMENSIONS:
        _delta_map[_dim] = _payload.get("delta")
```

Defensive: `isinstance(_payload, dict)` guard because JSONB can theoretically return non-dict.
Only accept dimensions that are in `ALL_NINE_DIMENSIONS` (prevents injection of junk keys).

---

### Lambda capture safety — confirmed no closure bugs

Both lambdas capture variables from the enclosing scope just before the call:
- Step 8 lambda captures `row` (function param, not in a loop)
- Step 9 lambda captures `session_id` (function param, not in a loop)

No closure-over-loop-variable risk. This was flagged in Story 3-29's BMAD review; the pattern
here is identical to that story's Step 1b (which passed the review).

---

### Mock builder extension pattern

The `_build_report_supabase` in `test_session_report_endpoint.py` uses a call-counter `n` to
return different mock chains per `supabase.table()` call. Current: 4 calls. New: 6 calls.

```python
def _build_report_supabase(
    session_data=_SESSION_ROW,
    quiz_rows=None,
    tb_rows=None,
    intervention_count=0,
    dna_data=None,          # NEW: pass a dict with 9 dims, or None
    growth_events=None,     # NEW: pass list of {"payload": {...}} dicts, or None/[]
) -> MagicMock:
```

Handler additions:
```python
elif n == 5:
    # learner_dna — maybe_single
    m.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = dna_data
elif n == 6:
    # session_events dna_update — two .eq() filters
    m.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = (
        growth_events if growth_events is not None else []
    )
```

---

### Test constants to add

```python
_DNA_DIM_VALUE = 85.0  # Proficient (≥75, <90)

_DNA_ROW: dict = {dim: _DNA_DIM_VALUE for dim in (
    "pattern_recognition", "logical_deduction", "processing_speed",
    "frustration_tolerance", "persistence", "help_seeking",
    "goal_orientation", "curiosity_index", "study_independence",
)}

_GROWTH_EVENTS_ALL_IMPROVING: list[dict] = [
    {
        "payload": {
            "dimension": dim,
            "old_value": 80.0,
            "new_value": 83.1,
            "delta": 3.1,  # > 2.0 → "Improving"
        }
    }
    for dim in _DNA_ROW
]
```

---

### Boundary test values — exact

| Test | Input | Expected output |
|------|-------|-----------------|
| Strong boundary (AC 7) | delta = 2.0 | `"Stable"` |
| Needs Attention boundary (AC 7) | delta = -2.0 | `"Stable"` |
| Just above improving | delta = 2.0001 | `"Improving"` |
| Just below needs attention | delta = -2.0001 | `"Needs Attention"` |

The boundary tests at ±2.0 are the most important — they directly verify the `>` vs `>=`
strictness of `_delta_to_growth_label`.

---

### DB schema reference — `learner_dna` table columns

```sql
CREATE TABLE public.learner_dna (
  id                   uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id              uuid         NOT NULL UNIQUE REFERENCES public.users(id),
  pattern_recognition  numeric(5,2) CHECK (... BETWEEN 0 AND 100),
  logical_deduction    numeric(5,2) CHECK (...),
  processing_speed     numeric(5,2) CHECK (...),
  frustration_tolerance numeric(5,2) CHECK (...),
  persistence          numeric(5,2) CHECK (...),
  help_seeking         numeric(5,2) CHECK (...),
  goal_orientation     numeric(5,2) CHECK (...),
  curiosity_index      numeric(5,2) CHECK (...),
  study_independence   numeric(5,2) CHECK (...),
  badge_labels         text[],
  profile_text         text,
  session_count        integer NOT NULL DEFAULT 0,
  last_updated         timestamptz NOT NULL DEFAULT now()
);
```

The 9 dimension columns are **nullable** (no NOT NULL). After `process_onboarding()`, all 9 are
populated. After `fuse_learner_dna()`, all 9 are EMA-blended. Use `or 0.0` fallback for safety.

---

### `session_events` `dna_update` payload schema

Written by `record_dna_growth()` in `dna_growth.py`:

```python
{
    "session_id": session_id,
    "event_type": "dna_update",
    "payload": {
        "dimension": "<dim_name>",       # one of ALL_NINE_DIMENSIONS
        "old_value": float | None,       # None on first session
        "new_value": float,              # EMA-blended result (0–100)
        "delta": float | None,           # round(new - old, 4); None if old is None
    },
}
```

9 rows per session (one per dimension). Written AFTER `fuse_learner_dna()` completes Step 5 upsert.

---

### Learner DNA display rules (CLAUDE.md — NON-NEGOTIABLE)

- Never return raw numeric dimension values (`pattern_recognition: 67.5` is BANNED)
- No IQ / EQ / SQ language in labels, values, or comments
- No clinical claims
- `_score_to_label()` is the ONLY approved conversion function
- Growth labels ("Improving", "Stable", "Needs Attention") are approved plain English

---

### Previous story learnings (Stories 3-28, 3-29)

1. **Mock builder call-counter pattern** — the `n`-indexed mock builder is the established test
   pattern for this endpoint. Extend it, do not replace it.

2. **Boundary tests are REQUIRED by BMAD review** — the 5-agent review for Story 3-29 flagged
   missing boundary tests at 80%/60% as BLOCKERs. For this story, boundary tests at ±2.0 are
   similarly critical and must be in the RED phase, not added post-review.

3. **SEC-006 assertion in wrong-user test** — Story 3-29's BMAD review added an assertion that
   `len(supabase._captured_mocks) == 1` when ownership fails. This assertion MUST remain. With 6
   calls on the happy path, the wrong-user path still makes only 1 call (sessions).

4. **Lambda capture** — Story 3-29 BMAD review confirmed the lambda capture pattern is safe when
   not inside a loop. Both new lambdas (Steps 8 and 9) are outside loops — safe.

5. **`from __future__ import annotations`** — service.py has this at the top. All type annotations
   in service.py use string-forward-reference style due to `TYPE_CHECKING` guard. Match this
   convention.

6. **No sentinel needed for dna_data=None** — in Story 3-29 a `_NO_TIER_ROW = object()` sentinel
   was used because `None` was ambiguous (could mean "no row" vs. "row with null data"). For
   `learner_dna`, `.maybe_single().execute().data = None` unambiguously means "no row found".
   Use `None` directly.

---

## Senior Developer Review (AI)
*(Filled after /bmad-code-review)*

---

## Dev Agent Record

### Completion Notes

All 15 ACs satisfied. Key implementation decisions:

- `_delta_to_growth_label` uses strict `>` / `<` operators (not `>=` / `<=`), so delta=±2.0 correctly maps to "Stable" per AC 7 boundary rule.
- Call 6 (session_events dna_update) executes ONLY inside the `if _dna_resp.data:` guard — it is never reached when the learner_dna row is absent, giving 5 total calls on the no-DNA path and 6 on the happy path (AC 9).
- SEC-006 preserved: ownership check raises 404 at line ~598; calls 5 and 6 are physically unreachable from the wrong-user path (AC 10).
- `conftest.py` extended to stub `openai.types` and `openai.types.chat` — this was also required in Task 2 (Story 3-29) and was not yet in `main`; same fix applied here since this branch is from `main`.
- Added extra AC 6 test (`test_report_none_dimension_value_maps_to_beginning`) to cover None dimension → "Beginning" path (not in original task list but required by AC 6).

### File List

- `apps/api/app/modules/assessment/router.py` — added `from typing import Any`; added `learner_dna_snapshot: dict[str, Any] | None = None` to `SessionReport`
- `apps/api/app/modules/assessment/service.py` — added `_DNA_GROWTH_IMPROVING_THRESHOLD`, `_DNA_GROWTH_DECLINING_THRESHOLD`, `_delta_to_growth_label()`; extended `get_session_report` with Steps 8 and 9
- `apps/api/tests/test_session_report_endpoint.py` — extended `_build_report_supabase` (n=5, n=6); added `_ALL_DIMS`, `_DNA_ROW`, `_GROWTH_EVENTS`, `_growth_event_for()`; updated asyncio count test to assert 5 (no-DNA path); added 12 new tests
- `apps/api/tests/test_posthog_events.py` — added `learner_dna_snapshot=None` to `SessionReport(...)` constructor
- `apps/api/tests/conftest.py` — added `openai.types` and `openai.types.chat` stubs

### Change Log

| Date | Author | Note |
|------|--------|------|
| 2026-07-21 | Dev 3 (tannmayygupta) | Story created — Learner Mode Sprint Task 3 |
| 2026-07-21 | Dev 3 (tannmayygupta) | Implementation complete — 42/42 tests pass, status → review |
