# Deferred Work

## Deferred from: code review of 1-07-websocket-client (2026-07-02)

- **`handleClose` gives up silently after 5 reconnect attempts with no way to distinguish "permanently failed" from a transient `closed` state** [`apps/web/src/lib/ws/lessonSocket.ts:handleClose`] — not required by any AC today since nothing consumes `status` yet. Revisit once Sprint 3 wires the lesson player UI to `LessonSocketStatus`.
- **`apps/web/src/lib/assessment.ts` has no tests and doesn't handle a rejected `api.post` call** [`apps/web/src/lib/assessment.ts`] — pre-existing file with unchanged behavior; only newly git-tracked as a side effect of this story's `.gitignore` fix. Out of scope for a WebSocket-client story; needs its own follow-up task.
- **`sendControl()`'s 9 flow events (`segment_complete`, `quiz_trigger`, etc.) have no caller anywhere yet** [`apps/web/src/lib/ws/lessonSocket.ts`] — the receive side (server → store) is wired and tested, but nothing on the player side sends these to drive the backend tutor FSM. Wiring segment-end/quiz-trigger detection to `sendControl()` is separate Sprint 2/3 UI work.

## Deferred from: code review of S0-9 (2026-06-26)

- **`OpenAILLMProvider` captures singleton by reference at construction** [`providers/llm/openai.py:44`] — stale reference in tests if singleton is reset mid-test; not a production bug since singleton is never reset in prod. Revisit if test suite grows to construct providers across singleton resets.
- **`generation.end()` not called on exception path in `openai.py`** [`providers/llm/openai.py:63, 107`] — pre-existing before S0-9; open-ended Langfuse spans on every LLM error obscure error rates. Fix in Sprint 1 when nodes are wired end-to-end.
- **No `atexit` hook for crash-safe flush** [`core/langfuse.py`] — traces lost on SIGKILL or unhandled exception before lifespan shutdown runs. Consider `atexit.register(get_langfuse().flush)` as a safety net in Sprint 2 hardening.
- **Lifespan integration test missing for `flush()` call path** [`tests/unit/test_langfuse_core.py`] — unit tests cover the singleton contract but not the full `main.py` lifespan shutdown sequence. Add in Sprint 1 when test infrastructure for lifespan is established.
- **No concurrency test for singleton race** [`core/langfuse.py`] — race condition (P1) should be fixed first with a `threading.Lock`; add a concurrent-access test after the fix.
