-- ============================================================
-- Migration: 20260703010000_add_analytics_consent.sql
-- Story 3-22: DPDP Act 2023 compliance for PostHog behavioral events
-- Applied: pending (requires manual apply via Supabase dashboard or CLI)
-- ============================================================
-- Adds analytics_consent column to public.users.
-- Until a user explicitly grants consent (set to TRUE via the consent UI),
-- PostHog behavioral events (quiz_accuracy, ces_contribution, score) are
-- suppressed at the posthog_client.capture_event() layer.
-- Default FALSE = safe: no events sent until consent is granted.
-- ============================================================

ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS analytics_consent BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN public.users.analytics_consent IS
  'User has explicitly consented to behavioral analytics data collection '
  '(quiz scores, CES contributions, teachback scores forwarded to PostHog). '
  'Required under DPDP Act 2023 before any performance metrics are transferred '
  'to a third-party analytics processor. Default FALSE = no events sent.';
