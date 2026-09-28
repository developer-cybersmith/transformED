# Slide Strategy Alignment — 15 / 30 / 45-Minute Formats vs Current Pipeline

**Status:** Draft — scoping only, no code written, no branch created. Not yet Story-First-Gate-ready.
**Source specs (all three now read in full, all already present in the repo):**
- `docs/proposals/source-specs/2026-09-hie-lecture-format-45min-and-onboarding-pack.pdf` (v1.0) — also contains Sections 4.1/4.2/4.3, the three onboarding forms
- `docs/proposals/source-specs/2026-09-hie-lecture-format-30min.pdf` (v1.1)
- `docs/proposals/source-specs/2026-09-hie-lecture-format-15min.pdf` (v1.1)

**Affects:** `apps/api/app/modules/content/pipeline/graph.py` (`topic_selection_node`, `segment_expansion_node`, `lesson_planner_node`, `slide_generator_node`, `narration_generator_node`), `apps/api/app/schemas/lesson.py` (`Slide`, `Narration`, `QuizQuestion`, tier constants), `packages/shared/lesson_package.schema.json` + `types/lesson.ts` (frozen contract, §16 sign-off required for schema changes), a new onboarding-form module (does not exist yet).
**Relates to (already-registered, independently-found defects that this initiative must resolve or absorb):** D188, D193, D194, D195, D196 in `docs/DEFECT-REGISTER.md`.
**Policy conflict flagged (read Section D1 before scoping implementation):** the spec's Q&A slides require live IQ/EQ/SQ/CTQ/RRQ labels shown to the tutor/student; CLAUDE.md §18 binding rule says *"No raw IQ/EQ/SQ claims — branded as 'Learner DNA'... No clinical scores shown to students."* This needs a product decision before any Section 4.4/4.1-derived UI ships, not an engineering workaround.

---

## 0. What this doc is

A verified, code-checked diff between three product specs (15/30/45-minute "HIE Slide Running Strategy") and what the pipeline actually does today, organized so it can be split into BMAD stories once scoped. Every claim about current code below was read from the live file at the time of writing (2026-09-28), not recalled from memory — file:line citations are given throughout.

---

## 1. The three specs, side by side

| | **15-min (T3)** | **30-min (T2)** | **45-min (T1)** |
|---|---|---|---|
| Slide count | **7** (fixed) | **10** (fixed) | **10** (fixed) |
| Topic count | **1** | **2** | **2** |
| Q&A rounds | 1 | 2 (one per topic) | 2 (one per topic) |
| Split-screen slides | 1 (slide 4) | 2 (slides 4, 7) | 2 (slides 4, 7) |
| Broader-picture + mind-map | Combined into 1 slide each (6, 7), 1 min each | Combined into ONE closing block for both topics (9, 10) | Separate slide each (9, 10) |
| Total time | 15:00 | 30:00 | 45:00 |
| Compression logic | Drop to 1 topic entirely — "teach one topic properly, not two superficially" | Keep 2 topics, compress each component to 70–80% of the 45-min timing, merge the two topics' closing blocks into one | Reference / uncompressed |
| Structural design note | "At 15 min, splitting into two topics would starve each below the threshold for genuine comprehension" | "At 30 min there is enough runway (~13 min/topic) to preserve full diagram-building and split-screen for both" | — |

**One real point of alignment with current code:** the spec's topic count per tier (T3=1, T2=2, T1=2) is **exactly** `TIER_TOPIC_COUNT = {"T1": 2, "T2": 2, "T3": 1}` (`apps/api/app/schemas/lesson.py:97`), already implemented by `topic_selection_node` (`graph.py:1427`). This is the one structural decision the current pipeline already gets right relative to the spec — everything downstream of it diverges.

**All three carry these rules unchanged, at every tier:**
- Split-screen mandate: LEFT = technical, RIGHT = a relatable reference (movie/cricket/festival/Hinglish), same concept, both halves freshly built per topic.
- 40/60 content ratio (40% relatable/simplified, 60% core technical) within teaching + split-screen slides.
- "Penta-Intelligence" tagging (IQ, EQ, SQ, Critical Thinking, Research Reasoning) live on every Q&A slide.
- 16:9 visual ratio, diagrams + gold keyword-emphasis mandatory on every topic slide.
- Hinglish/multilingual hooks on every topic + split-screen slide.
- A spoken transcript protocol: slide numbers declared aloud, deliberate pauses, opens by quoting the learner's own onboarding answers (goal, named doubt).
- A routing table naming which onboarding-form question feeds which slide (differs per tier only in which slide numbers are addressed — the underlying question IDs, e.g. Q1/Q21 for the goal hook, Q9–Q11 for humour, Q16–Q20 for psychometric Q&A calibration, are identical across all three specs).

---

## 2. What the current pipeline actually does (verified against live code, 2026-09-28)

```
embed → topic_selection_node → segment_expansion_node → [Phase-1 fan-out] → lesson_planner_node → slide_generator_node → narration_generator_node → ...
```

- **`topic_selection_node`** (`graph.py:1427`) collapses the chapter to `TIER_TOPIC_COUNT[tier]` topics: 1 for T3, 2 for T1/T2 — matches the spec (see §1).
- **`segment_expansion_node`** (`graph.py:1554`, added by Story S5-5, fixed by S5-5b) immediately **re-slices** those 1–2 topics into however many narration "delivery units" are needed to hit the tier's narration-minutes floor (`narration_budget_minutes(tier)`, `lesson.py:110-118` — T1=45/T2=30/T3=15 as a **minimum**, not a fixed target). Its own worked example: **T3→3 units, T2→5 units, T1→8 units** for a normal-length chapter. This node has no tier-conditional branching itself — it only sees a `min_narration_minutes` float.
- **`_tier_slide_budget_per_segment`** (`graph.py:1823-1878`) then gives each of those units a **duration-proportional** slide count via `_TIER_MINUTES_PER_SLIDE_BAND` (`graph.py:1796-1800`: T1=(0.8,1.2) min/slide, T2=(1.2,1.8), T3=(2.0,3.0)), clamped to **1–8 slides per unit** (`_MIN/MAX_SLIDES_PER_SEGMENT`, `graph.py:1820,2816`).
- **`slide_generator_node`** (`graph.py:2638ff`) builds one generic slide-set per unit: `slide_id, title, bullets` (`Slide` model, `apps/api/app/schemas/lesson.py:181-192` — no other fields). No slide-type distinction anywhere.

**Net effect for T1 (45 min):** 2 topics → ~8 narration units → each unit gets its own proportional slide budget → **38–56 total slides** in a real lesson (this exact number is independently confirmed by `D193` in the Defect Register, which found it blows the $3.00/lesson cost ceiling on images alone). The spec wants exactly **10**.

---

## 3. Gap-by-gap breakdown

### B1 — Slide count is structurally impossible to fix without touching `segment_expansion_node`

The spec's 7/10/10 counts are per-lesson **totals**. The current pipeline has no concept of a lesson-wide slide-count target at all — `slide_generator_node` only ever sees one unit's own duration and computes that unit's own slide range, unaware of how many other units exist. Hitting "exactly 10" requires either:
(a) capping `segment_expansion_node`'s unit count to something the spec's per-topic slide allocation implies (roughly 3-4 slide-bearing units per topic for T1/T2, ~5 for T3), or
(b) decoupling slide count from unit count entirely — i.e., generate exactly N typed slides per topic regardless of how many narration units that topic was sliced into, with each slide type consuming 1+ narration units' worth of content.

(b) is closer to what the spec actually describes (fixed slide *roles*, e.g. "Topic I — Teaching" is one slide regardless of the topic's length) and is almost certainly the right target shape, but it's a bigger structural change than it looks: `segment_expansion_node` exists specifically to solve a **narration-duration** problem (hitting the tier's minutes floor via D195/D196's fix), and slide count has been derived from narration units ever since `_tier_slide_budget_per_segment` was written. Decoupling them means slide generation stops being 1:1 (or proportional) with narration units, which changes `narration_generator_node`'s own per-unit dispatch too (it's `Send()`-fanned-out per unit today).

**This is the central architectural question this initiative has to answer before any story can be written**, and it's exactly the tension `D193` already names from the cost angle ("D188 and D192 want deciding together").

### B2 — Slide types / schema: spec has 7 distinct roles, code has 1

`Slide` (`schemas/lesson.py:181`) = `slide_id, title, bullets, image_url, fallback_image_url`. No `layout`, `slide_type`, or split-content field exists. None of the following exist as distinguishable outputs today: Overview, Contents/Map, Topic-Teaching (diagram-mandated), **Split-Screen** (left/right, technical/relatable), Q&A (scored), Broader-Picture, Mind-Map. `slide_generator_node`'s prompt (`graph.py:2989-3006`, quoted in full in the prior turn) asks for uniform title+bullets slides with no typing at all.

### B3 — Split-screen layout does not exist anywhere in the stack

Not in the Pydantic `Slide` model, not in `packages/shared/lesson_package.schema.json`'s `Slide` definition, not in the player (`apps/web/src/components/player/`). This is a genuinely new feature end-to-end: schema field(s), LLM prompt instructions to produce two distinct halves referencing the same concept, and frontend rendering.

### B4 — Timing model is inverted

Spec: each slide *type* owns a fixed time (e.g., "Q&A is always 2:30 at 45 min, 2:00 at 30 min, 2:00 at 15 min") — time is a property of the slide's pedagogical role. Current: `lesson_planner_node` plans narration `duration_min` per unit first, and slide *count* falls out of that duration via the minutes-per-slide band. **No per-slide time budget field exists anywhere** — `Narration` (`schemas/lesson.py:239-250`) is `script, audio_url, audio_provider, timestamps, caption_lines`, nothing that pins a slide to a target seconds count. Actual on-screen dwell time today is whatever the TTS audio for that unit's script happens to run.

### B5 — 40/60 content-mix ratio: not implemented

No instruction resembling this exists in `slide_generator_node`'s or `narration_generator_node`'s prompts (both quoted verbatim in the prior turn's investigation — neither mentions a content-mix ratio).

### B6 — Hinglish/multilingual hooks: not implemented as a requirement

`chapter_context`'s `learning_need`/language fields don't map to this; there is no code instructing the LLM to weave specific-language hooks into specific slides.

### B7 — Live Q&A "Penta-Intelligence" scoring — real gap **and** a policy conflict, not just missing code

Current: `quiz_generator_node` (a Phase-1 economy node) produces `QuizQuestion{question_id, type, question, options, correct_index, explanation, difficulty}` (`schemas/lesson.py:258-268`) — generic, no IQ/EQ/SQ/CTQ/RRQ tagging field anywhere in the schema. Quiz timing in the tutor state machine (`apps/api/app/modules/tutor/state_machine/graph.py`) is **event-driven** (`quiz_trigger`, or `low_checkin_score` from `CHECKING_IN`) — not pinned to "always after slide 5 (and slide 8 at T1/T2)" as the spec requires.

**UPDATE (2026-09-28, corrected after checking Story 235):** this repo already has a live, shipped scoring system for exactly this kind of signal, and it's more advanced than first assumed. Two systems now coexist:
- **Learner DNA's original 9 behavioral dimensions** (`apps/api/app/modules/assessment/dna_fusion.py`: `pattern_recognition, logical_deduction, processing_speed, frustration_tolerance, persistence, help_seeking, goal_orientation, curiosity_index, study_independence`) — session-EMA-driven, unchanged by Story 235.
- **A real Penta-Intelligence baseline** (Story 235, `apps/api/app/modules/assessment/onboarding_questions.py`), scoring onboarding Q16–Q20 (the PDF's own CRT/EQ-scenario/SQ-dilemma/fact-vs-opinion/research-method questions, using the PDF's real answer key) into **5 new `learner_dna` columns**: `penta_iq, penta_eq, penta_sq, penta_ctq, penta_rrq` (`supabase/migrations/20260922020000_learner_dna_penta_intelligence.sql`), computed once at onboarding time.

**CLAUDE.md §18's rule is already honored, by precedent, not by policy debate:** these 5 columns are real numbers in the database, but the ONLY student-facing surface (`DNAResultCard.tsx`, the post-onboarding results screen) shows friendly badge labels instead — `"Sharp Reasoner," "Empathetic Responder," "Principled Decision-Maker," "Fact-Checker," "Deep Researcher"` (`PENTA_BADGE_THRESHOLDS`, `onboarding_questions.py`) — never the words "IQ"/"EQ"/"SQ" themselves. **Question 2 below was answered independently, correctly, and already in production**, before this doc even asked about it. Any Q&A-slide work should follow this exact precedent (score internally, never label raw) rather than inventing a new mechanism.

**What Story 235 explicitly does NOT do (its own stated scope, not a gap I found — quoted from `docs/stories/235-onboarding-30-question-redesign.md`):** Q6–Q15 (Bilingual Bridge, Info-Warfare Shield, Roast Ceiling, Scheduler/attention signals, Life-Pathway vision) and Q21–Q30 (one-liners, true/false) are **stored raw only, consumed by nothing** — the story's own text: *"each of them explicitly feeds a named system issue #235 itself lists as not yet built... store the raw answers, do not build the consuming system."* So the Roast Ceiling / Hinglish-hook / humour-profile personalization this proposal's specs lean on for slides 4/7 is captured data with **zero consumer** today, by design, not oversight.

### B8 — Transcript/pause protocol: not implemented

`narration_generator_node`'s prompt (quoted in full previously) says "write a conversational narration script for this section" — no slide-number call-outs, no `...pause...` markup, no instruction to open by quoting the learner's stated goal/doubt.

### B9 — Onboarding-form routing: **CORRECTED (2026-09-28)** — the form exists; the content-pipeline wiring doesn't

An earlier version of this section claimed Section 4.1 "does not exist," based on grepping for field names (`roast_ceiling`, `bilingual_bridge`, etc.) that turned out not to be how it was actually implemented. Verified properly this time (`apps/api/app/modules/assessment/onboarding_questions.py`, `supabase/migrations/20260922010000_onboarding_answers_v2.sql`, `docs/stories/235-onboarding-30-question-redesign.md`):

| Spec section | Maps to | Status |
|---|---|---|
| 4.2 Book Understanding (10 Q, per upload) | `book_context` (`apps/api/app/modules/content/context.py`) | **Implemented**, wired into `lesson_planner_node`/`slide_generator_node`/`narration_generator_node` |
| 4.3 Chapter Form (5 Q, per session) | `chapter_context` (`apps/api/app/modules/content/context_chapter.py`) | **Implemented**, wired into the same 3 nodes |
| 4.1 User Onboarding (30 Q, account creation) | `onboarding_answers_v2` table, all 30 questions stored (Story 235, merged) | **Form + storage fully built.** But: **not wired into the content-generation pipeline at all.** Q1–Q5 (goal/level/language/tone/schooling) feed a DIFFERENT consumer — `apps/api/app/modules/assessment/service.py`'s `LearnerContextDNA`/`_build_learner_prompt_text`, which serves the assessment/tutor module (teach-back scoring, live Q&A), not lesson/slide generation. Q16–Q20 feed the Penta-Intelligence badges (see B7 above), shown on a results screen, also not wired into slide/lesson prompts. Q6–Q15/Q21–Q30 are stored raw, consumed by nothing (Story 235's own explicit scope boundary). Confirmed by re-reading `prompt_context.py`'s docstring directly: still says *"no onboarding context in the prompt today... that injection is a separate story."* |

**Corrected conclusion:** this is a **much smaller gap than first described.** The data capture, storage, RLS, and even the psychometric scoring/badge system all already exist and are production-quality. What's missing is one specific bridge — an `onboarding_context` (or similarly named) merge layer, read once per lesson-generation run and merged into prompts, **following the exact pattern `book_context` (Story S5-1) and `chapter_context` (Story 249) already established twice in this codebase.** That pattern is: a `get_X_prompt_context()` fetch function, a `merge_X_context()` truncation-safe merge helper sharing `_merge_context_block`, a `PipelineState` field, a `_FAN_OUT_STATE_KEYS` entry, and 15-25 tests mirroring the existing two suites. This is a well-precedented, small-to-medium piece of work, not a prerequisite feature project.

Every one of the three specs' routing tables leans on Section 4.1 answers for slides 1/2 (goal hook — **available now, Q1/Q21 are Tier A/stored, just need the bridge**), 3-4/6-7 (language + humour — Q2-4 available; **Q6-11 humour/language hooks stored raw only, no consumer, Story 235's own deferred scope**), 5/8 (psychometric Q&A calibration — **Penta scores available, badges exist, just need the bridge**), 9 (career significance — Q15/Q25 available). So roughly half of Section 4.1's routing needs is genuinely just "build the bridge"; the other half (Bilingual Bridge, Roast Ceiling, humour-profile-driven reference selection) needs its own small consumer logic first, which Story 235 deliberately left undesigned.

### B10 — Broader-picture / Mind-map: not implemented as distinct slide types

No code distinguishes a "zoom out, industry relevance" slide or a "mind-map revision" slide from any other slide today.

---

## 4. Cross-reference: already-known Defect Register entries this initiative touches

| ID | Status | Relevance here |
|---|---|---|
| **D188** | Registered, not fixed | `_tier_slide_budget_per_segment` sized for many small sections, not large topics — the root cause of §3/B1's slide-count blowout. Its own trigger says "when piece 4 of issue #233 (per-duration fixed slide tables) is picked up" — **this proposal is that piece 4**, now with real source specs instead of a placeholder description. |
| **D193** | Escalated to product/CEO, unresolved | T1 cannot be produced within the $3.00/lesson ceiling at current slide counts (38-56 slides × ~$0.067/image). Fixing B1 to a real fixed-10-slide structure would very likely **fix D193 as a side effect** (10 slides ≈ $0.67 of images vs. 38-56 slides ≈ $2.51-3.77) — worth flagging to product as a reason to prioritize this. |
| **D194** | Accepted | `segment_expansion_node` slices an oversized topic from its prefix only, tail never taught — relevant if B1's fix keeps any per-topic slicing step. |
| **D195** | Fixed-guarded | The bug that made `segment_expansion_node` inert (planned N units, shipped 1 per topic) — the fix this node embodies today. Any B1 redesign must not reintroduce this. |
| **D196** | Registered, not fixed | Pre-D195 cached checkpoints can resurrect the old inert behavior on a retried job — relevant to any migration/rollout plan for a new slide-generation shape. |

---

## 5. Open questions blocking a Story-First-Gate story (need answers, not engineering)

1. **Architecture — DECIDED (2026-09-28): Decouple.** Slide generation stops being 1:1(ish) with `segment_expansion_node`'s narration units. `slide_generator_node` will instead read **all of a topic's narration units together** and produce the fixed, typed slide set (Overview / Contents / Topic-teaching / Split-screen / Q&A / Broader-picture / Mind-map) directly from the topic's full content — count and type both become spec-fixed per tier (7/10/10), not derived from how many narration units exist underneath. `segment_expansion_node` keeps its existing job unchanged (pacing narration to hit the tier's minute floor) but no longer has any influence on slide count.
   - Rejected: capping `segment_expansion_node`'s unit count to approximate the spec's totals — doesn't deliver typed slides, split-screen, or fixed per-slide timing on its own, only a closer raw count.
   - Consequence to track in scoping: `narration_generator_node`'s current `Send()`-per-unit fan-out shape is orthogonal to slide generation now, not coupled to it — a topic's slides pull from N narration units' worth of content, narration itself still generates per-unit as today. This needs to be spelled out precisely in whichever story implements Piece 2 (see §6).
2. **Psychometric labeling (§3/B7) — CORRECTED (2026-09-28): issue #233 already locked a stricter answer than this doc's own Q2 decision.** Re-read issue #233's actual text directly: *"build the slide mechanics only — show the question, collect the answer. Real live IQ/EQ/SQ/Critical-Thinking/Research scoring is explicitly OUT of scope [for slides] — kept in the separately-deferred Penta-Intelligence/CES-v2 initiative."* That supersedes this doc's earlier Q2 answer ("score it, but relabel it using Learner DNA's language") — the correct scope for the Q&A slide type is simpler: **no scoring logic of any kind lives in the slide/Q&A mechanism.** The slide just displays a question and records the student's answer, the same way `quiz_generator_node`/`QuizQuestion` already work today. Story 235's real, already-shipped Penta-Intelligence scoring (onboarding-time only, `learner_dna.penta_*` columns, badge-labeled) is a separate, already-complete system — the Q&A slide work doesn't need to build anything resembling it, extend it, or even read from it. This removes an entire piece of ambiguity from scoping Piece 6.
3. **Sequencing — RESOLVED (2026-09-28): no blocking dependency, confirmed by issue #233's own written scope.** *"Other referenced systems that don't exist yet (Roast Ceiling, Bilingual Cognitive Bridge, Life-Pathway engine, Comfortability Matrix, Scheduler agent)... degrade gracefully — use a personalization hook only when its underlying data already exists; skip otherwise. Do not build these systems here."* This settles it: slide-structure work starts now, using only the personalization that already reaches the pipeline (`book_context`/`chapter_context` — fully connected, see the companion handoff doc) and gracefully omitting everything the 30-question form would add until its own bridge is built as a later, independent piece. The `onboarding_context` bridge (Piece 5) is NOT a prerequisite for Piece 1-4 — it's additive, and when it lands later it's just one more `merge_*_context()` call added to already-working prompts, no rework needed.
4. **Frozen-contract sign-off (CLAUDE.md §16):** any `Slide`/`Narration` schema change (split-screen fields, slide typing, per-slide timing) touches `packages/shared/lesson_package.schema.json` + `types/lesson.ts`, which need sign-off from all 4 devs before merge — budget for that in sequencing, not just implementation time.
5. **Rollout scope:** does this replace slide generation for all three tiers at once, or land tier-by-tier (e.g., T3/15-min first, since it's structurally closest to current single-topic-loop behavior and lowest cost-risk)?

---

## 6. Proposed staged scope

**Status (2026-09-28): all of §5's open questions are now resolved.** No blocking dependency exists between pieces below and onboarding-form work — confirmed directly by issue #233's own written scope (§5 Q3). Piece 1 is scoped in detail in §7 below and is the recommended starting point.

- **Piece 1 — Schema & contract.** `Slide` gains a type/layout discriminator + split-screen fields + per-slide time budget; frozen-contract sign-off. No behavior change yet (existing slide shape still produced). **Scoped in detail, §7 below.**
- **Piece 2 — Fixed-count slide structure for one tier** (T3/15-min recommended as the pilot — smallest, single-topic, no split-block-merging logic, most aligned with `topic_selection_node`'s existing 1-topic decision), implementing §5 Q1's decoupled architecture concretely for at least one tier: `slide_generator_node` reads a whole topic's narration units and produces the 7 typed slides directly.
- **Piece 3 — Extend to T2/T1** (2-topic loop structure, the 30-min "compressed but not omitted" logic, the 45-min-vs-30-min timing-ratio table).
- **Piece 4 — Transcript/pause protocol + Hinglish hooks + 40/60 ratio** in `narration_generator_node`.
- **Piece 5 — `onboarding_context` bridge**, independent of Pieces 1-4, can run in parallel or after: (a) a `book_context`/`chapter_context`-shaped bridge reading `onboarding_answers_v2` + Penta badges into content-generation prompts, and (b) the not-yet-designed consumer logic for Q6-15/Q21-30 (Bilingual Bridge, Roast Ceiling, humour-profile reference selection) that Story 235 explicitly deferred. (a) is small and well-precedented; (b) is its own design question, not just wiring.
- **Piece 6 — Q&A slide mechanics** (display question, collect answer — no scoring logic at all, per §5 Q2's correction). Simpler than originally scoped; can likely fold into Piece 2/3 rather than standing alone, since it's just one of the 7 typed slides.

---

## 7. Piece 1 — Schema & Contract: detailed scope (draft, pending 4-dev sign-off)

**Goal:** add the data shape needed for typed, timed, split-screen slides — with zero behavior change to existing slide generation. This piece only changes what the `Slide` object *can* hold; `slide_generator_node` keeps producing today's shape until Piece 2 lands.

### Why this goes first
Every other piece depends on this shape existing. It also has the only real non-technical dependency in the whole initiative (4-developer sign-off on a frozen contract), which takes calendar time to schedule — starting it first means Piece 2 isn't stalled waiting on a review that could have been running in parallel.

### Proposed new fields on `Slide`

Following the exact precedent set by the avatar-fields proposal (`docs/proposals/avatar-fields-schema-change.md`) and Story 235's `learner_dna` migration: **additive, nullable, backward-compatible** — no existing field changes shape or becomes required.

| Field | Type | Purpose |
|---|---|---|
| `slide_type` | `enum \| null` — `overview \| contents \| topic_teaching \| split_screen \| qa \| broader_picture \| mind_map` | Which of the spec's 7 roles this slide fills. `null` for any pre-existing slide record (old shape, no type). |
| `topic_index` | `int \| null` | `1` or `2` for slides scoped to a specific topic (`topic_teaching`, `split_screen`, `qa`); `null` for lesson-wide slides (`overview`, `contents`, `broader_picture`, `mind_map`). |
| `target_duration_sec` | `int \| null` | The spec's fixed per-slide-type-per-tier time budget (e.g. 420 for a 45-min `topic_teaching` slide, 300 for a 30-min one) — informational for now (nothing enforces it yet; that's a later piece's job, e.g. pacing the transcript or the player). |
| `left_content` | `SplitScreenSide \| null` | Only populated when `slide_type == split_screen`. New nested type: `{heading: str, bullets: list[str]}` — the technical side. |
| `right_content` | `SplitScreenSide \| null` | Same shape, the relatable-reference side. |

`bullets` (existing field) stays exactly as-is for every type except `split_screen`, where it's expected empty and content lives in `left_content`/`right_content` instead — avoids inventing a second bullets convention.

### Files this touches

- `packages/shared/lesson_package.schema.json` — `Slide` definition, add the 5 new properties, all optional, `additionalProperties: false` stays enforced.
- `packages/shared/types/lesson.ts` — mirrored `Slide` interface + new `SplitScreenSide` interface + `SlideType` union type.
- `apps/api/app/schemas/lesson.py` — mirrored Pydantic `Slide` model + new `SplitScreenSide` model, matching the JSON schema exactly (existing convention: these three files are kept in lockstep by hand, no codegen).

### Draft ACs (for the eventual story file, not final)

1. `Slide` gains the 5 fields above in all three locations (JSON schema, TS types, Pydantic model), all optional/nullable.
2. Existing `slide_generator_node` output (no `slide_type` set) still validates against the updated schema unchanged — a real regression test loading a pre-existing lesson fixture must pass.
3. A new `SplitScreenSide` type is defined once and referenced by both `left_content`/`right_content` — not duplicated.
4. No behavior change: `package_builder_node`/any other consumer of `LessonPackage` continues to work identically for existing (non-typed) slides.
5. 4-developer sign-off recorded (per CLAUDE.md §16), same process Story 235 followed for its `learner_dna` migration and the avatar-fields proposal followed for its schema change.

### Explicitly NOT in this piece
- No change to `slide_generator_node`'s prompt or output — it doesn't set any of the new fields yet (that's Piece 2).
- No frontend rendering for split-screen layout — that's a separate frontend task once Piece 2 actually produces split-screen slides.
- No `target_duration_sec` enforcement anywhere — informational only for now.

---

*This doc is updated in place as decisions land, following the same pattern as `docs/proposals/2026-09-19-platform-changes-scope.md`'s multi-date structure — not superseded by a new file.*
