# Story: Quiz score summary re-dumps every question's explanation, cluttering the modal

**Reported:** 2026-09-29, direct product feedback: "when we are submitting quiz, we are given
the feedback for our answer at bottom of modal, but at the summary [section], we are given
feedback of all the quiz question together. that breaks the UI and hinders UX."

## Root cause

`QuizOverlay.tsx` has two distinct feedback surfaces, both rendered in the same modal:

1. **Per-question explanation** (`role="status"`, lines ~176-195): shown immediately after the
   student submits EACH question, one at a time — `question.explanation` for the CURRENT question
   only. This is the good, working UX the report describes ("feedback for our answer at bottom of
   modal").

2. **Score summary** (lines ~197-212): shown once, after `submitQuiz()` resolves on the LAST
   question. Intended to show the aggregate result (`correct_count`/`total_count`/percentage) — but
   also does `result.feedback.map((f) => <p>{f.explanation}</p>)`, re-rendering the `explanation`
   text for **every** question in the quiz, all stacked together in one block, directly below the
   per-question explanation the student already just read for that same last question.

For a single-question quiz this only duplicates one line. For a multi-question quiz, the student
sees a wall of every explanation they already read one at a time, moments after reading them
individually — cluttered, redundant, and exactly the "breaks the UI" complaint.

Confirmed this is the CURRENT, intentional-by-code (not accidental) behavior: two existing tests
in `QuizOverlay.test.tsx` explicitly assert on it —
`'shows the score summary feedback using the real backend field names...'` and
`'styles score summary feedback by is_correct...'` — both assert the per-question explanation text
reappears in the aggregate summary block. These need updating as part of this fix, not preserved.

## Fix

Remove the `result.feedback.map(...)` explanation dump from the score-summary block. Keep only the
aggregate line (`correct_count`/`total_count`/percentage) — the per-question explanation was
already shown to the student in real time via the existing `role="status"` block; nothing is lost
by not repeating it in the summary.

`result.feedback` itself (the array from `submitQuiz`'s response) is used nowhere else in this
component — removing its per-item render is safe and fully contained to this one block.

## Acceptance Criteria

1. **AC1**: after submitting a multi-question quiz's last question, the score-summary block shows
   `correct_count`/`total_count` and the percentage — unchanged.
2. **AC2**: the score-summary block does NOT render any `QuizFeedbackItem.explanation` text —
   neither the current (last) question's nor any earlier question's.
3. **AC3**: the per-question `role="status"` explanation (shown immediately after submitting each
   question, including the last one) is completely unaffected by this change — still renders
   exactly as before.
4. **AC4**: the two existing tests that previously asserted explanation text inside the summary
   block are updated to assert its ABSENCE there instead, not deleted outright — the score-summary
   block itself (aggregate numbers) still needs coverage.

## Scale & Load

N/A — a pure client-side rendering change (removing one `.map()` over an already-fetched, already
small (`<= number of quiz questions in one segment`, single-digit) array). No new data, no new I/O,
no new budget or limit of any kind.

## Completion notes

Implemented exactly as designed: removed the `result.feedback.map(...)` explanation dump from
the score-summary block, keeping only the aggregate `correct_count`/`total_count`/percentage line.

Updated the two existing tests that asserted the old behavior:
- Renamed/re-targeted `'shows the score summary feedback using the real backend field names...'`
  to assert the aggregate `"2/2 correct"` line instead of a repeated explanation string.
- Renamed `'styles score summary feedback by is_correct...'` to
  `'does NOT repeat any question explanation inside the score summary...'` — now asserts the
  mocked per-question explanation text (`'Correct feedback.'`/`'Incorrect feedback.'`) is absent
  from the DOM entirely, alongside the aggregate `"1/2 correct"` line still rendering correctly.

Verified: `QuizOverlay.test.tsx` 21/21, full player suite 462/462 (20 files), full web suite
1312/1312 (96 files), `eslint` clean, `tsc --noEmit` clean.

## Out of scope

No change to `submitQuiz`'s response shape, the backend grading logic, or the per-question
`role="status"` explanation flow — this story only removes the redundant re-display of already-seen
explanation text from the aggregate summary block.
