# Deferred Work

## Deferred from: code review of 1-15-brand-recolor (2026-07-02)

- **`/onboarding/page.tsx` is unbranded and has dead/no-op button classes** [`apps/web/src/app/onboarding/page.tsx`] — pre-existing, not touched by the S1-15 diff: it's the only route in the app using `dark:` Tailwind variants (will flip to a dark theme under OS dark mode while every other page stays light); uses `bg-primary-600`/`text-primary-700`-style numbered-scale classes that don't resolve to anything (no `tailwind.config`, no `--color-primary-600` token defined), so several buttons/selected-states on this live, auth-gated route likely render without their intended background; also still shows leftover copy "TransformED AI" instead of "HIE". Needs its own follow-up story.
- **Bare untokenized hex `#E8D08D` (lighter gold tint)** [`apps/web/src/components/ui/AuroraBackground.tsx`, `apps/web/src/components/sections/JourneyToSelfReliance.tsx`] — introduced as a literal rather than a named CSS variable; low priority, but a future gold retune would miss this shade on a `--accent-secondary` grep.
- **AC9 visual verification incomplete** [`_bmad-output/implementation-artifacts/1-15-brand-recolor.md`] — dashboard sidebar/nav active states, `QuizOverlay`, `TeachBackModal`, and `PlayerControls` were named in AC9's required manual-check list but never actually screenshotted; only landing and signup pages were. Recommend a follow-up manual pass with real auth credentials.
- **Residual cool-toned `slate-*` grays** [`apps/web/src/components/sections/CognitiveVisualization.tsx`, `apps/web/src/components/sections/Hero.tsx`, `apps/web/src/components/sections/HowItWorks.tsx`] — several `slate-*` Tailwind classes and matching hex literals remain from the old blue-family palette; not literally "blue" so out of this story's grep-defined scope, but read slightly mismatched against the new warm Navy/Gold/Grey system. Design-consistency nit, not a functional bug.

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
