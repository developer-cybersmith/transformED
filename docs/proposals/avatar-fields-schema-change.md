# Schema Change Proposal: Avatar Fields on `LessonPackage`

**Status:** Draft — needs sign-off from all 4 devs per CLAUDE.md §16 (frozen contract)
**Proposed by:** Dev 2
**Affects:** `packages/shared/lesson_package.schema.json`, `packages/shared/types/lesson.ts` (both frozen, Dev 2-authored)
**Blocks:** `docs/dev2-sprint-tracker.md` S1-05 — AvatarOverlay Component

---

## Problem

S1-05 (AvatarOverlay — HeyGen intro/outro + static avatar) has been blocked since Sprint 1. The frozen `LessonPackage` contract has **zero avatar-related fields** — confirmed by grepping `packages/shared/` for "avatar" (zero matches). There's nowhere for the frontend to read a clip/image URL from, and no Pydantic-mirrored place for the pipeline to write one.

## What's already built on the backend (verified directly, not assumed)

- `apps/api/app/providers/avatar/heygen.py` — a real `HeyGenAvatarProvider.get_cached_clip(clip_type)` exists. Matches the CLAUDE.md-mandated design exactly: **no live HeyGen API calls per lesson** — it returns a Supabase Storage **signed URL** for one of two pre-cached, generic MP4s (`clips/intro_default.mp4` / `clips/outro_default.mp4` in the `avatar-clips` bucket). Subject-specific variants are noted in the file as a future sprint.
- `apps/api/app/modules/media/router.py` — a `GET /media/signed-url` endpoint is registered and has `avatar-clips` in its bucket allowlist, but the handler body is a stub: `raise HTTPException(501, "Not implemented yet")`. Nothing can actually call it yet.
- The content pipeline (`apps/api/app/modules/content/pipeline/graph.py`, including `package_builder_node`) has **zero references to avatar anywhere** — nothing populates any avatar field into a lesson today, frozen schema or otherwise.
- There is no static-image equivalent of `get_cached_clip` yet — the provider only knows `"intro"`/`"outro"`, not a static mid-lesson avatar image.

So this proposal is the first of three things needed to unblock S1-05, not the whole fix — but it's the one that needs cross-team sign-off, so it should go first.

## Proposed fields

Add 3 new **top-level, nullable** fields to `LessonPackage`, following the exact pattern already used for `Slide.image_url`/`fallback_image_url` (always present in the object, value may be `null`, non-null value is a URI):

| Field | Type | Null when |
|---|---|---|
| `avatar_intro_url` | `string \| null` (URI) | Avatar generation/retrieval failed or wasn't configured for this lesson |
| `avatar_static_url` | `string \| null` (URI) | Same |
| `avatar_outro_url` | `string \| null` (URI) | Same |

Matches S1-05's own acceptance criteria: *"If `avatar_intro_url` is null: skip silently, start lesson audio immediately"* — the player must never block on these being present.

### `lesson_package.schema.json` diff

```diff
   "required": [
     "lesson_id",
     "book_id",
     "chapter_id",
     "created_at",
     "metadata",
     "segments",
-    "glossary"
+    "glossary",
+    "avatar_intro_url",
+    "avatar_static_url",
+    "avatar_outro_url"
   ],
   "additionalProperties": false,
   "properties": {
     ...
     "glossary": {
       "type": "array",
       "items": { "$ref": "#/definitions/GlossaryEntry" }
+    },
+    "avatar_intro_url": {
+      "oneOf": [{ "type": "string", "format": "uri" }, { "type": "null" }]
+    },
+    "avatar_static_url": {
+      "oneOf": [{ "type": "string", "format": "uri" }, { "type": "null" }]
+    },
+    "avatar_outro_url": {
+      "oneOf": [{ "type": "string", "format": "uri" }, { "type": "null" }]
     }
   },
```

### `types/lesson.ts` diff

```diff
 export interface LessonPackage {
   lesson_id: string;
   book_id: string;
   chapter_id: string;
   created_at: string;
   metadata: LessonMetadata;
   segments: Segment[];
   glossary: GlossaryEntry[];
+  avatar_intro_url: string | null;
+  avatar_static_url: string | null;
+  avatar_outro_url: string | null;
 }
```

(A mirrored `Optional[str] = None` change to Dev 1's Pydantic `LessonPackage` model would be needed too — not shown here since that file isn't in `packages/shared`.)

## Open question for Dev 1 (recommend resolving before merge, not blocking the sign-off itself)

`HeyGenAvatarProvider`'s signed URLs expire in 1 hour (`_SIGNED_URL_EXPIRY = 3_600`). If `package_builder_node` bakes a signed URL into the persisted `lessons.content` JSONB at generation time, it will be **dead within an hour** for any student who opens the lesson later — a real bug waiting to happen, not hypothetical given lessons are meant to be revisited.

Two reasonable fixes, Dev 1's call:
1. **Make `avatar-clips` a public bucket.** These are 2 generic, non-user-specific marketing-style clips (not per-student content) — there's no confidentiality reason they need signed URLs at all. Simplest fix, avoids the expiry problem entirely.
2. **Keep them signed, but generate URLs at player-load time, not pipeline-build time** — the frontend would need to call `GET /media/signed-url` fresh each session instead of trusting a value stored in the JSONB. Requires the media router endpoint to actually be implemented (it's still a 501 stub) and a schema note that `avatar_*_url` values may need periodic refresh.

Recommend (1) given these aren't per-user assets, but flagging both since it's Dev 1's storage/provider design call, not just a schema question.

## What still needs to happen after this sign-off (tracked separately, not blocking this proposal)

1. Implement `GET /media/signed-url` (currently a 501 stub) — or skip it entirely if the bucket goes public (see above).
2. Add a static-image clip variant to `HeyGenAvatarProvider` (only `intro`/`outro` exist today).
3. Wire `package_builder_node` to populate the 3 new fields.
4. Build `AvatarOverlay.tsx` (S1-05, Dev 2) once the above land.

## Sign-off

- [ ] Dev 1 (Infrastructure + Content Pipeline) — owns `package_builder_node`, the Pydantic mirror, and the open question above
- [ ] Dev 2 (Lesson Player + Frontend) — proposer, owns `AvatarOverlay.tsx` consumption
- [ ] Dev 3 (Assessment + Analytics)
- [ ] Dev 4 (Tutor Agent + Realtime)
