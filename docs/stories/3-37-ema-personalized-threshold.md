# Story 3-37 — EMA-Based Personalized Intervention Threshold

**Sprint:** Sprint 3 (CES v2 hardening)
**Dev:** Dev 3 (formula + Redis write) + Dev 4 (threshold read in process_attention_signal)
**Status:** ready-for-dev
**Branch:** `sprint3/s3-37-ema-personalized-threshold`
**Depends on:** Story 3-35 (session finalization — ces_final must be in DB for EMA to update)

---

## Background

`process_attention_signal` in `apps/api/app/modules/tutor/service.py:315-319` compares
`ces_value` against `settings.ces_threshold` (default 50.0, a static env var). This is the
same number for every user, every lesson, regardless of that user's individual engagement
baseline.

`apps/api/app/modules/assessment/ces_baseline.py` exists with a function
`compute_and_store_ces_baseline(user_id, session_id, supabase, redis, settings)` that computes
a rolling average of the last N sessions' `ces_final` values and caches it in Redis
`user:{user_id}:ces_baseline`. This function has zero callers in application code (Story 3-35
adds the first caller — the post-session trigger). The baseline value is never read by
`process_attention_signal`; the static threshold is used instead.

CLAUDE.md §11 specifies: "CES monitoring ONLY active in TEACHING state" and "2-minute cooldown
after any intervention". It does not specify an EMA formula for the threshold. The EMA formula
below is derived from industry practice for adaptive engagement scoring (same pattern used in
`dna_fusion.py` for dimension updates: `new = retain × old + (1-retain) × signal`).

EMA formula:
```
EMA_n = 0.30 × ces_final_n + 0.70 × EMA_{n-1}
```
Dynamic threshold:
```
threshold_n = clamp(EMA_n × 0.75, 40.0, 65.0)
```

A student whose typical CES is 70 gets a threshold of 52.5 (personalized, higher bar than
the static 50.0). A student whose typical CES is 55 gets 41.25 (lower bar, more sensitive).
Floor = 40.0 prevents over-sensitivity; ceiling = 65.0 prevents under-sensitivity.

### Defect Record

| ID | Description | Status |
|----|-------------|--------|
| D67 | `ces_baseline` computed but never used for threshold — static 50.0 used for all users | Opened by S3-37 |

---

## Acceptance Criteria

### AC 1 — EMA updated after every session finalization
After `finalize_session()` writes `ces_final` (Story 3-35, AC 3 baseline trigger), a new
`update_ces_ema(user_id, ces_final, redis, settings)` function is called. It:
1. Reads `user:{user_id}:ces_ema` from Redis (float; may be absent for first session)
2. If absent: EMA = `ces_final` (first session sets its own value as baseline)
3. If present: EMA = `0.30 × ces_final + 0.70 × previous_ema`
4. Writes `user:{user_id}:ces_ema` with TTL = 30 days (12 × 86400 s)

### AC 2 — Dynamic threshold computed from EMA in process_attention_signal
`process_attention_signal` reads `user:{user_id}:ces_ema` from Redis. If present, threshold =
`clamp(ema × 0.75, 40.0, 65.0)`. If absent (new user, no sessions yet), falls back to
`settings.ces_threshold` (default 50.0). The fallback is logged at DEBUG level.

### AC 3 — EMA update is non-blocking and non-fatal
`update_ces_ema()` is called via `asyncio.create_task()` in the `finalize_session` flow
(piggybacked on the baseline trigger call). A Redis failure in EMA update does not propagate.

### AC 4 — EMA is stored separate from ces_baseline
Redis key for EMA: `user:{user_id}:ces_ema` (new key). Redis key for baseline rolling average:
`user:{user_id}:ces_baseline` (existing key). Both exist independently. EMA = intervention
threshold. Baseline = percentile comparison for session reports.

### AC 5 — EMA coefficient is configurable
`settings.ces_ema_alpha: float = Field(default=0.30, ge=0.0, le=1.0)` added to `config.py`.
Threshold bounds are similarly configurable: `settings.ces_threshold_floor = 40.0`,
`settings.ces_threshold_ceiling = 65.0`.

### AC 6 — No ruff errors

### AC 7 — Unit tests: 18 minimum
At minimum 18 unit tests: first-session EMA (EMA = ces_final), second-session EMA (EMA =
0.30 × new + 0.70 × old), clamp at floor (input EMA = 48 → threshold = 40.0), clamp at
ceiling (input EMA = 90 → threshold = 65.0), mid-range (EMA = 70 → threshold = 52.5),
fallback to settings.ces_threshold when Redis key absent, EMA non-blocking (create_task
called), alpha configurable via settings.

---

## Tasks / Subtasks

- [ ] **T1** Write RED tests
- [ ] **T2** Add `ces_ema_alpha`, `ces_threshold_floor`, `ces_threshold_ceiling` to `config.py`
- [ ] **T3** Implement `update_ces_ema(user_id, ces_final, redis, settings)` in `ces_baseline.py`
- [ ] **T4** Integrate `update_ces_ema` call into `finalize_session` flow (Story 3-35 helper); ensure non-blocking
- [ ] **T5** Coordinate with Dev 4: update `process_attention_signal` to read EMA from Redis and use dynamic threshold
- [ ] **T6** Run `ruff check` + `pytest -m unit` — all pass
- [ ] **T7** 6-agent adversarial code review

---

## Scale & Load

**Q1 — Unit of work and range:**
One `GET user:{user_id}:ces_ema` Redis read per 5-second CES window per active session.
One `SET user:{user_id}:ces_ema` Redis write per session finalization. Both are O(1).

**Q2 — Fixed budgets vs variable input:**
EMA is a single float. Redis key size is fixed (~30 bytes key + 8 bytes value). TTL = 30 days
caps key lifetime. No accumulation; each update overwrites the previous value.

**Q3 — Scope of every limit:**
Per-user. `user:{user_id}:ces_ema` is namespaced by `user_id` — no cross-user interference.
At 10,000 concurrent users the Redis keyspace for EMA = 10,000 keys × ~40 bytes = ~400 KB,
within any reasonable Redis memory budget.

**Q4 — Unbounded reads/writes:**
One Redis GET per 5-second window. Bounded by session duration and the 5 s interval. One
Redis SET per session end. No unbounded accumulation.

**Q5 — Inherited caps re-derived:**
`ces_ema_alpha = 0.30` — derived from standard exponential smoothing literature; the same
0.30/0.70 split is used in `dna_fusion.py` for DNA dimension EMA. Re-derived: α = 0.30 gives
each session ~30% weight in the EMA, so a user's threshold adapts meaningfully after 3–5
sessions. Consistent with DNA fusion pattern already accepted by team review.

**Q6 — Check-then-act under concurrency:**
Redis SET is atomic; two concurrent `update_ces_ema` calls for the same user (impossible in
normal flow — one session finalizes at a time per user, but covered for correctness) would
result in the last writer's value prevailing. Both EMA values would be valid (differ only by
the ordering); no corruption. No advisory lock needed.

---

## Definition of Done

- [ ] Story file committed before any implementation code
- [ ] RED tests written and confirmed failing before implementation
- [ ] Implementation makes all tests GREEN (minimum 18 unit tests)
- [ ] Ruff: 0 errors in modified files
- [ ] 6-agent adversarial code review passed
- [ ] `docs/dev3-assessment-tracker.md` updated
- [ ] PR merged to main

---

## Dev Notes

### EMA update helper

```python
# apps/api/app/modules/assessment/ces_baseline.py

async def update_ces_ema(
    user_id: str,
    ces_final: float,
    *,
    redis,
    settings,
) -> float:
    """Update per-user EMA for dynamic intervention threshold.

    Returns new EMA value.
    Redis key: user:{user_id}:ces_ema (30-day TTL).
    """
    key = f"user:{user_id}:ces_ema"
    raw = await redis.get(key)
    alpha = settings.ces_ema_alpha  # default 0.30

    if raw is None:
        new_ema = ces_final
    else:
        old_ema = float(raw)
        new_ema = alpha * ces_final + (1.0 - alpha) * old_ema

    new_ema = round(new_ema, 4)
    await redis.set(key, str(new_ema), ex=30 * 86400)
    return new_ema
```

### Dynamic threshold in process_attention_signal (Dev 4 change)

```python
# apps/api/app/modules/tutor/service.py::process_attention_signal (Dev 4 code)

ema_raw = await redis.get(f"user:{user_id}:ces_ema")
if ema_raw is not None:
    ema = float(ema_raw)
    floor = settings.ces_threshold_floor    # 40.0
    ceiling = settings.ces_threshold_ceiling  # 65.0
    threshold = max(floor, min(ceiling, ema * 0.75))
else:
    logger.debug("[ces_threshold] No EMA for user %s — using static %.1f", user_id, settings.ces_threshold)
    threshold = settings.ces_threshold
```

### Files to modify

- `apps/api/app/config.py` — add `ces_ema_alpha`, `ces_threshold_floor`, `ces_threshold_ceiling`
- `apps/api/app/modules/assessment/ces_baseline.py` — add `update_ces_ema()`
- `apps/api/app/modules/assessment/service.py` — integrate `update_ces_ema` call into `finalize_session`
- `apps/api/app/modules/tutor/service.py` — Dev 4 updates threshold read
- `apps/api/tests/test_ces_ema.py` — new test file
