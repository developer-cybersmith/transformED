# Story: Wire onboarding-form answers into the content-generation pipeline

**Requested:** 2026-09-28. Follows two Dev 1 handoff reference docs (repo root,
untracked, not stories): `2026-09-28-handoff-onboarding-form-30q.md` (the gap
this story closes) and `2026-09-28-handoff-book-chapter-context.md` (the
`book_context`/`chapter_context` pattern this story copies).

**Explicit scope, set by the user before implementation began:** wire only the
onboarding-time, well-defined subset — Q1-Q5 (goal/level/language/tone/
schooling, all MCQ) and the 5 Penta-Intelligence badge labels — into lesson
generation. The remaining 25 questions (Q6-Q15, Q21-Q30) have no
scoring/consumer logic behind them yet per the handoff doc's own explicit call
-out ("building the bridge alone won't make those slides personalized; it
needs its own small design pass first") — building that is out of scope here,
registered instead (see D199 below).

## Root cause / current gap

Per the handoff doc, verified independently against live code before writing
this story:
- The onboarding form itself (all 30 questions, frontend + storage + Penta
  scoring) is fully built and merged (issue #235, PR #239, merged
  2026-09-24).
- Q1-Q5 already have ONE real consumer: `assessment/service.py`'s
  `_read_onboarding_headline_answers` + `_build_learner_prompt_text`, used
  only by the live tutor-chat context endpoint (`get_learner_context`) — a
  different, already-working code path this story does not touch.
- Zero connection exists to `lesson_planner_node`/`slide_generator_node`/
  `narration_generator_node` — confirmed via `prompt_context.py`'s own module
  docstring: *"When no onboarding context is in the prompt today (it isn't —
  that injection is a separate story)..."*

## Pattern being copied

`book_context` (Story S5-1/#231) and `chapter_context` (Story 249/#249) are
the two prior, fully-shipped instances of exactly this bridge shape. Both:
fetch once in `lesson_planner_node` (before its idempotency cache check),
propagate to `slide_generator_node`/`narration_generator_node` via
`_FAN_OUT_STATE_KEYS`, format into a prompt block in a dedicated
content-module file, merge via a shared truncation-safe helper
(`prompt_context.py`) with its own independently-derived character budget and
an explicit, persisted `_truncated` flag — never silent truncation.

**One real difference this story cannot just copy:** `onboarding_answers_v2`
and `learner_dna` (badge labels) are tables owned by the **assessment**
module, not content. CLAUDE.md's one-discipline rule ("modules communicate
only through service layer, never via direct DB access into another module's
tables") means the content module cannot read them directly the way
`context.py`/`context_chapter.py` read their OWN tables. This story adds one
new **public** function to `assessment/service.py` —
`get_onboarding_lesson_context(user_id)` — as the sanctioned service-layer
crossing point; the new content-module file
(`content/context_onboarding.py`) calls that function and does its own
formatting, exactly as `context.py`/`context_chapter.py` format their own
data independently of any other module's conventions.

Onboarding context is fetched **per user**, not per book/chapter (it doesn't
change per lesson-generation run) — same never-cached, refetch-every-run
choice book/chapter context already make, just keyed by `user_id` alone.

**Precedence order** (`prompt_context.py`'s own docstring, unchanged by this
story, now given a concrete implementation): *"...user profile (onboarding)
→ book context → chapter instructions..."* — onboarding context merges
**before** book_context at all three call sites, not after.

## Design

- `assessment/schemas.py`: new `OnboardingLessonContext` model — `stated_goal`,
  `current_level`, `preferred_language`, `preferred_tone`, `schooling_level`
  (all `str | None`, mirroring `LearnerContextDNA`'s existing Q1-Q5 fields
  exactly) plus `penta_badge_labels: list[str]`.
- `assessment/service.py`: new public `get_onboarding_lesson_context(user_id)`
  — reuses the existing `_read_onboarding_headline_answers` (same headline
  read `get_learner_context` already uses) plus a new `learner_dna.badge_labels`
  read, filtered to `PENTA_BADGE_THRESHOLDS.values()` only (the 9 behavioral
  dimension badges are session-behavior-derived, not onboarding-form answers —
  out of scope for THIS bridge). Never raises; returns an empty
  `OnboardingLessonContext()` on any error, matching
  `get_book_context_prompt_context`'s own never-raises contract.
- `content/context_onboarding.py` (new): `get_onboarding_context_prompt_context
  (user_id)` — calls the above, formats a `[Onboarding Context]` block (own
  header, own field labels), defensively sanitises (collapses newlines) even
  though these are MCQ-selected values, not free-typed text — matching
  `context.py`'s own defensive posture for its MCQ fields. Never raises.
- `prompt_context.py`: new `_ONBOARDING_CONTEXT_MAX_CHARS`,
  `_ONBOARDING_TRUNCATION_MARKER`, `merge_onboarding_context()` — same shared
  `_merge_context_block` algorithm, independently-derived budget (see Scale &
  Load Q5 below — NOT copied from book_context's 2,000 or chapter_context's
  1,300).
- `graph.py`: `onboarding_context: str` + `onboarding_context_truncated: bool`
  added to `PipelineState`; fetched in `lesson_planner_node` before the
  idempotency cache check (both the cache-hit and fresh-compute return paths
  carry `onboarding_context`, matching book/chapter — see D191 amendment
  below for the one known, deliberately-accepted gap this inherits);
  `_planner_system_prompt`/`_run_planner_batch` gain an `onboarding_context`
  parameter, merged first; `slide_generator_node` and `narration_generator_node`
  merge it the same way as their existing book/chapter merges (narration
  does NOT return `onboarding_context_truncated`, same Send()-concurrency
  reason book/chapter's flags are excluded there); `package_builder_node`
  persists `onboarding_context_truncated` into `lesson_jobs.node_outputs`;
  `_FAN_OUT_STATE_KEYS` gains `onboarding_context`/`onboarding_context_truncated`,
  with matching `setdefault(...)` calls at both fan-out sites (Phase-1 and
  post-planner narration) — the exact pattern D192 already established for
  book/chapter's own truncated flags.

## Acceptance Criteria

1. **AC1**: `get_onboarding_lesson_context(user_id)` returns Q1-Q5's stored
   `response_text` values plus only the Penta-dimension badge labels (not the
   9 behavioral ones) from `learner_dna.badge_labels`.
2. **AC2**: `get_onboarding_lesson_context` never raises — a DB error, a
   missing user, or no onboarding data at all returns an empty
   `OnboardingLessonContext()`.
3. **AC3**: `get_onboarding_context_prompt_context(user_id)` formats a
   `[Onboarding Context]` block with only the non-empty fields present;
   returns `""` when nothing is set (mirrors `get_book_context_prompt_context`'s
   own `len(lines) == 1` empty-check).
4. **AC4**: `merge_onboarding_context` enforces its own independently-derived
   character budget with the same truncation-at-newline-boundary algorithm as
   `merge_book_context`/`merge_chapter_context`, with its own distinct
   truncation marker.
5. **AC5**: `lesson_planner_node` fetches onboarding context before its
   idempotency cache check and returns it on BOTH the cache-hit and
   fresh-compute paths; `_planner_system_prompt` merges it via
   `merge_onboarding_context`, not raw concatenation, and merges it BEFORE
   `book_context` (precedence order).
6. **AC6**: `slide_generator_node` and `narration_generator_node` both merge
   onboarding context into their real constructed prompts, in the same
   before-book-context order; `narration_generator_node`'s returned dict
   never includes `onboarding_context_truncated` (Send()-concurrency
   `InvalidUpdateError` hazard — same exclusion already proven for
   book/chapter).
7. **AC7**: `_FAN_OUT_STATE_KEYS` carries `onboarding_context` and
   `onboarding_context_truncated`; both fan-out router functions
   (`_fan_out_phase1_economy_nodes`, `_fan_out_narration_after_planning`)
   default them (`""` / `False`) in every dispatched payload, so
   `test_fan_out_payload_carries_every_declared_key`-style guards hold for
   the new keys too.
8. **AC8**: `onboarding_context_truncated` reaches `package_builder_node`'s
   persisted `lesson_jobs.node_outputs` record, same as
   `book_context_truncated`/`chapter_context_truncated` already do.
9. **AC9** (regression guard, mirrors D189's own test): the 5 Phase-1 economy
   nodes never reference `onboarding_context` in their source — they run
   before the fetch happens, same structural reason book/chapter context
   don't reach them either.

## Scale & Load

1. **Unit of work**: one onboarding-context fetch + format, once per
   lesson-generation attempt (keyed by `user_id` alone, not book/chapter) —
   min/typical/max is a single small `SELECT` (Q1-Q5, `.limit(5)`, already
   bounded by construction) plus one `.maybe_single()` read of
   `learner_dna.badge_labels`. No range concern — this can never grow with
   input size; it is exactly 2 bounded reads regardless of book/chapter/user
   history size.
2. **Fixed budget vs. variable input**: `merge_onboarding_context`'s own
   character cap is the one fixed budget here. Derivation:
   `OnboardingAnswer.response_text` is Pydantic-capped at 1,000 chars for
   EVERY format including `mcq` — unlike `book_context`'s MCQ fields (closed
   Python `Literal` enums with a fixed lookup table, no possible length
   growth), onboarding's `response_text` has no matching-known-option-text
   validation at the DB/API layer, so a field's stored value is only bounded
   by that 1,000-char Pydantic cap, not by today's actual (short) option
   strings. Budget must be derived from the enforced cap, not incidental
   current content, to hold for any future frontend copy change. 5 fields ×
   1,000 chars + 5 labels (~70 chars) + newlines (~5) + a badges line (5
   fixed backend-owned badge strings, ~121 chars worst case) + the
   `"[Onboarding Context]"` header (~21 chars) ≈ 5,217 measured worst case.
   Set to **5,500** (≈5.4% headroom, in line with book_context's ~2.6% and
   chapter_context's ~6.6% margins). Past the budget: explicit
   `merge_onboarding_context` truncation at a newline boundary, an explicit
   `[Onboarding context truncated]` marker, and a `onboarding_context_truncated`
   flag persisted to the admin-visible `lesson_jobs.node_outputs` record —
   never silent.
3. **Scope of every limit**: per-`user_id`, evaluated fresh on every
   lesson-generation attempt (no caching, no cross-request state) — same
   scope as book_context (per book+user) and chapter_context (per
   chapter+user), just one level broader (per user only).
4. **Unbounded reads/writes**: none introduced. The Q1-Q5 read is
   `.in_("question_id", [5 fixed ids]).limit(5)` (already-existing, bounded
   by construction); the new `learner_dna` read is `.maybe_single()` on a
   `user_id`-unique row — at most one row, same shape as
   `get_book_context_prompt_context`'s own `.maybe_single()` read.
5. **Inherited caps re-derived**: `_ONBOARDING_CONTEXT_MAX_CHARS` is derived
   fresh (see Q2) — explicitly NOT copied from book_context's 2,000 or
   chapter_context's 1,300, per CLAUDE.md's re-derive rule (matching Story
   249's own explicit re-derivation of chapter_context's budget rather than
   reusing book_context's unchanged).
6. **Concurrent check-then-act**: no new write path exists in this story at
   all — `onboarding_answers_v2`/`learner_dna` are read-only from the content
   module's perspective; nothing here writes them or performs any
   check-then-act sequence. N/A, with reason.

## Out of scope

- The remaining 25 onboarding questions (Q6-Q15, Q21-Q30) — no scoring/
  consumer logic exists for them yet; registered as D199, not silently
  dropped.
- Building any of the systems the source spec names but nothing implements
  yet (Roast Ceiling, Bilingual Cognitive Bridge, Comfortability Matrix,
  Life-Pathway engine, Scheduler agent) — each needs its own design pass
  first, per the handoff doc's own explicit statement.
- Moving book/chapter/onboarding context fetches earlier so the 5 Phase-1
  economy nodes could see them (D189's own accepted scope boundary,
  unchanged by this story — onboarding_context joins the same exclusion for
  the identical structural reason).
