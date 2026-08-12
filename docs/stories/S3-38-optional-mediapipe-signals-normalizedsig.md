---
id: "S3-38"
title: "Optional MediaPipe signals — NormalizedSignal behavioral/head_pose/blink -> float|None (D5)"
status: Draft
sprint: 3
story_points: 3
owner: Dev4 / Dev3
decision_refs: [D5, D16]
depends_on: [S3-42, S3-43, S3-44]
migration: "NO"
branch: implemented/ces-fallback
---

# Story S3-38 — Optional MediaPipe signals: NormalizedSignal behavioral/head\_pose/blink → `float | None` (D5)

## Context

During a live lesson session, the browser's MediaPipe Face Landmarker WASM module may be
unavailable in a given 5-second window — camera permission denied mid-session, face not in
frame, browser tab backgrounded, or a transient WASM crash. When that happens the frontend
sends `null` for `behavioral_score`, `head_pose_score`, and/or `blink_rate` instead of a
numeric value.

Currently `NormalizedSignal` treats all three MediaPipe-derived fields as required `float`.
`_parse_signal` raises a `ValueError` and the whole signal is dropped. The CES computation
misses the window entirely, the intervention trigger sees fewer data points, and Redis history
lists accumulate misleading `0.0` entries or no entries depending on how the error is handled
upstream.

D5 corrects this by making the three MediaPipe signals optional — `float | None` — throughout
the signal processing pipeline, and skipping the Redis LPUSH for any field that is `None` so
that history lists contain only genuine measurements.

**This story must not be implemented until S3-42, S3-43, and S3-44 have been merged to `main`
and the `ces-fallback` branch has been merged (D16 merge order).** The `ces-fallback` branch
carries the CES redistribution logic and `ces_breakdown` changes that S3-38's `assessment/ces.py`
update depends on.

---

## User Story

**As the system** processing a live attention signal from a student's browser,
**I want** `behavioral_score`, `head_pose_score`, and `blink_rate` to be treated as optional
(may be `null`/`None`) in the signal parsing and CES computation pipeline,
**so that** a MediaPipe frame drop or camera-unavailable event does not discard the entire
5-second window and the CES history list stays clean (no ghost `0.0` values for absent signals).

---

## Acceptance Criteria

### AC 1 — `NormalizedSignal` dataclass: three fields become `float | None`

`NormalizedSignal` in `apps/api/app/modules/tutor/service.py` has the following field types
after this change:

```python
behavioral_score: float | None   # was: float
head_pose_score:  float | None   # was: float
blink_rate:       float | None   # was: float
```

`quiz_accuracy` and `teachback_score` are already `float | None` and remain unchanged.

**Verified by:** `test_normalized_signal_fields_are_optional` — asserts that creating
`NormalizedSignal(session_id="x", quiz_accuracy=None, teachback_score=None,
behavioral_score=None, head_pose_score=None, blink_rate=None)` does not raise.

---

### AC 2 — `_parse_signal`: uses `_optional_float` for all three MediaPipe fields

`_parse_signal` in `tutor/service.py` switches from `_require_float` to `_optional_float`
for `behavioral_score`, `head_pose_score`, and `blink_rate`. A payload with any of these
fields absent or explicitly `null` must parse successfully and produce a `NormalizedSignal`
with the corresponding field set to `None`.

**Verified by:**
- `test_parse_signal_null_behavioral_score_accepted` — payload `{"behavioral_score": null}` → `NormalizedSignal.behavioral_score is None`
- `test_parse_signal_null_head_pose_accepted` — same for `head_pose_score`
- `test_parse_signal_null_blink_rate_accepted` — same for `blink_rate`
- `test_parse_signal_all_three_null_accepted` — all three null simultaneously → three `None` fields, no exception
- `test_parse_signal_missing_behavioral_score_accepted` — field absent from payload → `None` (not `ValueError`)

---

### AC 3 — `_parse_signal`: NaN / ±inf for MediaPipe fields still rejected

A finite-number guard is applied to the three fields even in their optional form. A `null`
value is accepted; a non-null non-finite value (`NaN`, `Infinity`, `-Infinity`) raises
`ValueError` with the field name in the message.

**Verified by:**
- `test_parse_signal_nan_behavioral_raises` — `{"behavioral_score": "NaN"}` → `ValueError` mentioning `behavioral_score`
- `test_parse_signal_inf_head_pose_raises` — `{"head_pose_score": float("inf")}` → `ValueError`

---

### AC 4 — `process_attention_signal`: LPUSH is skipped when a signal is `None`

In `process_attention_signal`, the Redis LPUSH to `session:{sid}:behavioral_history`,
`session:{sid}:head_pose_history`, and `session:{sid}:blink_history` is guarded by a `None`
check. When the field value is `None`, no LPUSH or LTRIM is issued for that key in that window.

Exact guard pattern for each key:

```python
if normalized.behavioral_score is not None:
    await redis.lpush(f"session:{session_id}:behavioral_history", normalized.behavioral_score)
    await redis.ltrim(f"session:{session_id}:behavioral_history", 0, _CES_HISTORY_MAX - 1)
    await redis.expire(f"session:{session_id}:behavioral_history", _CES_WINDOW_TTL)
```

(Identical pattern for `head_pose_history` and `blink_history`.)

**Verified by:**
- `test_process_signal_none_behavioral_skips_lpush` — asserts `redis.lpush` not called with `behavioral_history` key when `behavioral_score=None`
- `test_process_signal_none_head_pose_skips_lpush`
- `test_process_signal_none_blink_skips_lpush`
- `test_process_signal_all_none_no_lpush_for_mediapipe_keys` — all three None → zero LPUSH calls for the three MediaPipe history keys (CES history and window keys are still written)

---

### AC 5 — `process_attention_signal`: CES is still computed and written when MediaPipe signals are `None`

When one or more MediaPipe signals are `None`, the CES is still computed (using the
weight-redistribution logic from `compute_ces`) and written to `session:{sid}:ces_window`
and `session:{sid}:ces_history`. The signal window is not discarded.

**Verified by:**
- `test_process_signal_all_mediapipe_none_returns_ces_result` — call with `behavioral_score=None, head_pose_score=None, blink_rate=None` returns a `CesResult` with `ces >= 0.0`

---

### AC 6 — `assessment/ces.py` `compute_ces`: three MediaPipe parameters become `float | None`

`compute_ces` in `apps/api/app/modules/assessment/ces.py` accepts `behavioral`, `head_pose`,
and `blink` as `float | None`. When any is `None`, its weight is redistributed proportionally
across the present signals, using the same generalised weight-redistribution already applied to
`teachback_score`.

Updated signature:

```python
def compute_ces(
    *,
    quiz_accuracy: float | None,
    teachback_score: float | None,
    behavioral: float | None,
    head_pose: float | None,
    blink: float | None,
    settings: Settings,
) -> float:
```

Internal weight-redistribution: build a `(value, weight)` list of non-None signals, normalise
each weight by dividing by the sum of present weights, then compute CES. This generalises the
existing teachback-None branch and handles any combination of absent signals.

Special case: if ALL five signals are `None` (no data at all), return `0.0`.

**Verified by:**
- `test_ces_behavioral_none_redistributes_weight` — `behavioral=None`, others at `1.0` → CES equals the value you would get if you divided the behavioral weight across the remaining signals
- `test_ces_head_pose_none_redistributes_weight`
- `test_ces_blink_none_redistributes_weight`
- `test_ces_all_mediapipe_none_uses_quiz_and_teachback_only` — only quiz=1.0 and teachback=1.0 present → CES = 100.0
- `test_ces_all_signals_none_returns_zero` — all five `None` → `0.0`
- `test_ces_behavioral_none_weight_sum_still_normalised` — with default weights, absent behavioral (0.20) redistributed across remaining (0.80) → present weights still sum to 1.0 after normalisation

---

### AC 7 — Existing `compute_ces` tests remain GREEN with no change

All existing unit tests in `tests/unit/test_ces.py` (and any file testing `compute_ces`) pass
without modification. This AC confirms the signature change is backward-compatible: callers that
passed `float` values still work (a non-None `float` satisfies `float | None`).

**Verified by:** `pytest apps/api/tests/ -k ces -x` exits 0.

---

### AC 8 — `ws.ts` `AttentionSignalMessage`: three payload fields become `number | null`

`packages/shared/types/ws.ts` `AttentionSignalMessage.payload` changes:

```typescript
behavioral_score: number | null;   // was: number
head_pose_score:  number | null;   // was: number
blink_rate:       number | null;   // was: number
```

This is a **frozen-contract change** — it requires a PR reviewed and signed off by all 4
developers before merge. The PR description must state that null means "MediaPipe unavailable
in this window" and that the server will skip the Redis history write for that field.

**Verified by:** TypeScript type-check (`tsc --noEmit`) exits 0 after the change.

Note: This is an additive loosening of the contract (accepting `null` where only `number` was
accepted before). Existing clients sending non-null values are unaffected.

---

### AC 9 — `tutor/service.py` `compute_ces` (`NormalizedSignal`-based): already handles `None` — no change needed

The `compute_ces` function in `tutor/service.py` (which takes a `NormalizedSignal` object)
already filters out `None` values:

```python
present = [(v, w) for (v, w) in pairs if v is not None]
```

Making the three fields `Optional` in `NormalizedSignal` automatically enables the
redistribution for those fields with zero code change to that function.

**Verified by:** `test_tutor_compute_ces_with_none_behavioral_redistributes` — creates a
`NormalizedSignal` with `behavioral_score=None` and asserts the CES matches the expected
redistributed value.

---

### AC 10 — No regression in session report `ces_breakdown`

The `ces_breakdown` computation in `assessment/service.py` (added by S3-42) reads from the
Redis history lists. When MediaPipe signals were `None` for a window, no value was pushed for
that window (AC 4). The breakdown average is therefore computed over only the windows where data
was present. The breakdown must not include `0.0` ghost values for absent signals.

**Verified by:**
- `test_ces_breakdown_excludes_none_windows` — simulates 3 windows: window 1 has behavioral=0.8,
  window 2 has behavioral=None (skipped), window 3 has behavioral=0.6. The `behavioral` breakdown
  value equals `(0.8 + 0.6) / 2 = 0.70`, not `(0.8 + 0.0 + 0.6) / 3 = 0.467`.

---

## Tasks / Subtasks

### Task 1 — Update `NormalizedSignal` and `_parse_signal` in `tutor/service.py`
- [ ] **1.1** Change `behavioral_score: float`, `head_pose_score: float`, `blink_rate: float` to `float | None` in the `NormalizedSignal` dataclass
- [ ] **1.2** Change `_parse_signal` to call `_optional_float("behavioral_score")`, `_optional_float("head_pose_score")`, `_optional_float("blink_rate")` instead of `_require_float`

### Task 2 — Guard LPUSH in `process_attention_signal` in `tutor/service.py`
- [ ] **2.1** Wrap each of the three MediaPipe history LPUSH/LTRIM/expire calls in `if normalized.<field> is not None:` guard

### Task 3 — Update `assessment/ces.py` `compute_ces` signature and logic
- [ ] **3.1** Change `behavioral: float`, `head_pose: float`, `blink: float` parameters to `float | None`
- [ ] **3.2** Replace the current `if teachback_score is None` / `else` branching with a generalised weight-redistribution: build a list of `(value, weight)` for non-None signals and normalise by present weight sum
- [ ] **3.3** Add `if not present: return 0.0` guard (all five signals None)

### Task 4 — Update `ws.ts` (frozen contract — 4-dev sign-off required)
- [ ] **4.1** Change `behavioral_score: number`, `head_pose_score: number`, `blink_rate: number` to `number | null` in `AttentionSignalMessage.payload`
- [ ] **4.2** Open PR, add 4-dev review requirement to PR description

### Task 5 — Write / update tests
- [ ] **5.1** Add tests for `NormalizedSignal` optional fields (AC 1)
- [ ] **5.2** Add `_parse_signal` optional-null tests (AC 2, AC 3)
- [ ] **5.3** Add `process_attention_signal` LPUSH-skip tests (AC 4, AC 5)
- [ ] **5.4** Add `assessment/ces.py` redistribution tests (AC 6, AC 7)
- [ ] **5.5** Add `ces_breakdown` ghost-value exclusion test (AC 10)
- [ ] **5.6** Run `pytest apps/api/tests/ -x` and confirm 0 failures

### Task 6 — Verify merge prerequisites
- [ ] **6.1** Confirm S3-42 merged to `main`
- [ ] **6.2** Confirm S3-43 merged to `main`
- [ ] **6.3** Confirm S3-44 merged to `main`
- [ ] **6.4** Confirm `ces-fallback` branch merged to `main` (D16 merge order)
- [ ] **6.5** Rebase this branch on `main` and resolve any conflicts before implementation begins

---

## Scale & Load

### Q1 — What is ONE unit of work, and what is its range?

One unit of work = processing one `attention_signal` WebSocket message for one session.

- **Min:** All five signals present (`quiz_accuracy`, `teachback_score`, `behavioral`, `head_pose`, `blink`). 5 Redis writes (ces_window, tutor_ces, ces_history LPUSH, + 3 MediaPipe history LPUSHes).
- **Typical:** `quiz_accuracy` and `teachback_score` are `None` for most of the lesson (no quiz yet); `behavioral`, `head_pose`, `blink` are present. 5 Redis writes.
- **MediaPipe-absent case (this story):** One or more of `behavioral`, `head_pose`, `blink` are `None`. The LPUSH for that field is skipped. Redis writes: 2 (ces_window, tutor_ces) + 1 (ces_history LPUSH) + only the non-None MediaPipe history writes. Min = 3 writes (all three None), max = 5 writes.
- **Beyond:** No change. The cadence is one signal per 5-second window per active session, regardless of how many signals are `None`. There is no fan-out.

### Q2 — Which budgets are FIXED while the input VARIES — and what happens when input exceeds them?

| Budget | Value | Behaviour when exceeded |
|--------|-------|------------------------|
| `_CES_HISTORY_MAX = 10` (per list) | 10 entries | `LTRIM` enforces the bound after every LPUSH — when a window's signal is `None` and LPUSH is skipped, the list length does not grow. Explicit cap, not silent truncation. |
| `_CES_WINDOW_TTL = 86_400 s` (24 h) | 1 day | Redis TTL auto-expires keys. Sessions lasting >24 h are expected to have ended; stale keys evict automatically. |
| Weight-redistribution divisor | `sum(present weights)` | If ALL five signals are `None`, divisor is 0. The guard `if not present: return 0.0` returns explicitly — no division-by-zero, no silent wrong answer. |

No silent truncation is introduced by this story. The LPUSH guard (AC 4) is an explicit skip, not a covert discard — the skip is determined before the Redis call, so there is no window where data is silently lost.

### Q3 — What is the SCOPE of every limit?

| Limit | Scope |
|-------|-------|
| `_CES_HISTORY_MAX = 10` | Per session (the key is `session:{sid}:*_history`) |
| `_CES_WINDOW_TTL = 86_400 s` | Per session key in Redis |
| Weight-sum guard (`return 0.0` when all None) | Per signal window (stateless computation) |

No cross-session, cross-user, or cross-instance shared limits are introduced. The Redis keys are session-scoped.

### Q4 — Which reads and writes are UNBOUNDED?

No unbounded reads or writes are introduced. Every Redis write in `process_attention_signal`
is either:
- `SET` (bounded by key — one value per session key, O(1))
- `LPUSH` + `LTRIM` bounded to `_CES_HISTORY_MAX = 10` entries
- `EXPIRE` (O(1))

The new `None` guard only reduces writes — it cannot increase them.

No Supabase reads or writes are added by this story.

`# BOUNDED:` comment: The history lists are bounded at 10 entries per session by `LTRIM`; the `None` guard only further reduces the write count.

### Q5 — Which caps were INHERITED from an earlier design, and have they been re-derived?

`_CES_HISTORY_MAX = 10` was set in the original `process_attention_signal` implementation
(Dev 4 sprint 3 baseline). It was sized for the triggering rule: "CES < 50 for 2 consecutive
5-second windows". 10 entries is 5× the required look-back — appropriate headroom.

When MediaPipe signals are `None` for a window, the history list for that signal does NOT
receive an entry. If MediaPipe is permanently unavailable for a session, the history list
stays empty. The `ces_breakdown` computation (S3-42) averages over available entries, so an
empty list produces `None` (not 0.0) in the breakdown — this is correct and must be preserved.

The 10-entry cap does not need re-derivation for this story: the unit of work (one signal
window) is unchanged. The cap now applies to fewer entries on camera-absent sessions, which
is strictly safer.

### Q6 — Is every check-then-act sequence safe under CONCURRENT requests?

The only state modification in the changed code is the Redis LPUSH/LTRIM/EXPIRE trio. Redis
single-command operations are atomic. LPUSH is not conditioned on a prior read, so there is no
TOCTOU gap. The `None` guard is a pure in-process check on `normalized.<field>` — no shared
state is read between the guard and the LPUSH.

The CES computation itself is stateless (pure function). The weight redistribution is computed
from the signal values and settings object, both of which are local to the call.

No check-then-act sequences are added by this story.

---

## Security

### Auth / Ownership

`process_attention_signal` is called from the WebSocket handler (Dev 4), which enforces JWT
authentication before any message is processed. This story adds no new authentication surface.
The session-scoped Redis keys (`session:{sid}:*_history`) are written using the `session_id`
from the parsed `NormalizedSignal.session_id` field, which the caller (WebSocket handler)
validates against the authenticated user's session before invoking
`process_attention_signal`. No change in ownership check.

### Input Validation

The change from `_require_float` to `_optional_float` does not weaken the NaN/±inf guard (AC 3).
A `null` value becomes `None` (safe). A non-null non-finite value still raises `ValueError`.
A non-null non-numeric string still raises `ValueError`. The only newly accepted value is JSON
`null` / Python `None`.

### Frozen Contract

`ws.ts` is a frozen interface contract. The `behavioral_score`, `head_pose_score`, and
`blink_rate` fields are changed from `number` to `number | null`. This is a **loosening** of
the contract (null now accepted), not a breaking change for existing clients that send numeric
values. A 4-dev PR sign-off is required before merge (CLAUDE.md §16).

### No New Attack Surface

This story adds no new endpoints, no new DB tables, no new Redis key namespaces, and no new
LLM calls. The attack surface is unchanged.

---

## Test Requirements

The following test names must exist and pass at merge time. File paths are recommendations;
the CI requirement is that the test exists somewhere in `apps/api/tests/`.

### `test_normalized_signal_optional_mediapipe.py` (new file) — or added to existing `test_tutor_service.py`

| Test name | AC |
|-----------|----|
| `test_normalized_signal_fields_are_optional` | AC 1 |
| `test_parse_signal_null_behavioral_score_accepted` | AC 2 |
| `test_parse_signal_null_head_pose_accepted` | AC 2 |
| `test_parse_signal_null_blink_rate_accepted` | AC 2 |
| `test_parse_signal_all_three_null_accepted` | AC 2 |
| `test_parse_signal_missing_behavioral_score_accepted` | AC 2 |
| `test_parse_signal_nan_behavioral_raises` | AC 3 |
| `test_parse_signal_inf_head_pose_raises` | AC 3 |
| `test_process_signal_none_behavioral_skips_lpush` | AC 4 |
| `test_process_signal_none_head_pose_skips_lpush` | AC 4 |
| `test_process_signal_none_blink_skips_lpush` | AC 4 |
| `test_process_signal_all_none_no_lpush_for_mediapipe_keys` | AC 4 |
| `test_process_signal_all_mediapipe_none_returns_ces_result` | AC 5 |
| `test_tutor_compute_ces_with_none_behavioral_redistributes` | AC 9 |

### Added to `test_ces.py` (or `test_ces_optional_signals.py`)

| Test name | AC |
|-----------|----|
| `test_ces_behavioral_none_redistributes_weight` | AC 6 |
| `test_ces_head_pose_none_redistributes_weight` | AC 6 |
| `test_ces_blink_none_redistributes_weight` | AC 6 |
| `test_ces_all_mediapipe_none_uses_quiz_and_teachback_only` | AC 6 |
| `test_ces_all_signals_none_returns_zero` | AC 6 |
| `test_ces_behavioral_none_weight_sum_still_normalised` | AC 6 |

### Regression — existing tests must remain GREEN

| Scope | Command |
|-------|---------|
| All existing CES tests | `pytest apps/api/tests/ -k ces -x` exits 0 (AC 7) |
| Full Dev 3 + Dev 4 test suite | `pytest apps/api/tests/ -x` exits 0 |

### `test_ces_breakdown_optional_signals.py` (new, depends on S3-42 fixtures)

| Test name | AC |
|-----------|----|
| `test_ces_breakdown_excludes_none_windows` | AC 10 |

---

## Migration

**NO migration required.** This story changes:
- Python dataclass field types (`NormalizedSignal`)
- Python function signatures (`_parse_signal`, `compute_ces`)
- Redis write guards (skip LPUSH for `None`)
- TypeScript type (frozen contract update)

No new DB tables, columns, or migrations are introduced.

---

## Decision References

| Decision | What this story implements |
|----------|---------------------------|
| **D5** | `NormalizedSignal.behavioral_score / head_pose_score / blink_rate: float | None`; `_parse_signal` uses `_optional_float`; LPUSH skipped when `None` |
| **D16** | Branch merge order: S3-42 → main, S3-43 → main, S3-44 → main, `ces-fallback` → main before this story is implemented |

---

## Dependencies

| Story | Why required |
|-------|-------------|
| **S3-42** | Adds `ces_breakdown` to session report using Redis history lists; AC 10 tests must pass against S3-42's breakdown logic |
| **S3-43** | Part of `ces-fallback` merge order (D16); must be on `main` before this story's branch is based |
| **S3-44** | Part of `ces-fallback` merge order (D16); must be on `main` before this story's branch is based |

The `ces-fallback` branch (which includes S3-34 through S3-44 fixes) must be fully merged to
`main` (D16) before implementation begins. Implementation on a stale branch would produce
merge conflicts with `assessment/ces.py` changes from S3-42.

---

## Dev Notes

### Files to modify — exactly 3 (plus ws.ts under 4-dev PR)

| File | Change |
|------|--------|
| `apps/api/app/modules/tutor/service.py` | `NormalizedSignal` field types; `_parse_signal` switch to `_optional_float`; LPUSH guards in `process_attention_signal` |
| `apps/api/app/modules/assessment/ces.py` | `compute_ces` signature + generalised weight redistribution |
| `packages/shared/types/ws.ts` | `AttentionSignalMessage` payload fields (frozen contract, 4-dev review) |

### `compute_ces` redistribution — reference implementation pattern

```python
# Generalised redistribution — handles any combination of None signals
pairs = [
    (quiz_accuracy, settings.ces_weight_quiz),
    (teachback_score, settings.ces_weight_teachback),
    (behavioral, settings.ces_weight_behavioral),
    (head_pose, settings.ces_weight_head_pose),
    (blink, settings.ces_weight_blink),
]
# Clamp non-None values to [0, 1]
clamped = [(min(1.0, max(0.0, v)), w) for (v, w) in pairs if v is not None]
if not clamped:
    return 0.0
weight_sum = sum(w for _, w in clamped)
raw = sum(v * (w / weight_sum) for v, w in clamped)
return min(100.0, round(raw * 100, 4))
```

Note: `quiz_accuracy=None` was previously treated as `0.0` with full weight retained (per
existing docstring). Under the generalised redistribution it would be redistributed instead.
**Preserve the existing behaviour for `quiz_accuracy=None`**: treat it as `0.0` (not absent)
by converting `None → 0.0` before building the pairs list, or by documenting this intentional
difference if the behaviour is changed. See existing `ces.py` docstring for the rationale.

### Why `quiz_accuracy=None` is different from MediaPipe `None`

Per the existing `compute_ces` docstring: `quiz_accuracy=None` is a transient "no quiz
submitted yet" state — the student has not yet reached a quiz checkpoint. Treating it as `0.0`
is intentional (the student has not demonstrated any quiz accuracy). MediaPipe `None` means
"signal unavailable" — the student's attention is unknown, not zero. These are semantically
different and the redistribution logic must reflect that distinction.

If the team decides to unify the treatment, that is a separate decision and must be registered
before implementation.

---

## Senior Developer Review (AI)

_To be completed after implementation._

---

## Dev Agent Record

| Date | Author | Note |
|------|--------|------|
| 2026-08-12 | Dev 3 (tannmayygupta) | Story created — story-first gate before implementation |
