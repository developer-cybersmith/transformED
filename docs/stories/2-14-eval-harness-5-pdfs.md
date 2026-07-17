---
baseline_commit: 358d3c0f3a9986b05f51a2a5c16bb9bc804dfabd
---

# Story 2.14: Eval Harness — 5 PDFs (S2-14)

Status: ready-for-dev

## Story

As a **platform operator**,
I want an automated eval harness that runs 5 representative PDFs through the full content pipeline and scores the resulting `LessonPackage` output,
so that pipeline quality regressions are caught before Sprint 3's expanded 20-PDF gate (S3-1), matching `docs/dev1-tracker.md`'s S2-14 AC: "All 5 PDFs produce a valid `LessonPackage`; no pipeline crash; per-lesson scores visible in Langfuse."

**Follows the pre-existing `/run-evals` command spec exactly** (`.claude/commands/run-evals.md`, present in the repo before this story — not invented here): PDFs load from `apps/api/tests/fixtures/eval_pdfs/`, the runner lives at `apps/api/tests/evals/runner.py`, golden comparisons at `apps/api/tests/evals/golden/<pdf-name>/`, timestamped results at `apps/api/tests/evals/results/<timestamp>.json`, and `pytest tests/evals/ -v` is the manual entry point. This story builds the 5-PDF subset of that design (S3-1, Sprint 3, expands it to 20 PDFs with the "15/20 rated useful" human-review gate — that gate is explicitly OUT of scope here).

**Scope decision, made with the user before implementation:** no real representative textbook PDFs were available in this session. Five **synthetic** PDFs are generated programmatically (via `fpdf2`, a new dev-only dependency — MIT-licensed, added to `pyproject.toml`'s `[project.optional-dependencies].dev`) covering the tracker's 5 required categories: short (≤10 pages), long (≥100 pages), dense-text, table-heavy, image-heavy. The generator is a standalone script so real PDFs can replace the synthetic ones later (e.g. the Windows Internals book used in Sprint 1's live E2E testing) without changing the runner.

**Second scope decision, made with the user before implementation:** this story builds and unit-tests the harness (PDF generator + scorer + runner, all offline-testable against mocks) but does **not** execute the actual 5 live pipeline runs — each run hits live OpenAI/Sarvam/Azure/Supabase, costs real money, and can take up to ~15 minutes per the PRD's per-lesson SLA. The user triggers the real 5-PDF run separately (`pytest apps/api/tests/evals/runner.py::test_eval_all_pdfs -v -m live_eval` or `/run-evals --all`) when ready.

## Acceptance Criteria

1. **5 synthetic PDF fixtures generated and committed**, one per required category, under `apps/api/tests/fixtures/eval_pdfs/`: `short.pdf` (≤10 pages, generated via `apps/api/tests/fixtures/generate_eval_pdfs.py`), `long.pdf` (≥100 pages), `dense_text.pdf` (paragraph-heavy, no tables/images), `table_heavy.pdf` (multiple fpdf2 tables per page), `image_heavy.pdf` (multiple embedded raster images per page, generated via Pillow — already a project dependency, no new dep needed for this one).
2. **Generator is deterministic and re-runnable**, not a one-off script whose output is hand-edited afterward — running it twice produces byte-identical (or at least structurally identical) PDFs, and it's committed as a real script (not thrown away after generating the fixtures once).
3. **`apps/api/tests/evals/scoring.py`** provides two pure, offline-testable scoring functions operating on an already-produced `LessonPackage` dict: `score_slide_quality(lesson_package) -> EvalScore` and `score_quiz_relevance(lesson_package) -> EvalScore`, where `EvalScore` is a small dataclass/TypedDict with at least `{value: float in [0,1], issues: list[str]}`. **Both are explicitly rule-based/heuristic, not semantic/NLP-based** — documented honestly as such in their docstrings (matching this codebase's established convention of flagging provisional/heuristic implementations rather than overclaiming, e.g. `package_builder_node`'s `teachback_prompt` note). No new LLM calls are spent scoring — that would defeat the purpose of a cheap regression-catching harness.
4. **`apps/api/tests/evals/runner.py`** provides `async def run_eval(pdf_path, pdf_key, lesson_id, user_id) -> EvalResult` — runs one PDF through `run_pipeline()` (the existing `apps/api/app/modules/content/pipeline/graph.py` entry point, unmodified), asserts the result is a valid `LessonPackage` via `LessonPackage.model_validate()`, computes both scores from AC-3, and returns a result object capturing `{pdf_key, lesson_id, package_valid, slide_quality, quiz_relevance, elapsed_seconds, error}`. A pipeline exception is caught and recorded in `error`, not re-raised — one PDF's failure must not abort the other 4 (mirrors the pipeline's own "never hard-fail" nodes' philosophy, applied at the harness level).
5. **Scores recorded in Langfuse** per run: the runner opens its own Langfuse span for the eval (`get_langfuse().start_observation(name=f"eval:{pdf_key}", as_type="span")`), and calls `.score_trace(name="slide_quality", value=..., data_type="NUMERIC")` / `.score_trace(name="quiz_relevance", value=..., data_type="NUMERIC")` on it before `.end()`. Verified against the actual installed `langfuse` v4 SDK API (`Langfuse.start_observation`, `LangfuseSpan.score_trace`/`.end`) — not guessed.
6. **A results JSON is written** to `apps/api/tests/evals/results/<ISO-8601-timestamp>.json` containing all 5 `EvalResult`s plus a summary (`{pdfs_run, pdfs_valid, pdfs_crashed, mean_slide_quality, mean_quiz_relevance}`), matching the `/run-evals` command spec's documented output location.
7. **Offline unit tests exist and pass** for `scoring.py` (fixture `LessonPackage`-shaped dicts, both well-formed and deliberately malformed, asserting the score direction and issue reporting) and for `runner.py`'s error-isolation behavior (AC-4, `run_pipeline` mocked to raise — the result's `error` field is populated, `package_valid=False`, and the function returns normally rather than propagating). These run in the normal `pytest tests/unit` (or `tests/evals`, matching the command spec) suite with zero live service calls.
8. **The actual 5-PDF live run is explicitly NOT executed by this story** (per the scope decision above) — a `@pytest.mark.live_eval` marker gates the real end-to-end test (`test_eval_all_pdfs`) so it's skipped by default in CI/local runs and only fires when explicitly requested (`-m live_eval`), consistent with this being a cost-incurring, credential-requiring integration test, not a unit test.
9. All existing tests continue to pass unmodified.

## Tasks / Subtasks

- [ ] Task 1: Add `fpdf2` dev dependency (AC: 1)
  - [ ] 1.1 Already added to `pyproject.toml`'s `[project.optional-dependencies].dev` and installed via `uv sync --extra dev` (done ahead of story-first gate, during scoping — confirm `uv.lock` reflects it).

- [ ] Task 2: PDF fixture generator (AC: 1, 2)
  - [ ] 2.1 `apps/api/tests/fixtures/generate_eval_pdfs.py` — one function per category (`_build_short()`, `_build_long()`, `_build_dense_text()`, `_build_table_heavy()`, `_build_image_heavy()`), each returning bytes or writing directly to `apps/api/tests/fixtures/eval_pdfs/<name>.pdf`. A `main()` regenerates all 5; runnable via `python -m tests.fixtures.generate_eval_pdfs` from `apps/api/`.
  - [ ] 2.2 `image_heavy.pdf` generates its embedded images with Pillow (`PIL.Image`) at generation time (simple synthetic shapes/gradients, no external asset files) — no new dependency, Pillow is already in `pyproject.toml`.
  - [ ] 2.3 Run the generator once to produce and commit the 5 actual `.pdf` files under `apps/api/tests/fixtures/eval_pdfs/`.

- [ ] Task 3: Scoring functions (AC: 3)
  - [ ] 3.1 `apps/api/tests/evals/scoring.py` — `EvalScore` dataclass, `score_slide_quality()`, `score_quiz_relevance()`. Slide quality heuristics: non-blank title, 1-8 bullets present (mirrors `slide_generator_node`'s own AC-4 band), no blank bullets, no single bullet over a length threshold flagged as "wall of text". Quiz relevance heuristics: exactly 4 options present, valid `correct_index`, non-blank question/explanation, plus a simple keyword-overlap check between the quiz question text and its segment's `title`/`summary` (weak topical-relevance proxy, documented as such — not semantic similarity).
  - [ ] 3.2 Both functions accept a `LessonPackage`-shaped dict (not a Pydantic instance) since the runner works with `run_pipeline()`'s raw dict return value — mirrors `package_builder_node`'s own dict-first-validate-second pattern.

- [ ] Task 4: Eval runner (AC: 4, 5, 6, 8)
  - [ ] 4.1 `apps/api/tests/evals/runner.py` — `EvalResult` dataclass, `async def run_eval(...)`, `async def run_all_evals(...)` (loops the 5 fixtures, writes the results JSON per AC-6).
  - [ ] 4.2 Langfuse span wiring per AC-5 — verify the exact method names/signatures against the installed `langfuse` package before writing (do not guess; `python -c "from langfuse import Langfuse; help(Langfuse.start_observation)"` / inspect `LangfuseSpan`).
  - [ ] 4.3 `@pytest.mark.live_eval`-marked `test_eval_all_pdfs` in `runner.py` (or a sibling test file) that calls `run_all_evals()` against the 5 real fixtures — registered as a pytest marker in `pyproject.toml`'s `[tool.pytest.ini_options]` (`markers = [...]`) so it doesn't warn as unknown, and excluded from the default run via `-m "not live_eval"` guidance in a module docstring (not necessarily wired into CI `addopts`, since this repo's existing CI config is out of this story's scope to modify without confirming with the team).

- [ ] Task 5: Offline tests (AC: 7, 9)
  - [ ] 5.1 `apps/api/tests/unit/test_eval_scoring.py` — well-formed `LessonPackage` fixture scores high with zero issues; a fixture with an empty-bullets slide, a >8-bullet slide, a 3-option quiz question, and an out-of-range `correct_index` each independently score lower and report a matching issue string.
  - [ ] 5.2 `apps/api/tests/unit/test_eval_runner.py` — `run_eval()` with `run_pipeline` mocked to return a valid `LessonPackage` dict: asserts `package_valid=True`, both scores computed, Langfuse span opened/scored/ended (mock `get_langfuse()`). A second test mocks `run_pipeline` to raise: asserts `package_valid=False`, `error` populated, function returns (not raises) — AC-4's "one PDF's failure must not abort the other 4" contract, exercised in isolation.
  - [ ] 5.3 Full regression suite run before and after.

## Dev Notes

### Langfuse v4 API — verified against the installed package, not guessed

```
Langfuse.start_observation(*, name, as_type='span', input=None, output=None, metadata=None, ...) -> LangfuseSpan
LangfuseSpan.score_trace(*, name: str, value: float | str, data_type: ScoreDataType | None = None, comment=None, metadata=None) -> None
LangfuseSpan.end(*, end_time=None) -> LangfuseObservationWrapper
```
This mirrors the existing pattern in `apps/api/app/providers/llm/openai.py` (`self._langfuse.start_observation(..., as_type="generation")`, later `.end()`), except the eval harness uses `as_type="span"` (not `"generation"` — no LLM call is being wrapped, the pipeline's own nodes already create their own generation spans) and calls `.score_trace()` before `.end()`. Wrap every Langfuse call in the existing `_safe_trace()` helper pattern (see `openai.py`) so a Langfuse outage never crashes an eval run — matches this codebase's established observability-must-not-block-the-feature philosophy.

### Why rule-based scoring, not LLM-based

An eval harness whose own scoring step spends LLM budget defeats its purpose as a cheap, frequent regression check — and CLAUDE.md's cost-ceiling discipline applies here too, even though `check_ceiling()`/`accumulate_cost()` themselves don't (this is post-hoc scoring of an already-completed lesson, not a pipeline node). Rule-based heuristics are honestly weaker than semantic scoring (a keyword-overlap "relevance" proxy will miss a topically-relevant question that happens to paraphrase rather than reuse the segment's vocabulary) — document this limitation directly in `scoring.py`'s docstrings rather than presenting the scores as more rigorous than they are. If genuine semantic scoring is wanted later (e.g. an LLM-as-judge pass), that's a deliberate follow-up story, not something to silently upgrade to here.

### Why the live 5-PDF run is out of scope for this story

Per the scope decision made with the user before implementation: running `run_pipeline()` for real hits live OpenAI (lesson_planner/slide_generator/economy nodes), Sarvam/Azure (tts_node), GPT Image/Imagen (image_generator), and Supabase — real API cost, and up to ~15 minutes per lesson × 5 lessons. This story delivers a fully-built, fully-unit-tested harness (offline, mocked) that the user can trigger live whenever they choose, rather than autonomously spending real money and ~15-75 minutes of live runtime without an explicit go-ahead for that specific action.

### Testing standards

pytest, matching sibling stories' conventions. `scoring.py` tests need zero mocking (pure functions over plain dicts). `runner.py`'s offline tests mock `app.modules.content.pipeline.graph.run_pipeline` and `app.core.langfuse.get_langfuse` — locate the exact patch targets by checking how `runner.py` imports them (module-level or lazy, follow whichever convention keeps tests working per this codebase's established `patch("app.providers.llm.openai.OpenAILLMProvider", ...)`-at-the-source-module pattern for lazy imports).

### Branch

Single shared branch for all of Sprint 2: `sprint2/phase-b-generation-nodes` — do not create a new branch. Story-first gate still applies.

### Project Structure Notes

New files: `apps/api/tests/fixtures/generate_eval_pdfs.py`, `apps/api/tests/fixtures/eval_pdfs/{short,long,dense_text,table_heavy,image_heavy}.pdf`, `apps/api/tests/evals/scoring.py`, `apps/api/tests/evals/runner.py`, `apps/api/tests/unit/test_eval_scoring.py`, `apps/api/tests/unit/test_eval_runner.py`. Modified: `apps/api/pyproject.toml` (fpdf2 dev dep + `live_eval` pytest marker registration), `apps/api/uv.lock` (already synced).

### References

- [Source: docs/dev1-tracker.md — Sprint 2 section, S2-14]
- [Source: .claude/commands/run-evals.md — pre-existing design spec this story implements the 5-PDF subset of]
- [Source: apps/api/app/modules/content/pipeline/graph.py — `run_pipeline()`, the harness's entry point, unmodified]
- [Source: apps/api/app/core/langfuse.py — `get_langfuse()` singleton]
- [Source: apps/api/app/providers/llm/openai.py — `start_observation()`/`.end()`/`_safe_trace()` usage pattern this story mirrors]
- [Source: apps/api/app/schemas/lesson.py — `LessonPackage` for AC-4's validation]

## Dev Agent Record

### Agent Model Used

_To be filled by dev-story._

### Debug Log References

_To be filled by dev-story._

### Completion Notes List

_To be filled by dev-story._

### File List

_To be filled by dev-story._

## Change Log

| Date | Change |
|------|--------|
| 2026-07-17 | Story created via `bmad-create-story`. |
