---
baseline_commit:
status: done
---

# Story 4-5 — Onboarding Question Quality Audit

**Sprint:** 4 (Weeks 8–9)
**Owner:** Dev 3
**Type:** Quality audit — no new features, no API changes

---

## Story

As the product team, we want a brutal, evidence-based audit of all 20 onboarding diagnostic questions so that we ship a Learner DNA diagnostic that actually measures what it claims to measure, has no clinical risk, no cultural bias, and produces discriminating (non-trivial) scores — not a socially-desirable self-report that gives every student the same profile.

---

## Acceptance Criteria

- **AC1** — Every question reviewed against 5 criteria: ambiguity, clinical language, cultural bias, mapping correctness (does it measure the sub-dimension it's assigned to?), and social desirability bias
- **AC2** — Every flagged question has a concrete replacement proposed with the same ID and dimension mapping
- **AC3** — `e5` (AI tracking comfort as help_seeking proxy) is explicitly addressed — it conflates DPDP consent with diagnostic scoring
- **AC4** — `e3` (time pressure / test anxiety) is explicitly addressed given CLAUDE.md's explicit "no test anxiety" principle
- **AC5** — Dimension coverage verified: all 9 sub-dimensions have adequate question coverage with correct mappings
- **AC6** — Social desirability audit: every question where the "academically correct" answer is obvious is flagged for rewording or removal
- **AC7** — Audit output written to `docs/sprint4-onboarding-audit.md` with: findings table, replacement questions, and a go/no-go verdict per question
- **AC8** — `QUESTION_SUBDIMENSION_MAP` in `onboarding_questions.py` updated to reflect any corrected mappings
- **AC9** — `questions.ts` updated with replacement question text where flagged questions are replaced
- **AC10** — No question contains clinical language (anxiety, depression, IQ, EQ, SQ, impairment, disorder)

---

## Scale & Load

1. **Unit of work:** 20 questions, static content — no DB reads, no LLM calls, no variable input
2. **Fixed budgets:** N/A — pure content audit
3. **Scope:** Content-only change; `QUESTION_SUBDIMENSION_MAP` is a static dict; `questions.ts` is static content
4. **Unbounded reads/writes:** None
5. **Inherited caps:** N/A
6. **Concurrent safety:** N/A — static file changes

---

## Dev Notes

### Files

| File | Action |
|------|--------|
| `apps/web/src/components/onboarding/questions.ts` | Update flagged question text + options |
| `apps/api/app/modules/assessment/onboarding_questions.py` | Update `QUESTION_SUBDIMENSION_MAP` if mappings corrected |
| `docs/sprint4-onboarding-audit.md` | Create — full audit findings |

### Audit criteria per question

1. **Ambiguity** — Is the question or any option open to multiple interpretations?
2. **Clinical language** — Does it imply diagnosis, disorder, or impairment?
3. **Cultural bias** — Does it assume a specific study culture (Western, exam-driven, etc.)?
4. **Mapping correctness** — Does the question actually measure the assigned `learner_dna` sub-dimension?
5. **Social desirability bias** — Is one answer clearly "what a good student says"? If yes, the question has no discrimination power.

### Key constraints (CLAUDE.md)

- No teach-back timer — creates test anxiety (same principle applies to e3)
- No clinical scores shown to students
- No IQ/EQ/SQ language
- DPDP consent is separate from diagnostic scoring (relevant to e5)
