# Story 3-38 — NormalizedSignal Optional Fields (DEFER-003)

**Sprint:** Sprint 3 (CES v2 hardening)
**Dev:** Dev 3 (parsing logic) + Dev 4 (NormalizedSignal dataclass ownership)
**Status:** ready-for-dev
**Branch:** `sprint3/s3-38-normalizedsignal-optional-fields`
**Depends on:** Story 3-34 (canonical ces.py already accepts Optional for all 5 signals)
**Blocks:** Story 3-39 (MediaPipe failure protocol requires None-able fields)

---

## Background

`NormalizedSignal` in `apps/api/app/modules/tutor/service.py:37-40` types three MediaPipe-
derived fields as plain `float` (not `Optional[float]`):

```python
behavioral_score: float
head_pose_score: float
blink_rate: float
```

`_parse_signal()` (same file) calls `_require_float()` for these three fields, which raises
`ValueError` if a field is absent or non-finite in the WebSocket message payload. This means:

- If MediaPipe tracking is unavailable (camera off, initialization failed, WASM load error),
  the three fields are absent from the incoming JSON.
- `_parse_signal` raises `ValueError` before the CES computation is reached.
- `compute_ces` in `assessment/ces.py` never sees `behavioral=None`, `head_pose=None`,
  `blink=None` from the WebSocket path — the None-redistribution paths in `ces.py` are
  unreachable from production traffic (confirmed by DEFER-003 in `docs/deferred-work.md`).

Story 3-34 made `compute_ces` accept all five signals as `Optional[float]` in
forward-compatibility for this story. This story completes the integration by updating the
upstream parsing layer.

`quiz_accuracy` and `teachback_score` are STILL required via `_require_float()` when present:
a submitted quiz score or teach-back score cannot legitimately be absent — if the field
appears in the payload, it must be a valid number.

### Defect Record (DEFER-003)

| ID | Description | Status |
|----|-------------|--------|
| DEFER-003 | `behavioral_score`, `head_pose_score`, `blink_rate` typed `float` — None-redistribution unreachable | Trigger: S3-38 |

---

## Acceptance Criteria

### AC 1 — NormalizedSignal fields updated to Optional
`NormalizedSignal.behavioral_score`, `NormalizedSignal.head_pose_score`, and
`NormalizedSignal.blink_rate` are typed as `float | None` (or `Optional[float]`).
`quiz_accuracy` and `teachback_score` remain `float | None` as they already are (or if not,
update them to match).

### AC 2 — _parse_signal uses _optional_float for MediaPipe fields
`_parse_signal()` uses `_optional_float()` (or equivalent) for the three MediaPipe fields,
returning `None` when the key is absent from the payload or when the value is `null`.
It continues to use `_require_float()` for `quiz_accuracy` and `teachback_score` — these
fields must be valid floats when present (absent fields at the JSON level return `None` as
for MediaPipe fields, but a key present with a non-float value still raises).

### AC 3 — NaN still rejected upstream
`_parse_signal` (or its helper) continues to reject `NaN` and `±inf` values with
`ValueError`, consistent with CES p-A behavior. The distinction is:
- Key absent from JSON → `None` (signal not measured)
- Key present, value = `NaN` → `ValueError` (corrupt signal)

### AC 4 — compute_ces receives None for absent MediaPipe signals
When a WebSocket `AttentionSignalMessage` arrives without `behavioral_score`, `head_pose_score`,
and `blink_rate` (e.g., MediaPipe not yet initialized), `_parse_signal` returns a
`NormalizedSignal` with those three fields as `None`, and `compute_ces` receives `behavioral=None`,
`head_pose=None`, `blink=None` — triggering the proportional redistribution to the academic
signals.

### AC 5 — All existing tutor service tests pass
No regressions in `apps/api/tests/test_tutor_service.py` or any test that exercises
`_parse_signal`, `NormalizedSignal`, or `compute_ces` via the WebSocket path.

### AC 6 — No ruff errors

### AC 7 — Unit tests: 15 minimum
At minimum 15 unit tests: MediaPipe fields absent → NormalizedSignal fields are None (AC 4),
MediaPipe fields present → float (AC 1), NaN value → ValueError (AC 3), null JSON value →
None (AC 2), quiz_accuracy absent → None (consistent with Optional), quiz_accuracy = NaN →
ValueError, compute_ces redistribution path reached when behavioral=None (end-to-end AC 4
test through the full signal path).

---

## Tasks / Subtasks

- [ ] **T1** Write RED tests
- [ ] **T2** Coordinate with Dev 4: update `NormalizedSignal` dataclass to `float | None` for the 3 fields
- [ ] **T3** Add `_optional_float()` helper or update existing parse helpers in `tutor/service.py`
- [ ] **T4** Update `_parse_signal()` to use optional parsing for the 3 MediaPipe fields
- [ ] **T5** Verify end-to-end path: absent MediaPipe fields → NormalizedSignal None → compute_ces redistribution (unit test)
- [ ] **T6** Run `ruff check` + `pytest -m unit` — all pass
- [ ] **T7** 6-agent adversarial code review

---

## Scale & Load

**Q1 — Unit of work and range:**
One `_parse_signal` call per 5-second WebSocket message per active session. O(1) per call.
Approximately 12 calls per minute per session; at 100 concurrent sessions = 1,200 parses/min.
All in-memory, no I/O.

**Q2 — Fixed budgets vs variable input:**
Parse is stateless and O(1). No budgets affected. Optional typing removes the `ValueError`
hard-fail on absent MediaPipe fields — this is a relaxation, not a tightening.

**Q3 — Scope of every limit:**
Per-message, stateless. No per-user or per-deployment scope.

**Q4 — Unbounded reads/writes:**
None. Pure in-memory parsing.

**Q5 — Inherited caps re-derived:**
The `_require_float()` assumption for all 3 MediaPipe fields was inherited from CES v1 when
MediaPipe was assumed always available. Re-derived for S3-39: camera failure is a first-class
scenario; the 3 fields may legitimately be absent for extended periods (WASM init failure,
browser permission denied). The academic signals (`quiz_accuracy`, `teachback_score`) are
submitted only when a quiz or teach-back completes — they are never continuously present,
but when present they must be valid floats (a score of "undefined" has no meaning).

**Q6 — Check-then-act under concurrency:**
Fully stateless parse; concurrent calls are safe. No shared mutable state.

---

## Definition of Done

- [ ] Story file committed before any implementation code
- [ ] RED tests written and confirmed failing before implementation
- [ ] Implementation makes all tests GREEN (minimum 15 unit tests)
- [ ] Ruff: 0 errors in modified files
- [ ] 6-agent adversarial code review passed
- [ ] DEFER-003 in `docs/deferred-work.md` removed (trigger condition met)
- [ ] `docs/dev3-assessment-tracker.md` updated
- [ ] PR merged to main

---

## Dev Notes

### _optional_float helper pattern

```python
def _optional_float(payload: dict, key: str) -> float | None:
    """Return float from payload[key] or None if key absent or value is None/null.

    Raises ValueError if key is present but value is NaN or ±inf.
    """
    val = payload.get(key)
    if val is None:
        return None
    f = float(val)
    if not math.isfinite(f):
        raise ValueError(f"Signal {key!r} must be finite; got {f!r}")
    return f
```

### NormalizedSignal update (Dev 4 ownership)

```python
@dataclass
class NormalizedSignal:
    quiz_accuracy: float | None
    teachback_score: float | None
    behavioral_score: float | None   # was: float
    head_pose_score: float | None    # was: float
    blink_rate: float | None         # was: float
```

### _parse_signal update

```python
def _parse_signal(payload: dict) -> NormalizedSignal:
    return NormalizedSignal(
        quiz_accuracy=_optional_float(payload, "quiz_accuracy"),
        teachback_score=_optional_float(payload, "teachback_score"),
        behavioral_score=_optional_float(payload, "behavioral_score"),  # changed
        head_pose_score=_optional_float(payload, "head_pose_score"),    # changed
        blink_rate=_optional_float(payload, "blink_rate"),              # changed
    )
```

### Files to modify

- `apps/api/app/modules/tutor/service.py` — Dev 4 owns dataclass; Dev 3 updates parse helpers
- `apps/api/tests/test_normalizedsignal_optional.py` — new test file
