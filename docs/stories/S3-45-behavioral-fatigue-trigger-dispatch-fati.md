---
id: "S3-45"
title: "Behavioral fatigue trigger — dispatch fatigue_detected from process_attention_signal based on blink+head_pose thresholds after 15min (D7)"
status: Draft
sprint: 3
story_points: 3
owner: Dev3
priority: P1
decisions: D7
depends_on: ["S3-38", "S3-48"]
branch: "sprint3/s3-45-fatigue-signal-trigger"
migration: "NO"
---

# Story S3-45 — Behavioral Fatigue Trigger: dispatch fatigue_detected from process_attention_signal based on blink+head_pose thresholds after 15min (D7)

## Context

**Missing trigger (unreachable FSM path):** `fatigue_detected` is a first-class event in the
tutor state machine (`graph.py:18`, `graph.py:274-278`), defined in `_EVENT_INTERVENTION_TYPE`
as `"fatigue": "fatigue"`, and guarded by `_can_intervene_fatigue`. The FSM handles it
correctly. However, no code in the application ever dispatches `fatigue_detected`. The only
intervention dispatch in `process_attention_signal` is `distraction_detected` (CES < threshold).
Fatigue interventions, which CLAUDE.md §10 explicitly specifies as a named intervention type
with once-per-session semantics, have never fired in production.

**Decision D7 (approved):** Add a behavioral fatigue trigger to `process_attention_signal`.
Primary trigger: `blink_rate < settings.ces_fatigue_blink_threshold` AND
`head_pose_score < settings.ces_fatigue_head_pose_threshold` for **2 consecutive windows**, AND
session duration >= `settings.ces_fatigue_min_session_seconds` (default 900 s = 15 minutes),
AND `_can_intervene_fatigue` returns True. Exhaustion fallback: when **all three MediaPipe
signals** (`behavioral_score`, `head_pose_score`, `blink_rate`) are `None` (camera failure)
AND duration >= `ces_fatigue_min_session_seconds`, dispatch `fatigue_detected` as a
conservative exhaustion-based intervention.

**Research basis (from CES Engineering Handoff):** PERCLOS (NHTSA gold standard for
drowsiness) uses eye closure > 2 s as the trigger threshold. Non-EEG validated proxies:
increased blink frequency and closure duration (Schleicher et al. 2008), forward head lean and
chin drop in learning contexts (Bosch et al. 2015). ASSISTments and Carnegie Learning
Cognitive Tutor use time-on-task with a behavioral floor. The 15-minute floor prevents false
positives during normal session startup. Once-per-session matches ITS best practice (VanLehn
2011, D'Mello & Graesser 2012).

**Prerequisite — S3-38 (NormalizedSignal optional fields):** S3-38 changes
`NormalizedSignal.behavioral_score`, `head_pose_score`, and `blink_rate` from `float` to
`float | None`. The exhaustion fallback in this story checks
`if normalized.blink_rate is None and normalized.head_pose_score is None
and normalized.behavioral_score is None` — this check is only reachable after S3-38 merges.
On current `main`, all three are required floats and the fallback is structurally unreachable.

**Prerequisite — S3-48 (atomic distraction guard, D6):** S3-48 replaces the two-step
EXISTS+GET in `_can_intervene_distraction` with a Redis Lua script and changes
`tutor_fatigue_fired` writes to use SET NX. S3-45 calls `_can_intervene_fatigue`, which after
S3-48 uses the atomic SET NX guard. Without S3-48, two concurrent attention signals arriving
within the same 5 s window could both pass `_can_intervene_fatigue`'s EXISTS check and both
dispatch `fatigue_detected` — a TOCTOU race that the Lua+NX pattern in S3-48 closes.

**Prerequisite — S3-42 (per-signal Redis history lists):** S3-42 added `lpush`/`ltrim` of
`session:{session_id}:blink_history` and `session:{session_id}:head_pose_history` to
`process_attention_signal`. This story reads those lists (last 2 entries) to evaluate the
2-window fatigue trigger. If S3-42 is not yet merged, both lists are empty and the threshold
check never fires — fail-closed, no false positives. (S3-42 is already merged to
`sprint3/s3-42-ces-breakdown-accuracy`; per D16 it merges to `main` before this story.)

## User Story

**As a** student 45 minutes into a 90-minute lesson showing persistent low blink rate and
forward head lean,
**I want** the tutor engine to recognise my behavioral fatigue signals and offer a break
suggestion,
**so that** I receive the pacing intervention mandated by CLAUDE.md §10 before exhaustion
degrades my retention rather than discovering the lesson had a fatigue path that never
activated.

**As the system,**
**I want** `process_attention_signal` to evaluate blink+head_pose history against configured
thresholds and session duration before dispatching `fatigue_detected` to the tutor FSM,
**so that** the once-per-session fatigue intervention fires exactly when the behavioral
evidence warrants it — not on session startup, not twice, and not for an engaged student
whose MediaPipe is temporarily unavailable without a sufficient duration floor.

## Acceptance Criteria

### AC 1 — Three config settings added to config.py

`apps/api/app/config.py` gains three new `Field` entries inside the `Settings` class,
with the exact names, defaults, and constraints below:

```python
ces_fatigue_blink_threshold: float = Field(
    default=0.3,
    ge=0.0,
    le=1.0,
    description="Blink rate (0-1) below which the signal indicates fatigue. "
                "Default 0.3 per Schleicher et al. 2008. "
                "Env: CES_FATIGUE_BLINK_THRESHOLD",
)
ces_fatigue_head_pose_threshold: float = Field(
    default=0.3,
    ge=0.0,
    le=1.0,
    description="Head pose score (0-1) below which the signal indicates fatigue. "
                "Default 0.3 per Bosch et al. 2015. "
                "Env: CES_FATIGUE_HEAD_POSE_THRESHOLD",
)
ces_fatigue_min_session_seconds: int = Field(
    default=900,
    ge=60,
    description="Minimum session duration in seconds before fatigue can trigger. "
                "Default 900 (15 min). Prevents false positives on session startup. "
                "Env: CES_FATIGUE_MIN_SESSION_SECONDS",
)
```

**Exact assertion:** With default env, `get_settings().ces_fatigue_blink_threshold == 0.3`,
`get_settings().ces_fatigue_head_pose_threshold == 0.3`,
`get_settings().ces_fatigue_min_session_seconds == 900`.

Setting `CES_FATIGUE_MIN_SESSION_SECONDS=59` raises `ValidationError` (ge=60 constraint).

### AC 2 — Session start timestamp written to Redis in _init_session_state

`_init_session_state` in `apps/api/app/core/websocket.py` writes
`session:{session_id}:session_start_ts` as `str(int(time.time()))` with `ex=86400` TTL
(matching all other per-session keys). The write is inside the same `try/except Exception`
block as the existing `IDLE` state key — a Redis failure logs at WARNING and never raises.

This key is **not** written on reconnect (the `_restore_or_init_session` path that returns
early when `tutor_state:{session_id}` already exists). A reconnecting student retains the
original start timestamp, so duration is measured from session creation, not reconnection.

**Exact assertion:** After calling `_init_session_state("sess-001")` with a mocked Redis:
- `redis.set` was called with `"session:sess-001:session_start_ts"` and a numeric string
  (parseable as `int`) as the value, and `ex=86400`.
- The stored value `V` satisfies `abs(int(V) - int(time.time())) <= 2`.

**Exact assertion (reconnect isolation):** When `_restore_or_init_session` returns a non-None
state (reconnect path), `_init_session_state` is NOT called, so
`session:{session_id}:session_start_ts` is NOT overwritten.

### AC 3 — Primary fatigue trigger dispatches fatigue_detected after 15-minute floor

`process_attention_signal` dispatches `fatigue_detected` to the tutor FSM exactly when all
of the following hold simultaneously:

1. `state_raw == "TEACHING"`
2. Session duration `>= settings.ces_fatigue_min_session_seconds`:
   `time.time() - float(session_start_ts_raw) >= settings.ces_fatigue_min_session_seconds`
3. `blink_history` has >= 2 entries AND `float(blink_history[0]) < settings.ces_fatigue_blink_threshold`
   AND `float(blink_history[1]) < settings.ces_fatigue_blink_threshold`
4. `head_pose_history` has >= 2 entries AND
   `float(head_pose_history[0]) < settings.ces_fatigue_head_pose_threshold`
   AND `float(head_pose_history[1]) < settings.ces_fatigue_head_pose_threshold`
5. `_can_intervene_fatigue(session_id)` returns `True`

`blink_history` and `head_pose_history` are read via `lrange` from
`session:{session_id}:blink_history` and `session:{session_id}:head_pose_history` (written by
S3-42). Index 0 is the most-recent entry (LPUSH ordering).

**Exact test setup:**
- `redis.get("tutor_state:sess-001")` → `"TEACHING"`
- `redis.get("session:sess-001:session_start_ts")` → `str(int(time.time()) - 1000)` (1000 s ago)
- `redis.lrange("session:sess-001:blink_history", 0, 1)` → `["0.2", "0.25"]` (both < 0.3)
- `redis.lrange("session:sess-001:head_pose_history", 0, 1)` → `["0.15", "0.2"]` (both < 0.3)
- `redis.exists("tutor_fatigue_fired:sess-001")` → `0`

**Exact assertion:** `dispatch_event` is called with positional arg `"fatigue_detected"`.
`result.intervention_dispatched == True`.

### AC 4 — Fatigue not dispatched before ces_fatigue_min_session_seconds

When `session_start_ts_raw` indicates duration < `settings.ces_fatigue_min_session_seconds`,
`fatigue_detected` is NOT dispatched, even if blink and head_pose are both below thresholds.

**Exact test setup:** Same as AC 3 except `redis.get(session_start_ts)` returns
`str(int(time.time()) - 100)` (100 s ago, < 900 s floor).

**Exact assertion:** `dispatch_event` is NOT called with `"fatigue_detected"`.

### AC 5 — Fatigue not dispatched when only one signal is below threshold

Both blink AND head_pose must be below their respective thresholds for both of the 2 most-recent
windows. If only blink is low (head_pose normal) or only head_pose is low (blink normal),
no fatigue trigger fires.

**Exact test setup A (blink low, head_pose normal):**
- `blink_history` → `["0.2", "0.25"]` (both < 0.3)
- `head_pose_history` → `["0.5", "0.6"]` (both > 0.3)
- Duration >= 900 s, state == TEACHING, guard not fired

**Exact assertion A:** `dispatch_event` NOT called with `"fatigue_detected"`.

**Exact test setup B (head_pose low, blink normal):**
- `blink_history` → `["0.6", "0.7"]` (both > 0.3)
- `head_pose_history` → `["0.1", "0.2"]` (both < 0.3)

**Exact assertion B:** `dispatch_event` NOT called with `"fatigue_detected"`.

### AC 6 — Fatigue not dispatched with fewer than 2 windows of blink or head_pose data

If `blink_history` or `head_pose_history` contains fewer than 2 entries (session just started,
first signal processed, or histories expired), `fatigue_detected` is NOT dispatched even if
the single available entry is below threshold.

**Exact test setup:** `blink_history` → `["0.2"]` (1 entry), `head_pose_history` →
`["0.15"]` (1 entry), duration >= 900 s, state == TEACHING, guard not fired.

**Exact assertion:** `dispatch_event` NOT called with `"fatigue_detected"`.

### AC 7 — Fatigue not dispatched twice in same session (once-per-session guard)

When `_can_intervene_fatigue(session_id)` returns `False` (because
`tutor_fatigue_fired:{session_id}` is already set — written by `intervening_node` after the
first dispatch), `fatigue_detected` is NOT dispatched regardless of blink/head_pose values.

**Exact test setup:** All primary trigger conditions met (AC 3), but mock
`_can_intervene_fatigue` returns `False`.

**Exact assertion:** `dispatch_event` NOT called with `"fatigue_detected"`.

### AC 8 — Fatigue not dispatched outside TEACHING state

Even with all behavioral conditions met, `fatigue_detected` is NOT dispatched when
`state_raw != "TEACHING"` (e.g., state == "QUIZZING", "INTERVENING", "CHECKING_IN").

**Exact test setup:** All primary trigger conditions met (AC 3) except
`redis.get("tutor_state:sess-001")` → `"QUIZZING"`.

**Exact assertion:** `dispatch_event` NOT called with `"fatigue_detected"`.

### AC 9 — Exhaustion fallback dispatches when all MediaPipe signals None after duration floor

When all of the following hold:
1. `normalized.behavioral_score is None` AND `normalized.head_pose_score is None` AND
   `normalized.blink_rate is None` (all MediaPipe signals absent — requires S3-38)
2. `state_raw == "TEACHING"`
3. Session duration >= `settings.ces_fatigue_min_session_seconds`
4. `_can_intervene_fatigue(session_id)` returns `True`

`process_attention_signal` dispatches `fatigue_detected` via the exhaustion fallback path.

**Exact assertion:** Given a signal with all three MediaPipe fields absent (or explicitly
`None`), session running for 1000 s (> 900 s floor), state == TEACHING, guard not fired,
`dispatch_event` is called with `"fatigue_detected"`.

### AC 10 — Exhaustion fallback not triggered before duration floor

When all MediaPipe signals are `None` AND duration < `ces_fatigue_min_session_seconds`,
the exhaustion fallback does NOT dispatch `fatigue_detected`.

**Exact assertion:** Signal with all None MediaPipe fields, session running for 100 s,
`dispatch_event` NOT called with `"fatigue_detected"`.

### AC 11 — WS tutor_intervene message delivered to client on fatigue dispatch

When `fatigue_detected` is dispatched and the FSM transitions to INTERVENING with
`intervention_type == "fatigue"`, a WebSocket message is sent to the client via
`manager.send()`:
```json
{
  "type": "tutor_intervene",
  "payload": {
    "session_id": "<session_id>",
    "type": "fatigue",
    "message": "<pre-generated fatigue intervention message or null>"
  }
}
```
This mirrors the existing `distraction_detected` delivery path in `process_attention_signal`.
Best-effort: any exception in `manager.send()` is caught and logged at EXCEPTION level without
re-raising (same pattern as the distraction path at lines ~352-366).

**Exact assertion:** When `dispatch_event` returns
`{"current_state": "INTERVENING", "intervention_type": "fatigue",
"intervention_message": "Take a short break..."}`,
`manager.send` is called with `session_id` and a dict where `payload["type"] == "fatigue"`
and `payload["message"] == "Take a short break..."`.

### AC 12 — blink_history and head_pose_history lrange use end index 1 (not -1)

In `process_attention_signal`, the fatigue trigger reads only the 2 most-recent entries from
each signal history via `lrange(key, 0, 1)` — not `lrange(key, 0, -1)`. End index `1`
guarantees at most 2 entries read regardless of list length.

**Exact assertion (source inspection):**
`inspect.getsource(process_attention_signal)` contains the strings `"blink_history"` and
`"head_pose_history"`. The lrange calls for the fatigue check use end argument `1`, not `-1`.
A source scan for the pattern `lrange.*blink_history.*-1` must return no matches.

### AC 13 — session_start_ts key missing treated as duration unknown (fail-closed)

When `session:{session_id}:session_start_ts` does not exist in Redis (key expired, or session
predates this story), the fatigue trigger treats duration as unknown and does NOT dispatch
`fatigue_detected`. This is the safe default: unknown duration = duration not yet met.

**Exact assertion:** Mock `redis.get("session:sess-001:session_start_ts")` → `None`. All other
conditions met. `dispatch_event` NOT called with `"fatigue_detected"`.

### AC 14 — Distraction trigger behaviour unchanged (regression guard)

The existing distraction trigger logic (`CES < threshold for 2 consecutive windows`) continues
to function identically after this story. `fatigue_detected` is dispatched independently of
and never instead of `distraction_detected`. Both triggers can fire in the same session
(distraction up to max_distraction_per_session times, fatigue exactly once).

**Exact assertion:** All existing tests in `test_tutor_service.py` that assert
`dispatch_event("distraction_detected")` continue to pass without modification.

### AC 15 — ruff check and ruff format 0 errors in modified files

`ruff check apps/api/app/modules/tutor/service.py apps/api/app/core/websocket.py apps/api/app/config.py`
exits 0. `ruff format --check` on the same files exits 0.

### AC 16 — Minimum 19 unit tests, all passing under pytest -m unit

All tests listed in the Test Requirements section exist in
`apps/api/tests/test_s3_45_fatigue_trigger.py` and pass under `pytest -m unit`. Mocked Redis
and FSM — no real Redis or DB required.

## Tasks / Subtasks

### Task 1 — Story file (story-first gate)
- [ ] 1.1 Create `docs/stories/S3-45-behavioral-fatigue-trigger-dispatch-fati.md`
- [ ] 1.2 Commit story-only to `sprint3/s3-45-fatigue-signal-trigger`
- [ ] 1.3 Push story commit to remote before any implementation

### Task 2 — RED phase (failing tests)
- [ ] 2.1 Create `apps/api/tests/test_s3_45_fatigue_trigger.py`
- [ ] 2.2 Write test for AC 1 — config defaults
- [ ] 2.3 Write test for AC 1 — validation (min_session_seconds < 60 raises)
- [ ] 2.4 Write test for AC 2 — session_start_ts written in _init_session_state
- [ ] 2.5 Write test for AC 2 — session_start_ts TTL is 86400
- [ ] 2.6 Write test for AC 2 — no overwrite on reconnect
- [ ] 2.7 Write test for AC 3 — primary trigger dispatches after floor
- [ ] 2.8 Write test for AC 4 — no dispatch before min duration
- [ ] 2.9 Write test for AC 5A — blink low, head_pose normal → no dispatch
- [ ] 2.10 Write test for AC 5B — head_pose low, blink normal → no dispatch
- [ ] 2.11 Write test for AC 6 — fewer than 2 windows → no dispatch
- [ ] 2.12 Write test for AC 7 — once-per-session guard blocks second dispatch
- [ ] 2.13 Write test for AC 8 — no dispatch outside TEACHING state
- [ ] 2.14 Write test for AC 9 — exhaustion fallback dispatches after floor
- [ ] 2.15 Write test for AC 10 — exhaustion fallback blocked before floor
- [ ] 2.16 Write test for AC 11 — WS tutor_intervene message delivered
- [ ] 2.17 Write test for AC 12 — lrange end=1 source guard
- [ ] 2.18 Write test for AC 13 — session_start_ts missing → fail-closed
- [ ] 2.19 Write test for AC 14 — distraction path regression
- [ ] 2.20 Confirm all 19 tests FAIL before implementation

### Task 3 — GREEN phase (implementation)
- [ ] 3.1 `apps/api/app/config.py`: add the three new `Field` entries from AC 1
- [ ] 3.2 `apps/api/app/core/websocket.py` — `_init_session_state`: add
          `session:{session_id}:session_start_ts` SET inside the existing try/except block
- [ ] 3.3 `apps/api/app/modules/tutor/service.py` — `process_attention_signal`:
          add the fatigue trigger block AFTER the existing distraction dispatch block.
          Block structure:
          - Check `state_raw == "TEACHING" and not intervention_dispatched`
          - Get `session_start_ts_raw`; if None → skip (fail-closed)
          - Compute `duration_s = time.time() - float(session_start_ts_raw)`
          - If `duration_s < settings.ces_fatigue_min_session_seconds` → skip
          - `lrange(blink_history, 0, 1)` and `lrange(head_pose_history, 0, 1)`
          - Evaluate `primary_trigger` (2-window blink AND head_pose both below thresholds)
          - Evaluate `exhaustion_fallback` (all three MediaPipe fields `is None`)
          - If `(primary_trigger or exhaustion_fallback) and await _can_intervene_fatigue(...)`:
            dispatch `fatigue_detected`, set `intervention_dispatched = True`,
            deliver WS `tutor_intervene` message (best-effort, try/except)
- [ ] 3.4 Add `# BOUNDED: lrange end=1 limits read to 2 entries` comment on each lrange call
- [ ] 3.5 Confirm all 19 tests PASS

### Task 4 — REFACTOR + validation
- [ ] 4.1 `ruff check .` — zero new errors repo-wide
- [ ] 4.2 `ruff format --check` — zero format violations
- [ ] 4.3 Full Dev 3 regression suite GREEN (`pytest -m unit`)
- [ ] 4.4 Confirm existing `test_tutor_service.py` tests pass (AC 14 regression guard)

### Task 5 — 6-agent adversarial review
- [ ] 5.1 Layer 1 — Story Quality
- [ ] 5.2 Layer 2 — Blind Hunter (Security)
- [ ] 5.3 Layer 3 — Test Coverage
- [ ] 5.4 Layer 4 — AC Completeness
- [ ] 5.5 Layer 5 — Process Integrity
- [ ] 5.6 Layer 6 — Scale & Load

### Task 6 — Commit + push
- [ ] 6.1 Final implementation commit on `sprint3/s3-45-fatigue-signal-trigger`
- [ ] 6.2 Push to remote
- [ ] 6.3 Update `docs/dev3-assessment-tracker.md`

## Scale & Load

### Q1 — What is ONE unit of work, and what is its range?

One unit of work is one execution of the fatigue-trigger evaluation block inside a single call
to `process_attention_signal`. It runs on every attention signal while the session is in
TEACHING state — approximately once every 5 seconds per active session.

- **Min:** 0 evaluations triggering fatigue per session (session never enters TEACHING, or
  duration never crosses the 15-minute floor, or fatigue fires once and the once-per-session
  guard blocks all subsequent evaluations with a single EXISTS call).
- **Typical:** ~180 signals before the floor (skipped), then ~180 more during a 30-minute
  lesson after crossing 900 s. Full evaluation (3 Redis reads + EXISTS) runs until the first
  successful dispatch. After dispatch: EXISTS returns True → guard returns False → skip.
- **Largest measured:** ~720 signals for a 60-minute session. After the first fatigue dispatch
  (once-per-session), all subsequent evaluations short-circuit on EXISTS. No growth after first
  dispatch.
- **Beyond the bound:** No growth path. Once-per-session guard ensures the full 4-operation
  Redis read path runs at most once per session (on the dispatching signal). All later signals
  short-circuit at EXISTS.

Each full evaluation at its most expensive: 4 Redis operations
(`GET session_start_ts` + `LRANGE blink_history, 0, 1` + `LRANGE head_pose_history, 0, 1` +
`EXISTS tutor_fatigue_fired`). O(1) at all call counts. Post-dispatch: 1 EXISTS per signal.

### Q2 — Which budgets are FIXED while the input VARIES — and what happens past them?

| Budget | Value | Scope | Past the limit |
|--------|-------|-------|----------------|
| `ces_fatigue_min_session_seconds` | 900 s (env var, default) | Per deployment | Below 900 s: fatigue evaluation exits immediately after `GET session_start_ts`. Explicit skip, logged at DEBUG. |
| `ces_fatigue_blink_threshold` | 0.3 (env var, 0.0–1.0) | Per deployment | Values >= threshold: no contribution to trigger. No silent truncation. |
| `ces_fatigue_head_pose_threshold` | 0.3 (env var, 0.0–1.0) | Per deployment | Same as blink. |
| blink_history lrange read | `lrange(key, 0, 1)` — 0 to 2 entries | Per signal | End index `1` hard-caps read at 2 entries regardless of list length. `# BOUNDED:` comment required on the lrange call. |
| head_pose_history lrange read | `lrange(key, 0, 1)` — 0 to 2 entries | Per signal | Same as blink. |
| Once-per-session cap | `_can_intervene_fatigue` (EXISTS on `tutor_fatigue_fired`) | Per session | After first dispatch: EXISTS returns True → guard returns False → 1 EXISTS per signal, no further evaluation. Explicit, no accumulation. |
| `session_start_ts` TTL | 86400 s (24 h) | Per session | After 24 h: key expires, GET returns None, evaluation skips (fail-closed). |

No silent truncation: every budget past its limit produces an explicit, documented skip.

### Q3 — What is the SCOPE of every limit?

| Limit | Scope | Justification |
|-------|-------|---------------|
| `ces_fatigue_min_session_seconds = 900` | Per deployment (env var) | One value across all Railway replicas. Sessions active during an env var change retain their original `session_start_ts` — the new floor applies only to future `GET`-then-compare evaluations, which is safe (monotonically increasing `time.time()` vs. stored timestamp). |
| `ces_fatigue_blink_threshold = 0.3` | Per deployment (env var) | Consistent across all replicas. A configuration drift scenario (one replica gets a new value, others don't) is a Railway env-var deployment concern, not an application correctness concern. |
| `ces_fatigue_head_pose_threshold = 0.3` | Per deployment (env var) | Same as blink. |
| `lrange(key, 0, 1)` bound | Per session, per signal | `blink_history` and `head_pose_history` are namespaced by `session_id`. Two concurrent sessions never share list reads. |
| `session:{session_id}:session_start_ts` | Per session | One key per UUIDv4 session. Shared across Railway replicas via the single Railway Redis instance. `SET` is atomic — no partial-write race. |
| `tutor_fatigue_fired:{session_id}` | Per session | Written by `intervening_node` after first fatigue dispatch. Read by `_can_intervene_fatigue`. Shared across replicas via Railway Redis. SET NX (from S3-48) makes this atomic. |

### Q4 — Which reads and writes are UNBOUNDED?

None introduced by this story.

**Writes:**
- `session:{session_id}:session_start_ts`: one `SET` per fresh WebSocket connect. O(1). No
  append, no accumulation.

**Reads:**
- `GET session_start_ts` — single key. O(1).
- `LRANGE blink_history, 0, 1` — bounded to 2 entries by end index `1`. NOT `lrange(0, -1)`.
  `# BOUNDED: lrange end=1 limits read to 2 entries` comment required at the call site.
- `LRANGE head_pose_history, 0, 1` — same, 2 entries max.
- `EXISTS tutor_fatigue_fired` — single key. O(1).

**Upstream list bounds (inherited):** `blink_history` and `head_pose_history` are trimmed to
`_CES_HISTORY_MAX = 10` entries by S3-42's `lpush`+`ltrim` pattern. This story reads only 2
of those at most 10 entries — always bounded independently of the trim cap.

### Q5 — Which caps were INHERITED from an earlier design, and have they been re-derived?

- **`_CES_HISTORY_MAX = 10` (from S3-34/S3-42):** This story reads only 2 of the up-to-10
  entries via `lrange(0, 1)`. The inherited cap is not a constraint for the fatigue check — we
  deliberately read fewer entries than the cap allows. Re-derived: 2 entries = 10 seconds of
  data at 5-second cadence, which is the exact minimum for a "2 consecutive windows" check.
- **`_CES_WINDOW_TTL = 86400 s` (from S3-34):** Inherited for `session_start_ts`. Valid:
  session data is only meaningful within 24 h. After expiry, duration is unknown and the
  fatigue evaluation skips fail-closed — correct behaviour.
- **`ces_fatigue_min_session_seconds = 900 s`:** New cap derived for this story. Basis: the
  ASSISTments ITS and Carnegie Learning Cognitive Tutor both use a 20–30 minute floor for
  fatigue signals (from CES Engineering Handoff). 15 minutes (900 s) is the conservative
  minimum that prevents false positives during a 30-minute lesson's first half. Configurable
  via env var for Sprint 4 calibration against real session data.
- **Once-per-session cap (S3-48 SET NX):** The existing `_can_intervene_fatigue` uses EXISTS.
  S3-48 upgrades this to SET NX for atomic acquisition. The once-per-session semantic was
  already established in the FSM design (`graph.py:184-185`); S3-48 closes the concurrent-
  dispatch race without changing the semantic.

### Q6 — Is every check-then-act sequence safe under CONCURRENT requests?

Two concurrent attention signals for the same session (e.g., rapid-fire signals from a client
with network jitter) could both reach the fatigue evaluation block simultaneously.

**Race condition analysis:**

1. Both calls read `session_start_ts` — pure read, safe.
2. Both calls read `blink_history` and `head_pose_history` — pure reads, safe.
3. Both calls reach `_can_intervene_fatigue(session_id)`:
   - **Pre-S3-48 (current main):** `EXISTS(tutor_fatigue_fired)` is read-only. Both see the
     flag absent and both call `dispatch_event("fatigue_detected")`. This is the TOCTOU race.
     The second dispatch reaches `route_from_teaching` which re-checks `_can_intervene_fatigue`
     synchronously before transitioning — the first dispatch atomically writes
     `tutor_fatigue_fired` in `intervening_node`, so the second sees the flag and returns
     `"teaching"` (stays in TEACHING). The double dispatch is wasteful but not catastrophically
     wrong in most cases. Full correctness requires S3-48.
   - **Post-S3-48:** `_can_intervene_fatigue` uses Redis SET NX for `tutor_fatigue_fired`.
     Exactly one caller acquires the NX key; the other receives `None` → returns `False` →
     no dispatch. Atomic by Redis SET NX semantics.

**Dependency correctness:** This story's concurrent-dispatch safety guarantee requires S3-48 to
be merged before production use. Running S3-45 without S3-48 is safe enough for testing
(double-dispatch degrades gracefully via FSM route guard) but should not go to production
against real students without S3-48's SET NX protection.

**session_start_ts write:** One `SET` in `_init_session_state` at WebSocket connect.
`SET` is atomic. No check-then-act pattern. Not a race concern.

## Security

### Authentication and ownership

`process_attention_signal` is called from `_handle_attention_signal` in `websocket.py`,
which is behind the `/ws/{session_id}` WebSocket route. The `session_id` is validated by
`_SESSION_ID_RE` (UUID format) at the route boundary before any dispatch. The WebSocket
connection is JWT-authenticated (per S3-43 / D7 in the CES decision record). No client can
dispatch `fatigue_detected` directly — it is explicitly excluded from `_CLIENT_DRIVABLE_EVENTS`
and `_TUTOR_CLIENT_EVENTS`. The fatigue dispatch originates exclusively from server-side
signal evaluation, not from client-supplied events.

### Threshold manipulation

`ces_fatigue_blink_threshold` and `ces_fatigue_head_pose_threshold` are server-side config
(env vars). A client cannot manipulate the thresholds. The client-supplied `blink_rate` and
`head_pose_score` values are:
- Validated as finite floats by `_parse_signal` (NaN/±inf rejected with `ValueError`)
- Compared to thresholds only — no computation that amplifies a crafted value
- Used only in a boolean comparison against a fixed constant

An adversarial client sending crafted low blink/head_pose values to trigger an early fatigue
intervention would also need to manipulate `session_start_ts` (a server-written Redis key)
to bypass the 15-minute floor. Clients have no write access to Railway Redis.

### Redis key integrity

`session:{session_id}:session_start_ts` is written only by server-side code in
`_init_session_state`. The `session_id` in the key is UUIDv4-validated by `_SESSION_ID_RE`
before `_init_session_state` is called. A client cannot SET this key directly (Redis is not
client-accessible) and cannot forge a valid session_id that maps to another user's session
(UUIDv4 collision probability ~1 in 5.3×10^36).

### No new HTTP endpoints

No new routes, no new parameters, no new authentication surface. Only the WebSocket signal
processing path and the session initialization path are modified, both of which are already
within the existing authenticated WebSocket boundary.

### Information disclosure

The fatigue intervention message delivered to the client (`"Take a short break..."`) is
pre-generated at lesson build time and stored in
`LessonPackage.segments[].interventions.fatigue`. No signal values, no threshold values,
and no session metadata are included in the `tutor_intervene` WebSocket message beyond the
intervention text. Raw attention data (blink_rate, head_pose_score) is never included in any
outbound message — consistent with CLAUDE.md §18 ("Raw webcam video NEVER leaves browser —
only 5 derived numbers sent").

## Test Requirements

All tests in `apps/api/tests/test_s3_45_fatigue_trigger.py`, marked `@pytest.mark.unit`.
No real Redis, no real DB, no real FSM — all dependencies mocked.

| Test name | AC | Type |
|-----------|-----|------|
| `test_ces_fatigue_blink_threshold_default_is_0_3` | AC 1 | Settings default |
| `test_ces_fatigue_head_pose_threshold_default_is_0_3` | AC 1 | Settings default |
| `test_ces_fatigue_min_session_seconds_default_is_900` | AC 1 | Settings default |
| `test_ces_fatigue_min_session_seconds_below_60_raises_validation_error` | AC 1 | Settings validation |
| `test_init_session_state_writes_session_start_ts_to_redis` | AC 2 | Runtime (mocked Redis) |
| `test_init_session_state_session_start_ts_has_86400_ttl` | AC 2 | Runtime (mocked Redis) |
| `test_session_start_ts_not_overwritten_on_reconnect` | AC 2 | Runtime (mocked Redis) |
| `test_fatigue_detected_dispatched_after_15_minute_floor_with_low_blink_and_head_pose` | AC 3 | Runtime (mocked) |
| `test_fatigue_not_dispatched_before_ces_fatigue_min_session_seconds` | AC 4 | Runtime (mocked) |
| `test_fatigue_not_dispatched_when_only_blink_is_low` | AC 5 | Runtime (mocked) |
| `test_fatigue_not_dispatched_when_only_head_pose_is_low` | AC 5 | Runtime (mocked) |
| `test_fatigue_not_dispatched_with_fewer_than_2_blink_windows` | AC 6 | Runtime (mocked) |
| `test_fatigue_not_dispatched_with_fewer_than_2_head_pose_windows` | AC 6 | Runtime (mocked) |
| `test_fatigue_not_dispatched_twice_in_same_session` | AC 7 | Runtime (mocked) |
| `test_fatigue_not_dispatched_outside_teaching_state` | AC 8 | Runtime (mocked) |
| `test_exhaustion_fallback_dispatches_when_all_mediapipe_none_after_floor` | AC 9 | Runtime (mocked) |
| `test_exhaustion_fallback_not_dispatched_before_duration_floor` | AC 10 | Runtime (mocked) |
| `test_fatigue_tutor_intervene_ws_message_delivered_on_dispatch` | AC 11 | Runtime (mocked WS) |
| `test_blink_history_lrange_uses_end_index_1_not_minus_1` | AC 12 | Source inspection |
| `test_session_start_ts_missing_does_not_dispatch_fatigue` | AC 13 | Runtime (mocked) |

**Regression tests (must remain GREEN, no modifications permitted):**
- `apps/api/tests/test_tutor_service.py` — full existing suite. In particular:
  `test_distraction_detected_dispatched_when_ces_below_threshold`,
  `test_distraction_not_dispatched_when_in_cooldown`,
  `test_distraction_not_dispatched_after_max_interventions`
  (AC 14 regression guard — distraction path must be unchanged).

## Decision References

| Decision | Description | This story |
|----------|-------------|------------|
| D7 | Behavioral fatigue trigger: blink+head_pose thresholds for 2 windows + 15-min floor; exhaustion fallback when all MediaPipe None | Implemented in full by this story. |
| D5 | NormalizedSignal behavioral/head_pose/blink Optional[float]; skip LPUSH when None | Required by the exhaustion fallback (`all None` check). D5 is implemented in S3-38, which must merge before this story. |
| D6 | Lua script for atomic distraction+fatigue guards; SET NX for fatigue_fired | Closes the concurrent-dispatch TOCTOU race. D6 is implemented in S3-48, which must merge before production deployment of this story. |
| D3 | Per-signal Redis history lists in process_attention_signal | Implemented by S3-42 (already merged). Provides `blink_history` and `head_pose_history` lists that this story reads. |

## Dependencies

- **S3-38** (NormalizedSignal optional fields, D5): Must merge to `main` before this story.
  The exhaustion fallback's `normalized.blink_rate is None` check is structurally unreachable
  on current `main` where `blink_rate` is a required float.

- **S3-48** (Atomic distraction guard via Redis Lua script, D6): Must merge to `main` before
  production use. S3-48 makes `_can_intervene_fatigue` use SET NX, closing the TOCTOU race
  where two simultaneous signals at the 15-minute threshold could both dispatch `fatigue_detected`.

- **S3-42** (CES breakdown accuracy, per-signal Redis history): Already merged. Provides
  `session:{session_id}:blink_history` and `session:{session_id}:head_pose_history` that this
  story reads via `lrange(key, 0, 1)`.

## Migration

**NO** — This story modifies server-side signal processing and session initialisation only.
No new Supabase tables, columns, or constraints. `supabase/migrations/` is unchanged.

New Redis key introduced:
- `session:{session_id}:session_start_ts` — string (int unix timestamp), TTL 86400 s.
  Written in `_init_session_state` on fresh WebSocket connect. Not DB-backed; expires after
  24 h. Read in `process_attention_signal` during the fatigue duration check.

## Status

Draft
