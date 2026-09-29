# Handoff — 30-Question Onboarding Form (Section 4.1) → Content Generation

**Status:** Handoff reference doc — not a story, no code proposed here.
**Audience:** whoever picks up wiring onboarding data into lesson/slide generation.
**Source spec:** `docs/proposals/source-specs/2026-09-hie-lecture-format-45min-and-onboarding-pack.pdf`, Section 4.1 (pages 3-6) + Master Routing Map (page 11).
**Related GitHub issues:** #235 (form itself, OPEN, PR #239 merged 2026-09-24), #233 (slide generation, OPEN, touches this data as a consumer).
**Verified against live code:** 2026-09-28.

---

## 1. Expected behaviour (what the spec asks for)

Per Section 4.1's own Master Routing Map, the 30 onboarding answers are meant to personalize the actual lesson content a student watches — not just a one-time results screen. Specifically:

- **Q1, Q21** (primary goal, 6-month goal) → opening hook on the lesson's first slide(s): *"Today we conquer [Topic] — remember, YOU said your goal is [Q21 answer]."*
- **Q2–Q4** (level, language, tone) → difficulty weighting and tone of the generated content.
- **Q6–Q7** (Bilingual Bridge: inner-voice language, translation gap) → mother-tongue/Hinglish hooks woven into topic and split-screen slides.
- **Q9–Q11** (comedy culture, roast reaction, Roast Ceiling) → which relatable reference (movie/cricket/festival) gets picked for the split-screen slide, and how far the tutor's tone can push.
- **Q15, Q25** (5-year vision, 2030 self-view) → framing for the "broader picture / industry relevance" slide.
- **Q16–Q20** (Penta-Intelligence psychometric baseline: CRT, EQ scenario, SQ dilemma, fact-vs-opinion, research method) → calibrates the difficulty of live Q&A during the lesson.
- Every other question (Q5, Q8, Q12–14, Q22–24, Q26–30) feeds a named system: Comfortability Matrix, Information Warfare Shield, attention/scheduler pacing, etc.

## 2. Current state (verified against live code)

**Fully built and merged (Story 235 / issue #235, PR #239 by `Developer-2-max`, merged 2026-09-24):**

- Frontend: `apps/web/src/components/onboarding/OnboardingFlow.tsx`, `QuestionCard.tsx`, `questions.ts` — all 30 questions, all 3 answer formats (MCQ / one-liner / true-false).
- Backend question spec: `apps/api/app/modules/assessment/onboarding_questions.py` — `Q_SPEC` (all 30 ids + formats), `MCQ_OPTION_COUNTS`, `ALL_QUESTION_IDS`.
- Storage: `onboarding_answers_v2` table (`supabase/migrations/20260922010000_onboarding_answers_v2.sql`) — every one of the 30 raw answers, RLS-protected, one row per `(user_id, question_id)`.
- Psychometric scoring: `PENTA_SCORING` (the PDF's real Q16-Q20 answer key), `PENTA_DIMENSIONS`, `PENTA_QUESTION_MAP` — writes 5 new columns on `learner_dna` (`supabase/migrations/20260922020000_learner_dna_penta_intelligence.sql`): `penta_iq, penta_eq, penta_sq, penta_ctq, penta_rrq` (numeric 0-100, computed once at onboarding time).
- Student-facing labels: `PENTA_BADGE_THRESHOLDS` maps each Penta dimension to a plain-English badge ("Sharp Reasoner," "Empathetic Responder," "Principled Decision-Maker," "Fact-Checker," "Deep Researcher") — the raw "IQ/EQ/SQ" words never reach the student, per CLAUDE.md §18. Same convention already used for the original 9 behavioral dimensions (`BADGE_THRESHOLDS`).

**Where the data actually goes today (all verified, nothing assumed):**

| Questions | Consumer | What it's used for |
|---|---|---|
| Q1–Q5 (Goal, Level, Language, Tone, Schooling) | `LearnerContextDNA` / `_build_learner_prompt_text` (`apps/api/app/modules/assessment/service.py`), served via `GET /assessment/.../learner-context` | **Live tutor chat only** — the endpoint's own docstring: *"Internal endpoint called by Dev 4's tutor module to personalise LLM responses."* This is the real-time conversation during a session, not pre-built lesson content. |
| Q16–Q20 (Penta-Intelligence) | `DNAResultCard.tsx`, via `OnboardingResult.badge_labels`/`profile_text` | **One-time results screen** right after onboarding completes. Never read again afterward. |
| Q6–Q15, Q21–Q30 (Bilingual Bridge, Info-Warfare Shield, Roast Ceiling, attention/scheduler signals, Life-Pathway vision, all one-liners, all true/false) | Nothing | **Stored only.** Confirmed by grep (zero consumers anywhere in `apps/api/app`) and by the story's own explicit scope note (see §3). |

**Process note (unconfirmed, worth checking, not asserted as fact):** issue #235 is still **OPEN** on GitHub despite PR #239 being merged. The PR's last status update (2026-09-23, one day before merge) said: *"Open blocker: Dev 1 has not yet reviewed [the frozen-contract schema changes]... please don't merge until that lands."* Whether that review happened before the 2026-09-24 merge, or the issue was simply never closed as bookkeeping, isn't established here — flagging for whoever picks this area up to verify, not claiming either way.

## 3. What is NOT implemented — the actual gap

**Zero connection to the content-generation pipeline.** None of the 30 answers, in any form (raw, scored, or badge-labeled), reach `lesson_planner_node`, `slide_generator_node`, or `narration_generator_node`. Verified directly: `apps/api/app/modules/content/pipeline/prompt_context.py`'s own module docstring still reads *"When no onboarding context is in the prompt today (it isn't — that injection is a separate story), book context is simply the first personalization layer."*

Concretely, none of these exist:
- No `get_onboarding_context_prompt_context()` fetch function (the pattern `apps/api/app/modules/content/context.py` and `context_chapter.py` both already establish for book/chapter context).
- No `merge_onboarding_context()` merge helper in `prompt_context.py`.
- No `onboarding_context` field on `PipelineState` (`graph.py`).
- No entry in `_FAN_OUT_STATE_KEYS`.

**And, separately, no consuming logic exists yet for the systems the spec assumes:**
- No "Roast Ceiling" enforcement anywhere (tone-intensity limiting).
- No "Bilingual Cognitive Bridge" (mother-tongue/Hinglish hook insertion).
- No "Comfortability Matrix" (25 personality modes).
- No "Life-Pathway engine" (career-goal-driven content framing).
- No "Scheduler agent" duration auto-selection from Q14 (today, tier/duration is an explicit user click in `ModeSelection.tsx`, not inferred from onboarding data).

**Why this specific gap exists — traced to source, not guessed:** both issues that touched this area explicitly declined to build it, independently of each other:
- Issue #235's own locked decision: *"Wire answers into personalization only where a consumer already exists today... Where the spec references a system that doesn't exist yet... store the raw answers, do not build the consuming system."*
- Issue #233's own locked decision: *"use a personalization hook only when its underlying data already exists; skip otherwise. Do not build these systems here."*

Each assumed the connecting piece was either already handled or out of its own scope. No issue currently owns closing that gap.

## 4. Where to pick this up

The precedent for exactly this kind of bridge already exists **twice** in this codebase — `book_context` (Story S5-1 / issue #231) and `chapter_context` (Story 249 / issue #249). See the companion handoff doc, `2026-09-28-handoff-book-chapter-context.md`, for the working pattern to copy: a `get_X_prompt_context()` fetch, a `merge_X_context()` truncation-safe merge sharing `_merge_context_block`, a `PipelineState` field, a `_FAN_OUT_STATE_KEYS` entry, and a dedicated test file.

Two things make this NOT a pure copy-paste of that pattern, though:
1. Only Q1–Q5 and the Penta badges have real, well-defined values today. The rest of the spec's routing table (Q6–Q15's humour/language/roast hooks) has no scoring/consumer logic behind it yet — building the bridge alone won't make those slides personalized; it needs its own small design pass first (see `2026-09-28-slide-strategy-15-30-45-alignment.md` §3/B9 and §6 Piece 5).
2. Unlike book/chapter context, onboarding data is fetched once per **user**, not once per lesson-generation run — worth deciding whether it's cached/refetched per run the same way, or handled differently (it doesn't change per chapter or per book, only per account).
