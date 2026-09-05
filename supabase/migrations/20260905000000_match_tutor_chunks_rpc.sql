-- ============================================================
-- TransformED AI — Migration: match_tutor_chunks RPC
-- Migration: 20260905000000_match_tutor_chunks_rpc.sql
-- Story 4-28 (Phase 2, P2-1) — Tutor Q&A real backend
--
-- Adds a single Postgres function performing the pgvector cosine-similarity
-- top-K search the tutor Q&A endpoint needs, scoped to one chapter (falling
-- back to the whole book when a lesson has no chapter_id) — never
-- corpus-wide across every book. Chunks table + HNSW index already exist
-- (20260625000000_chunks_inline_embedding.sql); this migration adds no new
-- columns or tables, only the search function.
--
-- Called via `supabase.rpc("match_tutor_chunks", {...}).execute()`, the
-- same RPC-call convention already used by
-- `increment_learner_dna_session_count` (dna_fusion.py) and
-- content/pipeline/graph.py's own `.rpc(...)` call.
-- ============================================================

CREATE OR REPLACE FUNCTION public.match_tutor_chunks(
  query_embedding vector(1536),
  p_chapter_id    uuid DEFAULT NULL,
  p_book_id       uuid DEFAULT NULL,
  p_match_count   integer DEFAULT 5
)
RETURNS TABLE (
  chunk_id   uuid,
  content    text,
  similarity double precision
)
LANGUAGE sql
STABLE
AS $$
  -- 1 - cosine_distance = cosine_similarity (pgvector's `<=>` operator
  -- returns distance, not similarity — this repo's own callers want a
  -- similarity score for the relevance-gate threshold comparison, so the
  -- conversion happens here, once, not re-derived at every call site).
  SELECT
    c.chunk_id,
    c.content,
    1 - (c.embedding <=> query_embedding) AS similarity
  FROM public.chunks c
  WHERE c.embedding IS NOT NULL
    -- Scoped retrieval (never corpus-wide): prefer chapter_id when given: a
    -- lesson's own chapter is the tightest, most relevant scope. Fall back
    -- to book_id only when chapter_id is null (lessons.chapter_id is a
    -- nullable FK, 20260803000000_chapters_book_scoped.sql) — never both
    -- NULL in a real call; the service layer resolves at least one before
    -- calling this function.
    AND (
      (p_chapter_id IS NOT NULL AND c.chapter_id = p_chapter_id)
      OR (p_chapter_id IS NULL AND p_book_id IS NOT NULL AND c.book_id = p_book_id)
    )
  ORDER BY c.embedding <=> query_embedding
  LIMIT p_match_count;
$$;

-- RLS note: this is a SECURITY INVOKER function (the default — no SECURITY
-- DEFINER clause) reading only public.chunks, a table with no per-user RLS
-- restriction (chunks belong to books, not directly to users; every
-- authenticated caller may already read any chunk's content via the
-- existing generation pipeline's own reads). No new RLS policy needed.

COMMENT ON FUNCTION public.match_tutor_chunks IS
  'Story 4-28 — pgvector cosine-similarity top-K chunk search for tutor Q&A retrieval, scoped to one chapter (or book as fallback), never corpus-wide.';
