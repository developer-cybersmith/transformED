-- ============================================================
-- Razorpay Payments — Story 4-1
-- Migration: 20260826000000_razorpay_payments.sql
-- Applied: 2026-08-26
-- WARNING: Migrations are NEVER modified once applied.
-- ============================================================


-- ============================================================
-- TABLE: lesson_access
-- Tracks verified Razorpay payment.captured events.
-- razorpay_payment_id UNIQUE constraint enforces idempotency
-- at the DB level — concurrent webhook redeliveries cannot
-- double-credit (same class of gap as D45).
-- ============================================================

CREATE TABLE public.lesson_access (
  id                   uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id              uuid        NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  lesson_id            uuid        NOT NULL REFERENCES public.lessons(lesson_id) ON DELETE CASCADE,
  razorpay_payment_id  text        NOT NULL,
  razorpay_order_id    text        NOT NULL,
  amount_paise         integer     NOT NULL,
  currency             text        NOT NULL DEFAULT 'INR',
  status               text        NOT NULL DEFAULT 'captured'
                                   CHECK (status IN ('captured', 'refunded')),
  created_at           timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT lesson_access_razorpay_payment_id_key UNIQUE (razorpay_payment_id)
);

-- Index: fast lookup by user for "has this user paid for this lesson?"
CREATE INDEX lesson_access_user_lesson_idx
  ON public.lesson_access (user_id, lesson_id);


-- ============================================================
-- RLS: users read only their own lesson_access rows
-- ============================================================

ALTER TABLE public.lesson_access ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users read their own lesson access"
  ON public.lesson_access
  FOR SELECT
  USING (auth.uid() = user_id);

-- Service role (webhook handler) can insert; no user-facing insert.
CREATE POLICY "Service role inserts lesson access"
  ON public.lesson_access
  FOR INSERT
  WITH CHECK (true);
