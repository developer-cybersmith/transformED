---
status: in-progress
baseline_commit: ""
---

# Story 5-17 — Wire `force: true` on chapter-context re-generate (D187)

## Story

**As a** student who has filled in (or updated) chapter-context answers,
**I want** clicking "Generate Now" to always produce a lesson built from my latest answers,
**so that** my context is never silently discarded in favour of an older cached lesson.

## Background

**D187 root cause:** The backend's Gate 5 idempotency check
(`for existing in rows(existing_resp) if not body.force else []`) already supports a
`force: bool = False` field on `GenerateLessonRequest` (Python schema). However:

- `books.service.ts :: GenerateLessonRequest` interface has no `force` field.
- `ChapterContextForm.tsx :: handleGenerateNow()` calls `onGenerate()` without any argument.
- `ChapterGenerateControl.tsx :: handleGenerate()` never passes `force` to `generateLesson`.

Result: every "Generate Now" click after a context save goes through the idempotency path and
returns the *old* lesson, silently discarding the updated answers.

"Skip" is explicitly NOT force — it is the student saying "just generate, I have nothing to add",
which the backend idempotency logic should handle normally.

## Acceptance Criteria

- **AC1:** When a student fills chapter-context answers and clicks "Generate Now", the POST to
  `content/books/{bookId}/chapters/{chapterId}/lessons` includes `"force": true` in the JSON body.
- **AC2:** When a student clicks "Skip" on the chapter-context form, the POST body does NOT include
  a `force` field (backend defaults `force = False`). Existing idempotency behaviour is unchanged.
- **AC3:** `GenerateLessonRequest` in `books.service.ts` gains an optional `force?: boolean` field.
- **AC4:** `ChapterContextFormProps.onGenerate` prop type changes from `() => void` to
  `(force: boolean) => void`. `handleGenerateNow()` calls `onGenerate(true)`.
- **AC5:** `ChapterGenerateControl.handleGenerate(tier, force = false)` accepts `force` and passes
  it to `booksService.generateLesson`. The `onGenerate` callback is updated from
  `() => handleGenerate(phase.tier)` to `(force) => handleGenerate(phase.tier, force)`.
- **AC6:** All existing `ChapterGenerateControl` tests pass unmodified — the Skip path still sends
  `{ tier }` with no `force` field, matching the existing assertion
  `expect(seenBody).toEqual({ tier: expected })`.
- **AC7:** A new test in `ChapterGenerateControl.test.tsx` confirms that clicking "Generate Now"
  (not Skip) sends `force: true` in the POST body.

## Tasks

- [x] Write this story file and create story-first commit
- [ ] Add `force?: boolean` to `GenerateLessonRequest` in `books.service.ts` and thread it through
      `generateLesson(bookId, chapterId, tier, force?)`
- [ ] Update `ChapterContextFormProps.onGenerate` to `(force: boolean) => void`; call
      `onGenerate(true)` in `handleGenerateNow()`
- [ ] Update `ChapterGenerateControl`: `handleGenerate(tier, force = false)`,
      `onGenerate={(force) => handleGenerate(phase.tier, force)}`
- [ ] Add AC7 test in `ChapterGenerateControl.test.tsx` for the Generate Now → `force: true` path
- [ ] Run existing tests — confirm all pass (AC6)
- [ ] Write source-scan guard `tests/unit/test_d187_force_wiring_guard.py` (AC1/AC4/AC5)
- [ ] Run guard test locally
- [ ] Update D187 in `docs/DEFECT-REGISTER.md` to FIXED-GUARDED

## Scale & Load

1. **Unit of work:** One `POST /lessons` request per user click. Fixed at 1; no variance.
2. **Fixed budgets vs. variable input:** None introduced. `force` is a boolean flag appended to an
   existing JSON body. No allocation, quota, or window changes.
3. **Scope of limits:** The rate-limit (3/min, 20/hr, 3-concurrent per user) is per-user and
   unchanged. This fix does not add a new call — it changes a field on an existing call.
4. **Unbounded reads/writes:** None introduced. Frontend-only change; no new DB queries.
5. **Inherited caps re-derived:** The existing 3-concurrent cap still applies. A student clicking
   "Generate Now" repeatedly is rate-limited by the existing server-side guard (D45 is a separate
   open defect about the idempotency UNIQUE constraint race — out of scope here).
6. **Check-then-act safety:** The `force` flag bypasses the idempotency check on the backend.
   The backend's existing race condition risk (D45) is unchanged. No new CTA sequence introduced
   by this story.

## Dev Notes

Three files change, in dependency order:
1. `apps/web/src/services/books.service.ts` — add `force?` to interface and function
2. `apps/web/src/components/dashboard/books/ChapterContextForm.tsx` — prop type + call site
3. `apps/web/src/components/dashboard/books/ChapterGenerateControl.tsx` — thread `force` through

The Python guard test scans these TypeScript files as text — no compile, no runtime.

## Change Log

| Date | Change |
|------|--------|
| 2026-09-28 | Story created |
