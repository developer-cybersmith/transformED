-- Story 5-15 — DB CHECK constraints on free-text context fields
-- Fixes D178 (book_context) and D190 (chapter_context).
--
-- Pydantic already enforces max_length=500 at the API boundary for all five
-- columns below. These constraints mirror that limit at the database layer so
-- that a direct Supabase client write, a migration backfill, or a future API
-- refactor cannot bypass the 500-char contract silently.
--
-- All five ALTER TABLE statements are additive: they add no new columns and
-- reject only values that Pydantic would already have rejected. No existing row
-- can violate them (the Pydantic validators have been live since both tables
-- were created).
--
-- Constraint naming convention: {table}_{column}_len — identifiable in Postgres
-- error messages without consulting this migration file.

-- D178: book_context text field constraints
ALTER TABLE book_context
    ADD CONSTRAINT book_context_motivation_len
        CHECK (char_length(motivation) <= 500),
    ADD CONSTRAINT book_context_end_goal_len
        CHECK (char_length(end_goal) <= 500),
    ADD CONSTRAINT book_context_feared_section_len
        CHECK (char_length(feared_section) <= 500);

-- D190: chapter_context text field constraints
ALTER TABLE chapter_context
    ADD CONSTRAINT chapter_context_specific_doubt_len
        CHECK (char_length(specific_doubt) <= 500),
    ADD CONSTRAINT chapter_context_goal_and_skip_len
        CHECK (char_length(goal_and_skip) <= 500);
