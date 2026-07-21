---
baseline_commit: baf79fa14f1be5bbbc75152a894df7b875aed713
---

# Story 2.12: `lesson_ready` WebSocket Delivery — Reconcile With Real `LessonPackage` (S2-12)

Status: done

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

- [x] Task 1: Fix `package_summary`'s counts (AC: 1)
  - [x] 1.1 Replaced `lesson_package.get("slides", [])`/`.get("quiz_questions", [])`/`.get("audio_assets", [])` with the correct nested-segment aggregation (`sum(len(seg.get("slides", [])) for seg in segments)`, same for `quiz`; `audio_count = len(segments)`).
  - [x] 1.2 `segments = lesson_package.get("segments", [])` — an empty/missing `lesson_package` degrades to `{"slides_count": 0, "quiz_count": 0, "audio_count": 0}` without raising, verified by a dedicated test.

- [x] Task 2: Update stale comments (AC: 2)
  - [x] 2.1 `content_pipeline.py`'s `[DEV1-SPRINT2-PENDING]` comment above the `run_pipeline()` call updated to reflect Story 2-11 has landed.
  - [x] 2.2 `pubsub.py`'s `[DEV1-SPRINT2-PENDING]` comment above the lesson-package cache-write updated likewise.

- [x] Task 3: Align the WS payload with the frozen `ws.ts` contract (AC: 3, 4)
  - [x] 3.1 Removed `session_id` from inside the `payload` dict published in `content_pipeline_job` — `payload` is now exactly `{"lesson_id": ..., "lesson": ...}`.
  - [x] 3.2 Confirmed `pubsub.py`'s subscriber extracts `session_id` from the CHANNEL name (`channel.removeprefix("lesson_ready:")`) only — it never read the payload's `session_id` in the first place (verified by reading the code before removing it); no behavior change to the subscriber, existing subscriber tests untouched and still passing.
  - [x] 3.3 `session_id` fallback (`lesson_row.get("session_id") or lesson_id`) left exactly as-is — no new column, no new endpoint.

- [x] Task 4: Tests (AC: 5, 6) — all added to the existing `tests/test_lesson_ready_pubsub.py` (per Dev Notes' guidance to extend rather than fork)
  - [x] 4.1 Updated `test_publish_message_has_correct_ws_shape` and `test_routing_reaches_correct_client_when_session_id_differs` to assert the payload matches `ws.ts`'s `LessonReadyMessage` exactly (no `session_id` key) against a new realistic multi-segment `REAL_LESSON_PACKAGE` fixture (replacing the old flat-stub-shaped fixtures in both).
  - [x] 4.2 Two new tests: `test_package_summary_counts_real_nested_lesson_package_shape` (2 segments, 3 slides/1 quiz/2 audio expected) and `test_package_summary_handles_empty_lesson_package_gracefully`.
  - [x] 4.3 Pre-existing `test_subscriber_forwards_pmessage_to_manager` already covers this exact scenario — confirmed still passing, no change needed.
  - [x] 4.4 Full regression suite: 942 passed (after patch round; 939 before), 48 pre-existing unrelated failures across 5 files (`test_auth.py`, `test_dna_fusion.py`, `test_dna_growth.py`, `test_onboarding_content.py`, `test_tutor_service.py` — confirmed identical failure set before and after this story's changes), 2 skipped — 0 regressions introduced.

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

claude-sonnet-5

### Debug Log References

- Discovered `apps/api/tests/test_lesson_ready_pubsub.py` exists OUTSIDE `tests/unit/` (directly under `tests/`), and `pyproject.toml`'s `testpaths = ["tests"]` collects the whole tree — meaning every prior story's "full regression suite" run in this session (`pytest tests/unit -q`) never actually included this file. Re-baselined against `pytest tests -q`: 937 passed, 48 pre-existing failures, 2 skipped — confirmed these 48 predate this story (not introduced by any Sprint 2 pipeline-node work) before making any change. **Correction (2026-07-16 review, Acceptance Auditor):** the initial completion notes under-enumerated the failing files as only `test_dna_growth.py`/`test_onboarding_content.py`/`test_tutor_service.py` — the real set is 5 files: those three plus `test_auth.py` (6 failures) and `test_dna_fusion.py` (1 failure), all unrelated Dev 3/Dev 4 modules with zero overlap with this story's diff.
- Red-green-refactor: wrote `test_package_summary_counts_real_nested_lesson_package_shape` first against the pre-existing buggy code — confirmed it failed with `assert 0 == 3` (the exact bug: `slides_count` silently reporting 0 against a real nested `LessonPackage`). Implemented the fix; green after.
- Updated the 2 existing tests whose fixtures/assertions encoded the old flat-stub shape and the old (extra-`session_id`-in-payload) message shape, per Task 4.1 — this is an intentional behavior change (AC-3), not a "0 test changes" refactor like Story 2-15's.

### Completion Notes List

- All 4 tasks / 12 subtasks complete. This was a reconciliation/bug-fix story, not new infrastructure — the `lesson_ready` WebSocket delivery mechanism (Redis pub/sub publish in `content_pipeline_job` → `pubsub.py`'s subscriber → `ConnectionManager.send()`) was already built by Dev 4 (`4534078 fix(arq): lesson_ready via Redis pub/sub`) and already fully wired into `main.py`'s lifespan.
- **Real bug fixed**: `package_summary`'s `slides_count`/`quiz_count`/`audio_count` had silently reported `0`/`0`/`0` for every successful lesson since Story 2-11 landed — they read top-level `slides`/`quiz_questions`/`audio_assets` keys that only existed on the old flat stub shape. Fixed to aggregate from `LessonPackage.segments[].slides`/`.quiz`, with `audio_count` as the segment count (package_builder_node guarantees exactly one narration per assembled segment).
- **Frozen-contract deviation fixed**: the published WS payload had an extra `session_id` key not present in `ws.ts`'s `LessonReadyMessage` type. Removed it — confirmed via code reading (not just assumption) that `pubsub.py`'s subscriber only ever extracted `session_id` from the CHANNEL name, never read it back out of the payload, so this was purely redundant, never load-bearing.
- `session_id` fallback behavior (`lesson_row.get("session_id") or lesson_id`) is explicitly UNCHANGED and confirmed correct — no new column, no new endpoint, matching this story's own scope boundary (AC-4) and the earlier in-session decision that a real `sessions`-table mapping is out of scope pending genuine Dev 4 coordination.
- Stale `[DEV1-SPRINT2-PENDING]` comments in both `content_pipeline.py` and `pubsub.py` (both said "Story S2-11, not yet built") corrected now that it has landed.
- **Patch round (2026-07-16):** a 3-layer adversarial review (Blind Hunter, Edge Case Hunter, Acceptance Auditor) found 0 issues from Blind Hunter (who additionally proved AC-1's `audio_count = len(segments)` claim correct against `package_builder_node`'s actual invariant, and confirmed via a broad grep of both `apps/api` and `apps/web` that removing `session_id` from the payload has no dangling consumer), 4 MEDIUM findings from Edge Case Hunter (1 downgraded from an initial HIGH after reconciling with Blind Hunter's proof that it's unreachable in production), and 1 MEDIUM + 1 LOW from Acceptance Auditor (a factual inaccuracy in this story's own failure-file enumeration, corrected above). All patchable findings applied: an `isinstance(segments, list)` defensive guard (cheap hardening against an unreachable-today but bad failure mode — crash after the WS publish already succeeded), a malformed-segment test, a test for a non-list `segments` value, and a schema round-trip test (`LessonPackage.model_validate(REAL_LESSON_PACKAGE)`) so the fixture can never silently drift out of sync with the real schema again. AC-5's one LOW note (this story adds zero new `pubsub.py`-specific tests, only reuses a pre-existing one) is accurate, not a dodge — `pubsub.py`'s forwarding behavior itself is unchanged by this story (comment-only edit), so no new behavior needed a new test there.

### File List

- `apps/api/app/workers/jobs/content_pipeline.py` (modified — `package_summary` fix + defensive guard, payload fix, stale comment fix)
- `apps/api/app/core/pubsub.py` (modified — stale comment fix only)
- `apps/api/tests/test_lesson_ready_pubsub.py` (modified, then patched — 5 new tests total, 2 existing tests updated for the new payload shape, 1 new realistic `LessonPackage` fixture replacing 3 stale flat-stub fixtures)

## Change Log

| Date | Change |
|------|--------|
| 2026-07-16 | Story created via `bmad-create-story`. |
| 2026-07-16 | Implemented via `bmad-dev-story`: fixed the `package_summary` bug (silently reporting 0/0/0 since Story 2-11 landed), removed the extra `session_id` key from the WS payload to match `ws.ts`'s frozen `LessonReadyMessage` type exactly, updated stale S2-11-not-yet-built comments, added 2 new tests + updated 2 existing tests. 939 passed / 48 pre-existing unrelated failures (unchanged from baseline) / 2 skipped in the full `tests` suite — 0 regressions. Status → review. |
| 2026-07-16 | Code review patch round: added a defensive `isinstance(segments, list)` guard (cheap hardening against an unreachable-today but bad crash-after-publish failure mode), 3 new tests (non-list `segments`, segment missing `slides`/`quiz` keys, schema round-trip check on the `REAL_LESSON_PACKAGE` fixture), and corrected this story's own failure-file enumeration (5 files, not 3). 942 passed / same 48 pre-existing unrelated failures / 2 skipped — 0 regressions. Status → done. |

### Review Findings (2026-07-16 — 3-layer adversarial review: Blind Hunter, Edge Case Hunter, Acceptance Auditor)

- [x] [Review][Patch] **FIXED 2026-07-16 — MEDIUM (downgraded from an initial HIGH after reconciling two reviewers) — `lesson_package["segments"]` being an explicit non-list value (not just a missing key) would crash `package_summary` AFTER the WS publish already succeeded**, a real design smell (client already notified, job then raises and may retry/duplicate-publish) even though Blind Hunter proved it's unreachable via a real validated `LessonPackage` (which always produces a well-formed list). Fixed with a cheap `if not isinstance(segments, list): segments = []` guard. Verified by a new test with `{"segments": None}`. [`app/workers/jobs/content_pipeline.py`] (Edge Case Hunter, reconciled against Blind Hunter's invariant proof)
- [x] [Review][Patch] **FIXED 2026-07-16 — MEDIUM — No test covered a segment dict missing the `slides`/`quiz` keys entirely (only the empty-list-present case was tested).** Added `test_package_summary_handles_segment_missing_slides_and_quiz_keys`. [`tests/test_lesson_ready_pubsub.py`] (Edge Case Hunter)
- [x] [Review][Patch] **FIXED 2026-07-16 — MEDIUM — The new `REAL_LESSON_PACKAGE` fixture had no schema round-trip check, so it could silently drift out of sync with the real `LessonPackage`/`Segment` models if either changes shape again — exactly the class of bug this story exists to fix.** Added `test_real_lesson_package_fixture_round_trips_through_schema`, asserting `LessonPackage.model_validate(REAL_LESSON_PACKAGE)` succeeds. [`tests/test_lesson_ready_pubsub.py`] (Edge Case Hunter)
- [x] [Review][Patch] **FIXED 2026-07-16 — MEDIUM — This story's own Dev Agent Record under-enumerated the 48 pre-existing test failures as only 3 files, when the real count is 5 files** (`test_auth.py`, `test_dna_fusion.py` were omitted). Didn't change the AC-6 verdict (zero overlap with this diff either way) but was a factual inaccuracy. Corrected in the Debug Log References above. [`docs/stories/2-12-lesson-ready-websocket-push.md`] (Acceptance Auditor)
- [x] [Review][Dismiss] **LOW — Sharing the realistic `REAL_LESSON_PACKAGE` fixture across the routing/payload-shape tests (which don't test `package_summary`) adds incidental coupling to a future schema change.** Not a defect — sharing one realistic fixture across related tests in the same file is normal practice, and the new schema round-trip test (see above) now protects exactly this coupling from silently breaking. Dismissed. (Edge Case Hunter) — dismissed, not a real defect.
- [x] [Review][Dismiss] **LOW — AC-5's "subscriber forwarding test already existed, no new test needed" framing could be read as underselling that zero new `pubsub.py`-specific tests were added.** Confirmed accurate, not a dodge: `pubsub.py`'s forwarding behavior itself is unchanged by this story (a comment-only edit), so no new behavior existed that needed a new test — reusing the pre-existing, still-accurate test is the correct call, not a coverage gap. Dismissed. (Acceptance Auditor) — dismissed, story's claim verified honest.
