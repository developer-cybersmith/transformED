-- Story S5-3: Chapter context form (§4.3 — 5 questions per session)
-- Stores per-(chapter, user) answers collected just before lesson generation.
-- Pattern mirrors book_context (20260921000000_book_context.sql).

CREATE TABLE IF NOT EXISTS chapter_context (
    id                 UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    chapter_id         UUID         NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    user_id            UUID         NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    -- Q41 MCQ: how deep + how long for this specific chapter
    -- values: quick_15_20m | standard_30_45m | deep_60_90m | mastery_multi | ai_decide
    depth_duration     TEXT,
    -- Q42 MCQ: what the student needs most in this lesson
    -- values: examples_analogies | formulas_derivations | diagrams_visuals | practice_questions | adaptive_mix
    learning_need      TEXT,
    -- Q43 one-liner: specific doubt or topic the student wants clarified
    specific_doubt     TEXT,
    -- Q44 one-liner: goal by lesson end + topics to skip
    goal_and_skip      TEXT,
    -- Q45 T/F: student confirms prerequisites are complete
    prerequisites_done BOOLEAN,
    updated_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (chapter_id, user_id)
);

-- RLS: students read/write only their own rows. No DELETE: rows are upserted, not deleted.
ALTER TABLE chapter_context ENABLE ROW LEVEL SECURITY;

CREATE POLICY "chapter_context_select_own"
    ON chapter_context FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "chapter_context_insert_own"
    ON chapter_context FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "chapter_context_update_own"
    ON chapter_context FOR UPDATE
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);
