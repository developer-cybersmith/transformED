---
id: "S3-49"
title: "JSON timestamps in ces_history {v:float, t:int} and gap-check on trigger to prevent stale-history interventions (D4)"
status: "Draft"
sprint: 3
story_points: 3
owner: Dev3
priority: P1
decisions: D4
depends_on: ["S3-35"]
branch: "sprint3/s3-49-ces-history-timestamps"
migration: "NO"
---

# Story S3-49 -- JSON Timestamps in ces_history {v:float, t:int} and Gap-Check on Trigger to Prevent Stale-History Interventions (D4)

## Context

**Decision D4:** Store `session:{session_id}:ces_history` entries as JSON `{"v": float, "t": int}`
where `v` is the CES value and `t` is a Unix timestamp in integer seconds. Before firing the
distraction intervention trigger, check `abs(t[0] - t[1]) <= 2 * settings.ces_cadence_seconds`
(default: 10 s at 5 s cadence) on the two most-recent entries.

**Problem being solved:** The existing `ces_history` stores bare CES floats via
`lpush(history_key, ces)`. The intervention trigger reads the two most-recent entries and fires
if both fall below `settings.ces_threshold`. However, if a student's MediaPipe signals are
interrupted (tab switch, brief network pause, or MediaPipe restart), the history list retains
stale CES values from before the gap. When signals resume, the very first new value is compared
to a stale value from potentially minutes earlier -- a temporal mismatch that can trigger a false
distraction intervention in a session where engagement is actually improving.

**Example failure scenario (without D4):** Student pauses 30 s (MediaPipe stops). `ces_history`
retains `[48.0, 47.5]` (both below threshold). Student resumes. Next signal is 45.0 (legitimately
distracted), trigger sees `[45.0, 48.0]` where 48.0 is from 35 seconds ago, not 5 seconds ago.
D4 gates the trigger on a timestamp proximity check: if the two most-recent entries are more than
`2 * cadence` seconds apart, the trigger does not fire regardless of CES values.

**Scope:** Only `ces_history` is affected. The per-signal breakdown lists
(`behavioral_history`, `head_pose_history`, `blink_history`) introduced by S3-42 are used
only for the session report `ces_breakdown` computation, not the real-time trigger.
Those lists are not changed by this story.

**Dependency on S3-35:** `compute_ces_from_session_aggregates` is defined by S3-35 in
`apps/api/app/modules/assessment/service.py`. It reads `ces_history` and converts entries to
floats via `float(entry)`. After D4, entries are JSON strings; `float('{"v": 48.0, "t": 1720}')`
raises `ValueError`. S3-35 must be merged before S3-49 is implemented so that
`compute_ces_from_session_aggregates` can be updated in this story.

## User Story

**As a** student in an active lesson,
**I want** distraction interventions to fire only when two consecutive real-time attention
windows both show low engagement,
**so that** I am not interrupted by a false-positive intervention caused by a stale CES value
from before a brief signal gap.

**As the system** processing CES attention signals,
**I want** each `ces_history` entry to carry a Unix timestamp alongside the CES value,
and to verify that the two most-recent entries are temporally adjacent before firing an
intervention,
**so that** the trigger is accurate across signal gaps, reconnections, and MediaPipe restarts --
never firing on a comparison between the present and the past.

## Acceptance Criteria

### AC 1 -- ces_history entries written as JSON {"v": float, "t": int}

After each call to `process_attention_signal`, the value pushed to
`session:{session_id}:ces_history` via `lpush` is a JSON-encoded string of the form
`{"v": <CES float>, "t": <Unix seconds int>}` -- not a bare float string.

**Exact assertion:** Mock `redis.lpush` and call `process_attention_signal("sess-001", signal)`
with `behavioral_score=0.8, head_pose_score=0.7, blink_rate=0.6`. Capture the value passed
to `lpush` for the `ces_history` key. Parse it as `json.loads(captured)`. Assert:
- `isinstance(parsed["v"], float)` is True
- `isinstance(parsed["t"], int)` is True
- `abs(parsed["t"] - int(time.time())) <= 2` (timestamp within 2 s of now)
- `0.0 <= parsed["v"] <= 100.0` (valid CES range)

**Source guard:** `inspect.getsource(process_attention_signal)` contains the string `json.dumps`
and the pattern `"v":` in the history write block. The string `lpush(history_key, ces)`
(bare float write) does NOT appear in the source.

### AC 2 -- ces_cadence_seconds env var added to Settings in config.py

`Settings` in `apps/api/app/config.py` declares:
```python
ces_cadence_seconds: int = Field(default=5, gt=0)
```
The env var name is `CES_CADENCE_SECONDS`. The default is `5` (matching CLAUDE.md section 11:
"CES computed per 5s window").

**Exact assertions:**
- `get_settings().ces_cadence_seconds == 5` when `CES_CADENCE_SECONDS` is not set in the
  environment.
- `Field(default=5, gt=0)` constraint rejects `CES_CADENCE_SECONDS=0` with a `ValidationError`
  (cadence of zero makes `2 * cadence = 0`, blocking all interventions via the gap check).
- `inspect.getsource(Settings)` contains the string `ces_cadence_seconds`.

### AC 3 -- Intervention trigger applies gap-check: gap must be <= 2 * ces_cadence_seconds

Before the existing CES threshold check (`all(v < settings.ces_threshold ...)`), the trigger
parses the two most-recent `ces_history` entries as JSON and evaluates:

```
abs(t0 - t1) <= 2 * settings.ces_cadence_seconds
```

where `t0` is the timestamp in `history_raw[0]` (most recent) and `t1` is the timestamp in
`history_raw[1]` (second most recent). If the gap exceeds `2 * ces_cadence_seconds`, the
intervention trigger does NOT fire -- even if both `v` values are below `settings.ces_threshold`.

**Exact assertion (gap fails -- no intervention):**
Configure `ces_cadence_seconds=5` (tolerance=10 s). Inject mock `ces_history` containing:
- `history_raw[0] = '{"v": 40.0, "t": 1720000015}'`
- `history_raw[1] = '{"v": 42.0, "t": 1720000000}'`

Gap = 15s > 10s. Both v values (40.0, 42.0) below threshold (50.0). Tutor state = TEACHING.
No cooldown. Assert: `dispatch_event` NOT called. `intervention_dispatched` is `False`.

**Exact assertion (gap passes -- intervention fires):**
Same setup with:
- `history_raw[0] = '{"v": 40.0, "t": 1720000008}'`
- `history_raw[1] = '{"v": 42.0, "t": 1720000000}'`

Gap = 8s <= 10s. Both v values below threshold. Tutor state = TEACHING. No cooldown.
Assert: `dispatch_event` IS called with event `"distraction_detected"`.
`intervention_dispatched` is `True`.

### AC 4 -- Trigger parses JSON entries; non-JSON entries are skipped (fail-safe)

When a `ces_history` entry cannot be parsed as JSON (e.g., a bare float string `"48.5"` left
by pre-D4 code), the entry is treated as having `t = 0` and `v = float(entry)` if float
conversion succeeds, or skipped entirely if both JSON parse and float conversion fail.

The practical effect: a legacy entry always produces `t = 0`, so
`abs(t_new - 0) = t_new` which equals current Unix time (~1.7e9 s) and vastly exceeds
`2 * cadence`. The gap check fails safely -- the intervention does not fire based on a
comparison between a timestamped new entry and an untimestamped legacy entry.

**Exact assertion:** Inject mock `ces_history` where `history_raw[0]` is valid JSON
`'{"v": 40.0, "t": 1720000000}'` and `history_raw[1]` is legacy bare float `"42.0"`.
Assert: `dispatch_event` NOT called (legacy entry has `t=0`, gap check fails).
Assert: no exception raised; function returns a `CesResult`.

### AC 5 -- compute_ces_from_session_aggregates parses JSON entries to extract v

The function `compute_ces_from_session_aggregates(session_id, redis, settings)` from S3-35
(`apps/api/app/modules/assessment/service.py`) must be updated in this story to handle the
new JSON entry format. The parsing loop changes from `float(entry)` to:

```python
for entry in raw_entries:
    try:
        parsed = json.loads(entry)
        v = float(parsed["v"])
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        try:
            v = float(entry)  # backward compat: legacy bare float
        except (ValueError, TypeError):
            continue  # skip fully corrupt entry
    windows.append(v)
```

**Exact assertion:** Call `compute_ces_from_session_aggregates("sess-001", mock_redis, settings)`
where `redis.lrange` returns:
```python
['{"v": 50.0, "t": 1720000000}', '{"v": 60.0, "t": 1719999995}', 'not_a_number',
 '{"v": 70.0, "t": 1719999990}', '{"v": 80.0, "t": 1719999985}', '{"v": 45.0, "t": 1719999980}']
```
The corrupt entry `'not_a_number'` is skipped. 5 valid entries remain (>= 5 threshold from
S3-35 AC3). Assert: return value == `round(statistics.mean([50.0, 60.0, 70.0, 80.0, 45.0]), 2)` == `61.0`.

### AC 6 -- Trigger source does not contain legacy bare-float parse pattern

After implementation, `inspect.getsource(process_attention_signal)` does NOT contain:
```
float(v) for v in history_raw[:2]
```
This CI guard prevents re-introduction of the pre-D4 float-parse pattern, which would silently
skip the timestamp gap check on every trigger evaluation.

**Exact assertion:** `'float(v) for v in history_raw[:2]'` not in
`inspect.getsource(process_attention_signal)`.

## Tasks / Subtasks

### Task 1 -- Story file (story-first gate)
- [x] 1.1 Create `docs/stories/S3-49-json-timestamps-in-ces-history-v-float-t.md`
- [ ] 1.2 Commit story-only to `sprint3/s3-49-ces-history-timestamps`
- [ ] 1.3 Push to remote before any implementation

### Task 2 -- RED phase (failing tests)
- [ ] 2.1 Create `apps/api/tests/test_s3_49_ces_history_timestamps.py`
- [ ] 2.2 `test_ces_history_write_is_json_not_bare_float` -- AC 1 source guard
- [ ] 2.3 `test_ces_history_lpush_value_is_valid_json` -- AC 1 runtime (mocked Redis)
- [ ] 2.4 `test_ces_history_json_has_v_float_and_t_int` -- AC 1 runtime type assertions
- [ ] 2.5 `test_ces_cadence_seconds_in_settings` -- AC 2 source/settings inspection
- [ ] 2.6 `test_ces_cadence_seconds_default_is_5` -- AC 2 value assertion
- [ ] 2.7 `test_gap_check_blocks_intervention_when_timestamps_too_far_apart` -- AC 3 fail
- [ ] 2.8 `test_gap_check_allows_intervention_when_timestamps_within_tolerance` -- AC 3 pass
- [ ] 2.9 `test_legacy_bare_float_entry_does_not_trigger_intervention` -- AC 4
- [ ] 2.10 `test_legacy_entry_does_not_raise_exception` -- AC 4
- [ ] 2.11 `test_compute_ces_aggregates_parses_json_entries` -- AC 5
- [ ] 2.12 `test_compute_ces_aggregates_skips_non_json_and_non_float_entries` -- AC 5
- [ ] 2.13 `test_legacy_float_pattern_not_in_process_attention_signal_source` -- AC 6 CI guard
- [ ] 2.14 Confirm all 13 tests FAIL before implementation

### Task 3 -- GREEN phase (implementation)
- [ ] 3.1 `apps/api/app/config.py`: add `ces_cadence_seconds: int = Field(default=5, gt=0)`
- [ ] 3.2 `apps/api/app/modules/tutor/service.py`:
        - Change `lpush(history_key, ces)` to `lpush(history_key, json.dumps({"v": ces, "t": int(_time.time())}))`
        - Update trigger read block: parse JSON, extract v and t, apply gap check before threshold check, apply backward-compat fallback for non-JSON entries
- [ ] 3.3 `apps/api/app/modules/assessment/service.py`:
        - Update `compute_ces_from_session_aggregates` entry-parsing loop for JSON with backward-compat fallback
- [ ] 3.4 Confirm all 13 tests PASS

### Task 4 -- REFACTOR pass
- [ ] 4.1 `ruff check` on modified files -- zero errors
- [ ] 4.2 `ruff format --check` on modified files -- zero violations
- [ ] 4.3 Full Dev 3 regression suite GREEN (`pytest apps/api/tests/ -m unit`)
- [ ] 4.4 Confirm S3-42 and S3-35 regression tests still pass (no regressions)

### Task 5 -- 6-agent adversarial review
- [ ] 5.1 Layer 1 -- Story Quality
- [ ] 5.2 Layer 2 -- Blind Hunter (Security)
- [ ] 5.3 Layer 3 -- Test Coverage
- [ ] 5.4 Layer 4 -- AC Completeness
- [ ] 5.5 Layer 5 -- Process Integrity
- [ ] 5.6 Layer 6 -- Scale & Load

### Task 6 -- Commit + push
- [ ] 6.1 Final implementation commit on `sprint3/s3-49-ces-history-timestamps`
- [ ] 6.2 Push to remote
- [ ] 6.3 Update `docs/dev3-assessment-tracker.md`

## Scale & Load

### Q1 -- What is ONE unit of work, and what is its range?

One unit = one `process_attention_signal` call: serialize one JSON string (<= 40 bytes), push to
`ces_history`, read at most 2 entries, run one integer subtraction and one comparison.

**Min:** 0 calls/session (session never enters TEACHING). History empty.
**Typical:** ~360 calls for a 30-minute lesson (5s cadence, 1800s/5 = 360 windows). Gap check
runs 358 times (requires >= 2 history entries).
**Largest measured:** ~720 calls for a 60-minute session.
**Beyond the bound:** `_CES_HISTORY_MAX = 10` (inherited from S3-34) caps the list. Each entry
is now <= 40 bytes; total per key <= 400 bytes (up from <= 80 bytes for bare floats).
`lrange(0, -1)` in `compute_ces_from_session_aggregates` still reads at most 10 entries.

### Q2 -- Which budgets are FIXED while the input VARIES -- and what happens past them?

| Budget | Value | Past the limit |
|--------|-------|----------------|
| `ces_history` list length | `_CES_HISTORY_MAX = 10` entries (inherited, S3-34) | `ltrim` enforces: 11th entry pushes oldest off. Max 10 entries always. |
| JSON entry size | <= ~40 bytes (`{"v": 100.00, "t": 9999999999}`) | Fixed: CES clamped [0,100] 2dp; Unix timestamp 10 digits through 2286. Neither varies with input. |
| Gap-check tolerance | `2 * settings.ces_cadence_seconds` (default 10s) | Gap > 10s: trigger does not fire. Explicit non-firing -- not silent truncation. Session continues without intervention. |
| Redis TTL | `_CES_WINDOW_TTL = 86400` s (inherited, S3-34) | After 24h, `lrange` returns `[]`. Finalization returns `None` (< 5 windows). Trigger skips gap check safely. |

No silent truncation introduced: gap-check failure is an explicit non-action, not a hidden
behavior. A stale entry skipped by gap check produces the same observable result as no entry.

### Q3 -- What is the SCOPE of every limit?

| Limit | Scope | Justification |
|-------|-------|---------------|
| `_CES_HISTORY_MAX = 10` | Per session (`session:{sid}:ces_history`) | Each session key isolated. Concurrent sessions share no list state. |
| `ces_cadence_seconds = 5` (default) | Per deployment (env var) | One cadence for all sessions on all replicas. Changing `CES_CADENCE_SECONDS` affects all sessions on next restart. |
| Gap-check tolerance (2 * cadence = 10s) | Per trigger evaluation | Derived from env var at call time. No session-level state held for this value. |
| Redis memory per key | <= 400 bytes per `ces_history` key | Per session. 1,000 concurrent sessions: <= 400 KB total for all `ces_history` keys -- negligible. |

### Q4 -- Which reads and writes are UNBOUNDED?

None introduced by this story.

**Writes:** `json.dumps` + `lpush` + `ltrim` + `expire` -- four atomic Redis ops. `ltrim`
enforces 10-entry cap. Output size bounded (<= 40 bytes/entry, <= 10 entries).

**Reads (trigger path):** `lrange(history_key, 0, _CES_HISTORY_MAX - 1)` reads at most 10
entries. Gap check reads only `history_raw[:2]` -- exactly 2 entries maximum.
`# BOUNDED: ltrim cap of _CES_HISTORY_MAX=10 applied at write time` comment required on the
`lrange` call in `process_attention_signal`.

**Reads (finalization path):** `lrange(key, 0, -1)` in `compute_ces_from_session_aggregates`
reads all entries. Still bounded by same `ltrim` cap. No change from S3-35.

**Existing DB reads in `get_session_report`:** not changed by this story.

### Q5 -- Which caps were INHERITED from an earlier design, and have they been re-derived?

`_CES_HISTORY_MAX = 10` and `_CES_WINDOW_TTL = 86400` were established in S3-34 for the
real-time CES trigger. S3-49 inherits both for the JSON-format `ces_history` entries.

**Re-derivation for `_CES_HISTORY_MAX`:** Previously each entry was a bare float (~8 bytes).
After D4, each entry <= 40 bytes. The cap of 10 remains valid: 10 x 40 bytes = 400 bytes per
key -- negligible increase with no behavioral consequence. The semantics of "last 10 windows"
still represent the last 50 s of engagement (10 x 5 s cadence), sufficient for both the trigger
and the finalization mean.

**`ces_cadence_seconds = 5` (new constant, no prior value):** Derived from CLAUDE.md section 11:
"CES computed per 5s window". The gap tolerance `2 * cadence = 10 s` allows one full window to
be missed (common during brief reads or MediaPipe freezes) before declaring history stale.
A single missed window doubles the gap from 5s to 10s; two consecutive missed windows produce
15s gap (> 10s tolerance), correctly identifying a multi-window interruption as a signal gap.

### Q6 -- Is every check-then-act sequence safe under CONCURRENT requests?

No new check-then-act sequences introduced by this story.

The gap check (`abs(t0 - t1) <= 2 * cadence`) is a pure in-process computation on two values
already read from Redis. It does not write to Redis or DB and does not gate a subsequent write.

The subsequent `dispatch_event` call is the same check-then-act as pre-D4. Concurrent
`process_attention_signal` calls for the same session can both evaluate the gap check
simultaneously and both dispatch `distraction_detected`. This is the same race condition as
pre-D4 -- no change in risk. The existing cooldown key `tutor_cooldown:{session_id}` is the
guard; the gap check does not affect its atomicity properties.

Two concurrent `lpush` calls for the same `ces_history` key are atomic (Redis guarantees).
`ltrim` after each `lpush` is also atomic. Two concurrent trims to length 10 produce the same
result regardless of ordering.

## Security

### Authentication and ownership

`process_attention_signal` is called from the WebSocket handler after session validation.
`session_id` is validated against UUID format by `_SESSION_ID_RE` in `websocket.py` before any
Redis operation. S3-49 introduces no new session-id usage.

`compute_ces_from_session_aggregates` is called from `finalize_session` (server-side, triggered
by session lifecycle events) and from `get_session_report` (JWT-protected endpoint with SEC-006
ownership guard). Neither call path accepts `session_id` from unauthenticated input.

### JSON parsing safety

`json.loads(entry)` is called on values read from Redis -- values written by server-side code in
`process_attention_signal`. Redis is a trusted internal store. However, the parser is defended
against corrupt Redis entries:
- `json.loads` raises `json.JSONDecodeError` for non-JSON input -- caught.
- `parsed["v"]` raises `KeyError` if `"v"` is absent -- caught.
- `float(parsed["v"])` raises `ValueError`/`TypeError` for non-numeric values -- caught.
- `float(parsed["t"])` raises `ValueError`/`TypeError` for non-numeric timestamps -- caught.

All four exceptions are handled in the backward-compat fallback. No path allows a corrupt Redis
entry to cause an uncaught exception in the hot signal-processing path.

### No new attack surface

No new HTTP endpoints. No new DB tables. No new migrations. Existing `ces_history` Redis key
namespace unchanged. JSON format increases per-entry size from ~8 bytes to <= 40 bytes --
not a meaningful DoS surface given the 10-entry `ltrim` bound and 400-byte ceiling per key.

### Information disclosure

Timestamp `t` is Unix seconds -- no PII, session content, or student-identifiable information
beyond the session ID already scoping the key. The `ces_breakdown` values in `get_session_report`
are not changed by D4 (they come from per-signal histories from S3-42, not from `ces_history`).

## Test Requirements

All tests in `apps/api/tests/test_s3_49_ces_history_timestamps.py`, all `@pytest.mark.unit`
(no real Redis, no real DB, no real network).

| Test name | AC | Type | What it verifies |
|-----------|-----|------|-----------------|
| `test_ces_history_write_is_json_not_bare_float` | AC 1 | Source inspection | `json.dumps` present; bare `lpush(history_key, ces)` absent |
| `test_ces_history_lpush_value_is_valid_json` | AC 1 | Runtime (mocked Redis) | Captured `lpush` arg parseable by `json.loads` |
| `test_ces_history_json_has_v_float_and_t_int` | AC 1 | Runtime (mocked Redis) | Parsed entry has `isinstance(v, float)` and `isinstance(t, int)` |
| `test_ces_cadence_seconds_in_settings` | AC 2 | Source inspection | `ces_cadence_seconds` in `Settings` source |
| `test_ces_cadence_seconds_default_is_5` | AC 2 | Runtime | `get_settings().ces_cadence_seconds == 5` when env var unset |
| `test_gap_check_blocks_intervention_when_timestamps_too_far_apart` | AC 3 | Runtime | Gap=15s > 10s; below threshold; TEACHING; no cooldown -- NOT dispatched |
| `test_gap_check_allows_intervention_when_timestamps_within_tolerance` | AC 3 | Runtime | Gap=8s <= 10s; below threshold; TEACHING; no cooldown -- dispatched |
| `test_legacy_bare_float_entry_does_not_trigger_intervention` | AC 4 | Runtime | Legacy `"42.0"` entry has t=0; gap fails; no intervention |
| `test_legacy_entry_does_not_raise_exception` | AC 4 | Runtime | Mixed JSON + legacy entries -- returns `CesResult`, no exception |
| `test_compute_ces_aggregates_parses_json_entries` | AC 5 | Runtime | 5 JSON entries -- mean of `v` values returned correctly |
| `test_compute_ces_aggregates_skips_non_json_and_non_float_entries` | AC 5 | Runtime | `'not_a_number'` skipped; 5 valid entries -- correct mean |
| `test_compute_ces_aggregates_backward_compat_bare_float` | AC 5 | Runtime | Mix of JSON + legacy bare-float entries -- both parsed; correct mean |
| `test_legacy_float_pattern_not_in_process_attention_signal_source` | AC 6 | Source inspection CI guard | `'float(v) for v in history_raw[:2]'` not in source |

**Regression tests (must remain GREEN, no changes to these files required):**
- `apps/api/tests/test_s3_42_ces_breakdown_accuracy.py` -- S3-42 per-signal history tests
  (write to `behavioral_history`, `head_pose_history`, `blink_history` -- not affected by D4)
- `apps/api/tests/test_session_finalization.py` -- S3-35 tests; existing test data (raw floats)
  must still parse via backward-compat fallback so tests remain GREEN without modification

## Decision References

| Decision | Description | This story |
|----------|-------------|------------|
| D4 | Store `ces_history` as JSON `{"v": float, "t": int}`; check `abs(t[0]-t[1]) <= 2*cadence` in trigger | Fully implemented: JSON write in `process_attention_signal`, gap-check in trigger, JSON parse in `compute_ces_from_session_aggregates`, `ces_cadence_seconds` env var in `config.py` |

## Dependencies

**S3-35** (must be merged first, per D16): Defines `compute_ces_from_session_aggregates`
in `apps/api/app/modules/assessment/service.py`. S3-49 must update that function to parse the
new JSON entry format; the function must exist before S3-49 can update it.

**S3-42** (already merged as of 2026-08-12): Established the per-signal history lists
(`behavioral_history`, `head_pose_history`, `blink_history`). S3-49 does NOT modify those
lists. D4 does not require timestamp serialization for the per-signal breakdown lists.

## Migration

**NO** -- This story modifies Redis write/read behaviour and adds one env var to `config.py`.
No new Supabase tables, columns, or constraints. `supabase/migrations/` is unchanged.

The Redis key `session:{session_id}:ces_history` exists with a 24-hour TTL. After deployment,
new entries will be JSON; existing bare-float entries expire within 24h or are pushed out by
`ltrim` within 50 seconds of the first new signal. The backward-compat fallback handles the
transition window.

## BMAD Process Gate

- [x] Story file committed first (this file, before any implementation)
- [ ] Story commit pushed to `sprint3/s3-49-ces-history-timestamps` before any implementation
- [ ] RED tests written and failing before implementation
- [ ] GREEN implementation -- all 13 tests pass
- [ ] REFACTOR -- ruff 0 errors; no logic changes
- [ ] 6-agent adversarial code review completed
- [ ] `docs/dev3-assessment-tracker.md` updated

## Status

Draft
