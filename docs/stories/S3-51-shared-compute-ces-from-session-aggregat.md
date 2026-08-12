---
id: "S3-51"
title: "Shared compute_ces_from_session_aggregates utility called by both get_session_report and finalize_session (D15)"
status: "Draft"
sprint: 3
story_points: 2
owner: Dev3
priority: P2
decision_ref: D15
depends_on: ["S3-46"]
branch: "sprint3/s3-51-ces-aggregates-utility"
migration: "NO"
---

# Story S3-51 — Shared `compute_ces_from_session_aggregates` Utility Called by Both `get_session_report` and `finalize_session` (D15)

## Context

**Decision D15:** Shared utility function — `finalize_session` uses same formula as `ces_breakdown`.

### The problem

After S3-46 lands, `get_session_report` delegates its CES breakdown arithmetic to the
private helper `_build_ces_breakdown` (single underscore prefix, accessible only within
`assessment/service.py`). A second CES-aggregates consumer is imminent: `finalize_session`,
implemented by Story S3-35, must write `sessions.ces_final` — the single authoritative
`ces_score` source for every session report.

Without a shared utility, two independent formula paths will exist:

- `get_session_report` → `_build_ces_breakdown` → 5-key breakdown dict
- `finalize_session` (S3-35) → inline arithmetic → `ces_final` scalar

Any future change to the breakdown formula (e.g., tuning a weight redistribution constant)
must be applied in both places independently. Because `_build_ces_breakdown` is private to
the assessment module, `tutor/graph.py` (where `finalize_session` lives) cannot import it
directly — violating the cross-module safety principle.

**Concrete failure mode (before this fix):** A developer implementing S3-35 writes their own
inline CES computation that uses `avg_teachback / 100.0 * settings.ces_weight_teachback * 100`
with nominal weights even when `teachback_normalised is None`. The breakdown and `ces_final`
diverge. A student who skipped teach-back sees `ces_score = 68.27` and a breakdown that sums
to `52.0` — neither matches the other, and neither matches the real-time computation from D2.

### The solution (D15)

Extract a **public** module-level function `compute_ces_from_session_aggregates` in
`apps/api/app/modules/assessment/service.py`. This function:

- Is importable by `tutor/graph.py` (cross-module, pure Python — no DB access, no async)
- Applies the same proportional-redistribution algebra as `_build_ces_breakdown` (S3-46)
  and `compute_ces` (S3-23 canonical)
- Returns the same 5-key `dict[str, float]` that `get_session_report` returns as
  `ces_breakdown`
- Allows S3-35 to call it, sum the returned dict, and write `sessions.ces_final` — so
  `sum(ces_breakdown.values()) == ces_final` for any session where the inputs are identical

### Relationship to S3-46

S3-46 introduced `_build_ces_breakdown` as a private helper. S3-51:
- Adds `compute_ces_from_session_aggregates` as the public, cross-module version of the
  same computation
- Updates `get_session_report` to call `compute_ces_from_session_aggregates` (not
  `_build_ces_breakdown` directly)
- `_build_ces_breakdown` may remain as a private alias that delegates to the new public
  function, or it may be removed — the implementation may choose either approach as long as
  all S3-46 test assertions still pass

---

## User Story

**As a** student viewing my session report after completing a lesson,
**I want** my displayed `ces_score` to exactly match the sum of the five `ces_breakdown`
components shown in the same report,
**so that** the score and its components tell a consistent story and I can trust the
engagement feedback I receive.

**As the** `finalize_session` implementation (Story S3-35),
**I want** a single importable function `compute_ces_from_session_aggregates` from
`assessment/service.py` that returns the same breakdown dict already used by
`get_session_report`,
**so that** I can write `ces_final = sum(result.values())` once and never diverge from
the student-visible breakdown.

---

## Acceptance Criteria

### AC 1 — `compute_ces_from_session_aggregates` exists at module level in `assessment/service.py` with the correct signature

A module-level function `compute_ces_from_session_aggregates` is defined in
`apps/api/app/modules/assessment/service.py` with the following exact signature:

```python
def compute_ces_from_session_aggregates(
    *,
    quiz_accuracy: float,
    teachback_normalised: float | None,
    behavioral_avg: float,
    head_pose_avg: float,
    blink_avg: float,
    settings: Settings,
) -> dict[str, float]:
```

- `quiz_accuracy`: fraction of quiz questions answered correctly (0.0–1.0); 0.0 when no
  quiz submitted yet in this session.
- `teachback_normalised`: `avg_teachback_score / 100.0` when at least one teach-back
  attempt exists; `None` when no attempts exist (teach-back absent — redistribute weights
  per D2 formula from S3-46).
- `behavioral_avg`, `head_pose_avg`, `blink_avg`: per-signal averages (0.0–1.0) derived
  from Redis history lists (S3-42). Must be `0.0` (not `None`) when Redis is unavailable.
- Return value has **exactly 5 keys**: `"quiz"`, `"teachback"`, `"behavioral"`,
  `"head_pose"`, `"blink"`.

**Exact assertion:**
```python
params = inspect.signature(compute_ces_from_session_aggregates).parameters
assert set(params) == {
    "quiz_accuracy", "teachback_normalised",
    "behavioral_avg", "head_pose_avg", "blink_avg", "settings"
}
```

### AC 2 — `compute_ces_from_session_aggregates` is a pure function with no I/O

`inspect.getsource(compute_ces_from_session_aggregates)` must NOT contain any of the
strings: `"supabase"`, `"redis"`, `"await"`, `"asyncio"`, `"to_thread"`.

No network call, no DB read, no Redis read, no async operation — only arithmetic on the
six inputs.

**Exact assertion:** For each banned string `s` in
`["supabase", "redis", "await", "asyncio", "to_thread"]`:
```python
assert s not in inspect.getsource(compute_ces_from_session_aggregates)
```

### AC 3 — All 5 weight lookups reference `settings.ces_weight_*`, no hardcoded literals

Source inspection of `compute_ces_from_session_aggregates` confirms all weight lookups
reference `settings` attributes, not float literals.

**Exact assertions** (each string must appear in the function source):
```python
for attr in [
    "settings.ces_weight_quiz",
    "settings.ces_weight_teachback",
    "settings.ces_weight_behavioral",
    "settings.ces_weight_head_pose",
    "settings.ces_weight_blink",
]:
    assert attr in inspect.getsource(compute_ces_from_session_aggregates)
```

### AC 4 — Nominal-weight path: when `teachback_normalised` is not `None`

With default weights (quiz=0.35, teachback=0.25, behavioral=0.20, head_pose=0.12, blink=0.08)
and `teachback_normalised=0.80` (not None), all five components use their nominal weights.

**Exact inputs:**
`quiz_accuracy=0.6, teachback_normalised=0.80, behavioral_avg=0.5, head_pose_avg=0.4, blink_avg=0.3`

**Exact expected output:**
```python
{
    "quiz":       21.0,    # round(0.6  * 0.35 * 100, 4)
    "teachback":  20.0,    # round(0.80 * 0.25 * 100, 4)
    "behavioral": 10.0,    # round(0.5  * 0.20 * 100, 4)
    "head_pose":   4.8,    # round(0.4  * 0.12 * 100, 4)
    "blink":       2.4,    # round(0.3  * 0.08 * 100, 4)
}
```

Sum = 58.2. This matches `compute_ces(quiz_accuracy=0.6, teachback_score=0.80,
behavioral=0.5, head_pose=0.4, blink=0.3, settings=default_settings)` = 58.2.

**Exact assertions:**
```python
result = compute_ces_from_session_aggregates(
    quiz_accuracy=0.6, teachback_normalised=0.80,
    behavioral_avg=0.5, head_pose_avg=0.4, blink_avg=0.3,
    settings=default_settings,
)
assert result["quiz"]       == pytest.approx(21.0,  rel=1e-4)
assert result["teachback"]  == pytest.approx(20.0,  rel=1e-4)
assert result["behavioral"] == pytest.approx(10.0,  rel=1e-4)
assert result["head_pose"]  == pytest.approx(4.8,   rel=1e-4)
assert result["blink"]      == pytest.approx(2.4,   rel=1e-4)
```

### AC 5 — Redistributed-weight path: when `teachback_normalised` is `None`

With the same default weights and `teachback_normalised=None`, the teachback weight (0.25)
is redistributed proportionally across the four remaining signals.
`remaining = 1.0 - ces_weight_teachback = 0.75`.

**Exact inputs:**
`quiz_accuracy=0.6, teachback_normalised=None, behavioral_avg=0.5, head_pose_avg=0.4, blink_avg=0.3`

**Exact expected output:**
```python
{
    "quiz":       28.0,     # round(0.6 * (0.35 / 0.75) * 100, 4)
    "teachback":   0.0,
    "behavioral": 13.3333,  # round(0.5 * (0.20 / 0.75) * 100, 4)
    "head_pose":   6.4,     # round(0.4 * (0.12 / 0.75) * 100, 4)
    "blink":       3.2,     # round(0.3 * (0.08 / 0.75) * 100, 4)
}
```

**Exact assertions:**
```python
result = compute_ces_from_session_aggregates(
    quiz_accuracy=0.6, teachback_normalised=None,
    behavioral_avg=0.5, head_pose_avg=0.4, blink_avg=0.3,
    settings=default_settings,
)
assert result["quiz"]       == pytest.approx(round(0.6 * (0.35 / 0.75) * 100, 4), rel=1e-4)
assert result["teachback"]  == 0.0
assert result["behavioral"] == pytest.approx(round(0.5 * (0.20 / 0.75) * 100, 4), rel=1e-4)
assert result["head_pose"]  == pytest.approx(round(0.4 * (0.12 / 0.75) * 100, 4), rel=1e-4)
assert result["blink"]      == pytest.approx(round(0.3 * (0.08 / 0.75) * 100, 4), rel=1e-4)
```

### AC 6 — Full-engagement redistributed path sums within 0.001 of 100.0

When all four present signals are 1.0 and `teachback_normalised=None`:

**Exact inputs:**
`quiz_accuracy=1.0, teachback_normalised=None, behavioral_avg=1.0, head_pose_avg=1.0, blink_avg=1.0`

**Exact assertion:**
```python
result = compute_ces_from_session_aggregates(
    quiz_accuracy=1.0, teachback_normalised=None,
    behavioral_avg=1.0, head_pose_avg=1.0, blink_avg=1.0,
    settings=default_settings,
)
assert abs(sum(result.values()) - 100.0) < 0.001
```

(Inherent 4-dp rounding residual is at most 0.0001 — within the 0.001 tolerance.)

### AC 7 — Degenerate guard: `ces_weight_teachback >= 1.0` returns all zeros without error

When `settings.ces_weight_teachback = 1.0` (pathological misconfiguration, prevented in
production by the `model_validator` but injectable in tests):

**Exact assertion:**
```python
result = compute_ces_from_session_aggregates(
    quiz_accuracy=0.5, teachback_normalised=None,
    behavioral_avg=0.5, head_pose_avg=0.5, blink_avg=0.5,
    settings=degenerate_settings,  # ces_weight_teachback=1.0
)
assert all(v == 0.0 for v in result.values())
```

No `ZeroDivisionError`, no exception of any kind.

### AC 8 — Return dict has exactly 5 keys

**Exact assertion:**
```python
result = compute_ces_from_session_aggregates(
    quiz_accuracy=0.5, teachback_normalised=0.5,
    behavioral_avg=0.5, head_pose_avg=0.5, blink_avg=0.5,
    settings=default_settings,
)
assert set(result.keys()) == {"quiz", "teachback", "behavioral", "head_pose", "blink"}
assert len(result) == 5
```

### AC 9 — `get_session_report` calls `compute_ces_from_session_aggregates`, not `_build_ces_breakdown` directly

After S3-51, `get_session_report` must reference `compute_ces_from_session_aggregates` in
its source.

**Exact assertion (source inspection):**
```python
assert "compute_ces_from_session_aggregates" in inspect.getsource(get_session_report)
```

**Regression guard (must also pass):**
```python
assert '"behavioral": 0.0' not in inspect.getsource(get_session_report)
```
(Prevents re-introduction of the hardcoded-zero anti-pattern removed by S3-46.)

### AC 10 — `compute_ces_from_session_aggregates` output sum equals `compute_ces()` for both formula variants

Cross-function consistency: `sum(compute_ces_from_session_aggregates(...).values())`
must equal `compute_ces(same inputs)` within floating-point tolerance.

**Variant A — teachback present, inputs all 0.5:**
```python
from app.modules.assessment.ces import compute_ces

result_dict = compute_ces_from_session_aggregates(
    quiz_accuracy=0.5, teachback_normalised=0.5,
    behavioral_avg=0.5, head_pose_avg=0.5, blink_avg=0.5,
    settings=default_settings,
)
ces_direct = compute_ces(
    quiz_accuracy=0.5, teachback_score=0.5,
    behavioral=0.5, head_pose=0.5, blink=0.5,
    settings=default_settings,
)
assert abs(sum(result_dict.values()) - ces_direct) < 0.001
```

**Variant B — teachback absent (`teachback_normalised=None`):**
```python
result_dict = compute_ces_from_session_aggregates(
    quiz_accuracy=0.5, teachback_normalised=None,
    behavioral_avg=0.5, head_pose_avg=0.5, blink_avg=0.5,
    settings=default_settings,
)
ces_direct = compute_ces(
    quiz_accuracy=0.5, teachback_score=None,
    behavioral=0.5, head_pose=0.5, blink=0.5,
    settings=default_settings,
)
assert abs(sum(result_dict.values()) - ces_direct) < 0.001
```

Both assertions call the real `compute_ces` from `assessment.ces` — no mocking.

### AC 11 — `compute_ces_from_session_aggregates` is importable from outside the assessment module without error

**Exact assertion:**
```python
from app.modules.assessment.service import compute_ces_from_session_aggregates
assert callable(compute_ces_from_session_aggregates)
```

This import must succeed at module-import time (no circular import, no missing dependency).
The test confirms this from within the test suite that mocks all DB/Redis connections.

### AC 12 — CI guard: no inline `ces_breakdown` dict literal in `get_session_report` source

**Exact assertion:**
```python
assert '"behavioral": 0.0' not in inspect.getsource(get_session_report)
```

(Prevents the pre-S3-46 hardcoded-zero anti-pattern from returning even after S3-51's
refactoring of the delegation chain.)

### AC 13 — S3-46 regression tests remain GREEN without modification

All tests in `test_s3_46_ces_breakdown_redistribution.py` (added by S3-46) continue to
pass after S3-51's implementation without any changes to those test assertions.

**Exact assertion:** `pytest apps/api/tests/test_s3_46_ces_breakdown_redistribution.py`
exits 0 with the same count of passed tests as before S3-51.

### AC 14 — New test file `test_s3_51_ces_aggregates_utility.py` is `@pytest.mark.unit` and passes without real DB/Redis/LLM

All tests in the new file are decorated `@pytest.mark.unit`. No test makes a real
Supabase call, a real Redis call, or a real OpenAI API call.

**Exact assertion:**
`pytest -m unit apps/api/tests/test_s3_51_ces_aggregates_utility.py` exits 0.

---

## Tasks / Subtasks

### Task 1 — Story file (story-first gate)
- [ ] 1.1 Create `docs/stories/S3-51-shared-compute-ces-from-session-aggregat.md`
- [ ] 1.2 Commit story-only to `sprint3/s3-51-ces-aggregates-utility`
- [ ] 1.3 Push to remote before any implementation

### Task 2 — RED phase (failing tests)
- [ ] 2.1 Create `apps/api/tests/test_s3_51_ces_aggregates_utility.py`
- [ ] 2.2 Test AC 1 — function exists with correct 6-parameter signature
- [ ] 2.3 Test AC 2 — purity: none of the banned I/O strings in function source
- [ ] 2.4 Test AC 3 — all 5 `settings.ces_weight_*` strings in function source
- [ ] 2.5 Test AC 4 — nominal path: all 5 components match exact expected values
- [ ] 2.6 Test AC 5 — redistributed path: correct values when `teachback_normalised=None`
- [ ] 2.7 Test AC 6 — full-engagement redistribution sums within 0.001 of 100.0
- [ ] 2.8 Test AC 7 — degenerate guard: `ces_weight_teachback=1.0` → all zeros, no exception
- [ ] 2.9 Test AC 8 — return dict has exactly 5 keys
- [ ] 2.10 Test AC 9 — `get_session_report` source contains `"compute_ces_from_session_aggregates"`
- [ ] 2.11 Test AC 10 (variant A) — sum equals `compute_ces()` when teachback present
- [ ] 2.12 Test AC 10 (variant B) — sum equals `compute_ces()` when teachback absent
- [ ] 2.13 Test AC 11 — importable from outside assessment module without circular-import error
- [ ] 2.14 Test AC 12 — `'"behavioral": 0.0'` not in `get_session_report` source
- [ ] 2.15 Confirm all new tests FAIL before implementation

### Task 3 — GREEN phase (implementation)
- [ ] 3.1 `apps/api/app/modules/assessment/service.py`:
      Define `compute_ces_from_session_aggregates` at module level above `get_session_report`:
      - Nominal path (teachback_normalised not None): each component = `round(signal * weight * 100, 4)`
      - Redistributed path (teachback_normalised is None): each component = `round(signal * (weight / remaining) * 100, 4)`
      - Degenerate guard: `if remaining <= 0.0: return {"quiz": 0.0, "teachback": 0.0, "behavioral": 0.0, "head_pose": 0.0, "blink": 0.0}`
- [ ] 3.2 Update `get_session_report` Step 5 to call `compute_ces_from_session_aggregates` (replacing the `_build_ces_breakdown` call or inline dict):
      - `teachback_normalised = (avg_teachback / 100.0) if teachback_count > 0 else None`
      - `behavioral_avg`, `head_pose_avg`, `blink_avg` from S3-42 Redis reads (or 0.0 if unavailable)
      - `settings` from `get_settings()`
- [ ] 3.3 Decide fate of `_build_ces_breakdown`:
      Option A: keep as `_build_ces_breakdown = compute_ces_from_session_aggregates` (alias)
      Option B: remove `_build_ces_breakdown` and update any S3-46 tests referencing it by name
      Document decision choice in implementation commit message
- [ ] 3.4 Also create `apps/api/tests/test_ces_score_consistency.py` with 4 cross-check tests:
      - `test_ces_score_sum_consistency_teachback_present`
      - `test_ces_score_sum_consistency_teachback_absent`
      - `test_ces_score_sum_consistency_all_zeros`
      - `test_ces_score_sum_consistency_degenerate_weight_1`
- [ ] 3.5 Confirm all AC tests PASS after implementation

### Task 4 — REFACTOR + validation
- [ ] 4.1 `ruff check .` — zero new errors repo-wide
- [ ] 4.2 `ruff format --check` — zero format violations
- [ ] 4.3 Full Dev 3 regression suite: `pytest -m unit` exits 0 with no regressions
- [ ] 4.4 S3-46 regression suite: `pytest apps/api/tests/test_s3_46_ces_breakdown_redistribution.py` exits 0

### Task 5 — 6-agent adversarial review
- [ ] 5.1 Layer 1 — Story Quality
- [ ] 5.2 Layer 2 — Blind Hunter (Security)
- [ ] 5.3 Layer 3 — Test Coverage
- [ ] 5.4 Layer 4 — AC Completeness
- [ ] 5.5 Layer 5 — Process Integrity
- [ ] 5.6 Layer 6 — Scale & Load

### Task 6 — Commit + push
- [ ] 6.1 Final implementation commit on `sprint3/s3-51-ces-aggregates-utility`
- [ ] 6.2 Push to remote
- [ ] 6.3 Update `docs/dev3-assessment-tracker.md`

---

## Scale & Load

### Q1 — What is ONE unit of work, and what is its range?

One unit of work is a single call to `compute_ces_from_session_aggregates`, invoked once
per `get_session_report` call (assessment path) and once per `finalize_session` invocation
(tutor path, S3-35).

- **Min:** One call per session report view or session finalization — O(1) CPU, zero I/O.
- **Typical:** One invocation per completed session report. The function performs 4–10
  arithmetic operations (multiplications, one conditional division, rounded floats).
  Sub-microsecond execution time on any modern hardware.
- **Largest possible:** Identical to minimum. The function is stateless and takes the same
  amount of CPU regardless of session duration, quiz count, or teachback count. Session
  length and learner behavior do not affect this function's runtime.
- **Beyond the bound:** Not applicable. There is no budget or input-size limit — the
  function accepts six scalars, performs pure arithmetic, and returns a 5-key dict.

### Q2 — Which budgets are FIXED while the input VARIES — and what happens past them?

One fixed constraint: if `settings.ces_weight_teachback` reaches or exceeds `1.0`, the
divisor `remaining = 1.0 - ces_weight_teachback` becomes `<= 0.0`. The explicit guard
`if remaining <= 0.0: return all_zeros_dict` handles this deterministically — no
`ZeroDivisionError`, no exception, no silent `NaN` propagation.

The Settings `model_validator` prevents `ces_weight_teachback >= 1.0` in production (the
five weights must sum to `1.0 ± 0.001`). The guard exists for test environments and
defense in depth.

Silent truncation: not applicable. The function performs pure arithmetic and all outputs
are explicitly rounded to 4 dp. No input or output is silently clipped or dropped.

### Q3 — What is the SCOPE of every limit?

| Limit | Scope | Justification |
|-------|-------|---------------|
| `remaining <= 0.0` degenerate guard | Per-call | Stateless — no shared state between calls |
| `CES_WEIGHT_*` env vars | Per-deployment | `get_settings()` is `lru_cache(maxsize=1)` — same Settings instance for the worker's lifetime; env var changes require a Railway redeploy to propagate |
| 4-dp rounding of each component | Per-call | Deterministic, isolated to this function's output |

### Q4 — Which reads and writes are UNBOUNDED?

None introduced by this story.

`compute_ces_from_session_aggregates` performs no I/O. Its only inputs are five floats and
a settings object. Its output is a 5-key dict of floats.

- No Supabase reads or writes.
- No Redis reads or writes.
- No LLM calls.
- No HTTP calls.

Existing `get_session_report` DB reads (`quiz_attempts`, `teachback_attempts`,
`session_events`, `sessions`, `lessons`, `learner_dna`) are unchanged by this story.
Those reads were bounded pre-S3-51 by session scope.

Existing Redis reads in `get_session_report` (via S3-42's `_signal_avg`) read at most
`_CES_HISTORY_MAX` entries per key — unchanged and unaffected by this story.

### Q5 — Which caps were INHERITED from an earlier design, and have they been re-derived?

The redistribution formula `remaining = 1.0 - ces_weight_teachback` is inherited from:
- Story 3-23 (`compute_ces` with proportional redistribution)
- S3-34 (generalised redistribution for any absent signal)
- S3-46 (`_build_ces_breakdown` applying redistribution to the session-report breakdown path)

S3-51 promotes this formula to a public function. No re-derivation is required — S3-34 and
S3-46 already proved correctness and S3-46's 23 unit tests guard it.

The deliberate asymmetry — redistribute only `ces_weight_teachback`, not quiz or attention
signals — is unchanged and documented in CLAUDE.md §11.

### Q6 — Is every check-then-act sequence safe under CONCURRENT requests?

No check-then-act sequences are introduced by this story.

`compute_ces_from_session_aggregates` is a pure function with no shared mutable state.
Multiple concurrent calls from different sessions, different users, or both callers
(`get_session_report` and `finalize_session` simultaneously) do not interact.

`get_session_report` acquires no locks. The ownership check (Step 1) is a read-only DB
query that creates no check-then-act race — the session row is immutable once ended.

`finalize_session` (S3-35, future consumer) will use this function. The NX idempotency
guard preventing double-finalization is owned by S3-35, not by this utility.

---

## Security

### Authentication and ownership

`compute_ces_from_session_aggregates` is a pure internal function with no HTTP surface.
It receives only pre-validated floats derived from DB queries that have already passed the
ownership check in `get_session_report` (SEC-006 pattern: `session.user_id == jwt_sub`).

An attacker with no valid JWT cannot reach `get_session_report` (FastAPI `CurrentUser`
dependency rejects unauthenticated requests before the function is called). An attacker
who guesses a valid `session_id` for another user's session receives HTTP 404 (SEC-006
anti-enumeration — identical message for non-existent and wrong-owner sessions).

`finalize_session` (S3-35) will call this function only with data from a session_id that
passed through the WebSocket ownership check established by S3-43.

### Input validation

All five float inputs are derived from upstream-validated sources:

- `quiz_accuracy`: `correct_count / total_count` — bounded [0.0, 1.0] by construction
- `teachback_normalised`: `avg_teachback / 100.0` — bounded [0.0, 1.0] since `avg_teachback`
  is the average of DB-stored `score` values, each constrained by
  `CHECK(score >= 0 AND score <= 100)`
- `behavioral_avg`, `head_pose_avg`, `blink_avg`: averages of Redis-stored floats originally
  normalised to [0.0, 1.0] by the WebSocket boundary layer (S3-42); `_signal_avg` returns
  `0.0` for empty history — never negative, never > 1.0

Out-of-range floats produced by a buggy caller produce out-of-range output — a correctness
bug in the caller, not a security issue in this utility. Defense: clamping at [0, 1] before
applying weights (mirrors `compute_ces`'s implementation) is strongly recommended
in the implementation to prevent out-of-range contributions.

### No new attack surface

This story adds no new HTTP endpoints, no new Supabase tables, no new migrations, and no
new Redis keys. It extracts an existing arithmetic step in `get_session_report` into a
public importable function and adds the corresponding test file.

---

## Test Requirements

All new tests live in `apps/api/tests/test_s3_51_ces_aggregates_utility.py` and are
`@pytest.mark.unit` (no real Redis, no real DB, no real LLM calls).

### New tests (`test_s3_51_ces_aggregates_utility.py`)

| Test name | AC | Type |
|-----------|-----|------|
| `test_compute_ces_from_session_aggregates_signature_has_6_params` | AC 1 | Source inspection |
| `test_compute_ces_from_session_aggregates_is_pure_no_io_imports` | AC 2 | Source inspection |
| `test_compute_ces_from_session_aggregates_source_has_all_weight_settings` | AC 3 | Source inspection |
| `test_compute_ces_from_session_aggregates_nominal_path_quiz` | AC 4 | Unit (pure function) |
| `test_compute_ces_from_session_aggregates_nominal_path_teachback` | AC 4 | Unit (pure function) |
| `test_compute_ces_from_session_aggregates_nominal_path_behavioral` | AC 4 | Unit (pure function) |
| `test_compute_ces_from_session_aggregates_nominal_path_head_pose` | AC 4 | Unit (pure function) |
| `test_compute_ces_from_session_aggregates_nominal_path_blink` | AC 4 | Unit (pure function) |
| `test_compute_ces_from_session_aggregates_nominal_path_all_five_exact` | AC 4 | Unit (pure function) |
| `test_compute_ces_from_session_aggregates_redistributed_quiz` | AC 5 | Unit (pure function) |
| `test_compute_ces_from_session_aggregates_redistributed_teachback_is_zero` | AC 5 | Unit (pure function) |
| `test_compute_ces_from_session_aggregates_redistributed_behavioral` | AC 5 | Unit (pure function) |
| `test_compute_ces_from_session_aggregates_redistributed_head_pose` | AC 5 | Unit (pure function) |
| `test_compute_ces_from_session_aggregates_redistributed_blink` | AC 5 | Unit (pure function) |
| `test_compute_ces_from_session_aggregates_full_engagement_redistribution_sums_to_100` | AC 6 | Unit (pure function) |
| `test_compute_ces_from_session_aggregates_degenerate_weight_1_returns_zeros` | AC 7 | Unit (pure function) |
| `test_compute_ces_from_session_aggregates_returns_exactly_5_keys` | AC 8 | Unit (pure function) |
| `test_get_session_report_calls_compute_ces_from_session_aggregates` | AC 9 | Source inspection |
| `test_get_session_report_no_inline_hardcoded_behavioral_zero` | AC 9, AC 12 | Source inspection (CI guard) |
| `test_compute_ces_from_session_aggregates_sum_equals_compute_ces_nominal` | AC 10 | Unit (cross-check with real `compute_ces`) |
| `test_compute_ces_from_session_aggregates_sum_equals_compute_ces_redistributed` | AC 10 | Unit (cross-check with real `compute_ces`) |
| `test_compute_ces_from_session_aggregates_importable_from_outside_assessment` | AC 11 | Import smoke test |

Total: 22 new unit tests.

### Consistency guard file (`test_ces_score_consistency.py`)

| Test name | Purpose |
|-----------|---------|
| `test_ces_score_sum_consistency_teachback_present` | `sum(compute_ces_from_session_aggregates(...).values())` == `compute_ces(same inputs)` when teachback is present |
| `test_ces_score_sum_consistency_teachback_absent` | Same cross-check when `teachback_normalised=None` |
| `test_ces_score_sum_consistency_all_zeros` | Both return 0.0 when all inputs are 0.0 and teachback is None |
| `test_ces_score_sum_consistency_degenerate_weight_teachback_1` | Both return 0.0 with degenerate settings |

Total: 4 additional unit tests in `apps/api/tests/test_ces_score_consistency.py`.

### Regression tests (must remain GREEN without modification)

| File | Count | AC |
|------|-------|----|
| `apps/api/tests/test_s3_46_ces_breakdown_redistribution.py` | 23 | AC 13 |
| `apps/api/tests/test_session_report_endpoint.py` | existing | no regressions |
| `apps/api/tests/test_ces.py` | 20 | no regressions |

---

## Decision References

| Decision | Description | Implementation in this story |
|----------|-------------|------------------------------|
| D15 | `ces_score` source of truth for `SessionReport` — shared utility; `finalize_session` uses same formula as breakdown | `compute_ces_from_session_aggregates` at module level in `assessment/service.py`; `get_session_report` delegates to it; `finalize_session` (S3-35) will import and call it to write `sessions.ces_final = sum(result.values())` |

---

## Dependencies

- **S3-46** (must be merged first): Introduced `_build_ces_breakdown` as a private helper
  in `assessment/service.py` with proportional-redistribution logic. S3-51's
  `compute_ces_from_session_aggregates` supersedes or wraps this private function.
  Without S3-46, the redistribution formula is not in place and the cross-check tests
  (AC 10) cannot verify parity between the utility and `compute_ces`.

### What S3-51 unblocks

- **S3-35** (`finalize_session` implementation): S3-35 can import
  `compute_ces_from_session_aggregates` from `app.modules.assessment.service` and call it
  with `quiz_accuracy`, `teachback_normalised`, `behavioral_avg`, `head_pose_avg`,
  `blink_avg` read from DB/Redis. `sum(result.values())` becomes `sessions.ces_final`.
  Without S3-51, S3-35 must either duplicate the formula (introducing drift risk) or import
  the private `_build_ces_breakdown` (cross-module private import — unsafe pattern).

---

## Migration

**NO migration required.** This story modifies only Python business logic and test files:

- `apps/api/app/modules/assessment/service.py` — add `compute_ces_from_session_aggregates`
  at module level; update `get_session_report` to call it instead of `_build_ces_breakdown`
- `apps/api/tests/test_s3_51_ces_aggregates_utility.py` — new file (22 unit tests)
- `apps/api/tests/test_ces_score_consistency.py` — new file (4 consistency guard tests)

No new Supabase tables, columns, or constraints added. `supabase/migrations/` unchanged.
