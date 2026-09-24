-- Story S5-1 (Issue #231): per-book personalization context.
--
-- One row per (book_id, user_id) pair, capturing the learner's intent for
-- a specific book. Six fields map exactly to §4.2 of
-- AI_Learning_Product_Final_Strategy.pdf (see docs/proposals/2026-09-19-
-- platform-changes-scope.md). Fully optional — no field has NOT NULL; a
-- student who never fills the form simply has no row here, and callers must
-- treat a missing row as "no context" rather than an error.
--
-- Upsert semantics: ON CONFLICT (book_id, user_id) DO UPDATE SET ... —
-- atomic at the Postgres level, so concurrent submits from the same user
-- cannot produce duplicate rows and no application-level check-then-act is
-- needed (AC6, Scale & Load Q6 in the story).
--
-- RLS: service-role client in API code, so RLS doesn't filter automatically
-- in the FastAPI process. The API layer enforces ownership via _fetch_owned_book
-- (router.py) before reading/writing this table. RLS policies below still
-- apply for any direct Supabase client access (e.g. frontend SDK calls).

CREATE TABLE IF NOT EXISTS book_context (
    id                   UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    book_id              UUID         NOT NULL REFERENCES books(book_id) ON DELETE CASCADE,
    user_id              UUID         NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    -- §4.2 Q31 MCQ: "Why have you uploaded this book/PDF?"
    -- values: exam_prep | project_job | deep_mastery | quick_reference | recommended_reading
    purpose              TEXT,
    -- §4.2 Q32 MCQ: "What do you want covered?"
    -- values: complete_book | selected_chapters | difficult_sections | exam_relevant | ai_decide
    coverage_scope       TEXT,
    -- §4.2 Q33 MCQ: "Which parts of this book do you expect to be hardest for you?"
    -- values: theory_heavy | numerical_formula | case_studies | dense_language | dont_know
    expected_difficulty  TEXT,
    -- §4.2 Q34 MCQ: "Your deadline and depth requirement:"
    -- values: urgent_2wk | one_month | two_three_months | no_deadline | key_insights_only
    deadline_depth       TEXT,
    -- §4.2 Q35 MCQ: "Should the tutor follow the book exactly, or reorganise it for learning?"
    -- values: follow_exactly | reorganise_by_difficulty | reorganise_by_goal | hybrid | ai_choose
    structure_preference TEXT,
    -- §4.2 Q36 one-liner: "Why do you want to learn from this specific book — in one honest line?"
    motivation           TEXT,
    -- §4.2 Q37 one-liner: "What is the end goal once you finish learning this book?"
    end_goal             TEXT,
    -- §4.2 Q38 one-liner: "Which section or topic in this book are you most worried about, and why?"
    feared_section       TEXT,
    -- §4.2 Q39 T/F: "I have tried to read this book before and stopped midway."
    prior_attempt        BOOLEAN,
    -- §4.2 Q40 T/F: "I can clearly picture how I will use this knowledge in real life."
    outcome_clarity      BOOLEAN,
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (book_id, user_id)
);

-- One row per learner per book — bounded by definition, no list query needed.
CREATE INDEX IF NOT EXISTS book_context_user_id_idx ON book_context (user_id);

-- RLS policies (defence in depth — the API layer also enforces ownership).
ALTER TABLE book_context ENABLE ROW LEVEL SECURITY;

CREATE POLICY book_context_select ON book_context
    FOR SELECT USING (user_id = auth.uid());

CREATE POLICY book_context_insert ON book_context
    FOR INSERT WITH CHECK (user_id = auth.uid());

CREATE POLICY book_context_update ON book_context
    FOR UPDATE USING (user_id = auth.uid());

CREATE POLICY book_context_delete ON book_context
    FOR DELETE USING (user_id = auth.uid());
