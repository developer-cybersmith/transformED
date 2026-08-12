# CES Lifecycle — Live Learner Journey

> **Accuracy contract:** Every claim in this document cites an exact `file:line` read on
> 2026-08-12. Where two files contradict each other, both are reported verbatim; the
> contradiction is explicitly flagged. A QA engineer should be able to derive integration
> test assertions from this document without reading the source.

---

## 1. Session Initialization

**Entry point:** `apps/api/app/core/websocket.py:138` — `websocket_endpoint` route
(`/ws/{session_id}`).

### 1a. WebSocket connect

`manager.connect()` (`websocket.py:65`) is called after the UUID-format validation guard
(`websocket.py:145-147`). It delegates to `_restore_or_init_session` (`websocket.py:189`).

**Reconnect path** (`websocket.py:204-209`): if `tutor_state:{session_id}` already exists in
Redis, the stored state string is returned and a `state_change` message (from_state == to_state)
is pushed to the reconnecting client. `_seed_learner_tier` is also called on reconnect.

**Fresh connect path** (`websocket.py:213`): `_init_session_state` is called.

### 1b. `_init_session_state` (`websocket.py:217-255`)

All writes are best-effort (wrapped in `try/except`). A Redis failure here logs a WARNING but
does not crash the WS accept handshake.

| Redis key | Value | TTL | Line |
|-----------|-------|-----|------|
| `tutor_state:{session_id}` | `"IDLE"` | 86400 s | 236 |
| `tutor_distraction_count:{session_id}` | `"0"` | 86400 s | 237 |
| `tutor_cooldown:{session_id}` | (deleted) | — | 238 |
| `tutor_fatigue_fired:{session_id}` | (deleted) | — | 239 |
| `session:{session_id}:segment_index` | (deleted) | — | 240–242 |
| `session:{session_id}:session_start_ts` | `str(int(time.time()))` | 86400 s | 244–250 |

`session_start_ts` is written with `nx=True` (`websocket.py:249`) so that reconnects do not
reset the clock. **D61:** if the write fails (Redis unavailable at connect time), the key is
never set and fatigue detection is silently disabled for the entire session (see Section 6a and
Section 12).

After the Redis writes, `_seed_learner_tier` (`websocket.py:261-306`) runs: it reads
`lesson_package:{session_id}`, extracts `metadata.tier`, and writes
`session:{session_id}:learner_tier` and `session:{session_id}:qa_phase_seconds` via a pipeline
(transaction=False). This is best-effort; a failure does not abort the handshake.

### 1c. session_start event → TEACHING

The client sends `{"type": "session_start", ...}` over the WebSocket.
`_handle_session_start` (`websocket.py:312`) is called, which:

1. Optionally writes `session:{session_id}:learner_tier` and `session:{session_id}:qa_phase_seconds`
   from a `learner_tier` field in the WS payload (`websocket.py:341-365`). This is a WS-payload
   override of the lesson-package tier seeded at connect time (last-writer-wins caveat documented
   in `websocket.py:325-335`).
2. Calls `start_session(session_id)` (`tutor/service.py:184-193`), which calls
   `dispatch_event(session_id, "session_start")`.
3. `dispatch_event` (`state_machine/graph.py:540-609`) reads the current state from Redis,
   builds `TutorMachineState`, invokes the compiled LangGraph with `recursion_limit=5`
   (`graph.py:586`), and sends a `state_change` WS message when the state actually changes
   (`graph.py:594-608`).
4. `route_from_idle` (`graph.py:428-430`) routes `session_start` → `"teaching"`.
5. `teaching_node` (`graph.py:219-224`) persists `TutorState.TEACHING` to Redis and sets
   `in_teachback=False`.

**Result after initialization:** `tutor_state:{session_id}` = `"TEACHING"`, all counters
reset, `session_start_ts` set, learner tier seeded if lesson package was cached.

---

## 2. Teaching Phase — Every CES Window (5-second cadence)

**Entry:** `websocket.py:162-163` — inbound `attention_signal` message →
`_handle_attention_signal` → `process_attention_signal(session_id, signal)`
(`tutor/service.py:271`).

`process_attention_signal` is the **only** function that computes CES and evaluates
intervention triggers. Its full step-by-step logic:

```
Step 1  Read tutor_state:{session_id} from Redis           [service.py:294]
Step 2  If state == "TEACHING":
          a. Parse & validate signal → NormalizedSignal    [service.py:300]
          b. Compute CES float (0-100)                     [service.py:301]
          c. Write ces_window + tutor_ces keys             [service.py:303-308]
          d. LPUSH + LTRIM + EXPIRE ces_history (cap=10)   [service.py:312-315]
          e. Write per-signal histories (no TTL — D64)     [service.py:320-336]
          f. Read back history (lrange 0..9)               [service.py:340-342]
          g. If len(history) >= 2: run distraction check   [service.py:344-411]
Step 3  If state == "TEACHING" AND no intervention dispatched:
          a. Read session_start_ts                         [service.py:421]
          b. If not None: compute duration                 [service.py:432]
          c. If duration >= 900s: run fatigue check        [service.py:435-502]
Step 4  If state == "QUIZZING": check Q&A deadline         [service.py:507-514]
Step 5  Return CesResult(session_id, ces, intervention_dispatched)
```

**Security:** `_handle_attention_signal` (`websocket.py:394-415`) sends only an `attention_ack`
message back to the client. Raw CES scores are never exposed to the client per PRD §18.

---

## 3. CES Formula — Exact Calculation

**Critical finding: there are two separate `compute_ces` implementations in this codebase
with different behaviour for `None` signal values. Only one runs during a live session.**

### 3a. Live-session formula (production path)

**File:** `apps/api/app/modules/tutor/service.py:107-137` — `compute_ces(signal: NormalizedSignal)`

This is the version called by `process_attention_signal` at line 301. It imports settings via
`get_settings()` (`service.py:121-122`).

**Weight configuration** (from `config.py:219-223`, all `ge=0.0, le=1.0`):

| Signal | Default weight | Env var |
|--------|---------------|---------|
| `quiz_accuracy` | 0.35 | `CES_WEIGHT_QUIZ` |
| `teachback_score` | 0.25 | `CES_WEIGHT_TEACHBACK` |
| `behavioral_score` | 0.20 | `CES_WEIGHT_BEHAVIORAL` |
| `head_pose_score` | 0.12 | `CES_WEIGHT_HEAD_POSE` |
| `blink_rate` | 0.08 | `CES_WEIGHT_BLINK` |

Validated at startup: `abs(sum - 1.0) > 0.001` raises `ValueError` (`config.py:266-279`).

**Formula (live-session implementation):**

```python
pairs = [(signal.quiz_accuracy, w_quiz),   # all 5 may be None
         (signal.teachback_score, w_tb),
         (signal.behavioral_score, w_beh),
         (signal.head_pose_score,  w_hp),
         (signal.blink_rate,       w_blink)]
present = [(v, w) for (v, w) in pairs if v is not None]  # drop None signals
weight_sum = sum(w for _, w in present)
if weight_sum <= 0:
    return 0.0                                             # all-None exhaustion
CES = sum(v * (w / weight_sum) for v, w in present) * 100.0
return max(0.0, min(100.0, CES))                          # clamp, no rounding
```

**Nominal (all 5 signals present):**
```
CES = (quiz×0.35 + tb×0.25 + beh×0.20 + hp×0.12 + blink×0.08) × 100
```

### 3b. `teachback_score=None` — weight redistribution (live-session)

When `teachback_score` is None in the live-session path, the 0.25 weight is dropped from
`present` and the remaining weights (`0.35 + 0.20 + 0.12 + 0.08 = 0.75`) become the
denominator. Effective weights:

| Signal | Effective weight | Points at signal=1.0 |
|--------|-----------------|----------------------|
| quiz | 0.35/0.75 = 0.4667 | 46.67 |
| behavioral | 0.20/0.75 = 0.2667 | 26.67 |
| head_pose | 0.12/0.75 = 0.1600 | 16.00 |
| blink | 0.08/0.75 = 0.1067 | 10.67 |

This matches the PRD §11 redistributed formula exactly.

### 3c. `quiz_accuracy=None` — CONTRADICTORY BEHAVIOUR between implementations

**Live-session (`tutor/service.py:125-132`):** `quiz_accuracy=None` causes its 0.35 weight to
be dropped from `present` and redistributed proportionally to the remaining present signals.
A student who has not yet taken a quiz gets an effectively inflated CES from the three
MediaPipe signals.

**Report/test implementation (`assessment/ces.py:55`):** `quiz_accuracy=None` is treated as
`0.0` with the full 0.35 weight retained. The `ces.py` docstring (`line 36-39`) states
explicitly: "When quiz_accuracy is None (no quiz submitted yet in this window), it is treated
as 0.0 with its full weight retained — this is a transient 'no data yet' state, not a
permanent skip, so no redistribution occurs."

This is a real divergence. During a live session, an unquizzed student has a higher CES than
the report later shows. Intervention thresholds in-session and the final report use different
arithmetic for the same input.

### 3d. Other signals `None` — MediaPipe frame drop

In the live-session path, `behavioral_score`, `head_pose_score`, and `blink_rate` may all be
`None` (see `_parse_signal`, `service.py:98-100`). Each `None` is silently dropped from
`present` and the remaining weights scale up accordingly.

### 3e. All MediaPipe signals `None` — exhaustion path

If `behavioral_score`, `head_pose_score`, and `blink_rate` are all `None`:

- If `quiz_accuracy` or `teachback_score` are also `None`: `weight_sum=0` → `compute_ces`
  returns `0.0` (`service.py:134-135`).
- If quiz or teachback are present: CES is computed from those signals only, with their
  weights scaling to sum to 1.0.

The same all-three-MediaPipe-None condition is the **exhaustion fallback** for the fatigue
trigger (Section 6c).

---

## 4. Redis State Written Each Window

Written by `process_attention_signal` **only in TEACHING state** (`service.py:299-336`).

| Key | Operation | Value | TTL | Bound | Line |
|-----|-----------|-------|-----|-------|------|
| `session:{id}:ces_window` | SET | CES float | 86400 s | single value | 307 |
| `tutor_ces:{id}` | SET | CES float | 86400 s | single value | 308 |
| `session:{id}:ces_history` | LPUSH + LTRIM(0,9) + EXPIRE | JSON `{"v":float,"t":int}` | 86400 s | 10 entries max | 312–315 |
| `session:{id}:behavioral_history` | LPUSH + LTRIM(0,9) | float (if not None) | **NONE — D64** | 10 entries max | 320–326 |
| `session:{id}:head_pose_history` | LPUSH + LTRIM(0,9) | float (if not None) | **NONE — D64** | 10 entries max | 327–333 |
| `session:{id}:blink_history` | LPUSH + LTRIM(0,9) | float (if not None) | **NONE — D64** | 10 entries max | 334–336 |

**D64:** `behavioral_history`, `head_pose_history`, and `blink_history` have no `EXPIRE`
call (`service.py:320-336`). `ces_history` correctly gets `expire(_CES_WINDOW_TTL)` at
`service.py:315`. The per-signal keys persist until Redis eviction.

**History entry format (D4):** `{"v": <CES float>, "t": <Unix seconds int>}`. Legacy
bare-float strings are accepted by a backward-compat fallback (`service.py:348-356`); they
produce `t=0` which causes the D4 gap check to always fail for that pair, preventing false
interventions on mixed old/new history.

---

## 5. Distraction Trigger Lifecycle (end-to-end)

### 5a. Prerequisite checks

```
→ state_raw == "TEACHING"           [service.py:299]
→ _parse_signal succeeds            [service.py:300]
→ compute_ces returns float         [service.py:301]
→ Redis history written             [service.py:303-336]
→ lrange history read               [service.py:340-342]
→ len(history_raw) >= 2             [service.py:344]
```

If any step fails or the length check fails, the distraction path is skipped entirely and
`intervention_dispatched` remains `False`.

### 5b. D4 timestamp gap check

```python
v0, t0 = parse(history_raw[0])   # most recent (LPUSH prepends)
v1, t1 = parse(history_raw[1])   # second most recent
gap_ok = abs(t0 - t1) <= 2 * settings.ces_cadence_seconds   # default: <= 10 s
```

`ces_cadence_seconds` default = 5 (`config.py:256`), so the tolerance window is 10 seconds.
Pairs outside this window are treated as stale (e.g., MediaPipe restart, browser tab switch).
A corrupt entry produces `t=0`, making `abs(now - 0)` >> 10 s — always failing the check.
(`service.py:358-362`)

### 5c. Lua atomic guard (`_can_intervene_distraction`)

Condition: `gap_ok AND v0 < ces_threshold AND v1 < ces_threshold` (default threshold = 50.0,
`config.py:224`). If this condition is met, `_can_intervene_distraction` is called.
(`service.py:366-371`)

The Lua script (`graph.py:70-78`) executes atomically in Redis's single-threaded VM:

```lua
local in_cooldown = redis.call('EXISTS', KEYS[1])   -- tutor_cooldown:{id}
if in_cooldown == 1 then return 'cooldown' end
local count = tonumber(redis.call('GET', KEYS[2]))  -- tutor_distraction_count:{id}
or 0
if count >= tonumber(ARGV[1]) then return 'max_reached' end   -- ARGV[1]=3 default
redis.call('INCR', KEYS[2])
redis.call('EXPIRE', KEYS[2], tonumber(ARGV[2]))   -- ARGV[2]=86400
return 'ok'
```

Returns `True` only on `b"ok"` or `"ok"` (`graph.py:151`). Any Redis error returns `False`
(fail-closed, `graph.py:152-156`).

### 5d. Cooldown enforcement

Cooldown key `tutor_cooldown:{session_id}` is **set by `intervening_node`** (not by the Lua
script). The Lua script only checks `EXISTS`. The cooldown TTL is
`settings.intervention_cooldown_seconds` (default 120 s, env var `INTERVENTION_COOLDOWN_SECONDS`,
`config.py:309`). Written with `nx=True` (`graph.py:250`) so a concurrent intervention cannot
reset an already-running cooldown.

### 5e. Dispatch and WS delivery

```
→ _segment_intervention_messages(session_id, redis)         [service.py:382]
    reads lesson_package:{session_id}, finds segment by index, returns {type: [msgs]}
→ dispatch_event(session_id, "distraction_detected",
                 payload={"intervention_messages": seg_msgs}) [service.py:383-387]
→ route_from_teaching returns "intervening"                  [graph.py:365-369]
→ intervening_node:
    → sets tutor_cooldown:{id} TTL=120s nx=True             [graph.py:250]
    → picks first message from messages["distraction"]      [graph.py:256-257]
    → asyncio.create_task(write_intervention_event(...))    [graph.py:269-280]
    → persists INTERVENING state                            [graph.py:282]
→ dispatch_event sends state_change WS message              [graph.py:596-608]
→ if current_state=="INTERVENING" and msg:
    manager.send(session_id, {"type":"tutor_intervene",
                              "payload": {"type":"distraction","message":msg}})
                                                            [service.py:393-411]
```

WS delivery is best-effort (`service.py:408-411`): a delivery failure is logged at EXCEPTION
level but never raises, so the signal processing path always completes.

---

## 6. Fatigue Trigger Lifecycle (end-to-end)

### 6a. Duration floor (900 s default)

Fatigue evaluation only runs when `state_raw == "TEACHING" and not intervention_dispatched`
(`service.py:419`).

```
→ redis.get(f"session:{session_id}:session_start_ts")       [service.py:421]
→ if None: logger.warning + SKIP fatigue for entire session [service.py:424-429]   ← D61
→ duration_s = time.time() - float(session_start_ts_raw)    [service.py:432]
→ if duration_s < ces_fatigue_min_session_seconds: SKIP     [service.py:435]
```

Default `ces_fatigue_min_session_seconds` = 900 (15 min), env var
`CES_FATIGUE_MIN_SESSION_SECONDS`, `config.py:248`.

### 6b. Primary trigger (blink + head_pose both low, 2 windows)

```python
blink_hist  = await redis.lrange(f"session:{id}:blink_history",     0, 1)  # at most 2
hp_hist     = await redis.lrange(f"session:{id}:head_pose_history",  0, 1)
primary_trigger = (
    len(blink_hist) >= 2
    and all(float(v) < settings.ces_fatigue_blink_threshold     for v in blink_hist)
    and len(hp_hist)  >= 2
    and all(float(v) < settings.ces_fatigue_head_pose_threshold for v in hp_hist)
)
```

(`service.py:437-454`)

Defaults: `ces_fatigue_blink_threshold` = 0.3 (`config.py:228`),
`ces_fatigue_head_pose_threshold` = 0.3 (`config.py:238`). Both documented per
Schleicher et al. 2008 / Bosch et al. 2015.

The `lrange 0, 1` bound is deliberate per CLAUDE.md unbounded-query rule (comment at
`service.py:436-439`): only the two most recent entries are checked.

### 6c. Exhaustion fallback (all MediaPipe None)

```python
exhaustion_fallback = (
    normalized.blink_rate         is None
    and normalized.head_pose_score is None
    and normalized.behavioral_score is None
)
```

(`service.py:455-459`)

This fires when MediaPipe is completely unavailable (e.g., camera permission revoked,
WASM load failure). Either `primary_trigger or exhaustion_fallback` gates the fatigue
attempt.

### 6d. Cooldown check (NEW — S3-52 fix)

`_can_intervene_fatigue(session_id)` (`graph.py:159-196`) checks the cooldown **before**
attempting the once-per-session SET NX:

```
Step 1: EXISTS tutor_cooldown:{session_id}  → return False if cooldown active
Step 2: SET NX tutor_fatigue_fired:{session_id} "1" ex=86400
        → returns True only for the first (winning) caller
```

The EXISTS→SET-NX pair is NOT fully atomic (two Redis round-trips). A documented race
window of < 1 ms exists where a concurrent `intervening_node` could set the cooldown key
between steps 1 and 2, allowing fatigue and a new intervention to both start. This is
accepted per S3-52 Scale & Load §6 (`graph.py:178-180`); the SET NX in step 2 is still
atomic so fatigue can only fire once per session regardless.

### 6e. Once-per-session gate (SET-NX)

`SET NX tutor_fatigue_fired:{session_id}` returns `True` only for the first caller.
All subsequent calls return `None` (not `True`), so `_can_intervene_fatigue` returns
`False` for all later attempts (`graph.py:195-196`). The flag is set with `ex=_STATE_TTL`
(86400 s).

**Note:** The flag is written by `_can_intervene_fatigue`, NOT separately by
`intervening_node`. The docstring at `graph.py:243-244` is explicit: callers must not
re-write the key after this function returns `True`.

### 6f. Dispatch and WS delivery

```
→ _segment_intervention_messages(session_id, redis)         [service.py:473]
→ dispatch_event(session_id, "fatigue_detected",
                 payload={"intervention_messages": seg_msgs}) [service.py:474-478]
→ _EVENT_INTERVENTION_TYPE["fatigue_detected"] = "fatigue"  [graph.py:84-88]
→ route_from_teaching returns "intervening"                  [graph.py:371-373]
→ intervening_node: sets cooldown, picks messages["fatigue"][0]
→ asyncio.create_task(write_intervention_event(type="fatigue"))
→ dispatch_event sends state_change WS message
→ if current_state=="INTERVENING" and msg:
    manager.send({"type":"tutor_intervene",
                  "payload": {"type":"fatigue", "message":msg}})
                                                            [service.py:485-501]
```

---

## 7. State Machine Guard Rules

**File:** `apps/api/app/modules/tutor/state_machine/graph.py`

### 7a. What TEACHING state allows

Inbound events routed from TEACHING (`route_from_teaching`, `graph.py:360-385`):

| Event | Next state | Guard enforced by |
|-------|-----------|-------------------|
| `distraction_detected` | INTERVENING | `_can_intervene_distraction` Lua in service.py before dispatch |
| `fatigue_detected` | INTERVENING | `_can_intervene_fatigue` SET-NX in service.py before dispatch |
| `segment_complete` | CHECKING_IN | none (always allowed) |
| `quiz_trigger` | QUIZZING | none (always allowed) |
| `lesson_complete` | SESSION_END | none (always allowed) |
| anything else | TEACHING (stay) | default fallthrough |

### 7b. What QUIZZING/INTERVENING blocks

`process_attention_signal` reads `tutor_state:{session_id}` as its **first** action
(`service.py:294`). CES computation and history writes run ONLY when `state_raw == "TEACHING"`
(`service.py:299`). In QUIZZING or INTERVENING, the entire CES block is skipped and
`ces=0.0`, `intervention_dispatched=False` are returned immediately (after the QUIZZING
deadline check at `service.py:507`).

Accumulating CES history in non-TEACHING states would create false low-CES pairs and
trigger spurious interventions when TEACHING resumes. This is documented at `service.py:292-297`
(D14 comment).

### 7c. TEACH_BACK — never interrupted

`route_from_teach_back` (`graph.py:404-417`) is the authoritative enforcement:

```python
if event == "teachback_complete":
    return "teaching"
if event == "teachback_failed":
    return "intervening"
return "teach_back"   # guard: interventions blocked during teach-back
```

Any event not listed — including `distraction_detected` and `fatigue_detected` — causes the
FSM to stay in `TEACH_BACK`. This is the routing-level enforcement of the CLAUDE.md §10 rule
"NEVER interrupt mid-TEACH_BACK" (`graph.py:407-408`).

---

## 8. Intervention Cooldown — 2-Minute Window

**Key:** `tutor_cooldown:{session_id}`

**Written by:** `intervening_node` (`graph.py:249-250`):
```python
await redis.set(cooldown_key, "1", ex=settings.intervention_cooldown_seconds, nx=True)
```

`nx=True` means the first intervention to set the key wins; a concurrent intervention
cannot reset the TTL and shorten the window.

**Checked by:**
- `_can_intervene_distraction` Lua script (`graph.py:71-72`): `EXISTS` check is atomic.
- `_can_intervene_fatigue` (`graph.py:191`): separate `await redis.exists(cooldown_key)`.

**Default duration:** 120 seconds (2 min), env var `INTERVENTION_COOLDOWN_SECONDS`
(`config.py:309-311`).

---

## 9. Distraction Cap — Maximum 3 Per Session

**Key:** `tutor_distraction_count:{session_id}` (string int, 24 h TTL)

**Checked and incremented atomically** by the `_DISTRACTION_GUARD_LUA` script
(`graph.py:70-78`) in a single `redis.eval()` call (`graph.py:143-151`).

**Default cap:** 3, env var `MAX_DISTRACTION_PER_SESSION` (`config.py:313-315`).

The count is NOT decremented when a session resumes from TEACH_BACK or CHECKING_IN.
It only resets when `_init_session_state` deletes `tutor_distraction_count:{session_id}`
at WS connect time (`websocket.py:237`).

**Persistence across Redis restart:** `_get_distraction_count` (`assessment/service.py:1415-1443`)
reconstructs the count from `session_events` table on a Redis cache miss. However, this
function is only defined in assessment/service.py and there is no evidence it is called
during the live intervention path — the Lua script reads directly from Redis.

---

## 10. Session End — Report Fields

`session_end_node` (`graph.py:335-354`) calls `_finalize_session` via `asyncio.create_task`
(fire-and-forget, never blocks the FSM transition).

### 10a. `ces_history_summary` (D18 / S3-50)

**File:** `assessment/service.py:993-1018` — built inside `get_session_report`.

Reads `session:{session_id}:ces_history` (lrange 0, 9, bounded to 10 entries). Returns:
```json
{
  "mean": <float, 2 d.p.>,
  "min": <float, 2 d.p.>,
  "max": <float, 2 d.p.>,
  "window_count": <int>
}
```
Returns `None` if Redis is unavailable or history is empty.

### 10b. `intervention_messages_used` (D19 / S3-51)

**File:** `assessment/service.py:1053` — set to `interventions_count`.

`interventions_count` is a COUNT query on `session_events` where `event_type =
'intervention_triggered'` (`assessment/service.py:879-888`). This counts both distraction
and fatigue interventions together.

### 10c. `ces_breakdown` per signal

**File:** `assessment/service.py:910-917`, delegating to `_build_ces_breakdown`
(`assessment/service.py:715-756`).

Per-signal averages for behavioral/head_pose/blink are read from Redis per-signal history
keys via `_signal_avg` (`assessment/service.py:896-904`). Quiz accuracy comes from DB
`quiz_attempts`. Teachback score comes from DB `teachback_attempts`.

**When `teachback_normalised` is None** (no teach-back attempts in the session):
`_build_ces_breakdown` redistributes the teachback weight using
`remaining = 1.0 - ces_weight_teachback`. Each remaining signal's contribution uses
`signal * (nominal_weight / remaining) * 100` (`assessment/service.py:750-755`).

### 10d. `formula_applied` and `signal_coverage`

**File:** `assessment/service.py:873-876`.
```python
formula_applied = "teachback_redistributed_4_signal" if teachback_score is None else "full_5_signal"
signal_coverage = 4 if teachback_score is None else 5
```

### 10e. `ces_final` write

`_finalize_session` (`graph.py:660-714`) computes `ces_final` as the mean of the
`ces_history` values (lrange 0, 9, at most 10 entries), rounded to 2 d.p. Returns `0.0`
on empty history. Writes to `sessions.ces_final` and `sessions.ended_at` via
`asyncio.to_thread`.

**D62:** `compute_ces_from_session_aggregates` (`assessment/service.py:677-712`) is defined
but never called in production. `_finalize_session` uses its own inline averaging with
different `None`-handling semantics (returns `0.0` for empty history instead of `None` for
fewer than 5 windows). These two implementations diverge silently.

---

## 11. All 20 Live-Learner Scenarios — Coverage Table

| # | Scenario | Implemented | File:Function | Test | Status |
|---|----------|-------------|---------------|------|--------|
| 1 | TEACHING, all signals present, CES > 50 → no intervention | Yes | `service.py:344-366` | `test_two_below_threshold_no_cooldown_dispatches` (checks inverse) | Green (D30 fix) |
| 2 | TEACHING, first window below threshold → no intervention (history count < 2) | Yes | `service.py:344` — `len(history_raw) >= 2` gate | No dedicated positive test | Gap |
| 3 | TEACHING, 2 consecutive windows below 50, gap ok, no cooldown, cap not reached → distraction dispatched | Yes | `service.py:362-411`, `graph.py:125-156` | `test_two_below_threshold_no_cooldown_dispatches` (D30 fix) | Partial — WS delivery not tested |
| 4 | TEACHING, 2 low-CES windows, abs(t0-t1) > 10 s (D4 gap fails) → no intervention | Yes | `service.py:362` | `test_s3_52_ces_production_hardening.py` (D65 partial) | Green |
| 5 | TEACHING, 2 low-CES windows, cooldown active → Lua returns "cooldown" → no intervention | Yes | `graph.py:71-72`, `service.py:371` | `test_intervention_delivers_tutor_intervene_message` (mock path) | Partial — mock-backed |
| 6 | TEACHING, 2 low-CES windows, cap at 3 → Lua returns "max_reached" → no intervention | Yes | `graph.py:73-74` | No dedicated test | **Gap — D65** |
| 7 | QUIZZING state + incoming attention_signal → CES monitoring skipped, no writes | Yes | `service.py:299` — `if state_raw == "TEACHING"` guard | `test_s3_52_ces_production_hardening.py` (D65 partial) | Green |
| 8 | INTERVENING state + low CES → CES monitoring skipped | Yes | `service.py:299` | `test_s3_52_ces_production_hardening.py` | Green |
| 9 | TEACH_BACK state + distraction_detected event dispatched externally → FSM stays in TEACH_BACK | Yes | `graph.py:404-417` (`route_from_teach_back` default) | No dedicated test | **Gap** |
| 10 | TEACH_BACK state + fatigue_detected → FSM stays in TEACH_BACK | Yes | `graph.py:416` (default return "teach_back") | No dedicated test | **Gap — D65** |
| 11 | teachback_score=None → 4-signal weight redistribution → CES computable, higher per-signal weight | Yes | `service.py:130-136` (live); `ces.py:60-74` (test/report) | `test_ces_breakdown_sum_approx_ces_score_teachback_none` | Green |
| 12 | quiz_accuracy=None, MediaPipe signals present → live-session: 0.35 weight redistributed; report: 0.0 with weight retained | Yes (divergent) | `service.py:132` (drops None); `ces.py:55` (treats as 0.0) | `test_ces_breakdown_sum_approx_ces_score_all_signals_present` | Partial — divergence not tested |
| 13 | Session duration < 15 min → fatigue check not evaluated | Yes | `service.py:435` — `duration_s >= settings.ces_fatigue_min_session_seconds` | No dedicated test | **Gap** |
| 14 | Duration >= 15 min + blink_hist & hp_hist both have ≥ 2 entries all < 0.3 → primary fatigue trigger | Yes | `service.py:445-454` | No dedicated test for positive path | **Gap — D65** |
| 15 | Duration >= 15 min + all MediaPipe None → exhaustion fallback → fatigue dispatched | Yes | `service.py:455-459` | No dedicated test | **Gap** |
| 16 | Fatigue conditions met + cooldown active (recent distraction < 2 min) → `_can_intervene_fatigue` step 1 returns False | Yes | `graph.py:191` | No dedicated test | **Gap** |
| 17 | Fatigue conditions met, already fired once → SET NX returns None → blocked | Yes | `graph.py:195-196` | No dedicated test | **Gap** |
| 18 | `session_start_ts` missing in Redis → D61: logger.warning + fatigue detection silently disabled | Yes (partial) | `service.py:424-429` | No test — DISCIPLINE only | **Gap — D61** |
| 19 | Distraction already dispatched this window → `intervention_dispatched=True` → fatigue block not reached | Yes | `service.py:419` — `not intervention_dispatched` guard | No dedicated test for this guard | **Gap** |
| 20 | lesson_complete → SESSION_END → `_finalize_session` writes ces_final + ended_at; session report returns ces_history_summary | Yes | `graph.py:335-354`, `assessment/service.py:993-1018` | `test_write_intervention_event_is_importable` (AC1 only) | Partial |

**Legend:** Green = passing CI test; Partial = tested but with gaps or mock-backed; Gap = no test covering the scenario.

---

## 12. Known Limitations and Registered Defects

### D61 — `session_start_ts` missing silently disables fatigue for entire session

**Status:** OPEN · **Owner:** Dev 4

If Redis is unavailable when `_init_session_state` runs (WS connect time), the
`session:{id}:session_start_ts` key is never set. `process_attention_signal` (`service.py:422-429`)
checks `if session_start_ts_raw is not None` and emits only a `logger.warning` before
skipping the entire fatigue block for the rest of the session. No error is raised, CES
reports look normal, and the student never receives a fatigue intervention.

**Partial fix implemented:** `logger.warning` added at `service.py:425-429`.
**Full fix needed:** fall back to `sessions.started_at` from DB when the Redis key is absent.
**Enforcement:** `DISCIPLINE` — the warning is not machine-checked.

### D62 — `compute_ces_from_session_aggregates` is dead code; `_finalize_session` has divergent inline implementation

**Status:** OPEN · **Owner:** Dev 3

`assessment/service.py:677-712` defines `compute_ces_from_session_aggregates` but no
production call site exists. `_finalize_session` (`graph.py:668-688`) has its own inline
averaging that returns `0.0` for empty history (not `None` for < 5 windows, which would
be the appropriate signal of insufficient data). A student ending a session with fewer than
5 CES windows gets `ces_final = 0.0` — indistinguishable from zero engagement.

**Fix:** Wire `_finalize_session` to call `compute_ces_from_session_aggregates` and handle
the `None` → `0.0` mapping explicitly with a log entry.
**Enforcement:** `DISCIPLINE` — no CI guard prevents the divergence widening.

### D63 — `_get_distraction_count` is dead code; `dna_fusion.py` wiring was never completed

**Status:** OPEN · **Owner:** Dev 3

`assessment/service.py:1415-1443` defines `_get_distraction_count` but `dna_fusion.py`
contains no import or call to it. The function was specified to be wired into
`fuse_learner_dna()` in Story S3-36 (Task 3.2–3.3). It is tested in isolation but the
production call site was never connected. As a result, `frustration_tolerance` in Learner
DNA does not reflect live distraction counts.

**Enforcement:** `DISCIPLINE` — import graphs are not CI-checked.

### D64 — Per-signal Redis history keys have no TTL

**Status:** OPEN · **Owner:** Dev 3/Dev 4

`process_attention_signal` writes `behavioral_history`, `head_pose_history`, and
`blink_history` (`service.py:320-336`) with LPUSH and LTRIM but without `EXPIRE`.
`ces_history` correctly receives `expire(_CES_WINDOW_TTL)` at `service.py:315`.

The per-signal history keys persist until Redis eviction. On Railway Redis (64 MB limit),
orphaned keys from sessions that never reach `SESSION_END` accumulate without bound.

**Fix:** Add `await redis.expire(f"session:{session_id}:{signal}_history", _CES_WINDOW_TTL)`
after each `ltrim` call in `tutor/service.py:322`, `330`, `336`.
**Enforcement:** `DISCIPLINE`.

### D65 — Distraction trigger path has zero unit test coverage for positive case

**Status:** PARTIALLY FIXED (S3-52) · **Owner:** Dev 4

The distraction trigger (`service.py:344-411`) — 2 consecutive low-CES windows →
`dispatch_event("distraction_detected")` — has no unit test for the positive trigger path.
The Lua atomic guard, cooldown check, distraction cap, and D4 gap/stale-history check are
all live code. The same gap covers: cap exhaustion (Scenario 6), TEACH_BACK blocking
scenarios (Scenarios 9-10), and fatigue-after-distraction-in-same-window (Scenario 19).

**S3-52 fix:** `tests/test_s3_52_ces_production_hardening.py` covers:
- D4 stale gap check non-dispatch path
- QUIZZING and INTERVENING state blocks
- Per-signal history not written in QUIZZING

**Remaining gap:** The positive distraction trigger path (TEACHING + 2 low-CES + gap_ok →
`_can_intervene_distraction` → dispatch) has no test. Write
`tests/test_distraction_trigger.py` covering the positive path and the Lua guard.
**Enforcement:** `DISCIPLINE` — the missing test file is absent, not a failing test.

---

### Undocumented divergence (not yet registered)

**Two `compute_ces` implementations with contradictory `quiz_accuracy=None` semantics:**

| Aspect | `tutor/service.py:107` (live session) | `assessment/ces.py:19` (report/test) |
|--------|--------------------------------------|--------------------------------------|
| `quiz_accuracy=None` | Weight redistributed to other present signals | Treated as 0.0, full weight retained |
| `behavioral/head_pose/blink=None` | Any or all may be None; weight redistributed | Required floats (no None in signature) |
| Result rounding | No rounding, only `min/max` clamp | `round(raw * 100, 4)` |

During a live session, a student who has not yet taken a quiz receives a higher CES than
the session report will later show — the live path redistributes the 0.35 quiz weight
upward, reducing the probability of intervention, while the report path assigns 0.0 with
full 0.35 weight, producing a lower displayed score for the same inputs.

This divergence should be registered as a defect (candidate for D66) before Sprint 3
calibration; any threshold tuning done against session report CES values will not predict
live-session intervention behaviour.
