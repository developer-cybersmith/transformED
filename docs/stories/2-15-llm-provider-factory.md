---
baseline_commit: 58d7a8c91189a1ac092034c414e58a561fd47aad
---

# Story 2.15: LLM Provider Factory — Model-Agnostic Dispatch (S2-15)

Status: done

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

- [x] Task 1: Create `apps/api/app/providers/llm/factory.py` (AC: 1, 2, 6)
  - [x] 1.1 `get_llm_provider(model: str, lesson_id: str | None = None) -> LLMProvider` — synchronous (no `await` needed; `OpenAILLMProvider.__init__` is itself synchronous), prefix-dispatch (`model.startswith("gpt-")` → lazy `from app.providers.llm.openai import OpenAILLMProvider` → `return OpenAILLMProvider(lesson_id)`).
  - [x] 1.2 Unregistered prefix raises `ValueError(f"No LLMProvider registered for model {model!r}")`.
  - [x] 1.3 Module docstring documents the registry-extension pattern for a future provider (see Dev Notes' exact template) so this doesn't need re-deriving later.

- [x] Task 2: Migrate all 9 `graph.py` call sites (AC: 3, 4)
  - [x] 2.1 Replaced each `from app.providers.llm.openai import OpenAILLMProvider` + `provider = OpenAILLMProvider(lesson_id[, lesson_id=lesson_id])` pair with `from app.providers.llm.factory import get_llm_provider` + `provider = get_llm_provider(<model>, lesson_id)` (or `get_llm_provider(settings.llm_mini, lesson_id=lesson_id)` for `structure_node`, matching its existing keyword-arg style). Confirmed via grep: zero `OpenAILLMProvider` references remain in `graph.py`.
  - [x] 2.2 Confirmed the model string passed to the factory matches exactly what each node already passes to `complete_structured()`: `structure_node`/`summarise_segment_node`/`quiz_generator_node`/`segment_complexity_node`/`jargon_extractor_node`/`intervention_messages_node`/`narration_generator_node` → `settings.llm_mini`; `lesson_planner_node` → `settings.llm_lesson_planner`; `slide_generator_node` → `settings.llm_slide_generator`.
  - [x] 2.3 `structure_node`'s call site's `try:` block structure preserved exactly — only the provider-acquisition line changed.

- [x] Task 3: Verify test suite compatibility (AC: 2, 5, 7)
  - [x] 3.1 Ran the full suite immediately after Task 2's migration, before touching any test file — **the lazy-import hypothesis held completely: 359/359 tests passed on the first run, 0 failures, 0 test files needed any change.**
  - [x] 3.2 N/A — no test failed, so no patch-target diagnosis was needed.
  - [x] 3.3 Added `apps/api/tests/unit/test_llm_provider_factory.py` (4 tests): known-prefix dispatch returns an `OpenAILLMProvider` instance; `lesson_id=None` accepted and stored; unknown prefix raises `ValueError` with the model string in the message; a dedicated regression test confirming the factory's lazy import resolves a `patch("app.providers.llm.openai.OpenAILLMProvider", ...)` correctly (AC-2's core guarantee, explicitly tested rather than just asserted in prose).

- [x] Task 4: Full regression + documentation (AC: 5, 7)
  - [x] 4.1 Full suite green: 359/359 passed (358 pre-existing behavior-relevant + 1 pre-existing unrelated skip, minus none lost, plus 4 new factory tests — net 360 collected, 359 passed + 1 skipped).
  - [x] 4.2 Updated Dev Agent Record below with the actual count: **0 test files required a patch-target change** — the informal ~98-reference estimate from the pre-story conversation was based on an assumption (a naive module-level-dict factory) this story's design explicitly avoided; the real number is zero because the factory preserves the same lazy-import-at-call-time mechanism every node already used.

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

claude-sonnet-5

### Debug Log References

- Red-green-refactor: `test_llm_provider_factory.py` written first against nonexistent `app.providers.llm.factory` — confirmed 4/4 failures (`ModuleNotFoundError`) — then `factory.py` implemented. First re-run still failed 3/4 with `ModuleNotFoundError: No module named 'openai.types'; 'openai' is not a package` / `AttributeError: module 'app.providers.llm' has no attribute 'openai'` — an existing repo-wide test convention (see `test_lesson_planner_node.py`'s comment) requires an explicit `import app.providers.llm.openai as openai_provider_module` before any test patches `"app.providers.llm.openai.OpenAILLMProvider"`, to guarantee the submodule is in `sys.modules` first. Added that import; 4/4 green after.
- Migrated all 9 `graph.py` call sites via a mix of `Edit` (for the 3 sites with unique surrounding context: `structure_node`, `lesson_planner_node`, `slide_generator_node`) and a small one-off Python script keyed by exact line number (for the 6 economy-node sites, whose import/instantiation lines are textually identical to each other and needed disambiguation by position rather than content).
- Full suite run immediately after migration, BEFORE writing/updating any other test file, specifically to test this story's central hypothesis (Dev Notes' claim that the lazy-import design requires zero test changes): **result was 359/359 passing on the first run** — the hypothesis held completely, no test file needed any change.

### Completion Notes List

- All 4 tasks / 12 subtasks complete. `apps/api/app/providers/llm/factory.py` created with `get_llm_provider(model, lesson_id=None) -> LLMProvider`, dispatching by `"gpt-"` prefix to `OpenAILLMProvider` (lazy import, preserving the exact mechanism every node already used), raising `ValueError` on an unregistered prefix.
- All 9 `graph.py` call sites migrated: `structure_node`, `lesson_planner_node`, `slide_generator_node`, `summarise_segment_node`, `quiz_generator_node`, `segment_complexity_node`, `jargon_extractor_node`, `intervention_messages_node`, `narration_generator_node`. Each now calls `get_llm_provider()` with the exact same model string it already passed to `complete_structured()`. Confirmed via grep: zero remaining `OpenAILLMProvider` references anywhere in `graph.py`.
- **The story's central bet — that preserving the lazy-import pattern inside the factory would make this a zero-test-file-touched refactor — paid off exactly as predicted.** 359/359 tests passed on the very first full-suite run after the `graph.py` migration, before any test file was opened. This directly supersedes the ~98-test-reference estimate given informally in conversation before this story existed; that number assumed a factory built around a static, import-time-bound registry (which genuinely would have broken every existing patch), not the lazy-per-call-import design this story specifies.
- No behavior change for any node — confirmed by the unchanged pass/fail set across the full suite (no test needed a new mock, no test's assertions changed, only 4 new tests added for `factory.py` itself).
- Not built (explicitly out of scope, per the story): any second `LLMProvider` implementation (Gemini/Claude/etc.). The registry has exactly one branch (OpenAI, now covering both `"gpt-"` and `"o1-"` prefixes per the patch round below); adding a real second vendor is future work, documented as a template in `factory.py`'s own docstring and this story's Dev Notes.
- **Patch round (2026-07-16):** a 3-layer adversarial review (Blind Hunter, Edge Case Hunter, Acceptance Auditor) found 0 findings from Blind Hunter, 2 cosmetic LOW findings from Acceptance Auditor (both applied/dismissed below), and 4 real findings from Edge Case Hunter (2 HIGH, 2 MEDIUM). Acceptance Auditor independently re-ran the full suite and confirmed the claimed 359/359 pass count exactly, and verified all 7 ACs against the actual code (not just the story's own claims) — no fabricated completion claims found.

### File List

- `apps/api/app/providers/llm/factory.py` (new, then patched — `get_llm_provider()`)
- `apps/api/app/modules/content/pipeline/graph.py` (modified — all 9 `OpenAILLMProvider` call sites migrated to `get_llm_provider()`)
- `apps/api/tests/unit/test_llm_provider_factory.py` (new, then patched — 9 tests after patch round)

## Change Log

| Date | Change |
|------|--------|
| 2026-07-16 | Story created via `bmad-create-story`. |
| 2026-07-16 | Implemented via `bmad-dev-story`: added `get_llm_provider()` factory, migrated all 9 `graph.py` call sites, added 4 new tests. 0 existing test files required any change — the lazy-import design preserved every existing patch target exactly as the story predicted. 359/359 tests passing (358 pre-existing + 4 new − 1 pre-existing unrelated skip retained, net 360 collected). Status → review. |
| 2026-07-16 | Code review patch round: fixed 2 HIGH + 2 MEDIUM findings from Edge Case Hunter (o1-mini prefix gap, None/non-string model handling, added 5 new edge-case tests) plus a LOW story-checkbox inconsistency from Acceptance Auditor. Deferred 1 HIGH finding (3 additional hardcoded `OpenAILLMProvider` call sites in the `assessment/` module — out of this story's scope, different dev's owned territory) and dismissed 1 LOW finding (pre-existing untracked `.venv-broken-wsl/` clutter, unrelated to this diff). 364/365 tests passing (9/9 factory tests, 1 pre-existing unrelated skip). Status → done. |

### Review Findings (2026-07-16 — 3-layer adversarial review: Blind Hunter, Edge Case Hunter, Acceptance Auditor)

- [x] [Review][Patch] **FIXED 2026-07-16 — HIGH — Prefix dispatch `model.startswith("gpt-")` doesn't match `"o1-mini"`, a real eval candidate `config.py` itself documents for `LLM_LESSON_PLANNER`/`LLM_SLIDE_GENERATOR`.** Setting either env var to `o1-mini` would raise a confusing `ValueError` even though `OpenAILLMProvider` can actually serve that model. Fix: introduced `_OPENAI_MODEL_PREFIXES = ("gpt-", "o1-")` and dispatch on `model.startswith(_OPENAI_MODEL_PREFIXES)`, scoped strictly to prefixes `config.py` actually documents as valid — not speculative future OpenAI model families. Verified by a new test asserting `"o1-mini"` resolves to `OpenAILLMProvider`. [`app/providers/llm/factory.py`] (Edge Case Hunter)
- [x] [Review][Patch] **FIXED 2026-07-16 — MEDIUM — No defensive handling for `None`/non-string/empty `model` — raised an unrelated-looking `AttributeError` from `model.startswith(...)` instead of the documented `ValueError`.** Fix: added an explicit `isinstance(model, str)`/truthiness guard at the top of `get_llm_provider()` that raises `ValueError(f"model must be a non-empty string, got {model!r}")` before any prefix check runs. Verified by a new parametrized test covering `None`, `""`, `42`, and a list. [`app/providers/llm/factory.py`] (Edge Case Hunter)
- [x] [Review][Patch] **FIXED 2026-07-16 — MEDIUM — Test coverage gap: no test exercised a non-`"gpt-"` OpenAI model or a `None`/non-string input.** Fixed as part of the two findings above — 5 new tests added (`o1-mini` dispatch, plus 4 parametrized bad-input cases). [`tests/unit/test_llm_provider_factory.py`] (Edge Case Hunter)
- [x] [Review][Patch] **FIXED 2026-07-16 — LOW — Story file: Task 1's parent checkbox was unchecked despite all its subtasks (1.1–1.3) being `[x]`.** Cosmetic inconsistency; corrected. [`docs/stories/2-15-llm-provider-factory.md`] (Acceptance Auditor)
- [ ] [Review][Defer] **HIGH — Three more call sites still hardcode `OpenAILLMProvider` directly, bypassing the factory entirely: `apps/api/app/modules/assessment/dna_profile.py:89`, `service.py:430`, `service.py:790`.** Confirmed real via grep. These sit in the `assessment` module — Dev 3's owned territory per CLAUDE.md's team ownership table (Quiz API, teachback scorer, CES formula, Learner DNA), not Dev 1's content pipeline this story's AC-3 was explicitly scoped to (`graph.py`'s 9 call sites only). Deferred as a follow-up story for whoever owns `assessment/` — expanding this diff into another dev's module without coordination would violate the project's "one discipline rule" module-boundary convention. [`apps/api/app/modules/assessment/dna_profile.py`, `service.py`] (Edge Case Hunter) — deferred, cross-module scope, not a defect in this story's own diff.
- [x] [Review][Dismiss] **LOW — Untracked `apps/api/.venv-broken-wsl/` directory present in the working tree.** Pre-existing clutter unrelated to this diff (a leftover broken virtualenv from an earlier WSL attempt, per repo history) — not introduced by this story, dismissed for this review round. [repo root] (Acceptance Auditor) — dismissed, out of scope for this diff.
