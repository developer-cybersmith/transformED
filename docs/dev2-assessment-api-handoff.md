# Assessment API Handoff — Dev 2 Integration Guide

**From:** Dev 3 (tannmayygupta)
**Date:** 2026-06-26
**Branch:** `dev3-sprint0-task7`
**Spec file:** `docs/openapi-assessment.json` (committed to this branch)

---

## What Is This File?

This is the official API contract document for all 5 assessment endpoints. It has the exact field shapes, copy-paste TypeScript interfaces, JSON examples, and a confirmation checklist at the bottom that you need to fill in and send back before Sprint 1 starts.

**Your 3 steps:**
1. Read the two "CRITICAL" sections first — there is one broken import in your code right now
2. Copy the TypeScript interfaces into your types file
3. Fill in the checklist at the bottom and reply to confirm

---

## CRITICAL — Fix These Before Sprint 1

### 1. Broken Import That Will Crash at Runtime

In `apps/web/src/app/(app)/onboarding/page.tsx` line 6:

```typescript
// CURRENT (broken — this file does NOT exist):
import { apiClient } from '@/lib/api/client'

// FIX — change to the real client that already exists:
import api from '@/lib/api'
// then call: api.post('/api/assessment/onboarding/submit', { responses })
```

The real API client is at `apps/web/src/lib/api.ts`. It already auto-injects the Supabase JWT Bearer token on every request. You do not need to do anything extra for authentication.

---

### 2. No STT — Teach-Back Input Must Be a Text Area

In `apps/web/src/components/lesson/InteractivePlayer.tsx` the teach-back section currently shows "Speak your answer aloud" and a Mic icon. **This must be replaced with a typed text input (textarea).** Voice/STT is banned by project rules — the field is called `response_text`, not `transcript`. There is no audio input anywhere in the teach-back flow.

---

## All 5 Endpoints at a Glance

| Method | Path | When to call |
|--------|------|--------------|
| `POST` | `/api/assessment/quiz` | After student answers all questions in a segment |
| `POST` | `/api/assessment/teachback` | After student submits typed teach-back response |
| `GET` | `/api/assessment/session/{session_id}/report` | At session end to show the report screen |
| `GET` | `/api/assessment/user/dna` | On dashboard to show the Learner DNA panel |
| `POST` | `/api/assessment/onboarding/submit` | On onboarding completion (202 response, no body data) |

Base URL: `process.env.NEXT_PUBLIC_API_URL` (default: `http://localhost:8000/api`)

All 5 endpoints require a valid Supabase JWT. The `api` client in `lib/api.ts` handles this automatically.

---

## TypeScript Interfaces — Copy These Into Your Types File

```typescript
// ── Shared building blocks ────────────────────────────────────────────────

export interface QuizAnswer {
  question_id: string;   // matches QuizQuestion.question_id from LessonPackage
  response_index: number; // which option the student chose (0-indexed)
  response_time_ms?: number; // optional, defaults to 0 if omitted
}

export interface OnboardingAnswer {
  question_id: string;   // e.g. "c1", "e3", "s7"
  dimension: "cognitive" | "emotional" | "self_direction";
  selected_index: number;
  selected_text: string;
}

// ── POST /api/assessment/quiz ─────────────────────────────────────────────

export interface QuizSubmission {
  session_id: string;
  lesson_id: string;
  segment_id: string;
  answers: QuizAnswer[];
}

export interface QuizResult {
  session_id: string;
  score: number;           // 0.0–1.0
  correct_count: number;
  total_count: number;
  ces_contribution: number; // this value feeds into WebSocket attention_signal.quiz_accuracy
  feedback: Array<{        // per-question feedback — keys: question_id, correct, explanation
    [key: string]: unknown;
  }>;
}

// ── POST /api/assessment/teachback ────────────────────────────────────────

export interface TeachbackSubmission {
  session_id: string;
  lesson_id: string;
  segment_id: string;
  response_text: string;   // TYPED text only — NO transcript, NO audio, NO STT
}

export interface TeachbackResult {
  session_id: string;
  rubric_scores: {          // keys: "accuracy", "depth", "clarity", "relevance" (all 0.0–1.0)
    accuracy?: number;
    depth?: number;
    clarity?: number;
    relevance?: number;
    [key: string]: number | undefined;
  };
  overall_score: number;    // 0.0–1.0 — feeds into WebSocket attention_signal.teachback_score
  ces_contribution: number;
  feedback: string;         // plain text paragraph shown to student
}

// ── GET /api/assessment/session/{session_id}/report ───────────────────────

export interface SessionReport {
  session_id: string;
  user_id: string;
  lesson_id: string;
  ces_score: number;        // 0–100 final CES score
  ces_breakdown: {          // keys match CES formula weights
    quiz_accuracy?: number;
    teachback_score?: number;
    behavioral?: number;
    head_pose?: number;
    blink?: number;
    [key: string]: number | undefined;
  };
  interventions_count: number;
  quiz_score: number | null;
  teachback_score: number | null;
  duration_minutes: number; // NOTE: this is duration_minutes, NOT duration_seconds
  completed_at: string | null; // ISO 8601
}

// ── GET /api/assessment/user/dna ──────────────────────────────────────────

export interface LearnerDNA {
  user_id: string;
  badge_labels: string[];      // e.g. ["Pattern Thinker", "Deep Diver"]
  profile_text: string | null; // see DPDP rule below — never truncate this field
  session_count: number;
  reassessment_due: boolean;
  last_updated: string | null; // ISO 8601
}

// ── POST /api/assessment/onboarding/submit ────────────────────────────────

export interface OnboardingDiagnosticSubmission {
  responses: OnboardingAnswer[]; // array of all answers, NOT subject+grade_level
}

// Response: HTTP 202 Accepted
// Body: { message: string }
```

---

## JSON Examples

### Quiz Submission

```json
POST /api/assessment/quiz
Authorization: Bearer <supabase-jwt>

{
  "session_id": "sess_abc123",
  "lesson_id": "lesson_xyz",
  "segment_id": "seg_01",
  "answers": [
    { "question_id": "q_001", "response_index": 2, "response_time_ms": 4200 },
    { "question_id": "q_002", "response_index": 0, "response_time_ms": 1800 }
  ]
}

Response 200:
{
  "session_id": "sess_abc123",
  "score": 0.75,
  "correct_count": 3,
  "total_count": 4,
  "ces_contribution": 0.75,
  "feedback": [
    { "question_id": "q_001", "correct": true,  "explanation": "..." },
    { "question_id": "q_002", "correct": false, "explanation": "..." }
  ]
}
```

### Teach-Back Submission

```json
POST /api/assessment/teachback
Authorization: Bearer <supabase-jwt>

{
  "session_id": "sess_abc123",
  "lesson_id": "lesson_xyz",
  "segment_id": "seg_01",
  "response_text": "Photosynthesis is the process by which plants convert sunlight into glucose..."
}

Response 200:
{
  "session_id": "sess_abc123",
  "rubric_scores": { "accuracy": 0.9, "depth": 0.7, "clarity": 0.8, "relevance": 0.85 },
  "overall_score": 0.81,
  "ces_contribution": 0.81,
  "feedback": "Strong answer — good accuracy and clarity. Consider mentioning the role of CO2."
}
```

### Onboarding Submit

```json
POST /api/assessment/onboarding/submit
Authorization: Bearer <supabase-jwt>

{
  "responses": [
    { "question_id": "c1", "dimension": "cognitive",      "selected_index": 2, "selected_text": "I prefer to understand the why behind things" },
    { "question_id": "e3", "dimension": "emotional",      "selected_index": 0, "selected_text": "I get frustrated quickly when stuck" },
    { "question_id": "s7", "dimension": "self_direction", "selected_index": 1, "selected_text": "I often set my own study schedule" }
  ]
}

Response 202 Accepted:
{ "message": "Onboarding diagnostic accepted" }
```

---

## How to Use the API Client

```typescript
import api from '@/lib/api'

// POST example
const result = await api.post<QuizResult>('/api/assessment/quiz', submission)
const quizResult = result.data

// GET example
const report = await api.get<SessionReport>(`/api/assessment/session/${sessionId}/report`)
const sessionReport = report.data
```

The `api` client at `apps/web/src/lib/api.ts` automatically:
- Prepends `process.env.NEXT_PUBLIC_API_URL` (default: `http://localhost:8000/api`)
- Attaches the Supabase session JWT as `Authorization: Bearer <token>`

You do not need to add auth headers manually.

---

## Connecting Assessment Results to WebSocket CES

After you receive a `QuizResult`, send the score to Dev 4's WebSocket CES pipeline:

```typescript
// After quiz submit:
const quizResult = await api.post<QuizResult>('/api/assessment/quiz', submission)

// Include in the next attention_signal WebSocket message (Dev 4's AttentionSignalMessage):
// attention_signal.quiz_accuracy = quizResult.data.ces_contribution

// After teachback submit:
const teachbackResult = await api.post<TeachbackResult>('/api/assessment/teachback', submission)

// Include in the next attention_signal WebSocket message:
// attention_signal.teachback_score = teachbackResult.data.overall_score
```

If teach-back was skipped (student hit Skip), send `teachback_score: null` in the WebSocket message. CES formula handles null by redistributing weight — no special handling needed on your side.

---

## DPDP Rule — Do Not Truncate `profile_text`

The `profile_text` field in `LearnerDNA` always ends with a legal disclaimer required by the DPDP Act 2023. Do not:
- Truncate the string with `...` or character limits
- Strip the last paragraph
- Show only the first N characters

Render the full string. If the UI space is tight, use a scrollable area or "Read more" that expands to the full text — never cut it off.

---

## The Full OpenAPI Spec

The machine-readable spec is at `docs/openapi-assessment.json` in the repo. You can:

- Open in Postman/Insomnia: File → Import → `docs/openapi-assessment.json`
- Auto-generate TypeScript types:
  ```bash
  npx openapi-typescript docs/openapi-assessment.json -o apps/web/src/types/assessment-api.generated.ts
  ```
- View all 11 schemas and exact field types with descriptions

---

## Confirmation Checklist

Please review the spec and reply with this checklist filled in. Once I get your confirmation, Task 7 (Sprint 0) is complete and we can both move to Sprint 1.

```
[ ] I have read docs/openapi-assessment.json
[ ] POST /api/assessment/quiz — field shapes confirmed
[ ] POST /api/assessment/teachback — I will use response_text (typed text, no STT)
[ ] POST /api/assessment/onboarding/submit — I will use responses[] (not subject/grade_level)
[ ] GET  /api/assessment/session/{session_id}/report — field shapes confirmed
[ ] GET  /api/assessment/user/dna — field shapes confirmed
[ ] I will fix the broken @/lib/api/client import in (app)/onboarding/page.tsx
[ ] I will replace the Mic/voice input in InteractivePlayer.tsx with a textarea
[ ] I understand profile_text always includes a DPDP disclaimer — I will never truncate it
```

If any endpoint shape doesn't match what you expected, flag it here before we both build against it. The spec is now the source of truth — changes to any of the 5 endpoint signatures require a 4-developer PR review before merging.
