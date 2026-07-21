---
status: ready-for-dev
baseline_commit: ""
---

# Story 3-31 — Re-assessment Prompt After 10 Sessions

## Story

**As a** learner who has completed 10 or more sessions,
**I want** the platform to recognise that my Learner DNA profile may have drifted,
**So that** I am prompted to retake the 20-question onboarding diagnostic and refresh my profile.

---

## Background & Context

Learner DNA is built from Exponential Moving Average fusion across sessions. After 10 sessions,
the EMA has compounded enough drift that the onboarding baseline may no longer reflect the
learner's current patterns — a fresh diagnostic re-anchors the profile.

The trigger lives in `fuse_learner_dna()` (post-upsert Step 7): when `session_count`
reaches a multiple of 10, a Redis flag `user:{user_id}:reassessment_due = "1"` is set.
`GET /assessment/user/dna` reads that flag and returns `reassessment_due: true`.
The frontend displays a re-assessment prompt banner when this field is true.
When the user completes the onboarding form again via `POST /assessment/onboarding/submit`,
the flag is cleared and the cycle resets.

The `LearnerDNA.reassessment_due: bool = False` field already exists in the frozen
API contract in `router.py` — it is currently hardcoded to `False`. This story wires
the real logic.

**Dependency boundary (Dev 3 only):**
- `fuse_learner_dna()` is called by Dev 4's WebSocket handler after `ces_final` is written.
  Dev 4's caller signature must NOT change — adding `redis=None` is purely additive.
- The router `get_learner_dna()` already calls `get_learner_dna_data()` — adding
  the `redis` argument is internal to Dev 3.

---

## Acceptance Criteria

**AC 1** — `_REASSESSMENT_INTERVAL: int = 10` is defined as a module-level constant in
`apps/api/app/modules/assessment/dna_fusion.py`. Never hardcode `10` elsewhere.

**AC 2** — `fuse_learner_dna()` signature gains an optional keyword-only `redis=None`
parameter. Existing callers that pass no `redis` continue to work without modification.
Positional call with `redis` still raises `TypeError` (keyword-only contract preserved
— all params are `*` kwargs).

**AC 3** — After the Step 5 upsert succeeds, a new **Step 7** in `fuse_learner_dna()`:
```python
new_count = old_session_count + 1
if new_count % _REASSESSMENT_INTERVAL == 0 and redis is not None:
    _safe_uid = str(user_id).replace("\n", " ").replace("\r", " ")
    try:
        await redis.set(f"user:{user_id}:reassessment_due", "1")
        logger.info("DNA fusion: reassessment flag set for user=%s at count=%d", _safe_uid, new_count)
    except Exception as exc:
        logger.warning("DNA fusion: reassessment flag set failed user=%s: %s", _safe_uid, exc)
```
Non-fatal: Redis failure logs WARNING and does NOT raise `HTTPException` or re-raise.
The function still returns `new_dims` regardless.

**AC 4** — The Redis flag `user:{user_id}:reassessment_due = "1"` is set (not overwritten
silently — `.set()` replaces existing) at `session_count = 10, 20, 30` (every multiple of
`_REASSESSMENT_INTERVAL`). Not set at counts 1, 5, 9, 11, 19.

**AC 5** — When `redis=None` (default), Step 7 is a no-op: no Redis call is made at all.
Verified by test asserting Redis mock is never called when `redis=None`.

**AC 6** — `get_learner_dna_data()` in `apps/api/app/modules/assessment/service.py` gains
an optional keyword-only `redis=None` parameter.

**AC 7** — Inside `get_learner_dna_data()`, after fetching the `learner_dna` row,
read `reassessment_due` from Redis:
```python
reassessment_due: bool = False
if redis is not None:
    try:
        val = await redis.get(f"user:{user_id}:reassessment_due")
        reassessment_due = val is not None
    except Exception as exc:
        logger.warning("get_learner_dna_data: redis check failed user=%s: %s", safe_uid, exc)
        reassessment_due = False
```
Key exists (any truthy string) → `True`. Key absent (`None`) → `False`.
Redis exception → `False` (non-fatal, log WARNING).

**AC 8** — When `redis=None`, `reassessment_due` is `False` without any Redis operation.
This preserves backward compatibility for any unit tests that call `get_learner_dna_data()`
without a `redis` param.

**AC 9** — The `get_learner_dna()` router handler in `router.py` passes `redis=get_redis()`
to `get_learner_dna_data()`:
```python
body = await get_learner_dna_data(user_id=user_id, supabase=supabase, redis=get_redis())
```
`get_redis` is imported lazily inside the handler (same local-import pattern as `get_supabase`).

**AC 10** — The `submit_onboarding_diagnostic()` router handler clears the reassessment flag
after successful processing. After the `result = await process_onboarding(...)` line succeeds,
add:
```python
# Clear re-assessment flag (non-fatal)
try:
    await redis.delete(f"user:{user_id}:reassessment_due")
except Exception as exc:
    logger.warning("onboarding: reassessment flag clear failed user=%s: %s", user_id, exc)
```
`redis` is already in scope (existing variable from the onboarding idempotency logic).
The delete is non-fatal: failure logs WARNING, does NOT prevent the onboarding result from
being returned.

**AC 11** — `GET /assessment/user/dna` end-to-end contract: when the Redis flag is set,
`LearnerDNA.reassessment_due == True` in the JSON response. When flag is absent or cleared,
`reassessment_due == False`. Verified by unit tests mocking Redis.

**AC 12** — Security: `user_id` in the Redis key comes exclusively from `current_user["sub"]`
(JWT-decoded at router level), never from any request body field. Verified structurally by
inspecting router.py — the `user_id: str = current_user["sub"]` line precedes the Redis call.

**AC 13** — Log-injection prevention: all logger calls that include `user_id` use
`_safe_uid = str(user_id).replace("\n", " ").replace("\r", " ")`, matching the existing
log-injection prevention pattern in `dna_fusion.py` and `dna_growth.py`.

**AC 14** — `test_reassessment_flag.py` at `apps/api/tests/test_reassessment_flag.py`
contains ≥ 15 `@pytest.mark.unit` tests covering all ACs, all passing.

**AC 15** — Full suite `pytest -m unit` has 0 regressions. Existing `test_dna_fusion.py`
and `test_session_report_endpoint.py` tests still pass without modification (additive
`redis=None` default preserves their mock setups).

---

## Tasks

- [ ] Task 1: Add `_REASSESSMENT_INTERVAL` constant and `redis=None` param to `dna_fusion.py`
  - [ ] 1.1 Add `_REASSESSMENT_INTERVAL: int = 10` constant after the other signal constants
  - [ ] 1.2 Add `redis=None` as a keyword-only parameter to `fuse_learner_dna()` signature
  - [ ] 1.3 Update the function docstring to document `redis` param

- [ ] Task 2: Implement Step 7 (reassessment flag) in `fuse_learner_dna()`
  - [ ] 2.1 After Step 6 (growth tracking) block, add Step 7 comment block
  - [ ] 2.2 Compute `new_count = old_session_count + 1` (reuse the value already computed for the upsert payload)
  - [ ] 2.3 Guard: `if new_count % _REASSESSMENT_INTERVAL == 0 and redis is not None:`
  - [ ] 2.4 Build `_safe_uid` for log injection prevention (AC 13)
  - [ ] 2.5 `await redis.set(f"user:{user_id}:reassessment_due", "1")` in try block
  - [ ] 2.6 Log INFO on success; except Exception → WARNING + do not re-raise (AC 3)
  - [ ] 2.7 Verify: function still returns `new_dims` regardless of Redis outcome (AC 5)

- [ ] Task 3: Add `redis=None` param to `get_learner_dna_data()` in `service.py`
  - [ ] 3.1 Add `redis=None` as keyword-only param to `get_learner_dna_data()` signature
  - [ ] 3.2 After the `row = resp.data` assignment, add the Redis flag check block (AC 7)
  - [ ] 3.3 Build `safe_uid` for log injection prevention in the Redis check block
  - [ ] 3.4 Return `"reassessment_due": reassessment_due` (replaces the hardcoded `False`)
  - [ ] 3.5 Verify: when `redis=None`, `reassessment_due` is `False` without Redis call (AC 8)

- [ ] Task 4: Wire `redis=get_redis()` in router endpoints (AC 9, AC 10)
  - [ ] 4.1 In `get_learner_dna()` handler: add lazy import `from app.core.redis import get_redis`
  - [ ] 4.2 Pass `redis=get_redis()` to `get_learner_dna_data()` call
  - [ ] 4.3 In `submit_onboarding_diagnostic()` handler: add non-fatal reassessment flag clear
        after `result = await process_onboarding(...)` succeeds (before `return result`)

- [ ] Task 5: Write `apps/api/tests/test_reassessment_flag.py` (RED → GREEN)
  - [ ] 5.1 `test_reassessment_interval_constant_is_10` — AC 1
  - [ ] 5.2 `test_fuse_dna_redis_param_defaults_to_none` — call without redis, confirm no Redis call
  - [ ] 5.3 `test_fuse_dna_sets_flag_at_session_10` — AC 4 (count=9→10, flag set)
  - [ ] 5.4 `test_fuse_dna_sets_flag_at_session_20` — AC 4 (count=19→20, flag set)
  - [ ] 5.5 `test_fuse_dna_sets_flag_at_session_30` — AC 4 (count=29→30, flag set)
  - [ ] 5.6 `test_fuse_dna_does_not_set_flag_at_session_11` — AC 4 (non-multiple, no set call)
  - [ ] 5.7 `test_fuse_dna_does_not_set_flag_at_session_1` — AC 4 (count=0→1, no set call)
  - [ ] 5.8 `test_fuse_dna_redis_failure_is_non_fatal` — AC 3 (Redis.set raises → still returns new_dims)
  - [ ] 5.9 `test_fuse_dna_redis_none_skips_step7` — AC 5 (redis=None, Redis mock never called)
  - [ ] 5.10 `test_get_learner_dna_data_flag_true_when_key_exists` — AC 7 (redis.get returns "1" → True)
  - [ ] 5.11 `test_get_learner_dna_data_flag_false_when_key_absent` — AC 7 (redis.get returns None → False)
  - [ ] 5.12 `test_get_learner_dna_data_flag_false_when_redis_none` — AC 8 (no redis → False, no call)
  - [ ] 5.13 `test_get_learner_dna_data_redis_exception_returns_false` — AC 7 (exception → False, non-fatal)
  - [ ] 5.14 `test_submit_onboarding_clears_reassessment_flag` — AC 10 (redis.delete called after success)
  - [ ] 5.15 `test_submit_onboarding_flag_clear_failure_is_non_fatal` — AC 10 (delete raises → still returns result)

- [ ] Task 6: Run full test suite — AC 14, AC 15
  - [ ] 6.1 `pytest -m unit tests/test_reassessment_flag.py` → ≥ 15/15 PASSED
  - [ ] 6.2 `pytest -m unit tests/test_dna_fusion.py` → all PASSED (0 regressions from redis=None default)
  - [ ] 6.3 `pytest -m unit` full suite → 0 new failures

---

## Dev Notes

### Files Being MODIFIED

```
apps/api/app/modules/assessment/dna_fusion.py   — Add constant + redis=None + Step 7
apps/api/app/modules/assessment/service.py      — Add redis=None to get_learner_dna_data()
apps/api/app/modules/assessment/router.py       — Wire get_redis() in 2 endpoints
```

### Files Being CREATED (NEW)

```
apps/api/tests/test_reassessment_flag.py        — NEW ≥ 15 unit tests
```

### Files NOT Touched

```
supabase/migrations/   — No DB column changes; Redis handles the flag
packages/shared/       — Read-only for Dev 3
apps/api/app/modules/assessment/dna_growth.py   — No changes
apps/api/app/modules/assessment/dna_profile.py  — No changes
apps/api/app/modules/assessment/prompts.py      — No changes
apps/api/app/config.py                          — No new settings needed
```

### Existing `dna_fusion.py` Structure (as of main)

The function ends with:
```python
    # ── Step 6: Write growth tracking events (non-fatal) ──────────────────────
    from app.modules.assessment.dna_growth import record_dna_growth  # local import
    old_dims_for_growth = {dim: (...) for dim in _NINE_DIMENSIONS}
    _safe_sid_growth = str(session_id).replace("\n", " ").replace("\r", " ")
    try:
        await record_dna_growth(...)
    except Exception as exc:
        logger.warning("DNA fusion: growth tracking failed session=%s: %s", _safe_sid_growth, exc)

    logger.info("DNA fusion: updated user=%s session=%s session_count=%d", ...)
    return new_dims
```

Insert **Step 7** AFTER the Step 6 try/except block but BEFORE the final `logger.info` and `return`.

### `old_session_count + 1` Value

`old_session_count + 1` is already computed as part of the upsert payload:
```python
upsert_payload = {"user_id": user_id, "session_count": old_session_count + 1, **new_dims}
```
Reuse this as `new_count = old_session_count + 1` in Step 7. Do NOT call Supabase again
to re-read `session_count`.

### `get_learner_dna_data()` Current Return (on main — to be modified)

```python
return {
    "user_id": str(row["user_id"]),
    "badge_labels": row.get("badge_labels") or [],
    "profile_text": row.get("profile_text"),
    "session_count": int(row.get("session_count") or 0),
    "reassessment_due": False,   # <-- REPLACE with Redis-backed bool
    "last_updated": row.get("last_updated"),
}
```

### `submit_onboarding_diagnostic()` Current Router Structure

The handler already has `redis` in scope (used for onboarding idempotency via
`user:{user_id}:onboarding_done` key). The reassessment clear uses the same `redis` object.
No new import needed.

Current flow:
```python
redis = get_redis()
was_set = await redis.set(onboarding_key, "1", nx=True)
if not was_set:
    raise HTTPException(409, ...)
try:
    result = await process_onboarding(...)
except HTTPException:
    await redis.delete(onboarding_key)
    raise
return result                 # ← INSERT reassessment clear BEFORE this line
```

After the `except HTTPException` block ends and before `return result`:
```python
try:
    await redis.delete(f"user:{user_id}:reassessment_due")
except Exception as exc:
    logger.warning("onboarding: reassessment flag clear failed user=%s: %s", user_id, exc)
return result
```

A `logger` import already exists in `router.py`? Check. If not, add:
```python
import logging
logger = logging.getLogger(__name__)
```
at the top of `router.py`.

### Redis Key Pattern

```
user:{user_id}:reassessment_due  →  "1"   (key present = due)
                                   absent  (key deleted = not due)
```
No TTL — the key persists until cleared by `submit_onboarding_diagnostic()`.

### Test Mock Pattern for `fuse_learner_dna`

For Step 7 tests, mock `redis` as an `AsyncMock`:
```python
from unittest.mock import AsyncMock, MagicMock, patch

mock_redis = AsyncMock()
mock_redis.set = AsyncMock()

# Patch the DB calls as before; pass redis=mock_redis
result = await fuse_learner_dna(
    user_id="user-123",
    session_id="sess-456",
    supabase=mock_supabase,
    settings=mock_settings,
    redis=mock_redis,
)
mock_redis.set.assert_called_once_with("user:user-123:reassessment_due", "1")
```

For `get_learner_dna_data` Redis tests:
```python
mock_redis = AsyncMock()
mock_redis.get = AsyncMock(return_value="1")   # key exists → True

body = await get_learner_dna_data(user_id="user-123", supabase=mock_supabase, redis=mock_redis)
assert body["reassessment_due"] is True
```

### Log Injection Convention

Match the pattern already in `dna_fusion.py`:
```python
_safe_uid = str(user_id).replace("\n", " ").replace("\r", " ")
logger.info("...", _safe_uid, ...)
```
Never pass `user_id` directly to any logger call.

---

## Senior Developer Review

*(To be completed after implementation and code review — not pre-filled.)*

---

## Dev Agent Record

### Completion Notes

*(To be filled by dev agent on task completion.)*

### File List

*(To be filled by dev agent on task completion.)*

### Change Log

*(To be filled by dev agent on task completion.)*
