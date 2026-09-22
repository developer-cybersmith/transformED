# Story S5-3 — Chapter Context Form (§4.3 — 5 Questions Per Session)

**Sprint:** 5  
**Story:** S5-3  
**Author:** Dev 3  
**Status:** Ready for implementation  
**Branch:** `sprint5/s5-3-chapter-context-form`  
**Date:** 2026-09-21

---

## Background

The user flow (confirmed by user 2026-09-21) is:
> Book upload → Book form (S5-1) → Chapter selection → Duration (15/30/45) → **Chapter form** → Generate

This story implements the chapter form — the per-session form that appears in `ChapterGenerateControl`
AFTER the student selects a duration and BEFORE the generation API call is made.

The form contains 5 questions from §4.3 of the HIE design spec:
- **Q41** `depth_duration` — MCQ: How deep + how long for this specific chapter?
- **Q42** `learning_need` — MCQ: What do you need most in this lesson?
- **Q43** `specific_doubt` — One-liner: What specifically do you want to understand?
- **Q44** `goal_and_skip` — One-liner: What should you be able to do? What to SKIP?
- **Q45** `prerequisites_done` — T/F: Prerequisites completed for this chapter?

Answers are stored per `(chapter_id, user_id)` and upserted on each generation (overwriting previous
answers). The pipeline reads them in `lesson_planner_node` and injects them at the "chapter
instructions" precedence slot (§5 of the strategy doc — after book context, before user prompt).

**Dependency note:** This story branches from `main`. When S5-1 (`sprint5/s5-1-book-context-form`)
is merged to main first, the chapter context injection in `graph.py` will sit at the correct
precedence level (chapter instructions, after book_context). Until then, chapter context is
appended immediately after `tier_framing` in `_planner_system_prompt`.

---

## User Story

> As a student about to generate a lesson, I want to tell the AI exactly what I need from this
> specific chapter — my doubt, my goal, and what to skip — so the generated lesson is personalised
> to my exact situation, not just my overall book intent.

---

## Acceptance Criteria

### Database

**AC1.** New migration `supabase/migrations/20260921010000_chapter_context.sql` creates table
`chapter_context` with columns: `id` (UUID PK), `chapter_id` (FK→chapters, ON DELETE CASCADE),
`user_id` (FK→auth.users, ON DELETE CASCADE), `depth_duration` (TEXT, nullable), `learning_need`
(TEXT, nullable), `specific_doubt` (TEXT, nullable), `goal_and_skip` (TEXT, nullable),
`prerequisites_done` (BOOLEAN, nullable), `updated_at` (TIMESTAMPTZ NOT NULL DEFAULT now()).
UNIQUE constraint on `(chapter_id, user_id)`. RLS enabled: `SELECT/INSERT/UPDATE` for
`auth.uid() = user_id` only. No DELETE RLS — rows are never deleted, only overwritten.

**AC2.** The migration file is the ONLY place these columns are defined. No hand-coded column lists
outside the migration and `context_chapter.py` (AC5 below).

### Backend — `context_chapter.py`

**AC3.** New file `apps/api/app/modules/content/context_chapter.py` provides three functions:
- `upsert_chapter_context(chapter_id, user_id, *, depth_duration, learning_need, specific_doubt, goal_and_skip, prerequisites_done)` — upserts into `chapter_context` table; all fields nullable.
- `get_chapter_context_row(chapter_id, user_id)` — returns the row dict or `None`.
- `get_chapter_context_prompt_block(chapter_id, user_id)` — returns a formatted string block
  suitable for injection into a planner system prompt; returns `""` when no row exists or all
  fields are `None`.

**AC4.** `get_chapter_context_prompt_block` format:
```
\n\n[Chapter Instructions]
Depth and time needed: <human-readable label or blank>
Primary learning need: <human-readable label or blank>
Specific doubt: <text or blank>
Goal and skip: <text or blank>
Prerequisites completed: Yes/No
```
Only fields with non-None values are included. A row with all-None fields returns `""` (no block).

**AC5.** MCQ values are stored as compact enum strings and mapped to readable labels in prompt output
(same pattern as book context). Never expose raw enum values to the LLM.

**AC6.** Text fields (`specific_doubt`, `goal_and_skip`) have a 500-char Pydantic max_length in
the request schema. Internal newlines are collapsed to a single space before formatting (injection
guard — same as AC3 in S5-1 review findings).

**AC7.** No DPDP-sensitive data in Langfuse traces — the planner node must log only
`has_chapter_context: bool`, never the field values.

### Backend — `schemas.py`

**AC8.** New Pydantic models in `apps/api/app/modules/content/schemas.py`:
- `ChapterContextRequest` — 5 optional fields with appropriate Literal types for MCQ fields,
  `str | None` with `max_length=500` for text fields, `bool | None` for T/F.
- `ChapterContextResponse` — same 5 fields plus `chapter_id: str` and `updated_at: str | None`.

MCQ Literal types:
- `depth_duration`: `Literal["quick_15_20m", "standard_30_45m", "deep_60_90m", "mastery_multi", "ai_decide"] | None`
- `learning_need`: `Literal["examples_analogies", "formulas_derivations", "diagrams_visuals", "practice_questions", "adaptive_mix"] | None`

### Backend — `router.py`

**AC9.** Two new endpoints added to `apps/api/app/modules/content/router.py`:
- `PUT /books/{book_id}/chapters/{chapter_id}/context` — upserts chapter context; requires auth
  (JWT); verifies chapter belongs to book and to caller. Returns `ChapterContextResponse`.
- `GET /books/{book_id}/chapters/{chapter_id}/context` — returns existing context or 204 (no
  content) when none exists. Requires auth.

Both endpoints follow the same auth pattern as the existing book context endpoints (AC9 in S5-1).
No new auth abstraction needed.

**AC10.** The PUT endpoint sanitizes text fields (collapse internal newlines) before calling
`upsert_chapter_context`. The GET endpoint returns the raw stored values (sanitization is
write-path only).

### Backend — `graph.py` pipeline injection

**AC11.** `lesson_planner_node` in `graph.py` fetches chapter context AFTER checking the cache
(same position as any context fetch). The chapter context block is appended to the planner system
prompt after `tier_framing`:
```python
system_prompt = _planner_system_prompt(tier_framing)
chapter_ctx_block = await get_chapter_context_prompt_block(chapter_id, user_id)
# when book_context (S5-1) is also present: book_ctx is merged last via merge_book_context
full_prompt = system_prompt + chapter_ctx_block
```

**AC12.** `chapter_id` and `user_id` must already be present in the LangGraph state (they are —
`chapter_id` is set when the lesson is created in `router.py`, and `user_id` is in state from
the job enqueue). No new state keys added for S5-3; chapter context is fetched from the DB, not
from state.

**AC13.** The chapter context fetch has a graceful fallback: if the DB call fails (network error,
table not found), log a warning and continue with `""` — never fail the lesson generation for a
missing chapter context. An explicit `try/except` wraps the call.

**AC14.** Langfuse span for `lesson_planner_node` logs only `has_chapter_context: bool`, never
field values.

**AC15.** Guard tests pass: `test_node_return_shape` (no `**state` spread introduced),
`test_unbounded_queries` (the chapter context query is a single-row `.eq().single()` — naturally
bounded, add `# BOUNDED:` comment), `test_no_hardcoded_*` (no model strings hardcoded).

### Frontend — `books.service.ts`

**AC16.** New TypeScript types and service methods added to
`apps/web/src/services/books.service.ts`:
- `DepthDurationValue`, `LearningNeedValue` type aliases (union strings matching the Literal types)
- `ChapterContextRequest` and `ChapterContextResponse` interfaces
- `booksService.putChapterContext(bookId, chapterId, body)` — PUT call
- `booksService.getChapterContext(bookId, chapterId)` — GET call, returns `ChapterContextResponse | null` (null on 204)

### Frontend — `ChapterContextForm.tsx`

**AC17.** New component `apps/web/src/components/dashboard/books/ChapterContextForm.tsx`:
- Props: `bookId: string`, `chapterId: string`, `onGenerate: () => void`, `onSkip: () => void`
- On mount: fetches existing chapter context and pre-populates fields.
- Q41: chip-style radio buttons (5 options, same style as BookContextForm's MCQ chips).
- Q42: chip-style radio buttons (5 options).
- Q43, Q44: single-line `<input type="text" maxLength={500} />` with placeholder text.
- Q45: True/False toggle buttons (same style as BookContextForm's boolean toggles).
- Primary action: "Generate Now" button → calls `booksService.putChapterContext` then calls
  `onGenerate()`. The PUT is fire-and-forget with graceful failure: if it fails, log a warning
  and still call `onGenerate()` so the lesson is never blocked by a context save failure.
- Secondary action: "Skip" link → calls `onSkip()` immediately (no PUT; existing DB answers
  are preserved and the pipeline will use them if present).
- Loading and save states handled locally; no global state needed.

**AC18.** The form is wrapped in a 500-char client-side maxLength guard on text inputs (matches
AC6). No validation required for MCQ or boolean fields — they are always optional.

### Frontend — `ChapterGenerateControl.tsx`

**AC19.** New `"chapter-form"` phase added to the `Phase` union:
```typescript
| { kind: "chapter-form"; tier: LearnerTier }
```

**AC20.** `handleSelect(tier)` — previously directly called `booksService.generateLesson` —
is changed to `setPhase({ kind: "chapter-form", tier })` only. No generation API call in
`handleSelect` any more.

**AC21.** New `handleGenerate(tier: LearnerTier)` function contains the original API call logic
from `handleSelect` (unchanged). Called by `ChapterContextForm`'s `onGenerate` and `onSkip`.

**AC22.** In the JSX, a new branch renders `<ChapterContextForm>` when `phase.kind === "chapter-form"`.
Cancel button in the header row is updated to reset to `"idle"` from any of `choosing` or
`chapter-form`.

**AC23.** The existing `ALREADY_GENERATING_MESSAGE`, `ALREADY_READY_MESSAGE`,
`GENERATION_STARTED_MESSAGE`, `TRUNCATION_WARNING` constants are **unchanged** — they are a
frozen contract for Dev 2's tests.

### Tests

**AC24.** New file `apps/api/tests/test_s5_3_chapter_context.py` covers:
- Schema: MCQ Literal validation rejects invalid values; text fields respect 500-char cap.
- `get_chapter_context_prompt_block`: all-None row returns `""`.
- `get_chapter_context_prompt_block`: partial row includes only non-None fields.
- `get_chapter_context_prompt_block`: internal newlines in text fields are collapsed to spaces
  (injection guard — MUST NOT appear in prompt).
- `get_chapter_context_prompt_block`: False `prerequisites_done` emits "No" (not omitted).
- MCQ display: stored value "examples_analogies" maps to human-readable label in prompt output.

---

## Out of Scope

- Adding chapter context to `_FAN_OUT_STATE_KEYS` for narration nodes — lesson_planner is the
  primary consumer; narration injection is a Phase 2 enhancement.
- Slide generator injection — the planner's lesson plan already structures the lesson.
- S5-1's book context injection — `merge_book_context` is S5-1's concern; this story adds only
  chapter context.
- Chapter context in session reports or analytics endpoints.

---

## Files Changed

| File | Change |
|------|--------|
| `supabase/migrations/20260921010000_chapter_context.sql` | New: chapter_context table + RLS |
| `apps/api/app/modules/content/context_chapter.py` | New: upsert/get/prompt_block functions |
| `apps/api/app/modules/content/schemas.py` | Add ChapterContextRequest/Response models |
| `apps/api/app/modules/content/router.py` | Add PUT/GET /chapters/{id}/context endpoints |
| `apps/api/app/modules/content/pipeline/graph.py` | lesson_planner_node: fetch + inject chapter context |
| `apps/web/src/services/books.service.ts` | Add chapter context types + service methods |
| `apps/web/src/components/dashboard/books/ChapterContextForm.tsx` | New: the form component |
| `apps/web/src/components/dashboard/books/ChapterGenerateControl.tsx` | Add chapter-form phase |
| `apps/api/tests/test_s5_3_chapter_context.py` | New: unit tests |

---

## Scale & Load

**Q1 — Unit of work and range:**  
One unit = one DB upsert (PUT /context) + one DB read (in lesson_planner_node). The upsert is a
single `UPSERT` on a uniquely-keyed row `(chapter_id, user_id)`. Range: 0 or 1 row per call —
naturally bounded by the UNIQUE constraint.

**Q2 — Fixed budgets while input varies:**  
Text fields `specific_doubt` and `goal_and_skip` are capped at 500 chars each (Pydantic
`max_length=500`). The formatted `chapter_context` block is at most:
`[Chapter Instructions]\n` (~25 chars) + 5 lines × (label ~30 chars + value ~500 chars) ≈ ~2,650 chars maximum.
This goes into the planner prompt after `tier_framing` (~620 chars) and before the untrusted content
guard. The total prompt remains well within GPT-4o's 128k context. If truncation of chapter context
is needed in the future, an explicit `[Chapter context truncated]` marker (same as book context
pattern) must be used — silent truncation is never acceptable.

**Q3 — Scope of every limit:**  
500-char cap: per-field, per-request. The UNIQUE constraint on `(chapter_id, user_id)` means at
most 1 row per student per chapter — the row count is bounded by product_of(user count, chapter count).

**Q4 — Unbounded reads/writes:**  
`get_chapter_context_prompt_block` fetches a single row via `.eq("chapter_id", ...).eq("user_id", ...).single()`.
`# BOUNDED: single-row by (chapter_id, user_id) UNIQUE constraint` comment required.
The PUT upsert affects exactly one row. No unbounded queries.

**Q5 — Inherited caps re-derived:**  
No inherited caps. This is a new table and new code path.

**Q6 — Check-then-act under concurrent requests:**  
The PUT endpoint issues a single `UPSERT … ON CONFLICT (chapter_id, user_id) DO UPDATE`.
The UNIQUE constraint makes this a safe atomic operation — no check-then-act. No race condition.

---

## BMAD Pre-Implementation Gate

- [x] Story file created at `docs/stories/S5-3-chapter-context-form.md`
- [ ] Story-only commit on `sprint5/s5-3-chapter-context-form`
- [ ] Story-only push to remote
- [ ] Implementation begins (RED phase — failing tests first)
