-- Story 235: 30-question onboarding redesign.
--
-- New table for the 30 raw onboarding answers, replacing onboarding_responses as the
-- write target for the redesigned form. NOT an alteration of onboarding_responses --
-- that table is part of the frozen 20260611000000_initial_schema.sql and is never
-- touched. onboarding_responses's columns (response_value integer NOT NULL,
-- dimension_tag CHECK IN ('cognitive','emotional','self_direction')) cannot hold
-- free-text one-liner answers or the new question taxonomy, so a new table is
-- required rather than reused.
--
-- response_text doubles for MCQ's selected option text (matching onboarding_responses'
-- own selected_text convention) and one-liner free text -- never both on the same
-- row for a given format, enforced by the API's Pydantic model_validator, not a DB
-- CHECK (the API is the only writer).

CREATE TABLE public.onboarding_answers_v2 (
  id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          uuid        NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  question_id      text        NOT NULL,
  format           text        NOT NULL CHECK (format IN ('mcq', 'one_liner', 'true_false')),
  selected_index   integer,                    -- set only when format = 'mcq'
  response_text    text,                       -- set for 'mcq' (option text) and 'one_liner'
  response_bool    boolean,                    -- set only when format = 'true_false'
  response_time_ms integer,
  created_at       timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT onboarding_answers_v2_user_question_unique UNIQUE (user_id, question_id)
);

-- RLS: mirrors onboarding_responses' own enablement + 4 own-row policies exactly
-- (20260611000000_initial_schema.sql:333,726-741). CLAUDE.md is unconditional here:
-- "RLS on ALL Supabase tables -- users read only their own data."
ALTER TABLE public.onboarding_answers_v2 ENABLE ROW LEVEL SECURITY;

CREATE POLICY "onboarding_answers_v2: select own"
  ON public.onboarding_answers_v2 FOR SELECT
  USING (user_id = auth.uid());

CREATE POLICY "onboarding_answers_v2: insert own"
  ON public.onboarding_answers_v2 FOR INSERT
  WITH CHECK (user_id = auth.uid());

CREATE POLICY "onboarding_answers_v2: update own"
  ON public.onboarding_answers_v2 FOR UPDATE
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

CREATE POLICY "onboarding_answers_v2: delete own"
  ON public.onboarding_answers_v2 FOR DELETE
  USING (user_id = auth.uid());
