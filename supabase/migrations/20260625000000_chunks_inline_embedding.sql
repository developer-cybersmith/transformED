-- ============================================================
-- TransformED AI — Migration: inline embedding into chunks
-- Migration: 20260625000000_chunks_inline_embedding.sql
-- Reconciles chunks table with PDF Upload Flow doc (v6, 2026-06-22)
--
-- Changes:
--   1. Create books table (was missing; chapters.book_id was a dangling UUID)
--   2. Add FK on chapters.book_id → books.book_id (ON DELETE CASCADE)
--   3. Add lessons.book_id (nullable FK, ON DELETE SET NULL — lesson survives book deletion)
--   4. Add book_id, token_count, embedding, embedding_metadata to chunks
--   5. Migrate data: copy embeddings.vector + metadata → chunks (safe no-op if empty)
--   6. Backfill chunks.book_id from chapters
--   7. Drop the embeddings table (index + RLS policies cascade)
--   8. Create HNSW index on chunks.embedding
--   9. RLS policies for books table
--
-- NOTE: chunks.content TEXT is intentionally KEPT in the schema.
--   Industry standard: chunk text is always stored alongside the vector.
--   Dropping it would require re-extracting 200-300ms per pipeline node call
--   and would break lessons if the source PDF is ever deleted.
-- ============================================================


-- ============================================================
-- STEP 1: Create books table
-- ============================================================

CREATE TABLE public.books (
  book_id     uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid        NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  filename    text        NOT NULL,
  page_count  integer,
  status      text        NOT NULL DEFAULT 'processing'
                          CHECK (status IN ('processing', 'ready', 'failed')),
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER books_set_updated_at
  BEFORE UPDATE ON public.books
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

CREATE INDEX ON public.books (user_id);
CREATE INDEX ON public.books (status);


-- ============================================================
-- STEP 2: Add FK on chapters.book_id → books.book_id
-- The column already exists as a bare UUID (no constraint) in the
-- initial migration. We retrofit the referential integrity here.
-- NOTE: This will fail if chapters rows exist with book_id values
-- that do not exist in books. In that case, truncate chapters first
-- (only safe if no production data yet).
-- ============================================================

ALTER TABLE public.chapters
  ADD CONSTRAINT chapters_book_id_fkey
    FOREIGN KEY (book_id) REFERENCES public.books(book_id) ON DELETE CASCADE;


-- ============================================================
-- STEP 3: Add lessons.book_id (nullable FK, SET NULL on book delete)
-- When a book is deleted, lessons.book_id → NULL.
-- The lesson JSONB is self-contained, so the lesson still plays.
-- UI checks: lessons.book_id IS NULL → show "Source book removed" badge.
-- ============================================================

ALTER TABLE public.lessons
  ADD COLUMN book_id uuid REFERENCES public.books(book_id) ON DELETE SET NULL;

-- Backfill: link existing lessons to their book via chapters.
-- Safe no-op if no lessons exist yet (Sprint 0 state).
UPDATE public.lessons l
SET book_id = c.book_id
FROM (
  SELECT DISTINCT ON (lesson_id) lesson_id, book_id
  FROM public.chapters
  ORDER BY lesson_id, chapter_index
) c
WHERE c.lesson_id = l.lesson_id;


-- ============================================================
-- STEP 4: Add new columns to chunks
-- All nullable initially to allow backfill before constraints.
-- ============================================================

ALTER TABLE public.chunks
  ADD COLUMN book_id             uuid          REFERENCES public.books(book_id) ON DELETE CASCADE,
  ADD COLUMN token_count         integer,
  ADD COLUMN embedding           vector(1536),
  ADD COLUMN embedding_metadata  jsonb         NOT NULL DEFAULT '{}';


-- ============================================================
-- STEP 5: Migrate existing embedding data into chunks
-- Safe no-op if the embeddings table is empty (Sprint 0 state).
-- Assumes one-to-one: one embedding row per chunk.
-- ============================================================

UPDATE public.chunks ck
SET
  embedding          = e.vector,
  embedding_metadata = e.metadata
FROM public.embeddings e
WHERE e.chunk_id = ck.chunk_id;


-- ============================================================
-- STEP 5: Backfill chunks.book_id from chapters
-- ============================================================

UPDATE public.chunks ck
SET book_id = c.book_id
FROM public.chapters c
WHERE c.chapter_id = ck.chapter_id;


-- ============================================================
-- STEP 6: Drop the embeddings table
-- Cascades: HNSW index on embeddings.vector, all RLS policies,
-- and the FK index on embeddings.chunk_id are all dropped.
-- ============================================================

DROP TABLE public.embeddings;


-- ============================================================
-- STEP 7: HNSW index on chunks.embedding (inline)
-- Replaces the dropped index that was on embeddings.vector.
-- ============================================================

CREATE INDEX ON public.chunks USING hnsw (embedding vector_cosine_ops);


-- ============================================================
-- STEP 8: RLS — enable and add policies for books table
-- ============================================================

ALTER TABLE public.books ENABLE ROW LEVEL SECURITY;

CREATE POLICY "books: select own"
  ON public.books FOR SELECT
  USING (user_id = auth.uid());

CREATE POLICY "books: insert own"
  ON public.books FOR INSERT
  WITH CHECK (user_id = auth.uid());

CREATE POLICY "books: update own"
  ON public.books FOR UPDATE
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

CREATE POLICY "books: delete own"
  ON public.books FOR DELETE
  USING (user_id = auth.uid());


-- ============================================================
-- END OF MIGRATION
-- ============================================================
