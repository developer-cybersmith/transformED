---
baseline_commit: "eba1f0a579ffd0eaf94feb3a27d7ad6a325a4658"
---

# Story 4-2: Test Coverage for the Redis CES Signal Buffer

**Status:** in-progress

---

## Story

As Dev 4,
I want unit tests proving `process_attention_signal()` correctly maps signals, writes the
`ces_window`/`ces_history` Redis keys via LPUSH/LTRIM/expire, reads via LRANGE, and dispatches
`distraction_detected` only when the guard conditions hold,
so that the Sprint 0 `redis_lpush_pattern` task (and the related Sprint 1 `redis_signal_buffer` AC)
can move from **Partial** to **Completed** on proven behaviour, not just inspection.

---

## Context — cross-check finding (2026-06-29)

The tracker marked `redis_lpush_pattern` **Partial** with the note *"pattern not implemented / AC NOT MET."*
That note is **stale**: `apps/api/app/modules/tutor/service.py` already implements the full pattern in
`process_attention_signal()`:

- `redis.set("session:{sid}:ces_window", ces, ex=86400)`
- `redis.lpush("session:{sid}:ces_history", ces)` → `redis.ltrim(..., 0, 9)` → `redis.expire(..., 86400)`
- `redis.lrange("session:{sid}:ces_history", 0, 9)`
- trigger: two most-recent values both `< settings.ces_threshold` **and** no `tutor_cooldown:{sid}` →
  `dispatch_event(sid, "distraction_detected")`

The genuine gap is **test coverage** — no test exercises any of this. This story adds it. No production
code changes.

---

## Acceptance Criteria

### Parsing (`_parse_signal`)

- **AC 1:** A full `WsMessage` envelope `{"type": "attention_signal", "payload": {...}}` and a flat dict
  produce an equivalent `NormalizedSignal`.
- **AC 2:** Missing `session_id` → `ValueError`; missing any required float (`behavioral_score`,
  `head_pose_score`, `blink_rate`) → `ValueError`.
- **AC 3:** `quiz_accuracy=None` and `teachback_score=None` are preserved as `None` (not coerced);
  a non-numeric value for any field → `ValueError`.

### Buffer writes (`process_attention_signal`)

- **AC 4:** `ces_window` is written with `ex=86400` and key `session:{sid}:ces_window`.
- **AC 5:** `lpush` → `ltrim(key, 0, 9)` → `expire(key, 86400)` are all called on
  `session:{sid}:ces_history`.
- **AC 6:** history is read via `lrange(key, 0, 9)`.

### Trigger logic

- **AC 7:** Two most-recent history values both `< ces_threshold` AND no cooldown →
  `dispatch_event(sid, "distraction_detected")` called once; `CesResult.intervention_dispatched is True`.
- **AC 8:** One below + one above threshold → `dispatch_event` NOT called; `intervention_dispatched is False`.
- **AC 9:** Both below threshold BUT `tutor_cooldown:{sid}` exists → NOT dispatched.
- **AC 10:** Fewer than 2 history values → NOT dispatched.
- **AC 11:** `CesResult` carries the correct `session_id` and `ces`.

---

## Tasks / Subtasks

- [ ] 1.1 Create `apps/api/tests/test_tutor_service.py`.
- [ ] 1.2 Parsing tests (AC 1–3) calling `_parse_signal` directly.
- [ ] 1.3 Buffer-write tests (AC 4–6) asserting Redis mock call args/order.
- [ ] 1.4 Trigger tests (AC 7–10) controlling `lrange` return + `exists` (cooldown) + `ces_threshold`.
- [ ] 1.5 Result test (AC 11).
- [ ] 1.6 Run `pytest tests/test_tutor_service.py -v` → green; full suite → no regressions.

---

## Dev Notes

### File to change

| File | Change | What |
|------|--------|------|
| `apps/api/tests/test_tutor_service.py` | CREATE | Full CES buffer test file |

No production code changes. `service.py` is already correct.

### Patch targets (lazy imports inside `process_attention_signal`)

`process_attention_signal` imports inside the function body, so patch at the source modules:
- `app.core.redis.get_redis` → return an `AsyncMock()` redis
- `app.config.get_settings` → return a `MagicMock` with `.ces_threshold`
- `app.modules.tutor.state_machine.graph.dispatch_event` → `AsyncMock()`

`_parse_signal` and `compute_ces` are pure/sync and imported directly from
`app.modules.tutor.service`.

### Redis mock shape

```python
redis = AsyncMock()
redis.lrange = AsyncMock(return_value=["0.1", "0.2"])  # index 0 = most recent
redis.exists = AsyncMock(return_value=0)               # 0 = no cooldown
```

`compute_ces` is a stub returning `0.5`, so the *written* CES is always 0.5; the trigger is driven by
the **mocked `lrange` return**, not by what `lpush` wrote (redis is mocked). Control `ces_threshold` and
the `lrange` list to exercise each branch:
- AC 7 dispatch: `lrange=["0.1","0.2"]`, `ces_threshold=0.5`, `exists=0`
- AC 8 no dispatch: `lrange=["0.1","0.9"]`, `ces_threshold=0.5`
- AC 9 cooldown: `lrange=["0.1","0.2"]`, `exists=1`
- AC 10 short history: `lrange=["0.1"]`

### Conventions

- `@pytest.mark.unit` on every test; `from __future__ import annotations`.
- Async tests run under `asyncio_mode = "auto"` (pyproject).
- Assert Redis call args with `assert_any_call` / inspect `call_args_list` for ordering (AC 5).
