# Epic 3: Assessment + Analytics + Learner DNA

| Field | Value |
|---|---|
| Epic ID | E-03 |
| Status | Planned |
| Owner | Dev 3 |
| Target Sprints | Sprint 1–3 (Weeks 2–7) |
| Priority | P1 — required for session report; Learner DNA data collection required before Phase 2 profile display |

---

## Problem Statement

TransformED is not a passive video — it must know how well a student understood the material. Without a scoring layer for quizzes and teach-backs, we cannot produce a session report, cannot compute the CES engagement signal, and cannot offer the differentiated Learner DNA profile that is the platform's primary competitive differentiator. This epic builds the full assessment back-end and the onboarding experience that seeds the learner profile.

---

## Goal / Success Metric

> **A student who completes a lesson can view a session report showing their quiz accuracy, teach-back score, and overall engagement. Their Learner DNA onboarding responses are persisted and ready for Phase 2 profile generation.**

---

## User Stories

- As a **student**, after answering a quiz I immediately see whether I got it right and my running accuracy for the segment.
- As a **student**, I can explain a concept in my own words (teach-back) without being penalized by a timer or blocked from continuing.
- As a **student**, at the end of a lesson I can view a session report with my scores and engagement summary.
- As a **student**, during onboarding I complete a 20-question assessment and am told my Learner DNA profile name (shown in Phase 2).
- As a **developer**, teach-back rubric weights are configurable via env vars, not hardcoded.
- As a **platform operator**, raw cognitive / emotional / self-direction scores are never exposed to students — only the Learner DNA composite label.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/assessment/quiz` | Score an MCQ answer; return correct/incorrect + explanation |
| `POST` | `/api/assessment/teachback` | Score free-text teach-back via GPT-4o-mini rubric |
| `GET` | `/api/session/{id}/report` | Return full session report JSON |
| `POST` | `/api/onboarding/dna` | Submit 20-question onboarding batch; store scores + label |
| `GET` | `/api/onboarding/dna/{user_id}` | Retrieve stored DNA scores (internal / admin use) |

---

## Quiz Scoring

- Input: `{ session_id, segment_id, question_id, selected_option, response_time_ms }`
- Logic: compare `selected_option` against `lesson_package.quiz[question_id].correct`
- Output: `{ correct: bool, explanation: str, segment_accuracy: float }`
- Response time is stored but does not penalize score (used in CES behavioral signal)
- Segment accuracy = running mean across all questions answered in that segment

---

## Teach-Back Scoring

Rubric evaluated by GPT-4o-mini with structured output (`response_format: json_object`):

| Dimension | Weight | Description |
|---|---|---|
| Accuracy | 40% | Factual correctness vs. lesson content |
| Completeness | 30% | Coverage of key concepts in the segment |
| Clarity | 30% | Coherent, organized explanation |

**Hard constraints (non-negotiable):**
- NEVER gate lesson progress on teach-back score
- NO timer on teach-back input
- Score stored and used in CES; never shown as a grade to the student in Phase 1
- Rubric weights are env vars: `TEACHBACK_ACCURACY_WEIGHT`, `TEACHBACK_COMPLETENESS_WEIGHT`, `TEACHBACK_CLARITY_WEIGHT`

---

## CES Formula (v1)

Computed by Epic 4 but defined and owned here:

```
CES = (quiz_accuracy × 0.35)
    + (teachback_score × 0.25)
    + (behavioral_engagement × 0.20)
    + (head_pose_score × 0.12)
    + (blink_rate_score × 0.08)
```

All weights are env vars. `behavioral_engagement` = inverse of distraction interventions fired / max possible. `head_pose_score` and `blink_rate_score` come from MediaPipe signals (Epic 2 / 4).

---

## Session Report Schema

```jsonc
{
  "session_id": "uuid",
  "lesson_id": "uuid",
  "user_id": "uuid",
  "completed_at": "ISO8601",
  "quiz": {
    "total_questions": 9,
    "correct": 7,
    "accuracy": 0.78,
    "by_segment": [{ "segment_id": "s1", "accuracy": 0.67 }]
  },
  "teachback": {
    "segments_attempted": 3,
    "average_score": 0.81
  },
  "ces": 0.74,
  "interventions_fired": 2,
  "duration_minutes": 22
}
```

---

## Learner DNA Onboarding

### Question Breakdown

| Domain | Framework Basis | Count | Purpose |
|---|---|---|---|
| Cognitive | Raven's Progressive Matrices (style) | 8 | Fluid reasoning pattern |
| Emotional | Mayer-Salovey-Caruso EI model | 5 | Emotional processing style |
| Self-Direction | SDLRS (Self-Directed Learning Readiness Scale) | 7 | Autonomy and motivation profile |

Total: **20 questions**, multiple-choice, completed once at onboarding.

### Fusion + Profile Generation

1. Score each domain independently (normalized 0–1)
2. Fusion formula: `dna_composite = cognitive×0.40 + emotional×0.35 + self_direction×0.25`
3. Map composite to one of 6 named learner profiles (label list defined in `backend/dna/profiles.py`)
4. Call GPT-4o-mini with scores + label to generate a 2-paragraph personalized profile narrative
5. Store `{ user_id, cognitive_score, emotional_score, self_direction_score, dna_label, profile_narrative, completed_at }` in `learner_dna` table

### Legal + Display Constraints

- Legal disclaimer shown before onboarding: "This is not a clinical assessment. Scores are used only to personalize your learning experience."
- Raw domain scores (`cognitive_score`, etc.) NEVER returned to frontend
- Only `dna_label` and `profile_narrative` are user-facing — and only in Phase 2
- No IQ, EQ, or SQ terminology anywhere in UI or API responses

---

## Technical Scope

| Layer | Files / Modules |
|---|---|
| Quiz scoring | `backend/assessment/quiz.py` |
| Teach-back scoring | `backend/assessment/teachback.py` |
| Session report builder | `backend/assessment/report.py` |
| CES formula | `backend/assessment/ces.py` (formula definition; computation in Epic 4) |
| Learner DNA onboarding | `backend/dna/onboarding.py` |
| DNA profile mapping | `backend/dna/profiles.py` |
| DNA profile generation | `backend/dna/generator.py` (GPT-4o-mini call) |
| API routers | `backend/routers/assessment.py`, `backend/routers/dna.py` |
| DB migrations | `supabase/migrations/` — `quiz_responses`, `teachback_responses`, `session_reports`, `learner_dna` |
| Frontend onboarding | `app/onboarding/page.tsx` (Epic 2 route, data layer here) |

---

## Out of Scope (Phase 2)

- Learner DNA profile display in student dashboard
- Adaptive difficulty (quiz difficulty adjusted by prior performance)
- Longitudinal learning analytics (cross-session trends)
- Teach-back voice input (text only in Phase 1)
- Peer comparison / class analytics

---

## Dependencies

| Dependency | Status |
|---|---|
| Sprint 0 infra + DB | Done |
| `lesson_package.json` quiz schema (Epic 1) | Must be finalized before quiz API built |
| Epic 2 player fires quiz + teachback at correct moments | Integration dependency |
| Epic 4 CES computation (reads quiz_accuracy, teachback_score) | Parallel development; interface contract agreed Sprint 1 |
| GPT-4o-mini API access provisioned | Must be done before Sprint 1 Day 1 |

---

## Definition of Done

- [ ] `POST /api/assessment/quiz` returns correct/incorrect with explanation in < 200ms
- [ ] `POST /api/assessment/teachback` returns rubric scores in < 5s (GPT-4o-mini latency)
- [ ] `GET /api/session/{id}/report` returns complete report JSON matching schema
- [ ] Session report accessible by lesson owner only (RLS verified)
- [ ] 20-question onboarding flow completes end-to-end; `learner_dna` row written to DB
- [ ] Raw domain scores not present in any API response to frontend (verified by contract test)
- [ ] Legal disclaimer rendered before onboarding questions
- [ ] Teach-back has no timer UI element (verified by Dev 2)
- [ ] CES formula weights configurable via env vars (smoke test: change weight, recompute)
- [ ] GPT-4o-mini rubric prompt stored in `backend/assessment/prompts.py` (not inline)
- [ ] All endpoints have Pydantic request/response models
- [ ] Unit tests: quiz scorer, teachback scorer, DNA fusion formula

---

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| GPT-4o-mini teach-back latency > 5s frustrates students | Medium | Medium | Show "Evaluating your response..." animation; async scoring possible |
| GPT-4o-mini returns malformed JSON for rubric | Medium | Medium | Structured output mode + fallback default scores with alert log |
| DNA profile labels feel stigmatizing | Low | High | UX review of all 6 profile names before Sprint 3 launch |
| Teach-back prompt injection (student manipulates scores) | Low | Medium | System prompt isolation; score clamped 0–1 server-side |
| DPDP Act compliance gap on sensitive onboarding data | Medium | High | Legal review of disclaimer text + data retention policy in Sprint 3 |
