-- Story F2-2: Add score_source flag to teachback_attempts.
-- DEFAULT 'llm' is correct for all pre-existing rows: every row written before
-- this migration was produced by the LLM path (skip = no row; fallback = 502,
-- no row written either).

ALTER TABLE public.teachback_attempts
  ADD COLUMN score_source TEXT NOT NULL DEFAULT 'llm'
    CHECK (score_source IN ('llm', 'fallback', 'skipped'));
