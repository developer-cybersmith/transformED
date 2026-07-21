-- Story 2-2 (Learner Mode infra, AC-2): content-depth tier on lessons.
--
-- Tier drives slide count / content depth in lesson_planner (S2-7) and
-- slide_generator (S2-8) — see S2-LM4/S2-LM5 for the generation logic itself;
-- this migration only adds the persisted column those stories will read.
--
-- Additive, backward-compatible: DEFAULT 'T2' backfills every existing row
-- with no manual data migration step required.

ALTER TABLE public.lessons
  ADD COLUMN tier text NOT NULL DEFAULT 'T2' CHECK (tier IN ('T1', 'T2', 'T3'));
