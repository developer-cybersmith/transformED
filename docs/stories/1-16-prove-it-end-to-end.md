# Story 1.16: Prove it end to end (book-scale Phase 7)

Status: in-progress — build half done, acceptance run pending

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

## Dev Agent Record — build half (AC1-AC3)

### What was verified rather than assumed

Before writing anything I mutation-checked the two Phase 7 work items the tracker lists as
outstanding. **Both were already satisfied** by guards Phases 3-6 shipped:

| Mutation | Result |
|---|---|
| `chapter_index` reverted to the pre-book-scale constant `1` | **RED** — `test_writes_one_row_per_chapter_with_null_lesson_id` |
| `max_chapter_pages` silently moved 200 → 2000 | **RED** — 4 tests in `test_generate_lesson_endpoint.py` |

So the tracker's step 8 needed no new work. Building a third guard to make the phase look
substantial would have been the same instinct that produces tests which cannot fail.

### The one gap that was real

Detection tests prove the ladder finds the right chapters. Endpoint tests prove the generate
endpoint refuses an over-cap span. **Nothing asserted the two agree** — that what detection offers
a student is something the endpoint will accept. A chapter wider than the cap would leave both
suites green and the UI showing a Generate button that 422s every time. The failure lives in the
join, which is exactly where the original bug lived.

`tests/integration/test_book_scale_composition.py`, 9 tests over one book **with** a bookmark tree
(`d2l`) and one **without** (`ncert-xii-phys-part1`).

**AC2 mutation — the assertion fires.** The corpus maximum is 98 pages against a 200 cap, so a
pass proves little on its own. Lowering the cap to 50 produced:

> `d2l: 7 detected chapter(s) exceed max_chapter_pages=50 and would be un-generatable from the
> chapter card: [(1, 'Preliminaries', 52), (7, 'Modern Convolutional Neural Networks', 57), …
> (13, 'Computer Vision', 98) …]`

Reverted; 9 pass.

**One thing the test does that the story did not ask for.** `DetectedChapter.page_span` and the
endpoint's inline `page_end - page_start + 1` are two expressions of the same number in two
layers. The test asserts they **agree** rather than picking one — a divergence between the span
the student is shown and the span the gate enforces would otherwise be invisible.

**AC3** — the module docstring states plainly that this runs over captured detection output, not a
live PDF parse, and asserts nothing about generated content. A green run here is not end-to-end
proof.

Gating suite **1038 passed, 1 skipped**. ruff clean.

### Still outstanding — AC4-AC14

The acceptance run and the merge. Both need authorisation to spend and a person at a browser.
