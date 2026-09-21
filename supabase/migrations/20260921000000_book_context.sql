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
    book_id              UUID         NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    user_id              UUID         NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    -- §4.2 field 1: "Why did you upload this book/PDF?"
    why_uploaded         TEXT,
    -- §4.2 field 2: "What do you want to achieve from it?"
    what_to_achieve      TEXT,
    -- §4.2 field 3: "Complete book or selected chapters?" — "complete" | "selected" | free text
    complete_or_selected TEXT,
    -- §4.2 field 4: "Which sections or topics are most important or difficult for you?"
    important_sections   TEXT,
    -- §4.2 field 5: "What is your deadline, and how much depth do you want?"
    deadline_and_depth   TEXT,
    -- §4.2 field 6: "Should we follow the document exactly, or reorganize it for optimal learning?"
    follow_or_reorganize TEXT,
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
