-- ============================================================
-- Migration: 20260826000001_lesson_price_paise.sql
-- Applied: 2026-08-26
-- Purpose: Add server-side price to lessons table so the payment
--          backend can enforce the canonical price rather than
--          trusting the client-supplied amount (S4-1 patch 1).
-- WARNING: Migrations are NEVER modified once applied.
-- ============================================================

ALTER TABLE public.lessons
  ADD COLUMN price_paise integer NOT NULL DEFAULT 0;

COMMENT ON COLUMN public.lessons.price_paise IS
  'Lesson price in Indian paise (INR × 100). 0 = free. '
  'Set by admin; used server-side to create Razorpay orders — '
  'the client-supplied amount is never trusted.';
