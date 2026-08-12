# CES System — Developer Decision Reference

**Owner:** Dev 3 (formula, session report, intervention persistence) + Dev 4 (WebSocket, Redis, FSM)
**Last updated:** 2026-08-12
**Verified against:** `apps/api/app/modules/tutor/service.py`, `apps/api/app/modules/tutor/state_machine/graph.py`, `apps/api/app/modules/assessment/ces.py`, `apps/api/app/modules/assessment/service.py`, `apps/api/app/config.py`

> **Purpose:** Definitive, code-verified reference for every CES design decision. Not a design proposal — describes what is actually implemented as of this date. Gaps are documented honestly in Section 13.

> **Numbering note:** Decision IDs D1–D19 in this document are CES-subsystem decision IDs tracked in story frontmatter. They are entirely separate from the global defect register IDs (D1–D65). The defect register entries D61–D65 use the global numbering; all other "D-nn" in this document are CES-local. Do not conflate them.

---

## Quick-Reference Table — All Design Decisions

| CES Decision | Title | Story | Owner | Status | File:Function |
|---|---|---|---|---|---|
| D1 | CES formula weights (PRD §11) | — (PRD) | Dev 3 | Implemented | `assessment/ces.py:compute_ces`, `tutor/service.py:compute_ces` |
| D2 | Weight redistribution when teachback=None | — (PRD §11) | Dev 3 | Implemented (two divergent implementations — D62) | `assessment/ces.py:compute_ces`, `tutor/service.py:compute_ces` |
| D3 | Session finalization: ces_final + ended_at write | S3-35 | Dev 4 | Draft | `tutor/state_machine/graph.py:session_end_node`, `_finalize_session` |
| D4 | Timestamp gap-check: reject stale CES history | S3-52 (AC 4) | Dev 4 | Implemented; non-dispatch path untested (D65) | `tutor/service.py:process_attention_signal` |
| D5 | NormalizedSignal optional fields (older label; now D13) | S3-45 ref | Dev 4 | Superseded by D13 — use D13 | `tutor/service.py:NormalizedSignal` |
| D6 | Lua script for atomic distraction guard | S3-48, S3-52 | Dev 4 | Implemented | `tutor/state_machine/graph.py:_DISTRACTION_GUARD_LUA`, `_can_intervene_distraction` |
| D7 | Behavioral fatigue trigger (blink+head_pose, 15-min floor) | S3-45, S3-52 | Dev 3 | Implemented | `tutor/service.py:process_attention_signal` (fatigue block) |
| D8 | Distraction cap max 3 per session | — (PRD §10) | Dev 4 | Implemented via D6 Lua | `tutor/state_machine/graph.py:_DISTRACTION_GUARD_LUA` |
| D9 | Per-signal Redis histories for CES breakdown accuracy | S3-42 | Dev 4 | Implemented; no TTL (D64) | `tutor/service.py:process_attention_signal` |
| D12 | Fire-and-forget write_intervention_event via asyncio.create_task | S3-36, S3-37 | Dev 3/Dev 4 | Implemented | `assessment/service.py:write_intervention_event`, `graph.py:intervening_node` |
| D13 | NormalizedSignal behavioral/head_pose/blink Optional[float] | S3-38 | Dev 4 | Implemented | `tutor/service.py:NormalizedSignal`, `_parse_signal` |
| D14 | Gate compute_ces and history writes on TEACHING state | S3-39 | Dev 4 | Implemented | `tutor/service.py:process_attention_signal` |
| D15 | Write session_start_ts at WS connect (nx=True) | S3-40 | Dev 4 | Draft; D61 open | `core/websocket.py:_init_session_state` |
| D18 | ces_history_summary in SessionReport | S3-50 | Dev 3 | Draft | `assessment/service.py:get_session_report` |
| D19 | intervention_messages_used in SessionReport | S3-51 | Dev 3 | Draft | `assessment/service.py:get_session_report` |

---

## 1. CES Formula (D1, D2)

### Exact formula (PRD §11)

```
CES = quiz_accuracy×0.35 + teachback_score×0.25 + behavioral×0.20 + head_pose×0.12 + blink×0.08
```

All signals normalised to [0, 1]. Result is on the 0–100 point scale. Threshold for intervention: CES < 50.0 for 2 consecutive TEACHING-state windows.

### Redistribution rule when teachback_score is None (D2)

PRD §11 specifies redistribution when teachback is skipped:

```
CES = quiz_accuracy×0.467 + behavioral×0.267 + head_pose×0.160 + blink×0.107
```

These redistributed weights are derived as: `original_weight / (1.0 - 0.25)`. Each weight is divided by the sum of the remaining weights (0.75).

### Env var names for all weights

All weights are validated to sum to 1.0 ± 0.001 at startup via `_ces_weights_must_sum_to_one` model validator in `config.py`. Changing one weight without adjusting the others raises `ValidationError` on startup.

| Signal | Env Var | Default | Config Field |
|--------|---------|---------|---|
| Quiz accuracy | `CES_WEIGHT_QUIZ` | 0.35 | `settings.ces_weight_quiz` |
| Teachback score | `CES_WEIGHT_TEACHBACK` | 0.25 | `settings.ces_weight_teachback` |
| Behavioral | `CES_WEIGHT_BEHAVIORAL` | 0.20 | `settings.ces_weight_behavioral` |
| Head pose | `CES_WEIGHT_HEAD_POSE` | 0.12 | `settings.ces_weight_head_pose` |
| Blink rate | `CES_WEIGHT_BLINK` | 0.08 | `settings.ces_weight_blink` |

### Two divergent implementations (D62 — cross-team issue)

**This is a live defect. See Section 12.**

There are two separate `compute_ces` functions in production:

**Implementation A** — `apps/api/app/modules/assessment/ces.py:compute_ces()`
- "CES v1 formula" module written for Dev 3/Dev 4 handoff
- Signature: `compute_ces(*, quiz_accuracy, teachback_score, behavioral, head_pose, blink, settings)`
- `behavioral`, `head_pose`, `blink` are **required floats** — cannot be None
- `quiz_accuracy=None` is treated as 0.0 with full weight retained (no redistribution)
- `teachback_score=None` triggers redistribution across the 4 remaining signals only
- Returns float rounded to 4 decimal places
- Called by: assessment module only (and possibly not called at all in the live signal path)

**Implementation B** — `apps/api/app/modules/tutor/service.py:compute_ces(signal: NormalizedSignal)`
- Live production function called on every attention signal in `process_attention_signal`
- All 5 signals (`quiz_accuracy`, `teachback_score`, `behavioral_score`, `head_pose_score`, `blink_rate`) are `float | None`
- Weight redistribution applies to ALL None signals (not just teachback) — a MediaPipe frame drop redistributes weight across whichever signals are present
- Returns float clamped to [0.0, 100.0] (no rounding at this step)

**Divergence example:** If `behavioral_score=None` (MediaPipe frame drop):
- Implementation A: raises `TypeError` (float required)
- Implementation B: redistributes the 0.20 behavioral weight proportionally across the other present signals

**Neither implementation calls the other.** The live signal path uses Implementation B exclusively.

---

## 2. Signal Normalization and None Handling (D5/D13, S3-38)

### NormalizedSignal model

Defined in `apps/api/app/modules/tutor/service.py`:

```python
@dataclass
class NormalizedSignal:
    session_id: str
    quiz_accuracy: float | None   # None when quiz not yet attempted
    teachback_score: float | None # None when teach-back skipped
    behavioral_score: float | None  # None on MediaPipe frame drop (S3-38 D13)
    head_pose_score: float | None   # None on MediaPipe frame drop (S3-38 D13)
    blink_rate: float | None        # None on MediaPipe frame drop (S3-38 D13)
```

### Which signals can be None and why

| Signal | None condition | Handled by |
|--------|----------------|------------|
| `quiz_accuracy` | Quiz not yet attempted in this session window | Weight retained, value treated as 0.0 in Implementation A; weight redistributed in Implementation B |
| `teachback_score` | Student skipped teach-back (never gated per CLAUDE.md) | Weight redistributed proportionally in both implementations |
| `behavioral_score` | MediaPipe frame drop (face not visible, camera stutter) | Weight redistributed in Implementation B; Implementation A crashes |
| `head_pose_score` | Same as above | Same |
| `blink_rate` | Same as above | Same |

### How None propagates through compute_ces (Implementation B)

`_parse_signal` uses `_optional_float()` for all five fields. A `null` JSON value → Python `None` → not included in the `present` pairs list → excluded from weight redistribution.

```python
pairs = [
    (signal.quiz_accuracy, s.ces_weight_quiz),
    (signal.teachback_score, s.ces_weight_teachback),
    (signal.behavioral_score, s.ces_weight_behavioral),
    (signal.head_pose_score, s.ces_weight_head_pose),
    (signal.blink_rate, s.ces_weight_blink),
]
present = [(v, w) for (v, w) in pairs if v is not None]
weight_sum = sum(w for _, w in present)
if weight_sum <= 0:
    return 0.0
ces = sum(v * (w / weight_sum) for v, w in present) * 100.0
return max(0.0, min(100.0, ces))
```

If all 5 signals are None: `weight_sum = 0` → returns `0.0`. This is the signal for the exhaustion fallback check in the fatigue trigger.

### NaN and ±inf rejection

`_optional_float` calls `math.isfinite()` on every parsed value and raises `ValueError` if the float is not finite. This prevents NaN or infinity from propagating into the CES formula (NaN would clamp to a misleading value).

---

## 3. CES History and Window Management (D4, S3-39, S3-42)

### Redis key schema for CES history

| Key | Format | Value | TTL | Cap | Purpose |
|-----|--------|-------|-----|-----|---------|
| `session:{id}:ces_window` | string | float | 86400 s | N/A (single value) | Latest window CES (overwritten each signal) |
| `tutor_ces:{id}` | string | float | 86400 s | N/A | Running CES (also latest window; kept for backward compat) |
| `session:{id}:ces_history` | Redis list | JSON `{"v": float, "t": int}` entries | 86400 s | 10 entries (ltrim) | History for distraction trigger and session report |
| `session:{id}:behavioral_history` | Redis list | float strings | **None** (D64) | 10 entries (ltrim) | Behavioral signal history for CES breakdown |
| `session:{id}:head_pose_history` | Redis list | float strings | **None** (D64) | 10 entries (ltrim) | Head-pose signal history for CES breakdown |
| `session:{id}:blink_history` | Redis list | float strings | **None** (D64) | 10 entries (ltrim) | Blink-rate signal history for fatigue trigger and CES breakdown |

### Window TTL values

- `_CES_WINDOW_TTL = 86_400` (24 h) — applied via `redis.expire()` after `ces_history` ltrim
- Per-signal histories (`behavioral_history`, `head_pose_history`, `blink_history`): **no TTL set** (D64 — see Section 12)

### ltrim cap (_CES_HISTORY_MAX = 10)

Defined in `tutor/service.py`:

```python
_CES_HISTORY_MAX = 10
```

Applied at every write:
```python
await redis.lpush(history_key, _entry)
await redis.ltrim(history_key, 0, _CES_HISTORY_MAX - 1)
await redis.expire(history_key, _CES_WINDOW_TTL)
```

Index 0 is the most-recent entry (LPUSH prepends). The distraction trigger reads indices 0 and 1 (the two most-recent windows). The session report reads the full list (lrange 0..9, at most 10 entries).

### Per-signal history keys and their purpose

- Written in `process_attention_signal` **only when the signal is not None** (D13 guard — no write on MediaPipe frame drop)
- Read by `get_session_report` via `_signal_avg()` closure (lrange 0..9, bounded) for the `ces_breakdown` computation
- Read by the fatigue trigger (lrange 0..1, exactly 2 most-recent entries) for the 2-window blink+head_pose threshold check
- Each list is trimmed to `_CES_HISTORY_MAX = 10` entries via `ltrim` — same cap as `ces_history`

### D4 timestamp gap-check rule

The distraction trigger rejects stale CES history pairs where the two most-recent timestamps are too far apart:

```python
gap_ok = abs(t0 - t1) <= 2 * settings.ces_cadence_seconds
```

With `ces_cadence_seconds = 5` (default), the tolerance is ≤10 seconds between consecutive windows. A gap larger than 10 s indicates a signal interruption (MediaPipe restart, network jitter, browser backgrounded). In that case the distraction trigger does NOT fire even if both CES values are below threshold.

The check uses the JSON `{"v": float, "t": int}` format introduced in S3-49. Legacy bare-float entries (pre-S3-49) receive `t=0`; `abs(now - 0) >> 10 s` means the gap check always fails for a mixed old/new history pair — fail-closed, no false interventions.

**Coverage gap:** The non-dispatch path (stale timestamps) has partial coverage via S3-52 tests but the test uses `t=0` for both entries (always passes gap check). See D65 and S3-52 AC 4.

---

## 4. Distraction Trigger (D6, D8)

### Trigger conditions

1. `state_raw == "TEACHING"` (D14 gate)
2. `len(history_raw) >= 2` (at least 2 windows in history)
3. `gap_ok` (D4 timestamp check passes)
4. `v0 < settings.ces_threshold` AND `v1 < settings.ces_threshold` (both last two windows below threshold, default 50.0)
5. `_can_intervene_distraction(session_id, redis, settings)` returns `True`

### Lua script atomicity — why Lua, not EXISTS+INCR

A two-step EXISTS + INCR sequence allows a race: two concurrent attention signals arriving within the same 5 s window could both pass the EXISTS check (cooldown not set, count not at cap) and both increment the counter, causing double-dispatch in the same window.

The Lua script (`_DISTRACTION_GUARD_LUA` in `graph.py`) runs atomically in Redis's single-threaded Lua VM:

```lua
local in_cooldown = redis.call('EXISTS', KEYS[1])
if in_cooldown == 1 then return 'cooldown' end
local count = tonumber(redis.call('GET', KEYS[2])) or 0
if count >= tonumber(ARGV[1]) then return 'max_reached' end
redis.call('INCR', KEYS[2])
redis.call('EXPIRE', KEYS[2], tonumber(ARGV[2]))
return 'ok'
```

- `KEYS[1]` = `tutor_cooldown:{session_id}`
- `KEYS[2]` = `tutor_distraction_count:{session_id}`
- `ARGV[1]` = `max_distraction_per_session` (default 3)
- `ARGV[2]` = `_STATE_TTL` (86400 s)

Returns `'ok'` (proceed), `'cooldown'` (within 2-min window), or `'max_reached'` (cap hit). The count is **incremented inside the Lua script** — `intervening_node` does NOT do a second INCR. Doing so would double-count.

Implemented in: `tutor/state_machine/graph.py:_can_intervene_distraction`

### Cooldown key check

The Lua script checks `EXISTS tutor_cooldown:{session_id}` as its first step. If the key exists (set by `intervening_node` after any intervention), the script returns `'cooldown'` immediately without reading or incrementing the counter.

### Distraction cap (max 3 per session — D8)

Enforced by `ARGV[1]` in the Lua script. Default: `settings.max_distraction_per_session = 3`. Once the count reaches 3, `_can_intervene_distraction` returns `False` for the rest of the session.

The count key (`tutor_distraction_count:{session_id}`) has TTL=86400 s (set by the Lua script itself). It is not written anywhere except by the Lua script.

### Positive trigger path coverage gap (D65)

The positive distraction trigger path — TEACHING state, 2 consecutive sub-threshold CES windows, gap ok, Lua guard returns 'ok' → `dispatch_event("distraction_detected")` — has **no unit test** in the current test suite. See Section 12 (D65).

---

## 5. Fatigue Trigger (D7, S3-45, S3-52)

### Primary trigger conditions (all must hold simultaneously)

1. `state_raw == "TEACHING"` (D14 gate)
2. `not intervention_dispatched` (distraction did not already fire this signal)
3. `session_start_ts_raw is not None` (D61 — key missing disables fatigue silently)
4. `duration_s >= settings.ces_fatigue_min_session_seconds` (default 900 s = 15 min)
5. `len(blink_hist) >= 2` AND both `blink_hist[0]` and `blink_hist[1]` < `ces_fatigue_blink_threshold` (0.3)
6. `len(hp_hist) >= 2` AND both `hp_hist[0]` and `hp_hist[1]` < `ces_fatigue_head_pose_threshold` (0.3)
7. `_can_intervene_fatigue(session_id)` returns `True` (cooldown clear + once-per-session flag not set)

`blink_hist` = `lrange(session:{id}:blink_history, 0, 1)` — at most 2 entries. Index 0 is most-recent (LPUSH ordering).

### Exhaustion fallback

When all three MediaPipe signals are None AND duration floor is met, the fatigue intervention fires as a conservative fallback even when blink/head_pose histories are unavailable. Trigger conditions:

1. `state_raw == "TEACHING"` and `not intervention_dispatched`
2. `session_start_ts_raw is not None` and `duration_s >= ces_fatigue_min_session_seconds`
3. `normalized.blink_rate is None` AND `normalized.head_pose_score is None` AND `normalized.behavioral_score is None`
4. `_can_intervene_fatigue(session_id)` returns `True`

Requires S3-38 (D13 optional fields) — on old `main` where signals are required floats, this branch is structurally unreachable.

### Duration floor (900 s)

`session_duration_s = time.time() - float(session_start_ts_raw)`

If `session_start_ts_raw` is `None` (D61 — Redis unavailable at WS connect), the entire fatigue block is skipped via `if session_start_ts_raw is not None:`. A `logger.warning` is emitted but the skip is otherwise silent.

### Cooldown check (S3-52 fix — PRD §10)

`_can_intervene_fatigue` (in `graph.py`) checks the cooldown key BEFORE attempting the once-per-session SET-NX:

```python
# Step 1: PRD §10 cooldown check — fast-fail if any intervention is still in window.
if await redis.exists(cooldown_key):
    return False

# Step 2: once-per-session atomic gate.
was_set = await redis.set(fatigue_key, "1", ex=_STATE_TTL, nx=True)
return was_set is not None
```

**This cooldown check was NOT present before S3-52.** Prior to S3-52, a distraction intervention firing → 1 s later fatigue conditions met → fatigue would fire despite the 2-minute cooldown (Gap A from the S3-52 BMAD review).

The EXISTS → SET-NX sequence is NOT fully atomic (two Redis round-trips). A sub-millisecond race where `intervening_node` sets the cooldown key between step 1 and step 2 is accepted and documented in S3-52 Scale & Load §6.

### Once-per-session SET-NX gate

`redis.set(f"tutor_fatigue_fired:{session_id}", "1", ex=_STATE_TTL, nx=True)`

- Returns a non-None value only for the winning caller (the one that sets the key)
- All subsequent callers get `None` → `False` → no dispatch
- TTL = 86400 s (same as `_STATE_TTL`)
- `intervening_node` does NOT re-write this key after dispatch — the SET-NX in `_can_intervene_fatigue` IS the guard

### session_start_ts missing → fail-closed

If `session_start_ts_raw` is `None`, the code explicitly skips the entire fatigue evaluation block. This is fail-closed (safe default: unknown duration = floor not met). The missing-key case is logged at WARNING. See D61 in Section 12.

---

## 6. Session Initialization (D15, S3-40)

### session_start_ts write at WS connect

Written in `apps/api/app/core/websocket.py:_init_session_state`:

```python
await redis.set(
    f"session:{session_id}:session_start_ts",
    str(int(time.time())),
    ex=86400,
    nx=True,
)
```

- Written inside the existing `try/except Exception` block — Redis failure logs at WARNING and never raises
- TTL = 86400 s (24 h) — matches all other per-session keys

### nx=True (first-connect wins)

`nx=True` prevents a reconnecting client from resetting the session start timestamp. The original timestamp is preserved across reconnects, so `session_duration_s` measures from session creation, not the most recent reconnection.

**This behaviour is only correct on the FRESH session initialization path** (`_init_session_state`). On the reconnect path (`_restore_or_init_session` returning a non-None state), `_init_session_state` is NOT called and the key is NOT overwritten.

### What happens if the key is missing (D61)

If Redis is unavailable when `_init_session_state` runs, the `session_start_ts` key is never written. The fatigue detection block in `process_attention_signal` checks `if session_start_ts_raw is not None:` and silently skips fatigue for the entire session. A `logger.warning` is emitted. There is no DB fallback (e.g., reading `sessions.started_at`). See D61 in Section 12.

---

## 7. Intervention Event Persistence (D12, S3-36, S3-37)

### write_intervention_event() — fire-and-forget

Defined in `apps/api/app/modules/assessment/service.py`:

```python
async def write_intervention_event(
    session_id: str,
    *,
    intervention_type: str,  # "distraction" | "fatigue"
    window_index: int,
    ces_at_trigger: float,
    message_key: str,
    supabase,
) -> None:
```

**Must be called via `asyncio.create_task` — never awaited directly.** The DB write must not block the Redis hot path.

Exception handling: all exceptions are caught, logged at ERROR, and captured to Sentry. The exception is never re-raised. A failed write means the audit record is absent; the intervention was already delivered to the student.

Called from `intervening_node` in `graph.py` (S3-37):

```python
asyncio.create_task(
    write_intervention_event(
        session_id,
        intervention_type=intervention_type,
        window_index=int(state.get("window_index") or 0),
        ces_at_trigger=float(state.get("last_ces") or 0.0),
        message_key=message_key,
        supabase=get_supabase(),
    )
)
```

### session_events table schema

Inserted row shape:

```json
{
  "session_id": "<session_id>",
  "event_type": "intervention_triggered",
  "payload": {
    "intervention_type": "distraction" | "fatigue",
    "window_index": 0,
    "ces_at_trigger": 42.5,
    "message_key": "distraction_01"
  }
}
```

Table: `session_events` (schema in `supabase/migrations/20260611000000_initial_schema.sql`).

The `event_type` literal is `"intervention_triggered"` — a string constant, not a variable. The `payload->>'intervention_type'` field distinguishes distraction from fatigue.

Session ceiling: at most 4 rows per session (3 distraction + 1 fatigue) — enforced upstream by the Lua guard and SET-NX, not by `write_intervention_event` itself.

### "intervention_triggered" added to KNOWN_EVENT_TYPES

`apps/api/app/modules/analytics/service.py` — `"intervention_triggered"` must be present in `KNOWN_EVENT_TYPES`. Without it, analytics ingestion batches containing this event_type are soft-rejected with a WARNING (the events are written to `session_events` but the analytics side-path drops them).

### How intervention_messages_used is counted

`intervention_messages_used` in `SessionReport` = count of `intervention_triggered` rows in `session_events` for the session. See S3-51 AC 2:

```sql
SELECT count(*) FROM session_events
WHERE session_id = :session_id
  AND event_type = 'intervention_triggered'
```

This count equals `interventions_count` (the same query). WS delivery is best-effort (try/except) and is NOT subtracted from the count — the field reflects interventions triggered (DB events), not confirmed deliveries.

---

## 8. Session Report Fields (D18, D19, S3-50, S3-51)

### ces_history_summary

**Source:** Redis `session:{id}:ces_history` (JSON list of `{"v": float, "t": int}` entries)

**Computation:**
```python
ces_vals = [float(json.loads(raw)["v"]) for raw in raw_history]
# Backward-compat fallback: legacy bare-float strings also accepted
ces_history_summary = {
    "mean": round(sum(ces_vals) / len(ces_vals), 2),
    "min": round(min(ces_vals), 2),
    "max": round(max(ces_vals), 2),
    "window_count": len(ces_vals),
}
```

**None conditions:**
1. `redis` kwarg not provided (`if redis is None`) → `ces_history_summary = None`
2. Redis provided but `lrange` returns `[]` (`if ces_vals:` fails) → `ces_history_summary = None`

Rounding: mean/min/max to 2 decimal places; `window_count` is int (no rounding).

**Important:** This reads at most 10 entries (ltrim cap). It reflects the MOST RECENT 10 windows, not the full session history. A 90-minute session at 5-second cadence generates ~1,080 windows; only the last 10 are summarised.

**Divergence with `compute_ces_from_session_aggregates` (D62):**
`assessment/service.py` also defines `compute_ces_from_session_aggregates()` which returns `None` if fewer than 5 windows are present (minimum data requirement). The inline `ces_history_summary` computation in `get_session_report` has no such minimum — it returns a summary even for 1 window. The `_finalize_session` inline computation in `graph.py` also has no minimum and returns `0.0` for empty history instead of `None`. See D62 in Section 12.

### intervention_messages_used

**Source:** Same `session_events` count query as `interventions_count` (Step 4 of `get_session_report`).

**Intentional design (S3-51 AC 2):** `interventions_count` and `intervention_messages_used` are **the same value** in the current implementation. If a future story needs to differentiate "triggered vs delivered", it must explicitly introduce a new field or modify both sources.

**Caveat:** WS delivery is best-effort (`try/except` in `process_attention_signal`) and failures are not reflected in the count. The field name "used" may be misleading — it counts events written to DB, not confirmed WebSocket deliveries.

---

## 9. Dev 3 ↔ Dev 4 Integration Contract

### Who owns what

| Component | Owner | File | Notes |
|-----------|-------|------|-------|
| `compute_ces()` formula | Dev 3 | `assessment/ces.py` | CES v1; not called on live signal path (D62) |
| `compute_ces(signal)` live implementation | Dev 4 | `tutor/service.py` | Called every attention signal |
| `NormalizedSignal` model | Dev 4 | `tutor/service.py` | |
| `process_attention_signal()` | Dev 4 | `tutor/service.py` | Main signal processing function |
| `_can_intervene_distraction()` | Dev 4 | `tutor/state_machine/graph.py` | Lua guard |
| `_can_intervene_fatigue()` | Dev 4 | `tutor/state_machine/graph.py` | EXISTS + SET-NX |
| `intervening_node()` | Dev 4 | `tutor/state_machine/graph.py` | Calls write_intervention_event |
| `session_end_node()` + `_finalize_session()` | Dev 4 | `tutor/state_machine/graph.py` | Writes ces_final + ended_at |
| `write_intervention_event()` | Dev 3 | `assessment/service.py` | Called by Dev 4's intervening_node |
| `_get_distraction_count()` | Dev 3 | `assessment/service.py` | Redis-first DB fallback helper (dead code — D63) |
| `compute_ces_from_session_aggregates()` | Dev 3 | `assessment/service.py` | Not called in production (D62) |
| `get_session_report()` + `_build_ces_breakdown()` | Dev 3 | `assessment/service.py` | Session report generation |
| `ces_history_summary` field | Dev 3 | `assessment/service.py` | Reads Dev 4's Redis history keys |
| `intervention_messages_used` field | Dev 3 | `assessment/service.py` | Reads `session_events` written by Dev 4 |
| `_init_session_state()` with session_start_ts | Dev 4 | `core/websocket.py` | D15/S3-40 |

### Redis key handoff points

Dev 4 writes these keys; Dev 3 reads them in `get_session_report`:
- `session:{id}:ces_history` → `ces_history_summary`
- `session:{id}:behavioral_history` → `ces_breakdown.behavioral`
- `session:{id}:head_pose_history` → `ces_breakdown.head_pose`
- `session:{id}:blink_history` → `ces_breakdown.blink`

Dev 3 writes `session_events` rows (via `write_intervention_event` called from Dev 4's `intervening_node`); Dev 3's `get_session_report` reads those rows.

### What Dev 3 reads vs Dev 4 writes

```
Dev 4 writes:                          Dev 3 reads:
─────────────────────────────────────────────────────────────
session:{id}:ces_history      →   get_session_report() ces_history_summary
session:{id}:behavioral_history → get_session_report() _build_ces_breakdown()
session:{id}:head_pose_history  → get_session_report() _build_ces_breakdown()
session:{id}:blink_history      → get_session_report() _build_ces_breakdown()
session_events (via create_task) → get_session_report() interventions_count / intervention_messages_used
```

### Breaking change protocol

Any change to the following requires explicit sync between Dev 3 and Dev 4:
- The `NormalizedSignal` field names or types (Dev 4 → Dev 3 impact)
- The Redis key naming scheme (any renaming breaks `get_session_report`)
- The `session_events` `event_type = "intervention_triggered"` literal (Dev 3 reads this in multiple places)
- The `payload` shape of `intervention_triggered` events (Dev 3's `_get_distraction_count` filters on `payload->>'intervention_type' = 'distraction'`)
- The `ces_history` JSON format (currently `{"v": float, "t": int}`; backward-compat fallback exists for bare floats)

These are frozen contracts. Shape changes require a 4-dev PR review per CLAUDE.md §16.

---

## 10. Redis Key Schema (Complete Reference)

All keys scoped to `session_id` (UUIDv4). Shared across Railway Redis — all replicas see the same keys. `_STATE_TTL = 86400` s (24 h) in `graph.py`. `_CES_WINDOW_TTL = 86400` s in `service.py`.

| Key | Format | Type | Written by | TTL | Cap | Notes |
|-----|--------|------|-----------|-----|-----|-------|
| `tutor_state:{session_id}` | string | FSM state name | `graph.py:_persist_state` | 86400 s | N/A | Current tutor FSM state (IDLE/TEACHING/etc.) |
| `tutor_ces:{session_id}` | string | float | `tutor/service.py:process_attention_signal` | 86400 s | N/A | Alias for current-window CES; kept for backward compat |
| `tutor_cooldown:{session_id}` | string | "1" | `graph.py:intervening_node` | `intervention_cooldown_seconds` (120 s) | N/A | Present during 2-min cooldown. `nx=True` on write so first writer wins. |
| `tutor_distraction_count:{session_id}` | string | int | `graph.py:_DISTRACTION_GUARD_LUA` (INCR inside Lua) | 86400 s (set inside Lua) | N/A | Count of distraction interventions fired this session (max 3) |
| `tutor_fatigue_fired:{session_id}` | string | "1" | `graph.py:_can_intervene_fatigue` (SET NX) | 86400 s | N/A | Once-per-session flag. SET NX is atomic. |
| `session:{id}:ces_window` | string | float | `tutor/service.py:process_attention_signal` | 86400 s | N/A | Current window CES (overwritten each signal) |
| `session:{id}:ces_history` | Redis list | JSON `{"v": float, "t": int}` | `tutor/service.py:process_attention_signal` | 86400 s | 10 (ltrim) | LPUSH prepends; index 0 = most recent. Backward-compat: bare float strings accepted as legacy format. |
| `session:{id}:behavioral_history` | Redis list | float strings | `tutor/service.py:process_attention_signal` | **None (D64)** | 10 (ltrim) | Only written when `behavioral_score is not None`. |
| `session:{id}:head_pose_history` | Redis list | float strings | `tutor/service.py:process_attention_signal` | **None (D64)** | 10 (ltrim) | Only written when `head_pose_score is not None`. |
| `session:{id}:blink_history` | Redis list | float strings | `tutor/service.py:process_attention_signal` | **None (D64)** | 10 (ltrim) | Only written when `blink_rate is not None`. |
| `session:{id}:session_start_ts` | string | Unix timestamp int | `core/websocket.py:_init_session_state` | 86400 s | N/A | `nx=True` — first-connect wins; reconnects do not reset. |
| `session:{id}:segment_index` | string | int | `tutor/service.py:advance_tutor_state` | 86400 s | N/A | Current segment position (0-based). Incremented on `segment_complete` event. |
| `session:{id}:quiz_deadline_at` | string | Unix timestamp int | `graph.py:quizzing_node` | 86400 s | N/A | Quiz time limit. Deleted on expiry to prevent double-fire. |
| `session:{id}:qa_phase_seconds` | string | int | `core/websocket.py:_seed_learner_tier` | — | N/A | Tier-based Q&A phase duration. Read by `quizzing_node`. |
| `lesson_package:{session_id}` | string | JSON | `core/pubsub.py` (Dev 4) | — | N/A | Cached `LessonPackage`. Read-only in `tutor/service.py:_segment_intervention_messages`. |
| `user:{user_id}:ces_baseline` | string | float | Assessment module (Dev 3) | `ces_baseline_ttl_seconds` (86400 s) | N/A | Per-user CES baseline (average of last N sessions). |

---

## 11. Configuration Reference (env vars)

All CES-related settings are in `apps/api/app/config.py:Settings`.

| Env Var | Config Field | Default | Validation | Used In | Scale Contract Note |
|---------|-------------|---------|------------|---------|---------------------|
| `CES_WEIGHT_QUIZ` | `ces_weight_quiz` | 0.35 | 0.0–1.0; sum must = 1.0 ± 0.001 | `assessment/ces.py`, `tutor/service.py` | Per deployment; all replicas share one value |
| `CES_WEIGHT_TEACHBACK` | `ces_weight_teachback` | 0.25 | 0.0–1.0; sum constraint | Same | Same |
| `CES_WEIGHT_BEHAVIORAL` | `ces_weight_behavioral` | 0.20 | 0.0–1.0; sum constraint | Same | Same |
| `CES_WEIGHT_HEAD_POSE` | `ces_weight_head_pose` | 0.12 | 0.0–1.0; sum constraint | Same | Same |
| `CES_WEIGHT_BLINK` | `ces_weight_blink` | 0.08 | 0.0–1.0; sum constraint | Same | Same |
| `CES_THRESHOLD` | `ces_threshold` | 50.0 | — | `tutor/service.py` | Per deployment |
| `CES_FATIGUE_BLINK_THRESHOLD` | `ces_fatigue_blink_threshold` | 0.3 | ge=0.0, le=1.0 | `tutor/service.py` | Per deployment. Schleicher et al. 2008 basis. |
| `CES_FATIGUE_HEAD_POSE_THRESHOLD` | `ces_fatigue_head_pose_threshold` | 0.3 | ge=0.0, le=1.0 | `tutor/service.py` | Per deployment. Bosch et al. 2015 basis. |
| `CES_FATIGUE_MIN_SESSION_SECONDS` | `ces_fatigue_min_session_seconds` | 900 | ge=60; below 60 raises ValidationError on startup | `tutor/service.py` | Per deployment. Setting below 60 is rejected at startup — cannot be misconfigured silently. |
| `CES_CADENCE_SECONDS` | `ces_cadence_seconds` | 5 | gt=0 | `tutor/service.py` (D4 gap check) | Per deployment. Gap tolerance = 2 × cadence (default 10 s). |
| `CES_BASELINE_WINDOW` | `ces_baseline_window` | 5 | ge=1, le=50 | Assessment module | Per deployment |
| `CES_BASELINE_TTL_SECONDS` | `ces_baseline_ttl_seconds` | 86400 | ge=60 | Assessment module | Redis key TTL — per deployment, same across replicas |
| `INTERVENTION_COOLDOWN_SECONDS` | `intervention_cooldown_seconds` | 120 | — | `graph.py:intervening_node` | TTL for `tutor_cooldown:` key. Changing this changes how long after an intervention the next can fire. Scope: per deployment; shared via Railway Redis. |
| `MAX_DISTRACTION_PER_SESSION` | `max_distraction_per_session` | 3 | — | `graph.py:_DISTRACTION_GUARD_LUA` (ARGV[1]) | Per session enforcement via Lua atomic counter. Scope: per deployment. Changing it affects all active sessions immediately (Lua reads the current ARGV on each call). |
| `DNA_EMA_RETAIN` | `dna_ema_retain` | 0.7 | ge=0.0, le=1.0 | Assessment module (Learner DNA) | EMA retention weight for dimension updates. |

### Sum validator

The `_ces_weights_must_sum_to_one` model validator in `config.py` runs at startup and raises `ValueError` if `|sum(weights) - 1.0| > 0.001`. This means:
- You cannot change one weight without adjusting others
- Any misconfigured weight combination is caught at startup before any request is processed
- This is the only machine-checked constraint on the formula's well-formedness

---

## 12. Defect Register Cross-Reference

### CES-subsystem defects from the global DEFECT-REGISTER.md

The entries below (D61–D65) use **global defect register numbering**, not CES decision IDs.

---

### D61 — session_start_ts missing silently disables fatigue for entire session

**Status:** OPEN · **Owner:** Dev 4 · **Severity:** Medium

**What it means for CES developers:**
If `_init_session_state` runs while Redis is unavailable (temporary blip at WS connect time), `session:{id}:session_start_ts` is never written. Every subsequent call to `process_attention_signal` checks `if session_start_ts_raw is not None:` and skips the entire fatigue trigger block for the duration of the session. A `logger.warning` is emitted but there is no observable error, no HTTP error, and the CES computation itself continues normally.

**Impact:** Fatigue interventions never fire for affected sessions. `SessionReport.ces_history_summary` and distraction detection are unaffected.

**Partial fix in place:** The warning log. Full fix (DB fallback to `sessions.started_at`) is not implemented.

**Enforcement:** DISCIPLINE (warning log is not machine-checked).

---

### D62 — compute_ces_from_session_aggregates is dead code; _finalize_session has divergent inline implementation

**Status:** OPEN · **Owner:** Dev 3 · **Severity:** Medium

**What it means for CES developers:**

Two separate CES averaging paths exist that can return different results for the same history:

| Path | Function | File | None < 5 windows | Empty history |
|------|----------|------|-------------------|---------------|
| `get_session_report` inline | anonymous code block | `assessment/service.py:get_session_report` ~line 992 | returns summary (no minimum) | `None` |
| `_finalize_session` inline | `_finalize_session` | `graph.py:_finalize_session` | returns `0.0` (no minimum) | `0.0` |
| `compute_ces_from_session_aggregates` | `assessment/service.py:compute_ces_from_session_aggregates` | defined but never called | returns `None` | `None` |

A student who ends their session after fewer than 5 CES windows gets:
- `sessions.ces_final = 0.0` (written by `_finalize_session`) — indistinguishable from zero engagement
- `ces_history_summary` in the report may still contain a non-zero mean (if any windows exist)

These are inconsistent. `compute_ces_from_session_aggregates` is the function specified in the story (S3-49) to be the authoritative source for `_finalize_session`, but the wiring was never completed.

**Fix options:**
1. Wire `_finalize_session` to call `compute_ces_from_session_aggregates`, mapping `None → 0.0` explicitly with a logged warning
2. Delete `compute_ces_from_session_aggregates` and document the `0.0` artifact in the session report schema

**Enforcement:** DISCIPLINE.

---

### D63 — _get_distraction_count is dead code; dna_fusion.py wiring never completed

**Status:** OPEN · **Owner:** Dev 3 · **Severity:** Medium

**What it means for CES developers:**

`assessment/service.py:_get_distraction_count` implements Redis-first DB-fallback distraction counting (S3-36 Task 3.2–3.3). It is tested in isolation. However, `apps/api/app/modules/assessment/dna_fusion.py` has no import and no call to it.

Consequence: `fuse_learner_dna()` reads the distraction count incorrectly. It either uses a direct Redis read (without the DB fallback for cache misses) or always returns 0 — the `frustration_tolerance` dimension never decrements from its baseline regardless of intervention count.

**Impact:** Learner DNA `frustration_tolerance` dimension is permanently stuck at its onboarding baseline. The EMA-based decrement formula in `dna_fusion.py` receives count=0 on every session.

**Fix:** Import and call `_get_distraction_count(session_id, redis=redis, supabase=supabase)` in `fuse_learner_dna()` where the distraction count is currently computed.

**Enforcement:** DISCIPLINE (import graphs are not CI-checked).

---

### D64 — Per-signal history keys have no TTL

**Status:** OPEN · **Owner:** Dev 3/Dev 4 · **Severity:** Low–Medium

**What it means for CES developers:**

`process_attention_signal` writes `session:{id}:behavioral_history`, `session:{id}:head_pose_history`, and `session:{id}:blink_history` to Redis but does NOT call `redis.expire()` on these keys. In contrast, `session:{id}:ces_history` correctly receives `expire(_CES_WINDOW_TTL)` after its `ltrim`.

These keys persist until Redis eviction policy removes them. On Railway Redis with a memory limit (64 MB), sessions that end abnormally (client closes browser, network drop before SESSION_END) accumulate orphaned history keys indefinitely. At 5 s cadence over a 90-minute session with 3 keys × 10 entries × ~10 bytes per float string ≈ ~300 bytes per session, this is low-severity today but grows with user count.

**Fix:** Add the following after each `ltrim` call in `tutor/service.py:process_attention_signal`:

```python
await redis.expire(f"session:{session_id}:behavioral_history", _CES_WINDOW_TTL)
await redis.expire(f"session:{session_id}:head_pose_history", _CES_WINDOW_TTL)
await redis.expire(f"session:{session_id}:blink_history", _CES_WINDOW_TTL)
```

**Enforcement:** DISCIPLINE.

---

### D65 — Distraction trigger positive path has zero unit test coverage

**Status:** PARTIALLY FIXED (S3-52) · **Owner:** Dev 4 · **Severity:** Medium

**What it means for CES developers:**

The distraction trigger in `tutor/service.py:process_attention_signal` (lines 344–411) — TEACHING state, 2 consecutive sub-threshold CES windows, gap_ok=True, Lua guard returns 'ok' → `dispatch_event("distraction_detected")` — has **no unit test asserting the positive path**.

The following behaviours are also untested:
- The Lua script returning 'ok' and distraction being dispatched
- The cooldown check blocking a second distraction within 120 s
- The distraction cap (count=3) blocking a fourth distraction
- The "distraction blocks fatigue in same window" scenario (Scenario 12 in the coverage matrix)

**S3-52 partial fix (2026-08-12):** `tests/test_s3_52_ces_production_hardening.py` now covers:
- D4 timestamp gap-check non-dispatch path (stale entries → no dispatch)
- `dispatch_event.assert_not_called()` for QUIZZING and INTERVENING states with low CES
- Per-signal `lpush` not called in QUIZZING state

**Remaining gap:** Write `tests/test_distraction_trigger.py` covering the POSITIVE trigger path: TEACHING state + 2 consecutive sub-threshold CES + gap_ok=True + Lua guard returning 'ok' → `dispatch_event("distraction_detected")` called.

**Enforcement:** DISCIPLINE (test file is absent, not a failing CI check).

---

## 13. What Is NOT Implemented (Known Gaps)

This section documents gaps confirmed by reading the production code. Each gap corresponds to a defect register entry.

### D62: Two divergent compute_ces implementations

`assessment/ces.py:compute_ces()` is the "CES v1" module written as a Dev 3/Dev 4 handoff contract. It is **not called on the live signal path**. The live signal path uses `tutor/service.py:compute_ces(signal: NormalizedSignal)` exclusively. `compute_ces_from_session_aggregates()` in `assessment/service.py` — the intended authoritative function for `_finalize_session` — is never called in production.

Any developer reading `assessment/ces.py` and assuming it describes the live behaviour is wrong.

### D63: _get_distraction_count dead code

`assessment/service.py:_get_distraction_count()` exists, is tested, and is documented in S3-36. The intended call site in `dna_fusion.py` was never wired. `frustration_tolerance` Learner DNA dimension never decrements.

### D64: Per-signal history TTL missing

`session:{id}:behavioral_history`, `session:{id}:head_pose_history`, and `session:{id}:blink_history` accumulate without TTL. On high-traffic Railway Redis, these are an eviction pressure that grows with user count. The fix is a one-line `redis.expire()` per key after each `ltrim`.

### D65: Distraction positive trigger path untested

The `_can_intervene_distraction` Lua guard, cooldown check, distraction cap, and the `dispatch_event("distraction_detected")` call path have zero positive-path unit test coverage. This means a regression in the Lua script or the trigger logic would not be caught by the CI test suite.

### Fatigue cooldown race (S3-52 Scale §6 — accepted)

The `_can_intervene_fatigue` EXISTS → SET-NX sequence is not fully atomic. A sub-millisecond race where `intervening_node` sets `tutor_cooldown` between the two Redis calls could allow fatigue and a concurrent intervention to both start. This is accepted and documented in S3-52. The fix (a single Lua script replacing EXISTS + SET-NX) is noted but not implemented.

### session_start_ts missing on Redis blip (D61)

If Redis is unavailable at WebSocket connect time, fatigue detection is silently disabled for the entire session. The full fix (DB fallback to `sessions.started_at`) is not implemented.

### WS delivery confirmation not tracked

`intervention_messages_used` in `SessionReport` counts DB events written, not confirmed WebSocket deliveries. WS delivery uses try/except and failures are swallowed. There is no way to distinguish "intervention triggered and delivered" from "intervention triggered but WS send failed".

### once-per-session flag not separate from per-intervention cooldown

`tutor_fatigue_fired:{session_id}` (once-per-session) and `tutor_cooldown:{session_id}` (per-intervention, 120 s TTL) are separate Redis keys checked in sequence. They are not combined into a single atomic operation. The gap is accepted (S3-52 Scale §6) but developers should not assume the two checks are equivalent.
