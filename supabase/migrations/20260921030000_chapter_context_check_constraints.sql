-- Story S5-3 BMAD fix: add CHECK constraints on MCQ columns in chapter_context.
-- Prevents unknown enum values reaching the prompt formatter (_format_chapter_context_block).
-- Separate migration because 20260921010000 was already applied to CSS_HIE.

ALTER TABLE chapter_context
    ADD CONSTRAINT chapter_context_depth_duration_check
        CHECK (depth_duration IS NULL OR depth_duration IN (
            'quick_15_20m', 'standard_30_45m', 'deep_60_90m', 'mastery_multi', 'ai_decide'
        ));

ALTER TABLE chapter_context
    ADD CONSTRAINT chapter_context_learning_need_check
        CHECK (learning_need IS NULL OR learning_need IN (
            'examples_analogies', 'formulas_derivations', 'diagrams_visuals',
            'practice_questions', 'adaptive_mix'
        ));
