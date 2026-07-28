# Dev 2 Handoff: Wire the Player to Real Lesson Content

**From:** Dev 1 (developer1-cybersmith)
**To:** Dev 2 (Next.js / player owner)
**Date:** 2026-07-23
**Branch where the backend work landed:** `main` (PR #85 — Story 3-6, PR #86 — Story 1-6)
**Severity:** Blocking for real-content testing — until this is wired, the player only ever renders `apps/web/src/mocks/`, regardless of what the pipeline actually generates.

---

## TL;DR

Two backend endpoints just went from "broken/incomplete" to "real":

1. **`GET /api/content/lessons/{lesson_id}`** now returns a `content` field — the full, real `LessonPackage`, with every `audio_url`/`image_url` already resolved to a working signed URL. It never did before (Sprint 1 gap, discovered 2026-07-23).
2. **`GET /api/media/signed-url`** now actually signs (was a `501` stub). You should **not** need to call this directly — endpoint #1 already resolves URLs for you.

**What you need to do:** point `useLesson()` at the real endpoint instead of `apps/web/src/mocks/`, and handle three states the mock world never had to: *still generating*, *failed*, and *signed URLs that can expire*. Details and exact file locations below.

**What you do NOT need to do:** anything with signed URLs yourself, touch `upload.service.ts`'s polling logic (it already calls the real endpoint and already works), or wire the dashboard list (`getLesson`) or progress tracking (`updateLessonProgress`) — those still have no real backend equivalent, leave them on mocks.

---

## 1. What Actually Changed (Backend Side)

### 1a. `GET /api/content/lessons/{lesson_id}` — now returns `content`

Before, the response only ever had:

```json
{ "lesson_id": "...", "status": "ready", "title": "...", "error": null, "created_at": "...", "completed_at": "..." }
```

Now, when `status == "ready"`, it also includes `content`:

```json
{
  "lesson_id": "...",
  "status": "ready",
  "title": "...",
  "error": null,
  "created_at": "...",
  "completed_at": "...",
  "content": {
    "lesson_id": "...", "book_id": "...", "chapter_id": "...", "created_at": "...",
    "metadata": { "title": "...", "subject": "...", "total_segments": 2, "estimated_duration_mins": 5.0, "complexity_level": "medium", "tier": "T2" },
    "segments": [
      {
        "segment_id": "seg_0", "segment_index": 0, "title": "...", "summary": "...",
        "complexity": { "...": "..." },
        "slides": [
          { "slide_id": "sl_1", "title": "...", "bullets": ["..."], "image_url": "https://<real-signed-url>", "fallback_image_url": null }
        ],
        "narration": {
          "script": "...", "audio_url": "https://<real-signed-url>", "audio_provider": "azure",
          "timestamps": [{ "slide_id": "sl_1", "start_ms": 0, "end_ms": 3000 }]
        },
        "quiz": ["..."], "teachback_prompt": "...", "jargon": ["..."], "interventions": { "...": "..." }
      }
    ],
    "glossary": ["..."]
  }
}
```

`content`'s shape is **exactly** `packages/shared/types/lesson.ts`'s `LessonPackage` — the frozen contract, unchanged. Nothing about the TS type needed to change; the gap was purely that the backend never populated it.

For `status == "generating"` or `"failed"`, `content` is `null` — same as it's always been.

### 1b. `audio_url`/`image_url` are real, working signed URLs — not the bare paths the pipeline actually stores

`package_builder` (the pipeline stage that writes `lessons.content`) stores **bare private-bucket paths** like `"22222222-.../seg_1.mp3"` — this was always true, by design (a signed URL baked in at generation time would expire long before some lessons get viewed). What's new is that `GET /lessons/{id}` now resolves every one of those bare paths to a real signed URL **before** the response goes out, so you never see or need to handle bare paths.

- If signing an individual asset fails (rare — a storage outage, a missing object), that **one** asset degrades to its "no media" value (`audio_url: ""`, `image_url: null`) rather than failing the whole response. Your existing fallback UI already handles `image_url: null` (`SlideRenderer.tsx`'s `SlideImage` component falls back to `fallback_image_url` or a placeholder) — worth double-checking `AudioTimeline.tsx` has *some* graceful behavior for `audio_url: ""` too, since that's now a value the real world can actually send you (the mock world never did).

- **Signed URLs expire after 1 hour** (`expires_in` defaults to 3600s). This isn't a new problem you need to solve right now — a single lesson session shouldn't realistically run that long — but it's worth knowing for testing: if you leave a lesson player open and idle for over an hour before pressing play, the audio/image URLs fetched at page-load will have expired. `useLesson`'s `revalidateOnFocus: false` (intentional, so player state doesn't reset on tab refocus) means there's currently no mechanism that would catch this. Flagging as a known limitation, not asking you to fix it as part of this handoff.

### 1c. Nothing about auth or the WebSocket contract changed

`GET /lessons/{id}` uses the same `CurrentUser` JWT dependency it always has — same auth as every other content endpoint. `packages/shared/types/ws.ts`'s `lesson_ready` message is untouched.

---

## 2. The One Thing That Might Actually Bite You: `lesson_ready`'s WS Payload Is NOT Signed

I checked `useLessonSocket.ts` before writing this, and good news — **you already got this right**:

```ts
case 'lesson_ready':
  // Live via Redis pub/sub, but per the wire contract a client that may have
  // missed it must fetch via REST rather than rely on this push; no-op.
  break;
```

This comment is exactly correct, and I want to confirm *why*, since the frozen `ws.ts` type's doc comment ("full package delivered to client") could otherwise mislead someone into thinking the WS push is playable as-is:

`lesson_ready`'s `payload.lesson` is the **raw** `LessonPackage` as `package_builder` wrote it to `lessons.content` — forwarded byte-for-byte from Redis pub/sub (`apps/api/app/core/pubsub.py`). It has never been signed, and still isn't — signing only happens in the REST `GET /lessons/{id}` response, not in the WS push. If anything is ever built that renders `payload.lesson` directly, its `audio_url`/`image_url` will be bare storage paths, and every `<audio>`/`<img>` will 404.

**Your existing no-op is the right call — keep it.** The intended flow is: `lesson_ready` (or `UploadFlow.tsx`'s existing status poll) tells you *when* to fetch, and `GET /lessons/{id}` is the *only* place you should ever read `audio_url`/`image_url` from. That REST endpoint was the missing piece your comment was waiting on — it's real now.

---

## 3. Where To Actually Make Changes

### 3a. `apps/web/src/services/lesson.service.ts` — the swap

```ts
// Current (mock):
export const lessonService = {
    getLesson: (id: string) => lessonApi.getLessonById(id),
    getLessonPackage: (id: string) => lessonApi.getLessonPackageById(id),
    updateProgress: (id: string, percent: number) => lessonApi.updateLessonProgress(id, percent),
};
```

Only `getLessonPackage` has a real backend equivalent now. Point it at `GET /api/content/lessons/{id}` through the **same authenticated axios client** `upload.service.ts` already uses (`@/lib/api.ts` — it already attaches the Supabase JWT via an interceptor; don't build a second auth path).

**Leave `getLesson` and `updateProgress` on mocks.** Neither has a real backend counterpart yet:
- `getLesson` expects `MockLesson`'s dashboard-card shape (`thumbnailUrl`, `progressPercent`, `chapterTitle`, `lastAccessed`) — the real `lessons` table has none of these columns. Wiring the dashboard list is a separate, not-yet-started piece of work.
- `updateProgress` (`PATCH`-style progress tracking) has no real endpoint at all yet.

### 3b. `apps/web/src/hooks/useLesson.ts` — the shape mismatch you'll hit immediately

This is the part most likely to break silently if not handled: the real endpoint's response is **`LessonStatusResponse`** (`{ lesson_id, status, title, error, created_at, completed_at, content }`), not a bare `LessonPackage`. Today's hook assumes the fetcher directly returns a `LessonPackage | null`:

```ts
// Current
export function useLesson(lessonId: string): UseLessonResult {
  const { data, error, isLoading } = useSWR<LessonPackage | null>(
    lessonId ? `lesson:${lessonId}` : null,
    async () => {
      const response = await lessonService.getLessonPackage(lessonId);
      return response.data;   // ← mock shape: response.data IS the LessonPackage
    },
    { revalidateOnFocus: false },
  );
  return { lesson: data ?? null, isLoading, error };
}
```

With the real endpoint, `response.data` is the whole `LessonStatusResponse` — the package you want is at `response.data.content`. A one-line fix for the happy path:

```ts
return response.data.content;   // instead of response.data
```

**But this is also exactly where the "frontend doesn't break" part of your ask comes in** — a bare `content ?? null` throws away `status`/`error`, and `PlayerLoader.tsx` currently treats any `!lesson` as a hard, non-recoverable error:

```ts
// PlayerLoader.tsx, current
if (error) return <LessonErrorState />;
if (isLoading) return <PlayerSkeleton />;
if (!lesson) return <LessonErrorState />;   // ← this line is the problem
return <Player lesson={lesson} />;
```

In the mock world, `!lesson` never legitimately happened. In the real world, `content: null` is a **normal, expected** response whenever `status` is `"generating"` — which is exactly what happens if a user navigates to `/lesson/{id}` directly (bookmark, shared link, browser back-button, or just refreshing mid-generation) rather than only arriving via `UploadFlow.tsx`'s poll-then-navigate flow. Today that would render the permanent "This lesson could not be loaded" error page for a lesson that is, correctly, still generating.

**You'll want `useLesson` to also surface `status`/`error`** (not just the resolved package) so `PlayerLoader` can distinguish:
- `status == "generating"` → some kind of "still generating, hang tight" state (possibly with SWR polling via `refreshInterval` while non-ready, similar to what `UploadFlow.tsx` already does by hand)
- `status == "failed"` → show `response.data.error`, not a generic message
- `status == "ready"` with `content` → render the player, same as today

I'm not prescribing the exact UI/hook shape for this — that's squarely your call as player owner — just flagging that the current `!lesson → error` branch is a real gap once real data (rather than always-succeeding mocks) is flowing through it, and it's worth deciding on purpose rather than discovering it when someone hits refresh mid-lesson during testing.

### 3c. `apps/web/src/services/upload.service.ts` — no functional change needed, one type to keep honest

This file is **already real** — `getLessonStatus()` already calls the actual `GET /api/content/lessons/{id}` (used by `UploadFlow.tsx`'s polling loop) and already works correctly today. Nothing here needs to change functionally.

The one thing worth doing for correctness: its hand-duplicated local `LessonStatusResponse` interface doesn't have the new `content` field —

```ts
export interface LessonStatusResponse {
    lesson_id: string;
    status: LessonStatus;
    title: string | null;
    error: string | null;
    created_at: string | null;
    completed_at: string | null;
    // content: LessonPackage | null;  ← add this
}
```

`UploadFlow.tsx` only reads `.status`/`.lesson_id`/`.error` today so this won't break anything either way — it's just type drift waiting to happen (two independent hand-written interfaces for the same backend response, in `upload.service.ts` and now conceptually in `useLesson.ts`). Consider whether these two should share one type instead of each re-declaring it — your call, not blocking.

---

## 4. What I Explicitly Did NOT Touch

Per the story's own scope (backend-only), zero files under `apps/web/**` were changed by either PR. Confirmed via `git diff --stat` on both PRs and an independent cross-team sync check before merging. Nothing here should surprise you as an unannounced change to your files.

---

## 5. How To Test This End-to-End Once Wired

1. Upload a real PDF through the existing upload flow (`UploadFlow.tsx` already calls the real `POST /api/content/lessons` + polls the real status endpoint — this part needs no changes).
2. Wait for `status` to flip to `"ready"` (real pipeline run — several minutes, not the mock's fixed delay).
3. Once wired per §3, `/lesson/{id}` should now play a **real, pipeline-generated lesson** — real narration audio, real (or gracefully-fallback) slide images, real quiz questions — instead of the fixed mock package.
4. Specifically worth testing on purpose (these are exactly the states the mock world couldn't exercise):
   - Navigate to `/lesson/{id}` for a lesson that's still `"generating"` — confirm you get a sensible state, not the current permanent error page.
   - A lesson whose pipeline run ended in `"failed"` — confirm `error` is surfaced, not swallowed.
   - A segment whose image or audio failed to generate/sign (rare, but the pipeline's degrade-not-drop paths do produce these) — confirm `SlideImage`'s null-fallback and whatever you decide for `AudioTimeline` both hold up.

---

## 6. Files Involved

| File | Owner | Action Needed |
|------|-------|----------------|
| `apps/web/src/services/lesson.service.ts` | Dev 2 | Point `getLessonPackage` at the real endpoint via `@/lib/api.ts`; leave `getLesson`/`updateProgress` on mocks |
| `apps/web/src/hooks/useLesson.ts` | Dev 2 | Read `.content` instead of the bare response; decide how to surface `status`/`error` for the not-ready/failed cases |
| `apps/web/src/components/player/PlayerLoader.tsx` | Dev 2 | Decide the non-error "still generating" state instead of falling into `LessonErrorState` |
| `apps/web/src/components/player/AudioTimeline.tsx` | Dev 2 | Confirm graceful behavior for `audio_url: ""` (a real, if rare, degrade value now) |
| `apps/web/src/services/upload.service.ts` | Dev 2 | No functional change; optionally add `content` to its local `LessonStatusResponse` type for accuracy |
| `apps/web/src/hooks/useLessonSocket.ts` | Dev 2 | No change needed — your `lesson_ready` no-op is already correct |
| `apps/api/app/modules/content/router.py` | Dev 1 | Already done (Story 1-6) — `content` field, signed URLs |
| `apps/api/app/modules/media/router.py` | Dev 1 | Already done (Story 3-6) — real signing (you shouldn't need to call this directly) |

---

## 7. Reference

- `docs/stories/3-6-media-signed-url-layer.md` — the signing endpoint story
- `docs/stories/1-6-lesson-content-endpoint.md` — the content endpoint story (Senior Developer Review section has the full 5-agent review trail if you want the detail on edge cases already checked: degrade-not-drop, null-segments handling, corruption-not-swallowed)
- `docs/reports/audit-dev1-dev2-2026-07-22.md` — the original audit that surfaced the signing gap (HIGH finding #3)
