---
baseline_commit: ""
---

# Story 3-9: POST /api/assessment/teachback Endpoint Live

**Status:** done

---

## Story

As Dev 3 (tannmayygupta),
I want `POST /api/assessment/teachback` to fully delegate to a `grade_teachback()` service function,
so that a student's typed teach-back response is evaluated by GPT-4o-mini, persisted to
`teachback_attempts`, and returned with rubric scores, CES contribution, and praise/correction feedback.

---

## Context

Sprint 0 Task 6 established the full scoring foundation:
- `prompts.py` — `TeachbackScoreResult`, `TEACHBACK_SYSTEM_PROMPT`, `build_teachback_user_prompt()`, `score_teachback()`
- `router.py` — endpoint stub raises HTTP 501
- `schemas.py` — contains only quiz models (TeachbackSubmission / TeachbackResult are in router.py — they must be MOVED to schemas.py before service.py can import them without circular imports)

This story activates the endpoint: removes the 501, adds `grade_teachback()` in service.py, extends
`TeachbackScoreResult` to capture individual rubric sub-scores, moves the Teachback models to schemas.py,
and adds comprehensive tests covering all paths.

---

## Acceptance Criteria

### S1-3 — Endpoint live and validated

- **AC 1:** `POST /api/assessment/teachback` with a valid authenticated request returns HTTP 200 and a JSON body matching `TeachbackResult` shape
- **AC 2:** If session is not found → HTTP 404; if `session.user_id` ≠ JWT user → HTTP 403
- **AC 3:** IDOR guard — if `session.lesson_id` ≠ request `lesson_id` → HTTP 403 (identical pattern to grade_quiz)
- **AC 4:** Lesson not found → HTTP 404; segment not found in lesson content → HTTP 404
- **AC 5:** Request with no Authorization header → HTTP 401 or 403 (HTTPBearer auto_error fires before business logic)

### S1-4 — GPT-4o-mini rubric scoring

- **AC 6:** `score_teachback()` is called with `topic = segment["title"]`, `key_concepts = [j["term"] for j in segment.get("jargon", [])]`, and `response_text = body.response_text`
- **AC 7:** `OpenAILLMProvider` is constructed with `lesson_id=lesson_id` so cost is tracked against the lesson (provider handles cost internally)
- **AC 8:** `settings.llm_mini` is the model used — never a hardcoded string, never GPT-4o
- **AC 9:** `TeachbackResult.rubric_scores` contains exactly three float keys: `"accuracy"`, `"completeness"`, `"clarity"` — each in [0, 100] — populated from sub-scores returned by the LLM

### S1-5 — Praise + correction feedback format

- **AC 10:** When `result.score >= 90`: `TeachbackResult.feedback = result.praise` (correction is empty — `model_validator` in `TeachbackScoreResult` enforces this; service must not add a separator for an empty correction)
- **AC 11:** When `result.score < 90`: `TeachbackResult.feedback = f"{result.praise}\n\n{result.correction}"`
- **AC 12:** `TeachbackResult.overall_score = float(result.score)` — the aggregate rubric score on 0-100

### S1-6 — DB writes verified

- **AC 13:** One row inserted into `teachback_attempts` with: `session_id`, `segment_id`, `response_text`, `score`, `feedback_praise` (= `result.praise`), `feedback_correction` (= `result.correction`), `concepts_hit`, `concepts_missed`, `attempt_number`
- **AC 14:** `attempt_number` = (count of prior rows for same session+segment) + 1 — first attempt is 1
- **AC 15:** If supabase insert returns a truthy `.error` → HTTP 500 (same pattern as quiz insert check)

### Non-negotiable rule compliance

- **AC 16:** `TeachbackSubmission` has NO `transcript` field and NO `duration_seconds` field — enforce via schema inspection in a test
- **AC 17:** `TeachbackResult` has NO `duration_seconds` field — enforce via schema inspection in a test
- **AC 18:** `ces_contribution = round((result.score / 100.0) * settings.ces_weight_teachback * 100, 4)` — for score=100, contribution = ces_weight_teachback × 100 (max 25 pts at default weight 0.25); for score=50, contribution = 0.5 × 0.25 × 100 = 12.5

---

## Tasks / Subtasks

### Task 1 — Extend prompts.py (sub-scores for rubric_scores)

- [ ] 1.1 Add `accuracy_score: int = Field(ge=0, le=100)`, `completeness_score: int = Field(ge=0, le=100)`, `clarity_score: int = Field(ge=0, le=100)` to `TeachbackScoreResult` in `prompts.py`
- [ ] 1.2 Update `TEACHBACK_SYSTEM_PROMPT` to ask the LLM to return those three fields in the JSON output alongside `score`, `praise`, `correction`, `concepts_hit`, `concepts_missed`
- [ ] 1.3 Red: write failing test that asserts `TeachbackScoreResult` has `accuracy_score`, `completeness_score`, `clarity_score` attributes — confirm it fails before the change

### Task 2 — Move Teachback models to schemas.py and update router.py

- [ ] 2.1 Move `TeachbackSubmission` and `TeachbackResult` class definitions from `router.py` to `schemas.py`
- [ ] 2.2 In `router.py`: replace the two class bodies with `from app.modules.assessment.schemas import TeachbackSubmission, TeachbackResult`; keep `__all__` updated
- [ ] 2.3 Add `TeachbackSubmission` and `TeachbackResult` to `__all__` in `schemas.py`
- [ ] 2.4 Red: confirm existing tests still pass after the import refactor (no regression)

### Task 3 — Implement grade_teachback() in service.py

- [ ] 3.1 Add `grade_teachback()` async function to `service.py` following the exact same defensive pattern as `grade_quiz()`:
  - Validate session ownership (session 404 → 404, user mismatch → 403, IDOR lesson mismatch → 403)
  - Load lesson 404, segment 404
- [ ] 3.2 Extract `topic = segment["title"]`, `key_concepts = [j["term"] for j in segment.get("jargon", [])]`
- [ ] 3.3 Query `teachback_attempts` count for same session+segment to compute `attempt_number`
- [ ] 3.4 Construct `OpenAILLMProvider(lesson_id=lesson_id)` and call `score_teachback()`
- [ ] 3.5 Compute `ces_contribution = round((result.score / 100.0) * settings.ces_weight_teachback * 100, 4)`
- [ ] 3.6 Build `feedback` string: praise only if score ≥ 90, else `f"{praise}\n\n{correction}"`
- [ ] 3.7 Build and insert `teachback_attempts` row; capture and check insert response error
- [ ] 3.8 Return `TeachbackResult(session_id=..., rubric_scores={...}, overall_score=..., ces_contribution=..., feedback=...)`

### Task 4 — Wire router and add tests

- [ ] 4.1 In `router.py` `submit_teachback()`: remove 501, add lazy imports, call `grade_teachback()`
- [ ] 4.2 Create `apps/api/tests/test_teachback_endpoint.py` with all tests (see Dev Notes for test list)
- [ ] 4.3 Run full test suite: all existing 27 quiz tests still pass; all new teachback tests pass
- [ ] 4.4 Update `dev3-assessment-tracker.md`: mark S1-3, S1-4, S1-5, S1-6 done with today's date

---

## Dev Notes

### Files to Change

| File | Change type | What |
|------|-------------|------|
| `apps/api/app/modules/assessment/prompts.py` | UPDATE | Add 3 sub-score fields to `TeachbackScoreResult`, update system prompt |
| `apps/api/app/modules/assessment/schemas.py` | UPDATE | Move `TeachbackSubmission` + `TeachbackResult` here from router.py |
| `apps/api/app/modules/assessment/router.py` | UPDATE | Replace class bodies with imports from schemas.py; activate submit_teachback |
| `apps/api/app/modules/assessment/service.py` | UPDATE | Add `grade_teachback()` function |
| `apps/api/tests/test_teachback_endpoint.py` | CREATE | Full test file |
| `docs/dev3-assessment-tracker.md` | UPDATE | Mark S1-3..S1-6 done |

### prompts.py — exact TeachbackScoreResult change

Add three new fields **before** the existing `@model_validator`:
```python
accuracy_score: int = Field(ge=0, le=100, description="LLM-assessed accuracy sub-score 0-100")
completeness_score: int = Field(ge=0, le=100, description="LLM-assessed completeness sub-score 0-100")
clarity_score: int = Field(ge=0, le=100, description="LLM-assessed clarity sub-score 0-100")
```

The `score` field (aggregate) stays. The `@model_validator` stays unchanged.

### prompts.py — TEACHBACK_SYSTEM_PROMPT update

Update the "Return a JSON object" section to include the three new fields:
```
Return a JSON object with exactly these fields:
  score              integer 0-100 (weighted rubric total: accuracy*0.40 + completeness*0.35 + clarity*0.25)
  accuracy_score     integer 0-100 (raw accuracy sub-score before weighting)
  completeness_score integer 0-100 (raw completeness sub-score before weighting)
  clarity_score      integer 0-100 (raw clarity sub-score before weighting)
  praise             1-2 sentences of specific, encouraging feedback on what the student did well
  correction         1-2 sentences of constructive feedback on gaps or inaccuracies;
                     use an EMPTY STRING "" (not null, not "None") when score >= 90
  concepts_hit       list of key concepts from the segment that the student demonstrated
  concepts_missed    list of key concepts from the segment that the student omitted or got wrong
```

### schemas.py — Teachback model placement

Move verbatim from router.py. `TeachbackSubmission` must NOT have `transcript` or `duration_seconds`.
`TeachbackResult` must NOT have `duration_seconds`. Field shapes are frozen — do not add or remove fields.

```python
class TeachbackSubmission(BaseModel):
    session_id: str
    lesson_id: str
    segment_id: str
    response_text: str = Field(description="Student's typed teach-back response")

class TeachbackResult(BaseModel):
    session_id: str
    rubric_scores: dict[str, float]
    overall_score: float
    ces_contribution: float
    feedback: str
```

### service.py — grade_teachback() full function signature

```python
async def grade_teachback(
    *,
    session_id: str,
    lesson_id: str,
    segment_id: str,
    response_text: str,
    user_id: str,
    supabase: Any,
) -> TeachbackResult:
```

Do NOT add `duration_seconds` or any timing parameter.

### service.py — attempt_number query pattern

```python
count_resp = await asyncio.to_thread(
    lambda: supabase.table("teachback_attempts")
    .select("id", count="exact")
    .eq("session_id", session_id)
    .eq("segment_id", segment_id)
    .execute()
)
attempt_number = (count_resp.count or 0) + 1
```

`count_resp.count` is the supabase-py v2 count field when `count="exact"` is passed.

### service.py — teachback_attempts insert row

```python
row = {
    "session_id": session_id,
    "segment_id": segment_id,
    "response_text": response_text,
    "score": result.score,
    "feedback_praise": result.praise,
    "feedback_correction": result.correction,
    "concepts_hit": result.concepts_hit,
    "concepts_missed": result.concepts_missed,
    "attempt_number": attempt_number,
}
```

### service.py — CES contribution

```python
settings = get_settings()
ces_contribution: float = round((result.score / 100.0) * settings.ces_weight_teachback * 100, 4)
```

Max: score=100 → 1.0 × 0.25 × 100 = 25.0 pts on the CES scale (sums with quiz's max 35 pts, etc.)

### service.py — feedback string

```python
feedback = result.praise if not result.correction else f"{result.praise}\n\n{result.correction}"
```

When `score >= 90`, `TeachbackScoreResult.@model_validator` already sets `correction = ""`, so `not result.correction` is True and only praise is included.

### service.py — imports needed

```python
from app.modules.assessment.prompts import TeachbackScoreResult, score_teachback
from app.modules.assessment.schemas import TeachbackResult  # after moving from router.py
from app.providers.llm.openai import OpenAILLMProvider
```

### router.py — submit_teachback activated

```python
@router.post("/teachback", response_model=TeachbackResult, ...)
async def submit_teachback(body: TeachbackSubmission, current_user: CurrentUser) -> TeachbackResult:
    from app.core.db import get_supabase
    from app.modules.assessment.service import grade_teachback
    return await grade_teachback(
        session_id=body.session_id,
        lesson_id=body.lesson_id,
        segment_id=body.segment_id,
        response_text=body.response_text,
        user_id=current_user["sub"],
        supabase=get_supabase(),
    )
```

### Test file structure — tests/test_teachback_endpoint.py

Use the exact same mock architecture as `test_quiz_endpoint.py`:
- `asyncio.to_thread` patched with `mock_to_thread` fixture (makes sync calls async-safe in tests)
- `_build_supabase()` helper builds a MagicMock supabase client
- `_SESSION_ROW`, `_LESSON_CONTENT`, `_VALID_HTTP_PAYLOAD` module-level constants

**Critical mock difference for teachback:** The service also calls `score_teachback()` (an async LLM call).
Monkeypatch this at `app.modules.assessment.service.score_teachback` to return a known `TeachbackScoreResult`.

**`mock_to_thread` fixture pattern** (same as quiz tests):
```python
@pytest.fixture
def mock_to_thread(monkeypatch):
    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs) if callable(func) else func()
    monkeypatch.setattr("asyncio.to_thread", fake_to_thread)
    # Also patch OpenAILLMProvider to not need real credentials
    monkeypatch.setattr(
        "app.modules.assessment.service.OpenAILLMProvider",
        lambda **kwargs: MagicMock(),
    )
```

**`_build_supabase()` for teachback** needs to handle count queries too:
- Session query → returns `_SESSION_ROW`
- Lesson query → returns lesson data
- Count query (teachback_attempts count) → `mock.count = 0` (first attempt)
- Insert → `error = None`

**Required test list (18 tests):**

Session/auth validation (5):
1. `test_session_not_found` → 404
2. `test_session_wrong_user` → 403
3. `test_idor_lesson_mismatch` → 403
4. `test_lesson_not_found` → 404
5. `test_segment_not_found` → 404

Scoring (4):
6. `test_happy_path_returns_teachback_result` — full result shape, all fields present
7. `test_ces_contribution_at_full_score` — score=100 → ces_contribution = 1.0 × ces_weight_teachback × 100
8. `test_ces_contribution_at_partial_score` — score=50 → ces_contribution = 0.5 × ces_weight_teachback × 100
9. `test_rubric_scores_contains_accuracy_completeness_clarity` — all three keys present as floats

Feedback format (2):
10. `test_feedback_high_score_praise_only` — score=95 → feedback = praise (no separator)
11. `test_feedback_low_score_praise_and_correction` — score=60 → feedback = f"{praise}\n\n{correction}"

DB writes (4):
12. `test_response_text_written_to_db` — response_text in insert row
13. `test_score_written_to_db` — score in insert row
14. `test_concepts_written_to_db` — concepts_hit and concepts_missed in insert row
15. `test_attempt_number_increments` — existing count=1 → attempt_number=2 in insert row

Non-negotiable rule checks (2):
16. `test_submission_has_no_transcript_or_duration_fields` — schema inspection: `model_fields` must not contain "transcript" or "duration_seconds"
17. `test_result_has_no_duration_seconds_field` — schema inspection on TeachbackResult

HTTP layer (1):
18. `test_unauthenticated_request_returns_403` — no Authorization header → 401/403

Insert error (1):
19. `test_insert_error_raises_500` — insert_resp.error truthy → HTTPException 500

Total: 19 tests.

### Non-negotiable rules (from CLAUDE.md)

- NO `transcript` field anywhere — teach-back is always typed
- NO `duration_seconds` field — implies a timer; creates test anxiety
- NO teach-back timer of any kind
- NEVER gate lesson progress on teach-back score
- GPT call via `settings.llm_mini` only — through `OpenAILLMProvider`, never raw `AsyncOpenAI()`
- ALWAYS pass `lesson_id` to `OpenAILLMProvider` constructor (cost tracking)
- All supabase calls wrapped in `asyncio.to_thread`
- Insert response captured and `.error` checked

---

## Senior Developer Review (AI)

*(To be filled after implementation)*

---

## Dev Agent Record

**Status:** ready-for-dev

**Debug Log:** *(to be filled during implementation)*

**Completion Notes:** *(to be filled on completion)*
