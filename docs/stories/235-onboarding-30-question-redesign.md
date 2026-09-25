---
title: "Story 235 — Onboarding Form: Replace 20-Question Form with 30-Question Redesign"
status: review
owners: [Dev 2]
sprint: platform-change
---

# Story 235 — Onboarding Form: Replace 20-Question Form with 30-Question Redesign

## Problem Statement

GitHub issue #235 (Dev 1, assigned to Dev 2 2026-09-22): *"Replace the current 20-question onboarding
form with the 30-question redesign from the product spec (Section 4.1) — new categories, new question
formats (MCQ + one-liner free-text + true/false), and several new personalization concepts not in the
current model."*

Source of truth for question content: `docs/proposals/source-specs/2026-09-hie-lecture-format-45min-and-onboarding-pack.pdf`,
Section 4.1 "User Onboarding Form (30 Questions)" — read in full for this story (30 questions: Q1-Q20
MCQ, Q21-Q25 one-liner free-text, Q26-Q30 true/false).

**Decisions locked by issue #235 (carried forward here):**
- **Replace, not additive** — the 30-question form fully replaces the 20-question one for new sign-ups.
  Not "20 old + 10 new."
- **No data migration needed** — the app has no real users yet, so there is no existing onboarding data
  to migrate or reconcile.
- **Build the form + storage for all 30 answers now.** Wire answers into personalization only where a
  consumer already exists today. Where the spec references a system that doesn't exist yet — Roast
  Ceiling enforcement, Bilingual Cognitive Bridge, Info-Warfare Shield, Comfortability Matrix (25
  personality modes), Life-Pathway engine, Penta-Intelligence baseline (IQ/EQ/SQ/CTQ/RRQ) scoring —
  **store the raw answers, do not build the consuming system.**

**What this story additionally had to resolve (not resolved by issue #235 itself):**

1. **The new spec's 30 questions do not map onto the existing 9-dimension Learner DNA model at all**
   (confirmed by reading `onboarding_questions.py`, `dna_fusion.py`, `service.py::process_onboarding`
   directly). Today, `process_onboarding()` synchronously computes 9 sub-dimension scores from the 20
   answers (`_compute_dimension_scores`), derives badge labels, generates `profile_text` via a
   GPT-4o-mini call, and upserts all of it into `learner_dna` — all in the onboarding request itself.
   The new spec's Q1-Q30 use a completely different taxonomy (Goal/Level/Language/Tone/Schooling/Inner
   Voice/Roast Ceiling/Focus/Vision/Penta-Intelligence letter-tags A-J) that issue #235 itself says
   "do not map cleanly" onto `pattern_recognition/logical_deduction/processing_speed/...`. Forcing a
   fake mapping would fabricate scores from answers never designed to produce them — exactly the kind
   of thing CLAUDE.md's "degrade-not-fabricate" principle exists to prevent.
2. **The existing `onboarding_responses` table cannot hold the new answer shapes.** It is part of
   `20260611000000_initial_schema.sql`, one of CLAUDE.md's two explicitly frozen migrations ("never
   modify applied migrations"). Its columns are `response_value integer NOT NULL` (no room for
   free-text) and `dimension_tag text CHECK (IN ('cognitive','emotional','self_direction'))` (no room
   for the new A-J taxonomy). A new table is required — not an oversight in issue #235, just left
   unspecified there.
3. **`OnboardingAnswer` / `OnboardingDiagnosticSubmission` are explicitly marked as a frozen contract**
   in `schemas.py` ("Frozen contract (Sprint 2, Story 3-18) — shape changes require 4-dev PR review").
   Changing them to carry 3 answer formats instead of 1 MCQ-only shape is exactly the kind of change
   that gate exists for.

## ⚠️ Plan needing all-4-dev sign-off before implementation begins

The first draft of this story proposed dropping Learner DNA computation from onboarding entirely,
reasoning that the new question taxonomy doesn't map onto the old 9 behavioral dimensions and that
`dna_fusion.py`'s session-driven EMA update already has a clean cold-start path. **That was wrong** —
raised in review: the entire point of onboarding is to give lesson generation an initial learner
profile *before* any session exists to derive one from. Dropping it would mean a brand-new student's
very first lesson generates with zero personalization, which defeats the purpose of running onboarding
before lesson generation in the first place.

Revised plan (Design §1 below): the 30 questions are **not** treated as one undifferentiated batch —
the source spec itself already splits them into 3 tiers by design intent, and this story follows that
split rather than inventing its own:

| Tier | Questions | Treatment |
|---|---|---|
| **Direct preferences** | Q1-5 only (Goal, Level, Language, Tone, Schooling — all marked "no wrong answer" in the PDF, and none of them depend on a system this codebase doesn't have yet) | Stored raw **and** actively wired into the tutor's existing personalization consumer (no scoring, no fabrication risk — it's literally what the user said) |
| **Penta-Intelligence baseline** | Q16-20 (CRT / EQ scenario / SQ dilemma / fact-vs-opinion / research method) — the PDF's own **"(scored)"** section with a real answer key | **Scored at onboarding time** using the spec's answer key → 5 new numeric columns on `learner_dna`, seeding the very first lesson's personalization exactly as onboarding is meant to |
| **Deferred** | Q6-15 (Bilingual Bridge / Info-Warfare Shield / Roast Ceiling / attention & scheduler signals / Life-Pathway vision — each explicitly named in issue #235's own "systems that don't exist yet" list) and Q21-30 (one-liner needs an NLP scorer that doesn't exist; true/false is explicitly "cross-validated against telemetry in the first 7 sessions" — can't be scored before any sessions exist) | Stored raw only — matches issue #235's own "store, don't build the consumer" instruction |

**Correction from this table's first draft:** Q9-15 (Roast Ceiling, Focus Span, Reels Diet, Daily Time,
Vision) were initially grouped into "direct preferences" alongside Q1-5. On closer reading, each of
them explicitly feeds a named system issue #235 itself lists as not yet built — Roast Ceiling
enforcement, the Scheduler agent, the Life-Pathway engine. Wiring them into a live prompt as if they
were plain facts would mean half-building those systems' consumption logic without their actual
design. Only Q1-5 are genuinely dependency-free facts (goal/level/language/tone/schooling need no
supporting system to be usable as-is) — they're the only ones actually wired in §6/AC6 below. Q6-15
now sit in Tier C with Q21-30: stored, not consumed, until their real system gets designed.

This keeps the existing 9 behavioral dimensions (`pattern_recognition`, `logical_deduction`, ...)
**completely untouched** — they stay session-EMA-driven exactly as today. The 5 new Penta-Intelligence
scores are additive columns alongside them, not a replacement. **This split, and specifically the
decision to add 5 new `learner_dna` columns via a new migration, needs explicit sign-off from all 4
developers before implementation** — flagging here so it's visible in the PR diff, not buried in prose
a reviewer has to dig for.

## Design

### 1. Three-tier treatment of the 30 answers (see table above)

**Tier A — Direct preferences (Q1-5 only), stored raw, read directly.** No scoring. The tutor's
prompt-injection path (§6 below) reads these literally — e.g. "preferred tone: witty" goes straight
into a prompt as a fact, never through a derived score. Zero fabrication risk because nothing is
inferred beyond what the user stated. Deliberately narrower than the first draft of this section (see
the correction note above the tier table) — Q6-15 are excluded because each feeds a named system
issue #235 itself defers.

**Tier B — Penta-Intelligence baseline (Q16-20), scored at onboarding time.** Uses the PDF's own
answer key (Section 4.1, Q16-Q20 "Penta-Intelligence Psychometrics (scored)"):

```python
# apps/api/app/modules/assessment/onboarding_questions.py
# Each question's per-option score (0-100), taken directly from the PDF's answer key —
# not invented here. "b"/"c"/etc. are option letters, 0-indexed to selected_index.
PENTA_SCORING: dict[str, dict[int, float]] = {
    "q16": {0: 0.0, 1: 100.0, 2: 25.0, 3: 25.0, 4: 25.0},   # CRT: b) correct=100, a) intuitive trap=0
    "q17": {0: 0.0, 1: 100.0, 2: 60.0, 3: 0.0, 4: 60.0},     # EQ scenario: b) highest
    "q18": {0: 0.0, 1: 50.0, 2: 100.0, 3: 85.0, 4: 50.0},    # SQ dilemma: c) highest, d) also high
    "q19": {0: 0.0, 1: 0.0, 2: 100.0, 3: 0.0, 4: 0.0},       # CTQ fact-vs-opinion: c) correct
    "q20": {0: 25.0, 1: 25.0, 2: 75.0, 3: 100.0, 4: 25.0},   # RRQ research method: d) highest, c) second
}
PENTA_DIMENSIONS: tuple[str, ...] = ("penta_iq", "penta_eq", "penta_sq", "penta_ctq", "penta_rrq")
PENTA_QUESTION_MAP: dict[str, str] = {  # question_id -> learner_dna column
    "q16": "penta_iq", "q17": "penta_eq", "q18": "penta_sq", "q19": "penta_ctq", "q20": "penta_rrq",
}
```

Each of the 5 scores is a single-question measurement (unlike the old 9 dimensions, which each blend
multiple questions) — that's a property of the source spec's own design (5 scored questions mapped
1:1 to 5 named constructs), not a simplification this story is introducing.

**Source verification (added per Dev 3 review):** the PDF gives an exact right/wrong answer for Q16
and Q19 (binary: correct=full credit, everything else=0), and a *qualitative* ranking only —
"highest," "second," "also high," "mid," "low" — for Q17, Q18, and Q20, with no exact numbers. The
table below traces every option to the PDF's own wording and states plainly which scores are PDF-exact
vs. this story's own quantization of a stated qualitative rank:

| Q | Option (PDF text, Section 4.1) | PDF says | Assigned score | Source |
|---|---|---|---|---|
| Q16 | a) ₹10 | "intuitive trap" (wrong) | 0.0 | PDF-exact |
| Q16 | b) ₹5 | "correct" | 100.0 | PDF-exact |
| Q16 | c) ₹15 / d) ₹1 / e) ₹2.50 | not addressed | 25.0 | Quantized (uniform partial-credit for an unaddressed wrong option) |
| Q17 | a) Snap back immediately | "low" | 0.0 | Quantized |
| Q17 | b) Assume bad day, check later | "highest" | 100.0 | Quantized (PDF states rank, not number) |
| Q17 | c) Ignore for days | "mid" | 60.0 | Quantized |
| Q17 | d) Confront aggressively | "low" | 0.0 | Quantized |
| Q17 | e) Feel hurt, say nothing | "mid" | 60.0 | Quantized |
| Q18 | a) Keep the cash | "low" | 0.0 | Quantized |
| Q18 | b) Return, hope for reward | "mid" | 50.0 | Quantized |
| Q18 | c) Return anonymously | "highest" | 100.0 | Quantized |
| Q18 | d) Hand to police/authority | "also high" | 85.0 | Quantized |
| Q18 | e) Post about it to look good | "mid" | 50.0 | Quantized |
| Q19 | c) 'Unemployment rose from 4.1% to 5.3%' | "correct" (verifiable fact) | 100.0 | PDF-exact |
| Q19 | a/b/d/e (opinion/appeal-to-consensus statements) | "opinion/appeal fallacies" | 0.0 | PDF-exact |
| Q20 | a) First Google / b) Wikipedia / e) Ask AI | "dependence layers to train out" | 25.0 | Quantized |
| Q20 | c) Compare 3+ sources | "second [highest]" | 75.0 | Quantized |
| Q20 | d) Primary sources/papers | "highest" | 100.0 | Quantized |

Quantization rule used throughout: PDF "highest"/correct → 100, "also high" → 85, "second" → 75,
"mid" → 60, unaddressed-wrong → 25 (kept below the existing `BADGE_THRESHOLD = 70` so it never earns
a badge), "low"/fallacy/incorrect → 0. This preserves the PDF's stated ORDER exactly (100 > 85 > 75 >
60 > 25 > 0 matches "highest > also high > second > mid > low/wrong" in every one of the 5 questions)
— the only thing this story adds is the specific numbers between those ranks, which the PDF itself
doesn't give.

**CLAUDE.md compliance:** these 5 scores are computed and stored, but per "No raw IQ/EQ/SQ claims —
branded as Learner DNA" and "No clinical scores shown to students," they are **never labeled
literally** in any student-facing surface. A new `PENTA_BADGE_THRESHOLDS` map (mirrors the existing
`BADGE_THRESHOLDS` pattern exactly) gives each dimension a descriptive badge name for scores ≥ 70:
`penta_iq` → "Sharp Reasoner", `penta_eq` → "Empathetic Responder", `penta_sq` → "Principled
Decision-Maker", `penta_ctq` → "Fact-Checker", `penta_rrq` → "Deep Researcher". Raw scores are never
returned in any API response (same allowlist-filtering discipline `_build_learner_prompt_text` already
applies to the old 9 dimensions' badges).

**Fix from review (Dev 4):** `_build_learner_prompt_text` filters `badge_labels` through
`_VALID_BADGE_LABELS = frozenset(BADGE_THRESHOLDS.values())` (`service.py:2159,2180`) — an intentional
prompt-injection allowlist — before anything reaches the tutor's LLM prompt. The first draft of this
story added `PENTA_BADGE_THRESHOLDS` without updating that allowlist, so a student's earned Penta
badges would render correctly on `DNAResultCard.tsx` (which reads `badge_labels` directly, unfiltered)
but be silently stripped to "none yet" in the one prompt-injection surface this story's AC6 change
actually feeds — a real silent-degradation gap the story's own test plan (AC10, `DNAResultCard.tsx`
only) wouldn't have caught. **Fix:** `_VALID_BADGE_LABELS` becomes
`frozenset(BADGE_THRESHOLDS.values()) | frozenset(PENTA_BADGE_THRESHOLDS.values())`. See AC6b.

**Tier C — Deferred (Q6-15 and Q21-30).** Stored raw in `onboarding_answers_v2` only. Q6-8 (Bilingual
Bridge / Info-Warfare Shield inputs) and Q9-15 (Roast Ceiling / attention & scheduler signals /
Life-Pathway vision) each name a system issue #235 explicitly lists as not yet built. Q21-25 (one-liner)
need an NLP scorer that doesn't exist; Q26-30 (true/false) are explicitly "cross-validated against
telemetry in the first 7 sessions" and can't be scored before any sessions exist. All of Tier C matches
issue #235's own "store the raw answers, do not build the consuming system" instruction.

`OnboardingResult`'s frozen shape (`badge_labels: list[str]`, `profile_text: str`,
`session_count: int`) is **unchanged** — but now genuinely populated from real onboarding-time
signal again: `badge_labels` = Penta badges (≥ 70 threshold, same convention as the existing system),
`profile_text` = LLM-generated via the **same existing** `generate_onboarding_profile` call, now given
Penta badges instead of (today's) behavioral badges that don't exist yet pre-session. The immediate
post-onboarding "Your Learner DNA" screen (`DNAResultCard.tsx`) requires **no code change** — it
already renders whatever badges/profile_text it's given.

### 2. New table for the 30 raw answers, not a reused/altered `onboarding_responses`

New migration creates `onboarding_answers_v2` (name chosen to make it unambiguous this is a distinct
table from the frozen `onboarding_responses`, not a versioned alias of it):

```sql
CREATE TABLE public.onboarding_answers_v2 (
  id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          uuid        NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  question_id      text        NOT NULL,
  format           text        NOT NULL CHECK (format IN ('mcq', 'one_liner', 'true_false')),
  selected_index   integer,                    -- set only when format = 'mcq'
  response_text    text,                       -- set for 'mcq' (option text) and 'one_liner'
  response_bool    boolean,                    -- set only when format = 'true_false'
  response_time_ms integer,
  created_at       timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT onboarding_answers_v2_user_question_unique UNIQUE (user_id, question_id)
);

ALTER TABLE public.onboarding_answers_v2 ENABLE ROW LEVEL SECURITY;

CREATE POLICY "onboarding_answers_v2: select own"
  ON public.onboarding_answers_v2 FOR SELECT
  USING (user_id = auth.uid());

CREATE POLICY "onboarding_answers_v2: insert own"
  ON public.onboarding_answers_v2 FOR INSERT
  WITH CHECK (user_id = auth.uid());

CREATE POLICY "onboarding_answers_v2: update own"
  ON public.onboarding_answers_v2 FOR UPDATE
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

CREATE POLICY "onboarding_answers_v2: delete own"
  ON public.onboarding_answers_v2 FOR DELETE
  USING (user_id = auth.uid());
```

This mirrors `onboarding_responses`' own row-per-question shape, its
`UNIQUE(user_id, question_id)` constraint (added by `20260703000000_onboarding_unique_constraint.sql`),
and — caught in review (Dev 4) — its RLS enablement + 4 "own row" policies
(`20260611000000_initial_schema.sql:333,726-741`), which the first draft of this migration omitted
entirely despite this table storing more sensitive content than before (free-text one-liner answers).
CLAUDE.md is unconditional here: "RLS on ALL Supabase tables — users read only their own data." Fixed.
`response_text` doubles for MCQ's selected option text (matching the old table's `selected_text`
convention passed through today) and one-liner's free text — never both on the same row, enforced by
a model validator in the schema, not a DB CHECK (keeps the migration simple; the API is the only
writer).

**Second migration, same PR:** `learner_dna` gains 5 new nullable columns for the Tier B
Penta-Intelligence baseline — added via a **new** migration file (the table's original `CREATE TABLE`
lives in the frozen `20260611000000_initial_schema.sql` and is not touched; this follows the exact
precedent `20260813000001_dna_session_count_atomic_increment.sql` already set for building on top of
this same frozen table):

```sql
ALTER TABLE public.learner_dna
  ADD COLUMN penta_iq  numeric(5,2) CHECK (penta_iq  >= 0 AND penta_iq  <= 100),
  ADD COLUMN penta_eq  numeric(5,2) CHECK (penta_eq  >= 0 AND penta_eq  <= 100),
  ADD COLUMN penta_sq  numeric(5,2) CHECK (penta_sq  >= 0 AND penta_sq  <= 100),
  ADD COLUMN penta_ctq numeric(5,2) CHECK (penta_ctq >= 0 AND penta_ctq <= 100),
  ADD COLUMN penta_rrq numeric(5,2) CHECK (penta_rrq >= 0 AND penta_rrq <= 100);
```

All 5 nullable (a pre-redesign user, if any existed, would have none of these — not applicable here
since there are no real users yet, but the columns are nullable on principle, matching every other
optional dimension column in this table).

### 3. Backend schema changes (`OnboardingAnswer` / `OnboardingDiagnosticSubmission`)

```python
class OnboardingAnswer(BaseModel):
    question_id: str
    format: Literal["mcq", "one_liner", "true_false"]
    selected_index: int | None = Field(default=None, ge=0)
    response_text: str | None = Field(default=None, max_length=1000)
    response_bool: bool | None = None
    response_time_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _validate_shape_matches_format(self) -> "OnboardingAnswer":
        if self.format == "mcq" and (self.selected_index is None or self.response_text is None):
            raise ValueError("mcq answers require selected_index and response_text")
        if self.format == "one_liner" and not (self.response_text or "").strip():
            raise ValueError("one_liner answers require non-blank response_text")
        if self.format == "true_false" and self.response_bool is None:
            raise ValueError("true_false answers require response_bool")
        return self


class OnboardingDiagnosticSubmission(BaseModel):
    responses: list[OnboardingAnswer] = Field(min_length=30, max_length=30)
```

`response_text` caps at 1000 chars (defensive, matching this codebase's established convention for
any free-text field that could later reach an LLM prompt, even though no LLM call reads it yet in this
story's scope — Q21-25 are explicitly "NLP-analysed for depth" as a *future* deferred capability).

**This is a frozen-contract change** (`schemas.py`'s own comment: "Frozen contract (Sprint 2, Story
3-18) — shape changes require 4-dev PR review") and is additionally within the Assessment API, one of
CLAUDE.md's 4 globally-frozen interface contracts ("Assessment API (OpenAPI auto-generated from
FastAPI)"). **This PR requires review from all 4 developers before merge**, not just Dev 3.

### 4. `onboarding_questions.py` — drop the 9-dimension map entirely

Replaces `QUESTION_SUBDIMENSION_MAP` / `ALL_NINE_DIMENSIONS` / `BADGE_THRESHOLD` /
`BADGE_THRESHOLDS` (all now dead for the onboarding path — `ALL_NINE_DIMENSIONS`/`BADGE_THRESHOLDS`
stay defined here since `dna_fusion.py`/`service.py` still import them for the *session-driven* path;
only the *onboarding-driven* scoring map is removed) with a minimal validation spec the backend
actually needs — the question bank's authoritative copy (text, options) lives in the frontend
(`questions.ts`), matching how the existing 20-question form already splits this (backend never had
question *text*, only IDs and a dimension tag):

```python
Q_SPEC: dict[str, Literal["mcq", "one_liner", "true_false"]] = {
    "q1": "mcq", "q2": "mcq", ..., "q20": "mcq",
    "q21": "one_liner", ..., "q25": "one_liner",
    "q26": "true_false", ..., "q30": "true_false",
}
MCQ_OPTION_COUNTS: dict[str, int] = {"q1": 5, "q2": 5, ..., "q6": 4, "q7": 4, ...}  # per PDF (some MCQs are 4-option, not 5 -- Q6-Q7 in the source PDF)
ALL_QUESTION_IDS: frozenset[str] = frozenset(Q_SPEC)
```

### 5. `process_onboarding()` rewrite

```
1. Validate: exactly 30 responses, question_ids == ALL_QUESTION_IDS exactly (no missing, no unknown,
   no duplicates), each answer's format matches Q_SPEC[question_id], each mcq selected_index <
   MCQ_OPTION_COUNTS[question_id]. Any violation -> 422 (a degrade-not-fabricate style validation
   guard, matching the pattern already used for LLM-response validation elsewhere in this codebase --
   here applied to client input instead).
2. Bulk-insert 30 rows into onboarding_answers_v2 (same duplicate -> 409 handling as today, matching
   UNIQUE(user_id, question_id)).
3. Compute the 5 Penta-Intelligence scores from Q16-20's selected_index via PENTA_SCORING (Design
   Tier B) -- pure lookup, no LLM call.
4. Compute Penta badge labels (score >= 70, via PENTA_BADGE_THRESHOLDS).
5. Generate profile_text via the SAME existing generate_onboarding_profile() GPT-4o-mini call,
   now given the Penta badges as input (this call's own signature/logic is unchanged -- only what
   badge_labels are computed from changes).
6. Upsert learner_dna: the 9 existing behavioral dimension columns are left untouched (NULL if no
   row exists yet -- dna_fusion.py's session-driven EMA seeds them on the first completed session,
   exactly as it does today), the 5 NEW penta_* columns get the Step-3 scores, badge_labels = Step-4
   Penta badges, profile_text = Step-5 text, session_count = existing value if a row already exists
   (D137 reassessment convention, unchanged) else 0.
7. Return OnboardingResult(badge_labels=<Penta badges>, profile_text=<LLM text>, session_count=...).
```

The existing LLM-call-failure rollback logic (delete the just-inserted rows, return 503) is **kept**,
now guarding the Step-5 call instead of the old dimension-scoring call it guarded before — same
failure mode, same recovery path, just a different (cheaper, deterministic) input feeding it. Router-
level idempotency (`user:{id}:onboarding_done` Redis SET NX) and the reassessment bypass are
**unchanged** — both are format-agnostic.

**Registered as D173** (`docs/DEFECT-REGISTER.md`), **later FIXED in this story's own implementation
(2026-09-22)**, following the `/bmad-code-review` of PR #239. Re-reading `process_onboarding()`'s
current (pre-fix) insert path confirmed it used a plain `.insert()`, not an upsert, for
`onboarding_responses`/`onboarding_answers_v2` — meaning a reassessment resubmission hit the
`UNIQUE(user_id, question_id)` constraint and was misreported as a 409 "duplicate submission,"
independent of this story's own scope (this table carried the identical shape/behavior forward
unchanged from `onboarding_responses`, not a regression this story introduced). The review also
surfaced a compounding gap: `OnboardingFlow.tsx`'s 409-handler treats any 409 as "already onboarded"
and silently shows the student's stale pre-reassessment profile, masking the backend 409 into a false
success with no indication anything failed.

Step 5 above now reads **upsert, not insert** — `.upsert(rows, on_conflict="user_id,question_id")` —
so a reassessment resubmission overwrites the prior 30 rows cleanly instead of colliding with them.
The dead "duplicate key" 409-mapping branch was removed; any remaining `onboarding_answers_v2` write
error is now a genuine 500, since duplicate *submission attempts* are already gated upstream by
`router.py`'s Redis `SET NX`, not by a DB-level conflict here. Guarded by
`test_reassessment_resubmission_succeeds_against_the_actual_unique_constraint`
(`tests/unit/test_reassessment_blend.py`), which enforces the real `UNIQUE(user_id, question_id)`
constraint itself via an in-memory fake table (rather than a self-agreeing mock) and drives
`process_onboarding` through a genuine first-time-then-reassessment sequence. See D173's updated
register entry for the full fix/guard writeup.

### 6. Wire all 5 Tier A fields into the tutor's existing learner-context prompt path

The **only** existing LLM-prompt consumer of Learner DNA in this codebase is `get_learner_context()` /
`_build_learner_prompt_text()` (Story F2-1, `assessment/service.py`), read by Dev 4's tutor state
machine for live Q&A. (Confirmed by repo-wide search: the content-generation pipeline, `graph.py`, has
**no** learner-context read of any kind today — issue #6 in the platform-changes-scope tracking doc,
"learning behaviour in system prompt," is genuinely unimplemented and out of scope for this story.)

Add 5 new optional fields to `LearnerContextDNA` — `stated_goal: str | None`, `current_level: str |
None`, `preferred_language: str | None`, `preferred_tone: str | None`, `schooling_level: str | None`
— populated from Q1 (`[A · Goal]`), Q2 (`[B · Level]`), Q3 (`[C · Language]`), Q4 (`[C · Tone]`), Q5
(`[D · Schooling]`) via a new `_read_onboarding_headline_answers(user_id)` helper reading
`onboarding_answers_v2` directly (not `learner_dna`, since these now live only in the raw-answers
table). `_build_learner_prompt_text` gains one new descriptive line when any of the 5 are present:

```
- Stated goal: {stated_goal} | Level: {current_level} | Schooling: {schooling_level} | Language preference: {preferred_language} | Tone preference: {preferred_tone}
```

This is also an Assessment-API (frozen contract #3) change — same 4-dev PR review requirement as
section 3, and can land in the **same** PR (same review, same reviewers).

### 7. Frontend

- `apps/web/src/components/onboarding/questions.ts` — full rewrite: 30 `Question` entries, each
  tagged `format: 'mcq' | 'one_liner' | 'true_false'`. MCQ entries keep `options: string[]` (verbatim
  from the PDF, including the 2 four-option questions Q6/Q7 — not all MCQs in this form are 5-option
  like the old form's were). One-liner entries carry a `placeholder` string instead of `options`.
  True/false entries carry no options (rendered as fixed True/False buttons).
- `QuestionCard.tsx` — branches on `question.format`: `mcq` keeps today's `useRovingRadioGroup`
  radio-button rendering unchanged; new `format === 'true_false'` branch reuses the **same**
  `useRovingRadioGroup` hook with `optionCount: 2` (True/False as two roving-focus buttons — no new
  a11y pattern invented, matches CLAUDE.md's spirit of reusing accepted patterns rather than
  duplicating); new `format === 'one_liner'` branch renders a `<textarea>` (max 1000 chars, matching
  the backend cap, live character counter, no `useRovingRadioGroup` involvement).
- `OnboardingFlow.tsx`:
  - `answers` state becomes `Record<string, OnboardingAnswerValue>` where
    `OnboardingAnswerValue = { format: 'mcq'; index: number } | { format: 'one_liner'; text: string }
    | { format: 'true_false'; value: boolean }` — not a bare `number` anymore.
  - `canProceed`: `mcq` unchanged (`index !== undefined`); `one_liner` requires
    `text.trim().length > 0` (blank/whitespace-only never counts as answered, consistent with the
    backend validator); `true_false` requires the value to be explicitly set (`value !== undefined`,
    since `false` is a valid, real answer and must not be confused with "unanswered").
  - `handleSubmit()` maps each question + its stored answer into the new 3-shape
    `OnboardingAnswer` wire format.
  - `STORAGE_KEY` bumped from `onboarding_progress_v1` to `onboarding_progress_v2` — a stale v1 blob
    from the old 20-question shape must never be resumed into the new 30-question flow (the index
    positions and answer shapes are incompatible). Old key is not read or migrated; a returning user
    mid-way through the old form on redeploy day simply restarts (acceptable: "no real users yet" per
    issue #235's own locked decision).

## Acceptance Criteria

- **AC1** — New migration `supabase/migrations/<ts>_onboarding_answers_v2.sql` creates
  `onboarding_answers_v2` exactly as specified in Design §2, with `UNIQUE(user_id, question_id)`.
  `onboarding_responses` and its own migrations are untouched (frozen).
- **AC1b** — New migration `supabase/migrations/<ts>_learner_dna_penta_intelligence.sql` adds the 5
  nullable `penta_*` columns to `learner_dna` per Design §2. The frozen `initial_schema.sql` is not
  touched; the existing 9 behavioral dimension columns are not altered.
- **AC1c** — The AC1 migration enables RLS on `onboarding_answers_v2` and adds the same 4 "own row"
  (select/insert/update/delete) policies `onboarding_responses` already has, per CLAUDE.md's
  unconditional "RLS on ALL Supabase tables" rule (caught in review — Dev 4).
- **AC2** — `onboarding_questions.py`: `QUESTION_SUBDIMENSION_MAP` and its onboarding-scoring usage
  removed; new `Q_SPEC`/`MCQ_OPTION_COUNTS`/`ALL_QUESTION_IDS` added, matching the PDF's 30 questions
  exactly (20 MCQ across Q1-Q20 with correct per-question option counts including the two 4-option
  questions Q6/Q7, 5 one-liner Q21-Q25, 5 true/false Q26-Q30). `ALL_NINE_DIMENSIONS`/
  `BADGE_THRESHOLDS` remain (still used by the session-driven path).
- **AC3** — `OnboardingAnswer`/`OnboardingDiagnosticSubmission` updated to the 3-format shape in
  Design §3, with the format-matching `model_validator`. **AC3 requires 4-developer PR review**
  (frozen Assessment-API contract) — this story's PR is not mergeable on Dev 3 approval alone.
- **AC4** — `process_onboarding()` rewritten per Design §5: validates all 30 question_ids
  present/known/non-duplicate and format-matched (422 on violation), bulk-inserts into
  `onboarding_answers_v2`, computes the 5 Penta-Intelligence scores from Q16-20 via `PENTA_SCORING`
  (no LLM call for this part — pure answer-key lookup), computes Penta badge labels (≥ 70),
  generates `profile_text` via the existing `generate_onboarding_profile` LLM call seeded with the
  Penta badges, and upserts `learner_dna` with the 5 new `penta_*` columns + `badge_labels` +
  `profile_text` — **the existing 9 behavioral dimension columns are never written by this path**
  (left `NULL` for a first-time user; `dna_fusion.py`'s session-driven EMA seeds them after the first
  completed session, exactly as today). Returns `OnboardingResult(badge_labels=<Penta badges>,
  profile_text=<LLM text>, session_count=<existing or 0>)`.
- **AC5** — `POST /onboarding/submit` router: idempotency (Redis SET NX) and reassessment-bypass logic
  unchanged; a fresh `test_onboarding_endpoint.py` test proves 30 valid answers succeed end-to-end and
  a 409 still fires on a second submission attempt.
- **AC6** — `LearnerContextDNA` gains `stated_goal`/`current_level`/`schooling_level`/
  `preferred_language`/`preferred_tone` (all `str | None`), populated from Q1-Q5 via a new read of
  `onboarding_answers_v2`; `_build_learner_prompt_text` includes them in its output line per Design
  §6 when present, and omits the line entirely when all 5 are `None` (e.g. user hasn't onboarded via
  the new form, or the row doesn't exist). **Also requires 4-developer PR review** (same frozen
  contract as AC3 — can be the same review round).
- **AC6b** — `_VALID_BADGE_LABELS` (`service.py:2159`) is updated to
  `frozenset(BADGE_THRESHOLDS.values()) | frozenset(PENTA_BADGE_THRESHOLDS.values())` (caught in
  review — Dev 4). A new test asserts `_build_learner_prompt_text` actually surfaces a Penta badge in
  its output string when `dna.badge_labels` contains one — not just that `process_onboarding` computes
  one (AC10 alone doesn't cover this path, since `DNAResultCard.tsx` reads `badge_labels` unfiltered
  and would have masked the gap).
- **AC7** — `questions.ts` rewritten: all 30 questions present with exact PDF text/options/format,
  verified 1:1 against the source PDF (not paraphrased) in the PR description.
- **AC8** — `QuestionCard.tsx` renders all 3 formats correctly: MCQ (unchanged visual/a11y), True/False
  (2-option roving group, reusing `useRovingRadioGroup`), One-Liner (textarea, 1000-char cap with a
  visible counter, non-blank required to enable Next/Complete).
- **AC9** — `OnboardingFlow.tsx`: `answers` state and `handleSubmit()` updated per Design §7;
  `STORAGE_KEY` bumped to `onboarding_progress_v2`; `canProceed` correctly distinguishes "unanswered"
  from "answered false" / "answered index 0" for every format.
- **AC10** — Explicit test proving `process_onboarding()` produces real, spec-derived Penta badges
  (e.g. a submission answering Q16-20 with all top-scoring options yields all 5 Penta badges;
  answering with all lowest-scoring options yields zero) and that `DNAResultCard.tsx` renders them
  correctly with no component change needed — i.e. this story does NOT regress the post-onboarding
  screen, and the badges shown are now genuinely earned from Tier B answers, not empty/fabricated.
- **AC11** — `dna_fusion.py`, `dna_profile.py`, and the session-driven 9-dimension EMA/badge/
  profile_text pipeline are **untouched** by this story — existing tests for those modules pass
  unmodified, and a new test proves the 9 behavioral columns stay `NULL` immediately after onboarding
  (only the 5 `penta_*` columns are populated), then get correctly seeded from neutral 50 by
  `dna_fusion.py` on the student's first completed session, exactly as today.
- **AC12** — Existing guard/behavior tests referencing onboarding are updated, not deleted, for the
  new 30-question/3-format shape and pass: `test_onboarding_endpoint.py`,
  `test_onboarding_question_ordering.py`, `test_onboarding_content.py`,
  `test_onboarding_llm_failure.py` (still relevant — the LLM call for `profile_text` is kept, now
  seeded by Penta badges instead of behavioral ones; the existing failure/rollback test just needs its
  fixture data updated to 30 Tier-B-shaped answers), `test_learner_dna_real_onboarding.py`,
  `test_reassessment_blend.py`,
  `test_reassessment_flag.py`, `test_f2_1_learner_context.py` (AC6's new fields),
  `test_t28_dna_display_contract_dev2.py`, `test_openapi_spec.py`, `test_assessment_stub_contracts.py`.
  Named explicitly per CLAUDE.md's rule that a story touching a guarded module must list that
  module's guard tests as an AC, not discover them during review.
- **AC13** — `tsc --noEmit` and targeted `eslint` clean on all touched frontend files; `ruff`/`mypy`
  (or this repo's equivalent gate) clean on all touched backend files; full frontend **and** backend
  test suites green, zero regressions outside the files this story intentionally changes.

## Scale & Load

1. **Unit of work & range.** One onboarding submission = exactly 30 answers from exactly one user,
   inserted once (enforced by `UNIQUE(user_id, question_id)` + the Redis idempotency lock). Fixed size
   regardless of input — there is no variable-length dimension to this unit of work (unlike, say, a
   chapter's section count). No range to characterize beyond "always exactly 30."
2. **Fixed budgets vs. variable input.** `response_text` (one-liner answers) is capped at 1000 chars
   by the Pydantic `Field(max_length=1000)` — a client sending more gets an explicit 422, never a
   silent truncation. There is no other variable-sized input in this flow.
3. **Scope of every limit.** The `UNIQUE(user_id, question_id)` constraint and the Redis
   `user:{id}:onboarding_done` lock are both per-user, matching the existing (unchanged) pattern. No
   new per-instance or per-deployment limit is introduced.
4. **Unbounded reads/writes.** The bulk-insert is always exactly 30 rows (bounded by
   `Field(min_length=30, max_length=30)` on the submission schema itself, enforced before any DB call).
   The new `_read_onboarding_headline_answers` read (AC6) is `.eq("user_id", ...).in_("question_id",
   ["q1","q2","q3","q4","q5"]).limit(5)` — bounded by construction, never more than 5 rows regardless
   of how many total answers a user has on file.
5. **Inherited caps re-derived.** None inherited — this is new storage, not a modification of an
   existing capacity assumption. The old `onboarding_responses` table's 20-row-per-user shape is not
   reused or extended; the new table's 30-row-per-user shape is sized directly from this story's own
   fixed input (Q1-Q30), not copied from an unrelated prior constant.
6. **Concurrency safety of check-then-act sequences.** The existing Redis `SET NX` on
   `user:{id}:onboarding_done` (unchanged by this story) already closes the TOCTOU window between
   "check if already onboarded" and "write the result" for the common case. The bulk-insert's
   `UNIQUE(user_id, question_id)` constraint is the DB-layer backstop for the same race (matches the
   existing table's own belt-and-suspenders design, carried forward unchanged). The one **known,
   pre-existing, not-introduced-by-this-story** gap: a reassessment resubmission uses plain `.insert()`
   rather than upsert, so two answers for the same `question_id` cannot coexist for one user without
   hitting the unique constraint — see the Dev Note under Design §5. Not a new concurrency risk from
   this story; carried forward identically from the current 20-question implementation.

## Dev Notes

- `onboarding_questions.py:1-65` — read in full; `QUESTION_SUBDIMENSION_MAP`/`ALL_NINE_DIMENSIONS`/
  `BADGE_THRESHOLD`/`BADGE_THRESHOLDS` all confirmed still imported by `dna_fusion.py`/`service.py`'s
  session-driven path — do not delete the dimension/badge constants themselves, only their
  onboarding-time *usage*.
- `service.py:1622-1838` (`_compute_badge_labels`, `_fetch_existing_dna`, `process_onboarding`) — read
  in full; the LLM-failure rollback logic (lines ~1741-1784) is deleted in its entirety along with the
  LLM call it exists to guard, not left dead in place.
- `service.py:2152-2320` (`_build_learner_prompt_text`, `get_learner_context`) — the **only** existing
  LLM-prompt consumer of Learner DNA data in the repo; confirmed via repo-wide search that
  `apps/api/app/modules/content/pipeline/graph.py` has zero learner-context reads today (issue #6 from
  the wider platform-changes tracking doc is genuinely unimplemented, not something this story
  touches).
- `DNAResultCard.tsx` — read in full; already renders correctly with empty `badge_labels` (conditional
  block) and any non-empty `profile_text` string. No component change required for AC10, only a test.
- `useRovingRadioGroup.ts` — read in full; generic over `optionCount`, reused as-is for the new
  True/False rendering (`optionCount: 2`) rather than writing a second roving-focus implementation.
- Question text/options/formats for all 30 questions sourced verbatim from
  `docs/proposals/source-specs/2026-09-hie-lecture-format-45min-and-onboarding-pack.pdf`, Section 4.1
  (pages 3-6 of the PDF) — read directly, not summarized from a secondary source.

## File List

- `supabase/migrations/20260922010000_onboarding_answers_v2.sql` (new)
- `supabase/migrations/20260922020000_learner_dna_penta_intelligence.sql` (new)
- `apps/api/app/modules/assessment/onboarding_questions.py`
- `apps/api/app/modules/assessment/schemas.py`
- `apps/api/app/modules/assessment/service.py`
- `apps/api/app/modules/assessment/router.py` (verified only — no logic change needed)
- `apps/api/tests/test_onboarding_endpoint.py`
- `apps/api/tests/unit/test_onboarding_question_ordering.py`
- `apps/api/tests/test_onboarding_content.py`
- `apps/api/tests/test_onboarding_llm_failure.py`
- `apps/api/tests/test_learner_dna_real_onboarding.py`
- `apps/api/tests/unit/test_reassessment_blend.py`
- `apps/api/tests/test_reassessment_flag.py`
- `apps/api/tests/unit/test_f2_1_learner_context.py`
- `apps/api/tests/test_t28_dna_display_contract_dev2.py`
- `apps/api/tests/test_openapi_spec.py` (verified only — no changes needed)
- `apps/api/tests/test_assessment_stub_contracts.py`
- `apps/api/tests/test_posthog_events.py` (found during final sweep — module-level `OnboardingAnswer`
  construction would have failed to import with the old fields)
- `apps/api/tests/integration/test_migration_chapters_book_scoped.py` (live-Postgres RLS
  expected-tables guard — added `onboarding_answers_v2`)
- `apps/web/src/components/onboarding/questions.ts`
- `apps/web/src/components/onboarding/QuestionCard.tsx`
- `apps/web/src/components/onboarding/OnboardingFlow.tsx`
- `apps/web/src/types/assessment.ts` (`OnboardingAnswer` interface, frontend mirror of the backend
  frozen-contract change)
- `apps/web/src/__tests__/components/onboarding/OnboardingFlow.test.tsx`
- `apps/web/src/__tests__/components/onboarding/QuestionCard.test.tsx` (per-format rendering)
- `apps/web/src/__tests__/services/onboarding.service.test.ts` (fixture shape)
- `apps/web/src/__tests__/types/assessment.test.ts` (fixture shape)
- `apps/web/src/components/onboarding/DNAResultCard.tsx` (verified only, AC10 — no code change needed)

## Dev Agent Record

### Completion Notes

Implemented against the plan approved in PR #239 (all-4-dev sign-off obtained on the frozen-contract
changes and the `learner_dna` Penta-Intelligence columns).

- **Backend**: `onboarding_questions.py` rewritten (`Q_SPEC`/`MCQ_OPTION_COUNTS`/`ALL_QUESTION_IDS`/
  `PENTA_SCORING`/`PENTA_DIMENSIONS`/`PENTA_QUESTION_MAP`/`PENTA_BADGE_THRESHOLD`/
  `PENTA_BADGE_THRESHOLDS`), `QUESTION_SUBDIMENSION_MAP` removed. `ALL_NINE_DIMENSIONS`/
  `BADGE_THRESHOLDS` kept (still used by `dna_fusion.py`'s session-driven path, confirmed untouched).
- **Schemas**: `OnboardingAnswer`/`OnboardingDiagnosticSubmission` rewritten to the 3-format shape
  with a `model_validator` enforcing format-appropriate fields; `LearnerContextDNA` gained the 5
  Tier A fields (`stated_goal`/`current_level`/`schooling_level`/`preferred_language`/
  `preferred_tone`), all additive with `None` defaults.
- **Migrations**: `20260922010000_onboarding_answers_v2.sql` (new table, RLS + 4 own-row policies)
  and `20260922020000_learner_dna_penta_intelligence.sql` (5 nullable `penta_*` columns). Frozen
  `initial_schema.sql` untouched.
- **`process_onboarding()` rewrite**: new `_validate_onboarding_responses` guard (422 on any
  question_id/format/index mismatch, runs before any DB call — verified via a dedicated test that
  `supabase.table` is never called on an invalid submission), `_compute_penta_scores`/
  `_compute_penta_badge_labels` replace the old dimension-scoring pair, bulk-insert now targets
  `onboarding_answers_v2`. The 9 behavioral dimension columns are never written by this path —
  verified by a dedicated test asserting they're absent from the upsert payload.
- **Tier A wiring**: new `_read_onboarding_headline_answers` helper reads Q1-Q5 from
  `onboarding_answers_v2`, wired into `get_learner_context`; `_build_learner_prompt_text` gained a
  "Stated Preferences" line, omitted entirely when all 5 fields are `None`.
- **`_VALID_BADGE_LABELS` fix**: now unions `BADGE_THRESHOLDS.values()` and
  `PENTA_BADGE_THRESHOLDS.values()` — a real gap Dev 4 caught in review (Penta badges would have
  rendered on `DNAResultCard.tsx` but been silently stripped from the tutor prompt).
- **Frontend**: `questions.ts` rewritten with all 30 questions sourced verbatim from the PDF
  (multi-line object format for readability — the Penta option-order guard test's parser was
  rewritten to be format-agnostic rather than forcing single-line question objects).
  `QuestionCard.tsx` now branches on `question.format`: MCQ unchanged, True/False reuses
  `useRovingRadioGroup` with `optionCount: 2` (no second a11y implementation), One-Liner is a
  1000-char-capped textarea with a live counter. `OnboardingFlow.tsx`'s `answers` state became a
  discriminated union (`AnswerValue`), `STORAGE_KEY` bumped to `_v2`, `canProceed` correctly
  distinguishes unanswered from answered-false/answered-index-0 for every format.
- **Test updates**: 15 existing backend test files updated for the new shape (not deleted); 2 real
  pre-existing test-mock bugs found and fixed along the way (a `_fetch_existing_dna` mock-sequencing
  gap in `test_onboarding_llm_failure.py`, and a missing `onboarding_answers_v2` table branch in
  `test_f2_1_learner_context.py`'s mock that would have crashed every DNA-present test) — both were
  test-only artifacts, not production bugs. `test_migration_chapters_book_scoped.py`'s live-Postgres
  RLS-table-set guard updated to include the new table.
- **Verification**: `ruff`/`mypy` clean on all touched backend files; `tsc --noEmit`/`eslint` clean on
  all touched frontend files. Full backend suite run (not just touched files, per CLAUDE.md binding
  rule 1): 2708 passed, 75 failed — all 75 pre-existing and unrelated (missing optional deps
  `tinytag`/`fpdf`/`jsonschema`, network-dependent LLM smoke tests, tutor-state-machine timing
  flakiness, and a rate-limiter test-isolation issue in another PR's `chapter_context` tests); zero
  onboarding/assessment/Learner DNA files appear in the failure list. Full frontend suite: 95 files /
  1279 tests, zero regressions (baseline was 95/1254; net +25 new tests).
- **PR #239 Senior Developer Review response** (Dev 3, 2026-09-23): three follow-up items addressed:
  - `response_time_ms` gained an upper bound (`le=3_600_000`, 1 hour) — it previously had no ceiling,
    which would have let a corrupted/malicious client value pollute future per-question timing
    analytics with no error anywhere.
  - **Clean-slate assumption, stated explicitly**: this migration does not backfill
    `onboarding_answers_v2` from the old `onboarding_responses` table. Any user who completed the
    previous 20-question form has no rows in the new table, and the tutor's learner-context path
    (`_read_onboarding_headline_answers`) will treat them as not-yet-onboarded until they complete the
    new 30-question form. Acceptable pre-launch (zero real students have completed even one session
    as of this writing, per D173's own register entry) — revisit if any internal/preview user
    completes the old form before this PR merges.
  - **Rollback-on-failure logic removed** from both the Step 6 (LLM failure) and Step 7 (`learner_dna`
    upsert failure) exception handlers. That rollback (delete the just-written `onboarding_answers_v2`
    rows so a retry could re-insert) was only ever needed because Step 5 used to be a plain `.insert()`
    — a retry would otherwise hit the `UNIQUE(user_id, question_id)` constraint. Step 5 is now
    `.upsert()` (D173), which is idempotent: a retry re-upserts the same 30 rows cleanly with no
    rollback required. Worse, the stale rollback was actively harmful on a reassessment specifically —
    Step 5's upsert had already overwritten the student's *prior* answers by the time a Step 6/7
    failure fired, so the rollback-delete left `onboarding_answers_v2` empty instead of merely
    reverting to the pre-resubmission state. `test_onboarding_llm_failure_does_not_delete_rows`
    (replacing the old `test_onboarding_llm_failure_deletes_orphaned_rows`) now guards the corrected
    behavior.

### Deviations from the design's illustrative pseudo-code (reasoned, not oversights)

- Design §6's example `_build_learner_prompt_text` line format showed all 5 fields always present;
  the actual implementation only includes populated fields (joined with `|`), omitting missing ones
  inline rather than rendering e.g. "Schooling: None" — cleaner output, still satisfies AC6's "omit
  the line entirely when all 5 are `None`" requirement.

## References

- GitHub issue #235: "Onboarding form: replace 20-question form with 30-question redesign"
  (`developer-cybersmith/transformED`)
- `docs/proposals/source-specs/2026-09-hie-lecture-format-45min-and-onboarding-pack.pdf`, Section 4.1
- `docs/proposals/2026-09-19-platform-changes-scope.md` — "Change 1 — Multi-stage personalization
  forms" (Draft Story context, per-user form is this story; book/chapter forms are issues #231/#230,
  owned by other devs)
- [Source: apps/api/app/modules/assessment/service.py:1662-1838] `process_onboarding` (pre-story)
- [Source: apps/api/app/modules/assessment/dna_fusion.py:66-73] `_apply_ema`'s `old is None -> neutral
  50` cold-start path, the reason no onboarding-time seed is required
- [Source: apps/api/app/modules/assessment/schemas.py:187-201] frozen-contract comment on
  `OnboardingAnswer`/`OnboardingDiagnosticSubmission`
- [Source: supabase/migrations/20260611000000_initial_schema.sql:224-256] frozen `learner_dna`/
  `onboarding_responses` table definitions
