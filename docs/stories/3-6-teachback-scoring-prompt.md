---
baseline_commit: 617faa5a6a7b60db1a6e87b1f0d7dbee9a764fd8
---

# Story 3.6: Teach-back Scoring Prompt v1

Status: done

---

## Story

As Dev 3 (tannmayygupta),
I want a GPT-4o-mini rubric prompt and score_teachback() async function in prompts.py,
so that Sprint 1's POST /api/assessment/teachback endpoint has a tested, isolated scorer to call.

---

## Acceptance Criteria

1. File apps/api/app/modules/assessment/prompts.py exists and is importable
2. TeachbackScoreResult Pydantic model has exactly 5 fields: score: int (Field(ge=0, le=100)), praise: str, correction: str, concepts_hit: list[str], concepts_missed: list[str]
3. TEACHBACK_SYSTEM_PROMPT constant exists and contains rubric weights: 40%, 35%, 25%
4. System prompt instructs model to use correction="" (empty string, NOT null) when score >= 90
5. build_teachback_user_prompt(*, topic, key_concepts, response_text) function returns string containing all three inputs
6. score_teachback() async function signature: (*, topic: str, key_concepts: list[str], response_text: str, provider: Any) -> TeachbackScoreResult — ARCHITECTURAL NOTE: lesson_id is NOT in this function's signature. It is passed to OpenAILLMProvider at constructor time; the provider holds it for cost tracking. Callers must construct the provider with lesson_id before calling score_teachback(). (Deliberate design — documented in Dev Notes and tested without lesson_id param.)
7. score_teachback() calls provider.complete_structured() with model=settings.llm_mini and response_format=TeachbackScoreResult
8. score_teachback() uses get_settings() from app.config — NEVER hardcodes "gpt-4o-mini"
9. prompts.py does NOT import openai.AsyncOpenAI anywhere (not even in TYPE_CHECKING block)
10. No IQ/EQ/SQ language or clinical/diagnostic terms in any prompt text, field names, or docstrings
11. System prompt contains "Accuracy" (40%), "Completeness" (35%), "Clarity" (25%) labels
12. apps/api/tests/test_teachback_scoring_prompt.py exists with at minimum 8 @pytest.mark.unit tests
13. pytest -m unit tests/test_teachback_scoring_prompt.py exits 0 (all pass)
14. pytest -m unit tests/ exits 0 (no regressions in existing suite)

---

## Tasks / Subtasks

- [x] Task 1: Create story file docs/stories/3-6-teachback-scoring-prompt.md (this file) — AC: all — ✓ 2026-06-26
  - [x] 1.1 Write story with all 14 ACs and BMAD structure
  - [x] 1.2 Set baseline_commit in YAML frontmatter

- [x] Task 2: Implement apps/api/app/modules/assessment/prompts.py — AC: #1-#11 — ✓ 2026-06-26
  - [x] 2.1 Define TeachbackScoreResult Pydantic model (score ge=0 le=100, 4 str/list fields)
  - [x] 2.2 Write TEACHBACK_SYSTEM_PROMPT (rubric weights, correction="" rule, guidelines)
  - [x] 2.3 Write build_teachback_user_prompt() helper function
  - [x] 2.4 Write score_teachback() async function (uses provider.complete_structured, settings.llm_mini)

- [x] Task 3: Write unit tests apps/api/tests/test_teachback_scoring_prompt.py — AC: #12-#13 — ✓ 2026-06-26
  - [x] 3.1 test_model_has_five_fields
  - [x] 3.2 test_score_range_rejects_101_and_minus1 (split into _above_100 and _below_0)
  - [x] 3.3 test_user_prompt_contains_topic_concepts_response
  - [x] 3.4 test_system_prompt_has_three_rubric_weights
  - [x] 3.5 test_system_prompt_no_iq_eq_sq_language
  - [x] 3.6 test_score_teachback_calls_complete_structured_not_complete (AsyncMock)
  - [x] 3.7 test_score_teachback_uses_llm_mini_not_hardcoded_string (patch get_settings)
  - [x] 3.8 test_score_teachback_passes_response_format_as_teachback_score_result
  - [x] 3.9 test_no_asyncopenai_import_in_prompts_module (AST check)

- [x] Task 4: Run tests and verify ACs — AC: #13-#14 — ✓ 2026-06-26
  - [x] 4.1 pytest -m unit tests/test_teachback_scoring_prompt.py → 18 passed
  - [x] 4.2 pytest -m unit tests/ → 19 passed, 1 skipped (integration), exits 0, no regressions

---

## Dev Notes

### NON-NEGOTIABLE RULES (PR rejection if violated)
- NEVER call openai.AsyncOpenAI() directly — all LLM calls go through OpenAILLMProvider
- NEVER hardcode "gpt-4o-mini" — always use settings.llm_mini from get_settings()
- ALWAYS pass lesson_id to OpenAILLMProvider constructor for cost tracking
- NO IQ/EQ/SQ language — no "intelligence quotient", "emotional quotient" etc.
- NO duration_seconds, no transcript field — typed input only (response_text)
- score_teachback() is SPRINT 0 ONLY for isolation testing — Sprint 1 wires it into service.py

### OpenAILLMProvider Usage Pattern
- Constructor: OpenAILLMProvider(lesson_id="lesson-123") 
- complete_structured signature: (messages, model, response_format, **kwargs) -> Any
- lesson_id is passed to constructor, NOT to complete_structured()
- Cost tracking happens automatically via _maybe_accumulate_cost in the provider

### correction="" Rule (AC #4)
- When score >= 90: correction MUST be empty string ""
- Do NOT return null, "None", "No correction needed" or any other value
- Frontend checks: if (correction) { showCorrectionCard() } — empty string is falsy

### From __future__ import annotations Pattern
Use this at top of prompts.py so TYPE_CHECKING annotations are strings at runtime:
  from __future__ import annotations
  from typing import TYPE_CHECKING, Any
  if TYPE_CHECKING:
      from app.providers.llm.openai import OpenAILLMProvider
But annotate score_teachback provider parameter as Any to avoid runtime import.

### get_settings() Import Pattern
Import at module level (NOT inside the function):
  from app.config import get_settings
Then call inside score_teachback():
  settings = get_settings()
  model=settings.llm_mini
This allows mocking: patch("app.modules.assessment.prompts.get_settings", return_value=mock)

### Test Mocking Pattern for score_teachback()
from unittest.mock import AsyncMock, MagicMock, patch
from app.config import Settings

mock_provider = MagicMock()
mock_provider.complete_structured = AsyncMock(return_value=TeachbackScoreResult(...))
mock_settings = MagicMock()
mock_settings.llm_mini = Settings.model_fields["llm_mini"].default  # "gpt-4o-mini" without hardcoding

with patch("app.modules.assessment.prompts.get_settings", return_value=mock_settings):
    result = await score_teachback(..., provider=mock_provider)

---

## Dev Agent Record

### Agent Model Used
claude-sonnet-4-6

### Debug Log References
- test_system_prompt_no_iq_eq_sq_language false-positive: banned bare "iq" matched "technique" (contains "niq"). Fixed by replacing bare "iq" with "iq score" in the banned list and adding a separate word-boundary regex check (`\biq\b`) which correctly skips "technique".
- test_no_asyncopenai_direct_import_in_prompts_module path error: test used relative path `apps/api/app/modules/assessment/prompts.py` which resolves from cwd (apps/api/), producing `apps\api\apps\api\...`. Fixed to use `pathlib.Path(__file__).parent.parent / "app" / "modules" / "assessment" / "prompts.py"`.
- worktree pyproject.toml had UTF-8 BOM from git commit 617faa5. Replaced with fixed version from main (commit 4d9f58c post-review fix) to allow pytest to parse the TOML config file.

### Completion Notes List
- TeachbackScoreResult Pydantic model: 5 fields (score int ge=0 le=100, praise str, correction str, concepts_hit list[str], concepts_missed list[str]).
- TEACHBACK_SYSTEM_PROMPT: rubric with Accuracy (40%), Completeness (35%), Clarity (25%). correction="" rule explicitly stated. No clinical/diagnostic language.
- build_teachback_user_prompt(): keyword-only args, handles empty key_concepts list gracefully.
- score_teachback(): async, keyword-only params, calls provider.complete_structured() with settings.llm_mini. No hardcoded model string. No openai import.
- 18 unit tests written, all pass. 19 total unit tests (including suite health sentinel) pass. No regressions.
- Tests fixed two spec issues: (1) IQ check false-positive on "technique", (2) relative path for AST check.

### File List
- docs/stories/3-6-teachback-scoring-prompt.md — CREATED
- apps/api/app/modules/assessment/prompts.py — CREATED
- apps/api/tests/test_teachback_scoring_prompt.py — CREATED
- apps/api/pyproject.toml — replaced with BOM-free version from main (no content changes, encoding fix only)

### Change Log
- 2026-06-26: Created prompts.py with TeachbackScoreResult, TEACHBACK_SYSTEM_PROMPT, build_teachback_user_prompt(), score_teachback()
- 2026-06-26: Created test_teachback_scoring_prompt.py with 18 @pytest.mark.unit tests
- 2026-06-26: Fixed IQ false-positive in test_system_prompt_no_iq_eq_sq_language
- 2026-06-26: Fixed relative path in test_no_asyncopenai_direct_import_in_prompts_module
- 2026-06-26: Replaced pyproject.toml with BOM-free version (encoding fix, no content change)

---

## Senior Developer Review (AI)

**Reviewed 2026-06-26 by claude-sonnet-4-6**

**PASS — all 14 ACs satisfied.**

Key observations:
1. Provider abstraction: score_teachback() accepts provider as Any — no direct openai import anywhere. AST test verifies this at the module level.
2. Model name: settings.llm_mini sourced via get_settings() at call time, never hardcoded. Tests verify via Settings.model_fields default, not a string literal.
3. correction="" rule: clearly documented in system prompt as EMPTY STRING (not null, not "None"). Frontend-safe.
4. No banned language: no IQ/EQ/SQ, no clinical/diagnostic terms. Test uses word-boundary regex to avoid false positives on "technique".
5. Signature: keyword-only args on all public functions — prevents positional argument mistakes.
6. Sprint boundary: score_teachback() is intentionally not wired into service.py yet — Sprint 1 task per story notes.
