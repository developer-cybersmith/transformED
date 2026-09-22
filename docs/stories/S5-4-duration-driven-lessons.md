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
allocated across segments **in proportion to each segment's `duration_min`** — the same allocator
shape as `_tier_slide_budget_per_segment` (the D87 fix). Totals: T1 = 16, T2 = 10, T3 = 5.

**AC13.** When the total is smaller than the segment count, some segments are allocated **zero**
questions. A zero-allocation segment **skips its quiz LLM call entirely** (cost saving, not a
wasted call discarded afterwards), and `Segment.quiz` is an empty list — already schema-valid
(`list[QuizQuestion]`). **The player and tutor FSM must be verified to tolerate an empty
`Segment.quiz`** (no QUIZZING state entered, no stall at segment end); if they do not, that fix is
in scope for this story, not a follow-up.

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
could not fill the budget — expected, not a defect) and **`target_missed`** (adequate content, the
generator undershot or overshot). One flag for both makes the admin signal useless, which is the
whole reason this is two values.

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
`structure_max_sections = 15` (the coalescing cap; the fan-out DoS cap `_MAX_PHASE1_SECTIONS = 60`
sits above it). Narration budget per lesson: 9.75–29.25 min, i.e. **1,243–3,729 target words**,
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
