-- ============================================================
-- DPDP user_consents — unique constraint per consent event
-- Migration: 20260805000000_user_consents_unique_constraint.sql
-- Applied: 2026-08-05
-- Story: 3-32 (D29 fix — consent write endpoint)
-- ============================================================
-- Prevents duplicate consent rows for the same user/type/version.
-- The Story 3-32 service uses INSERT-first idempotency: it tries
-- the INSERT, and on a unique violation it falls back to a SELECT
-- of the existing row. Without this constraint, two concurrent
-- requests from the same user (e.g. double-click) could both pass
-- the application-level check and create duplicate rows.
-- ============================================================

ALTER TABLE public.user_consents
  ADD CONSTRAINT user_consents_unique_per_policy
  UNIQUE (user_id, consent_type, policy_version);

-- ============================================================
-- END OF MIGRATION
-- ============================================================
