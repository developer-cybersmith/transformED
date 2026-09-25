-- Story 235: 30-question onboarding redesign.
--
-- Adds 5 new columns to learner_dna for the Tier B Penta-Intelligence baseline
-- (Q16-Q20 of the redesigned onboarding form -- the PDF's own "(scored)" section,
-- with a real answer key). Additive alongside the existing 9 behavioral dimension
-- columns, which stay untouched and still session-EMA-driven (dna_fusion.py).
--
-- learner_dna's own CREATE TABLE lives in the frozen 20260611000000_initial_schema.sql
-- and is not touched -- this follows the exact precedent
-- 20260813000001_dna_session_count_atomic_increment.sql already set for building on
-- top of that same frozen table via a new migration.
--
-- All 5 nullable: computed once at onboarding time, never regenerated afterward in
-- this story's scope (unlike the 9 behavioral columns, which are continuously
-- EMA-updated per session).

ALTER TABLE public.learner_dna
  ADD COLUMN penta_iq  numeric(5,2) CHECK (penta_iq  >= 0 AND penta_iq  <= 100),
  ADD COLUMN penta_eq  numeric(5,2) CHECK (penta_eq  >= 0 AND penta_eq  <= 100),
  ADD COLUMN penta_sq  numeric(5,2) CHECK (penta_sq  >= 0 AND penta_sq  <= 100),
  ADD COLUMN penta_ctq numeric(5,2) CHECK (penta_ctq >= 0 AND penta_ctq <= 100),
  ADD COLUMN penta_rrq numeric(5,2) CHECK (penta_rrq >= 0 AND penta_rrq <= 100);
