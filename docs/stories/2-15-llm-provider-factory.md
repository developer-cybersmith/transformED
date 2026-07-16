---
baseline_commit: 58d7a8c91189a1ac092034c414e58a561fd47aad
---

# Story 2.15: LLM Provider Factory — Model-Agnostic Dispatch (S2-15)

Status: ready-for-dev

## Story

As a **developer who wants to experiment with a different LLM vendor (Gemini, Claude, etc.) for any pipeline node without touching node code**,
I want a single factory function that decides which concrete `LLMProvider` to instantiate based on the configured model string,
so that adding or switching a vendor is a one-file, one-registry-entry change — never a hunt through every node that calls an LLM.

This is a **mandatory refactor**, not a new feature — it does not change any node's behavior or output. It closes a gap between what CLAUDE.md claims ("swapping models is an env var change only") and what the code actually does today: `settings.llm_mini`/`settings.llm_lesson_planner`/`settings.llm_slide_generator`/`settings.llm_tutor` are genuinely env-var-driven for the **model string**, but every node hardcodes `from app.providers.llm.openai import OpenAILLMProvider` directly — the **provider class** is not selectable at all. Pointing an env var at a non-OpenAI model today does not gracefully degrade; it fails at the API-call boundary because `OpenAILLMProvider` talks to OpenAI's SDK specifically.

**Explicitly out of scope:** writing a second provider (no `GeminiLLMProvider`/`AnthropicLLMProvider` in this story). This story builds only the dispatch mechanism, structured so that a future provider is a pure addition (one new file + one registry entry), never a node-code change.

## Acceptance Criteria

1. **New `get_llm_provider(model: str, lesson_id: str | None = None) -> LLMProvider` factory function** in `apps/api/app/providers/llm/factory.py`. Dispatches by model-name prefix (e.g. `"gpt-"` → `OpenAILLMProvider`). Unknown/unregistered prefix raises `ValueError` with the offending model string in the message — never a silent fallback to a default provider.
2. **The factory's per-branch provider import stays lazy (inside the dispatch function, at call time), mirroring every node's existing `from app.providers.llm.openai import OpenAILLMProvider` pattern** — this is a hard requirement, not a style preference: it is what keeps every existing test's `patch("app.providers.llm.openai.OpenAILLMProvider", ...)` working unmodified once nodes call the factory instead of importing the class directly (see Dev Notes — verify this before assuming any test file needs edits).
3. **All 9 existing call sites in `graph.py` migrated off the direct `OpenAILLMProvider` import** to call `get_llm_provider(model, lesson_id)` instead. The 9 sites (by node function): `structure_node`, `lesson_planner_node`, `slide_generator_node`, `summarise_segment_node`, `quiz_generator_node`, `segment_complexity_node`, `jargon_extractor_node`, `intervention_messages_node`, `narration_generator_node`.
4. **Zero behavior change for any existing node** — same model strings resolved, same `OpenAILLMProvider` instantiated with the same `lesson_id`, same circuit-breaker/retry/cost-tracking/Langfuse behavior (all of that lives inside `OpenAILLMProvider` itself and is untouched by this story).
5. **Full regression suite stays green** with no test-logic changes — only test **patch targets** may change, and only where AC-2's lazy-import preservation turns out not to fully cover a given test's mocking approach (verify empirically per test file rather than assuming a blanket rewrite is needed).
6. **Registry is extensible without a node-code change** — the Dev Notes below spell out the exact shape a future `"gemini-"` entry would take, so the next developer adding a real second provider only touches `factory.py` (plus writing the new provider file itself).
7. All existing tests continue to pass.

## Tasks / Subtasks

- [ ] Task 1: Create `apps/api/app/providers/llm/factory.py` (AC: 1, 2, 6)
  - [ ] 1.1 `get_llm_provider(model: str, lesson_id: str | None = None) -> LLMProvider` — synchronous (no `await` needed; `OpenAILLMProvider.__init__` is itself synchronous), prefix-dispatch (`model.startswith("gpt-")` → lazy `from app.providers.llm.openai import OpenAILLMProvider` → `return OpenAILLMProvider(lesson_id)`).
  - [ ] 1.2 Unregistered prefix raises `ValueError(f"No LLMProvider registered for model {model!r}")`.
  - [ ] 1.3 Module docstring documents the registry-extension pattern for a future provider (see Dev Notes' exact template) so this doesn't need re-deriving later.

- [ ] Task 2: Migrate all 9 `graph.py` call sites (AC: 3, 4)
  - [ ] 2.1 Replace each `from app.providers.llm.openai import OpenAILLMProvider` + `provider = OpenAILLMProvider(lesson_id[, lesson_id=lesson_id])` pair with `from app.providers.llm.factory import get_llm_provider` + `provider = get_llm_provider(model=<the model this node already passes to complete_structured>, lesson_id=lesson_id)`.
  - [ ] 2.2 Confirm the model string passed to the factory is byte-for-byte the same one already passed to `complete_structured()`/`complete()` in that node (no node currently needs a different model for provider-selection vs. the actual call — verify this holds for `structure_node`, which uses `settings.llm_mini` for both).
  - [ ] 2.3 `structure_node`'s call site is inside a `try:` block (it's optional/best-effort) — preserve that structure exactly, only swap the provider-acquisition line.

- [ ] Task 3: Verify test suite compatibility (AC: 2, 5, 7)
  - [ ] 3.1 Run the full suite immediately after Task 2's migration, BEFORE touching any test file — per AC-2's lazy-import design, most/all tests patching `"app.providers.llm.openai.OpenAILLMProvider"` should keep passing unmodified, since the factory's lazy import resolves the (patched) attribute at call time exactly like the node's old direct import did.
  - [ ] 3.2 For any test that fails, diagnose whether it's patching at the wrong layer (e.g. patching `graph.OpenAILLMProvider` — a name that no longer exists in `graph.py`'s namespace once Task 2 lands) and fix only the patch target, not the test's assertions/logic.
  - [ ] 3.3 Add new unit tests for `factory.py` itself: known-prefix dispatch returns an `OpenAILLMProvider` instance; unknown prefix raises `ValueError` with the model string in the message; `lesson_id=None` is accepted and passed through.

- [ ] Task 4: Full regression + documentation (AC: 5, 7)
  - [ ] 4.1 Full suite green, 0 net new failures.
  - [ ] 4.2 Update `apps/api/app/providers/llm/factory.py`'s docstring and this story's Dev Agent Record with the actual count of test files that needed a patch-target change (expected: few or zero, per AC-2 — record the real number, don't guess).

## Dev Notes

### Why this is safe to do as a pure refactor — read `openai.py` before touching `graph.py`

`apps/api/app/providers/llm/openai.py` (already exists, unchanged by this story) is the ONLY concrete `LLMProvider` today. All circuit-breaker (`is_circuit_open`/`record_success`/`record_failure`, key `"openai"`), retry (`@with_retry(max_attempts=3)`), Langfuse tracing, and cost accumulation (`_maybe_accumulate_cost`) logic lives inside this class, keyed off the model string passed to `complete()`/`complete_structured()` — none of it depends on how the node obtained the provider instance. Moving provider *acquisition* behind a factory therefore cannot change any of that behavior; it only changes one line per node (how `provider` gets bound).

### The 9 call sites — exact locations as of baseline commit `58d7a8c`

All in `apps/api/app/modules/content/pipeline/graph.py`. Each currently has the pattern `from app.providers.llm.openai import OpenAILLMProvider` (a lazy, function-local import) immediately followed later in the same function by `provider = OpenAILLMProvider(lesson_id)` (or `OpenAILLMProvider(lesson_id=lesson_id)` for `structure_node` specifically — same effect, keyword vs positional):

| Node function | Model passed to the LLM call |
|---|---|
| `structure_node` | `settings.llm_mini` |
| `lesson_planner_node` | `settings.llm_lesson_planner` |
| `slide_generator_node` | `settings.llm_slide_generator` |
| `summarise_segment_node` | `settings.llm_mini` |
| `quiz_generator_node` | `settings.llm_mini` |
| `segment_complexity_node` | `settings.llm_mini` |
| `jargon_extractor_node` | `settings.llm_mini` |
| `intervention_messages_node` | `settings.llm_mini` |
| `narration_generator_node` | `settings.llm_mini` |

`settings.llm_tutor` (Phase 2 tutor Q&A) is NOT called from any pipeline node yet — no 10th call site exists today; when Phase 2 tutor code is built, it should call the factory from the start rather than repeating the direct-import pattern.

### The lazy-import trick — why it matters and how to verify it, don't assume

The existing tests patch the SOURCE module, not the consumer:
```python
patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider)
```
This works today because each node's `from app.providers.llm.openai import OpenAILLMProvider` executes INSIDE the function body, at call time — after the test's `patch()` context is already active. Python resolves that `from...import` by reading the CURRENT attribute off the `app.providers.llm.openai` module object, which the patch has already replaced with a `MagicMock`. (`test_lesson_planner_node.py` and `test_phase1_economy_nodes.py` both have comments calling this out explicitly — read them before writing `factory.py`.)

If `factory.py`'s `get_llm_provider()` ALSO does its `from app.providers.llm.openai import OpenAILLMProvider` lazily, inside the function, at call time — the exact same mechanism applies: the patched attribute is what gets resolved, regardless of whether the immediate caller is `graph.py` or `factory.py`. **This means existing tests should require ZERO patch-target changes**, not the ~98-file sweep that was informally estimated in conversation before this story existed. That earlier estimate assumed a naive factory built around a module-level dict populated at import time (which WOULD break existing patches, since the dict would capture the real class object before any test patch runs) — this story explicitly rejects that design. Verify this assumption empirically (Task 3.1) rather than trusting this note blindly; if some tests DO fail, the likely cause is a test patching `graph.OpenAILLMProvider` (i.e., patching the name as it appeared inside `graph.py`'s own namespace) rather than the source module — grep for `patch("app.modules.content.pipeline.graph.OpenAILLMProvider"` specifically if that happens.

### Future-provider registry shape (for the NEXT developer, not this story to build)

```python
# apps/api/app/providers/llm/factory.py — illustrative future addition, NOT part of this story
def get_llm_provider(model: str, lesson_id: str | None = None) -> LLMProvider:
    if model.startswith("gpt-"):
        from app.providers.llm.openai import OpenAILLMProvider
        return OpenAILLMProvider(lesson_id)
    if model.startswith("gemini-"):
        from app.providers.llm.gemini import GeminiLLMProvider  # future story
        return GeminiLLMProvider(lesson_id)
    raise ValueError(f"No LLMProvider registered for model {model!r}")
```
Adding the `"gemini-"` branch (once a real `GeminiLLMProvider` is written implementing the `LLMProvider` ABC in `app/providers/base.py`) is the ENTIRE integration point — no node in `graph.py` changes, because every node already only knows about `settings.llm_*` model strings and the factory, never a concrete provider class.

### `LLMProvider` ABC (already exists, unchanged by this story)

`apps/api/app/providers/base.py` — `complete()` and `complete_structured()`, both taking `model: str` as an explicit parameter. The factory's job stops at "which class to instantiate" — it does not wrap or change how `complete`/`complete_structured` are called at the node level.

### Branch

Single shared branch for all of Sprint 2: `sprint2/phase-b-generation-nodes` — do not create a new branch (Sprint 2 single-branch override, per project convention). Story-first gate still applies: commit this story file alone, push, THEN begin implementation.

### Testing standards

pytest, matching the established convention: new `factory.py`-specific tests get their own file (`tests/unit/test_llm_provider_factory.py`). Do not touch any node test's assertions/logic — only patch-target strings, and only if Task 3.1 proves a given test actually needs it.

### Project Structure Notes

One new file (`apps/api/app/providers/llm/factory.py`), one new test file (`apps/api/tests/unit/test_llm_provider_factory.py`), `graph.py` modified at exactly 9 call sites (import + instantiation lines only — no other logic in any of the 9 functions changes), zero or few existing test files touched (patch-target only, per Dev Notes).

### References

- [Source: docs/dev1-tracker.md — Sprint 2 section, S2-15]
- [Source: apps/api/app/providers/llm/openai.py — the only existing concrete `LLMProvider`, untouched by this story]
- [Source: apps/api/app/providers/base.py — `LLMProvider` ABC]
- [Source: apps/api/app/config.py — `llm_mini`/`llm_lesson_planner`/`llm_slide_generator`/`llm_tutor` env-var-driven model strings]
- [Source: apps/api/app/modules/content/pipeline/graph.py — the 9 call sites]
- [Source: apps/api/tests/unit/test_lesson_planner_node.py, test_phase1_economy_nodes.py — existing comments explaining the lazy-import/patch-target mechanism this story relies on]

## Dev Agent Record

### Agent Model Used

_To be filled by bmad-dev-story._

### Debug Log References

_To be filled by bmad-dev-story._

### Completion Notes List

_To be filled by bmad-dev-story._

### File List

_To be filled by bmad-dev-story._

## Change Log

| Date | Change |
|------|--------|
| 2026-07-16 | Story created via `bmad-create-story`. |
