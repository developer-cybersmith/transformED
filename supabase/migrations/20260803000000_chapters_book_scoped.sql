-- ============================================================
-- TransformED AI — Migration: chapters become book-scoped
-- Migration: 20260803000000_chapters_book_scoped.sql
-- Story 1-9 · book-scale ingestion Phase 2
--   docs/stories/1-9-chapters-storable-migration.md
--   docs/book-scale-phase-tracker.md (Phase 2)
--   docs/bmad/phase-3-chapter-detection-plan.md (§6 — why five enum values)
--
-- WHY
-- Today a chapter cannot exist without a lesson: chapters.lesson_id is
-- NOT NULL (20260611000000:132) and chunks.chapter_id is NOT NULL (:147).
-- That chain is why the pipeline hardcodes exactly one chapter per ingestion
-- (pipeline/graph.py:609-638, "chapter_index": 1 at :624). The spec has always
-- been the reverse — upload a book once, generate any chapter on demand
-- (CLAUDE.md §9). Phase 3 needs to write N chapter rows at upload time, before
-- any lesson exists.
--
-- Changes:
--   1. chapters.lesson_id → nullable (FK retained)
--   2. lessons.chapter_id → new nullable FK, ON DELETE SET NULL
--   3. UNIQUE (book_id, chapter_index) on chapters
--   4. chapters.boundary_confidence — which detection rung produced the row
--   5. RLS on chapters and chunks re-rooted from lessons.user_id to books.user_id
--
-- DIRECTION IS PERMISSIVE. Every change either relaxes a constraint, adds a
-- nullable column, or adds a constraint that existing data already satisfies.
-- No existing row can be invalidated.
--
-- FAIL-LOUD (Story 1-9 AC10): step 3 adds a UNIQUE constraint. If duplicate
-- (book_id, chapter_index) pairs already exist, Postgres raises 23505 and this
-- migration aborts. That is intended. There is deliberately no DELETE, no
-- TRUNCATE and no ON CONFLICT DO NOTHING here — silently discarding a duplicate
-- chapter row would destroy exactly the data this effort exists to produce.
-- Resolve duplicates deliberately, then re-apply.
--
-- Never modify an applied migration. This is a new file only.
-- ============================================================


-- ============================================================
-- STEP 1: chapters.lesson_id becomes nullable
-- The FK and its ON DELETE CASCADE are untouched — dropping NOT NULL does not
-- drop the constraint. A chapter may now belong to a book alone; when it does
-- carry a lesson_id, that lesson must still exist.
-- ============================================================

ALTER TABLE public.chapters
  ALTER COLUMN lesson_id DROP NOT NULL;


-- ============================================================
-- STEP 2: lessons.chapter_id — which chapter a lesson was generated from
-- ON DELETE SET NULL mirrors lessons.book_id (20260625000000:69-70): the
-- lesson JSONB is self-contained, so a lesson survives deletion of its source.
--
-- This and chapters.lesson_id now reference each other. Both are nullable, so
-- there is no chicken-and-egg on insert: Phase 3 writes chapters with
-- lesson_id = NULL, and Phase 5 sets lessons.chapter_id when a lesson is built.
-- Deliberately NOT DEFERRABLE — not needed, and it complicates PostgREST.
-- ============================================================

ALTER TABLE public.lessons
  ADD COLUMN chapter_id uuid REFERENCES public.chapters(chapter_id) ON DELETE SET NULL;

CREATE INDEX ON public.lessons (chapter_id);


-- ============================================================
-- STEP 3: one chapter_index per book
-- No such constraint exists today. Phase 3 writes sequential chapter_index
-- values per book; without this, a re-run could silently double them.
-- Per-book, not global — chapter 7 exists in every book.
-- ============================================================

ALTER TABLE public.chapters
  ADD CONSTRAINT chapters_book_id_chapter_index_key UNIQUE (book_id, chapter_index);


-- ============================================================
-- STEP 4: chapters.boundary_confidence — which rung detected this boundary
--
-- Five values, one per rung of the Phase 3 detection ladder
-- (docs/bmad/phase-3-chapter-detection-plan.md §3):
--   toc       R1 — the PDF's own outline via pypdfium2 get_toc()
--   contents  R2 — parsed from the book's printed contents page
--   heading   R3 — in-body "CHAPTER n" openers found by text sweep
--   font      R4 — existing detect_headings() font-signal path
--   fallback  R5 — no usable signal; the whole document as one chapter
--
-- Phase 1 measured all five as distinct provenances across 8 real textbooks.
-- Collapsing them (the original toc|font|fallback sketch) would destroy the
-- only signal that says which detector is failing in production.
--
-- DEFAULT 'fallback' is not a placeholder — it is accurate for every existing
-- row. Those were written by the hardcoded single-chapter path at
-- graph.py:609-638, which performs no detection at all.
-- ============================================================

ALTER TABLE public.chapters
  ADD COLUMN boundary_confidence text NOT NULL DEFAULT 'fallback'
    CHECK (boundary_confidence IN ('toc', 'contents', 'heading', 'font', 'fallback'));


-- ============================================================
-- STEP 5: re-root RLS from lessons.user_id to books.user_id
--
-- Every chapters and chunks policy currently resolves ownership by joining to
-- lessons (20260611000000:429-522):
--
--   EXISTS (SELECT 1 FROM lessons l
--           WHERE l.lesson_id = chapters.lesson_id AND l.user_id = auth.uid())
--
-- With lesson_id = NULL after step 1, that EXISTS can never be true, so every
-- book-scoped chapter is invisible and un-insertable to any RLS-bound caller.
-- Nothing breaks today — app/core/db.py:40-47 uses the service-role key, which
-- bypasses RLS, and the web app never reads chapters directly — but the
-- policies would be structurally incapable of matching the rows Phase 3 writes.
--
-- books.user_id is NOT NULL (20260625000000:30) and chapters.book_id is
-- NOT NULL with an FK to books (:57-59), so the re-rooted predicate is total:
-- it resolves for every chapter row, including ones that still carry a
-- lesson_id. This is a strict generalisation — nothing readable before this
-- migration becomes unreadable after it.
--
-- Policies must be DROPped by name first: CREATE POLICY does not replace, and
-- two policies on the same command OR together, which would widen access
-- rather than change it.
-- ============================================================

DROP POLICY "chapters: select own" ON public.chapters;
DROP POLICY "chapters: insert own" ON public.chapters;
DROP POLICY "chapters: update own" ON public.chapters;
DROP POLICY "chapters: delete own" ON public.chapters;

CREATE POLICY "chapters: select own"
  ON public.chapters FOR SELECT
  USING (
    EXISTS (
      SELECT 1 FROM public.books b
      WHERE b.book_id = chapters.book_id
        AND b.user_id = auth.uid()
    )
  );

CREATE POLICY "chapters: insert own"
  ON public.chapters FOR INSERT
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM public.books b
      WHERE b.book_id = chapters.book_id
        AND b.user_id = auth.uid()
    )
  );

CREATE POLICY "chapters: update own"
  ON public.chapters FOR UPDATE
  USING (
    EXISTS (
      SELECT 1 FROM public.books b
      WHERE b.book_id = chapters.book_id
        AND b.user_id = auth.uid()
    )
  );

CREATE POLICY "chapters: delete own"
  ON public.chapters FOR DELETE
  USING (
    EXISTS (
      SELECT 1 FROM public.books b
      WHERE b.book_id = chapters.book_id
        AND b.user_id = auth.uid()
    )
  );


-- chunks: chapters → books (was chapters → lessons)
DROP POLICY "chunks: select own" ON public.chunks;
DROP POLICY "chunks: insert own" ON public.chunks;
DROP POLICY "chunks: update own" ON public.chunks;
DROP POLICY "chunks: delete own" ON public.chunks;

CREATE POLICY "chunks: select own"
  ON public.chunks FOR SELECT
  USING (
    EXISTS (
      SELECT 1
      FROM public.chapters c
      JOIN public.books    b ON b.book_id = c.book_id
      WHERE c.chapter_id = chunks.chapter_id
        AND b.user_id = auth.uid()
    )
  );

CREATE POLICY "chunks: insert own"
  ON public.chunks FOR INSERT
  WITH CHECK (
    EXISTS (
      SELECT 1
      FROM public.chapters c
      JOIN public.books    b ON b.book_id = c.book_id
      WHERE c.chapter_id = chunks.chapter_id
        AND b.user_id = auth.uid()
    )
  );

CREATE POLICY "chunks: update own"
  ON public.chunks FOR UPDATE
  USING (
    EXISTS (
      SELECT 1
      FROM public.chapters c
      JOIN public.books    b ON b.book_id = c.book_id
      WHERE c.chapter_id = chunks.chapter_id
        AND b.user_id = auth.uid()
    )
  );

CREATE POLICY "chunks: delete own"
  ON public.chunks FOR DELETE
  USING (
    EXISTS (
      SELECT 1
      FROM public.chapters c
      JOIN public.books    b ON b.book_id = c.book_id
      WHERE c.chapter_id = chunks.chapter_id
        AND b.user_id = auth.uid()
    )
  );
