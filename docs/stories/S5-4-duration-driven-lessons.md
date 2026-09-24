# Story S5-4 — Duration-Driven Lessons (enforced 15/30/45 min seat time)

**Sprint:** 5
**Story:** S5-4
**Issue:** #230 (duration half only — see "Scope correction" below)
**Author:** Dev 4
**Status:** Ready for implementation
**Branch:** `feature/230-duration-driven-lessons`
**Date:** 2026-09-22

---

## Background

`T1`/`T2`/`T3` are labelled 45/30/15 min in the UI (`apps/web/src/types/learnerMode.ts`) but **no
backend mechanism enforces, targets, or even estimates spoken duration at generation time.**
Verified on `main` (31f6e3a):

- `lesson_planner_node` asks the LLM for a per-segment `duration_min` with **no target total**
  (`_planner_system_prompt`, graph.py:1358). Whatever it invents becomes `total_duration_min` →
  `LessonMetadata.estimated_duration_mins` (graph.py:6099).
- Slide budgets are derived **from those invented durations** (`_TIER_MINUTES_PER_SLIDE_BAND`,
  graph.py:1251) — so the only tier-sensitive lever today is anchored to an unanchored number.
- `narration_generator_node` has **no length target at all** — only a pacing *guard* that rejects
  scripts implying more than 15 words/sec (graph.py:3958).

### The finding that sets this story's shape

Duration was confirmed (2026-09-22) to mean **total seat time** — the whole session in the player:
narration + quizzes + teach-back + tutor Q&A. Under that contract the current interactive budgets
**already exceed the entire 45-minute claim before a single word of narration is spoken**:

| Component | T1 today | Source |
|---|---|---|
| Quizzes | 45–75 questions, approx **19–31 min** | `_TIER_QUIZ_COUNT_BAND` = (3,5) **per segment** x up to 15 segments (`structure_max_sections`) |
| Tutor Q&A | **10 min** | `learner_tier_t1_qa_seconds = 600` |
| Teach-back | unbounded | fires on `quiz_failed` (tutor FSM) — student-dependent |
| Narration | **4–16 min of 45** | whatever is left |

`_TIER_QUIZ_COUNT_BAND` is a **fixed per-segment count that multiplies by segment count** — the
identical defect shape **D87** already fixed for slides (fixed lesson-wide total to duration-
proportional allocation, `_tier_slide_budget_per_segment`). It was never caught for quizzes because
nothing ever measured total session time. This story applies the same fix next door.

### Scope correction (2026-09-22)

Issue #230 bundles two halves: duration enforcement **and** a chapter-build form. **The chapter-form
half is already shipped** — Dev 3's Story S5-3 (`docs/stories/S5-3-chapter-context-form.md`, PR #238,
merged to `main`) built it as a `chapter_context` table keyed `(chapter_id, user_id)`, not the
`lessons` jsonb column #230 proposed. This story is the **duration half only**. Nothing here adds a
form, a migration, or a `packages/shared` contract change.

---

## User Story

> As a student who picked "30 minutes" because that is the time I actually have, I want the lesson
> to really occupy about 30 minutes of my time — teaching, quizzes and Q&A together — so the
> duration I chose is a promise the product keeps, not a label on a card.

---

## Decisions locked (2026-09-22, product owner)

| # | Decision | Rationale |
|---|---|---|
| D-A | 15/30/45 = **total seat time**, not narration time | What a student means by "45 minutes". Forces Q&A to be subtracted, not added. |
| D-B | Seat-time split **65% narration / 15% quiz / 10% teach-back allowance / 10% tutor Q&A** | Teach-back is student-triggered and cannot be bounded at generation time — it is an **allowance**, not a budget. The seat-time contract is therefore *nominal path* (see Scale & Load Q1). |
| D-C | Keep the `T1`/`T2`/`T3` enum and DB column; reinterpret its meaning | No migration, no frozen-contract PR. Per #230 and the scope doc's recommendation. |
| D-D | Acceptable variance **+/-15%**, flagged — never silently truncated | #230. Binding CLAUDE.md rule on silent truncation. |
| D-E | Short chapters **run shorter** rather than being padded or hidden | #230. Padding conflicts with the pipeline's anti-fabrication guardrails. |
| D-F | Quiz count and `qa_phase_seconds` recalibrated **in this story**, not deferred | #230. Under D-A they are load-bearing, not cosmetic. |
| D-G | Drop the "FULL-DEPTH" / "CRITICAL-TOPICS-ONLY" depth wording | #230. Duration/word budget is the only instruction going forward. |

### Derived budget table (the numbers every AC below keys off)

Effective narration rate = `narration_words_per_minute (150) x sarvam_narration_pace (0.85)` =
**127.5 wpm**. The raw 150 is the wrong target — it bakes in an approx 18% overshoot against the
clock, because a pace below 1.0 makes the real audio *longer* than the word count implies.

| Tier | Seat | Narration | Target words | Quiz | Questions @25s | Teach-back | Tutor Q&A (today) |
|---|---|---|---|---|---|---|---|
| T1 | 45 min | 29.25 min | 3,729 | 6.75 min | **16** | 4.5 min | **270 s** (600) |
| T2 | 30 min | 19.50 min | 2,486 | 4.50 min | **10** | 3.0 min | **180 s** (300) |
| T3 | 15 min | 9.75 min | 1,243 | 2.25 min | **5** | 1.5 min | **90 s** (150) |

---

## Acceptance Criteria

### A. One source of truth for duration

**AC1.** `apps/api/app/schemas/lesson.py` gains `TIER_SEAT_MINUTES: dict[str, int] = {"T1": 45,
"T2": 30, "T3": 15}` and `SEAT_TIME_SHARES: dict[str, float] = {"narration": 0.65, "quiz": 0.15,
"teachback": 0.10, "qa": 0.10}`, with helpers `narration_budget_minutes(tier)`,
`quiz_budget_seconds(tier)` and `qa_budget_seconds(tier)`. These sit alongside
`VALID_TIERS`/`DEFAULT_TIER` (same established precedent: non-schema shared constants in the
contract-mirror file) and are **not** part of the `lesson_package.schema.json` mirror — no
`packages/shared` change, no 4-dev contract PR.

**AC2.** `SEAT_TIME_SHARES` values sum to exactly 1.0, asserted by a test. A share table that does
not sum to 1 silently under- or over-books the session.

**AC3.** `apps/api/app/modules/assessment/service.py::_TIER_MINUTES` becomes an alias of
`TIER_SEAT_MINUTES` (import, not a second literal). The existing guard test
`tests/unit/test_f2_3_tier_label_verify.py::test_tier_minutes_values` — which pins
`{"T1": 45, "T2": 30, "T3": 15}` and `int` type — **must still pass unmodified**.

**AC4.** `config.py`'s `learner_tier_t{1,2,3}_qa_seconds` defaults change to **270 / 180 / 90**
(from 600 / 300 / 150), derived from `qa_budget_seconds(tier)`. They remain env-tunable. Their
`description` strings must keep the words `Full-Depth` and `45` (T1), and must not reintroduce
`beginner`/`intermediate`/`advanced` — pinned by
`test_f2_3_tier_label_verify.py::TestConfigDescriptions`.

**AC5.** `apps/api/app/modules/tutor/service.py::qa_phase_seconds`'s docstring — which currently
documents **"T1 (beginner) ... T3 (advanced)"**, a third and unrelated reading of the same enum — is
corrected to the duration semantics. No behaviour change in that function beyond the new defaults.

### B. The planner is anchored to the narration budget

**AC6.** `_planner_system_prompt` states the narration budget explicitly: the plan's per-segment
`duration_min` values must sum to approximately `narration_budget_minutes(tier)`. The
`_TIER_PROMPT_FRAMING` depth wording ("FULL-DEPTH", "CRITICAL-TOPICS-ONLY") is **removed** (D-G);
the dict itself is deleted rather than left unreferenced.

**AC7.** After `lesson_planner_node` returns, `sum(duration_min)` is compared to the target. Outside
+/-15% it is **rescaled proportionally** (deterministic arithmetic, no second LLM call) so the
plan's durations become the contract downstream nodes are generated against. The pre-rescale sum,
the target and the scale factor are recorded (AC15). Rescaling preserves each segment's *share*, so
slide budgets (already derived from these numbers) stay internally consistent.

**AC8.** Where the chapter's extractable content cannot support the budget (see AC18), the target
used at AC7 is the **content capacity**, not the tier budget — the lesson runs shorter (D-E) and is
recorded as `content_limited`, never rescaled upward and never padded.

### C. Narration is generated to a real word budget

**AC9.** The `_plan_segment` slice dispatched to `narration_generator_node`
(`_fan_out_narration_after_planning`, graph.py:6324) carries `duration_min` in addition to
`segment_id`/`title`/`continuity_notes`. `_FAN_OUT_STATE_KEYS` is **unchanged** — `tier` is already
in it and `_plan_segment` is already dispatched, so no new fan-out key is introduced and
`tests/unit/test_fan_out_state_keys.py` must pass unmodified.

**AC10.** `narration_generator_node` computes `target_words = duration_min x effective_wpm`, where
`effective_wpm = settings.narration_words_per_minute x settings.sarvam_narration_pace`, and states
it in the prompt as an explicit target. A single helper computes `effective_wpm` — the factor is
never inlined at a call site.

**AC11.** A script whose word count falls outside +/-15% of `target_words` is **kept and flagged**,
never trimmed and never regenerated (D-D). The existing 15-words/sec pacing guard is untouched and
still rejects.

### D. Quiz volume is a lesson-level budget

**AC12.** `_TIER_QUIZ_COUNT_BAND` (per-segment) is replaced by a lesson-level total
`quiz_budget_seconds(tier) / settings.quiz_seconds_per_question` (new setting, default **25**),
allocated across segments **in proportion to each segment's teaching weight** — the same allocator
shape as `_tier_slide_budget_per_segment` (the D87 fix). Totals: T1 = 16, T2 = 10, T3 = 5.

**The weight is section body length, not `duration_min`.** `quiz_generator_node` is a Phase 1
node, dispatched *before* `lesson_planner` runs, so per-segment durations do not exist at that
point — an allocation keyed on `duration_min` is not implementable there without moving quiz
generation after the planner, which is a larger change than this story carries. Body length,
capped at `section_body_max_chars` (the text the quiz LLM is actually shown), is the available
proxy. The lesson TOTAL is identical either way, which is the property that closes the seat-time
overrun; the distribution is approximate, and a long-but-thin section can absorb questions from a
short-but-dense one. Recorded here rather than left as a silent substitution.

**AC13a.** When the total is smaller than the segment count, some segments are allocated **zero**
questions. A zero-allocation segment **skips its quiz LLM call entirely** (cost saving, not a
wasted call discarded afterwards), and `Segment.quiz` is an empty list — already schema-valid
(`list[QuizQuestion]`).

**AC13b.** The **player** must tolerate an empty `Segment.quiz`: it must not enter the QUIZ status
for a segment with no questions, and the lesson must still advance past that segment. Verified
against the real code, not the schema — `AudioTimeline` calls `enterQuiz()` at every segment
boundary unconditionally, and `QuizOverlay` renders `null` when there is no question at the current
index, so an unguarded empty quiz pauses the audio behind a blank overlay whose only exit
(`exitQuiz`) lives inside that overlay. A test must fail if the guard is removed.

**AC13c.** The **tutor FSM** must not be left waiting on a submission that can never arrive for a
zero-quiz segment. State what the FSM actually does in the Dev Agent Record rather than assuming it.

**AC14.** The tier-stamped quiz checkpoint validation (Story 2-31 AC-3,
`tests/unit/test_quiz_checkpoint_tier_stamp.py`) keeps working: a checkpoint written under the old
per-segment band must be treated as a cache **miss**, not served verbatim, since its question count
no longer matches the allocated budget.

### E. Measurement, and two kinds of miss

**AC15.** `package_builder_node` writes a `duration_report` into `lesson_jobs.node_outputs`, a
sibling of the existing `package_builder_degraded` and `section_truncations` records (same
admin-visible surface, no migration), containing at minimum: `tier`, `seat_minutes`,
`narration_target_min`, `planner_sum_before_rescale`, `rescale_factor`, `measured_narration_min`,
`variance_pct`, `outcome`, and per-segment word-count variances. Always written; empty/zero values
rather than a missing key.

**AC16.** `outcome` distinguishes **`on_target`**, **`content_limited`** (the chapter genuinely
could not fill the budget — expected, not a defect), **`target_missed`** (adequate content, the
generator undershot or overshot) and **`unknown`** (nothing could be measured at all). One flag for
the first three makes the admin signal useless, which is the whole reason they are separate; the
fourth exists so an unmeasurable lesson is never silently reported as on target.

**AC16b.** `content_limited` means "the text the pipeline could SEE could not fill the budget",
and what it sees is capped at `section_body_max_chars`. A chapter that coalesced into one huge
section therefore reads as content-limited when **our cap**, not the chapter, was the real limit.
The report must carry a `source_was_truncated` flag so the two are distinguishable; otherwise a
structure-detection failure on a 1,151-page book is indistinguishable from a genuinely short chapter.

**AC16c.** The report must cover the seat-time components it can measure, not narration alone —
a report that measured narration only would read `on_target` for a lesson whose quiz volume had
blown the budget, i.e. the story's own defect class invisible to the story's own instrument.

**AC17.** `measured_narration_min` is computed from the **real** summed `duration_ms`
(tinytag-derived in `tts_node`, already preferred by `_estimate_slide_timestamps` since S3-38), and
falls back to the word-count estimate only where that is absent (browser-fallback path). Where
measured audio exists, `LessonMetadata.estimated_duration_mins` is set from it rather than from the
planner's LLM guess.

**AC18.** Content capacity (AC8) is estimated **before** generation from the summed section-body
character count available to the pipeline, and a lesson whose target is capacity-bound is marked
`content_limited` at that point — not discovered after paying for narration and TTS.

### F. Frontend honesty

**AC19.** `apps/web/src/types/learnerMode.ts` copy is corrected. `deep`'s current description —
*"Full-depth lesson with **no time constraint** — covers everything."* — directly contradicts an
enforced 45-minute budget and must go. Descriptions state the seat-time meaning (teaching + quizzes
+ Q&A). `durationMinutes` values are unchanged.

**AC20.** Lessons generated before this story carry the *old* depth semantics. The minute badge in
`ModeSelection.tsx` is a forward-looking selector and is unaffected, but any surface that displays a
duration **for an existing lesson** must read it from that lesson's own recorded value and show no
enforced-minute claim when absent. Identify those surfaces; if none exist today, state that
explicitly in the Dev Agent Record rather than leaving AC20 silently unaddressed.

### G. Guard tests (CLAUDE.md: named as ACs, not assumed)

**AC21.** These existing guard/unit tests pass unmodified, or — where an intentional expectation
change is unavoidable — are updated **in the same commit** with a comment explaining why (silent
allowlist expansion is a process violation):
`tests/unit/test_f2_3_tier_label_verify.py`, `tests/unit/test_fan_out_state_keys.py`,
`tests/unit/test_quiz_generator_tier.py`, `tests/unit/test_quiz_checkpoint_tier_stamp.py`,
`tests/unit/test_lesson_planner_node.py`, `tests/unit/test_node_return_shape.py`,
`tests/unit/test_unbounded_queries.py`, `tests/test_tutor_graph.py`,
`tests/test_websocket_session.py`, `tests/integration/test_tier_differentiation_and_cost.py`.

**AC22.** `tests/unit/test_quiz_generator_tier.py` asserts the *old* per-segment band and **will**
need rewriting under AC12. The rewrite asserts the new lesson-level allocation — including the
zero-allocation case (AC13) — and carries a comment naming this story as the reason.

---

## Scale & Load

**Q1 — What is ONE unit of work, and what is its range?**
One unit = one chapter lesson generation at one tier. Range: 1 segment (a thin chapter) to
**60** — `structure_max_sections = 15` is the coalescing target, but `_MAX_PHASE1_SECTIONS = 60` is
the real ceiling and its truncation branch exists precisely because `structure_node` is observed to
produce more than 15. Sizing against 15 and inheriting 60 is how a cap gets re-derived against the
wrong number. **A second unit matters here and was missing from the first draft: one NARRATION
SEGMENT.** Its range is the lesson's narration budget divided across 1-60 segments — at T3 over 60
segments that is 9.75/60 = 0.16 min, i.e. a ~21-word segment with its own TTS call. Narration budget per lesson: 9.75–29.25 min, i.e. **1,243–3,729 target words**,
split across 1–15 segments. Quiz: **5–16 questions per lesson total** (was 5–75 — the change this
story makes). Beyond 15 segments, sections are already merged upstream, unchanged here.
**Explicit non-guarantee:** teach-back is student-triggered (`quiz_failed`) and unbounded in count,
so the seat-time contract is *nominal path*. The 10% is an allowance, not an enforced budget, and a
student who fails many quizzes will exceed the seat time. This is stated rather than implied because
a budget that silently excludes a variable component is the same defect class as an unbounded query.

**Q2 — Which budgets are FIXED while the input VARIES, and what happens past them?**
- Narration word target (fixed per tier) vs chapter length (varies): past it the script is **kept
  and flagged** (AC11), never trimmed. Silent truncation is banned.
- Planner duration sum (varies, LLM-generated) vs target (fixed): **proportionally rescaled**, with
  the pre-rescale value and factor recorded (AC7/AC15) — a visible arithmetic adjustment, not a
  silent one.
- Content capacity (varies) vs tier budget (fixed): the lesson **runs shorter** and is recorded
  `content_limited` (AC8/AC16). It is never padded, which would violate the anti-fabrication
  guardrails.
- `section_body_max_chars = 6000` is **inherited and unchanged** by this story; its existing
  `section_truncations` surfaced-degradation record continues to apply (see Q5).
- **The slide budget, and through it image-generation spend — the budget this story moves without
  naming it.** `_tier_slide_budget_per_segment` derives the lesson's slide total from
  `sum(segment_durations)`, and this story replaces that sum (previously the planner's free-running
  estimate) with the tier anchor. One image is generated per slide at ~$0.067 (Nano Banana) against
  the $3.00/lesson ceiling, so the slide total is a cost budget, not just a presentation one.
  Direction depends on chapter shape: on a SHORT chapter (3 segments) the rescale factor is >1 and
  T1's slide band roughly doubles (12-19 slides to 22-24, about $1.47-1.61 of images); on a LONG
  chapter (15 segments) the anchored total is smaller than the old free-running one and slide counts
  fall. Worst observed case, T1 at 15 segments, is 30 images = ~$2.01 of the $3.00 ceiling before any
  TTS or LLM spend. Past the ceiling the existing `check_ceiling` in `image_generator_node` degrades
  the lesson to text-only, which is a surfaced degradation and not silent — but it is now reachable
  from a duration choice, which it was not before.
- **`_MAX_SLIDES_PER_SEGMENT = 8` meeting a rescaled duration.** At T1 on a short chapter the
  per-segment ceiling binds (the story's own planner test shows two of three segments pinned at 8),
  so the minutes-per-slide ratio is silently not honoured. Accepted for this story — the clamp is a
  structural limit of `slide_generator`, not a duration budget — but recorded rather than discovered.

**Q3 — What is the SCOPE of every limit?**
`TIER_SEAT_MINUTES`, `SEAT_TIME_SHARES`, `quiz_seconds_per_question` and the narration rate are
**per lesson, per deployment** (module constants / env vars — identical on every replica, no
per-user or per-instance dimension). `learner_tier_*_qa_seconds` is **per session** at read time,
resolved from deployment-wide settings. None of them are per-user, so none multiply by replica
count (contrast **D49**, where `RATE_LIMIT_STORAGE_URL=memory://` multiplied every ceiling by
replica count).

**Q4 — Which reads and writes are UNBOUNDED?**
None added. This story introduces **no new Supabase query**. It reads state already in the pipeline
(`lesson_plan`, `_plan_segment`, `duration_ms` per segment — all bounded by segment count <= 15) and
adds one bounded write: the `duration_report` key inside the **existing** `lesson_jobs.node_outputs`
update in `package_builder_node`. Its per-segment variance list is bounded by the same <= 15.
`tests/unit/test_unbounded_queries.py` must stay green with no new `# BOUNDED:` exemption.

**Q5 — Which caps were INHERITED, and have they been re-derived?**
- `_TIER_QUIZ_COUNT_BAND` (3-5 / 2-3 / 1-2 **per segment**, Story 3-28): inherited, **re-derived
  and replaced** — it was sized when nobody was counting total session time, and at 15 segments it
  alone consumes 19–31 min of a 45-min budget. This is D87's defect shape one node over.
- `learner_tier_*_qa_seconds` (600/300/150): inherited, **re-derived** to 270/180/90 (AC4). The old
  values were additive to the lesson; under D-A they must be subtractive.
- `narration_words_per_minute = 150`: inherited **for a different purpose** (post-hoc timeline
  estimation, Story 2-19). Re-derived for use as a *generation target*: it must be multiplied by
  `sarvam_narration_pace` (0.85) or it systematically overshoots the clock by approx 18% (AC10).
- `section_body_max_chars = 6000`: inherited, **explicitly NOT re-derived here** — it is the
  documented open item from Story 3-39 and out of this story's scope. Its interaction with this
  story is recorded honestly: a chapter whose bodies are truncated at 6,000 chars may register as
  `content_limited` (AC16) when the real limit is the cap, not the chapter. `duration_report` must
  therefore be read alongside the existing `section_truncations` record, and AC15's report includes
  enough to tell them apart.
- `_TIER_MINUTES_PER_SLIDE_BAND` (D87): inherited, and its **input changed meaning** in this
  story — D87 sized it against `total_duration` = the planner's unanchored guess; it is now the
  enforced tier anchor. Re-derived rather than assumed: at 15 equal segments T2 yields
  `19.5/1.8 = 10.8` to `19.5/1.2 = 16.25` slides across 15 segments, i.e. about one per segment,
  which is arithmetically consistent with T2's own 1.2-1.8 min/slide ratio rather than a
  re-run of D87's "everything pinned to the floor" symptom. It does mean the `_MIN_SLIDES_PER_SEGMENT
  = 1` floor becomes the binding constraint at high segment counts, where the real slide count is
  `n_segments` regardless of budget — accepted, and the reason the cost note in Q2 exists.
- `_SOURCE_CHARS_PER_WORD = 6.0` and `_NARRATION_WORDS_PER_SOURCE_WORD = 1.0`: **new** in this
  story, not inherited, and they decide `content_limited` for every lesson. Coarse by design — they
  answer "can this chapter plausibly fill the budget at all", not any per-segment target. Their
  weakness is stated in AC16b: because the per-section term saturates at `section_body_max_chars`,
  capacity is effectively `n_sections x 7.84 min` for any chapter of ordinary density, so capacity
  is partly a segment-count test. `source_was_truncated` is what keeps that honest in the report.
- `_MIN_VIABLE_NARRATION_MIN = 1.0`: **new**. Floors the generation target so a chapter extracting
  a few hundred characters does not put "aim for about 1 words" into every prompt while still paying
  for planning, slides, images and TTS. Floors the target only — `capacity_min` is reported unfloored.
- **Known assumption, registered not hidden:** `effective_wpm` uses `sarvam_narration_pace`. On the
  Azure/browser fallback tiers the real pace differs, so a fallback lesson's measured duration will
  vary from target by more than +/-15% without the generator being at fault. This is recorded in
  `duration_report` (the fallback provider is already known per segment), not silently absorbed.

**Q6 — Is every check-then-act sequence safe under CONCURRENT requests?**
This story adds no check-then-act sequence: all budget arithmetic is pure, per-lesson, and derived
from constants plus that lesson's own state. It introduces no new idempotency key and does not
change Gate 5.
**One inherited concurrency hazard is in scope to record, not to fix here:** Gate 5 short-circuits
on `(chapter_id, tier, user_id)` (router.py:1264), while S5-3's `chapter_context` is **upserted per
generation**. A student who edits their chapter-form answers and regenerates the same chapter at the
same duration is handed the *existing* lesson, built from the *previous* answers — a success
response that silently discards the input. That is a live defect in merged code, it belongs to the
S5-3 surface rather than this story, and it must be raised as a defect-register entry with Dev 3
rather than fixed opportunistically here. This story must not make it worse: the budget constants
are not part of the idempotency key and do not need to be.

---

## Tasks

1. **RED** — failing tests for AC1–AC5 (constants, alias, config defaults, docstring), AC6–AC8
   (planner anchor + rescale + capacity), AC9–AC11 (word budget threading + variance flag),
   AC12–AC14 (lesson-level quiz allocation incl. zero-allocation), AC15–AC18 (duration_report,
   the three outcomes, measured-audio preference), AC19–AC20 (frontend copy).
2. Shared constants + helpers (`schemas/lesson.py`), `_TIER_MINUTES` alias, config defaults,
   `qa_phase_seconds` docstring.
3. Planner: budget in prompt, remove `_TIER_PROMPT_FRAMING`, post-return rescale + capacity check.
4. Narration: `duration_min` in the `_plan_segment` slice, `effective_wpm` helper, target in prompt,
   variance flag.
5. Quiz: lesson-level budget + proportional allocator, zero-allocation skip path, checkpoint
   validation, verify player/tutor tolerate an empty `Segment.quiz`.
6. `package_builder`: `duration_report`, `estimated_duration_mins` from measured audio.
7. Frontend copy (`learnerMode.ts`); resolve AC20's surfaces.
8. Run the full guard set locally before every push:
   `pytest tests/test_ces.py tests/unit/test_node_return_shape.py tests/unit/test_unbounded_queries.py -v`
   plus the AC21 list. Pull the **full** CI log and categorise every advisory-bucket FAILED line —
   a green check does not mean the advisory bucket is clean.

---

## Review

Requires the 6-agent gate: Story Quality, Blind Hunter, Test Coverage, AC Completeness, Process
Integrity, **Scale & Load**. Three of those six are not supplied by the `bmad-code-review` skill and
must be requested explicitly in the invoking prompt.

**Cross-team note:** this story edits `graph.py` (Dev 1's ownership area — content pipeline and all
11 nodes) and `learnerMode.ts` (Dev 2's). Dev 1 is to be notified before implementation starts, per
the ownership table in `CLAUDE.md` §21.

---

## Dev Agent Record

**Implemented:** 2026-09-23, Dev 4. Branch `feature/230-duration-driven-lessons`, PR #243.

### AC20 — duration surfaces for EXISTING lessons (the enumeration AC20 asked for)

Every surface that renders a per-lesson duration, audited rather than assumed:

| Surface | Renders | Verdict |
|---|---|---|
| `apps/web/src/components/player/Player.tsx:351` | `metadata.estimated_duration_mins` | **Changed.** Now labelled "min of teaching" — it is narration time, not the 15/30/45 seat time, and conflating them would make the player contradict the selector. |
| `apps/web/src/components/dashboard/upload/ModeSelection.tsx:36` | `option.durationMinutes` | **Unchanged** — a forward-looking selector for a lesson not yet generated, which AC20 exempts. |
| `apps/api/.../content/router.py` `_LIST_COLUMNS` | exposes `estimated_duration_mins` over the API | **No UI consumer** — no dashboard component renders it today. Stated here rather than left implied. |

No other surface renders a duration for an existing lesson. Pre-S5-4 lessons carry the planner's
old estimate in `estimated_duration_mins`; the "~N min of teaching" label is true of those too (it
was always a narration estimate), so no enforced-minute claim is made for a lesson that never had
one. `estimated_duration_mins` is nullable on the API — the player renders the `~ min` label with a
gap in that case, which is pre-existing and unchanged by this story.

### AC13c — what the tutor FSM does with a zero-quiz segment

The backend FSM is unaffected: `segment_complete` routes IDLE/TEACHING → CHECKING_IN
(`modules/tutor/state_machine/graph.py`), and QUIZZING is entered only on an explicit `quiz_trigger`
event, which a zero-quiz segment never sends. The stall was entirely client-side and is fixed in
`stores/player.machine.ts::enterQuiz` (AC13b).

### Review record

Six-agent adversarial review run 2026-09-23 (Story Quality, Blind Hunter, Test Coverage, AC
Completeness, Process Integrity, Scale & Load). It rejected the first implementation. Fixed in
response, with the finding that prompted each:

1. **Player hard-stall on a zero-quiz segment** (3 layers, independently) — the AC13 verification
   was never performed and the player did not tolerate the case S5-4 makes routine. Guarded in
   `enterQuiz`, with tests that fail if the guard is removed.
2. **`test_websocket_session.py::test_g9` failing in the GATING bucket** — an AC21-named guard test
   that passes on `main`. Missed because the first verification ran `tests/unit` and
   `tests/integration` but never `tests/` root. Updated, deriving from the shared table.
3. **`_quiz_count` fallback produced a quiz-free lesson** — integer division by section count gave
   `10 // 15 == 0` for every section at T2. Now re-runs the real allocator; and its own second
   version, which fell back to the whole-lesson budget, would have given every segment 16.
4. **Tier-stamped checkpoints from before this deploy served verbatim** (AC14) — a matching tier
   stamp no longer implies a matching count; oversized cached batches are truncated.
5. **Partial-TTS lessons under-reported** (AC17) — the fallback is now per segment, matching the
   comment that already claimed it, with `measured_segments`/`estimated_segments` in the report.
6. **Uncapped quiz weight** — one 500k-char section took ~92% of the questions. Capped at
   `section_body_max_chars`, matching the capacity estimate.
7. **`capacity_min == 0` escaped `content_limited`** — a chapter with no extractable text was handed
   the full tier budget. Zero is now the most content-limited case, with a floor on the target.
8. **Weakened guards** — a de-indented assertion in `test_fan_out_state_keys.py` (checking only the
   last dispatch), an exact-equality reducer guard turned into a `<=` ceiling in
   `test_howto_pipeline_e2e.py`, and a widened regex in `ModeSelection.test.tsx`. All restored.
9. **A test comment claiming a guarantee the test could not give** — the batched-planner pro-rata
   split; now guarded where it is actually visible, in the per-batch prompt.
10. **D78 conflict and the capacity/truncation conflation** — registered as **D184** and **D185**
    rather than resolved silently.

---

## Senior Developer Review — 6 agent layers (2026-09-23)

| Layer | Source | Verdict | Blocking findings |
|---|---|---|---|
| **Story Quality** | invoking prompt | REJECT → addressed | AC13 conflated three obligations and its verification was never done; two guard tests edited outside the authorised list |
| **Blind Hunter (Security)** | invoking prompt | BLOCK → addressed | Zero-quiz player stall (availability); quiz weight uncapped, letting one oversized section take ~92% of the questions |
| **Test Coverage** | invoking prompt | REJECT → addressed | Reducer guard weakened to a one-sided bound; a test documenting a property it could not detect; the three most consequential behaviours had no test that would fail on deletion |
| **AC Completeness** | invoking prompt | 5 of 22 ACs not satisfiable as written → addressed | AC13 not implemented, AC14 contradicted by its code, AC21 violated (gating-bucket regression), AC17 defective, AC20 paperwork unmet |
| **Process Integrity** | invoking prompt | REJECT → addressed | Gating bucket red (`test_g9`); zero-quiz allocation not surfaced or persisted; `D-nn`-less assumption; promised register entry never opened |
| **Scale & Load** | invoking prompt | REJECT → addressed + escalated | The D78 reversal (**D184**); Q2 missing the slide→image→cost-ceiling consequence; Q5 missing three inherited caps; the `_quiz_count` fallback |

Note for future invocations: the shipped `bmad-code-review` skill supplies only Blind Hunter, Edge
Case Hunter, Acceptance Auditor and Scale & Load. Story Quality, Test Coverage, AC Completeness and
Process Integrity were requested explicitly in the invoking prompt, as CLAUDE.md's review-gate
section requires.

**Escalated rather than decided by the implementer:** **D184** (this story reverses D78's recorded
"lesson length must be driven by the chapter's real content, not by any duration target" — at T2 an
ordinary 29-page chapter now generates roughly a third of the narration it did before), **D185**
(`content_limited` cannot distinguish a thin chapter from one our own `section_body_max_chars` cap
truncated), **D186** (fallback-TTS lessons cannot meet a Sarvam-derived target), **D187** (the
S5-3 chapter-context vs Gate 5 idempotency defect this story's Scale & Load Q6 promised to raise).

**Known deviation, not a finding:** the branch is named `feature/230-duration-driven-lessons`
(issue-led, matching `feature/236-narration-post-planner-ordering`) rather than
`sprint5/s5-4-duration-driven-lessons`. Both conventions are live in this repo; the branch was
created before the story was numbered S5-4, and renaming it now would orphan PR #243.

### Post-review merges (2026-09-24)

`main` moved twice while this story was in review, and both merges changed
behaviour rather than just resolving text:

1. **Story 232 made 60db.ai the PRIMARY TTS tier** at a default `speed` of 1.0,
   ahead of Sarvam. `_effective_narration_wpm` derived its rate from
   `sarvam_narration_pace` (0.85), so from the moment #240 merged, every
   deployment holding 60db credentials would have been budgeting ~18% fewer
   words than its audio actually needed — silently, on every lesson. The helper
   now reads the pace of whichever tier is configured primary
   (`sixtydb_api_key` + `sixtydb_voice_id` present ⇒ `sixtydb_speed`), with a
   test pinning both configurations. This is the same class of defect the story
   exists to fix, arriving from the side while the story was open.
2. **Story S5-1/S5-9** changed `_planner_system_prompt` to accept `book_context`
   and return `(prompt, was_truncated)`, and routed the narration system prompt
   through `_merge_bc`. Both S5-4 signals were folded into the new shapes: the
   narration budget replaces `tier_framing` in the planner, and the length
   instruction is spliced into `_narration_base_prompt` **before** the
   untrusted-content guard and **before** the book-context merge, so a long book
   context can never push the length target out of the prompt.
   `lesson_jobs.node_outputs` keeps both `duration_report` and
   `book_context_truncated` — siblings, not alternatives.

**Register IDs were renumbered twice** (D173-D176 → D180-D183 → D184-D187):
Story 232 had claimed D168-D179 and PR #246 then took D180. Worth a process
note for the next long-lived branch — a `D-nn` claimed when an entry is written
is not still free when the branch merges, which is precisely the collision the
register's own banner describes.
