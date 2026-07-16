---
baseline_commit: baf79fa14f1be5bbbc75152a894df7b875aed713
---

# Story 2.12: `lesson_ready` WebSocket Delivery — Reconcile With Real `LessonPackage` (S2-12)

Status: ready-for-dev

## Story

As a **student waiting for a chapter to finish generating**,
I want the `lesson_ready` WebSocket message I receive to carry the REAL, schema-validated lesson (not a stale placeholder), with accurate summary counts logged server-side,
so that the moment `package_builder_node` (S2-11) finishes, the notification pipeline built by Dev 4 correctly reflects what was actually generated.

**This story is a reconciliation/bug-fix story, NOT new infrastructure.** The `lesson_ready` WebSocket delivery mechanism already exists and is already wired end-to-end — built by Dev 4 in an earlier commit (`4534078 fix(arq): lesson_ready via Redis pub/sub`), consisting of:
1. `apps/api/app/workers/jobs/content_pipeline.py::content_pipeline_job` — publishes to Redis channel `lesson_ready:{session_id}` after `run_pipeline()` succeeds.
2. `apps/api/app/core/pubsub.py::_run_lesson_subscriber` — a background asyncio task (started in `app/main.py`'s lifespan) that subscribes to `lesson_ready:*` and forwards each message to `ConnectionManager.send()`.
3. `session_id` already falls back to `lesson_id` when no stored session exists yet (`lessons` has no `session_id` column today) — this is the ONLY code path that runs in practice, and it's already what a prior investigation in this session (before this story existed) confirmed is the right approach given `sessions` rows aren't created until a student starts playing a lesson, well after generation completes.

**What actually needs fixing, discovered by re-reading this code after Story 2-11 landed:**
1. **Real bug**: `content_pipeline_job`'s `package_summary` (`slides_count`/`quiz_count`/`audio_count`) still reads `lesson_package.get("slides", [])` / `.get("quiz_questions", [])` / `.get("audio_assets", [])` — those were the STUB's flat top-level keys. The REAL `LessonPackage` (Story 2-11) has no such top-level keys at all; `slides`/`quiz`/narration all live nested inside each `segment`. These counts have silently reported `0`/`0`/`0` since S2-11 landed, for every successful lesson.
2. **Stale comments**: both `content_pipeline.py` and `pubsub.py` still say "not the frozen LessonPackage from Dev 1's real package_builder (Story S2-11, not yet built)" — S2-11 landed 2026-07-16, this is now false.
3. **Frozen-contract deviation**: the published WS message's `payload` includes an extra `session_id` key (`{"session_id": ..., "lesson_id": ..., "lesson": ...}`) that isn't part of `packages/shared/types/ws.ts`'s `LessonReadyMessage` payload type (`{lesson_id: string; lesson: LessonPackage}` only). `session_id` is already implicit in which WebSocket connection receives the message — it doesn't need to be duplicated inside the payload too.
4. **Zero test coverage**: `tests/unit/test_queue_symmetry.py` has a comment referencing `test_lesson_ready_integration`, but no such test (or any test covering `content_pipeline_job`'s publish step, `pubsub.py`'s subscribe/forward step, or `package_summary`) exists anywhere in the repo.

## Acceptance Criteria

1. **`package_summary` counts are computed from the REAL nested `LessonPackage` shape**: `slides_count` = total slides across all segments (`sum(len(seg["slides"]) for seg in lesson_package["segments"])`); `quiz_count` = total quiz questions across all segments (`sum(len(seg["quiz"]) for seg in ...)` — note the field is `quiz`, not `quiz_questions`, on a `Segment`); `audio_count` = number of segments (every assembled segment has exactly one `narration` — `package_builder_node`'s own degrade-and-skip logic guarantees this, so `len(lesson_package["segments"])` is the correct, simple count).
2. **Stale `[DEV1-SPRINT2-PENDING]` comments in `content_pipeline.py` and `pubsub.py` updated** to reflect that Story 2-11's real `package_builder_node` has landed — the lesson package flowing through this code is now the real, schema-validated `LessonPackage`, not a flat stub.
3. **The published WS message's `payload` matches `ws.ts`'s `LessonReadyMessage` type exactly** — `{"lesson_id": ..., "lesson": ...}`, no extra `session_id` key inside `payload`. (`session_id` remains the pub/sub channel suffix / `ConnectionManager` routing key — unchanged, just no longer duplicated inside the message body.)
4. **`session_id` fallback behavior is unchanged and explicitly confirmed correct** — `lesson_row.get("session_id") or lesson_id` continues to always evaluate to `lesson_id` today (no `session_id` column exists on `lessons`), and this story does NOT add one, build a new endpoint, or otherwise expand scope into real session-tracking — that remains genuinely out of scope pending real Dev 4 coordination on a session-tracking column/flow, not something to invent here.
5. **New test coverage**: `content_pipeline_job` publishes the correct message shape (matching AC-3) to the correct channel (`lesson_ready:{lesson_id}` given today's fallback) when `run_pipeline()` succeeds; `package_summary`'s three counts are correct against a realistic multi-segment `LessonPackage`-shaped fixture; `pubsub.py`'s subscriber correctly forwards a received pub/sub message to `ConnectionManager.send()` with the channel's `session_id` suffix extracted correctly.
6. All existing tests continue to pass unmodified.

## Tasks / Subtasks

- [ ] Task 1: Fix `package_summary`'s counts (AC: 1)
  - [ ] 1.1 Replace `lesson_package.get("slides", [])`/`.get("quiz_questions", [])`/`.get("audio_assets", [])` with the correct nested-segment aggregation in `content_pipeline_job`.
  - [ ] 1.2 Handle `lesson_package` being an empty dict gracefully (defensive `.get("segments", [])` — matches this codebase's established defensive-degrade style, not a new invented behavior).

- [ ] Task 2: Update stale comments (AC: 2)
  - [ ] 2.1 `content_pipeline.py`'s `[DEV1-SPRINT2-PENDING]` comment above the `run_pipeline()` call updated.
  - [ ] 2.2 `pubsub.py`'s `[DEV1-SPRINT2-PENDING]` comment above the lesson-package cache-write updated.

- [ ] Task 3: Align the WS payload with the frozen `ws.ts` contract (AC: 3, 4)
  - [ ] 3.1 Remove `session_id` from inside the `payload` dict published in `content_pipeline_job` — `payload` becomes exactly `{"lesson_id": ..., "lesson": ...}`.
  - [ ] 3.2 Confirm `pubsub.py`'s subscriber still correctly extracts `session_id` from the CHANNEL name (`channel.removeprefix("lesson_ready:")`), NOT from the payload — verify this was already the case (it was; the payload's `session_id` was redundant, never actually read back out by the subscriber) before removing it, so nothing silently breaks.
  - [ ] 3.3 Confirm the `session_id` fallback (`lesson_row.get("session_id") or lesson_id`) is left exactly as-is — no new column, no new endpoint (AC-4).

- [ ] Task 4: Tests (AC: 5, 6)
  - [ ] 4.1 New test(s) for `content_pipeline_job`'s publish step: given a successful `run_pipeline()` returning a realistic multi-segment `LessonPackage` dict, assert the published Redis message matches the frozen payload shape exactly and the channel is `lesson_ready:{lesson_id}`.
  - [ ] 4.2 New test(s) for `package_summary`'s three counts against that same realistic fixture.
  - [ ] 4.3 New test for `pubsub.py`'s subscriber: a simulated `pmessage` on `lesson_ready:{some_id}` results in exactly one `manager.send(some_id, message)` call with the decoded message.
  - [ ] 4.4 Full regression suite passes.

## Dev Notes

### Read the existing, ALREADY-WORKING code before touching anything — this is reconciliation, not greenfield work

`apps/api/app/workers/jobs/content_pipeline.py` (lines ~103-118, current):
```python
# ── 4b. Notify client via Redis pub/sub ──────────────────────────────
import json
from app.core.redis import get_redis

redis = get_redis()
channel = f"lesson_ready:{session_id}"
message = {
    "type": "lesson_ready",
    "payload": {
        "session_id": session_id,
        "lesson_id": lesson_id,
        "lesson": lesson_package,
    },
}
await redis.publish(channel, json.dumps(message))
```
Only the `payload` dict's extra `"session_id"` key needs removing (AC-3) — the publish mechanism, channel naming, and `redis.publish()` call are correct and unchanged.

`apps/api/app/core/pubsub.py`'s `_run_lesson_subscriber` (already correct, do not modify its core logic): extracts `session_id` from the CHANNEL (`channel.removeprefix("lesson_ready:")`), not from the payload — confirming Task 3.2's verification will pass trivially, since the payload's `session_id` was already dead weight, never read back out anywhere.

### The real bug — `package_summary`'s stub-shape assumption

`content_pipeline_job`'s current summary block:
```python
"package_summary": {
    "slides_count": len(lesson_package.get("slides", [])),
    "quiz_count": len(lesson_package.get("quiz_questions", [])),
    "audio_count": len(lesson_package.get("audio_assets", [])),
},
```
`lesson_package` here is `run_pipeline()`'s return value — which, as of Story 2-11, is `package.model_dump(mode="json")` for a real `LessonPackage` (`apps/api/app/schemas/lesson.py`). Its top-level keys are `lesson_id`, `book_id`, `chapter_id`, `created_at`, `metadata`, `segments`, `glossary` — NONE of `slides`/`quiz_questions`/`audio_assets` exist at this level anymore. Every one of the three `.get(..., [])` calls above silently returns `[]`, so all three counts have been `0` since Story 2-11 shipped, for every successful lesson, with zero visible error (this is exactly the kind of cross-file consequence that made this story worth writing before moving further into Sprint 2 — a schema change in one node silently broke an unrelated consumer three files away).

Correct replacement, using `Segment`'s real per-segment fields (`slides: list[Slide]`, `quiz: list[QuizQuestion]`, `narration: Narration` — exactly one per segment):
```python
segments = lesson_package.get("segments", [])
"package_summary": {
    "slides_count": sum(len(seg.get("slides", [])) for seg in segments),
    "quiz_count": sum(len(seg.get("quiz", [])) for seg in segments),
    "audio_count": len(segments),  # package_builder_node guarantees exactly one narration per assembled segment
},
```

### Testing standards

pytest, matching sibling stories' conventions. Mock `redis.publish`/`get_redis` the same way existing ARQ job tests do (check for an existing `test_content_pipeline_job.py` or similar file first — if one exists, add to it rather than creating a parallel file). For `pubsub.py`, mock the `Redis.from_url`/`pubsub()`/`psubscribe`/`listen()` chain and the `ConnectionManager` (or use a real `ConnectionManager()` instance and assert on `._connections`).

### Branch

Single shared branch for all of Sprint 2: `sprint2/phase-b-generation-nodes` — do not create a new branch. Story-first gate still applies.

### Project Structure Notes

`apps/api/app/workers/jobs/content_pipeline.py` modified (package_summary fix, payload fix, comment fix), `apps/api/app/core/pubsub.py` modified (comment fix only), new or extended test file(s) for both.

### References

- [Source: docs/dev1-tracker.md — Sprint 2 section, S2-12]
- [Source: docs/stories/2-11-package-builder-node.md — the real LessonPackage shape this story reconciles against]
- [Source: apps/api/app/workers/jobs/content_pipeline.py — content_pipeline_job, the ARQ job publishing lesson_ready]
- [Source: apps/api/app/core/pubsub.py — the Redis pub/sub subscriber bridging to ConnectionManager]
- [Source: apps/api/app/core/websocket.py — ConnectionManager, session_id-keyed connection registry]
- [Source: packages/shared/types/ws.ts — LessonReadyMessage frozen payload type]
- [Source: apps/api/app/schemas/lesson.py — LessonPackage/Segment real shape]
- [Source: git log 4534078 "fix(arq): lesson_ready via Redis pub/sub" — Dev 4's original implementation this story reconciles, not replaces]

## Dev Agent Record

### Agent Model Used

_To be filled by bmad-dev-story._

### Debug Log References

_To be filled by bmad-dev-story._

### Completion Notes List

_To be filled by bmad-dev-story._

### File List

_To be filled by bmad-dev-story._

## Change Log

| Date | Change |
|------|--------|
| 2026-07-16 | Story created via `bmad-create-story`. |
