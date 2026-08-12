-- D72: Brand rename "TransformED" → "HIE" in learner_dna.profile_text.
--
-- DPDP_DISCLAIMER and ONBOARDING_PROFILE_SYSTEM_PROMPT in prompts.py are fixed
-- in code (Story 3-54). This migration backfills existing rows where GPT-4o-mini
-- already echoed the old brand into profile_text at onboarding time.
--
-- Uses REPLACE() which is non-destructive: rows without "TransformED" are
-- unchanged (LIKE guard prevents a full-table write for no-op rows).
-- Safe to run multiple times (idempotent: REPLACE on a string that no longer
-- contains the target is a no-op).

UPDATE learner_dna
SET    profile_text = REPLACE(profile_text, 'TransformED', 'HIE')
WHERE  profile_text LIKE '%TransformED%';
