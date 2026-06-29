# Deferred Work

## Deferred from: code review of 1-11-player-loading-errors (2026-06-29)

- **"Report a Bug" URL hardcoded placeholder** [`PlayerLoader.tsx` `LessonParseErrorState`] — `https://github.com/HIE-corp/hie/issues` is a placeholder. Wire `NEXT_PUBLIC_BUG_REPORT_URL` env var in Sprint 2 so the URL is configurable without a code change.
- **`window.location.reload()` in `LessonParseErrorState` technically contradicts AC3 "none requires a full browser refresh" wording** — intentional per spec dev notes (parse error recovery is the explicit exception). Tighten AC3 wording in next spec pass to make the exception explicit.

## Deferred from: code review of S0-9 (2026-06-26)

- **`OpenAILLMProvider` captures singleton by reference at construction** [`providers/llm/openai.py:44`] — stale reference in tests if singleton is reset mid-test; not a production bug since singleton is never reset in prod. Revisit if test suite grows to construct providers across singleton resets.
- **`generation.end()` not called on exception path in `openai.py`** [`providers/llm/openai.py:63, 107`] — pre-existing before S0-9; open-ended Langfuse spans on every LLM error obscure error rates. Fix in Sprint 1 when nodes are wired end-to-end.
- **No `atexit` hook for crash-safe flush** [`core/langfuse.py`] — traces lost on SIGKILL or unhandled exception before lifespan shutdown runs. Consider `atexit.register(get_langfuse().flush)` as a safety net in Sprint 2 hardening.
- **Lifespan integration test missing for `flush()` call path** [`tests/unit/test_langfuse_core.py`] — unit tests cover the singleton contract but not the full `main.py` lifespan shutdown sequence. Add in Sprint 1 when test infrastructure for lifespan is established.
- **No concurrency test for singleton race** [`core/langfuse.py`] — race condition (P1) should be fixed first with a `threading.Lock`; add a concurrent-access test after the fix.
