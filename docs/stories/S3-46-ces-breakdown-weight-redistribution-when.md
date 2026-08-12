---
id: "S3-46"
title: "ces_breakdown weight redistribution when teachback=None — breakdown must explain the score (D2)"
status: "Draft"
sprint: 3
story_points: 3
owner: Dev3
priority: P1
decision_ref: D2
depends_on: ["S3-34", "S3-42", "S3-35"]
branch: "sprint3/s3-46-ces-breakdown-redistribution"
migration: "NO"
---

# Story S3-46 — ces_breakdown Weight Redistribution When teachback=None: Breakdown Must Explain the Score (D2)

## Context

**Decision D2:** Redistribute weights in `ces_breakdown` when `teachback_score` is `None` — matching the real-time formula.

**The problem:** `get_session_report` in `apps/api/app/modules/assessment/service.py` computes the five
`ces_breakdown` component contributions using nominal weights regardless of whether the student submitted
any teach-back responses. When a student skips all teach-back segments (`teachback_count == 0`):

- `teachback_score` is `None` (correct — no data).
- `teachback_contribution` is `0.0` (correct — nothing contributed).
- But `quiz_contribution = quiz_accuracy * ces_weight_quiz * 100` still uses the **nominal** 0.35 weight.
- And `behavioral`, `head_pose`, `blink` contributions also use their **nominal** weights (0.20, 0.12, 0.08).

The real-time `compute_ces()` — called by the tutor WebSocket handler on every 5-second attention window —
redistributes the `ces_weight_teachback` (0.25) proportionally across the remaining four signals when
`teachback_score is None`. So the actual `ces_final` written to the `sessions` table was computed with:

```
quiz_effective_weight      = 0.35 / 0.75 ≈ 0.4667
behavioral_effective_weight = 0.20 / 0.75 ≈ 0.2667
head_pose_effective_weight  = 0.12 / 0.75 ≈ 0.1600
blink_effective_weight      = 0.08 / 0.75 ≈ 0.1067
```

But the breakdown returns:
```
quiz_contribution = quiz_accuracy * 0.35 * 100  (nominal — WRONG when teachback absent)
```

The result: the five breakdown components do not sum to `ces_final`, and the breakdown does not explain
the score. A student who scored CES = 68.27 sees a breakdown that sums to 52.0, with no explanation
for the discrepancy.

**Root cause:** Step 5 in `get_session_report` uses the same weight regardless of whether teachback data
exists. No redistribution logic exists in the breakdown path.

**Dependency on S3-42:** After S3-42, `get_session_report` accepts a `redis` parameter and reads real
`behavioral_avg`, `head_pose_avg`, `blink_avg` from per-signal Redis history lists. S3-46 uses those
averages in the redistributed contribution formula. S3-42 must be merged before S3-46 is implemented.

**Dependency on S3-34:** S3-34 establishes the canonical `compute_ces()` with generalized
proportional redistribution. S3-46 mirrors the same `remaining = 1.0 - ces_weight_teachback` algebra
in the breakdown — no divergence between the two paths.

**Dependency on S3-35:** S3-35 ensures `sessions.ces_final` is reliably written with the redistributed
formula on session end. The breakdown's accuracy is only meaningful when `ces_final` is the value
computed by the real-time formula; S3-35 closes the write path.

---

## User Story

**As a** student viewing my session report after skipping all teach-back segments,
**I want** `ces_breakdown` to show component contributions computed with the redistributed
weights that were actually used to produce my CES score,
**so that** the five breakdown values sum to my actual `ces_score` (within floating-point tolerance)
and I understand what drove my engagement score — not a breakdown that sums to 52 while my score
was 68.

**As the** system building a session report,
**I want** `get_session_report` to call a single pure helper `_build_ces_breakdown` that
applies proportional weight redistribution when `teachback_normalised is None`,
**so that** the breakdown path and the real-time `compute_ces()` path apply the same algebraic
redistribution and any future weight change propagates consistently to both.

---

## Acceptance Criteria

### AC 1 — `_build_ces_breakdown` helper extracted as a pure testable function

A module-level function `_build_ces_breakdown` is defined in
`apps/api/app/modules/assessment/service.py` with the following exact signature:

```python
def _build_ces_breakdown(
    *,
    quiz_accuracy: float,
    teachback_normalised: float | None,
    behavioral_avg: float,
    head_pose_avg: float,
    blink_avg: float,
    settings: Settings,
) -> dict[str, float]:
```

- `teachback_normalised` is the normalised teach-back score: `avg_teachback / 100.0` when at
  least one teach-back attempt exists, `None` when no attempts exist.
- The return value has exactly 5 keys: `"quiz"`, `"teachback"`, `"behavioral"`,
  `"head_pose"`, `"blink"`.
- The function has no I/O — no Supabase calls, no Redis calls, no LLM calls, no
  `asyncio` usage. `inspect.getsource(_build_ces_breakdown)` does not contain the strings
  `"supabase"`, `"redis"`, `"await"`, `"asyncio"`.

**Exact assertion:** `inspect.signature(_build_ces_breakdown).parameters` contains exactly
the 6 keys `{"quiz_accuracy", "teachback_normalised", "behavioral_avg", "head_pose_avg",
"blink_avg", "settings"}`.

### AC 2 — Nominal-weight path: when teachback_normalised is not None

With default weights (quiz=0.35, teachback=0.25, behavioral=0.20, head_pose=0.12, blink=0.08)
and `teachback_normalised=0.85` (not None), all five components use their nominal weights:

**Exact inputs:**
`quiz_accuracy=0.5, teachback_normalised=0.85, behavioral_avg=0.7, head_pose_avg=0.5, blink_avg=0.4`

**Exact expected output:**
```python
{
    "quiz":       17.5,    # round(0.5  * 0.35 * 100, 4)
    "teachback":  21.25,   # round(0.85 * 0.25 * 100, 4)
    "behavioral": 14.0,    # round(0.7  * 0.20 * 100, 4)
    "head_pose":   6.0,    # round(0.5  * 0.12 * 100, 4)
    "blink":       3.2,    # round(0.4  * 0.08 * 100, 4)
}
```

Sum = 61.95. This matches what `compute_ces(all present, same values)` would return (61.95 on
the 0–100 scale).

### AC 3 — Redistributed-weight path: when teachback_normalised is None

With the same default weights and `teachback_normalised=None`, the teachback weight (0.25)
is redistributed across the four remaining signals.

**Redistribution formula:** `effective_weight_i = ces_weight_i / (1.0 - ces_weight_teachback)`
where `remaining = 1.0 - ces_weight_teachback = 0.75`.

**Exact inputs:**
`quiz_accuracy=0.5, teachback_normalised=None, behavioral_avg=0.7, head_pose_avg=0.5, blink_avg=0.4`

**Exact expected output:**
```python
{
    "quiz":       23.3333,  # round(0.5 * (0.35/0.75) * 100, 4)
    "teachback":   0.0,
    "behavioral": 18.6667,  # round(0.7 * (0.20/0.75) * 100, 4)
    "head_pose":   8.0,     # round(0.5 * (0.12/0.75) * 100, 4)
    "blink":       4.2667,  # round(0.4 * (0.08/0.75) * 100, 4)
}
```

**Verification:** `compute_ces(quiz_accuracy=0.5, teachback_score=None, behavioral=0.7, head_pose=0.5, blink=0.4, settings=default_settings)` → `round(0.5*(0.35/0.75) + 0.7*(0.20/0.75) + 0.5*(0.12/0.75) + 0.4*(0.08/0.75), 4) * 100 = round(0.54267 * 100, 4) = 54.2667`. The sum of the breakdown components is also 54.2667. The breakdown explains the score.

### AC 4 — Full-engagement redistribution sums within 0.001 of 100.0

When all four present signals are 1.0 and `teachback_normalised=None`:

**Exact inputs:**
`quiz_accuracy=1.0, teachback_normalised=None, behavioral_avg=1.0, head_pose_avg=1.0, blink_avg=1.0`

**Expected:**
```python
{
    "quiz":       46.6667,  # round(1.0 * (0.35/0.75) * 100, 4)
    "teachback":   0.0,
    "behavioral": 26.6667,  # round(1.0 * (0.20/0.75) * 100, 4)
    "head_pose":  16.0,     # round(1.0 * (0.12/0.75) * 100, 4)
    "blink":      10.6667,  # round(1.0 * (0.08/0.75) * 100, 4)
}
```

**Exact assertion:** `abs(sum(result.values()) - 100.0) < 0.001`

(The tiny residual of 0.0001 is inherent to per-component rounding; `compute_ces` computes
the sum before rounding and returns exactly 100.0. The tolerance of 0.001 is both strict
enough to catch a broken formula and lenient enough for this inherent 4-dp rounding effect.)

### AC 5 — Zero-signal redistribution yields all zeros

When `teachback_normalised=None` and all other signals are 0.0:

```python
_build_ces_breakdown(
    quiz_accuracy=0.0,
    teachback_normalised=None,
    behavioral_avg=0.0,
    head_pose_avg=0.0,
    blink_avg=0.0,
    settings=default_settings,
)
== {"quiz": 0.0, "teachback": 0.0, "behavioral": 0.0, "head_pose": 0.0, "blink": 0.0}
```

No `ZeroDivisionError` is raised. The guard is `if remaining <= 0.0: return all_zeros` —
this never fires with valid settings, but is present for defense in depth.

### AC 6 — Degenerate guard: ces_weight_teachback >= 1.0 returns all zeros without crashing

When `settings.ces_weight_teachback = 1.0` (pathological misconfiguration — the model_validator
prevents this in production, but tests can inject it):

`_build_ces_breakdown(..., teachback_normalised=None, settings=degenerate_settings)` returns
`{"quiz": 0.0, "teachback": 0.0, "behavioral": 0.0, "head_pose": 0.0, "blink": 0.0}`.

No `ZeroDivisionError` is raised. No exception of any kind is raised.

**Exact assertion:** calling the function with `ces_weight_teachback=1.0` and
`teachback_normalised=None` returns a dict with all values == 0.0.

### AC 7 — No hardcoded weight literals in `_build_ces_breakdown`

Source inspection of `_build_ces_breakdown` confirms that all weight lookups reference
`settings.ces_weight_*` — not literal floats.

**Exact assertions:**
- `"settings.ces_weight_quiz"` in `inspect.getsource(_build_ces_breakdown)`
- `"settings.ces_weight_teachback"` in `inspect.getsource(_build_ces_breakdown)`
- `"settings.ces_weight_behavioral"` in `inspect.getsource(_build_ces_breakdown)`
- `"settings.ces_weight_head_pose"` in `inspect.getsource(_build_ces_breakdown)`
- `"settings.ces_weight_blink"` in `inspect.getsource(_build_ces_breakdown)`

### AC 8 — `get_session_report` delegates to `_build_ces_breakdown`

`get_session_report` no longer contains an inline `ces_breakdown = { ... }` dict literal for
the five components. Instead it calls `_build_ces_breakdown(...)`.

**Exact assertion:** `"_build_ces_breakdown"` in `inspect.getsource(get_session_report)`.

The call passes:
- `quiz_accuracy` — the session-level quiz accuracy (fraction correct, 0–1)
- `teachback_normalised` — `avg_teachback / 100.0` when `teachback_count > 0`, else `None`
- `behavioral_avg`, `head_pose_avg`, `blink_avg` — averages from the Redis signal history
  lists (as established by S3-42); `0.0` when no signals recorded or Redis unavailable
- `settings` — from `get_settings()`

**Exact assertion:** `inspect.getsource(get_session_report)` contains both
`"teachback_normalised="` and `"_build_ces_breakdown("`.

### AC 9 — When teachback is absent, get_session_report breakdown uses redistributed weights

Integration-level: calling `get_session_report` with `teachback_attempts = []` and
`quiz_attempts = [{"is_correct": True}, {"is_correct": False}]` (quiz_accuracy = 0.5),
with `redis=None` (behavioral/head_pose/blink = 0.0):

**Expected `ces_breakdown`:**
```python
{
    "quiz":       round(0.5 * (0.35 / 0.75) * 100, 4),  # 23.3333
    "teachback":  0.0,
    "behavioral": 0.0,
    "head_pose":  0.0,
    "blink":      0.0,
}
```

**Exact assertion (replaces the pre-S3-46 test AC 8 in test_session_report_endpoint.py):**
`result.ces_breakdown["quiz"] == pytest.approx(round(0.5 * (0.35 / 0.75) * 100, 4), rel=1e-4)`

### AC 10 — When teachback is present, get_session_report breakdown uses nominal weights (unchanged)

Integration-level: calling `get_session_report` with `teachback_attempts = [{"score": 80}, {"score": 90}]`
(avg = 85.0, normalised = 0.85) and `quiz_attempts = [{"is_correct": True}, {"is_correct": True}, {"is_correct": False}]`
(quiz_accuracy = 2/3):

**Expected `ces_breakdown["quiz"]`:**
`round((2/3) * 0.35 * 100, 4) = 23.3333` (nominal weight — teachback is present)

**Expected `ces_breakdown["teachback"]`:**
`round((85.0/100.0) * 0.25 * 100, 4) = 21.25` (unchanged)

**Exact assertion:** `result.ces_breakdown["quiz"] == pytest.approx(round((2/3) * 0.35 * 100, 4), rel=1e-4)`

### AC 11 — Mock settings fixture updated to include all 5 CES weight fields

The `_mock_settings` fixture in `apps/api/tests/test_session_report_endpoint.py` currently
sets only `ces_weight_quiz` and `ces_weight_teachback`. After S3-46, `_build_ces_breakdown`
accesses all five weights. The fixture must be updated:

```python
mock_settings.ces_weight_quiz = 0.35
mock_settings.ces_weight_teachback = 0.25
mock_settings.ces_weight_behavioral = 0.20
mock_settings.ces_weight_head_pose = 0.12
mock_settings.ces_weight_blink = 0.08
```

**Exact assertion:** All existing tests in `test_session_report_endpoint.py` still pass after
this fixture update (no regressions introduced by adding the three missing weight attributes).

### AC 12 — CI guard: no inline `ces_breakdown` dict literal in `get_session_report` source

A source-inspection test asserts that `get_session_report` no longer builds the breakdown
dict inline with hardcoded keys.

**Exact assertion:** `'"behavioral": 0.0' not in inspect.getsource(get_session_report)`.

This prevents the S3-42 deferred-zeros anti-pattern from re-appearing.
(This test is additive — S3-42's guard `test_ces_breakdown_no_hardcoded_zero_for_behavioral`
remains in place; this story's guard confirms that the delegation to `_build_ces_breakdown`
is also enforced.)

---

## Tasks / Subtasks

### Task 1 — Story file (story-first gate)
- [ ] 1.1 Create `docs/stories/S3-46-ces-breakdown-weight-redistribution-when.md`
- [ ] 1.2 Commit story-only to `sprint3/s3-46-ces-breakdown-redistribution`
- [ ] 1.3 Push to remote before any implementation

### Task 2 — RED phase (failing tests)
- [ ] 2.1 Create `apps/api/tests/test_s3_46_ces_breakdown_redistribution.py`
- [ ] 2.2 Test AC 1 — signature: `_build_ces_breakdown` exists with the 6 required parameters
- [ ] 2.3 Test AC 1 — purity: `"asyncio"` not in source, `"redis"` not in source, `"supabase"` not in source
- [ ] 2.4 Test AC 2 — nominal path: all 5 components match exact expected values when `teachback_normalised=0.85`
- [ ] 2.5 Test AC 3 — redistributed path: `quiz=23.3333`, `teachback=0.0`, `behavioral=18.6667`, `head_pose=8.0`, `blink=4.2667` when `teachback_normalised=None`
- [ ] 2.6 Test AC 4 — full-engagement redistribution: `abs(sum(values) - 100.0) < 0.001`
- [ ] 2.7 Test AC 5 — zero signals + `teachback_normalised=None` → all zeros, no exception
- [ ] 2.8 Test AC 6 — degenerate guard: `ces_weight_teachback=1.0` + `teachback_normalised=None` → all zeros, no exception
- [ ] 2.9 Test AC 7 — source guard: all 5 `settings.ces_weight_*` strings present in `_build_ces_breakdown` source
- [ ] 2.10 Test AC 8 — delegation: `"_build_ces_breakdown"` in `inspect.getsource(get_session_report)`
- [ ] 2.11 Test AC 9 — integration: `get_session_report` with `tb_rows=[]`, `quiz_accuracy=0.5` → `quiz=23.3333`
- [ ] 2.12 Test AC 10 — integration: `get_session_report` with `tb_rows=[80,90]`, teachback present → quiz uses nominal 0.35
- [ ] 2.13 Test AC 12 — CI guard: `'"behavioral": 0.0'` not in `get_session_report` source
- [ ] 2.14 Confirm all tests FAIL before implementation

### Task 3 — GREEN phase (implementation)
- [ ] 3.1 `apps/api/app/modules/assessment/service.py`: define `_build_ces_breakdown` above `get_session_report`
      — implement nominal path (teachback_normalised not None) and redistributed path (teachback_normalised is None)
      — add degenerate guard for `remaining <= 0.0`
- [ ] 3.2 `get_session_report` Step 5: replace inline `ces_breakdown = { ... }` dict with a call to `_build_ces_breakdown`
      — compute `teachback_normalised = (avg_teachback / 100.0) if teachback_count > 0 else None`
      — pass `behavioral_avg`, `head_pose_avg`, `blink_avg` from S3-42 Redis reads (or 0.0 if unavailable)
- [ ] 3.3 Update `_mock_settings` fixture in `test_session_report_endpoint.py` to add `ces_weight_behavioral=0.20`,
      `ces_weight_head_pose=0.12`, `ces_weight_blink=0.08`
- [ ] 3.4 Update the pre-S3-46 `test_get_report_ces_breakdown_quiz_matches_formula` (AC 8 in the existing file)
      — the test used `tb_rows=[]` (teachback absent), so expected value changes from `round((2/3)*0.35*100,4)=23.3333`
      to `round((2/3)*(0.35/0.75)*100,4)=31.1111` — annotate with `# UPDATED-S3-46: teachback absent → redistributed`
- [ ] 3.5 Update the pre-S3-46 `test_get_report_ces_breakdown_attention_always_zero` (AC 10 in the existing file)
      — after S3-42 this test already changes; confirm it is correct under redistributed weights or update expected values
- [ ] 3.6 Confirm all AC tests PASS

### Task 4 — REFACTOR + validation
- [ ] 4.1 `ruff check .` — zero new errors repo-wide
- [ ] 4.2 `ruff format --check` — zero format violations
- [ ] 4.3 Full Dev 3 regression suite GREEN (all `pytest -m unit` tests pass)
- [ ] 4.4 Confirm existing `test_session_report_endpoint.py` tests all pass after fixture update

### Task 5 — 6-agent adversarial review
- [ ] 5.1 Layer 1 — Story Quality
- [ ] 5.2 Layer 2 — Blind Hunter (Security)
- [ ] 5.3 Layer 3 — Test Coverage
- [ ] 5.4 Layer 4 — AC Completeness
- [ ] 5.5 Layer 5 — Process Integrity
- [ ] 5.6 Layer 6 — Scale & Load

### Task 6 — Commit + push
- [ ] 6.1 Final implementation commit on `sprint3/s3-46-ces-breakdown-redistribution`
- [ ] 6.2 Push to remote
- [ ] 6.3 Update `docs/dev3-assessment-tracker.md`

---

## Scale & Load

### Q1 — What is ONE unit of work, and what is its range?

One unit of work is a single call to `_build_ces_breakdown`, invoked once per call to
`get_session_report`.

- **Min:** Called once per report request, regardless of session length.
- **Typical:** One call per completed session report view. The function performs 4–10
  arithmetic operations (multiplications, divisions, rounded floats). O(1).
- **Largest possible:** Identical to minimum — the function is stateless and takes the
  same amount of CPU regardless of session duration, number of quiz attempts, or number
  of teachback attempts. Session length does not affect this function.
- **Beyond the bound:** Not applicable. There is no budget to exceed. The function accepts
  five floats, performs arithmetic, and returns five floats.

`get_session_report` itself may be called concurrently by multiple users. Each call is
independent; `_build_ces_breakdown` shares no state.

### Q2 — Which budgets are FIXED while the input VARIES — and what happens past them?

`_build_ces_breakdown` has one fixed limit: the 5-slot signal schema. If `ces_weight_teachback`
reaches or exceeds `1.0`, the `remaining` divisor becomes `≤ 0.0`. The guard
`if remaining <= 0.0: return all_zeros` handles this explicitly — no division-by-zero, no
exception, no silent NaN propagation.

The Settings `model_validator` prevents `ces_weight_teachback >= 1.0` from reaching
production (the five weights must sum to `1.0 ± 0.001`). The guard exists for test
environments and defense in depth.

No other fixed budget is introduced by this story. All five weight env vars are read
from `settings` — changing them via Railway env vars propagates automatically.

Silent truncation: not applicable. This function performs pure arithmetic. All inputs
are floats (already validated upstream) and all outputs are explicitly rounded to 4 dp.

### Q3 — What is the SCOPE of every limit?

| Limit | Scope | Justification |
|-------|-------|---------------|
| `remaining <= 0.0` guard | Per-call | Stateless — no shared state between calls |
| `ces_weight_*` env vars | Per-deployment (all instances share the same Railway env) | `get_settings()` is an `lru_cache(maxsize=1)` — the same `Settings` object is returned for the lifetime of each worker. Changing an env var requires a redeploy to propagate. This is acceptable — weights are not session-specific. |
| 5-dp rounding of each component | Per-call | Each `round(..., 4)` is deterministic and isolated to this function's output. |

### Q4 — Which reads and writes are UNBOUNDED?

None introduced by this story.

- `_build_ces_breakdown` performs no I/O. Its only inputs are five floats plus a settings
  object. Its output is a 5-key dict of floats.
- The function does not query Supabase. It does not read Redis. It does not call LLMs.
- Existing `get_session_report` DB reads (`quiz_attempts`, `teachback_attempts`,
  `session_events`) are unchanged. Those reads were bounded pre-S3-46 (bounded by session
  scope; a session cannot accumulate more `quiz_attempts` than quiz questions in the lesson).
- Existing Redis reads in `get_session_report` (via S3-42's `_signal_avg`) read at most
  `_CES_HISTORY_MAX = 10` entries per key — unchanged.

### Q5 — Which caps were INHERITED from an earlier design, and have they been re-derived?

The redistribution formula `remaining = 1.0 - ces_weight_teachback` mirrors the real-time
`compute_ces()` implementation established by Story 3-23 and generalized by S3-34.
This story inherits that formula. Re-derivation is not required — S3-34 already proved
the formula is the correct generalization for any absent signal.

The choice to redistribute only `ces_weight_teachback` (not `ces_weight_quiz` or the
attention signals) is a deliberate asymmetry: quiz absence is a "no data yet" transient
state (treated as 0.0 in the breakdown, consistent with `compute_ces`), while teachback
absence is a permanent session-level state (student skipped all segments).

This asymmetry is established in S3-34 (D61 fix) and documented in CLAUDE.md §11.
S3-46 inherits and applies the same rule to the breakdown path.

### Q6 — Is every check-then-act sequence safe under CONCURRENT requests?

No check-then-act sequences are introduced by this story.

`_build_ces_breakdown` is a pure function with no shared mutable state. Multiple concurrent
calls from different sessions or different users do not interact.

`get_session_report` acquires no locks. The ownership check (Step 1) is a read-only DB query
that does not create a "check" that a concurrent write could invalidate between check and
act — the session row is immutable once ended.

---

## Security

### Authentication and ownership

`get_session_report` is called from `GET /api/assessment/session/{id}/report`, which requires
a valid JWT (`CurrentUser` dependency). The ownership check (`session.user_id == current_user["sub"]`)
runs in Step 1, before any data is read and before `_build_ces_breakdown` is called. An
attacker who guesses a valid `session_id` but cannot produce a JWT for its owner receives
HTTP 404 (SEC-006 anti-enumeration: the same error for non-existent and wrong-owner sessions).

`_build_ces_breakdown` receives only floats derived from validated, owned session data.
There is no path by which an attacker can inject a `teachback_normalised` value — the value
is derived from `teachback_attempts` rows that are already filtered by `session_id`.

### Input validation

All five float inputs are derived from:
- `quiz_accuracy`: `correct_count / total_count` — bounded [0.0, 1.0] by construction
  (counts are non-negative integers; a session cannot have more correct than total answers)
- `teachback_normalised`: `avg_teachback / 100.0` — bounded [0.0, 1.0] since `avg_teachback`
  is the average of DB-stored `score` values, each constrained by `CHECK(score >= 0 AND score <= 100)`
- `behavioral_avg`, `head_pose_avg`, `blink_avg`: averages of Redis-stored floats originally
  normalised to [0.0, 1.0] by the WebSocket boundary layer (S3-42). The `_signal_avg` helper
  returns 0.0 for empty history — never negative, never > 1.0.

No additional input validation is needed inside `_build_ces_breakdown`. Out-of-range floats
(which cannot occur via normal code paths) would produce an out-of-range contribution, which
is a correctness bug in the caller — not a security issue in `_build_ces_breakdown` itself.

### No new attack surface

This story adds no new HTTP endpoints, no new Supabase tables, no new migrations, and no new
Redis keys. It only restructures an existing arithmetic step in `get_session_report` into a
testable helper function.

---

## Test Requirements

All new tests live in `apps/api/tests/test_s3_46_ces_breakdown_redistribution.py` and are
`@pytest.mark.unit` (no real Redis, no real DB, no real LLM calls).

### New tests (test_s3_46_ces_breakdown_redistribution.py)

| Test name | AC | Type |
|-----------|-----|------|
| `test_build_ces_breakdown_signature_has_6_params` | AC 1 | Source inspection |
| `test_build_ces_breakdown_is_pure_no_io_imports` | AC 1 | Source inspection |
| `test_build_ces_breakdown_nominal_path_quiz` | AC 2 | Unit (pure function) |
| `test_build_ces_breakdown_nominal_path_teachback` | AC 2 | Unit (pure function) |
| `test_build_ces_breakdown_nominal_path_behavioral` | AC 2 | Unit (pure function) |
| `test_build_ces_breakdown_nominal_path_head_pose` | AC 2 | Unit (pure function) |
| `test_build_ces_breakdown_nominal_path_blink` | AC 2 | Unit (pure function) |
| `test_build_ces_breakdown_nominal_path_all_five_exact` | AC 2 | Unit (pure function) |
| `test_build_ces_breakdown_redistributed_quiz` | AC 3 | Unit (pure function) |
| `test_build_ces_breakdown_redistributed_teachback_is_zero` | AC 3 | Unit (pure function) |
| `test_build_ces_breakdown_redistributed_behavioral` | AC 3 | Unit (pure function) |
| `test_build_ces_breakdown_redistributed_head_pose` | AC 3 | Unit (pure function) |
| `test_build_ces_breakdown_redistributed_blink` | AC 3 | Unit (pure function) |
| `test_build_ces_breakdown_redistributed_sum_matches_compute_ces` | AC 3 | Unit (cross-check with `compute_ces`) |
| `test_build_ces_breakdown_full_engagement_redistribution_sums_to_100` | AC 4 | Unit (pure function) |
| `test_build_ces_breakdown_zero_signals_teachback_none_no_exception` | AC 5 | Unit (pure function) |
| `test_build_ces_breakdown_degenerate_weight_teachback_1_returns_zeros` | AC 6 | Unit (pure function) |
| `test_build_ces_breakdown_source_contains_all_weight_settings` | AC 7 | Source inspection |
| `test_get_session_report_delegates_to_build_ces_breakdown` | AC 8 | Source inspection |
| `test_get_session_report_passes_teachback_normalised_arg` | AC 8 | Source inspection |
| `test_get_session_report_teachback_absent_uses_redistributed_weight_for_quiz` | AC 9 | Integration (mocked Supabase) |
| `test_get_session_report_teachback_present_uses_nominal_weight_for_quiz` | AC 10 | Integration (mocked Supabase) |
| `test_get_session_report_no_inline_ces_breakdown_dict_with_hardcoded_zero` | AC 12 | Source inspection CI guard |

### Updated tests (test_session_report_endpoint.py)

| Test name | What changes | AC |
|-----------|-------------|-----|
| `test_get_report_ces_breakdown_quiz_matches_formula` | `expected` updated from `round((2/3)*0.35*100,4)` to `round((2/3)*(0.35/0.75)*100,4)` because `tb_rows=[]` (teachback absent) triggers redistribution | AC 9 |
| `_mock_settings` fixture | Add `ces_weight_behavioral=0.20`, `ces_weight_head_pose=0.12`, `ces_weight_blink=0.08` to prevent `AttributeError` in `_build_ces_breakdown` | AC 11 |

**Regression tests (must remain GREEN without modification):**
- `test_get_report_ces_breakdown_teachback_matches_formula` — still correct (teachback present, nominal weights)
- `test_get_report_ces_breakdown_teachback_zero_when_no_attempts` — still correct (teachback: 0.0 when no attempts)
- `test_get_report_ces_breakdown_has_exactly_5_keys` — still correct (5 keys unchanged)
- `test_get_report_wrong_user_returns_404` — no change (ownership check precedes breakdown)
- All SEC-006 tests — no change

---

## Decision References

| Decision | Description | Implementation in this story |
|----------|-------------|------------------------------|
| D2 | Redistribute weights in `ces_breakdown` when `teachback_score=None` — matching real-time formula | `_build_ces_breakdown` with proportional redistribution via `remaining = 1.0 - ces_weight_teachback` |

---

## Dependencies

- **S3-34** (must be merged first): Establishes canonical `compute_ces()` with generalized
  proportional redistribution. S3-46's formula mirrors S3-34's redistribution algebra exactly
  so the two paths never diverge.

- **S3-42** (must be merged first): Adds `behavioral_avg`, `head_pose_avg`, `blink_avg` from
  Redis signal history to `get_session_report`. S3-46 passes those values to
  `_build_ces_breakdown` — if S3-42 is not merged, the helper receives `0.0` for all three
  attention signals and the redistributed breakdown is partially wrong (quiz is correct;
  behavioral/head_pose/blink remain 0.0 even though signals were captured).

- **S3-35** (must be merged first): Ensures `sessions.ces_final` is written with the same
  redistributed formula on session end. Without S3-35, `ces_final` may be `NULL` or computed
  with a different formula, making the breakdown sum check meaningless.

---

## Migration

**NO migration required.** This story modifies only Python business logic:

- `apps/api/app/modules/assessment/service.py` — add `_build_ces_breakdown` helper; update
  Step 5 of `get_session_report` to call it
- `apps/api/tests/test_s3_46_ces_breakdown_redistribution.py` — new test file (23 tests)
- `apps/api/tests/test_session_report_endpoint.py` — fixture update + 1 test value update

No new Supabase tables, columns, or constraints are added. `supabase/migrations/` is
unchanged.
