---
baseline_commit: "f84668dfda27d7ff50deaf12981cbaad31e1d113"
---

# Story 4-3: Fix lesson_ready Pub/Sub Tests + Lifespan Coverage

**Status:** in-progress

---

## Story

As Dev 4,
I want the `lesson_ready` pub/sub tests to pass without depending on a fully-configured environment,
and the lifespan listener start/cancel path covered,
so that the Sprint 1 `arq_lesson_ready` task (cross-process delivery) can move from **Partial** to
**Completed** on a green, env-independent test suite.

---

## Context — cross-check finding (2026-06-29)

The tracker marked `arq_lesson_ready` **Partial** with *"AC NOT MET: cross-process delivery broken."*
That note is **stale**. Cross-process delivery is **fully implemented**:

- `workers/jobs/content_pipeline.py` publishes `{"type":"lesson_ready","payload":{session_id,lesson_id,lesson}}`
  to `lesson_ready:{session_id}` via `redis.publish` (Bug #5c nested-payload shape fixed).
- `core/pubsub.py::_run_lesson_subscriber` psubscribes `lesson_ready:*`, decodes, and forwards via
  `manager.send(session_id, message)` on a dedicated connection with back-off (Bug #6 fixed).
- `main.py` lifespan starts the listener (`start_lesson_ready_listener`) and cancels it on shutdown.
- `tests/test_lesson_ready_pubsub.py` already has 5 tests.

**The real gap:** 3 of those 5 tests are **RED**. `_run_lesson_subscriber` calls `get_settings()`, which
instantiates `Settings()` and fails validation when env vars are unset (the local/CI default). The tests
patch `app.core.pubsub.Redis` but never mock `get_settings`, so they raise `ValidationError` before
reaching any assertion. The implementation is fine; the tests are environment-fragile.

Failing:
- `test_subscriber_forwards_pmessage_to_manager`
- `test_subscriber_handles_malformed_json`
- `test_routing_reaches_correct_client_when_session_id_differs`

---

## Acceptance Criteria

- **AC 1:** The 3 failing subscriber tests pass without any real environment variables set — by mocking
  `app.config.get_settings` to return a stub whose `.redis_url` is a harmless string (the `Redis.from_url`
  call is already patched, so the value is never dialled).
- **AC 2:** No change to the assertions' intent — they still verify: pmessage → `manager.send(session_id, msg)`;
  malformed JSON → no `send`, no crash; `session_id != lesson_id` routing reaches the session key.
- **AC 3:** The 2 publish-path tests remain unchanged and green.
- **AC 4:** A new test covers the `start_lesson_ready_listener` **factory** the lifespan relies on:
  it returns a running `asyncio.Task` named `lesson_ready_subscriber`, the scheduled coroutine actually
  runs (reaches `psubscribe("lesson_ready:*")` — so a factory scheduling the wrong coroutine is caught),
  and cancelling completes cleanly (`CancelledError` propagates, no restart). The full `main.py` lifespan
  start/cancel is exercised end-to-end by the integration suite's `running_listener`.
- **AC 5:** Full `test_lesson_ready_pubsub.py` + `test_lesson_ready_integration.py` are green; no regressions
  elsewhere.

---

## Tasks / Subtasks

- [ ] 1.1 Add a small helper/fixture that patches `app.config.get_settings` → MagicMock with
  `.redis_url = "redis://localhost:6379/0"`; apply it to the 3 subscriber tests.
- [ ] 1.2 Confirm the 3 tests now pass; assertions unchanged.
- [ ] 1.3 Add `test_start_lesson_ready_listener_returns_cancellable_task` (AC 4).
- [ ] 1.4 Run the two lesson_ready test files + a regression sweep.

---

### Review Findings (dev4/s1 adversarial review — 2026-07-08)

- [ ] [Review][Patch] Flaky timing in `test_start_lesson_ready_listener_returns_cancellable_task` [`tests/test_lesson_ready_pubsub.py`] — polling loop `for _ in range(10): if mock_pubsub.psubscribe.await_count: break; await asyncio.sleep(0)` is non-deterministic under load. Replace with a `pytest-asyncio` fixture that drives the event loop until the task awaits `psubscribe` via a `threading.Event` or by awaiting the task's next suspension point explicitly.
- [x] [Review][Defer] `test_lesson_ready_integration.py` green status unverifiable from diff alone [`tests/test_lesson_ready_integration.py`] — deferred, pre-existing; run `pytest tests/test_lesson_ready_integration.py` to confirm before merging Sprint 1 integration branch.

---

## Dev Notes

### File to change

| File | Change | What |
|------|--------|------|
| `apps/api/tests/test_lesson_ready_pubsub.py` | UPDATE | Mock `get_settings` in 3 subscriber tests; add lifespan-listener test |

No production code changes. `pubsub.py`, `content_pipeline.py`, `main.py` are already correct.

### Patch target

`_run_lesson_subscriber` does `from app.config import get_settings` then `get_settings()`, and
`Redis.from_url(settings.redis_url, ...)`. So:

```python
mock_settings = MagicMock()
mock_settings.redis_url = "redis://localhost:6379/0"
mocker.patch("app.config.get_settings", return_value=mock_settings)
```

`Redis.from_url` is already patched in each subscriber test, so `redis_url` is never actually used to
connect — the mock only needs to exist so `Settings()` is never constructed.

### Lifespan listener test (AC 4)

```python
async def test_start_lesson_ready_listener_returns_cancellable_task(mocker):
    # Patch get_settings + Redis so the spawned task does not touch real config/redis.
    ...
    from app.core.pubsub import start_lesson_ready_listener
    task = await start_lesson_ready_listener(MagicMock())
    assert task.get_name() == "lesson_ready_subscriber"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
```

Note: `start_lesson_ready_listener` only does `asyncio.create_task(_run_lesson_subscriber(manager))`;
the task starts running, so patch `app.config.get_settings` and `app.core.pubsub.Redis` to keep it inert
before cancelling.

### Conventions

- `@pytest.mark.unit`; `asyncio_mode = "auto"` (no decorator).
- Keep the file's existing style (inline mocks, source-module patch targets).

---

## Review findings (surfaced, NOT fixed here)

Two findings from the adversarial review fall outside this test-fix story and are flagged for a
follow-up decision rather than changed unilaterally:

1. **[Decision — frozen contract] `lesson_ready` payload deviates from `ws.ts`.**
   `content_pipeline.py` publishes `payload: {session_id, lesson_id, lesson}`, but
   `packages/shared/types/ws.ts` `LessonReadyMessage` freezes the payload as `{lesson_id, lesson}`
   (no `session_id`). `ws.ts` is a frozen interface contract (§16 — 4-dev PR required to change).
   Either remove `session_id` from the published payload (routing already uses the channel name
   `lesson_ready:{session_id}`), or amend `ws.ts` via a 4-dev PR. **Not changed here.**

2. **[Follow-up coverage] back-off/reconnect path untested.** `_run_lesson_subscriber`'s
   `except Exception` branch (aclose + exponential back-off + reconnect, `pubsub.py:89-100`) has no
   test. A unit test would need to mock `asyncio.sleep` to avoid real delay; deferred to avoid adding a
   flaky global-sleep patch in this task. Recommended as a small dedicated follow-up.
