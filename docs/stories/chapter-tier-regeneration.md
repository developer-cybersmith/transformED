# Story: Generating a chapter at another tier is unreachable once any lesson is ready

**Requested:** 2026-10-01. User-reported: "we don't have a feature to regenerate a lesson in a
different tier. once generated in t1, it can't be regenerated into t2 or t3."

**Investigated before writing this story** (not assumed): the backend already fully supports
this — `content/router.py`'s Gate 5 idempotency key is `(chapter_id, tier, user_id)`, there is no
UNIQUE constraint on `lessons.chapter_id` or `(chapter_id, tier)` in any migration, and
`ChapterResponse` already models "a lesson per tier" (`lesson_count`/`lessons[]`), proven against a
real 1,151-page book generating two tiers on one chapter (`docs/stories/1-16-prove-it-end-to-end.md`
AC7). The gap is frontend-only.

## Root cause

`ChapterGenerateControl.tsx` already has a working tier picker and a "Generate at a different
depth" button (shown in its own `created`/`existing` phases) — but `ChapterRow.tsx:155-178` only
ever MOUNTS `ChapterGenerateControl` when the chapter has no ready lesson:

```
{readyLessonId != null ? (<Watch Link>)
 : isGenerating ? (<Generating spinner>)
 : (<ChapterGenerateControl .../>)}
```

The instant the chapter's newest lesson (at whatever tier) reaches `ready`, this branch permanently
renders only a Watch link on every subsequent render/reload. `ChapterGenerateControl` — and
therefore its tier picker — is unmounted and never reachable again from the dashboard for that
chapter. The "N other lessons" expandable list (Story 2-47) only lets a student WATCH existing
ready lessons at other tiers; it has no affordance to START a new tier's generation.

No existing `docs/DEFECT-REGISTER.md` entry or story documents this exact gap (checked: D45/D53/D54
are adjacent idempotency/concurrency issues, not this; `docs/stories/2-47-merge-library-into-books.md`
only added viewing non-latest lessons, not generating new ones).

## Fix

Confirmed with the user (AskUserQuestion, 2026-10-01): show a "Generate another tier" entry point
**alongside** the Watch link, not folded into the "other lessons" list.

1. `ChapterRow.tsx`: when `readyLessonId != null`, render the Watch link AND mount
   `ChapterGenerateControl` as siblings (both `shrink-0` cells in the existing flex row), instead of
   the Watch link replacing it. The `isGenerating` branch is untouched — this story only addresses
   the `ready` state.
2. `ChapterGenerateControl.tsx`: it already receives the full `chapter` prop, so no new prop is
   needed. Add `hasReadyLesson = chapter.latest_lesson?.status === "ready"` and use it to relabel
   the idle-phase button from the bare "Generate" to **"Generate another tier"** when a ready
   lesson already exists (mutually exclusive with the existing `isRetry` — `failed` and `ready` are
   different statuses) — so a student isn't confused into thinking the button regenerates the same
   content. `ModeSelection`'s tier cards are unchanged: all three tiers are always shown, including
   the already-generated one — this is the existing, deliberate design (re-picking the same tier
   correctly reaches the 200/`ALREADY_READY_MESSAGE` path, per the component's own comment) and is
   not altered by this story.

## Acceptance Criteria

1. **AC1**: `ChapterRow` renders both the Watch link and a Generate entry point when the chapter's
   latest lesson is `ready`.
2. **AC2**: that Generate entry point's idle-phase button reads "Generate another tier" (not bare
   "Generate") when a ready lesson already exists for the chapter.
3. **AC3**: the full tier-picker flow (`ModeSelection` → `ChapterContextForm` → generate) works
   identically whether reached from a chapter with zero lessons or one with a ready lesson —
   same component, no forked logic.
4. **AC4**: picking a tier that already has a ready lesson for this chapter still correctly reaches
   the existing 200/`ALREADY_READY_MESSAGE` path (unchanged backend/component behavior — this story
   only changes whether the control is reachable, never its own internal correctness).
5. **AC5**: the `isGenerating` (queued/running) branch of `ChapterRow` is unchanged — this story
   does not add a second concurrent-generation affordance while one is already in flight.
6. **AC6**: existing `ChapterRow`/`ChapterGenerateControl` tests continue to pass unmodified; new
   tests cover AC1 and AC2 directly.

## Scale & Load

N/A — a pure frontend rendering/conditional change. No new network calls, no new endpoint, no
change to request/response shape. The backend path this unblocks (`POST .../chapters/{id}/lessons`
with a different `tier`) already exists, is already rate-limited (3/min, 20/hr per user) and
already concurrency-capped (Gate 7, 3 concurrent per user) — unchanged by this story. No new
unbounded read/write: `ChapterGenerateControl` reads only the already-fetched `chapter` prop.

## Out of scope

- Any backend change — the backend already supports this fully, confirmed by investigation before
  writing this story.
- Filtering `ModeSelection` to hide already-generated tiers — the existing "always show all three,
  same tier reaches the 200 path" design is deliberate and unchanged.
- Adding a second Generate affordance while a generation is already in flight (`isGenerating`
  branch) — out of scope per the user's own confirmed fix scope.
- Folding this into the "N other lessons" expandable list — the user explicitly chose the
  alongside-Watch option over this alternative.
