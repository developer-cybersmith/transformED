---
baseline_commit: e1177e85db264a13062f3f300da1aed7e2e265ba
---

# Story 3.18: Onboarding Assessment Scoring — POST /api/assessment/onboarding/submit

Status: done

---

## Story

As Dev 3 (tannmayygupta),
I want to implement `POST /api/assessment/onboarding/submit` so that it validates, persists, and scores the 20-question diagnostic,
so that a new student's initial Learner DNA profile is computed and stored before their first lesson session begins.

---

## Acceptance Criteria

1. `POST /api/assessment/onboarding/submit` returns HTTP 409 if Redis key `user:{user_id}:onboarding_done` is already `"1"` (idempotency guard — prevents re-scoring).
2. `POST /api/assessment/onboarding/submit` returns HTTP 422 if `responses` contains fewer or more than 20 items (Pydantic `min_length=20, max_length=20`).
3. `POST /api/assessment/onboarding/submit` returns HTTP 422 if any `OnboardingAnswer.dimension` is not one of `"cognitive"`, `"emotional"`, `"self_direction"` (Pydantic `Literal` type).
4. `POST /api/assessment/onboarding/submit` returns HTTP 422 if any `OnboardingAnswer.selected_index` is outside `0–3` (Pydantic `Field(ge=0, le=3)`).
5. After a successful submission, all 20 rows exist in `onboarding_responses` with correct `user_id`, `question_id`, `response_value` (= `selected_index`), `dimension_tag` (= `dimension`), and optional `response_time_ms`.
6. After a successful submission, a `learner_dna` row exists for the user with all 9 dimension columns non-null and in the range 0.0–100.0 (DB CHECK constraint enforced; service also validates before upsert).
7. After a successful submission, `learner_dna.session_count` is `0` (initial write — Sprint 3 increments it per session).
8. After a successful submission, `learner_dna.profile_text` is non-empty and ends with the DPDP Act 2023 disclaimer: `"— Pursuant to DPDP Act 2023."`.
9. `profile_text` contains NO raw numeric scores — descriptive narrative only (CLAUDE.md Learner DNA display rules).
10. `badge_labels` uses plain-English labels (e.g., `"Pattern Thinker"`, `"Resilient Learner"`) — no `IQ`, `EQ`, or `SQ` language.
11. After a successful submission, Redis key `user:{user_id}:onboarding_done` is set to `"1"`.
12. The response body is `OnboardingResult` with `badge_labels: list[str]`, `profile_text: str`, `session_count: int` — no raw dimension scores exposed to the frontend.
13. `OnboardingAnswer` and `OnboardingDiagnosticSubmission` are defined in `schemas.py`, NOT in `router.py` (mirrors the Sprint 1 migration of quiz/teachback schemas).
14. All LLM calls use `settings.llm_mini` via `OpenAILLMProvider(lesson_id="onboarding")` — never hardcode model string, never call `AsyncOpenAI()` directly.
15. A new DB migration file `supabase/migrations/20260703000000_onboarding_unique_constraint.sql` adds `UNIQUE(user_id, question_id)` to `onboarding_responses` (closes the Sprint 0 code-review finding — no duplicate answers possible at DB level).
16. HTTP 500 is returned if the `onboarding_responses` bulk insert fails for a non-unique-violation reason; the error is logged with `safe_err` sanitization (same pattern as `grade_quiz`).
17. HTTP 409 is returned if the `onboarding_responses` bulk insert fails with a unique constraint violation (duplicate submission race condition).

---

## Tasks / Subtasks

- [x] Task 1: DB migration — add UNIQUE constraint to onboarding_responses (AC: #15) — ✓ 2026-07-02
  - [x] 1.1 Create `supabase/migrations/20260703000000_onboarding_unique_constraint.sql`
  - [x] 1.2 SQL: `ALTER TABLE public.onboarding_responses ADD CONSTRAINT onboarding_responses_user_question_unique UNIQUE (user_id, question_id);`
  - [x] 1.3 Do NOT apply the migration autonomously — create the file only (team PR review required before applying to Supabase)
  - [x] 1.4 Add a comment at the top explaining the constraint closes the Sprint 0 code review finding

- [x] Task 2: Migrate schemas + create OnboardingResult (AC: #2, #3, #4, #12, #13) — ✓ 2026-07-02
  - [x] 2.1 In `apps/api/app/modules/assessment/schemas.py`, add:
    ```python
    from typing import Literal

    class OnboardingAnswer(BaseModel):
        question_id: str
        dimension: Literal["cognitive", "emotional", "self_direction"]
        selected_index: int = Field(ge=0, le=3)
        selected_text: str
        response_time_ms: int | None = Field(default=None, ge=0)

    class OnboardingDiagnosticSubmission(BaseModel):
        responses: list[OnboardingAnswer] = Field(min_length=20, max_length=20)

    class OnboardingResult(BaseModel):
        badge_labels: list[str]
        profile_text: str
        session_count: int
    ```
  - [x] 2.2 Remove `OnboardingAnswer` and `OnboardingDiagnosticSubmission` class definitions from `router.py`
  - [x] 2.3 In `router.py`, add `OnboardingAnswer, OnboardingDiagnosticSubmission, OnboardingResult` to the `schemas` import

- [x] Task 3: Create onboarding_questions.py — question → sub-dimension mapping (AC: #6) — ✓ 2026-07-02
  - [x] 3.1 Create `apps/api/app/modules/assessment/onboarding_questions.py`
  - [x] 3.2 Define `QUESTION_SUBDIMENSION_MAP: dict[str, str]` mapping all 20 question IDs to their sub-dimension:
    ```python
    # Cognitive (c1–c8) → pattern_recognition, logical_deduction, processing_speed
    "c1": "pattern_recognition",   # learning style preference
    "c2": "logical_deduction",     # concept abstraction
    "c3": "logical_deduction",     # problem-solving approach
    "c4": "processing_speed",      # attention span
    "c5": "pattern_recognition",   # retention method
    "c6": "processing_speed",      # reading preference (sequential speed)
    "c7": "logical_deduction",     # ambiguity tolerance
    "c8": "pattern_recognition",   # quiz format preference
    # Emotional (e1–e5) → frustration_tolerance, persistence, help_seeking
    "e1": "frustration_tolerance", # reaction to wrong answers
    "e2": "persistence",           # response to encouragement
    "e3": "frustration_tolerance", # effect of time pressure
    "e4": "help_seeking",          # confusion reaction
    "e5": "help_seeking",          # AI tracking comfort
    # Self-direction (s1–s7) → goal_orientation, curiosity_index, study_independence
    "s1": "goal_orientation",      # goal-setting frequency
    "s2": "curiosity_index",       # free-choice behaviour
    "s3": "study_independence",    # pacing preference
    "s4": "study_independence",    # setback response
    "s5": "goal_orientation",      # self-review habit
    "s6": "curiosity_index",       # study consistency
    "s7": "study_independence",    # post-lesson behaviour
    ```
  - [x] 3.3 Define `ALL_NINE_DIMENSIONS: tuple[str, ...]` listing all 9 sub-dimension column names
  - [x] 3.4 Define `BADGE_THRESHOLDS: dict[str, str]` mapping sub-dimension → badge label (threshold: score >= 70)
    ```python
    "pattern_recognition": "Pattern Thinker",
    "logical_deduction": "Logical Reasoner",
    "processing_speed": "Quick Processor",
    "frustration_tolerance": "Resilient Learner",
    "persistence": "Persistent Achiever",
    "help_seeking": "Collaborative Learner",
    "goal_orientation": "Goal-Oriented",
    "curiosity_index": "Curious Explorer",
    "study_independence": "Self-Directed Learner",
    ```

- [x] Task 4: Add onboarding profile prompt to prompts.py (AC: #8, #9, #10) — ✓ 2026-07-02
  - [x] 4.1 Add `ONBOARDING_PROFILE_SYSTEM_PROMPT` constant — instructs model to write a 2–3 sentence descriptive profile using learning tendency language, no IQ/EQ/SQ terms, no clinical language, no raw numbers
  - [x] 4.2 Add `DPDP_DISCLAIMER` constant: `"This assessment reflects your personal learning preferences, not your intelligence or capability. TransformED Learner DNA is not a clinical assessment and does not diagnose any learning or psychological condition. — Pursuant to DPDP Act 2023."`
  - [x] 4.3 Add `build_onboarding_profile_prompt(badge_labels: list[str]) -> str` function — builds user-turn message using badge labels as dimension descriptors (no numeric scores in prompt to model either)
  - [x] 4.4 Add `generate_onboarding_profile(*, badge_labels: list[str], provider: Any) -> str` async function — calls `provider.complete()` with `settings.llm_mini`, appends `DPDP_DISCLAIMER` to the result before returning

- [x] Task 5: Implement process_onboarding() in service.py (AC: #5, #6, #7, #8, #9, #10, #14, #16, #17) — ✓ 2026-07-02
  - [x] 5.1 Import `OnboardingAnswer, OnboardingResult` from `schemas`, `QUESTION_SUBDIMENSION_MAP, ALL_NINE_DIMENSIONS, BADGE_THRESHOLDS` from `onboarding_questions`, `generate_onboarding_profile` from `prompts`
  - [x] 5.2 Add private `_compute_dimension_scores(responses: list[OnboardingAnswer]) -> dict[str, float]`:
    - For each response: `normalized = (selected_index / 3) * 100`
    - Group normalized scores by sub-dimension using `QUESTION_SUBDIMENSION_MAP`
    - Per sub-dimension: `score = round(mean(normalized_values_for_dim), 2)`
    - Default `50.0` for any dimension with no mapped questions (safety net)
    - Return dict with all 9 dimensions
  - [x] 5.3 Add private `_compute_badge_labels(scores: dict[str, float]) -> list[str]`:
    - Iterate `BADGE_THRESHOLDS`; add badge label if `scores[subdim] >= 70.0`
    - Return list (may be empty for first-time user with all mid-range scores)
  - [x] 5.4 Add async `process_onboarding(*, responses: list[OnboardingAnswer], user_id: str, supabase: Any) -> OnboardingResult`:
    - **Step 1** — Bulk insert 20 rows to `onboarding_responses`:
      ```python
      rows = [
          {
              "user_id": user_id,
              "question_id": ans.question_id,
              "response_value": ans.selected_index,   # selected_index → response_value
              "response_time_ms": ans.response_time_ms,
              "dimension_tag": ans.dimension,          # dimension → dimension_tag
          }
          for ans in responses
      ]
      ```
    - Wrap insert in `asyncio.to_thread`
    - Error check: inspect error string for `"duplicate"` / `"unique"` → HTTP 409; else → HTTP 500 with `safe_err` log
    - **Step 2** — Compute 9 dimension scores using `_compute_dimension_scores`
    - **Step 3** — Clamp all scores to [0.0, 100.0] (service-layer validation; DB constraint is the final gate)
    - **Step 4** — Compute badge labels using `_compute_badge_labels`
    - **Step 5** — Generate `profile_text` via `generate_onboarding_profile(badge_labels=badge_labels, provider=OpenAILLMProvider(lesson_id="onboarding"))`
    - **Step 6** — Upsert to `learner_dna`:
      ```python
      upsert_data = {
          "user_id": user_id,
          "session_count": 0,
          "badge_labels": badge_labels,
          "profile_text": profile_text,
          "last_updated": "now()",
          **{dim: scores[dim] for dim in ALL_NINE_DIMENSIONS},
      }
      ```
      Use `.upsert(upsert_data, on_conflict="user_id")` — not `.insert()` (handles the edge case where a row already exists)
    - Upsert wrapped in `asyncio.to_thread`
    - Error check: if upsert returns error → HTTP 500 with `safe_err` log
    - **Step 7** — Return `OnboardingResult(badge_labels=badge_labels, profile_text=profile_text, session_count=0)`

- [x] Task 6: Update router submit_onboarding_diagnostic() (AC: #1, #11, #12) — ✓ 2026-07-02
  - [x] 6.1 Change `status_code` from `HTTP_202_ACCEPTED` to `HTTP_201_CREATED`
  - [x] 6.2 Change return type annotation from `dict[str, str]` to `OnboardingResult`
  - [x] 6.3 Add `response_model=OnboardingResult`
  - [x] 6.4 Implement body (lazy imports pattern — same as `submit_quiz`):
    ```python
    from app.core.db import get_supabase
    from app.core.redis import get_redis
    from app.modules.assessment.service import process_onboarding

    user_id = current_user["sub"]
    redis = get_redis()
    onboarding_key = f"user:{user_id}:onboarding_done"

    existing = await redis.get(onboarding_key)
    if existing == "1":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Onboarding diagnostic already completed.",
        )

    result = await process_onboarding(
        responses=body.responses,
        user_id=user_id,
        supabase=get_supabase(),
    )

    await redis.set(onboarding_key, "1")
    return result
    ```

- [x] Task 7: Write unit tests in test_onboarding_endpoint.py (AC: #1–#17) — ✓ 2026-07-02
  - [x] 7.1 `test_409_when_onboarding_already_done` — mock `redis.get` returning `"1"` → assert 409
  - [x] 7.2 `test_422_when_fewer_than_20_responses` — send 19 responses → assert 422
  - [x] 7.3 `test_422_when_more_than_20_responses` — send 21 responses → assert 422
  - [x] 7.4 `test_422_when_invalid_dimension` — send `dimension="invalid_dim"` → assert 422
  - [x] 7.5 `test_422_when_selected_index_negative` — `selected_index=-1` → assert 422
  - [x] 7.6 `test_422_when_selected_index_exceeds_3` — `selected_index=4` → assert 422
  - [x] 7.7 `test_all_9_dimensions_computed` — mock 20 responses (c1-c8, e1-e5, s1-s7 all present), assert `_compute_dimension_scores` returns dict with exactly 9 keys matching `ALL_NINE_DIMENSIONS`
  - [x] 7.8 `test_dimension_scores_within_bounds` — all 20 responses with `selected_index=3` → all dimensions = 100.0; all `selected_index=0` → all dimensions = 0.0
  - [x] 7.9 `test_dimension_score_normalization` — `selected_index=1` → normalized = `round((1/3)*100, 2)` = `33.33`; verify score matches expected
  - [x] 7.10 `test_redis_set_after_success` — mock full flow, assert `redis.set(onboarding_key, "1")` called after `process_onboarding`
  - [x] 7.11 `test_profile_text_has_dpdp_disclaimer` — mock LLM returning `"You are a..."`, assert returned `profile_text` ends with `"— Pursuant to DPDP Act 2023."`
  - [x] 7.12 `test_profile_text_no_raw_numeric_scores` — assert response `profile_text` does not match `r"\b\d+\.\d+\b"` (no floats like "67.5" in the text)
  - [x] 7.13 `test_response_has_no_raw_dimension_scores` — assert `OnboardingResult` response does not have numeric dimension fields (no `pattern_recognition`, `logical_deduction`, etc. in response)
  - [x] 7.14 `test_session_count_is_zero` — assert upsert call includes `session_count: 0`
  - [x] 7.15 `test_badge_labels_no_iq_eq_sq` — generate badge_labels, assert none contain "IQ", "EQ", "SQ" (case-insensitive)
  - [x] 7.16 `test_insert_error_non_duplicate_returns_500` — mock insert error without "unique" in string → assert 500
  - [x] 7.17 `test_insert_error_duplicate_returns_409` — mock insert error containing "duplicate" → assert 409
  - [x] 7.18 `test_schemas_in_schemas_not_router` — import `OnboardingAnswer` from `app.modules.assessment.schemas`, assert it can be instantiated

- [x] Task 8: Run tests and verify 0 failures (AC: all) — ✓ 2026-07-02
  - [x] 8.1 Run `cd apps/api && pytest -m unit -v` — assert exit 0, zero failures
  - [x] 8.2 Verify no regressions in existing 72 unit tests (quiz 28 + teachback 44)
  - [x] 8.3 Verify new test count ≥ 18 in `test_onboarding_endpoint.py`
  - [x] 8.4 Verify `pytest` shows all new tests with descriptive names in output

---

## Dev Notes

### Critical Schema Issues in Current router.py (Must Fix)

The current `OnboardingAnswer` in `router.py` (lines 56–65) has two bugs:

| Issue | Current Code | Correct |
|-------|-------------|---------|
| Field name mismatch | `dimension: str` | Keep `dimension` in API schema (matches frontend); map to `dimension_tag` in service DB write |
| Missing field | No `response_time_ms` | Add `response_time_ms: int \| None = Field(default=None, ge=0)` |
| No validation on `selected_index` | `selected_index: int` (unbounded) | `selected_index: int = Field(ge=0, le=3)` |
| No validation on `dimension` | `dimension: str` (any string) | `Literal["cognitive", "emotional", "self_direction"]` |
| Missing length validation | `responses: list[OnboardingAnswer]` (any length) | `Field(min_length=20, max_length=20)` |

### DB Schema — onboarding_responses (read-only migration)

```sql
-- supabase/migrations/20260611000000_initial_schema.sql lines 247-256
CREATE TABLE public.onboarding_responses (
  id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          uuid        NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  question_id      text        NOT NULL,
  response_value   integer     NOT NULL,        -- stores selected_index (0-3)
  response_time_ms integer,                     -- nullable: frontend may not send it
  dimension_tag    text        NOT NULL
                               CHECK (dimension_tag IN ('cognitive', 'emotional', 'self_direction')),
  created_at       timestamptz NOT NULL DEFAULT now()
);
```

**Key mappings from API → DB:**
- `OnboardingAnswer.selected_index` → `onboarding_responses.response_value` (integer, NOT Likert 1-5)
- `OnboardingAnswer.dimension` → `onboarding_responses.dimension_tag` (rename in service layer)

**Sprint 0 code review finding (open):** No `UNIQUE(user_id, question_id)` constraint. Task 1 of this story adds this via a new migration.

### DB Schema — learner_dna (read-only migration)

```sql
-- supabase/migrations/20260611000000_initial_schema.sql lines 224-240
CREATE TABLE public.learner_dna (
  id                   uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id              uuid         NOT NULL UNIQUE REFERENCES public.users(id) ON DELETE CASCADE,
  pattern_recognition  numeric(5,2) CHECK (pattern_recognition  >= 0 AND pattern_recognition  <= 100),
  logical_deduction    numeric(5,2) CHECK (...),
  processing_speed     numeric(5,2) CHECK (...),
  frustration_tolerance numeric(5,2) CHECK (...),
  persistence          numeric(5,2) CHECK (...),
  help_seeking         numeric(5,2) CHECK (...),
  goal_orientation     numeric(5,2) CHECK (...),
  curiosity_index      numeric(5,2) CHECK (...),
  study_independence   numeric(5,2) CHECK (...),
  badge_labels         text[]       NOT NULL DEFAULT '{}',
  profile_text         text,
  session_count        integer      NOT NULL DEFAULT 0,
  last_updated         timestamptz  NOT NULL DEFAULT now()
);
```

**`user_id UNIQUE`** — upsert pattern is correct; one row per user. Use `.upsert(..., on_conflict="user_id")`.

### Question → Sub-dimension Mapping (define in onboarding_questions.py)

Based on the question areas documented in Story 3-4 (Task 1.1 and Task 3.1):

| Question ID | Area | Sub-dimension |
|------------|------|--------------|
| c1 | learning style preference | pattern_recognition |
| c2 | concept abstraction | logical_deduction |
| c3 | problem-solving approach | logical_deduction |
| c4 | attention span | processing_speed |
| c5 | retention method | pattern_recognition |
| c6 | reading preference | processing_speed |
| c7 | ambiguity tolerance | logical_deduction |
| c8 | quiz format preference | pattern_recognition |
| e1 | reaction to wrong answers | frustration_tolerance |
| e2 | response to encouragement | persistence |
| e3 | effect of time pressure | frustration_tolerance |
| e4 | confusion reaction | help_seeking |
| e5 | AI tracking comfort | help_seeking |
| s1 | goal-setting frequency | goal_orientation |
| s2 | free-choice behaviour | curiosity_index |
| s3 | pacing preference | study_independence |
| s4 | setback response | study_independence |
| s5 | self-review habit | goal_orientation |
| s6 | study consistency | curiosity_index |
| s7 | post-lesson behaviour | study_independence |

Sub-dimension counts: pattern_recognition=3, logical_deduction=3, processing_speed=2, frustration_tolerance=2, persistence=1, help_seeking=2, goal_orientation=2, curiosity_index=2, study_independence=3.

### Scoring Formula

```python
# For each response:
normalized = (answer.selected_index / 3) * 100   # maps 0→0, 1→33.33, 2→66.67, 3→100

# Per sub-dimension:
dim_score = round(mean(normalized_values_for_that_subdimension), 2)
# Default 50.0 for any subdimension with no mapped questions (safety net only)
```

`response_time_ms` is stored in DB but NOT used in Sprint 2 scoring computation. Sprint 3 will blend it into `processing_speed`. Do not implement time-based scoring in this story.

### Existing Code Patterns (MUST follow)

**asyncio.to_thread wrapping (service.py pattern):**
```python
resp = await asyncio.to_thread(
    lambda: supabase.table("onboarding_responses")
    .insert(rows)
    .execute()
)
```

**Error sanitization (grade_quiz / grade_teachback pattern):**
```python
if getattr(resp, "error", None):
    safe_err = str(resp.error).replace('\n', ' ').replace('\r', ' ')
    error_str = safe_err.lower()
    if "duplicate" in error_str or "unique" in error_str:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, ...)
    logger.error("onboarding_responses insert failed: %s", safe_err)
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, ...)
```

**LLM call pattern (prompts.py):**
```python
async def generate_onboarding_profile(*, badge_labels: list[str], provider: Any) -> str:
    settings = get_settings()
    messages = [
        {"role": "system", "content": ONBOARDING_PROFILE_SYSTEM_PROMPT},
        {"role": "user", "content": build_onboarding_profile_prompt(badge_labels=badge_labels)},
    ]
    text: str = await provider.complete(messages=messages, model=settings.llm_mini)
    return f"{text.strip()}\n\n{DPDP_DISCLAIMER}"
```

**Router lazy import pattern (submit_quiz pattern):**
```python
from app.core.db import get_supabase  # lazy — prevents circular import at module load
from app.core.redis import get_redis
from app.modules.assessment.service import process_onboarding
```

**OpenAILLMProvider for onboarding (no lesson_id):**
```python
provider = OpenAILLMProvider(lesson_id="onboarding")
# lesson_id="onboarding" is a sentinel — cost is tracked against this label
```
The provider's `_maybe_accumulate_cost` skips if `lesson_id` maps to no lesson row — this is safe. The cost tracking in Langfuse will show label "onboarding".

### Redis Usage

```python
# From app.core.redis — already used in dependencies.py
from app.core.redis import get_redis

redis = get_redis()  # synchronous getter, returns Redis[str] (decode_responses=True)
existing = await redis.get(f"user:{user_id}:onboarding_done")    # async get
await redis.set(f"user:{user_id}:onboarding_done", "1")           # async set
```

`get_redis()` throws `RuntimeError` if `init_redis()` was not called — but this is wired in `main.py` lifespan startup. No additional wiring needed.

### DPDP Disclaimer (exact string — must not be altered)

```python
DPDP_DISCLAIMER = (
    "This assessment reflects your personal learning preferences, not your intelligence "
    "or capability. TransformED Learner DNA is not a clinical assessment and does not "
    "diagnose any learning or psychological condition. — Pursuant to DPDP Act 2023."
)
```

Tests will assert `profile_text.endswith("— Pursuant to DPDP Act 2023.")` — the last fragment only, not the full paragraph (GPT may re-word the first sentence). The `generate_onboarding_profile` function appends the full `DPDP_DISCLAIMER` suffix after a newline, so the endswith check is always reliable.

### ONBOARDING_PROFILE_SYSTEM_PROMPT Guidelines

The prompt must:
- Ask for 2–3 sentences in second person ("You tend to...", "Your learning style...")
- Describe tendencies, not abilities ("You tend to approach concepts sequentially" not "You are a fast learner")
- Use only the badge_labels as input — no dimension names, no scores
- Explicitly forbid IQ/EQ/SQ language in the prompt itself
- Explicitly forbid clinical language
- NOT mention the word "assessment" or "test" in the generated text

### OpenAPI Contract Note

The current stub returns `HTTP 202 Accepted` with `dict[str, str]`. This story changes it to:
- `HTTP 201 Created` (synchronous creation, not async)
- Response: `OnboardingResult` (badge_labels, profile_text, session_count)

This is a breaking change to the OpenAPI spec that requires awareness from Dev 2 (frontend consumer). Communicate with Dev 2 before merging. The `docs/openapi-assessment.json` file should be regenerated and committed after this PR merges (run `python apps/api/scripts/export_openapi.py`).

### Files to Modify

| File | Change |
|------|--------|
| `apps/api/app/modules/assessment/schemas.py` | Add `OnboardingAnswer`, `OnboardingDiagnosticSubmission`, `OnboardingResult` |
| `apps/api/app/modules/assessment/router.py` | Remove old schemas, update `submit_onboarding_diagnostic()` |
| `apps/api/app/modules/assessment/service.py` | Add `process_onboarding()` + private helpers |
| `apps/api/app/modules/assessment/prompts.py` | Add `ONBOARDING_PROFILE_SYSTEM_PROMPT`, `DPDP_DISCLAIMER`, helpers |

### Files to Create

| File | Purpose |
|------|---------|
| `apps/api/app/modules/assessment/onboarding_questions.py` | Question → sub-dimension mapping constants |
| `supabase/migrations/20260703000000_onboarding_unique_constraint.sql` | UNIQUE(user_id, question_id) constraint |
| `apps/api/tests/test_onboarding_endpoint.py` | 18+ unit tests |

### Files NOT to Touch

| File | Reason |
|------|--------|
| `supabase/migrations/20260611000000_initial_schema.sql` | NEVER modify applied migrations |
| `supabase/migrations/20260625000000_chunks_inline_embedding.sql` | NEVER modify applied migrations |
| `packages/shared/` | Read-only for Dev 3 |
| `apps/api/app/providers/llm/openai.py` | Read-only provider — call, never modify |

### Test Mocking Strategy

Unit tests must mock:
- `redis.get` and `redis.set` (the async Redis client methods)
- `supabase.table("onboarding_responses").insert(...).execute()` via a lambda-captured mock
- `OpenAILLMProvider.complete()` — return a fixed profile text string
- No real DB calls, no real Redis, no real LLM in unit tests

Use `unittest.mock.AsyncMock` for `redis.get`/`redis.set` and `unittest.mock.MagicMock` for the synchronous Supabase client (wrapped in `asyncio.to_thread` — the thread call passes a lambda so the mock just needs to return an object with `.data` and no `.error`).

### Known Pending Issue — response_time_ms in Frontend

The current onboarding page (`apps/web/src/app/onboarding/page.tsx`) sends:
`{ question_id, dimension, selected_index, selected_text }` — no `response_time_ms` yet.

This is fine: `OnboardingAnswer.response_time_ms` defaults to `None`. The DB column `onboarding_responses.response_time_ms` is nullable. The scoring in Sprint 2 ignores `response_time_ms`. Sprint 3 will add time-based processing_speed signals (Dev 2 will update the frontend payload at that point).

---

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

None — implementation completed cleanly.

### Completion Notes List

- 41 unit tests written and passing (41/41 GREEN)
- No regressions in existing 72 assessment tests (113 total assessment tests pass)
- Scoring formula: normalized = (selected_index / 3) * 100; dim_score = round(mean, 2) — exact match to story spec
- DPDP_DISCLAIMER appended in generate_onboarding_profile via `f"{text.strip()}\n\n{DPDP_DISCLAIMER}"` — endswith check always reliable
- prompts.get_settings patched separately from service.get_settings in tests — both paths call get_settings independently
- router calls get_supabase() before process_onboarding, so HTTP tests must patch both get_redis and get_supabase
- session_count=0 confirmed in learner_dna upsert payload via capture_upsert side_effect test

### File List

- `docs/stories/3-18-onboarding-assessment-scoring.md` — this story file
- `supabase/migrations/20260703000000_onboarding_unique_constraint.sql` — new migration
- `apps/api/app/modules/assessment/schemas.py` — added OnboardingAnswer, OnboardingDiagnosticSubmission, OnboardingResult
- `apps/api/app/modules/assessment/onboarding_questions.py` — new file: QUESTION_SUBDIMENSION_MAP, ALL_NINE_DIMENSIONS, BADGE_THRESHOLDS
- `apps/api/app/modules/assessment/prompts.py` — added DPDP_DISCLAIMER, ONBOARDING_PROFILE_SYSTEM_PROMPT, generate_onboarding_profile
- `apps/api/app/modules/assessment/service.py` — added _compute_dimension_scores, _compute_badge_labels, process_onboarding
- `apps/api/app/modules/assessment/router.py` — updated submit_onboarding_diagnostic (201, OnboardingResult, full logic)
- `apps/api/tests/test_onboarding_endpoint.py` — 41 unit tests

---

## Change Log

| Date | Change |
|------|--------|
| 2026-07-02 | Story 3-18 created — Sprint 2 Task 1: Onboarding Assessment Scoring |
| 2026-07-02 | Story 3-18 implemented — all 8 tasks complete, 41 tests GREEN, status: done |
