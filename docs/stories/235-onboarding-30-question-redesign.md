---
title: "Story 235 — Onboarding Form: Replace 20-Question Form with 30-Question Redesign"
status: in-progress
owners: [Dev 2]
sprint: platform-change
---

# Story 235 — Onboarding Form: Replace 20-Question Form with 30-Question Redesign

## Problem Statement

GitHub issue #235 (Dev 1, assigned to Dev 2 2026-09-22): *"Replace the current 20-question onboarding
form with the 30-question redesign from the product spec (Section 4.1) — new categories, new question
formats (MCQ + one-liner free-text + true/false), and several new personalization concepts not in the
current model."*

Source of truth for question content: `docs/proposals/source-specs/2026-09-hie-lecture-format-45min-and-onboarding-pack.pdf`,
Section 4.1 "User Onboarding Form (30 Questions)" — read in full for this story (30 questions: Q1-Q20
MCQ, Q21-Q25 one-liner free-text, Q26-Q30 true/false).

**Decisions locked by issue #235 (carried forward here):**
- **Replace, not additive** — the 30-question form fully replaces the 20-question one for new sign-ups.
  Not "20 old + 10 new."
- **No data migration needed** — the app has no real users yet, so there is no existing onboarding data
  to migrate or reconcile.
- **Build the form + storage for all 30 answers now.** Wire answers into personalization only where a
  consumer already exists today. Where the spec references a system that doesn't exist yet — Roast
  Ceiling enforcement, Bilingual Cognitive Bridge, Info-Warfare Shield, Comfortability Matrix (25
  personality modes), Life-Pathway engine, Penta-Intelligence baseline (IQ/EQ/SQ/CTQ/RRQ) scoring —
  **store the raw answers, do not build the consuming system.**

**What this story additionally had to resolve (not resolved by issue #235 itself):**

1. **The new spec's 30 questions do not map onto the existing 9-dimension Learner DNA model at all**
   (confirmed by reading `onboarding_questions.py`, `dna_fusion.py`, `service.py::process_onboarding`
   directly). Today, `process_onboarding()` synchronously computes 9 sub-dimension scores from the 20
   answers (`_compute_dimension_scores`), derives badge labels, generates `profile_text` via a
   GPT-4o-mini call, and upserts all of it into `learner_dna` — all in the onboarding request itself.
   The new spec's Q1-Q30 use a completely different taxonomy (Goal/Level/Language/Tone/Schooling/Inner
   Voice/Roast Ceiling/Focus/Vision/Penta-Intelligence letter-tags A-J) that issue #235 itself says
   "do not map cleanly" onto `pattern_recognition/logical_deduction/processing_speed/...`. Forcing a
   fake mapping would fabricate scores from answers never designed to produce them — exactly the kind
   of thing CLAUDE.md's "degrade-not-fabricate" principle exists to prevent.
2. **The existing `onboarding_responses` table cannot hold the new answer shapes.** It is part of
   `20260611000000_initial_schema.sql`, one of CLAUDE.md's two explicitly frozen migrations ("never
   modify applied migrations"). Its columns are `response_value integer NOT NULL` (no room for
   free-text) and `dimension_tag text CHECK (IN ('cognitive','emotional','self_direction'))` (no room
   for the new A-J taxonomy). A new table is required — not an oversight in issue #235, just left
   unspecified there.
3. **`OnboardingAnswer` / `OnboardingDiagnosticSubmission` are explicitly marked as a frozen contract**
   in `schemas.py` ("Frozen contract (Sprint 2, Story 3-18) — shape changes require 4-dev PR review").
   Changing them to carry 3 answer formats instead of 1 MCQ-only shape is exactly the kind of change
   that gate exists for.

## Design

### 1. Stop computing 9-dimension Learner DNA scores from onboarding answers

`process_onboarding()` for the new form does **not** call `_compute_dimension_scores`, does **not**
call the profile-text LLM, and does **not** write to `learner_dna` at all. Reasoning: `dna_fusion.py`
(the per-session EMA updater) already treats a missing prior value as neutral 50 on first fusion
(`_apply_ema`'s `old is None → _NEUTRAL`) — the 9-dimension system already has a fully-defined
cold-start path that doesn't depend on onboarding having seeded anything. The dimension/badge/
profile_text system keeps working exactly as before, driven entirely by post-session behavioral
signals (quiz accuracy, teach-back, events) — onboarding just stops being one of its two current
inputs. This is not a regression to that system; it removes a weak, unvalidated input (20 self-report
MCQ answers guessing at 9 behavioral traits) and leaves the stronger one (actual session behavior)
untouched.

`OnboardingResult`'s shape (`badge_labels: list[str]`, `profile_text: str`, `session_count: int`) is
**not changed** — all three fields are non-optional but not "non-empty": the new flow returns
`badge_labels=[]` and a static, non-LLM-generated `profile_text` (e.g. "Your personalised learning
profile builds as you complete lessons — check back after your first session."). Confirmed against
`DNAResultCard.tsx` directly: it already renders correctly with an empty `badgeLabels` array (the
badge-pill row is conditionally rendered) and any non-empty `profileText` string — **no frontend
result-screen code change is required**, only a test proving this explicitly (AC10).

### 2. New table for the 30 raw answers, not a reused/altered `onboarding_responses`

New migration creates `onboarding_answers_v2` (name chosen to make it unambiguous this is a distinct
table from the frozen `onboarding_responses`, not a versioned alias of it):

```sql
CREATE TABLE public.onboarding_answers_v2 (
  id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          uuid        NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  question_id      text        NOT NULL,
  format           text        NOT NULL CHECK (format IN ('mcq', 'one_liner', 'true_false')),
  selected_index   integer,                    -- set only when format = 'mcq'
  response_text    text,                       -- set for 'mcq' (option text) and 'one_liner'
  response_bool    boolean,                    -- set only when format = 'true_false'
  response_time_ms integer,
  created_at       timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT onboarding_answers_v2_user_question_unique UNIQUE (user_id, question_id)
);
```

This mirrors `onboarding_responses`' own row-per-question shape and its
`UNIQUE(user_id, question_id)` constraint (added by `20260703000000_onboarding_unique_constraint.sql`)
rather than inventing a new pattern. `response_text` doubles for MCQ's selected option text (matching
the old table's `selected_text` convention passed through today) and one-liner's free text — never
both on the same row, enforced by a model validator in the schema, not a DB CHECK (keeps the migration
simple; the API is the only writer).

### 3. Backend schema changes (`OnboardingAnswer` / `OnboardingDiagnosticSubmission`)

```python
class OnboardingAnswer(BaseModel):
    question_id: str
    format: Literal["mcq", "one_liner", "true_false"]
    selected_index: int | None = Field(default=None, ge=0)
    response_text: str | None = Field(default=None, max_length=1000)
    response_bool: bool | None = None
    response_time_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _validate_shape_matches_format(self) -> "OnboardingAnswer":
        if self.format == "mcq" and (self.selected_index is None or self.response_text is None):
            raise ValueError("mcq answers require selected_index and response_text")
        if self.format == "one_liner" and not (self.response_text or "").strip():
            raise ValueError("one_liner answers require non-blank response_text")
        if self.format == "true_false" and self.response_bool is None:
            raise ValueError("true_false answers require response_bool")
        return self


class OnboardingDiagnosticSubmission(BaseModel):
    responses: list[OnboardingAnswer] = Field(min_length=30, max_length=30)
```

`response_text` caps at 1000 chars (defensive, matching this codebase's established convention for
any free-text field that could later reach an LLM prompt, even though no LLM call reads it yet in this
story's scope — Q21-25 are explicitly "NLP-analysed for depth" as a *future* deferred capability).

**This is a frozen-contract change** (`schemas.py`'s own comment: "Frozen contract (Sprint 2, Story
3-18) — shape changes require 4-dev PR review") and is additionally within the Assessment API, one of
CLAUDE.md's 4 globally-frozen interface contracts ("Assessment API (OpenAPI auto-generated from
FastAPI)"). **This PR requires review from all 4 developers before merge**, not just Dev 3.

### 4. `onboarding_questions.py` — drop the 9-dimension map entirely

Replaces `QUESTION_SUBDIMENSION_MAP` / `ALL_NINE_DIMENSIONS` / `BADGE_THRESHOLD` /
`BADGE_THRESHOLDS` (all now dead for the onboarding path — `ALL_NINE_DIMENSIONS`/`BADGE_THRESHOLDS`
stay defined here since `dna_fusion.py`/`service.py` still import them for the *session-driven* path;
only the *onboarding-driven* scoring map is removed) with a minimal validation spec the backend
actually needs — the question bank's authoritative copy (text, options) lives in the frontend
(`questions.ts`), matching how the existing 20-question form already splits this (backend never had
question *text*, only IDs and a dimension tag):

```python
Q_SPEC: dict[str, Literal["mcq", "one_liner", "true_false"]] = {
    "q1": "mcq", "q2": "mcq", ..., "q20": "mcq",
    "q21": "one_liner", ..., "q25": "one_liner",
    "q26": "true_false", ..., "q30": "true_false",
}
MCQ_OPTION_COUNTS: dict[str, int] = {"q1": 5, "q2": 5, ..., "q6": 4, "q7": 4, ...}  # per PDF (some MCQs are 4-option, not 5 -- Q6-Q7 in the source PDF)
ALL_QUESTION_IDS: frozenset[str] = frozenset(Q_SPEC)
```

### 5. `process_onboarding()` rewrite

```
1. Validate: exactly 30 responses, question_ids == ALL_QUESTION_IDS exactly (no missing, no unknown,
   no duplicates), each answer's format matches Q_SPEC[question_id], each mcq selected_index <
   MCQ_OPTION_COUNTS[question_id]. Any violation -> 422 (a degrade-not-fabricate style validation
   guard, matching the pattern already used for LLM-response validation elsewhere in this codebase --
   here applied to client input instead).
2. Bulk-insert 30 rows into onboarding_answers_v2 (same duplicate -> 409 handling as today, matching
   UNIQUE(user_id, question_id)).
3. Return OnboardingResult(badge_labels=[], profile_text=_ONBOARDING_COMPLETE_MESSAGE, session_count
   = existing session_count if a learner_dna row already exists, else 0) -- session_count is read
   only, never written by this path anymore.
```

No LLM call, no `learner_dna` write, no rollback-on-LLM-failure complexity (that entire failure mode
is deleted along with the LLM call it existed to guard). Router-level idempotency
(`user:{id}:onboarding_done` Redis SET NX) and the reassessment bypass are **unchanged** — both are
format-agnostic.

**Dev Note, not fixed in this story:** re-reading `process_onboarding()`'s current (pre-this-story)
insert path confirms it uses a plain `.insert()`, not an upsert, for `onboarding_responses` — meaning
a reassessment resubmission would already hit the `UNIQUE(user_id, question_id)` constraint and be
misreported as a 409 "duplicate submission" today, independent of this story. This story's new table
carries the identical shape/behavior forward unchanged (not a regression introduced here). Flagging
for a `docs/DEFECT-REGISTER.md` entry (owner: whoever next touches reassessment) rather than silently
noting it in a comment with no ID, per CLAUDE.md binding rule 5.

### 6. Wire 4 fields into the tutor's existing learner-context prompt path

The **only** existing LLM-prompt consumer of Learner DNA in this codebase is `get_learner_context()` /
`_build_learner_prompt_text()` (Story F2-1, `assessment/service.py`), read by Dev 4's tutor state
machine for live Q&A. (Confirmed by repo-wide search: the content-generation pipeline, `graph.py`, has
**no** learner-context read of any kind today — issue #6 in the platform-changes-scope tracking doc,
"learning behaviour in system prompt," is genuinely unimplemented and out of scope for this story.)

Add 4 new optional fields to `LearnerContextDNA` — `stated_goal: str | None`, `current_level: str |
None`, `preferred_language: str | None`, `preferred_tone: str | None` — populated from Q1
(`[A · Goal]`), Q2 (`[B · Level]`), Q3 (`[C · Language]`), Q4 (`[C · Tone]`) via a new
`_read_onboarding_headline_answers(user_id)` helper reading `onboarding_answers_v2` directly (not
`learner_dna`, since these now live only in the raw-answers table). `_build_learner_prompt_text` gains
one new descriptive line when any of the 4 are present:

```
- Stated goal: {stated_goal} | Level: {current_level} | Language preference: {preferred_language} | Tone preference: {preferred_tone}
```

This is also an Assessment-API (frozen contract #3) change — same 4-dev PR review requirement as
section 3, and can land in the **same** PR (same review, same reviewers).

### 7. Frontend

- `apps/web/src/components/onboarding/questions.ts` — full rewrite: 30 `Question` entries, each
  tagged `format: 'mcq' | 'one_liner' | 'true_false'`. MCQ entries keep `options: string[]` (verbatim
  from the PDF, including the 2 four-option questions Q6/Q7 — not all MCQs in this form are 5-option
  like the old form's were). One-liner entries carry a `placeholder` string instead of `options`.
  True/false entries carry no options (rendered as fixed True/False buttons).
- `QuestionCard.tsx` — branches on `question.format`: `mcq` keeps today's `useRovingRadioGroup`
  radio-button rendering unchanged; new `format === 'true_false'` branch reuses the **same**
  `useRovingRadioGroup` hook with `optionCount: 2` (True/False as two roving-focus buttons — no new
  a11y pattern invented, matches CLAUDE.md's spirit of reusing accepted patterns rather than
  duplicating); new `format === 'one_liner'` branch renders a `<textarea>` (max 1000 chars, matching
  the backend cap, live character counter, no `useRovingRadioGroup` involvement).
- `OnboardingFlow.tsx`:
  - `answers` state becomes `Record<string, OnboardingAnswerValue>` where
    `OnboardingAnswerValue = { format: 'mcq'; index: number } | { format: 'one_liner'; text: string }
    | { format: 'true_false'; value: boolean }` — not a bare `number` anymore.
  - `canProceed`: `mcq` unchanged (`index !== undefined`); `one_liner` requires
    `text.trim().length > 0` (blank/whitespace-only never counts as answered, consistent with the
    backend validator); `true_false` requires the value to be explicitly set (`value !== undefined`,
    since `false` is a valid, real answer and must not be confused with "unanswered").
  - `handleSubmit()` maps each question + its stored answer into the new 3-shape
    `OnboardingAnswer` wire format.
  - `STORAGE_KEY` bumped from `onboarding_progress_v1` to `onboarding_progress_v2` — a stale v1 blob
    from the old 20-question shape must never be resumed into the new 30-question flow (the index
    positions and answer shapes are incompatible). Old key is not read or migrated; a returning user
    mid-way through the old form on redeploy day simply restarts (acceptable: "no real users yet" per
    issue #235's own locked decision).

## Acceptance Criteria

- **AC1** — New migration `supabase/migrations/<ts>_onboarding_answers_v2.sql` creates
  `onboarding_answers_v2` exactly as specified in Design §2, with `UNIQUE(user_id, question_id)`.
  `onboarding_responses` and its own migrations are untouched (frozen).
- **AC2** — `onboarding_questions.py`: `QUESTION_SUBDIMENSION_MAP` and its onboarding-scoring usage
  removed; new `Q_SPEC`/`MCQ_OPTION_COUNTS`/`ALL_QUESTION_IDS` added, matching the PDF's 30 questions
  exactly (20 MCQ across Q1-Q20 with correct per-question option counts including the two 4-option
  questions Q6/Q7, 5 one-liner Q21-Q25, 5 true/false Q26-Q30). `ALL_NINE_DIMENSIONS`/
  `BADGE_THRESHOLDS` remain (still used by the session-driven path).
- **AC3** — `OnboardingAnswer`/`OnboardingDiagnosticSubmission` updated to the 3-format shape in
  Design §3, with the format-matching `model_validator`. **AC3 requires 4-developer PR review**
  (frozen Assessment-API contract) — this story's PR is not mergeable on Dev 3 approval alone.
- **AC4** — `process_onboarding()` rewritten per Design §5: validates all 30 question_ids
  present/known/non-duplicate and format-matched (422 on violation), bulk-inserts into
  `onboarding_answers_v2`, performs **no** dimension scoring, **no** LLM call, **no** `learner_dna`
  write. Returns `OnboardingResult(badge_labels=[], profile_text=<static message>, session_count=
  <read-only, existing or 0>)`.
- **AC5** — `POST /onboarding/submit` router: idempotency (Redis SET NX) and reassessment-bypass logic
  unchanged; a fresh `test_onboarding_endpoint.py` test proves 30 valid answers succeed end-to-end and
  a 409 still fires on a second submission attempt.
- **AC6** — `LearnerContextDNA` gains `stated_goal`/`current_level`/`preferred_language`/
  `preferred_tone` (all `str | None`), populated from Q1-Q4 via a new read of
  `onboarding_answers_v2`; `_build_learner_prompt_text` includes them in its output line per Design
  §6 when present, and omits the line entirely when all 4 are `None` (e.g. user hasn't onboarded via
  the new form, or the row doesn't exist). **Also requires 4-developer PR review** (same frozen
  contract as AC3 — can be the same review round).
- **AC7** — `questions.ts` rewritten: all 30 questions present with exact PDF text/options/format,
  verified 1:1 against the source PDF (not paraphrased) in the PR description.
- **AC8** — `QuestionCard.tsx` renders all 3 formats correctly: MCQ (unchanged visual/a11y), True/False
  (2-option roving group, reusing `useRovingRadioGroup`), One-Liner (textarea, 1000-char cap with a
  visible counter, non-blank required to enable Next/Complete).
- **AC9** — `OnboardingFlow.tsx`: `answers` state and `handleSubmit()` updated per Design §7;
  `STORAGE_KEY` bumped to `onboarding_progress_v2`; `canProceed` correctly distinguishes "unanswered"
  from "answered false" / "answered index 0" for every format.
- **AC10** — Explicit test (`DNAResultCard.test.tsx` or `OnboardingFlow.test.tsx`) proving the result
  screen renders correctly with `badge_labels: []` and a non-empty generic `profile_text` — i.e. this
  story does NOT silently regress the post-onboarding screen into an error or blank state.
- **AC11** — `dna_fusion.py`, `dna_profile.py`, and the session-driven 9-dimension EMA/badge/
  profile_text pipeline are **untouched** by this story — existing tests for those modules
  (`test_dna_growth.py`/equivalents) pass unmodified, proving the session-driven path still works
  identically with no onboarding-time seed.
- **AC12** — Existing guard/behavior tests referencing onboarding are updated, not deleted, for the
  new 30-question/3-format shape and pass: `test_onboarding_endpoint.py`,
  `test_onboarding_question_ordering.py`, `test_onboarding_content.py`,
  `test_onboarding_llm_failure.py` (re-scoped: no LLM call exists in this path anymore, so this file's
  purpose changes to proving the *removal* is intentional and doesn't crash, not proving fallback
  behavior on LLM failure), `test_learner_dna_real_onboarding.py`, `test_reassessment_blend.py`,
  `test_reassessment_flag.py`, `test_f2_1_learner_context.py` (AC6's new fields),
  `test_t28_dna_display_contract_dev2.py`, `test_openapi_spec.py`, `test_assessment_stub_contracts.py`.
  Named explicitly per CLAUDE.md's rule that a story touching a guarded module must list that
  module's guard tests as an AC, not discover them during review.
- **AC13** — `tsc --noEmit` and targeted `eslint` clean on all touched frontend files; `ruff`/`mypy`
  (or this repo's equivalent gate) clean on all touched backend files; full frontend **and** backend
  test suites green, zero regressions outside the files this story intentionally changes.

## Scale & Load

1. **Unit of work & range.** One onboarding submission = exactly 30 answers from exactly one user,
   inserted once (enforced by `UNIQUE(user_id, question_id)` + the Redis idempotency lock). Fixed size
   regardless of input — there is no variable-length dimension to this unit of work (unlike, say, a
   chapter's section count). No range to characterize beyond "always exactly 30."
2. **Fixed budgets vs. variable input.** `response_text` (one-liner answers) is capped at 1000 chars
   by the Pydantic `Field(max_length=1000)` — a client sending more gets an explicit 422, never a
   silent truncation. There is no other variable-sized input in this flow.
3. **Scope of every limit.** The `UNIQUE(user_id, question_id)` constraint and the Redis
   `user:{id}:onboarding_done` lock are both per-user, matching the existing (unchanged) pattern. No
   new per-instance or per-deployment limit is introduced.
4. **Unbounded reads/writes.** The bulk-insert is always exactly 30 rows (bounded by
   `Field(min_length=30, max_length=30)` on the submission schema itself, enforced before any DB call).
   The new `_read_onboarding_headline_answers` read (AC6) is `.eq("user_id", ...).in_("question_id",
   ["q1","q2","q3","q4"]).limit(4)` — bounded by construction, never more than 4 rows regardless of
   how many total answers a user has on file.
5. **Inherited caps re-derived.** None inherited — this is new storage, not a modification of an
   existing capacity assumption. The old `onboarding_responses` table's 20-row-per-user shape is not
   reused or extended; the new table's 30-row-per-user shape is sized directly from this story's own
   fixed input (Q1-Q30), not copied from an unrelated prior constant.
6. **Concurrency safety of check-then-act sequences.** The existing Redis `SET NX` on
   `user:{id}:onboarding_done` (unchanged by this story) already closes the TOCTOU window between
   "check if already onboarded" and "write the result" for the common case. The bulk-insert's
   `UNIQUE(user_id, question_id)` constraint is the DB-layer backstop for the same race (matches the
   existing table's own belt-and-suspenders design, carried forward unchanged). The one **known,
   pre-existing, not-introduced-by-this-story** gap: a reassessment resubmission uses plain `.insert()`
   rather than upsert, so two answers for the same `question_id` cannot coexist for one user without
   hitting the unique constraint — see the Dev Note under Design §5. Not a new concurrency risk from
   this story; carried forward identically from the current 20-question implementation.

## Dev Notes

- `onboarding_questions.py:1-65` — read in full; `QUESTION_SUBDIMENSION_MAP`/`ALL_NINE_DIMENSIONS`/
  `BADGE_THRESHOLD`/`BADGE_THRESHOLDS` all confirmed still imported by `dna_fusion.py`/`service.py`'s
  session-driven path — do not delete the dimension/badge constants themselves, only their
  onboarding-time *usage*.
- `service.py:1622-1838` (`_compute_badge_labels`, `_fetch_existing_dna`, `process_onboarding`) — read
  in full; the LLM-failure rollback logic (lines ~1741-1784) is deleted in its entirety along with the
  LLM call it exists to guard, not left dead in place.
- `service.py:2152-2320` (`_build_learner_prompt_text`, `get_learner_context`) — the **only** existing
  LLM-prompt consumer of Learner DNA data in the repo; confirmed via repo-wide search that
  `apps/api/app/modules/content/pipeline/graph.py` has zero learner-context reads today (issue #6 from
  the wider platform-changes tracking doc is genuinely unimplemented, not something this story
  touches).
- `DNAResultCard.tsx` — read in full; already renders correctly with empty `badge_labels` (conditional
  block) and any non-empty `profile_text` string. No component change required for AC10, only a test.
- `useRovingRadioGroup.ts` — read in full; generic over `optionCount`, reused as-is for the new
  True/False rendering (`optionCount: 2`) rather than writing a second roving-focus implementation.
- Question text/options/formats for all 30 questions sourced verbatim from
  `docs/proposals/source-specs/2026-09-hie-lecture-format-45min-and-onboarding-pack.pdf`, Section 4.1
  (pages 3-6 of the PDF) — read directly, not summarized from a secondary source.

## File List

- `supabase/migrations/<new-timestamp>_onboarding_answers_v2.sql` (new)
- `apps/api/app/modules/assessment/onboarding_questions.py`
- `apps/api/app/modules/assessment/schemas.py`
- `apps/api/app/modules/assessment/service.py`
- `apps/api/app/modules/assessment/router.py` (verify only — expected no logic change)
- `apps/api/tests/test_onboarding_endpoint.py`
- `apps/api/tests/unit/test_onboarding_question_ordering.py`
- `apps/api/tests/test_onboarding_content.py`
- `apps/api/tests/test_onboarding_llm_failure.py`
- `apps/api/tests/test_learner_dna_real_onboarding.py`
- `apps/api/tests/unit/test_reassessment_blend.py`
- `apps/api/tests/test_reassessment_flag.py`
- `apps/api/tests/unit/test_f2_1_learner_context.py`
- `apps/api/tests/test_t28_dna_display_contract_dev2.py`
- `apps/api/tests/test_openapi_spec.py`
- `apps/api/tests/test_assessment_stub_contracts.py`
- `apps/web/src/components/onboarding/questions.ts`
- `apps/web/src/components/onboarding/QuestionCard.tsx`
- `apps/web/src/components/onboarding/OnboardingFlow.tsx`
- `apps/web/src/__tests__/components/onboarding/OnboardingFlow.test.tsx` (existing, per earlier session context)
- New `apps/web/src/__tests__/components/onboarding/QuestionCard.test.tsx` (per-format rendering)
- `apps/web/src/components/onboarding/DNAResultCard.tsx` (verify only, AC10)

## Dev Agent Record

### Completion Notes

_(filled in after implementation)_

### File List

_(see File List above — updated after implementation if scope shifts)_

## References

- GitHub issue #235: "Onboarding form: replace 20-question form with 30-question redesign"
  (`developer-cybersmith/transformED`)
- `docs/proposals/source-specs/2026-09-hie-lecture-format-45min-and-onboarding-pack.pdf`, Section 4.1
- `docs/proposals/2026-09-19-platform-changes-scope.md` — "Change 1 — Multi-stage personalization
  forms" (Draft Story context, per-user form is this story; book/chapter forms are issues #231/#230,
  owned by other devs)
- [Source: apps/api/app/modules/assessment/service.py:1662-1838] `process_onboarding` (pre-story)
- [Source: apps/api/app/modules/assessment/dna_fusion.py:66-73] `_apply_ema`'s `old is None -> neutral
  50` cold-start path, the reason no onboarding-time seed is required
- [Source: apps/api/app/modules/assessment/schemas.py:187-201] frozen-contract comment on
  `OnboardingAnswer`/`OnboardingDiagnosticSubmission`
- [Source: supabase/migrations/20260611000000_initial_schema.sql:224-256] frozen `learner_dna`/
  `onboarding_responses` table definitions
