# CES Lifecycle — Live Learner Journey

> **Accuracy contract:** Every claim in this document cites an exact `file:line` read on
> 2026-08-13. Where behaviour changed in Phase 2 (S3-53), both the old and new behaviour are
> stated. A QA engineer should be able to derive integration test assertions from this document
> without reading source code.
>
> **Last updated:** 2026-08-13 — incorporates S3-53 Phase 2 fixes:
> `lesson_complete` dispatch from frontend, `ces_score: float | None` API change,
> color-coded CES display, `_finalize_session` returning `None` (not `0.0`) for empty history,
> and the `quiz_accuracy=None` formula convergence between both implementations.

---

## 1. Session Initialization

**Entry point:** `apps/api/app/core/websocket.py:138` — `websocket_endpoint` route (`/ws/{session_id}`).

### 1a. WebSocket connect

`manager.connect()` (`websocket.py:65`) is called after UUID-format validation (`websocket.py:145-147`). It delegates to `_restore_or_init_session` (`websocket.py:189`).

**Reconnect path** (`websocket.py:204-209`): if `tutor_state:{session_id}` already exists in Redis, the stored state string is returned and a `state_change` message (from_state == to_state) is pushed to the reconnecting client. `_seed_learner_tier` is also called on reconnect.

**Fresh connect path** (`websocket.py:213`): `_init_session_state` is called.

### 1b. `_init_session_state` (`websocket.py:217-255`)

All writes are best-effort (wrapped in `try/except`). A Redis failure logs a WARNING but does not crash the WS accept handshake.

| Redis key | Value | TTL | Line |
|-----------|-------|-----|------|
| `tutor_state:{session_id}` | `"IDLE"` | 86400 s | 236 |
| `tutor_distraction_count:{session_id}` | `"0"` | 86400 s | 237 |
| `tutor_cooldown:{session_id}` | (deleted) | — | 238 |
| `tutor_fatigue_fired:{session_id}` | (deleted) | — | 239 |
| `session:{session_id}:segment_index` | (deleted) | — | 240–242 |
| `session:{session_id}:session_start_ts` | `str(int(time.time()))` | 86400 s | 244–250 |

`session_start_ts` is written with `nx=True` (`websocket.py:249`) so that reconnects do not reset the clock. **D61:** if the write fails (Redis unavailable at connect time), the key is never set and fatigue detection is silently disabled for the entire session (see Section 6a and Section 14).

After the Redis writes, `_seed_learner_tier` (`websocket.py:261-306`) runs: it reads `lesson_package:{session_id}`, extracts `metadata.tier`, and writes `session:{session_id}:learner_tier` and `session:{session_id}:qa_phase_seconds` via a pipeline (transaction=False). Best-effort; a failure does not abort the handshake.

### 1c. session_start event → TEACHING

The client sends `{"type": "session_start", ...}` over the WebSocket. `_handle_session_start` (`websocket.py:312`) is called, which:

1. Optionally writes `session:{session_id}:learner_tier` and `session:{session_id}:qa_phase_seconds` from a `learner_tier` field in the WS payload (`websocket.py:341-365`). This is a WS-payload override of the lesson-package tier seeded at connect time (last-writer-wins caveat at `websocket.py:325-335`).
2. Calls `start_session(session_id)` (`tutor/service.py:184-193`), which calls `dispatch_event(session_id, "session_start")`.
3. `dispatch_event` (`state_machine/graph.py:540-609`) reads the current state from Redis, builds `TutorMachineState`, invokes the compiled LangGraph with `recursion_limit=5` (`graph.py:586`), and sends a `state_change` WS message when the state actually changes (`graph.py:594-608`).
4. `route_from_idle` (`graph.py:428-430`) routes `session_start` → `"teaching"`.
5. `teaching_node` (`graph.py:219-224`) persists `TutorState.TEACHING` to Redis and sets `in_teachback=False`.

**Result after initialization:** `tutor_state:{session_id}` = `"TEACHING"`, all counters reset, `session_start_ts` set, learner tier seeded if lesson package was cached.

---

## 2. Teaching Phase — Every CES Window (5-second cadence)

**Entry:** `websocket.py:162-163` — inbound `attention_signal` message → `_handle_attention_signal` → `process_attention_signal(session_id, signal)` (`tutor/service.py:271`).

`process_attention_signal` is the **only** function that computes CES and evaluates intervention triggers. Its full step-by-step logic:

```
Step 1  Read tutor_state:{session_id} from Redis                [service.py:294]
Step 2  If state == "TEACHING":
          a. Parse & validate signal → NormalizedSignal          [service.py:300]
          b. Compute CES float (0-100)                           [service.py:301]
          c. Write ces_window + tutor_ces keys                   [service.py:303-308]
          d. LPUSH + LTRIM + EXPIRE ces_history (cap=10)         [service.py:312-315]
          e. Write per-signal histories (no TTL — D64)           [service.py:320-336]
          f. Read back history (lrange 0..9)                     [service.py:340-342]
          g. If len(history) >= 2: run distraction check         [service.py:344-411]
Step 3  If state == "TEACHING" AND no intervention dispatched:
          a. Read session_start_ts                               [service.py:421]
          b. If not None: compute duration                       [service.py:432]
          c. If duration >= 900s: run fatigue check              [service.py:435-502]
Step 4  If state == "QUIZZING": check Q&A deadline              [service.py:507-514]
Step 5  Return CesResult(session_id, ces, intervention_dispatched)
```

**Security:** `_handle_attention_signal` (`websocket.py:394-415`) sends only an `attention_ack` message back to the client. Raw CES scores are **never** exposed to the client per PRD §18.

---

## 3. CES Formula — Exact Calculation

### 3a. Live-session formula (Implementation B — production path)

**File:** `apps/api/app/modules/tutor/service.py:107-137` — `compute_ces(signal: NormalizedSignal)`

Called by `process_attention_signal` at line 301 on every attention signal during TEACHING state.

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
present = [(v, w) for (v, w) in pairs if v is not None]   # drop None signals
weight_sum = sum(w for _, w in present)
if weight_sum <= 0:
    return 0.0                                              # all-None exhaustion
CES = sum(v * (w / weight_sum) for v, w in present) * 100.0
return max(0.0, min(100.0, CES))                           # clamp, no rounding
```

**Nominal (all 5 signals present):**
```
CES = (quiz×0.35 + tb×0.25 + beh×0.20 + hp×0.12 + blink×0.08) × 100
```

### 3b. Report/test formula (Implementation A — `assessment/ces.py`)

**File:** `apps/api/app/modules/assessment/ces.py:compute_ces()`

Used by assessment module, Learner DNA, and the session report's `_build_ces_breakdown`. All 5 signals follow the same redistribution rule as Implementation B. **As of S3-53, both implementations agree on `None`-handling:**

- `teachback_score=None` → weight redistributed proportionally across the remaining present signals
- `quiz_accuracy=None` → weight redistributed proportionally (same as live-session path)
- `behavioral/head_pose/blink=None` → weight redistributed proportionally

**Before S3-53:** Implementation A treated `quiz_accuracy=None` as `0.0` with full weight retained (no redistribution), creating a divergence from the live-session path. This meant a student who had not yet taken a quiz would have a higher live-session CES than their session report would later show. **This divergence was resolved in S3-53** — both implementations now redistribute.

### 3c. `teachback_score=None` — weight redistribution (both implementations)

When `teachback_score` is None, the 0.25 weight is dropped from `present` and the remaining weights (`0.35 + 0.20 + 0.12 + 0.08 = 0.75`) become the denominator. Effective weights:

| Signal | Effective weight | Points at signal=1.0 |
|--------|-----------------|----------------------|
| quiz | 0.35/0.75 = 0.4667 | 46.67 |
| behavioral | 0.20/0.75 = 0.2667 | 26.67 |
| head_pose | 0.12/0.75 = 0.1600 | 16.00 |
| blink | 0.08/0.75 = 0.1067 | 10.67 |

This matches PRD §11 redistributed formula exactly.

### 3d. `quiz_accuracy=None` — weight redistribution (S3-53 fix)

When `quiz_accuracy` is None (student has not yet attempted a quiz in this session), the 0.35 weight is redistributed across the remaining present signals. A student entering their first segment with no quiz history will have CES computed from the 4 behavioral signals only, with proportionally scaled weights.

**Before S3-53:** Implementation A (`assessment/ces.py`) treated this as `0.0` with full 0.35 weight retained, creating a divergence. Now both implementations redistribute.

### 3e. MediaPipe frame drop (behavioral/head_pose/blink = None)

In both implementations, `behavioral_score`, `head_pose_score`, and `blink_rate` may be `None` (camera not visible, WASM stutter — D13). Each `None` is silently dropped from `present` and the remaining weights scale up accordingly.

### 3f. All signals `None` — exhaustion path

If all 5 signals are `None`: `weight_sum=0` → `compute_ces` returns `0.0` (`service.py:134-135`).

This all-None condition is also the **exhaustion fallback** for the fatigue trigger (Section 6c). It does NOT mean CES = 0 for intervention purposes — it means CES computation was impossible, not that the student is disengaged.

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

**D64:** `behavioral_history`, `head_pose_history`, and `blink_history` have no `EXPIRE` call. `ces_history` correctly gets `expire(_CES_WINDOW_TTL)` at `service.py:315`. The per-signal keys persist until Redis eviction.

**History entry format:** `{"v": <CES float>, "t": <Unix seconds int>}`. Legacy bare-float strings are accepted by a backward-compat fallback (`service.py:348-356`); they produce `t=0` which causes the D4 gap check to always fail for that pair — fail-closed, no false interventions on mixed old/new history.

---

## 5. Distraction Trigger Lifecycle (end-to-end)

### 5a. Prerequisite checks

```
→ state_raw == "TEACHING"            [service.py:299]
→ _parse_signal succeeds             [service.py:300]
→ compute_ces returns float          [service.py:301]
→ Redis history written              [service.py:303-336]
→ lrange history read                [service.py:340-342]
→ len(history_raw) >= 2              [service.py:344]
```

If any step fails or the length check fails, the distraction path is skipped entirely and `intervention_dispatched` remains `False`.

### 5b. D4 timestamp gap check

```python
v0, t0 = parse(history_raw[0])    # most recent (LPUSH prepends)
v1, t1 = parse(history_raw[1])    # second most recent
gap_ok = abs(t0 - t1) <= 2 * settings.ces_cadence_seconds   # default: <= 10 s
```

`ces_cadence_seconds` default = 5 (`config.py:256`), so the tolerance window is 10 seconds. Pairs outside this window are treated as stale (MediaPipe restart, browser tab switch). A corrupt entry produces `t=0`, making `abs(now - 0)` >> 10 s — always failing the check. (`service.py:358-362`)

### 5c. Lua atomic guard (`_can_intervene_distraction`)

Condition: `gap_ok AND v0 < ces_threshold AND v1 < ces_threshold` (default threshold = 50.0, `config.py:224`). If this condition is met, `_can_intervene_distraction` is called. (`service.py:366-371`)

The Lua script (`graph.py:70-78`) executes atomically in Redis's single-threaded VM:

```lua
local in_cooldown = redis.call('EXISTS', KEYS[1])   -- tutor_cooldown:{id}
if in_cooldown == 1 then return 'cooldown' end
local count = tonumber(redis.call('GET', KEYS[2]))  -- tutor_distraction_count:{id}
or 0
if count >= tonumber(ARGV[1]) then return 'max_reached' end   -- ARGV[1]=3 default
redis.call('INCR', KEYS[2])
redis.call('EXPIRE', KEYS[2], tonumber(ARGV[2]))    -- ARGV[2]=86400
return 'ok'
```

Returns `True` only on `b"ok"` or `"ok"` (`graph.py:151`). Any Redis error returns `False` (fail-closed, `graph.py:152-156`).

### 5d. Cooldown enforcement

Cooldown key `tutor_cooldown:{session_id}` is **set by `intervening_node`** (not by the Lua script). The Lua script only checks `EXISTS`. TTL = `settings.intervention_cooldown_seconds` (default 120 s). Written with `nx=True` (`graph.py:250`) so a concurrent intervention cannot reset an already-running cooldown.

### 5e. Dispatch and WS delivery

```
→ _segment_intervention_messages(session_id, redis)          [service.py:382]
    reads lesson_package:{session_id}, finds segment by index
→ dispatch_event(session_id, "distraction_detected",
                 payload={"intervention_messages": seg_msgs}) [service.py:383-387]
→ route_from_teaching returns "intervening"                  [graph.py:365-369]
→ intervening_node:
    → sets tutor_cooldown:{id} TTL=120s nx=True              [graph.py:250]
    → picks first message from messages["distraction"]       [graph.py:256-257]
    → asyncio.create_task(write_intervention_event(...))     [graph.py:269-280]
    → persists INTERVENING state                             [graph.py:282]
→ dispatch_event sends state_change WS message               [graph.py:596-608]
→ if current_state=="INTERVENING" and msg:
    manager.send(session_id, {"type":"tutor_intervene",
                              "payload":{"type":"distraction","message":msg}})
                                                             [service.py:393-411]
```

WS delivery is best-effort (`service.py:408-411`): a failure is logged at EXCEPTION level but never raises, so the signal processing path always completes.

---

## 6. Fatigue Trigger Lifecycle (end-to-end)

### 6a. Duration floor (900 s default)

Fatigue evaluation only runs when `state_raw == "TEACHING" and not intervention_dispatched` (`service.py:419`).

```
→ redis.get(f"session:{session_id}:session_start_ts")        [service.py:421]
→ if None: logger.warning + SKIP fatigue for entire session  [service.py:424-429]  ← D61
→ duration_s = time.time() - float(session_start_ts_raw)     [service.py:432]
→ if duration_s < ces_fatigue_min_session_seconds: SKIP      [service.py:435]
```

Default `ces_fatigue_min_session_seconds` = 900 (15 min), env var `CES_FATIGUE_MIN_SESSION_SECONDS`, `config.py:248`.

### 6b. Primary trigger (blink + head_pose both low, 2 windows)

```python
blink_hist  = await redis.lrange(f"session:{id}:blink_history",    0, 1)   # at most 2
hp_hist     = await redis.lrange(f"session:{id}:head_pose_history", 0, 1)
primary_trigger = (
    len(blink_hist) >= 2
    and all(float(v) < settings.ces_fatigue_blink_threshold     for v in blink_hist)
    and len(hp_hist)  >= 2
    and all(float(v) < settings.ces_fatigue_head_pose_threshold for v in hp_hist)
)
```

(`service.py:437-454`)

Defaults: `ces_fatigue_blink_threshold` = 0.3 (`config.py:228`), `ces_fatigue_head_pose_threshold` = 0.3 (`config.py:238`). Both documented per Schleicher et al. 2008 / Bosch et al. 2015.

`lrange 0, 1` bound is deliberate per CLAUDE.md unbounded-query rule: only the two most recent entries are checked.

### 6c. Exhaustion fallback (all MediaPipe None)

```python
exhaustion_fallback = (
    normalized.blink_rate         is None
    and normalized.head_pose_score is None
    and normalized.behavioral_score is None
)
```

(`service.py:455-459`)

Fires when MediaPipe is completely unavailable (camera permission revoked, WASM load failure). Either `primary_trigger or exhaustion_fallback` gates the fatigue attempt.

### 6d. Cooldown check (S3-52 fix)

`_can_intervene_fatigue(session_id)` (`graph.py:159-196`) checks the cooldown **before** attempting the once-per-session SET-NX:

```
Step 1: EXISTS tutor_cooldown:{session_id}  → return False if cooldown active
Step 2: SET NX tutor_fatigue_fired:{session_id} "1" ex=86400
        → returns True only for the first (winning) caller
```

The EXISTS → SET-NX pair is NOT fully atomic (two Redis round-trips). A documented race window of < 1 ms exists where a concurrent `intervening_node` could set the cooldown key between steps 1 and 2, allowing fatigue and a new intervention to both start. Accepted per S3-52 Scale & Load §6; the SET-NX in step 2 is still atomic so fatigue can only fire once per session regardless.

### 6e. Once-per-session gate (SET-NX)

`SET NX tutor_fatigue_fired:{session_id}` returns `True` only for the first caller. All subsequent calls return `None`, so `_can_intervene_fatigue` returns `False` for all later attempts (`graph.py:195-196`). The flag is set with `ex=_STATE_TTL` (86400 s).

**Note:** The flag is written by `_can_intervene_fatigue`, NOT separately by `intervening_node`. Callers must not re-write the key after this function returns `True`.

### 6f. Dispatch and WS delivery

```
→ _segment_intervention_messages(session_id, redis)          [service.py:473]
→ dispatch_event(session_id, "fatigue_detected",
                 payload={"intervention_messages": seg_msgs}) [service.py:474-478]
→ _EVENT_INTERVENTION_TYPE["fatigue_detected"] = "fatigue"  [graph.py:84-88]
→ route_from_teaching returns "intervening"                  [graph.py:371-373]
→ intervening_node: sets cooldown, picks messages["fatigue"][0]
→ asyncio.create_task(write_intervention_event(type="fatigue"))
→ dispatch_event sends state_change WS message
→ if current_state=="INTERVENING" and msg:
    manager.send({"type":"tutor_intervene",
                  "payload":{"type":"fatigue","message":msg}})
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

`process_attention_signal` reads `tutor_state:{session_id}` as its first action (`service.py:294`). CES computation and history writes run ONLY when `state_raw == "TEACHING"` (`service.py:299`). In QUIZZING or INTERVENING, the entire CES block is skipped and `ces=0.0`, `intervention_dispatched=False` are returned immediately. This prevents accumulating false low-CES pairs that would trigger spurious interventions when TEACHING resumes (D14, `service.py:292-297`).

### 7c. TEACH_BACK — never interrupted

`route_from_teach_back` (`graph.py:404-417`) is the authoritative enforcement:

```python
if event == "teachback_complete":
    return "teaching"
if event == "teachback_failed":
    return "intervening"
return "teach_back"   # guard: interventions blocked during teach-back
```

Any event not listed — including `distraction_detected` and `fatigue_detected` — causes the FSM to stay in `TEACH_BACK`. This is the routing-level enforcement of the CLAUDE.md §10 rule "NEVER interrupt mid-TEACH_BACK" (`graph.py:407-408`).

---

## 8. Intervention Cooldown — 2-Minute Window

**Key:** `tutor_cooldown:{session_id}`

**Written by:** `intervening_node` (`graph.py:249-250`):
```python
await redis.set(cooldown_key, "1", ex=settings.intervention_cooldown_seconds, nx=True)
```

`nx=True` means the first intervention to set the key wins; a concurrent intervention cannot reset the TTL.

**Checked by:**
- `_can_intervene_distraction` Lua script (`graph.py:71-72`): `EXISTS` check is atomic.
- `_can_intervene_fatigue` (`graph.py:191`): separate `await redis.exists(cooldown_key)`.

**Default duration:** 120 seconds (2 min), env var `INTERVENTION_COOLDOWN_SECONDS` (`config.py:309-311`).

---

## 9. Distraction Cap — Maximum 3 Per Session

**Key:** `tutor_distraction_count:{session_id}` (string int, 24 h TTL)

**Checked and incremented atomically** by the `_DISTRACTION_GUARD_LUA` script (`graph.py:70-78`) in a single `redis.eval()` call (`graph.py:143-151`).

**Default cap:** 3, env var `MAX_DISTRACTION_PER_SESSION` (`config.py:313-315`).

The count is NOT decremented when a session resumes from TEACH_BACK or CHECKING_IN. It only resets when `_init_session_state` deletes `tutor_distraction_count:{session_id}` at WS connect time (`websocket.py:237`).

---

## 10. Frontend — lesson_complete Dispatch (Phase 2, S3-53)

**Critical fix landed in S3-53 Phase 2 commit `a12c931`.**

Before this fix, `lesson_complete` was never dispatched from the frontend. This made `_finalize_session` structurally unreachable — `sessions.ces_final` was never written for any session, and `ended_at` was never set.

### 10a. Dispatch location

**File:** `apps/web/src/components/player/AudioTimeline.tsx` (~line 385)

```typescript
} else {
  wsSendControl?.({ type: 'lesson_complete' });  // triggers FSM → SESSION_END
  endLesson();
}
```

This code path is reached when the last segment's audio completes. `wsSendControl` is the WebSocket send handle injected into `AudioTimeline`. It accepts any `LocalControlOut` type.

### 10b. What happens after dispatch

The WS message routes to the backend `_handle_lesson_complete` handler → `dispatch_event(session_id, "lesson_complete")` → `route_from_teaching` returns `"session_end"` → `session_end_node` (`graph.py:335-354`) is called.

`session_end_node` calls `asyncio.create_task(_finalize_session(...))` — fire-and-forget, never blocks the FSM transition.

### 10c. Type contract

`lesson_complete` is a valid `FlowEvent` in `apps/web/src/types/wireTypes.ts:27`. No new types were needed.

---

## 11. Session Finalization — `_finalize_session`

`session_end_node` (`graph.py:335-354`) calls `_finalize_session` via `asyncio.create_task` (fire-and-forget, never blocks the FSM transition).

### 11a. CES averaging

```python
raw_history = await redis.lrange(f"session:{session_id}:ces_history", 0, 9)  # bounded 10
values = []
for entry in raw_history:
    try:
        values.append(float(json.loads(entry)["v"]))
    except Exception:
        pass  # corrupt entry skipped

ces_final: float | None = round(sum(values) / len(values), 2) if values else None
```

(`graph.py:668-690`)

**Key behaviour (S3-53 fix):** `ces_final` is `None` for empty history, NOT `0.0`. An empty history means the session ended before any CES windows were computed (e.g., student left in the first 5 seconds). `None` is semantically correct — no data was collected, not zero engagement.

**Before S3-53:** the code returned `0.0` for empty history, which was indistinguishable from zero engagement and incorrectly shown as `ces_score: 0.0` in the session report.

### 11b. Database write

```python
supabase.table("sessions").update({
    "ces_final": ces_final,      # None or float rounded to 2 d.p.
    "ended_at": ended_at_iso
}).eq("session_id", session_id).execute()
```

Both `sessions.ces_final` (numeric, nullable) and `sessions.ended_at` (timestamptz, nullable) exist in both Supabase projects. **No migration is needed.**

### 11c. Logger format fix (S3-53 fix)

The logger at `graph.py:702` was changed from `"%.2f"` format to `"%s"` format to handle `None` without a `TypeError` crash:
```python
logger.info("_finalize_session: session=%s ces_final=%s", session_id, ces_final)
```

---

## 12. Session Report Fields

### 12a. `ces_score` — nullable (S3-53 Phase 2 fix)

**File:** `apps/api/app/modules/assessment/service.py:943-945`

```python
# None means the session ended before _finalize_session ran (lesson_complete
# not dispatched, or session ended before first CES window).
ces_score: float | None = float(ces_final) if ces_final is not None else None
```

**Before S3-53 Phase 2:** the code substituted `0.0` for None: `float(ces_final) if ces_final is not None else 0.0`. This was silent and misleading — an incomplete session looked like zero engagement.

**API response type:** `ces_score: float | None = None` in `apps/api/app/modules/assessment/router.py:47`.

**Frontend type:** `ces_score: number | null` in `apps/web/src/types/assessment.ts:93`.

### 12b. `ces_history_summary` (D18 / S3-50)

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

### 12c. `intervention_messages_used` (D19 / S3-51)

**File:** `assessment/service.py:1053` — set to `interventions_count`.

`interventions_count` is a COUNT query on `session_events` where `event_type = 'intervention_triggered'` (`assessment/service.py:879-888`). This counts both distraction and fatigue interventions together.

### 12d. `ces_breakdown` per signal

**File:** `assessment/service.py:910-917`, delegating to `_build_ces_breakdown` (`assessment/service.py:715-756`).

Per-signal averages for behavioral/head_pose/blink are read from Redis per-signal history keys via `_signal_avg` (`assessment/service.py:896-904`). Quiz accuracy comes from DB `quiz_attempts`. Teachback score comes from DB `teachback_attempts`.

**When `teachback_normalised` is None:** `_build_ces_breakdown` redistributes the teachback weight using `remaining = 1.0 - ces_weight_teachback`. Each remaining signal's contribution uses `signal * (nominal_weight / remaining) * 100` (`assessment/service.py:750-755`).

**Persistence gap:** `ces_breakdown` is computed from Redis at report fetch time. If Redis keys are flushed or expired between session end and report view (Redis TTL or restart), the per-signal breakdown falls back to zeros. `ces_final` in DB is unaffected. Accepted trade-off for MVP; Sprint 4 candidate to add `ces_breakdown jsonb` column to `sessions`.

### 12e. `formula_applied` and `signal_coverage`

**File:** `assessment/service.py:873-876`.
```python
formula_applied = "teachback_redistributed_4_signal" if teachback_score is None else "full_5_signal"
signal_coverage = 4 if teachback_score is None else 5
```

---

## 13. Frontend CES Display (Phase 2, S3-53)

### 13a. Color thresholds (`cesScoreColor`)

**File:** `apps/web/src/lib/utils.ts:58-63`

```typescript
export function cesScoreColor(cesScore: number | null): string {
    if (cesScore === null || !Number.isFinite(cesScore)) return "text-neutral-400";
    if (cesScore >= 70) return "text-emerald-600 dark:text-emerald-400";
    if (cesScore >= 50) return "text-amber-600 dark:text-amber-400";
    return "text-rose-600 dark:text-rose-400";
}
```

| Score | Color | Meaning |
|-------|-------|---------|
| null / non-finite | neutral-400 (grey) | Session did not produce a final score |
| ≥ 70 | emerald (green) | High engagement |
| 50–69 | amber (yellow) | Moderate engagement |
| < 50 | rose (red) | Low engagement — intervention was likely triggered |

Note: Color thresholds (50, 70) are different from the intervention trigger threshold (50 for distraction), which is deliberate — the report threshold reflects overall session health, not the per-window trigger point.

### 13b. `formatCesLabel` — accepts null (S3-53 fix)

**File:** `apps/web/src/lib/utils.ts:49-56`

```typescript
export function formatCesLabel(cesScore: number | null): string {
    if (cesScore === null) return "Not measured";
    if (!Number.isFinite(cesScore) || cesScore < 0 || cesScore > 100) return "Unknown";
    if (cesScore >= 80) return "Highly Engaged";
    if (cesScore >= 60) return "Well Focused";
    if (cesScore >= 40) return "Getting There";
    return "Room to Grow";
}
```

**Before S3-53:** signature was `(cesScore: number)` — `null` would cause a TypeScript error.

### 13c. Session Report Focus tile

**File:** `apps/web/src/components/reports/SessionReport.tsx:164-176`

```tsx
<div className="flex flex-col gap-1.5 p-5 rounded-2xl bg-white border border-neutral-100 shadow-sm">
  <span className="text-xs font-medium text-neutral-500 uppercase tracking-wider">
    Focus
  </span>
  <span className={`font-medium text-lg ${cesScoreColor(report.ces_score)}`}>
    {formatCesLabel(report.ces_score)}
  </span>
  {report.ces_score !== null && (
    <span className="text-neutral-400 text-xs">
      {Math.round(report.ces_score)}/100
    </span>
  )}
</div>
```

When `ces_score` is null: label shows "Not measured" in neutral grey, no numeric subtitle.
When `ces_score` is non-null: label is color-coded + numeric `/100` subtitle shown below.

---

## 14. All 21 Live-Learner Scenarios — Coverage Table

| # | Scenario | Implemented | File:Function | Test | Status |
|---|----------|-------------|---------------|------|--------|
| 1 | TEACHING, all 5 signals present, CES > 50 → no intervention | Yes | `service.py:344-366` | `test_two_below_threshold_no_cooldown_dispatches` (checks inverse) | Green |
| 2 | TEACHING, first window only (history count < 2) → no intervention | Yes | `service.py:344` — `len(history_raw) >= 2` gate | No dedicated positive test | Gap |
| 3 | TEACHING, 2 consecutive windows below 50, gap ok, no cooldown, cap not reached → distraction dispatched | Yes | `service.py:362-411`, `graph.py:125-156` | `test_two_below_threshold_no_cooldown_dispatches` | Partial — WS delivery not tested |
| 4 | TEACHING, 2 low-CES windows, abs(t0-t1) > 10 s (D4 gap fails) → no intervention | Yes | `service.py:362` | `test_s3_52_ces_production_hardening.py` | Green |
| 5 | TEACHING, 2 low-CES windows, cooldown active → Lua returns "cooldown" → no intervention | Yes | `graph.py:71-72`, `service.py:371` | Mock-backed test | Partial |
| 6 | TEACHING, 2 low-CES windows, distraction cap at 3 → Lua returns "max_reached" → no intervention | Yes | `graph.py:73-74` | No dedicated test | **Gap — D65** |
| 7 | QUIZZING state + incoming attention_signal → CES monitoring skipped, no history writes | Yes | `service.py:299` — TEACHING guard | `test_s3_52_ces_production_hardening.py` | Green |
| 8 | INTERVENING state + low CES → CES monitoring skipped | Yes | `service.py:299` | `test_s3_52_ces_production_hardening.py` | Green |
| 9 | TEACH_BACK state + distraction_detected event → FSM stays in TEACH_BACK | Yes | `graph.py:404-417` (`route_from_teach_back` default) | No dedicated test | **Gap** |
| 10 | TEACH_BACK state + fatigue_detected → FSM stays in TEACH_BACK | Yes | `graph.py:416` (default return "teach_back") | No dedicated test | **Gap — D65** |
| 11 | teachback_score=None → 4-signal redistribution, CES computable | Yes | `service.py:130-136` (live); `ces.py:60-74` (report) | `test_ces_breakdown_sum_approx_ces_score_teachback_none` | Green |
| 12 | quiz_accuracy=None → weight redistributed proportionally (S3-53 fix, both implementations now agree) | Yes | `service.py:132` (drops None); `ces.py:55` (same after S3-53) | `test_quiz_accuracy_none_redistributes_weight` | Green |
| 13 | Session duration < 15 min → fatigue check not evaluated | Yes | `service.py:435` — duration floor | No dedicated test | **Gap** |
| 14 | Duration ≥ 15 min + blink_hist & hp_hist both have ≥ 2 entries all < 0.3 → primary fatigue trigger | Yes | `service.py:445-454` | No dedicated positive test | **Gap — D65** |
| 15 | Duration ≥ 15 min + all MediaPipe None → exhaustion fallback → fatigue dispatched | Yes | `service.py:455-459` | No dedicated test | **Gap** |
| 16 | Fatigue conditions met + cooldown active → `_can_intervene_fatigue` step 1 returns False | Yes | `graph.py:191` | No dedicated test | **Gap** |
| 17 | Fatigue conditions met, already fired once → SET-NX returns None → blocked | Yes | `graph.py:195-196` | No dedicated test | **Gap** |
| 18 | `session_start_ts` missing (D61) → logger.warning + fatigue silently disabled | Yes (partial) | `service.py:424-429` | No machine-checked guard | **Gap — D61** |
| 19 | Distraction dispatched this window → `intervention_dispatched=True` → fatigue block not reached | Yes | `service.py:419` — `not intervention_dispatched` | No dedicated test | **Gap** |
| 20 | lesson_complete dispatched from frontend → SESSION_END → `_finalize_session` writes ces_final (None for empty history) + ended_at | Yes (S3-53 Phase 2 fix) | `AudioTimeline.tsx:~385`, `graph.py:335-354` | `test_finalize_session_empty_history_writes_ces_final_none` | Green |
| 21 | Student views report after session → ces_score is null (not 0.0) if session ended before CES windows → color: neutral-400, label: "Not measured" | Yes (S3-53 Phase 2) | `service.py:943`, `router.py:47`, `SessionReport.tsx:168-175` | `test_session_report_ces_score_null_when_ces_final_none` (if exists) | Partial |

**Legend:** Green = passing CI test; Partial = tested but with gaps or mock-backed; Gap = no test covering the scenario.

---

## 15. Database State — Supabase Audit (2026-08-13)

**Both projects confirmed ACTIVE_HEALTHY, ap-south-1, 12 migrations applied, identical schema.**

| Project | ID | Migrations |
|---------|-----|-----------|
| `transformed-dev` | `kxhgvwopdszclfyrrkqm` | 12 |
| `CSS_HIE` | `xjypglfmjunmlccbhjgn` | 12 |

**CES-relevant columns confirmed present in both projects:**

| Table | Column | Type | Nullable |
|-------|--------|------|----------|
| `sessions` | `ces_final` | numeric | YES ✅ |
| `sessions` | `ended_at` | timestamptz | YES ✅ |
| `session_events` | `event_type` | text | NO ✅ |
| `session_events` | `payload` | jsonb | NO ✅ |

**No migrations are needed** for the CES lifecycle as currently implemented.

**Optional improvements identified (not yet filed as stories):**

1. **`ces_breakdown jsonb` column on `sessions`** — persist signal-level breakdown at finalization time so the report can show it after Redis TTL expiry (currently falls back to zeros if Redis is flushed between session end and report view). Sprint 4 candidate.
2. **Composite index `(session_id, event_type)` on `session_events`** — makes the intervention count query in `get_session_report` an index-only scan instead of index + filter. Low-priority until load testing.

---

## 16. Known Limitations and Registered Defects

### D61 — `session_start_ts` missing silently disables fatigue for entire session

**Status:** OPEN · **Owner:** Dev 4 · **Register:** global D61

If Redis is unavailable when `_init_session_state` runs, `session_start_ts` is never written. `process_attention_signal` checks `if session_start_ts_raw is not None:` and emits only `logger.warning` before skipping the entire fatigue block for the rest of the session.

**Full fix needed:** fall back to `sessions.started_at` from DB when the Redis key is absent. Not yet implemented.

---

### D62 — `compute_ces_from_session_aggregates` dead code; partial fix applied in S3-53

**Status:** PARTIALLY FIXED · **Owner:** Dev 3 · **Register:** global D62

`assessment/service.py:compute_ces_from_session_aggregates()` is defined but never called in production. `_finalize_session` uses its own inline averaging.

**S3-53 fixes applied:**
- `_finalize_session` now returns `None` (not `0.0`) for empty history — no longer indistinguishable from zero engagement.
- Both `compute_ces` implementations now agree on `quiz_accuracy=None` redistribution.

**Remaining gap:** `compute_ces_from_session_aggregates` is still dead code. If it is ever wired into `_finalize_session`, the `None`-for-fewer-than-5-windows minimum requirement would conflict with the current inline behavior. Wiring requires explicit story.

---

### D63 — `_get_distraction_count` dead code; `dna_fusion.py` wiring never completed

**Status:** OPEN · **Owner:** Dev 3 · **Register:** global D63

`assessment/service.py:_get_distraction_count()` exists, is tested, and is documented in S3-36. The intended call site in `dna_fusion.py` was never wired. `frustration_tolerance` Learner DNA dimension never decrements from its onboarding baseline.

---

### D64 — Per-signal history keys have no TTL

**Status:** OPEN · **Owner:** Dev 3/Dev 4 · **Register:** global D64

`session:{id}:behavioral_history`, `session:{id}:head_pose_history`, `session:{id}:blink_history` have no `EXPIRE` call after `ltrim`. These keys accumulate until Redis eviction, creating orphaned key pressure on Railway Redis (64 MB limit) for sessions that end abnormally.

**Fix:** Add `await redis.expire(key, _CES_WINDOW_TTL)` after each `ltrim` in `tutor/service.py:322`, `330`, `336`.

---

### D65 — Distraction positive trigger path has zero unit test coverage

**Status:** PARTIALLY FIXED (S3-52) · **Owner:** Dev 4 · **Register:** global D65

The positive distraction trigger path (TEACHING + 2 low-CES + gap_ok → `dispatch_event("distraction_detected")`) has no unit test. The Lua atomic guard, cooldown check, distraction cap, and the `dispatch_event` call are all live code with zero positive-path coverage.

**S3-52 partial fix:** stale-history non-dispatch path, QUIZZING/INTERVENING blocking, per-signal history not written in QUIZZING — all covered.

**Remaining gap:** Write `tests/test_distraction_trigger.py` covering the POSITIVE trigger path and the Lua guard.
