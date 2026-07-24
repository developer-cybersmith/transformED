---
baseline_commit: f482b909d808cf6ec7cf225652fe1cd93bfb1e5a
---

# Story 2.13: Fix Assessment Library Test Gaps & Type Drift (from Sprint 2 test audit)

Status: review

## Story

As the frontend team,
I want `lib/assessment.ts`'s real `submitQuiz`/`submitTeachBack` implementations to actually be exercised by tests, and the drifted duplicate `TeachbackResult` type in `types/assessment.ts` fixed,
so that a typo'd endpoint, a dropped payload field, or a stale response-shape assumption in the assessment API layer would fail a test instead of shipping silently — the exact class of bug Story 2-11 already found and fixed once this sprint (on the Quiz side), left unaddressed on the TeachBack side.

**Source:** the Sprint 2 unit test audit (2026-07-23, 4 parallel AC-to-test-trace reviews across all 12 Sprint 2 stories) surfaced 2 High-severity findings, both in this file pair. This story fixes both, plus one additional, more severe variant of the second finding discovered while verifying the fix against the real backend (per this project's established "verify against the real shipped code, not the story doc" discipline).

### Finding 1 — `submitQuiz`/`submitTeachBack` never run their real code in any test

Confirmed: `QuizOverlay.test.tsx` and `TeachBackModal.test.tsx` both do `vi.mock('@/lib/assessment', () => ({ submitQuiz: submitQuizMock }))` / `({ submitTeachBack: submitTeachBackMock })` — the whole module is replaced, so the real function bodies (`apps/web/src/lib/assessment.ts:42-45, 70-73` — endpoint path, payload passthrough via `api.post`) never execute anywhere. `getSessionReport` in the same file is the existing model to match: `apps/web/src/__tests__/lib/assessment.test.ts` mocks only `api.get` and imports the real function, asserting the real URL is hit.

### Finding 2 — `types/assessment.ts`'s `TeachbackResult` is a dead, drifted duplicate with a self-referential test

Confirmed via grep: `TeachbackResult` (types/assessment.ts:50-62) is imported nowhere outside this file and its own test (`__tests__/types/assessment.test.ts:162`). Its `rubric_scores: {accuracy?, depth?, clarity?, relevance?, [key: string]: number | undefined}` doesn't match the real, actually-used `RubricScores` in `lib/assessment.ts` (`{accuracy, completeness, clarity}` — no `depth`/`relevance`, no index signature). The test constructs a value from the type's own (wrong) shape and asserts it against itself — it would keep passing regardless of whether `depth`/`relevance` are real fields. This is the identical bug class Story 2-11 found and fixed for `QuizResult.feedback` (which now reuses `lib/assessment.ts`'s `QuizFeedbackItem` instead of re-declaring a third copy) — the TeachBack side was simply missed at the time.

### Finding 3 (discovered during this story's own verification, not by the automated audit) — `lib/assessment.ts`'s *own*, actually-used `RubricScores` is ALSO stale

Verified directly against the real backend (`apps/api/app/modules/assessment/schemas.py:62-67`, `service.py:548-552`) — **not assumed**:

```python
# schemas.py:62-67
class TeachbackResult(BaseModel):
    session_id: str
    # B5 (Story 3-14): Changed from dict[str, float] to dict[str, str] — descriptive labels only.
    # Raw numeric sub-scores are never returned to students (CLAUDE.md Learner DNA display rules).
    rubric_scores: dict[str, str]  # {"accuracy": label, "completeness": label, "clarity": label}
    overall_score: float
    ces_contribution: float
    feedback: str

# service.py:548-552 (grade_teachback) — always exactly these 3 keys, string labels via _score_to_label()
rubric_scores={
    "accuracy": _score_to_label(result.accuracy_score),
    "completeness": _score_to_label(result.completeness_score),
    "clarity": _score_to_label(result.clarity_score),
},
```

Backend Story 3-14 changed `rubric_scores` from raw numeric sub-scores to descriptive string labels (a CLAUDE.md Learner-DNA-display-rules compliance fix on the backend side), but `lib/assessment.ts`'s `RubricScores` interface was never updated to match — it still declares `{accuracy: number; completeness: number; clarity: number}`. **This causes no live bug today** — confirmed by reading `TeachBackModal.tsx` in full: it only ever reads `result.feedback`, never `result.rubric_scores` or `result.overall_score` (by design — PRD: no rubric score shown to students in Phase 1). But the type is a real, verified type-safety hole: if any future code (a Sprint 3 admin/analytics view, say) reads `rubric_scores.accuracy` expecting a number per the current (wrong) type, it would silently receive a string. `TeachBackModal.test.tsx`'s own mock fixture (`rubric_scores: { accuracy: 80, completeness: 60, clarity: 90 }`, line 18) reflects this same stale assumption.

## Acceptance Criteria

1. **AC-1** — `apps/web/src/__tests__/lib/assessment.test.ts` gains a `describe('submitQuiz', ...)` block that mocks only `api.post` (not the whole `@/lib/assessment` module) and imports the real `submitQuiz`, asserting it calls `api.post('/assessment/quiz', payload)` with the exact payload passed in and returns `response.data` unchanged. Follow `getSessionReport`'s existing test pattern exactly.
2. **AC-2** — Same file gains a `describe('submitTeachBack', ...)` block, same pattern, asserting the real `/assessment/teachback` endpoint and full payload/response passthrough.
3. **AC-3** — `apps/web/src/lib/assessment.ts`'s `RubricScores` interface is corrected to `{ accuracy: string; completeness: string; clarity: string }` (string labels, matching the real backend contract cited above verbatim — exactly 3 keys, no more, no less). A code comment records the Story 3-14 backend change and cites `schemas.py`/`service.py` the same way `QuizFeedbackItem`'s existing comment cites `grade_quiz`.
4. **AC-4** — `apps/web/src/__tests__/components/player/TeachBackModal.test.tsx`'s `RESULT` fixture (line 18) is updated from `{ accuracy: 80, completeness: 60, clarity: 90 }` to string labels (e.g. `{ accuracy: 'Strong', completeness: 'Developing', clarity: 'Strong' }`) so the fixture matches the corrected type. No assertion in this file currently reads `rubric_scores` contents, so this is a type-correctness fix with zero behavior change — confirm this remains true (no new assertions needed on rubric_scores values, since `TeachBackModal.tsx` still never renders them, per its own explicit "never a numeric score or rubric breakdown" regression test staying green).
5. **AC-5** — `apps/web/src/types/assessment.ts`'s `TeachbackResult.rubric_scores` field is changed to reuse `RubricScores` imported from `@/lib/assessment` (exactly mirroring how `QuizResult.feedback` already reuses `QuizFeedbackItem` from the same module, per the S2-11 precedent) instead of re-declaring its own drifted shape. Do NOT delete `TeachbackResult` outright — reuse the field type, keep the interface (matches the established single-source-of-truth pattern already in this file for `QuizResult`).
6. **AC-6** — `apps/web/src/__tests__/types/assessment.test.ts`'s `'TeachbackResult has overall_score and rubric_scores'` test (line 162) is updated to construct its `rubric_scores` value using the corrected (string-label) shape, so the test would now genuinely fail if the reused `RubricScores` type drifted again — no longer self-referential/tautological.
7. **AC-7** — No regressions: full `apps/web` suite green, `tsc --noEmit` clean, `eslint` clean on every touched file.

## Tasks / Subtasks

- [x] Task 1 (AC: 3, 4): Fix `RubricScores` in `lib/assessment.ts` to match the real backend (string labels), update the stale numeric fixture in `TeachBackModal.test.tsx`.
  - [x] 1.1 Confirmed full suite passes unchanged after the type/fixture edit (type-only change, no behavior change).
  - [x] 1.2 GREEN: `tsc --noEmit` clean, full suite green.
- [x] Task 2 (AC: 1): Add a direct `submitQuiz` test to `apps/web/src/__tests__/lib/assessment.test.ts`.
  - [x] 2.1 RED: temporarily broke the real endpoint string (`/assessment/quiz-TEMP-BROKEN`), confirmed the new test genuinely failed, restored — proves the test exercises real code, not a stub.
  - [x] 2.2 GREEN.
- [x] Task 3 (AC: 2): Add a direct `submitTeachBack` test, same pattern.
  - [x] 3.1 RED (same revert-and-confirm technique), 3.2 GREEN.
- [x] Task 4 (AC: 5, 6): Fix `types/assessment.ts`'s `TeachbackResult.rubric_scores` to reuse `lib/assessment.ts`'s (now-corrected) `RubricScores`, and fix the self-referential test.
  - [x] 4.1 RED: reverted the type reuse temporarily (old inline wrong shape) — `tsc --noEmit` genuinely failed (3 `TS2322` errors) against the updated test, proving it's no longer tautological. Restored the fix.
  - [x] 4.2 GREEN.
- [x] Task 5 (AC: 7): Full `apps/web` suite green (48 files / 436 tests); `tsc --noEmit` clean; `eslint` clean on every touched file.

## Dev Notes

### Current state of every file this story touches (read directly, not assumed)

- **`apps/web/src/lib/assessment.ts`** (full file, 83 lines) — `submitQuiz`/`submitTeachBack`/`getSessionReport` all follow the same `api.post`/`api.get` passthrough pattern. `RubricScores` (lines 56-60) is the only stale piece: `{accuracy: number; completeness: number; clarity: number}`.
- **`apps/web/src/__tests__/lib/assessment.test.ts`** (full file, 30 lines) — currently only tests `getSessionReport`, mocking `@/lib/api`'s `get` only (not the whole `@/lib/assessment` module). This is the exact pattern Tasks 2/3 extend.
- **`apps/web/src/components/player/TeachBackModal.tsx`** — confirmed via full read: never accesses `result.rubric_scores` or `result.overall_score`, only `result.feedback`. AC-4's fixture change is behavior-neutral.
- **`apps/web/src/__tests__/components/player/TeachBackModal.test.tsx`** — `RESULT` fixture at line 18 is the only place needing the string-label update; no assertion elsewhere in this file touches `rubric_scores`.
- **`apps/web/src/types/assessment.ts`** — `QuizResult.feedback` (lines 30-39) already reuses `QuizFeedbackItem` from `lib/assessment.ts` (S2-11 precedent) with a comment explaining why. `TeachbackResult` (lines 50-62) is the one field left un-reused.
- **`apps/web/src/__tests__/types/assessment.test.ts`** (full file, 189 lines) — the `TeachbackResult` test at line 162 is the only one needing a fix; all 10 other cases (11 total in the file) were independently re-verified as correct against the real, live types (confirmed in the Sprint 2 audit — corrected count per this story's own review round, which caught this file's own miscount).
- **Backend (read-only, verified via `Read`/`Grep`, never modify):** `apps/api/app/modules/assessment/schemas.py:62-70` (`TeachbackResult` Pydantic model — `rubric_scores: dict[str, str]`), `apps/api/app/modules/assessment/service.py:347-556` (`grade_teachback` — confirms exactly 3 keys, `_score_to_label()` string outputs), `apps/api/app/modules/assessment/schemas.py:26-36, 53-59` (`QuizAnswer`/`QuizSubmission`/`TeachbackSubmission` — confirmed field names already match `lib/assessment.ts`'s request-side types exactly; no request-shape changes needed, only response-shape).

### What NOT to do

- Do NOT delete `TeachbackResult` from `types/assessment.ts` — reuse the field type (AC-5), matching the established `QuizResult` pattern in the same file. Deleting it would diverge from that precedent for no reason.
- Do NOT add any assertion on `rubric_scores` contents to `TeachBackModal.test.tsx` beyond fixing the fixture shape — the component never reads that field, and its existing "never a numeric score or rubric breakdown" test already correctly guards the real user-facing behavior.
- Do NOT touch the request-side types (`QuizAnswer`, `QuizSubmission`, `TeachbackSubmission`, `QuizSubmitPayload`, `TeachBackSubmitPayload`) — verified already correct against the real backend schemas, out of scope.
- Do NOT touch any backend file.
- Do NOT touch `getSessionReport` or its existing test — already correct, is the reference pattern, not the subject of this fix.

### Testing standards

Vitest. For Tasks 2/3, match `getSessionReport`'s existing mocking pattern in `apps/web/src/__tests__/lib/assessment.test.ts` exactly: `vi.mock('@/lib/api', () => ({ api: { get: apiGetMock, post: apiPostMock } }))`, import the real function under test, assert the exact call arguments and the return value. Do not mock `@/lib/assessment` itself in this file (that would defeat the entire point of this story).

### References

- [Source: this session's Sprint 2 Unit Test Audit, 2026-07-23] — Findings 1 and 2 (High severity) that this story fixes
- [Source: apps/api/app/modules/assessment/schemas.py, service.py] — real backend `TeachbackResult`/`grade_teachback` contract, read via `Read`/`Grep` this session, not assumed
- [Source: apps/web/src/__tests__/lib/assessment.test.ts] — `getSessionReport`'s existing test, the pattern to extend
- [Source: docs/stories/2-11-quiz-feedback-field-fix.md] — the precedent this story generalizes (same bug class, Quiz side, fixed then; TeachBack side, fixed now)

## Senior Developer Review (AI)

**Date:** 2026-07-23
**Outcome:** Approve — no code patches required.
**Reviewers:** Blind Hunter (diff-only), Edge Case Hunter (diff + repo access), Acceptance Auditor (diff + spec + context docs) — per CLAUDE.md's BMAD Code Review Gate.

### Findings

| # | Severity | Source | Finding | Resolution |
|---|----------|--------|---------|------------|
| 1 | High (dismissed) | Blind Hunter | Apparent duplicate `feedback` key / unterminated string in `TeachBackModal.test.tsx` | **False positive** — an artifact of the dev agent's own hand-transcription of the diff into the Blind Hunter's prompt (diff-only agents receive pasted text, not a live `git diff`). Verified the real file directly: single clean `feedback` key, no syntax error. The full suite (436/436) already ran green before this review round, which would have been impossible had this been real. |
| 2 | Medium (refuted) | Blind Hunter | `RubricScores`'s narrower, all-required shape could break other consumers reading `.depth`/`.relevance` or a partial object | Refuted by Edge Case Hunter with repo access: grepped all of `apps/web/src` — zero other consumers of `RubricScores`/`rubric_scores` exist besides the two touched files. |
| 3 | Medium (refuted) | Blind Hunter | Test mock updated to string labels but component logic not shown in diff — risk of numeric rendering mismatch | Refuted — `TeachBackModal.tsx` was fully read (both by the dev agent before implementing and independently by both Edge Case Hunter and Acceptance Auditor during review): it only ever reads `result.feedback`, never `rubric_scores`/`overall_score`. Zero behavior change. |
| 4 | Low (accepted) | Blind Hunter | No runtime schema validation on the real API response shape | Accepted, out of scope — consistent with this file's own existing convention (`getSessionReport` has no runtime validation either); would require a schema-validation library across the whole module, well beyond this story. |
| 5 | Low (accepted) | Edge Case Hunter | New `submitQuiz` test's mocked `feedback: []` doesn't exercise a populated feedback array | Accepted — the test's `toEqual(responseData)` still catches endpoint/payload/passthrough drift regardless; feedback-array shape is already covered by `QuizOverlay.test.tsx` and the `QuizResult` type test. |
| 6 | Low (fixed) | Acceptance Auditor | Dev Notes miscounted `types/assessment.test.ts`'s pre-existing test count as "9 others" when the file has 11 total (10 others) | Fixed — corrected the count in Dev Notes. |

### Non-issues independently re-verified

- Backend citations (`schemas.py:62-70`, `service.py:546-556`) confirmed real and accurate by both Edge Case Hunter and Acceptance Auditor, reading the actual files, not trusting the story's own claims.
- `_score_to_label()` confirmed a total function (no branch omits a key) — the all-3-keys-required TS shape is backend-guaranteed, not just assumed.
- Test payloads in the new `submitQuiz`/`submitTeachBack` tests confirmed to match the real production call sites in `QuizOverlay.tsx`/`TeachBackModal.tsx` field-for-field.
- `TeachBackResult` (lib/assessment.ts) vs `TeachbackResult` (types/assessment.ts) — confirmed no import mix-up anywhere.
- Story-first gate honored (story-only commit `4c0f55a` chronologically first, implementation in `3339b45`).
- All 7 ACs independently re-verified satisfied by the Acceptance Auditor, including an independent `vitest run`/`tsc`/`eslint` pass on the checked-out branch (not just trusting the story's own claims).

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-23 | Story created from the Sprint 2 test audit's 2 High-severity findings, plus one additional stale-type finding (`RubricScores` still modeling raw numbers post backend Story 3-14's switch to string labels) discovered while verifying Finding 2 against the real backend. Branch `sprint2/s2-13-assessment-test-fixes` off `sprint2-master`. | Dev 2 |
| 2026-07-23 | Implemented all 5 tasks (RED→GREEN throughout, with genuine revert-and-confirm checks on both the new `submitQuiz`/`submitTeachBack` tests and the fixed `TeachbackResult` test). Full suite 48 files / 436 tests passing, `tsc --noEmit` and `eslint` clean. Status → review. | Dev 2 |
| 2026-07-23 | 3-agent code review round. 1 High finding dismissed as a review-prompt transcription artifact (verified against the real file); 2 Medium findings refuted by repo-access cross-checks; 2 Low findings accepted as out-of-scope/non-regressions; 1 trivial Dev Notes miscount fixed. No code changes required — approved as-is. | Dev 2 |

## Dev Agent Record

### Implementation Plan

- **Task 1** — `RubricScores` corrected to `{accuracy: string; completeness: string; clarity: string}`, verified against `apps/api/app/modules/assessment/schemas.py`/`service.py` directly (not assumed). `TeachBackModal.tsx` was confirmed (full read) to never consume `rubric_scores` contents, so this is a pure type-correctness fix with zero runtime behavior change — the existing "never a numeric score or rubric breakdown" regression test stayed green throughout.
- **Tasks 2/3** — `submitQuiz`/`submitTeachBack` tests added to `apps/web/src/__tests__/lib/assessment.test.ts`, mocking only `api.post` (not `@/lib/assessment` itself), following `getSessionReport`'s existing pattern exactly. Each RED-confirmed by temporarily renaming the real endpoint string (e.g. `/assessment/quiz-TEMP-BROKEN`) and observing the new test fail, then restoring — proving the tests genuinely exercise the real implementation.
- **Task 4** — `types/assessment.ts`'s `TeachbackResult.rubric_scores` now reuses `RubricScores` imported from `@/lib/assessment`, mirroring the existing `QuizResult.feedback` → `QuizFeedbackItem` reuse pattern from Story 2-11. The self-referential test at `__tests__/types/assessment.test.ts` was rewritten to assert `typeof result.rubric_scores.accuracy === 'string'` and the exact 3-key set — RED-confirmed by temporarily reverting the type to its old wrong inline shape and observing `tsc --noEmit` genuinely fail (3 `TS2322` errors), proving the test is no longer tautological.

### Completion Notes

- All 5 tasks complete, all ACs (1–7) satisfied.
- Full `apps/web` test suite: 48 files, 436 tests, all passing (+2 from before this story: the new `submitQuiz`/`submitTeachBack` direct tests).
- `tsc --noEmit`: clean. `eslint` on all touched files: clean.
- No backend changes. No changes to request-side types (already verified correct). No changes to `getSessionReport` (already the reference pattern).

### File List

- `apps/web/src/lib/assessment.ts` (MODIFIED — `RubricScores` type fix)
- `apps/web/src/types/assessment.ts` (MODIFIED — `TeachbackResult.rubric_scores` reuse fix)
- `apps/web/src/__tests__/lib/assessment.test.ts` (MODIFIED — added `submitQuiz`/`submitTeachBack` direct tests)
- `apps/web/src/__tests__/types/assessment.test.ts` (MODIFIED — fixed the self-referential `TeachbackResult` test)
- `apps/web/src/__tests__/components/player/TeachBackModal.test.tsx` (MODIFIED — updated stale numeric `rubric_scores` fixture)
