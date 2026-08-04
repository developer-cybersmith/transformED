# Story 1.13: Chapter-scoped generation (book-scale Phase 5)

Status: ready-for-dev

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

_not yet run_

### Debug Log References

### Completion Notes List

### File List
