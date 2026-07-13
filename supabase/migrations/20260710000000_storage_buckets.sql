-- Storage bucket provisioning as code (Story 2-0, AC-7 + review decision D1).
--
-- Every bucket referenced by apps/api code must exist before deploy.
-- ALL FOUR buckets are PRIVATE (public=false) — lesson content is the paid
-- deliverable and must never be fetchable unauthenticated / CDN-cached.
-- Media is served exclusively via signed URLs (media router):
--   source-pdfs   (private) — uploaded source PDFs, downloaded by extract node
--   lesson-images (private) — generated slide images, served via signed URLs
--   lesson-audio  (private) — generated TTS narration .mp3s, served via signed URLs
--   avatar-clips  (private) — pre-cached HeyGen MP4s, served via signed URLs
--                             (providers/avatar/heygen.py _AVATAR_BUCKET)
--
-- ON CONFLICT (id) DO UPDATE keeps this idempotent against buckets already
-- created manually in the dashboard AND reconciles their `public` visibility
-- flag to the declared posture (a manually-created public bucket is flipped
-- private on apply). Applied migrations are never modified.

insert into storage.buckets (id, name, public)
values
    ('source-pdfs',   'source-pdfs',   false),
    ('lesson-images', 'lesson-images', false),
    ('lesson-audio',  'lesson-audio',  false),
    ('avatar-clips',  'avatar-clips',  false)
on conflict (id) do update set public = excluded.public;
