# CES System — Developer Decision Reference

**Owner:** Dev 3 (formula, session report, intervention persistence) + Dev 4 (WebSocket, Redis, FSM)
**Last updated:** 2026-08-13 — incorporates S3-53 Phase 2 fixes and Supabase audit.
**Verified against:** `tutor/service.py`, `tutor/state_machine/graph.py`, `assessment/ces.py`, `assessment/service.py`, `assessment/router.py`, `config.py`, `core/websocket.py`, `web/src/components/player/AudioTimeline.tsx`, `web/src/lib/utils.ts`, `web/src/components/reports/SessionReport.tsx`, `web/src/types/assessment.ts`

> **Purpose:** Definitive, code-verified reference for every CES design decision. Not a design proposal — describes what is **actually implemented** as of this date. Gaps and open defects are documented honestly in Section 13.

> **Numbering note:** Decision IDs D1–D20 in this document are CES-subsystem decision IDs tracked in story frontmatter. They are entirely separate from the global defect register IDs (D61–D65). Do not conflate them.

---

## Quick-Reference Table — All Design Decisions

| CES Decision | Title | Story | Owner | Status | File:Function |
|---|---|---|---|---|---|
| D1 | CES formula weights (PRD §11) | — (PRD) | Dev 3 | **Implemented** | `assessment/ces.py:compute_ces`, `tutor/service.py:compute_ces` |
| D2 | Weight redistribution when any signal is None | — (PRD §11) | Dev 3 | **Implemented** (both implementations aligned as of S3-53) | `assessment/ces.py:compute_ces`, `tutor/service.py:compute_ces` |
| D3 | Session finalization: ces_final + ended_at write | S3-35 | Dev 4 | **Implemented** | `tutor/state_machine/graph.py:session_end_node`, `_finalize_session` |
| D4 | Timestamp gap-check: reject stale CES history | S3-52 (AC 4) | Dev 4 | **Implemented**; non-dispatch path untested (D65) | `tutor/service.py:process_attention_signal` |
| D5 | NormalizedSignal optional fields | S3-45 ref | Dev 4 | Superseded by D13 | `tutor/service.py:NormalizedSignal` |
| D6 | Lua script for atomic distraction guard | S3-48, S3-52 | Dev 4 | **Implemented** | `tutor/state_machine/graph.py:_DISTRACTION_GUARD_LUA` |
| D7 | Behavioral fatigue trigger (blink+head_pose, 15-min floor) | S3-45, S3-52 | Dev 3 | **Implemented** | `tutor/service.py:process_attention_signal` (fatigue block) |
| D8 | Distraction cap max 3 per session | — (PRD §10) | Dev 4 | **Implemented** via D6 Lua | `tutor/state_machine/graph.py:_DISTRACTION_GUARD_LUA` |
| D9 | Per-signal Redis histories for CES breakdown accuracy | S3-42 | Dev 4 | **Implemented**; no TTL (D64 open) | `tutor/service.py:process_attention_signal` |
| D12 | Fire-and-forget `write_intervention_event` via `asyncio.create_task` | S3-36, S3-37 | Dev 3/Dev 4 | **Implemented** | `assessment/service.py:write_intervention_event`, `graph.py:intervening_node` |
| D13 | NormalizedSignal behavioral/head_pose/blink `Optional[float]` | S3-38 | Dev 4 | **Implemented** | `tutor/service.py:NormalizedSignal`, `_parse_signal` |
| D14 | Gate `compute_ces` and history writes on TEACHING state | S3-39 | Dev 4 | **Implemented** | `tutor/service.py:process_attention_signal` |
| D15 | Write `session_start_ts` at WS connect (`nx=True`) | S3-40 | Dev 4 | **Implemented**; D61 open (no DB fallback when Redis blip) | `core/websocket.py:_init_session_state` |
| D16 | `lesson_complete` dispatch from frontend at last segment | S3-53 Phase 2 | Dev 2/Dev 4 | **Implemented** | `web/src/components/player/AudioTimeline.tsx:~385` |
| D17 | `ces_score: float \| None` in API response (None, not 0.0) | S3-53 Phase 2 | Dev 3 | **Implemented** | `assessment/service.py:943`, `assessment/router.py:47` |
| D18 | `ces_history_summary` in SessionReport | S3-50 | Dev 3 | **Implemented** | `assessment/service.py:get_session_report` |
| D19 | `intervention_messages_used` in SessionReport | S3-51 | Dev 3 | **Implemented** | `assessment/service.py:get_session_report` |
| D20 | Color-coded CES display with null-safe label | S3-53 Phase 2 | Dev 2/Dev 3 | **Implemented** | `web/src/lib/utils.ts:cesScoreColor`, `SessionReport.tsx:168` |

---

## 1. CES Formula (D1, D2)

### Exact formula (PRD §11)

```
CES = quiz_accuracy×0.35 + teachback_score×0.25 + behavioral×0.20 + head_pose×0.12 + blink×0.08
```

All signals normalised to [0, 1]. Result is on the 0–100 point scale. Threshold for distraction intervention: CES < 50.0 for 2 consecutive TEACHING-state windows.

### Redistribution rule — any signal is None (D2, unified in S3-53)

When any signal is `None`, its weight is dropped and the remaining present signals are proportionally rescaled:

```python
present = [(v, w) for (v, w) in all_pairs if v is not None]
weight_sum = sum(w for _, w in present)
if weight_sum <= 0:
    return 0.0      # all-None exhaustion
ces = sum(v * (w / weight_sum) for v, w in present) * 100.0
```

**teachback=None (PRD §11 example):** Remaining weights sum to 0.75; effective weights:
- quiz: 0.35/0.75 = 0.4667
- behavioral: 0.20/0.75 = 0.2667
- head_pose: 0.12/0.75 = 0.1600
- blink: 0.08/0.75 = 0.1067

**quiz=None:** Remaining weights sum to 0.65; redistribution across present signals.

**Any MediaPipe signal None:** weight redistributed across whichever signals are present.

### Two implementations — now aligned (S3-53 fix)

**Implementation A** — `apps/api/app/modules/assessment/ces.py:compute_ces()`
- Used by: `assessment` module session report, Learner DNA `_build_ces_breakdown`
- All 5 signals: `float | None` (aligned with Implementation B as of S3-53)
- Returns float rounded to 4 decimal places

**Implementation B** — `apps/api/app/modules/tutor/service.py:compute_ces(signal: NormalizedSignal)`
- Used by: live signal path in `process_attention_signal` (every attention signal)
- Returns float clamped to [0.0, 100.0] (no rounding at this step)

**Before S3-53:** Implementation A treated `quiz_accuracy=None` as `0.0` with full weight retained, while Implementation B redistributed. This meant live-session CES and report CES diverged for the same input. **Fixed in S3-53** — Implementation A now redistributes for all None signals identically to Implementation B.

**Remaining divergence:** `compute_ces_from_session_aggregates()` in `assessment/service.py` (dead code — D62) has different None-handling semantics. It is not called in production. See Section 13.

### Env var names for all weights

All weights are validated to sum to 1.0 ± 0.001 at startup via `_ces_weights_must_sum_to_one` model validator in `config.py`. Changing one weight without adjusting others raises `ValidationError` on startup — this is the only machine-checked constraint on formula well-formedness.

| Signal | Env Var | Default | Config Field |
|--------|---------|---------|---|
| Quiz accuracy | `CES_WEIGHT_QUIZ` | 0.35 | `settings.ces_weight_quiz` |
| Teachback score | `CES_WEIGHT_TEACHBACK` | 0.25 | `settings.ces_weight_teachback` |
| Behavioral | `CES_WEIGHT_BEHAVIORAL` | 0.20 | `settings.ces_weight_behavioral` |
| Head pose | `CES_WEIGHT_HEAD_POSE` | 0.12 | `settings.ces_weight_head_pose` |
| Blink rate | `CES_WEIGHT_BLINK` | 0.08 | `settings.ces_weight_blink` |

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
    behavioral_score: float | None  # None on MediaPipe frame drop (D13)
    head_pose_score: float | None   # None on MediaPipe frame drop (D13)
    blink_rate: float | None        # None on MediaPipe frame drop (D13)
```

### Which signals can be None and why

| Signal | None condition | Both implementations handle |
|--------|----------------|------------|
| `quiz_accuracy` | Quiz not yet attempted this session | Weight redistributed proportionally (S3-53 unified) |
| `teachback_score` | Student skipped teach-back (never gated per CLAUDE.md) | Weight redistributed proportionally in both |
| `behavioral_score` | MediaPipe frame drop (face not visible, camera stutter) | Weight redistributed in both (B); A accepts null as of S3-53 |
| `head_pose_score` | Same | Same |
| `blink_rate` | Same | Same |

### NaN and ±inf rejection

`_optional_float` calls `math.isfinite()` on every parsed value and raises `ValueError` if not finite. This prevents NaN or infinity from propagating into the formula — NaN would clamp to a misleading value.

---

## 3. CES History and Window Management (D4, S3-39, S3-42)

### Redis key schema for CES history

| Key | Format | Value | TTL | Cap | Purpose |
|-----|--------|-------|-----|-----|---------|
| `session:{id}:ces_window` | string | float | 86400 s | N/A | Latest window CES (overwritten each signal) |
| `tutor_ces:{id}` | string | float | 86400 s | N/A | Running CES alias; backward compat |
| `session:{id}:ces_history` | Redis list | JSON `{"v": float, "t": int}` | 86400 s | 10 (ltrim) | History for distraction trigger + session report |
| `session:{id}:behavioral_history` | Redis list | float strings | **None (D64)** | 10 (ltrim) | Behavioral signal history for CES breakdown |
| `session:{id}:head_pose_history` | Redis list | float strings | **None (D64)** | 10 (ltrim) | Head-pose history for fatigue trigger + breakdown |
| `session:{id}:blink_history` | Redis list | float strings | **None (D64)** | 10 (ltrim) | Blink history for fatigue trigger + breakdown |

### ltrim cap (_CES_HISTORY_MAX = 10)

```python
await redis.lpush(history_key, _entry)
await redis.ltrim(history_key, 0, _CES_HISTORY_MAX - 1)
await redis.expire(history_key, _CES_WINDOW_TTL)   # ces_history only — D64
```

Index 0 is the most-recent entry (LPUSH prepends). Distraction trigger reads indices 0 and 1. Session report reads the full list (lrange 0..9).

### D4 timestamp gap-check rule

```python
gap_ok = abs(t0 - t1) <= 2 * settings.ces_cadence_seconds
```

With `ces_cadence_seconds = 5` (default), tolerance is ≤10 seconds. A gap larger than 10 s indicates signal interruption (MediaPipe restart, browser backgrounded). Distraction does NOT fire on stale pairs. Legacy bare-float entries receive `t=0` — `abs(now - 0)` >> 10 s — always failing the check (fail-closed).

---

## 4. Distraction Trigger (D6, D8)

### Trigger conditions (all must hold)

1. `state_raw == "TEACHING"` (D14 gate)
2. `len(history_raw) >= 2`
3. `gap_ok` (D4 timestamp check)
4. `v0 < settings.ces_threshold` AND `v1 < settings.ces_threshold` (default 50.0)
5. `_can_intervene_distraction(session_id, redis, settings)` returns `True`

### Lua script atomicity — why Lua, not EXISTS+INCR

A two-step EXISTS + INCR sequence allows a race: two concurrent attention signals could both pass the EXISTS check and both increment the counter, causing double-dispatch.

The Lua script (`_DISTRACTION_GUARD_LUA` in `graph.py`) runs atomically in Redis's single-threaded VM:

```lua
local in_cooldown = redis.call('EXISTS', KEYS[1])    -- tutor_cooldown:{id}
if in_cooldown == 1 then return 'cooldown' end
local count = tonumber(redis.call('GET', KEYS[2])) or 0   -- distraction_count:{id}
if count >= tonumber(ARGV[1]) then return 'max_reached' end
redis.call('INCR', KEYS[2])
redis.call('EXPIRE', KEYS[2], tonumber(ARGV[2]))
return 'ok'
```

- `KEYS[1]` = `tutor_cooldown:{session_id}`
- `KEYS[2]` = `tutor_distraction_count:{session_id}`
- `ARGV[1]` = `max_distraction_per_session` (default 3)
- `ARGV[2]` = `_STATE_TTL` (86400 s)

Returns `'ok'`, `'cooldown'`, or `'max_reached'`. The count is incremented **inside the Lua script** — `intervening_node` does NOT do a second INCR. Doing so would double-count.

### Distraction cap (D8)

Enforced by `ARGV[1]` in the Lua script. Default: `settings.max_distraction_per_session = 3`. Once the count reaches 3, all further distraction attempts return `False` for the rest of the session.

### Positive trigger path coverage gap (D65)

The positive distraction trigger path has **no unit test** in the current test suite. See Section 13 (D65).

---

## 5. Fatigue Trigger (D7, S3-45, S3-52)

### Primary trigger conditions (all must hold simultaneously)

1. `state_raw == "TEACHING"` (D14 gate)
2. `not intervention_dispatched` (distraction did not already fire this signal)
3. `session_start_ts_raw is not None` (D61 — key missing disables fatigue silently)
4. `duration_s >= settings.ces_fatigue_min_session_seconds` (default 900 s = 15 min)
5. `len(blink_hist) >= 2` AND both `blink_hist[0]` and `blink_hist[1]` < `ces_fatigue_blink_threshold` (0.3)
6. `len(hp_hist) >= 2` AND both `hp_hist[0]` and `hp_hist[1]` < `ces_fatigue_head_pose_threshold` (0.3)
7. `_can_intervene_fatigue(session_id)` returns `True`

`blink_hist` = `lrange(session:{id}:blink_history, 0, 1)` — at most 2 entries, bounded per CLAUDE.md unbounded-query rule.

### Exhaustion fallback

When all three MediaPipe signals are None AND duration floor is met, fatigue fires as a conservative fallback:

1. `state_raw == "TEACHING"` and `not intervention_dispatched`
2. `session_start_ts_raw is not None` and `duration_s >= floor`
3. `normalized.blink_rate is None` AND `normalized.head_pose_score is None` AND `normalized.behavioral_score is None`
4. `_can_intervene_fatigue(session_id)` returns `True`

Requires S3-38 (D13) — on pre-D13 code where signals are required floats, this branch is structurally unreachable.

### Cooldown check (S3-52 fix)

`_can_intervene_fatigue` (in `graph.py`) checks the cooldown key BEFORE attempting the once-per-session SET-NX:

```python
# Step 1: cooldown check — fast-fail if any intervention is still in window.
if await redis.exists(cooldown_key):
    return False

# Step 2: once-per-session atomic gate.
was_set = await redis.set(fatigue_key, "1", ex=_STATE_TTL, nx=True)
return was_set is not None
```

**This cooldown check was NOT present before S3-52.** Prior to S3-52, a distraction followed immediately by fatigue conditions → fatigue would fire despite the 2-minute cooldown.

The EXISTS → SET-NX sequence is NOT fully atomic. A sub-millisecond race where `intervening_node` sets the cooldown key between step 1 and step 2 is accepted and documented in S3-52 Scale & Load §6. The SET-NX in step 2 is still atomic so fatigue can only fire ONCE per session regardless.

### Once-per-session gate

`redis.set(f"tutor_fatigue_fired:{session_id}", "1", ex=_STATE_TTL, nx=True)`

- Returns non-None only for the winning caller (the one that sets the key).
- All subsequent callers get `None` → `False` → no dispatch.
- TTL = 86400 s.
- `intervening_node` does NOT re-write this key — the SET-NX in `_can_intervene_fatigue` IS the guard.

---

## 6. Session Initialization (D15, S3-40)

### `session_start_ts` write at WS connect

Written in `core/websocket.py:_init_session_state`:

```python
await redis.set(
    f"session:{session_id}:session_start_ts",
    str(int(time.time())),
    ex=86400,
    nx=True,
)
```

- Written inside existing `try/except Exception` — Redis failure logs at WARNING and never raises.
- `nx=True` prevents a reconnecting client from resetting the timestamp. Original timestamp preserved across reconnects, so duration measures from session creation.

### What happens if the key is missing (D61)

If Redis is unavailable when `_init_session_state` runs, the key is never written. `process_attention_signal` checks `if session_start_ts_raw is not None:` and silently skips fatigue for the entire session. A `logger.warning` is emitted. There is no DB fallback. See D61 in Section 13.

---

## 7. `lesson_complete` Dispatch from Frontend (D16, S3-53 Phase 2)

### Problem this solves

Before S3-53 Phase 2, `lesson_complete` was never dispatched from the frontend. This made `_finalize_session` structurally unreachable — `sessions.ces_final` was never written for any session, and `sessions.ended_at` was never set.

### Implementation

**File:** `apps/web/src/components/player/AudioTimeline.tsx` (~line 385)

```typescript
} else {
  wsSendControl?.({ type: 'lesson_complete' });  // triggers FSM → SESSION_END
  endLesson();
}
```

This block executes when the last segment's audio completes. `wsSendControl` is the WebSocket send handle injected into `AudioTimeline`. It accepts any `LocalControlOut` type.

`lesson_complete` is a valid `FlowEvent` in `web/src/types/wireTypes.ts:27`.

### Backend flow triggered

```
lesson_complete WS message
  → _handle_lesson_complete (websocket.py)
  → dispatch_event(session_id, "lesson_complete")
  → route_from_teaching → "session_end"
  → session_end_node (graph.py:335-354)
  → asyncio.create_task(_finalize_session(...))  # fire-and-forget
```

### Why fire-and-forget

`_finalize_session` writes to Supabase (`sessions.ces_final`, `sessions.ended_at`). Awaiting it would block the FSM state transition and delay the `state_change` WS message the client needs to render the session report screen. The DB write is non-blocking by design.

---

## 8. Intervention Event Persistence (D12, S3-36, S3-37)

### `write_intervention_event()` — fire-and-forget

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

Exception handling: all exceptions are caught, logged at ERROR, and captured to Sentry. Never re-raised. A failed write means the audit record is absent; the intervention was already delivered to the student.

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

### `session_events` table — inserted row shape

```json
{
  "session_id": "<uuid>",
  "event_type": "intervention_triggered",
  "payload": {
    "intervention_type": "distraction" | "fatigue",
    "window_index": 0,
    "ces_at_trigger": 42.5,
    "message_key": "distraction_01"
  }
}
```

`event_type` literal is always `"intervention_triggered"`. The `payload->>'intervention_type'` field distinguishes distraction from fatigue.

Session ceiling: at most 4 rows per session (3 distraction + 1 fatigue) — enforced upstream by Lua guard and SET-NX, not by `write_intervention_event`.

### `"intervention_triggered"` in KNOWN_EVENT_TYPES

`apps/api/app/modules/analytics/service.py` — `"intervention_triggered"` must be present in `KNOWN_EVENT_TYPES`. Without it, analytics batches containing this `event_type` are soft-rejected (written to `session_events` but the analytics side-path drops them).

---

## 9. Session Report Fields (D17, D18, D19)

### `ces_score` — nullable API field (D17, S3-53 Phase 2)

**Backend:**
```python
# assessment/service.py:943-945
ces_score: float | None = float(ces_final) if ces_final is not None else None
```

**Router model:**
```python
# assessment/router.py:47
ces_score: float | None = None  # None when session ended before finalization
```

**Frontend type:**
```typescript
// web/src/types/assessment.ts:93
ces_score: number | null; // null when session ended before _finalize_session ran
```

**Before S3-53 Phase 2:** `ces_score` defaulted to `0.0` for None, making incomplete sessions appear as zero engagement.

**Rule for consumers:** Never substitute `0` for null when displaying `ces_score`. Use `formatCesLabel(ces_score)` which returns `"Not measured"` for null.

### `ces_history_summary` (D18)

**Source:** Redis `session:{id}:ces_history` (lrange 0, 9)

```python
ces_history_summary = {
    "mean": round(sum(ces_vals) / len(ces_vals), 2),
    "min": round(min(ces_vals), 2),
    "max": round(max(ces_vals), 2),
    "window_count": len(ces_vals),
}
```

Returns `None` if Redis unavailable or history is empty. Reflects the MOST RECENT 10 windows only — not the full session history. A 90-minute session at 5 s cadence generates ~1,080 windows; only the last 10 are summarised.

### `intervention_messages_used` (D19)

Count of `intervention_triggered` rows in `session_events` for the session. Same as `interventions_count`. WS delivery failures are NOT subtracted — the field counts events written to DB, not confirmed deliveries.

---

## 10. Color-Coded CES Display (D20, S3-53 Phase 2)

### `cesScoreColor` — Tailwind class by threshold

**File:** `apps/web/src/lib/utils.ts:58-63`

```typescript
export function cesScoreColor(cesScore: number | null): string {
    if (cesScore === null || !Number.isFinite(cesScore)) return "text-neutral-400";
    if (cesScore >= 70) return "text-emerald-600 dark:text-emerald-400";
    if (cesScore >= 50) return "text-amber-600 dark:text-amber-400";
    return "text-rose-600 dark:text-rose-400";
}
```

| Score | Tailwind class | Semantic meaning |
|-------|---------------|-----------------|
| null / non-finite | `text-neutral-400` | No data collected |
| ≥ 70 | `text-emerald-*` | Strong engagement |
| 50–69 | `text-amber-*` | Moderate engagement |
| < 50 | `text-rose-*` | Low engagement; intervention likely triggered |

**Note:** The display threshold (50 for amber/rose boundary) deliberately matches the intervention trigger threshold so the student intuitively connects "rose" with "you needed a check-in."

### `formatCesLabel` — null-safe (S3-53 fix)

**File:** `apps/web/src/lib/utils.ts:49-56`

Accepts `number | null`. Returns `"Not measured"` for null. Returns `"Unknown"` for non-finite values. Returns one of four descriptive labels for valid scores (80+, 60+, 40+, <40). Raw numeric scores are NEVER shown as the primary label — PRD §18 prohibition.

### SessionReport.tsx — Focus tile

Applies `cesScoreColor` for text class. Shows `{Math.round(ces_score)}/100` as a subtitle ONLY when `ces_score !== null`. When null, shows only the "Not measured" label in neutral grey with no numeric subtitle.

---

## 11. Dev 3 ↔ Dev 4 Integration Contract

### Who owns what

| Component | Owner | File | Notes |
|-----------|-------|------|-------|
| `compute_ces()` formula (report/test) | Dev 3 | `assessment/ces.py` | Aligned with live path as of S3-53 |
| `compute_ces(signal)` live implementation | Dev 4 | `tutor/service.py` | Called every attention signal |
| `NormalizedSignal` model | Dev 4 | `tutor/service.py` | |
| `process_attention_signal()` | Dev 4 | `tutor/service.py` | Main signal processing function |
| `_can_intervene_distraction()` | Dev 4 | `tutor/state_machine/graph.py` | Lua guard |
| `_can_intervene_fatigue()` | Dev 4 | `tutor/state_machine/graph.py` | EXISTS + SET-NX |
| `intervening_node()` | Dev 4 | `tutor/state_machine/graph.py` | Calls write_intervention_event |
| `session_end_node()` + `_finalize_session()` | Dev 4 | `tutor/state_machine/graph.py` | Writes ces_final + ended_at |
| `write_intervention_event()` | Dev 3 | `assessment/service.py` | Called by Dev 4's intervening_node |
| `_get_distraction_count()` | Dev 3 | `assessment/service.py` | Redis-first DB fallback (dead code — D63) |
| `compute_ces_from_session_aggregates()` | Dev 3 | `assessment/service.py` | Dead code — D62 |
| `get_session_report()` + `_build_ces_breakdown()` | Dev 3 | `assessment/service.py` | Session report generation |
| `ces_history_summary` field | Dev 3 | `assessment/service.py` | Reads Dev 4's Redis history keys |
| `intervention_messages_used` field | Dev 3 | `assessment/service.py` | Reads `session_events` written by Dev 4 |
| `_init_session_state()` + `session_start_ts` | Dev 4 | `core/websocket.py` | D15/S3-40 |
| `lesson_complete` WS dispatch | Dev 2 | `AudioTimeline.tsx` | D16/S3-53 Phase 2 — triggers finalization |

### Dev 2 contract additions (S3-53 Phase 2)

**`ces_score: number | null`** in `SessionReport` type (`web/src/types/assessment.ts:93`). Dev 2 must not assume `ces_score` is always a number. Use `cesScoreColor(report.ces_score)` and `formatCesLabel(report.ces_score)` from `utils.ts` — both are null-safe.

### Redis key handoff points

Dev 4 writes these keys; Dev 3 reads them in `get_session_report`:

```
Dev 4 writes:                           Dev 3 reads:
──────────────────────────────────────────────────────────────────
session:{id}:ces_history       →   get_session_report() ces_history_summary
session:{id}:behavioral_history → get_session_report() _build_ces_breakdown()
session:{id}:head_pose_history  → get_session_report() _build_ces_breakdown()
session:{id}:blink_history      → get_session_report() _build_ces_breakdown()
session_events (via create_task) → get_session_report() interventions_count / intervention_messages_used
sessions.ces_final (via _finalize_session) → get_session_report() ces_score field
```

### Breaking change protocol

Any change to the following requires explicit sync between Dev 3, Dev 4, and (where applicable) Dev 2:

- `NormalizedSignal` field names or types → breaks `assessment/ces.py` signature alignment
- Redis key naming scheme → breaks `get_session_report` silently (no error, zero values)
- `session_events.event_type = "intervention_triggered"` literal → breaks intervention count query
- `payload` shape of `intervention_triggered` events → breaks `_get_distraction_count` (if ever wired)
- `ces_history` JSON format `{"v": float, "t": int}` → break D4 gap check (backward-compat fallback exists for bare floats)
- `ces_score: number | null` frontend type → break any Dev 2 code treating it as always-number
- `AudioTimeline` WS send for `lesson_complete` → removing it makes finalization unreachable again

These are frozen contracts. Shape changes require a 4-dev PR review per CLAUDE.md §16.

---

## 12. Redis Key Schema (Complete Reference)

All keys scoped to `session_id` (UUIDv4). Shared across Railway Redis — all replicas see the same keys. `_STATE_TTL = 86400` s in `graph.py`. `_CES_WINDOW_TTL = 86400` s in `service.py`.

| Key | Format | Type | Written by | TTL | Cap | Notes |
|-----|--------|------|-----------|-----|-----|-------|
| `tutor_state:{session_id}` | string | FSM state name | `graph.py:_persist_state` | 86400 s | N/A | Current tutor FSM state |
| `tutor_ces:{session_id}` | string | float | `tutor/service.py` | 86400 s | N/A | Current-window CES; backward compat alias |
| `tutor_cooldown:{session_id}` | string | "1" | `graph.py:intervening_node` | 120 s (default) | N/A | Present during 2-min cooldown. `nx=True` so first writer wins. |
| `tutor_distraction_count:{session_id}` | string | int | Lua INCR inside `_DISTRACTION_GUARD_LUA` | 86400 s | N/A | Count of distraction interventions (max 3) |
| `tutor_fatigue_fired:{session_id}` | string | "1" | `graph.py:_can_intervene_fatigue` (SET-NX) | 86400 s | N/A | Once-per-session flag. SET-NX is atomic. |
| `session:{id}:ces_window` | string | float | `tutor/service.py` | 86400 s | N/A | Latest CES window value |
| `session:{id}:ces_history` | Redis list | JSON `{"v": float, "t": int}` | `tutor/service.py` | 86400 s | 10 (ltrim) | LPUSH prepends; index 0 = most recent. Legacy bare floats accepted. |
| `session:{id}:behavioral_history` | Redis list | float strings | `tutor/service.py` | **None (D64)** | 10 (ltrim) | Written only when `behavioral_score is not None`. |
| `session:{id}:head_pose_history` | Redis list | float strings | `tutor/service.py` | **None (D64)** | 10 (ltrim) | Written only when `head_pose_score is not None`. |
| `session:{id}:blink_history` | Redis list | float strings | `tutor/service.py` | **None (D64)** | 10 (ltrim) | Written only when `blink_rate is not None`. |
| `session:{id}:session_start_ts` | string | Unix timestamp int | `core/websocket.py:_init_session_state` | 86400 s | N/A | `nx=True` — first-connect wins; reconnects do not reset. |
| `session:{id}:segment_index` | string | int | `tutor/service.py:advance_tutor_state` | 86400 s | N/A | Current segment position (0-based). |
| `session:{id}:quiz_deadline_at` | string | Unix timestamp int | `graph.py:quizzing_node` | 86400 s | N/A | Quiz time limit. |
| `session:{id}:qa_phase_seconds` | string | int | `core/websocket.py:_seed_learner_tier` | — | N/A | Tier-based Q&A phase duration. |
| `lesson_package:{session_id}` | string | JSON | `core/pubsub.py` (Dev 4) | — | N/A | Cached `LessonPackage`. Read-only in service.py. |
| `user:{user_id}:ces_baseline` | string | float | Assessment module (Dev 3) | 86400 s | N/A | Per-user CES baseline (average of last N sessions). |

---

## 13. Configuration Reference (env vars)

All CES-related settings are in `apps/api/app/config.py:Settings`.

| Env Var | Config Field | Default | Validation | Scope |
|---------|-------------|---------|------------|-------|
| `CES_WEIGHT_QUIZ` | `ces_weight_quiz` | 0.35 | 0–1; sum must = 1.0 ± 0.001 | per deployment |
| `CES_WEIGHT_TEACHBACK` | `ces_weight_teachback` | 0.25 | same | per deployment |
| `CES_WEIGHT_BEHAVIORAL` | `ces_weight_behavioral` | 0.20 | same | per deployment |
| `CES_WEIGHT_HEAD_POSE` | `ces_weight_head_pose` | 0.12 | same | per deployment |
| `CES_WEIGHT_BLINK` | `ces_weight_blink` | 0.08 | same | per deployment |
| `CES_THRESHOLD` | `ces_threshold` | 50.0 | — | per deployment; affects all active sessions |
| `CES_FATIGUE_BLINK_THRESHOLD` | `ces_fatigue_blink_threshold` | 0.3 | ge=0, le=1 | per deployment; Schleicher et al. 2008 basis |
| `CES_FATIGUE_HEAD_POSE_THRESHOLD` | `ces_fatigue_head_pose_threshold` | 0.3 | ge=0, le=1 | per deployment; Bosch et al. 2015 basis |
| `CES_FATIGUE_MIN_SESSION_SECONDS` | `ces_fatigue_min_session_seconds` | 900 | ge=60 (startup rejects < 60) | per deployment |
| `CES_CADENCE_SECONDS` | `ces_cadence_seconds` | 5 | gt=0 | per deployment; D4 gap tolerance = 2× cadence |
| `CES_BASELINE_WINDOW` | `ces_baseline_window` | 5 | ge=1, le=50 | per deployment |
| `CES_BASELINE_TTL_SECONDS` | `ces_baseline_ttl_seconds` | 86400 | ge=60 | per deployment; Redis TTL |
| `INTERVENTION_COOLDOWN_SECONDS` | `intervention_cooldown_seconds` | 120 | — | per deployment; shared via Railway Redis |
| `MAX_DISTRACTION_PER_SESSION` | `max_distraction_per_session` | 3 | — | per deployment; Lua ARGV[1]; affects all active sessions immediately |
| `DNA_EMA_RETAIN` | `dna_ema_retain` | 0.7 | ge=0, le=1 | per deployment |

**Scale note:** `CES_THRESHOLD` and `MAX_DISTRACTION_PER_SESSION` take effect immediately for all active sessions when the env var changes. There is no per-session snapshotting of these values.

---

## 14. Database State — Supabase Audit (2026-08-13)

**Both projects confirmed ACTIVE_HEALTHY, ap-south-1, PostgreSQL 17.6, 12 migrations applied, identical schema.**

| Project | ID | Status | Migrations |
|---------|-----|--------|-----------|
| `transformed-dev` | `kxhgvwopdszclfyrrkqm` | ACTIVE_HEALTHY | 12 applied |
| `CSS_HIE` | `xjypglfmjunmlccbhjgn` | ACTIVE_HEALTHY | 12 applied |

### Applied migrations (both projects)

| # | Migration name |
|---|----------------|
| 1 | `initial_schema` |
| 2 | `chunks_inline_embedding_and_books_table` |
| 3 | `unique_attempt_constraints` |
| 4 | `dpdp_user_consents` |
| 5 | `onboarding_unique_constraint` |
| 6 | `add_analytics_consent` |
| 7 | `storage_buckets` |
| 8 | `lesson_job_node_output_merge_fn` |
| 9 | `add_lesson_tier` |
| 10 | `chapters_book_scoped` |
| 11 | `user_consents_unique_constraint` |
| 12 | `user_notification_preferences` |

### CES columns confirmed present in both projects

| Table | Column | Type | Nullable | Used by |
|-------|--------|------|----------|---------|
| `sessions` | `ces_final` | numeric | YES | `_finalize_session` write; `get_session_report` read |
| `sessions` | `ended_at` | timestamptz | YES | `_finalize_session` write |
| `session_events` | `event_type` | text | NO | `write_intervention_event` write; `get_session_report` count |
| `session_events` | `payload` | jsonb | NO | `write_intervention_event` write; `_get_distraction_count` (dead) |

**No migrations are required** for the CES lifecycle as currently implemented.

### Optional schema improvements (Sprint 4 candidates, not yet filed as stories)

1. **`sessions.ces_breakdown jsonb` column** — persist per-signal averages at finalization time. Currently computed from Redis at report fetch; fallback to zeros if Redis is flushed between session end and report view. Fix: write at `_finalize_session` time alongside `ces_final`. Requires 1 migration + changes in `_finalize_session` + `get_session_report`.

2. **Composite index `(session_id, event_type)` on `session_events`** — makes the intervention count query in `get_session_report` an index-only scan. Currently uses separate `session_id_idx` + filter on `event_type`. Low-priority until Sprint 4 load tests.

---

## 15. Defect Register Cross-Reference

The entries below (D61–D65) use **global defect register numbering** (not CES decision IDs).

---

### D61 — `session_start_ts` missing silently disables fatigue

**Status:** OPEN · **Owner:** Dev 4 · **Severity:** Medium

If `_init_session_state` runs while Redis is unavailable, `session_start_ts` is never written. Every subsequent `process_attention_signal` call skips the entire fatigue block for the session duration. A `logger.warning` is emitted. **No DB fallback to `sessions.started_at`.**

**Impact:** Fatigue interventions never fire for affected sessions. CES computation and distraction detection are unaffected.

**Full fix:** Fall back to `sessions.started_at` from Supabase when the Redis key is absent.

---

### D62 — `compute_ces_from_session_aggregates` dead code; partial fix in S3-53

**Status:** PARTIALLY FIXED · **Owner:** Dev 3 · **Severity:** Medium

`assessment/service.py:compute_ces_from_session_aggregates()` is defined but never called in production. `_finalize_session` has its own inline averaging.

**S3-53 fixes applied:**
- `_finalize_session` now returns `None` (not `0.0`) for empty history
- Both `compute_ces` implementations now agree on `None`-redistribution

**Remaining gap:** `compute_ces_from_session_aggregates` is still dead code. If it is ever wired into `_finalize_session`, the `None`-for-fewer-than-5-windows minimum requirement would conflict with the current inline behavior (no minimum). Wiring requires an explicit story.

**Three-way comparison as of 2026-08-13:**

| Path | Function | Empty history | < 5 windows |
|------|----------|---------------|-------------|
| `get_session_report` inline | anonymous | `None` | Returns summary (no minimum) |
| `_finalize_session` inline | `_finalize_session` | `None` (S3-53 fix) | Returns mean (no minimum) |
| `compute_ces_from_session_aggregates` | dead code | `None` | Returns `None` (has minimum of 5) |

---

### D63 — `_get_distraction_count` dead code

**Status:** OPEN · **Owner:** Dev 3 · **Severity:** Medium

`assessment/service.py:_get_distraction_count()` implements Redis-first DB-fallback distraction counting. Tested in isolation. `dna_fusion.py` has no import and no call to it. `frustration_tolerance` Learner DNA dimension never decrements.

**Fix:** Import and call `_get_distraction_count(session_id, redis=redis, supabase=supabase)` in `fuse_learner_dna()`.

---

### D64 — Per-signal history keys have no TTL

**Status:** OPEN · **Owner:** Dev 3/Dev 4 · **Severity:** Low–Medium

`session:{id}:behavioral_history`, `session:{id}:head_pose_history`, and `session:{id}:blink_history` have no `EXPIRE` after `ltrim`. Orphaned keys from sessions that end abnormally (browser close before SESSION_END) accumulate without bound. Railway Redis has a 64 MB memory limit.

**Fix:** Add after each `ltrim` in `tutor/service.py:322`, `330`, `336`:
```python
await redis.expire(f"session:{session_id}:behavioral_history", _CES_WINDOW_TTL)
await redis.expire(f"session:{session_id}:head_pose_history", _CES_WINDOW_TTL)
await redis.expire(f"session:{session_id}:blink_history", _CES_WINDOW_TTL)
```

---

### D65 — Distraction positive trigger path has zero unit test coverage

**Status:** PARTIALLY FIXED (S3-52) · **Owner:** Dev 4 · **Severity:** Medium

The positive distraction trigger path (TEACHING + 2 sub-threshold CES + gap_ok + Lua guard returns 'ok' → `dispatch_event("distraction_detected")`) has no unit test. The Lua script, cooldown check, distraction cap, and fatigue-blocks-distraction-in-same-window are all live code with zero positive-path coverage.

**S3-52 partial fix:** stale-history non-dispatch, QUIZZING/INTERVENING blocking, per-signal history not written in QUIZZING — covered.

**Remaining gap:** Write `tests/test_distraction_trigger.py` covering the POSITIVE trigger path.

---

## 16. What Is NOT Implemented (Known Gaps Summary)

| Gap | Status | Severity | Fix |
|-----|--------|----------|-----|
| `_finalize_session` never called before S3-53 | **FIXED** (S3-53) | Was critical | `lesson_complete` dispatch added to `AudioTimeline.tsx` |
| `ces_score=0.0` for None (silent) | **FIXED** (S3-53) | Was medium | `ces_score: float \| None` in service + router + frontend |
| `quiz_accuracy=None` formula divergence | **FIXED** (S3-53) | Was medium | `assessment/ces.py` aligned with `tutor/service.py` |
| `compute_ces_from_session_aggregates` dead code | OPEN | Medium | Wire into `_finalize_session` or delete |
| `_get_distraction_count` dead code | OPEN | Medium | Wire into `dna_fusion.py` |
| Per-signal history keys have no TTL | OPEN | Low | Add `expire()` after each `ltrim` |
| Distraction positive trigger path untested | OPEN | Medium | Write `tests/test_distraction_trigger.py` |
| `session_start_ts` missing → fatigue disabled silently | OPEN | Medium | DB fallback to `sessions.started_at` |
| `ces_breakdown` not persisted to DB | OPEN | Low | Add `ces_breakdown jsonb` column (Sprint 4 candidate) |
| Fatigue cooldown race (EXISTS→SET-NX not atomic) | ACCEPTED | Low | Lua script combining both steps — noted in S3-52 Scale §6 |
| WS delivery failures not reflected in intervention count | ACCEPTED | Low | Intentional — field counts triggered, not delivered |
