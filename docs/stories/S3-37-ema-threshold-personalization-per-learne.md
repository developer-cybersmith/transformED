# Story S3-37 — EMA Threshold Personalization: Per-Learner CES Baseline Update After Session Finalization

**Status:** Draft  
**Sprint:** Sprint 3  
**Dev:** Dev 3 (formula + Redis write) + Dev 4 (threshold read in process_attention_signal)  
**Branch:** `implemented/ces-fallback`  
**Depends on:** S3-35 (session finalization — `ces_final` must be written to DB before EMA update runs)  
**Decisions implemented:** D11 (session finalization trigger), D15 (shared utility hook)  
**Migration:** NO — no new DB table; EMA lives in Redis only

---

## User Story

**As a learner** completing repeated sessions on TransformED,  
**I want** the CES intervention threshold to adapt to my personal engagement baseline,  
**so that** interventions fire when my engagement drops below *my* normal level — not at a static cutoff that ignores my history.

**As the system** (tutor state machine),  
**I want** a per-user EMA (`user:{user_id}:ces_ema`) available in Redis before each session begins,  
**so that** `process_attention_signal` can read a personalized threshold without any synchronous DB lookup during the 5-second CES window.

---

## Background

`process_attention_signal` in `apps/api/app/modules/tutor/service.py` compares the computed CES value against `settings.ces_threshold` (default 50.0, a static env var). This is identical for every user, regardless of individual engagement history.

`apps/api/app/modules/assessment/ces_baseline.py` already contains `compute_and_store_ces_baseline()`, which computes a rolling average of recent sessions. That function was designed to be called after session finalization (S3-35) and is already implemented. However, the rolling average serves a different purpose than intervention thresholding — it is used for percentile comparison in session reports.

This story adds a second Redis key (`user:{user_id}:ces_ema`) holding an EMA-smoothed CES score that drives dynamic threshold computation in `process_attention_signal`. The two keys remain independent:

| Redis key | Purpose | Who writes | Who reads |
|---|---|---|---|
| `user:{user_id}:ces_baseline` | Rolling average (last N sessions); session report percentile | `compute_and_store_ces_baseline()` | `get_session_report` |
| `user:{user_id}:ces_ema` | EMA for dynamic intervention threshold | `update_ces_ema()` (new) | `process_attention_signal` |

### EMA and Threshold Formulas

```
EMA_n = alpha × ces_final_n + (1 − alpha) × EMA_{n−1}   (default alpha = 0.30)

threshold_n = clamp(EMA_n × 0.75, floor=40.0, ceiling=65.0)
```

First session (no prior EMA): `EMA = ces_final` (own value seeds the EMA).

Examples at default alpha=0.30 and floor/ceiling=40.0/65.0:

| EMA | 0.75 × EMA | Clamped threshold |
|-----|-----------|-------------------|
| 50  | 37.5      | 40.0 (floor)      |
| 70  | 52.5      | 52.5              |
| 90  | 67.5      | 65.0 (ceiling)    |

A learner averaging CES 70 gets a threshold of 52.5 — a higher bar than the static 50.0.  
A learner averaging CES 55 gets a threshold of 41.25 — more sensitive than the static 50.0.  
Floor = 40.0 prevents hair-trigger interventions; ceiling = 65.0 prevents under-sensitivity.

### Defect Addressed

**D67 — `ces_baseline` computed but never used for threshold; static 50.0 used for all users** — opened by this story; closed when AC 2 and AC 6 are satisfied.

---

## Acceptance Criteria

**AC 1** — `update_ces_ema` function exists and is importable from `app.modules.assessment.ces_baseline`:

```python
from app.modules.assessment.ces_baseline import update_ces_ema
```

Function signature (keyword-only after `user_id` and `ces_final`):

```python
async def update_ces_ema(
    user_id: str,
    ces_final: float,
    *,
    redis: Redis,
    settings: Settings,
) -> float:
```

**AC 2** — First session (Redis key `user:{user_id}:ces_ema` absent): the function sets `new_ema = ces_final` exactly (no blending). For input `ces_final = 70.0`, `redis.get` returns `None`, the function writes `"70.0000"` to Redis and returns `70.0`.

**AC 3** — Subsequent session (prior EMA exists in Redis): the function applies `new_ema = alpha × ces_final + (1 − alpha) × old_ema`. For `ces_final = 80.0`, `old_ema = 60.0`, `alpha = 0.30`: `new_ema = 0.30 × 80.0 + 0.70 × 60.0 = 24.0 + 42.0 = 66.0`. Return value is `66.0` rounded to 4 decimal places.

**AC 4** — Redis key pattern is `user:{user_id}:ces_ema`. For `user_id = "user-abc"`, the key written is `"user:user-abc:ces_ema"`. Any other key pattern is a defect.

**AC 5** — TTL is `30 × 86400 = 2592000` seconds. `redis.set` is called with `ex=2592000`. The EMA key does not persist indefinitely.

**AC 6** — `process_attention_signal` (Dev 4 code, `apps/api/app/modules/tutor/service.py`) reads `user:{user_id}:ces_ema` from Redis. If the key is present, threshold = `max(settings.ces_threshold_floor, min(settings.ces_threshold_ceiling, ema × 0.75))`. If absent (new user or TTL expired), threshold = `settings.ces_threshold` (static fallback). The fallback is logged at DEBUG level with the user_id and static value.

**AC 7** — `update_ces_ema` is called non-blocking after `finalize_session` writes `ces_final`. It is dispatched via `asyncio.create_task()` so a Redis failure in EMA update does not propagate to the session finalization response. The call site is in the finalize flow introduced by S3-35.

**AC 8** — The three new `Settings` fields are added to `apps/api/app/config.py` with these defaults:

```python
ces_ema_alpha: float = Field(default=0.30, ge=0.0, le=1.0, ...)
ces_threshold_floor: float = Field(default=40.0, ge=0.0, le=100.0, ...)
ces_threshold_ceiling: float = Field(default=65.0, ge=0.0, le=100.0, ...)
```

All three are readable via env vars `CES_EMA_ALPHA`, `CES_THRESHOLD_FLOOR`, `CES_THRESHOLD_CEILING`.

**AC 9** — Return value is rounded to 4 decimal places. For `ces_final = 66.123456789`, the EMA (first session) is stored as `"66.1235"` and returned as `66.1235`.

**AC 10** — No hardcoded `30 * 86400` integer literal in `ces_baseline.py`; the TTL is computed from a named constant `_EMA_TTL_SECONDS = 30 * 86_400` (or equivalent named constant). Verified by AST scan test.

**AC 11** — No hardcoded `0.30`, `0.70`, `40.0`, or `65.0` literals in the EMA update function body; all come from `settings.*` fields. Verified by AST scan test.

**AC 12** — When `redis.get` raises an exception in `update_ces_ema`, the exception is caught, logged at WARNING, and the function returns `ces_final` as the EMA (fail-open: first-session behaviour). The Redis write is also skipped silently on failure.

**AC 13** — `__all__` in `ces_baseline.py` is extended to include `"update_ces_ema"`.

**AC 14** — No ruff errors in modified files (`apps/api/app/modules/assessment/ces_baseline.py`, `apps/api/app/config.py`, `apps/api/app/modules/tutor/service.py`). CI passes clean.

**AC 15** — Unit test count: minimum 18 tests in `apps/api/tests/test_ces_ema.py`, all marked `@pytest.mark.unit`, all passing. Full test suite has 0 regressions.

**AC 16** — `docs/DEFECT-REGISTER.md` entry D67 updated from "OPEN" to "FIXED" with the guard name `test_update_ces_ema_first_session` and the implementing story ID `S3-37`.

---

## Tasks / Subtasks

- [ ] **T1 — Write RED tests** (`apps/api/tests/test_ces_ema.py`)
  - [ ] T1.1 All 18+ tests import `update_ces_ema` — fail on `ImportError` initially
  - [ ] T1.2 Confirm `pytest -m unit tests/test_ces_ema.py` exits non-zero (all failing)

- [ ] **T2 — Config additions** (`apps/api/app/config.py`)
  - [ ] T2.1 Add `ces_ema_alpha: float = Field(default=0.30, ge=0.0, le=1.0)`
  - [ ] T2.2 Add `ces_threshold_floor: float = Field(default=40.0, ge=0.0, le=100.0)`
  - [ ] T2.3 Add `ces_threshold_ceiling: float = Field(default=65.0, ge=0.0, le=100.0)`
  - [ ] T2.4 Verify `@model_validator` for CES weight sum is unaffected

- [ ] **T3 — Implement `update_ces_ema()`** (`apps/api/app/modules/assessment/ces_baseline.py`)
  - [ ] T3.1 Add `_EMA_TTL_SECONDS = 30 * 86_400` module constant
  - [ ] T3.2 Implement first-session path (`redis.get` returns `None` → EMA = `ces_final`)
  - [ ] T3.3 Implement subsequent-session path (EMA blend formula)
  - [ ] T3.4 Round result to 4 decimal places before writing and returning
  - [ ] T3.5 Wrap `redis.get` and `redis.set` in try/except; log WARNING on failure; return `ces_final` on any error
  - [ ] T3.6 Update `__all__` to include `"update_ces_ema"`

- [ ] **T4 — Integrate into finalize_session flow** (S3-35 code path)
  - [ ] T4.1 After `compute_and_store_ces_baseline()` call in `finalize_session`, dispatch `asyncio.create_task(update_ces_ema(user_id, ces_final, redis=redis, settings=settings))`
  - [ ] T4.2 Confirm the create_task pattern does not await the result (non-blocking)

- [ ] **T5 — Dev 4 coordination: dynamic threshold in `process_attention_signal`**
  - [ ] T5.1 Read `user:{user_id}:ces_ema` from Redis before CES trigger check
  - [ ] T5.2 Compute `threshold = max(floor, min(ceiling, ema * 0.75))` if EMA present
  - [ ] T5.3 Fall back to `settings.ces_threshold` if EMA absent; log at DEBUG
  - [ ] T5.4 Confirm EMA read does not block the 5-second signal window

- [ ] **T6 — GREEN + REFACTOR**
  - [ ] T6.1 `pytest -m unit tests/test_ces_ema.py` → ≥18 PASSED
  - [ ] T6.2 `ruff check apps/api/app/modules/assessment/ces_baseline.py apps/api/app/config.py apps/api/app/modules/tutor/service.py` → 0 errors
  - [ ] T6.3 Full unit suite → 0 regressions

- [ ] **T7 — Register + tracker updates**
  - [ ] T7.1 Update `docs/DEFECT-REGISTER.md` D67 → FIXED
  - [ ] T7.2 Update `docs/dev3-assessment-tracker.md`

- [ ] **T8 — 6-agent adversarial code review**

---

## Scale & Load

**Q1 — Unit of work and range:**  
One `REDIS GET user:{user_id}:ces_ema` + one `REDIS SET` per session finalization. Per active session during TEACHING, one additional `REDIS GET` per 5-second CES window to read the EMA for threshold computation. At a typical 30-minute lesson with a 5-second cadence: 360 REDIS GETs (one per window) + 1 REDIS SET at finalization. All O(1), ~40 bytes per key. No growth over session duration — EMA is a single overwriting float, not an accumulating list.

**Q2 — Fixed budgets while input varies:**  
EMA is one float per user. It is unconditionally overwritten on each update — no accumulation. TTL = 30 days caps key lifetime; the key expires automatically for inactive users. No storage budget concern: 10,000 concurrent users × ~40 bytes per EMA key = ~400 KB Redis footprint. The alpha coefficient (0.30 default) is an env var; changing it affects threshold sensitivity but not storage or performance.

**Q3 — Scope of every limit:**  
Per-user. `user:{user_id}:ces_ema` is keyed by `user_id` from the JWT — no cross-user interference. Floor/ceiling config values are per-deployment (same for all users) but the EMA value and resulting threshold are per-user. Rate-limit scope is not applicable — EMA writes happen at most once per session end, and reads happen at the 5-second cadence already governed by the existing signal pipeline.

**Q4 — Unbounded reads/writes:**  
REDIS GET (1 per 5-second window): bounded by session duration, itself bounded by `max_attention_signals_per_session` (D13). REDIS SET (1 per session finalization): bounded by one per session. No unbounded accumulation. The EMA read inside `process_attention_signal` is a single O(1) GET — identical cost structure to the existing `ces_history` reads already in that function.

**Q5 — Inherited caps re-derived:**  
`ces_ema_alpha = 0.30` — same coefficient used in `dna_fusion.py` for Learner DNA dimension EMA. Re-derived for this use case: α = 0.30 means each session contributes 30% weight; 5 sessions blend in ~83% of the user's recent history. Floor = 40.0 and ceiling = 65.0 are newly sized against the static 50.0 default: floor prevents intervention for any learner whose baseline EMA is below 53.3 (0.75 × 53.3 = 40.0); ceiling prevents non-intervention for any learner whose EMA is above 86.7. Both bounds are configurable without redeploy.

**Q6 — Check-then-act under concurrent requests:**  
`update_ces_ema` performs a Redis GET followed by a Redis SET. Two concurrent finalization calls for the same user (theoretically impossible — one session finalizes at a time per user — but covered for correctness) would both read the same prior EMA and both write the same new EMA (same inputs → same output). The result is idempotent. No advisory lock is needed because both writes produce the same value. If they differ (e.g., two sessions finalized in the same millisecond), the last writer prevails — both values are valid EMA updates, and the error is bounded to one session cycle.

---

## Security

1. **JWT ownership**: `user_id` passed to `update_ces_ema` must originate from the JWT-decoded subject (`user.id`) established by `get_current_user` at the router level. The function itself does not validate `user_id` — it trusts the caller. The call site in `finalize_session` must use the session-owner's `user_id`, not a caller-supplied value.

2. **Redis key namespacing**: Keys are `user:{user_id}:ces_ema`. A user cannot influence another user's EMA key because `user_id` is JWT-sourced. No user-supplied input is interpolated into the key beyond the JWT subject.

3. **No DB writes**: `update_ces_ema` writes only to Redis. It does not access any Supabase table. No RLS consideration applies.

4. **EMA value bounds**: The stored EMA is a float derived from `ces_final`, which is itself clamped to [0, 100] by the CES formula. A malformed Redis value (e.g., corrupted string) is caught by the `float()` conversion and triggers the error-handling path (fail-open: treat as first session).

5. **Threshold floor/ceiling prevents adversarial threshold manipulation**: Even if an attacker could write an arbitrary `user:{user_id}:ces_ema` to Redis (they cannot without service-role access), the clamping formula `max(floor, min(ceiling, ema × 0.75))` bounds the dynamic threshold to [40.0, 65.0]. An injected EMA of 0.0 → threshold = 40.0. An injected EMA of 1,000,000 → threshold = 65.0. Neither extreme bypasses the intervention system.

---

## Test Requirements

All tests live in `apps/api/tests/test_ces_ema.py` and are marked `@pytest.mark.unit`.

| # | Test name | What it verifies (AC ref) |
|---|-----------|---------------------------|
| 1 | `test_update_ces_ema_first_session` | First session: EMA = ces_final, no blending (AC 2) |
| 2 | `test_update_ces_ema_second_session` | EMA = 0.30 × 80.0 + 0.70 × 60.0 = 66.0 (AC 3) |
| 3 | `test_update_ces_ema_clamp_floor` | EMA=50 → 0.75×50=37.5 → clamped to 40.0 (AC 6, threshold formula) |
| 4 | `test_update_ces_ema_clamp_ceiling` | EMA=90 → 0.75×90=67.5 → clamped to 65.0 (AC 6, threshold formula) |
| 5 | `test_update_ces_ema_mid_range` | EMA=70 → 0.75×70=52.5 within bounds (AC 6, threshold formula) |
| 6 | `test_update_ces_ema_writes_to_redis` | `redis.set` called with key `user:{user_id}:ces_ema` (AC 4) |
| 7 | `test_update_ces_ema_30_day_ttl` | `redis.set` called with `ex=2592000` (AC 5) |
| 8 | `test_update_ces_ema_returns_float` | Return value is a `float` (AC 9) |
| 9 | `test_update_ces_ema_rounded_4dp` | Return rounded to 4 decimal places (AC 9) |
| 10 | `test_update_ces_ema_redis_value_is_string` | Value written to Redis is a `str` (AC 4 — Redis SET requires string) |
| 11 | `test_update_ces_ema_alpha_configurable` | alpha=1.0: new EMA = 1.0 × ces_final + 0.0 × old = ces_final (AC 8) |
| 12 | `test_update_ces_ema_alpha_zero` | alpha=0.0: EMA unchanged from old value (AC 8) |
| 13 | `test_update_ces_ema_bytes_from_redis` | Redis returns bytes (b"60.0"); float() decodes correctly (AC 3 robustness) |
| 14 | `test_update_ces_ema_ces_final_100` | Edge case: ces_final=100.0 on first session (AC 2) |
| 15 | `test_update_ces_ema_redis_read_failure_fallback` | redis.get raises → returns ces_final (fail-open) (AC 12) |
| 16 | `test_update_ces_ema_redis_write_failure_silent` | redis.set raises → no exception propagated (AC 12) |
| 17 | `test_update_ces_ema_no_hardcoded_ttl_literal` | AST scan: no raw integer `2592000` in source (AC 10) |
| 18 | `test_update_ces_ema_no_hardcoded_alpha_literal` | AST scan: no raw `0.30` or `0.70` in function body (AC 11) |
| 19 | `test_dunder_all_includes_update_ces_ema` | `update_ces_ema` in `ces_baseline.__all__` (AC 13) |

---

## Dependencies

- **S3-35** (session finalization) — must be complete and merged before S3-37 implementation begins. The `finalize_session()` helper introduced by S3-35 is the call site for `asyncio.create_task(update_ces_ema(...))`.
- **D16** (branch merge order) — `implemented/ces-fallback` must merge to `main` after S3-42, S3-43, S3-44 are merged (in that order).

## Decision References

| Decision | Description | Relevance to S3-37 |
|----------|-------------|-------------------|
| D11 | `UPDATE sessions SET ces_final=X, ended_at=NOW()` | Finalization writes `ces_final` — the input to EMA |
| D15 | Shared utility `compute_ces_from_session_aggregates()` called from both report and finalize | Finalize flow (S3-35) where EMA update is dispatched |
| D16 | Branch merge order | Deployment sequencing for this story |
| D67 | Static threshold for all users — opened by this story | Closed when AC 2 and AC 6 are satisfied |

## Migration

**NO** — no new database table or column. EMA lives exclusively in Redis under `user:{user_id}:ces_ema`. The 30-day TTL means no migration clean-up is needed; keys expire automatically.
