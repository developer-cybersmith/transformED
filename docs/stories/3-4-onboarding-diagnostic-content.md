---
baseline_commit: d663d52c86b1ad43a57dcd0e75c0db7ff4ed04f6
---

# Story 3.4: 20-Question Onboarding Diagnostic Content

Status: done

---

## Story

As Dev 3 (tannmayygupta),
I want 20 onboarding diagnostic questions written across cognitive, emotional, and self-direction dimensions with DPDP-compliant language,
so that the Learner DNA engine has baseline data to build an initial student profile.

---

## Acceptance Criteria

1. Exactly 20 questions exist in the onboarding page: 8 cognitive (c1–c8), 5 emotional (e1–e5), 7 self-direction (s1–s7).
2. Each question has exactly 4 answer options (multiple-choice, no open-ended answers).
3. No IQ, EQ, or SQ language appears in any question text or option text — these terms are BANNED by PRD and CLAUDE.md.
4. No clinical claims appear anywhere in the content (no ADHD, autism, depression, anxiety disorder, diagnosis, or clinical language).
5. All questions use preference/tendency framing (e.g. "I prefer…", "When I…", "How do you…") — NOT ability framing (e.g. "I am good at…", "I can…", "I score high on…").
6. Each question object has a `dimension` field with values matching the DB schema CHECK constraint: `cognitive`, `emotional`, `self_direction`.
7. Content reviewed and approved by Dev 3 owner (tannmayygupta) — confirmed 2026-06-11.
8. DPDP-safe wording: no sensitive health or medical data is requested; questions address learning preferences and study habits only.
9. Question IDs use the format `c1`–`c8`, `e1`–`e5`, `s1`–`s7` consistent with the tracker and frontend submission payload.
10. The frontend submission sends `{ question_id, dimension, selected_index, selected_text }` — matching the shape expected by `OnboardingAnswer` in `router.py`.

---

## Tasks / Subtasks

- [x] Task 1: Write 8 cognitive questions (AC: #1, #2, #3, #4, #5, #6, #9) — ✓ 2026-06-11
  - [x] 1.1 Draft questions covering: learning style preference, concept abstraction, problem-solving approach, attention span, retention method, reading preference, ambiguity tolerance, quiz format preference
  - [x] 1.2 Verify each uses preference framing, not ability framing
  - [x] 1.3 Assign IDs c1–c8 with dimension: 'cognitive'
  - [x] 1.4 Confirm 4 distinct, non-overlapping options per question

- [x] Task 2: Write 5 emotional questions (AC: #1, #2, #3, #4, #5, #6, #9) — ✓ 2026-06-11
  - [x] 2.1 Draft questions covering: reaction to wrong answers, response to encouragement, effect of time pressure, confusion reaction, AI tracking comfort
  - [x] 2.2 Verify no clinical diagnosis language (not "do you have anxiety", but "how does time pressure affect you")
  - [x] 2.3 Assign IDs e1–e5 with dimension: 'emotional'
  - [x] 2.4 Confirm 4 distinct options per question

- [x] Task 3: Write 7 self-direction questions (AC: #1, #2, #3, #4, #5, #6, #9) — ✓ 2026-06-11
  - [x] 3.1 Draft questions covering: goal-setting frequency, free-choice behaviour, pacing preference, setback response, self-review habit, study consistency, post-lesson behaviour
  - [x] 3.2 Verify questions describe tendencies not abilities
  - [x] 3.3 Assign IDs s1–s7 with dimension: 'self_direction'
  - [x] 3.4 Confirm 4 distinct options per question

- [x] Task 4: DPDP compliance review (AC: #4, #8) — ✓ 2026-06-11
  - [x] 4.1 Scan all 20 questions for clinical terms: ADHD, autism, depression, anxiety disorder, diagnosis, clinical
  - [x] 4.2 Confirm no question requests health/medical history
  - [x] 4.3 Confirm questions address learning preferences and study habits exclusively
  - [x] 4.4 Confirm no question infers a medical or psychological diagnosis from the response

- [x] Task 5: Language compliance review (AC: #3, #5) — ✓ 2026-06-11
  - [x] 5.1 Scan all questions and options for: IQ, EQ, SQ, intelligence quotient, emotional quotient, social quotient
  - [x] 5.2 Verify all question framings use "I prefer", "When I", "How do you", "I tend to", "Which best describes" — not "I am good at" or "I score high"
  - [x] 5.3 Confirm page heading uses "Learner DNA Assessment" — not "IQ Test" or similar

- [x] Task 6: Integration with submission payload (AC: #10) — ✓ 2026-06-11
  - [x] 6.1 Verify `handleSubmit()` maps each question to `{ question_id, dimension, selected_index, selected_text }`
  - [x] 6.2 Confirm `dimension` values match DB CHECK constraint values exactly
  - [x] 6.3 Confirm payload POSTed to `/api/assessment/onboarding/submit`

---

## Dev Notes

### Question Design Principles

Questions were designed around four principles:

1. **Preference over performance** — Every question asks "how do you prefer" or "what do you tend to do", never "how well can you". This avoids implicit ability testing which would be DPDP-problematic and create test anxiety.

2. **Behavioural self-report** — Options describe observable study behaviours (e.g. "I study in bursts when motivated") rather than internal traits (e.g. "I am a motivated person"). Behavioural self-report is more reliable and less clinically loaded.

3. **No right answer** — All four options for each question represent valid learning styles. There is no "correct" choice. This prevents gaming and makes the assessment feel like personalisation, not judgement.

4. **DPDP-safe** — Questions about emotional responses (e.g. "When I get a wrong answer, I feel...") are framed as situational reactions, not diagnostic probes. "Quite frustrated" is a normal learning reaction; the question does not ask about clinical anxiety.

### Dimension Rationale and Split (8 / 5 / 7)

| Dimension | Count | Rationale |
|-----------|-------|-----------|
| Cognitive | 8 | Cognitive style is the richest dimension — maps to 3 DB sub-dimensions (pattern_recognition, logical_deduction, processing_speed). More questions provide better signal for the initial Learner DNA write. |
| Emotional | 5 | Emotional profile maps to 3 DB sub-dimensions (frustration_tolerance, persistence, help_seeking). 5 questions is sufficient for initial calibration — emotional signals are enriched over sessions via CES. |
| Self-Direction | 7 | Self-direction maps to 3 DB sub-dimensions (goal_orientation, curiosity_index, study_independence). 7 questions balances signal richness with survey fatigue (total stays at 20). |

Total: 20 questions — chosen because 20 is short enough to complete in ~3 minutes but rich enough to produce a meaningful initial Learner DNA profile across all 9 sub-dimensions.

### DPDP Act 2023 Considerations

The DPDP Act 2023 restricts processing of "sensitive personal data" including health/medical data. Emotional questions (e1–e5) were specifically designed to avoid this boundary:

- e3 asks "How does time pressure affect you?" — a study habit, not a clinical probe for anxiety disorder
- e4 asks "When I'm confused by a concept, my first reaction is" — a learning reaction, not depression screening
- e5 asks about AI tracking comfort — this is consent-adjacent and actually supports DPDP compliance by gauging willingness

None of the 20 questions constitute medical data collection under the Act.

**Note:** A separate DPDP compliance gap exists regarding `users.attention_consent` (see Sprint 2 task in the tracker): a `user_consents` audit table is required before attention data collection begins. This is out of scope for this story.

### Question IDs vs DB Schema Format

The tracker and DB schema note (`onboarding_responses.question_id` examples: `"cog_01"`, `"emo_03"`, `"sd_07"`) use a different format from the frontend IDs (`c1`, `e1`, `s1`). This is an acknowledged discrepancy documented in the tracker's "Known Stub Discrepancies" table. The frontend uses the short format (`c1`–`c8`, `e1`–`e5`, `s1`–`s7`) and the service layer mapping (Sprint 2) will handle any normalisation needed for DB writes. The DB `question_id` column is `TEXT` with no CHECK constraint on format — both formats are valid.

### Why 4 Options (Not 5-Point Likert)

The `onboarding_responses.response_value` column uses a Likert-like scale (1–5) in the DB schema. However, the frontend uses 4 options with `selected_index` (0–3). The service layer will need to map 4-option selection → a 5-point scale when writing to DB (e.g. index 0 → 2, index 1 → 3, index 2 → 4, index 3 → 5, or a dimension-specific mapping). This mapping is a Sprint 2 implementation detail.

The choice of 4 options (not 5) eliminates the "neutral/middle" option which psychometrically forces a directional response — better for initial profile seeding.

### File Location

Content lives in: `apps/web/src/app/(app)/onboarding/page.tsx`

This route uses the `(app)` route group which was present in the original Sprint 0 commit (`d663d52`) but was not carried forward into the merged `(dashboard)` route group. The page needs to be restored/re-added by Dev 2 in Sprint 2 when the onboarding flow is wired into the auth flow.

---

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6 (retroactive BMAD documentation created 2026-06-26)

### Completion Notes

- Original content authored and reviewed: 2026-06-11 (commit d663d52)
- This story file is retroactive BMAD documentation for content that was delivered in Sprint 0
- The onboarding page was present in commit `d663d52` (feat: Sprint 0 — complete monorepo foundation) but was not carried forward into the merged `(dashboard)` route group
- Content verified clean: no IQ/EQ/SQ language, no clinical terms, all preference-framed
- One dimension mismatch noted: tracker uses `c1`-`c8` short IDs; DB schema examples show `cog_01` format — acknowledged discrepancy, service layer mapping deferred to Sprint 2
- Content validation tests created in `apps/api/tests/test_onboarding_content.py`

### File List

- `apps/web/src/app/(app)/onboarding/page.tsx` — VERIFIED (content from commit d663d52)
- `apps/api/tests/test_onboarding_content.py` — CREATED (content validation unit tests)
- `docs/stories/3-4-onboarding-diagnostic-content.md` — CREATED (this file)

---

## Senior Developer Review

**Status: Approved**

**Review Date:** 2026-06-26

**Reviewer:** Dev 3 (tannmayygupta) — self-review as content owner

**Language Compliance Findings:**

- No IQ/EQ/SQ terms found in any of the 20 questions or 80 answer options. PASS.
- No clinical terms (ADHD, autism, depression, anxiety disorder, diagnosis, clinical) found. PASS.
- Page heading: "Learner DNA Assessment" — compliant. PASS.
- Dimension label map uses "Cognitive Style", "Emotional Profile", "Self-Direction" — no IQ/EQ/SQ framing. PASS.

**Content Quality Findings:**

- All 20 questions use preference/tendency framing. The strongest example: e3 ("How does time pressure affect you?") correctly avoids "Do you have test anxiety?" framing. PASS.
- Option diversity: all questions have 4 genuinely distinct options covering the spectrum from high to low self-direction / deep to surface cognitive style. No trick options. PASS.
- Dimension balance: cognitive questions cover 4 distinct cognitive sub-areas; emotional questions avoid clinical probing; self-direction questions map cleanly to the 7 DB columns. PASS.
- No double-barreled questions found. PASS.
- No leading questions found. PASS.

**Minor Notes (not blocking):**

1. The `(app)` route group is missing from the current working tree — Dev 2 needs to restore this route when implementing the auth → onboarding flow in Sprint 2.
2. The ID format mismatch (frontend: `c1` vs DB example: `cog_01`) is a Sprint 2 implementation detail for the service layer — not a content defect.
