-- Migration: notification_log
-- Story: 2-52 (S4-12) — Email Notifications (Lesson Ready + Session Report)
-- Purpose: idempotency guard for the notification-email ARQ job. Without a
-- UNIQUE constraint here, an ARQ retry of content_pipeline_job (or any
-- duplicate enqueue of send_notification_email_job) would send the same
-- "lesson ready" email twice. This is deliberately NOT an app-level
-- SELECT-then-INSERT check — that exact shape is D45 (a check-then-act race
-- under concurrent requests, unguarded by any DB constraint). The job claims
-- a send via INSERT ... ON CONFLICT DO NOTHING RETURNING id against this
-- table's UNIQUE constraint; only the caller that gets a row back proceeds.
-- Owner: Dev 2 (S4-12, explicit user-approved exception crossing into apps/api).

CREATE TABLE public.notification_log (
  id                uuid        NOT NULL DEFAULT gen_random_uuid(),
  user_id           uuid        NOT NULL
                      REFERENCES public.users(id) ON DELETE CASCADE,
  notification_type text        NOT NULL
                      CHECK (notification_type IN ('lesson_ready', 'session_report')),
  resource_id       text        NOT NULL,
  sent_at           timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id),
  UNIQUE (user_id, notification_type, resource_id)
);

-- Every lookup this job performs is `.eq('user_id', ...).eq('notification_type', ...)
-- .eq('resource_id', ...)` — the same triple the UNIQUE constraint already
-- indexes, so no separate lookup index is needed. This one supports an
-- eventual admin "notifications sent to this user" view without a full scan.
CREATE INDEX notification_log_user_id_idx
  ON public.notification_log (user_id);

-- No frontend surface reads or writes this table (per Story 2-52's Dev Notes —
-- preference toggling is the entire frontend surface for this feature). RLS is
-- enabled with zero policies: service-role (used exclusively by the ARQ job)
-- bypasses RLS entirely per Supabase's default behaviour; anon/authenticated
-- roles get a default-deny with no policy granting them any access at all.
ALTER TABLE public.notification_log ENABLE ROW LEVEL SECURITY;
