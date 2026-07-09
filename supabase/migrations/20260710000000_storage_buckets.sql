-- Storage bucket provisioning as code (Story 2-0, AC-7).
--
-- Every bucket referenced by apps/api code must exist before deploy:
--   source-pdfs   (private) — uploaded source PDFs, downloaded by extract node
--   lesson-images (public)  — generated slide images, served via CDN
--   lesson-audio  (public)  — generated TTS narration .mp3s, served via CDN
--   avatar-clips  (private) — pre-cached HeyGen MP4s, served via signed URLs
--                             (providers/avatar/heygen.py _AVATAR_BUCKET)
--
-- ON CONFLICT DO NOTHING keeps this idempotent against buckets already
-- created manually in the dashboard. Applied migrations are never modified.

insert into storage.buckets (id, name, public)
values
    ('source-pdfs',   'source-pdfs',   false),
    ('lesson-images', 'lesson-images', true),
    ('lesson-audio',  'lesson-audio',  true),
    ('avatar-clips',  'avatar-clips',  false)
on conflict (id) do nothing;
