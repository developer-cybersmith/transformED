---
baseline_commit: "6cbc4c1b1a53dac04602c74fa5fec19a77347326"
---

# Story 4-7: Full 7-State Machine Real Logic + Fatigue Bug Fix

**Status:** in-progress

---

## Story

As Dev 4,
I want the tutor FSM nodes to carry real intervention logic — correct intervention-type recording
(fixing the fatigue bug), pre-generated message selection, the `in_teachback` flag, and Langfuse tracing —
so that the Sprint 2 `full_state_machine` task is complete and a simulated session flows
IDLE → TEACHING → INTERVENING → TEACHING without errors.

---

## Context

- **MED bug (from s2-2 review):** `dispatch_event` sets `intervention_type = payload.get("intervention_type")
  if payload else None`. `distraction_detected` / `fatigue_detected` are dispatched WITHOUT a payload, so
  `intervention_type` is `None` → `intervening_node` records neither branch → `tutor_fatigue_fired` is never
  set and `tutor_distraction_count` is never incremented on the real CES path. The fatigue-once guard can't
  trip in production.
- **Intervention message selection:** `intervening_node` is a partial stub — it records + sets cooldown but
  does not select the pre-generated message. `LessonPackage` segments carry
  `intervention_messages: {distraction: [3], confusion: [3], fatigue: [3]}` (frozen schema). Valid types:
  **distraction | confusion | fatigue**.
- **Langfuse:** `get_langfuse()` singleton exists (`core/langfuse.py`); no tracing around `dispatch_event` yet.
- **`in_teachback`:** `teach_back_node` already returns `in_teachback: True`; `teaching_node` resets it to
  `False`. (Verify with a test.)

**Boundary:** the actual DB/Redis `LessonPackage` *fetch* and the WS *delivery* to the client (`{type:
intervention, message, ...}`, <50ms latency) are the separate `intervention_selection` task. Here,
`intervening_node` selects from a package supplied via the event payload and stores the chosen message in
state; fetch + delivery come later.

---

## Acceptance Criteria

### Fatigue bug fix (MED)

- **AC 1:** `dispatch_event` derives `intervention_type` from the event when not given in payload:
  `distraction_detected → "distraction"`, `fatigue_detected → "fatigue"`, `teachback_failed → "confusion"`.
  An explicit `payload["intervention_type"]` still wins.
- **AC 2:** A `fatigue_detected` event that reaches `intervening_node` sets `tutor_fatigue_fired = "1"`
  (so the fatigue-once guard trips on the next attempt). A `distraction_detected` increments
  `tutor_distraction_count`.

### Intervention message selection (real logic)

- **AC 3:** When the event payload carries `intervention_messages` (a segment's
  `{distraction|confusion|fatigue: [..]}`), `intervening_node` selects the list for the active
  `intervention_type` and stores the chosen message in `state["intervention_message"]` (first of the list).
- **AC 4:** When no package/messages are supplied (e.g. current CES path), `intervening_node` does NOT crash;
  `intervention_message` is `None` and recording/cooldown still happen.

### Observability

- **AC 5:** `dispatch_event` wraps `graph.ainvoke` in a Langfuse trace (name `tutor.dispatch_event`, with
  `session_id`, `event`, resulting state). Tracing is **best-effort**: a Langfuse failure or missing config
  must NEVER break a dispatch (wrapped so exceptions are swallowed).

### Flow + flags

- **AC 6:** `teach_back_node` sets `in_teachback = True`; `teaching_node` sets it `False` (test asserts).
- **AC 7:** Simulated session flows IDLE → TEACHING → INTERVENING → TEACHING (session_start →
  distraction_detected[guard allows] → intervention_complete) with no errors (stateful-Redis step-through).

### No regressions

- **AC 8:** Existing graph/websocket/service tests stay green; full suite green.

---

## Tasks / Subtasks

- [ ] 1.1 `graph.py` `dispatch_event`: add `_EVENT_INTERVENTION_TYPE` map + derive `intervention_type`
  (payload override wins). Wrap `graph.ainvoke` in a defensive Langfuse trace helper.
- [ ] 1.2 `graph.py` `intervening_node`: select `intervention_messages[intervention_type]` from
  `state["event_payload"]` when present; store first message in `state["intervention_message"]`; keep
  recording (now correct) + cooldown + persist. Add `intervention_message: str | None` to
  `TutorMachineState`.
- [ ] 1.3 Defensive Langfuse helper `_trace_dispatch(...)` (try/except, no-op on any failure).
- [ ] 1.4 Tests in `test_tutor_graph.py`: AC1–AC7.
- [ ] 1.5 Run new tests + full regression.

---

## Dev Notes

### dispatch_event — intervention_type derivation (AC1)

```python
_EVENT_INTERVENTION_TYPE = {
    "distraction_detected": "distraction",
    "fatigue_detected": "fatigue",
    "teachback_failed": "confusion",
}
...
explicit = payload.get("intervention_type") if payload else None
intervention_type = explicit or _EVENT_INTERVENTION_TYPE.get(event)
input_state["intervention_type"] = intervention_type
```

### intervening_node — message selection (AC3/AC4)

`intervention_type` defaults to `"distraction"` today (graph.py:159). Keep that default for recording, but
selection must use the real type. After the existing recording/cooldown:

```python
messages = (state.get("event_payload") or {}).get("intervention_messages") or {}
chosen_list = messages.get(intervention_type) or []
intervention_message = chosen_list[0] if chosen_list else None
return {**state, "current_state": TutorState.INTERVENING, "intervention_message": intervention_message}
```

Add `intervention_message: str | None` to `TutorMachineState`. The `event_payload` for a real CES-triggered
intervention will eventually carry the current segment's `intervention_messages` (wired by
`intervention_selection`); until then it's absent and `intervention_message` is `None` (AC4).

### Langfuse — defensive trace (AC5)

```python
def _trace_dispatch(session_id, event, result):
    try:
        from app.core.langfuse import get_langfuse
        get_langfuse().trace(
            name="tutor.dispatch_event",
            session_id=session_id,
            input={"event": event},
            output={"current_state": str(result.get("current_state")) if result else None},
        )
    except Exception:  # noqa: BLE001 — observability must never break the FSM
        logger.debug("langfuse trace skipped for %s/%s", session_id, event, exc_info=True)
```
Call it after `graph.ainvoke` returns (and on the exception path if you prefer). Verify the installed
`langfuse` (>=2.0.0) `.trace(...)` signature; if it differs, the try/except keeps the FSM safe regardless —
but aim to call the correct API. In tests, patch `app.core.langfuse.get_langfuse` with a MagicMock and assert
`.trace` was called; also a test where `get_langfuse` raises → `dispatch_event` still returns normally.

### Test patch targets

- Redis: `app.core.redis.get_redis` (AsyncMock). intervening_node needs `app.config.get_settings`
  (cooldown seconds) — use the existing `_patch_settings` helper in test_tutor_graph.py.
- Langfuse: `app.core.langfuse.get_langfuse`.
- For AC2 fatigue: seed state TEACHING, fatigue guard `redis.exists("tutor_fatigue_fired")=0`; after the
  dispatch assert `redis.set` called with `("tutor_fatigue_fired:{sid}", "1", ex=...)`.
- For AC3: pass `payload={"intervention_messages": {"fatigue": ["rest your eyes", ...], ...}}` to
  `dispatch_event(sid, "fatigue_detected", payload=...)`; assert `result["intervention_message"] ==
  "rest your eyes"`.

### Out of scope

- DB/Redis `LessonPackage` fetch + WS delivery of the intervention to the client → `intervention_selection`.
- Type alignment note: ws.ts `InterventionType` = `distraction | confusion | fatigue` (matches the schema);
  the tracker text "encouragement" is stale — use the schema's three types.

---

## Review outcome (adversarial — Blind + Edge Case Hunter, 2026-06-30)

No blocking correctness bug. Fatigue-once is enforced end-to-end; None/absent-message paths are safe; types
match the schema. 268 tests green. ACs 1–8 met.

**Applied (test gaps):**
- **AC1 override:** `test_explicit_intervention_type_overrides_event_default` — explicit payload type beats
  the event-derived one.
- **AC2 end-to-end:** `test_fatigue_fires_once_then_blocked` — fatigue fires once (real flag write) →
  intervention_complete → second fatigue blocked by the once-guard.
- **AC3 confusion:** `test_intervention_message_selected_for_confusion` — teachback_failed selects the
  confusion message set.

**⚠️ Flagged — NOT changed here:**
- **[Observability/dep] `langfuse>=2.0.0` is unpinned.** `.trace(...)` matches the existing `openai.py`
  usage and is valid for v2, but a v3 resolve removes `.trace` → the defensive try/except would silently
  no-op tutor tracing forever. Same exposure as `openai.py`. Recommend pinning langfuse. Also: the autouse
  test stub means no test exercises the real `.trace` signature.
- **[intervention_selection territory] Real CES path produces no message.** `process_attention_signal`
  dispatches `distraction_detected` with no payload, so `intervention_message` is always `None` in
  production until `intervention_selection` wires the segment's `intervention_messages` into the dispatch
  payload (and fetches the LessonPackage from DB/Redis). **Tripwire:** `intervention_selection` MUST pass
  the payload + deliver to the client, or interventions ship messageless.
- **[intervention_selection] Always selects `chosen[0]`** — the 3 pre-generated messages per type don't
  rotate; add rotation (e.g. by `tutor_distraction_count`) in `intervention_selection`.
- **[Minor] Dispatch failures aren't traced** (trace only on the success path); confusion interventions
  have no cap (cooldown-only, by design).
