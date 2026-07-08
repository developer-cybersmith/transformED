# Deferred Work

## Deferred from: code review of dev4/s1 branch (2026-07-08)

- **Race condition: duplicate `distraction_detected` dispatch** [`apps/api/app/modules/tutor/service.py`] — `redis.exists(cooldown_key)` check and `dispatch_event` are not atomic; two concurrent attention signals can both pass the cooldown guard before either sets the key. Fix requires Redis `SET NX EX` atomic guard or a Lua script. Defer to Sprint 3/4 hardening.
- **`compute_ces` stub (0.5) vs `ces_threshold` default (50.0) scale mismatch** [`apps/api/app/modules/tutor/service.py:367`] — stub always triggers interventions in production (0.5 < 50.0 always true). Tests set `threshold=0.5` to work around this. Will auto-fix when Dev 3 replaces stub with real formula in Sprint 3.
- **`attention_ack` WebSocket response leaks raw CES float to client** [`apps/api/app/core/websocket.py`] — PRD §18 prohibits clinical scores to students. Currently safe only because stub returns 0.5. Remove `ces` from `attention_ack` payload before Sprint 3 when real formula lands.
- **No per-session rate limiting on `attention_signal` messages** [`apps/api/app/core/websocket.py`] — PRD implies 5-second windows but the receive loop applies no throttle. A client sending 1000 signals/sec causes unbounded Redis writes. Add server-side rate limiting in Sprint 4 load hardening.
- **`_is_in_teachback()` is dead code in the new entry-router topology** [`apps/api/app/modules/tutor/state_machine/graph.py:128`] — TEACH_BACK guard is now enforced via `route_from_teach_back` in the entry router. Tests D1/D2 cover the function but it is never called from routing. Remove or document as utility in Sprint 2.
- **`fatigue_detected` → `intervening_node`: `intervention_type=None` defaults to distraction** [`apps/api/app/modules/tutor/state_machine/graph.py:159`] — fatigue fires increment distraction counter; flag owned by Sprint 2 `full_state_machine` task.
- **`session_id` from Redis pub/sub channel name not validated before use** [`apps/api/app/core/pubsub.py:72`] — `channel.removeprefix("lesson_ready:")` result is used directly in `manager.send()` with no length or format check. Low risk on private Redis; add validation before any multi-tenant deployment.
- **`process_attention_signal` dispatches `distraction_detected` regardless of current FSM state** [`apps/api/app/modules/tutor/service.py`] — CES triggers should be blocked in QUIZZING, TEACH_BACK, SESSION_END. Guard using Redis current state in Sprint 2 `full_state_machine`.
- **`_init_session_state` wipes mid-session state on reconnect** [`apps/api/app/core/websocket.py:64`] — second `connect()` on same `session_id` resets state to IDLE, erasing live session. Scoped to Sprint 2 `session_restore` task — fix `_init_session_state` to skip-if-active, or accept that reconnects reset to IDLE (decision required).
- **`test_lesson_ready_integration.py` green status unverifiable from diff** [`apps/api/tests/test_lesson_ready_integration.py`] — run `pytest tests/test_lesson_ready_integration.py` locally before declaring Story 4-3 done.
- **`_parse_signal` treats `{"payload": {}}` (empty nested dict) as falsy fallback** [`apps/api/app/modules/tutor/service.py:54`] — low practical impact (still raises ValueError), but confusing error message. Fix or document.
- **Pubsub backoff: `attempt` counter not reset correctly when connection succeeds then fails at `psubscribe`** [`apps/api/app/core/pubsub.py:48–50,96`] — minor error-recovery edge case in crash loop.



## Deferred from: code review of S0-9 (2026-06-26)

- **`OpenAILLMProvider` captures singleton by reference at construction** [`providers/llm/openai.py:44`] — stale reference in tests if singleton is reset mid-test; not a production bug since singleton is never reset in prod. Revisit if test suite grows to construct providers across singleton resets.
- **`generation.end()` not called on exception path in `openai.py`** [`providers/llm/openai.py:63, 107`] — pre-existing before S0-9; open-ended Langfuse spans on every LLM error obscure error rates. Fix in Sprint 1 when nodes are wired end-to-end.
- **No `atexit` hook for crash-safe flush** [`core/langfuse.py`] — traces lost on SIGKILL or unhandled exception before lifespan shutdown runs. Consider `atexit.register(get_langfuse().flush)` as a safety net in Sprint 2 hardening.
- **Lifespan integration test missing for `flush()` call path** [`tests/unit/test_langfuse_core.py`] — unit tests cover the singleton contract but not the full `main.py` lifespan shutdown sequence. Add in Sprint 1 when test infrastructure for lifespan is established.
- **No concurrency test for singleton race** [`core/langfuse.py`] — race condition (P1) should be fixed first with a `threading.Lock`; add a concurrent-access test after the fix.
