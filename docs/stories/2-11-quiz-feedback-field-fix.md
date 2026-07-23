---
baseline_commit: e44518facd64cb17065f2175946866998c65865d
---

# Story 2.11: Fix Quiz Feedback Field-Name Mismatch (Dev 2 counterpart to Story 3-28)

Status: review

## Story

As a student who just answered one or more quiz questions,
I want the per-question feedback and score summary to actually display,
so that the quiz result screen isn't silently blank where "Correct."/"Nice work." style feedback should be.

**Source:** discovered while scoping Dev 3's **Story 3-28** ("Tier-Aware Quiz Question Count" — `docs/stories/3-28-tier-aware-quiz-count.md`, merged to `main`), which changed `quiz_generator_node` to produce 1–5 questions per segment (tier-dependent) instead of always exactly 1, and changed the question ID format from `quiz_{segment_id}` to `quiz_{segment_id}_{index}`. Investigating `QuizOverlay.tsx` to see what needed updating for the count change surfaced something more important: **`QuizOverlay.tsx` already correctly handles a variable number of questions** (iterates the full array, tracks `questionIndex`, shows "X / N" progress, collects all answers and submits once at the end) — no functional change is needed for Story 3-28's core behavior at all. But the investigation surfaced a **real, pre-existing, currently-shipping bug**, unrelated to the question-count change: the per-question feedback the frontend renders after submission uses field names that don't match what the backend actually returns, so every quiz's feedback/score summary currently renders blank or `undefined` values.

**Confirmed by reading the actual backend code, not assumed:** `apps/api/app/modules/assessment/service.py`'s `grade_quiz()` (`service.py:341-360`) builds each feedback entry as:
```python
{
    "question_id": g["question"]["question_id"],
    "question": g["question"]["question"],
    "is_correct": g["is_correct"],
    "correct_index": g["question"]["correct_index"],
    "correct_option": g["question"]["options"][g["question"]["correct_index"]] if ... else None,
    "selected_option": g["question"]["options"][g["selected_index"]] if ... else None,
    "explanation": g["question"]["explanation"],
}
```
`QuizResult.feedback` is typed as `list[dict[str, Any]]` in the Pydantic schema (`schemas.py`) — not a strict named model — so there's no compile-time contract enforcing the frontend gets this right; the real key names only exist in `service.py`'s dict-literal construction above.

**What the frontend currently has instead** (`apps/web/src/lib/assessment.ts`):
```ts
export interface QuizFeedbackItem {
  question_id: string;
  correct: boolean;   // WRONG — backend sends is_correct
  message: string;    // WRONG — backend sends explanation (no field named "message" exists)
}
```
And `QuizOverlay.tsx` renders `f.correct ? ... : ...` and `{f.message}` (lines 167-168) — both read `undefined` from every real API response today. **This is a live, currently-shipping bug**, not something Story 3-28 introduced.

**Why the existing test suite never caught this:** `QuizOverlay.test.tsx`'s own `RESULT` fixture (line 38-48) uses the same wrong shape (`{ question_id, correct: true, message: 'Nice work.' }`) as the component — the test and the component agree with each other, but neither matches the real backend. This is exactly the kind of "story's own assumption, unverified against the real backend, gets faithfully reproduced in both the code and its test" gap this session has caught twice before (Story 1-7's wire-status-value correction, Story 2-10's missing 'Exceptional' DNA label) — verify against the actual shipped Python, not against what the frontend already assumes.

**A second, smaller, related type-duplication issue found in passing:** `apps/web/src/types/assessment.ts` has its own separate `QuizAnswer`/`QuizSubmission`/`QuizResult` type declarations (used only by `apps/web/src/__tests__/types/assessment.test.ts`, never imported by any real component/service) that also has an inaccurate `feedback: Array<{ [key: string]: unknown }>` shape. It's dead code at runtime (only `lib/assessment.ts`'s versions are actually imported by `QuizOverlay.tsx`), but leaving an incorrect "reference" type sitting in the codebase, backed by its own passing test, is exactly the kind of drift that caused this bug in the first place.

## Acceptance Criteria

1. **AC-1 — `QuizFeedbackItem` matches the real backend shape.** `apps/web/src/lib/assessment.ts`'s `QuizFeedbackItem` gains the real fields: `is_correct: boolean` (replacing `correct`), `explanation: string` (replacing `message`), plus `question: string`, `correct_index: number`, `correct_option: string | null`, `selected_option: string | null` — matching `service.py`'s dict exactly.
2. **AC-2 — `QuizOverlay.tsx` renders the real fields.** The per-question feedback item (currently `f.correct ? ... : ...` / `{f.message}`) uses `f.is_correct` / `f.explanation` instead. Visual treatment (color, "Correct!"/"Not quite." labels) stays the same — this is a field-name fix, not a redesign.
3. **AC-3 — no change needed (confirmed, not "fixed") for variable question count.** `QuizOverlay.tsx` already correctly handles 1–5 questions per segment: iterates the full `questions` array, shows "X / N" progress only when `questions.length > 1`, collects one answer per question, submits all of them together on the last question. Add a test proving this explicitly for a segment with more than 2 questions (existing tests only ever use exactly 1 or 2) — this is confirmation/regression coverage, not new behavior.
4. **AC-4 — `question_id` format is opaque to the frontend, already safe.** The backend's ID format changed from `quiz_{segment_id}` to `quiz_{segment_id}_{index}` (confirmed in `apps/api/app/modules/content/pipeline/graph.py`'s `quiz_generator_node`). Nothing in `QuizOverlay.tsx`/`lib/assessment.ts` parses or assumes structure within a `question_id` — it's always treated as an opaque string round-tripped from `QuizQuestion.question_id` to `QuizAnswer.question_id`. Confirm this via a test using a realistic `_0`/`_1`-suffixed id, not just the existing `q_1`/`q_2` placeholder ids.
5. **AC-5 — fix `types/assessment.ts`'s duplicate `QuizResult.feedback` typing too.** Even though unused at runtime, correct its shape to match reality (or reference `lib/assessment.ts`'s `QuizFeedbackItem` directly) so it stops being a passing-but-wrong "reference contract" for the next person who looks at it.
6. **AC-6 — no regression.** All existing `QuizOverlay.tsx` behavior (no-timer requirement, disabled-until-selected, per-question explanation display, "Continue exits even on API failure," multi-question advance/reset, full answer-array submission with correct session/lesson/segment ids) continues to work exactly as today.
7. **AC-7 — tests.** Cover: feedback renders using the real field names (regression test proving the bug is fixed — assert the correct/incorrect styling and explanation text actually appear, not `undefined`); a 3+ question segment renders and submits correctly; a realistic `_0`/`_1`-suffixed question_id round-trips correctly through selection → submission.

## Tasks / Subtasks

- [x] Task 1 (AC: 1): `apps/web/src/lib/assessment.ts` — updated `QuizFeedbackItem` to the real backend shape (`is_correct`, `explanation`, `question`, `correct_index`, `correct_option`, `selected_option`).
  - [x] 1.1 Confirmed at the component level in Task 2 (no separate type-level test needed).
  - [x] 1.2 GREEN.
- [x] Task 2 (AC: 2, 6): `apps/web/src/components/player/QuizOverlay.tsx` — renders `f.is_correct`/`f.explanation` instead of `f.correct`/`f.message`. Also removed the stale `[DEV1-SPRINT2-PENDING]` comment block.
  - [x] 2.1 RED: updated `QuizOverlay.test.tsx`'s `RESULT` fixture to the real shape, then discovered the existing suite never actually asserted on the feedback list's rendered content at all — added a new dedicated test to get genuine RED, confirmed it failed against the unfixed component before implementing.
  - [x] 2.2 GREEN.
- [x] Task 3 (AC: 3): Added a 3-question test (`THREE_QUESTIONS` fixture) — passed on first run with zero code changes, confirming the story's premise that count-handling already worked.
- [x] Task 4 (AC: 4): Same test uses realistic `quiz_section_2_6_0`/`_1`/`_2`-suffixed `question_id` values instead of placeholder `q_1`/`q_2`, confirming the id round-trips unparsed through selection → submission.
- [x] Task 5 (AC: 5): `apps/web/src/types/assessment.ts` — `QuizResult.feedback` now reuses `lib/assessment.ts`'s `QuizFeedbackItem[]` instead of a third, independently-drifting `Array<{[key:string]: unknown}>` declaration. Updated the one `assessment.test.ts` fixture that used yet another (partially wrong) ad-hoc shape.
- [x] Task 6 (AC: 7): Full `apps/web` suite green (400/400, 46 files); `tsc --noEmit` clean; `eslint` clean on every touched file.
- [x] Task 7: Tracker update — `docs/dev2-sprint-tracker.md` gained a dated cross-team note.

## Dev Notes

### Current state of every file this story touches (read directly, not assumed)

- **`apps/web/src/components/player/QuizOverlay.tsx`** (full file, 202 lines): already imports `submitQuiz`, `QuizAnswer`, `QuizResult` from `@/lib/assessment` (the correctly-used module) — good, this story doesn't need to change *which* module it imports from. `handleSubmit` (lines 49-76) collects one `QuizAnswer` per question into a `useRef` array, and on the last question calls `submitQuiz({session_id, lesson_id, segment_id, answers})` — this whole flow is already count-agnostic. The bug is purely in the JSX at lines 166-169:
  ```tsx
  {result.feedback.map((f) => (
    <p key={f.question_id} className={f.correct ? 'text-emerald-400' : 'text-red-400'}>
      {f.message}
    </p>
  ))}
  ```
  Carries a stale `[DEV1-SPRINT2-PENDING]` comment block (lines 12-15) referencing "Story S2-11, not yet built" — that story number collides with *this* story's own number by coincidence (this story is also informally "2-11" in this session's local numbering, unrelated to Dev 1's original S2-11/package_builder reference) — remove the stale comment regardless, the dependency it names has long since shipped.
- **`apps/web/src/lib/assessment.ts`** (full file, 75 lines): `QuizFeedbackItem` (lines 19-23) is the type to fix. `submitQuiz()` (line 34-37) itself needs no change — it already just POSTs the payload and returns whatever the backend sends, untyped-checked at the boundary (same trust-the-cast pattern used throughout this codebase's service layer).
- **`apps/api/app/modules/assessment/service.py`** (backend, read via `git show main:...`, not present on this branch's own history — this story does NOT touch this file, just cites it as the source of truth): `grade_quiz()`'s feedback dict construction at lines 341-360, quoted in full above in this story's Source section.
- **`apps/api/app/modules/assessment/schemas.py`** (backend, same caveat): `QuizResult.feedback: list[dict[str, Any]]` — confirms there's no backend-side Pydantic model enforcing the dict shape either; the real contract only exists as the dict literal in `service.py`.
- **`apps/web/src/__tests__/components/player/QuizOverlay.test.tsx`** (full file, 146 lines): `RESULT` fixture (lines 38-48) currently uses the wrong shape (`{question_id, correct, message}`) — matches the bug exactly, needs updating to the real shape as part of Task 2's RED step. All 9 existing tests are expected to keep passing once fixed, except wherever they touch `feedback` display specifically.
- **`apps/web/src/types/assessment.ts`**: `QuizAnswer`/`QuizSubmission`/`QuizResult` (lines 6-35) are a second, parallel, currently-unused-at-runtime set of type declarations for the identical API concept as `lib/assessment.ts`'s versions — confirmed via grep that nothing outside this file and its own test imports these three names from `@/types/assessment`. `QuizResult.feedback: Array<{ [key: string]: unknown }>` here is even vaguer than the wrong-but-specific shape in `lib/assessment.ts`.
- **`apps/web/src/__tests__/types/assessment.test.ts`**: has its own `QuizResult`/`QuizAnswer`/`QuizSubmission` conformance tests (around lines 55-70, 174+) — these test `types/assessment.ts`'s declarations, not `lib/assessment.ts`'s; update whichever specific assertions reference `feedback`'s shape if Task 5 changes it.

### What the real backend contract actually is (verified against `main`, not assumed)

```python
# apps/api/app/modules/content/pipeline/graph.py — quiz_generator_node
"question_id": f"quiz_{section_id}_{len(valid_results)}"   # index-suffixed, was quiz_{segment_id} before Story 3-28

# apps/api/app/modules/assessment/service.py — grade_quiz()'s feedback dict, per question:
{
    "question_id": str,
    "question": str,
    "is_correct": bool,
    "correct_index": int,
    "correct_option": str | None,   # None only if correct_index is somehow out of range (defensive)
    "selected_option": str | None,  # None only if the student's response_index is somehow out of range
    "explanation": str,
}
```

### What NOT to do

- Do NOT change `QuizOverlay.tsx`'s submission logic, question iteration, or progress-indicator logic — all of that already correctly handles a variable question count; this story is a field-name fix plus confirmation testing, not a redesign.
- Do NOT touch any backend file — this is a pure frontend fix; the backend contract is already correct and shipped.
- Do NOT remove `types/assessment.ts`'s `QuizAnswer`/`QuizSubmission`/`QuizResult` declarations wholesale as a "cleanup" — that's a bigger, unrequested refactor (would mean rewiring `assessment.test.ts` significantly). Just correct the one field this story is about (`feedback`'s shape) to stop it being wrong.
- Do NOT build Story 3-28's `QuizSubmission.answers` min/max validation UI-side (backend already enforces `min_length=1, max_length=50` — well outside any realistic 1-5 question range; not this story's concern).
- Do NOT change `packages/shared/types/lesson.ts`'s `QuizQuestion` type — it's unaffected (still just `{question_id, type, question, options, correct_index, explanation, difficulty}`, the same before and after Story 3-28; only the *value* of `question_id` and the *count* of questions per segment changed, not the shape).

### Project Structure Notes

Touches only: `apps/web/src/lib/assessment.ts`, `apps/web/src/components/player/QuizOverlay.tsx`, `apps/web/src/types/assessment.ts`, and their test files. No backend touches, no shared-contract changes, no new dependencies.

### Testing standards

Vitest + `@testing-library/react` + `@testing-library/user-event`, matching `QuizOverlay.test.tsx`'s existing pattern exactly (`vi.hoisted`/`vi.mock` for `@/lib/assessment`, real `usePlayerStore` state via `loadLesson`/`setState`, `userEvent.click` for interactions). Do not introduce a new mocking approach.

### References

- [Source: docs/stories/3-28-tier-aware-quiz-count.md] — the backend story this responds to (merged, `main`)
- [Source: apps/api/app/modules/assessment/service.py::grade_quiz, apps/api/app/modules/assessment/schemas.py::QuizResult, apps/api/app/modules/content/pipeline/graph.py::quiz_generator_node] — read via `git show main:...` this session, current state quoted above
- [Source: apps/web/src/components/player/QuizOverlay.tsx, apps/web/src/lib/assessment.ts, apps/web/src/types/assessment.ts, apps/web/src/__tests__/components/player/QuizOverlay.test.tsx, apps/web/src/__tests__/types/assessment.test.ts] — all read in full this session, current state documented above

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-23 | Story created — Dev 2 counterpart to Dev 3's Story 3-28. Investigation found the count-handling already works; the real gap is a pre-existing feedback field-name mismatch between `QuizOverlay.tsx`/`lib/assessment.ts` and the actual backend contract, verified directly against `service.py`. Branch `sprint2/s2-11-variable-quiz-count` off `sprint2-master`. | Dev 2 |

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (claude-sonnet-5)

### Debug Log References

- `npx vitest run src/__tests__/components/player/QuizOverlay.test.tsx` — after updating `RESULT`'s fixture shape alone, all 9 existing tests still passed unmodified — confirmed by inspection that none of them actually asserted on `result.feedback`'s rendered text. Added a new dedicated test (`'shows the score summary feedback using the real backend field names...'`) to get genuine RED: 1/9 failed as expected (`'Nice work.'` not found, since `f.explanation` was `undefined` against the unfixed `f.message` render). GREEN after implementation: 9/9 passed, then 10/10 after Task 3/4's test was added.
- `npx tsc --noEmit -p tsconfig.json` after Task 5 — caught the `assessment.test.ts` fixture that used yet a third ad-hoc feedback shape (`{question_id, correct, explanation}`, mixing old and new field names); fixed to the full real shape.
- Full suite: `npx vitest run` — 400/400 passing across 46 files.
- `npx tsc --noEmit -p tsconfig.json` — clean.
- `npx eslint` on every touched file — 0 errors, 0 warnings.
- No HALT conditions hit — no new dependencies, no ambiguous requirements, no 3-consecutive-failure loop. Confirmed (not fixed) that AC-3/AC-4 needed zero code changes: the 3-question/realistic-id test passed on its first run.

### Completion Notes List

- `lib/assessment.ts`: `QuizFeedbackItem` corrected to the real backend shape — `is_correct`/`explanation`/`question`/`correct_index`/`correct_option`/`selected_option`, matching `service.py::grade_quiz`'s dict literal exactly.
- `QuizOverlay.tsx`: score-summary feedback now renders `f.is_correct`/`f.explanation`. This was a live bug — every quiz submission's feedback list has been rendering blank/`undefined` text in production, unrelated to Story 3-28's question-count change. Removed the stale `[DEV1-SPRINT2-PENDING]` comment (the dependency it named shipped long ago).
- Confirmed, not fixed: `QuizOverlay.tsx`'s question iteration, progress indicator ("X / N", shown only when `questions.length > 1`), and full-answer-array submission logic already correctly handle 1–5 questions per segment with no changes needed. `question_id` is treated as a fully opaque string throughout — the backend's format change (`quiz_{segment_id}` → `quiz_{segment_id}_{index}`) required zero frontend changes.
- `types/assessment.ts`: `QuizResult.feedback` now imports and reuses `lib/assessment.ts`'s `QuizFeedbackItem[]` instead of maintaining a third, independently-wrong shape. This type module's `QuizResult`/`QuizAnswer`/`QuizSubmission` remain otherwise unused at runtime (only their own test imports them) — not restructured further, per this story's own scope limits.
- No backend changes, no changes to `packages/shared/types/lesson.ts`'s `QuizQuestion` type, no changes to `QuizOverlay.tsx`'s submission/iteration logic beyond the field-name fix.

### File List

**Files MODIFIED:**
- `apps/web/src/lib/assessment.ts` — `QuizFeedbackItem` corrected to the real backend shape
- `apps/web/src/components/player/QuizOverlay.tsx` — feedback render uses `is_correct`/`explanation`; stale comment removed
- `apps/web/src/types/assessment.ts` — `QuizResult.feedback` now reuses `lib/assessment.ts`'s `QuizFeedbackItem[]`
- `apps/web/src/__tests__/components/player/QuizOverlay.test.tsx` — `RESULT` fixture corrected; 1 new regression test (feedback field names); 1 new test (3-question segment + realistic ids)
- `apps/web/src/__tests__/types/assessment.test.ts` — 1 fixture corrected to the full real feedback shape
- `docs/dev2-sprint-tracker.md` — dated cross-team note added

### Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-23 | Story created — Dev 2 counterpart to Dev 3's Story 3-28. Investigation found the count-handling already works; the real gap is a pre-existing feedback field-name mismatch between `QuizOverlay.tsx`/`lib/assessment.ts` and the actual backend contract, verified directly against `service.py`. Branch `sprint2/s2-11-variable-quiz-count` off `sprint2-master`. | Dev 2 |
| 2026-07-23 | All 7 tasks implemented in strict RED→GREEN order. 2 new tests, 2 fixtures corrected; full `apps/web` suite 400/400 passing (46 files); `tsc --noEmit` clean; `eslint` clean. Tracker updated. Story marked `review`. | Dev 2 |
