-- ============================================================
-- DPDP Act 2023 Compliance — user_consents Audit Table
-- Migration: 20260702000000_dpdp_user_consents.sql
-- Applied: 2026-07-02
-- WARNING: Migrations are NEVER modified once applied.
-- Story: 3-17 (Sprint 1 production readiness — DPDP consent gap)
-- ============================================================
-- Addresses the consent gap in CLAUDE.md §18:
--   "users.attention_consent boolean is insufficient — a user_consents
--    audit table is required before any attention data is collected."
-- ============================================================


-- ============================================================
-- TABLE: user_consents
-- Immutable audit trail of user consent events.
-- INSERT-only (no UPDATE/DELETE) — DPDP Act 2023 requires
-- consent records to be permanently auditable.
-- ============================================================

CREATE TABLE public.user_consents (
  id             uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        uuid        NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  consent_type   text        NOT NULL
                             CHECK (consent_type IN ('attention_tracking', 'learner_dna')),
  policy_version text        NOT NULL,
  consented_at   timestamptz NOT NULL DEFAULT now(),
  created_at     timestamptz NOT NULL DEFAULT now()
);


-- ============================================================
-- INDEXES
-- ============================================================

CREATE INDEX ON public.user_consents (user_id);
CREATE INDEX ON public.user_consents (user_id, consent_type);


-- ============================================================
-- ROW LEVEL SECURITY
-- INSERT + SELECT only — records are immutable once created.
-- No UPDATE or DELETE policy is intentional (DPDP compliance).
-- ============================================================

ALTER TABLE public.user_consents ENABLE ROW LEVEL SECURITY;

CREATE POLICY "user_consents: select own"
  ON public.user_consents FOR SELECT
  USING (user_id = auth.uid());

CREATE POLICY "user_consents: insert own"
  ON public.user_consents FOR INSERT
  WITH CHECK (user_id = auth.uid());


-- ============================================================
-- TRIGGER: sync users.attention_consent from user_consents
-- When a user grants 'attention_tracking' consent, the
-- denormalized boolean on users is set to true.
-- The boolean is the fast-path RLS check; user_consents is
-- the authoritative audit source.
-- SECURITY DEFINER required: the INSERT fires in the user's
-- session context; the UPDATE on users must bypass RLS
-- re-evaluation inside the trigger body.
-- ============================================================

CREATE OR REPLACE FUNCTION public.sync_attention_consent_on_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  IF NEW.consent_type = 'attention_tracking' THEN
    UPDATE public.users
       SET attention_consent = true
     WHERE id = NEW.user_id;
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER user_consents_sync_attention
  AFTER INSERT ON public.user_consents
  FOR EACH ROW
  EXECUTE FUNCTION public.sync_attention_consent_on_insert();


-- ============================================================
-- UPDATE attention_events INSERT RLS — dual DPDP consent check
-- The existing policy only checked users.attention_consent = true
-- (a boolean that could be set without an audit trail).
-- The new policy adds a second condition: the user must have an
-- active user_consents row for 'attention_tracking'. Both must
-- be true — belt-and-suspenders DPDP compliance.
-- ============================================================

DROP POLICY IF EXISTS "attention_events: insert own" ON public.attention_events;

CREATE POLICY "attention_events: insert own"
  ON public.attention_events FOR INSERT
  WITH CHECK (
    -- Condition 1: session ownership + fast boolean flag (unchanged)
    EXISTS (
      SELECT 1
      FROM public.sessions s
      JOIN public.users    u ON u.id = s.user_id
      WHERE s.session_id = attention_events.session_id
        AND s.user_id = auth.uid()
        AND u.attention_consent = true
    )
    AND
    -- Condition 2: DPDP audit record must exist (new)
    EXISTS (
      SELECT 1
      FROM public.user_consents uc
      WHERE uc.user_id     = auth.uid()
        AND uc.consent_type = 'attention_tracking'
    )
  );


-- ============================================================
-- END OF MIGRATION
-- ============================================================
