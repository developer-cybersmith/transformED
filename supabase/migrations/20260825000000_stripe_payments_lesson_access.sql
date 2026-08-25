-- ============================================================
-- Stripe Checkout Payments — lesson_access + stripe_events
-- Migration: 20260825000000_stripe_payments_lesson_access.sql
-- WARNING: Migrations are NEVER modified once applied.
-- Story: 5-3 / S4-3 (Sprint 4 — Stripe Checkout integration)
-- ============================================================
-- lesson_access holds each user's spendable lesson-credit balance.
-- stripe_events is the webhook idempotency ledger — its PRIMARY KEY on
-- stripe_event_id IS the durable dedup guarantee (AC5): redelivering the
-- same Stripe event id can never grant a second credit, with no
-- application-level cache or SELECT-then-INSERT check involved.
-- ============================================================


-- ============================================================
-- TABLE: lesson_access
-- One row per user. Written ONLY by the service-role client (webhook
-- credit grant, generation-time credit spend) — no direct student write
-- path exists at all (AC7).
-- ============================================================

CREATE TABLE public.lesson_access (
  user_id       uuid        PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
  lesson_credits integer    NOT NULL DEFAULT 0 CHECK (lesson_credits >= 0),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER lesson_access_set_updated_at
  BEFORE UPDATE ON public.lesson_access
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

ALTER TABLE public.lesson_access ENABLE ROW LEVEL SECURITY;

-- AC7: the ONLY policy is SELECT-own. Deliberately no INSERT/UPDATE/DELETE
-- policy for authenticated/anon — every write happens server-side via the
-- service-role client (which bypasses RLS entirely, as it does everywhere
-- else in this codebase), so a student can never grant themselves credits
-- by writing their own row.
CREATE POLICY "lesson_access: select own"
  ON public.lesson_access FOR SELECT
  USING (user_id = auth.uid());


-- ============================================================
-- TABLE: stripe_events
-- Internal webhook idempotency ledger. Never read by a user-facing route —
-- zero RLS policies for authenticated/anon (service-role bypasses RLS).
-- ============================================================

CREATE TABLE public.stripe_events (
  stripe_event_id   text        PRIMARY KEY,
  stripe_session_id text        NOT NULL,
  event_type        text        NOT NULL,
  processed_at      timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.stripe_events ENABLE ROW LEVEL SECURITY;
-- No policies: zero access for authenticated/anon by default once RLS is
-- enabled with no permissive policy defined.


-- ============================================================
-- RPC: grant_lesson_credits
-- Atomic INSERT ... ON CONFLICT DO UPDATE — same shape as
-- increment_learner_dna_session_count (20260813000001), which replaced a
-- Python read-modify-write on a shared counter (D74) with exactly this
-- pattern. Two concurrent purchases for the same user both land correctly.
-- ============================================================

CREATE OR REPLACE FUNCTION public.grant_lesson_credits(p_user_id uuid, p_credits integer)
RETURNS void
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $$
BEGIN
  INSERT INTO public.lesson_access (user_id, lesson_credits)
  VALUES (p_user_id, p_credits)
  ON CONFLICT (user_id) DO UPDATE
    SET lesson_credits = public.lesson_access.lesson_credits + excluded.lesson_credits,
        updated_at = now();
END;
$$;

REVOKE EXECUTE ON FUNCTION public.grant_lesson_credits(uuid, integer) FROM public;
REVOKE EXECUTE ON FUNCTION public.grant_lesson_credits(uuid, integer) FROM anon;
REVOKE EXECUTE ON FUNCTION public.grant_lesson_credits(uuid, integer) FROM authenticated;
GRANT  EXECUTE ON FUNCTION public.grant_lesson_credits(uuid, integer) TO service_role;


-- ============================================================
-- RPC: decrement_lesson_credit
-- Single conditional UPDATE ... WHERE lesson_credits > 0. This is the
-- shape D45's own register entry names as the TOCTOU race to avoid: no
-- Python-side "SELECT credits, then IF credits > 0: UPDATE" exists anywhere
-- in this story. Returns whether a row was actually affected (FOUND).
-- ============================================================

CREATE OR REPLACE FUNCTION public.decrement_lesson_credit(p_user_id uuid)
RETURNS boolean
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $$
BEGIN
  UPDATE public.lesson_access
  SET lesson_credits = lesson_credits - 1,
      updated_at = now()
  WHERE user_id = p_user_id
    AND lesson_credits > 0;
  RETURN FOUND;
END;
$$;

REVOKE EXECUTE ON FUNCTION public.decrement_lesson_credit(uuid) FROM public;
REVOKE EXECUTE ON FUNCTION public.decrement_lesson_credit(uuid) FROM anon;
REVOKE EXECUTE ON FUNCTION public.decrement_lesson_credit(uuid) FROM authenticated;
GRANT  EXECUTE ON FUNCTION public.decrement_lesson_credit(uuid) TO service_role;


-- ============================================================
-- RPC: record_stripe_event_if_new
-- AC5's actual enforcement mechanism. INSERT ... ON CONFLICT (stripe_event_id)
-- DO NOTHING, returning whether THIS call's insert affected a row — a
-- redelivered event id (Stripe's own documented retry behavior on anything
-- but a 2xx) returns false and the caller grants no credit a second time.
-- Deliberately a dedicated RPC rather than a PostgREST-level upsert call:
-- a PostgREST `.upsert()` through the Supabase Python client was judged
-- (not independently benchmarked/proven in this session) likely to make
-- "did this specific call insert a new row" harder to distinguish
-- reliably from "already existed" depending on Prefer-header/resolution
-- settings; a dedicated RPC with an explicit RETURN FOUND removes that
-- ambiguity outright regardless of whether the PostgREST behavior itself
-- would have worked.
--
-- Used for every event type EXCEPT a real credit grant on
-- checkout.session.completed, which instead calls
-- record_stripe_event_and_grant_credits below — see that function's own
-- comment for why the two steps must NOT be split into two separate RPC
-- calls from Python.
-- ============================================================

CREATE OR REPLACE FUNCTION public.record_stripe_event_if_new(
  p_event_id text,
  p_session_id text,
  p_event_type text
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $$
BEGIN
  INSERT INTO public.stripe_events (stripe_event_id, stripe_session_id, event_type)
  VALUES (p_event_id, p_session_id, p_event_type)
  ON CONFLICT (stripe_event_id) DO NOTHING;
  RETURN FOUND;
END;
$$;

REVOKE EXECUTE ON FUNCTION public.record_stripe_event_if_new(text, text, text) FROM public;
REVOKE EXECUTE ON FUNCTION public.record_stripe_event_if_new(text, text, text) FROM anon;
REVOKE EXECUTE ON FUNCTION public.record_stripe_event_if_new(text, text, text) FROM authenticated;
GRANT  EXECUTE ON FUNCTION public.record_stripe_event_if_new(text, text, text) TO service_role;


-- ============================================================
-- RPC: record_stripe_event_and_grant_credits
-- Review Finding (Story 5-3, code review 2026-08-26) — the ORIGINAL design
-- called record_stripe_event_if_new and grant_lesson_credits as two
-- SEPARATE RPC calls from Python. That is a real defect, not a style
-- choice: the first call commits durably on its own; if the second call
-- then fails for ANY reason (a transient DB hiccup, an FK violation
-- because the user row was deleted between checkout and webhook
-- delivery), the exception propagates, but the event is now already
-- marked processed. Stripe's automatic retry of that SAME event_id then
-- finds record_stripe_event_if_new returning false and acknowledges 200
-- as an idempotent no-op — the student paid, Stripe considers the
-- webhook delivered, and the credit is permanently gone with no further
-- error signal. A `silent-wrong-result` scale finding that can never be
-- dismissed per docs/SCALE-CONTRACT.md.
--
-- Fixed by making both steps ONE plpgsql function body — a single
-- Postgres function call is one implicit transaction, so a failure
-- anywhere inside it (including the credit upsert) rolls back the
-- stripe_events insert too. Either both steps commit, or neither does;
-- Stripe's retry then sees a genuinely-unprocessed event and can
-- succeed on a later attempt instead of being told "already handled."
-- ============================================================

CREATE OR REPLACE FUNCTION public.record_stripe_event_and_grant_credits(
  p_event_id text,
  p_session_id text,
  p_event_type text,
  p_user_id uuid,
  p_credits integer
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $$
BEGIN
  INSERT INTO public.stripe_events (stripe_event_id, stripe_session_id, event_type)
  VALUES (p_event_id, p_session_id, p_event_type)
  ON CONFLICT (stripe_event_id) DO NOTHING;

  IF NOT FOUND THEN
    -- Already processed by an earlier delivery of this same event_id —
    -- no-op, do NOT grant a second time. The stripe_events insert above
    -- did nothing, so there is nothing to roll back either.
    RETURN false;
  END IF;

  INSERT INTO public.lesson_access (user_id, lesson_credits)
  VALUES (p_user_id, p_credits)
  ON CONFLICT (user_id) DO UPDATE
    SET lesson_credits = public.lesson_access.lesson_credits + excluded.lesson_credits,
        updated_at = now();

  RETURN true;
END;
$$;

REVOKE EXECUTE ON FUNCTION public.record_stripe_event_and_grant_credits(text, text, text, uuid, integer) FROM public;
REVOKE EXECUTE ON FUNCTION public.record_stripe_event_and_grant_credits(text, text, text, uuid, integer) FROM anon;
REVOKE EXECUTE ON FUNCTION public.record_stripe_event_and_grant_credits(text, text, text, uuid, integer) FROM authenticated;
GRANT  EXECUTE ON FUNCTION public.record_stripe_event_and_grant_credits(text, text, text, uuid, integer) TO service_role;
