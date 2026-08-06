-- Migration: 20260806000000_user_notification_preferences
-- Story: 3-33 / Defect: D60
-- Purpose: notification preference table consumed by Dev 3 get_notification_preference() helper
-- Owners: Dev 1 (migration), Dev 4 (PATCH /api/users/notifications endpoint), Dev 2 (frontend wiring)

CREATE TABLE public.user_notification_preferences (
  user_id               uuid        NOT NULL
                          REFERENCES public.users(id) ON DELETE CASCADE,
  session_report_email  boolean     NOT NULL DEFAULT true,
  lesson_ready_email    boolean     NOT NULL DEFAULT true,
  weekly_progress_email boolean     NOT NULL DEFAULT true,
  streak_reminders      boolean     NOT NULL DEFAULT true,
  updated_at            timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id)
);

CREATE INDEX user_notification_preferences_user_id_idx
  ON public.user_notification_preferences (user_id);

ALTER TABLE public.user_notification_preferences ENABLE ROW LEVEL SECURITY;

CREATE POLICY "user_notification_preferences: select own"
  ON public.user_notification_preferences
  FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "user_notification_preferences: insert own"
  ON public.user_notification_preferences
  FOR INSERT
  WITH CHECK (auth.uid() = user_id);

CREATE POLICY "user_notification_preferences: update own"
  ON public.user_notification_preferences
  FOR UPDATE
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

CREATE POLICY "user_notification_preferences: delete own"
  ON public.user_notification_preferences
  FOR DELETE
  USING (auth.uid() = user_id);
