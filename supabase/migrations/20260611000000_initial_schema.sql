-- ============================================================
-- HIE — Sprint 0 Initial Schema
-- Migration: 20260611000000_initial_schema.sql
-- Applied: 2026-06-11
-- WARNING: Migrations are NEVER modified once applied.
-- ============================================================

-- ============================================================
-- REDIS KEY PATTERNS (documentation only)
-- ============================================================
-- lesson:{lesson_id}:status          â†’ string  (generating | ready | failed)
-- lesson:{lesson_id}:content         â†’ string  (JSON-serialised lesson package)
-- job:{job_id}:status                â†’ string  (pending | running | completed | failed)
-- job:{job_id}:node_outputs          â†’ hash    (node_name â†’ JSON output)
-- session:{session_id}:events        â†’ list    (serialised session_event payloads)
-- user:{user_id}:dna                 â†’ string  (JSON-serialised learner_dna row)
-- user:{user_id}:onboarding_done     â†’ string  ("1" once onboarding complete)
-- attention:{session_id}:latest      â†’ string  (JSON-serialised most-recent attention_event)
-- embeddings:search:{hash}           â†’ string  (cached vector search results, TTL 300 s)
-- ============================================================


-- ============================================================
-- EXTENSIONS
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;


-- ============================================================
-- HELPER: updated_at trigger function
-- ============================================================

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;


-- ============================================================
-- HELPER: auto-insert into public.users on auth.users creation
-- ============================================================

CREATE OR REPLACE FUNCTION public.handle_new_auth_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  INSERT INTO public.users (id, email)
  VALUES (NEW.id, NEW.email)
  ON CONFLICT (id) DO NOTHING;
  RETURN NEW;
END;
$$;


-- ============================================================
-- TABLE: users
-- ============================================================

CREATE TABLE public.users (
  id                 uuid        PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email              text        NOT NULL,
  attention_consent  boolean     NOT NULL DEFAULT false,
  created_at         timestamptz NOT NULL DEFAULT now()
);

-- Trigger: auto-create public.users row when auth.users row is inserted
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW
  EXECUTE FUNCTION public.handle_new_auth_user();


-- ============================================================
-- TABLE: lessons
-- ============================================================

CREATE TABLE public.lessons (
  lesson_id        uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          uuid        NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  title            text,
  status           text        NOT NULL DEFAULT 'generating'
                               CHECK (status IN ('generating', 'ready', 'failed')),
  content          jsonb,
  source_file_path text,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);

-- Trigger: keep updated_at current
CREATE TRIGGER lessons_set_updated_at
  BEFORE UPDATE ON public.lessons
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();


-- ============================================================
-- TABLE: lesson_jobs
-- ============================================================

CREATE TABLE public.lesson_jobs (
  job_id        uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
  lesson_id     uuid          NOT NULL REFERENCES public.lessons(lesson_id) ON DELETE CASCADE,
  status        text          NOT NULL DEFAULT 'pending'
                              CHECK (status IN ('pending', 'running', 'completed', 'failed')),
  last_node     text,
  node_outputs  jsonb,
  error         text,
  attempt       integer       NOT NULL DEFAULT 0,
  cost_usd      numeric(10,4) NOT NULL DEFAULT 0,
  started_at    timestamptz,
  completed_at  timestamptz,
  created_at    timestamptz   NOT NULL DEFAULT now()
);


-- ============================================================
-- TABLE: chapters
-- ============================================================

CREATE TABLE public.chapters (
  chapter_id     uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  book_id        uuid        NOT NULL,
  lesson_id      uuid        NOT NULL REFERENCES public.lessons(lesson_id) ON DELETE CASCADE,
  title          text        NOT NULL,
  page_start     integer     NOT NULL,
  page_end       integer     NOT NULL,
  chapter_index  integer     NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now()
);


-- ============================================================
-- TABLE: chunks
-- ============================================================

CREATE TABLE public.chunks (
  chunk_id     uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  chapter_id   uuid        NOT NULL REFERENCES public.chapters(chapter_id) ON DELETE CASCADE,
  section      text,
  page_start   integer,
  page_end     integer,
  content      text        NOT NULL,
  chunk_index  integer     NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now()
);


-- ============================================================
-- TABLE: embeddings
-- ============================================================

CREATE TABLE public.embeddings (
  id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  chunk_id    uuid        NOT NULL REFERENCES public.chunks(chunk_id) ON DELETE CASCADE,
  vector      vector(1536) NOT NULL,
  metadata    jsonb       NOT NULL DEFAULT '{}',
  created_at  timestamptz NOT NULL DEFAULT now()
);


-- ============================================================
-- TABLE: sessions
-- ============================================================

CREATE TABLE public.sessions (
  session_id  uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid         NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  lesson_id   uuid         NOT NULL REFERENCES public.lessons(lesson_id) ON DELETE CASCADE,
  ces_final   numeric(5,2),
  started_at  timestamptz  NOT NULL DEFAULT now(),
  ended_at    timestamptz
);


-- ============================================================
-- TABLE: quiz_attempts
-- ============================================================

CREATE TABLE public.quiz_attempts (
  id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id       uuid        NOT NULL REFERENCES public.sessions(session_id) ON DELETE CASCADE,
  segment_id       text        NOT NULL,
  question_id      text        NOT NULL,
  response_index   integer,
  is_correct       boolean,
  response_time_ms integer,
  attempt_number   integer     NOT NULL DEFAULT 1,
  created_at       timestamptz NOT NULL DEFAULT now()
);


-- ============================================================
-- TABLE: teachback_attempts
-- ============================================================

CREATE TABLE public.teachback_attempts (
  id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id          uuid        NOT NULL REFERENCES public.sessions(session_id) ON DELETE CASCADE,
  segment_id          text        NOT NULL,
  response_text       text        NOT NULL,
  score               integer     CHECK (score >= 0 AND score <= 100),
  feedback_praise     text,
  feedback_correction text,
  concepts_hit        text[]      NOT NULL DEFAULT '{}',
  concepts_missed     text[]      NOT NULL DEFAULT '{}',
  attempt_number      integer     NOT NULL DEFAULT 1,
  created_at          timestamptz NOT NULL DEFAULT now()
);


-- ============================================================
-- TABLE: learner_dna
-- ============================================================

CREATE TABLE public.learner_dna (
  id                   uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id              uuid         NOT NULL UNIQUE REFERENCES public.users(id) ON DELETE CASCADE,
  pattern_recognition  numeric(5,2) CHECK (pattern_recognition  >= 0 AND pattern_recognition  <= 100),
  logical_deduction    numeric(5,2) CHECK (logical_deduction    >= 0 AND logical_deduction    <= 100),
  processing_speed     numeric(5,2) CHECK (processing_speed     >= 0 AND processing_speed     <= 100),
  frustration_tolerance numeric(5,2) CHECK (frustration_tolerance >= 0 AND frustration_tolerance <= 100),
  persistence          numeric(5,2) CHECK (persistence          >= 0 AND persistence          <= 100),
  help_seeking         numeric(5,2) CHECK (help_seeking         >= 0 AND help_seeking         <= 100),
  goal_orientation     numeric(5,2) CHECK (goal_orientation     >= 0 AND goal_orientation     <= 100),
  curiosity_index      numeric(5,2) CHECK (curiosity_index      >= 0 AND curiosity_index      <= 100),
  study_independence   numeric(5,2) CHECK (study_independence   >= 0 AND study_independence   <= 100),
  badge_labels         text[]       NOT NULL DEFAULT '{}',
  profile_text         text,
  session_count        integer      NOT NULL DEFAULT 0,
  last_updated         timestamptz  NOT NULL DEFAULT now()
);


-- ============================================================
-- TABLE: onboarding_responses
-- ============================================================

CREATE TABLE public.onboarding_responses (
  id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          uuid        NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  question_id      text        NOT NULL,
  response_value   integer     NOT NULL,
  response_time_ms integer,
  dimension_tag    text        NOT NULL
                               CHECK (dimension_tag IN ('cognitive', 'emotional', 'self_direction')),
  created_at       timestamptz NOT NULL DEFAULT now()
);


-- ============================================================
-- TABLE: session_events
-- ============================================================

CREATE TABLE public.session_events (
  id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id  uuid        NOT NULL REFERENCES public.sessions(session_id) ON DELETE CASCADE,
  event_type  text        NOT NULL,
  payload     jsonb       NOT NULL DEFAULT '{}',
  created_at  timestamptz NOT NULL DEFAULT now()
);


-- ============================================================
-- TABLE: attention_events
-- ============================================================

CREATE TABLE public.attention_events (
  id               uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id       uuid         NOT NULL REFERENCES public.sessions(session_id) ON DELETE CASCADE,
  gaze_score       numeric(5,2),
  head_pose_score  numeric(5,2),
  blink_rate       numeric(5,2),
  expression_label text,
  behavioral_score numeric(5,2),
  created_at       timestamptz  NOT NULL DEFAULT now()
);


-- ============================================================
-- INDEXES
-- ============================================================

-- Foreign key indexes
CREATE INDEX ON public.lessons           (user_id);
CREATE INDEX ON public.lesson_jobs       (lesson_id);
CREATE INDEX ON public.chapters          (lesson_id);
CREATE INDEX ON public.chapters          (book_id);
CREATE INDEX ON public.chunks            (chapter_id);
CREATE INDEX ON public.embeddings        (chunk_id);
CREATE INDEX ON public.sessions          (user_id);
CREATE INDEX ON public.sessions          (lesson_id);
CREATE INDEX ON public.quiz_attempts     (session_id);
CREATE INDEX ON public.teachback_attempts(session_id);
CREATE INDEX ON public.learner_dna       (user_id);
CREATE INDEX ON public.onboarding_responses(user_id);
CREATE INDEX ON public.session_events    (session_id);
CREATE INDEX ON public.attention_events  (session_id);

-- Status indexes
CREATE INDEX ON public.lessons    (status);
CREATE INDEX ON public.lesson_jobs(status);

-- session_events lookup indexes
CREATE INDEX ON public.session_events(event_type);

-- pgvector HNSW index for approximate nearest-neighbour cosine search
CREATE INDEX ON public.embeddings USING hnsw (vector vector_cosine_ops);


-- ============================================================
-- ROW LEVEL SECURITY â€” enable on all tables
-- ============================================================

ALTER TABLE public.users               ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.lessons             ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.lesson_jobs         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chapters            ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chunks              ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.embeddings          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sessions            ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.quiz_attempts       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.teachback_attempts  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.learner_dna         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.onboarding_responses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.session_events      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.attention_events    ENABLE ROW LEVEL SECURITY;


-- ============================================================
-- RLS POLICIES â€” users
-- ============================================================

CREATE POLICY "users: select own row"
  ON public.users FOR SELECT
  USING (id = auth.uid());

CREATE POLICY "users: insert own row"
  ON public.users FOR INSERT
  WITH CHECK (id = auth.uid());

CREATE POLICY "users: update own row"
  ON public.users FOR UPDATE
  USING (id = auth.uid())
  WITH CHECK (id = auth.uid());

CREATE POLICY "users: delete own row"
  ON public.users FOR DELETE
  USING (id = auth.uid());


-- ============================================================
-- RLS POLICIES â€” lessons
-- ============================================================

CREATE POLICY "lessons: select own"
  ON public.lessons FOR SELECT
  USING (user_id = auth.uid());

CREATE POLICY "lessons: insert own"
  ON public.lessons FOR INSERT
  WITH CHECK (user_id = auth.uid());

CREATE POLICY "lessons: update own"
  ON public.lessons FOR UPDATE
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

CREATE POLICY "lessons: delete own"
  ON public.lessons FOR DELETE
  USING (user_id = auth.uid());


-- ============================================================
-- RLS POLICIES â€” lesson_jobs
-- (join to lessons to confirm ownership)
-- ============================================================

CREATE POLICY "lesson_jobs: select own"
  ON public.lesson_jobs FOR SELECT
  USING (
    EXISTS (
      SELECT 1 FROM public.lessons l
      WHERE l.lesson_id = lesson_jobs.lesson_id
        AND l.user_id = auth.uid()
    )
  );

CREATE POLICY "lesson_jobs: insert own"
  ON public.lesson_jobs FOR INSERT
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM public.lessons l
      WHERE l.lesson_id = lesson_jobs.lesson_id
        AND l.user_id = auth.uid()
    )
  );

CREATE POLICY "lesson_jobs: update own"
  ON public.lesson_jobs FOR UPDATE
  USING (
    EXISTS (
      SELECT 1 FROM public.lessons l
      WHERE l.lesson_id = lesson_jobs.lesson_id
        AND l.user_id = auth.uid()
    )
  );

CREATE POLICY "lesson_jobs: delete own"
  ON public.lesson_jobs FOR DELETE
  USING (
    EXISTS (
      SELECT 1 FROM public.lessons l
      WHERE l.lesson_id = lesson_jobs.lesson_id
        AND l.user_id = auth.uid()
    )
  );


-- ============================================================
-- RLS POLICIES â€” chapters
-- (join through lessons)
-- ============================================================

CREATE POLICY "chapters: select own"
  ON public.chapters FOR SELECT
  USING (
    EXISTS (
      SELECT 1 FROM public.lessons l
      WHERE l.lesson_id = chapters.lesson_id
        AND l.user_id = auth.uid()
    )
  );

CREATE POLICY "chapters: insert own"
  ON public.chapters FOR INSERT
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM public.lessons l
      WHERE l.lesson_id = chapters.lesson_id
        AND l.user_id = auth.uid()
    )
  );

CREATE POLICY "chapters: update own"
  ON public.chapters FOR UPDATE
  USING (
    EXISTS (
      SELECT 1 FROM public.lessons l
      WHERE l.lesson_id = chapters.lesson_id
        AND l.user_id = auth.uid()
    )
  );

CREATE POLICY "chapters: delete own"
  ON public.chapters FOR DELETE
  USING (
    EXISTS (
      SELECT 1 FROM public.lessons l
      WHERE l.lesson_id = chapters.lesson_id
        AND l.user_id = auth.uid()
    )
  );


-- ============================================================
-- RLS POLICIES â€” chunks
-- (join through chapters â†’ lessons)
-- ============================================================

CREATE POLICY "chunks: select own"
  ON public.chunks FOR SELECT
  USING (
    EXISTS (
      SELECT 1
      FROM public.chapters c
      JOIN public.lessons  l ON l.lesson_id = c.lesson_id
      WHERE c.chapter_id = chunks.chapter_id
        AND l.user_id = auth.uid()
    )
  );

CREATE POLICY "chunks: insert own"
  ON public.chunks FOR INSERT
  WITH CHECK (
    EXISTS (
      SELECT 1
      FROM public.chapters c
      JOIN public.lessons  l ON l.lesson_id = c.lesson_id
      WHERE c.chapter_id = chunks.chapter_id
        AND l.user_id = auth.uid()
    )
  );

CREATE POLICY "chunks: update own"
  ON public.chunks FOR UPDATE
  USING (
    EXISTS (
      SELECT 1
      FROM public.chapters c
      JOIN public.lessons  l ON l.lesson_id = c.lesson_id
      WHERE c.chapter_id = chunks.chapter_id
        AND l.user_id = auth.uid()
    )
  );

CREATE POLICY "chunks: delete own"
  ON public.chunks FOR DELETE
  USING (
    EXISTS (
      SELECT 1
      FROM public.chapters c
      JOIN public.lessons  l ON l.lesson_id = c.lesson_id
      WHERE c.chapter_id = chunks.chapter_id
        AND l.user_id = auth.uid()
    )
  );


-- ============================================================
-- RLS POLICIES â€” embeddings
-- (join through chunks â†’ chapters â†’ lessons)
-- ============================================================

CREATE POLICY "embeddings: select own"
  ON public.embeddings FOR SELECT
  USING (
    EXISTS (
      SELECT 1
      FROM public.chunks   ck
      JOIN public.chapters c  ON c.chapter_id = ck.chapter_id
      JOIN public.lessons  l  ON l.lesson_id  = c.lesson_id
      WHERE ck.chunk_id = embeddings.chunk_id
        AND l.user_id = auth.uid()
    )
  );

CREATE POLICY "embeddings: insert own"
  ON public.embeddings FOR INSERT
  WITH CHECK (
    EXISTS (
      SELECT 1
      FROM public.chunks   ck
      JOIN public.chapters c  ON c.chapter_id = ck.chapter_id
      JOIN public.lessons  l  ON l.lesson_id  = c.lesson_id
      WHERE ck.chunk_id = embeddings.chunk_id
        AND l.user_id = auth.uid()
    )
  );

CREATE POLICY "embeddings: update own"
  ON public.embeddings FOR UPDATE
  USING (
    EXISTS (
      SELECT 1
      FROM public.chunks   ck
      JOIN public.chapters c  ON c.chapter_id = ck.chapter_id
      JOIN public.lessons  l  ON l.lesson_id  = c.lesson_id
      WHERE ck.chunk_id = embeddings.chunk_id
        AND l.user_id = auth.uid()
    )
  );

CREATE POLICY "embeddings: delete own"
  ON public.embeddings FOR DELETE
  USING (
    EXISTS (
      SELECT 1
      FROM public.chunks   ck
      JOIN public.chapters c  ON c.chapter_id = ck.chapter_id
      JOIN public.lessons  l  ON l.lesson_id  = c.lesson_id
      WHERE ck.chunk_id = embeddings.chunk_id
        AND l.user_id = auth.uid()
    )
  );


-- ============================================================
-- RLS POLICIES â€” sessions
-- ============================================================

CREATE POLICY "sessions: select own"
  ON public.sessions FOR SELECT
  USING (user_id = auth.uid());

CREATE POLICY "sessions: insert own"
  ON public.sessions FOR INSERT
  WITH CHECK (user_id = auth.uid());

CREATE POLICY "sessions: update own"
  ON public.sessions FOR UPDATE
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

CREATE POLICY "sessions: delete own"
  ON public.sessions FOR DELETE
  USING (user_id = auth.uid());


-- ============================================================
-- RLS POLICIES â€” quiz_attempts
-- (join through sessions)
-- ============================================================

CREATE POLICY "quiz_attempts: select own"
  ON public.quiz_attempts FOR SELECT
  USING (
    EXISTS (
      SELECT 1 FROM public.sessions s
      WHERE s.session_id = quiz_attempts.session_id
        AND s.user_id = auth.uid()
    )
  );

CREATE POLICY "quiz_attempts: insert own"
  ON public.quiz_attempts FOR INSERT
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM public.sessions s
      WHERE s.session_id = quiz_attempts.session_id
        AND s.user_id = auth.uid()
    )
  );

CREATE POLICY "quiz_attempts: update own"
  ON public.quiz_attempts FOR UPDATE
  USING (
    EXISTS (
      SELECT 1 FROM public.sessions s
      WHERE s.session_id = quiz_attempts.session_id
        AND s.user_id = auth.uid()
    )
  );

CREATE POLICY "quiz_attempts: delete own"
  ON public.quiz_attempts FOR DELETE
  USING (
    EXISTS (
      SELECT 1 FROM public.sessions s
      WHERE s.session_id = quiz_attempts.session_id
        AND s.user_id = auth.uid()
    )
  );


-- ============================================================
-- RLS POLICIES â€” teachback_attempts
-- (join through sessions)
-- ============================================================

CREATE POLICY "teachback_attempts: select own"
  ON public.teachback_attempts FOR SELECT
  USING (
    EXISTS (
      SELECT 1 FROM public.sessions s
      WHERE s.session_id = teachback_attempts.session_id
        AND s.user_id = auth.uid()
    )
  );

CREATE POLICY "teachback_attempts: insert own"
  ON public.teachback_attempts FOR INSERT
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM public.sessions s
      WHERE s.session_id = teachback_attempts.session_id
        AND s.user_id = auth.uid()
    )
  );

CREATE POLICY "teachback_attempts: update own"
  ON public.teachback_attempts FOR UPDATE
  USING (
    EXISTS (
      SELECT 1 FROM public.sessions s
      WHERE s.session_id = teachback_attempts.session_id
        AND s.user_id = auth.uid()
    )
  );

CREATE POLICY "teachback_attempts: delete own"
  ON public.teachback_attempts FOR DELETE
  USING (
    EXISTS (
      SELECT 1 FROM public.sessions s
      WHERE s.session_id = teachback_attempts.session_id
        AND s.user_id = auth.uid()
    )
  );


-- ============================================================
-- RLS POLICIES â€” learner_dna
-- ============================================================

CREATE POLICY "learner_dna: select own"
  ON public.learner_dna FOR SELECT
  USING (user_id = auth.uid());

CREATE POLICY "learner_dna: insert own"
  ON public.learner_dna FOR INSERT
  WITH CHECK (user_id = auth.uid());

CREATE POLICY "learner_dna: update own"
  ON public.learner_dna FOR UPDATE
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

CREATE POLICY "learner_dna: delete own"
  ON public.learner_dna FOR DELETE
  USING (user_id = auth.uid());


-- ============================================================
-- RLS POLICIES â€” onboarding_responses
-- ============================================================

CREATE POLICY "onboarding_responses: select own"
  ON public.onboarding_responses FOR SELECT
  USING (user_id = auth.uid());

CREATE POLICY "onboarding_responses: insert own"
  ON public.onboarding_responses FOR INSERT
  WITH CHECK (user_id = auth.uid());

CREATE POLICY "onboarding_responses: update own"
  ON public.onboarding_responses FOR UPDATE
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

CREATE POLICY "onboarding_responses: delete own"
  ON public.onboarding_responses FOR DELETE
  USING (user_id = auth.uid());


-- ============================================================
-- RLS POLICIES â€” session_events
-- (join through sessions)
-- ============================================================

CREATE POLICY "session_events: select own"
  ON public.session_events FOR SELECT
  USING (
    EXISTS (
      SELECT 1 FROM public.sessions s
      WHERE s.session_id = session_events.session_id
        AND s.user_id = auth.uid()
    )
  );

CREATE POLICY "session_events: insert own"
  ON public.session_events FOR INSERT
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM public.sessions s
      WHERE s.session_id = session_events.session_id
        AND s.user_id = auth.uid()
    )
  );

CREATE POLICY "session_events: update own"
  ON public.session_events FOR UPDATE
  USING (
    EXISTS (
      SELECT 1 FROM public.sessions s
      WHERE s.session_id = session_events.session_id
        AND s.user_id = auth.uid()
    )
  );

CREATE POLICY "session_events: delete own"
  ON public.session_events FOR DELETE
  USING (
    EXISTS (
      SELECT 1 FROM public.sessions s
      WHERE s.session_id = session_events.session_id
        AND s.user_id = auth.uid()
    )
  );


-- ============================================================
-- RLS POLICIES â€” attention_events
-- (join through sessions, also gate on attention_consent)
-- ============================================================

CREATE POLICY "attention_events: select own"
  ON public.attention_events FOR SELECT
  USING (
    EXISTS (
      SELECT 1
      FROM public.sessions s
      JOIN public.users    u ON u.id = s.user_id
      WHERE s.session_id = attention_events.session_id
        AND s.user_id = auth.uid()
        AND u.attention_consent = true
    )
  );

CREATE POLICY "attention_events: insert own"
  ON public.attention_events FOR INSERT
  WITH CHECK (
    EXISTS (
      SELECT 1
      FROM public.sessions s
      JOIN public.users    u ON u.id = s.user_id
      WHERE s.session_id = attention_events.session_id
        AND s.user_id = auth.uid()
        AND u.attention_consent = true
    )
  );

CREATE POLICY "attention_events: update own"
  ON public.attention_events FOR UPDATE
  USING (
    EXISTS (
      SELECT 1
      FROM public.sessions s
      JOIN public.users    u ON u.id = s.user_id
      WHERE s.session_id = attention_events.session_id
        AND s.user_id = auth.uid()
        AND u.attention_consent = true
    )
  );

CREATE POLICY "attention_events: delete own"
  ON public.attention_events FOR DELETE
  USING (
    EXISTS (
      SELECT 1
      FROM public.sessions s
      JOIN public.users    u ON u.id = s.user_id
      WHERE s.session_id = attention_events.session_id
        AND s.user_id = auth.uid()
    )
  );


-- ============================================================
-- END OF MIGRATION
-- ============================================================


