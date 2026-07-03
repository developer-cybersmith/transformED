---
status: in-progress
baseline_commit: ""
---

# Story 3-24 — Per-Learner CES Baseline Computation

## Story

As **Dev 4 (WebSocket / tutor state machine)**, I want an async
`compute_and_store_ces_baseline(user_id, supabase, redis, settings)` function
that reads a user's most recent completed sessions' CES final scores from
Supabase, computes a rolling average, caches the result in Redis under
`user:{user_id}:ces_baseline`, and returns the baseline as a float (or None if no
data exists), so that I can use the current session's CES deviation from baseline
to calibrate intervention thresholds and Learner DNA delta direction.

## Background & Context

### Why a baseline?
The raw CES score (0–100, computed by `compute_ces()` every 5 s) measures
instantaneous engagement. The *baseline* contextualises it: a CES of 55 is good
progress for a student whose history averages 40, but below-par for one who
usually scores 80. Sprint 3 Task 3 (Learner DNA fusion) uses the baseline to
determine delta direction.

### Data source
`sessions.ces_final` — written by Dev 4's WebSocket handler at session end.  
`sessions.ended_at` — non-NULL indicates a completed session.  
`sessions.user_id` — ownership.

### Redis key correction
The sprint tracker mentions `session:{session_id}:ces_baseline`. This is
semantically incorrect — the baseline is a per-user rolling average, not a
per-session value. The correct key is `user:{user_id}:ces_baseline`, consistent
with the existing patterns `user:{user_id}:dna` and
`user:{user_id}:onboarding_done` documented in the initial migration.

### Settings additions
Two new env-var-driven fields are added to `Settings` (never hardcoded):
- `CES_BASELINE_WINDOW` (default 5) — number of recent sessions to average
- `CES_BASELINE_TTL_SECONDS` (default 86400) — Redis key TTL in seconds

### Call contract (for Dev 4)
```python
from app.modules.assessment.ces_baseline import compute_and_store_ces_baseline

# Called after writing ces_final to the sessions table:
baseline: float | None = await compute_and_store_ces_baseline(
    user_id=user_id,
    supabase=supabase,
    redis=redis,
    settings=settings,
)
# baseline is None → first ever session, or no CES recorded yet
# baseline is float → rolling average of last N sessions (0.0–100.0, 4 d.p.)
```

## Acceptance Criteria

**AC 1** — `ces_baseline.py` is created at
`apps/api/app/modules/assessment/ces_baseline.py` and is importable without error.

**AC 2** — `__all__ = ["compute_and_store_ces_baseline"]` — only the public
async function is exported.

**AC 3** — Function signature is keyword-only async:
```
async def compute_and_store_ces_baseline(
    *,
    user_id: str,
    supabase: Any,
    redis: Redis,
    settings: Settings,
) -> float | None
```
Positional calls raise `TypeError`.

**AC 4** — Single completed session: baseline equals that session's `ces_final`
(rounded to 4 d.p.).

**AC 5** — Fewer than `window` completed sessions (e.g., 3 when window=5):
baseline is the simple average of all available scores, not zero-padded.

**AC 6** — More than `window` sessions available: baseline is the average of the
most recent `settings.ces_baseline_window` sessions only (ordered by `ended_at DESC`).
Older sessions are excluded.

**AC 7** — Rows where `ces_final IS NULL` are excluded from the average.
Only rows where both `ces_final IS NOT NULL` and `ended_at IS NOT NULL` count.

**AC 8** — When no completed sessions have a non-NULL `ces_final`, the function
returns `None` and does NOT write any key to Redis.

**AC 9** — The computed baseline is written to Redis key
`user:{user_id}:ces_baseline` as a string-encoded float
(e.g., `"65.4200"`). The key format is derived from the `user_id` argument,
not from any other identifier.

**AC 10** — The Redis key is set with `ex=settings.ces_baseline_ttl_seconds`
(default 86400 s = 24 h). Keys do not persist indefinitely.

**AC 11** — `ces_baseline_window: int = Field(default=5, ge=1, le=50)` is added
to `Settings` in `config.py`. Configurable via env var `CES_BASELINE_WINDOW`.

**AC 12** — `ces_baseline_ttl_seconds: int = Field(default=86400, ge=60)` is
added to `Settings` in `config.py`. Configurable via env var
`CES_BASELINE_TTL_SECONDS`.

**AC 13** — A Redis write failure (e.g., network error, Redis down) is caught,
logged at WARNING level, and does NOT propagate — the function still returns
the computed baseline float.

**AC 14** — A Supabase query failure raises
`HTTPException(status_code=503, detail="Could not read session history.")`.
The exception is logged at ERROR level before raising.

**AC 15** — No hardcoded numeric window literal (`5`) appears in
`ces_baseline.py` — the window always comes from `settings.ces_baseline_window`.
Verified by AST scan at test time.

**AC 16** — `ces_baseline.py` imports no forbidden modules: `supabase` (client),
`openai`, `posthog`, `httpx`, `requests`. Verified by AST scan.

**AC 17** — The Supabase query fetches at most
`settings.ces_baseline_window * 3` rows (a bounded over-fetch to account for
NULL-`ces_final` rows), ordered `ended_at DESC`. It never performs an unbounded
full-table scan.

**AC 18** — Baseline returned and stored in Redis is rounded to 4 decimal places,
consistent with `compute_ces()` output precision.

**AC 19** — `test_ces_baseline.py` contains ≥ 15 `@pytest.mark.unit` tests, all
passing. Full suite has 0 regressions.

## Tasks

- [ ] Task 1: Add `ces_baseline_window` and `ces_baseline_ttl_seconds` to Settings
  - [ ] 1.1 Add `ces_baseline_window: int = Field(default=5, ge=1, le=50, ...)` after CES weights block
  - [ ] 1.2 Add `ces_baseline_ttl_seconds: int = Field(default=86400, ge=60, ...)` after window field
  - [ ] 1.3 Verify existing `@model_validator` unaffected (only validates CES weight sum)

- [ ] Task 2: Create `apps/api/app/modules/assessment/ces_baseline.py`
  - [ ] 2.1 Module docstring + `__all__ = ["compute_and_store_ces_baseline"]`
  - [ ] 2.2 Private `_redis_key(user_id: str) -> str` returns `user:{user_id}:ces_baseline`
  - [ ] 2.3 Private `_compute_baseline(scores: list[float]) -> float | None` — pure avg, None on empty
  - [ ] 2.4 Async `compute_and_store_ces_baseline(*, user_id, supabase, redis, settings)` implementation
    - [ ] 2.4a Supabase query wrapped in `asyncio.to_thread`, catches exceptions → HTTPException 503
    - [ ] 2.4b Filter rows: `ces_final IS NOT NULL` AND `ended_at IS NOT NULL`, take window scores
    - [ ] 2.4c Return `None` early if no scores (no Redis write)
    - [ ] 2.4d Redis `SET key value EX ttl` — catches exceptions → logs WARNING, does NOT raise
    - [ ] 2.4e Return `float | None` baseline

- [ ] Task 3: Write `apps/api/tests/test_ces_baseline.py` (RED → GREEN)
  - [ ] 3.1 `test_dunder_all_exports_only_compute_and_store`
  - [ ] 3.2 `test_positional_args_raise_type_error`
  - [ ] 3.3 `test_redis_key_format` — verifies `user:{id}:ces_baseline` format
  - [ ] 3.4 `test_compute_baseline_single_score` — AC 4
  - [ ] 3.5 `test_compute_baseline_fewer_than_window` — AC 5
  - [ ] 3.6 `test_compute_baseline_exactly_window` — AC 6
  - [ ] 3.7 `test_compute_baseline_empty_returns_none` — AC 8
  - [ ] 3.8 `test_compute_baseline_rounded_to_4dp` — AC 18
  - [ ] 3.9 `test_async_returns_none_when_no_sessions` — AC 8 (async, mocked)
  - [ ] 3.10 `test_async_single_session_baseline` — AC 4 (async, mocked)
  - [ ] 3.11 `test_async_rolling_window_uses_most_recent` — AC 6 (async, mocked)
  - [ ] 3.12 `test_async_skips_null_ces_final_rows` — AC 7 (async, mocked)
  - [ ] 3.13 `test_async_writes_correct_redis_key` — AC 9 (async, mocked)
  - [ ] 3.14 `test_async_sets_correct_ttl` — AC 10 (async, mocked)
  - [ ] 3.15 `test_async_redis_failure_does_not_raise` — AC 13 (async, mocked)
  - [ ] 3.16 `test_async_db_failure_raises_503` — AC 14 (async, mocked)
  - [ ] 3.17 `test_no_hardcoded_window_literal` — AC 15 (AST)
  - [ ] 3.18 `test_no_forbidden_imports` — AC 16 (AST)
  - [ ] 3.19 `test_async_no_redis_write_when_no_sessions` — AC 8 (Redis.set NOT called)

- [ ] Task 4: Run full test suite — AC 19
  - [ ] 4.1 `pytest -m unit tests/test_ces_baseline.py` → all pass
  - [ ] 4.2 Full suite → 0 regressions

## Dev Notes

### Supabase query pattern
Uses synchronous supabase-py v2 client wrapped in `asyncio.to_thread`, matching the
pattern established in `service.py`. The query:
```python
resp = await asyncio.to_thread(
    lambda: supabase.table("sessions")
    .select("ces_final, ended_at")
    .eq("user_id", user_id)
    .order("ended_at", desc=True)
    .limit(settings.ces_baseline_window * 3)
    .execute()
)
```
NULL filtering is performed in Python after fetching (avoids supabase-py IS NOT NULL
API ambiguity). The `*3` multiplier means we fetch at most 15 rows by default
(window=5), safely bounded.

### Redis client
`redis.asyncio.Redis` from `app.core.redis.get_redis()`. Already `decode_responses=True`.
Write: `await redis.set(key, str(baseline), ex=ttl)` — stores as string, e.g. `"65.4200"`.

### Test mocking pattern
```python
from unittest.mock import AsyncMock, MagicMock
supabase = MagicMock()
redis = AsyncMock()
mock_resp = MagicMock()
mock_resp.data = [{"ces_final": 75.0, "ended_at": "2026-07-01T10:00:00"}]
supabase.table.return_value.select.return_value.eq.return_value\
    .order.return_value.limit.return_value.execute.return_value = mock_resp
```
`asyncio.to_thread` invokes the lambda synchronously in a thread — MagicMock
is synchronous, so it works correctly under `asyncio.to_thread`.

### Settings factory for tests
```python
def _settings(window: int = 5, ttl: int = 86400) -> Settings:
    return Settings(
        supabase_url="http://x", supabase_anon_key="x",
        supabase_service_role_key="x", supabase_jwt_secret="x",
        openai_api_key="x", sarvam_api_key="x", heygen_api_key="x",
        langfuse_public_key="x", langfuse_secret_key="x",
        ces_baseline_window=window, ces_baseline_ttl_seconds=ttl,
    )
```

### No DB write — read-only Supabase interaction
This function only reads `sessions`. It never writes to any DB table.
Only Redis is written.

### Dependency on Task 1 (Session 3 Task 2) completion
Dev 4 must call this function. The call happens after writing `ces_final` to the
sessions table. Dev 4 must import from `app.modules.assessment.ces_baseline`.

## Dev Agent Record

### Implementation Plan
RED → GREEN → REFACTOR. Tests written first (all fail on ImportError).
Config fields added first so tests can build Settings. Implementation written
in ces_baseline.py. GREEN: all tests pass. REFACTOR: AST tests confirm no
hardcoded literals and no forbidden imports.

### Debug Log
_To be filled during implementation._

### Completion Notes
_To be filled after implementation._

### File List
- `apps/api/app/modules/assessment/ces_baseline.py` — NEW
- `apps/api/app/config.py` — MODIFIED (two new fields)
- `apps/api/tests/test_ces_baseline.py` — NEW

### Change Log
- 2026-07-03: Story created — Sprint 3 Task 2 CES baseline computation (BMAD story-first gate)

## Senior Developer Review (AI)
_To be filled by /bmad-code-review after implementation._
