# Sprint 4 — Onboarding Question Quality Audit

**Story:** 4-5
**Date:** 2026-08-29
**Auditor:** Dev 3
**Verdict scope:** All 20 questions across 3 dimensions (8 cognitive, 5 emotional, 7 self-direction)

---

## Executive Summary

**7 of 20 questions are flagged.** 2 are critical (remove or replace immediately). 5 require rewording.

The dominant failure mode is not clinical language or cultural bias — it is **mapping mismatch + social desirability bias**. Most questions don't measure what `QUESTION_SUBDIMENSION_MAP` claims, and most have an obvious "good student" answer that destroys discrimination power. A student who wants to look capable will score identically to a student who actually is.

| Severity | Count | Questions |
|----------|-------|-----------|
| CRITICAL — Remove or replace | 2 | e3, e5 |
| HIGH — Remap or reword | 3 | c4, e2, s4 |
| MEDIUM — Reword for bias | 2 | s2, s6 |
| PASS | 13 | c1–c3, c5–c8, e1, e4, s1, s3, s5, s7 |

---

## Findings: Cognitive (c1–c8)

### c1 — "When learning something new, I prefer to:" → `pattern_recognition` ✅ PASS

Options: big-picture first / examples then generalise / step-by-step / discover patterns on my own

**Mapping:** Acceptable. Option 4 ("discover patterns") is the clearest pattern_recognition signal; options 1–3 represent contrasting styles that score lower appropriately.
**Social desirability:** Low — no option is clearly "smarter". Students answer genuinely.
**Ambiguity:** None.
**Verdict:** PASS.

---

### c2 — "I understand abstract concepts best when:" → `logical_deduction` ✅ PASS (with note)

Options: diagrams/visuals / real-world analogies / numbered steps / linked to prior knowledge

**Mapping note:** "Linked to prior knowledge" (option 4) maps better to `pattern_recognition` than `logical_deduction`. Options 2–3 are also not clearly deductive. The mapping is loose but tolerable — the question captures structured vs holistic preference which correlates with deductive reasoning style.
**Social desirability:** Low.
**Verdict:** PASS. Note mapping weakness in `QUESTION_SUBDIMENSION_MAP` comment.

---

### c3 — "When I encounter a difficult problem, I typically:" → `logical_deduction` ✅ PASS

Options: break into sub-problems / look for similar problem / think holistically first / try approaches until one works

**Mapping:** Strong. Breaking into sub-problems is deductive. "Look for similar problem" (pattern matching) is the highest-scoring logical_deduction-adjacent behaviour but is closer to `pattern_recognition` — this is acceptable as the discriminator between deductive and intuitive problem-solvers.
**Social desirability:** Low — all four options are defensible study behaviours.
**Verdict:** PASS.

---

### c4 — "My attention span during focused study is roughly:" → `processing_speed` 🔴 HIGH

Options: < 15 min / 15–30 min / 30–45 min / > 45 min

**Mapping FAIL:** Attention span is sustained attention, not processing speed. These are orthogonal constructs. A student who processes very quickly may have a 15-minute span; a slow processor may study for 2 hours. The DB column `processing_speed` should reflect how fast a student converts input to understanding — not how long they sit at a desk.

**Social desirability:** Severe. "Less than 15 minutes" is socially undesirable for students who want to appear capable. Expected 80%+ responses in the top two options ("30–45 min" and "> 45 min") regardless of actual span, making this question non-discriminating.

**Replacement:**
```
ID: c4 | dimension: cognitive | maps to: processing_speed

Text: "When studying new material, how quickly do you typically grasp the core idea?"

Options:
  A. Immediately — I connect it to what I know within the first pass
  B. After one full reading or explanation
  C. After a second pass or worked example
  D. Only after practising with it multiple times
```

This directly measures processing speed (time-to-comprehension), removes social desirability (all options are valid), and correctly maps to `processing_speed`.

---

### c5 — "How do you best retain new information?" → `pattern_recognition` ✅ PASS (with note)

Options: repetition and practice / teaching it to someone else / making notes in my own words / connecting to a story or narrative

**Mapping note:** "Connecting to a story or narrative" (pattern) and "teaching it" (active recall) both have weak ties to pattern_recognition. Retention method is a learning style signal, not purely a pattern-recognition signal. However, the distinction between rote repetition and pattern/connection-based encoding is meaningful enough to retain.

**Social desirability:** Moderate. "Teaching it to someone else" (Feynman technique) is the most well-known retention method — students familiar with learning science will pick it regardless of actual behaviour.

**Mitigation:** Reorder options to remove primacy/recency bias. No replacement needed but reorder:
1. Making notes in my own words
2. Connecting it to a story or narrative
3. Repetition and practice
4. Teaching it to someone else

**Verdict:** PASS with reorder.

---

### c6 — "When reading technical text, I prefer:" → `processing_speed` ✅ PASS (with note)

Options: dense detailed explanations / concise summaries / examples alongside theory / narrative with minimal jargon

**Mapping note:** Reading preference correlates weakly with processing speed (students who process quickly often prefer dense text; slow processors prefer concise summaries). The correlation exists but the question measures preference not ability. Acceptable as a behavioural proxy.
**Social desirability:** Low — all options are valid reading preferences.
**Verdict:** PASS.

---

### c7 — "How comfortable are you with ambiguity while learning?" → `logical_deduction` ✅ PASS (with note)

Options: Very comfortable / Somewhat comfortable / I prefer clear answers but can tolerate / Strongly prefer definite answers

**Mapping note:** Ambiguity tolerance ≠ logical deduction. However, tolerance for ambiguity correlates with exploratory problem-solving which is adjacent to deductive reasoning in practice. Acceptable proxy.

**Social desirability:** Moderate. "Very comfortable — I enjoy open-ended exploration" reads as the academically sophisticated answer. Some skew expected.

**Mitigation:** Reframe option 1 to be neutral: "I work well with open-ended problems" (remove "enjoy" which sounds aspirational).

**Verdict:** PASS with minor reword.

---

### c8 — "Which type of quiz question do you find most useful for learning?" → `pattern_recognition` ✅ PASS (with note)

Options: MCQ recall / short written explanation / problem-solving / real-world application

**Mapping note:** Quiz format preference has weak ties to pattern_recognition. "Real-world application scenario" is the most pattern-recognition-adjacent. However, this question effectively discriminates between rote learners (MCQ) and applied learners (application), which is useful signal even if the mapping label is imprecise.
**Social desirability:** Moderate. "Real-world application scenario" sounds like the sophisticated choice.
**Verdict:** PASS with mapping note.

---

## Findings: Emotional (e1–e5)

### e1 — "When I get a wrong answer on a quiz, I feel:" → `frustration_tolerance` 🟡 PASS (bias note)

Options: Motivated to understand why / Briefly discouraged then move on / Quite frustrated / Indifferent

**Mapping:** Good. Emotional response to failure maps well to frustration_tolerance.

**Social desirability:** HIGH. "Motivated to understand why" is the aspirational academic response. In a real population, "Quite frustrated" and "Indifferent" are likely underreported. Options go from most to least positive — ordering bias compounds social desirability.

**Mitigation:** Reorder to remove ordering bias:
1. Indifferent — I focus on the next question
2. Briefly discouraged, then I move on
3. Motivated to understand why
4. Quite frustrated

This removes the "positive-to-negative" ordering cue.

**Verdict:** PASS with reorder.

---

### e2 — "Praise and encouragement during study:" → `persistence` 🔴 HIGH

Options: Significantly boosts motivation / Helps somewhat / Makes little difference / Can feel patronising

**Mapping FAIL:** Sensitivity to praise is a measure of external vs internal motivation (extrinsic/intrinsic motivation locus), not `persistence`. Persistence is the tendency to continue effort after setbacks — it is not determined by whether praise helps you. A student can be highly persistent and intrinsically motivated (praise makes little difference) OR highly persistent and extrinsically motivated (praise boosts them). Both would score differently on this question but equally on true persistence.

`persistence` has **only 1 question** (this one) — and it measures the wrong construct.

**Replacement:**
```
ID: e2 | dimension: emotional | maps to: persistence

Text: "When you repeatedly fail at a difficult topic, you:"

Options:
  A. Keep trying with different approaches until I succeed
  B. Take a break and return with fresh eyes
  C. Lower the difficulty and build up gradually
  D. Move on to a different topic and return later (or not at all)
```

This directly measures persistence (continued effort after repeated failure), removes social desirability ambiguity, and correctly maps to `persistence`.

---

### e3 — "How does time pressure affect you?" → `frustration_tolerance` 🚨 CRITICAL

Options: Perform better / Slightly stresses but manage / Significantly impairs thinking / Strongly dislike it and avoid it

**CLAUDE.md violation:** The project rule explicitly states "No teach-back timer — creates test anxiety." This is not just about teach-back — it establishes a principle: the platform should not create or exploit anxiety around performance under time constraint. e3 directly asks students to self-report their anxiety response to time pressure and then uses that score to adjust their profile.

**Clinical language risk:** "It significantly impairs my thinking" is adjacent to self-reporting cognitive impairment under stress — a near-clinical statement.

**Practical impact:** If the system uses a low `frustration_tolerance` score (driven partly by e3) to label a student as a "Resilient Learner" — but achieves this by not being timed — then the question has no real-world validity in this product context because the product deliberately avoids time pressure.

**REMOVE this question.** Do not replace with another time-pressure question. Replace with a frustration_tolerance question that uses the platform's actual design:

**Replacement:**
```
ID: e3 | dimension: emotional | maps to: frustration_tolerance

Text: "When a concept takes significantly longer to understand than you expected, you:"

Options:
  A. Stay with it — I know persistence will pay off
  B. Feel frustrated but push through
  C. Take a break before returning to it
  D. Move on and hope it becomes clearer later
```

---

### e4 — "When I'm confused by a concept, my first reaction is:" → `help_seeking` ✅ PASS (with note)

Options: Curiosity — dig deeper / Mild anxiety, push through / I feel stuck and need a hint / Anxious and want to move on

**Mapping:** Reasonable. "I feel stuck and need a hint" directly maps to help_seeking. "Curiosity — dig deeper" is self-directed (low help-seeking). The gradient from autonomous to help-dependent is captured.

**Note:** "Mild anxiety" and "Anxious and want to move on" contain emotional descriptors that approach clinical territory. Neither is explicitly clinical, but the "anxious" wording in options 2 and 4 creates a cluster — students with genuine test anxiety may answer in ways that aren't representative of their help-seeking behaviour.

**Mitigation:** Replace "Mild anxiety, but I push through" → "A bit uneasy, but I push through" and "I feel anxious and want to move on" → "Overwhelmed — I'd rather skip ahead".

**Verdict:** PASS with reword.

---

### e5 — "How do you feel about AI tracking your engagement?" → `help_seeking` 🚨 CRITICAL

Options: Excited / Fine if privacy protected / Slightly uncomfortable / Would prefer to opt out

**CRITICAL — Remove immediately.**

**Reason 1 — DPDP conflict:** This question directly elicits consent signal but does NOT trigger any actual opt-out flow. The DPDP consent modal (Story 3-32, `POST /api/assessment/consent`) is the correct mechanism for consent. A student who selects "I would prefer to opt out" receives no confirmation that they have opted out — they just receive a lower `help_seeking` score. This creates a legally problematic situation where a student believes they have expressed a preference to opt out but the system has silently recorded it as a scoring dimension.

**Reason 2 — Mapping is wrong:** Comfort with AI tracking has nothing to do with `help_seeking`. Help_seeking is about whether a student asks for assistance when confused. Whether they consent to attention monitoring is a governance question, not a learning behaviour.

**Reason 3 — The question presupposes the system:** A student answering the onboarding diagnostic has not yet seen the platform. Asking them how they feel about AI engagement tracking before they have experienced it produces uninformed, anxiety-primed responses.

**Replacement:**
```
ID: e5 | dimension: emotional | maps to: help_seeking

Text: "When you're stuck on something, your first instinct is to:"

Options:
  A. Search for the answer or explanation yourself
  B. Ask a classmate, tutor, or AI tool
  C. Re-read the material more carefully
  D. Take a break and come back to it
```

This is a clean help_seeking question — does the student reach out for help or self-resolve? No anxiety priming, no consent conflation.

---

## Findings: Self-Direction (s1–s7)

### s1 — "How often do you set explicit learning goals before studying?" → `goal_orientation` ✅ PASS

Options: Always with detailed plans / Usually / Occasionally / Rarely or never

**Mapping:** Strong. Goal-setting frequency directly measures goal_orientation.
**Social desirability:** Moderate — "Always with detailed plans" is the idealised academic behaviour. Skew expected but manageable since the gradient is clear.
**Verdict:** PASS.

---

### s2 — "When given free choice on a topic to study, you:" → `curiosity_index` 🟡 MEDIUM

Options: Dive in with structured plan / Explore broadly before focusing / Wait for guidance / Feel overwhelmed and delay

**Mapping note:** "Explore broadly before focusing" is the clearest curiosity signal. Option 1 ("Dive in with structured plan") is self-direction, not curiosity. Options 3 and 4 are avoidance, not curiosity.

**Social desirability:** HIGH. "Feel overwhelmed and delay starting" is extremely socially undesirable — virtually no student will self-report this in an onboarding flow. This option has near-zero discrimination power and skews all responses toward options 1–2.

**Replacement for option 4:**
"Prefer to start with a well-defined scope before exploring"

This is a real study behaviour pattern (boundary-setting before exploration) that is socially neutral and meaningfully different from option 3.

**Verdict:** MEDIUM — replace option 4 only.

---

### s3 — "How do you prefer to pace your lessons?" → `study_independence` ✅ PASS

Options: Full control / Guided with override / Mostly guided / Fully guided

**Mapping:** Excellent. Autonomy in pacing is a direct measure of study_independence.
**Social desirability:** Low — there is no "correct" pacing preference.
**Verdict:** PASS.

---

### s4 — "How do you typically respond to a learning setback?" → `study_independence` 🔴 HIGH

Options: Analyse and adjust / Short break then retry / Ask for help / Often give up

**Mapping FAIL:** Response to setback maps to `persistence` and `frustration_tolerance`, not `study_independence`. Study independence is about autonomy and self-pacing, not about coping with failure. A student who gives up on one topic and self-directs to another is arguably more study-independent than one who keeps asking for hints.

**Social desirability:** Severe. "I often give up on that topic for now" is the most socially undesirable option in the entire diagnostic. Expected near-zero honest responses. This question cannot discriminate.

**Remap + replace:**
```
ID: s4 | dimension: self_direction | maps to: study_independence

Text: "When working through a lesson, you prefer:"

Options:
  A. To decide the order and depth of topics yourself
  B. A recommended path with freedom to skip or dive deeper
  C. A set sequence with clear checkpoints
  D. To follow exactly what the system suggests
```

This directly measures study independence (autonomy in sequencing) with no social desirability — all four options are legitimate preferences.

---

### s5 — "I review my own understanding of a topic:" → `goal_orientation` ✅ PASS

Options: Regularly through self-testing / Occasionally when uncertain / Rarely, rely on external tests / Almost never

**Mapping:** Good. Self-testing frequency maps to goal_orientation.
**Verdict:** PASS.

---

### s6 — "Which best describes your study consistency?" → `curiosity_index` 🟡 MEDIUM

Options: Every day at fixed times / Most days, flexible / Bursts when motivated / Primarily close to deadlines

**Mapping FAIL:** Study consistency (time regularity) maps to `self_regulation` or `goal_orientation`, not `curiosity_index`. Curiosity is about breadth of interest and desire to explore new information — it has no meaningful relationship with whether someone studies daily or in bursts.

A deadline-driven student could be intensely curious but procrastinatory. A daily fixed-schedule student could be rigidly methodical with low curiosity. This question tells us nothing about curiosity.

However: `curiosity_index` already has s2 as its only other question. Replacing this mapping changes the dimension coverage.

**Remap:** Move s6 to `goal_orientation` (which currently has s1 and s5 — adding s6 gives 3 questions, still within the dimension's purpose). Replace s6 with a curiosity question:

```
ID: s6 | dimension: self_direction | maps to: curiosity_index

Text: "When you encounter an interesting topic in a lesson, you typically:"

Options:
  A. Follow tangential links and explore further on your own
  B. Note it for later but stay on the lesson path
  C. Finish the required material first, then explore if time allows
  D. Stay focused — extra reading is not something I usually do
```

**Verdict:** MEDIUM — remap + replace question.

---

### s7 — "When you finish a lesson, you typically:" → `study_independence` ✅ PASS

Options: Review and summarise immediately / Reflect briefly then move on / Check off to-do and move on / Rarely do anything after

**Mapping:** Good. Post-lesson consolidation behaviour maps to study independence.
**Social desirability:** Moderate — "Immediately review and summarise" is the optimal academic behaviour. Reorder to reduce primacy bias:
1. Check off a to-do and move on
2. Reflect briefly, then move on
3. Immediately review and summarise notes
4. Rarely do anything after finishing

**Verdict:** PASS with reorder.

---

## Dimension Coverage After Fixes

| Sub-dimension | Questions (before) | Questions (after) | Coverage |
|---------------|-------------------|-------------------|----------|
| pattern_recognition | c1, c5, c8 | c1, c5, c8 | ✅ 3 |
| logical_deduction | c2, c3, c7 | c2, c3, c7 | ✅ 3 |
| processing_speed | c4, c6 | c4 (replaced), c6 | ✅ 2 |
| frustration_tolerance | e1, e3 | e1, e3 (replaced) | ✅ 2 |
| persistence | e2 | e2 (replaced) | ⚠️ 1 (thin) |
| help_seeking | e4, e5 | e4, e5 (replaced) | ✅ 2 |
| goal_orientation | s1, s5 | s1, s5, s6 (remapped) | ✅ 3 |
| curiosity_index | s2, s6 | s2, s6 (replaced) | ✅ 2 |
| study_independence | s3, s4, s7 | s3, s4 (replaced), s7 | ✅ 3 |

**`persistence` is still thin at 1 question.** This is an acceptable MVP tradeoff since e2 (replacement) is now a direct persistence measure. Flag for Sprint 5 — add a second persistence question.

---

## Go/No-Go Verdict Per Question

| ID | Verdict | Action |
|----|---------|--------|
| c1 | ✅ GO | No change |
| c2 | ✅ GO | Add code comment noting loose mapping |
| c3 | ✅ GO | No change |
| c4 | 🔴 NO-GO | Replace question text + options |
| c5 | ✅ GO | Reorder options |
| c6 | ✅ GO | No change |
| c7 | ✅ GO | Reword option 1 |
| c8 | ✅ GO | No change |
| e1 | ✅ GO | Reorder options |
| e2 | 🔴 NO-GO | Replace question text + options |
| e3 | 🚨 CRITICAL | Replace — CLAUDE.md principle conflict |
| e4 | ✅ GO | Reword options 2 + 4 |
| e5 | 🚨 CRITICAL | Replace — DPDP conflict + wrong mapping |
| s1 | ✅ GO | No change |
| s2 | 🟡 REWORD | Replace option 4 only |
| s3 | ✅ GO | No change |
| s4 | 🔴 NO-GO | Replace question text + options + remap |
| s5 | ✅ GO | No change |
| s6 | 🟡 REMAP | Replace question + remap to curiosity_index |
| s7 | ✅ GO | Reorder options |

**Summary:** 2 CRITICAL, 3 NO-GO (replace), 2 REMAP/REWORD, 13 PASS.
