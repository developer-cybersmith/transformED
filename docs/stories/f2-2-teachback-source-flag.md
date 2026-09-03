# Story F2-2 — Teachback Score Source Flag

**Sprint:** Bug Resolution (Feature Sprint 2)
**Priority:** Low
**Owner:** Dev 3
**Status:** ready-for-dev
**Branch:** `feature2/f2-2-teachback-source-flag`
**Story file committed before any implementation code** (CLAUDE.md Pre-Implementation Checklist)

---

## Story

As a Dev 3 engineer building CES calibration and funnel analytics,
I want every `teachback_attempts` row to carry a `score_source` flag
(`"llm"`, `"fallback"`, or `"skipped"`),
so that I can distinguish a real GPT-4o-mini evaluation from a neutral
fallback (LLM unavailable) or a deliberate skip — without guessing from
score values alone.

---

## Background & Scope

### Why this is needed

The Sprint 4 funnel analysis (S4-7) found a 90.6% drop-off between
`session_start` and `quiz_submitted`. The same blind spot exists for
teachbacks: there is currently no way to tell from `teachback_attempts`
data whether a row represents a genuine student response, a silent LLM
failure, or a skipped segment. All three paths can produce similar scores
(or nulls) with no distinguishing metadata.

### Three paths in scope

| Path | Trigger | Current behaviour | Target behaviour |
|------|---------|-------------------|-----------------|
| `"llm"` | Student submits response, LLM scores it | Implicit (no flag) | `score_source = "llm"` stored |
| `"fallback"` | LLM fails after retries | Raises `HTTPException 502` — no DB row written | Store row with `score=None, score_source="fallback"`, return graceful result |
| `"skipped"` | Student presses Skip | Frontend skips the endpoint entirely — no DB row written | New optional `is_skip: bool` field on request; store row with `score=None, score_source="skipped"` |

### Frozen contract note

`POST /assessment/teachback` is one of the 5 frozen endpoint signatures.
Adding `is_skip: bool = False` to `TeachbackSubmission` (request) is
ADDITIVE and backward-compatible (existing clients that omit the field get
`False` — identical to current behaviour). Adding `score_source` to
`TeachbackResult` (response) is also additive. Both changes still require
the PR to be reviewed by all 4 developers per CLAUDE.md Interface Contracts
§1, but neither is a breaking change.

---

## Acceptance Criteria

**AC1 — New migration adds `score_source` column**
`supabase/migrations/20260903000000_teachback_score_source.sql` exists and
contains:
```sql
ALTER TABLE public.teachback_attempts
  ADD COLUMN score_source TEXT NOT NULL DEFAULT 'llm'
    CHECK (score_source IN ('llm', 'fallback', 'skipped'));
```
`DEFAULT 'llm'` means all existing rows are correctly labelled (every row
written before this migration was produced by the LLM path).

**AC2 — `TeachbackResult` response carries `score_source`**
`TeachbackResult` in `schemas.py` has a new field:
```python
score_source: Literal["llm", "fallback", "skipped"]
```
Existing consumers that ignore the new field are unaffected (additive
change). The field is always present in the response — never absent.

**AC3 — `TeachbackSubmission` gains optional `is_skip` field**
`TeachbackSubmission` in `schemas.py` has a new optional field:
```python
is_skip: bool = Field(default=False)
```
When `is_skip=False` (the default), existing `response_text` validation is
unchanged: blank/whitespace-only text still raises 422. When `is_skip=True`,
`response_text` is allowed to be empty (stored as `""` in DB — valid for
`TEXT NOT NULL`).

The `response_text` field itself keeps `max_length=4000` but its
`min_length=1` constraint is moved into a `@model_validator` that only fires
when `is_skip=False`. The validator message is unchanged for the non-skip
path. No migration needed: `TEXT NOT NULL` in Postgres accepts `""`.

**AC4 — `"llm"` path unchanged except for `score_source`**
When `is_skip=False` and LLM scoring succeeds:
- `score_source = "llm"` is added to the `teachback_attempts` insert row
- `TeachbackResult.score_source = "llm"` is returned
- All other existing behaviour (score, rubric_scores, feedback, CES
  contribution, PostHog event) is unchanged

**AC5 — `"fallback"` path: graceful degradation instead of 502**
When `is_skip=False` and the LLM call raises any exception after retries:
- Do NOT re-raise `HTTPException 502`
- Instead, insert a `teachback_attempts` row:
  ```python
  {
      "session_id": session_id,
      "segment_id": segment_id,
      "response_text": response_text,
      "score": None,
      "feedback_praise": None,
      "feedback_correction": None,
      "concepts_hit": [],
      "concepts_missed": [],
      "attempt_number": attempt_number,
      "score_source": "fallback",
  }
  ```
- Return:
  ```python
  TeachbackResult(
      session_id=session_id,
      rubric_scores={},
      overall_score=0.0,
      ces_contribution=0.0,
      feedback="Scoring temporarily unavailable — your response has been saved.",
      score_source="fallback",
  )
  ```
- Log at `WARNING` (not `ERROR`) with sanitised `session_id` and the
  exception message (no newlines in log values).
- CES contribution is `0.0` — a fallback does not count toward CES, same
  as if the teachback was skipped.

**AC6 — `"skipped"` path: record skip without LLM call**
When `is_skip=True`:
- Skip Steps 2–6 of `grade_teachback` (no lesson JSONB load, no LLM call)
- Insert a `teachback_attempts` row:
  ```python
  {
      "session_id": session_id,
      "segment_id": segment_id,
      "response_text": "",
      "score": None,
      "feedback_praise": None,
      "feedback_correction": None,
      "concepts_hit": [],
      "concepts_missed": [],
      "attempt_number": attempt_number,
      "score_source": "skipped",
  }
  ```
- Return:
  ```python
  TeachbackResult(
      session_id=session_id,
      rubric_scores={},
      overall_score=0.0,
      ces_contribution=0.0,
      feedback="",
      score_source="skipped",
  )
  ```
- No PostHog event fired for a skipped teachback (analytics only tracks
  real submissions: `is_skip=False`).
- **Lesson progress is never gated on teachback score.** `score=None` must
  never block the student from continuing (this is a CLAUDE.md absolute
  rule, not an AC — mentioned here as a reminder).

**AC7 — `attempt_number` still computed correctly for all three paths**
The existing `count_resp` query (Step 5 in `grade_teachback`) must run for
ALL three paths — `"llm"`, `"fallback"`, and `"skipped"` — so that
`attempt_number` is correct even if a student submits, then gets a fallback,
then submits again.
Exception: for the `"skipped"` path, Steps 1 (session ownership) and 5
(attempt count) still run; Steps 2–6 (lesson load, LLM call) do not.

**AC8 — No raw score is injected as a fake LLM score**
`"fallback"` and `"skipped"` rows MUST store `score=None`. They MUST NOT
store `score=50` or any other sentinel integer. The CHECK constraint enforces
the `score_source` enum; the `score IS NULL` fact is what tells analytics
these rows are non-evaluative.

**AC9 — `TeachbackDetail` in session report carries `score_source`**
`TeachbackDetail` schema (`router.py`) adds:
```python
score_source: Literal["llm", "fallback", "skipped"] = "llm"
```
(default `"llm"` so pre-migration rows — which have no column and will read
as the DB DEFAULT — deserialise correctly). The session report service's
`teachback_attempts` SELECT must include `score_source` in the select list.
This is an additive change to `SessionReport` (which contains
`list[TeachbackDetail] | None`) — backward-compatible.

**AC10 — Existing guard tests pass**
- `tests/test_ces.py::test_dunder_all_contains_only_compute_ces`
- `tests/test_ces.py::test_no_hardcoded_weight_literals_in_ces_py`
- `tests/unit/test_unbounded_queries.py` — all tests (no new unbounded
  queries introduced; the `teachback_attempts` count query in Step 5 already
  exists and is unchanged)
- `tests/unit/test_node_return_shape.py`

---

## Tasks / Subtasks

- [ ] T1 — Write failing unit tests (RED phase)
  - [ ] T1.1 AC1: migration file exists with correct SQL
  - [ ] T1.2 AC2: `TeachbackResult` has `score_source` field
  - [ ] T1.3 AC3: `TeachbackSubmission` has `is_skip` field; blank text raises 422 when `is_skip=False`; blank text accepted when `is_skip=True`
  - [ ] T1.4 AC4: `"llm"` happy path returns `score_source="llm"` and inserts it to DB row
  - [ ] T1.5 AC5: LLM exception → fallback row inserted, 200 returned with `score_source="fallback"`, `score=None`, `ces_contribution=0.0`
  - [ ] T1.6 AC6: `is_skip=True` → skip row inserted, no LLM call, `score_source="skipped"`, `score=None`, `ces_contribution=0.0`
  - [ ] T1.7 AC7: `attempt_number` correct for skip and fallback paths
  - [ ] T1.8 AC8: fallback and skipped rows have `score=None` not an integer
  - [ ] T1.9 AC9: `TeachbackDetail` has `score_source`; session report SELECT includes it
  - [ ] T1.10 AC10: guard tests still pass after changes

- [ ] T2 — Write migration
  - [ ] T2.1 `supabase/migrations/20260903000000_teachback_score_source.sql`

- [ ] T3 — Schema changes (`schemas.py`)
  - [ ] T3.1 Add `score_source: Literal["llm", "fallback", "skipped"]` to `TeachbackResult`
  - [ ] T3.2 Add `is_skip: bool = Field(default=False)` to `TeachbackSubmission`; refactor `response_text` validator to `@model_validator(mode="after")` that fires only when `is_skip=False`
  - [ ] T3.3 Add `score_source: Literal["llm", "fallback", "skipped"] = "llm"` to `TeachbackDetail` in `router.py`

- [ ] T4 — Service changes (`service.py` — `grade_teachback`)
  - [ ] T4.1 Skipped path: when `is_skip=True`, run Steps 1 + 5, skip Steps 2–6, insert skipped row, return skipped result
  - [ ] T4.2 LLM path: add `score_source="llm"` to Step 9 insert row and return value
  - [ ] T4.3 Fallback path: replace `raise HTTPException 502` with fallback row insert + graceful return; log at WARNING
  - [ ] T4.4 Session report SELECT: add `score_source` to `teachback_attempts` select in `get_session_report`

- [ ] T5 — Run full unit suite; confirm no regressions

---

## Dev Notes

### Files to modify

| File | Change |
|------|--------|
| `supabase/migrations/20260903000000_teachback_score_source.sql` | New file — ALTER TABLE |
| `apps/api/app/modules/assessment/schemas.py` | `TeachbackResult` + `TeachbackSubmission` |
| `apps/api/app/modules/assessment/router.py` | `TeachbackDetail` schema |
| `apps/api/app/modules/assessment/service.py` | `grade_teachback` + `get_session_report` |

### Do NOT touch

- `ces.py` — guard tests are strict equality on `__all__`
- `dna_fusion.py` — not in scope
- Any of the other 4 frozen endpoint handlers

### `grade_teachback` call site in `router.py`

The router currently calls:
```python
return await grade_teachback(
    session_id=body.session_id,
    lesson_id=body.lesson_id,
    segment_id=body.segment_id,
    response_text=body.response_text,
    user_id=current_user.id,
    supabase=get_supabase(),
)
```
Add `is_skip=body.is_skip` to this call after adding the parameter to
`grade_teachback`'s signature.

### Fallback path — what NOT to do

Do NOT store `score=50` as a neutral fallback integer. Storing `None`
is the correct signal that this row has no real score; consumers (CES,
Learner DNA) already handle `None` teachback scores via the redistributed
4-signal CES formula (CLAUDE.md CES Formula section).

### `response_text` validator refactor

Current code:
```python
@field_validator("response_text")
@classmethod
def response_text_not_blank(cls, v: str) -> str:
    if not v.strip():
        raise ValueError("response_text must not be blank or whitespace-only")
    return v
```

Replace with a `@model_validator(mode="after")` that fires only when
`is_skip=False`:
```python
@model_validator(mode="after")
def _validate_response_or_skip(self) -> "TeachbackSubmission":
    if not self.is_skip and not self.response_text.strip():
        raise ValueError("response_text must not be blank or whitespace-only")
    return self
```
Also change `response_text` field from `min_length=1` to `min_length=0`
(or just `str = Field(default="", max_length=4000)`).

### Test file location

`apps/api/tests/unit/test_f2_2_teachback_source_flag.py`
Mark all tests `@pytest.mark.unit`.

### Mock pattern

Follow `test_f2_1_dna_prompt_context.py`'s `_make_supabase()` and
`_make_redis()` factory pattern. For LLM mocking, mock `score_teachback`
directly with `AsyncMock(side_effect=Exception("LLM down"))` for the
fallback path and `AsyncMock(return_value=<result_fixture>)` for the llm
path.

---

## Scale & Load

**Q1 — Unit of work and range**
One function call per teachback submission per segment per session. Min: 0
(student skips all — with this story, each skip now generates one row).
Typical: ~10 rows per session (one per segment). Max: ~50 rows (5 attempts
per segment × 10 segments). Beyond: no hard cap on attempts per segment —
this is a pre-existing gap (D107), not introduced here.

**Q2 — Fixed budgets vs variable input**
`score_source` is a fixed-enum CHECK constraint — bounded by definition.
No new budgets introduced. The existing `count_resp` query (attempt_number
computation) carries no `.limit()` — this is a pre-existing gap (D107
tracking unbounded retake count) that is OUT OF SCOPE here; the gap is not
worsened by this story since the query already existed.

**Q3 — Scope of limits**
Per `session_id` + `segment_id` (naturally bounded by session lifecycle and
lesson structure).

**Q4 — Unbounded reads**
No new unbounded queries introduced. The `teachback_attempts` count query
(Step 5) and the `teachback_attempts` select in `get_session_report` both
pre-existed.

**Q5 — Inherited caps**
`DEFAULT 'llm'` for the new column is re-derived: all rows written before
this migration were produced by the LLM path. No historical row was a skip
or fallback (skip = no row written; fallback = 502 with no row written).
DEFAULT is therefore correct for all historical data.

**Q6 — TOCTOU**
No check-then-act sequences added. The attempt_number count-then-insert is
a pre-existing pattern (shared with quiz_attempts); no new race is
introduced.

---

## Dev Agent Record

### Implementation Plan
_To be filled in by dev agent._

### Debug Log
_To be filled in by dev agent._

### Completion Notes
_To be filled in by dev agent._

### File List
_To be filled in by dev agent._

### Change Log
_To be filled in by dev agent._
