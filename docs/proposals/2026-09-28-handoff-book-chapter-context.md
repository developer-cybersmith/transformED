# Handoff — Book Form (4.2) & Chapter Form (4.3) → Content Generation

**Status:** Handoff reference doc — not a story, no code proposed here.
**Audience:** whoever needs an accurate current-state picture of these two forms, or is building the onboarding-form bridge described in the companion doc and wants the working pattern to copy.
**Source spec:** `docs/proposals/source-specs/2026-09-hie-lecture-format-45min-and-onboarding-pack.pdf`, Sections 4.2 (pages 7-8) and 4.3 (page 9).
**Related GitHub issues:** #231 (book form, CLOSED), #249 (wire both into all content nodes, CLOSED).
**Verified against live code:** 2026-09-28.

---

## 1. Expected behaviour (what the spec asks for)

**4.2 — Book Understanding Form** (10 questions, runs once per book upload): sets ingestion depth, which chapters to cover, expected difficulty areas, deadline/pacing, and whether to follow the book's own structure or reorganize it — then that context should appear inside the actual lesson-generation prompts, framed as the book-level personalization layer.

**4.3 — Chapter/Sub-Chapter Form** (5 questions, runs at the start of every chapter session): sets this specific session's depth/duration target, what resource type the student needs most, their named doubt, their stated success outcome (plus a skip-list), and prerequisite readiness — again, meant to reach the actual generation prompts as the chapter-level layer, precedence-ordered directly after book context.

## 2. Current state — this is the one part of the whole initiative that's fully built as designed

**Both are genuinely complete implementations, not partial ones.** Confirmed field-by-field against live code, not assumed from the spec.

### 4.2 — Book context

- Frontend: `apps/web/src/components/dashboard/books/BookContextForm.tsx`.
- Backend request/response schema: `BookContextRequest`/`BookContextResponse` (`apps/api/app/modules/content/schemas.py`) — **all 10 spec fields present**: `purpose, coverage_scope, expected_difficulty, deadline_depth, structure_preference` (Q31–Q35, MCQ), `motivation, end_goal, feared_section` (Q36–Q38, one-liners, 500-char cap), `prior_attempt, outcome_clarity` (Q39–Q40, true/false).
- Storage: `book_context` table (`supabase/migrations/20260921000000_book_context.sql`).
- Prompt formatting: `apps/api/app/modules/content/context.py` — `_BOOK_CONTEXT_COLUMNS` reads all 10 fields, `_MCQ_LABELS`/`_MCQ_DISPLAY` render the 5 MCQ fields as human-readable text (e.g. `purpose: "exam_prep"` → `"Upload purpose: Exam preparation"`), all 10 fields genuinely reach the formatted prompt block, not a subset.
- Truncation budget: `_BOOK_CONTEXT_MAX_CHARS = 2_000` (`apps/api/app/modules/content/pipeline/prompt_context.py:91`), explicit-degradation on overflow (`book_context_truncated` flag, persisted to the admin-visible `lesson_jobs.node_outputs` record — never silent).

### 4.3 — Chapter context

- Backend request/response schema: `ChapterContextRequest`/`ChapterContextResponse` (`apps/api/app/modules/content/schemas.py`) — **all 5 spec fields present**: `depth_duration, learning_need` (Q41–Q42, MCQ), `specific_doubt, goal_and_skip` (Q43–Q44, one-liners, 500-char cap each), `prerequisites_done` (Q45, true/false).
- Storage: `chapter_context` table (`supabase/migrations/20260921010000_chapter_context.sql`).
- Prompt formatting: `apps/api/app/modules/content/context_chapter.py` — `_format_chapter_context_block`, with a `_sanitize()` pass (collapses newlines) as a basic prompt-injection mitigation on the two free-text fields.
- Truncation budget: `_CHAPTER_CONTEXT_MAX_CHARS = 1_300` (`prompt_context.py:125`), independently derived (not copied from book_context's 2,000 — arithmetic re-derived for chapter_context's own, smaller field set), same explicit-degradation guarantee (`chapter_context_truncated`, persisted).

### Where both reach — verified, not assumed

| Node | book_context | chapter_context |
|---|---|---|
| `lesson_planner_node` | ✅ (fetched before the idempotency cache-hit check, returned on both cache-hit and fresh paths) | ✅ (same) |
| `slide_generator_node` | ✅ | ✅ |
| `narration_generator_node` | ✅ (merges into prompt; does NOT return the truncation flag — Send()-dispatched N-way concurrently, would raise LangGraph's `InvalidUpdateError` on a non-reducer channel) | ✅ (same) |
| `summarise_segment_node`, `quiz_generator_node`, `segment_complexity_node`, `jargon_extractor_node`, `intervention_messages_node` (the 5 "Phase-1" nodes) | ❌ | ❌ |

Both context strings are merged in the same order at every site that uses both — `_UNTRUSTED_CONTENT_GUARD` → `merge_book_context` → `merge_chapter_context` — with an explicit prompt-injection guard telling the LLM to treat the content as untrusted reference text, not instructions.

## 3. What is NOT implemented — the one real, deliberately-registered gap

**The 5 Phase-1 economy nodes never see either form's answers.** This is the entire gap, and it is a written-down, intentional decision, not an oversight:

- Registered as **D189** in `docs/DEFECT-REGISTER.md`, opened by issue #249 itself.
- Reason: both contexts are fetched once, inside `lesson_planner_node` (Phase 2 of the pipeline). The 5 Phase-1 nodes are `Send()`-dispatched and complete **before** Phase 2 ever runs — there's nothing to give them at their dispatch time without moving the fetch earlier in the graph, which is a real structural change (into a new dedicated fetch step, or folded into `embed_node`/`topic_selection_node`), not a wiring fix.
- It is also judged **not obviously valuable**: unlike slides/narration (which plainly benefit from a student's named doubt or feared topic), it's not established that quiz/jargon/complexity/intervention-message quality actually improves from seeing this data.
- Registered trigger for revisiting: *"if a future story's own review or user feedback shows quiz/jargon/complexity/intervention quality is measurably worse without either context — not before."*
- Owner: Dev 1.

**Two smaller, also-registered gaps, lower priority, not blocking anything today:**
- **D190**: `chapter_context`'s two free-text columns (`specific_doubt`, `goal_and_skip`) have no DB-level `CHECK (length <= 500)` constraint — only Pydantic enforces the 500-char cap on the one real write path. Same class of gap already registered as D178 for `book_context`'s equivalent columns. Latent, not exploitable today (Pydantic blocks the only real write path), but the 1,300-char chapter budget's "proven sufficient" claim technically depends on that Pydantic cap holding, not a DB guarantee.
- **D191**: on an ARQ-retried lesson job specifically, if `lesson_planner_node` cache-hits (skips recompute because a prior attempt already produced a plan), the cache-hit return path doesn't re-surface `book_context_truncated`/`chapter_context_truncated` into that attempt's own persisted record — an admin-record accuracy gap on a narrow retry path, not something a student would ever see wrong.

## 4. Bottom line

If you're comparing this against the onboarding-form handoff doc: **this is what "done" looks like for this initiative.** Both forms — data capture, storage, RLS, prompt formatting, truncation-safe merging, explicit degradation surfaced to admins, and wiring into all 3 real content-generation nodes — are complete, tested (`test_s5_1_book_context.py`, `test_249_context_wiring.py`), and reviewed (both went through the full BMAD 6-agent adversarial review process before merge). The only open item is the deliberately-scoped-out Phase-1-node question (D189), which was evaluated and explicitly deferred, not missed.
