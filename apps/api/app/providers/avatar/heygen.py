"""
HeyGen avatar provider — cached clip approach (PRD §8, Option 6).

Architecture decision
---------------------
There are NO live HeyGen API calls per lesson.  Instead, a small set of
intro/outro clips are pre-generated in HeyGen and stored in Supabase Storage.
This provider simply returns signed URLs to those pre-cached clips.

This keeps per-lesson latency low, eliminates HeyGen API dependency from the
critical path, and dramatically reduces cost (one-time generation vs. per-lesson).

Clip variants (expandable)
---------------------------
intro               Generic lesson-start avatar greeting
outro               Generic lesson-end avatar farewell
intro_{subject}     Subject-specific greeting (future sprint)
outro_{subject}     Subject-specific farewell (future sprint)
"""

from __future__ import annotations

import logging

from app.core.db import get_supabase
from app.providers.base import AvatarProvider

logger = logging.getLogger(__name__)

# Supabase Storage bucket holding the pre-cached HeyGen MP4 clips
_AVATAR_BUCKET = "avatar-clips"

# Signed URL expiry in seconds (1 hour — long enough to start playback)
_SIGNED_URL_EXPIRY = 3_600

# Mapping from clip_type → storage object path within the bucket
_CLIP_PATHS: dict[str, str] = {
    "intro": "clips/intro_default.mp4",
    "outro": "clips/outro_default.mp4",
}


class HeyGenAvatarProvider(AvatarProvider):
    """Returns pre-cached Supabase Storage signed URLs for HeyGen avatar clips.

    No live HeyGen API calls are made — this is intentional by design.
    """

    async def get_cached_clip(self, clip_type: str) -> str:
        """Return a signed URL to the cached avatar clip for *clip_type*.

        Args:
            clip_type: One of ``"intro"`` or ``"outro"`` (extensible for future
                       subject-specific variants).

        Returns:
            A time-limited signed URL to the MP4 clip in Supabase Storage.

        Raises:
            ValueError:  If *clip_type* is not a known variant.
            RuntimeError: If the Supabase Storage signed URL generation fails.
        """
        if clip_type not in _CLIP_PATHS:
            raise ValueError(
                f"Unknown clip_type '{clip_type}'. Valid values: {sorted(_CLIP_PATHS.keys())}"
            )

        object_path = _CLIP_PATHS[clip_type]
        supabase = get_supabase()

        try:
            result = supabase.storage.from_(_AVATAR_BUCKET).create_signed_url(
                path=object_path,
                expires_in=_SIGNED_URL_EXPIRY,
            )
            # result["signedURL"] is typed Optional by the supabase client; a
            # successful create_signed_url always returns the URL. Guard None so
            # the annotated str return type holds — types-only, the None branch
            # is unreachable in a successful call.
            signed_url = result["signedURL"]
            if signed_url is None:
                raise RuntimeError("Supabase returned no signedURL for the avatar clip")
            logger.debug(
                "Signed URL generated for clip_type='%s' path='%s'", clip_type, object_path
            )
            return signed_url

        except Exception as exc:
            logger.exception("Failed to generate signed URL for avatar clip '%s'", clip_type)
            raise RuntimeError(
                f"Could not retrieve cached clip '{clip_type}' from Supabase Storage"
            ) from exc
