---
baseline_commit: "e0733e3b41cf4f3e8ceaf86f77d3aecd11a4fa27"
---

# Story 4-8: Intervention Message Selection + Delivery

**Status:** in-progress

---

## Story

As Dev 4,
I want a triggered intervention to fetch the pre-generated message for the right type + current segment
from a Redis-cached LessonPackage and deliver it to the student over WebSocket (`tutor_intervene`, Redis
reads only, no DB/LLM on the hot path),
so that the Sprint 2 `intervention_selection` task is complete (it's currently Partial — the FSM selects
the message but nothing caches the package, tracks the segment, or delivers it).

---

## Context (architect design — Winston, 2026-06-30)

- `intervening_node` already selects `event_payload["intervention_messages"][type][0]` →
  `state["intervention_message"]`. Missing: package cache, segment tracking, delivery.
- The `lesson_ready` pub/sub subscriber (`core/pubsub.py`) already receives the full package in
  `payload.payload.lesson` — piggyback a Redis cache write there.
- `process_attention_signal` runs IN the API process → `manager.send` is reachable (lazy import).
- ws.ts frozen outbound type is **`tutor_intervene`** with payload `{session_id, type, message, action?}`
  (NOT `"intervention"` — that's the stale Bug #5b name).

---

## Acceptance Criteria

- **AC 1:** On a `lesson_ready` pmessage, the subscriber caches the package at
  `lesson_package:{session_id}` (JSON, 24h TTL) in addition to forwarding it to the client.
- **AC 2:** `session:{session_id}:segment_index` (int, default 0 when absent) is INCREMENTED when a
  `segment_complete` event is dispatched (via `advance_tutor_state`), with 24h TTL.
- **AC 3:** When `process_attention_signal` triggers an intervention, it reads the cached package + segment
  index (clamped to range), passes that segment's `intervention_messages` into the dispatch payload, and —
  if the guard fired the intervention (`current_state == INTERVENING`) and a message was selected — sends a
  `tutor_intervene` message `{type:"tutor_intervene", payload:{session_id, type, message}}` via `manager.send`.
- **AC 4 (degrade):** Cache miss / JSON error / empty-or-short segments / index out of range → no crash, no
  synchronous Supabase read; the FSM still records the intervention + cooldown, and the `tutor_intervene`
  send is skipped (logged). `process_attention_signal` still returns its `CesResult`.
- **AC 5 (latency / hot path):** The intervention path performs only Redis reads (GET package + GET index)
  + `manager.send` — NO DB/Supabase call, NO LLM.
- **AC 6:** `manager` is imported lazily inside the function (in-process); never imported into the FSM node
  or any worker path.

---

## Tasks / Subtasks

- [ ] 1.1 `core/pubsub.py`: after the existing `manager.send`, cache `lesson_package:{sid}` from the
  forwarded message's `payload.lesson` (best-effort; a cache failure must not break forwarding).
- [ ] 1.2 `tutor/service.py` `advance_tutor_state`: when `event == "segment_complete"`, `INCR
  session:{sid}:segment_index` + `expire` 24h (before/after dispatch — order doesn't matter for the index).
- [ ] 1.3 `tutor/service.py`: add `_segment_intervention_messages(session_id, redis) -> dict` helper
  (GET package, json.loads, clamp index, return `segments[idx].intervention_messages` or `{}` on any miss).
- [ ] 1.4 `tutor/service.py` `process_attention_signal`: pass `{"intervention_messages": seg_msgs}` to
  `dispatch_event`; deliver `tutor_intervene` via lazily-imported `manager` when INTERVENING + message present;
  wrap delivery so it never breaks the `CesResult` return.
- [ ] 1.5 Tests + full regression.

---

## Dev Notes

### pubsub cache write (AC1)

In `_run_lesson_subscriber`, after `await manager.send(session_id, message)`:
```python
try:
    lesson = (message.get("payload") or {}).get("lesson")
    if lesson is not None:
        await _sub_conn.set(f"lesson_package:{session_id}", json.dumps(lesson), ex=86400)
except Exception:
    logger.warning("lesson_package cache write failed for %s", session_id)
```
Use the subscriber's own connection (`_sub_conn`) or `get_redis()` — either is in the API process. Keep it
best-effort (never break message forwarding).

### segment_index (AC2) — advance_tutor_state

```python
async def advance_tutor_state(session_id, event):
    if event not in _CLIENT_DRIVABLE_EVENTS:
        raise ValueError(...)
    from app.core.redis import get_redis
    from app.modules.tutor.state_machine.graph import dispatch_event
    if event == "segment_complete":
        redis = get_redis()
        await redis.incr(f"session:{session_id}:segment_index")
        await redis.expire(f"session:{session_id}:segment_index", 86400)
    await dispatch_event(session_id, event)
```

### selection helper + delivery (AC3–AC6) — process_attention_signal

```python
async def _segment_intervention_messages(session_id, redis) -> dict:
    try:
        raw = await redis.get(f"lesson_package:{session_id}")
        if not raw:
            return {}
        pkg = json.loads(raw)
        segments = pkg.get("segments") or []
        if not segments:
            return {}
        idx_raw = await redis.get(f"session:{session_id}:segment_index")
        idx = int(idx_raw) if idx_raw else 0
        idx = max(0, min(idx, len(segments) - 1))
        return segments[idx].get("intervention_messages") or {}
    except Exception:
        logger.warning("intervention message lookup failed for %s", session_id, exc_info=True)
        return {}
```

In the trigger block, replace the bare dispatch:
```python
seg_msgs = await _segment_intervention_messages(session_id, redis)
result = await dispatch_event(session_id, "distraction_detected",
                              payload={"intervention_messages": seg_msgs})
intervention_dispatched = result.get("current_state") == "INTERVENING"
msg = result.get("intervention_message")
if intervention_dispatched and msg:
    try:
        from app.core.websocket import manager
        await manager.send(session_id, {
            "type": "tutor_intervene",
            "payload": {
                "session_id": session_id,
                "type": result.get("intervention_type") or "distraction",
                "message": msg,
            },
        })
    except Exception:
        logger.exception("tutor_intervene delivery failed for %s", session_id)
```
Compare `current_state` as a string (`"INTERVENING"`) — TutorState is a StrEnum so `== "INTERVENING"` holds.
`json` is already imported in service.py.

### Test patch targets

- `app.core.redis.get_redis` (AsyncMock); for the package, `redis.get(lesson_package:{sid})` returns a JSON
  string of a package with one segment carrying intervention_messages; `redis.get(segment_index)` → "0".
- Delivery: patch `app.core.websocket.manager` with a MagicMock whose `.send` is an AsyncMock; assert called
  with the `tutor_intervene` shape. (Lazy import resolves the patched module attribute.)
- Degrade test: `redis.get(lesson_package)` → None → assert `manager.send` NOT called, no raise, CesResult returned.
- pubsub AC1: drive `_run_lesson_subscriber` (existing test pattern) with a lesson_ready pmessage carrying
  `payload.lesson`; assert the sub connection `.set("lesson_package:{sid}", ...)` was called.
- segment_index AC2: `advance_tutor_state(sid, "segment_complete")` → assert `redis.incr(session:{sid}:segment_index)`.

### Out of scope (deferred)

- **Message rotation** (always `[0]` for now) — cheap follow-up: rotate distraction by its incremented count.
- Richer segment-progression signals (slide-level); delivering `fatigue`/`confusion` triggers (no caller
  dispatches them yet — design is type-generic).
- Broader `"intervention"` → `"tutor_intervene"` rename elsewhere (Bug #5b) — separate cleanup.

---

## Review outcome (adversarial — Blind + Edge Case Hunter, 2026-06-30)

**🐛 CRITICAL fixed (both reviewers, independently):** the selection read `segments[idx].interventions_messages`
[sic] — actually `intervention_messages` — but the frozen `Segment` schema (`schemas/lesson.py:181`,
`lesson_package.schema.json`) names the field **`interventions`** (`SegmentInterventions` =
{distraction|confusion|fatigue: [3]}). Against a real package the lookup returned `None` → `{}` → **no
intervention message would EVER be delivered in production**, and the original tests masked it by inventing the
`intervention_messages` key. **Fixed:** `_segment_intervention_messages` now reads `interventions`; test
fixtures use the real field. (The internal service→FSM payload key stays `intervention_messages` — consistent
on both sides, not a contract.)

**Also applied:**
- Reset `session:{sid}:segment_index` in `_init_session_state` (on WS connect) so a reused session_id never
  inherits a stale 24h index (MED). Asserted in websocket test A3.
- Direct `_segment_intervention_messages` unit tests: happy (correct `interventions` field), cache miss,
  malformed JSON, empty segments, out-of-range index clamp.
- Strengthened the pub/sub cache test (asserts value + `ex=86400`) and the segment_complete test (asserts `expire`).

**Flagged — NOT changed:**
- TTL-expiry mid-session reconnect with no re-publish → cache miss → degrade (no message). MVP-acceptable;
  a warm-on-reconnect re-hydrate would need a (non-hot-path) DB read.
- `type` sent to client isn't validated against the `InterventionType` union — low risk (FSM sets a fixed set).
- Message rotation still `[0]` (deferred).
