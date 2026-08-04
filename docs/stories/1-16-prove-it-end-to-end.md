# Story 1.16: Prove it end to end (book-scale Phase 7)

Status: ready-for-dev

**Branch:** `book-scale/integration` · **Phase:** 7 of 9 — the last one
**Discharges:** Story 1-13 AC10 · Phases 5, 6, 6.5 · Track W W0–W4

## Story

As **the team**,
I want **one run that proves a 1,000-page book becomes real lessons a student can study**,
so that **we can merge to `main` knowing the product works rather than that the tests do**.

## Most of this phase is already done, and pretending otherwise would be the defect

The tracker's Phase 7 work list was written before Phases 3–6 existed. Checked against the repo:

| Work item | State |
|---|---|
| Commit a fixture **with** a bookmark tree and one **without** | **Already done** (Phase 3) — `tests/fixtures/chapter_detection/` holds `d2l` (outline) and three NCERT books (no outline), committed and gzipped |
| A guard that fails if `chapter_index` reverts to a constant | **Already done** — mutation-verified 2026-08-04: reverting it reddens `test_writes_one_row_per_chapter_with_null_lesson_id` |
| A guard that fails if a cap silently moves | **Already done** — moving `max_chapter_pages` 200 → 2000 reddens **4** tests |
| Integration test: chapter count, page ranges | Partly — asserted at the *detection* layer, never across the book-scale boundary |
| Integration test: valid package, no truncation warning | **Not possible without generation** — needs the paid run |

So this story adds **one** test — the composition — and then performs the run. Inventing work to
make the phase look substantial would be the same instinct that produces tests which cannot fail.

## Acceptance Criteria

### A. Buildable now — no money, no browser

**AC1 — One end-to-end test across the book-scale boundary, over the committed fixtures.**
Detection is well covered per-rung; nothing asserts that what detection produces is *generatable*.
For `d2l` (outline) and at least one NCERT book (no outline), assert the whole chain composes:

- `chapter_index` is sequential from zero with no gaps
- page ranges ascend, never overlap, and lie inside the document
- **every detected chapter's span is within `settings.max_chapter_pages`** — i.e. every chapter
  the student is offered can actually be generated. This is the assertion that would have caught
  the original bug, and it is the one nothing currently makes.
- every chapter records the rung that found it

**AC2 — The span assertion must be able to fail.** Mutation-check it by lowering
`max_chapter_pages` below the corpus maximum (98 pages for `d2l`) and confirming red. A test that
passes because the cap is generous proves nothing about the cap.

**AC3 — Say what the test does NOT cover.** It runs over captured detection output, not a live
PDF parse, and asserts nothing about generated content. Both are the paid run's job. State it in
the module docstring so nobody reads a green suite as end-to-end proof.

### B. The acceptance run — needs authorisation and a person

**AC4** — Upload a real 1,000+ page textbook **through the UI**.
**AC5** — Chapters appear. Phase 6 measured 1,151 pages → 21 chapters in 90.3 s.
**AC6** — List them at `/books/{id}`; every chapter shows its real page range.
**AC7** — Generate **two different chapters at two different tiers**, from the chapter card.
**AC8** — Both produce schema-valid packages with **no truncation warning** — so pick chapters
under ~40 pages (D46); the corpus book's chapters run 10–98, so choose deliberately and record which.
**AC9** — Play both in the player; take both quizzes.
**AC10** — A connected WebSocket receives `lesson_ready` keyed to a real session (Phase 6.5 AC10).
**AC11** — Full suite + `ruff` + `mypy`, **repo-wide** (binding rule 1).
**AC12** — Record every observed number in the tracker. A phase with no recorded evidence is not
verified.

### C. The merge

**AC13 — Tell Dev 2 before merging, not after.** D41's trigger is this merge: `main` gains an
upload endpoint that 422s on `tier`. It is the moment three other developers' assumptions change.

**AC14 — One merge, after the run passes.** If any of AC4–AC10 fails, **nothing** merges and
Phases 5, 6, 6.5 and Track W all stay `Implemented`. They were carried forward together on the
D43 exception; there is no partial credit.

## Dev Notes

- Run recipe, including the stale-process checks that cost the most time in Phase 6:
  `docs/book-scale-phase-7-run-recipe.md`.
- The corpus fixtures are captured detection output (`.json.gz`), not PDFs — the PDFs are
  gitignored and live outside the repo. AC1 works from the captures; the paid run works from a
  real file.
- `settings.max_chapter_pages` is 200 and `_TRUNCATION_WARN_PAGES` is 40. They gate different
  failures — do not collapse them into one number.
