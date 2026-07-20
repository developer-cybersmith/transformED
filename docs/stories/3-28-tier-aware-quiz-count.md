---
story_id: "3-28"
epic: "3"
title: "Tier-Aware Quiz Question Count in quiz_generator_node"
status: "ready-for-dev"
branch: "learner-mode-sprint-dev3-task1"
baseline_commit: ""
---

# Story 3-28 — Tier-Aware Quiz Question Count in quiz_generator_node

## User Story

**As a** student using TransformED in a specific Learner Mode tier,  
**I want** the number of quiz questions per lesson segment to match my learning depth,  
**so that** T1 (full-depth) learners get more comprehensive quiz coverage, T2 (standard) learners get balanced reinforcement, and T3 (refresher) learners are not overwhelmed.

---

## Background and Context

`quiz_generator_node` (Phase 1 economy node, `graph.py`) currently generates exactly **1 MCQ per segment** via a single LLM call. This was the correct MVP default (Story 2-1) but is now being extended by the Learner Mode sprint.

The codebase already has a tier-aware constant pattern for slide budgets (`_TIER_TOTAL_SLIDE_BAND`) and `lesson_planner` depth framing (`_TIER_PROMPT_FRAMING`). This story follows the same pattern for quiz question counts.

**Critical scope note (line 958–963 of graph.py):** The comment "S2-LM5 does NOT extend to Phase 1 economy nodes' quiz/narration depth" was written to constrain Story S2-LM5's scope only — it does NOT prohibit Story 3-28. This story is the explicit Learner Mode sprint extension that adds tier-aware depth to `quiz_generator_node`.

**Package schema contract (FROZEN — do not modify):**
- `packages/shared/types/lesson.ts`: `Segment.quiz: QuizQuestion[]` — already an array, no change needed
- `packages/shared/lesson_package.schema.json`: `Segment.quiz` has no `minItems` constraint — 1-5 questions all pass validation without schema change
- No modification to `packages/shared/` is permitted (read-only for Dev 3)

---

## Acceptance Criteria

### AC 1 — T1 tier: 3-5 questions per segment (default)
Given a lesson with `tier = "T1"`, `quiz_generator_node` returns between 3 and 5 validated quiz questions for each segment.

### AC 2 — T2 tier: 2-3 questions per segment (default)
Given a lesson with `tier = "T2"`, `quiz_generator_node` returns between 2 and 3 validated quiz questions for each segment.

### AC 3 — T3 tier: 1-2 questions per segment (default)
Given a lesson with `tier = "T3"`, `quiz_generator_node` returns between 1 and 2 validated quiz questions for each segment.

### AC 4 — Bands defined as module-level constant (no env vars)
A constant `_TIER_QUIZ_COUNT_BAND: dict[str, tuple[int, int]]` is added to `graph.py`, parallel to `_TIER_TOTAL_SLIDE_BAND`. Values are `{"T1": (3, 5), "T2": (2, 3), "T3": (1, 2)}`. No new fields added to `config.py` — quiz count bands are architectural constants (same pattern as slide bands, which are not env-var driven either).

### AC 5 — Per-question `question_id` uses 0-indexed suffix
Each question in the batch has `question_id = f"quiz_{section_id}_{i}"` where `i` is the 0-based position in the returned list. (Previously: `quiz_{section_id}` for the single question; the suffix unambiguously distinguishes multiple questions for the same segment.)

### AC 6 — All existing per-question validation guards apply to each question in the batch
Every guard that exists in the current single-question path must be applied to **each individual question** in the batch:
- 5+ options → truncate to exactly 4
- < 4 options → reject that question (skip it, log warning)
- `correct_index` out of range → reject that question
- blank `question` or `explanation` text → reject that question
- any blank option string → reject that question
- duplicate options (normalized to `.strip().lower()`) → reject that question
- difficulty not in `("easy", "medium", "hard")` → clamp to `"medium"` (existing pattern)

### AC 7 — Zero valid questions degrades gracefully
If ALL questions in the LLM batch fail their individual validation guards, the node returns `{"quiz_questions": []}` without raising an exception (same "degrade, never crash" pattern as the current `_reject()` helper).

### AC 8 — Partial batch accepted (below N_min is warned, not rejected)
If the LLM returns a batch where some questions pass and some fail validation, the node keeps every passing question and logs a warning if the final count is below N_min. It does NOT discard the passing questions. A lesson with 1 valid question for a T1 segment is better than a lesson with 0 valid questions.

### AC 9 — Checkpoint shape changes; old single-question checkpoints are cache-misses
The checkpoint written for `quiz_generator:{section_id}` changes to:
```json
{
  "segment_id": "<section_id>",
  "questions": [
    {"segment_id": "<section_id>", "data": {<QuizQuestion fields>}},
    ...
  ]
}
```
The `_read_phase1_checkpoint` call is updated to `required_keys=("segment_id", "questions")`. Old checkpoints with `{"segment_id": ..., "data": {...}}` (single-question shape) fail the `required_keys` check and are treated as cache-misses, triggering a re-run. **No stale data forwarded downstream.**

### AC 10 — Existing `TestAC3QuizGenerator` tests remain GREEN
All 7 existing quiz_generator tests in `TestAC3QuizGenerator` (`test_phase1_economy_nodes.py`) must continue to pass. Mock objects must be updated from single-`_QuizQuestionLLM` shape to `_QuizBatchLLM`-shaped mocks (i.e., provide `response.questions = [...]` instead of `response.question/options/...` directly). The tested behaviours do not change — only the mock shape.

### AC 11 — `package_builder_node` is NOT modified
The existing `_group_by_segment_id` helper in `package_builder_node` already supports multiple entries per `segment_id` (it builds `dict[str, list]`). Returning N entries in `quiz_questions` (each `{"segment_id": ..., "data": {...}}`) naturally produces N questions for the segment in the final `Segment.quiz` array. Zero code change required in `package_builder_node`.

### AC 12 — Shared types NOT modified
`packages/shared/types/lesson.ts` and `packages/shared/lesson_package.schema.json` are read-only for Dev 3. No change is permitted.

### AC 13 — Model alias from `settings.llm_mini`, never hardcoded
`quiz_generator_node` already uses `settings.llm_mini` for the LLM call. This must remain unchanged — the second argument to `provider.complete_structured(messages, settings.llm_mini, ...)` must stay `settings.llm_mini`.

### AC 14 — Unknown/invalid tier falls back to T2 band with a warning
If `state["tier"]` is not in `_TIER_QUIZ_COUNT_BAND` (e.g., empty string or unexpected value), the node falls back to the T2 band `(2, 3)` and logs a warning. This mirrors how `_tier_slide_budget_per_segment` defaults to T2 on unknown tier.

### AC 15 — Single LLM call per segment (not N separate calls)
The node makes exactly ONE `provider.complete_structured` call per segment regardless of tier, using `_QuizBatchLLM` as the structured-output schema. This preserves the existing "one call per Send()-dispatch" contract (AC from Story 2-1).

---

## Tasks and Subtasks

- [ ] **Task 1: Add `_TIER_QUIZ_COUNT_BAND` constant in `graph.py`**
  - [ ] 1.1 Add `_TIER_QUIZ_COUNT_BAND: dict[str, tuple[int, int]] = {"T1": (3, 5), "T2": (2, 3), "T3": (1, 2)}` near `_TIER_TOTAL_SLIDE_BAND` (around line 903)

- [ ] **Task 2: Add `_QuizBatchLLM` Pydantic model in `graph.py`**
  - [ ] 2.1 Add `class _QuizBatchLLM(BaseModel): questions: list[_QuizQuestionLLM]` below the existing `_QuizQuestionLLM` class (around line 1751)
  - [ ] 2.2 Keep `_QuizQuestionLLM` unchanged — it is still used as the element type within the batch

- [ ] **Task 3: Add `_quiz_batch_is_valid_shape()` validator in `graph.py`**
  - [ ] 3.1 Add `_quiz_batch_is_valid_shape(cached: dict[str, Any]) -> bool` immediately after `_quiz_data_is_valid_shape`
  - [ ] 3.2 Checks: `cached.get("questions")` is a non-empty list; each element passes `_quiz_data_is_valid_shape`
  - [ ] 3.3 Keep `_quiz_data_is_valid_shape` unchanged — it is reused by `_quiz_batch_is_valid_shape` to validate each question in the batch

- [ ] **Task 4: Modify `quiz_generator_node` to generate N questions**
  - [ ] 4.1 Read `tier = state.get("tier", DEFAULT_TIER)` at the top of the node
  - [ ] 4.2 Look up `n_min, n_max = _TIER_QUIZ_COUNT_BAND.get(tier, _TIER_QUIZ_COUNT_BAND["T2"])` — log warning if `tier` not in band
  - [ ] 4.3 Update `_read_phase1_checkpoint` call: `required_keys=("segment_id", "questions")`, `extra_validate=_quiz_batch_is_valid_shape`
  - [ ] 4.4 On cache hit, return `{"quiz_questions": cached["questions"]}` (list of per-question dicts)
  - [ ] 4.5 Update system prompt: `"Write {n_min} to {n_max} multiple-choice questions testing understanding of this section. For each question, provide exactly 4 distinct answer options, the 0-based index of the correct option, a brief explanation, and a difficulty (easy/medium/hard)."`
  - [ ] 4.6 Call `provider.complete_structured(messages, settings.llm_mini, _QuizBatchLLM)` (note: `_QuizBatchLLM` not `_QuizQuestionLLM`)
  - [ ] 4.7 If `response is None` or `response.questions` is empty, return `{"quiz_questions": []}` (degrade, don't crash)
  - [ ] 4.8 Loop over `response.questions`, apply all existing guards per question, assign `question_id = f"quiz_{section_id}_{i}"` (0-based), collect valid results
  - [ ] 4.9 Truncate valid results to `n_max` if somehow > n_max (defensive guard)
  - [ ] 4.10 If count < n_min (but > 0), log a warning — do NOT discard valid questions
  - [ ] 4.11 If count == 0, log warning and return `{"quiz_questions": []}`
  - [ ] 4.12 Write batch checkpoint: `{"segment_id": section_id, "questions": results}` where `results` is the list of `{"segment_id": ..., "data": {...}}`
  - [ ] 4.13 Return `{"quiz_questions": results}`

- [ ] **Task 5: Update existing `TestAC3QuizGenerator` tests in `test_phase1_economy_nodes.py`**
  - [ ] 5.1 Update every mock in `TestAC3QuizGenerator` from single-question shape to batch shape: mock object must have `.questions` attribute containing a list of individual question objects
  - [ ] 5.2 Update count assertions that currently check `len(result["quiz_questions"]) == 1` — T2 default now returns up to 3, but each test can use a T2 state with a mock that returns exactly 1 question in the batch to preserve 1-question assertions
  - [ ] 5.3 Verify all 7 existing `TestAC3QuizGenerator` tests pass with the updated mocks

- [ ] **Task 6: Write new tests in `apps/api/tests/unit/test_quiz_generator_tier.py`**
  - [ ] 6.1 `test_t1_tier_produces_3_to_5_questions` — mock returns 4 valid questions, assert `len(result["quiz_questions"]) == 4`
  - [ ] 6.2 `test_t2_tier_produces_2_to_3_questions` — mock returns 2 valid questions, assert count == 2
  - [ ] 6.3 `test_t3_tier_produces_1_to_2_questions` — mock returns 1 valid question, assert count == 1
  - [ ] 6.4 `test_question_ids_are_0_indexed_suffixed` — mock returns 3 questions (T1 state), assert `question_id` values are `quiz_{section_id}_0`, `quiz_{section_id}_1`, `quiz_{section_id}_2`
  - [ ] 6.5 `test_batch_checkpoint_cache_hit_returns_all_questions` — patch `_read_phase1_checkpoint` to return a batch-shaped checkpoint, assert LLM NOT called and all questions returned
  - [ ] 6.6 `test_old_single_question_checkpoint_is_treated_as_cache_miss` — confirm that `required_keys=("segment_id", "questions")` causes old `{"segment_id": ..., "data": {...}}` checkpoint to miss (validate via `_read_phase1_checkpoint` logic — see `_quiz_batch_is_valid_shape` validator)
  - [ ] 6.7 `test_mixed_valid_invalid_batch_keeps_only_valid` — batch has 3 questions; question[1] has duplicate options; assert only 2 questions returned (question[0] and question[2])
  - [ ] 6.8 `test_all_invalid_batch_returns_empty_list` — batch has 2 questions, both with blank explanation; assert returns `{"quiz_questions": []}`
  - [ ] 6.9 `test_unknown_tier_falls_back_to_t2_band` — state with `tier="T99"`, mock returns 2 questions, assert 2 returned (T2 band accepts 2-3)
  - [ ] 6.10 `test_single_llm_call_per_segment_regardless_of_tier` — T1 state, assert `mock_provider.complete_structured.call_count == 1`
  - [ ] 6.11 `test_tier_band_constant_has_correct_values` — import `_TIER_QUIZ_COUNT_BAND` and assert all 3 tier values
  - [ ] 6.12 `test_quiz_batch_is_valid_shape_rejects_missing_questions_key` — unit-test the validator directly
  - [ ] 6.13 `test_quiz_batch_is_valid_shape_rejects_empty_questions_list` — validator rejects `{"segment_id": ..., "questions": []}`
  - [ ] 6.14 `test_quiz_batch_is_valid_shape_rejects_old_single_question_shape` — validator rejects `{"segment_id": ..., "data": {...}}` (old format)

- [ ] **Task 7: Run full test suite to verify no regressions**
  - [ ] 7.1 `pytest apps/api/tests/unit/test_quiz_generator_tier.py -v` — all 14 new tests green
  - [ ] 7.2 `pytest apps/api/tests/unit/test_phase1_economy_nodes.py -v` — all existing tests green (including updated `TestAC3QuizGenerator`)
  - [ ] 7.3 `pytest apps/api/tests/unit/ -v` — full unit suite green (0 regressions)

---

## Dev Notes

### File to modify
**Primary:** `apps/api/app/modules/content/pipeline/graph.py`
**Test (update):** `apps/api/tests/unit/test_phase1_economy_nodes.py` — only `TestAC3QuizGenerator` class
**Test (new):** `apps/api/tests/unit/test_quiz_generator_tier.py`

### No config.py changes
The `_TIER_QUIZ_COUNT_BAND` constant goes in `graph.py`, not `config.py`. Rationale: `_TIER_TOTAL_SLIDE_BAND` (line 903) and `_tier_slide_budget_per_segment()` (line 927) both live in `graph.py` as module-level constants and functions — quiz counts follow the same pattern. CES weights are in `config.py` because they must sum to 1.0 and require post-calibration tuning; quiz counts have no such constraint.

### Exact insertion points in graph.py
- `_TIER_QUIZ_COUNT_BAND`: insert near line 903 (after `_TIER_TOTAL_SLIDE_BAND`)
- `_QuizBatchLLM`: insert after `_QuizQuestionLLM` (around line 1751)
- `_quiz_batch_is_valid_shape`: insert after `_quiz_data_is_valid_shape` (around line 1786)
- `quiz_generator_node` body changes: lines 1789–1914 (the entire function)

### `DEFAULT_TIER` import already exists
`from app.schemas.lesson import DEFAULT_TIER, VALID_TIERS` is already imported at line 55–58. `DEFAULT_TIER = "T2"` is the fallback for unknown tiers.

### Tier in PipelineState
`state["tier"]` (type `str`) is already declared at line 88: `tier: str  # Learner Mode tier: "T1" | "T2" | "T3"`. No state schema change required.

### `_group_by_segment_id` already supports multiple questions
`package_builder_node` uses `_group_by_segment_id` (line 3050–3064) which already accumulates multiple `{"segment_id": ..., "data": {...}}` entries per segment into a `dict[str, list]`. Returning N entries in `quiz_questions` (all with the same `segment_id`) will naturally produce N questions in the final `Segment.quiz` list. **Verify this in tests before implementation.**

### Why one LLM call (not N calls)
One call is cheaper (fewer API round-trips) and aligns with the existing `_tier_slide_budget_per_segment` pattern (which computes N at plan-time from a single call). Multiple sequential calls would create N checkpoints per segment (naming collision), bloat `lesson_jobs.node_outputs`, and violate the node's AC from Story 2-1 (one call per dispatch).

### Existing `_reject` pattern
The current `_reject()` inner async function will still be useful for individual question validation failures inside the batch loop. However, the node no longer returns immediately on a single question failure — it collects failures and continues to the next question. The "reject" pattern becomes per-question rejection within the loop, with node-level rejection only if ALL questions fail.

### `_quiz_data_is_valid_shape` is NOT deprecated
This function is still needed — `_quiz_batch_is_valid_shape` calls it to validate each question in the batch. Keep it unchanged.

### Mock shape for existing tests (Task 5)
Current mock (BEFORE):
```python
mock_output = type("Quiz", (), {
    "question": "...", "options": [...], "correct_index": 1, "explanation": "...", "difficulty": "medium",
})()
```
Updated mock (AFTER):
```python
single_q = type("Q", (), {
    "question": "...", "options": [...], "correct_index": 1, "explanation": "...", "difficulty": "medium",
})()
mock_output = type("Batch", (), {"questions": [single_q]})()
```
The state for existing tests does NOT need a `tier` key — the node falls back to `DEFAULT_TIER = "T2"` when `state.get("tier", DEFAULT_TIER)` is called (because `_base_state()` currently doesn't set tier). Verify `_base_state()` definition in conftest/test file and confirm the fallback path.

### Checkpoint cache hit return path
On cache hit, the cached value is:
```python
{
    "segment_id": section_id,
    "questions": [
        {"segment_id": section_id, "data": {question_dict_1}},
        {"segment_id": section_id, "data": {question_dict_2}},
        ...
    ]
}
```
Return path: `return {"quiz_questions": cached["questions"]}` — this correctly feeds the existing `_group_by_segment_id` downstream.

### Concurrency note
`quiz_generator_node` is `Send()`-dispatched once per section in parallel. Multiple sections may write checkpoints concurrently. The `_write_phase1_checkpoint` function uses an atomic RPC merge (existing story 2-1b implementation) — no race condition introduced by this change.

### Test for "old checkpoint treated as cache-miss" (AC 9 / Task 6.6)
Rather than calling the full node (which requires DB mocking), test the `_quiz_batch_is_valid_shape` function directly against the old shape:
```python
old_shape = {"segment_id": "seg_1", "data": {"question_id": "quiz_seg_1", ...}}
assert not _quiz_batch_is_valid_shape(old_shape)
```
This proves the validator correctly rejects the old format, meaning `_read_phase1_checkpoint` would return `None` (cache miss) when it encounters an old checkpoint.

---

## Dependencies

| Dependency | Status |
|-----------|--------|
| `_TIER_TOTAL_SLIDE_BAND` constant pattern (graph.py line 903) | Already merged to main |
| `tier: str` in `PipelineState` (graph.py line 88) | Already merged to main |
| `DEFAULT_TIER`, `VALID_TIERS` imports in graph.py (line 55–58) | Already merged to main |
| `_group_by_segment_id` multi-value support in package_builder | Already merged to main |
| `Segment.quiz: QuizQuestion[]` frozen schema | Already frozen — no change needed |

---

## Dev Agent Record

### Implementation Plan
(to be filled by dev agent during implementation)

### Debug Log
(to be filled by dev agent during implementation)

### Completion Notes
(to be filled by dev agent on completion)

### File List
(to be filled by dev agent on completion)

### Change Log
- 2026-07-20: Story 3-28 created — Learner Mode Sprint Task 1, tier-aware quiz question count

---

## Senior Developer Review (AI)
(to be filled after `/bmad-code-review` — 5 required agent layers)
