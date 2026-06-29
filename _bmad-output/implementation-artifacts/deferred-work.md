# Deferred Work

## Deferred from: code review of 1-12-player-sync-test-harness (2026-06-29)

- **Unsorted `timestamps` precondition unguarded** [`AudioTimeline.tsx`] — `binarySearchTimestamps` assumes sorted input; no validation at ingestion or runtime. Validate sort order when building `lesson_package.json`, or add a guard + test when integration tests are added in Sprint 2.
- **Fractional `currentMs` contract undocumented** [`slideSync.test.ts`] — `currentTime * 1000` produces floats; `<=` comparison handles them correctly but no test explicitly documents this. Add a float-input case in a future harness expansion pass.
- **`ts` at describe scope — mutation risk** [`slideSync.test.ts`] — `make30Timestamps()` called once per describe block, not inside `beforeEach`. Safe because `binarySearchTimestamps` is read-only, but worth moving inside `beforeEach` if the function signature ever changes.
- **Magic numbers in `processTimeUpdate` tests** [`slideSync.test.ts`] — `16000`, `30000`, `3000` etc. are derived from `mockLessonPackage` internals with no assertion on fixture shape. If the mock changes these tests break silently. Add a shape-assertion helper or inline fixture constants if mock is ever updated.
- **`currentSegmentIndex` OOB guard path untested** [`slideSync.test.ts`] — `processTimeUpdate` returns early if `segment` is undefined, but no test sets `currentSegmentIndex` beyond `lesson.segments.length`. Add in Sprint 2 player integration tests.
- **Overshoot seek (`ms` well past `segmentEnd`) unasserted** [`slideSync.test.ts`] — quiz fires correctly via `>=` but no test explicitly covers `ms = segmentEnd + N`. Low priority; add in a future edge-cases pass.
- **Double-tick idempotency at boundary untested** [`slideSync.test.ts`] — two consecutive `processTimeUpdate(segmentEnd)` calls with no intervening state change; store's `quizFiredForSegment` guard handles it, but no test verifies. Add in stress/edge-case harness.

## Deferred from: code review of S0-9 (2026-06-26)

- **`OpenAILLMProvider` captures singleton by reference at construction** [`providers/llm/openai.py:44`] — stale reference in tests if singleton is reset mid-test; not a production bug since singleton is never reset in prod. Revisit if test suite grows to construct providers across singleton resets.
- **`generation.end()` not called on exception path in `openai.py`** [`providers/llm/openai.py:63, 107`] — pre-existing before S0-9; open-ended Langfuse spans on every LLM error obscure error rates. Fix in Sprint 1 when nodes are wired end-to-end.
- **No `atexit` hook for crash-safe flush** [`core/langfuse.py`] — traces lost on SIGKILL or unhandled exception before lifespan shutdown runs. Consider `atexit.register(get_langfuse().flush)` as a safety net in Sprint 2 hardening.
- **Lifespan integration test missing for `flush()` call path** [`tests/unit/test_langfuse_core.py`] — unit tests cover the singleton contract but not the full `main.py` lifespan shutdown sequence. Add in Sprint 1 when test infrastructure for lifespan is established.
- **No concurrency test for singleton race** [`core/langfuse.py`] — race condition (P1) should be fixed first with a `threading.Lock`; add a concurrent-access test after the fix.
