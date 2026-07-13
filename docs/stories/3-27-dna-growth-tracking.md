---
status: done
baseline_commit: "b03b8cdf1386750b9bf28df30b7e436f43d7df02"
---

# Story 3-27 — Learner DNA Growth Tracking (delta per dimension per session)

## Story

As **Dev 4 (WebSocket / tutor state machine)**, after `fuse_learner_dna()` upserts
the updated 9-dimension profile, I want `session_events` rows written automatically
(one per dimension, `event_type = "dna_update"`) containing the old value, new value,
and delta for each dimension, so that `GET /api/assessment/session/{id}/report`
(Story 3-28) can display a "growth since last session" view showing how the learner
improved across all 9 dimensions in this session.

## Background & Context

### Why growth tracking?

`fuse_learner_dna()` (Story 3-25) already has both the old dimension values (read
at Step 3 from `learner_dna`) and the new EMA-blended values (computed at Step 4)
before it upserts to the DB at Step 5. This is the only place where both sides of
the delta are available — reading them again from the DB in a separate function
would require a second round-trip and introduce a race condition risk.

The growth tracking therefore adds a **Step 6** to `fuse_learner_dna()`: after the
`learner_dna` upsert succeeds, call `record_dna_growth()` with the old and new dims.
Growth events are **analytics / observability data** — failure must be non-fatal.
A failed growth write must never prevent the session from completing or the DNA
from being updated.

### Separation of concerns (matches established pattern)

```
dna_fusion.py   — EMA math, learner_dna upsert       (Story 3-25 — DONE)
dna_profile.py  — LLM profile text, profile_text upsert (Story 3-26 — DONE)
dna_growth.py   — growth events, session_events insert  (THIS STORY)
```

`dna_growth.py` is a NEW file. `dna_fusion.py` is MODIFIED (add Step 6 call only).

### session_events table schema (applied migration — never modify)

```sql
CREATE TABLE public.session_events (
  id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id  uuid        NOT NULL REFERENCES public.sessions(session_id) ON DELETE CASCADE,
  event_type  text        NOT NULL,
  payload     jsonb       NOT NULL DEFAULT '{}',
  created_at  timestamptz NOT NULL DEFAULT now()
);
```

Key observations:
- **No `user_id` column** — access is via `session_id`
- `payload` is JSONB — Python dicts map directly
- `event_type` is plain text — no CHECK constraint, value `"dna_update"` is our convention
- `session_id` FK is NOT NULL — must always be provided

### Payload contract (one row per dimension, 9 rows per fusion)

```json
{
  "dimension": "pattern_recognition",
  "old_value": 65.0,
  "new_value": 69.5,
  "delta": 4.5
}
```

- `dimension`: one of the 9 exact column names from `_NINE_DIMENSIONS` in `dna_fusion.py`
- `old_value`: `float | null` — `null` when no prior DB row existed (first session)
- `new_value`: `float` — always present, clamped [0.0, 100.0] by `_apply_ema()`
- `delta`: `round(new_value - old_value, 4)` when both float; `null` when `old_value` is null

### First session edge case

On a user's first session, `old_row` in `fuse_learner_dna()` Step 3 is `{}` (empty dict,
no DB row yet). All 9 `old_row.get(dim)` calls return `None`. In growth events:
- `old_value = None` (JSON `null`) — correct, there was no prior value
- `delta = None` (JSON `null`) — cannot compute delta without a prior value
- `new_value` = the EMA-blended result (using `_NEUTRAL = 50.0` as the phantom base)

### Insertion strategy: single bulk insert

Supabase client supports bulk insert: `table.insert([row1, row2, ...]).execute()`.
Use ONE `asyncio.to_thread` call inserting all 9 rows at once — NOT 9 separate calls.
This matches the codebase pattern and avoids 9× DB round-trips per session end.

### asyncio.to_thread pattern (match dna_fusion.py exactly)

```python
resp = await asyncio.to_thread(
    lambda: supabase.table("session_events").insert(rows).execute()
)
```

### Log injection prevention

Follow the `_safe_uid` pattern from `dna_profile.py`:
```python
_safe_sid = str(session_id).replace("\n", " ").replace("\r", " ")
```
Use `_safe_sid` in all logger calls — never pass `session_id` directly to logger.

### Where to add Step 6 in dna_fusion.py

After line 354 (`logger.info("DNA fusion: updated user=...")`) — wait, actually Step 6
should happen BEFORE the logger.info success log, but AFTER the upsert try/except.
The insertion point is immediately after the `try/except` block for the upsert
(after `except HTTPException: raise` and `except Exception: raise`) and before
the existing `logger.info(...)` success line.

```python
# ── Step 6: Write growth tracking events (non-fatal) ──────────────────────
old_dims_for_growth: dict[str, float | None] = {
    dim: (float(old_row[dim]) if old_row.get(dim) is not None else None)
    for dim in _NINE_DIMENSIONS
}
await record_dna_growth(
    session_id=session_id,
    old_dims=old_dims_for_growth,
    new_dims=new_dims,
    supabase=supabase,
)
```

`record_dna_growth` must be a **local import** inside `fuse_learner_dna()` to avoid
circular imports at module load time (same pattern as `generate_dna_profile_text`
in `dna_profile.py`).

---

## Acceptance Criteria

**AC 1** — `apps/api/app/modules/assessment/dna_growth.py` is created, importable
without error, and exports exactly `__all__ = ["record_dna_growth"]`.

**AC 2** — `record_dna_growth` async function signature is keyword-only:
```python
async def record_dna_growth(
    *,
    session_id: str,
    old_dims: dict[str, float | None],
    new_dims: dict[str, float],
    supabase: Any,
) -> int:
```
Positional calls raise `TypeError`.

**AC 3** — For each dimension in `new_dims`, `record_dna_growth` builds a row dict:
```python
{
    "session_id": session_id,
    "event_type": "dna_update",
    "payload": {
        "dimension": dim_name,
        "old_value": old_float_or_none,
        "new_value": new_float,
        "delta": delta_or_none,
    },
}
```

**AC 4** — All rows are inserted in a **single** `supabase.table("session_events").insert(rows)` call
wrapped in `asyncio.to_thread`. NOT 9 separate insert calls.

**AC 5** — `delta = round(new_value - old_value, 4)` when `old_value` is a float. `delta = None`
when `old_value is None` (first session — no prior value). 4 decimal places to match the precision
used by `_apply_ema()` in `dna_fusion.py`.

**AC 6** — On DB exception → log WARNING, return `0`. Non-fatal. The growth event failure must
not raise `HTTPException` or any other exception to the caller.

**AC 7** — On `insert_resp.error` truthy → log WARNING with sanitized error, return `0`. Non-fatal.

**AC 8** — On success → log INFO with inserted row count and sanitized session_id, return the count of
inserted rows (normally 9 when `new_dims` has all 9 dimensions).

**AC 9** — `record_dna_growth` with empty `new_dims` (`{}`) returns `0` without calling Supabase.

**AC 10** — `record_dna_growth` uses `_safe_sid = str(session_id).replace("\n", " ").replace("\r", " ")`
in all logger calls (log injection prevention).

**AC 11** — `fuse_learner_dna()` in `apps/api/app/modules/assessment/dna_fusion.py` is modified to call
`record_dna_growth` as **Step 6**, immediately after the `learner_dna` upsert succeeds (after the
outer `try/except` block, before `logger.info("DNA fusion: updated...")`).

**AC 12** — `record_dna_growth` is imported as a **local import** inside `fuse_learner_dna()`:
```python
from app.modules.assessment.dna_growth import record_dna_growth
```
This pattern prevents circular import risk at module load time.

**AC 13** — `old_dims_for_growth` passed to `record_dna_growth` is built from `old_row`:
```python
old_dims_for_growth = {
    dim: (float(old_row[dim]) if old_row.get(dim) is not None else None)
    for dim in _NINE_DIMENSIONS
}
```
When a dimension was `None` in `old_row` (first session), `old_dims_for_growth[dim] = None`.

**AC 14** — `fuse_learner_dna()` return value (`new_dims`) is unchanged regardless of whether
`record_dna_growth` succeeds or fails.

**AC 15** — `dna_growth.py` contains zero `import openai` or `from openai` lines. Verified by AST
scan test.

**AC 16** — `dna_growth.py` contains zero hardcoded model strings (`"gpt-4o-mini"`, `"gpt-4o"`).
Verified by source scan test.

**AC 17** — `test_dna_growth.py` at `apps/api/tests/test_dna_growth.py` contains ≥ 20
`@pytest.mark.unit` tests, all passing. Full suite has 0 regressions.

**AC 18** — `record_dna_growth` failure (any exception) does NOT prevent `fuse_learner_dna()`
from returning `new_dims`. Verified by test that patches `record_dna_growth` to raise and confirms
`fuse_learner_dna()` still returns the dict.

---

## Tasks

- [x] Task 1: Create apps/api/app/modules/assessment/dna_growth.py — ✓ 2026-07-06
  - [x] 1.1 Module docstring: separation from dna_fusion.py, no-LLM rule, analytics-only purpose
  - [x] 1.2 `from __future__ import annotations` + imports (asyncio, logging, Any)
  - [x] 1.3 `__all__ = ["record_dna_growth"]`
  - [x] 1.4 Implement `record_dna_growth(*, session_id, old_dims, new_dims, supabase) -> int`
    - [x] 1.4a Early-exit: if `not new_dims`, return `0` without touching DB (AC 9)
    - [x] 1.4b Build `_safe_sid` for log injection prevention (AC 10)
    - [x] 1.4c Build rows list: iterate `new_dims.items()`, compute `old_val`, `delta` (AC 3, 5)
    - [x] 1.4d Single bulk `asyncio.to_thread` insert all rows (AC 4)
    - [x] 1.4e Check `resp.error` truthy → WARNING + return 0 (AC 7)
    - [x] 1.4f Log INFO on success, return inserted count (AC 8)
    - [x] 1.4g `except Exception` → WARNING + return 0 (AC 6)

- [x] Task 2: Modify apps/api/app/modules/assessment/dna_fusion.py — add Step 6 — ✓ 2026-07-06
  - [x] 2.1 After the `learner_dna` upsert try/except block, add Step 6 comment block
  - [x] 2.2 Build `old_dims_for_growth` dict from `old_row` (AC 13)
  - [x] 2.3 Add local import `from app.modules.assessment.dna_growth import record_dna_growth` (AC 12)
  - [x] 2.4 `await record_dna_growth(session_id=session_id, old_dims=old_dims_for_growth, new_dims=new_dims, supabase=supabase)` (AC 11)
  - [x] 2.5 Verify: `fuse_learner_dna()` return value and existing behaviour unchanged (AC 14)
  - [x] 2.6 Verify: existing 29 tests in `test_dna_fusion.py` still pass (0 regressions)

- [x] Task 3: Write apps/api/tests/test_dna_growth.py (RED → GREEN) — ✓ 2026-07-06
  - [x] 3.1 `test_dunder_all_exports_only_record_dna_growth`
  - [x] 3.2 `test_positional_args_raise_type_error`
  - [x] 3.3 `test_record_dna_growth_inserts_9_rows_for_all_dims`
  - [x] 3.4 `test_record_dna_growth_uses_single_bulk_insert` — verify insert called once
  - [x] 3.5 `test_record_dna_growth_payload_structure` — all 4 keys present + correct types
  - [x] 3.6 `test_record_dna_growth_delta_computed_correctly` — `round(new - old, 4)`
  - [x] 3.7 `test_record_dna_growth_delta_precision_4_decimal_places`
  - [x] 3.8 `test_record_dna_growth_old_value_none_first_session` — `old_value=None`, `delta=None`
  - [x] 3.9 `test_record_dna_growth_mixed_old_some_none` — some dims have old, some don't
  - [x] 3.10 `test_record_dna_growth_event_type_is_dna_update` — all rows have correct event_type
  - [x] 3.11 `test_record_dna_growth_session_id_in_all_rows`
  - [x] 3.12 `test_record_dna_growth_empty_new_dims_returns_zero_no_db_call`
  - [x] 3.13 `test_record_dna_growth_db_exception_returns_zero`
  - [x] 3.14 `test_record_dna_growth_insert_error_field_returns_zero`
  - [x] 3.15 `test_record_dna_growth_returns_inserted_count`
  - [x] 3.16 `test_fuse_learner_dna_calls_record_dna_growth_after_upsert`
  - [x] 3.17 `test_fuse_learner_dna_growth_failure_does_not_prevent_return` (AC 14)
  - [x] 3.18 `test_fuse_learner_dna_old_dims_for_growth_none_on_first_session`
  - [x] 3.19 `test_no_openai_import_in_dna_growth` (AST scan — AC 15)
  - [x] 3.20 `test_no_hardcoded_model_string_in_dna_growth` (AC 16)

- [x] Task 4: Run full test suite — AC 17 — ✓ 2026-07-06
  - [x] 4.1 `pytest -m unit tests/test_dna_growth.py` → 20/20 passed
  - [x] 4.2 `pytest -m unit tests/test_dna_fusion.py` → 29/29 passed (0 regressions)
  - [x] 4.3 Full suite `pytest -m unit` → 0 new regressions (pre-existing Dev 4 failures unchanged)

---

## Dev Notes

### Files being MODIFIED

```
apps/api/app/modules/assessment/dna_fusion.py   — ADD Step 6 only (~10 lines)
```

### Files being CREATED (NEW)

```
apps/api/app/modules/assessment/dna_growth.py   — NEW ~70 lines
apps/api/tests/test_dna_growth.py               — NEW ≥ 20 unit tests
```

### Files NOT touched

```
apps/api/app/modules/assessment/dna_profile.py  — no changes
apps/api/app/modules/assessment/prompts.py      — no changes
apps/api/app/modules/assessment/router.py       — no changes (no new endpoints)
apps/api/app/modules/assessment/service.py      — no changes
apps/api/app/config.py                          — no new settings
supabase/migrations/                            — NEVER modify applied migrations
packages/shared/                               — read-only for Dev 3
```

### Exact dna_fusion.py insertion point

After line ~353 (just before the final `logger.info`), add Step 6. The function body
currently ends:

```python
    # (end of Step 5 upsert try/except)
    logger.info(
        "DNA fusion: updated user=%s session=%s session_count=%d",
        user_id,
        session_id,
        old_session_count + 1,
    )
    return new_dims
```

Becomes:

```python
    # ── Step 6: Write growth tracking events (non-fatal) ──────────────────────
    from app.modules.assessment.dna_growth import record_dna_growth  # local import
    old_dims_for_growth: dict[str, float | None] = {
        dim: (float(old_row[dim]) if old_row.get(dim) is not None else None)
        for dim in _NINE_DIMENSIONS
    }
    await record_dna_growth(
        session_id=session_id,
        old_dims=old_dims_for_growth,
        new_dims=new_dims,
        supabase=supabase,
    )

    logger.info(
        "DNA fusion: updated user=%s session=%s session_count=%d",
        user_id,
        session_id,
        old_session_count + 1,
    )
    return new_dims
```

### Supabase bulk insert (single round-trip)

```python
# CORRECT — one asyncio.to_thread for all 9 rows
resp = await asyncio.to_thread(
    lambda: supabase.table("session_events").insert(rows).execute()
)

# WRONG — 9 separate round-trips
for row in rows:
    await asyncio.to_thread(
        lambda: supabase.table("session_events").insert(row).execute()
    )
```

### Complete dna_growth.py template

```python
"""DNA growth tracking — writes dna_update events after each learner_dna upsert.

Called by fuse_learner_dna() as Step 6 after the learner_dna upsert succeeds.
Writes one session_events row per dimension (9 total) recording the old value,
new EMA-blended value, and delta. Non-fatal: returns 0 on any failure.

No LLM calls. No model strings. Pure analytics write.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["record_dna_growth"]


async def record_dna_growth(
    *,
    session_id: str,
    old_dims: dict[str, float | None],
    new_dims: dict[str, float],
    supabase: Any,
) -> int:
    """Insert dna_update session_events rows for each dimension in new_dims.

    Builds one row per dimension with payload:
        {"dimension": str, "old_value": float|None, "new_value": float, "delta": float|None}

    delta = round(new - old, 4) when old is float; None when old is None (first session).

    Args:
        session_id: UUID of the session that just ended.
        old_dims:   {dim: old_float | None} — None means no prior DB row (first session).
        new_dims:   {dim: new_float} — EMA-blended values from fuse_learner_dna.
        supabase:   Synchronous Supabase client (service-role key).

    Returns:
        Number of rows inserted (normally 9); 0 on any failure.
    """
    if not new_dims:
        return 0

    _safe_sid = str(session_id).replace("\n", " ").replace("\r", " ")

    rows = []
    for dim, new_val in new_dims.items():
        old_val = old_dims.get(dim)
        delta = round(new_val - old_val, 4) if old_val is not None else None
        rows.append({
            "session_id": session_id,
            "event_type": "dna_update",
            "payload": {
                "dimension": dim,
                "old_value": old_val,
                "new_value": new_val,
                "delta": delta,
            },
        })

    try:
        resp = await asyncio.to_thread(
            lambda: supabase.table("session_events").insert(rows).execute()
        )
        insert_error = getattr(resp, "error", None)
        if insert_error:
            safe_err = str(insert_error).replace("\n", " ").replace("\r", " ")
            logger.warning(
                "DNA growth: insert error session=%s: %s",
                _safe_sid,
                safe_err,
            )
            return 0
        inserted = len(resp.data or [])
        logger.info("DNA growth: inserted %d rows session=%s", inserted, _safe_sid)
        return inserted
    except Exception as exc:
        logger.warning("DNA growth: insert exception session=%s: %s", _safe_sid, exc)
        return 0
```

### Test helper patterns

```python
def _all_new_dims(value: float = 70.0) -> dict[str, float]:
    return {
        "pattern_recognition": value,
        "logical_deduction": value,
        "processing_speed": value,
        "frustration_tolerance": value,
        "persistence": value,
        "help_seeking": value,
        "goal_orientation": value,
        "curiosity_index": value,
        "study_independence": value,
    }


def _all_old_dims(value: float | None = 65.0) -> dict[str, float | None]:
    return {k: value for k in _all_new_dims()}


def _supabase_mock_growth(
    insert_raises: bool = False,
    insert_error: bool = False,
    inserted_count: int = 9,
):
    supabase = MagicMock()
    tbl = MagicMock()

    def _resp(data):
        r = MagicMock()
        r.data = data
        r.error = None
        return r

    if insert_raises:
        tbl.insert.return_value.execute.side_effect = Exception("DB insert failed")
    elif insert_error:
        err_resp = MagicMock()
        err_resp.error = "some db error"
        err_resp.data = None
        tbl.insert.return_value.execute.return_value = err_resp
    else:
        tbl.insert.return_value.execute.return_value = _resp(
            [{"id": f"uuid-{i}"} for i in range(inserted_count)]
        )

    supabase.table.return_value = tbl
    return supabase


# For testing fuse_learner_dna integration:
# Patch record_dna_growth at the module level it's IMPORTED into (dna_fusion):
# patch("app.modules.assessment.dna_growth.record_dna_growth", new_callable=AsyncMock)
# BUT since it's a LOCAL import inside the function body, you need to patch the
# module where it's defined:
# patch("app.modules.assessment.dna_growth.record_dna_growth", new_callable=AsyncMock)
```

### Patching record_dna_growth in fuse_learner_dna tests

Since `record_dna_growth` is a local import inside `fuse_learner_dna()`, to patch it
in tests for `dna_fusion.py`, patch at its definition module:

```python
with patch(
    "app.modules.assessment.dna_growth.record_dna_growth",
    new_callable=AsyncMock,
) as mock_growth:
    result = await fuse_learner_dna(...)
    mock_growth.assert_called_once()
```

### Rule: non-fatal, always

`record_dna_growth` MUST NOT raise under any circumstances. It must always return `int`.
The reasoning: growth events are analytics. If they fail, the session still completed
successfully and the learner_dna still got updated. Surfacing a 503 for a failed
analytics write would be a disproportionate response.

### Rule: no session_count in growth payload

The payload contains only `{dimension, old_value, new_value, delta}`.
Do NOT add `session_count`, `user_id`, or any other fields. The `session_id` foreign key
links back to the session (and through it to the user). Lean schema.

### Rule: 9 rows per call (when all dims present)

The caller (`fuse_learner_dna`) always passes all 9 `_NINE_DIMENSIONS` in `new_dims`.
The test `test_record_dna_growth_inserts_9_rows_for_all_dims` must explicitly assert
that exactly 9 rows were in the insert payload.

---

## Dev Agent Record

### Debug Log

- Test 17 `test_fuse_learner_dna_growth_failure_does_not_prevent_return` failed initially because
  Step 6 in `dna_fusion.py` had no try/except guard. Fixed by wrapping `await record_dna_growth(...)`
  in try/except per AC 14 ("non-fatal"). `record_dna_growth` is internally non-fatal, but the
  integration guard is belt-and-suspenders.

### Completion Notes

- 20/20 new tests GREEN, 29/29 `test_dna_fusion.py` regression tests GREEN (49/49 total)
- Pre-existing Dev 4 failures (test_tutor_graph, test_tutor_service, 9× test_websocket_session)
  unchanged — confirmed by git stash verification
- `record_dna_growth` is always non-fatal internally (returns 0 on any exception)
- Step 6 in `fuse_learner_dna` adds belt-and-suspenders try/except so growth tracking can never
  propagate exceptions to the session-end handler
- Local import pattern (`from app.modules.assessment.dna_growth import record_dna_growth` inside
  `fuse_learner_dna`) prevents circular import risk at module load time

### File List

| File | Action |
|------|--------|
| `apps/api/app/modules/assessment/dna_growth.py` | CREATED — 70 lines, `record_dna_growth` |
| `apps/api/app/modules/assessment/dna_fusion.py` | MODIFIED — Step 6 added (~14 lines) |
| `apps/api/tests/test_dna_growth.py` | CREATED — 20 unit tests |

### Change Log

| Date | Change |
|------|--------|
| 2026-07-06 | Story created — Sprint 3 Task 5 |
| 2026-07-06 | Implementation complete — 20/20 tests GREEN, 0 regressions |
| 2026-07-06 | Code review complete — 5-agent adversarial review, 2 BLOCKERs + 1 decision |

---

## Senior Developer Review (AI)

**Review date:** 2026-07-06
**Review outcome:** Changes Requested
**Agents:** Story Quality, Blind Hunter (Security), Test Coverage, AC Completeness, Process Integrity

### Action Items

#### Decision-Needed

- [x] [Review][Decision] Module boundary: `dna_growth.py` writes directly to `session_events` without going through `analytics.service` — Resolved: Option B applied — `write_system_events()` added to `analytics/service.py`; `dna_growth.py` now routes through it via local import.

#### BLOCKERs (patch before merge)

- [x] [Review][Patch] R1 — AC 10 missing test: no test verifies `_safe_sid` log sanitization. Add `caplog` test passing `session_id="evil\nsession\rid"` and asserting `\n`/`\r` absent from log output. [apps/api/tests/test_dna_growth.py] — FIXED: `test_record_dna_growth_session_id_sanitized_in_logs` added; 21/21 GREEN
- [x] [Review][Patch] R2 — Log injection at `dna_fusion.py:369`: `logger.warning("DNA fusion: growth tracking failed session=%s: %s", session_id, exc)` uses raw `session_id`. Fix: `_safe_sid = str(session_id).replace("\n", " ").replace("\r", " ")` before the try block and use `_safe_sid` in the catch. [apps/api/app/modules/assessment/dna_fusion.py:369] — FIXED: `_safe_sid_growth` added before try block at Step 6

#### Deferred (non-blocking)

- [x] [Review][Defer] R4 — NaN/Inf float: `round(nan - old, 4)` = nan silently causes insert failure. Add `math.isfinite` guard. [dna_growth.py:56] — deferred, pre-existing pattern, non-fatal
- [x] [Review][Defer] R5 — DB error message logs internal schema detail verbatim at WARNING level. Demote raw error to DEBUG. [dna_growth.py:73-79] — deferred, pre-existing codebase pattern
- [x] [Review][Defer] R6 — `asyncio.to_thread` not verified by test (only single bulk insert count is checked). Add AST scan. [tests/test_dna_growth.py] — deferred, behavioral coverage adequate
- [x] [Review][Defer] R7 — `resp.data=None` on success returns 0 silently (Supabase `return=minimal` mode). [dna_growth.py:81] — deferred, non-fatal, no user impact
- [x] [Review][Defer] R8 — ACs 6/7/8: log level/message not captured in tests. [tests/test_dna_growth.py] — deferred, return value verification sufficient

**Dismissed (noise/non-vulnerabilities):** 3 (JSONB injection, dim key injection, lambda closure race — all confirmed non-issues by Blind Hunter)

---

### R3 Detail — Module Boundary Decision

**Finding:** `dna_growth.py` line 70 writes directly to `session_events` from within the `assessment` module. CLAUDE.md one-discipline rule: "modules communicate only through service layer, never via direct DB access into another module's tables."

**Context:**
- `dna_fusion.py` lines 273-282 already reads from `session_events` directly (accepted in Story 3-25)
- `analytics/service.py`'s `ingest_events()` is designed for user-triggered events with ownership validation — NOT for system-generated events
- A separate `analytics.service.write_system_event()` function would be the strict-compliance fix

**Recommendation (Option A — Preferred):** Accept `session_events` as cross-module accessible, document exception in CLAUDE.md. Rationale: the read was already accepted, the table is infrastructure (not domain-specific to analytics), and analytics service was not designed for system writes.

**Option B (strict compliance):** Add `analytics.service.write_system_event(session_id, event_type, payload, supabase)` that skips user-ownership check, and call it from `dna_growth.py`.

### Review Follow-ups (AI)

- [x] R1 — Add caplog test for AC 10 log injection prevention
- [x] R2 — Fix raw session_id in dna_fusion.py:369 logger call
- [x] R3 — Resolve module boundary decision (Option B applied — write_system_events added to analytics.service)
