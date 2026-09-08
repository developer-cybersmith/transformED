# Story F2-1 — Learner Context API for Tutor Prompt Injection

**Epic:** Feature 2 — Bug Resolution Sprint  
**Story:** F2-1  
**Branch:** `feature2/f2-1-dna-prompt-context-api`  
**Owner:** Dev 3  
**Status:** ready-for-dev

---

## Story

As the **tutor state machine (Dev 4)**, I need a single internal endpoint that returns a student's historical Learner DNA combined with their current session's engagement signals, in a format ready to inject directly into an LLM system prompt, so the tutor's GPT-4o responses are grounded in who this specific student is and how they are performing right now.

---

## Background

The tutor module (Dev 4) currently has no way to personalise its LLM context. When a student asks a question mid-lesson, the LLM knows nothing about whether they are a visual pattern-thinker, struggling with quiz accuracy, or just skipped three teach-back prompts in a row.

This endpoint fixes that. It is an **internal read-only** endpoint called by Dev 4's tutor state machine, gated by the same JWT the student already holds. No new auth mechanism is introduced.

**Design decisions (clarified 2026-09-04):**
- Behaviour signals: both historical (Learner DNA dimensions + badges + profile_text) and current session (quiz accuracy, teachback scores, CES)
- Response format: structured JSON + a pre-built `prompt_text` string ready for LLM injection
- Auth: standard JWT (`CurrentUser` dependency) — same pattern as every other assessment endpoint

---

## Acceptance Criteria

**AC1 — Endpoint exists and returns 200:**  
`GET /api/assessment/session/{session_id}/learner-context` returns HTTP 200 with a `LearnerContext` response body for the authenticated student's own session.

**AC2 — IDOR protection:**  
If `session_id` belongs to a different user, the endpoint returns HTTP 404 with the unified message `"Session not found or access denied."` — never 403 (existence oracle prevention).

**AC3 — DNA block populated when learner_dna row exists:**  
Response `dna` field contains `badge_labels` (list[str]), `profile_text` (str ending with the DPDP disclaimer), `session_count` (int), and `dimension_labels` (dict mapping each of the 9 dimension keys to a descriptive band string: "strong" | "developing" | "building" | "emerging"). Raw numeric dimension values are NOT returned in this block.

**AC4 — DNA block is null when no learner_dna row exists:**  
When the student has not completed onboarding (no `learner_dna` row), `dna` is `null`. The endpoint still returns HTTP 200 — graceful degradation.

**AC5 — current_session block:**  
Response `current_session` field contains:
- `quiz_accuracy: float | None` — ratio of correct to total quiz answers this session (None if no quiz attempts)
- `quiz_total: int` — total quiz questions answered this session
- `teachback_score: float | None` — average score across all teachback_attempts for this session (None if none)
- `teachback_count: int` — number of teach-back attempts this session
- `ces_score: float | None` — from `sessions.ces_final` if set, else None (session still in progress)

**AC6 — prompt_text is a pre-built LLM-ready string:**  
`prompt_text` is a non-empty string when at least one of `dna` or `current_session` has data. It uses descriptive language only — no raw numeric dimension values appear in it (bands like "strong", "developing" are permitted; raw floats like "72.5" are not). It is safe to prepend directly to an LLM system prompt.

**AC7 — prompt_text is empty string when no context exists:**  
When both `dna` is null and `current_session` has no quiz/teachback data and no CES, `prompt_text` is `""` (empty string, not null).

**AC8 — All DB reads are bounded:**  
Every Supabase query uses `.maybe_single()`, `.limit()`, or operates on a naturally bounded set. No unbounded `select("*")` across arbitrary rows. Guard test `test_unbounded_queries.py` must pass.

**AC9 — No LLM calls — pure data aggregation:**  
The endpoint assembles data from DB and (optionally) Redis. Zero LLM calls. No cost tracking needed. No hardcoded model strings.

**AC10 — `LearnerContext` added to `schemas.py.__all__`; guard tests pass:**  
`LearnerContext` schema added to `schemas.py` and exported in `__all__`. `test_dunder_all_schemas` guard test (if present) passes. `test_unbounded_queries.py` passes. `test_node_return_shape.py` passes (not a node — N/A).

**AC11 — No STT, no timer fields, no raw scores to students:**  
The endpoint body contains no `transcript`, `duration_seconds`, or raw numeric dimension values in any student-displayable field. (The internal `current_session.quiz_accuracy` and `current_session.teachback_score` fields are numeric but are on the internal response object, not in `prompt_text` as raw numbers.)

---

## Scale & Load

**Q1 — Unit of work and range:**  
One unit = one call per tutor prompt build. Triggered once per student question in the TEACH_BACK or TEACHING state. Range: 0–~20 calls per session (bounded by lesson segment count). Peak concurrent: as many active tutor sessions as the platform has students.

**Q2 — Fixed budgets vs variable input:**  
Three DB reads (sessions, learner_dna, quiz/teachback aggregation). All are equality-filtered by session_id or user_id — O(1) with the existing primary-key indexes. No budget is silently variable. If the learner_dna row is absent, that is an explicit null, not a silent failure.

**Q3 — Scope of every limit:**  
- IDOR check: per-session ownership verified per call (stateless)
- DB reads: all per-user, not global scans

**Q4 — Unbounded reads:**  
None. Quiz attempts: `.eq("session_id", ...).select(...)` — bounded by the finite segments in a lesson (~5–20). Teachback attempts: same pattern. Sessions: `.maybe_single()`. Learner_dna: `.maybe_single()`.

**Q5 — Inherited caps re-derived:**  
No inherited caps. This is a new endpoint with no prior design to inherit from.

**Q6 — Check-then-act under concurrent requests:**  
Read-only endpoint. No state is written. No TOCTOU. Safe under concurrent calls.

---

## Dev Notes

### New file: `apps/api/tests/unit/test_f2_1_learner_context.py`
All tests live here. Minimum 9 tests covering ACs 1–11.

### Schema addition: `apps/api/app/modules/assessment/schemas.py`
Add `LearnerContext` at the bottom of the file. Add it to `__all__`.

```python
class LearnerContextDNA(BaseModel):
    badge_labels: list[str]
    profile_text: str | None  # always ends with DPDP disclaimer when not None
    session_count: int
    dimension_labels: dict[str, str]  # 9 keys → descriptive band (no raw floats)

class LearnerContextSession(BaseModel):
    quiz_accuracy: float | None = None
    quiz_total: int = 0
    teachback_score: float | None = None
    teachback_count: int = 0
    ces_score: float | None = None

class LearnerContext(BaseModel):
    session_id: str
    user_id: str
    dna: LearnerContextDNA | None = None
    current_session: LearnerContextSession
    prompt_text: str
```

### Service function: `get_learner_context(session_id, user_id, supabase)`
Add to `apps/api/app/modules/assessment/service.py`.

Logic:
1. Fetch `sessions` row by `session_id` — `.maybe_single()` — verify ownership (404 if missing or wrong user)
2. Fetch `learner_dna` row by `user_id` — `.maybe_single()` — None → `dna=null`
3. Fetch quiz_attempts for `session_id` — `.eq("session_id", ...).select("is_correct")` — compute accuracy
4. Fetch teachback_attempts for `session_id` — `.eq("session_id", ...).select("score")` — compute avg
5. Read `sessions.ces_final` from the already-fetched sessions row
6. Build `prompt_text` using helper `_build_learner_prompt_text(dna, session)`

### Router addition: `apps/api/app/modules/assessment/router.py`
Add new route:
```python
@router.get("/session/{session_id}/learner-context", response_model=LearnerContext, ...)
async def get_learner_context_endpoint(session_id: str, current_user: CurrentUser) -> LearnerContext:
    ...
```

### `_build_learner_prompt_text` helper (in service.py)
- Uses `_dim_descriptor()` (already in `prompts.py`) for dimension bands
- `prompt_text` sections:
  1. If dna not None: "**Student Learning Profile:**\n- Style: {badges}\n- Dimensions: {dim_labels}\n"
  2. "**Current Session:**\n- Quiz: {accuracy_label} ({total} questions)\n- Teach-back: {tb_label}\n- Engagement (CES): {ces_label}\n"
  3. End with "Use this context to personalise your explanation for this student."
- Descriptive labels used for CES and quiz (see existing `_quiz_accuracy_label` and `_score_to_label` helpers)
- Raw floats never appear in prompt_text

### Existing dimension descriptor
`_dim_descriptor(value: float) -> str` is already in `prompts.py`:
```python
if value >= 75.0: return "strong"
elif value >= 55.0: return "developing"
elif value >= 35.0: return "building"
else: return "emerging"
```
Import from `prompts.py` in `service.py` — do not duplicate.

### DB column names (verified from migrations)
- `sessions`: `session_id`, `user_id`, `lesson_id`, `started_at`, `ended_at`, `ces_final`
- `learner_dna`: `user_id`, `dimensions` (JSONB), `badge_labels` (text[]), `profile_text`, `session_count`, `updated_at`
- `quiz_attempts`: `session_id`, `is_correct` (boolean)
- `teachback_attempts`: `session_id`, `score` (int)

### Guard tests to run before every push
```
pytest apps/api/tests/unit/test_unbounded_queries.py -v
pytest apps/api/tests/unit/test_node_return_shape.py -v
pytest apps/api/tests/unit/test_f2_1_learner_context.py -v
```

---

## Tasks / Subtasks

- [ ] T1: Add `LearnerContextDNA`, `LearnerContextSession`, `LearnerContext` to `schemas.py` and `__all__`
- [ ] T2: Write failing RED tests in `tests/unit/test_f2_1_learner_context.py` (AC1–AC11)
- [ ] T3: Implement `get_learner_context()` service function and `_build_learner_prompt_text()` helper in `service.py`
- [ ] T4: Add `GET /session/{session_id}/learner-context` route to `router.py`
- [ ] T5: Run all tests GREEN — `test_f2_1_learner_context.py` + guard tests + full suite
- [ ] T6: Update `docs/dev3-assessment-tracker.md` — mark F2-1 done

---

## File List

**New:**
- `apps/api/tests/unit/test_f2_1_learner_context.py`

**Modified:**
- `apps/api/app/modules/assessment/schemas.py` — add 3 new schema classes + `__all__` entries
- `apps/api/app/modules/assessment/service.py` — add `get_learner_context` + `_build_learner_prompt_text`
- `apps/api/app/modules/assessment/router.py` — add 1 new route
- `docs/dev3-assessment-tracker.md` — mark F2-1 done

---

## Change Log

| Date | Change |
|------|--------|
| 2026-09-05 | Story created (BMAD story-first commit) |
