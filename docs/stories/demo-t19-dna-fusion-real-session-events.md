# Demo T19 — Learner DNA Fusion: concrete EMA values and real session event mix

**Status:** in-progress
**Sprint:** Demo Sprint
**Owner:** Dev 3
**Branch:** `dev3-demo-t19-phaseL5`
**Depends on:** T16 (UUID session pattern), T18 (Learner DNA onboarding coverage)

---

## Problem Statement

`test_dna_fusion.py` (Story 3-25, 29 tests) validates the `dna_fusion.py` signal
computation and EMA formula at the extremes (cap=100, zero=0) and checks that the happy
path returns 9 dimensions in [0, 100]. What it never does:

1. **Intermediate event counts** — only `_JARGON_CAP` (100%) and `0` are tested; an
   off-by-one in the formula (e.g. `/ (_JARGON_CAP - 1)`) passes every existing test.
2. **Exact EMA output values** — `test_async_happy_path_returns_9_dimension_dict` only
   asserts `0 <= v <= 100`; a bug that returns `old * retain` (missing the signal term)
   still passes.
3. **Upsert payload dimension values** — `test_async_session_count_incremented` captures
   the upsert payload and only asserts `session_count == 4`; all 9 EMA dimension values
   in the payload are unasserted.
4. **Mixed real session** — no test exercises all four event types simultaneously
   (`jargon_hover`, `help_seeking`, `skip_segment`, `intervention_triggered`) alongside
   quiz and teachback data in one fusion call.
5. **Redis reassessment flag** — `_REASSESSMENT_INTERVAL = 10`; the Redis
   `user:{uid}:reassessment_due` write at session 10 is completely untested.
6. **Two-segment teachback persistence** — `test_compute_signals_persistence_retry_after_low_score`
   uses a single segment; the `defaultdict(list)` grouping logic for multi-segment sessions
   is exercised only at AC level — never with two segments having different retry outcomes.

T19 adds 9 tests that verify concrete, arithmetically-derived expected values from the
production code constants.

---

## Acceptance Criteria

### AC1 — Intermediate curiosity_index: 2 jargon_hover events → 40.0 signal

**Given** `event_counts = {"jargon_hover": 2}` (below `_JARGON_CAP = 5`),
**When** `_compute_signals(quiz_rows=[], tb_rows=[], event_counts=event_counts)` is called,
**Then**:
- `curiosity_index == pytest.approx(40.0, rel=1e-3)` — formula: `(2/5)*100 = 40.0`
- `study_independence == 100.0` — no `help_seeking` events, inverse of help signal (0%)
- Both `curiosity_index` and `study_independence` are in `[0.0, 100.0]`

*Why:* Validates the `/cap` denominator at an intermediate count; an off-by-one (`cap-1=4`)
produces `50.0` not `40.0` and is caught here but not by the existing at-cap tests.

---

### AC2 — Mixed real-session: all 4 event types + quiz + teachback simultaneously

**Given** a realistic session:
- `quiz_rows`: 3 correct out of 4 answers, all `response_time_ms=10_000` (below
  `_FAST_RESPONSE_MS=15_000` → processing_speed=100.0)
- `event_counts`: `{"jargon_hover": 3, "help_seeking": 1, "skip_segment": 1,
  "intervention_triggered": 1}`
- `tb_rows`: seg-1 attempt_1 score=40 (below `_TEACHBACK_LOW_SCORE=60`), attempt_2
  score=75 (retry) → `persistence = 100.0`

**When** `_compute_signals(...)` is called,
**Then** verify all 9 signals with exact formula-derived values:
- `pattern_recognition == pytest.approx(75.0, rel=1e-3)` — 3/4 correct
- `logical_deduction == pytest.approx(75.0, rel=1e-3)` — same as pattern_recognition
- `processing_speed == 100.0` — all responses at 10_000ms ≤ _FAST_RESPONSE_MS
- `frustration_tolerance == pytest.approx(66.67, rel=1e-2)` — `(1-1/3)*100`
- `persistence == 100.0` — retry after low score
- `help_seeking == pytest.approx(25.0, rel=1e-3)` — `(1/4)*100`
- `study_independence == pytest.approx(75.0, rel=1e-3)` — `100 - 25`
- `goal_orientation == pytest.approx(75.0, rel=1e-3)` — `(1-1/4)*100`
- `curiosity_index == pytest.approx(60.0, rel=1e-3)` — `(3/5)*100`

*Why:* End-to-end formula verification for a realistic session. A bug in any one formula
path is caught without requiring separate isolated tests.

---

### AC3 — Concrete EMA output: `fuse_learner_dna` upsert payload contains exact values

**Given** a known `dna_row` with:
```python
{"pattern_recognition": 80.0, "logical_deduction": 70.0, ..., "session_count": 2}
```
And all-correct quiz (signal=100.0) with retain=0.7, no events:

**When** `fuse_learner_dna(...)` is called and the upsert payload is captured via spy,
**Then** the payload contains:
- `pattern_recognition == pytest.approx(round(0.7*80.0 + 0.3*100.0, 4), rel=1e-4)` → `86.0`
- `logical_deduction == pytest.approx(round(0.7*70.0 + 0.3*100.0, 4), rel=1e-4)` → `79.0`
- Every dimension value is a `float` (not `None`, not `int`)
- `session_count == 3` (old=2, +1)
- `user_id == _USER_UUID`

*Why:* Closes the gap in `test_async_happy_path_returns_9_dimension_dict` — range-only
assertion allows a bug that returns `old_value * retain` (drops the signal term) to pass.

---

### AC4 — Two-segment teachback: different retry outcomes per segment

**Given** teachback rows across 2 segments:
```python
[
    {"score": 45, "attempt_number": 1, "segment_id": "seg-A"},  # low, no retry
    {"score": 50, "attempt_number": 1, "segment_id": "seg-B"},  # low
    {"score": 72, "attempt_number": 2, "segment_id": "seg-B"},  # retry on seg-B
]
```

**When** `_compute_signals(quiz_rows=[], tb_rows=tb_rows, event_counts={})` is called,
**Then**:
- `persistence == 100.0` — seg-B had low score AND retry → `had_retry_after_low = True`
- `had_retry_after_low` takes precedence even when seg-A gave up

*Why:* The `defaultdict(list)` grouping path processes multiple segments; the existing
single-segment test never exercises the multi-segment any/all logic.

---

### AC5 — `ended_at=None` returns `None` with no upsert side-effect

**Given** session row with `"ended_at": None`,
**When** `fuse_learner_dna(...)` is called with a spy on `supabase.table`,
**Then**:
- Return value is `None`
- `supabase.table` called at most once (sessions read) — learner_dna upsert is NOT called

*Why:* Strengthens the existing AC14 test — the existing test only asserts `result is None`
but does not verify that no DB write occurred. A buggy implementation could return `None`
after silently writing zeros to learner_dna.

---

### AC6 — No-quiz session: cognitive signal policy divergence

**Given** `quiz_rows=[]`, no events, no teachback,
**When** `_compute_signals(...)` is called,
**Then**:
- `pattern_recognition == 0.0` and `logical_deduction == 0.0` — pessimistic (no data →
  signal=0, not neutral)
- `processing_speed == 50.0` — neutral (`_NEUTRAL`) when no response times
- `frustration_tolerance == 100.0` — 0 interventions (no frustration events = perfect)
- `goal_orientation == 100.0` — 0 skips
- `curiosity_index == 0.0` — 0 jargon_hover events

*Why:* Documents the intentional policy divergence between cognitive dims (pessimistic)
and processing_speed (neutral) with no quiz data. Any accidental unification of policies
is caught.

---

### AC7 — IDOR: session belonging to user_B raises 404 for user_A (SEC-006)

**Given** session row with `"user_id": user_B_uuid` and `"ended_at": "2026-08-13T10:00:00"`,
**When** `fuse_learner_dna(user_id=user_A_uuid, ...)` is called,
**Then**:
- `HTTPException` with `status_code=404` is raised
- Not 403 — 403 would be an existence oracle for session IDs (SEC-006 pattern)

---

### AC8 — Redis reassessment flag at session 10

**Given** `dna_row` with `session_count=9`, a valid ended session, a mock async Redis client,
**When** `fuse_learner_dna(...)` is called with `redis=mock_redis`,
**Then**:
- `mock_redis.set` is called exactly once
- Called with `(f"user:{_USER_UUID}:reassessment_due", "1")`
- The function still returns 9 dimensions (Redis call is non-fatal path)

*Why:* `_REASSESSMENT_INTERVAL = 10` is completely untested. A module constant change
(e.g. to 5) or a modulo-off-by-one bug passes every existing test.

---

### AC9 — Redis failure is non-fatal: function returns result despite Redis error

**Given** `dna_row` with `session_count=9` (triggers flag path), a mock Redis that raises
`ConnectionError` on `set(...)`,
**When** `fuse_learner_dna(...)` is called,
**Then**:
- No exception propagates to the caller
- Returns dict with 9 dimension keys (fusion succeeded despite Redis failure)

*Why:* The `try/except` block in Step 7 is correct but untested — a future refactor
could accidentally re-raise, making session-10 fusion permanently fail.

---

## Scale & Load

**Q1 — Unit of work and range:**
One `fuse_learner_dna` call per ended session. Input range per call:
- Session row: exactly 1 (fixed)
- `quiz_attempts` per session: 0 (no quiz) to ~60 (3 segments × 5 questions × 4 attempts)
- `teachback_attempts` per session: 0 to ~14 (7 segments × 2 attempts)
- `session_events` per session: 0 to ~200 (20 jargon hovers × 10 segments)
- Output: always exactly 9 dimensions. T19 is tests-only — no new limits introduced.

**Q2 — Fixed budgets while input varies:**
`_JARGON_CAP=5`, `_HELP_CAP=4`, `_SKIP_CAP=4`, `_INTERVENTION_CAP=3` are all module
constants that cap signals at 100% without hard-erroring above the cap (min/max clamp).
Events beyond the cap contribute nothing (signal saturates). This is documented behaviour,
not silent truncation — the result is never wrong, only saturated. No new budgets
introduced by T19.

**Q3 — Scope of every limit:**
Caps above are per-session-call (not per user, not per deployment). `_REASSESSMENT_INTERVAL`
is per-user lifetime count, stored in `learner_dna.session_count`.

**Q4 — Unbounded reads/writes:**
Three `asyncio.to_thread` reads (quiz_attempts, teachback_attempts, session_events) are
bounded by `session_id` — a session has a finite number of attempts. No `.limit()` is
needed because the bound is semantic (a session ends). T19 adds no new reads.

**Q5 — Inherited caps re-derived:**
`_REASSESSMENT_INTERVAL = 10` was set in Story 3-25. If the product changes to 5 sessions,
this constant must be updated manually. AC8 adds a test that would catch a value change
without a corresponding test update — but it does not enforce the business value itself.
Denominator caps (`_JARGON_CAP` etc.) are derived from the UX brief (5 jargon hovers =
expert curiosity). No re-derivation needed for T19 — tests exercise the constants, not
override them.

**Q6 — Check-then-act concurrency:**
`fuse_learner_dna` uses `upsert(on_conflict="user_id")` — a single atomic write, not
read-then-write. No TOCTOU risk. Redis set is fire-and-forget, non-fatal. No new
concurrent sequences introduced.

---

## Technical Requirements

- File: `apps/api/tests/test_dna_fusion_real_session.py` (new)
- 9 tests: AC1 through AC9
- Import: `_compute_signals`, `_apply_ema`, `_JARGON_CAP`, `_HELP_CAP`, `_SKIP_CAP`,
  `_INTERVENTION_CAP`, `_NEUTRAL`, `_FAST_RESPONSE_MS`, `_TEACHBACK_LOW_SCORE`,
  `_REASSESSMENT_INTERVAL` from `app.modules.assessment.dna_fusion`
- `fuse_learner_dna` from `app.modules.assessment.dna_fusion`
- All AC3, AC5, AC7, AC8, AC9 tests call `fuse_learner_dna` — use the existing
  `_supabase_mock` pattern from `test_dna_fusion.py` (routes by table name)
- `asyncio_mode = "auto"` (pyproject.toml) — no `@pytest.mark.asyncio` decorator needed
- No production code changes — tests-only diff

### `asyncio.to_thread` shim (for AC3, AC5, AC7, AC8, AC9):
```python
@pytest.fixture
def mock_to_thread(monkeypatch):
    async def _sync_shim(func, *args, **kwargs):
        return func(*args, **kwargs)
    monkeypatch.setattr("app.modules.assessment.dna_fusion.asyncio.to_thread", _sync_shim)
```

### Redis mock (for AC8, AC9):
```python
mock_redis = AsyncMock()
```
Pass as `redis=mock_redis` to `fuse_learner_dna`.

### Supabase mock for `fuse_learner_dna` (5-table call order):
```
sessions → maybe_single → session_row
quiz_attempts → select/eq/execute → quiz_rows
teachback_attempts → select/eq/execute → tb_rows
session_events → select/eq/execute → event_rows
learner_dna → maybe_single → dna_row (read)
learner_dna → upsert (write) — spy to capture payload
```
Route by `lambda name: {...}[name]` to avoid call-order fragility (same fix as T18 P6).

### Expected values reference (AC2):
```
quiz 3/4 correct → accuracy=0.75 → pattern=logical=75.0
response 10_000ms, _FAST=15_000, _SLOW=60_000 → range=45_000
  raw_speed = 100 - (10_000-15_000)/45_000*100 = 100 - (-11.11) = 111.11 → clamped to 100.0
1 intervention_triggered, _CAP=3 → frustration = 100 - (1/3)*100 = 66.67
1 help_seeking, _HELP_CAP=4 → help_seeking = (1/4)*100 = 25.0; study_independence = 75.0
1 skip_segment, _SKIP_CAP=4 → goal_orientation = (1-1/4)*100 = 75.0
3 jargon_hover, _JARGON_CAP=5 → curiosity_index = (3/5)*100 = 60.0
teachback retry on seg-B → persistence = 100.0
```

### Expected values reference (AC3):
```
All-correct quiz → accuracy=1.0 → pattern=logical signal=100.0
EMA: round(0.7*80.0 + 0.3*100.0, 4) = round(56.0 + 30.0, 4) = 86.0  # pattern_recognition
EMA: round(0.7*70.0 + 0.3*100.0, 4) = round(49.0 + 30.0, 4) = 79.0  # logical_deduction
```

---

## Dependencies

- `app.modules.assessment.dna_fusion` — module under test
  - Private functions: `_compute_signals`, `_apply_ema`
  - Public: `fuse_learner_dna`
  - Constants: `_JARGON_CAP`, `_HELP_CAP`, `_SKIP_CAP`, `_INTERVENTION_CAP`, `_NEUTRAL`,
    `_FAST_RESPONSE_MS`, `_TEACHBACK_LOW_SCORE`, `_REASSESSMENT_INTERVAL`
- `app.modules.assessment.dna_growth.record_dna_growth` — called in Step 6;
  must be monkeypatched to an `AsyncMock` to prevent real DB calls in tests
- No LLM, no new migrations, no service.py changes — tests-only diff

---

## Tasks / Subtasks

- [ ] **T1 — RED: write 9 failing tests (one per AC)**
- [ ] **T2 — GREEN: confirm all 9 tests pass (no implementation changes needed)**
- [ ] **T3 — VERIFY: run existing test_dna_fusion.py + T19 suite, confirm no regressions**
- [ ] **T4 — UPDATE dev3-assessment-tracker.md**

---

## Dev Notes

### Why test private functions?
`_compute_signals` is the signal kernel — if it maps event_type strings to the wrong
dimension or uses the wrong denominator, every downstream EMA value is silently wrong.
A public-API-only test (only calling `fuse_learner_dna`) cannot isolate which step failed.

### `dna_growth.record_dna_growth` must be patched
`fuse_learner_dna` Step 6 calls `record_dna_growth(session_id, old_dims, new_dims, supabase)`.
Patch it as `AsyncMock` in all tests that call `fuse_learner_dna`, otherwise Step 6 hits
the real `dna_growth.py` which makes additional DB calls not set up in the mock.

Patch target: `"app.modules.assessment.dna_fusion.record_dna_growth"`

### Session_count=9 → 10 path
`new_count = old_session_count + 1 = 10`; `10 % 10 == 0`; Redis `set` fires.
The Redis call uses `await redis.set(key, value)` — use `AsyncMock()` for the client.

### Processing_speed formula at 10_000ms
`_FAST_RESPONSE_MS=15_000` — a response of 10_000ms is FASTER than the fast threshold.
`raw_speed = 100 - (avg_ms - _FAST_RESPONSE_MS) / speed_range * 100`
`= 100 - (10_000 - 15_000) / (60_000 - 15_000) * 100`
`= 100 - (-5_000 / 45_000) * 100`
`= 100 + 11.11 = 111.11` → clamped to 100.0 by `min(100.0, max(0.0, raw_speed))`
