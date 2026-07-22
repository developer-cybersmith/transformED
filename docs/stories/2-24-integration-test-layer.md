---
baseline_commit: 7da95e48ddde7b9ba0f8a03cbeec8f42f9c928d0
---

# Story 2.24: Real-graph integration test on a step-numbered how-to (the missing layer)

Status: ready-for-dev

> **TEST-INFRA / remediation, from the 2026-07-22 audit.** The audit's #1 systemic gap: *no test ever executes the real graph* — every test mocks node boundaries with clean fixtures, and the boundaries are exactly where the bug class lives (over-segmentation, count-mismatch, newline-in-id, space-in-id, empty-timestamps, whole-segment-drop). This story adds a real `run_pipeline()` end-to-end test on a **step-numbered how-to** input (the failure class), mocking ONLY external providers, that would have caught all of the above.

## Acceptance Criteria

1. **AC-1 — the REAL graph runs end-to-end.** A test invokes `run_pipeline(lesson_id, chapter_content=<step-numbered how-to text>)` through the actual compiled LangGraph — every node's real logic (structure detection + coalesce, `_derive_section_id`, Phase-1 fan-out, planner + slide guards, tts/image/package assembly) executes. Only external providers are mocked: `get_llm_provider`/`OpenAILLMProvider` (a dispatching mock keyed on `response_format`), TTS/image fallbacks, cost tracker, and a **stateful** Supabase fake (accumulates `lesson_jobs.node_outputs`; `chapters.insert` returns an id; `chunks` return `[]` so `embed` no-ops — chunks feed only RAG, not generation; `lessons`/`books`/storage no-op).
2. **AC-2 — a valid LessonPackage is produced and JSON-schema-validated.** The returned package validates against the FROZEN `packages/shared/lesson_package.schema.json` (via `jsonschema`, not just Pydantic) — a genuine Dev1→Dev2 contract test on real output.
3. **AC-3 — the bug class is regression-guarded end-to-end** on the how-to input:
   - sections are bounded (`≤ structure_max_sections`) despite the how-to's many numbered "steps" (RC-1 / Story 2-16);
   - every `segment_id` is a safe single token matching `_SAFE_SEGMENT_ID_RE` (Stories 2-18/2-20);
   - every segment's `narration.timestamps` is non-empty and contiguous (Story 2-19);
   - every prompt sent to the planner/slide LLM has exactly one line per segment (Story 2-20);
   - the package completes (no wholesale-reject / whole-segment-drop) (Stories 2-21/2-22).
4. **AC-4 — the harness is reusable.** The stateful Supabase fake + dispatching LLM mock live in `tests/integration/` (a conftest or helper module) so future pipeline integration tests reuse them.
5. **AC-5 — runs in CI (no cost, no network).** No real provider/network calls; deterministic; marked so it runs in the default suite.

## Tasks / Subtasks
- [ ] Task 1: `tests/integration/` harness — `StatefulSupabaseFake`, `dispatching_llm_provider` (per-`response_format` valid instances; planner/slide echo the prompt's segment_ids), TTS/image/cost mocks.
- [ ] Task 2: `tests/integration/test_howto_pipeline_e2e.py` — run_pipeline on step-numbered how-to text; assert AC-2/AC-3.
- [ ] Task 3: JSON-schema contract assertion against `lesson_package.schema.json`.
- [ ] Task 4: green in the default unit+integration suite; ruff + mypy clean.

## Dev Notes
- `run_pipeline(lesson_id, chapter_content=...)` (graph.py:4005) runs the graph from `extract`; with `chapter_content` set and no PDF, extraction uses the raw text.
- Structure LLM path is dead for real docs (RC-2), so a `DocumentStructure(sections=[])` mock forces the REAL rule-based `detect_headings` + `coalesce_sections` — the exact over-segmentation path.
- `response_format` models to dispatch: `DocumentStructure`, `_SegmentSummaryLLM`, `_QuizQuestionLLM`, `_SegmentComplexityLLM`, `_JargonListLLM`, `_SegmentInterventionsLLM`, `_NarrationScriptLLM`, `_LessonPlanLLM`, `_SlideDeckLLM`. Planner/slide must echo the prompt's `- segment_id={id}:` list 1:1.
- Patch both `app.providers.llm.factory.get_llm_provider` and `app.providers.llm.openai.OpenAILLMProvider` (nodes use both). Patch `_synthesize_with_fallback` / `_generate_image_with_fallback` at the graph module. `check_ceiling`→False, `accumulate_cost`→no-op.

## Change Log
| Date | Change | Author |
|------|--------|--------|
| 2026-07-22 | Test-infra story from the audit (the missing real-graph integration layer). | Dev 1 |

## Dev Agent Record
_(to be completed during dev-story)_
