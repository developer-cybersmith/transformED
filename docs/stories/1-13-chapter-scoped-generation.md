# Story 1.13: Chapter-scoped generation (book-scale Phase 5)

Status: review

**Sprint:** Book-scale ingestion, Phase 5 of 9
**Owner:** Dev 1
**Branch:** `book-scale/phase-5-chapter-scoped-generation` — from `book-scale/integration` (D41)
**Depends on:** Phase 4 ✅ Verified 2026-08-04
**Blocks:** Phase 6 (the generate endpoint), SYNC-2

---

## Story

As **a student picking one chapter of a 1,151-page book**,
I want **the pipeline to generate from that chapter's pages only**,
so that **I get a lesson about that chapter instead of one built from 4 % of the book**.

## Context

This is the phase the whole effort has been walking toward. Phases 1–3.5 find and store chapters;
Phase 4 taught the extractor to read a page range. **Nothing yet connects them** — `extract_node`
still downloads the whole PDF and calls the 3-argument subprocess form.

The prize, from the brief: feeding the pipeline ~40 pages instead of 1,151 makes every existing
default correct again, **without changing any of the eleven generation nodes**.
`structure_max_sections=15` (`config.py:301`), the 6,000-char prompt cap
(`graph.py:1751-1770`) and `_MAX_PHASE1_SECTIONS=60` (`graph.py:4173`) stop binding at chapter
scale — they were always chapter-shaped numbers pointed at a whole book.

---

## THE CONTRACT

### `chapter_id` becomes a required pipeline input

```python
class PipelineState(TypedDict, total=False):
    lesson_id: str
    user_id: str
    book_id: str
    chapter_id: str          # NEW — required
    source_pdf_path: str
    ...

async def run_pipeline(
    lesson_id: str,
    chapter_content: str = "",
    user_id: str = "",
    source_pdf_path: str = "",
    book_id: str = "",
    chapter_id: str = "",    # NEW
    tier: str = "T2",
    attempt: str = "",
) -> dict[str, Any]: ...
```

**How it arrives:** `content_pipeline_job` already reads the lesson row; it reads
`lessons.chapter_id` — the column Phase 2 added and **nothing has used yet** — and passes it
through. Phase 6's endpoint sets that column when it creates the lesson.

**`chapter_content` keeps working.** Tests pass raw text with no PDF and no chapter; that path
stays, and `chapter_id` is only required on the PDF path.

### `extract_node` resolves the range and passes bounds

Read the chapter row, take `page_start`/`page_end`, pass them as argv 4 and 5 to the subprocess —
the parameters Phase 4 built. A chapter row that does not exist, or does not belong to
`book_id`, is a **hard error**, not a fallback to whole-document: silently generating from 1,151
pages is precisely the defect this effort exists to remove.

### Idempotency — reuse, never re-embed

`CLAUDE.md`: *"Chunk embeddings at ingestion only — never regenerate stored chunk embeddings."*

If `chunks` already exist for this `chapter_id`, **reuse them** and skip chunking and embedding
entirely. Two lessons from the same chapter at different tiers share one set of chunks and one
embedding spend — which is the "process once, reuse everywhere" principle (PRD §5.2) finally
being true.

**No migration.** A `UNIQUE (chapter_id, chunk_index)` constraint was considered and rejected:
reuse makes it unnecessary, and it would drag a frozen-contract 4-developer review into a phase
that otherwise needs none.

---

## Acceptance Criteria

1. `chapter_id` is on `PipelineState` and `run_pipeline`; `content_pipeline_job` reads
   `lessons.chapter_id` and passes it.
2. `extract_node` resolves the chapter's `page_start`/`page_end` and passes them to the
   subprocess. The extraction reads **only** those pages.
3. A missing chapter, or one whose `book_id` does not match the lesson's, **raises** — with a
   message naming both ids. **Never falls back to whole-document.**
4. **The hardcoded chapter row at `graph.py:609-651` is deleted.** `chunk_node` takes
   `chapter_id` from state. This is AC23 from Story 1-10, deferred twice and now actionable
   because a real `chapter_id` finally exists.
5. `chunks` written by `chunk_node` carry the state `chapter_id`.
6. **Regenerating the same chapter performs zero new embedding API calls** — asserted by counting
   calls, not by inspection.
7. D33 closed: the `or ""` / `.get(..., "")` defaults for `book_id`/`chapter_id`
   (`graph.py:711`, `:3742`) are gone. An empty string can never satisfy the `UUID` fields at
   `schemas/lesson.py:212-213`, so the default turned a missing upstream output into a bare
   Pydantic `ValidationError` at the final node — after full spend.
8. The guard from Story 1-11 is **extended to `chapters`**: nothing under `pipeline/` writes
   `books` **or** `chapters`. It was scoped to `books` only because this deletion had not happened
   yet; now it can cover both.
9. **No generation node is modified.** `lesson_planner`, `slide_generator`, quiz, narration,
   jargon, interventions, TTS, images, package_builder — untouched. If one needs changing, the
   premise of this phase is wrong; report it rather than editing.
10. Generating a real chapter produces a package validating against
    `packages/shared/lesson_package.schema.json`, with **no truncation warning** in the logs —
    today a big book emits them constantly.
11. Repo-wide, against a `main` baseline measured with the identical command: gating scope green;
    `ruff check .` clean; `ruff format --check` and `mypy app` show no new findings.

---

## Tasks / Subtasks

- [ ] **T1 — `chapter_id` through the state** — `PipelineState`, `run_pipeline`,
      `content_pipeline_job`. (AC1)
- [ ] **T2 — `extract_node` passes bounds**, with the hard-error path. (AC2, AC3)
- [ ] **T3 — Delete `graph.py:609-651`**; `chunk_node` reads `chapter_id` from state. (AC4, AC5)
- [ ] **T4 — Chunk reuse**, so regeneration re-embeds nothing. (AC6)
- [ ] **T5 — Close D33** — drop the empty-string defaults. (AC7)
- [ ] **T6 — Extend the pipeline-writes guard to `chapters`.** (AC8)
- [ ] **T7 — Tests** for T1–T5. (AC1–7, AC9)
- [ ] **T8 — Real-chapter verification** + repo-wide gates + tracker. (AC10, AC11)

---

## Dev Notes

### Current state of the files being changed

**`graph.py:83-120` `PipelineState`** — has `lesson_id`, `user_id`, `book_id`,
`source_pdf_path`, `chapter_content`, `tier`. No `chapter_id`.

**`graph.py:~240-330` `extract_node`** — checkpoint cache-hit first (`node_outputs["extract"]`),
then downloads `source_pdf_path` from Storage, writes it to a temp dir, and calls the subprocess
with exactly three positional arguments. **That call site is what T2 changes**, and Phase 4 built
argv 4/5 for precisely this.

**`graph.py:609-651`** — the hardcoded chapter row. Currently an **upsert** with
`on_conflict="book_id,chapter_index"` (added during the Phase 2 review so an ARQ retry could not
23505 the job). Deleting the block removes that concern with it. `chapter_id` from it is consumed
at `:659` for the chunk rows — that consumer is what makes the deletion possible only now.

**`graph.py:4490-4498` `run_pipeline`** — all-keyword-with-defaults; adding `chapter_id` there is
additive.

**`app/workers/jobs/content_pipeline.py`** — reads the lesson row already. `lessons.chapter_id`
exists (Phase 2 migration `20260803000000`) and has **no reader anywhere in the codebase**; this
story is its first.

### Do not reinvent

- Phase 4's bounds are `page_start`/`page_end`, **0-based inclusive**, argv 4 and 5, matching
  `chapters.page_start`/`page_end` exactly. No conversion is needed — that alignment was
  deliberate.
- `single_row()` / `rows()` in `app/core/db.py` for response-boundary access.
- The chunk-reuse check belongs in `chunk_node` alongside its existing `node_outputs["chunk"]`
  cache-hit, not as a new node.

### Testing standards

- Markers `unit`, `integration`, `slow`, `live_eval`, `postgres`; `--strict-markers`;
  `filterwarnings = ["error"]`.
- Eval PDFs auto-generate at import (Story 1-12) — do not reintroduce a skip.
- AC6 must **count embedding calls**, not inspect code. A mock that records call counts is
  legitimate here; mark it `# MOCK-CONTRACT:` and name the real-dependency test.
- Running locally: Postgres `55432`, PostgREST `53000`, API `8077`.

### References

- [Source: docs/book-scale-phase-tracker.md#Phase-5]
- [Source: docs/stories/1-12-page-scoped-extraction.md] — the bounds contract this consumes
- [Source: docs/stories/1-10-book-ingest-chapter-detection.md] — AC23, deferred twice, landing here
- [Source: CLAUDE.md] — §5.2 process once/reuse everywhere; the embeddings rule; D33; binding rules 1, 2, 7

---

## Dev Agent Record

### Agent Model Used

claude-opus-5[1m] — 2026-08-04. Four agents: implementation, new tests, and two test-repair
agents on disjoint files.

### Debug Log References

**Verified against the code, not by inspection:**

| AC | Check | Result |
|---|---|---|
| 1 | `chapter_id` on `PipelineState`, `run_pipeline`, and read from `lessons.chapter_id` | yes |
| 2 | `page_start`/`page_end` reach the subprocess spawn args | yes |
| 4 | `"chapter_index": 1` gone; **any** `chapters` write from `pipeline/` | **none** |
| 7 | D33 — `or ""` now normalises then raises a diagnostic before Pydantic sees it | yes |
| 8 | Guard widened to `books` **and** `chapters`, mutation-checked | yes |
| 9 | Of the eleven generation nodes, **none touched** | confirmed by line-to-function mapping |

AC9 was checked by mapping every changed line to its enclosing function rather than by reading
the diff: `extract_node`, `chunk_node`, `package_builder_node`, `run_pipeline` and one new helper.
`package_builder_node` appears only because AC7 mandates the D33 fix there — it assembles the
package, it does not generate content. **`lesson_planner`, `slide_generator`, quiz, narration,
jargon, interventions, complexity, TTS and image are byte-identical.** That was the phase's
central bet: ~40 pages makes their existing defaults correct without edits.

**AC6 is guarded by a counting test, not an inspection.** Two lessons over one chapter run through
`chunk_node → embed_node` against a shared mutable chunk store; run 2 asserts the embedding
provider's constructor `call_count == 0` and `embed_texts.await_count == 0`. Mutation-checked by
the test author: disabling reuse makes it fail.

**Chunk reuse costs nothing extra to get right.** It sits before `chunk_sections`, so a reused
chapter skips tokenisation too, and it needs no migration: reused chunks already carry non-NULL
`embedding`, so `embed_node`'s existing `is_("embedding","null")` query returns nothing and it
takes its "all already done" branch. A `UNIQUE (chapter_id, chunk_index)` constraint was
considered and rejected — it would have dragged a frozen-contract review into a phase needing none.

**25 existing tests failed and every one was repaired without weakening an assertion.** Two
categories, handled differently:

- **21 stale fixtures** — subprocess spawn/timeout/reaping, image-upload concurrency, retry,
  ordering, checkpoint shape. All still assert exactly what they did before; only the state and
  the Supabase double changed. The cancellation/reaping tests came from a real incident where
  4 GB tesseract orphans survived, so their assertions were left byte-identical.
- **4 asserting the old shape — inverted, not deleted.**
  `test_chunk_node_writes_chapter_row` now asserts the pipeline writes **no** chapter row;
  `test_chunk_node_chapter_write_is_retry_safe` becomes "a retry cannot collide because there is
  no write to collide"; `test_graph_still_uses_the_three_argument_form` — a Phase 4 marker whose
  docstring said it existed to fail when Phase 5 landed — now guards the wiring in the opposite
  direction; the D33 symptom test now asserts a diagnostic error and explicitly **not** a
  `pydantic.ValidationError`.

**A story error the implementer caught.** The contract said "`chapter_id` is only required on the
PDF path". That is wrong: `chunks.chapter_id` is `UUID NOT NULL` and the row `chunk_node` used to
manufacture is gone, so **every** path that writes chunks needs one. The raw-text
(`chapter_content`) affordance is test-only; the integration tests now pass a `chapter_id`. The
story's wording was the defect, not the implementation.

**Stale line numbers in the story:** D33's sites were `:569` and `:4091`/`:3752`, not `:711` and
`:3742`. Fixed at the real sites.

### Completion Notes List

- T1-T7 complete. **AC10 (a real paid end-to-end generation) is NOT done** — see below.
- Gating scope **917 passed, 1 skipped** (was 898). `ruff check .` clean. `mypy app` 24 errors in
  3 files, unchanged from `main`. `ruff format --check` flags only the pre-existing
  `tests/test_tutor_service.py`.
- **Phase 5 is Implemented, not Verified.** AC10 requires generating a real chapter through all
  eleven nodes, which spends real money on the project's OpenAI key (the repo's own `live_eval`
  marker exists for exactly this class of run). That is the user's call, not mine.

### File List

- `apps/api/app/modules/content/pipeline/graph.py` (modified)
- `apps/api/app/workers/jobs/content_pipeline.py` (modified — first reader of `lessons.chapter_id`)
- `apps/api/tests/unit/test_chapter_scoped_generation.py` (new — 18 tests)
- `apps/api/tests/unit/test_pipeline_writes_no_books.py` (modified — widened to `chapters`)
- `apps/api/tests/unit/test_extract_node.py`, `test_pipeline_tier1.py`, `test_extract_page_bounds.py` (repaired)
- `apps/api/tests/unit/test_chunk_node.py`, `test_package_builder_node.py` (repaired/inverted)
- `apps/api/tests/integration/test_howto_pipeline_e2e.py` (modified — passes `chapter_id`)
