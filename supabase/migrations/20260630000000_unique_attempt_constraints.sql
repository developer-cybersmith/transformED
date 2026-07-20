-- Migration: 20260630000000_unique_attempt_constraints.sql
-- Adds UNIQUE constraints to prevent duplicate attempt rows.
-- NEVER apply autonomously. User runs: supabase db push
-- Depends on Story 3-12 (attempt_number dynamic) being merged first.

ALTER TABLE quiz_attempts
  ADD CONSTRAINT uq_quiz_attempt
  UNIQUE (session_id, question_id, attempt_number);

ALTER TABLE teachback_attempts
  ADD CONSTRAINT uq_teachback_attempt
  UNIQUE (session_id, segment_id, attempt_number);
